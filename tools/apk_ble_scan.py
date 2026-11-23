#!/usr/bin/env python3
"""
apk_ble_scan.py — 从 APK 里挖 BLE 协议线索

不需要 jadx / apktool / java。纯标准库,直接扫 dex 里的字符串。

用法:
    python apk_ble_scan.py 醉清风.apk
    python apk_ble_scan.py xxx.apk --json report.json

输出:
    1. APK 结构概览
    2. 所有 UUID(按类型分组: 标准 SIG / 自定义)
    3. 蓝牙相关权限与类名
    4. 候选广播名(大概率就是设备的 BLE 广播名)
    5. 每个自定义 UUID 的上下文串(附近的字符串,用于判断用途)
"""

import sys
import re
import json
import zipfile
from collections import Counter, defaultdict

PRINTABLE = re.compile(rb"[\x20-\x7e]{4,}")
UUID_FULL = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

SIG_SUFFIX = "-0000-1000-8000-00805f9b34fb"

BLE_WORDS = (
    "bluetooth", "bluetoothgatt", "gatt", "ble", "characteristic",
    "descriptor", "writecharacteristic", "setnotify", "notification",
    "writewithoutresponse", "conninterval", "mtu",
)

NODENAME = re.compile(r"^[A-Z][A-Z0-9_\-]{3,19}$")


def extract_strings(blob, minlen=4):
    out = []
    for m in PRINTABLE.finditer(blob):
        s = m.group().decode("ascii", "ignore")
        if len(s) >= minlen:
            out.append((m.start(), s))
    return out


def is_sig(u):
    return u.lower().endswith(SIG_SUFFIX)


def scan(apk_path):
    report = {
        "file": apk_path,
        "dex_files": [],
        "uuids": {},
        "ble_strings": [],
        "node_name_candidates": [],
        "permissions": [],
        "notes": [],
    }

    try:
        zf = zipfile.ZipFile(apk_path)
    except Exception as e:
        report["notes"].append(f"不是有效的 APK/ZIP: {e}")
        return report

    names = zf.namelist()
    dexes = [n for n in names if re.match(r"^classes\d*\.dex$", n)]
    report["dex_files"] = [
        {"name": n, "size": zf.getinfo(n).file_size} for n in dexes
    ]
    report["notes"].append(f"共 {len(names)} 个条目, {len(dexes)} 个 dex")

    if "AndroidManifest.xml" in names:
        raw = zf.read("AndroidManifest.xml")
        for m in PRINTABLE.finditer(raw):
            s = m.group().decode("ascii", "ignore")
            if "android.permission" in s or "BLUETOOTH" in s.upper():
                report["permissions"].append(s)

    uuid_hits = Counter()
    uuid_ctx = defaultdict(list)
    ble_seen = set()
    node_hits = Counter()

    for dx in dexes:
        blob = zf.read(dx)
        strs = extract_strings(blob)

        for m in UUID_FULL.finditer(blob.decode("latin-1")):
            uuid_hits[m.group().lower()] += 1

        for i, (pos, s) in enumerate(strs):
            low = s.lower()

            if UUID_FULL.fullmatch(s):
                uuid_hits[s.lower()] += 1

            for w in BLE_WORDS:
                if w in low and s not in ble_seen and len(s) < 120:
                    ble_seen.add(s)
                    if len(report["ble_strings"]) < 400:
                        report["ble_strings"].append(s)
                    break

            if NODENAME.match(s) and not s.startswith("ANDROID"):
                if len(s) <= 16:
                    node_hits[s] += 1

            if not UUID_FULL.fullmatch(s):
                continue
            lo = max(0, i - 6)
            hi = min(len(strs), i + 7)
            neigh = [strs[j][1] for j in range(lo, hi)
                     if j != i and len(strs[j][1]) < 80]
            key = s.lower()
            if len(uuid_ctx[key]) < 8:
                uuid_ctx[key].extend(x for x in neigh if x not in uuid_ctx[key])

    sig, custom = {}, {}
    for u, c in uuid_hits.items():
        (sig if is_sig(u) else custom)[u] = c
    report["uuids"] = {
        "standard_sig": dict(sorted(sig.items(), key=lambda kv: -kv[1])),
        "custom": dict(sorted(custom.items(), key=lambda kv: -kv[1])),
        "context": dict(uuid_ctx),
    }

    cands = sorted(node_hits.items(), key=lambda kv: (-kv[1], abs(len(kv[0]) - 8)))
    report["node_name_candidates"] = [{"name": n, "count": c} for n, c in cands[:60]]

    report["ble_strings"] = sorted(set(report["ble_strings"]))[:400]
    report["permissions"] = sorted(set(report["permissions"]))
    return report


def render(rep):
    L = []
    L.append("=" * 72)
    L.append(f"APK: {rep['file']}")
    L.append("=" * 72)

    L.append("\n[结构]")
    for d in rep["dex_files"]:
        L.append(f"  {d['name']:14s} {d['size']:>10,} bytes")
    for n in rep["notes"]:
        L.append(f"  · {n}")

    if rep["permissions"]:
        L.append("\n[蓝牙相关权限/清单串]")
        for p in rep["permissions"][:40]:
            L.append(f"  {p}")

    u = rep["uuids"]
    std = u.get("standard_sig", {})
    cus = u.get("custom", {})

    L.append(f"\n[标准 SIG UUID] {len(std)} 个")
    for k, v in list(std.items())[:30]:
        L.append(f"  {k}  x{v}")

    L.append(f"\n[自定义 UUID] {len(cus)} 个   <-- 重点看这里")
    for k, v in list(cus.items())[:60]:
        ctx = u.get("context", {}).get(k, [])
        L.append(f"  {k}  x{v}")
        if ctx:
            L.append(f"      上下文: {' | '.join(ctx[:8])}")

    L.append("\n[候选广播名] 前 40")
    for c in rep["node_name_candidates"][:40]:
        L.append(f"  {c['name']:24s} x{c['count']}")

    L.append(f"\n[蓝牙关键词串] {len(rep['ble_strings'])} 条")
    for s in rep["ble_strings"][:80]:
        L.append(f"  {s}")

    L.append("\n" + "=" * 72)
    L.append("判读提示:")
    L.append("  · 自定义 UUID 里出现 fff0/fff1/ffe0/ffe1/eea0 这类,")
    L.append("    基本就是控制通道。")
    L.append("  · 候选广播名里如果看到 NFY008 / XHT 这种模组名,")
    L.append("    说明可以套用已有的通用协议。")
    L.append("=" * 72)
    return "\n".join(L)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    apk = sys.argv[1]
    json_out = None
    if "--json" in sys.argv:
        i = sys.argv.index("--json")
        if i + 1 < len(sys.argv):
            json_out = sys.argv[i + 1]

    rep = scan(apk)
    print(render(rep))

    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(f"\n完整报告已写入: {json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
