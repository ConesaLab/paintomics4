#!/usr/bin/env python3
"""Both arms must say where their citations are BORN, not only how many shipped.

Base has counted this for rounds: `batch_citations`, `batches_with_citations`,
`synth_citations`, added because -- in the counter's own words -- "whether the
batches never cited, or the synthesis dropped citations the batches had supplied"
are "two different bugs that look the same from the outside".

Reading them for the first time (INFO logging only started reaching the round log
recently) gave the same line four times across rounds 37 and 38: **3 batches, 0
citing, 0 distinct markers**. Base's interpretation batches cite NOTHING, and a
run that ships 17-24 citations gets all of them later. That falsifies the premise
DELEGATE_CHUNK's docstring rests on -- "the shipped arm writes fourteen batches,
each citing its own papers" -- and with it the planned chunk-count experiment.

The agent arm had no equivalent counter at all, so the same question could not
even be asked of it. It does now: how many papers its delegated writers were
shown, and how many distinct [N] they wrote.

    python -m src.tests.test_where_citations_are_born
"""
from __future__ import annotations

import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS, _stage_budget  # noqa: E402
from src.classes.AIInterpret import agent_loop as L  # noqa: E402

_PASSED, _FAILED = [], []


def test_both_arms_now_report_where_citations_are_born():
    for key in ("batch_citations", "batches_with_citations", "synth_citations",
                "delegate_markers", "delegate_papers_shown"):
        assert key in STAGE_COUNTS, "%s is not archived" % key


def test_the_counters_survive_the_tool_call():
    """delegate_interpretation returns before stats are written, so the count
    has to live on the run context, not in the tool's locals."""
    from dataclasses import fields
    names = {f.name for f in fields(L.LoopContext)}
    assert "delegate_markers" in names
    assert "delegate_attribution" in names


def test_markers_are_counted_distinctly_not_by_occurrence():
    """A writer citing [3] eleven times has produced one citation, not eleven --
    counting occurrences would make a repetitive writer look prolific."""
    reports = ["a [3] b [3] c [3]", "d [7]"]
    distinct = len({m for r in reports for m in re.findall(r"\[(\d+)\]", r)})
    assert distinct == 2


def test_the_count_is_wired_where_the_reports_land():
    import inspect
    src = inspect.getsource(L)
    i = src.index("c.delegated.extend(")
    window = src[i:i + 700]
    assert "c.delegate_markers" in window, (
        "the markers are not counted where the delegated reports arrive")


def test_papers_shown_is_counted_on_both_attribution_paths():
    """A chunk that fell back to the most-recent papers was still SHOWN papers;
    counting only the matched path would under-report what writers saw."""
    import inspect
    src = inspect.getsource(L)
    i = src.index('tally["papers_shown"]')
    window = src[i:i + 200]
    assert "if hits else" in window, (
        "papers_shown ignores the fallback path, so it undercounts")


def test_the_pair_makes_a_conversion_rate_computable():
    """The point of the pair: markers alone cannot say whether a writer used what
    it was given."""
    row = _stage_budget({"delegate_papers_shown": 30, "delegate_markers": 11})
    assert row["delegate_papers_shown"] == 30 and row["delegate_markers"] == 11
    assert row["delegate_markers"] / row["delegate_papers_shown"] < 1.0


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_both_arms_now_report_where_citations_are_born,
              test_the_counters_survive_the_tool_call,
              test_markers_are_counted_distinctly_not_by_occurrence,
              test_the_count_is_wired_where_the_reports_land,
              test_papers_shown_is_counted_on_both_attribution_paths,
              test_the_pair_makes_a_conversion_rate_computable):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
