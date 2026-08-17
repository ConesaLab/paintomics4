#!/usr/bin/env python3
"""Interleaved A/B timing sweep: for every scenario and repeat, run the
baseline checkout and the candidate checkout back to back under the same
machine conditions, so drift (thermal, background load) hits both sides
alike. Output trees are bench_all-compatible.

    PAINTOMICS_KEGG_DATA=... PAINTOMICS_CLIENT_TMP=... \
    python -m src.benchmarks.bench_ab \
        --a /path/to/baseline/PaintomicsServer --b /path/to/candidate/PaintomicsServer \
        --out /tmp/bench/ab --repeat 3
"""
import argparse
import json
import os
import subprocess
import sys
import time

from src.benchmarks.bench_all import DEFAULT_SCENARIOS


def runOne(root, scenario, runDir, python, env, timeout):
    os.makedirs(runDir, exist_ok=True)
    started = time.time()
    proc = subprocess.run(
        [python, "-m", "src.benchmarks.bench_runner", "--scenario", scenario, "--out", runDir],
        cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
    record = {"scenario": scenario, "wall": round(time.time() - started, 2),
              "returncode": proc.returncode, "root": root}
    if proc.returncode == 0:
        try:
            record.update(json.loads(proc.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            pass
    else:
        record["stderr_tail"] = proc.stderr[-3000:]
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True, help="baseline PaintomicsServer dir")
    parser.add_argument("--b", required=True, help="candidate PaintomicsServer dir")
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--scenarios", nargs="*", default=DEFAULT_SCENARIOS)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()

    env = dict(os.environ, PYTHONHASHSEED="0")
    summary = []
    for scenario in args.scenarios:
        for run in range(1, args.repeat + 1):
            for label, root in (("A", args.a), ("B", args.b)):
                runDir = os.path.join(args.out, label, scenario, "run%d" % run)
                record = runOne(root, scenario, runDir, args.python, env, args.timeout)
                record.update({"side": label, "run": run})
                summary.append(record)
                print("%-32s run%d %s %8.1fs %s" % (
                    scenario, run, label, record["wall"],
                    "ok" if record["returncode"] == 0 else "FAIL"), flush=True)
                with open(os.path.join(args.out, "summary.json"), "w") as handle:
                    json.dump(summary, handle, indent=2)

    failures = [r for r in summary if r["returncode"] != 0]
    print("\n%d/%d runs ok" % (len(summary) - len(failures), len(summary)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
