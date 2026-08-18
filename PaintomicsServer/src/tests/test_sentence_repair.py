#!/usr/bin/env python3
"""Repair the sentences that failed, not the report around them.

Measured on round 34: a base verify iteration costs ~83 s, of which the 8-way
verification fan-out is ~8 s and a full-report rewrite is the rest -- three
iterations per run, 250 s of a 430 s run. Fixing citation [7] does not depend on
fixing [12], so this is independent work being done serially.

The rewrite is destructive too, in ways the surrounding code then undoes: it
re-authors the References section (forcing every quote to be re-collected and
the section re-rendered) and drops the appended data tables (which
_reattach_blocks puts back). Replacing one sentence changes one sentence.

These tests pin the guardrails, because an unattended string substitution is
the dangerous half: a model that answers with a preamble, an apology or the
whole report echoed back would otherwise silently swallow a paragraph.

    python -m src.tests.test_sentence_repair
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent as A  # noqa: E402

_PASSED, _FAILED = [], []

REPORT = """## Findings

Glycolytic flux increases sharply in the treated group [3].

A second, unrelated statement stands here [9].

### References

[3] Some paper
[9] Another paper
"""


class _Result:
    def __init__(self, text):
        self.final_output = text


def _install(replies):
    """Stub the SDK runner: reply is chosen by the sentence in the prompt."""
    class _Runner:
        @staticmethod
        async def run(agent, prompt, context=None, max_turns=None):
            line = [l for l in prompt.split("\n") if l.startswith("SENTENCE: ")]
            key = line[0][len("SENTENCE: "):] if line else ""
            answer = replies.get(key)
            if isinstance(answer, Exception):
                raise answer
            return _Result(answer)
    A.Runner = _Runner


def _fail(sentence, ref=3, mode="claim"):
    return {"ref_index": ref, "reason": "overstated", "mode": mode,
            "cited_text": "Glycolytic flux was elevated.",
            "claim_sentence": sentence}


def _run(report, failed, replies):
    original_runner = A.Runner
    _install(replies)
    try:
        stats = {}
        out, n = asyncio.get_event_loop().run_until_complete(
            A._repair_sentences(object(), None, report, failed, "T", stats, 5))
        return out, n, stats
    finally:
        A.Runner = original_runner


def test_a_repaired_sentence_replaces_exactly_that_sentence():
    s = "Glycolytic flux increases sharply in the treated group [3]."
    fixed = "Glycolytic flux is elevated in the treated group [3]."
    out, n, stats = _run(REPORT, [_fail(s)], {s: fixed})
    assert n == 1 and stats["sentences_repaired"] == 1
    assert fixed in out and s not in out


def test_the_rest_of_the_report_is_untouched():
    """This is the property that makes the re-quote, the re-render and the
    table re-attach unnecessary."""
    s = "Glycolytic flux increases sharply in the treated group [3]."
    out, _, _ = _run(REPORT, [_fail(s)], {s: "Flux is elevated [3]."})
    assert "### References" in out and "[9] Another paper" in out
    assert "A second, unrelated statement stands here [9]." in out


def test_a_sentence_that_is_not_in_the_report_is_skipped():
    """The verifier quotes a claim sentence; the report may have moved on."""
    ghost = "This sentence was never written."
    out, n, stats = _run(REPORT, [_fail(ghost)], {ghost: "anything"})
    assert n == 0 and out == REPORT
    assert stats["repair_unlocatable"] == 1


def test_an_ambiguous_sentence_is_skipped_rather_than_guessed():
    """Two identical sentences: replacing 'the first one' is a coin flip."""
    doubled = REPORT + "\nGlycolytic flux increases sharply in the treated group [3].\n"
    s = "Glycolytic flux increases sharply in the treated group [3]."
    out, n, stats = _run(doubled, [_fail(s)], {s: "Flux is elevated [3]."})
    assert n == 0 and out == doubled
    assert stats["repair_unlocatable"] == 1


def test_a_runaway_answer_is_rejected():
    """The whole report echoed back would replace one sentence with everything."""
    s = "Glycolytic flux increases sharply in the treated group [3]."
    out, n, stats = _run(REPORT, [_fail(s)], {s: REPORT * 2})
    assert n == 0 and out == REPORT, "a runaway repair was pasted in"
    assert stats["repairs_rejected"] == 1


def test_an_empty_answer_is_rejected():
    s = "Glycolytic flux increases sharply in the treated group [3]."
    out, n, _ = _run(REPORT, [_fail(s)], {s: ""})
    assert n == 0 and out == REPORT


def test_one_failed_call_does_not_lose_the_others():
    """Repairs are independent; a gateway error on one must not cost the rest."""
    s1 = "Glycolytic flux increases sharply in the treated group [3]."
    s2 = "A second, unrelated statement stands here [9]."
    out, n, _ = _run(REPORT, [_fail(s1), _fail(s2, ref=9)],
                     {s1: RuntimeError("gateway 500"), s2: "A second statement [9]."})
    assert n == 1, "the surviving repair was lost with the failed one"
    assert "A second statement [9]." in out
    assert s1 in out, "the failed repair should leave its sentence alone"


def test_both_repairs_land_when_both_succeed():
    s1 = "Glycolytic flux increases sharply in the treated group [3]."
    s2 = "A second, unrelated statement stands here [9]."
    out, n, _ = _run(REPORT, [_fail(s1), _fail(s2, ref=9)],
                     {s1: "Flux is elevated [3].", s2: "A second statement [9]."})
    assert n == 2
    assert "Flux is elevated [3]." in out and "A second statement [9]." in out


def test_the_flag_is_off_by_default():
    """It changes the shipped arm's behaviour, so it ships dark until a round
    has measured it."""
    assert A.SENTENCE_REPAIR is False


def test_a_drift_repair_that_drops_its_citation_is_rejected():
    """The quote is real -- that is what drift means -- so the narrowed sentence
    is still a cited claim. Dropping [N] turns a fixable citation into a lost
    one, and the reference it leaves behind is redacted along with the sentence."""
    s = "Glycolytic flux increases sharply in the treated group [3]."
    out, n, stats = _run(REPORT, [_fail(s)], {s: "Glycolytic flux is elevated."})
    assert n == 0 and out == REPORT, "a repair silently dropped its citation"
    assert stats["repairs_rejected"] == 1


def test_a_drift_repair_keeping_its_citation_is_accepted():
    s = "Glycolytic flux increases sharply in the treated group [3]."
    fixed = "Glycolytic flux is elevated in the treated group [3]."
    out, n, _ = _run(REPORT, [_fail(s)], {s: fixed})
    assert n == 1 and fixed in out


def test_a_text_mode_repair_may_drop_the_citation():
    """Here the quote is NOT in the paper, so keeping the marker would force the
    model to retain a citation it was just told is unsupportable."""
    s = "Glycolytic flux increases sharply in the treated group [3]."
    out, n, _ = _run(REPORT, [_fail(s, mode="text")],
                     {s: "Glycolytic flux is elevated in the treated group."})
    assert n == 1, "a text-mode repair was forced to keep an unsupportable citation"
    assert "Glycolytic flux is elevated in the treated group." in out


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_repaired_sentence_replaces_exactly_that_sentence,
              test_the_rest_of_the_report_is_untouched,
              test_a_sentence_that_is_not_in_the_report_is_skipped,
              test_an_ambiguous_sentence_is_skipped_rather_than_guessed,
              test_a_runaway_answer_is_rejected,
              test_an_empty_answer_is_rejected,
              test_one_failed_call_does_not_lose_the_others,
              test_both_repairs_land_when_both_succeed,
              test_the_flag_is_off_by_default,
              test_a_drift_repair_that_drops_its_citation_is_rejected,
              test_a_drift_repair_keeping_its_citation_is_accepted,
              test_a_text_mode_repair_may_drop_the_citation):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
