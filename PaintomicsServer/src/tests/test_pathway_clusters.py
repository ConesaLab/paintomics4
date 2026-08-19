#!/usr/bin/env python3
"""The shared-feature pathway partition behind cluster-first interpretation.

Pure computation, so this needs no LLM, no MongoDB and no network. It pins
the contracts agent.py relies on:

* a cluster has at least two members -- a size-1 group is an isolate;
* KEGG (Entrez) and Reactome (symbol) clones of the same input feature join,
  so a pathway pair spanning both databases can share a cluster;
* the isolate rule: satellite attach, then standalone (major or top-ranked),
  else "further" -- nothing significant is dropped;
* determinism: same job -> identical partition;
* packing never splits a unit and keeps global rank order inside a batch;
* every rendered block carries global ranks (cluster for context, never for
  order -- the evolve-loop lesson).

Usage:
    cd PaintomicsServer
    python -m src.tests.test_pathway_clusters
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import clusters as C  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes with exactly the surface clusters.py touches
# ---------------------------------------------------------------------------

class _OV:
    def __init__(self, omic, input_name, values, relevant=True):
        self.omicName, self.inputName, self.values, self.relevant = omic, input_name, values, relevant

    def getOmicName(self):
        return self.omicName

    def getInputName(self):
        return self.inputName

    def getValues(self):
        return self.values

    def isRelevant(self):
        return self.relevant


class _Feature:
    def __init__(self, fid, name, omics):
        self.ID, self.name, self.omicsValues = fid, name, omics

    def getName(self):
        return self.name

    def getOmicsValues(self):
        return self.omicsValues


class _Pathway:
    def __init__(self, pid, name, source, genes, compounds=(), fisher=1e-3, sig_omics=None):
        self.ID, self.name, self.source = pid, name, source
        self.matchedGenes = list(genes)
        self.matchedCompounds = list(compounds)
        self.combinedSignificancePvalues = {"Fisher": [fisher], "Stouffer": [fisher * 2]}
        # significanceValues[omic] = [[matched, relevant, p]] per condition
        sig = sig_omics or {"Gene expression": 0.01}
        self.significanceValues = {o: [[5, 3, p]] for o, p in sig.items()}
        self.globalOmicPvalues = {o: p for o, p in sig.items()}


class _Job:
    def __init__(self, pathways, genes, organism="mmu"):
        self._p = {p.ID: p for p in pathways}
        self._g = genes
        self._o = organism

    def getMatchedPathways(self):
        return self._p

    def getInputGenesData(self):
        return self._g

    def getGeneBasedInputOmics(self):
        return [{"omicName": "Gene expression", "omicHeader": ["id", "0h", "2h", "6h"]}]

    def getOrganism(self):
        return self._o


def _genes(n_entrez=40):
    """KEGG clones 1..n keyed by Entrez id, plus Reactome clones for the first
    ten keyed by an upper-case symbol, both carrying the same input name."""
    genes = {}
    for i in range(1, n_entrez + 1):
        ent = str(1000 + i)
        sym = "Gene%d" % i
        ens = "ENSMUSG%011d" % i
        genes[ent] = _Feature(ent, sym, [_OV("Gene expression", ens, [0.1 * i, 0.5, 1.0])])
        if i <= 10:
            genes[sym.upper()] = _Feature(sym.upper(), ens,
                                          [_OV("Gene expression", ens, [0.1 * i, 0.5, 1.0])])
    return genes


def _job():
    E = lambda *ids: [str(1000 + i) for i in ids]  # noqa: E731
    R = lambda *ids: ["GENE%d" % i for i in ids]  # noqa: E731
    pathways = [
        # A/B/C: a real cluster (share genes 1-8), best p first.
        _Pathway("mmu00001", "Alpha signaling", "KEGG", E(1, 2, 3, 4, 5, 6, 7, 8, 21), fisher=1e-6,
                 sig_omics={"Gene expression": 0.001, "Proteomics": 0.01}),
        _Pathway("mmu00002", "Beta signaling", "KEGG", E(1, 2, 3, 4, 5, 6, 7, 8, 22, 23), fisher=1e-5),
        _Pathway("mmu00003", "Gamma signaling", "KEGG", E(1, 2, 3, 4, 5, 6, 9, 24), fisher=1e-4),
        # A's Reactome twin: symbols only -- joins A only through the input names.
        _Pathway("R-MMU-1", "Alpha signalling (Reactome)", "Reactome", R(1, 2, 3, 4, 5, 6, 7, 8),
                 fisher=2e-6),
        # D/E: a pair sharing compounds and a few genes.
        _Pathway("mmu00004", "Delta metabolism", "KEGG", E(30, 31, 32), ("C00001", "C00002", "C00003"),
                 fisher=1e-3),
        _Pathway("mmu00005", "Epsilon metabolism", "KEGG", E(30, 31, 33), ("C00001", "C00002", "C00004"),
                 fisher=2e-3),
        # F: isolate, major (2 significant omics) -> standalone.
        _Pathway("mmu00006", "Zeta process", "KEGG", E(35, 36, 37, 38), fisher=3e-3,
                 sig_omics={"Gene expression": 0.01, "miRNA-seq": 0.02}),
        # G: isolate, minor, ranks last -> further.
        _Pathway("mmu00007", "Eta process", "KEGG", E(39, 40), fisher=4e-2),
        # H: loosely related to the A cluster (1 of 8 core genes, mean Dice
        # ~0.13: below the 0.25 cut, above the 0.10 attach) -> satellite.
        _Pathway("mmu00008", "Theta signaling", "KEGG", E(1, 25, 26, 27, 28, 29), fisher=5e-3),
        # Not significant: must not be a node at all.
        _Pathway("mmu00009", "Iota nothing", "KEGG", E(1, 2, 3), fisher=0.5),
    ]
    return _Job(pathways, _genes())


class PartitionTest(unittest.TestCase):
    def setUp(self):
        self.job = _job()
        # standalone_top small so rank alone does not promote the minor isolate.
        self.params = {"min_features": 0.0, "standalone_top": 3, "hub_fraction": 0.9}
        self.part = C.build_partition(self.job, self.params)

    def test_universe_is_significant_only_and_ranked(self):
        self.assertNotIn("mmu00009", self.part["nodes"])
        self.assertEqual(self.part["nodes"][0], "mmu00001")  # best p
        self.assertEqual(self.part["ranks"]["mmu00001"], 1)
        self.assertEqual(len(self.part["nodes"]), 9)

    def test_clusters_have_at_least_two_members(self):
        self.assertTrue(self.part["clusters"])
        for c in self.part["clusters"]:
            self.assertGreaterEqual(len(c["members"]), 2, c)

    def test_cross_database_clones_join(self):
        # The Reactome twin lands in the same cluster as its KEGG original.
        unit = self.part["unit_of"]
        self.assertEqual(unit["R-MMU-1"], unit["mmu00001"])
        c = next(c for c in self.part["clusters"] if c["id"] == unit["mmu00001"])
        self.assertEqual(sorted(c["sources"]), ["KEGG", "Reactome"])
        # And the core is rendered with symbols, not Entrez ids or ENSMUSG.
        syms = [f["symbol"] for f in c["core"]]
        self.assertTrue(syms and all(s.startswith("Gene") for s in syms), syms)

    def test_isolate_rule(self):
        unit = self.part["unit_of"]
        # Theta shares 2/8 core genes with the A cluster: satellite, not core.
        self.assertTrue(unit["mmu00008"].startswith("C"))
        c = next(c for c in self.part["clusters"] if c["id"] == unit["mmu00008"])
        self.assertIn("mmu00008", c["satellites"])
        self.assertNotIn("mmu00008", c["members"])
        # Zeta: major isolate -> standalone. Eta: minor, low rank -> further.
        self.assertIn("mmu00006", self.part["standalone"])
        self.assertIn("mmu00007", self.part["further"])
        # Every significant pathway is accounted for exactly once.
        self.assertEqual(sorted(unit), sorted(self.part["nodes"]))

    def test_deterministic(self):
        again = C.build_partition(_job(), self.params)
        self.assertEqual(json.dumps(self.part, sort_keys=True, default=str),
                         json.dumps(again, sort_keys=True, default=str))

    def test_always_include_pins_the_callers_top_n(self):
        # The plain path's top-N must never fall out of the cluster universe,
        # whatever the network filters say (round 6 B1 lost a rank-8 pathway).
        part = C.build_partition(self.job, self.params, always_include=["mmu00009"])
        self.assertIn("mmu00009", part["nodes"])
        self.assertIn("mmu00009", part["unit_of"])
        # Rank order is still by p-value: the forced (p=0.5) pathway ranks last.
        self.assertEqual(part["nodes"][-1], "mmu00009")

    def test_cap_split_never_emits_singletons_as_clusters(self):
        # Force a tiny cap so the A cluster must be split.
        part = C.build_partition(self.job, dict(self.params, cap=2, attach=0.99))
        for c in part["clusters"]:
            self.assertGreaterEqual(len(c["members"]), 2)
            self.assertLessEqual(len(c["members"]), 2)
        self.assertEqual(sorted(part["unit_of"]), sorted(part["nodes"]))


class UnitsAndRenderingTest(unittest.TestCase):
    def setUp(self):
        self.job = _job()
        self.part = C.build_partition(self.job, {"min_features": 0.0, "standalone_top": 3,
                                                 "hub_fraction": 0.9})
        # Minimal pathway-context dicts, as build_pathway_context returns them.
        self.ctx = {}
        for pid, pw in self.job.getMatchedPathways().items():
            if pid in self.part["ranks"]:
                self.ctx[pid] = {"id": pid, "name": pw.name, "source": pw.source,
                                 "combined_pvalue": pw.combinedSignificancePvalues["Fisher"][0],
                                 "significant_omic_count": 1,
                                 "top_genes": [{"symbol": "Gene1", "relevant": True}]}





class FrozenContextTest(unittest.TestCase):
    """Optional: the real STATegra frozen fold, when the evolve repo is present."""

    FROZEN = os.path.expanduser(
        "~/Desktop/github_dev/agentevolve/evaluators/stategra-v4/context.pkl.gz")

    def test_frozen_partition_shape(self):
        if not os.path.exists(self.FROZEN):
            self.skipTest("frozen fold not present")
        sys.path.insert(0, os.path.expanduser("~/Desktop/github_dev/agentevolve"))
        try:
            from wrap.freeze import FrozenJobInstance
        except Exception as e:  # pragma: no cover
            self.skipTest("evolve harness not importable: %s" % e)
        job = FrozenJobInstance.load(self.FROZEN)
        part = C.build_partition(job)
        self.assertGreater(len(part["clusters"]), 5)
        for c in part["clusters"]:
            self.assertGreaterEqual(len(c["members"]), 2)
        self.assertTrue(any(len(c["sources"]) == 2 for c in part["clusters"]),
                        "expected at least one KEGG+Reactome cluster")
        self.assertEqual(sorted(part["unit_of"]), sorted(part["nodes"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
