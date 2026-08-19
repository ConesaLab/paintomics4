#!/usr/bin/env python3
"""search_literature is 60% of the tool calls and 12% of them reach the report.

Measured on round 34's agent replicates: 126 papers retrieved to cite 15, and
91 retrieved to cite 14, against a base arm that retrieves ~35 and cites ~24 on
the SAME job. Earlier measurement already cleared the obvious suspects --
novelty is 99.9% (the searches are not repeats), and the ~400-char listing per
paper puts a whole run around 50 kB against a 400 kB tool-output ceiling, so
neither duplication nor the character budget explains it.

What is left is conversion, and conversion has a natural unit: every search
carries a topic_tag naming the theme it supports, and that tag rides on every
paper it registers. The tags surviving on the CITED papers therefore say which
searches reached the report and which only spent budget -- the difference
between "the agent over-searches" and "the agent searches themes it never
writes about", which call for opposite fixes.

    python -m src.tests.test_search_themes_convert
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS, _stage_budget  # noqa: E402
from src.classes.AIInterpret.agent_loop import _theme_conversion  # noqa: E402

_PASSED, _FAILED = [], []


def test_a_theme_that_reached_the_references_counts():
    searched, converted = _theme_conversion(
        {"glycolysis", "tca cycle"}, [{"pathways": ["glycolysis"]}])
    assert (searched, converted) == (2, 1)


def test_a_theme_searched_but_never_cited_is_the_waste_being_measured():
    """Two searches, one report mention: the other search spent 2 s and ~4 kB
    of context for nothing, and that is the number worth knowing."""
    searched, converted = _theme_conversion(
        {"glycolysis", "tca cycle"}, [{"pathways": ["glycolysis"]}])
    assert searched - converted == 1


def test_tags_are_matched_the_way_the_search_tool_stores_them():
    """search_literature does str(topic_tag).strip().lower(); the tag on the
    paper is whatever the Lead typed. Matching them raw would report near-zero
    conversion for a run that converted fine."""
    searched, converted = _theme_conversion(
        {"b cell differentiation"}, [{"pathways": ["  B Cell Differentiation "]}])
    assert converted == 1, "case and whitespace broke the match"


def test_one_theme_cited_many_times_still_counts_once():
    """The unit is the search, not the citation -- otherwise a single popular
    theme hides every barren one."""
    searched, converted = _theme_conversion(
        {"glycolysis"}, [{"pathways": ["glycolysis"]}] * 6)
    assert converted == 1


def test_papers_carrying_no_tag_vote_for_nothing():
    """Papers can arrive untagged; they must not crash the count or inflate it."""
    searched, converted = _theme_conversion(
        {"glycolysis"}, [{"pathways": []}, {}, {"pathways": [""]}, {"pathways": None}])
    assert (searched, converted) == (1, 0)


def test_a_cited_tag_nobody_searched_for_is_not_credited():
    """Delegation and the top-up can leave tags behind; only searched themes
    are being scored, or the metric stops measuring searches."""
    searched, converted = _theme_conversion(
        {"glycolysis"}, [{"pathways": ["apoptosis"]}])
    assert converted == 0


def test_a_run_that_searched_nothing_is_not_a_division_by_zero():
    assert _theme_conversion(set(), []) == (0, 0)
    assert _theme_conversion(None, None) == (0, 0)


def test_both_numbers_reach_the_archive():
    for key in ("tags_searched", "tags_with_a_cited_paper"):
        assert key in STAGE_COUNTS, "%s is not archived" % key
    row = _stage_budget({"tags_searched": 14, "tags_with_a_cited_paper": 9})
    assert row["tags_searched"] == 14 and row["tags_with_a_cited_paper"] == 9


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_theme_that_reached_the_references_counts,
              test_a_theme_searched_but_never_cited_is_the_waste_being_measured,
              test_tags_are_matched_the_way_the_search_tool_stores_them,
              test_one_theme_cited_many_times_still_counts_once,
              test_papers_carrying_no_tag_vote_for_nothing,
              test_a_cited_tag_nobody_searched_for_is_not_credited,
              test_a_run_that_searched_nothing_is_not_a_division_by_zero,
              test_both_numbers_reach_the_archive):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
