#!/usr/bin/env python3
"""The stitch must not rewrite prose the Lead already wrote.

`MERGE_MODE == "stitch"` never uses the Lead's report in the candidate. It feeds
the report plus 60 kB of delegated detail to a framing agent, asks for Key
Findings, Cross-Pathway Themes, Follow-up Experiments and Limitations, and builds
the candidate from THAT -- so the Lead's own writing, and its citations, are
discarded and re-derived.

Measured against it: the Lead already writes all four sections (six of six
rejected-merge reports have Themes, Follow-up and Limitations; five of six have
Key Findings), and the rewrite is where grounding goes -- round 47 r3's draft
carried 25 citations, 21 grounded, and the framed candidate carried 12, so the
guard threw the entire stitch away and the run shipped with no pathway section.

    python -m src.tests.test_lead_framing_is_reused
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402

_PASSED, _FAILED = [], []

FULL = """## Key Findings
- Cd19 rises early [3] and stays up [7].

## Cross-Pathway Themes
B-cell receptor signalling couples to Rap1 [12].

## Detailed Pathway Analysis

### Rap1 signaling pathway (mmu04015)
The Lead's own compressed treatment [12].

## Suggested Follow-up Experiments
1. Knock down Rap1 [12].

## Limitations and Caveats
Single time course.
"""


def test_the_head_keeps_the_leads_framing_and_its_citations():
    head, tail = L._lead_framing(FULL)
    assert "## Key Findings" in head and "## Cross-Pathway Themes" in head
    for marker in ("[3]", "[7]", "[12]"):
        assert marker in head or marker in tail, (
            "citation %s was lost by the split" % marker)


def test_the_leads_own_pathway_section_is_dropped():
    """It is being REPLACED by the delegated detail; keeping both would print
    the same pathways twice."""
    head, _tail = L._lead_framing(FULL)
    assert "Rap1 signaling pathway (mmu04015)" not in head, head
    assert "compressed treatment" not in head


def test_the_tail_starts_at_follow_up():
    _head, tail = L._lead_framing(FULL)
    assert tail.lstrip().startswith("## Suggested Follow-up Experiments"), tail[:80]
    assert "## Limitations and Caveats" in tail


def test_a_report_without_the_sections_falls_back():
    """Strict on purpose: splicing detail into a report missing its framing is
    worse than paying for the LLM call."""
    assert L._lead_framing("Just some prose with no headings at all.") == (None, None)
    assert L._lead_framing("## Key Findings\nonly this") == (None, None)
    assert L._lead_framing("") == (None, None)
    assert L._lead_framing(None) == (None, None)


def test_a_report_with_no_detail_section_still_splits():
    """The Lead need not have written a pathway section for the splice to work;
    the head then runs up to the follow-up marker."""
    text = ("## Key Findings\n- a [1]\n\n## Cross-Pathway Themes\nb [2]\n\n"
            "## Suggested Follow-up Experiments\n1. c\n")
    head, tail = L._lead_framing(text)
    assert "Cross-Pathway Themes" in head
    assert tail.lstrip().startswith("## Suggested Follow-up")


def test_headings_are_matched_case_and_depth_tolerantly():
    text = ("### key findings\n- a [1]\n\n### suggested follow-up experiments\n1. b\n")
    head, tail = L._lead_framing(text)
    assert head and tail, "a real report was rejected over heading style"


def test_the_flag_defaults_on():
    """DEFAULT FLIPPED ON for the agent-v54-r3 ship.

    Round 49 measured it: merge rejections went from 21% of runs to 0 of 4, and
    merge_s from 18-20 s to 6-7 s. A rejected merge costs the run its entire
    delegated section -- r3 of round 47 shipped 31 kB instead of 71 kB -- so this
    is worth more than the LLM framing call it replaces.
    """
    assert L.FRAMING_REUSE_LEAD is True


def test_the_splice_is_wired_to_the_flag():
    """Pins the CALL SITE, after a bug in this project where the default path
    broke because a change 'meant to be dark' was spliced in wrongly."""
    src = open(L.__file__.replace(".pyc", ".py")).read()
    i = src.index("reused_head, reused_tail = _lead_framing(report)")
    j = src.index("elif MERGE_MODE ==", i)
    block = src[i:j]
    assert "FRAMING_REUSE_LEAD" in src[:i][-400:], "the reuse is not flag-gated"
    assert "Detailed Pathway Analysis" in block, "the splice lost its heading"
    assert "resolve_pmid_mentions" in block, (
        "PMID-form citations from the delegates would never become [N] markers")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_head_keeps_the_leads_framing_and_its_citations,
              test_the_leads_own_pathway_section_is_dropped,
              test_the_tail_starts_at_follow_up,
              test_a_report_without_the_sections_falls_back,
              test_a_report_with_no_detail_section_still_splits,
              test_headings_are_matched_case_and_depth_tolerantly,
              test_the_flag_defaults_on,
              test_the_splice_is_wired_to_the_flag):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
