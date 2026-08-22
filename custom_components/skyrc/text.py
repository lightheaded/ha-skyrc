"""The name a channel's next saved preset will get.

Saving takes a name, and a name has to be typed somewhere. The field sits on
the channel it saves — Home Assistant sorts a device's configuration rows by
name, so "Channel A preset name" lands beside "Channel A preset" and "Channel
A save preset" rather than pages away from them.

The field keeps what is typed into it. It is a setting, not an action: the
save button next to it is what saves, and the name stays put afterwards so it
is clear which preset was just written.
"""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CHANNELS, PRESET_NAME_MAX_LENGTH
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the per-channel preset name fields."""
    coordinator = entry.runtime_data
    async_add_entities(
        SkyRcPresetNameText(coordinator, channel) for channel in CHANNELS
    )


class SkyRcPresetNameText(SkyRcEntity, TextEntity, RestoreEntity):
    """The name the channel's next saved preset will get."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "preset_name"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = PRESET_NAME_MAX_LENGTH

    def __init__(self, coordinator: SkyRcCoordinator, channel: str) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_translation_placeholders = {"channel": channel}
        self._attr_unique_id = f"{coordinator.address}_{channel}_preset_name"

    @property
    def available(self) -> bool:
        """Typing a name does not need the charger."""
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.preset_names[self._channel]

    async def async_set_value(self, value: str) -> None:
        self.coordinator.async_set_preset_name(self._channel, value)

    async def async_added_to_hass(self) -> None:
        """Bring back the name typed before the restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in ("unknown", "unavailable"):
            return
        self.coordinator.async_set_preset_name(self._channel, last_state.state)
