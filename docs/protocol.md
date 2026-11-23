# Protocol notes

Reverse-engineered from two sources:

1. **Android APK** (`cn.intofun.mizzzee`) — the BLE layer lives in plain
   `uni-app` JavaScript at `assets/apps/*/www/app-service.js`.
2. **Windows app** (Boo Boop) — `%APPDATA%\BooBoop\logs\btserver.log` records
   every outgoing command in hex, including what the official sync feature sends.

---

## Device

```
advertised name   MIZZZEE XW
service           0000DDDD-0000-1000-8000-00805F9B34FB
write             0000DDD1-…   (write + write-without-response)
notify            0000DDD2-…
read              0000DDD3-…
```

`write` must use **write-without-response**. Requesting a response returns
`GATT Protocol Error: Invalid Handle` on Windows.

---

## Frame format

```
[0xAA, CMD, LEN, ...PAYLOAD, CHECKSUM]
CHECKSUM = sum(all preceding bytes) & 0xFF
```

Reference implementation (from the app's minified `Ce()` / `Il()`):

```js
function Il(cmd, payload = []) {
  const s = [0xAA, cmd, payload.length, ...payload];
  let sum = 0;
  for (const b of s) sum += b;
  return s.concat([sum & 0xFF]);
}
```

Python equivalent lives in `cupdrive/protocol.py::aa_frame`.

---

## Commands

| CMD | Name | Payload | Notes |
|---|---|---|---|
| `0x04` | controlHeat | `[1]` / `[0]` | untested on this unit |
| `0x06` | modeControl | `[t,v,s,r,h]` | 5 channels, one value each |
| `0x08` | flexibleControl | `[t,v,s,r,dur_lo,dur_hi]` | **main control path** |
| `0x0A` | startCount | `[1]` start / `[0]` stop | **required before 0x08** |
| `0x0D` | resetCount | `[1]` | |

### Working sequence

```
1.  AA 0A 01 01 B6                                  start
2.  AA 08 06 <t> <v> <s> <r> 00 00 <CS>             intensity, 0..99 each
3.  AA 08 06 00 00 00 00 00 00 B8                   zero
4.  AA 0A 01 00 B5                                  stop
```

**Step 1 is not optional.** Without `startCount`, intensity frames are accepted
silently (the device even answers on notify) but do nothing. This cost several
hours to find.

**Step 2 payload must be 6 bytes.** Single-byte payloads are interpreted as a
preset selector, not an intensity.

Values `0..99` map 1:1 to the number shown on the device's own display —
verified at 10 / 25 / 50 / 75 / 99.

---

## Channel mapping

Hardcoded in the app's `nC()`:

```js
s === "thrust"  || s === "stretch" ? l = 0 :
s === "vibration"                  ? l = 1 :
s === "suction" || s === "sucking" ? l = 2 :
s === "rotation" || s === "rotate" ? l = 3 : ...
```

| idx | app name | actual hardware on MIZZZEE XW |
|---|---|---|
| 0 | thrust / stretch | **reciprocating stroke** (伸缩) |
| 1 | vibration | **vibration** (振动) |
| 2 | suction | **high-frequency shake** (抖动) — *not* suction |
| 3 | rotation | **nothing** — no motor |

The app's own `sendMotorIntensity()` sets all four to the same slider value:

```js
bn.flexibleControl({telescopic:e, vibration:e, suction:e, rotation:e, duration:0})
```

**Do not copy this.** On this hardware it means the mechanical stroke and the
shake both slam to whatever the slider says. That is how you pinch a hand.
Drive one channel at a time; see `docs/safety.md`.

---

## What the official app actually sends

From 792 logged commands during one full video playback:

```
All commands were: AA BB 01 <v>      v = 0x00 .. 0x0A  (0-10)
Average rate:      1.65 cmd/s
```

`0xBB` is a *different* command path from `0x08` — a compact single-byte
intensity, 11 levels. The official sync feature uses only this.

Behaviour extracted from the sequence:

| property | value |
|---|---|
| rise step | **always +1**, never more |
| fall step | up to **−5** |
| value distribution | bell-shaped, peak at 5 |
| long silences | 16 s at start, 8 s mid, 13 s at end |

Rise being 5× slower than fall is the single most important finding — it is
what makes the motion feel restrained rather than eager. `cupdrive/tune.py`
reproduces it with hard rate limiting instead of exponential smoothing.

We use `0x08` (0–99) rather than `0xBB` (0–10) because the extra resolution is
free and the safety guard already handles smoothing.

---

## Authentication

None.

```js
function Qy(){return Qy}   // verifyApp
function Zy(){return Zy}   // verifyDevice
```

Both are empty stubs. There is no key exchange, no challenge-response, no
pairing requirement beyond standard BLE bonding. Any client that knows the UUIDs
and the frame format can drive the device.

---

## Device status (notify)

10 bytes:

```
AA 01 06 <6 bytes> <checksum>
```

Observed payload `4E 04 B0 1F 01 2C`:

| field | interpretation |
|---|---|
| `B0 1F` little-endian | 8112 → **battery 81.12 %** |
| `01 2C` big-endian | 300 → **3.00 V** |

Checksum verified: `sum(AA,01,06,4E,04,B0,1F,01,2C) & 0xFF = 0x02`.

The device does not acknowledge individual commands — the same status frame
repeats regardless of what you send. Open-loop control, no feedback.

---

## Dead ends

**`03 12 XX` frames.** The app contains a second protocol
(`xht-utils/ble-manager.js`) with 20-byte frames beginning `03 12`. Sending
those to `MIZZZEE XW` produces a notify reply but no motion. That path belongs
to a different product line (XHTKJ / 安可尼 / ZQF devices).

**`AA 06 05 ...` (modeControl).** Accepted, ignored.

**Single-byte `AA 08 01 <v>`.** Changes a preset, not an intensity. The device
display jumps to a fixed value per preset regardless of `v`.

---

## Reproducing the analysis

`tools/apk_ble_scan.py` finds BLE UUIDs and broadcast names inside any APK
without jadx. `tools/analyze_log.py` parses a `btserver.log` into a command
time series.
