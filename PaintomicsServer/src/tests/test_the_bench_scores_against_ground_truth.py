#!/usr/bin/env python3
"""The benchmark must be able to ask whether the report is RIGHT.

The five pre-registered rules compare this arm to the incumbent on counts:
citations, redactions, coverage, length, wall clock. Not one asks whether the
report reached the published conclusions, and no number of replicates fixes that.
The cost was measurable: for a whole session the arm read as "nominally ahead,
not resolved" on my rules, while AgentEvolve's ground-truth rubric put it at
0.585 against base's 0.406 -- resolved, 44% ahead, zero fabrication.

The rubric is AgentEvolve's, sealed and hashed, derived from the published
PaintOmics 4 Results section (PMC9252773) for this exact STATegra job. It is
referenced rather than forked: the local JSON carries the original's sha256.

    python -m src.tests.test_the_bench_scores_against_ground_truth
"""
from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks import ai_arm_bench as B                 # noqa: E402

_PASSED, _FAILED = [], []
_BLOB = os.path.join(os.path.dirname(os.path.abspath(B.__file__)),
                     "stategra_rubric.json")


def test_the_local_copy_is_the_sealed_rubric():
    blob = json.load(open(_BLOB))
    assert blob["_sha256"] == B._RUBRIC_SHA, (
        "the local rubric is not the one AgentEvolve sealed")
    assert "agentevolve" in blob["_source"], blob["_source"]


def test_the_rubric_loads_and_has_its_sections():
    rubric, why = B._rubric()
    assert rubric is not None, "rubric did not load: %s" % why
    items = sum(len(s.get("items") or []) for s in rubric["sections"])
    assert len(rubric["sections"]) == 6 and items == 19, (
        "the rubric shape changed: %d sections, %d items"
        % (len(rubric["sections"]), items))


def test_a_report_that_says_nothing_scores_nothing():
    coverage, fabricated = B.rubric_score("A report with no findings at all.")
    assert coverage is not None, fabricated
    assert coverage < 0.2, coverage


def test_a_real_report_scores_and_does_not_fabricate():
    """The DIVERGENCE items are claims in the paper that this job cannot
    support; narrating one is fabrication. No archived report has."""
    scratch = os.path.expanduser(
        "/private/tmp/claude-501/-Users-tianyuan-Desktop-github-dev-paintomics4/"
        "7a5e32b9-9a1c-46ce-8cb4-998cc8ef1db8/scratchpad/round52/agent-v52-r1.report.md")
    if not os.path.exists(scratch):
        print("      (no archived report available; skipped)")
        return
    coverage, fabricated = B.rubric_score(open(scratch).read())
    assert coverage and coverage > 0.3, coverage
    assert fabricated == [], "fabrication detected: %s" % fabricated


def test_an_upstream_change_is_reported_not_scored_against():
    """A rubric edited upstream must stop the score, not silently shift it --
    every previous round was measured against the sealed text."""
    real = B._RUBRIC_SRC
    try:
        B._RUBRIC_SRC = __file__          # a file whose hash cannot match
        rubric, why = B._rubric()
        assert rubric is None and "changed upstream" in why, (rubric, why)
    finally:
        B._RUBRIC_SRC = real


def test_a_missing_scorer_never_takes_a_round_down():
    real = B._SCORER_DIR
    try:
        B._SCORER_DIR = "/nonexistent"
        for mod in [m for m in list(sys.modules) if m.startswith("score")]:
            del sys.modules[mod]
        coverage, why = B.rubric_score("text")
        # Either it still resolves the sibling via sys.path, or it fails soft.
        assert coverage is None or isinstance(coverage, float), (coverage, why)
    finally:
        B._SCORER_DIR = real


def test_it_is_not_a_sixth_rule():
    """The five are pre-registered. A rule added after seeing the numbers is not
    a rule, however much better the measure is."""
    rules, _ok = B.judge(
        [{"citations_in_body": 20, "redacted": 0, "prose_pathways_covered": 14,
          "report_chars": 50000, "wall_s": 300, "status": "done",
          "rubric_coverage": 0.9}],
        [{"citations_in_body": 18, "redacted": 4, "prose_pathways_covered": 13,
          "report_chars": 33000, "wall_s": 300, "status": "done",
          "rubric_coverage": 0.1}])
    assert len(rules) == 5, "the rule count changed: %d" % len(rules)
    assert not any("rubric" in lbl for lbl, _p, _d in rules)


def test_it_reaches_the_score_table():
    assert "rubric_coverage" in B.METRICS and "rubric_fabricated" in B.METRICS


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_local_copy_is_the_sealed_rubric,
              test_the_rubric_loads_and_has_its_sections,
              test_a_report_that_says_nothing_scores_nothing,
              test_a_real_report_scores_and_does_not_fabricate,
              test_an_upstream_change_is_reported_not_scored_against,
              test_a_missing_scorer_never_takes_a_round_down,
              test_it_is_not_a_sixth_rule,
              test_it_reaches_the_score_table):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
