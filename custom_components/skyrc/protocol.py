"""Frame encoding/decoding for the SkyRC neo-series BLE protocol.

Reverse-engineered from the open-source SkyCharger app
(https://github.com/sidhantgoel/SkyCharger). Byte offsets marked "unverified"
below are read directly from that source and confirmed empirically against a
live Q200neo — see PROTOCOL.md.

Frame layout (both directions)::

    [0x0F] [len] [command] [args...] [checksum]

* ``len``      = number of payload bytes (command + args) + 1
* ``payload``  = the ``len - 1`` bytes after ``len`` (payload[0] is the command)
* ``checksum`` = sum(payload) & 0xFF
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import (
    CMD_QUERY_CHANNEL_STATUS,
    FRAME_START,
    INVALID_U16,
    MASK_TO_CHANNEL,
    STATE_DONE,
    STATE_ERROR,
    STATE_NAMES,
)

# Plausible per-cell voltage window (mV): NiMH ~1.0 V up to LiPo ~4.3 V.
CELL_MV_MIN = 500
CELL_MV_MAX = 5000


def build_command(command: int, args: bytes = b"") -> bytes:
    """Build a request frame for ``command`` with optional ``args``."""
    payload = bytes([command]) + args
    length = len(payload) + 1
    checksum = sum(payload) & 0xFF
    return bytes([FRAME_START, length]) + payload + bytes([checksum])


def build_channel_query(mask: int) -> bytes:
    """Build a QUERY_CHANNEL_STATUS frame for the given channel ``mask``."""
    return build_command(CMD_QUERY_CHANNEL_STATUS, bytes([mask]))


@dataclass
class Frame:
    """A decoded protocol frame."""

    command: int
    data: bytes  # payload after the command byte

    @property
    def checksum_ok(self) -> bool:  # pragma: no cover - trivial
        return True  # validated during extraction


class FrameReader:
    """Reassembles frames from a stream of (possibly fragmented) notifications."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, chunk: bytes) -> list[Frame]:
        """Add ``chunk`` to the buffer and return any complete frames."""
        self._buf.extend(chunk)
        frames: list[Frame] = []

        while True:
            # Drop leading garbage until a start byte.
            start = self._buf.find(FRAME_START)
            if start == -1:
                self._buf.clear()
                break
            if start > 0:
                del self._buf[:start]

            if len(self._buf) < 2:
                break  # need the length byte

            length = self._buf[1]
            total = length + 2  # 0x0F + len + (length-1 payload) + checksum
            if len(self._buf) < total:
                break  # incomplete — wait for more

            payload = bytes(self._buf[2 : 2 + length - 1])
            checksum = self._buf[total - 1]
            del self._buf[:total]

            if (sum(payload) & 0xFF) != checksum or not payload:
                # Bad frame; resync past this start byte.
                continue

            frames.append(Frame(command=payload[0], data=payload[1:]))

        return frames


def _u16(data: bytes, offset: int) -> int | None:
    """Big-endian u16 at ``offset``; ``None`` if out of range or sentinel."""
    if offset + 1 >= len(data):
        return None
    value = (data[offset] << 8) | data[offset + 1]
    return None if value == INVALID_U16 else value


def _u8(data: bytes, offset: int) -> int | None:
    if offset >= len(data):
        return None
    return data[offset]


def _s8(value: int | None) -> int | None:
    """Interpret a byte as a signed temperature."""
    if value is None:
        return None
    return value - 256 if value > 127 else value


@dataclass
class ChannelStatus:
    """Parsed per-channel working info (``parseChannelWorkingInfo``)."""

    mask: int
    channel: str
    state: int
    state_name: str
    capacity_mah: int | None = None
    duration_s: int | None = None
    voltage_mv: int | None = None
    current_ma: int | None = None
    battery_temp_c: int | None = None
    internal_temp_c: int | None = None
    resistance_mohm: int | None = None
    cell_voltages_mv: list[int] = field(default_factory=list)
    system_error: int | None = None
    charge_error: int | None = None
    raw: str = ""

    @property
    def is_done(self) -> bool:
        return self.state == STATE_DONE

    @property
    def is_error(self) -> bool:
        return self.state == STATE_ERROR


def parse_channel_status(data: bytes) -> ChannelStatus | None:
    """Parse a QUERY_CHANNEL_STATUS payload (bytes after the command echo).

    ``data`` corresponds to ``d[...]`` in the reference implementation.
    """
    if len(data) < 2:
        return None

    mask = data[0]
    state = data[1]
    status = ChannelStatus(
        mask=mask,
        channel=MASK_TO_CHANNEL.get(mask, f"0x{mask:02X}"),
        state=state,
        state_name=STATE_NAMES.get(state, "unknown"),
        raw=data.hex(),
    )

    if state == STATE_ERROR:
        status.system_error = _u8(data, 2)
        status.charge_error = _u8(data, 3)
    else:
        status.capacity_mah = _u16(data, 2)

    status.duration_s = _u16(data, 4)
    status.voltage_mv = _u16(data, 6)
    status.current_ma = _u16(data, 8)
    # Battery (external) probe reports 0 when no probe is attached.
    batt = _u8(data, 10)
    status.battery_temp_c = None if batt in (None, 0) else _s8(batt)
    status.internal_temp_c = _s8(_u8(data, 11))
    status.resistance_mohm = _u16(data, 12)

    # Cell voltages 1–6 at d[14..25], plus 7–8 at d[26..29] on longer payloads.
    # Only plausible single-cell readings are kept; empty slots report 0 and
    # some trailing bytes carry small non-cell values.
    cells: list[int] = []
    for offset in range(14, 30, 2):
        value = _u16(data, offset)
        if value is None:
            break
        if CELL_MV_MIN <= value <= CELL_MV_MAX:
            cells.append(value)
    status.cell_voltages_mv = cells

    return status
