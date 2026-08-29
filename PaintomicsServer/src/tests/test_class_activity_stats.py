#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Guards for src/common/ClassActivity.py -- the two metabolite class tests.

What is pinned here, and why each pin exists:

1. The per-metabolite F-test agrees with scipy's one-way ANOVA on a plain
   two-group design (no strata), so the model is the textbook one and not a
   private approximation of it.
2. The self-contained binomial with p0 = alpha gives the hand-computed
   numbers (3 of 4 at alpha 0.05 is 4*0.05^3*0.95 + 0.05^4), and the
   competitive null with p0 = 0.71 gives the ~0.67 that made every STATegra
   class unreachable -- the whole reason the default moved.
3. Under a design with NO effect the permutation p is not small; with a
   planted effect on a class's members it is. A permutation test that
   cannot tell those apart is decoration.
4. Missing values: a row with a few NaN cells is still tested (on its
   complete columns, with fewer residual df); a row with almost nothing is
   not, and reports NaN rather than a made-up F.
5. The BRITE walk puts alanine under Peptides > Amino acids > Common amino
   acids, GABA under three level-2 classes, and one measured name ticked
   under two KEGG ids is ONE member of the class -- the same dedup the
   level-2 binomial already does.
6. designFactors reads Ctr_0H..Ik_24H as two factors and stratifies the
   treatment by time; a design without crossed names is one factor with a
   single stratum.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_class_activity_stats
"""
import os
import sys
import unittest
from collections import OrderedDict

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common import ClassActivity as CA  # noqa: E402


def _twoByThreeDesign(reps=3):
    """Ctr/Ik x 0H,2H,6H with `reps` replicates each: columns in design order."""
    sampleHeader = ["Ctr_0H", "Ctr_2H", "Ctr_6H", "Ik_0H", "Ik_2H", "Ik_6H"]
    mapping = [i for i in range(len(sampleHeader)) for _ in range(reps)]
    return sampleHeader, mapping


class FactorTest(unittest.TestCase):

    def test_two_groups_no_strata_is_one_way_anova(self):
        rng = np.random.default_rng(1)
        Y = rng.normal(size=(5, 8))
        Y[0, 4:] += 3.0
        level = np.array([0, 0, 0, 0, 1, 1, 1, 1])
        strata = np.zeros(8, dtype=int)
        F, P, df1, df2 = CA.factorTest(Y, level, strata)
        for i in range(5):
            ref = stats.f_oneway(Y[i, :4], Y[i, 4:])
            self.assertAlmostEqual(F[i], ref.statistic, places=9)
            self.assertAlmostEqual(P[i], ref.pvalue, places=9)
        self.assertEqual((df1[0], df2[0]), (1, 6))
        self.assertLess(P[0], 1e-2)

    def test_interaction_is_caught_when_the_main_effect_cancels(self):
        # Up early, down late: the overall Ik-vs-Ctr difference is ~0 but the
        # Ik x time interaction is large. A test without the interaction term
        # would miss it; this one must not.
        sampleHeader, mapping = _twoByThreeDesign()
        factor = min(CA.designFactors(sampleHeader, mapping), key=lambda f: len(f["levels"]))
        rng = np.random.default_rng(2)
        Y = rng.normal(scale=0.1, size=(1, 18))
        level = np.array(factor["columnLevel"])
        strata = np.array(factor["strata"])
        Y[0, (level == 1) & (strata == 0)] += 2.0   # Ik up at 0H
        Y[0, (level == 1) & (strata == 2)] -= 2.0   # Ik down at 6H
        F, P, df1, df2 = CA.factorTest(Y, level, strata)
        self.assertEqual((df1[0], df2[0]), (3, 12))
        self.assertLess(P[0], 1e-6)

    def test_missing_cells_are_tolerated_and_reported(self):
        rng = np.random.default_rng(3)
        Y = rng.normal(size=(3, 8))
        level = np.array([0, 0, 0, 0, 1, 1, 1, 1])
        strata = np.zeros(8, dtype=int)
        Y[1, 0] = np.nan                    # one gap: still tested, df2 drops by 1
        Y[2, :6] = np.nan                   # two values left: cannot be tested
        F, P, df1, df2 = CA.factorTest(Y, level, strata)
        self.assertTrue(np.isfinite(F[0]) and np.isfinite(F[1]))
        self.assertEqual(df2[1], df2[0] - 1)
        self.assertTrue(np.isnan(F[2]) and np.isnan(P[2]))


class BinomialTest(unittest.TestCase):

    def _classes(self):
        return {"Peptides > Amines": {"members": {"a", "b", "c", "d"}},
                "Nucleic acids > Bases": {"members": {"e", "f", "g"}}}

    def test_alpha_null_matches_the_hand_computation(self):
        relevant = {k: [True] for k in "abc"}
        relevant.update({k: [False] for k in "defg"})
        relevant["e"] = [True]
        res = CA.binomialClassTest(self._classes(), relevant, 1, [0.05])
        self.assertEqual(res["Peptides > Amines"]["k"], [3])
        self.assertAlmostEqual(res["Peptides > Amines"]["p"][0],
                               4 * 0.05 ** 3 * 0.95 + 0.05 ** 4, places=12)
        self.assertAlmostEqual(res["Nucleic acids > Bases"]["p"][0], 1 - 0.95 ** 3, places=12)
        # BH across the two classes of the condition.
        self.assertAlmostEqual(res["Peptides > Amines"]["bh"][0], 2 * res["Peptides > Amines"]["p"][0], places=12)

    def test_competitive_null_is_powerless_on_a_targeted_panel(self):
        relevant = {k: [True] for k in "abc"}
        relevant.update({k: [False] for k in "defg"})
        res = CA.binomialClassTest(self._classes(), relevant, 1, [29.0 / 41])
        self.assertGreater(res["Peptides > Amines"]["p"][0], 0.6)

    def test_a_degenerate_null_reports_one(self):
        relevant = {k: [True] for k in "abcdefg"}
        res = CA.binomialClassTest(self._classes(), relevant, 1, [1.0])
        self.assertEqual(res["Peptides > Amines"]["p"], [1.0])

    def test_per_condition_counts_and_nulls(self):
        relevant = {"a": [True, False], "b": [True, False], "c": [False, True], "d": [False, False],
                    "e": [False, False], "f": [False, False], "g": [False, False]}
        res = CA.binomialClassTest(self._classes(), relevant, 2, [0.05, 0.5])
        self.assertEqual(res["Peptides > Amines"]["k"], [2, 1])
        self.assertLess(res["Peptides > Amines"]["p"][0], 0.05)
        self.assertGreater(res["Peptides > Amines"]["p"][1], 0.5)


class PermutationTest(unittest.TestCase):

    def _setup(self, effect):
        sampleHeader, mapping = _twoByThreeDesign()
        factor = min(CA.designFactors(sampleHeader, mapping), key=lambda f: len(f["levels"]))
        rng = np.random.default_rng(4)
        Y = rng.normal(scale=0.2, size=(12, 18))
        level = np.array(factor["columnLevel"])
        # Members of class A respond to Ik at every time point; B do not.
        for row in range(4):
            Y[row, level == 1] += effect
        classes = {2: {"X > A": {"name": "A", "parent": "X", "path": ["X", "A"], "members": {"m%d" % i for i in range(4)}},
                       "X > B": {"name": "B", "parent": "X", "path": ["X", "B"], "members": {"m%d" % i for i in range(4, 12)}}}}
        rows = {"m%d" % i: i for i in range(12)}
        return Y, factor, classes, rows

    def test_a_planted_effect_is_found_and_no_effect_is_not(self):
        Y, factor, classes, rows = self._setup(effect=1.5)
        res = CA.permutationClassTest(Y, factor, classes, rows, nPerm=300, seed=0)
        a = res["levels"][2]["X > A"]
        b = res["levels"][2]["X > B"]
        self.assertLess(a["p"], 0.02)
        self.assertGreater(b["p"], 0.2)
        self.assertGreater(a["meanF"], a["nullQ95"])
        self.assertEqual(a["n"], 4)
        self.assertEqual(a["nsig"], 4)
        # Direction strip: Ik - Ctr per time point, positive for A.
        self.assertEqual(res["effects"]["labels"], ["0H", "2H", "6H"])
        self.assertTrue(all(v > 1.0 for v in a["eff"]))
        self.assertAlmostEqual(a["E"], float(np.mean([abs(v) for v in a["eff"]])), places=9)
        # The smallest reachable p is 1/(B+1), never 0.
        self.assertGreaterEqual(a["p"], 1.0 / 301)

    def test_null_data_gives_a_uniform_ish_p(self):
        Y, factor, classes, rows = self._setup(effect=0.0)
        res = CA.permutationClassTest(Y, factor, classes, rows, nPerm=300, seed=1)
        self.assertGreater(res["levels"][2]["X > A"]["p"], 0.05)
        self.assertGreater(res["levels"][2]["X > B"]["p"], 0.05)
        self.assertAlmostEqual(res["levels"][2]["X > A"]["nullMedian"], 1.0, delta=0.5)

    def test_untestable_members_do_not_break_the_class(self):
        Y, factor, classes, rows = self._setup(effect=1.5)
        Y[1, :16] = np.nan                  # m1 cannot be tested
        res = CA.permutationClassTest(Y, factor, classes, rows, nPerm=100, seed=0)
        a = res["levels"][2]["X > A"]
        self.assertEqual((a["n"], a["tested"]), (4, 3))
        self.assertLess(a["p"], 0.05)

    def test_raw_intensities_are_logged_first(self):
        Y, factor, classes, rows = self._setup(effect=0.0)
        res = CA.permutationClassTest(2 ** (Y * 10 + 12), factor, classes, rows, nPerm=20, seed=0)
        self.assertTrue(res["transformed"])
        res = CA.permutationClassTest(Y, factor, classes, rows, nPerm=20, seed=0)
        self.assertFalse(res["transformed"])


class BriteTest(unittest.TestCase):

    def test_levels_and_multi_membership(self):
        brite = CA.loadBrite()
        self.assertEqual(brite["C00041"], [("Peptides", "Amino acids", "Common amino acids")])
        levels = CA.membershipsByLevel({"alanine": ["C00041", "C01401"],   # one name, two ids
                                        "gaba": ["C00334"],
                                        "glucose": ["C00031"]}, brite)
        aa = levels[2]["Peptides > Amino acids"]
        self.assertEqual(aa["members"], {"alanine", "gaba"})
        self.assertEqual(levels[3]["Peptides > Amino acids > Common amino acids"]["members"], {"alanine"})
        gabaClasses = {key for key, entry in levels[2].items() if "gaba" in entry["members"]}
        self.assertEqual(gabaClasses, {"Peptides > Amino acids", "Peptides > Amines",
                                       "Hormones and transmitters > Neurotransmitters"})
        self.assertEqual(levels[1]["Carbohydrates"]["members"], {"glucose"})
        self.assertEqual(levels[2]["Peptides > Amino acids"]["parent"], "Peptides")


class DesignFactorsTest(unittest.TestCase):

    def test_crossed_names_give_two_factors_with_strata(self):
        sampleHeader, mapping = _twoByThreeDesign(reps=2)
        factors = CA.designFactors(sampleHeader, mapping)
        self.assertEqual([f["id"] for f in factors], ["factor0", "factor1"])
        treatment = factors[0]
        self.assertEqual(treatment["levels"], ["Ctr", "Ik"])
        self.assertEqual(treatment["strataLabels"], ["0H", "2H", "6H"])
        self.assertEqual(treatment["columnLevel"], [0] * 6 + [1] * 6)
        self.assertEqual(treatment["strata"], [0, 0, 1, 1, 2, 2] * 2)
        time = factors[1]
        self.assertEqual(time["levels"], ["0H", "2H", "6H"])
        self.assertEqual(time["strataLabels"], ["Ctr", "Ik"])

    def test_plain_groups_are_one_factor_one_stratum(self):
        factors = CA.designFactors(["WT", "KO"], [0, 0, 1, 1])
        self.assertEqual(len(factors), 1)
        self.assertEqual(factors[0]["id"], "design")
        self.assertEqual(factors[0]["levels"], ["WT", "KO"])
        self.assertEqual(factors[0]["strata"], [0, 0, 0, 0])


class GapsKeepTheNullExchangeableTest(unittest.TestCase):
    """A metabolite below LOD in one arm.

    The interaction's rank depends on which cells the surviving columns
    occupy; under a relabelling the labels move while the gaps stay on their
    columns, so the observed fit was at (df1=1, df2=6) and most permuted fits
    at (2, 5) -- a lighter tail, 8% of pure-noise classes called at nominal
    5%. A row with a gap is fitted additively now, at the same degrees of
    freedom under every relabelling.
    """

    def setUp(self):
        # Ctr/Ik x 0H/2H, three replicates: 12 columns.
        self.level = np.array([0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1])
        self.strata = np.array([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
        rng = np.random.default_rng(3)
        self.Y = rng.normal(size=(6, 12))
        self.Y[0, 0:3] = np.nan          # Ctr_0H missing for row 0

    def test_a_gap_is_fitted_at_the_same_df_under_every_relabelling(self):
        _F, _p, df1, df2 = CA.factorTest(self.Y, self.level, self.strata)
        self.assertEqual((df1[0], df2[0]), (1, 6))
        self.assertEqual((df1[1], df2[1]), (2, 8))          # a complete row keeps the interaction
        rng = np.random.default_rng(11)
        seen = set()
        for _ in range(40):
            permuted = CA._shuffleWithinStrata(self.level, self.strata, rng)
            _F, _p, d1, d2 = CA.factorTest(self.Y, permuted, self.strata)
            seen.add((d1[0], d2[0]))
        self.assertEqual(seen, {(1, 6)})

    def test_a_member_missing_a_cell_does_not_blank_the_class_direction(self):
        # Four members up by ~1.5 at 0H; the fourth has no Ctr_0H columns.
        Y = np.random.default_rng(5).normal(size=(4, 12)) * 0.1
        Y[:, 3:6] += 1.5
        Y[3, 0:3] = np.nan
        factor = {"columnLevel": self.level, "strata": self.strata, "levels": ["Ctr", "Ik"],
                  "strataLabels": ["0H", "2H"]}
        classes = {2: OrderedDict([("K", {"name": "K", "parent": "P", "path": ["P", "K"],
                                           "members": {"a", "b", "c", "d"}})])}
        rows = {"a": 0, "b": 1, "c": 2, "d": 3}
        out = CA.permutationClassTest(Y, factor, classes, rows, nPerm=50, seed=1)
        entry = out["levels"][2]["K"]
        self.assertEqual(len(entry["eff"]), 2)
        self.assertIsNotNone(entry["eff"][0])
        self.assertGreater(entry["eff"][0], 1.0)

    def test_nsig_counts_at_the_callers_alpha(self):
        Y = np.random.default_rng(7).normal(size=(3, 12)) * 0.1
        Y[0, self.level == 1] += 3.0                        # one member responds hard
        factor = {"columnLevel": self.level, "strata": self.strata, "levels": ["Ctr", "Ik"],
                  "strataLabels": ["0H", "2H"]}
        classes = {2: OrderedDict([("K", {"name": "K", "parent": "P", "path": ["P", "K"],
                                           "members": {"a", "b", "c"}})])}
        rows = {"a": 0, "b": 1, "c": 2}
        strict = CA.permutationClassTest(Y, factor, classes, rows, nPerm=50, seed=1, alpha=1e-12)
        loose = CA.permutationClassTest(Y, factor, classes, rows, nPerm=50, seed=1, alpha=0.05)
        self.assertEqual(strict["levels"][2]["K"]["nsig"], 0)
        self.assertEqual(loose["levels"][2]["K"]["nsig"], 1)
        self.assertEqual(loose["alpha"], 0.05)


if __name__ == "__main__":
    unittest.main()
