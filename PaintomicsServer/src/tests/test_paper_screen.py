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
              test_both_arms_screen_to_the_same_standard):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
