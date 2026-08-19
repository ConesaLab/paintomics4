#!/usr/bin/env python3
"""The tool-value report must be computed, not remembered.

"Which tool is really useful" has been answered from whichever single trace
happened to survive on disk, while `_archive_trace` was quietly keeping every
run. This pins the analyzer that reads the whole archive: era filtering (a
retired design must not go on voting), the never-called row that makes a tool a
removal candidate, and the fact that a truncated file cannot take the report
down with it.

    python -m src.tests.test_tool_value_reads_the_archive
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.conf import serverconf                              # noqa: E402

serverconf.CLIENT_TMP_DIR = tempfile.mkdtemp(prefix="toolvalue-")

from src.benchmarks import tool_value as V                   # noqa: E402

_PASSED, _FAILED = [], []
_DIR = os.path.join(serverconf.CLIENT_TMP_DIR, "ai_traces")


def _write(name, tools, outcome=None, raw=None):
    os.makedirs(_DIR, exist_ok=True)
    path = os.path.join(_DIR, name)
    with open(path, "w") as fh:
        if raw is not None:
            fh.write(raw)
            return path
        for i, (tool, result) in enumerate(tools):
            fh.write(json.dumps({"seq": i, "t": float(i), "tool": tool,
                                 "args": "", "result": result, "ms": 10}) + "\n")
        if outcome is not None:
            fh.write(json.dumps({"seq": 99, "gate": True, "tool": "__outcome__",
                                 "result": json.dumps(outcome), "ms": 0}) + "\n")
    return path


def _clear():
    for f in os.listdir(_DIR) if os.path.isdir(_DIR) else []:
        os.remove(os.path.join(_DIR, f))


def test_runs_from_a_retired_design_are_excluded():
    """A trace without the era marker describes a different agent."""
    _clear()
    _write("OLD-1.jsonl", [("search_literature", "ok"), ("submit_report", "ok")])
    _write("NEW-2.jsonl", [("delegate_interpretation", "ok"), ("submit_report", "ok")])
    runs = V.load_runs(limit=40)
    assert len(runs) == 1 and runs[0][0] == "NEW-2.jsonl", (
        "era filtering let a retired design vote: %r" % [r[0] for r in runs])


def test_a_never_called_tool_is_visible_as_zero():
    """The row that makes a tool a removal candidate. A tool nobody calls still
    ships its schema in every Decide turn, so 'used in 0 runs' has to be
    printable rather than simply absent from the table."""
    _clear()
    _write("A-1.jsonl", [("delegate_interpretation", "ok"), ("read_paper", "ok")])
    _write("A-2.jsonl", [("delegate_interpretation", "ok")])
    rows = {r["tool"]: r for r in V.adoption(V.load_runs())}
    assert rows["read_paper"]["runs"] == 1, rows["read_paper"]
    assert rows["delegate_interpretation"]["runs"] == 2


def test_failures_are_counted_separately_from_calls():
    _clear()
    _write("B-1.jsonl", [("delegate_interpretation", "ok"),
                         ("get_pathway_details", "ERROR KeyError: 'x'")])
    rows = {r["tool"]: r for r in V.adoption(V.load_runs())}
    assert rows["get_pathway_details"]["failures"] == 1, rows["get_pathway_details"]


def test_a_truncated_trace_does_not_take_the_report_down():
    """Traces are appended while a run is in flight, so the newest file on disk
    is routinely half-written. Analysis reads the archive; it must never be the
    reason a round's data is unreadable."""
    _clear()
    _write("C-1.jsonl", [("delegate_interpretation", "ok")],
           outcome={"citations": 10, "papers_retrieved": 20, "papers": 5,
                    "redacted": 0, "seconds": 300})
    _write("C-2.jsonl", None, raw='{"seq": 1, "tool": "delegate_inter')
    runs = V.load_runs()
    assert len(runs) == 1, "a half-written file was not skipped: %r" % [r[0] for r in runs]
    assert "Retrieval" in V.report(runs)


def test_a_run_with_no_outcome_stamp_still_counts_for_adoption():
    """Adoption comes from the trace; only the value table needs an outcome."""
    _clear()
    _write("D-1.jsonl", [("delegate_interpretation", "ok"), ("read_paper", "ok")])
    runs = V.load_runs()
    assert len(runs) == 1
    assert V.retrieval_value(runs) == [], "an outcome was invented from nothing"
    assert {r["tool"] for r in V.adoption(runs)} == {"delegate_interpretation",
                                                     "read_paper"}


def test_the_report_says_when_nothing_can_be_valued():
    _clear()
    _write("E-1.jsonl", [("delegate_interpretation", "ok")])
    text = V.report(V.load_runs())
    assert "nothing to value" in text, text


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_runs_from_a_retired_design_are_excluded,
              test_a_never_called_tool_is_visible_as_zero,
              test_failures_are_counted_separately_from_calls,
              test_a_truncated_trace_does_not_take_the_report_down,
              test_a_run_with_no_outcome_stamp_still_counts_for_adoption,
              test_the_report_says_when_nothing_can_be_valued):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
