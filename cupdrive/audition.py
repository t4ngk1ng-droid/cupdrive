#!/usr/bin/env python3
"""
make_audition.py — 把曲线渲染成音频，让耳朵先听一遍

用途: 在没有设备的情况下，判断"设备跟着这条曲线动"是什么感觉。

原理:
    生成一段低频嗡鸣 (110Hz + 220Hz 泛音 + 低通噪声),
    音量包络 = 曲线值^1.8  (非线性, 让强弱对比接近触觉)

输出:
    listen_B.wav   表现轨 → 设备实际会怎么动 (听这个)
    listen_A.wav   强度轨 → 素材本身的激烈程度 (对照用)

用法:
    python make_audition.py cupdrive/out/tuned.json
"""

import sys
import os
import json
import wave

import numpy as np

SR = 16000
FADE = 0.4       # 首尾淡入淡出秒数
GAIN_EXP = 1.8   # 振幅非线性指数


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d, np.asarray(d["a"], float), np.asarray(d["b"], float)


def render(curve, hz, dur_s, sr=SR):
    """把 10Hz 的曲线升采样成音频，并生成对应音量的嗡鸣"""
    n_audio = int(dur_s * sr)
    t = np.arange(n_audio) / sr

    # 曲线 → 音频采样率 (线性插值)
    src_t = np.arange(len(curve)) / hz
    env = np.interp(t, src_t, curve) / 100.0
    env = np.clip(env, 0, 1)

    # 非线性振幅, 让弱更弱、强更强
    amp = np.power(env, GAIN_EXP)

    # 基频 + 二次谐波 (低频嗡鸣, 耳机里也能听清)
    # 加极轻微的频率漂移, 避免死板
    drift = 1.0 + 0.004 * np.sin(2 * np.pi * 0.13 * t)
    sig = (0.62 * np.sin(2 * np.pi * 110 * t * drift)
           + 0.22 * np.sin(2 * np.pi * 220 * t * drift)
           + 0.10 * np.sin(2 * np.pi * 330 * t * drift))

    # 低通噪声做质感
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 1, n_audio)
    k = 180
    kern = np.ones(k) / k
    noise = np.convolve(noise, kern, mode="same")
    noise = noise / (np.abs(noise).max() + 1e-9)

    out = (sig * 0.85 + noise * 0.18) * amp

    # 首尾淡入淡出
    f = int(FADE * sr)
    if f > 0 and n_audio > 2 * f:
        ramp = np.linspace(0, 1, f)
        out[:f] *= ramp
        out[-f:] *= ramp[::-1]

    # 归一化到 -3dBFS
    peak = np.abs(out).max()
    if peak > 1e-9:
        out = out / peak * 0.71
    return out


def write_wav(path, data, sr=SR):
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def stats(x, nm):
    ps = np.percentile(x, [10, 50, 90])
    return f"{nm}: mean={x.mean():5.1f} std={x.std():5.2f} p10={ps[0]:4.0f} p50={ps[1]:4.0f} p90={ps[2]:4.0f}"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    d, a, b = load(path)
    hz = d.get("hz", 10)
    dur = d.get("duration") or (len(a) / hz)
    outdir = os.path.dirname(os.path.abspath(path))

    print("=" * 60)
    print(f"时长 {dur:.1f}s  采样率 {SR}Hz")
    print(" ", stats(a, "A"))
    print(" ", stats(b, "B"))

    for name, curve in (("A", a), ("B", b)):
        sig = render(curve, hz, dur)
        p = os.path.join(outdir, f"listen_{name}.wav")
        write_wav(p, sig)
        mb = os.path.getsize(p) / 1048576
        print(f"  → {p}  ({mb:.1f} MB)")

    print("\n听法:")
    print("  1. 戴上耳机 (低频在扬声器上听不出来)")
    print("  2. 先听 listen_B.wav —— 这就是设备会怎么动")
    print("  3. 再听 listen_A.wav —— 素材本身的强度, 对比加工改了什么")
    print("  4. 想感受同步, 就静音视频画面, 一边看一边听 B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
