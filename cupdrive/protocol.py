#!/usr/bin/env python3
"""
mizzy_protocol.py — 谜姬(Mizz Zee / 醉清风) BLE 协议

实测设备: MIZZZEE XW   (XX:XX:XX:XX:XX:XX)
         service 0000DDDD / write 0000DDD1 / notify 0000DDD2

════════════════════════════════════════════════════════════════
★ 协议 = AA 帧   (源码 app-service.js:  function Ce / Il / bn)
════════════════════════════════════════════════════════════════

帧格式:
    [0xAA, CMD, LEN, ...PAYLOAD, CHECKSUM]
    CHECKSUM = (所有前面字节之和) & 0xFF

────────────────────────────────────────────────────────────────
控制流程（必须按这个顺序）

    ① 启动    AA 0A 01 01 B6
    ② 强度    AA 08 06 <v> <v> <v> <v> 00 00 <CS>      v = 0..99
    ③ 停止    AA 08 06 00 00 00 00 00 00 B8
              AA 0A 01 00 B5

    * 不先发 ① 的话，② 会被忽略。
    * payload 必须是 6 字节：四个通道同值 + duration 两字节。
    * 值 0..99 与设备屏显强度 1:1 对应（实测 10/25/50/75/99 全部吻合）。

────────────────────────────────────────────────────────────────
其他命令（源码 bn 表）

    CMD 0x04  controlHeat      payload=[1]/[0]
    CMD 0x06  modeControl      payload=[telescopic,vibration,suction,rotation,heat]
    CMD 0x08  flexibleControl  payload=[t,v,s,r,dur_lo,dur_hi]   ← 强度用这个
    CMD 0x0A  startCount       payload=[1] 开始 / [0] 结束
    CMD 0x0D  resetCount       payload=[1]

════════════════════════════════════════════════════════════════
✗ 无效协议 = 03 12 XX 帧 (源码 xht-utils/ble-manager.js)
    那是另一条产品线。对本机无效：有 notify 回应但不执行动作。

════════════════════════════════════════════════════════════════
notify 上报 (10 字节): AA 01 06 <6字节> <校验和>
    实测 4E 04 B0 1F 01 2C
         B0 1F 小端 = 8112 → 电量 81.12%
         01 2C 大端 = 300  → 电压 3.00V
"""

import struct
import random

DEFAULT_NAME = "MIZZZEE XW"
DEFAULT_ADDR = ""

SERVICE = "0000DDDD-0000-1000-8000-00805F9B34FB"
WRITE = "0000DDD1-0000-1000-8000-00805F9B34FB"
NOTIFY = "0000DDD2-0000-1000-8000-00805F9B34FB"
READ = "0000DDD3-0000-1000-8000-00805F9B34FB"

VALUE_MAX = 99

# 通道索引（源码 nC() 写死）
CH_THRUST = 0      # 伸缩
CH_VIB = 1         # 振动
CH_SUCTION = 2     # 吮吸 / 夹吸   ★ 危险，单独驱动前务必确认
CH_ROTATE = 3      # 旋转


# ── 帧 ─────────────────────────────────────────────────────────
def aa_frame(cmd: int, payload) -> bytes:
    body = [0xAA, cmd & 0xFF, len(payload) & 0xFF] + [b & 0xFF for b in payload]
    return bytes(body + [sum(body) & 0xFF])


def start():
    """① 启动 —— 不发这个，强度命令会被忽略"""
    return aa_frame(0x0A, [1])


def halt():
    """③ 结束"""
    return aa_frame(0x0A, [0])


def strength(v):
    """
    ② 强度 0..99 —— 只驱动振动通道 (index 1)，其余通道保持 0。

    ⚠ 绝对不要四个通道同值。源码里 App 的滑条会同时设
      telescopic / vibration / suction / rotation，其中 suction 是
      夹吸机构，拉满会夹伤人。本项目只用振动。
    """
    v = max(0, min(VALUE_MAX, int(round(v))))
    return aa_frame(0x08, [0, v, 0, 0, 0, 0])


def strength_all(v):
    """四通道同值 —— 仅用于诊断，日常不要用（会触发夹吸）"""
    v = max(0, min(VALUE_MAX, int(round(v))))
    return aa_frame(0x08, [v, v, v, v, 0, 0])


def strength_one(ch, v):
    """单独驱动某个通道：ch = 0伸缩 / 1振动 / 2夹吸 / 3旋转"""
    ch = max(0, min(3, int(ch)))
    v = max(0, min(VALUE_MAX, int(round(v))))
    p = [0, 0, 0, 0]
    p[ch] = v
    return aa_frame(0x08, p + [0, 0])


def strength_ch(t=0, vib=0, suc=0, rot=0, duration=0):
    """分通道强度（未验证实际效果，保留）"""
    clamp = lambda x: max(0, min(255, int(x)))
    return aa_frame(0x08, [clamp(t), clamp(vib), clamp(suc), clamp(rot),
                           clamp(duration & 0xFF), clamp((duration >> 8) & 0xFF)])


def heat(on: bool):
    return aa_frame(0x04, [1 if on else 0])


def mode5(telescopic=0, vibration=0, suction=0, rotation=0, heat_level=0):
    return aa_frame(0x06, [telescopic, vibration, suction, rotation, heat_level])


def reset_count():
    return aa_frame(0x0D, [1])


def stop():
    return strength(0)


# ── 曲线值映射 ─────────────────────────────────────────────────
def pct_to_value(pct: float) -> int:
    """曲线 0..100 → 设备值 0..99"""
    return max(0, min(VALUE_MAX, int(round(float(pct) * VALUE_MAX / 100.0))))


class ValueMapper:
    """曲线 0..100 → 0..99，带可选的 gamma 与整体缩放。"""

    def __init__(self, scale=1.0, gamma=1.0):
        self.scale = scale
        self.gamma = gamma

    def __call__(self, pct: float) -> int:
        v = max(0.0, min(100.0, float(pct) * self.scale)) / 100.0
        if self.gamma != 1.0:
            v = v ** self.gamma
        return max(0, min(VALUE_MAX, int(round(v * VALUE_MAX))))


# ── notify ─────────────────────────────────────────────────────
def parse_notify(payload: bytes):
    if len(payload) < 10 or payload[0] != 0xAA:
        return None
    d = payload[3:9]
    out = {"raw": payload.hex()}
    if len(d) >= 1:
        out["byte0"] = d[0]
    if len(d) >= 4:
        out["power"] = struct.unpack_from("<H", d, 2)[0] / 100.0
    if len(d) >= 6:
        out["volt"] = struct.unpack_from(">H", d, 4)[0] / 100.0
    return out


# ── 设备解析 ───────────────────────────────────────────────────
LEGACY_DEVICES = {
    "mizzzee_0010": ("0000fee1-0000-1000-8000-00805f9b34fb",) * 3,
    "mizzzee_0014": ("0000AE30-0000-1000-8000-00805F9B34FB",
                     "0000AE01-0000-1000-8000-00805F9B34FB",
                     "0000AE02-0000-1000-8000-00805F9B34FB"),
    "mizzzee_0029": ("0000FFE0-0000-1000-8000-00805F9B34FB",
                     "0000FFE1-0000-1000-8000-00805F9B34FB",
                     "0000FFE1-0000-1000-8000-00805F9B34FB"),
}


def resolve(name: str):
    if name and "MIZZZEE" in name.upper():
        return SERVICE, WRITE, NOTIFY
    for k, v in LEGACY_DEVICES.items():
        if name and k.lower() in name.lower():
            return v
    return SERVICE, WRITE, NOTIFY


def dev_type_of(name: str) -> str:
    if not name:
        return ""
    u = name.upper()
    if "MIZZZEE" in u or "MIJI" in u:
        return "aa"
    if "XHTKJ" in u or "ZQF" in u or "ANKNI" in u or "安可尼" in name:
        return "xht"
    return ""


def handshake():
    buf = bytearray(18)
    buf[0] = 0x01
    buf[1] = 0x01
    buf[2:] = bytes(random.randrange(1, 256) for _ in range(16))
    return bytes(buf)


# ── 自测 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    hx = lambda b: " ".join(f"{x:02X}" for x in b)

    print("=== 控制流程 ===")
    print("  ① start   :", hx(start()))
    print("  ② v=0     :", hx(strength(0)))
    print("  ② v=50    :", hx(strength(50)))
    print("  ② v=99    :", hx(strength(99)))
    print("  ③ halt    :", hx(halt()))
    print("  heat on   :", hx(heat(True)))
    print("  mode5     :", hx(mode5(vibration=50)))

    print("\n=== 曲线映射 ===")
    m = ValueMapper()
    for p in (0, 25, 50, 75, 100):
        print(f"  曲线 {p:3d}% → 设备值 {m(p):2d}")

    print("\n=== notify ===")
    print(" ", parse_notify(bytes.fromhex("AA01064E04B01F012CFF")))
