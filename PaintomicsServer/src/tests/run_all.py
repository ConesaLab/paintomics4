#!/usr/bin/env python3
"""Run every test suite and report what THIS branch broke.

There is no runner in this repo -- each suite is a standalone `__main__` script,
so "run the tests" has meant a shell loop, and a shell loop gets the answer
wrong. The first one written for this branch reported 148 of 215 suites as
not-passing; all but a handful had exited 0 and simply not printed a line the
loop's regex recognised. A runner that cannot tell a pass from a silence is worse
than none, because its output looks like work.

Three output conventions are in use here and all three are legitimate:

    Passed: 7 / 7        the standalone _check/_PASSED style
    OK / FAILED          unittest
    (nothing)            a script that just exits 0

So classification reads, in order: an explicit Passed line, then a unittest
verdict, then the exit code.

The second thing this fixes is more expensive. Several suites fail on `master`
too -- and finding that out cost most of an afternoon, because a worktree at
origin/master had no `serverconf.py` (it is gitignored), so every test SKIPPED
and the run reported `OK` while executing zero tests. A green result that ran
nothing is the worst possible answer to "did I break this". BASELINE records the
suites already failing on master, so a run can answer the question that matters:
did this branch introduce a failure?

    python -m src.tests.run_all                  # everything
    python -m src.tests.run_all --only ai        # substring filter
    python -m src.tests.run_all --baseline       # rewrite BASELINE from this run
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# Suites that fail on origin/master in a normal dev environment, verified by
# running them in a master worktree with this checkout's serverconf.py copied in.
# A failure here is inherited, not caused. Trim this list when master goes green;
# never add to it to make a branch look clean.
BASELINE = {
    "test_ai_agent_endtoend": "3 failures: the stub gateway cannot satisfy the "
                              "quote extractor, so reference [1] renders with no "
                              "Cited Text and every citation is then redacted",
    "test_more_servlet_step1": "17 failures",
    "test_pathway_universe_database_filter": "1 failure",
    "test_relevance_file_shape_and_conditions": "2 failures",
    "test_dependencies_declared": "1 failure: an external import does not resolve",
}


def classify(returncode, out):
    """PASS / FAIL from whichever convention the suite used."""
    counted = re.search(r"Passed:\s*(\d+)\s*/\s*(\d+)", out)
    if counted:
        ok, total = int(counted.group(1)), int(counted.group(2))
        return "PASS" if (ok == total and returncode == 0) else "FAIL"
    verdict = re.search(r"^(OK|FAILED)", out, re.M)
    if verdict:
        return "PASS" if (verdict.group(1) == "OK" and returncode == 0) else "FAIL"
    return "PASS" if returncode == 0 else "FAIL"


def run_one(name, timeout):
    env = dict(os.environ)
    # serverconf reads this at import time; without it the AI suites skip and a
    # skipped suite reports OK.
    env.setdefault("PAINTOMICS_KEGG_DATA",
                   os.path.expanduser("~/Desktop/github_dev/paintomics4_data"))
    started = time.time()
    try:
        proc = subprocess.run([sys.executable, "-m", "src.tests." + name],
                              capture_output=True, text=True, timeout=timeout,
                              cwd=_ROOT, env=env)
        out = proc.stdout + proc.stderr
        state = classify(proc.returncode, out)
        skipped = bool(re.search(r"Ran 0 tests|OK \(skipped", out))
    except subprocess.TimeoutExpired:
        out, state, skipped = "", "TIMEOUT", False
    return {"suite": name, "state": state, "skipped": skipped,
            "secs": round(time.time() - started, 1),
            "failing": re.findall(r"^FAIL[: ]+(\S+)", out, re.M)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", default="", help="substring filter on suite name")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--baseline", action="store_true",
                        help="print a BASELINE block from this run's failures")
    args = parser.parse_args(argv)

    names = sorted(os.path.basename(p)[:-3]
                   for p in glob.glob(os.path.join(_ROOT, "src/tests/test_*.py")))
    if args.only:
        names = [n for n in names if args.only in n]

    results = [run_one(n, args.timeout) for n in names]
    bad = [r for r in results if r["state"] != "PASS"]
    inherited = [r for r in bad if r["suite"] in BASELINE]
    introduced = [r for r in bad if r["suite"] not in BASELINE]
    skipped = [r for r in results if r["skipped"]]

    print("%d suites | %d pass | %d inherited | %d INTRODUCED"
          % (len(results), len(results) - len(bad), len(inherited), len(introduced)))
    if skipped:
        print("\n%d suite(s) skipped everything -- a skip is not a pass:" % len(skipped))
        for r in skipped:
            print("   %s" % r["suite"])
    if inherited:
        print("\ninherited from master (not this branch):")
        for r in inherited:
            print("   %-46s %s" % (r["suite"], BASELINE[r["suite"]][:60]))
    if introduced:
        print("\nINTRODUCED BY THIS BRANCH:")
        for r in introduced:
            print("   %-46s %s" % (r["suite"], ", ".join(r["failing"])[:60]))

    if args.baseline:
        print("\nBASELINE = {")
        for r in bad:
            print('    "%s": "",' % r["suite"])
        print("}")

    return 1 if introduced else 0


if __name__ == "__main__":
    sys.exit(main())
