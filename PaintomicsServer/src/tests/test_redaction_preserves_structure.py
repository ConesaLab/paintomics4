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










def test_a_sentence_keeps_its_place_when_another_citation_verified():
    """39% of citation-bearing sentences in the stored reports carry two or more
    citations, and one carried ten. Deleting the sentence for one bad index
    destroys the evidence that passed: on a live run an agent submitted 11
    citations it had checked and grounded, and the gate returned 6."""
    text = ("Papers [2], [9], and [4] support this claim.\n\n"
            "### References\n\n[2] A.\n[4] B.\n[9] C.\n")
    out, _ = redact_unverified_v2(text, [{"ref_index": 9}])
    body = _body(out)
    assert "support this claim" in body, "the whole sentence was deleted"
    assert "[2]" in body and "[4]" in body, "verified citations were lost with it"
    assert "[9]" not in body


def test_a_sentence_resting_only_on_a_failed_citation_still_goes():
    text = "Only [9] backs this.\n\n### References\n\n[9] C.\n"
    out, _ = redact_unverified_v2(text, [{"ref_index": 9}])
    assert "backs this" not in _body(out), "an unsupported claim survived"


def test_the_surviving_citation_list_reads_correctly():
    """Editing markers in place produced 'from [1] and agrees' and 'rose, [2]'.
    The list is re-rendered from its survivors instead."""
    for text, bad, expect_in, expect_out in (
            ("Evidence from [1] and [9] agrees.", 9, "from [1] agrees", " and agrees"),
            ("Rose sharply [9], [2].", 9, "sharply [2]", ", [2]"),
            ("A list [3], [9], [5] repeated.", 9, "[3] and [5] repeated", ", ,")):
        full = text + "\n\n### References\n\n[1] A.\n[2] B.\n[3] C.\n[5] D.\n[9] E.\n"
        body = _body(redact_unverified_v2(full, [{"ref_index": bad}])[0])
        assert expect_in in body, "expected %r in %r" % (expect_in, body)
        assert expect_out not in body, "left %r behind: %r" % (expect_out, body)


def test_prose_commas_are_not_touched():
    text = ("Fruit, vegetables, and grain rose [9], [2].\n\n"
            "### References\n\n[2] B.\n[9] E.\n")
    body = _body(redact_unverified_v2(text, [{"ref_index": 9}])[0])
    assert "Fruit, vegetables, and grain" in body, "an Oxford comma in prose was eaten"


def test_a_ten_citation_sentence_loses_only_the_bad_one():
    import re
    cites = ", ".join("[%d]" % i for i in range(1, 11))
    text = ("Papers %s provide mechanistic support.\n\n### References\n\n" % cites
            + "".join("[%d] Paper.\n" % i for i in range(1, 11)))
    body = _body(redact_unverified_v2(text, [{"ref_index": 7}])[0])
    kept = {int(n) for n in re.findall(r"\[(\d+)\]", body)}
    assert kept == set(range(1, 11)) - {7}, "expected nine survivors, got %s" % sorted(kept)








def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    # Collected, not hand-listed. Five tests were removed with the workflow
    # arm they exercised and this tuple still named them, so the suite died on
    # a NameError instead of running. That is the fourth hand-written list in
    # this repo to rot the same way.
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith('test_') and callable(o)]
    assert tests, 'no tests collected'
    for name, t in tests:
        _check(name, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
