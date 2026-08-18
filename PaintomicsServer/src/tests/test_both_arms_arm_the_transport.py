#!/usr/bin/env python3
"""The agent arm imported the deadline and never called it.

The retry shim under the Agents SDK backs off on its own schedule -- up to 7
attempts with waits that reached 60 s in round 35. It is stopped from
overrunning the run by one guard:

    left = _run_seconds_left()
    if left is not None and left < delay + RETRY_MIN_ATTEMPT_SECONDS:
        raise

`left` is None unless somebody called set_run_deadline(). The full-agent arm
imported that function and, across every commit checked, never called it -- so
the guard was dead there and the transport could retry past the deadline the
rest of the arm respects. It stayed invisible because every OTHER bound sits
above the transport: the loop's _time_guard, AGENT_RUN_SECONDS, and bounded()
around each call. Runs finished on time, so nothing looked wrong.

This is the same shape as the reference sorter the SDK rewrite orphaned: a
function that is imported, believed to be wired, and is not. An import is not a
call, and only a test that looks for the CALL can tell the difference.

    python -m src.tests.test_both_arms_arm_the_transport
"""
from __future__ import annotations

import inspect
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent, agent_loop  # noqa: E402

_PASSED, _FAILED = [], []


def test_both_arms_actually_call_set_run_deadline():
    for module in (agent, agent_loop):
        src = inspect.getsource(module)
        calls = re.findall(r"(?<!def )set_run_deadline\(", src)
        assert calls, (
            "%s imports set_run_deadline but never calls it; the transport's "
            "deadline guard is dead in that arm" % module.__name__)


def test_both_arms_arm_the_retry_tally():
    """Armed in the same place, or a run reports no gateway weather at all and
    an absent tally reads exactly like a calm gateway."""
    for module in (agent, agent_loop):
        src = inspect.getsource(module)
        assert re.search(r"(?<!def )reset_run_retries\(\)", src), (
            "%s never starts the retry tally" % module.__name__)


def test_the_deadline_is_armed_before_the_loop_runs():
    """Arming it after the work has started leaves the early calls unguarded."""
    src = inspect.getsource(agent_loop)
    armed = src.index("set_run_deadline(ctx.hard_deadline)")
    started = src.index("Runner.run(lead, kickoff")
    assert armed < started, "the deadline is armed after the Lead loop starts"


def test_the_guard_actually_reads_the_deadline():
    """If the transport stopped consulting it, arming it would be theatre."""
    src = inspect.getsource(agent)
    assert "_run_seconds_left()" in src
    assert "RETRY_MIN_ATTEMPT_SECONDS" in src, (
        "the transport no longer reserves time for the attempt it is about to make")


def test_a_run_with_no_tally_reports_nothing_rather_than_zero():
    agent._RUN_RETRIES.set(None)
    assert agent.run_retry_counts() == {}, (
        "an unarmed run reports {} so absent stays distinguishable from calm")


def test_the_tally_separates_rate_limits_from_other_retries():
    """Gateway congestion and a flaky connection are different weather."""
    agent.reset_run_retries()

    class RateLimitError(Exception):
        pass

    agent._count_retry(RateLimitError())
    agent._count_retry(TimeoutError())
    counts = agent.run_retry_counts()
    assert counts["transport"] == 2 and counts["rate_limited"] == 1


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_both_arms_actually_call_set_run_deadline,
              test_both_arms_arm_the_retry_tally,
              test_the_deadline_is_armed_before_the_loop_runs,
              test_the_guard_actually_reads_the_deadline,
              test_a_run_with_no_tally_reports_nothing_rather_than_zero,
              test_the_tally_separates_rate_limits_from_other_retries):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
