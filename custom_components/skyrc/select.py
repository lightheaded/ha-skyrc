"""Battery type and program selects for the staged program of each channel."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CHANNELS
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
        )
    ]
    entities.append(SkyRcBeepVolumeSelect(coordinator))
    async_add_entities(entities)


class SkyRcStagedSelect(SkyRcEntity, SelectEntity, RestoreEntity):
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

    async def async_added_to_hass(self) -> None:
        """Restore the last selection into the staged program."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._restore(last_state.state)

    def _restore(self, value: str) -> None:
        """Apply a restored state to the staged program, if it still fits."""
        if value in self.options:
            setattr(self._staged, self._key, value)


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
        """Change the battery type, resetting the program to suit it."""
        staged = self._staged
        staged.battery_type = option
        if staged.program not in programs_for(option):
            staged.program = programs_for(option)[0]
        self.coordinator.staged[self._channel] = staged.with_defaults()
        self.coordinator.async_update_listeners()


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
        """The staged program, or the first available one if it no longer fits.

        Restored selections are applied per entity, so a program restored
        before its battery type can briefly disagree with it.
        """
        options = self.options
        if self._staged.program not in options:
            return options[0]
        return self._staged.program

    async def async_select_option(self, option: str) -> None:
        """Change the program, resetting its parameters to their defaults."""
        staged = self._staged
        staged.program = option
        self.coordinator.staged[self._channel] = staged.with_defaults()
        self.coordinator.async_update_listeners()


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
        self._staged.cycle_model = CYCLE_ORDER_CODES[option]
        self.coordinator.async_update_listeners()

    def _restore(self, value: str) -> None:
        """The order is stored as the cycle_model byte, not by name."""
        if value in CYCLE_ORDER_CODES:
            self._staged.cycle_model = CYCLE_ORDER_CODES[value]


class SkyRcBeepVolumeSelect(SkyRcEntity, SelectEntity):
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
