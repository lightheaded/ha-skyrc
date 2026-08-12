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

from dataclasses import dataclass, replace
from typing import Final, NamedTuple

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
