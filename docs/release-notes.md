## cupdrive v0.3.2

Turn any video into Bluetooth toy motion — offline, no account.

**Download `cupdrive-win64.zip`, unzip, run `cupdrive.exe`. No Python required.**

### What's new / 更新

- **Calibrator is bilingual too** — same `EN` / `中` switch as the desktop app.
  **标定台也支持中英切换**——和桌面版共享语言设置。
- **GitHub docs** — Chinese and English README, user guide and release notes.
  **GitHub 文档中英双版**——README、使用说明和本页都提供中英。
- **Playback hardening** — session guard, 2-second watchdog, token-protected API,
  BLE write accounting. Stale frames are dropped after pause, panic or reconnect.
  **播放安全加固**——会话代号、2 秒看门狗、令牌保护 API、BLE 写入计数；
  暂停、急停、重连后旧帧直接丢弃。
- **Short curves** keep their length after tuning.
  **短曲线**加工后不再被平滑窗口拉长。

### Read first / 先读

- [中文使用说明](https://github.com/t4ngk1ng-droid/cupdrive/blob/main/docs/usage.md)
- [English guide](https://github.com/t4ngk1ng-droid/cupdrive/blob/main/docs/usage.en.md)
- Windows SmartScreen: **More info → Run anyway** (unsigned exe).
  首次启动 SmartScreen：**更多信息 → 仍要运行**。

Windows 10/11 x64.
