# SkyRC Charger — Home Assistant integration

[![Validate](https://github.com/lightheaded/ha-skyrc/actions/workflows/validate.yml/badge.svg)](https://github.com/lightheaded/ha-skyrc/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

An **unofficial** custom integration that monitors [SkyRC](https://www.skyrc.com/)
smart chargers over Bluetooth Low Energy and exposes each channel's state as
Home Assistant entities — so you can get a push notification the moment a battery
finishes charging.

### Supported chargers

| Model | Status |
|---|---|
| Q200neo (product code `100197`) | ✅ Tested |
| Other SkyRC "neo"-series chargers | ⚠️ May work (same BLE protocol) — reports welcome |

The neo-series BLE protocol is shared across models; the domain is generic
(`skyrc`) so additional models can be added without breaking existing entities.

> Not affiliated with or endorsed by SkyRC. The BLE protocol was reverse
> engineered; see [PROTOCOL.md](PROTOCOL.md). Use at your own risk.

> 🤖 **Built entirely by [Claude Opus 4.8](https://www.anthropic.com/claude)** —
> the protocol port, integration code, tests, and on-hardware validation against
> a live Q200neo were all done by the AI, end to end. Review the code before
> trusting it near your batteries.

## Features

- Auto-discovery of the charger over Bluetooth (advertises as `#Charger-XXXX`)
- Works with a local Bluetooth adapter **or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)** — the charger doesn't need to be near the HA host
- Per-channel (A–D) entities:
  - **Status** (`working` / `idle` / `done` / `error` / `ready` / `standby` / `dc_power`)
  - **Charging** binary sensor
  - Capacity (mAh), Voltage (V), Current (A), Battery temperature (°C)
  - Duration (disabled by default)
- Charger internal temperature (diagnostic)
- Connect → poll → disconnect cycle that leaves the single BLE slot free for the SkyCharger phone app between polls

### Example

<img width="760" height="1146" alt="Screenshot 2026-07-07 at 10 22 12" src="https://github.com/user-attachments/assets/60a948e8-1b09-4898-bfe9-59b04fbbe7ce" />

## Requirements

- Home Assistant **2024.12** or newer
- A Bluetooth adapter or ESPHome Bluetooth proxy within range of the charger
- The charger's channel **password disabled** in the SkyCharger app (see [PROTOCOL.md](PROTOCOL.md))

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/lightheaded/ha-skyrc`, category **Integration**
3. Install **SkyRC Charger**, then restart Home Assistant

### Manual

Copy `custom_components/skyrc` into your HA `config/custom_components/`
directory and restart Home Assistant.

## Setup

The charger is usually auto-discovered: **Settings → Devices & Services →
Discovered**. Otherwise add it via **+ Add Integration → SkyRC Charger**
and pick it from the list of chargers in range.

## Notify when charging finishes

The integration deliberately ships **no** notification logic — wire it up with a
plain automation:

```yaml
alias: Notify when a battery finishes charging
triggers:
  - trigger: state
    entity_id:
      - sensor.charger_8f12_channel_a_status
      - sensor.charger_8f12_channel_b_status
      - sensor.charger_8f12_channel_c_status
      - sensor.charger_8f12_channel_d_status
    to: "done"
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Charging complete
      message: "{{ trigger.to_state.attributes.friendly_name }} is done."
```

## Development

```bash
python -m pytest        # unit tests for the frame parser
```

## Credits

- Protocol reference: [sidhantgoel/SkyCharger](https://github.com/sidhantgoel/SkyCharger)
- BLE-over-proxy patterns from the Home Assistant `bluetooth` stack

## License

[MIT](LICENSE)
