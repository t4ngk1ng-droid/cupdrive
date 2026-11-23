#!/usr/bin/env python3
"""
service.py — 无 GUI 的核心服务：BLE + 曲线 + 加工

桌面壳（webapp.py）和测试都调这里。不 import 任何 GUI 库，
所以 PyInstaller 打包时不会带 pythonnet。

安全模型
──────────────────────────────────────────────────────────────
1. 播放会话有代号（gen）。begin() 签发，暂停/急停/改参数/断连
   都会让它失效；旧代号的 send 直接被丢弃。
2. BLE 写入只有一个执行者：asyncio loop。HTTP 线程只负责把
   最新一帧投递进去，不并发写。
3. 看门狗：播放中超过 2 秒没有新帧，自动归零。防止页面崩溃、
   浏览器被杀后设备停在最后一个强度。
"""

import os
import re
import json
import glob
import time
import tempfile
import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeout

from . import protocol as P
from . import ble as BLE
from . import tune as TUNE
from .safety import MultiGuard

SLEW = 25.0                 # 固定限速，不接受前端调整
DEFAULT_CHANS = "1"
WATCHDOG_S = 2.0            # 播放中无新帧多久自动归零


class BleWorker:
    """独立线程跑 asyncio loop；bleak 的协程都投递进去。"""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.link = BLE.BleLink()
        self.mock = False
        self.caps = {P.CH_VIB: BLE.HARD_CAPS[P.CH_VIB]}
        self.guard = MultiGuard(self.caps, slew_per_sec=SLEW)

        self.sent = 0               # 请求计数（mock 时就是帧数）
        self.last = [0, 0, 0, 0]
        self.frame_hex = ""
        self.error = ""
        self._scan_cache = {}
        self._lock = threading.Lock()

        # 播放会话
        self._gen = 0
        self._active = False
        self._last_send = 0.0

        threading.Thread(target=self._watchdog, daemon=True).start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def call(self, coro, timeout=45):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return fut.result(timeout)
        except FutureTimeout:
            # 超时只停止等待；取消任务，避免迟到结果改状态。
            fut.cancel()
            raise

    # ── 看门狗 ────────────────────────────────────────────────
    def _watchdog(self):
        while True:
            time.sleep(0.5)
            frame = None
            with self._lock:
                if (self._active and not self.mock and self.link.connected
                        and time.time() - self._last_send > WATCHDOG_S):
                    self._active = False
                    self._gen += 1
                    self.guard = MultiGuard(self.caps, slew_per_sec=SLEW)
                    self.last = [0, 0, 0, 0]
                    frame = P.aa_frame(0x08, [0, 0, 0, 0, 0, 0])
            if frame is not None:
                try:
                    asyncio.run_coroutine_threadsafe(self.link.send(frame), self.loop)
                except Exception:
                    pass

    # ── 扫描 ──────────────────────────────────────────────────
    async def _scan(self, sec):
        sec = max(1.0, min(float(sec), 20.0))
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
        with self._lock:
            self.mock = False
            self.error = ""
            self._gen += 1
            self._active = False
            self.guard = MultiGuard(self.caps, slew_per_sec=SLEW)
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
        with self._lock:
            self.mock = True
            self.error = ""
            self._gen += 1
            self._active = False
            self.guard = MultiGuard(self.caps, slew_per_sec=SLEW)
            self.last = [0, 0, 0, 0]
        return {"ok": True}

    # ── 断开 ──────────────────────────────────────────────────
    async def _disconnect(self):
        await self.link.close()
        with self._lock:
            self.mock = False
            self._active = False
            self._gen += 1

    def disconnect(self):
        try:
            self.call(self._disconnect(), timeout=15)
        except Exception:
            pass
        self.last = [0, 0, 0, 0]
        return {"ok": True}

    # ── 参数 / 播放会话 ───────────────────────────────────────
    def configure(self, chans=DEFAULT_CHANS):
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
            self._gen += 1
            self._active = False
            self.guard = MultiGuard(caps, slew_per_sec=SLEW)
        return {"ok": True, "caps": caps,
                "names": {ch: BLE.CH_NAMES.get(ch, str(ch)) for ch in caps}}

    def begin(self):
        """签发一次播放会话。之前的代号立即失效。"""
        with self._lock:
            self._gen += 1
            self._active = True
            self._last_send = time.time()
            self.guard = MultiGuard(self.caps, slew_per_sec=SLEW)
            return {"ok": True, "gen": self._gen}

    # ── 发送 ──────────────────────────────────────────────────
    def send(self, v0=0.0, v1=0.0, v2=0.0, v3=0.0, gen=0):
        # 没连设备也不是 mock 时，不要假装发了：不消耗护栏、不动强度条。
        if not self.mock and not self.link.connected:
            return False
        values = [v0, v1, v2, v3]
        with self._lock:
            if gen and gen != self._gen:
                return False        # 旧会话的帧，丢弃
            if gen:
                self._last_send = time.time()
            pcts = {ch: max(0.0, min(100.0, float(values[ch]))) for ch in self.caps}
            frame = self.guard.set(pcts)
            self.last = list(frame[3:7])
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
        """立即归零：先让会话失效，再发零帧。"""
        with self._lock:
            self._gen += 1
            self._active = False
            self.guard = MultiGuard(self.caps, slew_per_sec=SLEW)
            self.last = [0, 0, 0, 0]
        try:
            self.call(self._panic(), timeout=5)
        except Exception as e:
            self.error = "归零失败: " + str(e)
        return {"ok": True,
                "writes_ok": self.link.writes_ok,
                "writes_fail": self.link.writes_fail}

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
            "sent": self.sent if self.mock else self.link.writes_ok,
            "last": list(self.last),
            "battery": self.link.battery,
            "volt": self.link.volt,
            "error": self.error or self.link.last_error,
            "caps": {str(ch): cap for ch, cap in self.caps.items()},
            "frame": self.frame_hex,
            "gen": self._gen,
            "active": self._active,
            "writes_ok": self.link.writes_ok,
            "writes_fail": self.link.writes_fail,
        }

    def shutdown(self):
        try:
            self.call(self._disconnect(), timeout=10)
        except Exception:
            pass
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=3)
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
        self.curves_dir = os.path.abspath(curves_dir)
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

    def set_params(self, chans=DEFAULT_CHANS):
        return self.ble.configure(chans)

    def begin(self):
        return self.ble.begin()

    def send(self, v0=0.0, v1=0.0, v2=0.0, v3=0.0, gen=0):
        return self.ble.send(v0, v1, v2, v3, gen)

    def stop(self):
        return self.ble.panic()

    def panic(self):
        return self.ble.panic()

    # ── 曲线 ──────────────────────────────────────────────────
    def _curve_path(self, name_or_path):
        """只接受 curves/ 下的普通文件，拒绝链接和路径逃逸。"""
        name = os.path.basename(str(name_or_path))
        if not name.lower().endswith(".json") or name.startswith("."):
            raise ValueError("不是 JSON 曲线")
        root = os.path.realpath(self.curves_dir)
        full = os.path.join(root, name)
        if os.path.islink(full):
            raise ValueError("不允许符号链接")
        target = os.path.realpath(full)
        if os.path.dirname(target) != root or not os.path.isfile(target):
            raise ValueError("只允许加载 curves/ 下的曲线")
        return target

    def list_curves(self):
        items = []
        for p in glob.glob(os.path.join(self.curves_dir, "*.json")):
            try:
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                b = d.get("b") or []
                if not b:
                    continue
                hz = float(d.get("hz", 10) or 10)
                if not (1 <= hz <= 100):
                    continue
                items.append({
                    "path": p,
                    "name": os.path.basename(p),
                    "duration": float(d.get("duration") or (len(b) / hz)),
                    "points": len(b),
                    "hz": hz,
                    "source": d.get("source", ""),
                    "mtime": os.path.getmtime(p),
                })
            except Exception:
                continue
        items.sort(key=lambda x: (-x["mtime"], x["name"]))
        return items

    def load_curve(self, path):
        target = self._curve_path(path)
        with open(target, encoding="utf-8") as f:
            d = json.load(f)
        b = d.get("b") or []
        if not isinstance(b, list) or not b:
            raise ValueError("曲线为空")
        hz = float(d.get("hz", 10) or 10)
        if not (1 <= hz <= 100):
            raise ValueError("非法采样率")
        return {
            "path": target,
            "name": os.path.basename(target),
            "b": b,
            "hz": hz,
            "duration": float(d.get("duration") or (len(b) / hz)),
            "source": d.get("source", ""),
        }

    def import_data(self, name, text):
        """标定台导出的 script.json 内容 → 加工 → curves/"""
        try:
            d = json.loads(text)
            if not isinstance(d, dict):
                return {"ok": False, "error": "不是 JSON 对象"}
            a = d.get("a")
            if not isinstance(a, list) or len(a) < 2:
                return {"ok": False, "error": "不是标定台脚本（缺 a 轨）"}
            hz = float(d.get("hz", 10) or 10)
            if not (1 <= hz <= 100):
                return {"ok": False, "error": "采样率不合法"}
            if len(a) > 2_000_000:
                return {"ok": False, "error": "曲线太长"}

            stem = _safe_stem(name)
            dest = os.path.join(self.curves_dir, stem + ".tuned.json")

            fd, tmp_in = tempfile.mkstemp(
                prefix=".incoming-", suffix=".json", dir=self.curves_dir)
            fd2, tmp_out = tempfile.mkstemp(
                prefix=".out-", suffix=".json", dir=self.curves_dir)
            os.close(fd2)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(d, f)
                out, base, b, has_mv = TUNE.tune_file(tmp_in, tmp_out)
                os.replace(tmp_out, dest)       # 原子发布，同名覆盖
            finally:
                for p in (tmp_in, tmp_out):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

            return {
                "ok": True,
                "path": dest,
                "name": os.path.basename(dest),
                "points": len(b),
                "duration": len(b) / hz,
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
