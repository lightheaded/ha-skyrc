"""Unit tests for the SkyRC frame parser (no Home Assistant required).

``protocol`` and ``const`` are pure Python; we load them via a lightweight stub
package so the tests don't drag in the HA-dependent ``__init__``.
"""

import importlib.util
import os
import sys
import types

_COMP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components",
    "skyrc",
)
_pkg = types.ModuleType("_skyrc")
_pkg.__path__ = [_COMP]
sys.modules["_skyrc"] = _pkg
for _name in ("const", "programs", "protocol"):
    _spec = importlib.util.spec_from_file_location(
        f"_skyrc.{_name}", os.path.join(_COMP, f"{_name}.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"_skyrc.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

programs = sys.modules["_skyrc.programs"]
protocol = sys.modules["_skyrc.protocol"]
ProgramConfig = programs.ProgramConfig
FrameReader = protocol.FrameReader
build_basic_info_query = protocol.build_basic_info_query
build_channel_query = protocol.build_channel_query
build_command = protocol.build_command
parse_basic_info = protocol.parse_basic_info
parse_channel_status = protocol.parse_channel_status
build_start_charge = protocol.build_start_charge
build_set_safety_timer = protocol.build_set_safety_timer
build_set_capacity_limit = protocol.build_set_capacity_limit
build_set_min_input_voltage = protocol.build_set_min_input_voltage
build_set_max_input_power = protocol.build_set_max_input_power
build_set_sounds = protocol.build_set_sounds
parse_system_info = protocol.parse_system_info
build_stop_charge = protocol.build_stop_charge
parse_ack = protocol.parse_ack


def _status_frame(data: bytes) -> bytes:
    """Wrap channel-status payload bytes in a full 0x55 response frame."""
    return build_command(0x55, data)


def test_build_channel_query_matches_reference():
    # Reference example from the protocol handoff: query channel A.
    assert build_channel_query(0x01) == bytes.fromhex("0F035501 56".replace(" ", ""))


def test_parse_done_channel():
    data = bytes(
        [
            0x01,  # mask A
            0x03,  # DONE
            0x05, 0xDC,  # capacity 1500 mAh
            0x0E, 0x10,  # duration 3600
            0x20, 0xD0,  # voltage 8400 mV
            0x00, 0x00,  # current 0 mA
            25,  # battery temp
            30,  # internal temp
            0x00, 0x32,  # resistance 50
            0x10, 0x68,  # cell 1 = 4200 mV
            0x10, 0x68,  # cell 2 = 4200 mV
            0x00, 0x00,  # cell 3 (empty)
            0x00, 0x00,  # cell 4 (empty)
            0x00, 0x00,  # cell 5 (empty)
            0x00, 0x00,  # cell 6 (empty)
        ]
    )
    frame = _status_frame(data)
    frames = FrameReader().feed(frame)
    assert len(frames) == 1
    status = parse_channel_status(frames[0].data)
    assert status is not None
    assert status.channel == "A"
    assert status.is_done
    assert status.capacity_mah == 1500
    assert status.duration_s == 3600
    assert status.voltage_mv == 8400
    assert status.current_ma == 0
    assert status.battery_temp_c == 25
    assert status.internal_temp_c == 30
    assert status.cell_voltages_mv == [4200, 4200]


def test_invalid_sentinels_become_none():
    data = bytes([0x02, 0x02, 0xFF, 0xFF, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])
    status = parse_channel_status(data)
    assert status is not None
    assert status.channel == "B"
    assert status.capacity_mah is None
    assert status.voltage_mv is None
    assert status.current_ma is None


def test_error_state_carries_error_codes():
    data = bytes([0x04, 0x04, 0x02, 0x07, 0x00, 0x00])
    status = parse_channel_status(data)
    assert status is not None
    assert status.is_error
    assert status.system_error == 0x02
    assert status.charge_error == 0x07


def test_fragmented_notifications_reassemble():
    frame = _status_frame(bytes([0x08, 0x02, 0x00, 0x00]))
    reader = FrameReader()
    assert reader.feed(frame[:2]) == []
    frames = reader.feed(frame[2:])
    assert len(frames) == 1
    assert parse_channel_status(frames[0].data).channel == "D"


def test_two_frames_in_one_chunk():
    a = _status_frame(bytes([0x01, 0x02, 0x00, 0x00]))
    b = _status_frame(bytes([0x02, 0x03, 0x00, 0x00]))
    frames = FrameReader().feed(a + b)
    assert [f.data[0] for f in frames] == [0x01, 0x02]


def test_live_frame_channel_c_done():
    # Captured from a real Q200neo: channel C, 2S pack, charge complete.
    data = bytes.fromhex(
        "04030155052820bc0005001f0000105b105f0000000000090009000000000100"
    )
    status = parse_channel_status(data)
    assert status.channel == "C"
    assert status.is_done
    assert status.voltage_mv == 8380
    assert status.current_ma == 5
    assert status.internal_temp_c == 31
    assert status.battery_temp_c is None  # no external probe attached
    assert status.cell_voltages_mv == [4187, 4191]  # noise bytes filtered out


def _basic_info(
    mask=0x01, state=0x01, battery_type=0x00, cells=3, program=0x00, password=0
):
    return bytes(
        [
            mask,
            state,
            battery_type,
            cells,
            program,
            0x14,  # charge max 2000 mA
            0x0A,  # discharge max 1000 mA
            0x01,  # version major
            0x23,  # version minor
            password,
        ]
    )


def test_build_basic_info_query_sends_password_digits():
    # 0x5F, channel A, password "0000"; checksum = 0x5F + 0x01.
    assert build_basic_info_query(0x01) == bytes.fromhex("0F075F010000000060")


def test_parse_basic_info_lithium_discharge():
    info = parse_basic_info(_basic_info(battery_type=0x00, program=0x02))
    assert info is not None
    assert info.channel == "A"
    assert info.battery_type == "lipo"
    assert info.chemistry == "lithium"
    assert info.cell_count == 3
    assert info.program == "discharge"
    assert info.password_required is False


def test_parse_basic_info_nickel_program_codes_differ():
    # 0x04 is "cycle" for nickel but "fast charge" for lithium.
    nickel = parse_basic_info(_basic_info(battery_type=0x04, program=0x04))
    lithium = parse_basic_info(_basic_info(battery_type=0x00, program=0x04))
    assert nickel.battery_type == "nimh"
    assert nickel.program == "cycle"
    assert lithium.program == "fast_charge"


def test_parse_basic_info_unknown_battery_type():
    info = parse_basic_info(_basic_info(battery_type=0x7F, program=0x02))
    assert info.battery_type is None
    assert info.program is None  # program codes are meaningless without chemistry


def test_parse_basic_info_password_flag_and_short_payload():
    assert parse_basic_info(_basic_info(password=1)).password_required is True
    assert parse_basic_info(_basic_info()[:9]) is None


def _working_status(program=None):
    status = parse_channel_status(bytes([0x01, 0x01, 0x00, 0x00, 0x00, 0x00]))
    status.program = program
    return status


def test_detailed_state_splits_working_by_program():
    assert _working_status("balance_charge").detailed_state == "charging"
    assert _working_status("fast_charge").detailed_state == "charging"
    assert _working_status("discharge").detailed_state == "discharging"


def test_detailed_state_falls_back_when_direction_is_ambiguous():
    # Storage and cycle run either way; an unread program is unknown.
    assert _working_status("storage").detailed_state == "working"
    assert _working_status("cycle").detailed_state == "working"
    assert _working_status(None).detailed_state == "working"


def test_detailed_state_only_refines_the_working_state():
    status = parse_channel_status(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x00]))
    status.program = "discharge"
    assert status.detailed_state == "done"


def test_bad_checksum_dropped():
    frame = bytearray(_status_frame(bytes([0x01, 0x02, 0x00, 0x00])))
    frame[-1] ^= 0xFF  # corrupt checksum
    assert FrameReader().feed(bytes(frame)) == []


# --- control frames -------------------------------------------------------
#
# The frames asserted here were checked against a live Q200neo: the charger
# acknowledged them and its basic-info reply echoed back the battery type, cell
# count, program and current limit that had been sent.


def _decode_args(frame: bytes) -> bytes:
    """Strip header, command and checksum off a request frame."""
    assert frame[0] == 0x0F
    # len counts the payload (command + args) plus one.
    assert frame[1] == len(frame) - 2
    payload = frame[2:-1]
    assert frame[-1] == sum(payload) & 0xFF
    return payload[1:]


def test_build_stop_charge_matches_device():
    # Acknowledged by a live Q200neo with "01 01".
    assert build_stop_charge(0x01) == bytes([0x0F, 0x03, 0xFE, 0x01, 0xFF])
    assert build_stop_charge(0x08) == bytes([0x0F, 0x03, 0xFE, 0x08, 0x06])


def test_build_start_charge_lithium_charge():
    frame = build_start_charge(
        0x01,
        ProgramConfig(
            battery_type="lipo",
            program="charge",
            cell_count=3,
            charge_current=2500,
            charge_voltage=4200,
        ),
    )
    assert frame[2] == 0x05
    args = _decode_args(frame)
    assert len(args) == 16
    assert args[0] == 0x01  # channel mask
    assert args[1] == 0x00  # LiPo
    assert args[2] == 3  # cells
    assert args[3] == 0x01  # charge program
    assert args[4] == 25  # 2500 mA / 100
    assert args[8:10] == (4200).to_bytes(2, "big")
    # A plain charge takes no discharge parameters.
    assert args[5] == 0
    assert args[6:8] == b"\x00\x00"
    assert args[10:16] == bytes(6)


def test_build_start_charge_storage_sends_one_target_twice():
    """Storage runs to a single voltage, sent as both setpoints."""
    frame = build_start_charge(
        0x02,
        ProgramConfig(
            battery_type="liion",
            program="storage",
            cell_count=6,
            charge_current=5000,
            discharge_current=2000,
            charge_voltage=4100,
            discharge_voltage=3800,
        ),
    )
    args = _decode_args(frame)
    assert args[1] == 0x01  # Li-ion
    assert args[3] == 0x03  # storage
    assert args[4] == 50
    assert args[5] == 20
    assert args[6:8] == (3800).to_bytes(2, "big")
    assert args[8:10] == (3800).to_bytes(2, "big")


def test_build_start_charge_nickel_cycle():
    frame = build_start_charge(
        0x04,
        ProgramConfig(
            battery_type="nimh",
            program="cycle",
            cell_count=8,
            charge_current=2000,
            discharge_current=1000,
            cycle_model=1,
            cycle_number=3,
            track_voltage=60,
        ),
    )
    args = _decode_args(frame)
    assert args[1] == 0x04  # NiMH
    assert args[3] == 0x04  # cycle
    assert args[2] == 8
    assert args[10] == 1  # discharge first
    assert args[11] == 3  # three cycles
    assert args[12:14] == (60).to_bytes(2, "big")


def test_build_start_charge_nickel_re_peak():
    frame = build_start_charge(
        0x08,
        ProgramConfig(
            battery_type="nicd",
            program="re_peak",
            cell_count=4,
            charge_current=3000,
            repeak_number=1,
            track_voltage=60,
        ),
    )
    args = _decode_args(frame)
    assert args[3] == 0x03  # re-peak
    assert args[10] == 1  # repeak count
    assert args[11] == 0
    assert args[12:14] == (60).to_bytes(2, "big")


def test_build_start_charge_lead_acid_discharge():
    frame = build_start_charge(
        0x01,
        ProgramConfig(
            battery_type="pb",
            program="discharge",
            cell_count=6,
            discharge_current=1000,
            discharge_voltage=1900,
        ),
    )
    args = _decode_args(frame)
    assert args[1] == 0x06  # Pb
    assert args[3] == 0x01  # lead acid discharge
    assert args[4] == 0  # no charge current
    assert args[5] == 10
    assert args[6:8] == (1900).to_bytes(2, "big")
    assert args[8:10] == b"\x00\x00"


def test_parse_ack():
    # Live replies: stop -> "01 01", start -> "01 00".
    assert parse_ack(bytes([0x01, 0x01])) == (0x01, 0x01)
    assert parse_ack(bytes([0x04, 0x00])) == (0x04, 0x00)
    assert parse_ack(b"\x01") is None


# --- charger settings -----------------------------------------------------
#
# The payload below is a real QUERY_SYSTEM_INFO reply from a Q200neo whose menus
# read: Safety Timer 240 Minute, Max. Capacity 12000 mAh, Min. Input Voltage
# 11.0V, Max. Input Power 200W.
SYSTEM_INFO = bytes.fromhex(
    "010a0100f0012ee00101 2af80014 00 000000080007000000000009000900000000 0000".replace(" ", "")
)


def test_parse_system_info_matches_the_charger_menus():
    settings = parse_system_info(SYSTEM_INFO)
    assert settings is not None
    assert settings.safety_timer_enabled is True
    assert settings.safety_timer_minutes == 240
    assert settings.capacity_limit_enabled is True
    assert settings.capacity_limit_mah == 12000
    assert settings.min_input_voltage_mv == 11000
    assert settings.max_input_power_w == 200
    assert settings.beep_volume == 1
    assert settings.completion_beep is True


def test_parse_system_info_needs_a_full_payload():
    assert parse_system_info(SYSTEM_INFO[:10]) is None


def test_build_set_safety_timer():
    args = _decode_args(build_set_safety_timer(True, 180))
    assert args == bytes([0x01, 0x01, 0x01, 0x00, 180])


def test_build_set_capacity_limit():
    args = _decode_args(build_set_capacity_limit(True, 10000))
    assert args == bytes([0x01, 0x02, 0x01, 0x27, 0x10])


def test_build_set_min_input_voltage():
    args = _decode_args(build_set_min_input_voltage(10500))
    assert args == bytes([0x01, 0x04, 0x29, 0x04, 0x00])


def test_build_set_max_input_power_uses_ten_watt_units():
    args = _decode_args(build_set_max_input_power(200))
    assert args == bytes([0x01, 0x07, 20, 0x00, 0x00])


def test_build_set_sounds_writes_both_bytes():
    args = _decode_args(build_set_sounds(2, False))
    assert args == bytes([0x01, 0x03, 2, 0, 0x00])
