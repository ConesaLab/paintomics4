#!/usr/bin/env python3
"""Compare two scripts/perf/profile.sh output directories (before / after).

For the functions named on the command line (the ones chosen for
optimisation, by default the pre-optimisation top three) print the median
cumulative seconds in each directory and the change; then the wall clocks
and their medians.

    python scripts/perf/compare.py <before-dir> <after-dir> --runs 3 --rate 200 \
        --function "processFilesContent (classes/JobInstances/PathwayAcquisitionJob.py)" ...
"""
import argparse
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import report  # noqa: E402

DEFAULT_FUNCTIONS = [
    "processFilesContent (classes/JobInstances/PathwayAcquisitionJob.py)",
    "parseGeneBasedFiles (classes/Job.py)",
    "mapFeatureNamesToKeggIDs (common/FeatureNamesToKeggIDsMapper.py)",
]


def load(directory, runs, rate):
    profiles = [report.read_profile(os.path.join(directory, "profiles", "run-%d.raw" % i))
                for i in range(1, runs + 1)]
    walls = []
    for i in range(1, runs + 1):
        with open(os.path.join(directory, "timings", "run-%d.json" % i), encoding="utf-8") as handle:
            walls.append(json.load(handle)["total"])
    return profiles, walls


def seconds(profiles, key, rate):
    return [cumulative.get(key, 0) / rate for cumulative, _, _, _, _ in profiles]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--rate", type=int, default=200)
    parser.add_argument("--function", action="append", default=None)
    args = parser.parse_args(argv)
    functions = args.function or DEFAULT_FUNCTIONS

    before, walls_before = load(args.before, args.runs, args.rate)
    after, walls_after = load(args.after, args.runs, args.rate)

    print("Cumulative time per function, median over %d py-spy recordings each (s)" % args.runs)
    print("%-72s %9s %9s %8s" % ("function (file)", "before", "after", "change"))
    for key in functions:
        b = statistics.median(seconds(before, key, args.rate))
        a = statistics.median(seconds(after, key, args.rate))
        change = (a - b) / b * 100 if b else float("nan")
        print("%-72s %9.2f %9.2f %+7.1f%%   (runs: %s -> %s)" % (
            key, b, a, change,
            "/".join("%.1f" % s for s in seconds(before, key, args.rate)),
            "/".join("%.1f" % s for s in seconds(after, key, args.rate))))
    print()
    print("Wall clock, %d cold runs each (s)" % args.runs)
    print("  before: %s -> median %.2f" % (", ".join("%.2f" % w for w in walls_before), statistics.median(walls_before)))
    print("  after:  %s -> median %.2f" % (", ".join("%.2f" % w for w in walls_after), statistics.median(walls_after)))
    mb, ma = statistics.median(walls_before), statistics.median(walls_after)
    print("  change: %+.1f%%" % ((ma - mb) / mb * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
