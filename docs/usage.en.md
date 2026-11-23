# cupdrive User Guide

**English** | [简体中文](usage.md)

> Turn a video's rhythm into device motion. Fully offline — no network, no uploads.

Device: **MIZZZEE XW (醉清风)**. Other models need a protocol mapping first.

**Version** v0.3.2 · Windows 10/11 x64

---

## 0. Quick start (5 minutes)

1. Unzip `cupdrive-win64.zip`, run `cupdrive.exe`;
2. Click **Mock mode** → **▶** to confirm the UI works (no hardware needed);
3. Click **Calibrator** → drop a video → **⚡ 全自动** → a `<name>.script.json` downloads;
4. Back in the window, click **Import script** and pick that file;
5. **Scan devices** → click `MIZZZEE XW` → **Open video** → **▶**.

The rest of this guide explains the details. First-time users should read
sections 1–5 in order.

---

## 1. Download and install

1. Open the repository's **Releases** page and download `cupdrive-win64.zip`.
2. Unzip into a **writable** folder, for example:
   - `D:\cupdrive\`
   - `C:\Users\<you>\Documents\cupdrive\`
   - **Not** `C:\Program Files\` — the app writes `curves\` next to the exe.
3. Run `cupdrive.exe`.

The exe is unsigned, so Windows SmartScreen warns on first launch:

> **More info → Run anyway**

This is normal. The app never connects to the internet; the local server binds
to `127.0.0.1` only.

On first launch:

- an **Edge/Chrome app window** opens, titled `cupdrive`;
- a `curves\` folder appears next to the exe, containing `example.tuned.json`;
- closing the window leaves the background process running for two idle minutes,
  then it exits. The **Quit** button in the header exits immediately.

> If no window appears: wait five seconds and check the taskbar. If it still
> does not show, open `cupdrive.log` next to the exe — the last lines contain
> `cupdrive http://127.0.0.1:PORT/`. Open that address in a browser.

---

## 2. Interface

```
┌──────────────────────────────────────────────────────────────┐
│ cupdrive  ●Connected  81% 3.00V  123 frames   Calibrator      │
│                                   Import  Scan  Mock  EN Quit │
├───────────────────────────────┬──────────────────────────────┤
│                               │ Video     [Open video]        │
│                               │ Curve     [dropdown] + graph  │
│          video                │ Parameters Intensity/Lead/Lag │
│                               │ Channels  Vib / Thrust / Shake│
│                               │ Device    [Disconnect] + list │
├───────────────────────────────┴──────────────────────────────┤
│ ▶  ──────progress──────  00:00 / 03:20          [STOP]        │
│ Vib ████████░░░░  Thrust ██░░░░░░░░  Shake ░░░░░░░░░░         │
└──────────────────────────────────────────────────────────────┘
```

**Header**

| Item | Meaning |
|---|---|
| Dot + text | Disconnected / Connected / Mock |
| `81% 3.00V` | Device battery and voltage (after connecting) |
| `123 frames` | Control frames sent |
| **Calibrator** | Opens the curve editor in a browser tab |
| **Import script** | Pick a `.script.json`, tune it, add to the curve list |
| **Scan devices** | Search for nearby BLE devices (about 6 s) |
| **Mock mode** | Full timeline without BLE |
| **EN / 中** | Switch UI language (remembered locally) |
| **Quit** | Stop the background service |

**Footer**

| Item | Meaning |
|---|---|
| ▶ / ❚❚ | Play / pause |
| Progress bar | Seek |
| **STOP** | Zero immediately (shortcut `Esc`) |
| Three bars | Actual vibration / thrust / shake output |

---

## 3. First run

### Step 1 — confirm the software works

1. Click **Mock mode** (the header shows `Mock`);
2. Pick `example.tuned.json` in the curve dropdown;
3. Click **▶**.

The intensity bars follow the 12-second example curve, without touching
hardware. This confirms timing and rendering.

### Step 2 — calibrate a curve

1. Click **Calibrator** — the browser opens the curve editor;
2. Drop a video into the page (or click the open button);
3. Click **⚡ 全自动**:
   - scans audio loudness;
   - synthesizes a performance track;
   - downloads `<video-name>.script.json`.

The file lands in your browser's download folder.

The editor's manual tools:

| Tool | Use |
|---|---|
| Brush | Draw directly on the intensity/performance tracks |
| Eraser | Remove drawn parts |
| Selection | Raise/lower a whole range |

There is also **Undo**, **Save draft** (stored in the browser), and **Export JSON**.
The editor follows the same language setting — use the `EN` / `中` button in its
header.

### Step 3 — import and tune

1. Back in the cupdrive window, click **Import script**;
2. Select the downloaded `<video-name>.script.json`;
3. The app denoises → percentile-stretches → blends → rate-limits → adds breath,
   then writes `<video-name>.tuned.json` into `curves\` and selects it.

The success toast shows point count, duration and whether motion blending was
used.

### Step 4 — open the video

Click **Open video** on the right, or drag the file into the black area.

If the curve's `source` matches the video filename, the curve is selected
automatically.

### Step 5 — connect the device

1. **Kill the phone app** (`醉清风`) completely — not just background it — and
   ideally turn off phone Bluetooth;
2. Power on the device;
3. Click **Scan devices**, wait 6 seconds;
4. Click the `MIZZZEE XW` entry marked with ★;
5. The header turns green and shows battery level.

### Step 6 — play

1. Leave **Intensity** around 85%;
2. Click **▶**;
3. **STOP** or `Esc` zeros everything immediately.

---

## 4. Parameters

| Parameter | Range | Default | Meaning |
|---|---|---|---|
| **Intensity** | 20–100% | 85% | Scales the whole curve. Start at 60–70% |
| **Lead** | -500–+1000 ms | 0 | Positive values make the device act earlier; add 100–200 ms if it feels late |
| **Thrust lag** | 0–2.0 s | 0.8 s | Delays thrust relative to vibration |

**Shortcuts**

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `Esc` | Zero immediately |

---

## 5. Channels and safety

The desktop app enables **vibration only** by default.

| Channel | Cap | Notes |
|---|---|---|
| Vibration | 55 | Enabled by default |
| Thrust | 40 | Mechanical stroke — **can pinch**; enabling asks for confirmation |
| Shake | 35 | High-frequency shake, not suction |
| Rotation | — | No hardware on this model |

Clicking **Thrust** or **Shake** shows a confirmation dialog. That is deliberate.

Five safety mechanisms:

1. **Channel whitelist** — mechanical channels stay off until explicitly enabled.
2. **Hard caps** — even if the UI sends 100, the backend clamps to 40/55/35.
3. **Slew limit** — at most 25 units/second; no jumps.
4. **Fail-safe zero** — pause, panic, disconnect, window close and process exit
   all send a zero frame first.
5. **Watchdog** — if the UI stops sending for 2 seconds, the service zeros the
   device itself.

**Testing any new device:** one channel at a time, smallest values first
(3, then 5, 8, 12), hands off the hardware.

---

## 6. FAQ

**No devices found**

- The phone app is still holding the connection (most common);
- Phone Bluetooth is still connected to the device;
- The device is off or out of battery;
- Move within one metre and scan again.

**Connecting fails**

- Another program is using the device — kill the phone app and other controllers;
- Power-cycle the device;
- Use **Mock mode** to rule out the software.

**The device moves, but weakly**

- Intensity slider is low (default 85%, try higher);
- The curve itself is flat: recalibrate and draw the intensity track higher;
- Vibration is capped at 55 by design.

**Nothing moves**

- The header must say **Connected**, not **Mock**;
- The vibration bar must be moving;
- Some devices need a physical power-button press to wake.

**No video audio**

- Do not mute the video;
- Check system volume.

**Video and curve lengths differ**

- Normal. Out-of-range sections send zero.
- Best results come from calibrating the same video you play.

**The process lingers after closing the window**

- It exits within two idle minutes;
- To exit immediately, reopen the window and click **Quit**, or end
  `cupdrive.exe` in Task Manager.

**No window appears**

- Wait five seconds;
- Open `cupdrive.log` next to the exe, find `http://127.0.0.1:PORT/`, open it in
  a browser;
- Make sure Edge or Chrome is installed (Windows 10/11 ships with Edge).

---

## 7. Run from source

Requires Python 3.9+.

```bash
pip install -r requirements.txt
python webapp.py
```

Or double-click `cupdrive.cmd` on Windows.

Options:

```bash
python webapp.py --check              # backend self-check, no window
python webapp.py --selftest           # start, exercise the API, exit
python webapp.py --no-browser         # server only
python webapp.py --port 8123          # fixed port
python webapp.py --debug              # log HTTP requests
```

Command-line playback:

```bash
python -m cupdrive.play curves/example.tuned.json --backend ble --wait
```

Build the release:

```bat
release.bat
```

Output: `release\cupdrive-win64.zip`.

---

## 8. Other devices

Only `MIZZZEE XW` has been verified byte-for-byte. For another device:

1. Capture its advertised name;
2. Confirm service / write / notify UUIDs (`tools/channel_probe.py`);
3. Update the UUID table in `cupdrive/protocol.py`;
4. **One channel at a time**, starting from the smallest value.

Protocol notes: [`protocol.md`](protocol.md). Safety design: [`safety.md`](safety.md).

---

## 9. Disclaimer

**Read this before use.** Downloading, installing or running this software means
you have read and accepted these terms. If you do not agree, do not use it.

### 9.1 As-is

The software is provided **AS IS** and **AS AVAILABLE**, without any express or
implied warranty, including merchantability, fitness for a particular purpose,
non-infringement, freedom from errors, or compatibility with any specific device
or firmware.

### 9.2 High-risk activity

This software drives hardware that moves. You accept the risk:

1. **Pinching / entanglement** — thrust and shake can catch fingers, skin, hair
   or clothing. Keep hands and body clear while running.
2. **Unpredictable strength** — the same value can feel different across
   devices, firmware and battery states. Start at the lowest value.
3. **Loss of control** — Bluetooth drops, system stalls, crashes or battery
   death can stop or continue motion. You must be able to cut power immediately.
4. **Never unattended** — do not use while asleep, intoxicated, sedated, or
   unable to free yourself.
5. **Medical implants** — vibration and electromagnetic interference may affect
   pacemakers, insulin pumps and neurostimulators. Consult a doctor.
6. **Skin and allergies** — lubricants, materials and hygiene can cause
   irritation or infection. No medical advice is provided.
7. **Children and pets** — not a toy. Adults only. Keep away from children and
   pets.
8. **Charging / water / heat** — do not use while charging, in damp
   environments, in water, or at high temperature. Follow the device vendor's
   instructions.
9. **Photosensitivity** — the UI contains moving graphics.

**If you or anyone else is injured, stop and seek medical help.** To the maximum
extent permitted by law, the authors accept no liability for personal injury;
nothing here excludes liability that cannot legally be excluded.

### 9.3 Not a medical device

This software is not a medical device and is not intended for diagnosis,
treatment, rehabilitation, contraception or any medical purpose. It provides no
medical, psychological, sexual-health or safety advice.

### 9.4 Legal use, age and consent

1. You confirm you are at least 18 (or the age of majority where you live) and
   legally competent.
2. You confirm use complies with local law, including adult-product, privacy,
   child-protection and export-control rules.
3. Use only on hardware **you own or are authorized to control**.
4. If others are involved, they must be informed, consenting, of legal age, and
   free to stop at any time. **Never** use this for non-consensual, coercive,
   covert recording, or any involvement of minors.
5. You are responsible for the environment, cleaning, disinfection and storage
   of the hardware.

### 9.5 Not affiliated with the vendor

This is an independent open-source project. It is **not affiliated with,
endorsed by, sponsored by or authorized by** MIZZZEE, 醉清风, 谜姬 or any device
vendor. All trademarks belong to their owners. Protocol information comes from
interoperability analysis of publicly available client software and Bluetooth
traffic.

### 9.6 Limitation of liability

To the maximum extent permitted by law, the authors, contributors and
maintainers are **not liable for any direct, indirect, incidental, special,
punitive, exemplary or consequential damages**, including personal injury,
death, illness, device or battery damage, data loss, lost profits, business
interruption or third-party claims, however caused and under any theory of
liability, even if advised of the possibility.

Where liability cannot be excluded, the **aggregate liability is 0 CNY** (the
software is free); where zero is not permitted, it is the amount you paid for
the software (0).

### 9.7 Indemnity

You agree to indemnify and hold harmless the authors and contributors from any
claim, damage, liability or expense (including reasonable legal fees) arising
from your use or misuse of the software, violation of these terms, or violation
of law or third-party rights.

### 9.8 Privacy

The software runs locally. Videos, curves and device data are **not uploaded**.
The web service binds to `127.0.0.1` only. There is no telemetry, account system
or analytics. You are responsible for backing up `curves\`.

### 9.9 Third-party components

The software depends on Python, bleak, numpy and other open-source components
under their respective licenses (MIT, BSD, PSF). Those licenses prevail over
this section in case of conflict.

### 9.10 Changes and acceptance

These terms may be updated with any release. Continued use means acceptance.

### 9.11 Severability

If any provision is held invalid, it is limited to the minimum extent necessary
and the remaining provisions stay in effect. This section is the entire
agreement regarding use of the software.

### 9.12 Governing law

These terms are governed by the laws of the **People's Republic of China**
(excluding conflict-of-law rules). Disputes should first be resolved in good
faith; otherwise they fall under the jurisdiction of the courts where the
maintainer resides. Mandatory consumer rights are not excluded.

---

**In one sentence:** free open-source software driving moving hardware. You are
responsible for your safety, legality and device. If unsure, don't use it.
