#!/usr/bin/env python3
"""A tool's bill is seconds AND characters, and only the seconds were counted.

Every character a tool returns enters the Lead's context and is re-sent on
EVERY later Decide turn, so a tool answering in 6 kB where 600 bytes would do
taxes the whole remainder of the investigation. The framework already meters
this -- TOOL_CHAR_BUDGET has been enforced since the first run, and the agent
is shown its own spend in the ledger note on every turn.

It was enforced and never recorded. 119 archived traces store a hand-written
summary of each result ("12 papers, 8 new", the matched pathway IDs) and never
its size, and no completed run carried the ledger total, so the question "which
tool ate the context" could not be asked of the archive at all.

    python -m src.tests.test_context_bill_is_itemised
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# `_trace` archives every tool call to CLIENT_TMP_DIR/ai_traces, which is the
# LIVE corpus every tool-usefulness figure in this project is computed from --
# including runs that came through the servlet, not just the benchmark. A test
# that writes there puts fabricated tool calls into that dataset, and the next
# analysis counts them. Four suites were doing it.
import tempfile as _tempfile
from src.conf import serverconf as _serverconf
_serverconf.CLIENT_TMP_DIR = _tempfile.mkdtemp(prefix="tracetest-")

from src.benchmarks.ai_arm_bench import STAGE_COUNTS, STAGE_MAPS, _stage_budget  # noqa: E402
from src.classes.AIInterpret import agent_loop as L  # noqa: E402

_PASSED, _FAILED = [], []


def _ctx():
    import time
    # The REAL context, never a stub: a hand-rolled object missing a field
    # turns a tool's AttributeError into its "tool failed" string, and an
    # assertion then passes on a result that never ran. That has happened here.
    return L.LoopContext(job_instance=None, job_id="T", organism_name="mmu",
                         experiment_design="", started_at=time.time(),
                         hard_deadline=time.time() + 600)


def test_a_tool_result_is_charged_to_that_tool():
    c = _ctx()
    L._spend(c, "x" * 300, "search_literature")
    L._spend(c, "y" * 120, "read_paper")
    assert c.tool_chars_by_tool == {"search_literature": 300, "read_paper": 120}
    assert c.tool_chars == 420, "the total and the breakdown disagree"


def test_repeat_calls_accumulate_against_the_same_tool():
    """A cheap tool called forty times is not a cheap tool."""
    c = _ctx()
    for _ in range(4):
        L._spend(c, "z" * 50, "get_pathway_details")
    assert c.tool_chars_by_tool["get_pathway_details"] == 200


def test_an_unattributed_result_still_counts_against_the_total():
    """Attribution is additive: a call site that forgets its name must not
    silently stop charging the budget the agent is shown."""
    c = _ctx()
    L._spend(c, "q" * 90)
    assert c.tool_chars == 90
    assert c.tool_chars_by_tool == {}


def test_the_budget_still_truncates():
    """The ledger is a guard first and a metric second; adding the metric must
    not disarm the guard."""
    c = _ctx()
    out = L._spend(c, "w" * (L.TOOL_CHAR_BUDGET + 5000), "search_literature")
    assert "TOOL BUDGET EXHAUSTED" in out
    assert len(out) < L.TOOL_CHAR_BUDGET + 5000


def test_every_spending_tool_names_itself():
    """An unnamed call site is a hole in the bill, and the holes are invisible:
    the total still adds up, so nothing looks wrong."""
    import inspect
    import re
    src = inspect.getsource(L)
    calls = re.findall(r"_spend\(c,.*?\)\n", src, re.S)
    unnamed = [c for c in calls if not re.search(r'"[a-z_]+"\)', c)]
    assert not unnamed, ("%d _spend call site(s) charge nothing to a tool: %s"
                         % (len(unnamed), [c[:70] for c in unnamed]))


def test_the_itemised_bill_reaches_the_archive():
    for key in ("tool_chars",):
        assert key in STAGE_COUNTS, "%s is not archived" % key
    assert "tool_chars_by_tool" in STAGE_MAPS
    row = _stage_budget({"tool_chars": 41000,
                         "tool_chars_by_tool": {"search_literature": 30000}})
    assert row["tool_chars"] == 41000
    assert row["tool_chars_by_tool"]["search_literature"] == 30000


def test_an_empty_bill_is_not_archived():
    """A run that spent nothing writes no key, so absent stays distinguishable
    from zero -- the same rule the top-up scorer follows."""
    assert "tool_chars_by_tool" not in _stage_budget({"tool_chars_by_tool": {}})


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_tool_result_is_charged_to_that_tool,
              test_repeat_calls_accumulate_against_the_same_tool,
              test_an_unattributed_result_still_counts_against_the_total,
              test_the_budget_still_truncates,
              test_every_spending_tool_names_itself,
              test_the_itemised_bill_reaches_the_archive,
              test_an_empty_bill_is_not_archived):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
