"""The SkyRC Charger integration."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .coordinator import SkyRcConfigEntry, SkyRcCoordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: SkyRcConfigEntry) -> bool:
    """Set up SkyRC Q200neo from a config entry."""
    _async_remove_charging_binary_sensors(hass, entry)

    coordinator = SkyRcCoordinator(hass, entry, entry.data[CONF_ADDRESS])
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: SkyRcConfigEntry) -> None:
    """Reload the entry so changed options take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SkyRcConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _async_remove_charging_binary_sensors(
    hass: HomeAssistant, entry: SkyRcConfigEntry
) -> None:
    """Drop the per-channel 'charging' binary sensors removed in 0.2.0.

    The channel status sensor now reports charging/discharging directly; the
    old entities would otherwise linger in the registry as unavailable.
    """
    registry = er.async_get(hass)
    stale = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.domain == Platform.BINARY_SENSOR
        and entity.unique_id.endswith("_charging")
    ]
    for entity_id in stale:
        registry.async_remove(entity_id)
