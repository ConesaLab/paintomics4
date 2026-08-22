#!/usr/bin/env python3
"""A citation should be allowed to sit on a sentence that states a result.

`build_evidence_shelf_block` tells the writers to keep data sentences and
literature sentences apart, and gives its reason as "a claim written first and
supported afterwards is the one that fails verification". That reason is about
ORDER, and the quote shelf already fixes order by handing the passages over
before the writer starts.

Measured against the archive the rule is over-corrected: 5-10% of citation
sentences join a data claim to a citation anyway, every one of them survived the
gate, and read side by side they are the best citations in the corpus --

    "Igll1 (peak -4.43) and Vpreb1b (peak -4.39) are strongly repressed, matching
     the known role of Ikaros/Aiolos as direct repressors of Igll1 and Vpreb1 in
     small pre-B cells [2]"

    "Prkcb shows profound, sustained repression (-4.87 to -5.03) yet PKCb is
     described as promoting the germinal center reaction in B cells [6]"

-- the second setting data against literature, which is interpretation rather
than recitation.

    python -m src.tests.test_a_citation_may_touch_the_data
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402
from src.benchmarks.ai_arm_bench import citation_grounding   # noqa: E402

_PASSED, _FAILED = [], []


def test_the_flag_defaults_off():
    """Every round measured so far ran without it."""
    assert L.JOIN_DATA_AND_CITATION is False


def test_the_note_is_appended_only_when_there_is_a_shelf():
    """With no passages there is nothing to join a measurement to, and the note
    would be an instruction to cite something the writer has not been given."""
    src = open(L.__file__.replace(".pyc", ".py")).read()
    src.index("_JOIN_NOTE")
    call = src[src.index("if shelf and JOIN_DATA_AND_CITATION"):][:120]
    assert "shelf and" in call, call


def test_it_does_not_ask_for_more_citations():
    """The failure mode of any instruction about citations in this pipeline is
    inflation: rounds 13-15 reworded the delegate prompt and citations went
    7 -> 3. The note must not read as 'cite more'."""
    note = L._JOIN_NOTE
    assert "NOT a licence to cite more" in note, note
    assert "still goes uncited" in note
    assert "still carries no marker" in note


def test_it_shows_the_shape_rather_than_describing_it():
    """Both examples are real sentences from the archive that passed the gate."""
    note = L._JOIN_NOTE
    assert "Igll1 falls to -4.43" in note
    assert "Prkcb is repressed throughout" in note


def test_it_permits_the_disagreeing_case():
    """The most interpretive citation found in the corpus set the data AGAINST
    the literature. An instruction that only allowed confirmation would suppress
    exactly that."""
    assert "where the two disagree" in L._JOIN_NOTE
    assert "tension stated plainly" in L._JOIN_NOTE


def test_the_example_sentences_would_score_as_linked():
    """The metric and the instruction have to agree about what they are for, or
    a round could follow the note and score no differently."""
    for sentence in ("Igll1 falls to -4.43 by 24h, matching the known role of "
                     "Ikaros as a direct repressor of Igll1 [2].",
                     "Prkcb is repressed throughout (-4.87 to -5.03), yet PKCb "
                     "is described as promoting the germinal centre reaction [6]."):
        total, linked = citation_grounding(sentence)
        assert (total, linked) == (1, 1), (sentence, total, linked)


def test_the_shared_prompt_is_untouched():
    """Editing build_evidence_shelf_block would change the shipped arm too, and
    the shipped arm is the control."""
    from src.classes.AIInterpret import prompts
    block = prompts.build_evidence_shelf_block({1: "a passage"})
    assert "One more thing about the two kinds" not in block, (
        "the note leaked into the shared block, contaminating base")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_flag_defaults_off,
              test_the_note_is_appended_only_when_there_is_a_shelf,
              test_it_does_not_ask_for_more_citations,
              test_it_shows_the_shape_rather_than_describing_it,
              test_it_permits_the_disagreeing_case,
              test_the_example_sentences_would_score_as_linked,
              test_the_shared_prompt_is_untouched):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
