#!/usr/bin/env python3
"""A pre-registration should know what its round is capable of resolving.

Every pre-registration in this project named a predicted effect and none named
the sample needed to detect it. The consequences ran through a whole session:
round 47 predicted converted themes 9.8 -> 13 and checked it at n=4; round 49
predicted coverage +1.5; round 50 predicted +2.5. At the archive's variances a
round of n=4 resolves a citation effect of about 6 and a coverage effect of about
3, so all three were undetectable before they were launched.

The variances are not a mystery -- base alone, which is FIXED code, ranges 10-15
on coverage and 10-26 on citations across the archive.

    python -m src.tests.test_power_says_what_a_round_can_see
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks import ai_arm_bench as B                 # noqa: E402

_PASSED, _FAILED = [], []


def _rounds(tmp, cites):
    d = os.path.join(tmp, "r")
    os.makedirs(d, exist_ok=True)
    for i, c in enumerate(cites):
        json.dump({"arm": "agent", "citations_in_body": c,
                   "prose_pathways_covered": 14, "redacted": 0,
                   "report_chars": 50000, "wall_s": 300},
                  open(os.path.join(d, "agent-r%d.json" % i), "w"))
    return d


def _run(rounds, n):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        B.cmd_power(argparse.Namespace(rounds=rounds, n=n))
    return buf.getvalue()


def test_a_noisy_metric_needs_a_bigger_effect():
    tmp = tempfile.mkdtemp()
    out = _run(_rounds(tmp, [10, 26, 12, 24, 11, 25]), 4)
    line = [l for l in out.splitlines() if "citations_in_body" in l][0]
    detectable = float(line.split()[2])
    assert detectable > 5, "a spread of 10-26 should need a large effect: %s" % line


def test_a_quiet_metric_needs_a_smaller_one():
    tmp = tempfile.mkdtemp()
    out = _run(_rounds(tmp, [18, 18, 19, 18, 19, 18]), 4)
    line = [l for l in out.splitlines() if "citations_in_body" in l][0]
    detectable = float(line.split()[2])
    assert detectable < 2, "a tight spread should resolve small effects: %s" % line


def test_more_replicates_lower_the_bar():
    tmp = tempfile.mkdtemp()
    d = _rounds(tmp, [10, 26, 12, 24, 11, 25])
    small = float([l for l in _run(d, 4).splitlines()
                   if "citations_in_body" in l][0].split()[2])
    large = float([l for l in _run(d, 16).splitlines()
                   if "citations_in_body" in l][0].split()[2])
    assert large < small, "n=16 must detect smaller effects than n=4"
    # Halving the standard error takes four times the replicates.
    assert abs(small / large - 2.0) < 0.01, (small, large)


def test_it_agrees_with_the_judge_s_own_threshold():
    """`judge` calls a margin resolved at 2 standard errors. The power figure
    must be the same rule read backwards, or a round could be told it can see an
    effect the scorer would then call noise."""
    tmp = tempfile.mkdtemp()
    d = _rounds(tmp, [10, 26, 12, 24, 11, 25])
    detectable = float([l for l in _run(d, 4).splitlines()
                        if "citations_in_body" in l][0].split()[2])
    agent = [{"citations_in_body": 20 + detectable, "redacted": 0,
              "prose_pathways_covered": 14, "wall_s": 300,
              "report_chars": 50000, "status": "done"} for _ in range(4)]
    base = [{"citations_in_body": 20, "redacted": 0,
             "prose_pathways_covered": 14, "wall_s": 300,
             "report_chars": 50000, "status": "done"} for _ in range(4)]
    verdict = B.resolvable(agent, base, "citations_in_body", detectable)
    assert verdict and verdict[0] == "resolved", verdict


def test_an_empty_directory_is_reported_not_crashed():
    tmp = tempfile.mkdtemp()
    empty = os.path.join(tmp, "none")
    os.makedirs(empty, exist_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = B.cmd_power(argparse.Namespace(rounds=empty, n=4))
    assert rc == 1 and "no rows" in buf.getvalue()


def test_it_is_reachable_from_the_command_line():
    src = open(B.__file__.replace(".pyc", ".py")).read()
    assert '"power": cmd_power' in src and 'add_parser("power"' in src


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_noisy_metric_needs_a_bigger_effect,
              test_a_quiet_metric_needs_a_smaller_one,
              test_more_replicates_lower_the_bar,
              test_it_agrees_with_the_judge_s_own_threshold,
              test_an_empty_directory_is_reported_not_crashed,
              test_it_is_reachable_from_the_command_line):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
