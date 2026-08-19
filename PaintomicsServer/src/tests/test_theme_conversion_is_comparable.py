#!/usr/bin/env python3
"""One retrieval measure both arms report on the same denominator.

The agent arm retrieves ~3x more literature than base and cites less of it: a
median 75 papers to cite 13 (14.9%) against base's 32 to cite 19 (61.7%). Round
35's new per-theme figure localised the loss inside the agent arm -- 8 of 15
searched themes put a paper in the references, stable at 8/15 and 8/14 across
two different jobs -- but base reported None, so there was nothing to compare
it to and no way to say whether 8/15 is bad or simply what this work looks like.

The agent arm's `tags_searched` cannot be that shared measure: it counts every
search including the barren ones, which is arm-specific. Both arms DO tag every
paper with the theme its search was run for, so themes-that-brought-literature-
back is computable identically on either side.

    python -m src.tests.test_theme_conversion_is_comparable
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS, _stage_budget  # noqa: E402
from src.classes.AIInterpret.verification import theme_conversion as tc  # noqa: E402

_PASSED, _FAILED = [], []


def _p(*tags):
    return {"pathways": list(tags)}


def test_the_unit_is_the_theme_not_the_paper():
    """Six papers on one theme is one theme, or a popular theme hides the
    barren ones -- which is the entire failure being measured."""
    assert tc([_p("glycolysis")] * 6, [_p("glycolysis")] * 3) == (1, 1)


def test_a_theme_that_brought_papers_but_no_citation_is_the_loss():
    got, cited = tc([_p("glycolysis"), _p("tca cycle")], [_p("glycolysis")])
    assert (got, cited) == (2, 1)


def test_tags_are_normalised_the_way_both_arms_store_them():
    """The agent arm lowercases its topic_tags; the base arm carries pathway
    names verbatim. Matching raw would report near-zero conversion for base."""
    assert tc([_p("B Cell Differentiation")], [_p(" b cell differentiation ")]) == (1, 1)


def test_a_cited_theme_that_was_never_retrieved_is_not_credited():
    """Delegation and the top-up can leave tags behind; the denominator is
    retrieval, so a theme outside it cannot raise the numerator above it."""
    got, cited = tc([_p("glycolysis")], [_p("apoptosis")])
    assert cited == 0 and cited <= got


def test_untagged_papers_do_not_count_either_way():
    assert tc([{"pathways": []}, {}, _p("")], [{}]) == (0, 0)


def test_empty_inputs_are_safe():
    assert tc([], []) == (0, 0)
    assert tc(None, None) == (0, 0)


def test_both_arms_compute_it():
    """A measure only one arm reports is the problem this replaces."""
    from src.classes.AIInterpret import agent_loop
    for module in (agent_loop,):
        src = inspect.getsource(module)
        assert "theme_conversion(retrieved_all, unique_papers)" in src, (
            "%s does not compute the shared theme measure" % module.__name__)


def test_it_reaches_the_archive():
    for key in ("themes_retrieved", "themes_cited"):
        assert key in STAGE_COUNTS, "%s is not archived" % key
    row = _stage_budget({"themes_retrieved": 15, "themes_cited": 8})
    assert row["themes_retrieved"] == 15 and row["themes_cited"] == 8


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_unit_is_the_theme_not_the_paper,
              test_a_theme_that_brought_papers_but_no_citation_is_the_loss,
              test_tags_are_normalised_the_way_both_arms_store_them,
              test_a_cited_theme_that_was_never_retrieved_is_not_credited,
              test_untagged_papers_do_not_count_either_way,
              test_empty_inputs_are_safe,
              test_both_arms_compute_it,
              test_it_reaches_the_archive):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
