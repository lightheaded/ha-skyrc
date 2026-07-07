"""DataUpdateCoordinator for the SkyRC Q200neo."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SkyRcClient, SkyRcError
from .const import DEFAULT_POLL_INTERVAL, DOMAIN
from .protocol import ChannelStatus

_LOGGER = logging.getLogger(__name__)

type SkyRcConfigEntry = ConfigEntry[SkyRcCoordinator]


class SkyRcCoordinator(DataUpdateCoordinator[dict[str, ChannelStatus]]):
    """Polls the charger over BLE on a fixed interval."""

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
        self._client = SkyRcClient(address)

    async def _async_update_data(self) -> dict[str, ChannelStatus]:
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise UpdateFailed(
                f"Charger {self.address} not currently in range of a Bluetooth adapter"
            )
        try:
            return await self._client.async_poll(ble_device)
        except SkyRcError as err:
            raise UpdateFailed(str(err)) from err
