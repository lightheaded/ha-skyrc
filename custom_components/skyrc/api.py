"""BLE client for the SkyRC Q200neo charger.

Uses a connect → poll-all-channels → disconnect cycle. Freeing the radio
between polls keeps the single BLE slot available for the SkyCharger phone app
and copes better with the weak/proxied links typical of a homelab deployment.
"""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    CHANNEL_MASKS,
    CHAR_UUID,
    CMD_QUERY_BASIC_INFO,
    CMD_QUERY_CHANNEL_STATUS,
    STATE_DONE,
    STATE_IDLE,
    STATE_READY,
    STATE_WORKING,
)
from .protocol import (
    ChannelBasicInfo,
    ChannelStatus,
    Frame,
    FrameReader,
    build_basic_info_query,
    build_channel_query,
    parse_basic_info,
    parse_channel_status,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 20.0
RESPONSE_TIMEOUT = 5.0

# Give up on basic-info queries after this many consecutive timeouts, so a
# charger that never answers them doesn't stall every poll cycle.
MAX_BASIC_INFO_FAILURES = 3


class SkyRcError(Exception):
    """Raised when the charger cannot be queried."""


class SkyRcClient:
    """Talks to one charger over BLE."""

    def __init__(self, address: str) -> None:
        self._address = address
        self._lock = asyncio.Lock()
        self._reader = FrameReader()
        self._pending_cmd: int | None = None
        self._pending: asyncio.Future[Frame] | None = None
        # Last known basic info per channel, kept until the channel goes idle.
        self._basic_info: dict[str, ChannelBasicInfo] = {}
        self._basic_info_failures = 0

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
            await client.write_gatt_char(CHAR_UUID, frame, response=True)
            return await asyncio.wait_for(self._pending, RESPONSE_TIMEOUT)
        finally:
            self._pending = None
            self._pending_cmd = None

    async def _query_basic_info(
        self, client: BleakClient, mask: int
    ) -> ChannelBasicInfo | None:
        """Read a channel's battery type and program; ``None`` if unavailable."""
        if self._basic_info_failures >= MAX_BASIC_INFO_FAILURES:
            return None
        try:
            frame = await self._query(
                client, CMD_QUERY_BASIC_INFO, build_basic_info_query(mask)
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
        if info.password_required:
            _LOGGER.debug(
                "%s: channel %s reports a password is set", self._address, info.channel
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
            return

        if status.state == STATE_WORKING or (
            status.state == STATE_DONE and channel not in self._basic_info
        ):
            info = await self._query_basic_info(client, status.mask)
            if info is not None:
                self._basic_info[channel] = info

        cached = self._basic_info.get(channel)
        if cached is not None:
            status.battery_type = cached.battery_type
            status.program = cached.program

    async def async_poll(self, ble_device: BLEDevice) -> dict[str, ChannelStatus]:
        """Connect, read all four channels, and disconnect."""
        async with self._lock:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self._address,
                timeout=CONNECT_TIMEOUT,
            )
            try:
                await client.start_notify(CHAR_UUID, self._notification_handler)
                results: dict[str, ChannelStatus] = {}
                for channel, mask in CHANNEL_MASKS.items():
                    try:
                        frame = await self._query(
                            client, CMD_QUERY_CHANNEL_STATUS, build_channel_query(mask)
                        )
                    except asyncio.TimeoutError:
                        _LOGGER.debug(
                            "%s: no reply for channel %s (mask 0x%02X)",
                            self._address,
                            channel,
                            mask,
                        )
                        continue
                    status = parse_channel_status(frame.data)
                    if status is not None:
                        await self._apply_basic_info(client, status)
                        results[status.channel] = status

                if not results:
                    raise SkyRcError(
                        "Charger connected but returned no channel data "
                        "(a channel password may be enabled in the SkyCharger app)"
                    )
                return results
            except BleakError as err:
                raise SkyRcError(f"BLE error while polling: {err}") from err
            finally:
                try:
                    await client.stop_notify(CHAR_UUID)
                except BleakError:  # pragma: no cover - best effort
                    pass
                await client.disconnect()
