# SkyRC Q200neo BLE protocol

Reverse-engineered from the open-source [SkyCharger](https://github.com/sidhantgoel/SkyCharger)
app and confirmed empirically against a Q200neo (product code `100197`).

## GATT

| | UUID |
|---|---|
| Service | `0000ffe0-0000-1000-8000-00805f9b34fb` |
| Characteristic (write + notify) | `0000ffe1-0000-1000-8000-00805f9b34fb` |

Write a command frame to the characteristic; the charger replies with one or
more notifications that must be reassembled into frames.

> The `ffe0` service is **not** present in the BLE advertisement — only in the
> GATT table. Discovery therefore matches on the advertised local name
> (`#Charger-*`, user-renameable in the SkyCharger app).

`ffe1` declares `read`, `notify` and **`write-without-response`** — but not
`write`. Asking for a write response therefore fails outright on a strict
stack: CoreBluetooth answers `Write Not Permitted` (ATT 0x03) before anything
reaches the charger. Measured MTU is 223 bytes, so no command needs splitting.

### The first frame after connecting is discarded

A Q200neo ignores whatever is written immediately after notifications are
enabled. Measured on one, repeatedly: with no delay the first frame was never
answered, and with 0.25 s it always was. Anything that connects, subscribes and
writes straight away silently loses its first command — for a client that polls
channels in order, that is channel A's reading, every cycle. This integration
waits 0.5 s after `start_notify`.

## Frame format (both directions)

```
[0x0F] [len] [command] [args...] [checksum]
```

- `len` = number of payload bytes (`command` + `args`) + 1
- `payload` = the `len - 1` bytes following `len`; `payload[0]` is the command echo
- `checksum` = `sum(payload) & 0xFF`

Example — query channel A: `0F 03 55 01 56`.

## Commands used

| Command | Byte | Args |
|---|---|---|
| START_CHARGE | `0x05` | 16 bytes, see below |
| QUERY_CHANNEL_STATUS | `0x55` | channel mask (A=`0x01`, B=`0x02`, C=`0x04`, D=`0x08`) |
| QUERY_BASIC_INFO | `0x5F` | channel mask + the four password digits as separate bytes (`00 00 00 00` by default) |
| STOP_CHARGE | `0xFE` | channel mask |

Commands the reference app also defines, tried against a Q200neo and **not
answered**: `INFO` (`0x57`, with the app's fixed 17-byte argument),
`QUERY_SYSTEM_SETTING` (`0x96`) and `QUERY_DC_STATUS` (`0x75`).

Answered but not currently used: `QUERY_VOLTAGE_INFO` (`0x58`, per-cell voltage
and resistance, all zero with no pack attached), `QUERY_SYSTEM_INFO` (`0x5A`)
and `SET_SYSTEM_INFO` (`0x11`) — see below.

## Channel status payload (`d[...]` = bytes after the command echo)

| Offset | Field | Notes |
|---|---|---|
| d[0] | channel mask | |
| d[1] | working state | see below |
| d[2..3] | capacity (mAh, u16 BE) | system/charge error codes when state = ERROR |
| d[4..5] | duration (u16 BE) | |
| d[6..7] | pack voltage (mV, u16 BE) | `0xFFFF` = invalid |
| d[8..9] | current (mA, u16 BE) | `0xFFFF` = invalid |
| d[10] | battery (external) temperature | signed |
| d[11] | charger (internal) temperature | signed |
| d[12..13] | internal resistance (u16 BE) | |
| d[14..25] | cell voltages 1–6 (mV, u16 BE each) | `0` = unpopulated slot |
| d[26..29] | cell voltages 7–8 | longer payloads only |

### Working states (`d[1]`)

| Value | State |
|---|---|
| 0x01 | Working (charging/discharging) |
| 0x02 | Idle |
| 0x03 | **Done** ← notification trigger |
| 0x04 | Error |
| 0x05 | Ready |
| 0x06 | Standby (unknown) |
| 0x07 | DC power supply mode |

The working state does **not** say which way the current flows — charging and
discharging both report `0x01`. The direction comes from the channel's program
in the basic-info payload below.

## Channel basic info payload (`0x5F`)

| Offset | Field | Notes |
|---|---|---|
| d[0] | channel mask | |
| d[1] | working state | as above |
| d[2] | battery type | `0x00` LiPo, `0x01` Li-ion, `0x02` LiFe, `0x03` LiHV, `0x04` NiMH, `0x05` NiCd, `0x06` Pb, `0x07` Pb AGM |
| d[3] | cell count | as configured, not as measured |
| d[4] | program | see below |
| d[5] | charge current limit | ×100 mA |
| d[6] | discharge current limit | ×100 mA |
| d[7], d[8] | firmware version | major, minor |
| d[9] | password set | `1` = the channel requires `VERIFY_PASSWORD` |

### Programs (`d[4]`)

The codes are reused per chemistry, so `d[4]` only has meaning together with
the battery type in `d[2]`:

| Value | Lithium | Nickel | Lead acid |
|---|---|---|---|
| 0x00 | Balance charge | Charge | Charge |
| 0x01 | Charge | Auto charge | Discharge |
| 0x02 | Discharge | Discharge | — |
| 0x03 | Storage | Re-peak | — |
| 0x04 | Fast charge | Cycle | — |

Storage and cycle programs charge *or* discharge depending on the pack, so
this integration reports them as plain `working`.

## Starting and stopping a channel

Both write commands were exercised against a live Q200neo with no packs
attached. **Neither needs any passcode handshake.**

### STOP_CHARGE (`0xFE`)

One argument, the channel mask. Reply: `[mask] [0x01]`. It stops a running
channel, and clears a channel latched in the error state back to idle.

### START_CHARGE (`0x05`)

Sixteen argument bytes. Voltages are **per cell** in mV — the charger's own
"Condition" setting — and currents are in mA.

| Offset | Field | Notes |
|---|---|---|
| a[0] | channel mask | |
| a[1] | battery type | same codes as `0x5F` d[2] |
| a[2] | cell count | |
| a[3] | program | same codes as `0x5F` d[4], per chemistry |
| a[4] | charge current | ÷100 mA |
| a[5] | discharge current | ÷100 mA |
| a[6..7] | discharge voltage (mV, u16 BE) | cut-off; the target for storage |
| a[8..9] | charge voltage (mV, u16 BE) | for storage, the same value as a[6..7] |
| a[10] | re-peak count, or cycle order | nickel only; `0x00` charge first, `0x01` discharge first |
| a[11] | cycle count | nickel cycle only |
| a[12..13] | peak sensitivity (mV, u16 BE) | nickel only ("track voltage") |
| a[14..15] | current high bytes | D200NEX only; zero here |

Parameters a program does not take are sent as zero, which is what the
reference app ends up doing for them; a Q200neo accepted such frames and its
`0x5F` reply echoed back the battery type, cell count, program and current
limit that had been sent.

The last program stays readable through `0x5F` after the channel goes back to
idle, so a channel's staged configuration survives a stop.

### A busy channel ignores it outright

START_CHARGE sent to a channel that is already working gets **no reply at all** —
not a refusal, silence. (An idle channel always acknowledges, even when it goes
on to refuse the program.) So a channel has to be stopped before a new program
can be started on it, and a start that goes unanswered is worth re-reading the
channel status over: working means busy, not broken.

### The reply is an acknowledgement, not a result

`[mask] [byte]`, where the second byte was `0x00` for every START_CHARGE
observed — including ones the charger went on to refuse — and `0x01` for every
STOP_CHARGE. The reference app parses these two bytes as `errorCode` and
`success`, which does not match the device: byte 0 tracks the channel mask
asked for (`0x04` for channel C), and byte 1 never varied with the outcome.

Read the channel status to find out what actually happened. A channel that is
still `idle` a second or two later means the charger refused the program; one
that reports `error` started and then failed (`CONNECTION_BREAK`, `0x0B`, with
nothing attached).

### The charger validates almost nothing

Observed on a Q200neo:

- a per-cell charge voltage of **9999 mV** for a 1S LiPo was accepted and run;
- an undefined program code (`0x09`) was ignored, leaving the channel idle;
- `STOP_CHARGE` with a nonsense channel mask (`0x10`) was acknowledged `10 01`.

So limits have to be enforced by the client. This integration keeps the ranges
the SkyCharger app enforces for the Q200neo in `programs.py` and refuses to
build a frame outside them.

## Charger settings (`0x5A` / `0x11`)

`QUERY_SYSTEM_INFO` (`0x5A`, one argument: the channel mask) reports the
charger's own settings. `SET_SYSTEM_INFO` (`0x11`) writes one of them:
`[mask] [setting] [b1] [b2] [b3]`, replying `[mask] [0x01]`.

**The settings are global, not per-channel.** Writing the safety timer to
channel A changed what channel B reported, so the channel argument is
decorative. All four channels return the same values.

Mapped empirically on a Q200neo — write one setting, diff the `0x5A` payload,
write the old value back — and cross-checked against the charger's own menus:

| Setting | `0x11` | Argument bytes | `0x5A` offset | Menu item |
|---|---|---|---|---|
| Recycle | `0x00` | value | d[1] | — |
| Safety timer | `0x01` | enable, minutes u16 BE | d[2], d[3..4] | Task Parameters ▸ Safety Timer |
| Max capacity | `0x02` | enable, mAh u16 BE | d[5], d[6..7] | Task Parameters ▸ Max. Capacity |
| Beeps | `0x03` | key beep, system beep | d[8], d[9] | System Settings ▸ Volume |
| Min input voltage | `0x04` | mV u16 BE | d[10..11] | System Settings ▸ Min. Input Voltage |
| Max input power | `0x07` | value (×10 W) | d[13] | System Settings ▸ Max. Input Power |

Acknowledged but with **no observable effect** on this firmware: temperature
(`0x05`), balance (`0x06`), LCD backlight (`0x10`), warning (`0x11`) and sleep
time (`0x12`). The reference app reads those from payload offsets 33-40, which
only exist on payloads of 37 bytes or more; this charger returns 35, so either
the firmware ignores them or it keeps them somewhere `0x5A` does not report.
Since the acknowledgement is identical either way, **do not write a setting you
cannot read back** — there is no way to confirm the old value was restored.

Not tried, deliberately: `RESET` (`0x15`), which restores factory settings, and
the DC ones (`0x08`-`0x0B`), which switch the charger into power-supply mode.

<a name="passwords"></a>

## Passwords

`0x5F` is the only command that carries the passcode: the four digits, one per
byte. `d[9]` of the reply is a flag about them, and the sense of it appears to
be **"the digits were accepted"**, not "a passcode is required" — the reference
app opens its passcode dialog when `d[9]` is `0`, and treats `1` as authorised.
An earlier version of this document had that backwards.

**Observed on a Q200neo with a passcode set in the SkyCharger app:** sending the
default `00 00 00 00` gets `d[9] = 0x00` on all four channels, and everything
works anyway — `0x55`, `0x5F`, `0x58`, `0x5A` all answer, and START_CHARGE and
STOP_CHARGE are both carried out. Nothing observed so far is gated on the
passcode.

### The passcode prompt on the display

Two Q200neos show `PASSCODE: XXXX` on their own screen while a client is
polling. It does not affect the readings, and it does not stop START_CHARGE or
STOP_CHARGE. It is persistent enough to make the charger's own front panel hard
to operate.

The likely mechanism: `0x5F` arrives with digits the charger does not accept
(`d[9] = 0`), so the charger displays the code for whoever is standing at it to
type into the app. That fits the app's flow, and `0x5F` is the only command in
play that carries passcode digits. Still **not proven** against the display —
that needs someone watching one while a client sends nothing but `0x55`.

What made it *persistent* was on the client side: this integration re-sent
`0x5F` for every working channel on every poll, so a prompt was raised every 30
seconds. A channel's program cannot change without it passing through idle, so
the query now runs once per run — a run that both starts and ends between two
polls is caught by the elapsed duration going backwards. Measured over three
consecutive polls of a charging channel: one `0x5F`, twelve `0x55`.

There is no passcode item anywhere in the charger's own menu tree (checked
against the V1.2 manual: System Settings, Task Parameters, Factory Settings,
System Info), so this is an app-side feature.

Two ways out, both available in the integration's options:

- set the real passcode, so `0x5F` is answered with `d[9] = 1`;
- turn off program polling, so `0x5F` is never sent. The cost is the
  charge/discharge direction, since that is the only place the protocol reports
  a channel's program — though a program *started* from Home Assistant is
  remembered, so direction still works for those runs.

A channel that genuinely refuses to answer is still untested. The reference app
implies a `VERIFY_PASSWORD (0x74)` handshake; if `0x5F` goes unanswered the
client stops asking after three timeouts and the direction falls back to
`working`. `0x55` returning nothing at all surfaces as a clear setup error.

## Notes / open items
- The `duration` unit (seconds vs minutes) and `status` byte semantics are not
  yet nailed down; the raw payload is logged at debug level for future work.
- Whether the `PASSCODE` prompt on the display comes from `0x5F` is unconfirmed;
  see above.
- The Q200neo offers AGM and Cold charge programs for lead-acid packs, and a
  Pb AGM battery type. The reference app has no program byte for either, so they
  are left out rather than guessed at.
- Five `SET_SYSTEM_INFO` settings acknowledge without any readable effect
  (temperature, balance, LCD backlight, warning, sleep time). They stay
  unexposed until a charger is found that reports them.
- The device identifies itself as ASCII `100197` in the reference app's device
  table, matching the product code, but the `INFO` command that would return it
  is not answered.
