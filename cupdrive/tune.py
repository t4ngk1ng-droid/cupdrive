#!/usr/bin/env python3
"""
curve_tune.py — 把标定台导出的原始曲线，加工成"能驱动设备"的曲线

输入   marker.html 导出的 xxx.script.json
输出   xxx.tuned.json

核心问题与对策
──────────────────────────────────────────────────────────────
标定台导出的 A / mv 都用 max 归一化。max 会被切镜、单点峰值拉高,
导致真实变化被压进很窄的区间 (实测 p5-p95 只有 15)。

本工具改用 **百分位拉伸**: 把 p5→0, p95→100, 动态范围被真正拉开。

加工流程
──────────────────────────────────────────────────────────────
  1. A(音频) 与 mv(画面) 各自百分位拉伸
  2. 融合成 base  (画面占比可调)
  3. gamma 提升低端
  4. 去毛刺
  5. 重新合成 B:
       预示(取未来窗口最大值) → 快攻击/慢释放
       + 地板浮动 + 呼吸(0.22Hz) + 微扰动
  6. 单调审计: 死段注入变化

用法:
    python curve_tune.py "xxx.script.json"
    python curve_tune.py "xxx.script.json" --video-weight 0.45
"""

import sys
import json
import math
import os

import numpy as np

HZ = 10

# ── 可调参数 ────────────────────────────────────────────────────
A_LO_P = 5            # A 拉伸下百分位
A_HI_P = 95           # A 拉伸上百分位
MV_LO_P = 10
MV_HI_P = 95
VIDEO_W = 0.40        # 画面权重 (音频 = 1 - 这个)

PRE_SMOOTH = 40       # 拉伸前的平滑窗口 (4 秒) —— 先降噪再拉伸, 顺序不能反
GAMMA = 1.00          # 拉伸后 gamma (1.0 = 不额外抬升, 实测最佳)
SMOOTH_A = 3

# 官方式包络：慢上快下（实测官方日志 789 条命令反推）
#   上升 16.5 单位/秒   下降 82.5 单位/秒   —— 上升是下降的 1/5
UP_RATE = 16.5
DOWN_RATE = 82.5

FLOOR_MIN = 14.0
FLOOR_MAX = 22.0
CEIL = 90.0
LOOKAHEAD = 1.2
BREATH_HZ = 0.22
BREATH_AMP = 3.5
JITTER_AMP = 2.2


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    a = np.asarray(d["a"], dtype=np.float64)
    b = np.asarray(d.get("b", [0] * len(a)), dtype=np.float64)
    mv = np.asarray(d.get("mv", []), dtype=np.float64)
    return d, a, b, mv


def stretch(x, lo_p, hi_p):
    """百分位拉伸: p_lo → 0, p_hi → 100"""
    if len(x) == 0:
        return x
    lo = np.percentile(x, lo_p)
    hi = np.percentile(x, hi_p)
    if hi - lo < 1e-6:
        return np.zeros_like(x)
    return np.clip((x - lo) / (hi - lo), 0, 1) * 100.0


def gamma_lift(x, gamma):
    return np.power(np.clip(x, 0, 100) / 100.0, gamma) * 100.0


def moving_avg(x, k):
    # np.convolve(mode="same") 返回 max(len(x), len(k))，窗口比轨道长时
    # 会把短曲线拉长。先夹住窗口，保证输出点数等于输入点数。
    n = len(x)
    if n <= 1 or k <= 1:
        return x
    k = max(1, min(int(k), n))
    if k == 1:
        return x
    ker = np.ones(k) / k
    return np.convolve(x, ker, mode="same")[:n]


def looksay_max(a, lookahead_s):
    """取未来窗口最大值 → 让曲线提前爬升 (预示)"""
    n = len(a)
    k = max(1, int(lookahead_s * HZ))
    out = a.copy()
    for i in range(n):
        out[i] = a[i:min(n, i + k)].max()
    return out


def breath(n):
    t = np.arange(n) / HZ
    return BREATH_AMP * np.sin(2 * math.pi * BREATH_HZ * t)


def jitter(n, seed=7):
    rng = np.random.default_rng(seed)
    raw = rng.uniform(-1.0, 1.0, n)
    out = np.zeros(n)
    v = 0.0
    for i in range(n):
        v += (raw[i] - v) * 0.02
        out[i] = v
    return out * JITTER_AMP * 3.0


def slew_follow(x, hz=HZ, up=UP_RATE, down=DOWN_RATE):
    """
    限速跟随 —— 官方实现的核心。

    上升每步最多 up/hz 单位，下降每步最多 down/hz 单位。
    上升慢、下降快，和官方日志里 "只 +1、可 -5" 的规律一致。

    不做指数平滑，直接硬限速：曲线永远贴着目标走，但速度受控。
    """
    out = np.empty_like(x)
    up_step = up / hz
    down_step = down / hz
    v = 0.0
    for i in range(len(x)):
        tgt = x[i]
        if tgt > v:
            v = min(v + up_step, tgt)
        else:
            v = max(v - down_step, tgt)
        out[i] = v
    return out


def floor_track(base, lo, hi):
    act = moving_avg(base, int(8 * HZ))
    p = np.percentile(act, 90)
    if p <= 1e-6:
        return np.full_like(base, lo)
    frac = np.clip(act / p, 0, 1)
    return lo + (hi - lo) * frac


def segment_report(a):
    act = a > 8
    segs, cur, start = [], act[0], 0
    for i in range(1, len(a)):
        if act[i] != cur:
            segs.append((cur, start / HZ, i / HZ))
            cur, start = act[i], i
    segs.append((cur, start / HZ, len(a) / HZ))
    return [s for s in segs if s[2] - s[1] >= 2.0]


def tune(d, a_raw, b_raw, mv_raw, video_w):
    n = len(a_raw)

    # 1) 先降噪 (4 秒) -> 加权融合 -> 再统一百分位拉伸
    #    注意: 必须"先融合再拉伸"。分别拉伸会把两路噪声各自拉到满格,
    #    融合后反而丢失相对信息, 实测会把整体均值顶高。
    a_den = moving_avg(a_raw, PRE_SMOOTH)
    has_mv = len(mv_raw) == n and mv_raw.max() > 1.0
    if has_mv:
        m_den = moving_avg(mv_raw, PRE_SMOOTH)
        mixed = a_den * (1 - video_w) + m_den * video_w
    else:
        mixed = a_den
    base = stretch(mixed, A_LO_P, A_HI_P)

    # 2) gamma + 去毛刺
    base = gamma_lift(base, GAMMA)
    base = moving_avg(base, SMOOTH_A)

    # 3) B 合成
    src = looksay_max(base, LOOKAHEAD)
    b = slew_follow(src)

    bmin, bmax = b.min(), b.max()
    if bmax - bmin < 1e-6:
        b = np.full(n, FLOOR_MIN)
    else:
        b = (b - bmin) / (bmax - bmin) * (CEIL - FLOOR_MIN) + FLOOR_MIN

    b = b * 0.82 + floor_track(base, FLOOR_MIN, FLOOR_MAX) * 0.18
    b = b + breath(n) + jitter(n)
    b = np.clip(b, 0, 100)

    # 4) 单调审计
    flat = np.zeros(n, dtype=bool)
    win = int(6 * HZ)
    for i in range(0, n - win, max(1, win // 2)):
        seg = b[i:i + win]
        if seg.max() - seg.min() < 2.0:
            flat[i:i + win] = True
    if flat.any():
        rng = np.random.default_rng(11)
        b[flat] += rng.uniform(-2.5, 2.5, int(flat.sum()))
        b = np.clip(b, 0, 100)

    return base, b, has_mv


def stats(x, name):
    nz = int((x > 1).sum())
    return (f"{name}: min={x.min():5.1f} max={x.max():5.1f} "
            f"mean={x.mean():5.1f} std={x.std():5.2f} nz={nz/len(x)*100:5.1f}%")


def ascii_plot(a, b, n_bucket=110, height=9):
    n = len(a)
    step = max(1, n // n_bucket)
    la = [a[i:i + step].mean() for i in range(0, n, step)]
    lb = [b[i:i + step].mean() for i in range(0, n, step)]
    rows = []
    for r in range(height, -1, -1):
        lvl = r / height * 100
        line = ""
        for i in range(len(la)):
            ch = " "
            if la[i] >= lvl:
                ch = "."
            if lb[i] >= lvl:
                ch = "#" if ch == " " else "*"
            line += ch
        rows.append(f"{lvl:5.0f} |{line}")
    rows.append("      +" + "-" * len(la))
    return "\n".join(rows)


def default_out(path):
    """xxx.script.json → 同目录 xxx.tuned.json"""
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem.lower().endswith(".script"):
        stem = stem[:-7]
    return os.path.join(os.path.dirname(path) or ".", stem + ".tuned.json")


def tune_file(path, out=None, video_w=VIDEO_W):
    """完整加工流程：读脚本 → 加工 → 写 tuned.json。

    返回 (out_path, base, b, has_mv)，给 CLI 和桌面版共用。
    """
    d, a_raw, b_raw, mv_raw = load(path)
    base, b, has_mv = tune(d, a_raw, b_raw, mv_raw, video_w)
    out = out or default_out(path)

    res = dict(d)
    res["a"] = [int(round(v)) for v in base]
    res["b"] = [int(round(v)) for v in b]
    res["tuned"] = {
        "stretch": [A_LO_P, A_HI_P], "pre_smooth": PRE_SMOOTH,
        "video_weight": video_w if has_mv else 0.0,
        "gamma": GAMMA,
        "up_rate": UP_RATE, "down_rate": DOWN_RATE,
        "floor": [FLOOR_MIN, FLOOR_MAX], "ceil": CEIL,
        "lookahead_s": LOOKAHEAD,
        "breath_hz": BREATH_HZ, "breath_amp": BREATH_AMP,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    return out, base, b, has_mv


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    out = None
    video_w = VIDEO_W
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            out = sys.argv[i + 1]
    if "--video-weight" in sys.argv:
        i = sys.argv.index("--video-weight")
        if i + 1 < len(sys.argv):
            video_w = float(sys.argv[i + 1])

    d, a_raw, b_raw, mv_raw = load(path)
    out, base, b, has_mv = tune_file(path, out, video_w)

    print("=" * 70)
    print("原始 (标定台 max 归一化的结果)")
    print("  " + stats(a_raw, "A "))
    if len(mv_raw):
        print("  " + stats(mv_raw, "mv"))
    print("\n加工后")
    print("  " + stats(base, "A'")) 
    print("  " + stats(b, "B "))
    print(f"\n画面融合: {'启用, 权重 %.2f' % video_w if has_mv else '无画面数据, 纯音频'}")

    segs = segment_report(base)
    act = [s for s in segs if s[0]]
    quiet = [s for s in segs if not s[0]]
    print(f"\n段落: 活跃 {len(act)} / 安静 {len(quiet)}")
    for s in sorted(act, key=lambda x: -(x[2] - x[1]))[:6]:
        print(f"  活跃 {s[1]:6.1f}s → {s[2]:6.1f}s  ({s[2]-s[1]:5.1f}s)")
    for s in sorted(quiet, key=lambda x: -(x[2] - x[1]))[:3]:
        print(f"  安静 {s[1]:6.1f}s → {s[2]:6.1f}s  ({s[2]-s[1]:5.1f}s)")

    print("\n曲线形态  ( . = A'   # = B   * = 重合 )")
    print(ascii_plot(base, b))

    print(f"\n→ {out}")
    print(f"  {os.path.getsize(out)/1024:.0f} KB, {len(base)} points")
    return 0


if __name__ == "__main__":
    sys.exit(main())
