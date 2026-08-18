#!/usr/bin/env python3
"""A silent fallback restores the failure the attribution exists to prevent.

Each delegated sub-agent is meant to see the papers retrieved for ITS OWN
pathways -- the topic_tag on every search is the attribution key. When no tag
matches, `_papers_for` falls back to the most recently retrieved papers, which
belong to whatever the Lead was investigating last. The sub-agent then reasons
over somebody else's literature, which is exactly round 4's failure: 39 k
characters and four citations.

Both paths return papers, so the prompt looks identical from the outside and
nothing recorded which one produced it.

Why it matters now: ~15 themes are searched per run and only ~8 put a paper in
the references, while delegation covers ~15 pathways -- so the loss is not
papers reaching no writer. A chunk handed the wrong literature is the leading
explanation still standing, and it could not be tested without this count.

    python -m src.tests.test_delegate_attribution_is_counted
"""
from __future__ import annotations

import inspect
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS, _stage_budget  # noqa: E402
from src.classes.AIInterpret import agent_loop as L  # noqa: E402

_PASSED, _FAILED = [], []


def _source_of(fn_name):
    """_papers_for is nested well inside delegate_interpretation, so the slice
    runs to the NEXT top-level tool rather than a guessed character count."""
    src = inspect.getsource(L)
    start = src.index("def %s(" % fn_name)
    end = src.index("@function_tool", start)
    return src[start:end]


def test_both_outcomes_are_counted_not_just_the_failure():
    """A fallback count with no matched count cannot be read as a rate."""
    body = _source_of("delegate_interpretation")
    assert 'tally["fallback"]' in body, "the fallback is not counted"
    assert 'tally["matched"]' in body, (
        "only the failure is counted; without the denominator the number "
        "cannot say whether attribution usually works")


def test_the_counter_survives_the_tool_call():
    """It lives on the run context, not a local, or it dies with the tool."""
    from dataclasses import fields
    assert any(f.name == "delegate_attribution" for f in fields(L.LoopContext))


def test_the_tally_accumulates_across_chunks():
    """One run delegates several chunks; the count is per chunk, not per run."""
    import time
    ctx = L.LoopContext(job_instance=None, job_id="T", organism_name="mmu",
                        experiment_design="", started_at=time.time(),
                        hard_deadline=time.time() + 600)
    tally = ctx.delegate_attribution
    for _ in range(3):
        tally["fallback"] = tally.get("fallback", 0) + 1
    tally["matched"] = tally.get("matched", 0) + 1
    assert tally == {"fallback": 3, "matched": 1}


def test_it_reaches_the_archive():
    for key in ("delegate_matched", "delegate_fallback"):
        assert key in STAGE_COUNTS, "%s is not archived" % key
    row = _stage_budget({"delegate_matched": 1, "delegate_fallback": 2})
    assert row["delegate_matched"] == 1 and row["delegate_fallback"] == 2


def test_a_run_that_never_delegated_records_nothing():
    """Absent must stay distinguishable from zero, as everywhere else here."""
    assert "delegate_matched" not in _stage_budget({})


def test_the_fallback_still_returns_papers():
    """Counting it must not turn a soft failure into an empty prompt: a chunk
    with no literature at all is worse than a chunk with the wrong literature."""
    body = _source_of("delegate_interpretation")
    m = re.search(r'tally\["fallback"\].*?\n\s*(hits = papers\[-DELEGATE_PAPERS:\])',
                  body, re.S)
    assert m, "the fallback no longer assigns papers after being counted"


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_both_outcomes_are_counted_not_just_the_failure,
              test_the_counter_survives_the_tool_call,
              test_the_tally_accumulates_across_chunks,
              test_it_reaches_the_archive,
              test_a_run_that_never_delegated_records_nothing,
              test_the_fallback_still_returns_papers):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
