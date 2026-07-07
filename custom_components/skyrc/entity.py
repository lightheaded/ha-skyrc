"""Base entity for the SkyRC Q200neo integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import SkyRcCoordinator


class SkyRcEntity(CoordinatorEntity[SkyRcCoordinator]):
    """Base class wiring entities to the charger device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SkyRcCoordinator) -> None:
        super().__init__(coordinator)
        address = coordinator.address
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=coordinator.config_entry.title,
        )
