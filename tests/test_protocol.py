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
for _name in ("const", "protocol"):
    _spec = importlib.util.spec_from_file_location(
        f"_skyrc.{_name}", os.path.join(_COMP, f"{_name}.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"_skyrc.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

protocol = sys.modules["_skyrc.protocol"]
FrameReader = protocol.FrameReader
build_basic_info_query = protocol.build_basic_info_query
build_channel_query = protocol.build_channel_query
build_command = protocol.build_command
parse_basic_info = protocol.parse_basic_info
parse_channel_status = protocol.parse_channel_status


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
