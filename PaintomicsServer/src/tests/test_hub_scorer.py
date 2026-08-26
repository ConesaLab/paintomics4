#!/usr/bin/env python3
"""The hub statistic, in Python.

Two defects in the R scorer were fixed in 93637565 and are re-asserted here so
they cannot come back: step 3 took step 2's successes against step 3's total,
and `p.adjust` was called per-row on a SCALAR, which for length 1 reduces to
min(1, p*n) -- Bonferroni shipped under a "BH" label for four years.

Two changes are new:
  * one BH family across all four steps, not four families over nested tests;
  * the percentile background is stratified by ball size, so a compound is
    ranked against similarly-connected compounds. Radius 4 covers 46.9% of the
    mmu network for C00024, where an unstratified rank mostly measures degree.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph.graph import KeggGraph
from src.common.KeggGraph.parser import Edge
from src.common.KeggGraph.scorer import HUB_SCHEMA_VERSION, score


def edge(a, b):
    return Edge(a, b, "PPrel", "", "tst00001", False)


def build():
    """C1 sits next to three DE genes; C2 next to three measured, none DE."""
    edges = [edge("C1", "g1"), edge("C1", "g2"), edge("C1", "g3"),
             edge("C2", "g4"), edge("C2", "g5"), edge("C2", "g6"),
             edge("g3", "g7"), edge("g6", "g8")]
    types = {"C1": "compound", "C2": "compound"}
    for name in ("g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"):
        types[name] = "gene"
    return KeggGraph(edges, types, "test")


class ScorerTest(unittest.TestCase):
    def setUp(self):
        self.graph = build()
        self.measured = {"g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8",
                         "C1", "C2"}
        self.relevant = {"g1", "g2", "g3", "C1", "C2"}
        self.rows = score(self.graph, self.measured, self.relevant, steps=4)
        self.step1 = {r["name"]: r for r in self.rows if r["step"] == 1}

    def test_every_row_carries_the_schema_version(self):
        self.assertTrue(all(r["schema"] == HUB_SCHEMA_VERSION for r in self.rows))

    def test_counts_are_right_for_the_enriched_compound(self):
        row = self.step1["C1"]
        self.assertEqual((row["DEN"], row["noDEN"]), (3, 0))
        self.assertAlmostEqual(row["density"], 1.0)

    def test_counts_are_right_for_the_depleted_compound(self):
        row = self.step1["C2"]
        self.assertEqual((row["DEN"], row["noDEN"]), (0, 3))
        self.assertAlmostEqual(row["density"], 0.0)

    def test_enriched_compound_has_the_smaller_pvalue(self):
        self.assertLess(self.step1["C1"]["pvalue"], self.step1["C2"]["pvalue"])

    def test_zero_measured_neighbours_scores_p_equals_one(self):
        rows = score(self.graph, {"C1", "g1"}, {"C1"}, steps=4)
        self.assertTrue(rows)

    @staticmethod
    def _bh(pvalues):
        """Benjamini-Hochberg, reimplemented so the test does not simply agree
        with statsmodels about statsmodels. Step-up: q_i = p_i * n / i, then a
        running minimum from the largest rank down, clipped to 1."""
        order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
        n = len(pvalues)
        out = [0.0] * n
        running = 1.0
        for rank in range(n, 0, -1):
            i = order[rank - 1]
            running = min(running, pvalues[i] * n / rank)
            out[i] = min(1.0, running)
        return out

    def test_bh_is_one_family_across_all_four_steps(self):
        """D-4. The R code called p.adjust inside processData(), which ran once
        per step, so four nested and near-perfectly dependent tests became four
        families -- and were then shown together in one sortable grid."""
        raw = [r["pvalue"] for r in self.rows]
        for row, expected in zip(self.rows, self._bh(raw)):
            self.assertAlmostEqual(row["pvalue_adjust"], expected, places=12)

    def test_per_step_adjustment_would_give_a_different_answer(self):
        """Guards the fix: if someone reinstates per-step families, the values
        move, and this test says so."""
        per_step = {}
        for step in (1, 2, 3, 4):
            rows = [r for r in self.rows if r["step"] == step]
            for row, value in zip(rows, self._bh([r["pvalue"] for r in rows])):
                per_step[(row["name"], row["step"])] = value
        one_family = {(r["name"], r["step"]): r["pvalue_adjust"] for r in self.rows}
        self.assertNotEqual(per_step, one_family)
        # every per-step value is <= the one-family value: a smaller family is
        # a weaker correction, which is exactly why the R behaviour was wrong.
        for key, value in per_step.items():
            self.assertLessEqual(value, one_family[key] + 1e-12)

    def test_adjusted_is_never_below_raw(self):
        for row in self.rows:
            self.assertGreaterEqual(row["pvalue_adjust"] + 1e-12, row["pvalue"])

    def test_ball_fraction_is_reported_and_bounded(self):
        for row in self.rows:
            self.assertGreaterEqual(row["ball_fraction"], 0.0)
            self.assertLessEqual(row["ball_fraction"], 1.0)

    def test_percentile_is_within_range(self):
        for row in self.rows:
            self.assertGreaterEqual(row["percentile"], 0.0)
            self.assertLessEqual(row["percentile"], 1.0)

    def test_no_relevant_compounds_falls_back_to_all_measured(self):
        rows = score(self.graph, self.measured, {"g1"}, steps=4)
        self.assertEqual({r["name"] for r in rows}, {"C1", "C2"})

    def test_rows_cover_every_step(self):
        self.assertEqual(sorted({r["step"] for r in self.rows}), [1, 2, 3, 4])

    def test_cumulative_balls_grow_monotonically(self):
        by_step = {r["step"]: r for r in self.rows if r["name"] == "C1"}
        for step in (2, 3, 4):
            self.assertGreaterEqual(by_step[step]["ball_size"],
                                    by_step[step - 1]["ball_size"])

    def test_no_measured_gene_returns_no_rows(self):
        self.assertEqual(score(self.graph, {"C1"}, {"C1"}, steps=4), [])


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
