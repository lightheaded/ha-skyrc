# SkyRC Charger — Home Assistant integration

[![Validate](https://github.com/lightheaded/ha-skyrc/actions/workflows/validate.yml/badge.svg)](https://github.com/lightheaded/ha-skyrc/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

An **unofficial** custom integration that monitors and controls
[SkyRC](https://www.skyrc.com/) smart chargers over Bluetooth Low Energy — get a
push notification the moment a battery finishes charging, and start or stop a
charge program from Home Assistant.

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
- **Control**: stage a program per channel (battery type, cell count, program, currents, per-cell voltages) and **start** or **stop** it — from the dashboard, or in one call from an automation with `skyrc.start_program`
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
Q200neo with one set, every query is answered and both start and stop are
carried out. If your charger shows a `PASSCODE` prompt on its display while
Home Assistant is polling, see [the passcode prompt](#the-passcode-prompt-on-the-charger)
below.

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

## Starting and stopping a charge

> [!CAUTION]
> A charger that can be started remotely can be started when you are not
> there. The manual is blunt about this — *never leave charging batteries
> unattended, never charge overnight* — and lithium packs do catch fire. The
> charger itself checks almost nothing it is sent: a live Q200neo accepted a
> per-cell charge voltage of 9999 mV without complaint. This integration
> enforces the same limits as the SkyCharger app, but limits inside the right
> range are still yours to get right, and a program aimed at the wrong
> chemistry or cell count will happily run. Think about what an automation of
> yours could start, and where the charger sits when it does.

Each channel gets a staged program, then two buttons:

| Entity | What it is |
|---|---|
| `select.…_channel_a_battery_type` | LiPo, Li-ion, LiFe, LiHV, NiMH, NiCd, lead acid |
| `select.…_channel_a_program` | the programs that battery type allows — balance charge, charge, discharge, storage, re-peak, cycle |
| `number.…_channel_a_cell_count` | cells in series (6 lithium, 15 nickel, 10 lead acid) |
| `number.…_channel_a_charge_current` | mA |
| `number.…_channel_a_discharge_current` | mA |
| `number.…_channel_a_charge_voltage_per_cell` | mV — the charger's own "Condition" setting |
| `number.…_channel_a_discharge_voltage_per_cell` | mV cut-off, or the target for a storage run |
| `button.…_channel_a_start` | runs the staged program |
| `button.…_channel_a_stop` | stops the channel, and clears a latched error |

Ranges follow the charger: they change with the battery type and program, and a
parameter the program does not use (a discharge current on a plain charge, say)
reports unavailable rather than pretending to matter. Nickel packs also get a
peak sensitivity, cycle count and cycle order, disabled by default.

Changing the battery type or program resets that program's parameters to the
charger's defaults, so a half-changed program cannot be left staged.

### From an automation

`skyrc.start_program` runs one program in a single call without touching the
staged settings. Anything left out comes from the staged program, except that
naming a different battery type or program starts from that program's defaults —
so a call only has to state what matters:

```yaml
alias: SkyRC — storage-charge the flight pack after a session
triggers:
  - trigger: state
    entity_id: input_boolean.flying_done
    to: "on"
actions:
  - action: skyrc.start_program
    target:
      entity_id: button.charger_8f12_channel_b_start
    data:
      battery_type: liion
      program: storage
      cell_count: 6
      charge_current: 2000
      discharge_current: 1000
      discharge_voltage: 3800   # per cell
```

Stopping is just `button.press` on the channel's stop button.

A program the charger will not accept fails the service call with the reason —
wrong program for the chemistry, too many cells, a current or voltage outside
the range for that pack. If the charger takes the frame and then refuses to act
on it, the call fails too: the channel is checked afterwards, and one still idle
means refused.

### What the charger does with it

The charger keeps the last program a channel ran, so the physical **CHARGE
SETTING** menu shows what Home Assistant sent. The staged values in Home
Assistant are separate from that and survive a restart; they are not read back
from the charger, so the two can differ until you press start.

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

A program started *from Home Assistant* is remembered, so its direction is
reported even when the charger's own program query is unavailable or turned off.

## The passcode prompt on the charger

Some chargers show `PASSCODE: XXXX` on their own display while Home Assistant is
polling. It does not affect the readings, and it does not block starting or
stopping a channel.

The likely cause is the query that carries the passcode digits: the charger is
showing the code for someone standing at it to type into the SkyCharger app.
Only that one query is involved, and only when the digits sent do not match.
**Settings → Devices & Services → SkyRC Charger → Configure** has two ways to
deal with it:

| Option | Effect |
|---|---|
| **Passcode** | The four digits set in the SkyCharger app. Sent with the query, so the charger accepts it instead of prompting. |
| **Read the program of a running channel** | Turn it off and that query is never sent at all. The cost is charge-vs-discharge for runs the integration did not start itself — those channels read `working`. |

This explanation is not yet confirmed against a display — if you can watch the
charger while Home Assistant polls it, a note on
[the discussion thread](https://community.home-assistant.io/t/skyrc-charger-ble-per-channel-monitoring-charging-done-notifications/1016445)
would settle it.

## Development

```bash
python -m pytest        # frame encoding/parsing and program limits
```

## Credits

- Protocol reference: [sidhantgoel/SkyCharger](https://github.com/sidhantgoel/SkyCharger)
- BLE-over-proxy patterns from the Home Assistant `bluetooth` stack

## License

[MIT](LICENSE)
