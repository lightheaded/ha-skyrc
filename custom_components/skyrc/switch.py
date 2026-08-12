"""Charger-wide on/off settings.

The two cut-offs are the charger's own safety net — Task Parameters ▸ Safety
Timer and Max. Capacity — and they are what stops a run that goes wrong when
nobody is watching. They are enabled on the charger by default and worth
leaving that way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity
from .protocol import ChargerSettings


@dataclass(frozen=True, kw_only=True)
class SkyRcSwitchDescription(SwitchEntityDescription):
    """Describes one on/off charger setting."""

    value_fn: Callable[[ChargerSettings], bool]
    # Attribute of ChargerSettings to write.
    setting: str


SWITCHES: tuple[SkyRcSwitchDescription, ...] = (
    SkyRcSwitchDescription(
        key="safety_timer_enabled",
        translation_key="safety_timer_enabled",
        setting="safety_timer_enabled",
        value_fn=lambda s: s.safety_timer_enabled,
    ),
    SkyRcSwitchDescription(
        key="capacity_limit_enabled",
        translation_key="capacity_limit_enabled",
        setting="capacity_limit_enabled",
        value_fn=lambda s: s.capacity_limit_enabled,
    ),
    SkyRcSwitchDescription(
        key="completion_beep",
        translation_key="completion_beep",
        setting="completion_beep",
        value_fn=lambda s: s.completion_beep,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the charger's on/off settings."""
    coordinator = entry.runtime_data
    async_add_entities(
        SkyRcSettingSwitch(coordinator, description) for description in SWITCHES
    )


class SkyRcSettingSwitch(SkyRcEntity, SwitchEntity):
    """One on/off setting of the charger itself."""

    entity_description: SkyRcSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: SkyRcCoordinator, description: SkyRcSwitchDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.settings is not None

    @property
    def is_on(self) -> bool | None:
        settings = self.coordinator.settings
        if settings is None:
            return None
        return self.entity_description.value_fn(settings)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_settings(
            **{self.entity_description.setting: True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_settings(
            **{self.entity_description.setting: False}
        )
