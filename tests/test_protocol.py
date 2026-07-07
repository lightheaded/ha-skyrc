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
build_channel_query = protocol.build_channel_query
build_command = protocol.build_command
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


def test_bad_checksum_dropped():
    frame = bytearray(_status_frame(bytes([0x01, 0x02, 0x00, 0x00])))
    frame[-1] ^= 0xFF  # corrupt checksum
    assert FrameReader().feed(bytes(frame)) == []
