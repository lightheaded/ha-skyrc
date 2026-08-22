"""The field that saves a channel's staged program as a named preset.

Saving needs a name, and a name has to be typed somewhere. The field sits on
the channel it saves — type a name, press enter, and the channel's preset
select offers it from then on. Home Assistant sorts a device's configuration
rows by name, so "Channel A save preset as" lands next to "Channel A preset"
rather than pages away from it.
"""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CHANNELS, PRESET_NAME_MAX_LENGTH
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the per-channel save-preset fields."""
    coordinator = entry.runtime_data
    async_add_entities(
        SkyRcSavePresetText(coordinator, channel) for channel in CHANNELS
    )


class SkyRcSavePresetText(SkyRcEntity, TextEntity):
    """Saves the channel's staged program under the name typed into it."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "save_preset_as"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = PRESET_NAME_MAX_LENGTH

    def __init__(self, coordinator: SkyRcCoordinator, channel: str) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_translation_placeholders = {"channel": channel}
        self._attr_unique_id = f"{coordinator.address}_{channel}_save_preset_as"

    @property
    def available(self) -> bool:
        """What is staged is known whether or not the charger answers."""
        return True

    @property
    def native_value(self) -> str:
        """Always empty: the field is an action, not a setting.

        It clears itself once the preset is saved, so it is ready for the next
        one and never claims to hold the name of something already saved.
        """
        return ""

    async def async_set_value(self, value: str) -> None:
        """Save the staged program under ``value``.

        A rejected name — blank, too long, one preset too many — leaves the
        field as it was and surfaces the reason to whoever typed it.
        """
        if value.strip():
            self.coordinator.async_save_preset(value, self._channel)
        self.async_write_ha_state()
