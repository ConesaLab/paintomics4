#!/usr/bin/env python3
"""A tool's context bill must be readable per call, not only per run.

`tool_chars_by_tool` says get_pathway_details cost 48 116 characters. That
number cannot distinguish two opposite situations:

    chatty   -- three calls returning 16 kB each; the fix is a smaller payload
    popular  -- thirty calls returning 1.6 kB each; there is nothing to fix,
                the agent keeps choosing it because it answers

Both read as "30% of the bill". Counting calls beside characters is what makes
cost-per-call fall out of the archive, and cost-per-call is the number that
decides whether a tool needs rebuilding or leaving alone.

The call counts also had to be joinable to the run that produced them. 177
archived traces share two job IDs -- a benchmark replicate reuses the job -- so
matching a stats record to its trace meant guessing by file mtime, which is
how an earlier verification in this project reached a wrong answer.

    python -m src.tests.test_tool_cost_is_per_call
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402
from src.benchmarks import ai_arm_bench as B                 # noqa: E402
from src.conf import serverconf                              # noqa: E402

# `_trace` archives to CLIENT_TMP_DIR/ai_traces, which is the LIVE corpus every
# tool-usefulness figure in this project is computed from. The first version of
# this file wrote three fake runs into it, and the very next analysis -- "which
# tool is really useful" over 180 archived traces -- would have counted them.
# A test that measures instrumentation must not appear in the measurements.
serverconf.CLIENT_TMP_DIR = tempfile.mkdtemp(prefix="tracetest-")

_PASSED, _FAILED = [], []


def _ctx():
    """The REAL dataclass. A stub here would agree with whatever I assumed."""
    return L.LoopContext(job_instance=None, job_id="COSTPROBE",
                         organism_name="mmu", experiment_design="")


def test_calls_are_counted_per_tool():
    c = _ctx()
    c.started_at = time.time()
    for _ in range(3):
        L._trace(c, "get_pathway_details", "p", "ok", time.time())
    L._trace(c, "read_paper", "1", "ok", time.time())
    assert c.tool_calls_by_tool == {"get_pathway_details": 3, "read_paper": 1}, (
        "per-tool call counts are wrong: %r" % (c.tool_calls_by_tool,))


def test_a_failed_call_still_counts():
    """A raise spent a turn and a model round-trip. Hiding it would flatter
    exactly the tools that are hardest to call correctly."""
    c = _ctx()
    c.started_at = time.time()
    L._trace(c, "compare_gene_profiles", "(raised)", "ERROR KeyError", time.time())
    assert c.tool_calls_by_tool.get("compare_gene_profiles") == 1, (
        "a failed call vanished from the per-tool counts: %r"
        % (c.tool_calls_by_tool,))


def test_gate_calls_are_not_counted_as_toolbelt_calls():
    """`_trace_gate` exists so verifier spend never contaminates the toolbelt
    numbers that every round so far has been compared on."""
    c = _ctx()
    c.started_at = time.time()
    L._trace_gate(c, "verify_citation", "ref 3", "ok", time.time())
    assert c.tool_calls_by_tool == {}, (
        "a gate call landed in the toolbelt counts: %r" % (c.tool_calls_by_tool,))


def test_cost_per_call_is_derivable():
    """The point of the whole change, stated as the sum it enables."""
    c = _ctx()
    c.started_at = time.time()
    L._spend(c, "x" * 900, "get_pathway_details")
    L._trace(c, "get_pathway_details", "p", "ok", time.time())
    L._spend(c, "x" * 100, "get_pathway_details")
    L._trace(c, "get_pathway_details", "p", "ok", time.time())
    chars = c.tool_chars_by_tool["get_pathway_details"]
    calls = c.tool_calls_by_tool["get_pathway_details"]
    assert chars / calls == 500, "cost per call came out %r" % (chars / calls)


def test_the_stats_write_matches_the_real_context():
    """Pins the CALL SITE, not my idea of it: every attribute the archiving
    lines read must exist on the dataclass the loop actually builds."""
    c = _ctx()
    src = open(L.__file__.replace(".pyc", ".py")).read()
    for attr in ("tool_chars", "tool_chars_by_tool", "tool_calls_by_tool",
                 "trace_path"):
        assert 'ctx.%s' % attr in src, "%s is never read when archiving" % attr
        assert hasattr(c, attr), (
            "the loop archives ctx.%s but LoopContext has no such field" % attr)


def test_the_bench_keeps_them():
    """Measuring into the void is the failure this project has hit twice."""
    left = B.unarchived_stats({"tool_calls_by_tool": {"a": 1},
                               "trace_file": "/tmp/x.jsonl"})
    assert left == [], "the bench would drop: %r" % left


def test_a_run_names_its_own_trace_file():
    c = _ctx()
    c.started_at = time.time()
    L._trace(c, "read_paper", "1", "ok", time.time())
    assert c.trace_path.endswith(".jsonl"), (
        "the run cannot say which trace file is its own: %r" % c.trace_path)
    assert "COSTPROBE" in c.trace_path


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_calls_are_counted_per_tool,
              test_a_failed_call_still_counts,
              test_gate_calls_are_not_counted_as_toolbelt_calls,
              test_cost_per_call_is_derivable,
              test_the_stats_write_matches_the_real_context,
              test_the_bench_keeps_them,
              test_a_run_names_its_own_trace_file):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
