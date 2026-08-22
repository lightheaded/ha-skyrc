"""Selects for the staged program of each channel, and for saved presets."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CHANNELS,
    PRESET_NAME_MAX_LENGTH,
    SERVICE_DELETE_PRESET,
    SERVICE_SAVE_PRESET,
)
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity
from .programs import (
    BATTERY_TYPE_OPTIONS,
    BEEP_VOLUME_NAMES,
    BEEP_VOLUMES,
    CYCLE_CHARGE_FIRST,
    CYCLE_DISCHARGE_FIRST,
    CYCLE_MODEL,
    CYCLE_ORDER_CODES,
    CYCLE_ORDER_NAMES,
    ProgramConfig,
    programs_for,
)

PRESET_NAME_SCHEMA = {
    vol.Required("name"): vol.All(
        cv.string, vol.Length(min=1, max=PRESET_NAME_MAX_LENGTH)
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the per-channel program selects and the charger's beep volume."""
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [
        select
        for channel in CHANNELS
        for select in (
            SkyRcBatteryTypeSelect(coordinator, channel),
            SkyRcProgramSelect(coordinator, channel),
            SkyRcCycleOrderSelect(coordinator, channel),
            SkyRcPresetSelect(coordinator, channel),
        )
    ]
    entities.append(SkyRcBeepVolumeSelect(coordinator))
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SAVE_PRESET,
        cv.make_entity_service_schema(PRESET_NAME_SCHEMA),
        "async_handle_save_preset",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_PRESET,
        cv.make_entity_service_schema(PRESET_NAME_SCHEMA),
        "async_handle_delete_preset",
    )


class SkyRcSelect(SkyRcEntity, SelectEntity):
    """Base for every select on the charger, including the preset services.

    Deleting a preset is charger-wide, so any of them will do it. Saving one
    needs a channel, so it belongs to that channel's preset select.
    """

    async def async_handle_save_preset(self, name: str) -> None:
        """Handle save_preset on a select that has no channel to save."""
        raise ServiceValidationError(
            f"{self.entity_id} cannot save a preset; target the channel's "
            "preset select instead"
        )

    async def async_handle_delete_preset(self, name: str) -> None:
        """Delete a preset by name."""
        self.coordinator.async_delete_preset(name)


class SkyRcStagedSelect(SkyRcSelect):
    """Base for selects that hold part of a channel's staged program."""

    _attr_entity_category = EntityCategory.CONFIG
    _key: str

    def __init__(self, coordinator: SkyRcCoordinator, channel: str) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_translation_placeholders = {"channel": channel}
        self._attr_unique_id = f"{coordinator.address}_{channel}_{self._key}"

    @property
    def _staged(self) -> ProgramConfig:
        return self.coordinator.staged[self._channel]

    @property
    def available(self) -> bool:
        """Staged settings are editable even while the charger is unreachable."""
        return True


class SkyRcBatteryTypeSelect(SkyRcStagedSelect):
    """The battery type a channel will be started with."""

    _key = "battery_type"
    _attr_translation_key = "battery_type"

    def __init__(self, coordinator: SkyRcCoordinator, channel: str) -> None:
        super().__init__(coordinator, channel)
        self._attr_options = list(BATTERY_TYPE_OPTIONS)

    @property
    def current_option(self) -> str:
        return self._staged.battery_type

    async def async_select_option(self, option: str) -> None:
        """Change the battery type, moving the program to one it offers."""
        self.coordinator.async_select(self._channel, battery_type=option)


class SkyRcProgramSelect(SkyRcStagedSelect):
    """The program a channel will be started with."""

    _key = "program"
    _attr_translation_key = "program"

    @property
    def options(self) -> list[str]:
        """Only the programs the staged battery type supports."""
        return list(programs_for(self._staged.battery_type))

    @property
    def current_option(self) -> str:
        """The staged program, or the first available one if it no longer fits."""
        options = self.options
        if self._staged.program not in options:
            return options[0]
        return self._staged.program

    async def async_select_option(self, option: str) -> None:
        """Change the program, refilling the parameters it takes.

        Values entered for this program before come back; the rest fall back on
        what was last entered elsewhere, then on the program's own defaults.
        """
        self.coordinator.async_select(self._channel, program=option)


class SkyRcCycleOrderSelect(SkyRcStagedSelect):
    """Whether a nickel cycle program charges first or discharges first."""

    _key = "cycle_order"
    _attr_translation_key = "cycle_order"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SkyRcCoordinator, channel: str) -> None:
        super().__init__(coordinator, channel)
        self._attr_options = [CYCLE_CHARGE_FIRST, CYCLE_DISCHARGE_FIRST]

    @property
    def available(self) -> bool:
        """Only the cycle programs take an order."""
        return self._staged.uses(CYCLE_MODEL)

    @property
    def current_option(self) -> str:
        return CYCLE_ORDER_NAMES[self._staged.cycle_model]

    async def async_select_option(self, option: str) -> None:
        self.coordinator.async_set_parameter(
            self._channel, CYCLE_MODEL, CYCLE_ORDER_CODES[option]
        )


class SkyRcPresetSelect(SkyRcSelect):
    """The saved preset a channel is running, and the way to stage another.

    Selecting a preset applies every parameter it holds to the channel; editing
    any of them afterwards leaves the selection blank again, because what is
    staged is no longer the preset.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "preset"

    def __init__(self, coordinator: SkyRcCoordinator, channel: str) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_translation_placeholders = {"channel": channel}
        self._attr_unique_id = f"{coordinator.address}_{channel}_preset"

    @property
    def options(self) -> list[str]:
        return sorted(self.coordinator.programs.presets)

    @property
    def available(self) -> bool:
        """Nothing to pick until a preset has been saved."""
        return bool(self.coordinator.programs.presets)

    @property
    def current_option(self) -> str | None:
        return self.coordinator.programs.applied.get(self._channel)

    async def async_select_option(self, option: str) -> None:
        self.coordinator.async_apply_preset(self._channel, option)

    async def async_handle_save_preset(self, name: str) -> None:
        """Save this channel's staged program under ``name``."""
        self.coordinator.async_save_preset(name, self._channel)


class SkyRcBeepVolumeSelect(SkyRcSelect):
    """The charger's beep volume — System Settings ▸ Volume."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "beep_volume"

    def __init__(self, coordinator: SkyRcCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_options = list(BEEP_VOLUMES)
        self._attr_unique_id = f"{coordinator.address}_beep_volume"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.settings is not None

    @property
    def current_option(self) -> str | None:
        settings = self.coordinator.settings
        if settings is None:
            return None
        # The charger stores whatever it is given; anything outside the three
        # known levels is reported as unknown rather than guessed at.
        return BEEP_VOLUME_NAMES.get(settings.beep_volume)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write_settings(beep_volume=BEEP_VOLUMES[option])
