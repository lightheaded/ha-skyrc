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
    BATTERY_CHEMISTRY,
    BATTERY_TYPE_NAMES,
    CHARGE_PROGRAMS,
    CHEM_NICKEL,
    CMD_QUERY_BASIC_INFO,
    CMD_QUERY_CHANNEL_STATUS,
    CMD_QUERY_SYSTEM_INFO,
    CMD_SET_SYSTEM_INFO,
    CMD_START_CHARGE,
    CMD_STOP_CHARGE,
    DEFAULT_PASSWORD,
    DISCHARGE_PROGRAMS,
    FRAME_START,
    INVALID_U16,
    MASK_TO_CHANNEL,
    POWER_STEP_W,
    PROGRAM_CYCLE,
    PROGRAM_NAMES,
    PROGRAM_RE_PEAK,
    PROGRAM_STORAGE,
    SETTING_CAPACITY,
    SETTING_MAX_INPUT_POWER,
    SETTING_MIN_INPUT_VOLTAGE,
    SETTING_SAFETY_TIMER,
    SETTING_SOUND,
    SETTINGS_MASK,
    STATE_CHARGING,
    STATE_DISCHARGING,
    STATE_DONE,
    STATE_ERROR,
    STATE_NAMES,
    STATE_WORKING,
)
from .programs import (
    BATTERY_TYPE_CODES,
    CHARGE_CURRENT,
    CHARGE_VOLTAGE,
    DISCHARGE_CURRENT,
    DISCHARGE_VOLTAGE,
    PROGRAM_CODES,
    TRACK_VOLTAGE,
    ProgramConfig,
    chemistry_of,
)

# Plausible per-cell voltage window (mV): NiMH ~1.0 V up to LiPo ~4.3 V.
CELL_MV_MIN = 500
CELL_MV_MAX = 5000

# How far the pack voltage has to move, in mV across the whole pack, before a
# channel running a both-ways program is called charging or discharging. The
# charger reports whole millivolts and its readings are steady to a few of them
# between polls, so this is above the noise while still resolving a slow
# storage discharge within a poll or two.
DIRECTION_THRESHOLD_MV = 10

# How far from the storage setpoint a pack has to sit, per cell, before the
# direction of a storage run this integration started is called before the
# voltage has had time to move.
STORAGE_MARGIN_MV_PER_CELL = 20


def build_command(command: int, args: bytes = b"") -> bytes:
    """Build a request frame for ``command`` with optional ``args``."""
    payload = bytes([command]) + args
    length = len(payload) + 1
    checksum = sum(payload) & 0xFF
    return bytes([FRAME_START, length]) + payload + bytes([checksum])


def build_channel_query(mask: int) -> bytes:
    """Build a QUERY_CHANNEL_STATUS frame for the given channel ``mask``."""
    return build_command(CMD_QUERY_CHANNEL_STATUS, bytes([mask]))


def build_basic_info_query(mask: int, password: str = DEFAULT_PASSWORD) -> bytes:
    """Build a QUERY_BASIC_INFO frame for the given channel ``mask``.

    The four password digits are sent as separate bytes, as the SkyCharger app
    does; they are ignored by chargers with no channel password set.
    """
    digits = bytes(int(d) for d in password[:4])
    return build_command(CMD_QUERY_BASIC_INFO, bytes([mask]) + digits)


def build_stop_charge(mask: int) -> bytes:
    """Build a STOP_CHARGE frame for the given channel ``mask``."""
    return build_command(CMD_STOP_CHARGE, bytes([mask]))


def build_start_charge(mask: int, config: ProgramConfig) -> bytes:
    """Build a START_CHARGE frame running ``config`` on channel ``mask``.

    ``config`` is expected to have been validated already (see
    :func:`.programs.validate`) — the charger does not range-check what it is
    sent. Parameters the program does not use are sent as zero, which is what
    the SkyCharger app ends up doing for them.
    """
    chemistry = chemistry_of(config.battery_type)

    def used(parameter: str) -> int:
        return getattr(config, parameter) if config.uses(parameter) else 0

    # Storage runs to a single target voltage; the app sends it as both
    # setpoints, and the program takes no separate charge voltage.
    charge_mv = (
        config.discharge_voltage
        if config.program == PROGRAM_STORAGE
        else used(CHARGE_VOLTAGE)
    )

    args = bytearray(16)
    args[0] = mask
    args[1] = BATTERY_TYPE_CODES[config.battery_type]
    args[2] = config.cell_count
    args[3] = PROGRAM_CODES[chemistry][config.program]
    args[4] = (used(CHARGE_CURRENT) // 100) & 0xFF
    args[5] = (used(DISCHARGE_CURRENT) // 100) & 0xFF
    args[6:8] = used(DISCHARGE_VOLTAGE).to_bytes(2, "big")
    args[8:10] = charge_mv.to_bytes(2, "big")
    if chemistry == CHEM_NICKEL:
        if config.program == PROGRAM_RE_PEAK:
            args[10] = config.repeak_number
        elif config.program == PROGRAM_CYCLE:
            args[10] = config.cycle_model
            args[11] = config.cycle_number
    args[12:14] = used(TRACK_VOLTAGE).to_bytes(2, "big")
    # args[14:16] carry the high bytes of the currents on the D200NEX only.
    return build_command(CMD_START_CHARGE, bytes(args))


def parse_ack(data: bytes) -> tuple[int, int] | None:
    """Parse a START_CHARGE/STOP_CHARGE reply into ``(mask, result)``.

    The charger echoes the channel mask it acted on, then one result byte:
    ``0x01`` for STOP_CHARGE and ``0x00`` for START_CHARGE on a live Q200neo,
    including for programs it went on to refuse. The result byte is therefore
    not a success flag — the channel status is what tells you what happened.
    """
    if len(data) < 2:
        return None
    return data[0], data[1]


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
    # From the channel's basic info (QUERY_BASIC_INFO), when available.
    battery_type: str | None = None
    program: str | None = None
    # Which way the pack voltage is moving, for the programs whose name does
    # not say (see :class:`DirectionTracker`).
    direction: str | None = None

    @property
    def is_done(self) -> bool:
        return self.state == STATE_DONE

    @property
    def is_error(self) -> bool:
        return self.state == STATE_ERROR

    @property
    def detailed_state(self) -> str:
        """State name refined with the charge/discharge direction.

        The charger reports one "working" state for both directions. For most
        programs the program name says which it is; for the ones that can run
        either way (storage, cycle) — and when the program is not known at all
        — the direction the pack voltage is moving does, once it has moved far
        enough to be sure. Until then the state stays "working".
        """
        if self.state != STATE_WORKING:
            return self.state_name
        if self.program in DISCHARGE_PROGRAMS:
            return STATE_DISCHARGING
        if self.program in CHARGE_PROGRAMS:
            return STATE_CHARGING
        return self.direction or self.state_name


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


class DirectionTracker:
    """Tells charging from discharging by watching the pack voltage.

    The storage and cycle programs charge *or* discharge depending on where the
    pack starts, and nothing in either the channel status or the basic info
    says which one is happening. The voltage does: it rises on a charge and
    falls on a discharge. Movement is measured against an anchor rather than
    the previous poll, so a slow storage discharge that moves a millivolt at a
    time still adds up to a verdict instead of being lost in the deadband.
    """

    def __init__(self) -> None:
        self._anchor: dict[str, int] = {}
        self._direction: dict[str, str] = {}

    def reset(self, channel: str) -> None:
        """Forget a channel — it went idle, or started a different run."""
        self._anchor.pop(channel, None)
        self._direction.pop(channel, None)

    def seed(self, channel: str, direction: str | None) -> None:
        """Set the direction a run is expected to take before it shows."""
        self.reset(channel)
        if direction is not None:
            self._direction[channel] = direction

    def update(self, status: ChannelStatus) -> str | None:
        """Fold ``status`` into what is known about its channel's direction."""
        channel = status.channel
        if status.state != STATE_WORKING or status.voltage_mv is None:
            self.reset(channel)
            return None

        anchor = self._anchor.get(channel)
        if anchor is None:
            self._anchor[channel] = status.voltage_mv
        elif abs(delta := status.voltage_mv - anchor) >= DIRECTION_THRESHOLD_MV:
            self._anchor[channel] = status.voltage_mv
            self._direction[channel] = (
                STATE_CHARGING if delta > 0 else STATE_DISCHARGING
            )
        return self._direction.get(channel)


def expected_direction(config: ProgramConfig, voltage_mv: int | None) -> str | None:
    """Which way a storage run will go, from the voltage the pack starts at.

    Only for programs this integration started itself: it is the one case where
    the setpoint is known exactly. A pack sitting within a cell or two of the
    setpoint could go either way, so it gets no verdict — the voltage will say
    soon enough.
    """
    if config.program != PROGRAM_STORAGE or not voltage_mv or not config.cell_count:
        return None
    target = config.discharge_voltage * config.cell_count
    margin = STORAGE_MARGIN_MV_PER_CELL * config.cell_count
    if voltage_mv <= target - margin:
        return STATE_CHARGING
    if voltage_mv >= target + margin:
        return STATE_DISCHARGING
    return None


@dataclass
class ChannelBasicInfo:
    """Parsed per-channel basic info (``parseBasicInfo``).

    Carries the configured battery type and program — the only place the
    protocol says whether a working channel is charging or discharging.
    """

    mask: int
    channel: str
    state: int
    battery_type: str | None = None
    chemistry: str | None = None
    cell_count: int | None = None
    program: str | None = None
    passcode_accepted: bool = True
    raw: str = ""


def parse_basic_info(data: bytes) -> ChannelBasicInfo | None:
    """Parse a QUERY_BASIC_INFO payload (bytes after the command echo)."""
    if len(data) < 10:
        return None

    mask = data[0]
    battery_code = data[2]
    chemistry = BATTERY_CHEMISTRY.get(battery_code)
    program_code = data[4]

    return ChannelBasicInfo(
        mask=mask,
        channel=MASK_TO_CHANNEL.get(mask, f"0x{mask:02X}"),
        state=data[1],
        battery_type=BATTERY_TYPE_NAMES.get(battery_code),
        chemistry=chemistry,
        cell_count=data[3],
        program=PROGRAM_NAMES.get(chemistry, {}).get(program_code)
        if chemistry
        else None,
        # d[9] is the charger's verdict on the passcode digits sent with the
        # query: 1 when they are accepted, 0 when they are not. Proven on a
        # Q200neo — it read 0 for three different wrong codes and 1 for the
        # right one, on all four channels.
        passcode_accepted=data[9] == 1,
        raw=data.hex(),
    )


# --- charger settings (QUERY_SYSTEM_INFO / SET_SYSTEM_INFO) ---------------


def build_system_info_query(mask: int = SETTINGS_MASK) -> bytes:
    """Build a QUERY_SYSTEM_INFO frame."""
    return build_command(CMD_QUERY_SYSTEM_INFO, bytes([mask]))


def _build_setting(setting: int, b1: int, b2: int = 0, b3: int = 0) -> bytes:
    return build_command(
        CMD_SET_SYSTEM_INFO, bytes([SETTINGS_MASK, setting, b1, b2, b3])
    )


def build_set_safety_timer(enabled: bool, minutes: int) -> bytes:
    """Stop a run after ``minutes``; the charger's Task Parameters ▸ Safety Timer."""
    return _build_setting(
        SETTING_SAFETY_TIMER, 1 if enabled else 0, *divmod(minutes, 0x100)
    )


def build_set_capacity_limit(enabled: bool, capacity_mah: int) -> bytes:
    """Stop a run after ``capacity_mah``; Task Parameters ▸ Max. Capacity."""
    return _build_setting(
        SETTING_CAPACITY, 1 if enabled else 0, *divmod(capacity_mah, 0x100)
    )


def build_set_min_input_voltage(millivolts: int) -> bytes:
    """Refuse to run below this input voltage; System Settings ▸ Min. Input Voltage."""
    return _build_setting(SETTING_MIN_INPUT_VOLTAGE, *divmod(millivolts, 0x100))


def build_set_max_input_power(watts: int) -> bytes:
    """Cap total charge power; System Settings ▸ Max. Input Power."""
    return _build_setting(SETTING_MAX_INPUT_POWER, watts // POWER_STEP_W)


def build_set_sounds(beep_volume: int, completion_beep: bool) -> bytes:
    """Set both beep bytes; System Settings ▸ Volume and Completion Signal."""
    return _build_setting(SETTING_SOUND, beep_volume, 1 if completion_beep else 0)


@dataclass
class ChargerSettings:
    """The charger's own settings, as reported by QUERY_SYSTEM_INFO.

    Global, not per channel: writing one on channel A changes what every
    channel reports.
    """

    safety_timer_enabled: bool
    safety_timer_minutes: int
    capacity_limit_enabled: bool
    capacity_limit_mah: int
    beep_volume: int
    completion_beep: bool
    min_input_voltage_mv: int
    max_input_power_w: int
    raw: str = ""


def parse_system_info(data: bytes) -> ChargerSettings | None:
    """Parse a QUERY_SYSTEM_INFO payload (bytes after the command echo).

    Offsets were mapped by writing one setting at a time and diffing the
    payload, then cross-checked against the charger's own menus. Offsets past
    d[14] are not decoded: this firmware returns a payload too short for the
    fields the reference app reads there.
    """
    if len(data) < 15:
        return None

    return ChargerSettings(
        safety_timer_enabled=data[2] == 1,
        safety_timer_minutes=(data[3] << 8) | data[4],
        capacity_limit_enabled=data[5] == 1,
        capacity_limit_mah=(data[6] << 8) | data[7],
        beep_volume=data[8],
        completion_beep=data[9] != 0,
        min_input_voltage_mv=(data[10] << 8) | data[11],
        max_input_power_w=data[13] * POWER_STEP_W,
        raw=data.hex(),
    )
