#!/usr/bin/env python3
"""The agent's scope is significance; what it does inside that is its own call.

This replaces test_the_lead_can_be_scoped_by_cluster, whose flag is gone. The
history is worth keeping because it is three wrong answers in a row:

    DELEGATE_MAX_PATHWAYS   20, then 60 -- never reached (coverage 15-18)
    the tool's stated cap   raised to 60; the Lead still named 15
    SEARCH_BUDGET           40, about 15 used
    AI_AGENT_CLUSTER_SCOPE  round 67, 8 replicates: 15.4 -> 17.4 pathways,
                            rubric coverage 0.571 -> 0.611, wall 422 -> 420 s

Every one of those treated the problem as "the agent is allowed too little" and
every one of them missed, because the agent was never TOLD about the rest of the
experiment. It was handed the top fifteen by p-value and widened to the
significant set only if it happened to call cluster_pathways. A choice needs
options in view; ranking had already made the choice upstream.

So: significance decides membership, the prompt no longer scopes by rank, and
the caps that remain must announce themselves rather than truncate in silence.

    python -m src.tests.test_the_agent_chooses_within_significance
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402
from src.classes.AIInterpret import prompts as P             # noqa: E402

_PASSED, _FAILED = [], []


# --------------------------------------------------------------- the prompt

def test_the_lead_prompt_no_longer_scopes_by_rank():
    """"top-ranked" appeared five times and was the whole limiter."""
    t = L._lead_instructions()
    assert "top-ranked" not in t, (
        "the Lead is rank-scoped again: %s"
        % [ln for ln in t.split("\n") if "top-ranked" in ln][:3])


def test_the_prompt_is_one_source_with_no_rewrites():
    """CLUSTER_SCOPE rewrote the shipped prompt at import time, so what a run
    actually obeyed could not be read off prompts.py. It is folded in now."""
    assert L._lead_instructions() == P.SYSTEM_PROMPT_LEAD_AGENT
    assert not hasattr(L, "CLUSTER_SCOPE"), (
        "the dead flag is back; its content belongs in the prompt")
    assert not hasattr(L, "_SCOPE_REWRITES")


def test_the_prompt_points_the_agent_at_the_design():
    """The one input that says which significant pathways are the POINT of the
    experiment. It was in the context and steered nothing."""
    t = L._lead_instructions()
    assert "EXPERIMENT \\\ndesign" in t or "EXPERIMENT DESIGN" in t.replace("\\\n", ""), t[:400]


def test_setting_a_pathway_aside_is_an_allowed_answer():
    """Coverage measured by "did you name it" rewards padding unless declining
    is explicitly on the table."""
    t = L._lead_instructions().replace("\\\n", " ")
    assert "set it aside" in t or "set aside" in t, t[:400]
    assert "silence" in t, "declining must be distinguished from omission"


def test_the_structure_requirements_are_untouched():
    """The rescope must not quietly change what a report contains."""
    t = L._lead_instructions()
    for heading in ("## Key Findings", "## Cross-Pathway Themes",
                    "## Detailed Pathway Analysis",
                    "## Suggested Follow-up Experiments",
                    "## Limitations and Caveats"):
        assert heading in t, "lost the %s requirement" % heading


# ------------------------------------------------------------- the universe

class _FakePw(object):
    def __init__(self, pid, name):
        self.ID, self.name, self.source = pid, name, "KEGG"
        self.matchedGenes, self.matchedCompounds = [], []
        self.significanceValues = {}


def test_the_universe_is_the_significant_set_not_the_top_n():
    """The regression this whole change exists to prevent: an agent handed
    fifteen rows cannot decide anything about the other ninety."""
    seen = {}

    class _Clusters(object):
        @staticmethod
        def select_network_nodes(job):
            return [(str(i), _FakePw(str(i), "PW%d" % i)) for i in range(90)]

    def _fake_ctx(job, max_pathways=None, pathway_ids=None):
        seen["max_pathways"] = max_pathways
        seen["ids"] = list(pathway_ids or [])
        return [{"id": p, "name": "PW" + p} for p in (pathway_ids or [])]

    old_c, old_b = L.clusters_mod, L.build_pathway_context
    try:
        L.clusters_mod, L.build_pathway_context = _Clusters, _fake_ctx
        stats = {}
        out = L._significant_universe(object(), {"max_pathways": 15}, stats)
    finally:
        L.clusters_mod, L.build_pathway_context = old_c, old_b
    assert len(out) == 90, "universe is %d, not the 90 significant" % len(out)
    assert seen["max_pathways"] is None, "still capped at a top-N"
    assert stats["universe_source"] == "significant"
    assert stats["universe_pathways"] == 90


def test_an_empty_significant_set_falls_back_rather_than_shipping_nothing():
    """No pathway under 0.05 is a real job, not an error. Fifteen weak rows can
    still be written about honestly; zero rows cannot."""
    class _Clusters(object):
        @staticmethod
        def select_network_nodes(job):
            return []

    def _fake_ctx(job, max_pathways=None, pathway_ids=None):
        return [{"id": str(i), "name": "PW%d" % i} for i in range(max_pathways or 0)]

    old_c, old_b = L.clusters_mod, L.build_pathway_context
    try:
        L.clusters_mod, L.build_pathway_context = _Clusters, _fake_ctx
        stats = {}
        out = L._significant_universe(object(), {"max_pathways": 15}, stats)
    finally:
        L.clusters_mod, L.build_pathway_context = old_c, old_b
    assert len(out) == 15
    assert stats["universe_source"] == "top_p_fallback"


def test_a_broken_selector_does_not_take_the_run_down_with_it():
    """select_network_nodes reads a network file off disk."""
    class _Clusters(object):
        @staticmethod
        def select_network_nodes(job):
            raise IOError("pathways_network.json missing")

    def _fake_ctx(job, max_pathways=None, pathway_ids=None):
        return [{"id": str(i)} for i in range(max_pathways or 0)]

    old_c, old_b = L.clusters_mod, L.build_pathway_context
    try:
        L.clusters_mod, L.build_pathway_context = _Clusters, _fake_ctx
        stats = {}
        out = L._significant_universe(object(), {"max_pathways": 15}, stats)
    finally:
        L.clusters_mod, L.build_pathway_context = old_c, old_b
    assert len(out) == 15 and stats["universe_source"] == "top_p_fallback"


# ------------------------------------------------------------- the kickoff

def test_the_kickoff_states_the_size_and_the_rule_instead_of_a_ranking():
    """A numbered list of the top fifteen taught the agent that fifteen was the
    experiment; a numbered list of 150 would teach it to march down a ranking."""
    pathways = [{"name": "PW%d" % i, "id": str(i), "source": "KEGG",
                 "combined_pvalue": 0.001, "significant_omic_count": 2,
                 "matched_gene_count": 9} for i in range(114)]
    text = P.build_lead_kickoff_prompt("Mus musculus", "Ikaros time course",
                                       pathways, 40, 40, 600)
    assert "114 pathways reached significance" in text, text[:400]
    assert "no quota" in text, text[:400]
    assert "PW113" not in text, "the kickoff is enumerating the universe again"
    assert "Ikaros time course" in text, "the design must survive"


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_lead_prompt_no_longer_scopes_by_rank,
              test_the_prompt_is_one_source_with_no_rewrites,
              test_the_prompt_points_the_agent_at_the_design,
              test_setting_a_pathway_aside_is_an_allowed_answer,
              test_the_structure_requirements_are_untouched,
              test_the_universe_is_the_significant_set_not_the_top_n,
              test_an_empty_significant_set_falls_back_rather_than_shipping_nothing,
              test_a_broken_selector_does_not_take_the_run_down_with_it,
              test_the_kickoff_states_the_size_and_the_rule_instead_of_a_ranking):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
