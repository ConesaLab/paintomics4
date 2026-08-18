#!/usr/bin/env python3
"""Which references failed, not just how many.

Round 40 raised a question the archive could not answer. The agent arm's keep
rate rose (24% -> 28-32%) while failures rose 0.50 -> 2.50 and redactions
1.2 -> 5.5, so the obvious suspect is the screen's new permissive stance
admitting weaker papers while the pool is small.

That is testable, because a paper's ref_index IS its admission order: if the
failures cluster at low indices, they are the papers admitted under the
permissive branch. But `stats["verification"]` is a dict, the bench keeps only
scalars, and every archived round therefore retained the COUNT and discarded the
indices.

    python -m src.tests.test_failed_refs_are_archived
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_NOTES, _stage_budget  # noqa: E402

_PASSED, _FAILED = [], []


def test_the_indices_reach_the_archive():
    assert "failed_refs" in STAGE_NOTES
    row = _stage_budget({"failed_refs": "3,17,29"})
    assert row["failed_refs"] == "3,17,29"


def test_a_clean_run_writes_nothing():
    """Absent must stay distinguishable from 'ran and found none', the rule this
    archive follows everywhere else."""
    assert "failed_refs" not in _stage_budget({})
    assert "failed_refs" not in _stage_budget({"failed_refs": ""})


def test_both_arms_record_it():
    from src.classes.AIInterpret import agent, agent_loop
    for module in (agent, agent_loop):
        assert 'stats["failed_refs"]' in inspect.getsource(module), module.__name__


def test_it_is_captured_before_renumbering():
    """renumber_citations rewrites every ref_index a few lines later. Recording
    afterwards would give indices that no longer mean admission order -- the one
    property this is for."""
    from src.classes.AIInterpret import agent, agent_loop
    for module in (agent, agent_loop):
        src = inspect.getsource(module)
        recorded = src.index('stats["failed_refs"]')
        renumbered = src.index("renumber_citations(report)")
        assert recorded < renumbered, module.__name__


def test_non_integer_indices_are_dropped_not_crashed():
    """A malformed verdict must not take the whole record down with it."""
    from src.classes.AIInterpret import agent
    src = inspect.getsource(agent)
    i = src.index('stats["failed_refs"]')
    assert "isinstance(c.get(\"ref_index\"), int)" in src[i:i + 320]


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_indices_reach_the_archive,
              test_a_clean_run_writes_nothing,
              test_both_arms_record_it,
              test_it_is_captured_before_renumbering,
              test_non_integer_indices_are_dropped_not_crashed):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
