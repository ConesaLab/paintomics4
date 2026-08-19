#!/usr/bin/env python3
"""An agent-versus-agent question should not pay for the control twice.

Most remaining questions here compare two AGENT configurations, and the sealed
rubric scores a report absolutely -- it does not need base at all. Meanwhile base
in cluster mode, which is its best measured configuration, costs 486-1014 s a
replicate: two thirds of a round's wall clock re-measuring a control whose numbers
are already in the archive.

`--arms agent` skips it. The danger is reading the wrong thing afterwards: rules
2, 3, 4 and 5 are all relative to base, so a round run without base must be read
on `rubric_coverage` and the agent columns.

    python -m src.tests.test_a_round_can_skip_the_control
"""
from __future__ import annotations

import argparse
import io
import contextlib
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks import ai_arm_bench as B                 # noqa: E402

_PASSED, _FAILED = [], []


def _plan(arms):
    """Run cmd_round with the gateway check and the runner stubbed out."""
    calls = []
    real = (B.cmd_ready, B.cmd_run, B.cmd_score)
    B.cmd_ready = lambda a: 0
    B.cmd_run = lambda a: calls.append((a.arm, a.label))
    B.cmd_score = lambda a: 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            B.cmd_round(argparse.Namespace(jobs="J1,J2", outdir="/tmp/x",
                                           label="agent-vX", design="d", arms=arms))
    finally:
        B.cmd_ready, B.cmd_run, B.cmd_score = real
    return calls


def test_the_default_still_interleaves_both_arms():
    """Interleaving exists because gateway throughput drifts over tens of
    minutes; running one arm back to back puts that weather on one side."""
    plan = _plan("base,agent")
    assert [a for a, _l in plan] == ["base", "agent", "base", "agent"], plan


def test_agent_only_runs_no_control():
    plan = _plan("agent")
    assert [a for a, _l in plan] == ["agent", "agent"], plan


def test_base_only_is_also_possible():
    """Re-measuring the control alone after a config change to base."""
    assert [a for a, _l in _plan("base")] == ["base", "base"]


def test_a_missing_arms_attribute_defaults_to_both():
    """cmd_round is called directly elsewhere with a hand-built Namespace."""
    calls = []
    real = (B.cmd_ready, B.cmd_run, B.cmd_score)
    B.cmd_ready = lambda a: 0
    B.cmd_run = lambda a: calls.append(a.arm)
    B.cmd_score = lambda a: 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            B.cmd_round(argparse.Namespace(jobs="J1", outdir="/tmp/x",
                                           label="agent-vX", design="d"))
    finally:
        B.cmd_ready, B.cmd_run, B.cmd_score = real
    assert calls == ["base", "agent"], calls


def test_one_replicate_per_job_either_way():
    assert len(_plan("agent")) == 2, "two jobs must give two agent replicates"


def test_the_option_is_registered_and_documented():
    src = open(B.__file__.replace(".pyc", ".py")).read()
    assert 'rnd.add_argument("--arms"' in src
    assert "read the rubric, not" in src, (
        "the help text must warn that the five rules are relative to base")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_default_still_interleaves_both_arms,
              test_agent_only_runs_no_control,
              test_base_only_is_also_possible,
              test_a_missing_arms_attribute_defaults_to_both,
              test_one_replicate_per_job_either_way,
              test_the_option_is_registered_and_documented):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
