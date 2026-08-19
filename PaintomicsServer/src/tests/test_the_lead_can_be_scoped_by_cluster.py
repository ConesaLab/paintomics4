#!/usr/bin/env python3
"""What limits the agent's coverage is its own prompt, not any constant.

The agent covers a median 16 pathways of the 102 it indexes. Every constant I
suspected turned out not to bind:

    DELEGATE_MAX_PATHWAYS   20, never reached (coverage 15-18)
    the tool's stated cap   raised to 60; the Lead still named 15
    SEARCH_BUDGET           40, about 15 used

The limiter is SYSTEM_PROMPT_LEAD_AGENT, which says "top-ranked" five times, and
"roughly a dozen searches" -- matching the observed 15.5 exactly. Cluster-mode
base has no rank scoping at all, covers 74, and scores 0.617 on the sealed rubric
against this arm's 0.538.

This pins the rescope: cluster-bounded instead of rank-bounded, with the structure
requirements untouched.

    python -m src.tests.test_the_lead_can_be_scoped_by_cluster
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402
from src.classes.AIInterpret import prompts as P             # noqa: E402

_PASSED, _FAILED = [], []


def _scoped():
    before = L.CLUSTER_SCOPE
    L.CLUSTER_SCOPE = True
    try:
        return L._lead_instructions()
    finally:
        L.CLUSTER_SCOPE = before


def test_the_default_is_byte_identical():
    """Every round measured so far ran the stock prompt."""
    assert L.CLUSTER_SCOPE is False
    assert L._lead_instructions() == P.SYSTEM_PROMPT_LEAD_AGENT


def test_the_rescope_replaces_rank_scoping_with_cluster_scoping():
    t = _scoped()
    assert "every CLUSTER is either analysed" in t
    assert "covering EVERY cluster" in t
    assert "top-ranked pathways" not in t, (
        "a rank-scoping clause survived: the Lead would still bound itself")


def test_the_search_count_is_raised_to_match_the_cluster_count():
    """'roughly a dozen searches' is the other half of the cap: a dozen searches
    cannot cover twenty clusters, so raising one without the other leaves
    delegated pathways with no literature to cite."""
    t = _scoped()
    assert "a dozen" not in t.split("Coverage checklist")[0] or "twenty searches" in t
    assert "twenty searches" in t


def test_the_structure_requirements_are_untouched():
    """Five sections and rank presentation are load-bearing -- AgentEvolve's round
    1 REVERTED a change that reordered the rank presentation (train -0.108)."""
    t = _scoped()
    assert "all five sections required" in t
    assert "## Key Findings" in t and "## Cross-Pathway Themes" in t


def test_a_rewrite_that_matches_nothing_is_reported():
    """If the upstream prompt is reworded, a silent no-match would leave the
    prompt rank-scoped while the fingerprint claimed a change."""
    src = open(L.__file__.replace(".pyc", ".py")).read()
    i = src.index("def _lead_instructions")
    body = src[i:i + 900]
    assert "logger.warning" in body and "rewrite missed" in body, body[-300:]


def test_the_fingerprint_and_the_stamp_see_the_rescope():
    """Two runs with different scopes must not average together."""
    src = open(L.__file__.replace(".pyc", ".py")).read()
    assert "_lead_instructions()]" in src, "the code fingerprint still hashes the stock prompt"
    assert '"lead_prompt_chars": len(_lead_instructions())' in src


def test_the_shipped_arm_is_untouched():
    """SYSTEM_PROMPT_LEAD_AGENT is the Lead's, and the Lead exists only here --
    but assert it, because a shared prompt would contaminate the control."""
    import src.classes.AIInterpret.agent as base
    assert "SYSTEM_PROMPT_LEAD_AGENT" not in open(base.__file__.replace(".pyc", ".py")).read()


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_default_is_byte_identical,
              test_the_rescope_replaces_rank_scoping_with_cluster_scoping,
              test_the_search_count_is_raised_to_match_the_cluster_count,
              test_the_structure_requirements_are_untouched,
              test_a_rewrite_that_matches_nothing_is_reported,
              test_the_fingerprint_and_the_stamp_see_the_rescope,
              test_the_shipped_arm_is_untouched):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
