#!/usr/bin/env python3
"""Run every (or a chosen) example scenario through bench_runner, N times each,
in fresh subprocesses, and collect the timing summaries.

    PAINTOMICS_KEGG_DATA=... PAINTOMICS_CLIENT_TMP=... \
    python -m src.benchmarks.bench_all --out /tmp/bench/baseline --repeat 3

PYTHONHASHSEED is pinned so set-iteration order cannot masquerade as a result
difference between two builds; both sides of an A/B comparison must run
through this driver for that pin to hold.
"""
import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DEFAULT_SCENARIOS = [
    "gene-single-condition",
    "gene-multi-condition",
    "gene-multi-condition-relevance",
    "multiomics-integration",
    "regulatory-mirna",
    "regulatory-more",
    "region-based",
    "stategra-multiomics",
    "stategra-regions",
    "stategra-mirna",
    "stategra-more",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--scenarios", nargs="*", default=DEFAULT_SCENARIOS)
    parser.add_argument("--timeout", type=int, default=3600,
                        help="per-run kill timeout in seconds")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    env = dict(os.environ, PYTHONHASHSEED="0")

    summary = []
    for scenario in args.scenarios:
        for run in range(1, args.repeat + 1):
            runDir = os.path.join(args.out, scenario, "run%d" % run)
            os.makedirs(runDir, exist_ok=True)
            started = time.time()
            proc = subprocess.run(
                [args.python, "-m", "src.benchmarks.bench_runner",
                 "--scenario", scenario, "--out", runDir],
                cwd=ROOT, env=env, capture_output=True, text=True,
                timeout=args.timeout)
            elapsed = round(time.time() - started, 2)
            record = {"scenario": scenario, "run": run, "wall": elapsed,
                      "returncode": proc.returncode}
            if proc.returncode == 0:
                try:
                    record.update(json.loads(proc.stdout.strip().splitlines()[-1]))
                except (ValueError, IndexError):
                    pass
            else:
                record["stderr_tail"] = proc.stderr[-3000:]
            summary.append(record)
            status = "ok" if proc.returncode == 0 else "FAIL"
            print("%-32s run%d %8.1fs %s" % (scenario, run, elapsed, status),
                  flush=True)
            with open(os.path.join(args.out, "summary.json"), "w") as handle:
                json.dump(summary, handle, indent=2)

    failures = [r for r in summary if r["returncode"] != 0]
    print("\n%d/%d runs ok" % (len(summary) - len(failures), len(summary)))
    if failures:
        for record in failures:
            print("FAILED: %(scenario)s run%(run)d" % record)
        sys.exit(1)


if __name__ == "__main__":
    main()
