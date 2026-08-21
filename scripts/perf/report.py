#!/usr/bin/env python3
"""Write the profile report from a scripts/perf/profile.sh output directory.

    timings/run-N.json   un-profiled wall clock per run (perf_run.py output)
    profiles/run-N.raw   py-spy raw recordings at --rate Hz

The report has three parts: the wall clocks and their median; the top
functions of the product (PaintomicsServer/src) by cumulative time, each
function's cumulative seconds being the MEDIAN over the profiled runs of
samples / rate; and the same ranking over every frame (pandas, scipy, the
standard library included) for context.

    python scripts/perf/report.py <out-dir> --runs 3 --rate 200
"""
import argparse
import json
import os
import platform
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import topfuncs  # noqa: E402


def read_profile(path):
    """{key: cumulative samples}, {key: self samples}, total, {key: is_src}"""
    cumulative, self_time, in_src, total = defaultdict(int), defaultdict(int), {}, 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stack, _, count = line.rstrip("\n").rpartition(" ")
            try:
                count = int(count)
            except ValueError:
                continue
            total += count
            frames = []
            for raw in stack.split(";"):
                if raw:
                    key, is_src = topfuncs.frame_key(raw)
                    frames.append(key)
                    in_src[key] = is_src
            for key in set(frames):
                cumulative[key] += count
            if frames:
                self_time[frames[-1]] += count
    return cumulative, self_time, total, in_src


def median_table(profiles, rate, only_src, top):
    keys = set()
    for cumulative, _, _, _ in profiles:
        keys |= set(cumulative)
    in_src = {}
    for _, _, _, flags in profiles:
        in_src.update(flags)
    rows = []
    for key in keys:
        if only_src and not in_src.get(key):
            continue
        cums = [c.get(key, 0) / rate for c, _, _, _ in profiles]
        selfs = [s.get(key, 0) / rate for _, s, _, _ in profiles]
        rows.append((statistics.median(cums), statistics.median(selfs), cums, key))
    rows.sort(key=lambda r: -r[0])
    return rows[:top]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--rate", type=int, default=200)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    walls, phases = [], []
    for i in range(1, args.runs + 1):
        with open(os.path.join(args.out, "timings", "run-%d.json" % i), encoding="utf-8") as handle:
            record = json.load(handle)
        walls.append(record["total"])
        phases.append(record["phases"])
    profiles = [read_profile(os.path.join(args.out, "profiles", "run-%d.raw" % i))
                for i in range(1, args.runs + 1)]

    print("PaintOmics profiling report -- tests/perf/large_input (20,000 genes x 6, 5,000 proteins x 6, 400 compounds x 6)")
    print("host: %s %s, %s, python %s" % (platform.system(), platform.release(), platform.machine(), platform.python_version()))
    print("runs: %d un-profiled wall clocks, %d py-spy recordings at %d Hz (subprocesses included); every run a fresh interpreter (cold caches)" % (args.runs, args.runs, args.rate))
    print()
    print("Wall clock (s): " + ", ".join("%.2f" % w for w in walls) + "  -> median %.2f" % statistics.median(walls))
    phase_keys = sorted(phases[0], key=lambda k: -statistics.median(p.get(k, 0) for p in phases))
    print("Phase medians (s):")
    for key in phase_keys:
        print("    %-48s %8.2f" % (key, statistics.median(p.get(key, 0) for p in phases)))
    print()
    totals = [t for _, _, t, _ in profiles]
    print("Samples per profiled run: " + ", ".join(str(t) for t in totals))
    print()
    print("Top %d functions of PaintomicsServer/src by cumulative time (median over %d recordings; seconds = samples / %d Hz)" % (args.top, args.runs, args.rate))
    print("%4s %9s %9s  %-24s %s" % ("#", "cumul s", "self s", "per run (s)", "function (file)"))
    for rank, (cum, self_s, cums, key) in enumerate(median_table(profiles, args.rate, True, args.top), 1):
        print("%4d %9.2f %9.2f  %-24s %s" % (rank, cum, self_s, "/".join("%.1f" % c for c in cums), key))
    print()
    print("Top %d frames overall (libraries included), same measure" % args.top)
    print("%4s %9s %9s  %s" % ("#", "cumul s", "self s", "function (file)"))
    for rank, (cum, self_s, cums, key) in enumerate(median_table(profiles, args.rate, False, args.top), 1):
        print("%4d %9.2f %9.2f  %s" % (rank, cum, self_s, key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
