#!/usr/bin/env python3
"""
channel_probe.py — 逐个通道找安全阈值

目的
──────────────────────────────────────────────────────────────
对四个通道（伸缩/振动/夹吸/旋转）分别从最小值开始逐级提升，
找出"刚开始有反应"的那个值 —— 那就是该通道的安全下限。

安全约束（写死在代码里）
──────────────────────────────────────────────────────────────
  伸缩 上限 30      机械行程，不测高位
  振动 上限 50      无夹持风险
  夹吸 上限 15      ★ 有夹持风险，最保守
  旋转 上限 30

  每个值 2.5 秒，通道之间归零 2 秒，全程不并发。

用法
──────────────────────────────────────────────────────────────
  python channel_probe.py
  python channel_probe.py --only 1        # 只测振动
  python channel_probe.py --sec 3         # 每个值 3 秒

★ 测试时手离开设备。随时 Ctrl+C，会立即归零。
"""

import sys
import os
import time
import argparse
import asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mizzy_protocol as P

TESTS = [
    (P.CH_THRUST,  "伸缩 thrust",    [1, 2, 3, 5, 8, 12, 20, 30], 30),
    (P.CH_VIB,     "振动 vibration", [1, 3, 5, 8, 12, 20, 35, 50], 50),
    (P.CH_SUCTION, "夹吸 suction",   [1, 2, 3, 5, 8, 10, 12, 15], 15),
    (P.CH_ROTATE,  "旋转 rotation",  [1, 2, 3, 5, 8, 12, 20, 30], 30),
]


def zero_frame():
    return P.aa_frame(0x08, [0, 0, 0, 0, 0, 0])


def frame(ch, v):
    p = [0, 0, 0, 0]
    p[ch] = max(0, min(99, int(v)))
    return P.aa_frame(0x08, p + [0, 0])


async def run(args):
    from bleak import BleakScanner, BleakClient

    print("=" * 68)
    print("通 道 逐 个 探 测")
    print("=" * 68)
    print("  伸缩 <=30   振动 <=50   夹吸 <=15   旋转 <=30")
    print(f"  每个值 {args.sec} 秒，通道之间归零 2 秒")
    print("  * 手离开设备，随时 Ctrl+C")
    print("=" * 68)

    devs = await BleakScanner.discover(timeout=8.0)
    dev = next((d for d in devs if d.name and "MIZZZEE" in d.name.upper()), None)
    if not dev:
        print("找不到 MIZZZEE 设备")
        return 1
    print(f"\n连接 {dev.name}  {dev.address}\n")

    cl = BleakClient(dev)
    await cl.connect()
    try:
        try:
            await cl.start_notify(P.NOTIFY, lambda h, d: None)
        except Exception:
            pass

        await cl.write_gatt_char(P.WRITE, zero_frame(), response=False)
        await cl.write_gatt_char(P.WRITE, P.start(), response=False)
        await asyncio.sleep(0.5)

        t0 = time.time()
        for ch, name, seq, cap in TESTS:
            if args.only is not None and ch != args.only:
                continue

            print("\n" + "-" * 68)
            print(f"[通道 {ch}] {name}    上限 {cap}")
            print("-" * 68)

            await cl.write_gatt_char(P.WRITE, zero_frame(), response=False)
            await asyncio.sleep(2.0)

            for i, v in enumerate(seq, 1):
                if v > cap:
                    continue
                print(f"  #{i}  [{time.time()-t0:6.1f}s]  值 {v:2d}", flush=True)
                await cl.write_gatt_char(P.WRITE, frame(ch, v), response=False)
                await asyncio.sleep(args.sec)

            print("  归零")
            await cl.write_gatt_char(P.WRITE, zero_frame(), response=False)
            await asyncio.sleep(2.0)

        print("\n" + "-" * 68)
        print("全部完成")

    finally:
        try:
            await cl.write_gatt_char(P.WRITE, zero_frame(), response=False)
            await asyncio.sleep(0.2)
            await cl.write_gatt_char(P.WRITE, P.halt(), response=False)
        except Exception:
            pass
        try:
            await cl.disconnect()
        except Exception:
            pass
        print("已归零并断开")

    print("""
================================================================
请回报每个通道「第一次看到/感觉到动作」的值，例如：

  伸缩:  3
  振动:  1
  夹吸:  5
  旋转:  8

没反应的写「无」。有了这组数字，就能给每个通道设定
安全的起始值和工作区间。
================================================================
""")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, choices=[0, 1, 2, 3], default=None)
    ap.add_argument("--sec", type=float, default=2.5)
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
