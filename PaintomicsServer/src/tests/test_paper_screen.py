#!/usr/bin/env python3
"""The one mechanism base has that the agent arm never had: a paper screen.

Round 38, same jobs, same denominator: base carried 27-31 papers and converted
13 of 14 retrieved themes into cited papers; this arm carried 65 and converted
7 of 14. Per paper base ships ~0.78 citations, this arm ~0.22.

Retrieval VOLUME is not the cause -- across 72 archived runs corr(papers,
citations) is only +0.16, and pools of 30 or fewer median FEWER citations than
pools over 60. What differs is that base screens every search through a Paper
Filter ("keep at most a handful"; the test is a specific quotable finding about
the MECHANISM) and this arm registered everything PubMed returned.

Ported into the search TOOL rather than added as a pipeline stage: the agent still
chooses what to search for, the tool decides what is worth keeping.

    python -m src.tests.test_paper_screen
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS  # noqa: E402
from src.classes.AIInterpret import agent_loop as L  # noqa: E402

_PASSED, _FAILED = [], []

PAPERS = [{"pmid": "1", "title": "Mechanism paper", "abstract": "Hk2 drives flux."},
          {"pmid": "2", "title": "Keyword-only paper", "abstract": "Unrelated."},
          {"pmid": "3", "title": "Review", "abstract": "We review the field."}]


class _Res:
    def __init__(self, pmids): self.final_output = type("O", (), {"pmids": pmids})()


def _run(reply):
    """Drive the real screener against a stubbed SDK runner."""
    original = L.Runner

    class _Runner:
        @staticmethod
        async def run(agent, prompt, context=None, max_turns=None):
            if isinstance(reply, Exception):
                raise reply
            return _Res(reply)
    L.Runner = _Runner
    ctx = L.LoopContext(job_instance=None, job_id="T", organism_name="mmu",
                        experiment_design="timecourse")
    try:
        return asyncio.get_event_loop().run_until_complete(
            L._screen_papers(ctx, PAPERS, "q", "glycolysis"))
    finally:
        L.Runner = original


def test_it_keeps_only_what_the_screen_named():
    kept, dropped = _run(["1"])
    assert [p["pmid"] for p in kept] == ["1"] and dropped == 2


def test_an_explicit_empty_answer_keeps_nothing():
    """'Nothing here fits' is the most useful thing a strict filter can say, and
    the prompt asks for it -- so it must not be treated as a failure."""
    kept, dropped = _run([])
    assert kept == [] and dropped == 3


def test_a_BROKEN_screen_keeps_everything():
    """A screen that raises must never silently empty the pool: losing every
    paper costs the whole report, while keeping every paper costs precision."""
    kept, dropped = _run(RuntimeError("gateway 500"))
    assert len(kept) == 3 and dropped == 0


def test_a_pmid_the_screen_invented_is_ignored():
    """The answer is intersected with the candidates, so a hallucinated PMID
    cannot add a paper that was never retrieved."""
    kept, _ = _run(["1", "999999"])
    assert [p["pmid"] for p in kept] == ["1"]


def test_no_papers_in_means_no_call_out():
    kept, dropped = _run(["1"])
    ctx = L.LoopContext(job_instance=None, job_id="T", organism_name="mmu",
                        experiment_design="")
    out = asyncio.get_event_loop().run_until_complete(L._screen_papers(ctx, [], "q", "t"))
    assert out == ([], 0)


def test_it_lives_inside_the_search_tool():
    """A separate stage would be the workflow shape this framework avoids."""
    src = inspect.getsource(L)
    i = src.index("async def search_literature(")
    end = src.index("@function_tool", i)
    assert "_screen_papers(" in src[i:end], "the screen is not inside the tool"


def test_the_screen_is_off_by_default_and_stamped():
    assert L.SCREEN_PAPERS is False
    assert "papers_screened_out" in STAGE_COUNTS
    src = inspect.getsource(L)
    stamp = src[src.index('_trace_gate(ctx, "__config__"'):][:2000]
    assert '"screen_papers"' in stamp


def test_both_arms_screen_to_the_same_standard():
    """If the standard is wrong it should be wrong in one place, not two."""
    src = inspect.getsource(L)
    assert "prompts_mod.SYSTEM_PROMPT_SEARCH_SUBAGENT" in src
    from src.classes.AIInterpret import agent as A
    assert "prompts_mod.SYSTEM_PROMPT_SEARCH_SUBAGENT" in inspect.getsource(A)


def test_the_screen_cannot_shrink_the_metrics_denominator():
    """The hazard in measuring this experiment at all.

    themes_retrieved counts themes that brought a paper back. A screen that
    rejects every hit for a theme removes that theme from the DENOMINATOR too, so
    themes_cited/themes_retrieved can rise while nothing more is cited -- the
    screen would grade itself. searched_tags is immune: it is recorded when a
    search RUNS, before any hit is fetched or screened.

    This pins the ordering, because moving the tag record below the fetch would
    break the denominator silently and the number would still look sensible.
    """
    src = inspect.getsource(L)
    i = src.index("async def search_literature(")
    body = src[i:src.index("@function_tool", i)]
    tagged = body.index("c.searched_tags.add(")
    fetched = body.index("fetch_abstracts")
    screened = body.index("_screen_papers(")
    assert tagged < fetched < screened, (
        "the theme is recorded after fetching or screening, so the screen can "
        "shrink its own denominator")


def test_an_all_rejected_search_does_not_tell_the_agent_to_broaden():
    """A defect the screen introduced, caught before it shipped a second round.

    The tool's only signal for "nothing to show" was an empty list, and empty
    meant one thing before the screen: PubMed matched nothing, so the query is
    too narrow -- broaden it. With the screen, empty has a second and opposite
    cause: PubMed matched fine and every hit was rejected as keyword-only.
    Broadening there returns MORE marginal papers for the screen to reject, so
    the old advice spends budget making the problem worse.
    """
    src = inspect.getsource(L)
    i = src.index("if not listed and screened_here:")
    branch = src[i:src.index("elif not listed:", i)]
    # Assert on the ASSEMBLED message, not the source. A prompt written across
    # adjacent string literals contains no sentence contiguously -- "Broadening "
    # ends one literal and "will return..." starts the next -- so a substring
    # test against source fails on text that is perfectly correct at runtime.
    # This is the third time in one session that reading source instead of
    # building the value produced a wrong answer.
    assembled = re.sub(r'"\s*\n\s*"', "", branch)
    assert "Broadening will return more of the same" in assembled, assembled
    assert "probably too narrow" not in assembled, (
        "the all-rejected branch still gives the broaden-your-query advice")


def test_the_original_empty_message_survives_for_a_real_no_hit():
    """7 of 14 searches once came back genuinely empty from over-stacked AND
    clauses; that advice is still right when nothing matched."""
    src = inspect.getsource(L)
    i = src.index("elif not listed:")
    branch = src[i:i + 700]
    assert "probably too narrow" in branch and "Drop an AND clause" in branch


def test_a_partly_screened_search_says_how_many_were_dropped():
    """A query whose hits are mostly keyword-only is a query worth changing, and
    the agent cannot see that from a shortened list alone."""
    src = inspect.getsource(L)
    assert "further hit(s) were screened out as keyword-only" in src


def test_the_two_empty_causes_cannot_collapse_back_together():
    """screened_here must be initialised on every path, or an all-rejected search
    would fall through to the wrong branch whenever the screen is off."""
    src = inspect.getsource(L)
    i = src.index("async def search_literature(")
    body = src[i:src.index("@function_tool", i)]
    init = body.index("screened_here = 0")
    used = body.index("if not listed and screened_here:")
    assert init < used, "screened_here is used before it is set"


def _prompt_for(pool_size, n_pathways=15):
    """Build the screen's prompt against a real context of a given pool size."""
    captured = {}
    original = L.Runner

    class _Runner:
        @staticmethod
        async def run(agent, prompt, context=None, max_turns=None):
            captured["p"] = prompt
            return _Res(["1"])
    L.Runner = _Runner
    ctx = L.LoopContext(job_instance=None, job_id="T", organism_name="mmu",
                        experiment_design="d")
    ctx.pathways = [{"id": "p%d" % i} for i in range(n_pathways)]
    ctx.paper_index = {i: {"ref_index": i} for i in range(1, pool_size + 1)}
    try:
        asyncio.get_event_loop().run_until_complete(
            L._screen_papers(ctx, PAPERS, "q", "theme"))
    finally:
        L.Runner = original
    return captured["p"]


def test_the_standard_does_not_move_with_the_pool():
    """Round 40 measured what happens when it does.

    Making strictness depend on the pool -- permissive below half the target, on
    the reasoning that a thin paper beats an empty theme -- raised the keep rate
    24% -> 28-32% and barely moved the pool (27 -> 29), while failures went
    0.50 -> 3.33, redactions 1.2 -> 8.7 and coverage 16.2 -> 11.7 across three
    replicates.

    The bar is what makes a screened paper worth 0.91 citations. A thin paper does
    not beat an empty theme: it costs the sentence it lands on. Starvation is
    answered with more candidates, not a lower standard.
    """
    for pool in (2, 20, 60):
        p = _prompt_for(pool)
        assert "specific quotable finding" in p
        assert "thin paper beats an empty theme" not in p, (
            "the permissive stance is back at pool=%d" % pool)
        assert "keep ONLY what is clearly better" not in p


def test_the_pool_size_is_still_reported():
    """The screener should know where it stands even though the bar does not
    move -- the number is context, not permission."""
    p = _prompt_for(4)
    assert "hold 4 papers" in p and "about 35" in p, p


def test_the_target_is_not_the_delegation_window():
    """A correction to my own analysis, kept as a test so it cannot come back.

    I had the screen aiming at _writer_window() -- DELEGATE_PAPERS x chunks --
    on the reasoning that a paper no writer can be shown cannot be cited. Then
    delegate_markers came in at ZERO on all four of round 39's replicates: the
    delegated analyses cite nothing whatever. The Lead writes the citing draft
    and sees every paper through the search listings, so the delegation window
    has no say in how many citations a run can carry.

    The target now comes from the measured line, citations = 0.91 x papers - 7.2.
    """
    import inspect
    src = inspect.getsource(L._screen_papers)
    assert "SCREEN_TARGET_POOL" in src
    assert "_writer_window" not in src, (
        "the screen is aiming at the delegation window again")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_it_keeps_only_what_the_screen_named,
              test_an_explicit_empty_answer_keeps_nothing,
              test_a_BROKEN_screen_keeps_everything,
              test_a_pmid_the_screen_invented_is_ignored,
              test_no_papers_in_means_no_call_out,
              test_it_lives_inside_the_search_tool,
              test_the_screen_is_off_by_default_and_stamped,
              test_both_arms_screen_to_the_same_standard,
              test_the_screen_cannot_shrink_the_metrics_denominator,
              test_an_all_rejected_search_does_not_tell_the_agent_to_broaden,
              test_the_original_empty_message_survives_for_a_real_no_hit,
              test_a_partly_screened_search_says_how_many_were_dropped,
              test_the_two_empty_causes_cannot_collapse_back_together,
              test_the_standard_does_not_move_with_the_pool,
              test_the_pool_size_is_still_reported,
              test_the_target_is_not_the_delegation_window):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
