#!/usr/bin/env python3
"""The one tool every run calls was handing back a verdict without its evidence.

check_my_citations has 100% adoption: all 23 archived agent runs that reached
submit_report called it, unprompted by any fixed sequence. It is therefore the
highest-leverage surface in the toolbelt -- and it was answering the wrong
question confidently.

It asks "does a supporting sentence EXIST in the paper". The gate asks "does
THIS sentence support THAT claim". Measured across the archive those verdicts
run 79.5% supported, 20.1% claim drift, 0.4% fabrication, so about a fifth of
the citations this tool waves through still lose their sentence at the gate --
and redaction removes the SENTENCE, not just the marker. Worse, when nothing
was flagged the tool said "Every citation resolves and is quotable", which
reads as a clean bill of health for a check that never looked at drift.

The quotes were already collected to answer the existence question. Showing
them costs one LLM call of nothing and lets the agent do the comparison the
gate is about to do.

    python -m src.tests.test_check_my_citations_shows_its_evidence
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L  # noqa: E402

_PASSED, _FAILED = [], []


def test_the_quote_for_a_shipping_citation_is_shown():
    lines = L._quote_evidence_lines({3}, {3: "Loss of Ikzf1 impairs B cell development."})
    body = "\n".join(lines)
    assert '[3] "Loss of Ikzf1 impairs B cell development."' in body, body


def test_a_quote_for_a_paper_this_draft_does_not_cite_is_withheld():
    """The cache is seeded from earlier delegation, so it holds papers the draft
    never cites. Listing those invites citations the agent had not chosen."""
    lines = L._quote_evidence_lines({3}, {3: "cited one", 9: "never cited here"})
    assert "never cited here" not in "\n".join(lines)


def test_each_quote_occupies_exactly_one_line():
    """Quotes come out of paper text and carry newlines; a multi-line entry
    breaks the one-citation-one-line reading the agent has to do."""
    lines = L._quote_evidence_lines({3}, {3: "First half\n   and\tsecond half."})
    quote_lines = [l for l in lines if l.startswith("  [")]
    assert len(quote_lines) == 1
    assert quote_lines[0] == '  [3] "First half and second half."', quote_lines


def test_a_long_quote_is_truncated():
    """Every character re-enters the Lead's context on every later turn."""
    lines = L._quote_evidence_lines({3}, {3: "x" * 500})
    assert len(lines[1]) < 220, "an unbounded quote rides in every later turn"


def test_the_overflow_is_named_rather_than_silently_dropped():
    """A silent cap reads as 'those were the only ones'."""
    quotes = {i: "quote %d" % i for i in range(20)}
    lines = L._quote_evidence_lines(set(quotes), quotes, limit=12)
    assert lines[-1] == "  ...and 8 more, same rule.", lines[-1]
    assert len([l for l in lines if l.startswith('  [')]) == 12


def test_no_header_when_there_is_no_evidence():
    """An advisory block with nothing under it is noise in every turn after."""
    assert L._quote_evidence_lines(set(), {}) == []
    assert L._quote_evidence_lines({4}, {}) == []


def test_the_all_clear_no_longer_promises_what_the_gate_withholds():
    """'Every citation resolves and is quotable' was the sentence that made a
    20%-failure outcome look like a pass."""
    # @function_tool replaces the function with a FunctionTool, so the source
    # comes from the module and is sliced to this tool's body.
    module_src = inspect.getsource(L)
    start = module_src.index("def check_my_citations(")
    end = module_src.index("@function_tool", start)
    src = module_src[start:end]
    assert "resolves and is quotable." not in src, (
        "the unqualified all-clear is back")
    assert "NOT the" in src and "gate" in src, (
        "the all-clear no longer warns that quotable != supporting")


def test_the_description_tells_the_agent_the_evidence_is_there():
    """A tool that returns something the description never mentions gets used
    for the thing the description does mention."""
    tool = [t for t in L.TOOLBELT if t.name == "check_my_citations"][0]
    assert "quote" in (tool.description or "").lower()
    assert len(tool.description) <= 700, "descriptions ride in every Decide turn"


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_quote_for_a_shipping_citation_is_shown,
              test_a_quote_for_a_paper_this_draft_does_not_cite_is_withheld,
              test_each_quote_occupies_exactly_one_line,
              test_a_long_quote_is_truncated,
              test_the_overflow_is_named_rather_than_silently_dropped,
              test_no_header_when_there_is_no_evidence,
              test_the_all_clear_no_longer_promises_what_the_gate_withholds,
              test_the_description_tells_the_agent_the_evidence_is_there):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
