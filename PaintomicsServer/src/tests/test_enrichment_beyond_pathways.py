#!/usr/bin/env python3
"""GO-style enrichment with elim, against the measured universe only.

Why this exists
---------------
Four dev studies wanted GO enrichment. The two failure modes worth pinning:
a genome-wide background inflating every p (the universe here is what the
experiment measured, enforced by construction), and DAG redundancy -- a
parent term "significant" only because its child is. The elim fixture makes
the second visible: with elim off the parent lights up, with elim on the
child's genes are removed from it first and it goes dark.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_enrichment_beyond_pathways
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret.enrichment import (   # noqa: E402
    GeneSetCollection, bh_qvalues, enrich_collection)
from src.classes.AIInterpret.facts import FactsLedger  # noqa: E402

UNIVERSE = ["G%02d" % i for i in range(50)]


def _collection():
    """child (G00-G02) under parent (child + G03, G04) under root."""
    sets = {
        "GO:child": {"name": "intrinsic signal", "genes": ["G00", "G01", "G02"]},
        "GO:parent": {"name": "regulation of signal",
                      "genes": ["G00", "G01", "G02", "G03", "G04"]},
        "GO:other": {"name": "unrelated process",
                     "genes": ["G40", "G41", "G42", "G43"]},
    }
    parents = {"GO:child": ["GO:parent"], "GO:parent": []}
    return GeneSetCollection("GO_BP", sets, parents)


class BHTest(unittest.TestCase):

    def test_hand_computed_bh(self):
        # p = (0.01, 0.02, 0.9): q = (0.03, 0.03, 0.9)
        q = bh_qvalues([0.01, 0.02, 0.9])
        self.assertAlmostEqual(q[0], 0.03)
        self.assertAlmostEqual(q[1], 0.03)
        self.assertAlmostEqual(q[2], 0.9)

    def test_q_is_monotone_in_p(self):
        q = bh_qvalues([0.5, 0.001, 0.04, 0.2])
        pairs = sorted(zip([0.5, 0.001, 0.04, 0.2], q))
        self.assertTrue(all(pairs[i][1] <= pairs[i + 1][1]
                            for i in range(len(pairs) - 1)))


class EnrichTest(unittest.TestCase):

    HITS = ["G00", "G01", "G02"]

    def test_the_child_is_significant_by_hand(self):
        res = enrich_collection(_collection(), self.HITS, UNIVERSE, elim=False)
        child = next(r for r in res["results"] if r["id"] == "GO:child")
        # P(overlap >= 3 | universe 50, set 3, hits 3) = 1/C(50,3)
        self.assertEqual(child["k"], 3)
        self.assertAlmostEqual(child["p"], 1.0 / math.comb(50, 3), places=12)

    def test_without_elim_the_parent_rides_its_child(self):
        res = enrich_collection(_collection(), self.HITS, UNIVERSE, elim=False)
        parent = next(r for r in res["results"] if r["id"] == "GO:parent")
        self.assertEqual(parent["k"], 3)
        self.assertLess(parent["p"], 0.001)

    def test_with_elim_the_parent_goes_dark(self):
        res = enrich_collection(_collection(), self.HITS, UNIVERSE, elim=True)
        parent = next(r for r in res["results"] if r["id"] == "GO:parent")
        self.assertEqual(parent["k"], 0)
        self.assertEqual(parent["elim_pruned"], 3)
        self.assertAlmostEqual(parent["p"], 1.0)
        self.assertIn("elim", res["method"])

    def test_the_unrelated_set_is_untouched_either_way(self):
        for elim in (False, True):
            res = enrich_collection(_collection(), self.HITS, UNIVERSE,
                                    elim=elim)
            other = next(r for r in res["results"] if r["id"] == "GO:other")
            self.assertEqual(other["k"], 0)

    def test_hits_outside_the_universe_are_dropped(self):
        res = enrich_collection(_collection(), self.HITS + ["PHANTOM"],
                                UNIVERSE)
        self.assertEqual(res["hits_in_universe"], 3)

    def test_sets_are_intersected_with_the_universe(self):
        # Three measured members (the MIN_SET floor) plus two phantoms: K
        # must count only what the experiment measured.
        sets = {"S": {"name": "s",
                      "genes": ["G00", "G01", "G02",
                                "NOTMEASURED1", "NOTMEASURED2"]}}
        res = enrich_collection(GeneSetCollection("X", sets),
                                ["G00", "G01"], UNIVERSE)
        s = res["results"][0]
        self.assertEqual(s["K"], 3)          # only the measured members count

    def test_pq_are_ledgered_when_a_ledger_is_passed(self):
        ledger = FactsLedger()
        res = enrich_collection(_collection(), self.HITS, UNIVERSE,
                                ledger=ledger)
        child = next(r for r in res["results"] if r["id"] == "GO:child")
        self.assertTrue(child["p_fact"].startswith("f"))
        self.assertTrue(child["q_fact"].startswith("f"))
        self.assertEqual(ledger.get(child["p_fact"]).kind, "pvalue")

    def test_an_empty_hit_list_is_an_error_not_a_zero_table(self):
        res = enrich_collection(_collection(), ["PHANTOM"], UNIVERSE)
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
