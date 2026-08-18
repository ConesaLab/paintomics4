#!/usr/bin/env python3
"""The verify loop re-asks a question whose answer cannot have changed.

Round 36 corrected the model of where this loop spends its time. The
full-report correction rewrite was replaced with parallel per-sentence repairs,
and verify_loop_s did not move -- 230 s against 250 s -- on a replicate that
repaired ONE sentence. So the rewrite was never the cost.

What is left is the fan-out. Each citation is checked by a SIX-TURN verifier
agent, a base run carries ~25 citations, and the loop runs three iterations over
all of them. A repair round that fixes one sentence leaves 24 citations
byte-identical -- and asks all 24 again.

A verdict answers exactly one question: does THIS quote support THIS sentence.
If neither string changed, the answer cannot have changed. Skipping it is
redundancy elimination by construction, not a bet on model determinism.

    python -m src.tests.test_verification_memo
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS, STAGE_TIMES  # noqa: E402
from src.classes.AIInterpret import agent as A  # noqa: E402

_PASSED, _FAILED = [], []


def _cit(ref=3, claim="X drives Y [3].", quote="X is associated with Y."):
    return {"ref_index": ref, "claim_sentence": claim, "cited_text": quote}


def test_the_same_pair_is_the_same_question():
    assert A._verdict_key(_cit()) == A._verdict_key(_cit())


def test_surrounding_whitespace_is_not_a_different_question():
    """The report is re-parsed each iteration and spacing shifts; treating that
    as a change would defeat the memo silently."""
    assert A._verdict_key(_cit(claim="  X drives Y [3].  ")) == \
           A._verdict_key(_cit(claim="X drives Y [3]."))


def test_a_repaired_sentence_is_a_new_question():
    """The whole point: once the sentence changes, the old verdict is void."""
    assert A._verdict_key(_cit(claim="X is associated with Y [3].")) != \
           A._verdict_key(_cit())


def test_a_changed_quote_is_a_new_question():
    assert A._verdict_key(_cit(quote="Something else entirely.")) != \
           A._verdict_key(_cit())


def test_the_same_sentence_citing_a_different_paper_is_a_new_question():
    """Two papers can be cited for one claim; each needs its own verdict."""
    assert A._verdict_key(_cit(ref=9)) != A._verdict_key(_cit(ref=3))


def test_a_missing_field_does_not_collapse_two_citations_together():
    """A citation with no claim_sentence must not become interchangeable with
    every other one that also lacks it -- ref_index keeps them apart."""
    a = A._verdict_key({"ref_index": 3})
    b = A._verdict_key({"ref_index": 4})
    assert a != b


def test_the_flag_is_off_by_default():
    """It changes the shipped arm's verification, so it ships dark."""
    assert A.VERIFY_MEMO is False


def test_the_split_and_the_skip_count_are_archived():
    """Round 36 was launched unable to measure its own change; not twice."""
    for key in ("verify_fanout_s", "verify_repair_s"):
        assert key in STAGE_TIMES, "%s is not archived" % key
    for key in ("verify_memo_skipped", "verify_citations_checked"):
        assert key in STAGE_COUNTS, "%s is not archived" % key


def test_the_memo_only_skips_what_passed():
    """Failures must be re-asked -- they are what the repair is trying to fix.
    The set is populated only in the supported branch."""
    import inspect
    src = inspect.getsource(A)
    i = src.index("verified_before.add(_verdict_key(cit))")
    window = src[max(0, i - 260):i]
    assert 'v.get("text_match") and v.get("supports_claim")' in window, (
        "the memo records a key outside the supported branch; a failed citation "
        "could be skipped and ship unchecked")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_same_pair_is_the_same_question,
              test_surrounding_whitespace_is_not_a_different_question,
              test_a_repaired_sentence_is_a_new_question,
              test_a_changed_quote_is_a_new_question,
              test_the_same_sentence_citing_a_different_paper_is_a_new_question,
              test_a_missing_field_does_not_collapse_two_citations_together,
              test_the_flag_is_off_by_default,
              test_the_split_and_the_skip_count_are_archived,
              test_the_memo_only_skips_what_passed):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
