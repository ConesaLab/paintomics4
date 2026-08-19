#!/usr/bin/env python3
"""Pulling a top-up marker back costs nothing; letting it through costs a sentence.

Rounds 39-43: `topup_added_failed` equalled `failed_citations` in every
replicate, base's equalled zero, and the top-up failed 40-50% of what it added
regardless of volume. Round 44 removed the stage: rule 3 went perfect (0
redactions across replicates) and rule 2 broke (16.0 citations against base's
22.3). Capping was refuted separately -- the failure RATE is flat in volume.

The asymmetry that makes a third option work: the top-up attaches [N] to
sentences that already stood on their own. Taking the marker back restores the
sentence exactly; leaving a bad one costs the sentence at the gate. So the stage
can keep the citations that hold and give back the ones that do not.

    python -m src.tests.test_topup_verifies_itself
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.verification import strip_markers  # noqa: E402

_PASSED, _FAILED = [], []

REPORT = "Alpha stands alone [7]. Beta cites two [3][7]. Gamma has none."


def test_a_stripped_marker_leaves_its_sentence_intact():
    """The whole basis of the design. redact_unverified_v2 would delete the
    first sentence, because its last citation went."""
    out, removed = strip_markers(REPORT, [7])
    assert "Alpha stands alone." in out, out
    assert out.count(".") == REPORT.count("."), "a sentence was lost"
    assert removed == 2


def test_other_citations_survive_in_the_same_sentence():
    out, _ = strip_markers(REPORT, [7])
    assert "Beta cites two [3]." in out, out


def test_nothing_to_strip_changes_nothing():
    out, removed = strip_markers(REPORT, [99])
    assert out == REPORT and removed == 0


def test_no_refs_is_a_no_op():
    assert strip_markers(REPORT, []) == (REPORT, 0)
    assert strip_markers(REPORT, None) == (REPORT, 0)


def test_punctuation_is_closed_up_after_removal():
    """A marker removed mid-sentence must not leave ' .' or a dangling '()'."""
    out, _ = strip_markers("Claim here [7] .", [7])
    assert " ." not in out, out


def test_a_failed_TOPUP_citation_loses_its_marker_not_its_sentence():
    """The design, stated as behaviour.

    A failed citation the top-up added is a marker bolted onto prose that stood
    on its own; pulling it back restores the sentence. A failed citation the
    writer put there is a claim with no support left, and redaction is right.
    """
    from src.classes.AIInterpret import agent_loop as loop
    src = inspect.getsource(loop)
    i = src.index('bolted = [c for c in final["failed_citations"]')
    block = src[i:i + 700]
    assert "strip_markers(report," in block
    assert 'final["failed_citations"] = [c for c in final["failed_citations"]' in block, (
        "the pulled citations are still handed to redaction")


def test_writer_citations_are_still_redacted():
    """Only the top-up's own additions get the free pass."""
    from src.classes.AIInterpret import agent_loop as loop
    src = inspect.getsource(loop)
    i = src.index('bolted = [c for c in final["failed_citations"]')
    assert "redact_unverified_v2(report, final[" in src[i:i + 1200], (
        "redaction no longer runs for the citations the writer added"
    )


def test_it_reuses_the_gates_verdict_rather_than_asking_again():
    """An earlier version ran its own quote check BEFORE the gate and was wrong
    twice: it tested whether a quote EXISTS while the gate tests whether the
    quote SUPPORTS the claim, and it read _collect_cited_quotes' `known`
    argument backwards -- that argument EXCLUDES already-quoted refs from the
    result, so every ref with a quote looked unquotable and had its marker
    stripped. The smoke run showed 6 pulled and 6 still failing."""
    from src.classes.AIInterpret import agent_loop as loop
    src = inspect.getsource(loop)
    assert "_verify_topup_additions" not in src, "the pre-gate check is back"
    i = src.index('bolted = [c for c in final["failed_citations"]')
    assert src.index("verify_report_v2(report,") < i, (
        "the pull-back runs before the gate has produced a verdict")


def test_it_is_off_by_default_and_stamped():
    from src.classes.AIInterpret import agent_loop as loop
    assert loop.VERIFY_TOPUP is False
    src = inspect.getsource(loop)
    stamp = src[src.index('_trace_gate(ctx, "__config__"'):][:2200]
    assert '"verify_topup"' in stamp


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_stripped_marker_leaves_its_sentence_intact,
              test_other_citations_survive_in_the_same_sentence,
              test_nothing_to_strip_changes_nothing,
              test_no_refs_is_a_no_op,
              test_punctuation_is_closed_up_after_removal,
              test_a_failed_TOPUP_citation_loses_its_marker_not_its_sentence,
              test_writer_citations_are_still_redacted,
              test_it_reuses_the_gates_verdict_rather_than_asking_again,
              test_it_is_off_by_default_and_stamped):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
