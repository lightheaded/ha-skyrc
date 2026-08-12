"""Constants for the SkyRC Q200neo integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "skyrc"

MANUFACTURER: Final = "SkyRC"
MODEL: Final = "Q200neo"

# Default advertised name prefix (user-renameable in the SkyCharger app).
NAME_PREFIX: Final = "#Charger-"

# GATT — shared across the SkyRC neo/MC series.
SERVICE_UUID: Final = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID: Final = "0000ffe1-0000-1000-8000-00805f9b34fb"

# Frame protocol.
FRAME_START: Final = 0x0F

# Commands.
CMD_START_CHARGE: Final = 0x05
CMD_QUERY_CHANNEL_STATUS: Final = 0x55
CMD_INFO: Final = 0x57
CMD_QUERY_BASIC_INFO: Final = 0x5F
CMD_STOP_CHARGE: Final = 0xFE

# Channel password digits sent with QUERY_BASIC_INFO. "0000" is the factory
# default and the value the SkyCharger app starts from.
DEFAULT_PASSWORD: Final = "0000"

# Config entry options.
CONF_PASSCODE: Final = "passcode"
CONF_POLL_PROGRAM: Final = "poll_program"

# Services.
SERVICE_START_PROGRAM: Final = "start_program"

# Channels A–D and their bit masks.
CHANNELS: Final = ("A", "B", "C", "D")
CHANNEL_MASKS: Final = {"A": 0x01, "B": 0x02, "C": 0x04, "D": 0x08}
MASK_TO_CHANNEL: Final = {v: k for k, v in CHANNEL_MASKS.items()}

# Working-state byte (d[1] of the channel status payload).
STATE_WORKING: Final = 0x01
STATE_IDLE: Final = 0x02
STATE_DONE: Final = 0x03
STATE_ERROR: Final = 0x04
STATE_READY: Final = 0x05
STATE_STATE6: Final = 0x06
STATE_DC_SUPPLY: Final = 0x07

# Enum sensor option strings (also the keys used in translations).
STATE_NAMES: Final[dict[int, str]] = {
    STATE_WORKING: "working",
    STATE_IDLE: "idle",
    STATE_DONE: "done",
    STATE_ERROR: "error",
    STATE_READY: "ready",
    STATE_STATE6: "standby",
    STATE_DC_SUPPLY: "dc_power",
}

# Derived states: the charger reports a single "working" state, so the
# charge/discharge direction comes from the channel's program (see below).
STATE_CHARGING: Final = "charging"
STATE_DISCHARGING: Final = "discharging"

STATE_OPTIONS: Final = list(dict.fromkeys(STATE_NAMES.values())) + [
    STATE_CHARGING,
    STATE_DISCHARGING,
    "unknown",
]

# --- QUERY_BASIC_INFO (0x5F) ---------------------------------------------

CHEM_LITHIUM: Final = "lithium"
CHEM_NICKEL: Final = "nickel"
CHEM_LEAD: Final = "lead"

# Battery type (d[2]) → name / chemistry.
BATTERY_TYPE_NAMES: Final[dict[int, str]] = {
    0x00: "lipo",
    0x01: "liion",
    0x02: "life",
    0x03: "lihv",
    0x04: "nimh",
    0x05: "nicd",
    0x06: "pb",
    0x07: "pb_agm",
}
BATTERY_CHEMISTRY: Final[dict[int, str]] = {
    0x00: CHEM_LITHIUM,
    0x01: CHEM_LITHIUM,
    0x02: CHEM_LITHIUM,
    0x03: CHEM_LITHIUM,
    0x04: CHEM_NICKEL,
    0x05: CHEM_NICKEL,
    0x06: CHEM_LEAD,
    0x07: CHEM_LEAD,
}

# Programs that need special handling when a START_CHARGE frame is built.
PROGRAM_STORAGE: Final = "storage"
PROGRAM_RE_PEAK: Final = "re_peak"
PROGRAM_CYCLE: Final = "cycle"

# Program byte (d[4]) → operation mode. The codes are reused per chemistry.
PROGRAM_NAMES: Final[dict[str, dict[int, str]]] = {
    CHEM_LITHIUM: {
        0x00: "balance_charge",
        0x01: "charge",
        0x02: "discharge",
        0x03: "storage",
        0x04: "fast_charge",
    },
    CHEM_NICKEL: {
        0x00: "charge",
        0x01: "auto_charge",
        0x02: "discharge",
        0x03: "re_peak",
        0x04: "cycle",
    },
    CHEM_LEAD: {
        0x00: "charge",
        0x01: "discharge",
    },
}

# Programs whose direction is unambiguous. "storage" and "cycle" charge *or*
# discharge depending on where the pack starts, so they stay plain "working".
CHARGE_PROGRAMS: Final = frozenset(
    {"balance_charge", "charge", "fast_charge", "auto_charge", "re_peak"}
)
DISCHARGE_PROGRAMS: Final = frozenset({"discharge"})

# Sentinel meaning "value not measured".
INVALID_U16: Final = 0xFFFF

# Polling.
DEFAULT_POLL_INTERVAL: Final = 30  # seconds
