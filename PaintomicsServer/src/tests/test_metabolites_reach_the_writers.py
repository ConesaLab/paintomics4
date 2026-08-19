#!/usr/bin/env python3
"""A five-omics experiment must not be interpreted as four.

The STATegra job carries Gene expression, Proteomics, miRNA-seq and DNase-seq as
gene-based omics and **Metabolomics as compound-based**. Nothing in AIInterpret
read the compound layer: "compound" appeared zero times in context_builder.py,
agent.py and agent_loop.py, and clusters.py used matchedCompounds only for
Sorensen-Dice similarity. No report in either arm has ever named a metabolite.

The cost, measured against the published paper: rubric item E2 is "polyamines --
spermidine, putrescine, spermine -- decline toward pre-BII", and the job holds
exactly that, all three flagged differential:

    Spermidine  0.18 -0.10 -0.07 -0.42 -0.46 -0.56
    Putrescine  0.26  0.12  0.12 -0.53 -0.96 -1.27
    Spermine    0.16  0.09  0.03 -0.30 -0.37 -0.34

Per-pathway compounds alone do NOT fix it: mmu00330 (Arginine and proline
metabolism) ranks #421 of 887 by combined p, and the best-ranked pathway carrying
Spermidine or Spermine is #114. Only Putrescine reaches a context window, via
Efferocytosis at #12. So the finding is metabolite-level, not pathway-level, and
needs a block that does not depend on pathway rank.

    python -m src.tests.test_metabolites_reach_the_writers
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import context_builder as C     # noqa: E402
from src.classes.AIInterpret import agent_loop as L          # noqa: E402

_PASSED, _FAILED = [], []


class _Omic:
    def __init__(self, name, values, relevant=True):
        self._n, self._v, self._r = name, values, relevant

    def getOmicName(self):
        return self._n

    def getValues(self):
        return self._v

    def isRelevant(self):
        return self._r


class _Compound:
    def __init__(self, name, values, relevant=True):
        self._name, self._omics = name, [_Omic("Metabolomics", values, relevant)]

    def getName(self):
        return self._name

    def getOmicsValues(self):
        return self._omics


class _Job:
    """Two real polyamines, a synonym triple, and one flat compound."""
    def __init__(self):
        self._c = {
            "C00134": _Compound("Putrescine", [0.26, 0.12, -0.53, -1.27]),
            "C00315": _Compound("Spermidine", [0.18, -0.10, -0.42, -0.56]),
            "C00149": _Compound("Malic acid, L-Malic acid", [0.12, 0.08, -0.46, -0.79]),
            "C00711": _Compound("L-Malic acid", [0.12, 0.08, -0.46, -0.79]),
            "C00497": _Compound("D-Malic acid", [0.12, 0.08, -0.46, -0.79]),
            "C09999": _Compound("Boringine", [0.0, 0.0, 0.0, 0.0], relevant=False),
        }

    def getInputCompoundsData(self):
        return self._c

    def getGeneBasedInputOmics(self):
        # The real accessor. My first stub called it getInputOmics and every
        # test failed on the header map -- a stub that does not match the object
        # it stands in for tests nothing.
        return []


def _block():
    return C.build_differential_metabolites_block(_Job(), limit=20)


def test_the_polyamines_reach_the_agent():
    block = _block()
    for name in ("Putrescine", "Spermidine"):
        assert name in block, "%s is still invisible:\n%s" % (name, block)


def test_the_series_is_shown_not_just_the_name():
    """"Spermidine is differential" is not the finding; the DECLINE is."""
    block = _block()
    assert "-1.27" in block and "-0.56" in block, block


def test_one_measurement_mapped_to_three_ids_prints_once():
    """Malic acid arrives as three KEGG ids carrying identical values. Three
    lines read as three independent observations -- wrong science, no symptom."""
    block = _block()
    assert block.count("Malic acid") == 1, block
    assert "C00149" in block and "C00711" in block, (
        "the alias ids were dropped rather than collapsed")


def test_a_flat_compound_is_left_out():
    assert "Boringine" not in _block()


def test_the_block_says_why_it_exists():
    """A reader must know these are NOT in the pathway table, or a metabolite
    absent from it looks like a metabolite that did not change."""
    block = _block()
    assert "not enriched" in block or "NOT reachable" in block, block


def test_nothing_is_emitted_when_there_are_no_compounds():
    class _Empty:
        def getInputCompoundsData(self):
            return {}

        def getGeneBasedInputOmics(self):
            return []
    assert C.build_differential_metabolites_block(_Empty()) == ""


def test_the_pathway_block_can_show_compounds_too():
    """Per-pathway metabolites are still worth having -- Putrescine reaches
    Efferocytosis at rank #12 -- they are just not sufficient."""
    pathway = {"name": "Efferocytosis", "id": "mmu04148", "source": "KEGG",
               "combined_pvalue": 0.001, "global_pvalue": 0.002,
               "significant_omic_count": 3, "top_genes": [],
               "matched_compound_count": 2,
               "top_compounds": [{"name": "Putrescine", "id": "C00134",
                                  "relevant": True, "effect_size": 1.27,
                                  "values": "0.26@0h, -1.27@24h",
                                  "pattern": "monotonic-down"}]}
    before = L.SHOW_COMPOUNDS
    L.SHOW_COMPOUNDS = True
    try:
        out = L._pathway_block(pathway)
    finally:
        L.SHOW_COMPOUNDS = before
    assert "Putrescine" in out and "Matched metabolites" in out, out
    L.SHOW_COMPOUNDS = False
    assert "Putrescine" not in L._pathway_block(pathway), "flag does not gate it"


def test_the_flag_defaults_off():
    assert L.SHOW_COMPOUNDS is False


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_polyamines_reach_the_agent,
              test_the_series_is_shown_not_just_the_name,
              test_one_measurement_mapped_to_three_ids_prints_once,
              test_a_flat_compound_is_left_out,
              test_the_block_says_why_it_exists,
              test_nothing_is_emitted_when_there_are_no_compounds,
              test_the_pathway_block_can_show_compounds_too,
              test_the_flag_defaults_off):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
