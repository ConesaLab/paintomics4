#!/usr/bin/env python3
"""The top-up's input, handed to the agent while the draft can still change.

Measured round 39, replicate 1: the top-up costs 83.5 s -- 24% of a 355 s run --
and supplies 9 of 26 citations. It works by taking a FINISHED report and adding
[N] to sentences that already stood on their own, which is the asymmetric bet
priced earlier in this session: a marker that verifies buys one citation, a
marker that fails costs the whole sentence.

The same information can reach the Lead while it is still drafting.
check_my_citations has 100% adoption -- every archived run calls it, a median of
twice -- and it is called before submit. Giving it the uncited pool lets a
citation be written INTO the sentence rather than bolted onto it afterwards.

This does not remove the top-up. It gives the agent the chance to make it a
no-op, which is the only honest way to find out whether the stage is needed.

    python -m src.tests.test_uncited_pool_reaches_the_agent
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L  # noqa: E402

_PASSED, _FAILED = [], []

INDEX = {
    1: {"ref_index": 1, "title": "A paper the draft cites"},
    2: {"ref_index": 2, "title": "Uncited, abstract only"},
    3: {"ref_index": 3, "title": "Uncited, full text", "full_text_available": True},
}


def test_only_uncited_papers_are_listed():
    out = L._uncited_papers(INDEX, {1})
    assert [p["ref_index"] for p in out] == [3, 2], out


def test_full_text_papers_come_first():
    """A quotable sentence for a specific claim usually sits in Results, and 30%
    of surviving quotes come from full text -- so those are the papers most
    likely to convert."""
    out = L._uncited_papers(INDEX, {1})
    assert out[0]["ref_index"] == 3


def test_a_fully_cited_draft_gets_no_list():
    """Nothing to say is worth saying nothing about: this block rides in a tool
    result that is re-sent on every later turn."""
    assert L._uncited_papers(INDEX, {1, 2, 3}) == []


def test_the_list_is_capped():
    big = {i: {"ref_index": i, "title": "t%d" % i} for i in range(1, 60)}
    assert len(L._uncited_papers(big, set(), limit=12)) == 12


def test_empty_inputs_are_safe():
    assert L._uncited_papers({}, set()) == []
    assert L._uncited_papers(None, None) == []


def test_the_advice_does_not_encourage_stuffing():
    """The top-up's own prompt learned this the hard way: a citation that does
    not fit is removed along with the claim it sits on. The nudge has to carry
    that, or it trades citations for sentences."""
    src = inspect.getsource(L)
    i = src.index("Retrieved papers your draft cites NOWHERE")
    block = src[i:i + 700]
    assembled = block.replace('"\n', "").replace('"', "")
    assert "Leaving a paper uncited is a fine outcome" in assembled, assembled
    assert "costs the sentence it lands on" in assembled


def test_it_is_wired_into_the_tool_every_run_calls():
    """A pool nobody reads is the top-up's problem restated, not solved."""
    src = inspect.getsource(L)
    i = src.index("def check_my_citations(")
    body = src[i:src.index("@function_tool", i)]
    assert "_uncited_papers(c.paper_index, cited)" in body


def test_it_ships_dark_so_the_next_round_can_REPLICATE():
    """Not about this change: about the bar.

    Round 39 is the first round where the agent arm leads every rule, and the
    shipping bar is 5/5 on two CONSECUTIVE rounds. A change landing between them
    -- however well motivated -- turns the replication into a new experiment, and
    a bar that never sees the same configuration twice can never be met. This is
    the discipline that the sentence-repair and framing rounds lacked.
    """
    assert L.SHOW_UNCITED is False
    src = inspect.getsource(L)
    i = src.index("def check_my_citations(")
    body = src[i:src.index("@function_tool", i)]
    assert "if SHOW_UNCITED else []" in body, (
        "the nudge is live, so round 40 cannot replicate round 39")


def test_it_reads_what_will_SHIP_not_just_the_draft():
    """check_my_citations already checks draft plus delegated analyses, because
    the merge brings citations this tool never saw. The uncited list must be
    computed against that same set or it will name papers the report does cite."""
    src = inspect.getsource(L)
    i = src.index("def check_my_citations(")
    body = src[i:src.index("@function_tool", i)]
    cited_line = body.index("cited = count_body_citations(shipping, valid)")
    used = body.index("_uncited_papers(c.paper_index, cited)")
    assert cited_line < used, "the uncited list is computed from the wrong set"


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_only_uncited_papers_are_listed,
              test_full_text_papers_come_first,
              test_a_fully_cited_draft_gets_no_list,
              test_the_list_is_capped,
              test_empty_inputs_are_safe,
              test_the_advice_does_not_encourage_stuffing,
              test_it_is_wired_into_the_tool_every_run_calls,
              test_it_ships_dark_so_the_next_round_can_REPLICATE,
              test_it_reads_what_will_SHIP_not_just_the_draft):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
