"""Numeric parameters of the staged program of each channel.

Ranges follow the charger: they change with the staged battery type and
program, and a parameter the program does not take reports unavailable rather
than offering a value that would be ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CHANNELS
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity
from .programs import (
    CHARGE_CURRENT,
    CHARGE_VOLTAGE,
    CYCLE_NUMBER,
    DISCHARGE_CURRENT,
    DISCHARGE_VOLTAGE,
    TRACK_VOLTAGE,
    Limit,
    ProgramConfig,
    cell_limit,
    limits_for,
)

CELL_COUNT = "cell_count"


@dataclass(frozen=True, kw_only=True)
class SkyRcNumberDescription(NumberEntityDescription):
    """Describes one staged program parameter."""

    # Attribute of ProgramConfig this entity edits.
    parameter: str


NUMBERS: tuple[SkyRcNumberDescription, ...] = (
    SkyRcNumberDescription(
        key=CELL_COUNT,
        translation_key=CELL_COUNT,
        parameter=CELL_COUNT,
        native_unit_of_measurement="cells",
    ),
    SkyRcNumberDescription(
        key=CHARGE_CURRENT,
        translation_key=CHARGE_CURRENT,
        parameter=CHARGE_CURRENT,
        device_class=NumberDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
    ),
    SkyRcNumberDescription(
        key=DISCHARGE_CURRENT,
        translation_key=DISCHARGE_CURRENT,
        parameter=DISCHARGE_CURRENT,
        device_class=NumberDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
    ),
    SkyRcNumberDescription(
        key=CHARGE_VOLTAGE,
        translation_key=CHARGE_VOLTAGE,
        parameter=CHARGE_VOLTAGE,
        device_class=NumberDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
    ),
    SkyRcNumberDescription(
        key=DISCHARGE_VOLTAGE,
        translation_key=DISCHARGE_VOLTAGE,
        parameter=DISCHARGE_VOLTAGE,
        device_class=NumberDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
    ),
    SkyRcNumberDescription(
        key=TRACK_VOLTAGE,
        translation_key=TRACK_VOLTAGE,
        parameter=TRACK_VOLTAGE,
        device_class=NumberDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_registry_enabled_default=False,
    ),
    SkyRcNumberDescription(
        key=CYCLE_NUMBER,
        translation_key=CYCLE_NUMBER,
        parameter=CYCLE_NUMBER,
        native_unit_of_measurement="cycles",
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the staged program parameters for all four channels."""
    coordinator = entry.runtime_data
    async_add_entities(
        SkyRcStagedNumber(coordinator, channel, description)
        for channel in CHANNELS
        for description in NUMBERS
    )


class SkyRcStagedNumber(SkyRcEntity, NumberEntity, RestoreEntity):
    """One numeric parameter of a channel's staged program."""

    entity_description: SkyRcNumberDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: SkyRcCoordinator,
        channel: str,
        description: SkyRcNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self.entity_description = description
        self._attr_translation_placeholders = {"channel": channel}
        self._attr_unique_id = f"{coordinator.address}_{channel}_{description.key}"

    @property
    def _staged(self) -> ProgramConfig:
        return self.coordinator.staged[self._channel]

    @property
    def _limit(self) -> Limit | None:
        """The range for this parameter under the staged battery type/program."""
        staged = self._staged
        if self.entity_description.parameter == CELL_COUNT:
            return cell_limit(staged.battery_type)
        return limits_for(staged.battery_type, staged.program).get(
            self.entity_description.parameter
        )

    @property
    def available(self) -> bool:
        """Unavailable when the staged program does not take this parameter."""
        return self._limit is not None

    @property
    def native_min_value(self) -> float:
        limit = self._limit
        return limit.min if limit else 0

    @property
    def native_max_value(self) -> float:
        limit = self._limit
        return limit.max if limit else 0

    @property
    def native_step(self) -> float:
        limit = self._limit
        return limit.step if limit else 1

    @property
    def native_value(self) -> float:
        return getattr(self._staged, self.entity_description.parameter)

    async def async_set_native_value(self, value: float) -> None:
        """Stage a new value, rounded to a step the charger accepts."""
        limit = self._limit
        if limit is None:
            return
        setattr(self._staged, self.entity_description.parameter, limit.clamp(int(value)))
        self.coordinator.async_update_listeners()

    async def async_added_to_hass(self) -> None:
        """Restore the last staged value, kept inside the current range."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        try:
            value = int(float(last_state.state))
        except ValueError:  # "unknown", "unavailable", or never recorded
            return
        limit = self._limit
        setattr(
            self._staged,
            self.entity_description.parameter,
            limit.clamp(value) if limit else value,
        )
