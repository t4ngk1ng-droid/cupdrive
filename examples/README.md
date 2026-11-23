# Examples

`script.example.json` is a 12-second synthetic curve in the format produced by
`web/index.html` and consumed by `cupdrive/tune.py` and `cupdrive/play.py`.

The desktop app tunes it automatically on first launch
(`curves/example.tuned.json`), so the window is never empty.

Preview it without hardware:

```bash
python -m cupdrive.play examples/script.example.json --limit 12 --hz 10
```

Or through the desktop shell:

```bash
python webapp.py
```

Then click **Mock 模式** in the window.
