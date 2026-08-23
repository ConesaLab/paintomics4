#!/usr/bin/env python3
"""A gene set the agent names is tested against the user's own data.

Why this exists
---------------
Three dev studies do the same thing PaintOmics could not: they take a set
that is NOT one of the loaded pathway databases and ask whether it is
enriched in their data — HALLMARK/REACTOME collections and a published
BACH2-repressed target list (2025-39903532), GO of a top-200 list
(2025-39903537), a published 993-gene CAR-dependent set (2025-40904458).
Three studies, so it clears the ">=3 dev studies" rule; nothing else in the
buildable residue does.

Three properties are pinned because getting any of them wrong turns a real
test into a misleading one:

  * The background is the job's OWN measured universe. A genomic background
    inflates every p-value on a targeted panel.
  * Symbols that were never measured are reported, not silently dropped. "18
    of your 40 genes are in this experiment" is the honest denominator.
  * The direction split is read from the raw values, never from the rendered
    two-decimal profile the agent sees.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_a_named_gene_set_is_tested_against_the_data
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import gene_sets  # noqa: E402


class _OV(object):
    def __init__(self, omic, values, relevant):
        self._omic, self._values, self._rel = omic, values, relevant

    def getOmicName(self):
        return self._omic

    def getValues(self):
        return self._values

    def isRelevant(self):
        return self._rel


class _Gene(object):
    def __init__(self, name, rows):
        self._name, self._rows = name, rows

    def getName(self):
        return self._name

    def getOmicsValues(self):
        return self._rows


class _Job(object):
    """20 genes; G01-G05 significant and rising, G06-G08 significant falling."""

    def __init__(self):
        self.genes = {}
        for i in range(1, 21):
            sym = "G%02d" % i
            if i <= 5:
                rows = [_OV("Gene expression", [1.0, 5.0], True)]
            elif i <= 8:
                rows = [_OV("Gene expression", [5.0, 1.0], True)]
            else:
                rows = [_OV("Gene expression", [2.0, 2.0], False)]
            if i % 4 == 0:
                rows.append(_OV("Proteomics", [3.0, 9.0], i <= 8))
            self.genes[sym] = _Gene(sym, rows)

    def getInputGenesData(self):
        return self.genes


class BackgroundTest(unittest.TestCase):

    def test_the_universe_is_the_job_not_the_genome(self):
        res = gene_sets.test_gene_set(_Job(), ["G01", "G02", "G03"])
        self.assertEqual(res["universe"], 20)
        self.assertEqual(res["relevant_in_universe"], 8)

    def test_an_omic_filter_narrows_both_universe_and_hits(self):
        res = gene_sets.test_gene_set(_Job(), ["G04", "G08", "G12"],
                                      omic="Proteomics")
        self.assertEqual(res["universe"], 5, "only every 4th gene has proteomics")
        self.assertEqual(sorted(res["hits"]), ["G04", "G08"])


class HonestDenominatorTest(unittest.TestCase):

    def test_symbols_not_measured_are_reported(self):
        res = gene_sets.test_gene_set(_Job(), ["G01", "NOPE1", "NOPE2"])
        self.assertEqual(res["measured"], 1)
        self.assertEqual(res["not_measured_count"], 2)
        self.assertIn("NOPE1", res["not_measured"])

    def test_a_set_with_nothing_measured_says_so(self):
        res = gene_sets.test_gene_set(_Job(), ["NOPE1", "NOPE2"])
        text = gene_sets.format_result("Ghosts", res)
        self.assertIn("none of its 2 symbols were measured", text)

    def test_the_reply_states_the_denominator(self):
        res = gene_sets.test_gene_set(_Job(), ["G01", "G02", "NOPE"])
        text = gene_sets.format_result("Published set", res)
        self.assertIn("2 of 3 symbols were measured", text)
        self.assertIn("hypergeometric p", text)

    def test_duplicates_and_junk_do_not_inflate_the_count(self):
        res = gene_sets.test_gene_set(_Job(), ["G01", "g01", " G01,", "", None])
        self.assertEqual(res["given"], 1)
        self.assertEqual(res["measured"], 1)

    def test_an_oversized_set_is_refused(self):
        res = gene_sets.test_gene_set(_Job(), ["G%05d" % i for i in range(3000)])
        self.assertIn("limit", res.get("error", ""))


class ArithmeticTest(unittest.TestCase):

    def test_all_significant_beats_chance(self):
        res = gene_sets.test_gene_set(_Job(), ["G01", "G02", "G03", "G04", "G05"])
        self.assertEqual(res["hit_count"], 5)
        self.assertLess(res["p_value"], 0.05)
        self.assertGreater(res["fold"], 1.0)

    def test_no_overlap_is_not_significant(self):
        res = gene_sets.test_gene_set(_Job(), ["G15", "G16", "G17"])
        self.assertEqual(res["hit_count"], 0)
        self.assertEqual(res["p_value"], 1.0)

    def test_the_tail_matches_the_closed_form(self):
        # 20 genes, 8 significant, draw 5, all 5 hit:
        # P = C(8,5)C(12,0)/C(20,5) = 56/15504
        p = gene_sets._hypergeom_sf(5, 20, 8, 5)
        self.assertAlmostEqual(p, 56.0 / 15504.0, places=10)

    def test_drawing_everything_is_certain(self):
        self.assertAlmostEqual(gene_sets._hypergeom_sf(8, 20, 8, 20), 1.0, places=9)


class DirectionTest(unittest.TestCase):

    def test_up_and_down_are_split(self):
        res = gene_sets.test_gene_set(
            _Job(), ["G01", "G02", "G03", "G06", "G07"])
        self.assertEqual(res["up"], 3)
        self.assertEqual(res["down"], 2)
        self.assertIn("3 up, 2 down", gene_sets.format_result("S", res))

    def test_a_flat_feature_counts_neither_way(self):
        self.assertEqual(gene_sets._direction([2.0, 2.0]), 0)
        self.assertEqual(gene_sets._direction([]), 0)
        self.assertEqual(gene_sets._direction([1.0]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
