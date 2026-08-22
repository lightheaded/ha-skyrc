"""DataUpdateCoordinator for the SkyRC Q200neo."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from bleak.backends.device import BLEDevice

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SkyRcClient, SkyRcError
from .const import (
    CHANNELS,
    CONF_PASSCODE,
    CONF_POLL_PROGRAM,
    DEFAULT_PASSWORD,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_PRESETS,
    PRESET_NAME_MAX_LENGTH,
    STORAGE_VERSION,
)
from .programs import ProgramConfig, ProgramError, StagedPrograms, validate
from .protocol import ChannelStatus, ChargerSettings

_LOGGER = logging.getLogger(__name__)

# Staged values are typed a few at a time; batch the writes.
SAVE_DELAY = 5

type SkyRcConfigEntry = ConfigEntry[SkyRcCoordinator]


class SkyRcCoordinator(DataUpdateCoordinator[dict[str, ChannelStatus]]):
    """Polls the charger over BLE on a fixed interval, and controls it."""

    def __init__(
        self, hass: HomeAssistant, entry: SkyRcConfigEntry, address: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {address}",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )
        self.address = address
        self._client = SkyRcClient(
            address,
            passcode=entry.options.get(CONF_PASSCODE, DEFAULT_PASSWORD),
            poll_program=entry.options.get(CONF_POLL_PROGRAM, True),
        )
        # The program each channel will run when it is started from Home
        # Assistant, the values that went into it, and the saved presets. Held
        # here, not on the charger: the charger only reports a channel's
        # battery type, cell count and program once one has run, and forgets
        # them again when the channel goes idle.
        self.programs = StagedPrograms(CHANNELS)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )

    @property
    def staged(self) -> dict[str, ProgramConfig]:
        """The program staged on each channel."""
        return self.programs.staged

    async def async_load_programs(self) -> None:
        """Restore the staged programs and presets from the last run."""
        self.programs.restore(await self._store.async_load())

    @callback
    def _async_programs_changed(self) -> None:
        """Persist the staged programs and tell the entities they moved."""
        self._store.async_delay_save(self.programs.as_dict, SAVE_DELAY)
        self.async_update_listeners()

    @callback
    def async_set_parameter(self, channel: str, parameter: str, value: int) -> None:
        """Set one parameter of a channel's staged program."""
        self.programs.set_parameter(channel, parameter, value)
        self._async_programs_changed()

    @callback
    def async_select(
        self,
        channel: str,
        *,
        battery_type: str | None = None,
        program: str | None = None,
    ) -> None:
        """Stage a different battery type and/or program on a channel."""
        self.programs.select(channel, battery_type=battery_type, program=program)
        self._async_programs_changed()

    @callback
    def async_save_preset(self, name: str, channel: str) -> None:
        """Save a channel's staged program as a named preset."""
        name = name.strip()
        if not name:
            raise ServiceValidationError("A preset needs a name")
        if len(name) > PRESET_NAME_MAX_LENGTH:
            raise ServiceValidationError(
                f"Preset name {name!r} is longer than {PRESET_NAME_MAX_LENGTH} "
                "characters"
            )
        known = name in self.programs.presets
        if not known and len(self.programs.presets) >= MAX_PRESETS:
            raise ServiceValidationError(
                f"There are already {MAX_PRESETS} presets; delete one before "
                "saving another"
            )
        self.programs.save_preset(name, channel)
        self._async_programs_changed()

    @callback
    def async_delete_preset(self, name: str) -> None:
        """Delete a named preset."""
        if name not in self.programs.presets:
            raise ServiceValidationError(f"There is no preset called {name!r}")
        self.programs.delete_preset(name)
        self._async_programs_changed()

    @callback
    def async_apply_preset(self, channel: str, name: str) -> None:
        """Stage a named preset on a channel."""
        if name not in self.programs.presets:
            raise ServiceValidationError(f"There is no preset called {name!r}")
        self.programs.apply_preset(channel, name)
        self._async_programs_changed()

    def _ble_device(self) -> BLEDevice:
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise SkyRcError(
                f"Charger {self.address} not currently in range of a Bluetooth adapter"
            )
        return device

    async def _async_update_data(self) -> dict[str, ChannelStatus]:
        try:
            data = await self._client.async_poll(self._ble_device())
        except SkyRcError as err:
            raise UpdateFailed(str(err)) from err

        # A refused passcode is why the charger puts a prompt on its display.
        # Ask for the right one rather than leaving it prompting: Home Assistant
        # only raises one reauth flow per entry, so this is safe to repeat.
        if self._client.passcode_accepted is False:
            self.config_entry.async_start_reauth(self.hass)
        return data

    async def async_start_program(
        self, channel: str, config: ProgramConfig
    ) -> ChannelStatus | None:
        """Validate ``config`` and run it on ``channel``."""
        try:
            validate(config, channel)
        except ProgramError as err:
            raise ServiceValidationError(str(err)) from err
        try:
            status = await self._client.async_start_program(
                self._ble_device(), channel, config
            )
        except SkyRcError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
        return status

    @property
    def settings(self) -> ChargerSettings | None:
        """The charger's own settings, as of the last poll."""
        return self._client.settings

    async def async_write_settings(self, **changes: object) -> None:
        """Change charger settings, then tell the entities."""
        try:
            await self._client.async_write_settings(self._ble_device(), changes)
        except SkyRcError as err:
            raise HomeAssistantError(str(err)) from err
        self.async_update_listeners()

    async def async_stop(self, channel: str) -> ChannelStatus | None:
        """Stop ``channel``."""
        try:
            status = await self._client.async_stop(self._ble_device(), channel)
        except SkyRcError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
        return status
