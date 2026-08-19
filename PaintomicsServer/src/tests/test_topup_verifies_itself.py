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


def test_the_checker_asks_only_about_the_topups_own_refs():
    """Re-quoting the whole report here would duplicate the collection that runs
    later anyway; the index is restricted to what the top-up just added."""
    from src.classes.AIInterpret import agent_loop as loop
    src = inspect.getsource(loop._verify_topup_additions)
    assert "subset = {r: ctx.paper_index[r] for r in refs}" in src


def test_an_unquotable_ref_is_stripped_not_redacted():
    from src.classes.AIInterpret import agent_loop as loop
    src = inspect.getsource(loop._verify_topup_additions)
    assert "strip_markers(report, unquotable)" in src
    assert "redact_unverified_v2" not in src, (
        "redaction would delete the sentence the top-up merely decorated")


def test_a_failed_check_keeps_every_citation():
    """A dead gateway must not strip the report's citations: the gate still
    verifies everything afterwards."""
    from src.classes.AIInterpret import agent_loop as loop
    src = inspect.getsource(loop._verify_topup_additions)
    i = src.index("except Exception")
    assert "return report, 0" in src[i:i + 200]


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
              test_the_checker_asks_only_about_the_topups_own_refs,
              test_an_unquotable_ref_is_stripped_not_redacted,
              test_a_failed_check_keeps_every_citation,
              test_it_is_off_by_default_and_stamped):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
