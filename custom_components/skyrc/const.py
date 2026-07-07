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

# Commands (subset used for monitoring).
CMD_QUERY_CHANNEL_STATUS: Final = 0x55
CMD_INFO: Final = 0x57

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
STATE_OPTIONS: Final = list(dict.fromkeys(STATE_NAMES.values())) + ["unknown"]

# States in which a battery is actively being charged/discharged.
ACTIVE_STATES: Final = frozenset({STATE_WORKING})

# Sentinel meaning "value not measured".
INVALID_U16: Final = 0xFFFF

# Polling.
DEFAULT_POLL_INTERVAL: Final = 30  # seconds
