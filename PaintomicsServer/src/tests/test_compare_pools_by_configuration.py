#!/usr/bin/env python3
"""Pooling rounds by configuration must be a command, not a heredoc.

I hand-rolled this analysis six times in one session and every error entered
there rather than in the pipeline: a join on file mtime that matched a run 28
hours old, a `sorted(keys)[:40]` slice that hid the stat being looked for, and
twice a mean taken across configurations that no longer applied.

It also has to report resolvability, because single rounds do not settle these
metrics. Two claims made this session from n=4 and n=8 -- "citations +4.6,
resolved" and "DELEGATE_CHUNK=3 cost 3.4 pathways, resolved" -- both shrank and
lost resolution once more replicates arrived.

    python -m src.tests.test_compare_pools_by_configuration
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks import ai_arm_bench as B                 # noqa: E402

_PASSED, _FAILED = [], []


def _round(tmp, name, agent_cov, base_cov):
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    for i, c in enumerate(agent_cov):
        json.dump({"arm": "agent", "prose_pathways_covered": c,
                   "citations_in_body": 20, "redacted": 0, "report_chars": 50000,
                   "wall_s": 300, "status": "done"},
                  open(os.path.join(d, "agent-v1-r%d.json" % i), "w"))
    for i, c in enumerate(base_cov):
        json.dump({"arm": "base", "prose_pathways_covered": c,
                   "citations_in_body": 18, "redacted": 4, "report_chars": 33000,
                   "wall_s": 300, "status": "done"},
                  open(os.path.join(d, "base-r%d.json" % i), "w"))
    return d


def _run(a, b):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        B.cmd_compare(argparse.Namespace(a=a, b=b))
    return buf.getvalue()


def test_several_round_dirs_pool_into_one_configuration():
    tmp = tempfile.mkdtemp()
    r1 = _round(tmp, "r1", [16, 17], [12, 13])
    r2 = _round(tmp, "r2", [15, 16], [13, 13])
    r3 = _round(tmp, "r3", [13, 13], [13, 14])
    out = _run("%s,%s" % (r1, r2), r3)
    assert "agent n=4" in out, out
    assert "agent n=2" in out, out


def test_a_difference_inside_the_noise_says_so():
    tmp = tempfile.mkdtemp()
    # Means must differ, or the margin is exactly 0 and "needs n~" is
    # correctly suppressed as infinite -- the first fixture here scored 14.0 on
    # both sides by accident and looked like a missing feature.
    a = _round(tmp, "a", [16, 12, 17, 13], [13, 13, 13, 13])
    b = _round(tmp, "b", [13, 15, 12, 11], [13, 13, 13, 13])
    out = _run(a, b)
    line = [l for l in out.splitlines() if "prose_pathways_covered" in l][0]
    assert "NOISE" in line, line
    assert "n~" in line, "it does not say how many replicates would settle it"


def test_the_margin_over_each_sets_own_base_is_reported():
    """Base drifts between rounds -- 10 to 15 on coverage with fixed code -- so
    comparing raw agent values across configurations compares two different
    yardsticks. The rules compare a margin, and so must this."""
    tmp = tempfile.mkdtemp()
    a = _round(tmp, "a", [16, 16], [12, 12])       # margin +4
    b = _round(tmp, "b", [16, 16], [15, 15])       # margin +1, same agent value
    out = _run(a, b)
    assert "margin over each set's own base" in out
    tail = out.split("margin over each set's own base")[1]
    assert "+4.00" in tail and "+1.00" in tail, tail


def test_an_empty_set_is_reported_not_crashed():
    tmp = tempfile.mkdtemp()
    a = _round(tmp, "a", [15], [13])
    empty = os.path.join(tmp, "nothing")
    os.makedirs(empty, exist_ok=True)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = B.cmd_compare(argparse.Namespace(a=a, b=empty))
    assert rc == 1 and "no agent rows" in buf.getvalue()


def test_it_is_reachable_from_the_command_line():
    src = open(B.__file__.replace(".pyc", ".py")).read()
    assert '"compare": cmd_compare' in src, "the subcommand is not dispatched"
    assert 'add_parser("compare"' in src, "the subcommand is not registered"


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_several_round_dirs_pool_into_one_configuration,
              test_a_difference_inside_the_noise_says_so,
              test_the_margin_over_each_sets_own_base_is_reported,
              test_an_empty_set_is_reported_not_crashed,
              test_it_is_reachable_from_the_command_line):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
