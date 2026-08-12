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
  - **Status** (`charging` / `discharging` / `idle` / `done` / `error` / `ready` / `standby` / `dc_power` / `working`), with the battery type and program as attributes
  - Capacity (mAh), Voltage (V), Current (A), Battery temperature (°C)
  - Duration (disabled by default)
- Charger internal temperature (diagnostic)
- Connect → poll → disconnect cycle that leaves the single BLE slot free for the SkyCharger phone app between polls

### Example

The device page: four channels, each with its own status, capacity, voltage,
current and battery temperature, plus the charger's internal temperature as a
diagnostic. The **duration** entities are greyed out because they are disabled
by default — enable them here if you want elapsed time.

<img width="760" alt="Home Assistant device page for a SkyRC Q200neo, showing per-channel status, capacity, voltage, current and battery temperature entities" src="https://raw.githubusercontent.com/lightheaded/ha-skyrc/master/images/device-page.png" />

Each channel's **status** sensor carries the pack details as attributes — cell
count, cell configuration and the individual cell voltages, plus the
`battery_type` and `program` that decide whether a running channel reads
`charging` or `discharging`:

<img width="560" alt="Attributes of a channel status sensor: cell count 6, cell configuration 6S, per-cell voltages, battery type liion, program storage, and the list of possible states" src="https://raw.githubusercontent.com/lightheaded/ha-skyrc/master/images/channel-status-attributes.png" />

Here the channel finished a **storage** run on a 6S Li-ion pack, which is one of
the two programs that deliberately stay `working` rather than guess a direction
(see [Charging or discharging?](#charging-or-discharging) below).

## Requirements

- Home Assistant **2024.12** or newer
- A Bluetooth adapter or ESPHome Bluetooth proxy within range of the charger

A passcode set in the SkyCharger app does **not** need to be removed: on a
Q200neo with one set, both the status and basic-info queries are answered
normally and the charger reports no password check. See
[PROTOCOL.md](PROTOCOL.md) for the one case that would degrade.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/lightheaded/ha-skyrc`, category **Integration**
3. Install **SkyRC Charger**, then restart Home Assistant

### Manual

Copy `custom_components/skyrc` into your HA `config/custom_components/`
directory and restart Home Assistant.

### Upgrading

Breaking changes and what to do about them are written up in the
[release notes](https://github.com/lightheaded/ha-skyrc/releases) for the
version you are upgrading to.

## Setup

The charger is usually auto-discovered: **Settings → Devices & Services →
Discovered**. Otherwise add it via **+ Add Integration → SkyRC Charger**
and pick it from the list of chargers in range.

## Notify when a channel finishes

The integration deliberately ships **no** notification logic — wire it up with a
plain automation. This one fires when any channel finishes and reports what
finished, the pack, and how well the cells are balanced:

> 🔋 Channel B at storage voltage
> Li-ion 6S · 22.56 V · 32 mAh
> Cells 3.753–3.763 V (Δ10 mV)

```yaml
alias: SkyRC — notify when a channel finishes
mode: queued
triggers:
  - trigger: state
    entity_id:
      - sensor.charger_8f12_channel_a_status
      - sensor.charger_8f12_channel_b_status
      - sensor.charger_8f12_channel_c_status
      - sensor.charger_8f12_channel_d_status
    to: "done"
    # Don't re-fire when a channel comes back from a failed BLE poll.
    not_from: ["unavailable", "unknown"]
actions:
  - action: notify.main # or notify.mobile_app_your_phone
    data:
      title: >-
        {%- set eid = trigger.entity_id -%}
        {%- set ch = eid.split('_channel_')[1].split('_status')[0] | upper -%}
        {%- set prog = state_attr(eid, 'program') -%}
        {%- set verb = {'charge': 'charged', 'balance_charge': 'charged',
        'fast_charge': 'charged', 'auto_charge': 'charged', 're_peak': 're-peaked',
        'discharge': 'discharged', 'storage': 'at storage voltage',
        'cycle': 'cycled'}.get(prog, 'finished') -%}
        🔋 Channel {{ ch }} {{ verb }}
      message: >-
        {%- set eid = trigger.entity_id -%}
        {%- set base = eid.replace('_status', '') -%}
        {%- set batt = {'lipo': 'LiPo', 'liion': 'Li-ion', 'life': 'LiFe',
        'lihv': 'LiHV', 'nimh': 'NiMH', 'nicd': 'NiCd', 'pb': 'Pb',
        'pb_agm': 'Pb AGM'}.get(state_attr(eid, 'battery_type')) -%}
        {%- set cells = state_attr(eid, 'cell_configuration') -%}
        {%- set cv = state_attr(eid, 'cell_voltages_mv') or [] -%}
        {%- set v = states(base ~ '_voltage') | float(0) -%}
        {%- set mah = states(base ~ '_capacity') | int(0) -%}
        {%- set t = states(base ~ '_battery_temperature') -%}
        {%- set spread = (cv | max - cv | min) if cv | count > 1 else 0 -%}
        {{ [batt, cells] | select('string') | join(' ') }}{% if batt or cells %} · {% endif %}{{ v | round(2) }} V{% if mah > 0 %} · {{ mah }} mAh{% endif %}{% if cv | count > 1 %}{{ '\n' }}Cells {{ (cv | min / 1000) | round(3) }}–{{ (cv | max / 1000) | round(3) }} V (Δ{{ spread }} mV){% if spread > 50 %} ⚠️{% endif %}{% endif %}{% if t not in ['unknown', 'unavailable', 'none'] %}{{ '\n' }}Pack {{ t }} °C{% endif %}
```

Replace `charger_8f12` with your charger's entity-ID slug (it follows the
advertised name, e.g. `#Charger-8F12` → `charger_8f12`).

Every part degrades on its own, so the message stays sensible whatever the
charger reports:

| Part | Comes from | Left out when |
|---|---|---|
| the verb (*charged*, *discharged*, *at storage voltage*, …) | `program` attribute | unknown program → a plain "finished" |
| `Li-ion 6S` | `battery_type` / `cell_configuration` attributes | the charger reports neither |
| `32 mAh` | capacity sensor | nothing was moved |
| cell spread, with ⚠️ over 50 mV | `cell_voltages_mv` attribute | fewer than two cells are reported |
| `Pack 24 °C` | battery temperature sensor | no external probe is attached |

Elapsed time is not in the message because the **duration** entity is disabled
by default — enable it on the channel's device page and add
`states(base ~ '_duration')` if you want it.

Prefer the enum states over friendly-name string matching — the status sensor
reports `done` / `charging` / `discharging` / `idle` / `error` / `ready` /
`standby` / `dc_power` / `working`.

### Charging or discharging?

The charger reports a single "working" state for both directions, so the status
sensor reads the channel's program (battery type + charge/discharge program) to
tell them apart. It is also published as attributes on the status sensor:

| Attribute | Example |
|---|---|
| `battery_type` | `lipo`, `liion`, `life`, `lihv`, `nimh`, `nicd`, `pb`, `pb_agm` |
| `program` | `balance_charge`, `charge`, `fast_charge`, `auto_charge`, `re_peak`, `discharge`, `storage`, `cycle` |

The program is kept while a channel is working and after it is done, so a
"charging done" automation can say *what* finished — `{{ state_attr(eid,
'program') }}`. It is cleared when the channel goes back to idle.

Two cases stay `working` rather than guessing: the **storage** and **cycle**
programs (they charge *or* discharge depending on the pack), and chargers that
do not answer the basic-info query at all. Having a passcode set in the
SkyCharger app is **not** one of those cases — see
[PROTOCOL.md](PROTOCOL.md#passwords).

## Development

```bash
python -m pytest        # unit tests for the frame parser
```

## Credits

- Protocol reference: [sidhantgoel/SkyCharger](https://github.com/sidhantgoel/SkyCharger)
- BLE-over-proxy patterns from the Home Assistant `bluetooth` stack

## License

[MIT](LICENSE)
