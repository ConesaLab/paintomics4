#!/usr/bin/env python3
"""The pre-registered rule must keep saying what it said before the data.

`judge()` decides whether the agent arm replaces the shipped workflow arm. It
was written before any arm ran, and the whole value of that is lost if it
quietly drifts -- a rule edited after seeing the numbers is not a rule. These
tests pin each of the five conditions, including the ones the agent arm has
been failing.

Also pins the prose cut, which is the metric that has already been wrong once:
counting a pathway as "covered" anywhere in the report let the agent arm score
102/102 by printing a table of pathway names it had not analysed.

    python -m src.tests.test_ai_arm_bench_rules
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import judge, prose_of  # noqa: E402

_PASSED, _FAILED = [], []


def _row(**kw):
    row = {"status": "done", "wall_s": 400.0, "citations_in_body": 20,
           "redacted": 4, "prose_pathways_covered": 15, "report_chars": 40000}
    row.update(kw)
    return row


def _verdict(agent, base=None):
    return judge(agent, base or [_row()])[1]


def test_a_matching_arm_passes_every_rule():
    assert _verdict([_row()]) is True, "an arm equal to base on every metric failed"


def test_a_replicate_over_the_ceiling_fails():
    assert _verdict([_row(wall_s=612.0)]) is False, "a 612 s run was accepted"


def test_an_errored_replicate_fails_even_if_the_others_are_good():
    assert _verdict([_row(), _row(status="error")]) is False, (
        "an errored replicate did not sink the round")


def test_fewer_citations_than_base_fails():
    """The rule the agent arm has failed in every round so far."""
    assert _verdict([_row(citations_in_body=18)]) is False


def test_two_extra_redactions_are_tolerated_three_are_not():
    assert _verdict([_row(redacted=6)]) is True, "base+2 redactions should pass"
    assert _verdict([_row(redacted=7)]) is False, "base+3 redactions should fail"


def test_less_coverage_than_base_fails():
    assert _verdict([_row(prose_pathways_covered=14)]) is False


def test_a_degenerate_report_fails_the_length_guard():
    assert _verdict([_row(report_chars=20000)]) is False, "0.5x base was accepted"
    assert _verdict([_row(report_chars=90000)]) is False, "2.25x base was accepted"
    assert _verdict([_row(report_chars=25000)]) is True, "0.625x base should pass"


def test_no_replicates_is_not_a_pass():
    assert _verdict([]) is False, "an empty arm must not be declared better"


def test_the_prose_cut_excludes_appended_tables():
    report = ("Real analysis of Glycolysis here.\n\n"
              "## Enriched Pathway Summary\n\n| Citrate cycle | 0.01 |\n"
              "### References\n\n[1] X.\n")
    prose = prose_of(report)
    assert "Real analysis" in prose
    assert "Citrate cycle" not in prose, (
        "the appended table is inside the prose cut; coverage will be inflated")
    assert "[1] X." not in prose


def test_the_prose_cut_takes_the_earliest_marker():
    report = "Analysis.\n## Pathway Clusters\ncluster rows\n### References\n[1] X."
    assert prose_of(report).strip() == "Analysis."


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_matching_arm_passes_every_rule,
              test_a_replicate_over_the_ceiling_fails,
              test_an_errored_replicate_fails_even_if_the_others_are_good,
              test_fewer_citations_than_base_fails,
              test_two_extra_redactions_are_tolerated_three_are_not,
              test_less_coverage_than_base_fails,
              test_a_degenerate_report_fails_the_length_guard,
              test_no_replicates_is_not_a_pass,
              test_the_prose_cut_excludes_appended_tables,
              test_the_prose_cut_takes_the_earliest_marker):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
