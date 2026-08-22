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
- **Presets**: save a staged program under a name and apply it to any channel later, straight from the device page
- Staged values are kept — across a program change, a lost Bluetooth link and a restart
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

A passcode set in the SkyCharger app does **not** need to be removed — every
query is answered and both start and stop are carried out regardless. It only
affects one thing: the charger will show a `PASSCODE` prompt on its display
until Home Assistant is told the code. See
[the passcode prompt](#the-passcode-prompt-on-the-charger) below.

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
| `select.…_channel_a_preset` | applies a saved preset to the channel |
| `button.…_channel_a_start` | runs the staged program |
| `button.…_channel_a_stop` | stops the channel, and clears a latched error |
| `text.…_channel_a_preset_name` | the name channel A's next saved preset gets |
| `button.…_channel_a_save_preset` | saves what is staged, under that name |

<img width="620" alt="Controls card on the Home Assistant device page: start and stop buttons for channels A to D, next to the activity log of the channel status sensors" src="https://raw.githubusercontent.com/lightheaded/ha-skyrc/master/images/controls.png" />

Ranges follow the charger: they change with the battery type and program, and a
parameter the program does not use (a discharge current on a plain charge, say)
reports unavailable rather than pretending to matter. Nickel packs also get a
peak sensitivity, cycle count and cycle order, disabled by default.

What you type is kept. A value entered for a program comes back when you return
to that program, currents carry over to whichever program you switch to, and
everything survives a lost Bluetooth link, a reload and a restart. Only what has
never been set falls back on the charger's default — so a half-changed program
still cannot be left staged. Voltage setpoints are the exception to the
carry-over: they belong to the chemistry, and a 4200 mV LiPo setpoint has no
business being squeezed into the LiFe range.

None of it needs the charger, either. Stage a program or edit a preset with the
charger switched off and it is there when the charger comes back — only the
entities that actually talk to it (the sensors, start and stop) report
unavailable in the meantime.

### Presets

A preset is a whole staged program under a name — battery type, program, cell
count, currents and voltages — kept by Home Assistant and applied to any
channel:

1. Stage the program you want on a channel.
2. Type a name in that channel's **preset name** field.
3. Press **Channel X save preset**.

Both sit in that channel's own block on the device page, next to its **preset**
select — which stages the lot in one pick from then on, and reads unavailable
until the first preset exists, because there is nothing to pick. Editing
any parameter afterwards leaves the select blank again — what is staged is no
longer the preset. Saving over a name replaces it; `skyrc.delete_preset` removes
one:

```yaml
action: skyrc.delete_preset
target:
  entity_id: select.charger_8f12_channel_a_preset
data:
  name: 3S race pack
```

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

A channel that is already running has to be **stopped first**; the charger
ignores a start sent to a busy channel outright, so the call fails with
`Channel A is already running`. That applies to runs started from the charger's
own panel too.

### What the charger does with it

The charger keeps the last program a channel ran, so the physical **CHARGE
SETTING** menu shows what Home Assistant sent. The staged values in Home
Assistant are separate from that and survive a restart; they are not read back
from the charger, so the two can differ until you press start.

## Charger settings

The charger's own settings — the ones behind **Task Parameters** and **System
Settings** on its front panel — are readable and writable too. They are global,
not per channel, so there is one of each:

| Entity | Charger menu | Range |
|---|---|---|
| `switch.…_safety_timer_cut_off` | Task Parameters ▸ Safety Timer | on/off |
| `number.…_safety_timer` | | 1–999 min |
| `switch.…_capacity_cut_off` | Task Parameters ▸ Max. Capacity | on/off |
| `number.…_capacity_limit` | | 100–50000 mAh |
| `number.…_minimum_input_voltage` | System Settings ▸ Min. Input Voltage | 10.0–30.0 V |
| `number.…_maximum_input_power` | System Settings ▸ Max. Input Power | 10–400 W |
| `select.…_beep_volume` | System Settings ▸ Volume | off / low / high |
| `switch.…_completion_beep` | System Settings ▸ Completion Signal | on/off |

<img width="400" alt="Configuration card on the Home Assistant device page: beep volume, capacity cut-off and capacity limit for the charger, then the staged program for channel A — LiPo, 3 cells, 100 mA, 4200 mV, balance charge — with the discharge current and voltage greyed out because the program does not use them" src="https://raw.githubusercontent.com/lightheaded/ha-skyrc/master/images/program-settings.png" />

The two cut-offs are the charger's own safety net, and the reason they are
worth having in Home Assistant: a safety timer and a capacity limit are what
stop a run that has gone wrong while nobody is watching. They are enabled from
the factory and worth leaving that way.

The ranges above are the *documented* ones, not the charger's own — it stores
whatever it is sent, including a 65535-minute timer and a 2550 W power cap, so
the bounds are enforced here. Input voltage and power limits come from the
Q200neo specification (DC input 10.0–30.0 V; 200 W on AC, 400 W on DC).

Settings the charger acknowledges but never reports back — LCD backlight,
warning, sleep time, temperature and balance — are deliberately **not** exposed.
A write that cannot be read back cannot be confirmed, or undone with any
confidence. See [PROTOCOL.md](PROTOCOL.md) if you want the detail.

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

The **storage** and **cycle** programs charge *or* discharge depending on where
the pack starts, and no part of the protocol says which. For those the pack
voltage does: the status sensor watches it and reports `charging` when it climbs
and `discharging` when it falls. It takes a poll or two of real movement, so a
run that has just started reads `working` until the voltage has moved 10 mV —
except for a storage run started from Home Assistant, where the setpoint is
known and the direction follows from the voltage the pack starts at.

The same watch covers chargers that do not answer the basic-info query at all,
which used to be stuck on `working` outright. Having a passcode set in the
SkyCharger app is **not** one of those cases — see
[PROTOCOL.md](PROTOCOL.md#passwords).

A program started *from Home Assistant* is remembered, so its direction is
reported even when the charger's own program query is unavailable or turned off.

## The passcode prompt on the charger

If your charger shows `PASSCODE: NNNN` on its display while Home Assistant is
polling, it has a passcode set in the SkyCharger app and Home Assistant is not
sending it. The charger is showing you the code it wants — it is a proximity
check, so that only someone who can see the charger can authorise a client.

**Home Assistant will ask you for it.** When the charger refuses the passcode,
the integration raises the standard "needs attention" prompt on the Integrations
page with a box to type the four digits into — read them off the charger's
screen. Nothing else stops working in the meantime.

You can also set it yourself at any time in **Settings → Devices & Services →
SkyRC Charger → Configure**, which has two options:

| Option | Effect |
|---|---|
| **Passcode** | The four digits. Sent with the query that asks a running channel what it is doing, so the charger accepts it instead of prompting. |
| **Read the program of a running channel** | Turn it off and that query is never sent at all, so nothing can prompt. The cost is charge-vs-discharge for runs the integration did not start itself — those channels read `working`. |

Chargers with no passcode set are unaffected: the default `0000` is correct for
them, and no prompt appears.

The prompt used to be far worse than it needed to be, and that part was this
integration's fault: the query went out for every running channel on **every
poll**, raising a fresh prompt every 30 seconds. It now runs **once per run**,
so even with the wrong passcode it is one prompt per charge.

The integration also logs a warning naming the passcode it tried when the
charger rejects it, so this shows up in the log rather than only on the device.

## Development

```bash
python -m pytest        # frame encoding/parsing and program limits
```

## Credits

- Protocol reference: [sidhantgoel/SkyCharger](https://github.com/sidhantgoel/SkyCharger)
- BLE-over-proxy patterns from the Home Assistant `bluetooth` stack

## License

[MIT](LICENSE)
