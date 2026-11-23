# Safety

`cupdrive/safety.py` exists because a test run pinched a hand.

---

## What happened

Channel mapping was mapped out from source code, and the app's own intensity
function was copied as-is:

```js
bn.flexibleControl({telescopic:e, vibration:e, suction:e, rotation:e, duration:0})
```

All four channels to the same value. Fine in the official UI, where the user
sees one slider and expects everything to move together.

During discovery, values up to 99 were sent this way. Channel 0 on this hardware
is a reciprocating mechanical stroke. At 99 it closes hard enough to pinch.

**It was luck that nothing was in the way.**

---

## Five gates

```python
from cupdrive.safety import MultiGuard
guard = MultiGuard({protocol.CH_VIB: 55, protocol.CH_THRUST: 40})
```

### 1. Channel whitelist

Mechanical channels refuse to activate without an explicit opt-in:

```python
SafetyGuard(channels=(protocol.CH_SUCTION,))
# raises SafetyError — needs allow_dangerous=True
```

An accidental call with a wrong index fails loudly instead of moving hardware.

### 2. Per-channel caps

| channel | cap | why |
|---|---|---|
| vibration | 55 | safe, no pinch risk; higher is just uncomfortable |
| thrust | **40** | mechanical stroke — the only thing that has hurt anyone |
| shake | 35 | conservative default, unmeasured |

These are **hand-tuned feel values, not device maxima.** The device accepts 99.

### 3. Slew limiting

25 units/s. No command can jump more than ~1.25 units per tick at 10 Hz.

```python
delta = slew * dt
v = last + max(-delta, min(delta, target - last))
```

### 4. Fail-safe zero

Every exit path zeroes the device before disconnecting:

```python
finally:
    await be.send(zero_frame())
    await be.send(halt())
```

Plus `atexit` and `SIGINT`/`SIGTERM` handlers.

> Note: if the process is killed with SIGKILL, nothing runs. The device keeps
> its last state until BLE times out or it is powered off. There is no
> heartbeat mechanism.

### 5. Audit

Every command is recorded. On exit:

```
伸缩: 命令数 120  峰值 40  均值 24.9  被限速/限幅 13 次 (13.0%)
振动: 命令数 120  峰值 55  均值 29.8  被限速/限幅 16 次 (16.0%)
```

If the clamp count is high, the curve is asking for more than the caps allow —
either soften the curve or raise the cap deliberately.

---

## Discovery procedure for an unknown device

**One channel at a time. Smallest value first. Hands off the hardware.**

```
1. read-only      connect, enumerate GATT, no writes
2. single pulse   one channel, value 3, hold 2 s, then zero
3. if no motion   value 5 → 8 → 12, one at a time
4. if motion      note which channel moved and how
5. repeat         next channel
```

Never send "all channels = X" as a probe. It is the one pattern that can move
several mechanisms at once, and you do not yet know what they are.

`tools/channel_probe.py` implements this with hardcoded per-channel ceilings.

---

## The general lesson

For any BLE toy, the failure mode is not "the software crashes". It is
"the software works, and the hardware does exactly what you told it".

Every new command shape is a physical action until proven otherwise.
