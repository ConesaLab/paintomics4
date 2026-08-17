#!/usr/bin/env python3
"""The loop's budgets are enforced in code, not in the prompt.

The whole safety argument for handing an LLM the wheel is that the tools, not
the model, decide how much of anything a run may spend: searches, time,
tool-output volume, and reference numbering. That argument is only worth
something if the enforcement is tested, so this covers it deterministically --
no gateway, no Mongo, no job.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_agent_loop_budgets
"""
import os
import sys
import time

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SERVER_ROOT)

from src.classes.AIInterpret import agent_loop as L

_PASSED, _FAILED = [], []


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  " + name)
    except Exception as exc:
        _FAILED.append((name, "%s: %s" % (type(exc).__name__, exc)))
        print("FAIL  %s\n      %s: %s" % (name, type(exc).__name__, exc))


def _ctx(**kw):
    defaults = dict(job_instance=None, job_id="TEST", organism_name="Mus musculus",
                    experiment_design="", started_at=time.time(),
                    hard_deadline=time.time() + 10_000)
    defaults.update(kw)
    return L.LoopContext(**defaults)


# -- the character ledger ---------------------------------------------------

def test_tool_output_under_budget_is_returned_whole():
    ctx = _ctx()
    text = "x" * 500
    assert L._spend(ctx, text) == text
    assert ctx.tool_chars == 500


def test_tool_output_over_budget_is_cut_and_says_so():
    ctx = _ctx()
    ctx.tool_chars = L.TOOL_CHAR_BUDGET - 10
    # A filler character that cannot appear in the exhaustion notice: counting
    # "y" here first failed on the "y" in "your report", which is the test
    # being wrong rather than the ledger.
    out = L._spend(ctx, "Z" * 1000)
    assert "TOOL BUDGET EXHAUSTED" in out, out[-120:]
    assert out.count("Z") == 10, (
        "the ledger let %d characters through when 10 remained" % out.count("Z"))


def test_the_ledger_line_reports_what_is_left():
    ctx = _ctx(searches_used=5)
    note = L._ledger_note(ctx)
    assert "%d searches left" % (L.SEARCH_BUDGET - 5) in note, note
    assert "s left" in note and "chars" in note, note


# -- the clock --------------------------------------------------------------

def test_the_time_guard_is_quiet_while_there_is_time():
    assert L._time_guard(_ctx()) is None


def test_the_time_guard_stops_investigation_with_time_left_to_write():
    # Inside the write reserve but not yet at the deadline: the guard must
    # already be refusing, because a report needs those seconds.
    ctx = _ctx(hard_deadline=time.time() + L.WRITE_RESERVE_SECONDS - 5)
    message = L._time_guard(ctx)
    assert message and "submit_report" in message, message
    assert "TIME IS UP" in message, message


def test_the_write_reserve_leaves_room_for_a_long_generation():
    # A reserve shorter than a long-form call would make the guard useless.
    assert L.WRITE_RESERVE_SECONDS >= 90, L.WRITE_RESERVE_SECONDS
    assert L.WRITE_RESERVE_SECONDS < (L.AGENT_RUN_SECONDS - L.GATE_RESERVE_SECONDS), (
        "the write reserve consumes the whole loop budget")


def test_the_gate_reserve_leaves_the_loop_something_to_do():
    loop_budget = L.AGENT_RUN_SECONDS - L.GATE_RESERVE_SECONDS
    assert loop_budget >= 120, loop_budget


# -- reference numbering ----------------------------------------------------

def test_papers_get_stable_increasing_reference_numbers():
    ctx = _ctx()
    first = L._register_papers(ctx, [{"pmid": "1", "title": "A"},
                                     {"pmid": "2", "title": "B"}], "pathway-x")
    assert [line[:3] for line in first] == ["[1]", "[2]"], first
    assert ctx.next_ref == 3


def test_the_same_pmid_never_gets_a_second_number():
    ctx = _ctx()
    L._register_papers(ctx, [{"pmid": "1", "title": "A"}], "pathway-x")
    again = L._register_papers(ctx, [{"pmid": "1", "title": "A"}], "pathway-y")
    assert ctx.next_ref == 2, "a duplicate PMID consumed a reference number"
    assert again and again[0].startswith("[1]"), again
    # ...and the second topic is remembered as attribution, not lost.
    assert ctx.paper_index[1]["pathways"] == ["pathway-x", "pathway-y"], \
        ctx.paper_index[1]["pathways"]


def test_a_paper_without_a_pmid_is_skipped():
    ctx = _ctx()
    assert L._register_papers(ctx, [{"title": "no id"}], "t") == []
    assert ctx.next_ref == 1


def test_registered_papers_default_to_abstract_only():
    ctx = _ctx()
    L._register_papers(ctx, [{"pmid": "9", "title": "T", "abstract": "a"}], "t")
    paper = ctx.paper_index[1]
    assert paper["fetch_tier"] == "abstract_only", paper["fetch_tier"]
    assert paper["full_text_available"] is False
    assert paper["sections"]["abstract"] == "a"


def main():
    for t in (test_tool_output_under_budget_is_returned_whole,
              test_tool_output_over_budget_is_cut_and_says_so,
              test_the_ledger_line_reports_what_is_left,
              test_the_time_guard_is_quiet_while_there_is_time,
              test_the_time_guard_stops_investigation_with_time_left_to_write,
              test_the_write_reserve_leaves_room_for_a_long_generation,
              test_the_gate_reserve_leaves_the_loop_something_to_do,
              test_papers_get_stable_increasing_reference_numbers,
              test_the_same_pmid_never_gets_a_second_number,
              test_a_paper_without_a_pmid_is_skipped,
              test_registered_papers_default_to_abstract_only):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
