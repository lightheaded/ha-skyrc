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

from .const import CHANNEL_MASKS, CHAR_UUID, CMD_QUERY_CHANNEL_STATUS
from .protocol import ChannelStatus, Frame, FrameReader, build_channel_query, parse_channel_status

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 20.0
RESPONSE_TIMEOUT = 5.0


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

    async def _query(self, client: BleakClient, mask: int) -> Frame:
        """Send a channel-status query and await the matching reply frame."""
        loop = asyncio.get_running_loop()
        self._reader.reset()
        self._pending_cmd = CMD_QUERY_CHANNEL_STATUS
        self._pending = loop.create_future()
        try:
            await client.write_gatt_char(
                CHAR_UUID, build_channel_query(mask), response=True
            )
            return await asyncio.wait_for(self._pending, RESPONSE_TIMEOUT)
        finally:
            self._pending = None
            self._pending_cmd = None

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
                        frame = await self._query(client, mask)
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
