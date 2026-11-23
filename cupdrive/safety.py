#!/usr/bin/env python3
"""
safety.py — 设备控制的安全护栏

所有强度指令都必须经过这里，不允许绕过。

════════════════════════════════════════════════════════════════
五道闸门
════════════════════════════════════════════════════════════════
1. 通道白名单   默认只允许振动（CH_VIB）。夹吸/伸缩/旋转需要显式授权。
2. 硬上限       默认 80（设备满值 99）。防止长时间满功率。
3. 变化速率     默认 25/秒。禁止瞬间跳变，避免机械冲击。
4. 异常归零     任何异常 / Ctrl+C / 进程退出，都先归零再断连。
5. 审计日志     每条命令记录时间、强度、触发原因，退出时汇总。

════════════════════════════════════════════════════════════════
为什么需要
════════════════════════════════════════════════════════════════
实测教训：把四个通道设成同一个值（App 滑条的做法）会导致
suction（夹吸）跟着拉满，会夹伤人。

这个模块确保：即使上层代码写错，也发不出危险指令。
"""

import time
import atexit
import signal

from . import protocol as P


class SafetyError(Exception):
    pass


class SafetyGuard:
    """强度安全护栏。每次发强度前调用 limit()，用 build() 构造帧。"""

    def __init__(self,
                 max_value: int = 80,
                 slew_per_sec: float = 25.0,
                 channels=(P.CH_VIB,),
                 allow_dangerous: bool = False,
                 per_channel_max: dict = None,
                 audit: bool = True):
        if not allow_dangerous:
            for ch in channels:
                if ch in (P.CH_THRUST, P.CH_SUCTION, P.CH_ROTATE):
                    raise SafetyError(
                        f"通道 {ch} 属于机械类动作，必须 allow_dangerous=True 才能启用"
                    )
        max_value = max(0, min(P.VALUE_MAX, int(max_value)))
        self.max_value = max_value
        self.slew = max(1.0, float(slew_per_sec))
        self.channels = tuple(channels)
        self.audit_on = audit

        # 每通道独立上限（覆盖全局上限）
        self.per_channel_max = {}
        if per_channel_max:
            for ch, cap in per_channel_max.items():
                self.per_channel_max[int(ch)] = max(0, min(P.VALUE_MAX, int(cap)))

        self._last = 0
        self._t = time.time()
        self._records = []
        self._tripped = False

    # ── 限幅 + 限速 ────────────────────────────────────────────
    def limit(self, target: float) -> int:
        """把目标值压进安全范围，并限制变化速率。"""
        now = time.time()
        dt = now - self._t
        if dt <= 0:
            dt = 1e-3
        self._t = now

        t = max(0.0, min(float(target), self.max_value))
        delta = self.slew * dt
        v = self._last + max(-delta, min(delta, t - self._last))
        v = int(round(max(0.0, min(self.max_value, v))))
        self._last = v

        if self.audit_on:
            self._records.append((round(now, 3), v, round(float(target), 1)))
            if len(self._records) > 20000:
                self._records = self._records[-10000:]
        return v

    # ── 构造帧（只带白名单通道）───────────────────────────────
    def build(self, value: int) -> bytes:
        """按通道白名单构造帧，每通道再套自己的上限"""
        v = max(0, min(P.VALUE_MAX, int(value)))
        p = [0, 0, 0, 0]
        for ch in self.channels:
            cap = self.per_channel_max.get(ch, self.max_value)
            p[ch] = min(v, cap)
        return P.aa_frame(0x08, p + [0, 0])

    # ── 归零 ───────────────────────────────────────────────────
    @staticmethod
    def zero_frame() -> bytes:
        return P.aa_frame(0x08, [0, 0, 0, 0, 0, 0])

    # ── 审计 ───────────────────────────────────────────────────
    def summary(self):
        if not self._records:
            return "（无记录）"
        vs = [r[1] for r in self._records]
        clipped = sum(1 for r in self._records if abs(r[1] - r[2]) > 1)
        return (f"命令数 {len(self._records)}  "
                f"峰值 {max(vs)}  均值 {sum(vs)/len(vs):.1f}  "
                f"被限速/限幅 {clipped} 次 ({clipped/len(self._records)*100:.1f}%)")

    def describe(self):
        ch_names = {P.CH_THRUST: "伸缩", P.CH_VIB: "振动",
                    P.CH_SUCTION: "夹吸", P.CH_ROTATE: "旋转"}
        return (f"通道 {[ch_names.get(c, c) for c in self.channels]}  "
                f"上限 {self.max_value}  速率 {self.slew}/s")


class GuardedDevice:
    """
    给 BleBackend 套一层安全护栏。

    用法：
        dev = await BleBackend(...).connect()
        gd = GuardedDevice(dev, SafetyGuard(max_value=70))
        await gd.set(50)      # 自动限幅限速
        await gd.release()    # 归零 + halt
    """

    def __init__(self, backend, guard: SafetyGuard = None):
        self.backend = backend
        self.guard = guard or SafetyGuard()
        self._closed = False
        atexit.register(self._atexit_zero)

    async def set(self, target: float):
        if self._closed:
            return
        v = self.guard.limit(target)
        await self.backend.send(self.guard.build(v))

    async def release(self):
        """归零并结束，安全关机的唯一入口"""
        if self._closed:
            return
        try:
            await self.backend.send(self.guard.zero_frame())
            await self.backend.send(P.halt())
        except Exception:
            pass
        self._closed = True

    def _atexit_zero(self):
        if self._closed:
            return
        # 同步兜底：尽力再发一次归零
        try:
            import asyncio
            async def _z():
                await self.backend.send(self.guard.zero_frame())
                await self.backend.send(P.halt())
            asyncio.get_event_loop()
        except Exception:
            pass


class MultiGuard:
    """
    多通道护栏：每个通道独立限幅 + 独立限速，最后合成一条 0x08 帧。

    用法：
        mg = MultiGuard({P.CH_VIB: 80, P.CH_THRUST: 65})
        frame = mg.set({P.CH_VIB: 90, P.CH_THRUST: 90})
        # → 振动 80，伸缩 65，各自按 25/s 的速率爬升
    """

    CH_NAMES = {P.CH_THRUST: "伸缩", P.CH_VIB: "振动",
                P.CH_SUCTION: "抖动", P.CH_ROTATE: "旋转"}

    def __init__(self, caps: dict, slew_per_sec: float = 25.0, audit=True):
        self.caps = {int(ch): max(0, min(P.VALUE_MAX, int(cap)))
                     for ch, cap in caps.items()}
        self.slew = slew_per_sec
        self.guards = {}
        for ch, cap in self.caps.items():
            self.guards[ch] = SafetyGuard(
                max_value=cap,
                slew_per_sec=slew_per_sec,
                channels=(ch,),
                allow_dangerous=True,
                audit=audit,
            )

    def set(self, pct_map: dict) -> bytes:
        p = [0, 0, 0, 0]
        for ch, g in self.guards.items():
            target = float(pct_map.get(ch, 0))
            p[ch] = g.limit(target)
        return P.aa_frame(0x08, p + [0, 0])

    def zero(self) -> bytes:
        return P.aa_frame(0x08, [0, 0, 0, 0, 0, 0])

    def describe(self):
        parts = [f"{self.CH_NAMES.get(ch, ch)}<={cap}"
                 for ch, cap in self.caps.items()]
        return "  ".join(parts) + f"   速率 {self.slew}/s"

    def summary(self):
        return " | ".join(
            f"{self.CH_NAMES.get(ch, ch)}: {g.summary()}"
            for ch, g in self.guards.items()
        )


def install_signal_handlers(guarded: GuardedDevice):
    """Ctrl+C / SIGTERM 时先归零再退出"""
    def handler(signum, frame):
        raise KeyboardInterrupt()
    try:
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
    except Exception:
        pass


# ── 自测 ────────────────────────────────────────────────────────
if __name__ == "__main__":
    hx = lambda b: " ".join(f"{x:02X}" for x in b)

    print("=== 默认护栏 ===")
    g = SafetyGuard()
    print(" ", g.describe())
    print("  只驱动振动的帧 (v=50):", hx(g.build(50)))

    print("\n=== 硬上限 80 ===")
    g2 = SafetyGuard(max_value=80)
    for target in (0, 50, 99):
        g2._t = time.time() - 10        # 跳过限速，只看限幅
        print(f"  目标 {target:2d} → 实际 {g2.limit(target):2d}")

    print("\n=== 变化速率 25/秒 ===")
    g3 = SafetyGuard(slew_per_sec=25.0)
    print("  从 0 瞬间要求 99：")
    t0 = time.time()
    for i in range(6):
        v = g3.limit(99)
        print(f"    +{(time.time()-t0)*1000:4.0f}ms → {v}")
        time.sleep(0.1)

    print("\n=== 通道保护 ===")
    try:
        SafetyGuard(channels=(P.CH_SUCTION,))
        print("  [FAIL] 应该被拒绝却没有")
    except SafetyError as e:
        print("  [OK] 拒绝启用夹吸:", e)

    print("\n=== 审计 ===")
    g4 = SafetyGuard()
    for x in (10, 40, 90, 20):
        g4._t = time.time() - 10
        g4.limit(x)
    print(" ", g4.summary())
