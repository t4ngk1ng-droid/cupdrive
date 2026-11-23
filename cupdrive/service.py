#!/usr/bin/env python3
"""
service.py — 无 GUI 的核心服务：BLE + 曲线 + 加工

桌面壳（webapp.py）和测试都调这里。不 import 任何 GUI 库，
所以 PyInstaller 打包时不会带 pythonnet。
"""

import os
import re
import json
import glob
import time
import asyncio
import threading

from . import protocol as P
from . import ble as BLE
from . import tune as TUNE
from .safety import MultiGuard

SLEW = 25.0
DEFAULT_CHANS = "1"


class BleWorker:
    """独立线程跑 asyncio loop；bleak 的协程都投递进去。"""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.link = BLE.BleLink()
        self.mock = False
        self.caps = {P.CH_VIB: BLE.HARD_CAPS[P.CH_VIB]}
        self.slew = SLEW
        self.guard = MultiGuard(self.caps, slew_per_sec=self.slew)

        self.sent = 0
        self.last = [0, 0, 0, 0]
        self.frame_hex = ""
        self.error = ""
        self._scan_cache = {}
        self._lock = threading.Lock()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, coro, timeout=45):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # ── 扫描 ──────────────────────────────────────────────────
    async def _scan(self, sec):
        items = await BLE.scan_devices(sec)
        with self._lock:
            for it in items:
                if it["name"]:
                    self._scan_cache[it["address"]] = it["dev"]
                    self._scan_cache[it["name"]] = it["dev"]
        return [{k: v for k, v in it.items() if k != "dev"} for it in items]

    def scan(self, sec=6):
        try:
            return {"ok": True,
                    "devices": self.call(self._scan(sec), timeout=sec + 20)}
        except Exception as e:
            self.error = str(e)
            return {"ok": False, "error": str(e), "devices": []}

    # ── 连接 ──────────────────────────────────────────────────
    async def _connect(self, address, name):
        with self._lock:
            dev = self._scan_cache.get(address) or self._scan_cache.get(name)
        if dev is None:
            items = await BLE.scan_devices(8.0)
            for it in items:
                if it["address"] == address or (name and it["name"].lower() == name.lower()):
                    dev = it["dev"]
                    break
        if dev is None:
            raise RuntimeError("找不到设备。手机 App 还占着连接吗？先彻底杀掉 App 再试。")

        await self.link.close()
        await self.link.connect(dev, name)
        self.mock = False
        self.error = ""
        self.guard = MultiGuard(self.caps, slew_per_sec=self.slew)
        self.last = [0, 0, 0, 0]
        return True

    def connect(self, address, name=""):
        try:
            self.call(self._connect(address, name))
            return {"ok": True, "device": self.link.device or name}
        except Exception as e:
            self.error = str(e)
            return {"ok": False, "error": str(e)}

    def use_mock(self):
        try:
            self.call(self._disconnect())
        except Exception:
            pass
        self.mock = True
        self.error = ""
        self.guard = MultiGuard(self.caps, slew_per_sec=self.slew)
        self.last = [0, 0, 0, 0]
        return {"ok": True}

    # ── 断开 ──────────────────────────────────────────────────
    async def _disconnect(self):
        await self.link.close()
        self.mock = False

    def disconnect(self):
        try:
            self.call(self._disconnect(), timeout=15)
        except Exception:
            pass
        self.last = [0, 0, 0, 0]
        return {"ok": True}

    # ── 参数 ──────────────────────────────────────────────────
    def configure(self, chans=DEFAULT_CHANS, slew=SLEW):
        caps = {}
        for tok in str(chans).split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                ch = int(tok)
            except ValueError:
                continue
            cap = BLE.HARD_CAPS.get(ch, 0)
            if cap > 0:
                caps[ch] = cap
        if not caps:
            caps = {P.CH_VIB: BLE.HARD_CAPS[P.CH_VIB]}
        with self._lock:
            self.caps = caps
            self.slew = max(1.0, float(slew))
            self.guard = MultiGuard(caps, slew_per_sec=self.slew)
        return {"ok": True, "caps": caps,
                "names": {ch: BLE.CH_NAMES.get(ch, str(ch)) for ch in caps}}

    # ── 发送 ──────────────────────────────────────────────────
    def _frame_now(self, values):
        with self._lock:
            pcts = {ch: max(0.0, min(100.0, float(values[ch]))) for ch in self.caps}
            frame = self.guard.set(pcts)
        return frame, list(frame[3:7])

    def send(self, v0=0.0, v1=0.0, v2=0.0, v3=0.0):
        values = [v0, v1, v2, v3]
        frame, actual = self._frame_now(values)
        self.last = actual
        self.frame_hex = frame.hex()
        self.sent += 1

        if self.mock:
            return True
        if not self.link.connected:
            return False
        try:
            asyncio.run_coroutine_threadsafe(self.link.send(frame), self.loop)
            return True
        except Exception as e:
            self.error = str(e)
            return False

    def panic(self):
        try:
            self.call(self._panic(), timeout=5)
        except Exception:
            pass
        with self._lock:
            self.guard = MultiGuard(self.caps, slew_per_sec=self.slew)
        self.last = [0, 0, 0, 0]
        return {"ok": True}

    async def _panic(self):
        zero = P.aa_frame(0x08, [0, 0, 0, 0, 0, 0])
        if self.link.connected:
            await self.link.send(zero)

    # ── 状态 ──────────────────────────────────────────────────
    def status(self):
        return {
            "connected": self.mock or self.link.connected,
            "mock": self.mock,
            "device": "mock" if self.mock else (self.link.device or ""),
            "sent": self.sent,
            "last": list(self.last),
            "battery": self.link.battery,
            "volt": self.link.volt,
            "error": self.error,
            "caps": {str(ch): cap for ch, cap in self.caps.items()},
            "frame": self.frame_hex,
        }

    def shutdown(self):
        try:
            self.call(self._disconnect(), timeout=10)
        except Exception:
            pass


def _safe_stem(name):
    stem = os.path.splitext(os.path.basename(str(name)))[0]
    if stem.lower().endswith(".script"):
        stem = stem[:-7]
    stem = re.sub(r"[^\w一-鿿.-]+", "_", stem).strip("._")
    return stem or "curve"


class Core:
    """对桌面壳暴露的全部能力。每个方法都返回可 JSON 序列化的 dict。"""

    def __init__(self, curves_dir, examples_dir):
        self.curves_dir = curves_dir
        self.examples_dir = examples_dir
        self.ble = BleWorker()
        self.last_request = time.time()
        os.makedirs(self.curves_dir, exist_ok=True)

    def touch(self):
        self.last_request = time.time()

    # ── 设备 ──────────────────────────────────────────────────
    def scan(self, sec=6):
        return self.ble.scan(sec)

    def connect(self, address, name=""):
        return self.ble.connect(address, name)

    def mock(self):
        return self.ble.use_mock()

    def disconnect(self):
        return self.ble.disconnect()

    def status(self):
        return self.ble.status()

    def set_params(self, chans=DEFAULT_CHANS, slew=SLEW):
        return self.ble.configure(chans, slew)

    def send(self, v0=0.0, v1=0.0, v2=0.0, v3=0.0):
        return self.ble.send(v0, v1, v2, v3)

    def stop(self):
        return self.ble.panic()

    def panic(self):
        return self.ble.panic()

    # ── 曲线 ──────────────────────────────────────────────────
    def list_curves(self):
        items = []
        for p in glob.glob(os.path.join(self.curves_dir, "*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                b = d.get("b") or []
                if not b:
                    continue
                items.append({
                    "path": p,
                    "name": os.path.basename(p),
                    "duration": float(d.get("duration") or (len(b) / d.get("hz", 10))),
                    "points": len(b),
                    "hz": d.get("hz", 10),
                    "source": d.get("source", ""),
                    "mtime": os.path.getmtime(p),
                })
            except Exception:
                continue
        items.sort(key=lambda x: (-x["mtime"], x["name"]))
        return items

    def load_curve(self, path):
        path = os.path.abspath(path)
        if not path.lower().endswith(".json"):
            raise ValueError("不是 JSON 曲线")
        if os.path.normcase(os.path.dirname(path)) != \
                os.path.normcase(os.path.abspath(self.curves_dir)):
            raise ValueError("只允许加载 curves/ 下的曲线")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        b = d.get("b") or []
        return {
            "path": path,
            "name": os.path.basename(path),
            "b": b,
            "hz": d.get("hz", 10),
            "duration": float(d.get("duration") or (len(b) / d.get("hz", 10))),
            "source": d.get("source", ""),
        }

    def import_data(self, name, text):
        """标定台导出的 script.json 内容 → 加工 → curves/"""
        try:
            d = json.loads(text)
            if not isinstance(d.get("a"), list) or not d["a"]:
                return {"ok": False, "error": "不是标定台脚本（缺 a 轨）"}
            stem = _safe_stem(name)
            tmp = os.path.join(self.curves_dir, ".incoming.script.json")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            try:
                dest = os.path.join(self.curves_dir, stem + ".tuned.json")
                out, base, b, has_mv = TUNE.tune_file(tmp, dest)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            return {
                "ok": True,
                "path": out,
                "name": os.path.basename(out),
                "points": len(b),
                "duration": len(b) / float(d.get("hz", 10) or 10),
                "has_mv": bool(has_mv),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def import_script(self, path):
        """本地路径版本，给 CLI / 测试用"""
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            return self.import_data(os.path.basename(path), text)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── 其他 ──────────────────────────────────────────────────
    def ensure_example(self):
        """首次运行生成一条可预览曲线，保证界面不是空的。"""
        if glob.glob(os.path.join(self.curves_dir, "*.json")):
            return None
        src = os.path.join(self.examples_dir, "script.example.json")
        if not os.path.isfile(src):
            return None
        try:
            out, base, b, _ = TUNE.tune_file(
                src, os.path.join(self.curves_dir, "example.tuned.json"))
            return out
        except Exception:
            return None

    def shutdown(self):
        self.ble.shutdown()
