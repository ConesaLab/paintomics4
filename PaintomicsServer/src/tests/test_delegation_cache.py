#!/usr/bin/env python3
"""A delegation already run must not be run again.

delegate_interpretation is the agent's most expensive tool by an order of
magnitude -- a median 29.8 s per call against 0-4 ms for the data tools. Across
the 60 archived runs, 7 re-issued an identical delegation, costing 25-62 s each
(mean 40) out of a 600 s budget, for an answer the run was already holding.
Repeated delegations are 269 of the 271 seconds this agent spends re-answering
itself; every other tool is cheap enough that a repeat does not matter.

The cache is keyed on the RESOLVED pathway set rather than the argument
spelling, so the same pathways requested under a different name still hit, while
a different focus is a different question and runs.

    python -m src.tests.test_delegation_cache
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from agents import RunContextWrapper                      # noqa: E402
from src.classes.AIInterpret import agent_loop as L       # noqa: E402


def _isolate_trace_archive():
    """Keep test traces out of the real archive.

    _archive_trace writes every run to CLIENT_TMP/ai_traces, which is the corpus
    the tool-usage benchmark reads. Unit tests that drive real tools were writing
    there too -- five files, and six simulated faults that the analyzer then
    reported as a defect in get_experiment_overview.
    """
    import tempfile
    L._archive_trace = lambda ctx: None
    return tempfile.gettempdir()


_isolate_trace_archive()

_PASSED, _FAILED = [], []


def _context():
    c = L.LoopContext(job_instance=None, job_id="TEST0001",
                      organism_name="Mus musculus",
                      experiment_design="two conditions")
    # The shape build_batch_interpretation_prompt actually requires. Using a
    # thinner dict made every call fail with KeyError('source') inside the SDK,
    # which swallows tool exceptions into a plain string -- so the tests still
    # "passed" while exercising nothing.
    def _pw(pid, name):
        return {"id": pid, "name": name, "source": "KEGG",
                "combined_pvalue": 1e-4, "global_pvalue": 1e-3,
                "per_omic": {"Gene expression": 1e-4},
                "matched_gene_count": 2,
                "top_genes": [{"symbol": "Ikzf1", "relevant": True,
                               "effect_size": 2.4, "omic_profiles": []}],
                "top_metabolites": [], "genes": [], "metabolites": []}

    c.pathways = [_pw("mmu04110", "Cell cycle"),
                  _pw("mmu04151", "PI3K-Akt signaling"),
                  _pw("mmu00010", "Glycolysis")]
    c.started_at = time.time()
    c.hard_deadline = time.time() + 600
    return c


def _call(tool, ctx, **kwargs):
    """Invoke a @function_tool the way the SDK does.

    The SDK catches any exception a tool raises and hands the model the string
    "An error occurred while running the tool", so a broken fixture looks like a
    working one. Fail loudly instead.
    """
    out = asyncio.new_event_loop().run_until_complete(
        tool.on_invoke_tool(RunContextWrapper(context=ctx), json.dumps(kwargs)))
    assert "An error occurred while running the tool" not in str(out), (
        "the tool raised and the SDK swallowed it: %s" % str(out)[:200])
    return out


def _stub_single_shot(counter):
    async def _fake(agent, prompt, c, max_turns, label):
        counter.append(label)
        return "Interpretation of %s [1]." % label
    return _fake


def _with_stub(fn):
    """Run fn with the delegated model call replaced by a counter."""
    calls = []
    original = L._single_shot
    L._single_shot = _stub_single_shot(calls)
    try:
        return fn(calls)
    finally:
        L._single_shot = original


def test_an_identical_delegation_is_not_run_twice():
    def body(calls):
        c = _context()
        first = _call(L.delegate_interpretation, c,
                      pathway_names=["Cell cycle", "PI3K-Akt signaling"], focus="")
        second = _call(L.delegate_interpretation, c,
                       pathway_names=["Cell cycle", "PI3K-Akt signaling"], focus="")
        assert len(calls) == 1, (
            "the sub-agents ran %d times for one distinct delegation" % len(calls))
        assert "already delegated" in second, "the repeat was not told it is a repeat"
        assert "Interpretation of" in second, "the cached analysis was not returned"
        assert "Interpretation of" in first
    _with_stub(body)


def test_a_cache_hit_does_not_duplicate_the_delegated_text():
    """The gate stitches from c.delegated; a duplicate would pad the merge
    toward STITCH_MAX_CHARS and let one claim be counted twice."""
    def body(calls):
        c = _context()
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"], focus="")
        before = len(c.delegated)
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"], focus="")
        assert len(c.delegated) == before, (
            "cache hit appended the same interpretation again (%d -> %d)"
            % (before, len(c.delegated)))
    _with_stub(body)


def test_the_same_pathways_under_another_name_still_hit():
    """The key is the resolved pathway set, not the spelling the Lead used."""
    def body(calls):
        c = _context()
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"], focus="")
        out = _call(L.delegate_interpretation, c, pathway_names=["cell CYCLE"], focus="")
        assert len(calls) == 1, "a spelling variant re-ran the sub-agents"
        assert "already delegated" in out
    _with_stub(body)


def test_a_different_focus_is_a_different_question():
    def body(calls):
        c = _context()
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"],
              focus="metabolic angle")
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"],
              focus="regulatory angle")
        assert len(calls) == 2, "a genuinely different focus was served from cache"
    _with_stub(body)


def test_a_different_pathway_set_is_not_a_hit():
    def body(calls):
        c = _context()
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"], focus="")
        _call(L.delegate_interpretation, c, pathway_names=["Glycolysis"], focus="")
        assert len(calls) == 2, "a different pathway set was served from cache"
    _with_stub(body)


def test_the_cache_hit_is_visible_in_the_trace():
    """Otherwise the saving cannot be measured from the archive afterwards."""
    def body(calls):
        c = _context()
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"], focus="")
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"], focus="")
        hits = [e for e in c.trace if "cache" in str(e.get("result", ""))]
        assert hits, "no trace event records the cache hit: %r" % c.trace[-1:]
    _with_stub(body)


def test_a_cache_hit_is_fast():
    """The whole point is the 30 s it does not spend."""
    def body(calls):
        c = _context()
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"], focus="")
        t0 = time.time()
        _call(L.delegate_interpretation, c, pathway_names=["Cell cycle"], focus="")
        assert time.time() - t0 < 1.0, "a cache hit took over a second"
    _with_stub(body)


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_an_identical_delegation_is_not_run_twice,
              test_a_cache_hit_does_not_duplicate_the_delegated_text,
              test_the_same_pathways_under_another_name_still_hit,
              test_a_different_focus_is_a_different_question,
              test_a_different_pathway_set_is_not_a_hit,
              test_the_cache_hit_is_visible_in_the_trace,
              test_a_cache_hit_is_fast):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
