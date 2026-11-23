## cupdrive v0.3.0

Turn any video into Bluetooth toy motion — offline, no account.

**Download `cupdrive-win64.zip`, unzip, run `cupdrive.exe`. No Python required.**

### What's new

- Session-guarded playback: stale frames are dropped after pause, panic or reconnect
- 2-second watchdog zeros the device if the UI stops sending
- Token-protected local API (Host/Origin checks; 403 without token)
- BLE write accounting; connect fails if init frames fail
- Short curves keep their length after tuning
- Device names rendered as text (no HTML injection)

### Read first

- [中文使用说明](https://github.com/t4ngk1ng-droid/cupdrive/blob/main/docs/usage.md) — calibration, connection, parameters, FAQ
- Windows SmartScreen: **More info → Run anyway** (unsigned exe)

Windows 10/11 x64.
