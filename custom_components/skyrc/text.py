"""The name a staged program is saved under.

Saving a preset takes a name, and a name has to be typed somewhere. One field
for the charger, next to the per-channel save buttons, keeps the whole flow on
the device page: type a name, press save on the channel, pick it again later
from that channel's preset select.
"""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import PRESET_NAME_MAX_LENGTH
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charger's preset name field."""
    async_add_entities([SkyRcPresetNameText(entry.runtime_data)])


class SkyRcPresetNameText(SkyRcEntity, TextEntity, RestoreEntity):
    """The name the next saved preset will get."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "preset_name"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = PRESET_NAME_MAX_LENGTH

    def __init__(self, coordinator: SkyRcCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_preset_name"

    @property
    def available(self) -> bool:
        """Typing a name does not need the charger."""
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.preset_name

    async def async_set_value(self, value: str) -> None:
        self.coordinator.async_set_preset_name(value)

    async def async_added_to_hass(self) -> None:
        """Bring back the name typed before the restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in ("unknown", "unavailable"):
            return
        self.coordinator.async_set_preset_name(last_state.state)
