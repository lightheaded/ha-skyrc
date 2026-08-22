"""The SkyRC Charger integration."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]


async def async_setup_entry(hass: HomeAssistant, entry: SkyRcConfigEntry) -> bool:
    """Set up SkyRC Q200neo from a config entry."""
    _async_remove_stale_entities(hass, entry)

    coordinator = SkyRcCoordinator(hass, entry, entry.data[CONF_ADDRESS])
    await coordinator.async_load_programs()
    # Deliberately not async_config_entry_first_refresh(): a charger that is
    # switched off or out of Bluetooth range would abort the whole setup, and
    # with it the staged programs and presets — which live here rather than on
    # the charger and need nothing from it. So set up either way, keep polling,
    # and let the entities that do need the charger report unavailable until a
    # poll succeeds.
    await coordinator.async_refresh()

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


async def async_remove_entry(hass: HomeAssistant, entry: SkyRcConfigEntry) -> None:
    """Drop the staged programs and presets kept for a removed charger."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


def _async_remove_stale_entities(hass: HomeAssistant, entry: SkyRcConfigEntry) -> None:
    """Drop entities earlier versions created that nothing updates any more.

    They would otherwise linger in the registry as unavailable rows on the
    device page:

    * the per-channel 'charging' binary sensors removed in 0.2.0 — the channel
      status sensor reports charging/discharging directly now;
    * the charger-wide preset name field and the per-channel save-preset
      buttons removed in 0.4.0b3, replaced by one field per channel that saves
      as soon as a name is typed into it.
    """
    registry = er.async_get(hass)
    stale = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if (
            entity.domain == Platform.BINARY_SENSOR
            and entity.unique_id.endswith("_charging")
        )
        or (
            entity.domain == Platform.TEXT
            and entity.unique_id.endswith("_preset_name")
        )
        or (
            entity.domain == Platform.BUTTON
            and entity.unique_id.endswith("_save_preset")
        )
    ]
    for entity_id in stale:
        registry.async_remove(entity_id)
