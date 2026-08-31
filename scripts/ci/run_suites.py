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

Exit status 1 when a suite fails that run_all's BASELINE does not already
account for -- exactly run_all's rule, and literally its code: the comparison
lives in run_all.split_by_baseline so the two runners cannot disagree.
A suite is answerable to this branch when it is not baselined at all, when it
names MORE failing tests than BASELINE records, or when it is baselined but did
not reproduce that baseline intact -- a class fixture died, no test ran, or it
timed out. Suites that skipped every
test are listed (a skip is not a pass) but, as in run_all, do not fail the run.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.abspath(os.path.join(HERE, "..", "..", "PaintomicsServer"))
sys.path.insert(0, SERVER)

from src.tests import run_all  # noqa: E402

TAIL_LINES = 25


def run_suite(name, timeout):
    """run_all.run_one, keeping the suite's output so a failure in CI can be
    read without re-running it by hand."""
    env = dict(os.environ)
    started = time.time()
    try:
        proc = subprocess.run([sys.executable, "-m", "src.tests." + name],
                              capture_output=True, text=True, timeout=timeout,
                              cwd=SERVER, env=env)
        out = proc.stdout + proc.stderr
        state = run_all.classify(proc.returncode, out)
        skipped = bool(re.search(r"Ran 0 tests|OK \(skipped", out))
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")) \
            + ((exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
        state, skipped = "TIMEOUT", False
    return {"suite": name, "state": state, "skipped": skipped,
            "secs": round(time.time() - started, 1),
            "ran": run_all.tests_run(out),
            "fixtures": run_all.BROKEN_FIXTURE.findall(out),
            "failing": run_all.FAILING_TEST.findall(out),
            "tail": "\n".join(out.strip().splitlines()[-TAIL_LINES:])}


SUITE_TIMES = os.path.join(HERE, "suite_times.txt")


def recorded_times():
    """What each suite cost last time anybody measured, or {} if unknown."""
    times = {}
    try:
        with open(SUITE_TIMES) as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name, _, secs = line.partition("\t")
                try:
                    times[name] = float(secs)
                except ValueError:
                    continue
    except OSError:
        return {}
    return times


def split(names, index, count):
    """The `index`-th of `count` shards, balanced by what the suites cost.

    This used to be `position % count` over the alphabetical list, which is
    arbitrary with respect to cost. The top six suites are 52% of the budget,
    so which shard carries them was decided by how the files are spelled --
    and adding or renaming ONE file re-deals every suite in the repository.
    Measured: parity gives 264 s / 198 s where this gives 231 s / 231 s, and in
    CI the same lottery has produced 395 s against 81 s (run 32859901451) and a
    601 s shard against a 600 s cap (run 33010348812).

    Longest-processing-time first: hand each suite, costliest first, to
    whichever shard is currently lightest. Deterministic -- ties break on the
    name -- so every runner in the matrix computes the same partition without
    talking to the others. A suite with no recorded time is charged the median,
    so a new one is never assumed free, and with no times file at all this
    falls back to the old parity split rather than failing.
    """
    times = recorded_times()
    if not times:
        return [name for position, name in enumerate(names)
                if position % count == index - 1]

    known = sorted(times.values())
    median = known[len(known) // 2]
    cost = lambda name: times.get(name, median)  # noqa: E731

    load = [0.0] * count
    shards = [[] for _ in range(count)]
    for name in sorted(names, key=lambda n: (-cost(n), n)):
        lightest = load.index(min(load))
        shards[lightest].append(name)
        load[lightest] += cost(name)

    print("shard %d/%d: %d suites, ~%.0f s of %.0f s (worst shard ~%.0f s)"
          % (index, count, len(shards[index - 1]), load[index - 1],
             sum(load), max(load)))
    # The median is 1.3 s; a new Mongo-backed suite at 100 s is mis-costed by
    # two orders of magnitude until the times file is refreshed. Say which.
    unrecorded = sorted(name for name in names if name not in times)
    if unrecorded:
        print("   %d suite(s) with no recorded time, charged the median %.1f s: %s"
              % (len(unrecorded), median, ", ".join(unrecorded)))
    return sorted(shards[index - 1])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--only", default="")
    parser.add_argument("--slowest", type=int, default=15,
                        help="how many of the slowest suites to list")
    parser.add_argument("--shard", default="",
                        help="I/N: run the I-th of N shards (1-based), balanced by "
                             "the costs in suite_times.txt, so the sweep can be "
                             "spread over N runners without one carrying the "
                             "slow suites by accident")
    args = parser.parse_args(argv)

    run_all.check_baseline()

    names = sorted(os.path.basename(path)[:-3]
                   for path in glob.glob(os.path.join(SERVER, "src/tests/test_*.py")))
    if args.only:
        names = [name for name in names if args.only in name]
    if args.shard:
        index, count = (int(part) for part in args.shard.split("/"))
        names = split(names, index, count)
    if not names:
        print("no suite matched", file=sys.stderr)
        return 2

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda name: run_suite(name, args.timeout), names))

    bad = [r for r in results if r["state"] != "PASS"]
    # One rule, defined next to BASELINE itself, so this wrapper and the runner
    # CONTRIBUTING points contributors at cannot drift apart -- they did, and
    # the documented one was the weaker of the two.
    inherited, introduced = run_all.split_by_baseline(bad)
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
            print("   %-50s %2d/%-2d  %s"
                  % (r["suite"], r["seen"], run_all.baseline_failures(r["suite"]),
                     run_all.BASELINE[r["suite"]][:60]))
    if skipped:
        print("\nskipped everything -- a skip is not a pass:")
        for r in skipped:
            print("   %s" % r["suite"])
    if introduced:
        print("\nFAILED (new, or worse than BASELINE records):")
        for r in introduced:
            if "fixture" in r:
                note = ("  [%s failed, so a class never ran: this run did not "
                        "reproduce the baseline]"
                        % ", ".join(sorted(set(r["fixture"]))))
            elif "timedout" in r:
                note = ("  [baselined for %d failing test(s) but did not finish: "
                        "nothing can be credited to master]" % r["timedout"])
            elif "collapsed" in r:
                note = ("  [baselined for %d failing test(s) but this run %s: it "
                        "did not get that far]"
                        % (r["collapsed"], "ran 0 tests" if r.get("ran") == 0
                           else "named no failing test"))
            elif "grew" in r:
                note = "  [was %d failing test(s) on master, now %d]" % r["grew"]
            else:
                note = ""
            print("   %-50s %s %s%s"
                  % (r["suite"], r["state"], ", ".join(r["failing"])[:80], note))
        for r in introduced:
            print("\n----- %s (%s): last %d lines -----" % (r["suite"], r["state"], TAIL_LINES))
            print(r["tail"])
    for r in skipped:
        if r not in introduced:
            print("\n----- %s (skipped everything): last %d lines -----" % (r["suite"], TAIL_LINES))
            print(r["tail"])
    return 1 if introduced else 0


if __name__ == "__main__":
    sys.exit(main())
