# cupdrive

**Turn any video into device motion.**

A small, offline pipeline that reads a video's rhythm and drives a Bluetooth toy in sync. No cloud, no accounts, no vendor content library.

Built for a specific device (Mizz Zee / 醉清风 `MIZZZEE XW`) whose BLE protocol was reverse-engineered from its Android APK and Windows app logs — but the architecture is generic.

---

## Download

**Windows 10/11 x64** — grab `cupdrive-win64.zip` from
[Releases](../../releases), unzip anywhere (not `Program Files`), and run
`cupdrive.exe`. No Python, no installer.

**中文使用说明：[docs/usage.md](docs/usage.md)** — 下载、标定、连接设备、参数、常见问题。

> The exe is unsigned, so SmartScreen may warn on first launch:
> **More info → Run anyway**.

The UI opens in an app-mode Edge/Chrome window. Close it and the background
process exits after two idle minutes; there is also a **退出** button in the
header.

---

## Why this exists

Commercial "AI sync" products (Boo Boop, 杰士邦 AI 观影杯, 心跳元力) all lock you into their own content. The hardware protocol is the easy part; the interesting problem is **turning arbitrary video into a control signal that feels alive**.

This repo is that pipeline, plus the reverse-engineering notes.

---

## Architecture

```
video ──► web/index.html ──► script.json ──► tune.py ──► tuned.json ──► play.py ──► BLE device
           (browser)                          (numpy)                    (bleak)
                                             ▲
                            webapp.py + ui/app.html (local HTTP + browser shell)
```

Five stages:

| Stage | What | Where |
|---|---|---|
| **Analyze** | Audio RMS + 3-layer motion analysis + cut detection, all in the browser | `web/index.html` |
| **Tune** | Denoise → percentile stretch → rate-limited envelope → breath | `cupdrive/tune.py` |
| **Guard** | Channel whitelist, per-channel caps, slew limit, fail-safe zero | `cupdrive/safety.py` |
| **Play** | 10 Hz curve playback, multi-channel with lag | `cupdrive/play.py` |
| **Desktop** | Video, curves, channel toggles, scan/connect, panic stop | `webapp.py`, `ui/app.html` |

The desktop shell is a local HTTP service plus an app-mode browser window.
Video decoding stays in the browser (no ffmpeg needed); BLE stays in Python.
Nothing is uploaded — the server binds to `127.0.0.1` only.

---

## Quick start

### Desktop app (Windows)

Download the release zip — full walkthrough in
[中文使用说明](docs/usage.md) — or run from source:

```bat
pip install -r requirements.txt
cupdrive.cmd
```

The window does everything: video, curves, channels, playback, emergency stop.

**Full flow**

1. **Calibrate** — click **标定台**. The browser opens; drop a video in, hit **⚡ 全自动**, and save `<name>.script.json`.
2. **Tune** — back in the window, click **导入脚本** and pick that file. It is tuned and added to the curve list.
3. **Play** — open the same video, pick the curve (it auto-matches by filename), connect the device, press play.

No hardware? **Mock 模式** runs the whole timeline, safety guard included, without sending BLE.

The desktop app defaults to **vibration only** (cap 55). Thrust (cap 40) and shake (cap 35) are mechanical channels and require an explicit confirmation. `Esc` or **紧急停止** zeros everything immediately.

### Command line

```bash
pip install bleak numpy
```

**1. Capture a curve**

Open `web/index.html` in Chrome/Edge, drop a video in, hit **⚡ 全自动**. It scans the file and downloads `<name>.script.json`.

**2. Tune it**

```bash
python -m cupdrive.tune path/to/script.json --out tuned.json
```

**3. Play it**

```bash
python -m cupdrive.play tuned.json --backend ble --wait
```

Press Enter the moment your video starts.

Run without `--backend ble` to see the intensity bar in the terminal — no hardware needed.

### Build a release

```bat
release.bat
```

Produces `release\cupdrive-win64.zip` (≈54 MB, Python bundled). Upload it to
GitHub Releases:

```bash
gh release create v0.2.0 release/cupdrive-win64.zip --title "cupdrive v0.2.0"
```

The build has no pythonnet dependency — BLE goes through `bleak`, the UI
through a local HTTP server, so PyInstaller produces a working exe.

---

## The curve is the hard part

The naive approach — extract intensity, feed it to the motor — produces something that feels like a broken massage chair. What actually works:

**1. The envelope is rate-limited, not smoothed.**

Watching 792 commands from the official app revealed the rule:

```
rise:  +1 step per command, never more    (16.5 units/s at 0-100 scale)
fall:  -5 steps per command allowed       (82.5 units/s)
```

Rise is 5× slower than fall. That asymmetry is why it reads as "restrained" rather than "clingy". `tune.py` reproduces this directly:

```python
if target > v:  v = min(v + up_step,   target)   # slow climb
else:           v = max(v - down_step, target)   # fast retreat
```

**2. Denoise before stretching, never after.**

Raw audio RMS on a real clip gave `std=4.68` — essentially a flat line at 13%. Stretching that first just amplifies noise. A 4-second moving average followed by 5–95 percentile stretch gives `std=28.77`, and the actual beat structure becomes visible.

**3. Blend audio and motion, then stretch once.**

Stretching each channel separately before combining destroys relative information and pushes the mean high. Fuse the raw signals first, stretch the result.

---

## Reverse-engineered protocol

Full notes in [`docs/protocol.md`](docs/protocol.md). Summary:

```
frame  = [0xAA, CMD, LEN, ...payload, CHECKSUM]
CHECKSUM = sum(all previous bytes) & 0xFF

0x0A  start/stop      [1] / [0]        ← MUST send start first
0x08  intensity       [t,v,s,r,dl,dh]  ← 4 channels + duration
0x04  heat            [1] / [0]
0x06  mode            5 bytes
```

Channel order, hardcoded in the app's `nC()`:

| idx | name | this device |
|---|---|---|
| 0 | thrust | ✅ 伸缩 |
| 1 | vibration | ✅ 振动 |
| 2 | suction | ⚠️ 抖动 (not suction!) |
| 3 | rotation | ❌ no hardware |

**There is no authentication.** The app's `verifyApp()` / `verifyDevice()` are empty stubs. Any client that knows the UUIDs and frame format can drive the device.

> Note: the vendor app sets all four channels to the same slider value. **Do not do that.** Channel 2 on this hardware is a high-frequency shake, and channel 0 is a mechanical stroke that can pinch. Driving all four at once is how you get hurt. See the safety section.

---

## Safety

`cupdrive/safety.py` exists because a test run pinched a hand.

Five gates, all mandatory:

1. **Channel whitelist** — mechanical channels (thrust/suction/rotate) refuse to activate unless explicitly allowed.
2. **Per-channel caps** — thrust is capped at 40, vibration at 55. These are hand-tuned, not theoretical maxima.
3. **Slew limiting** — 25 units/s. No jumps.
4. **Fail-safe** — `Ctrl+C`, exception, or process exit all zero the device before disconnecting.
5. **Audit** — every command logged; peak/mean/clamped counts printed on exit.

```python
from cupdrive.safety import MultiGuard
from cupdrive import protocol as P
guard = MultiGuard({P.CH_VIB: 55, P.CH_THRUST: 40})
```

**Test procedure for any new device:** one channel at a time, smallest value first (3, then 5, 8, 12), hands off the hardware.

---

## Status

Working, hand-tuned, not polished.

- [x] Protocol fully reverse-engineered, verified byte-for-byte against hardware
- [x] Browser curve editor with audio + motion analysis
- [x] Curve tuning with official-derived envelope
- [x] Multi-channel playback with lag
- [x] Safety guard
- [x] Desktop GUI — video, curves, one-click tune, scan/connect, mock mode, panic stop
- [x] Standalone Windows build (no Python required on the user's machine)
- [ ] Support for other device models
- [ ] Preset library

---

## Disclaimer

For private, personal use with hardware you own. Reverse engineering for interoperability. No warranty — this drives physical machinery, so test carefully and keep your hands clear during discovery.

Full terms, safety rules and liability limits: [docs/usage.md §9](docs/usage.md#9-免责声明与使用条款).
