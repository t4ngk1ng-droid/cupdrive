# Publishing

## 1. Create the repo

```bash
cd cupdrive-github
git init -b main          # 空仓库里不能先 git branch -M main
git add -A
git commit -m "initial commit: video-to-device pipeline with reverse-engineered BLE protocol"
git remote add origin https://github.com/<user>/cupdrive.git
git push -u origin main
```

Or with `gh`:

```bash
gh repo create cupdrive --public --source=. --remote=origin --push
```

Repo description:

> Turn any video into Bluetooth toy motion. Offline browser analysis,
> rate-limited curves, reverse-engineered BLE protocol, hard safety caps.

Topics:

```
ble  bluetooth  reverse-engineering  haptics  video-analysis  numpy  bleak
```

## 2. Before you push

- [ ] `python webapp.py --check` passes
- [ ] `python webapp.py --selftest --no-browser` prints `[selftest] OK`
- [ ] `python webapp.py --no-browser --port 8123` then
      `curl -o /dev/null -w "%{http_code}" http://127.0.0.1:8123/api/status` → `403`
- [ ] No real MAC addresses (`grep -r "50:F8" .` should be empty)
- [ ] No personal paths (`grep -r "Lenovo" .`)
- [ ] No large binaries (`du -sh .` — source under 400 KB; `dist/`, `release/`, `curves/` ignored)
- [ ] `curves/` and `*.script.json` are ignored
- [ ] `examples/script.example.json` has no real filename in `source`

## 3. Build the release

```bat
release.bat
```

Produces `release\cupdrive-win64.zip` (≈21 MB compressed, Python bundled, no
installer). Upload it with the release notes:

```bash
gh release create v0.3.0 release/cupdrive-win64.zip ^
  --title "cupdrive v0.3.0" ^
  --notes-file docs/release-notes.md
```

Users download the zip from the Releases page, unzip anywhere writable, and
double-click `cupdrive.exe`. The UI opens in an app-mode Edge/Chrome window.
