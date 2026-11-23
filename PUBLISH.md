# Publishing

```bash
cd cupdrive-github
git init -b main          # 空仓库里不能先 git branch -M main
git add -A
git commit -m "initial commit: video-to-device pipeline with reverse-engineered BLE protocol"
```

Create an empty repo on GitHub first, then:

```bash
git remote add origin https://github.com/<your-name>/cupdrive.git
git push -u origin main
```

Suggested repo description:

> Turn any video into Bluetooth toy motion. Browser-based analysis, rate-limited
> envelope, reverse-engineered MIZZZEE protocol, safety guard.

Suggested topics:

```
ble  bluetooth  reverse-engineering  haptics  video-analysis  numpy  bleak
```

## Before you push

- [ ] `python webapp.py --check` passes
- [ ] `python webapp.py --selftest --no-browser` prints `[selftest] OK`
- [ ] No real MAC addresses (`grep -r "50:F8" .` should be empty)
- [ ] No personal paths (`grep -r "Lenovo" .`)
- [ ] No large binaries (`du -sh .` — source under 300 KB; `dist/`, `release/`, `curves/` are ignored)
- [ ] `curves/` and `*.script.json` are ignored
- [ ] `examples/script.example.json` has no real filename in `source`

## Release

```bat
release.bat
```

Produces `release\cupdrive-win64.zip` (≈54 MB, Python bundled, no installer).
Upload it:

```bash
gh release create v0.2.0 release/cupdrive-win64.zip ^
  --title "cupdrive v0.2.0" ^
  --notes "Windows x64. Unzip and run cupdrive.exe. No Python required."
```

Users download the zip from the Releases page, unzip anywhere writable, and
double-click `cupdrive.exe`. The UI opens in an app-mode Edge/Chrome window.
