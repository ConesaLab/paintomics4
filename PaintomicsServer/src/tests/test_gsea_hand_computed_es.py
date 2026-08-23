#!/usr/bin/env python3
"""The enrichment score, checked against arithmetic done by hand.

Why this exists
---------------
A GSEA whose ES is off by a normalisation factor still produces plausible
tables. The fixtures pin the walk itself: a set at the very top of a 10-gene
list scores exactly +1, one at the very bottom exactly -1, and a split set's
extremum is computed by hand. Determinism (same seed, same p), the reported
permutation floor, and the leading edge round it out.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_gsea_hand_computed_es
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret.enrichment import (   # noqa: E402
    GeneSetCollection, _enrichment_score, run_gsea)

GENES = ["g%d" % i for i in range(1, 11)]            # g1 best ... g10 worst
SCORES = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
RANKED = [g.upper() for g in GENES]
WEIGHTS = list(SCORES)


class HandComputedTest(unittest.TestCase):

    def test_a_top_set_scores_exactly_plus_one(self):
        es, running, positions = _enrichment_score(RANKED, {"G1", "G2"},
                                                   WEIGHTS)
        # +10/19 then +9/19: the running sum reaches exactly 1.0 at rank 2.
        self.assertAlmostEqual(es, 1.0, places=12)
        self.assertAlmostEqual(running[0], 10.0 / 19.0, places=12)
        self.assertEqual(positions, [0, 1])

    def test_a_bottom_set_scores_exactly_minus_one(self):
        es, running, _ = _enrichment_score(RANKED, {"G9", "G10"}, WEIGHTS)
        # Eight misses of 1/8 each reach -1.0 before the first hit.
        self.assertAlmostEqual(es, -1.0, places=12)
        self.assertAlmostEqual(min(running), -1.0, places=12)

    def test_a_split_set_extremum_by_hand(self):
        # {G1, G3}: +10/18, miss -1/8, +8/18 -> extremum 0.875 at rank 3.
        es, running, _ = _enrichment_score(RANKED, {"G1", "G3"}, WEIGHTS)
        self.assertAlmostEqual(running[0], 10.0 / 18.0, places=12)
        self.assertAlmostEqual(running[1], 10.0 / 18.0 - 0.125, places=12)
        self.assertAlmostEqual(es, 10.0 / 18.0 - 0.125 + 8.0 / 18.0,
                               places=12)

    def test_a_set_absent_from_the_list_scores_zero(self):
        es, _r, positions = _enrichment_score(RANKED, {"NOPE"}, WEIGHTS)
        self.assertEqual(es, 0.0)
        self.assertEqual(positions, [])


class RunGseaTest(unittest.TestCase):

    def _collection(self):
        return GeneSetCollection("Hallmark", {
            "TOP": {"name": "top genes", "genes": ["G1", "G2", "G3"]},
            "BOTTOM": {"name": "bottom genes", "genes": ["G8", "G9", "G10"]},
        })

    def test_signs_point_the_right_way(self):
        res = run_gsea(GENES, SCORES, self._collection(),
                       n_permutations=200, seed=3)
        by_id = {r["id"]: r for r in res["results"]}
        self.assertGreater(by_id["TOP"]["es"], 0)
        self.assertLess(by_id["BOTTOM"]["es"], 0)
        self.assertGreater(by_id["TOP"]["nes"], 0)
        self.assertLess(by_id["BOTTOM"]["nes"], 0)

    def test_the_same_seed_reproduces_p(self):
        a = run_gsea(GENES, SCORES, self._collection(), n_permutations=200,
                     seed=7)
        b = run_gsea(GENES, SCORES, self._collection(), n_permutations=200,
                     seed=7)
        self.assertEqual([r["p"] for r in a["results"]],
                         [r["p"] for r in b["results"]])

    def test_the_floor_is_reported_and_respected(self):
        res = run_gsea(GENES, SCORES, self._collection(),
                       n_permutations=200, seed=3)
        self.assertAlmostEqual(res["min_attainable_p"], 1.0 / 201)
        for r in res["results"]:
            self.assertGreaterEqual(r["p"], res["min_attainable_p"] - 1e-12)
        self.assertIn("gene-label", res["method"])

    def test_the_leading_edge_is_the_front_of_a_positive_set(self):
        res = run_gsea(GENES, SCORES, self._collection(),
                       n_permutations=100, seed=3)
        top = next(r for r in res["results"] if r["id"] == "TOP")
        self.assertEqual(top["leading_edge"], ["G1", "G2", "G3"])

    def test_a_short_list_is_refused(self):
        res = run_gsea(GENES[:5], SCORES[:5], self._collection())
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
