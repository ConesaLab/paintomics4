#!/usr/bin/env python3
"""notebook_write had 100% adoption and, on 98% of runs, no reader at all.

The census across 25 real agent-loop runs put every one of the nine surviving
tools at 100% adoption -- the four dead tools were already removed on evidence,
so "nobody calls it" has no remaining targets. The interesting question moved to
tools that ARE called and do not earn it, and notebook_write is the clearest
case the call count cannot see.

Its stored output had exactly two readers, both on failure paths: the forced
synthesis and the model-free assembly. Across 64 archived runs, ONE reached
those (2%). On the other 98% the agent wrote a median of three notes that
nothing ever read.

That is not grounds for deletion -- a note stays in the SDK conversation
context, which is its own rehearsal, and the fallback needs the store. It is
grounds for giving it a reader on the path runs actually take. A finding the
agent recorded and then left out of its draft is either a deliberate cut or a
dropped one, and surfacing it costs no model call.

    python -m src.tests.test_notebook_has_a_reader
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.agent_loop import _unrepresented_notes as unrep  # noqa: E402
from src.classes.AIInterpret import agent_loop as L  # noqa: E402

_PASSED, _FAILED = [], []


def test_a_recorded_finding_missing_from_the_draft_is_surfaced():
    assert unrep(["Cd47 marks efferocytosis"], "The draft says nothing.") == [
        "Cd47 marks efferocytosis"]


def test_a_finding_that_reached_the_draft_is_not_nagged_about():
    assert unrep(["Ikzf1 drives B cell arrest"],
                 "We find Ikzf1 is central here.") == []


def test_the_report_may_rephrase_the_note():
    """Notes are prose and the report restates them; matching whole notes would
    flag everything. Entity tokens are what survive rephrasing."""
    notes = ["Glycolysis is strongly elevated in the treated arm"]
    assert unrep(notes, "Glycolysis rises sharply after treatment.") == []


def test_a_note_with_no_identifiable_entity_is_never_judged():
    """A general observation has nothing to match on; guessing would produce a
    warning the agent cannot act on."""
    assert unrep(["this looks like a coordinated response"], "") == []


def test_matching_ignores_case():
    assert unrep(["IKZF1 matters"], "the ikzf1 locus is disrupted") == []


def test_the_list_is_capped():
    """It rides in a tool result that is re-sent on every later turn."""
    notes = ["Gene%d does something" % i for i in range(20)]
    assert len(unrep(notes, "", limit=5)) == 5


def test_a_long_note_is_truncated():
    out = unrep(["Abc1 " + "x" * 400], "")
    assert len(out[0]) <= 110


def test_empty_inputs_are_safe():
    assert unrep([], "text") == []
    assert unrep(None, None) == []
    assert unrep(["Abc1 finding"], None) == ["Abc1 finding"]


def test_the_reader_is_actually_wired_into_the_tool():
    """A consumer nobody calls leaves the store exactly as unread as before."""
    src = inspect.getsource(L)
    start = src.index("def check_my_citations(")
    end = src.index("@function_tool", start)
    assert "_unrepresented_notes(c.notebook" in src[start:end], (
        "check_my_citations does not read the notebook")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_recorded_finding_missing_from_the_draft_is_surfaced,
              test_a_finding_that_reached_the_draft_is_not_nagged_about,
              test_the_report_may_rephrase_the_note,
              test_a_note_with_no_identifiable_entity_is_never_judged,
              test_matching_ignores_case,
              test_the_list_is_capped,
              test_a_long_note_is_truncated,
              test_empty_inputs_are_safe,
              test_the_reader_is_actually_wired_into_the_tool):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
