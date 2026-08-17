#!/usr/bin/env python3
"""Compare two bench_all output trees (baseline vs candidate).

Verdict per scenario:
    IDENTICAL   every artifact deep-equal (bitwise floats, NaN==NaN)
    EQUIVALENT  only float differences, all within --rtol (default 1e-12)
    DIFFERENT   anything else -- every differing path is listed

Comparison rules encode the client contract (see the reader reports):
dict *values* are compared key-by-key regardless of key order, EXCEPT the
paths in ORDERED_DICT_PATHS whose insertion order the client renders; lists
are order-sensitive everywhere (list-typed artifacts are either contractually
ordered, e.g. matchedMetabolites, or pre-sorted at capture time, e.g.
mapping-file lines).

    python -m src.benchmarks.bench_compare --a /tmp/bench/baseline \
        --b /tmp/bench/candidate [--rtol 1e-12]
"""
import argparse
import gzip
import json
import math
import os
import sys

# Dict paths whose KEY ORDER is part of the contract (client iterates and
# renders in insertion order).
ORDERED_DICT_PATHS = (
    "step2.classificationDict",
)

MAX_REPORTED_DIFFS = 40


class Comparison(object):
    def __init__(self, rtol):
        self.rtol = rtol
        self.diffs = []          # (path, kind, detail)
        self.maxFloatRel = 0.0
        self.floatOnly = True

    def record(self, path, kind, detail):
        self.diffs.append((path, kind, detail))
        if kind != "float":
            self.floatOnly = False

    def compare(self, a, b, path=""):
        if isinstance(a, float) or isinstance(b, float):
            self._floats(a, b, path)
            return
        if isinstance(a, dict) and isinstance(b, dict):
            self._dicts(a, b, path)
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                self.record(path, "len", "list %d vs %d" % (len(a), len(b)))
                return
            for index, (itemA, itemB) in enumerate(zip(a, b)):
                self.compare(itemA, itemB, "%s[%d]" % (path, index))
            return
        if type(a) is not type(b):
            # bool/int cross-type or str-vs-number: type is contract-relevant
            self.record(path, "type", "%s vs %s (%r vs %r)"
                        % (type(a).__name__, type(b).__name__,
                           _short(a), _short(b)))
            return
        if a != b:
            self.record(path, "value", "%r vs %r" % (_short(a), _short(b)))

    def _floats(self, a, b, path):
        okA = isinstance(a, (int, float)) and not isinstance(a, bool)
        okB = isinstance(b, (int, float)) and not isinstance(b, bool)
        if not (okA and okB):
            self.record(path, "type", "%s vs %s" % (type(a).__name__,
                                                    type(b).__name__))
            return
        a, b = float(a), float(b)
        if math.isnan(a) and math.isnan(b):
            return
        if a == b:
            return
        denom = max(abs(a), abs(b), 1e-300)
        rel = abs(a - b) / denom
        self.maxFloatRel = max(self.maxFloatRel, rel)
        if rel > self.rtol:
            self.record(path, "float-out-of-tol", "%r vs %r (rel %.3g)"
                        % (a, b, rel))
        else:
            self.record(path, "float", "%r vs %r (rel %.3g)" % (a, b, rel))

    def _dicts(self, a, b, path):
        keysA, keysB = list(a.keys()), list(b.keys())
        if set(keysA) != set(keysB):
            onlyA = sorted(set(keysA) - set(keysB))[:6]
            onlyB = sorted(set(keysB) - set(keysA))[:6]
            self.record(path, "keys", "only in A: %s; only in B: %s"
                        % (onlyA, onlyB))
        if any(path.endswith(ordered) for ordered in ORDERED_DICT_PATHS):
            shared = [k for k in keysA if k in b]
            sharedB = [k for k in keysB if k in a]
            if shared != sharedB:
                self.record(path, "key-order", "%s vs %s"
                            % (shared[:8], sharedB[:8]))
        for key in keysA:
            if key in b:
                self.compare(a[key], b[key], "%s.%s" % (path, key))


def _short(value, limit=120):
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def loadArtifacts(runDir):
    path = os.path.join(runDir, "artifacts.json.gz")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def compareScenario(dirA, dirB, rtol):
    comparison = Comparison(rtol)
    comparison.compare(loadArtifacts(dirA), loadArtifacts(dirB))
    hard = [d for d in comparison.diffs if d[1] not in ("float",)]
    if not comparison.diffs:
        return "IDENTICAL", comparison
    if not hard and comparison.maxFloatRel <= rtol:
        return "EQUIVALENT", comparison
    return "DIFFERENT", comparison


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True, help="baseline bench_all --out dir")
    parser.add_argument("--b", required=True, help="candidate bench_all --out dir")
    parser.add_argument("--run", default="run1")
    parser.add_argument("--rtol", type=float, default=1e-12)
    args = parser.parse_args()

    scenarios = sorted(
        name for name in os.listdir(args.a)
        if os.path.isdir(os.path.join(args.a, name, args.run)))

    exitCode = 0
    for scenario in scenarios:
        dirA = os.path.join(args.a, scenario, args.run)
        dirB = os.path.join(args.b, scenario, args.run)
        if not os.path.isdir(dirB):
            print("%-32s MISSING in B" % scenario)
            exitCode = 1
            continue
        try:
            verdict, comparison = compareScenario(dirA, dirB, args.rtol)
        except Exception as exc:
            print("%-32s ERROR %s" % (scenario, exc))
            exitCode = 1
            continue
        line = "%-32s %-10s" % (scenario, verdict)
        if comparison.maxFloatRel:
            line += " maxFloatRel=%.3g" % comparison.maxFloatRel
        print(line)
        if verdict == "DIFFERENT":
            exitCode = 1
            shown = 0
            for path, kind, detail in comparison.diffs:
                if kind == "float":
                    continue
                print("    %s [%s] %s" % (path or "<root>", kind, detail))
                shown += 1
                if shown >= MAX_REPORTED_DIFFS:
                    remaining = sum(1 for d in comparison.diffs
                                    if d[1] != "float") - shown
                    if remaining > 0:
                        print("    ... and %d more" % remaining)
                    break
    sys.exit(exitCode)


if __name__ == "__main__":
    main()
