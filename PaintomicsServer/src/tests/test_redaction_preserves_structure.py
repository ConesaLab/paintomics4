#!/usr/bin/env python3
"""redact_unverified_v2 must remove citations, not the document around them.

The redactor used to split the body on sentence boundaries and rejoin with a
single space. The split pattern `(?<=[.!?])\\s+` consumes the whitespace after a
full stop, and in a markdown report that whitespace is usually the newline
before a heading or a bullet. So one failed citation was enough to:

  * delete any heading glued to a removed sentence,
  * inline every other heading into the middle of a paragraph,
  * collapse bullet lists into a run-on line,
  * flatten every paragraph break that followed a sentence.

Measured on a five-section sample, redacting one index took the body from 13
newlines to 5 and destroyed two headings. Both arms call this function, so it
damaged shipped interpretations, and the frontend carries a newline-recovery
hack that exists to make the wreckage readable.

These tests pin the contract: a redaction removes whole sentences that cite a
failed index, and nothing else in the document moves.

    python -m src.tests.test_redaction_preserves_structure
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.verification import redact_unverified_v2  # noqa: E402
from src.classes.AIInterpret.agent import (_note_if_ungrounded,  # noqa: E402
                                           _keep_partial, _partial_result)

_PASSED, _FAILED = [], []

REPORT = """## Summary

Glycolysis is strongly repressed in the treated condition [1]. This is
consistent with the measured lactate drop [2].

## Central carbon metabolism

The TCA cycle shows coordinated induction [3]. Succinate dehydrogenase
rises with it [1].

- PDH flux falls sharply [2].
- Citrate synthase is unchanged [3].

### References

[1] Smith et al. Nature 2020.
[2] Jones et al. Cell 2021.
[3] Lee et al. Science 2022.
"""


def _body(text):
    return text.split("### References")[0]


def test_headings_survive_a_redaction():
    """`## Summary` was deleted outright: it was glued to the sentence that
    cited [1], so removing the sentence removed the section title."""
    out, _ = redact_unverified_v2(REPORT, [{"ref_index": 1}])
    body = _body(out)
    assert "## Summary" in body, "the heading was deleted with the sentence"
    assert "## Central carbon metabolism" in body


def test_headings_stay_on_their_own_line():
    """A surviving heading is no use if it is rendered mid-paragraph."""
    out, _ = redact_unverified_v2(REPORT, [{"ref_index": 1}])
    for line in _body(out).split("\n"):
        if "##" in line:
            assert line.strip().startswith("#"), (
                "heading inlined into prose: %r" % line)


def test_bullets_stay_separate_lines():
    out, _ = redact_unverified_v2(REPORT, [{"ref_index": 1}])
    bullets = [l for l in _body(out).split("\n") if l.strip().startswith("- ")]
    assert len(bullets) == 2, "bullet list collapsed: %r" % bullets


def test_only_offending_sentences_are_removed():
    out, _ = redact_unverified_v2(REPORT, [{"ref_index": 1}])
    body = _body(out)
    assert "[1]" not in body
    assert "lactate drop [2]" in body
    assert "coordinated induction [3]" in body
    assert "Succinate dehydrogenase" not in body, "the citing sentence stayed"


def test_paragraph_structure_is_not_flattened():
    """The original failure mode in one number: newlines must not collapse."""
    out, _ = redact_unverified_v2(REPORT, [{"ref_index": 1}])
    before = _body(REPORT).count("\n")
    after = _body(out).count("\n")
    assert after >= before - 3, (
        "body lost %d of %d newlines; structure was flattened" % (before - after, before))


def test_reference_entry_is_still_removed():
    out, _ = redact_unverified_v2(REPORT, [{"ref_index": 1}])
    refs = out.split("### References")[1]
    assert "Smith" not in refs, "the failed reference entry survived"
    assert "Jones" in refs and "Lee" in refs


def test_nothing_changes_when_nothing_failed():
    out, removed = redact_unverified_v2(REPORT, [])
    assert removed == 0
    assert _body(out).count("\n") == _body(REPORT).count("\n")


def test_a_heading_left_over_nothing_is_dropped():
    """A title standing over an empty section reads as a rendering failure."""
    text = ("## Kept\n\nA fact that stands [2].\n\n"
            "## Emptied\n\nThe only claim here [9].\n\n"
            "### References\n\n[2] Jones.\n[9] Bad.\n")
    out, _ = redact_unverified_v2(text, [{"ref_index": 9}])
    body = _body(out)
    assert "## Kept" in body
    assert "## Emptied" not in body, "orphan heading kept over an empty section"


def test_a_parent_heading_keeps_its_subsections():
    """Only the emptied leaf goes; the parent still has content beneath it."""
    text = ("## Parent\n\n### Leaf A\n\nStands [2].\n\n"
            "### Leaf B\n\nGoes [9].\n\n### References\n\n[2] J.\n[9] B.\n")
    out, _ = redact_unverified_v2(text, [{"ref_index": 9}])
    body = _body(out)
    assert "## Parent" in body and "### Leaf A" in body
    assert "### Leaf B" not in body


def test_table_rows_are_untouched():
    """A pipe table row is layout; sentence logic must not rewrite it."""
    text = ("| Pathway | q |\n| --- | --- |\n| Glycolysis | 0.01 |\n\n"
            "A claim [9].\n\n### References\n\n[9] B.\n")
    out, _ = redact_unverified_v2(text, [{"ref_index": 9}])
    body = _body(out)
    assert body.count("|") == text.split("### References")[0].count("|")


def test_code_fences_pass_through_whole():
    text = ("```\nx = 1. y = 2.\n```\n\nA claim [9].\n\n"
            "### References\n\n[9] B.\n")
    out, _ = redact_unverified_v2(text, [{"ref_index": 9}])
    assert "x = 1. y = 2." in out, "fenced content was sentence-split"


def test_a_sentence_spanning_two_lines_is_removed_whole():
    """Soft-wrapped prose must not leave a dangling half-sentence."""
    text = ("The measured effect was large and\nsustained over time [9].\n"
            "A separate fact [2].\n\n### References\n\n[2] J.\n[9] B.\n")
    out, _ = redact_unverified_v2(text, [{"ref_index": 9}])
    body = _body(out)
    assert "sustained over time" not in body
    assert "The measured effect" not in body, "left half of a removed sentence"
    assert "A separate fact [2]." in body


def test_removed_count_covers_body_and_references():
    """Two citing sentences plus one reference entry."""
    _, removed = redact_unverified_v2(REPORT, [{"ref_index": 1}])
    assert removed == 3, "expected 2 sentences + 1 reference, got %d" % removed


def test_redaction_never_glues_a_structure_token_to_prose():
    """The invariant behind the frontend's newline-recovery shim.

    Across the 56 reports stored locally the separation is total: 29 of 29 with
    a redaction carried glued structure tokens (mean 37.6 of them), 0 of 27
    without a redaction carried any. The glue was never model behaviour, which
    is what the client's _preprocessMarkdown comment claimed -- it was this
    function's " ".join(). This test is the guarantee that it stays gone.
    """
    import re as _re
    patterns = [
        (_re.compile(r"[^\n][ \t]+#{1,6} "), "heading glued after prose"),
        (_re.compile(r"[.!?\]\*][ \t]+- (?=\*|[A-Z])"), "bullet glued after prose"),
        (_re.compile(r"[^\n-][ \t]+-{3,}[ \t]*(?=\n|$)"), "rule glued after prose"),
    ]
    text = ("## A\n\nOne [9].\n\n## B\n\nTwo [2].\n\n"
            "- Bullet one [9].\n- Bullet two [2].\n\n---\n\n"
            "More prose [2].\n\n### References\n\n[2] J.\n[9] B.\n")
    out, _ = redact_unverified_v2(text, [{"ref_index": 9}])
    body = _body(out)
    for rx, label in patterns:
        assert not rx.search(body), "%s: %r" % (label, rx.search(body).group(0))



def test_a_report_that_grounded_nothing_says_so():
    """One stored run retrieved 56 papers, wrote 56 citations, found quotes for
    none, rendered no references, and shipped 49 752 characters as "done" with
    a verification score of 0.07. Nothing in the text said the interpretation
    was uncorroborated, and the text outlives the progress line."""
    out = _note_if_ungrounded("Findings without citations.", [], {1: {}, 2: {}})
    assert "Note on evidence" in out, "an ungrounded report shipped silently"
    assert "2 retrieved paper" in out, "the note does not say how many were tried"
    assert "measured data alone" in out


def test_a_grounded_report_gets_no_note():
    out = _note_if_ungrounded("Findings [1].", [{"ref_index": 1}], {1: {}})
    assert "Note on evidence" not in out, "a cited report was labelled ungrounded"


def test_a_run_that_retrieved_nothing_makes_no_claim():
    """No papers means no literature claim to walk back."""
    out = _note_if_ungrounded("Data-only findings.", [], {})
    assert "Note on evidence" not in out



def test_a_timeout_ships_what_exists_rather_than_nothing():
    """Roughly one base run in seven hits the ten-minute ceiling -- median 399 s,
    max 602 over 14 archived runs. Today that run raises and every phase's work
    is discarded, so a user who waited ten minutes is told to try again while a
    synthesised report with rendered references sat in memory."""
    stats = {}
    _keep_partial(stats, "Glycolysis is repressed [1].", [{"ref_index": 1}],
                  "references rendered")
    salvaged = _partial_result(stats, 10)
    assert salvaged is not None, "a report existed and was still discarded"
    report, papers = salvaged
    assert "Incomplete interpretation" in report, "the reader is not warned"
    assert "references rendered" in report, "the reader cannot tell how far it got"
    assert "Glycolysis is repressed [1]." in report, "the work itself was lost"
    assert len(papers) == 1
    assert stats.get("timed_out_at_stage") == "references rendered"


def test_a_timeout_with_nothing_to_show_still_fails():
    """Salvage must not manufacture a report out of an empty run."""
    assert _partial_result({}, 10) is None
    stats = {}
    _keep_partial(stats, "   ", [], "synthesis")
    assert _partial_result(stats, 10) is None, "whitespace was shipped as a report"



def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_headings_survive_a_redaction,
              test_headings_stay_on_their_own_line,
              test_bullets_stay_separate_lines,
              test_only_offending_sentences_are_removed,
              test_paragraph_structure_is_not_flattened,
              test_reference_entry_is_still_removed,
              test_nothing_changes_when_nothing_failed,
              test_a_heading_left_over_nothing_is_dropped,
              test_a_parent_heading_keeps_its_subsections,
              test_table_rows_are_untouched,
              test_code_fences_pass_through_whole,
              test_a_sentence_spanning_two_lines_is_removed_whole,
              test_a_report_that_grounded_nothing_says_so,
              test_a_grounded_report_gets_no_note,
              test_a_run_that_retrieved_nothing_makes_no_claim,
              test_a_timeout_ships_what_exists_rather_than_nothing,
              test_a_timeout_with_nothing_to_show_still_fails,
              test_removed_count_covers_body_and_references,
              test_redaction_never_glues_a_structure_token_to_prose):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
