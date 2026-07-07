"""Binary sensor platform for the SkyRC Q200neo."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACTIVE_STATES, CHANNELS
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity
from .protocol import ChannelStatus


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a 'charging' binary sensor per channel."""
    coordinator = entry.runtime_data
    async_add_entities(
        SkyRcChargingBinarySensor(coordinator, channel) for channel in CHANNELS
    )


class SkyRcChargingBinarySensor(SkyRcEntity, BinarySensorEntity):
    """On while a channel is actively charging/discharging."""

    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    def __init__(self, coordinator: SkyRcCoordinator, channel: str) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_translation_placeholders = {"channel": channel}
        self._attr_unique_id = f"{coordinator.address}_{channel}_charging"

    @property
    def _status(self) -> ChannelStatus | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._channel)

    @property
    def available(self) -> bool:
        return super().available and self._status is not None

    @property
    def is_on(self) -> bool | None:
        status = self._status
        if status is None:
            return None
        return status.state in ACTIVE_STATES
