#!/usr/bin/env python3
"""The agent's main data tool showed three unlabelled omics layers per gene.

`get_pathway_details` is the largest single consumer of the Lead's context: 33.7%
of the per-tool character bill over seven runs, 56 kB a run from a median of two
calls. Reading it closely for that reason turned up a plain defect --
context_builder emits `omic_name`, `_pathway_block` read `omic`, and so every
gene line was:

    - Ccr2* [effect 7.69] None: -0.42@0h, ...; None: ...; None: ...

Three profiles per gene with no way to tell transcript from miRNA from
metabolite, in a MULTI-OMICS interpreter whose whole job is relating layers.
Nothing failed, no exception, no warning: the tool returned a well-formed 46 kB
answer that was missing the one label that makes it multi-omics.

Measured composition of that answer, on a real job: gene lines 94% of the block,
raw temporal values 66%, pathway p-values 6%. The values earn their place -- the
`pattern` labels disagree with them often enough not to be trusted alone
('monotonic-up' for 0.11, -0.34, 0.07, 0.27...) -- so the fix is to label the
layers, not to trim the numbers.

    python -m src.tests.test_pathway_block_names_its_omics
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.agent_loop import _pathway_block  # noqa: E402

_PASSED, _FAILED = [], []


def _pathway(profiles):
    return {"name": "B cell receptor signaling", "id": "mmu04662",
            "source": "KEGG", "combined_pvalue": 0.001, "global_pvalue": 0.002,
            "significant_omic_count": 2,
            "top_genes": [{"symbol": "Ccr2", "relevant": True,
                           "effect_size": 7.69, "omic_profiles": profiles}]}


def test_the_layer_is_named():
    block = _pathway_block(_pathway([
        {"omic_name": "Gene expression", "values": "-0.4@0h", "pattern": "down"}]))
    assert "Gene expression: -0.4@0h" in block, block


def test_no_gene_line_says_none():
    """The exact symptom: a well-formed answer with the meaning missing."""
    block = _pathway_block(_pathway([
        {"omic_name": "miRNA-seq", "values": "0.1@0h", "pattern": "up"}]))
    for line in block.split("\n"):
        if line.startswith("- "):
            assert "None:" not in line, line


def test_several_layers_stay_distinguishable():
    """Relating layers is the product; two profiles that read identically are
    indistinguishable evidence."""
    block = _pathway_block(_pathway([
        {"omic_name": "Gene expression", "values": "1@0h", "pattern": "up"},
        {"omic_name": "Proteomics", "values": "2@0h", "pattern": "up"}]))
    assert "Gene expression: 1@0h" in block and "Proteomics: 2@0h" in block


def test_a_legacy_omic_key_still_works():
    """Older cached contexts used `omic`; they must not regress to unlabelled."""
    block = _pathway_block(_pathway([
        {"omic": "Metabolomics", "values": "3@0h", "pattern": "flat"}]))
    assert "Metabolomics: 3@0h" in block


def test_an_unlabelled_profile_says_so_rather_than_none():
    """If neither key is present the agent should see a visible gap, not a
    plausible-looking label."""
    block = _pathway_block(_pathway([{"values": "4@0h", "pattern": "up"}]))
    assert "omic?: 4@0h" in block, block


def test_the_pathway_pvalues_survive():
    """Only 6% of the block, and the part the prompt requires be quoted exactly."""
    block = _pathway_block(_pathway([
        {"omic_name": "Gene expression", "values": "1@0h", "pattern": "up"}]))
    assert "Combined p=0.001" in block and "global p=0.002" in block


def test_a_gene_with_no_profiles_does_not_break_the_block():
    block = _pathway_block(_pathway([]))
    assert "Ccr2" in block


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_layer_is_named,
              test_no_gene_line_says_none,
              test_several_layers_stay_distinguishable,
              test_a_legacy_omic_key_still_works,
              test_an_unlabelled_profile_says_so_rather_than_none,
              test_the_pathway_pvalues_survive,
              test_a_gene_with_no_profiles_does_not_break_the_block):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
