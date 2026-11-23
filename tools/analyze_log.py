#!/usr/bin/env python3
r"""
analyze_log.py - parse a Boo Boop btserver.log into a command time series

The Windows app writes one line per outgoing BLE command:

    INFO - Queued command 'aabb0105' for XX:XX:.. using key 'MIZZZEE XW'

That hex string is the actual frame sent to the device. 792 of them from one
playback session is enough to reconstruct the official sync algorithm.

Usage:
    python analyze_log.py "%APPDATA%\BooBoop\logs\btserver.log"
    python analyze_log.py log.txt --plot 60

Output:
    1. event breakdown (how much of the log is noise)
    2. command time series
    3. value distribution
    4. rise/fall step analysis   <- the interesting part
    5. playback gaps
"""

import re
import sys
import argparse
from datetime import datetime
from collections import Counter

LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
    r"[^I]*INFO - Queued command '([0-9a-fA-F]+)'"
)


def parse(path):
    seq = []
    total = 0
    noise = 0
    for ln in open(path, encoding="utf-8", errors="ignore"):
        total += 1
        if "Command not found" in ln:
            noise += 1
            continue
        m = LINE.match(ln)
        if not m:
            continue
        ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        payload = bytes.fromhex(m.group(2))
        seq.append((ts, payload))
    return seq, total, noise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--plot", type=int, default=40,
                    help="how many seconds to plot (default 40)")
    args = ap.parse_args()

    seq, total, noise = parse(args.logfile)
    print("=" * 66)
    print("file      %s" % args.logfile)
    print("lines     %d   (noise: %d, %.0f%%)" % (total, noise, noise / max(total, 1) * 100))
    print("commands  %d" % len(seq))
    if not seq:
        return

    # Only single-byte-value frames carry an intensity
    vals = [(t, p[3]) for t, p in seq if len(p) == 4 and p[1] == 0xBB]
    if not vals:
        print("\nno AA BB 01 <v> frames found; dumping frame shapes instead:")
        shapes = Counter("%02X %02X len=%d" % (p[0], p[1], len(p) - 3) for _, p in seq)
        for k, v in shapes.most_common(10):
            print("  %-20s %d" % (k, v))
        return

    t0 = vals[0][0]
    span = (vals[-1][0] - t0).total_seconds()
    print("span      %.0fs   rate %.2f cmd/s" % (span, len(vals) / max(span, 1)))

    print("\n" + "=" * 66)
    print("value distribution")
    print("=" * 66)
    c = Counter(v for _, v in vals)
    peak = max(c.values())
    for v in sorted(c):
        bar = "#" * int(c[v] / peak * 40)
        print("  v=%-3d %5d  %-40s %4.1f%%" % (v, c[v], bar, c[v] / len(vals) * 100))

    print("\n" + "=" * 66)
    print("step analysis  <- the algorithm")
    print("=" * 66)
    ups, downs, same = [], [], 0
    for i in range(1, len(vals)):
        d = vals[i][1] - vals[i - 1][1]
        if d > 0:
            ups.append(d)
        elif d < 0:
            downs.append(abs(d))
        else:
            same += 1
    print("  rise %d (mean +%.2f)   fall %d (mean -%.2f)   hold %d"
          % (len(ups), sum(ups) / max(len(ups), 1),
             len(downs), sum(downs) / max(len(downs), 1), same))
    print("  max single rise +%d" % (max(ups) if ups else 0))
    print("  max single fall -%d" % (max(downs) if downs else 0))
    print("  rise steps:", dict(sorted(Counter(ups).items())))
    print("  fall steps:", dict(sorted(Counter(downs).items())))

    print("\n" + "=" * 66)
    print("gaps >= 2s")
    print("=" * 66)
    for i in range(1, len(vals)):
        dt = (vals[i][0] - vals[i - 1][0]).total_seconds()
        if dt >= 2:
            at = (vals[i - 1][0] - t0).total_seconds()
            print("  at %6.0fs  pause %4.1fs   v=%d -> v=%d"
                  % (at, dt, vals[i - 1][1], vals[i][1]))

    print("\n" + "=" * 66)
    print("timeline (first %ds)" % args.plot)
    print("=" * 66)
    per_sec = Counter(int((t - t0).total_seconds()) for t, _ in vals)
    for s in range(args.plot):
        n = per_sec.get(s, 0)
        print("  %3ds %2d %s" % (s, n, "#" * n))


if __name__ == "__main__":
    sys.exit(main())
