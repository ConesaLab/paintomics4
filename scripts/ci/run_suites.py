#!/usr/bin/env python3
"""Run the PaintomicsServer test suites N at a time and report like run_all.

src/tests/run_all.py is the repository's runner: it knows the three output
conventions the suites use and which suites already fail on master (its
BASELINE), and it runs them one after another. Sequential is ~9.5 minutes on
a laptop, which is the whole PR budget on its own, so this wrapper reuses
run_all's classification unchanged and only changes the scheduling: suites
run concurrently in subprocesses, and every suite's duration is printed so
a slow one can be seen rather than guessed.

    python scripts/ci/run_suites.py --jobs 4 [--timeout 180] [--only SUBSTR]

Exit status 1 when any suite fails that run_all's BASELINE does not already
list -- exactly run_all's rule. Suites that skipped every test are listed
(a skip is not a pass) but, as in run_all, do not fail the run.
"""
import argparse
import glob
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.abspath(os.path.join(HERE, "..", "..", "PaintomicsServer"))
sys.path.insert(0, SERVER)

from src.tests import run_all  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--only", default="")
    parser.add_argument("--slowest", type=int, default=15,
                        help="how many of the slowest suites to list")
    args = parser.parse_args(argv)

    names = sorted(os.path.basename(path)[:-3]
                   for path in glob.glob(os.path.join(SERVER, "src/tests/test_*.py")))
    if args.only:
        names = [name for name in names if args.only in name]
    if not names:
        print("no suite matched", file=sys.stderr)
        return 2

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda name: run_all.run_one(name, args.timeout), names))

    bad = [r for r in results if r["state"] != "PASS"]
    inherited = [r for r in bad if r["suite"] in run_all.BASELINE]
    introduced = [r for r in bad if r["suite"] not in run_all.BASELINE]
    skipped = [r for r in results if r["skipped"]]
    total = sum(r["secs"] for r in results)

    print("%d suites | %d pass | %d inherited | %d INTRODUCED | %d skipped everything"
          % (len(results), len(results) - len(bad), len(inherited), len(introduced),
             len(skipped)))
    print("suite time %.0f s summed, %d at a time" % (total, args.jobs))
    print("\nslowest:")
    for r in sorted(results, key=lambda r: -r["secs"])[:args.slowest]:
        print("   %6.1f s  %-50s %s" % (r["secs"], r["suite"], r["state"]))
    if inherited:
        print("\ninherited from master (run_all.BASELINE):")
        for r in inherited:
            print("   %-50s %s" % (r["suite"], run_all.BASELINE[r["suite"]][:70]))
    if skipped:
        print("\nskipped everything -- a skip is not a pass:")
        for r in skipped:
            print("   %s" % r["suite"])
    if introduced:
        print("\nFAILED (not in BASELINE):")
        for r in introduced:
            print("   %-50s %s %s" % (r["suite"], r["state"], ", ".join(r["failing"])[:80]))
    return 1 if introduced else 0


if __name__ == "__main__":
    sys.exit(main())
