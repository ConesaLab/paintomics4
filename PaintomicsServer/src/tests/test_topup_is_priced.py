#!/usr/bin/env python3
"""The citation top-up is a bet, and only its winnings were being counted.

The top-up hands the synthesiser a finished report plus the papers nothing
cites, and asks it to add [N] markers wherever one of them genuinely supports a
sentence that is already there. Those sentences already stood on their own. So
each added marker is a wager with asymmetric stakes:

  * it verifies   -> the report gains one citation.
  * it fails      -> redact_unverified_v2 deletes THE WHOLE SENTENCE, because
                     redaction removes each claim along with its bad citation.

stats["topup_added"] recorded only the first outcome. Measured on the agent arm
the stage costs ~40 s -- 14% of a 282 s run -- to add two citations, and until
now nothing in the archive could say whether those two survived the gate or
took two paragraphs down with them.

    python -m src.tests.test_topup_is_priced
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS, STAGE_NOTES, _stage_budget  # noqa: E402
from src.classes.AIInterpret.verification import score_topup_survival  # noqa: E402

_PASSED, _FAILED = [], []


def _failed(*indices):
    return {"failed_citations": [{"ref_index": i, "reason": "no support"}
                                 for i in indices]}


def test_a_run_without_a_topup_records_nothing():
    """Absent must stay absent: a zero here would read as 'ran, lost nothing'."""
    stats = {}
    score_topup_survival(stats, _failed(3, 4))
    assert "topup_added_failed" not in stats, (
        "invented a top-up score for a run that never topped up: %r" % stats)


def test_it_counts_only_the_citations_the_topup_added():
    """Citations the agent wrote itself are not the top-up's to answer for."""
    stats = {"topup_added": 2, "topup_added_refs": [7, 9]}
    score_topup_survival(stats, _failed(1, 7, 12))
    assert stats["topup_added_failed"] == 1, (
        "expected only [7] charged to the top-up, got %r" % stats)


def test_a_clean_topup_scores_zero_not_nothing():
    """Zero is a result. It is what a stage worth keeping looks like."""
    stats = {"topup_added": 2, "topup_added_refs": [7, 9]}
    score_topup_survival(stats, _failed(1, 2))
    assert stats["topup_added_failed"] == 0


def test_a_topup_that_lost_every_bet_is_visible():
    """The case the metric exists for: two citations gained, two sentences
    destroyed, and topup_added=2 alone would call that a good round."""
    stats = {"topup_added": 2, "topup_added_refs": [7, 9]}
    score_topup_survival(stats, _failed(7, 9))
    assert stats["topup_added_failed"] == stats["topup_added"], (
        "a wholly negative top-up looked positive: %r" % stats)


def test_a_verification_with_no_failures_is_handled():
    stats = {"topup_added": 1, "topup_added_refs": [4]}
    score_topup_survival(stats, {})
    assert stats["topup_added_failed"] == 0


def test_both_halves_of_the_bet_reach_the_archive():
    """A stage measured on its wins alone can never be retired on evidence."""
    for key in ("topup_added", "topup_added_failed"):
        assert key in STAGE_COUNTS, "%s is not archived by the bench" % key
    row = _stage_budget({"topup_added": 3, "topup_added_failed": 2,
                         "topup_s": 41.27})
    assert row["topup_added"] == 3 and row["topup_added_failed"] == 2
    assert row["topup_s"] == 41.3


def test_a_stage_that_declined_to_run_says_why():
    """topup_skipped and topup_rejected carry sentences, and a stat that is only
    ever a number drops them -- leaving 'skipped' indistinguishable from
    'never happened' in the archive."""
    assert "topup_skipped" in STAGE_NOTES
    row = _stage_budget({"topup_skipped": "38 s left, needs 90",
                         "topup_rejected": True})
    assert row["topup_skipped"].startswith("38 s left"), row
    assert row["topup_rejected"] is True, "a rejected top-up left no trace: %r" % row


def test_both_arms_actually_call_the_scorer():
    """A scorer nobody calls passes every unit test and measures nothing.

    Both arms run the same top-up and the same gate, so both must price it --
    and the two call sites live in different files from the function, which is
    exactly the shape that goes stale (see the reference sorter the SDK rewrite
    orphaned, and the tool the Lead prompt kept instructing after deletion).
    """
    import inspect
    from src.classes.AIInterpret import agent, agent_loop
    for module in (agent, agent_loop):
        src = inspect.getsource(module)
        assert "score_topup_survival(stats, final)" in src, (
            "%s runs the top-up but never prices it" % module.__name__)
        gate = src.index("final = verify_report_v2(")
        call = src.index("score_topup_survival(stats, final)")
        assert call > gate, (
            "%s prices the top-up before the verdict exists" % module.__name__)


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_run_without_a_topup_records_nothing,
              test_it_counts_only_the_citations_the_topup_added,
              test_a_clean_topup_scores_zero_not_nothing,
              test_a_topup_that_lost_every_bet_is_visible,
              test_a_verification_with_no_failures_is_handled,
              test_both_halves_of_the_bet_reach_the_archive,
              test_a_stage_that_declined_to_run_says_why,
              test_both_arms_actually_call_the_scorer):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
