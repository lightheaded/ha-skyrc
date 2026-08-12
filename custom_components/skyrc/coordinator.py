"""DataUpdateCoordinator for the SkyRC Q200neo."""

from __future__ import annotations

import logging
from datetime import timedelta

from bleak.backends.device import BLEDevice

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SkyRcClient, SkyRcError
from .const import (
    CHANNELS,
    CONF_PASSCODE,
    CONF_POLL_PROGRAM,
    DEFAULT_PASSWORD,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .programs import ProgramConfig, ProgramError, validate
from .protocol import ChannelStatus

_LOGGER = logging.getLogger(__name__)

type SkyRcConfigEntry = ConfigEntry[SkyRcCoordinator]


class SkyRcCoordinator(DataUpdateCoordinator[dict[str, ChannelStatus]]):
    """Polls the charger over BLE on a fixed interval, and controls it."""

    def __init__(
        self, hass: HomeAssistant, entry: SkyRcConfigEntry, address: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {address}",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        self.address = address
        self._client = SkyRcClient(
            address,
            passcode=entry.options.get(CONF_PASSCODE, DEFAULT_PASSWORD),
            poll_program=entry.options.get(CONF_POLL_PROGRAM, True),
        )
        # The program each channel will run when it is started from Home
        # Assistant. Held here, not on the charger: the charger only reports a
        # channel's battery type, cell count and program once one has run.
        self.staged: dict[str, ProgramConfig] = {
            channel: ProgramConfig() for channel in CHANNELS
        }

    def _ble_device(self) -> BLEDevice:
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise SkyRcError(
                f"Charger {self.address} not currently in range of a Bluetooth adapter"
            )
        return device

    async def _async_update_data(self) -> dict[str, ChannelStatus]:
        try:
            return await self._client.async_poll(self._ble_device())
        except SkyRcError as err:
            raise UpdateFailed(str(err)) from err

    async def async_start_program(
        self, channel: str, config: ProgramConfig
    ) -> ChannelStatus | None:
        """Validate ``config`` and run it on ``channel``."""
        try:
            validate(config, channel)
        except ProgramError as err:
            raise ServiceValidationError(str(err)) from err
        try:
            status = await self._client.async_start_program(
                self._ble_device(), channel, config
            )
        except SkyRcError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
        return status

    async def async_stop(self, channel: str) -> ChannelStatus | None:
        """Stop ``channel``."""
        try:
            status = await self._client.async_stop(self._ble_device(), channel)
        except SkyRcError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
        return status
