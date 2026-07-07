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
| QUERY_CHANNEL_STATUS | `0x55` | channel mask (A=`0x01`, B=`0x02`, C=`0x04`, D=`0x08`) |

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

## Notes / open items

- A per-channel password (`passwordEnable`) can be set in the SkyCharger app. If
  set, `0x55` may not return data until a `VERIFY_PASSWORD (0x74)` handshake.
  This integration assumes no password is set and surfaces a clear error if the
  charger connects but returns nothing.
- The `duration` unit (seconds vs minutes) and `status` byte semantics are not
  yet nailed down; the raw payload is logged at debug level for future work.
