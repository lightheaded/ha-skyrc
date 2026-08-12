"""Unit tests for program limits and validation (no Home Assistant required)."""

import importlib.util
import os
import sys
import types

import pytest

_COMP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components",
    "skyrc",
)
_pkg = types.ModuleType("_skyrc")
_pkg.__path__ = [_COMP]
sys.modules.setdefault("_skyrc", _pkg)
for _name in ("const", "programs"):
    if f"_skyrc.{_name}" in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(
        f"_skyrc.{_name}", os.path.join(_COMP, f"{_name}.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"_skyrc.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

programs = sys.modules["_skyrc.programs"]
Limit = programs.Limit
ProgramConfig = programs.ProgramConfig
ProgramError = programs.ProgramError
validate = programs.validate


def test_limit_clamp_rounds_to_step():
    limit = Limit(100, 10000, 100, 100)
    assert limit.clamp(2540) == 2500
    assert limit.clamp(2560) == 2600
    assert limit.clamp(0) == 100
    assert limit.clamp(99999) == 10000


def test_limit_clamp_respects_offset_minimum():
    """Steps are counted from the minimum, not from zero."""
    limit = Limit(4150, 4250, 10, 4200)
    assert limit.clamp(4203) == 4200
    assert limit.clamp(4206) == 4210
    assert limit.clamp(4100) == 4150


def test_programs_for_battery_type():
    assert programs.programs_for("lipo") == (
        "balance_charge",
        "charge",
        "discharge",
        "storage",
    )
    assert programs.programs_for("nimh") == ("charge", "discharge", "re_peak", "cycle")
    assert programs.programs_for("pb") == ("charge", "discharge")
    assert programs.programs_for("nonsense") == ()


def test_cell_limits_per_chemistry():
    assert programs.cell_limit("lipo").max == 6
    assert programs.cell_limit("nimh").max == 15
    assert programs.cell_limit("pb").max == 10


def test_uses_only_reports_parameters_of_the_program():
    charge = ProgramConfig(battery_type="lipo", program="charge")
    assert charge.uses("charge_current")
    assert charge.uses("charge_voltage")
    assert not charge.uses("discharge_current")
    assert not charge.uses("track_voltage")

    cycle = ProgramConfig(battery_type="nimh", program="cycle")
    assert cycle.uses("cycle_number")
    assert cycle.uses("track_voltage")
    assert not cycle.uses("charge_voltage")


def test_with_defaults_resets_parameters_and_clamps_cells():
    config = ProgramConfig(
        battery_type="lipo",
        program="storage",
        cell_count=12,  # a nickel-sized pack; lithium stops at 6
        charge_current=9000,
        discharge_voltage=3000,
    )
    reset = config.with_defaults()
    assert reset.cell_count == 6
    assert reset.charge_current == 100
    assert reset.discharge_voltage == 3850  # LiPo storage target
    # Parameters the program does not take are left as they were.
    assert reset.charge_voltage == config.charge_voltage


def test_validate_accepts_a_sane_program():
    validate(
        ProgramConfig(
            battery_type="lipo",
            program="balance_charge",
            cell_count=6,
            charge_current=5000,
            charge_voltage=4200,
        ),
        "A",
    )


def test_validate_rejects_unknown_channel():
    with pytest.raises(ProgramError, match="Unknown channel"):
        validate(ProgramConfig(), "E")


def test_validate_rejects_unsupported_battery_type():
    with pytest.raises(ProgramError, match="Unsupported battery type"):
        validate(ProgramConfig(battery_type="pb_agm"), "A")


def test_validate_rejects_program_the_battery_type_lacks():
    with pytest.raises(ProgramError, match="not available"):
        validate(ProgramConfig(battery_type="pb", program="storage"), "A")
    with pytest.raises(ProgramError, match="not available"):
        validate(ProgramConfig(battery_type="lipo", program="cycle"), "A")


def test_validate_rejects_too_many_cells():
    with pytest.raises(ProgramError, match="Cell count 7 is outside 1-6"):
        validate(ProgramConfig(battery_type="lipo", program="charge", cell_count=7), "A")


def test_validate_rejects_out_of_range_charge_voltage():
    """The charger itself accepted 9999 mV per cell, so this must not."""
    with pytest.raises(ProgramError, match="Charge voltage 9999 is outside"):
        validate(
            ProgramConfig(
                battery_type="lipo",
                program="charge",
                cell_count=1,
                charge_current=100,
                charge_voltage=9999,
            ),
            "A",
        )


def test_validate_rejects_charge_current_over_device_maximum():
    with pytest.raises(ProgramError, match="Charge current 12000 is outside"):
        validate(
            ProgramConfig(
                battery_type="lipo", program="charge", charge_current=12000
            ),
            "A",
        )


def test_validate_ignores_parameters_the_program_does_not_use():
    """A leftover discharge current must not block a charge-only program."""
    validate(
        ProgramConfig(
            battery_type="lipo",
            program="charge",
            charge_current=1000,
            charge_voltage=4200,
            discharge_current=99999,
        ),
        "A",
    )
