"""Sensor platform for the SkyRC Q200neo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import CHANNELS, STATE_OPTIONS
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity
from .protocol import ChannelStatus


@dataclass(frozen=True, kw_only=True)
class SkyRcSensorDescription(SensorEntityDescription):
    """Describes a per-channel sensor."""

    value_fn: Callable[[ChannelStatus], StateType]


def _voltage(status: ChannelStatus) -> StateType:
    return None if status.voltage_mv is None else round(status.voltage_mv / 1000, 3)


def _current(status: ChannelStatus) -> StateType:
    return None if status.current_ma is None else round(status.current_ma / 1000, 3)


SENSORS: tuple[SkyRcSensorDescription, ...] = (
    SkyRcSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_OPTIONS,
        value_fn=lambda s: s.state_name,
    ),
    SkyRcSensorDescription(
        key="capacity",
        translation_key="capacity",
        native_unit_of_measurement="mAh",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.capacity_mah,
    ),
    SkyRcSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_voltage,
    ),
    SkyRcSensorDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_current,
    ),
    SkyRcSensorDescription(
        key="duration",
        translation_key="duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.duration_s,
    ),
    SkyRcSensorDescription(
        key="battery_temp",
        translation_key="battery_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.battery_temp_c,
    ),
)

# Device-level diagnostic sensor (read from whichever channel reports it).
CHARGER_TEMP = SkyRcSensorDescription(
    key="charger_temp",
    translation_key="charger_temp",
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda s: s.internal_temp_c,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for all four channels."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        SkyRcChannelSensor(coordinator, channel, description)
        for channel in CHANNELS
        for description in SENSORS
    ]
    entities.append(SkyRcChargerSensor(coordinator, CHARGER_TEMP))
    async_add_entities(entities)


class SkyRcChannelSensor(SkyRcEntity, SensorEntity):
    """A sensor for a single charger channel."""

    entity_description: SkyRcSensorDescription

    def __init__(
        self,
        coordinator: SkyRcCoordinator,
        channel: str,
        description: SkyRcSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self.entity_description = description
        self._attr_translation_placeholders = {"channel": channel}
        self._attr_unique_id = f"{coordinator.address}_{channel}_{description.key}"

    @property
    def _status(self) -> ChannelStatus | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._channel)

    @property
    def available(self) -> bool:
        return super().available and self._status is not None

    @property
    def native_value(self) -> StateType:
        status = self._status
        if status is None:
            return None
        return self.entity_description.value_fn(status)


class SkyRcChargerSensor(SkyRcEntity, SensorEntity):
    """A device-level sensor aggregated across channels."""

    entity_description: SkyRcSensorDescription

    def __init__(
        self, coordinator: SkyRcCoordinator, description: SkyRcSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    def native_value(self) -> StateType:
        if not self.coordinator.data:
            return None
        for status in self.coordinator.data.values():
            value = self.entity_description.value_fn(status)
            if value is not None:
                return value
        return None
