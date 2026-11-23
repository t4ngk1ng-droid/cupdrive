#!/usr/bin/env python3
"""
ble.py — BLE 连接层（扫描 / 连接 / 发送 / 断开）

只做传输，不做曲线、不做时序。桌面版和命令行共用这一层。

════════════════════════════════════════════════════════════════
为什么扫要用回调模式
════════════════════════════════════════════════════════════════
bleak 3.x 的 BleakScanner.discover() 返回的 BLEDevice 没有 rssi，
只有检测回调里的 AdvertisementData 才有。所以这里统一走回调。

════════════════════════════════════════════════════════════════
连接流程（协议要求）
════════════════════════════════════════════════════════════════
    连接 → 订阅 notify → 归零帧 → 启动帧 AA 0A 01 01 B6
    * 不发启动帧，后续强度帧会被静默忽略。
    * 所有写操作必须 write-without-response（带响应在 Windows 上报
      Invalid Handle）。

断开：归零 → 停止帧 AA 0A 01 00 B5 → disconnect。
"""

import asyncio

from . import protocol as P

SCAN_SEC = 6.0
CONNECT_TIMEOUT = 20.0

# 每通道的硬上限（0..99）。桌面版只允许在这之内调整。
# 这是安全线，不是性能线，前端传什么都不能突破。
HARD_CAPS = {
    P.CH_THRUST: 40,     # 伸缩：机械行程，可能夹手
    P.CH_VIB: 55,        # 振动：手调甜点值
    P.CH_SUCTION: 35,    # 抖动（不是吮吸）
    P.CH_ROTATE: 0,      # 本机无电机
}

CH_NAMES = {
    P.CH_THRUST: "伸缩",
    P.CH_VIB: "振动",
    P.CH_SUCTION: "抖动",
    P.CH_ROTATE: "旋转",
}


def is_target(name: str) -> bool:
    """是否谜姬生态设备（广播名匹配）"""
    u = (name or "").upper()
    return "MIZZZEE" in u or "MIJI" in u


async def scan_devices(sec: float = SCAN_SEC):
    """
    返回 [{name, address, rssi, target, dev}]，按 RSSI 从强到弱。
    拿不到名字的设备也保留，但排在后面。
    """
    from bleak import BleakScanner

    found = {}

    def cb(dev, adv):
        name = getattr(adv, "local_name", None) or dev.name or ""
        rssi = getattr(adv, "rssi", None)
        found[dev.address] = {
            "name": name,
            "address": dev.address,
            "rssi": rssi,
            "target": is_target(name),
            "dev": dev,
        }

    sc = BleakScanner(detection_callback=cb)
    await sc.start()
    try:
        await asyncio.sleep(max(1.0, float(sec)))
    finally:
        await sc.stop()

    out = list(found.values())
    out.sort(key=lambda d: (not d["target"],
                            -(d["rssi"] if d["rssi"] is not None else -999)))
    return out


class BleLink:
    """一条已连接的链路。上层负责安全护栏，这里只发帧。"""

    def __init__(self):
        self.client = None
        self.wr = None
        self.nt = None
        self.device = None
        self.battery = None
        self.volt = None
        self.on_disconnect = None
        self.on_notify = None
        self.writes_ok = 0
        self.writes_fail = 0
        self.last_error = ""
        # 只有归零帧和启动帧都写成功后才为 True；close() 立即置 False。
        self.ready = False

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    async def connect(self, dev, name_hint: str = ""):
        try:
            from bleak import BleakClient

            name = dev.name if dev is not None else name_hint
            _, wr, nt = P.resolve(name or "")
            self.wr, self.nt = wr, nt
            self.writes_ok = 0
            self.writes_fail = 0
            self.last_error = ""
            self.ready = False

            def _disconnected(_client):
                if _client is not self.client:
                    return          # 旧连接的回调，不能改新链路状态
                self.ready = False
                self.battery = None
                if self.on_disconnect:
                    try:
                        self.on_disconnect()
                    except Exception:
                        pass

            self.client = BleakClient(dev, disconnected_callback=_disconnected)
            await asyncio.wait_for(self.client.connect(), timeout=CONNECT_TIMEOUT)
            self.device = name

            def _notify(_h, data):
                info = P.parse_notify(bytes(data))
                if info:
                    self.battery = info.get("power")
                    self.volt = info.get("volt")
                    if self.on_notify:
                        try:
                            self.on_notify(info)
                        except Exception:
                            pass

            try:
                await self.client.start_notify(nt, _notify)
            except Exception:
                # 没有 notify 也能控制，只是拿不到电量
                pass

            # 归零 → 启动。两步都成功才算连上；否则设备可能根本没进入
            # 可控制状态，不能对外报"已连接"。
            if not await self._write(P.aa_frame(0x08, [0, 0, 0, 0, 0, 0])):
                raise RuntimeError("归零帧写入失败: " + (self.last_error or "unknown"))
            await asyncio.sleep(0.15)
            if not await self._write(P.start()):
                raise RuntimeError("启动帧写入失败: " + (self.last_error or "unknown"))
            await asyncio.sleep(0.20)
            self.ready = True       # 启动帧写成功才算就绪
            return True
        except Exception:
            # 任何失败路径都不能留下半连接状态
            await self.close()
            self.client = None
            raise

    async def _write(self, frame):
        if not self.connected:
            return False
        try:
            await self.client.write_gatt_char(self.wr, frame, response=False)
            self.writes_ok += 1
            return True
        except Exception as e:
            self.writes_fail += 1
            self.last_error = str(e)
            return False

    async def send(self, frame) -> bool:
        return await self._write(frame)

    async def close(self):
        self.ready = False
        if not self.client:
            return
        try:
            if self.connected:
                await self._write(P.aa_frame(0x08, [0, 0, 0, 0, 0, 0]))
                await asyncio.sleep(0.10)
                await self._write(P.halt())
        except Exception:
            pass
        try:
            await self.client.disconnect()
        except Exception:
            pass
        self.client = None
        self.wr = self.nt = None
        self.device = None
        self.battery = None
        self.volt = None


# ── 自测：不需要设备 ────────────────────────────────────────────
if __name__ == "__main__":
    print("HARD_CAPS:", {CH_NAMES[k]: v for k, v in HARD_CAPS.items()})
    print("is_target('MIZZZEE XW') =", is_target("MIZZZEE XW"))
    print("is_target('mizzzee_0029') =", is_target("mizzzee_0029"))
    print("is_target('WH-1000XM4') =", is_target("WH-1000XM4"))
    print("\n扫描 3 秒（需要蓝牙适配器）...")
    for d in asyncio.run(scan_devices(3)):
        star = " ★" if d["target"] else ""
        print(f"  {d['name']!r:28s} {d['address']}  "
              f"{d['rssi']} dBm{star}")
