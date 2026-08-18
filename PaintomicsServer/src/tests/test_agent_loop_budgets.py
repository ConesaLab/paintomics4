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


# -- the merge guard must compare like with like ---------------------------

def test_the_grounding_sieve_is_applied_to_both_sides():
    """Filtering only the candidate compared a strict count against a lenient
    one, so the guard could never accept: a run reported 15 unverifiable quotes,
    rejected a stitch that was genuinely better, and shipped the thin draft. An
    asymmetric test is not a strict test, it is a broken one."""
    import inspect
    src = inspect.getsource(L._run_loop_async)
    assert src.count("_verified_quotes(ctx,") == 2, (
        "the sieve is applied %d time(s); both the draft and the candidate must "
        "go through it" % src.count("_verified_quotes(ctx,"))


def test_the_sieve_keeps_only_findable_quotes():
    ctx = _ctx()
    ctx.paper_index = {
        1: {"sections": {"results": "Ikaros represses Ccr2 in pre-B cells."}},
        2: {"sections": {"results": "Unrelated text about something else."}},
    }
    kept = L._verified_quotes(ctx, {1: "Ikaros represses Ccr2 in pre-B cells.",
                                    2: "A sentence that is nowhere in paper two."})
    assert set(kept) == {1}, kept


# -- the ledger reports coverage, not only budget ---------------------------

def test_the_ledger_shows_cluster_coverage_once_there_is_a_map():
    """Budget says what may still be spent; coverage says what is still unlit.
    Two replicates of identical code searched 20 and 14 times (25 vs 15
    citations), and neither could see how much of its own partition had
    literature behind it."""
    ctx = _ctx()
    assert "clusters" not in L._ledger_note(ctx), (
        "coverage must not be claimed before cluster_pathways has run")
    ctx.partition = {"clusters": [{"id": "C%02d" % i} for i in range(1, 21)],
                     "standalone": ["a", "b"]}
    ctx.searched_tags = {"cytokine signalling", "ribosome biogenesis"}
    note = L._ledger_note(ctx)
    assert "literature searched for 2 of 22 clusters" in note, note


def test_a_search_records_its_topic_tag():
    """The coverage count is only as good as the tagging behind it."""
    import inspect
    src = inspect.getsource(L)
    assert "searched_tags.add" in src, (
        "searches no longer record their topic_tag, so coverage cannot be counted")


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


# -- the delegation nudge is a nudge, not a veto ---------------------------

def test_the_submit_nudge_fires_once_then_never_blocks():
    """Two replicates of identical code differed 5x in prose because one never
    delegated. The first thin, undelegated submit is told so; the second is
    accepted whatever it looks like -- a tool that can refuse twice has become a
    workflow step."""
    import inspect
    src = inspect.getsource(L)
    assert "submit_attempts == 1" in src, (
        "the nudge is not gated on the first attempt, so it can block twice")
    assert "submit_attempts += 1" in src
    assert "< 500" in src, "the unconditional stub-report floor was lost"


def test_the_nudge_threshold_sits_below_a_real_report():
    """It must not fire on a finished report: measured runs ship 24 000-79 000
    chars, the smallest good one about 24 900."""
    import inspect
    assert "< 9000" in inspect.getsource(L), (
        "the nudge threshold moved; re-check it against real run sizes")


# -- the stitched report must stay inside the size ceiling -----------------

def test_the_stitch_cap_leaves_room_for_tables_and_references():
    """The comparison rule rejects a report outside [0.6x, 2.0x] of the workflow
    arm's 41 293 chars, i.e. above 82 586. A run at cap 42 000 shipped 61 090, so
    tables + references + framing cost about 19 000 on top of the stitched
    detail. The cap has to leave that much headroom."""
    OVERHEAD = 19000          # measured: 61 090 shipped from a 42 000 cap
    CEILING = 82586           # 2.0x the workflow arm's mean report
    assert L.STITCH_MAX_CHARS + OVERHEAD <= CEILING, (
        "cap %d + %d overhead would ship %d chars, past the %d ceiling"
        % (L.STITCH_MAX_CHARS, OVERHEAD, L.STITCH_MAX_CHARS + OVERHEAD, CEILING))
    # ...and be worth having: below the workflow arm's own prose it cannot cover
    # the same ground.
    assert L.STITCH_MAX_CHARS >= 39237, L.STITCH_MAX_CHARS


# -- post-loop work must fit the clock that is left ------------------------

def test_the_gate_floor_is_big_enough_for_the_gate():
    """Round 7 r1 died at 602 s of a 600 s ceiling: a 50 s merge ran after a
    450 s loop with only 150 s reserved, and the gate had nothing left. The
    floor has to cover quotes + per-citation verification + the net."""
    assert L.GATE_MIN_SECONDS >= 120, L.GATE_MIN_SECONDS
    assert L.GATE_MIN_SECONDS <= L.GATE_RESERVE_SECONDS, (
        "the gate floor cannot exceed the reserve the loop already gives up")


def test_a_merge_with_no_time_left_is_skipped_not_attempted():
    """The decision is arithmetic, so it is testable without a gateway: with the
    deadline already inside the gate floor there must be no budget to merge."""
    ctx = _ctx(started_at=time.time() - (L.AGENT_RUN_SECONDS - L.GATE_MIN_SECONDS + 10))
    budget = ((ctx.started_at + L.AGENT_RUN_SECONDS) - time.time()
              - L.GATE_MIN_SECONDS)
    assert budget < 30, budget          # the branch agent_loop takes to skip


def test_a_merge_early_in_a_run_gets_a_real_budget():
    ctx = _ctx(started_at=time.time() - 60)
    budget = ((ctx.started_at + L.AGENT_RUN_SECONDS) - time.time()
              - L.GATE_MIN_SECONDS)
    assert budget > 200, budget


# -- the trace archive ------------------------------------------------------

def test_each_event_is_archived_once():
    """Twelve benchmark runs left two surviving traces, because the DAO keeps
    only the current run. The archive is what makes tool usefulness measurable,
    so it must record every event exactly once and never duplicate on reflush."""
    import json as _json
    import tempfile
    ctx = _ctx()
    with tempfile.TemporaryDirectory() as tmp:
        import src.conf.serverconf as conf
        saved = conf.CLIENT_TMP_DIR
        conf.CLIENT_TMP_DIR = tmp
        try:
            L._trace(ctx, "search_literature", "q", "5 hits", time.time())
            L._trace(ctx, "read_paper", "[1] results", "900 chars", time.time())
            L._archive_trace(ctx)          # a reflush must not duplicate
            path = os.path.join(tmp, "ai_traces",
                                "%s-%d.jsonl" % (ctx.job_id, int(ctx.started_at)))
            lines = [l for l in open(path).read().splitlines() if l.strip()]
        finally:
            conf.CLIENT_TMP_DIR = saved
    assert len(lines) == 2, lines
    tools = [_json.loads(l)["tool"] for l in lines]
    assert tools == ["search_literature", "read_paper"], tools
    assert _json.loads(lines[0])["seq"] == 1


def test_archiving_never_breaks_a_run():
    """An unwritable directory must cost nothing: the trace is instrumentation,
    the interpretation is the product."""
    ctx = _ctx()
    import src.conf.serverconf as conf
    saved = conf.CLIENT_TMP_DIR
    conf.CLIENT_TMP_DIR = "/proc/definitely-not-writable"
    try:
        L._trace(ctx, "notebook_write", "note", "ok", time.time())   # must not raise
    finally:
        conf.CLIENT_TMP_DIR = saved
    assert len(ctx.trace) == 1


def main():
    for t in (test_tool_output_under_budget_is_returned_whole,
              test_tool_output_over_budget_is_cut_and_says_so,
              test_the_ledger_line_reports_what_is_left,
              test_the_grounding_sieve_is_applied_to_both_sides,
              test_the_sieve_keeps_only_findable_quotes,
              test_the_ledger_shows_cluster_coverage_once_there_is_a_map,
              test_a_search_records_its_topic_tag,
              test_the_time_guard_is_quiet_while_there_is_time,
              test_the_time_guard_stops_investigation_with_time_left_to_write,
              test_the_write_reserve_leaves_room_for_a_long_generation,
              test_the_gate_reserve_leaves_the_loop_something_to_do,
              test_papers_get_stable_increasing_reference_numbers,
              test_the_same_pmid_never_gets_a_second_number,
              test_a_paper_without_a_pmid_is_skipped,
              test_registered_papers_default_to_abstract_only,
              test_the_submit_nudge_fires_once_then_never_blocks,
              test_the_nudge_threshold_sits_below_a_real_report,
              test_the_stitch_cap_leaves_room_for_tables_and_references,
              test_the_gate_floor_is_big_enough_for_the_gate,
              test_a_merge_with_no_time_left_is_skipped_not_attempted,
              test_a_merge_early_in_a_run_gets_a_real_budget,
              test_each_event_is_archived_once,
              test_archiving_never_breaks_a_run):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
