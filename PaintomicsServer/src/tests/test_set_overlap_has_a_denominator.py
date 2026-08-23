#!/usr/bin/env python3
"""An overlap without a background is not a finding.

Why this exists
---------------
Backlog #4, wanted by seven dev studies, and missed or not-derivable in four
of the eleven TEST studies — Venn panels across sex x genotype comparisons,
day-1 vs day-5 DEGs, proteome vs transcriptome, and shared KEGG enrichment.

"These two contrasts share 412 genes" means nothing on its own. It means
something against the number expected by chance, and that depends on the
universe THIS experiment measured — never the genome. What is pinned here is
that the background is the job's own features, that symbols absent from the
experiment are reported rather than dropped, and that the tail arithmetic
matches its closed form.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_set_overlap_has_a_denominator
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import set_overlap  # noqa: E402

OMIC = "Gene expression"


class _OV(object):
    def __init__(self, omic=OMIC):
        self._o = omic

    def getOmicName(self):
        return self._o

    def getValues(self):
        return [1.0, 2.0]

    def isRelevant(self):
        return True


class _Gene(object):
    def __init__(self, name):
        self._n = name

    def getName(self):
        return self._n

    def getOmicsValues(self):
        return [_OV()]


class _Job(object):
    def __init__(self, n=100):
        self.genes = {"G%03d" % i: _Gene("G%03d" % i) for i in range(n)}

    def getInputGenesData(self):
        return self.genes


class BackgroundTest(unittest.TestCase):

    def test_the_universe_is_the_experiment(self):
        res = set_overlap.compare(_Job(100),
                                  [("A", ["G001", "G002"]), ("B", ["G002", "G003"])])
        self.assertEqual(res["universe"], 100)

    def test_symbols_absent_from_the_experiment_are_reported(self):
        res = set_overlap.compare(_Job(50),
                                  [("A", ["G001", "NOPE1", "NOPE2"]),
                                   ("B", ["G001", "G002"])])
        a = [l for l in res["lists"] if l["name"] == "A"][0]
        self.assertEqual(a["given"], 3)
        self.assertEqual(a["measured"], 1)
        self.assertEqual(a["not_measured"], 2)
        self.assertIn("2 absent", set_overlap.format_result(res))

    def test_the_reply_states_the_background(self):
        res = set_overlap.compare(_Job(100), [("A", ["G001"]), ("B", ["G001"])])
        text = set_overlap.format_result(res)
        self.assertIn("100 measured features", text)
        self.assertIn("not the genome", text)


class ArithmeticTest(unittest.TestCase):

    def test_a_real_overlap_beats_chance(self):
        shared = ["G%03d" % i for i in range(10)]
        res = set_overlap.compare(
            _Job(1000),
            [("A", shared + ["G100", "G101"]), ("B", shared + ["G200", "G201"])])
        p = res["pairs"][0]
        self.assertEqual(p["shared"], 10)
        self.assertLess(p["p"], 1e-6)
        self.assertGreater(p["fold"], 10)

    def test_no_overlap_is_certain(self):
        res = set_overlap.compare(_Job(100),
                                  [("A", ["G001", "G002"]), ("B", ["G050", "G051"])])
        self.assertEqual(res["pairs"][0]["shared"], 0)
        self.assertEqual(res["pairs"][0]["p"], 1.0)

    def test_the_tail_matches_the_closed_form(self):
        # universe 20, draws of 8 and 5, all 5 shared:
        # P = C(8,5)C(12,0)/C(20,5) = 56/15504
        p = set_overlap._hypergeom_sf(5, 20, 8, 5)
        self.assertAlmostEqual(p, 56.0 / 15504.0, places=10)

    def test_jaccard_is_intersection_over_union(self):
        res = set_overlap.compare(
            _Job(100), [("A", ["G001", "G002", "G003"]), ("B", ["G002", "G003", "G004"])])
        self.assertAlmostEqual(res["pairs"][0]["jaccard"], 2 / 4.0, places=3)


class RefusalTest(unittest.TestCase):

    def test_one_list_is_not_a_comparison(self):
        res = set_overlap.compare(_Job(10), [("A", ["G001"])])
        self.assertIn("at least two", res["error"])

    def test_duplicates_do_not_inflate_a_list(self):
        res = set_overlap.compare(
            _Job(50), [("A", ["G001", "g001", " G001,"]), ("B", ["G001"])])
        self.assertEqual(res["lists"][0]["measured"], 1)

    def test_three_lists_give_three_pairs(self):
        res = set_overlap.compare(
            _Job(100),
            [("A", ["G001"]), ("B", ["G001"]), ("C", ["G002"])])
        self.assertEqual(len(res["pairs"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
