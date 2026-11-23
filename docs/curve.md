# Curve design

The naive pipeline — extract intensity, feed the motor — produces something
that feels like a broken massage chair. Here is what actually works, and the
measurements behind each decision.

---

## The problem: real audio is flat

A 7m23s clip, raw audio RMS, 10 Hz sampling:

```
min=0.0  max=37.0  mean=13.4  std=4.68   nonzero=100%
percentiles:  p5=7  p25=10  p50=13  p75=16  p95=22
```

`std = 4.68` on a 0–100 scale is essentially a straight line. The 30-second
window means ranged from 8.4 to 17.6 — no usable structure.

Two separate causes:

1. **The source audio is genuinely quiet and compressed** (peak RMS 0.074 of
   full scale). There is no loud/soft contrast to extract.
2. **The browser normalised by `max`.** A single cut-scene frame produced
   `max = 0.58`, which crushed everything else into the bottom 15 % of the range.

---

## Fix 1 — denoise, then stretch (order matters)

```
WRONG:  stretch(raw)          → amplifies noise, still looks like a flat line
RIGHT:  smooth(raw) → stretch → real structure appears
```

Smoothing window sweep, measuring the resulting spread:

| window | std after stretch | comment |
|---|---|---|
| 1 (none) | 28.8 | high-freq jitter, unreadable |
| 5 | 28.4 | still noisy |
| 10 | 28.6 | still noisy |
| **40 (4 s)** | **28.8** | **clean 段落 structure** |
| 100 (10 s) | 30.0 | starts eating real beats |

`std` barely changes, but the *shape* is completely different. At window=1 the
plot is a hairball; at window=40 it becomes readable phrase-level arcs.

Final: **4-second moving average, then 5–95 percentile stretch.**

```
after:  min=0  max=100  mean=45.5  std=28.77
```

Same source. Six-fold increase in usable range.

---

## Fix 2 — fuse before stretching, not after

Wrong order:

```python
a_s = stretch(audio)      # each becomes 0-100
m_s = stretch(motion)     # each becomes 0-100
base = a_s*0.6 + m_s*0.4  # noise from both is now amplified equally
```

This pushed the mean to 52 and lost the relative weighting between audio and
motion. Correct:

```python
mixed = smooth(audio)*0.6 + smooth(motion)*0.4   # fuse raw signals
base  = stretch(mixed)                            # stretch once
```

Result: `mean 45.5`, which is where we want it — room above and below.

---

## Fix 3 — rate-limited envelope, not exponential smoothing

Exponential smoothing with attack/release coefficients was the original
approach. It was wrong, because it makes rising *fast* and falling *slow*:

```python
v += (target - v) * (0.22 if rising else 0.033)   # rise 6x faster than fall
```

That produces motion that lunges at every beat and then lingers at high
intensity — the "clingy" feel.

The official app does the opposite. From 792 logged commands:

```
rise step:  always +1, never more
fall step:  up to -5
```

Rise is 5× **slower** than fall. Reproduced as hard rate limiting:

```python
up_step   = 16.5 / hz    # 16.5 units/s
down_step = 82.5 / hz    # 82.5 units/s

if target > v:  v = min(v + up_step,   target)
else:           v = max(v - down_step, target)
```

No smoothing coefficient, no inertia — just a speed limit on the way up.

Effect on the output:

| | exponential (old) | rate-limited (new) |
|---|---|---|
| B min | 15.9 | **10.5** |
| B mean | 49.3 | **45.0** |
| B std | 16.85 | **18.36** |

It can now drop lower and further, which is what "restrained" actually means.

---

## Fix 4 — a floor, and a little noise

Two additions that matter more than they look:

**Floor.** Intensity never goes to zero. `FLOOR_MIN = 14`, floating up to 22 in
busy passages. A device that stops completely reads as broken; a device that
sits at 14 reads as *waiting*.

**Jitter.** A low-frequency random walk at ~3 % amplitude. Without it, the same
curve shape repeats identically every time and the brain immediately tags it as
mechanical. With it, the motion is never twice the same.

---

## Full parameter list

```python
PRE_SMOOTH  = 40      # 4 s moving average, applied BEFORE stretching
STRETCH     = (5, 95) # percentile bounds
GAMMA       = 1.0     # no extra lift; stretching already did the work
VIDEO_W     = 0.40    # motion share in the fusion

UP_RATE     = 16.5    # units/s  (official-derived)
DOWN_RATE   = 82.5    # units/s  (official-derived)
LOOKAHEAD   = 1.2     # s — envelope reads ahead, so motion anticipates
FLOOR       = (14, 22)
CEIL        = 90
BREATH_HZ   = 0.22    # resting respiration
BREATH_AMP  = 3.5
```

---

## What the browser gives you

`web/index.html` produces the raw curve with two analysis passes:

**Audio** — time-domain RMS over the full spectrum, sampled via
`ScriptProcessorNode` (runs on the audio thread, so it survives tab
minimisation).

**Motion** — three layers, 128×72 downscale:

| layer | what |
|---|---|
| weighted motion | centre-weighted frame difference (subject is usually central) |
| block peak | max over a 4×4 grid — catches localised action |
| cut detection | 80 % of blocks changing at once = scene change |

Cut frames get their motion value replaced by the local neighbourhood average,
so a hard cut does not fabricate a spike.

Fusion weights adapt: `0.65 audio + 0.35 motion` when both have signal, pure
audio or pure motion when only one does.

Coverage is reported on export (`covAudio`, `covVideo`). Below 85 % the tool
warns — that is how the original 2× playback speed bug was caught (frame
analysis blocked the decoder, leaving 69-second holes in the data).
