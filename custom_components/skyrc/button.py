"""Start and stop buttons for each charger channel."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import voluptuous as vol

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CHANNELS, SERVICE_START_PROGRAM
from .coordinator import SkyRcConfigEntry, SkyRcCoordinator
from .entity import SkyRcEntity
from .programs import (
    BATTERY_TYPE_OPTIONS,
    CYCLE_ORDER_CODES,
    PROGRAM_LIMITS,
    ProgramConfig,
)

_LOGGER = logging.getLogger(__name__)

# Every program name any battery type offers; which ones are valid for the
# battery type actually asked for is checked when the program is validated.
ALL_PROGRAMS = sorted({program for t in PROGRAM_LIMITS.values() for program in t})

START_PROGRAM_SCHEMA = {
    vol.Optional("battery_type"): vol.In(BATTERY_TYPE_OPTIONS),
    vol.Optional("program"): vol.In(ALL_PROGRAMS),
    vol.Optional("cell_count"): vol.All(vol.Coerce(int), vol.Range(min=1, max=15)),
    vol.Optional("charge_current"): vol.All(
        vol.Coerce(int), vol.Range(min=100, max=10000)
    ),
    vol.Optional("discharge_current"): vol.All(
        vol.Coerce(int), vol.Range(min=100, max=2000)
    ),
    vol.Optional("charge_voltage"): vol.All(
        vol.Coerce(int), vol.Range(min=600, max=4500)
    ),
    vol.Optional("discharge_voltage"): vol.All(
        vol.Coerce(int), vol.Range(min=600, max=4500)
    ),
    vol.Optional("track_voltage"): vol.All(vol.Coerce(int), vol.Range(min=50, max=300)),
    vol.Optional("cycle_number"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
    vol.Optional("cycle_order"): vol.In(list(CYCLE_ORDER_CODES)),
    vol.Optional("repeak_number"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1)),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyRcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up start and stop buttons for all four channels."""
    coordinator = entry.runtime_data
    async_add_entities(
        button
        for channel in CHANNELS
        for button in (
            SkyRcStartButton(coordinator, channel),
            SkyRcStopButton(coordinator, channel),
            SkyRcSavePresetButton(coordinator, channel),
            SkyRcDeletePresetButton(coordinator, channel),
        )
    )

    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_START_PROGRAM,
        cv.make_entity_service_schema(START_PROGRAM_SCHEMA),
        "async_handle_start_program",
    )


class SkyRcChannelButton(SkyRcEntity, ButtonEntity):
    """Base for the per-channel control buttons."""

    _key: str

    def __init__(self, coordinator: SkyRcCoordinator, channel: str) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_translation_placeholders = {"channel": channel}
        self._attr_unique_id = f"{coordinator.address}_{channel}_{self._key}"

    async def async_handle_start_program(self, **overrides: Any) -> None:
        """Handle the start_program service on the wrong kind of button."""
        raise ServiceValidationError(
            f"{self.entity_id} cannot start a program; target the channel's "
            "start button instead"
        )


class SkyRcStartButton(SkyRcChannelButton):
    """Runs the channel's staged program."""

    _key = "start"
    _attr_translation_key = "start"

    async def async_press(self) -> None:
        await self._async_start(self.coordinator.staged[self._channel])

    async def async_handle_start_program(self, **overrides: Any) -> None:
        """Run a program given in a service call, leaving the staged one alone.

        Naming a different battery type or program starts from that program's
        defaults, so only the parameters worth stating have to be given.
        """
        config = self.coordinator.staged[self._channel]
        if "cycle_order" in overrides:
            overrides["cycle_model"] = CYCLE_ORDER_CODES[overrides.pop("cycle_order")]
        base = replace(
            config,
            battery_type=overrides.pop("battery_type", config.battery_type),
            program=overrides.pop("program", config.program),
        )
        if (base.battery_type, base.program) != (config.battery_type, config.program):
            base = base.with_defaults()
        await self._async_start(replace(base, **overrides))

    async def _async_start(self, config: ProgramConfig) -> None:
        status = await self.coordinator.async_start_program(self._channel, config)
        _LOGGER.debug(
            "Channel %s started %s %s: %s",
            self._channel,
            config.battery_type,
            config.program,
            status.detailed_state if status else "no status reported",
        )


class SkyRcStopButton(SkyRcChannelButton):
    """Stops whatever the channel is doing."""

    _key = "stop"
    _attr_translation_key = "stop"

    async def async_press(self) -> None:
        await self.coordinator.async_stop(self._channel)


class SkyRcSavePresetButton(SkyRcChannelButton):
    """Saves the channel's staged program under the name beside it."""

    _key = "save_preset"
    _attr_translation_key = "save_preset"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Saving what is staged does not need the charger."""
        return True

    async def async_press(self) -> None:
        self.coordinator.async_save_preset(
            self.coordinator.preset_names[self._channel], self._channel
        )


class SkyRcDeletePresetButton(SkyRcChannelButton):
    """Deletes the preset the channel is set to.

    Presets belong to the charger, so this removes it everywhere — but it
    deletes what the channel's preset select is showing rather than a name
    typed somewhere, so what is about to go is on screen next to the button.
    """

    _key = "delete_preset"
    _attr_translation_key = "delete_preset"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def _selected(self) -> str | None:
        return self.coordinator.programs.applied.get(self._channel)

    @property
    def available(self) -> bool:
        """Only offer to delete while the channel is set to a preset."""
        return self._selected is not None

    async def async_press(self) -> None:
        if (name := self._selected) is None:
            raise ServiceValidationError(
                f"Channel {self._channel} is not set to a preset; pick the one "
                "to delete in its preset select first"
            )
        self.coordinator.async_delete_preset(name)
