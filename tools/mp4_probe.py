#!/usr/bin/env python3
"""
mp4_probe.py — 纯标准库 MP4/MOV 探测

不需要 ffmpeg。用于快速判断一段素材适不适合做曲线驱动:
  - 总时长
  - 有几个轨道, 分别是什么编码
  - 有没有音轨 (音频预填的前提)
  - 分辨率 / 采样率

用法:
    python mp4_probe.py "video.mp4"
"""

import sys
import json
import struct

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf"}

CODEC_NAMES = {
    b"avc1": "H.264", b"avc3": "H.264", b"hvc1": "H.265", b"hev1": "H.265",
    b"vp09": "VP9", b"av01": "AV1", b"mp4v": "MPEG-4",
    b"mp4a": "AAC", b"ac-3": "AC-3", b"ec-3": "E-AC-3",
    b"Opus": "Opus", b"alac": "ALAC", b"twos": "PCM",
}


def iter_boxes(f, start, end):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        size = struct.unpack(">I", hdr[:4])[0]
        typ = hdr[4:8]
        hlen = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                break
            size = struct.unpack(">Q", ext)[0]
            hlen = 16
        elif size == 0:
            size = end - pos
        if size < hlen:
            break
        yield typ, pos + hlen, pos + size
        pos += size


def parse_mvhd(f, start, end):
    f.seek(start)
    ver = f.read(1)[0]
    f.read(3)
    if ver == 1:
        f.read(16)
        timescale = struct.unpack(">I", f.read(4))[0]
        duration = struct.unpack(">Q", f.read(8))[0]
    else:
        f.read(8)
        timescale = struct.unpack(">I", f.read(4))[0]
        duration = struct.unpack(">I", f.read(4))[0]
    return timescale, duration


def parse_mdhd(f, start, end):
    f.seek(start)
    ver = f.read(1)[0]
    f.read(3)
    if ver == 1:
        f.read(16)
        timescale = struct.unpack(">I", f.read(4))[0]
        duration = struct.unpack(">Q", f.read(8))[0]
    else:
        f.read(8)
        timescale = struct.unpack(">I", f.read(4))[0]
        duration = struct.unpack(">I", f.read(4))[0]
    return timescale, duration


def parse_hdlr(f, start, end):
    f.seek(start + 8)          # version/flags + pre_defined
    handler = f.read(4)
    return handler


def parse_stsd(f, start, end):
    """返回 [(codec_fourcc, kind, info)]"""
    f.seek(start)
    f.read(4)                  # version/flags
    count = struct.unpack(">I", f.read(4))[0]
    out = []
    pos = start + 8
    for _ in range(count):
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        size = struct.unpack(">I", hdr[:4])[0]
        fourcc = hdr[4:8]
        body = pos + 8
        info = {}
        try:
            if fourcc in (b"mp4a", b"Opus", b"alac", b"ac-3", b"ec-3"):
                f.seek(body + 8)
                ch = struct.unpack(">H", f.read(2))[0]
                bits = struct.unpack(">H", f.read(2))[0]
                f.read(4)
                sr = struct.unpack(">I", f.read(4))[0] >> 16
                info = {"channels": ch, "bits": bits, "sample_rate": sr}
            elif fourcc in (b"avc1", b"avc3", b"hvc1", b"hev1", b"vp09", b"av01", b"mp4v"):
                f.seek(body + 16)
                w = struct.unpack(">H", f.read(2))[0]
                h = struct.unpack(">H", f.read(2))[0]
                info = {"width": w, "height": h}
        except Exception:
            pass
        out.append({
            "fourcc": fourcc.decode("latin-1"),
            "codec": CODEC_NAMES.get(fourcc, fourcc.decode("latin-1")),
            "info": info,
        })
        pos += size
    return out


def probe(path):
    import os
    fsize = os.path.getsize(path)
    res = {
        "path": path,
        "size_mb": round(fsize / 1048576, 2),
        "brand": None,
        "duration": None,
        "tracks": [],
        "has_audio": False,
        "has_video": False,
    }
    with open(path, "rb") as f:
        for typ, s, e in iter_boxes(f, 0, fsize):
            if typ == b"ftyp":
                f.seek(s)
                res["brand"] = f.read(4).decode("latin-1", "ignore")
            elif typ == b"moov":
                moov_s, moov_e = s, e
                # mvhd
                for t2, s2, e2 in iter_boxes(f, moov_s, moov_e):
                    if t2 == b"mvhd":
                        ts, du = parse_mvhd(f, s2, e2)
                        if ts:
                            res["duration"] = round(du / ts, 3)
                    elif t2 == b"trak":
                        trk = {"type": "?", "codec": [], "duration": None}
                        for t3, s3, e3 in iter_boxes(f, s2, e2):
                            if t3 != b"mdia":
                                continue
                            for t4, s4, e4 in iter_boxes(f, s3, e3):
                                if t4 == b"hdlr":
                                    h = parse_hdlr(f, s4, e4)
                                    trk["type"] = h.decode("latin-1", "ignore").strip("\x00")
                                elif t4 == b"mdhd":
                                    ts2, du2 = parse_mdhd(f, s4, e4)
                                    if ts2:
                                        trk["duration"] = round(du2 / ts2, 3)
                                elif t4 == b"minf":
                                    for t5, s5, e5 in iter_boxes(f, s4, e4):
                                        if t5 == b"stbl":
                                            for t6, s6, e6 in iter_boxes(f, s5, e5):
                                                if t6 == b"stsd":
                                                    trk["codec"] = parse_stsd(f, s6, e6)
                        if trk["type"].startswith("vide"):
                            res["has_video"] = True
                        if trk["type"].startswith("soun"):
                            res["has_audio"] = True
                        res["tracks"].append(trk)
    return res


def verdict(r):
    d = r["duration"] or 0
    lines = []
    if not r["has_audio"]:
        lines.append("× 没有音轨 —— 音频预填不可用, 只能手画或走画面运动分析")
    if not r["has_video"]:
        lines.append("× 没有视频轨 —— 这不是一个可播放的视频")
    if d and d < 60:
        lines.append("! 时长不足 1 分钟 —— 太短, 标不出什么")
    elif 60 <= d <= 1200:
        lines.append("√ 时长合适 (1~20 分钟)")
    elif d > 1200:
        lines.append("! 超过 20 分钟 —— 精标会非常累, 建议先截 5 分钟试")
    if r["has_audio"] and r["has_video"]:
        lines.append("√ 有音轨 + 视频轨 —— 可以直接进标定台跑音频预填")
    return lines


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    r = probe(sys.argv[1])
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("\n判读:")
    for l in verdict(r):
        print("  " + l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
