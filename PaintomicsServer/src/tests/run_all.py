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
# The count is FAIL plus ERROR, not the "failures=N" that unittest prints in its
# last line: an exception is a test that broke before it reached an assertion,
# and unittest reports those separately. test_more_servlet_step1 is why this is
# spelled out -- it ran for months recorded as "17 failures" while producing 17
# failures and one error (ERROR: test_queues_step2_with_the_job), so the
# eighteenth broken test was outside the count by construction.
#
# It is empty, and worth keeping empty. The five entries that used to live here
# -- 26 tests, carried for months -- were read one at a time, and every one came
# back either a defect in the test or, in the largest case, a defect in the
# server. Not one was the "known broken, nothing to do" it was filed as:
#
#   test_more_servlet_step1 (18)  A REAL BUG. engineRefusal resolved `auto` to
#       the Rust engine and then refused it, so on a host with no more-rs binary
#       every PLS1 submission naming no engine -- an older client, a resubmitted
#       job, a scripted POST -- was turned away with the reference R engine
#       available. Fixed in MOREServlet.engineRefusal, along with the
#       backendUsed/engineId mismatch the same resolution caused, and pinned by
#       two new tests in test_more_engine_choice.
#   test_ai_agent_endtoend (4)    Asserts on references built from PubMed, which
#       this suite deliberately does not stub. Offline there are no papers, so
#       those four skip with the reason; the four that need no retrieval run.
#   test_relevance_file_shape_and_conditions (2)  Pinned `Nup50` and a literal
#       region id in regenerated example data -- exactly the trap the file's own
#       firstDataRow() helper exists to avoid, applied to its other tests but
#       never to these two.
#   test_pathway_universe_database_filter (1)  Asserted the size of the whole mmu
#       universe, so installing a supported fourth database (OmniPath, +120)
#       broke it while every KEGG and Reactome count stayed exactly right.
#   test_dependencies_declared (1)  Reported four first-party modules as missing
#       third-party ones, because the hand-written list of this repository's own
#       module names had gone stale.
#
# The lesson is in that arithmetic. A list like this gets read as "known and
# accepted", but nothing here was accepted on purpose, and one entry was hiding
# a refusal real users would have hit. If a suite ever has to go back on it,
# write the reason and the date into the value and treat the entry as a ticket
# rather than as a fact.
BASELINE = {}

# Both conventions the suites use to name a broken test: unittest's
# "FAIL: test_x (mod.Class)" / "ERROR: test_x (mod.Class)", and the hand-rolled
# runners' "FAIL  name". The separator must be a colon FOLLOWED by whitespace,
# or two spaces -- not a bare colon. `logging.error()` writes "ERROR:root:..."
# at the start of a line once basicConfig has run, and the server logs on every
# report, mail and hub failure path, so the looser `[: ]+` counted log records
# as failing tests: it inflated the number written into BASELINE, and a suite
# whose logging then went quiet could acquire that many real failures unnoticed.
FAILING_TEST = re.compile(r"^(?:FAIL|ERROR)(?::[ \t]+|[ \t]{2,})(\S+)", re.M)

# How many tests a suite actually executed, in whichever convention it used --
# unittest's "Ran 29 tests in 5.076s", the hand-rolled runners' "Passed: 3 / 4".
# None means neither line appeared, which is what a suite that died on import
# looks like.
_RAN_UNITTEST = re.compile(r"^Ran (\d+) tests?\b", re.M)
_RAN_HANDROLLED = re.compile(r"Passed:\s*\d+\s*/\s*(\d+)")


def tests_run(out):
    """The number of tests the run reported executing, or None if it never said."""
    match = _RAN_UNITTEST.search(out) or _RAN_HANDROLLED.search(out)
    return int(match.group(1)) if match else None


# A class or module fixture that raises: unittest prints one `ERROR: setUpClass`
# line and then silently does not run that class's tests, while the OTHER
# classes in the file run normally -- so the suite still reports a healthy
# "Ran 8 tests". The count rule is blind to it, because the dead fixture is
# exactly one name: a suite baselined for one failure can trade its known
# failure for an entire class that stopped executing and still compare equal.
# Whatever else is true, a run in that state has not reproduced the baseline,
# so it is never credited with it.
BROKEN_FIXTURE = re.compile(r"^ERROR:[ \t]+((?:setUp|tearDown)(?:Class|Module))\b", re.M)


def baseline_failures(suite):
    """How many failing tests this suite is known to have on master.

    `None` means the suite is not baselined at all, so any failure belongs to
    this branch. Otherwise it is the count BASELINE's own text states, and a run
    that fails MORE times than that has introduced something even though the
    suite name is on the list.

    A note with no parseable count raises rather than shielding the suite. The
    silent version of that used to be printable: `--baseline` emitted an entry
    per failing suite with an empty note, and pasting it back would have made
    every listed suite absorb an unlimited number of new failures forever.
    """
    note = BASELINE.get(suite)
    if note is None:
        return None
    match = re.match(r"\s*(\d+)\s+failures?\b", note)
    if not match:
        raise ValueError(
            "BASELINE[%r] does not begin with a count: %r. Write it as "
            "'<n> failures: why', because a baseline entry without a number "
            "shields the suite from every new failure it acquires." % (suite, note))
    return int(match.group(1))


def check_baseline():
    """Every BASELINE note states a count -- checked before anything runs."""
    for suite in BASELINE:
        baseline_failures(suite)


def split_by_baseline(bad):
    """Partition failing suites into (inherited, introduced).

    Matching on the suite NAME alone was the original hole: a suite baselined
    for one known failure absorbed a brand-new second one and the gate stayed
    green. Counting closed that. This closes the ways a count can still be
    fooled: a failure reported as ERROR was never counted at all, and a suite
    that never reaches its tests still compares favourably against its baseline.

    That last one is not only the import crash, which names nothing. unittest
    reports a broken class fixture as a single `ERROR: setUpClass (...)` line
    and then runs none of that class's tests -- one name against a baseline of
    four, which read as "no worse than master" while a whole class had stopped
    executing. If the file holds a second class the count does not even drop:
    planting a `raise` in one setUpClass of test_pathway_universe_database_filter
    still reported `Ran 8 tests`, one failing name, baseline 1, inherited, exit
    0. So the COUNT is consulted only once the run is known to have executed its
    tests with its fixtures intact; a broken fixture, a run of zero tests and a
    suite that never finished are all this branch's, whatever the number says.

    Annotates each result in place with `seen`, and with `fixture`, `collapsed`,
    `timedout` or `grew` where they apply, so the caller can say which it is.
    """
    inherited, introduced = [], []
    for result in bad:
        expected = baseline_failures(result["suite"])
        seen = len(result["failing"])
        ran = result.get("ran")
        result["seen"] = seen
        if expected is None:
            introduced.append(result)
        elif result.get("state") == "TIMEOUT":
            result["timedout"] = expected
            introduced.append(result)
        elif result.get("fixtures"):
            result["fixture"] = result["fixtures"]
            introduced.append(result)
        elif ran == 0 or (ran is None and seen == 0):
            result["collapsed"] = expected
            introduced.append(result)
        elif seen > expected:
            result["grew"] = (expected, seen)
            introduced.append(result)
        else:
            inherited.append(result)
    return inherited, introduced


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
    # serverconf reads these at import time. Without them a suite either skips
    # everything -- and a skipped suite reports OK -- or refuses to start, which
    # is what test_module_imports does, and it says so on stderr rather than
    # failing silently. Both are needed; providing only the first made that suite
    # look like a failure this branch had introduced.
    data = os.path.expanduser("~/Desktop/github_dev/paintomics4_data")
    env.setdefault("PAINTOMICS_KEGG_DATA", data)
    env.setdefault("PAINTOMICS_CLIENT_TMP", os.path.join(data, "CLIENT_TMP"))
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
            "ran": tests_run(out),
            "fixtures": BROKEN_FIXTURE.findall(out),
            "failing": FAILING_TEST.findall(out)}


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
        # A filter that matches nothing used to print "0 suites | 0 pass |
        # 0 INTRODUCED" and exit 0 -- a green result that ran no tests, which
        # is the single failure this runner exists to prevent. It reads as
        # success at a glance and as success to a shell. `--only` is a
        # SUBSTRING, so a comma-separated list matches nothing and silently
        # passes.
        if not names:
            print("--only %r matched no suite (it is a substring, not a list)"
                  % args.only, file=sys.stderr)
            return 2

    check_baseline()
    results = [run_one(n, args.timeout) for n in names]
    bad = [r for r in results if r["state"] != "PASS"]
    inherited, introduced = split_by_baseline(bad)
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
            print("   %-46s %2d/%-2d %s"
                  % (r["suite"], r["seen"], baseline_failures(r["suite"]),
                     BASELINE[r["suite"]][:60]))
    if introduced:
        print("\nINTRODUCED BY THIS BRANCH:")
        for r in introduced:
            if "fixture" in r:
                note = ("  [%s failed, so a class never ran: this run did not "
                        "reproduce the baseline]"
                        % ", ".join(sorted(set(r["fixture"]))))
            elif "timedout" in r:
                note = ("  [baselined for %d failing test(s) but did not "
                        "finish: nothing can be credited to master]"
                        % r["timedout"])
            elif "collapsed" in r:
                note = ("  [baselined for %d failing test(s) but this run %s: "
                        "it did not get that far]"
                        % (r["collapsed"], "ran 0 tests" if r.get("ran") == 0
                           else "named no failing test"))
            elif "grew" in r:
                note = "  [was %d on master, now %d]" % r["grew"]
            else:
                note = ""
            print("   %-46s %s%s" % (r["suite"], ", ".join(r["failing"])[:60], note))

    if args.baseline:
        # The count is the point. Printing an empty note used to produce a
        # BASELINE that let every listed suite absorb any number of new
        # failures, and baseline_failures() now refuses to load one.
        print("\nBASELINE = {")
        for r in bad:
            print('    "%s": "%d failures: WHY",' % (r["suite"], len(r["failing"])))
        print("}")

    return 1 if introduced else 0


if __name__ == "__main__":
    sys.exit(main())
