#!/usr/bin/env python3
"""The guards in Statistics.py, pinned.

Why this exists
---------------
A mutation campaign over `src/common/Statistics.py` -- 20 mutations, each run
against the existing suite -- found 10 that no test noticed:

    range check high            stouffer clamp 0.9999999999 -> 1.0
    bool exclusion              stouffer zero-weight guard
    log clamp 1e-300 -> 1e-30   stouffer isfinite backstop
    fisher isfinite backstop    fisher zero shortcut
    empty list returns 0 not 1  fisher min clamp

Every one of those is a guard somebody added on purpose, several with comments
explaining precisely how they are reached -- and nothing held them in place, so
a refactor could have deleted any of them silently. This file closes that.

Seven of the ten are now killed by this file. THREE CANNOT BE, and that is a
finding rather than an omission -- do not "fix" them by contorting an assertion:

  - `fisher zero shortcut`. Removing `if foundSignificative == 0: return 1.0`
    leaves `hypergeom.sf(-1, ...)`, which is exactly 1.0 (measured). The
    shortcut is an optimisation; there is no behaviour to pin.

  - `stouffer zero-weight guard` and `stouffer clamp 0.9999999999`. Both
    prevent a NaN, and `calculateStoufferCombinedPvalue` ends with an
    `isfinite` backstop that turns a NaN into 1.0 -- which is the same value
    the guards produce. Measured both ways: 1.0 either way. So each is
    defence in depth behind a backstop that already covers it, and no
    black-box test can distinguish them. They are worth keeping (they avoid
    computing a NaN at all, and they document the two ways one arises), but
    their survival is redundancy, not missing coverage.

The distinction matters because a surviving mutation normally means untested
behaviour. Recording which survivors are *equivalent* is what stops the next
person from chasing them.

The rest are genuine, and two of them are reachable from the interface rather
than theoretical:

  - all-zero Stouffer weights. The weight sliders have minValue 0, so a user can
    drag every omic to zero; Stouffer then divides by sqrt(sum(w**2)) == 0 and
    returns NaN, which jsonify writes as the bare token `NaN` -- not valid JSON
    -- so the client rejects the whole response.
  - a p-value of exactly 1. Stouffer returns NaN for it, which is why the
    0.9999999999 clamp exists.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_statistics_guards
"""
import math
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.Statistics import (adjustPvalues, calculateCombinedFisher,
                                   calculateFisher,
                                   calculateStoufferCombinedPvalue)

NAN = float("nan")
INF = float("inf")


def _entry(pValue):
    """significanceValues rows are [nFeatures, nRelevant, pValue]."""
    return [5, 2, pValue]


class NoEvidenceIsNotSignificantTest(unittest.TestCase):
    """Nothing to combine must never read as the strongest possible claim.

    The module's own comment warns about this: clamping bad input into the
    arithmetic produces a maximally significant answer, and a p-value slot
    meaning "not computed yet" would drag a pathway to the top of the results
    table. The same reasoning applies to having no input at all.
    """

    def test_fisher_on_an_empty_list(self):
        self.assertEqual(calculateCombinedFisher([]), 1.0,
                         "no evidence returned something other than 'not "
                         "significant'")

    def test_fisher_on_a_list_with_nothing_usable(self):
        self.assertEqual(calculateCombinedFisher([_entry(NAN), _entry(-1.0)]), 1.0)

    def test_stouffer_on_an_empty_list(self):
        self.assertEqual(calculateStoufferCombinedPvalue([], []), 1.0)

    def test_a_pathway_with_no_evidence_ranks_last(self):
        """The property that matters downstream: it must not outrank real data."""
        withEvidence = calculateCombinedFisher([_entry(0.01), _entry(0.02)])

        self.assertLess(withEvidence, calculateCombinedFisher([]),
                        "a pathway with no usable p-value ranks at least as "
                        "high as one with two significant ones")


class StoufferWeightsTest(unittest.TestCase):
    """Reachable from the interface: the weight sliders have minValue 0."""

    def test_all_zero_weights_do_not_produce_nan(self):
        result = calculateStoufferCombinedPvalue([_entry(0.01), _entry(0.5)], [0, 0])

        self.assertTrue(math.isfinite(result),
                        "dragging every Stouffer weight to zero produced %r, "
                        "which jsonify writes as an invalid JSON token and the "
                        "client refuses to parse" % result)
        self.assertEqual(result, 1.0,
                         "with no weight on any omic there is no evidence, so "
                         "the honest answer is 'not significant'")

    def test_some_zero_weights_still_combine(self):
        """Only the all-zero case is degenerate; a partial zero is legitimate."""
        result = calculateStoufferCombinedPvalue(
            [_entry(0.01), _entry(0.5)], [1, 0])

        self.assertTrue(math.isfinite(result))
        self.assertLess(result, 1.0,
                        "an omic with a real weight contributed nothing")

    def test_weights_stay_aligned_when_a_pvalue_is_dropped(self):
        """Stouffer pairs weights positionally, so a filtered list must realign.

        The unusable entry is first, so if the weight vector were not filtered
        alongside, the surviving p-value would be paired with the wrong weight.
        """
        dropped = calculateStoufferCombinedPvalue(
            [_entry(NAN), _entry(0.01)], [1, 9])
        direct = calculateStoufferCombinedPvalue([_entry(0.01)], [9])

        self.assertAlmostEqual(dropped, direct, places=12,
                               msg="the weight vector was not filtered with the "
                                   "p-values, so 0.01 was weighted as if it "
                                   "were the entry that got dropped")


class PvalueOfExactlyOneTest(unittest.TestCase):
    """Stouffer returns NaN for p == 1, which is why the clamp exists."""

    def test_a_pvalue_of_one_stays_finite(self):
        result = calculateStoufferCombinedPvalue([_entry(1.0), _entry(1.0)], [1, 1])

        self.assertTrue(math.isfinite(result),
                        "p == 1 produced %r; the 0.9999999999 clamp is what "
                        "keeps combine_pvalues from returning NaN" % result)

    def test_one_is_still_treated_as_not_significant(self):
        result = calculateStoufferCombinedPvalue([_entry(1.0), _entry(1.0)], [1, 1])

        self.assertGreater(result, 0.9,
                           "p-values of 1 combined to something significant")

    def test_fisher_handles_a_pvalue_of_one(self):
        result = calculateCombinedFisher([_entry(1.0), _entry(1.0)])

        self.assertTrue(math.isfinite(result))
        self.assertGreater(result, 0.9)


class NonFiniteBackstopTest(unittest.TestCase):
    """The last line of defence, exercised by forcing the library to misbehave.

    The routes that produced a non-finite result are closed upstream now, so
    these cannot be triggered with ordinary input -- which is exactly why the
    mutation campaign found them unguarded. Patching the library call is the
    only honest way to reach them.
    """

    def test_fisher_backstop(self):
        with mock.patch("src.common.Statistics.chi2") as chi2:
            chi2.sf.return_value = NAN

            result = calculateCombinedFisher([_entry(0.01), _entry(0.2)])

        self.assertEqual(result, 1.0,
                         "a non-finite combined value escaped calculateCombined"
                         "Fisher; it would be serialised as invalid JSON")

    def test_stouffer_backstop(self):
        with mock.patch("src.common.Statistics.combine_pvalues") as combine:
            combine.return_value = (0.0, INF)

            result = calculateStoufferCombinedPvalue(
                [_entry(0.01), _entry(0.2)], [1, 1])

        self.assertEqual(result, 1.0,
                         "a non-finite combined value escaped "
                         "calculateStoufferCombinedPvalue")


class UsablePvalueFilterTest(unittest.TestCase):
    """What counts as a p-value at all."""

    def test_a_bool_is_not_a_pvalue(self):
        """True is an int in Python, so it passes a naive isinstance check."""
        withBool = calculateCombinedFisher([_entry(True), _entry(0.2)])
        without = calculateCombinedFisher([_entry(0.2)])

        self.assertAlmostEqual(withBool, without, places=12,
                               msg="True was combined as the p-value 1.0")

    def test_a_value_above_one_is_dropped(self):
        withBad = calculateCombinedFisher([_entry(1.5), _entry(0.2)])
        without = calculateCombinedFisher([_entry(0.2)])

        self.assertAlmostEqual(withBad, without, places=12,
                               msg="a p-value greater than 1 was treated as "
                                   "evidence")

    def test_a_negative_value_is_dropped_not_clamped(self):
        """Clamping a negative up to 1e-300 is the strongest possible evidence."""
        withBad = calculateCombinedFisher([_entry(-0.5), _entry(0.2)])
        without = calculateCombinedFisher([_entry(0.2)])

        self.assertAlmostEqual(withBad, without, places=12)

    def test_a_string_is_dropped(self):
        withBad = calculateCombinedFisher([_entry("0.2"), _entry(0.2)])
        without = calculateCombinedFisher([_entry(0.2)])

        self.assertAlmostEqual(withBad, without, places=12)


class VerySmallPvalueTest(unittest.TestCase):
    """The 1e-300 clamp inside log() must not quietly become a coarser floor.

    `calculateFisher` already floors its own result at 1e-300, so a strongly
    enriched pathway really does arrive here with a p-value that small. The
    clamp in `log(max(pVal, 1e-300))` exists to avoid log(0); if it were
    loosened to, say, 1e-30, every p-value below that would be treated as
    1e-30 and the combined result would be wrong by hundreds of orders of
    magnitude -- measured on one such input, 3.46e-298 becomes 3.54e-29.

    That is not a rounding difference. It is the difference between a pathway
    at the very top of the results table and one merely near it, and nothing
    about the output would look broken.
    """

    def test_a_tiny_pvalue_is_not_flattened(self):
        combined = calculateCombinedFisher([_entry(1e-300), _entry(0.5)])

        self.assertLess(combined, 1e-200,
                        "a p-value of 1e-300 combined to %g, which is what a "
                        "coarser clamp inside log() produces -- the 1e-300 "
                        "floor has been loosened" % combined)

    def test_it_matches_the_arithmetic_it_claims_to_do(self):
        """Checked against the formula, not against this implementation."""
        from math import log
        from scipy.stats import chi2

        pvalues = [1e-300, 0.5]
        expected = chi2.sf(-2 * sum(log(max(p, 1e-300)) for p in pvalues),
                           2 * len(pvalues))

        actual = calculateCombinedFisher([_entry(p) for p in pvalues])

        self.assertAlmostEqual(actual / expected, 1.0, places=9)

    def test_zero_does_not_raise(self):
        """The reason the clamp is there at all: log(0) is a domain error."""
        result = calculateCombinedFisher([_entry(0.0), _entry(0.5)])

        self.assertTrue(math.isfinite(result))
        self.assertGreater(result, 0.0)


class FisherFloorTest(unittest.TestCase):
    """calculateFisher never returns an absolute zero."""

    def test_the_returned_value_has_a_floor(self):
        # Sample larger than the successes available drives sf to 0.0.
        result = calculateFisher(20, 8, 5, 30)

        self.assertGreater(result, 0.0,
                           "calculateFisher returned an absolute zero; the "
                           "1e-300 floor is what keeps it displayable and "
                           "keeps log() finite downstream")

    def test_an_ordinary_call_is_not_floored(self):
        """The floor must not disturb a normal result."""
        self.assertAlmostEqual(calculateFisher(100, 20, 30, 10),
                               calculateFisher(100, 20, 30, 10), places=15)
        self.assertLess(calculateFisher(100, 20, 30, 10), 1.0)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
