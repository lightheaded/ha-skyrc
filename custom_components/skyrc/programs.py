"""Charge programs, their parameter limits, and validation.

The charger accepts a START_CHARGE frame without checking much of it: a 9999 mV
per-cell charge voltage and a channel mask of 0x10 were both acknowledged on a
live Q200neo. Nothing on the device side stops a bad program from being run
against a real pack, so every parameter is validated here before a frame is
built.

The limits are the ones the SkyCharger app enforces for the Q200neo
(``DEVICE_ATTR[DeviceType.Q200NEO]`` in the reference app), which match the
"Standard Battery Parameters" table in the SkyRC manual.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields, replace
from typing import Any, Final, NamedTuple

from .const import (
    BATTERY_CHEMISTRY,
    BATTERY_TYPE_NAMES,
    CHANNEL_MASKS,
    CHEM_LEAD,
    CHEM_LITHIUM,
    CHEM_NICKEL,
    PROGRAM_NAMES,
)


class Limit(NamedTuple):
    """Allowed range for one program parameter."""

    min: int
    max: int
    step: int
    default: int

    def clamp(self, value: int) -> int:
        """Round ``value`` to the nearest step within the range."""
        stepped = self.min + round((value - self.min) / self.step) * self.step
        return max(self.min, min(self.max, stepped))


# Parameter names used both as dict keys here and as entity key suffixes.
CELL_COUNT: Final = "cell_count"
CHARGE_CURRENT: Final = "charge_current"
DISCHARGE_CURRENT: Final = "discharge_current"
CHARGE_VOLTAGE: Final = "charge_voltage"
DISCHARGE_VOLTAGE: Final = "discharge_voltage"
CYCLE_MODEL: Final = "cycle_model"
CYCLE_NUMBER: Final = "cycle_number"
REPEAK_NUMBER: Final = "repeak_number"
TRACK_VOLTAGE: Final = "track_voltage"

# Per battery type and program: the parameters the program takes, with the
# limits the app enforces. A parameter absent here is not sent (zero bytes).
PROGRAM_LIMITS: Final[dict[str, dict[str, dict[str, Limit]]]] = {
    "lipo": {
        "balance_charge": {
            CHARGE_VOLTAGE: Limit(4150, 4250, 10, 4200),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "charge": {
            CHARGE_VOLTAGE: Limit(4150, 4250, 10, 4200),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "discharge": {
            DISCHARGE_VOLTAGE: Limit(3000, 3400, 100, 3300),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
        "storage": {
            DISCHARGE_VOLTAGE: Limit(3750, 3900, 10, 3850),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
    },
    "liion": {
        "balance_charge": {
            CHARGE_VOLTAGE: Limit(4050, 4250, 10, 4100),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "charge": {
            CHARGE_VOLTAGE: Limit(4050, 4250, 10, 4100),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "discharge": {
            DISCHARGE_VOLTAGE: Limit(2900, 3300, 100, 3200),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
        "storage": {
            DISCHARGE_VOLTAGE: Limit(3700, 3850, 10, 3800),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
    },
    "life": {
        "balance_charge": {
            CHARGE_VOLTAGE: Limit(3580, 3700, 10, 3650),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "charge": {
            CHARGE_VOLTAGE: Limit(3580, 3700, 10, 3650),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "discharge": {
            DISCHARGE_VOLTAGE: Limit(2600, 3000, 100, 2900),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
        "storage": {
            DISCHARGE_VOLTAGE: Limit(3250, 3400, 10, 3300),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
    },
    "lihv": {
        "balance_charge": {
            CHARGE_VOLTAGE: Limit(4250, 4500, 10, 4350),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "charge": {
            CHARGE_VOLTAGE: Limit(4250, 4500, 10, 4350),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "discharge": {
            DISCHARGE_VOLTAGE: Limit(3100, 3500, 100, 3400),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
        "storage": {
            DISCHARGE_VOLTAGE: Limit(3850, 3950, 10, 3900),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
    },
    "nimh": {
        "charge": {
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
            TRACK_VOLTAGE: Limit(50, 300, 10, 50),
        },
        "discharge": {
            DISCHARGE_VOLTAGE: Limit(600, 1000, 100, 900),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
            TRACK_VOLTAGE: Limit(50, 300, 10, 50),
        },
        "re_peak": {
            CHARGE_CURRENT: Limit(100, 10000, 100, 3000),
            REPEAK_NUMBER: Limit(1, 1, 1, 1),
            TRACK_VOLTAGE: Limit(50, 300, 1, 60),
        },
        "cycle": {
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
            CYCLE_MODEL: Limit(0, 1, 1, 0),
            CYCLE_NUMBER: Limit(1, 3, 1, 2),
            TRACK_VOLTAGE: Limit(50, 300, 10, 50),
        },
    },
    "nicd": {
        "charge": {
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
            TRACK_VOLTAGE: Limit(50, 300, 10, 50),
        },
        "discharge": {
            DISCHARGE_VOLTAGE: Limit(600, 1000, 100, 900),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
            TRACK_VOLTAGE: Limit(50, 300, 10, 50),
        },
        "re_peak": {
            CHARGE_CURRENT: Limit(100, 10000, 100, 3000),
            REPEAK_NUMBER: Limit(1, 1, 1, 1),
            TRACK_VOLTAGE: Limit(59, 300, 1, 60),
        },
        "cycle": {
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
            CYCLE_MODEL: Limit(0, 1, 1, 0),
            CYCLE_NUMBER: Limit(1, 3, 1, 2),
            TRACK_VOLTAGE: Limit(50, 300, 10, 50),
        },
    },
    "pb": {
        "charge": {
            CHARGE_VOLTAGE: Limit(2300, 2750, 10, 2400),
            CHARGE_CURRENT: Limit(100, 10000, 100, 100),
        },
        "discharge": {
            DISCHARGE_VOLTAGE: Limit(1800, 2000, 100, 1900),
            DISCHARGE_CURRENT: Limit(100, 2000, 100, 100),
        },
    },
}

# The Q200neo also offers AGM and Cold charge programs for lead-acid packs, and
# a Pb AGM battery type. Neither has a known program byte — the reference app
# maps lead acid to charge/discharge only — so they are left out rather than
# guessed at.

# Cycle order (BatteryCycleType in the reference app), sent as the cycle_model
# byte of a nickel cycle program.
CYCLE_CHARGE_FIRST: Final = "charge_discharge"
CYCLE_DISCHARGE_FIRST: Final = "discharge_charge"
CYCLE_ORDER_NAMES: Final[dict[int, str]] = {
    0x00: CYCLE_CHARGE_FIRST,
    0x01: CYCLE_DISCHARGE_FIRST,
}
CYCLE_ORDER_CODES: Final[dict[str, int]] = {
    name: code for code, name in CYCLE_ORDER_NAMES.items()
}

# Beep volume (System Settings > Volume). The charger stores any byte it is
# given; these are the three levels its own menu offers.
BEEP_VOLUME_NAMES: Final[dict[int, str]] = {0: "off", 1: "low", 2: "high"}
BEEP_VOLUMES: Final[dict[str, int]] = {
    name: code for code, name in BEEP_VOLUME_NAMES.items()
}

# Cells per chemistry (BATTERY_CHEMISTRY_ATTR in the reference app).
CELL_LIMITS: Final[dict[str, Limit]] = {
    CHEM_LITHIUM: Limit(1, 6, 1, 3),
    CHEM_NICKEL: Limit(1, 15, 1, 4),
    CHEM_LEAD: Limit(1, 10, 1, 6),
}

# Reverse lookups: name -> byte code.
BATTERY_TYPE_CODES: Final[dict[str, int]] = {
    name: code for code, name in BATTERY_TYPE_NAMES.items()
}
PROGRAM_CODES: Final[dict[str, dict[str, int]]] = {
    chemistry: {name: code for code, name in programs.items()}
    for chemistry, programs in PROGRAM_NAMES.items()
}

# Battery types this integration can start a program on, in menu order.
BATTERY_TYPE_OPTIONS: Final = tuple(PROGRAM_LIMITS)


def chemistry_of(battery_type: str) -> str:
    """Chemistry for a battery type name."""
    return BATTERY_CHEMISTRY[BATTERY_TYPE_CODES[battery_type]]


def programs_for(battery_type: str) -> tuple[str, ...]:
    """Programs available for ``battery_type``, in menu order."""
    return tuple(PROGRAM_LIMITS.get(battery_type, {}))


def limits_for(battery_type: str, program: str) -> dict[str, Limit]:
    """Parameter limits for one battery type and program."""
    return PROGRAM_LIMITS.get(battery_type, {}).get(program, {})


def cell_limit(battery_type: str) -> Limit:
    """Cell-count range for ``battery_type``."""
    return CELL_LIMITS[chemistry_of(battery_type)]


@dataclass
class ProgramConfig:
    """A charge program staged for one channel.

    Voltages are per cell, in mV — the same units the charger's own
    "Condition" menu uses. Currents are in mA.
    """

    battery_type: str = "lipo"
    program: str = "balance_charge"
    cell_count: int = 3
    charge_current: int = 100
    discharge_current: int = 100
    charge_voltage: int = 4200
    discharge_voltage: int = 3300
    cycle_model: int = 0
    cycle_number: int = 2
    repeak_number: int = 1
    track_voltage: int = 50

    def with_defaults(self) -> ProgramConfig:
        """Copy with every parameter of the current program set to its default."""
        limits = limits_for(self.battery_type, self.program)
        changes = {name: limit.default for name, limit in limits.items()}
        changes["cell_count"] = cell_limit(self.battery_type).clamp(self.cell_count)
        return replace(self, **changes)

    def uses(self, parameter: str) -> bool:
        """Whether the current program takes ``parameter``."""
        return parameter in limits_for(self.battery_type, self.program)

    def as_dict(self) -> dict[str, Any]:
        """Plain-JSON form, for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProgramConfig:
        """Rebuild from :meth:`as_dict`, ignoring anything unrecognised.

        Stored data outlives the code that wrote it: a program that no longer
        exists, or a value of the wrong type, falls back to the default rather
        than failing the whole load.
        """
        config = cls()
        for field in fields(cls):
            if field.name not in data:
                continue
            value = data[field.name]
            if isinstance(getattr(config, field.name), int):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                setattr(config, field.name, int(value))
            elif isinstance(value, str):
                setattr(config, field.name, value)
        if config.battery_type not in PROGRAM_LIMITS:
            return cls()
        if config.program not in programs_for(config.battery_type):
            config.program = programs_for(config.battery_type)[0]
        return config.clamped()

    def clamped(self) -> ProgramConfig:
        """Copy with every parameter of the current program inside its range."""
        changes: dict[str, int] = {
            name: limit.clamp(getattr(self, name))
            for name, limit in limits_for(self.battery_type, self.program).items()
        }
        changes[CELL_COUNT] = cell_limit(self.battery_type).clamp(self.cell_count)
        return replace(self, **changes)


# Parameters that keep their value when the battery type changes. A current is
# a property of the pack in front of you, so it is worth carrying over; a
# voltage setpoint belongs to the chemistry, and clamping a 4200 mV LiPo
# setpoint into the LiFe range would silently land on that range's maximum.
CARRY_OVER_PARAMETERS: Final = frozenset(
    {CELL_COUNT, CHARGE_CURRENT, DISCHARGE_CURRENT, CYCLE_NUMBER, REPEAK_NUMBER}
)


class StagedPrograms:
    """What each channel will run next, what was typed before, and named presets.

    The charger keeps none of this: it reports a channel's program only while
    one is running, and forgets it when the channel goes idle. Holding it here
    means a value typed once survives a program change, a lost Bluetooth link
    and a restart, instead of reverting to the program's default each time.
    """

    def __init__(self, channels: Iterable[str]) -> None:
        self.channels = tuple(channels)
        self.staged: dict[str, ProgramConfig] = {
            channel: ProgramConfig() for channel in self.channels
        }
        # channel -> "battery_type/program" -> parameter -> value, as last set
        # by the user for exactly that combination.
        self._memory: dict[str, dict[str, dict[str, int]]] = {}
        # channel -> parameter -> value, as last set for any program: what a
        # carried-over parameter falls back on.
        self._last: dict[str, dict[str, int]] = {}
        self.presets: dict[str, ProgramConfig] = {}
        # channel -> the preset its staged program still matches, if any.
        self.applied: dict[str, str] = {}

    def get(self, channel: str) -> ProgramConfig:
        """The program staged for ``channel``."""
        return self.staged[channel]

    # --- editing ----------------------------------------------------------

    def set_parameter(self, channel: str, parameter: str, value: int) -> int:
        """Set one parameter of a staged program, and remember it.

        Returns the value actually staged, which is ``value`` rounded into the
        range the charger accepts for it.
        """
        staged = self.staged[channel]
        limit = (
            cell_limit(staged.battery_type)
            if parameter == CELL_COUNT
            else limits_for(staged.battery_type, staged.program).get(parameter)
        )
        if limit is not None:
            value = limit.clamp(value)
        setattr(staged, parameter, value)
        self._remember(channel, parameter, value)
        self.applied.pop(channel, None)
        return value

    def select(
        self,
        channel: str,
        *,
        battery_type: str | None = None,
        program: str | None = None,
    ) -> ProgramConfig:
        """Stage a different battery type and/or program on ``channel``.

        Parameters the new program takes are filled in from what the user last
        entered for it, then from what they last entered anywhere (currents
        only — see :data:`CARRY_OVER_PARAMETERS`), then from the program's
        default.
        """
        staged = self.staged[channel]
        new_type = battery_type or staged.battery_type
        new_program = program or staged.program
        if new_program not in programs_for(new_type):
            new_program = programs_for(new_type)[0]

        config = replace(
            staged, battery_type=new_type, program=new_program
        ).with_defaults()

        remembered = self._memory.get(channel, {}).get(_key(new_type, new_program), {})
        last = self._last.get(channel, {})
        limits = dict(limits_for(new_type, new_program))
        limits[CELL_COUNT] = cell_limit(new_type)
        for parameter, limit in limits.items():
            if parameter in remembered:
                value = remembered[parameter]
            elif parameter in CARRY_OVER_PARAMETERS and parameter in last:
                value = last[parameter]
            else:
                continue
            setattr(config, parameter, limit.clamp(value))

        self.staged[channel] = config
        self.applied.pop(channel, None)
        return config

    def _remember(self, channel: str, parameter: str, value: int) -> None:
        staged = self.staged[channel]
        key = _key(staged.battery_type, staged.program)
        self._memory.setdefault(channel, {}).setdefault(key, {})[parameter] = value
        self._last.setdefault(channel, {})[parameter] = value

    # --- presets ----------------------------------------------------------

    def save_preset(self, name: str, channel: str) -> ProgramConfig:
        """Save what ``channel`` has staged as a preset called ``name``."""
        config = replace(self.staged[channel])
        self.presets[name] = config
        self.applied[channel] = name
        return config

    def delete_preset(self, name: str) -> None:
        """Forget the preset called ``name``."""
        self.presets.pop(name, None)
        for channel, applied in list(self.applied.items()):
            if applied == name:
                del self.applied[channel]

    def apply_preset(self, channel: str, name: str) -> ProgramConfig:
        """Stage the preset called ``name`` on ``channel``."""
        config = replace(self.presets[name]).clamped()
        self.staged[channel] = config
        self.applied[channel] = name
        return config

    # --- persistence ------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        """Plain-JSON form of everything worth keeping across a restart."""
        return {
            "staged": {c: p.as_dict() for c, p in self.staged.items()},
            "memory": self._memory,
            "last": self._last,
            "presets": {name: p.as_dict() for name, p in self.presets.items()},
            "applied": self.applied,
        }

    def restore(self, data: Mapping[str, Any] | None) -> None:
        """Load :meth:`as_dict` output back, ignoring anything unusable."""
        if not data:
            return
        for channel, config in _mapping(data.get("staged")).items():
            if channel in self.staged and isinstance(config, Mapping):
                self.staged[channel] = ProgramConfig.from_dict(config)
        for name, config in _mapping(data.get("presets")).items():
            if isinstance(config, Mapping):
                self.presets[str(name)] = ProgramConfig.from_dict(config)
        self._memory = {
            channel: {
                key: {p: int(v) for p, v in _mapping(values).items() if _is_int(v)}
                for key, values in _mapping(programs).items()
            }
            for channel, programs in _mapping(data.get("memory")).items()
            if channel in self.staged
        }
        self._last = {
            channel: {p: int(v) for p, v in _mapping(values).items() if _is_int(v)}
            for channel, values in _mapping(data.get("last")).items()
            if channel in self.staged
        }
        self.applied = {
            channel: str(name)
            for channel, name in _mapping(data.get("applied")).items()
            if channel in self.staged and name in self.presets
        }


def _key(battery_type: str, program: str) -> str:
    return f"{battery_type}/{program}"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _is_int(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class ProgramError(ValueError):
    """Raised when a staged program cannot be run as configured."""


def validate(config: ProgramConfig, channel: str) -> None:
    """Check ``config`` against the device limits, or raise ``ProgramError``."""
    if channel not in CHANNEL_MASKS:
        raise ProgramError(
            f"Unknown channel {channel!r}; expected one of "
            f"{', '.join(CHANNEL_MASKS)}"
        )
    if config.battery_type not in PROGRAM_LIMITS:
        raise ProgramError(
            f"Unsupported battery type {config.battery_type!r}; expected one of "
            f"{', '.join(BATTERY_TYPE_OPTIONS)}"
        )

    available = programs_for(config.battery_type)
    if config.program not in available:
        raise ProgramError(
            f"Program {config.program!r} is not available for "
            f"{config.battery_type!r}; expected one of {', '.join(available)}"
        )

    cells = cell_limit(config.battery_type)
    if not cells.min <= config.cell_count <= cells.max:
        raise ProgramError(
            f"Cell count {config.cell_count} is outside {cells.min}-{cells.max} "
            f"for {config.battery_type!r}"
        )

    for name, limit in limits_for(config.battery_type, config.program).items():
        value = getattr(config, name)
        if not limit.min <= value <= limit.max:
            raise ProgramError(
                f"{name.replace('_', ' ').capitalize()} {value} is outside "
                f"{limit.min}-{limit.max} for {config.battery_type} "
                f"{config.program}"
            )
