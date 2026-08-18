#!/usr/bin/env python3
"""The verify loop must not start work the deadline will kill.

The 10-minute cap is one asyncio.wait_for around the whole pipeline, so no
phase could see it coming. Measured across live runs, the verify loop is the
largest consumer in the shipped arm -- 165-486 s, 23% of all wall-clock, four
times what retrieval costs -- and it would happily start a 200 s iteration with
60 s left. Round 33's base-r2 died exactly there, at "references rendered",
and shipped a partial report carrying 30 citations that were never verified.

Stopping early is strictly better than being killed: the programmatic net
redacts the unverified citations in ~0.1 s and the report is complete.

    python -m src.tests.test_verify_loop_deadline
"""
from __future__ import annotations

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.agent import (          # noqa: E402
    VERIFY_ITER_RESERVE, VERIFY_REWRITE_RESERVE, VERIFY_TAIL_RESERVE,
    _budget_allows, _seconds_left)

_PASSED, _FAILED = [], []


def test_a_fresh_run_may_verify():
    allowed, _ = _budget_allows(600.0, None, VERIFY_ITER_RESERVE)
    assert allowed, "a run with the whole budget left refused to verify"


def test_the_last_minute_does_not_start_an_iteration():
    allowed, needed = _budget_allows(100.0, None, VERIFY_ITER_RESERVE)
    assert not allowed, "started an iteration with 100 s left"
    assert needed == VERIFY_ITER_RESERVE + VERIFY_TAIL_RESERVE


def test_the_estimate_is_this_run_s_own_iteration():
    """A 200 s iteration in THIS run predicts the next one; the default does
    not. Runs measured between 165 s and 486 s for the same phase."""
    allowed, needed = _budget_allows(300.0, 200.0, VERIFY_ITER_RESERVE)
    assert needed == 200.0 * 1.2 + VERIFY_TAIL_RESERVE == 300.0
    assert allowed, "refused with exactly enough time"
    assert not _budget_allows(299.0, 200.0, VERIFY_ITER_RESERVE)[0]
    # the same 299 s would have looked fine on the default estimate
    assert _budget_allows(299.0, None, VERIFY_ITER_RESERVE)[0], (
        "the default happens to agree here; the test proves nothing")


def test_a_faster_iteration_earns_another_round():
    """A 40 s iteration should not be blocked by a 90 s default."""
    assert _budget_allows(120.0, 40.0, VERIFY_ITER_RESERVE)[0]
    assert not _budget_allows(120.0, None, VERIFY_ITER_RESERVE)[0]


def test_the_tail_is_always_reserved():
    """Quote collection alone is capped at 45 s and runs AFTER the loop."""
    allowed, needed = _budget_allows(VERIFY_ITER_RESERVE + 1.0, None,
                                     VERIFY_ITER_RESERVE)
    assert not allowed, "spent the tail reserve on an iteration"
    assert needed - VERIFY_ITER_RESERVE == VERIFY_TAIL_RESERVE


def test_the_rewrite_is_guarded_too():
    """A correction rewrite is a full synthesis echo (~70 s of a 347 s run)."""
    assert not _budget_allows(100.0, None, VERIFY_REWRITE_RESERVE)[0]
    assert _budget_allows(400.0, None, VERIFY_REWRITE_RESERVE)[0]


def test_seconds_left_counts_down_from_the_cap():
    from src.classes.AIInterpret import agent as A
    original = A.AI_MAX_RUN_SECONDS
    A.AI_MAX_RUN_SECONDS = 600.0
    try:
        start = time.time()
        assert 599.0 < _seconds_left(start) <= 600.0
        assert _seconds_left(start - 550.0) < 51.0, "the clock is not counting"
        assert _seconds_left(start - 700.0) < 0, "an overrun must go negative"
    finally:
        A.AI_MAX_RUN_SECONDS = original


def test_the_reserves_fit_inside_a_ten_minute_run():
    """Reserves large enough to block the FIRST iteration would silently turn
    verification off for every run."""
    first = VERIFY_ITER_RESERVE + VERIFY_TAIL_RESERVE
    assert first < 300.0, (
        "the reserves (%.0f s) eat half a 600 s budget; verification would "
        "rarely start" % first)


def test_the_fanout_itself_is_bounded_not_just_its_start():
    """The guard above estimates from this run's PREVIOUS iteration, and the
    first iteration has none. A 486 s round (measured) would sail past the 90 s
    default, so the fan-out carries its own deadline and cancels the stragglers.
    The agent arm hit this first: 19 citations, each hedged 45 s x2 over 8
    workers, ran to 602 s holding a finished report it never shipped."""
    import inspect
    from src.classes.AIInterpret import agent as A
    body = inspect.getsource(A._run_async)
    assert "asyncio.gather(*[_verify_one" not in body, (
        "the verification fan-out is unbounded again; a single round can "
        "outlive the whole run")
    assert "asyncio.wait(tasks, timeout=budget)" in body
    assert "verify_unchecked" in body, (
        "citations dropped for time are invisible; the count must be recorded")
    assert "task.cancel()" in body, "stragglers are left running"


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_fresh_run_may_verify,
              test_the_last_minute_does_not_start_an_iteration,
              test_the_estimate_is_this_run_s_own_iteration,
              test_a_faster_iteration_earns_another_round,
              test_the_tail_is_always_reserved,
              test_the_rewrite_is_guarded_too,
              test_seconds_left_counts_down_from_the_cap,
              test_the_reserves_fit_inside_a_ten_minute_run,
              test_the_fanout_itself_is_bounded_not_just_its_start):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
