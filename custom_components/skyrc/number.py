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
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CHANNELS
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity
from .programs import (
    CELL_COUNT,
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
    """Set up the staged program parameters and the charger's own settings."""
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = [
        SkyRcStagedNumber(coordinator, channel, description)
        for channel in CHANNELS
        for description in NUMBERS
    ]
    entities.extend(
        SkyRcSettingNumber(coordinator, description) for description in SETTINGS
    )
    async_add_entities(entities)


class SkyRcStagedNumber(SkyRcEntity, NumberEntity):
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
        """Stage a new value, rounded to a step the charger accepts.

        The coordinator keeps it: a value entered once comes back when the
        program changes back, and survives a restart.
        """
        if self._limit is None:
            return
        self.coordinator.async_set_parameter(
            self._channel, self.entity_description.parameter, int(value)
        )


# --- charger-wide settings ------------------------------------------------
#
# Limits are the charger's documented ones, not the charger's enforced ones: it
# stored a 65535-minute safety timer, a 0 mAh capacity limit and a 2550 W power
# cap without complaint. The DC input range and charge power totals come from
# the Q200neo manual's specification table.


@dataclass(frozen=True, kw_only=True)
class SkyRcSettingDescription(NumberEntityDescription):
    """Describes one charger-wide setting."""

    # Attribute of ChargerSettings this entity edits.
    setting: str
    # Scale between the charger's units and the entity's.
    factor: int = 1


SETTINGS: tuple[SkyRcSettingDescription, ...] = (
    SkyRcSettingDescription(
        key="safety_timer",
        translation_key="safety_timer",
        setting="safety_timer_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=NumberDeviceClass.DURATION,
        native_min_value=1,
        native_max_value=999,
        native_step=1,
    ),
    SkyRcSettingDescription(
        key="capacity_limit",
        translation_key="capacity_limit",
        setting="capacity_limit_mah",
        native_unit_of_measurement="mAh",
        native_min_value=100,
        native_max_value=50000,
        native_step=100,
    ),
    SkyRcSettingDescription(
        key="min_input_voltage",
        translation_key="min_input_voltage",
        setting="min_input_voltage_mv",
        device_class=NumberDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        # DC input is specified as 10.0-30.0 V.
        native_min_value=10,
        native_max_value=30,
        native_step=0.1,
        factor=1000,
    ),
    SkyRcSettingDescription(
        key="max_input_power",
        translation_key="max_input_power",
        setting="max_input_power_w",
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        # 200 W total on AC, 400 W on DC.
        native_min_value=10,
        native_max_value=400,
        native_step=10,
    ),
)


class SkyRcSettingNumber(SkyRcEntity, NumberEntity):
    """One numeric setting of the charger itself."""

    entity_description: SkyRcSettingDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: SkyRcCoordinator, description: SkyRcSettingDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.settings is not None

    @property
    def native_value(self) -> float | None:
        settings = self.coordinator.settings
        if settings is None:
            return None
        raw = getattr(settings, self.entity_description.setting)
        return raw / self.entity_description.factor

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_settings(
            **{
                self.entity_description.setting: round(
                    value * self.entity_description.factor
                )
            }
        )
