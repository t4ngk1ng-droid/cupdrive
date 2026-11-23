#!/usr/bin/env python3
"""
play.py — 把曲线播放成设备动作（多通道 + 安全护栏）

设备实测通道（MIZZZEE XW）
──────────────────────────────────────────────────────────────
    0  伸缩     上限 40（实测手感的甜点值）
    1  振动     上限 55
    2  抖动     上限建议 35
    3  旋转     本机无硬件（会被拒绝）

用法
──────────────────────────────────────────────────────────────
  python play.py cupdrive/out/tuned.json --backend ble --wait
  python play.py cupdrive/out/tuned.json --backend ble --wait --channels 0,1
  python play.py cupdrive/out/tuned.json --backend ble --wait --channels 0,1,2

参数
──────────────────────────────────────────────────────────────
  --channels 0,1,2     启用哪些通道（默认 1 = 只振动；3 = 旋转，本机无硬件，会被拒绝）
  --thrust-cap N       伸缩上限（默认 40）
  --vib-cap N          振动上限（默认 55）
  --shake-cap N        抖动上限（默认 35）
  --lag S              伸缩相对振动的滞后秒数（默认 0.8）
"""

import sys
import os
import json
import time
import argparse
import asyncio

from . import protocol as P
from .safety import MultiGuard

CH_KEYS = {"0": P.CH_THRUST, "1": P.CH_VIB, "2": P.CH_SUCTION, "3": P.CH_ROTATE}
CH_NAMES = {P.CH_THRUST: "伸缩", P.CH_VIB: "振动",
            P.CH_SUCTION: "抖动", P.CH_ROTATE: "旋转"}


class MockBackend:
    async def connect(self): return True
    async def send(self, frame): self.last = frame
    async def close(self): pass


class BleBackend:
    def __init__(self, dev_name):
        self.dev_name = dev_name
        self.client = None
        self.wr = None

    async def connect(self):
        from bleak import BleakScanner, BleakClient
        print(f"[ble] 扫描 {self.dev_name} ...")
        devs = await BleakScanner.discover(timeout=8.0)
        dev = None
        for d in devs:
            if d.name and self.dev_name.upper() in d.name.upper():
                dev = d
                break
        if dev is None:
            print(f"[ble] 找不到 {self.dev_name}")
            for d in devs:
                if d.name:
                    print(f"        {d.name}  {d.address}")
            return False

        _, wr, nt = P.resolve(dev.name)
        print(f"[ble] {dev.name}  {dev.address}")
        self.client = BleakClient(dev)
        await self.client.connect()
        self.wr = wr

        def on_notify(_h, data):
            info = P.parse_notify(bytes(data))
            if info and info.get("power") is not None:
                print(f"\n  [设备] 电量 {info['power']:.1f}%  {info['volt']:.2f}V")

        try:
            await self.client.start_notify(nt, on_notify)
        except Exception:
            pass

        await self.client.write_gatt_char(self.wr,
                                          P.aa_frame(0x08, [0, 0, 0, 0, 0, 0]),
                                          response=False)
        await asyncio.sleep(0.2)
        await self.client.write_gatt_char(self.wr, P.start(), response=False)
        await asyncio.sleep(0.3)
        print("[ble] 已归零并启动")
        return True

    async def send(self, frame):
        if not self.client or not self.client.is_connected:
            return
        await self.client.write_gatt_char(self.wr, frame, response=False)

    async def close(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        print("[ble] 已断开")


def bar(v, width=24):
    n = int(round(max(0, min(100, v)) / 100 * width))
    return "█" * n + "·" * (width - n)


def fmt_t(t):
    m, s = divmod(max(0, t), 60)
    return f"{int(m):02d}:{s:04.1f}"


async def run(args):
    with open(args.script, encoding="utf-8") as f:
        d = json.load(f)
    curve = d["b"]
    hz = d.get("hz", 10)
    dur = d.get("duration") or len(curve) / hz
    n = len(curve)
    if args.limit:
        dur = min(dur, args.limit)

    caps = {}
    for tok in args.channels.split(","):
        tok = tok.strip()
        if tok not in CH_KEYS:
            continue
        ch = CH_KEYS[tok]
        if ch == P.CH_ROTATE:
            print("拒绝通道 3（旋转）：本机没有该执行机构")
            continue
        caps[ch] = {P.CH_THRUST: args.thrust_cap,
                    P.CH_VIB: args.vib_cap,
                    P.CH_SUCTION: args.shake_cap}[ch]
    if not caps:
        print("没有可用通道")
        return 1

    mg = MultiGuard(caps, slew_per_sec=args.slew)
    lag_frames = int(args.lag * hz)

    print("=" * 70)
    print(f"脚本   {os.path.basename(args.script)}")
    print(f"时长   {fmt_t(dur)}   {n} 点 @ {hz}Hz")
    print(f"后端   {args.backend}   {args.hz}Hz   缩放 {args.scale}   gamma {args.gamma}")
    print(f"通道   {mg.describe()}")
    if P.CH_THRUST in caps:
        print(f"错位   伸缩比振动滞后 {args.lag:.2f} 秒")
    print("=" * 70)

    if args.backend == "ble":
        be = BleBackend(args.device)
        if not await be.connect():
            return 1
    else:
        be = MockBackend()
        await be.connect()

    if args.wait:
        input("\n按回车开始（同时让视频开始播放）...")
        print()

    t0 = time.time() - args.start
    period = 1.0 / args.hz
    next_tick = time.time()
    last_show = 0

    try:
        while True:
            now = time.time()
            t = now - t0
            if t >= dur:
                break
            idx = max(0, min(int(t * hz), n - 1))
            base = curve[idx]

            target = {}
            for ch in caps:
                v = curve[max(0, idx - lag_frames)] if (ch == P.CH_THRUST and lag_frames > 0) else base
                v = v * args.scale
                if args.gamma != 1.0:
                    v = 100.0 * (max(0.0, min(100.0, v)) / 100.0) ** args.gamma
                target[ch] = v

            frame = mg.set(target)
            await be.send(frame)

            if now - last_show >= 0.5:
                last_show = now
                fb = frame[3:7]
                cells = "  ".join(f"{CH_NAMES.get(ch, ch)}{fb[ch]:3d}" for ch in caps)
                print(f"\r{fmt_t(t)} |{bar(base)}| {base:5.1f}%  {cells}  ",
                      end="", flush=True)

            next_tick += period
            sleep = next_tick - time.time()
            if sleep > 0:
                await asyncio.sleep(sleep)
            else:
                next_tick = time.time()

    except KeyboardInterrupt:
        print("\n\n中断")
    finally:
        try:
            await be.send(P.aa_frame(0x08, [0, 0, 0, 0, 0, 0]))
            await asyncio.sleep(0.15)
            await be.send(P.halt())
        except Exception:
            pass
        await be.close()
        print(f"\r{' ' * 78}")
        print("安全摘要:", mg.summary())
        print("结束")


def main():
    ap = argparse.ArgumentParser(description="把曲线播放成设备动作")
    ap.add_argument("script")
    ap.add_argument("--backend", choices=["mock", "ble"], default="mock")
    ap.add_argument("--device", default=P.DEFAULT_NAME)
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--channels", default="1")
    ap.add_argument("--thrust-cap", type=int, default=40)
    ap.add_argument("--vib-cap", type=int, default=55)
    ap.add_argument("--shake-cap", type=int, default=35)
    ap.add_argument("--lag", type=float, default=0.8)
    ap.add_argument("--max", type=int, default=80,
                    help="兼容保留：通道 3（旋转）已被拒绝，此参数不再生效")
    ap.add_argument("--slew", type=float, default=25.0)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--limit", type=float, default=0)
    ap.add_argument("--wait", action="store_true")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
