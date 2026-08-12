"""BLE client for the SkyRC Q200neo charger.

Uses a connect → poll-all-channels → disconnect cycle. Freeing the radio
between polls keeps the single BLE slot available for the SkyCharger phone app
and copes better with the weak/proxied links typical of a homelab deployment.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    CHANNEL_MASKS,
    CHAR_UUID,
    CMD_QUERY_BASIC_INFO,
    CMD_QUERY_CHANNEL_STATUS,
    CMD_QUERY_SYSTEM_INFO,
    CMD_SET_SYSTEM_INFO,
    CMD_START_CHARGE,
    CMD_STOP_CHARGE,
    DEFAULT_PASSWORD,
    STATE_DC_SUPPLY,
    STATE_IDLE,
    STATE_READY,
    STATE_WORKING,
)
from .programs import ProgramConfig
from .protocol import (
    ChannelBasicInfo,
    ChannelStatus,
    ChargerSettings,
    Frame,
    FrameReader,
    build_basic_info_query,
    build_channel_query,
    build_set_capacity_limit,
    build_set_max_input_power,
    build_set_min_input_voltage,
    build_set_safety_timer,
    build_set_sounds,
    build_start_charge,
    build_stop_charge,
    build_system_info_query,
    parse_ack,
    parse_basic_info,
    parse_channel_status,
    parse_system_info,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 20.0
RESPONSE_TIMEOUT = 5.0

# How long to wait for a channel to leave idle after a start, and to settle
# after a stop. A live Q200neo had left idle within 1.5 s of the acknowledgement.
START_CONFIRM_DELAY = 1.5
START_CONFIRM_ATTEMPTS = 3
STOP_CONFIRM_DELAY = 1.0

# A Q200neo discards the first frame written immediately after notifications are
# enabled: measured against one, a write sent with no delay was never answered,
# while 0.25 s was already enough. Without this the first command of every
# connection is lost — which, polling channels in order, quietly cost channel A
# its reading on every cycle.
NOTIFY_SETTLE = 0.5

# Let a settings write land before the next frame.
SETTING_APPLY_DELAY = 0.4

# Give up on basic-info queries after this many consecutive timeouts, so a
# charger that never answers them doesn't stall every poll cycle.
MAX_BASIC_INFO_FAILURES = 3


class SkyRcError(Exception):
    """Raised when the charger cannot be queried."""


class SkyRcClient:
    """Talks to one charger over BLE."""

    def __init__(
        self,
        address: str,
        passcode: str = DEFAULT_PASSWORD,
        poll_program: bool = True,
    ) -> None:
        self._address = address
        self._passcode = passcode
        self._poll_program = poll_program
        self._lock = asyncio.Lock()
        self._reader = FrameReader()
        self._pending_cmd: int | None = None
        self._pending: asyncio.Future[Frame] | None = None
        # Last known basic info per channel, kept until the channel goes idle.
        self._basic_info: dict[str, ChannelBasicInfo] = {}
        self._basic_info_failures = 0
        # Programs this integration started itself, per channel: the fallback
        # for reporting charge/discharge direction when the charger's own
        # basic info is unavailable or not being polled.
        self._commanded: dict[str, tuple[str, str]] = {}
        # Last elapsed duration seen per channel, to spot a new run.
        self._durations: dict[str, int] = {}
        # The charger's own settings, refreshed on every poll.
        self.settings: ChargerSettings | None = None
        # Warn once, not on every poll, when the passcode is refused.
        self._passcode_warned = False
        # The charger's last verdict on the passcode, or None if it has not
        # been asked yet. It is only asked while a channel is running.
        self.passcode_accepted: bool | None = None

    def _notification_handler(self, _sender: int, data: bytearray) -> None:
        _LOGGER.debug("%s: notify <- %s", self._address, data.hex())
        for frame in self._reader.feed(bytes(data)):
            _LOGGER.debug(
                "%s: frame cmd=0x%02X data=%s", self._address, frame.command, frame.data.hex()
            )
            if (
                self._pending is not None
                and not self._pending.done()
                and frame.command == self._pending_cmd
            ):
                self._pending.set_result(frame)

    async def _query(self, client: BleakClient, command: int, frame: bytes) -> Frame:
        """Send ``frame`` and await the reply frame echoing ``command``."""
        loop = asyncio.get_running_loop()
        self._reader.reset()
        self._pending_cmd = command
        self._pending = loop.create_future()
        try:
            # The ffe1 characteristic declares write-without-response only:
            # asking for a write response makes CoreBluetooth reject the write
            # outright ("Write Not Permitted").
            await client.write_gatt_char(CHAR_UUID, frame, response=False)
            return await asyncio.wait_for(self._pending, RESPONSE_TIMEOUT)
        finally:
            self._pending = None
            self._pending_cmd = None

    @asynccontextmanager
    async def _session(self, ble_device: BLEDevice) -> AsyncIterator[BleakClient]:
        """Connect, enable notifications, and disconnect afterwards.

        One charger serves a single BLE connection at a time, so every exchange
        holds the same lock: a control command never overlaps a poll.
        """
        async with self._lock:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._address,
                timeout=CONNECT_TIMEOUT,
            )
            try:
                await client.start_notify(CHAR_UUID, self._notification_handler)
                await asyncio.sleep(NOTIFY_SETTLE)
                yield client
            except BleakError as err:
                raise SkyRcError(f"BLE error while talking to charger: {err}") from err
            finally:
                try:
                    await client.stop_notify(CHAR_UUID)
                except BleakError:  # pragma: no cover - best effort
                    pass
                await client.disconnect()

    async def _query_basic_info(
        self, client: BleakClient, mask: int
    ) -> ChannelBasicInfo | None:
        """Read a channel's battery type and program; ``None`` if unavailable."""
        if self._basic_info_failures >= MAX_BASIC_INFO_FAILURES:
            return None
        try:
            frame = await self._query(
                client,
                CMD_QUERY_BASIC_INFO,
                build_basic_info_query(mask, self._passcode),
            )
        except asyncio.TimeoutError:
            self._basic_info_failures += 1
            if self._basic_info_failures >= MAX_BASIC_INFO_FAILURES:
                _LOGGER.info(
                    "%s: charger does not answer basic-info queries (a channel "
                    "password may be enabled); charge/discharge direction will "
                    "not be reported until the integration is reloaded",
                    self._address,
                )
            else:
                _LOGGER.debug(
                    "%s: no basic-info reply for mask 0x%02X", self._address, mask
                )
            return None
        except BleakError as err:
            # A broken link fails the next status query anyway; don't lose the
            # channel data already collected in this poll over an optional read.
            _LOGGER.debug("%s: basic-info query failed: %s", self._address, err)
            return None

        self._basic_info_failures = 0
        info = parse_basic_info(frame.data)
        if info is None or info.mask != mask:
            return None
        self.passcode_accepted = info.passcode_accepted
        if not info.passcode_accepted and not self._passcode_warned:
            self._passcode_warned = True
            _LOGGER.warning(
                "%s: the charger rejected the passcode %r. It shows the code it "
                "wants on its own display while it is being asked — set that in "
                "the integration options, or turn off reading the program of a "
                "running channel to stop asking",
                self._address,
                self._passcode,
            )
        return info

    async def _apply_basic_info(
        self, client: BleakClient, status: ChannelStatus
    ) -> None:
        """Attach the channel's battery type and program to ``status``.

        Only queried for channels that need it: while working (the program can
        change between runs) and for a finished channel we haven't seen working
        — so a "done" channel still reports whether it charged or discharged.
        """
        channel = status.channel
        if status.state in (STATE_IDLE, STATE_READY):
            self._basic_info.pop(channel, None)
            self._commanded.pop(channel, None)
            self._durations.pop(channel, None)
            return

        # A channel's program cannot change without it passing through idle,
        # which clears the cache above — except when a whole run ends and
        # another starts between two polls, which shows up as the elapsed
        # duration going backwards. So ask once per run, not once per poll:
        # this query is the one that carries the passcode, and chargers that
        # want a passcode put a prompt on their display every time it arrives.
        previous = self._durations.get(channel)
        restarted = (
            status.duration_s is not None
            and previous is not None
            and status.duration_s < previous
        )
        if status.duration_s is not None:
            self._durations[channel] = status.duration_s

        if self._poll_program and (channel not in self._basic_info or restarted):
            info = await self._query_basic_info(client, status.mask)
            if info is not None:
                self._basic_info[channel] = info

        cached = self._basic_info.get(channel)
        if cached is not None:
            status.battery_type = cached.battery_type
            status.program = cached.program
        elif (commanded := self._commanded.get(channel)) is not None:
            # Fall back on what we asked the charger to run.
            status.battery_type, status.program = commanded

    async def _read_channel(
        self, client: BleakClient, mask: int
    ) -> ChannelStatus | None:
        """Read one channel's status; ``None`` if it did not answer."""
        try:
            frame = await self._query(
                client, CMD_QUERY_CHANNEL_STATUS, build_channel_query(mask)
            )
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "%s: no reply for channel mask 0x%02X", self._address, mask
            )
            return None
        return parse_channel_status(frame.data)

    async def _read_settings(self, client: BleakClient) -> ChargerSettings | None:
        """Read the charger's own settings; ``None`` if it did not answer."""
        try:
            frame = await self._query(
                client, CMD_QUERY_SYSTEM_INFO, build_system_info_query()
            )
        except asyncio.TimeoutError:
            _LOGGER.debug("%s: no system-info reply", self._address)
            return None
        return parse_system_info(frame.data)

    async def async_poll(self, ble_device: BLEDevice) -> dict[str, ChannelStatus]:
        """Connect, read all four channels and the charger settings, disconnect."""
        async with self._session(ble_device) as client:
            results: dict[str, ChannelStatus] = {}
            for mask in CHANNEL_MASKS.values():
                status = await self._read_channel(client, mask)
                if status is not None:
                    await self._apply_basic_info(client, status)
                    results[status.channel] = status

            if not results:
                raise SkyRcError(
                    "Charger connected but returned no channel data "
                    "(a channel password may be enabled in the SkyCharger app)"
                )
            # One query for the lot: the settings are global.
            self.settings = await self._read_settings(client)
            return results

    async def async_write_settings(
        self, ble_device: BLEDevice, changes: dict[str, object]
    ) -> ChargerSettings | None:
        """Apply ``changes`` to the charger's settings and read them back.

        Settings that share a frame (a limit and its enable flag, the two beep
        bytes) are sent together, filling in the unchanged half from what the
        charger currently reports. The charger stores whatever it is given —
        65535-minute timers and 2550 W power caps were all accepted — so values
        are expected to have been range-checked by the caller.
        """
        current = self.settings
        if current is None:
            raise SkyRcError(
                "Charger settings have not been read yet; try again after the "
                "next update"
            )

        def value(name: str) -> object:
            return changes.get(name, getattr(current, name))

        frames: list[bytes] = []
        if {"safety_timer_enabled", "safety_timer_minutes"} & changes.keys():
            frames.append(
                build_set_safety_timer(
                    bool(value("safety_timer_enabled")),
                    int(value("safety_timer_minutes")),  # type: ignore[arg-type]
                )
            )
        if {"capacity_limit_enabled", "capacity_limit_mah"} & changes.keys():
            frames.append(
                build_set_capacity_limit(
                    bool(value("capacity_limit_enabled")),
                    int(value("capacity_limit_mah")),  # type: ignore[arg-type]
                )
            )
        if {"beep_volume", "completion_beep"} & changes.keys():
            frames.append(
                build_set_sounds(
                    int(value("beep_volume")),  # type: ignore[arg-type]
                    bool(value("completion_beep")),
                )
            )
        if "min_input_voltage_mv" in changes:
            frames.append(
                build_set_min_input_voltage(int(value("min_input_voltage_mv")))  # type: ignore[arg-type]
            )
        if "max_input_power_w" in changes:
            frames.append(
                build_set_max_input_power(int(value("max_input_power_w")))  # type: ignore[arg-type]
            )

        async with self._session(ble_device) as client:
            for frame in frames:
                try:
                    await self._query(client, CMD_SET_SYSTEM_INFO, frame)
                except asyncio.TimeoutError as err:
                    raise SkyRcError(
                        "Charger did not acknowledge a settings change"
                    ) from err
                await asyncio.sleep(SETTING_APPLY_DELAY)
            self.settings = await self._read_settings(client)
        return self.settings

    @staticmethod
    def _raise_if_busy(status: ChannelStatus | None, channel: str) -> None:
        """Refuse to start a channel that is already running something."""
        if status is not None and status.state in (STATE_WORKING, STATE_DC_SUPPLY):
            raise SkyRcError(
                f"Channel {channel} is already running ({status.detailed_state}); "
                "stop it before starting a new program"
            )

    async def async_start_program(
        self, ble_device: BLEDevice, channel: str, config: ProgramConfig
    ) -> ChannelStatus | None:
        """Run ``config`` on ``channel``, then report what the channel did.

        The charger acknowledges a START_CHARGE frame whether or not it will
        act on it, so the acknowledgement is only checked for the channel it
        echoes; whether the program actually started is read back from the
        channel status. A channel still idle afterwards means the charger
        refused the program.
        """
        mask = CHANNEL_MASKS[channel]
        async with self._session(ble_device) as client:
            # A busy channel ignores a start frame outright — no reply at all,
            # where an idle one always acknowledges. Check first so the failure
            # says what is wrong instead of timing out.
            self._raise_if_busy(await self._read_channel(client, mask), channel)

            try:
                frame = await self._query(
                    client, CMD_START_CHARGE, build_start_charge(mask, config)
                )
            except asyncio.TimeoutError as err:
                # Started from the charger's own panel in the meantime, most
                # likely; otherwise the charger simply did not answer.
                self._raise_if_busy(await self._read_channel(client, mask), channel)
                raise SkyRcError(
                    f"Charger did not acknowledge the start of channel {channel}"
                ) from err

            ack = parse_ack(frame.data)
            if ack is not None and ack[0] != mask:
                raise SkyRcError(
                    f"Charger acknowledged channel mask 0x{ack[0]:02X} for a "
                    f"start on channel {channel} (mask 0x{mask:02X})"
                )
            _LOGGER.debug(
                "%s: started %s %s on channel %s",
                self._address,
                config.battery_type,
                config.program,
                channel,
            )
            self._commanded[channel] = (config.battery_type, config.program)

            # The channel takes a moment to leave idle.
            status = None
            for _ in range(START_CONFIRM_ATTEMPTS):
                await asyncio.sleep(START_CONFIRM_DELAY)
                status = await self._read_channel(client, mask)
                if status is not None and status.state != STATE_IDLE:
                    break
            if status is None:
                # The start was acknowledged, so it most likely took effect;
                # only the read-back failed. Say so rather than report success.
                _LOGGER.warning(
                    "%s: channel %s accepted the start but did not report its "
                    "status afterwards; check the charger",
                    self._address,
                    channel,
                )
                return None
            if status.state == STATE_IDLE:
                self._commanded.pop(channel, None)
                raise SkyRcError(
                    f"Charger refused the program for channel {channel}: it is "
                    "still idle. Check the battery type, cell count and program "
                    "against what this charger supports"
                )
            await self._apply_basic_info(client, status)
            return status

    async def async_stop(
        self, ble_device: BLEDevice, channel: str
    ) -> ChannelStatus | None:
        """Stop whatever ``channel`` is doing and report its status."""
        mask = CHANNEL_MASKS[channel]
        async with self._session(ble_device) as client:
            try:
                frame = await self._query(
                    client, CMD_STOP_CHARGE, build_stop_charge(mask)
                )
            except asyncio.TimeoutError as err:
                raise SkyRcError(
                    f"Charger did not acknowledge the stop of channel {channel}"
                ) from err

            ack = parse_ack(frame.data)
            if ack is not None and ack[0] != mask:
                raise SkyRcError(
                    f"Charger acknowledged channel mask 0x{ack[0]:02X} for a "
                    f"stop on channel {channel} (mask 0x{mask:02X})"
                )
            self._commanded.pop(channel, None)

            await asyncio.sleep(STOP_CONFIRM_DELAY)
            status = await self._read_channel(client, mask)
            if status is not None:
                await self._apply_basic_info(client, status)
            return status
