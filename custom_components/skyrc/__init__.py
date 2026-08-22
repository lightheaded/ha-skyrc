"""The SkyRC Charger integration."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import CHANNELS, DOMAIN, STORAGE_VERSION
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
    * the charger-wide preset name field of 0.4.0b1, now one field per channel;
    * the 'save preset as' fields of 0.4.0b3, which saved on enter — the save
      button they replaced is back, so the name field is a field again.

    Matched by exact unique_id, not by suffix: the per-channel preset name
    fields end in '_preset_name' too, and a suffix match would sweep away the
    entities this integration is currently creating.
    """
    address = entry.data[CONF_ADDRESS]
    gone = {f"{address}_preset_name"} | {
        f"{address}_{channel}_save_preset_as" for channel in CHANNELS
    }
    registry = er.async_get(hass)
    stale = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if (
            entity.domain == Platform.BINARY_SENSOR
            and entity.unique_id.endswith("_charging")
        )
        or (entity.domain == Platform.TEXT and entity.unique_id in gone)
    ]
    for entity_id in stale:
        registry.async_remove(entity_id)
