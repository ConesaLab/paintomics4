#!/usr/bin/env python3
"""The combining statistics, checked against scipy and against nonsense input.

Why this exists
---------------
`Statistics.py` produces the numbers on the results page and in exported
tables -- the "Combined pValue (Fisher)" and "(Stouffer)" columns people sort
by and publish. Three of its seven functions had no test naming them, including
`calculateCombinedFisher`, which computes Fisher's method by hand:

    X^2 = -2 * sum(ln(p_i)),  df = 2k

A hand-rolled statistic with no reference check is worth pinning even when it
is right, because nothing else in the tree would notice it drifting. The first
class below compares it against `scipy.stats.combine_pvalues` and
`fisher_exact`, which are independent implementations.

The second class covers the input the guard was not written for. Fisher's
method needs `ln(p)`, so `calculateCombinedFisher` clamps with
`max(pVal, 1e-300)` to avoid `log(0)`. That is right for zero and wrong for
everything below it: a negative clamps *up* to 1e-300, the smallest positive
p-value the function admits, which is the **most** significant contribution
possible. `Pathway` initialises its p-value slot to the sentinel -1.0, so a
value that means "not computed yet" would read as "overwhelmingly significant"
-- one such slot drags a pathway from p=0.98 to p=6e-298 and straight to the
top of the table.

No reachable path through the current call sites was found: `calculateFisher`
always returns a float in (0, 1], and the one place the sentinel could survive
(the single-condition branch, which writes only slot 0) also reads only slot 0.
This is a guard on the function's own contract rather than a fix for an
observed failure -- but a p-value outside (0, 1] is not input this function can
do anything sensible with, and of the available wrong answers "maximally
significant" is the worst one to pick silently.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_statistics_reference
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from scipy.stats import combine_pvalues, fisher_exact

from src.common.Statistics import (
    adjustPvalues,
    calculateCombinedFisher,
    calculateCombinedSignificancePvalue,
    calculateCombinedSignificancePvalues,
    calculateFisher,
    calculateSignificance,
    calculateStoufferCombinedPvalue,
)


class AgainstScipyTest(unittest.TestCase):
    """Independent implementations, same answers."""

    # (population, successes in population, sample size, successes in sample)
    ENRICHMENTS = [(100, 20, 30, 10), (1000, 50, 80, 12),
                   (500, 100, 50, 20), (50, 5, 10, 3)]

    def test_the_enrichment_p_matches_fisher_exact(self):
        for M, K, N, k in self.ENRICHMENTS:
            with self.subTest(M=M, K=K, N=N, k=k):
                ours = calculateFisher(M, N, K, k)
                reference = fisher_exact([[k, N - k], [K - k, M - N - K + k]],
                                         alternative="greater")[1]

                self.assertAlmostEqual(ours, reference, places=12)

    def test_calculate_significance_dispatches_to_fisher(self):
        for M, K, N, k in self.ENRICHMENTS:
            with self.subTest(M=M):
                self.assertEqual(calculateSignificance("fisher", M, K, N, k),
                                 calculateFisher(M, N, K, k))

    def test_an_unknown_test_is_refused_rather_than_guessed(self):
        with self.assertRaises(NotImplementedError):
            calculateSignificance("chi2", 100, 20, 30, 10)

    def test_combined_fisher_matches_scipy(self):
        for pvalues in ([0.01, 0.02], [0.5, 0.5, 0.5],
                        [0.001, 0.2, 0.03, 0.4], [0.9, 0.8]):
            with self.subTest(pvalues=pvalues):
                self.assertAlmostEqual(calculateCombinedFisher(pvalues),
                                       combine_pvalues(pvalues, method="fisher")[1],
                                       places=12)

    def test_combining_one_p_value_returns_it_unchanged(self):
        """chi2.sf(-2 ln p, 2) == p. A useful invariant, and it holds."""
        for pvalue in (0.03, 0.5, 0.9):
            with self.subTest(pvalue=pvalue):
                self.assertAlmostEqual(calculateCombinedFisher([pvalue]),
                                       pvalue, places=12)

    def test_the_triple_form_and_the_bare_form_agree(self):
        """Callers pass [nFeatures, nRelevant, pValue] or just the p-value."""
        triples = [[10, 3, 0.01], [20, 5, 0.02]]

        self.assertAlmostEqual(calculateCombinedFisher(triples),
                               calculateCombinedFisher([0.01, 0.02]), places=12)

    def test_no_omic_to_combine_is_not_a_combination(self):
        self.assertIsNone(calculateCombinedSignificancePvalue("fisher-combined",
                                                              [0.01]))

    def test_both_methods_are_returned_together(self):
        result = calculateCombinedSignificancePvalues([0.01, 0.02], [1, 1])

        self.assertEqual(sorted(result), ["Fisher", "Stouffer"])
        self.assertAlmostEqual(result["Fisher"],
                               calculateCombinedFisher([0.01, 0.02]), places=12)


class OutOfRangeInputTest(unittest.TestCase):
    """A p-value is in (0, 1]. Anything else must not become "significant"."""

    def test_a_negative_p_value_does_not_become_the_strongest_evidence(self):
        """The -1.0 sentinel `Pathway` initialises its p-value slot with."""
        withSentinel = calculateCombinedFisher([0.5, -1.0])

        self.assertGreater(
            withSentinel, 1e-100,
            "a p-value of -1.0 was clamped up to 1e-300 and reported as "
            "p=%g -- an uncomputed slot outranked every real result" % withSentinel)
        self.assertLessEqual(withSentinel, 1.0)
        self.assertGreaterEqual(withSentinel, 0.0)
        # Ignored means combining the one real p-value, not combining two.
        self.assertAlmostEqual(withSentinel, calculateCombinedFisher([0.5]),
                               places=12,
                               msg="an out-of-range value should be dropped, "
                                   "not folded into the combination")

    def test_dropping_a_sentinel_also_drops_its_degree_of_freedom(self):
        """Fisher's df is 2k, so k must count the p-values actually used.

        Keeping the df at 2 while combining one p-value would report a pathway
        as *less* significant than the single value it was built from.
        """
        self.assertAlmostEqual(calculateCombinedFisher([0.03, -1.0]), 0.03,
                               places=12)

    def test_a_p_value_above_one_is_ignored_too(self):
        self.assertAlmostEqual(calculateCombinedFisher([0.5, 4.2]),
                               calculateCombinedFisher([0.5]), places=12)

    def test_zero_is_still_admitted_and_clamped(self):
        """log(0) is the case the clamp was written for; keep it working."""
        result = calculateCombinedFisher([0.5, 0.0])

        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 1.0)
        self.assertLess(result, calculateCombinedFisher([0.5]),
                        "p=0 must still count as strong evidence")

    def test_every_p_value_out_of_range_is_not_significant(self):
        self.assertEqual(calculateCombinedFisher([-1.0, -1.0]), 1.0)

    def test_stouffer_ignores_an_out_of_range_p_value(self):
        self.assertAlmostEqual(
            calculateStoufferCombinedPvalue([0.5, -1.0], [1, 1]),
            calculateStoufferCombinedPvalue([0.5], [1]), places=12)

    def test_an_empty_list_is_not_significant(self):
        self.assertEqual(calculateCombinedFisher([]), 1.0)


class AdjustPvaluesTest(unittest.TestCase):

    def test_both_correction_methods_are_returned(self):
        adjusted = adjustPvalues({"a": 0.01, "b": 0.02, "c": 0.5})

        self.assertEqual(sorted(adjusted), ["FDR BH", "FDR BY"])

    def test_correction_never_lowers_a_p_value(self):
        raw = {"a": 0.01, "b": 0.02, "c": 0.5, "d": 0.9}
        adjusted = adjustPvalues(raw)

        for method, corrected in adjusted.items():
            for key, value in corrected.items():
                self.assertGreaterEqual(value, raw[key] - 1e-12,
                                        "%s made %s more significant" % (method, key))

    def test_an_empty_analysis_corrects_to_nothing(self):
        self.assertEqual(adjustPvalues({}), {"FDR BH": {}, "FDR BY": {}})


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
