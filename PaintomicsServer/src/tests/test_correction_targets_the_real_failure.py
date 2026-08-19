#!/usr/bin/env python3
"""The correction loop must ask for the repair the failure actually needs.

Measured over 1006 checked citations, the two verification failures are wildly
unequal: 0.4% are quotes that are not in the paper, 20.1% are real quotes
carrying a sentence that claims more than they support. The prompts addressed
only the rare one -- suggested_fix was requested "if text_match is false", and
the correction instruction said to "correct the Cited Text to match the actual
paper". For a drifted claim the cited text ALREADY matches, so the model was
asked to fix something that was not broken.

That is the mechanism behind the loop's "verification made no progress
(10 -> 10 failures)" exit, which costs a full report rewrite per round inside
the largest wall-clock stage in the pipeline.

    python -m src.tests.test_correction_targets_the_real_failure
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.prompts import (      # noqa: E402
    build_correction_prompt, build_verification_prompt)

_PASSED, _FAILED = [], []

DRIFT = {"ref_index": 4, "reason": "The paper measures mRNA, not protein",
         "cited_text": "IKZF1 transcript levels fell 3-fold",
         "claim_sentence": "IKZF1 protein is depleted after induction [4].",
         "actual_text": "IKZF1 transcript levels fell 3-fold",
         "suggested_fix": "IKZF1 transcript levels fall after induction [4].",
         "mode": "claim"}
MISSING = {"ref_index": 9, "reason": "No such passage",
           "cited_text": "glycolytic flux doubled",
           "claim_sentence": "Glycolytic flux doubled [9].",
           "actual_text": "", "suggested_fix": "", "mode": "text"}


def test_the_verifier_is_asked_for_a_claim_rewrite_not_only_a_quote():
    prompt = build_verification_prompt("A claim.", "A quote.", 3)
    assert "supports_claim** is false" in prompt or \
           "supports_claim" in prompt.split("What suggested_fix must contain")[1], (
        "suggested_fix is still only defined for the text_match failure, which "
        "is 0.4% of cases")
    guidance = prompt.split("What suggested_fix must contain")[1]
    assert "Claim" in guidance and "Narrow" in guidance, (
        "the verifier is not told to narrow the sentence: %s" % guidance[:300])
    assert "do not add facts" in guidance, (
        "nothing stops the rewrite importing facts from elsewhere")


def test_a_drifted_citation_is_told_to_change_the_sentence():
    text = build_correction_prompt("REPORT", [DRIFT])
    assert "Change the SENTENCE, not the quote" in text, (
        "the drift case still reads as a quote problem")
    assert "Your sentence:" in text and "IKZF1 protein is depleted" in text, (
        "the sentence being corrected is not even shown to the model")
    assert "Suggested sentence:" in text, "the fix is mislabelled as cited text"


def test_a_missing_quote_is_still_told_to_fix_the_quote():
    text = build_correction_prompt("REPORT", [MISSING])
    assert "the quoted text is not in the paper" in text
    assert "Change the SENTENCE, not the quote" not in text, (
        "the rare failure now gets the common failure's instruction")


def test_the_two_modes_do_not_contaminate_each_other():
    text = build_correction_prompt("REPORT", [DRIFT, MISSING])
    assert "1 of the 2 issues below are this kind." in text, (
        "the drift count is wrong or missing: the model cannot tell which "
        "instruction dominates")
    assert text.index("[4] Issue") < text.index("[9] Issue")


def test_narrowing_is_named_as_a_correct_outcome():
    """Without this the model restates the same claim in new words, the next
    iteration fails it again, and the loop exits for lack of progress."""
    text = build_correction_prompt("REPORT", [DRIFT])
    assert "Narrowing a claim is the correct outcome" in text
    assert "do not restate the same claim in new words" in text


def test_unflagged_citations_are_still_protected():
    text = build_correction_prompt("REPORT", [DRIFT])
    assert "Do NOT change citations that were not flagged." in text
    assert "Preserve all [N] reference indices." in text
    assert "Output the COMPLETE corrected report." in text


def test_a_missing_mode_is_treated_as_drift():
    """Older records and the legacy verification path carry no mode. Drift is
    50x more likely, so it is the safe default."""
    legacy = dict(DRIFT)
    legacy.pop("mode")
    text = build_correction_prompt("REPORT", [legacy])
    assert "Change the SENTENCE, not the quote" in text


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_verifier_is_asked_for_a_claim_rewrite_not_only_a_quote,
              test_a_drifted_citation_is_told_to_change_the_sentence,
              test_a_missing_quote_is_still_told_to_fix_the_quote,
              test_the_two_modes_do_not_contaminate_each_other,
              test_narrowing_is_named_as_a_correct_outcome,
              test_unflagged_citations_are_still_protected,
              test_a_missing_mode_is_treated_as_drift):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
