#!/usr/bin/env python3
"""Summarise an A/B tree (bench_ab or two bench_all trees) into a Markdown
table of per-scenario, per-phase medians with speed-ups, plus the
equivalence verdict from bench_compare for each scenario.

    python -m src.benchmarks.bench_report --a /tmp/bench/ab/A --b /tmp/bench/ab/B \
        [--strict-a /tmp/bench/baseline-mt1 --strict-b /tmp/bench/cand-mt1] \
        --out report.md
"""
import argparse
import json
import os
import statistics

from src.benchmarks.bench_compare import compareScenario


def loadRuns(root, scenario):
    runs = []
    scenarioDir = os.path.join(root, scenario)
    if not os.path.isdir(scenarioDir):
        return runs
    for name in sorted(os.listdir(scenarioDir)):
        path = os.path.join(scenarioDir, name, "timings.json")
        if os.path.isfile(path):
            with open(path) as handle:
                runs.append(json.load(handle))
    return runs


def medians(runs):
    phases = {}
    keys = set()
    for run in runs:
        keys.update(run.get("phases", {}).keys())
    for key in sorted(keys):
        values = [run["phases"][key] for run in runs if key in run.get("phases", {})]
        if values:
            phases[key] = statistics.median(values)
    total = statistics.median([run["total"] for run in runs]) if runs else None
    return total, phases


def fmt(seconds):
    if seconds is None:
        return "-"
    return "%.2f" % seconds if seconds < 100 else "%.1f" % seconds


def speedup(a, b):
    if a is None or b is None or b <= 0:
        return "-"
    return "%.2fx" % (a / b)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--strict-a")
    parser.add_argument("--strict-b")
    parser.add_argument("--rtol", type=float, default=1e-12)
    parser.add_argument("--out", required=True)
    parser.add_argument("--title", default="PaintOmics pipeline benchmark: baseline vs candidate")
    args = parser.parse_args()

    scenarios = sorted(name for name in set(os.listdir(args.a)) & set(os.listdir(args.b))
                       if os.path.isdir(os.path.join(args.a, name)) and os.path.isdir(os.path.join(args.b, name)))
    lines = ["# %s" % args.title, ""]
    lines.append("| Scenario | Baseline median (s) | Candidate median (s) | Speed-up | Runs (A/B) | Equivalence (timing runs) | Equivalence (strict, 1 worker) |")
    lines.append("|---|---:|---:|---:|:-:|:-:|:-:|")
    details = []
    for scenario in scenarios:
        runsA, runsB = loadRuns(args.a, scenario), loadRuns(args.b, scenario)
        totalA, phasesA = medians(runsA)
        totalB, phasesB = medians(runsB)
        try:
            verdict, comparison = compareScenario(os.path.join(args.a, scenario, "run1"),
                                                  os.path.join(args.b, scenario, "run1"), args.rtol)
        except Exception as exc:
            verdict, comparison = "ERROR: %s" % exc, None
        strictVerdict = "-"
        if args.strict_a and args.strict_b:
            try:
                strictVerdict, strictComparison = compareScenario(
                    os.path.join(args.strict_a, scenario, "run1"),
                    os.path.join(args.strict_b, scenario, "run1"), args.rtol)
            except Exception as exc:
                strictVerdict = "ERROR: %s" % exc
        lines.append("| %s | %s | %s | %s | %d/%d | %s | %s |" % (
            scenario, fmt(totalA), fmt(totalB), speedup(totalA, totalB),
            len(runsA), len(runsB), verdict, strictVerdict))
        details.append((scenario, phasesA, phasesB, verdict, comparison))

    lines.append("")
    lines.append("## Per-phase medians")
    for scenario, phasesA, phasesB, verdict, comparison in details:
        lines.append("")
        lines.append("### %s" % scenario)
        lines.append("")
        lines.append("| Phase | Baseline (s) | Candidate (s) | Speed-up |")
        lines.append("|---|---:|---:|---:|")
        for key in sorted(set(phasesA) | set(phasesB)):
            a, b = phasesA.get(key), phasesB.get(key)
            if (a or 0) < 0.05 and (b or 0) < 0.05:
                continue
            lines.append("| %s | %s | %s | %s |" % (key, fmt(a), fmt(b), speedup(a, b)))
        if comparison is not None and verdict == "DIFFERENT":
            lines.append("")
            lines.append("Differences (timing runs, first 15):")
            shown = 0
            for path, kind, detail in comparison.diffs:
                if kind == "float":
                    continue
                lines.append("- `%s` [%s] %s" % (path, kind, detail[:160]))
                shown += 1
                if shown >= 15:
                    break

    with open(args.out, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    print("\n".join(lines[:len(scenarios) + 4]))


if __name__ == "__main__":
    main()
