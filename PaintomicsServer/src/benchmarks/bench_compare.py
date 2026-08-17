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
import re
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
            if isinstance(a, str) and _stripCheckout(a) == _stripCheckout(b):
                return  # same file, different checkout root (A vs B worktree)
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


_CHECKOUT_ROOT = re.compile(r"^.*?/PaintomicsServer/")


def _stripCheckout(text):
    """Absolute example-file paths embed the checkout the run used; the A and
    B sides of a comparison are different worktrees by construction."""
    return _CHECKOUT_ROOT.sub("<checkout>/PaintomicsServer/", text)


def _short(value, limit=120):
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def loadArtifacts(runDir):
    path = os.path.join(runDir, "artifacts.json.gz")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


_PATH_INDEX = re.compile(r"\[\d+\]")


def pathClass(path):
    """A path with its data-dependent parts collapsed: list indices become
    [*], and from the third segment on every segment that has no lower-case
    letter (feature IDs, symbols, numeric keys -- schema keys are camelCase)
    becomes *, so `.step3.omicsValues.GSTP1.omicsValues[2].inputName` and the
    same field of another feature share a class."""
    generic = _PATH_INDEX.sub("[*]", path)
    parts = generic.split(".")
    for index in range(3, len(parts)):
        segment = parts[index]
        if segment and not any(ch.islower() for ch in segment.replace("[*]", "")):
            parts[index] = "*"
    return ".".join(parts)


def noiseClasses(dirA, dirB, rtol):
    """The diff classes two runs of the SAME code produce (run-to-run
    noise, e.g. which of two aliases wins a symbol-keyed slot after the
    forked mapper workers race). Used to tell a candidate's differences
    from the baseline's own nondeterminism."""
    comparison = Comparison(rtol)
    comparison.compare(loadArtifacts(dirA), loadArtifacts(dirB))
    return {pathClass(path) for path, kind, _ in comparison.diffs}


def compareScenario(dirA, dirB, rtol, noise=None):
    """Verdicts: IDENTICAL; EQUIVALENT (floats within rtol only);
    WITHIN-NOISE (every remaining difference falls in a class the baseline
    produces between two runs of itself -- only when `noise` is given);
    DIFFERENT."""
    comparison = Comparison(rtol)
    comparison.compare(loadArtifacts(dirA), loadArtifacts(dirB))
    hard = [d for d in comparison.diffs if d[1] not in ("float",)]
    if not comparison.diffs:
        return "IDENTICAL", comparison
    if not hard and comparison.maxFloatRel <= rtol:
        return "EQUIVALENT", comparison
    if noise is not None:
        outside = [d for d in comparison.diffs
                   if d[1] != "float" and pathClass(d[0]) not in noise]
        if not outside:
            return "WITHIN-NOISE", comparison
        comparison.outsideNoise = outside
    return "DIFFERENT", comparison


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True, help="baseline bench_all --out dir")
    parser.add_argument("--b", required=True, help="candidate bench_all --out dir")
    parser.add_argument("--run", default="run1")
    parser.add_argument("--rtol", type=float, default=1e-12)
    parser.add_argument("--noise-runs", nargs=2, metavar=("RUN_X", "RUN_Y"),
                        help="two run names under --a (e.g. run1 run2) whose "
                             "mutual differences define the baseline's own noise")
    args = parser.parse_args()

    scenarios = sorted(
        name for name in os.listdir(args.a)
        if os.path.isdir(os.path.join(args.a, name, args.run)))

    # The baseline's own run-to-run noise, pooled over every scenario: the
    # mechanism (forked mapper workers racing on which alias fills a slot)
    # is the same whatever the dataset, and one pair of runs of one dataset
    # samples only some of the slots it can hit.
    noise = None
    if args.noise_runs:
        noise = set()
        for scenario in scenarios:
            noiseA = os.path.join(args.a, scenario, args.noise_runs[0])
            noiseB = os.path.join(args.a, scenario, args.noise_runs[1])
            if os.path.isdir(noiseA) and os.path.isdir(noiseB):
                noise |= noiseClasses(noiseA, noiseB, args.rtol)
        print("baseline noise classes (%d): %s" % (len(noise), sorted(noise)))

    exitCode = 0
    for scenario in scenarios:
        dirA = os.path.join(args.a, scenario, args.run)
        dirB = os.path.join(args.b, scenario, args.run)
        if not os.path.isdir(dirB):
            print("%-32s MISSING in B" % scenario)
            exitCode = 1
            continue
        try:
            verdict, comparison = compareScenario(dirA, dirB, args.rtol, noise)
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
            reportable = getattr(comparison, "outsideNoise", None) or comparison.diffs
            for path, kind, detail in reportable:
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
