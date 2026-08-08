#!/usr/bin/env python3
"""A NaN p-value must not become a NaN combined p-value.

Why this exists
---------------
`_usablePvalues` promises "the p-values in [0, 1]; anything else is not
evidence and is dropped", and it dropped everything except NaN. NaN is a float,
so it passed the type check, and both range comparisons are False for it --
`nan < 0` and `nan > 1` -- so it passed the range check too and came out the
other side as a usable p-value.

It is reachable. `calculateFisher` returns `hypergeom.sf(...)`, which is NaN
whenever the sample is larger than the population:

    calculateFisher(10, 20, 5, 8)  ->  nan

That value is stored in the pathway's significanceValues and later combined.
Measured before the fix:

    calculateCombinedFisher([[5,2,nan],[5,2,0.2]])  ->  nan

What a NaN costs is out of proportion to it. `jsonify` writes it as the bare
token `NaN`, which is not valid JSON (RFC 8259), so the client's JSON.parse
rejects the *entire* response -- not just the affected pathway -- and the user
sees "Oops..Internal error! Unable to parse the error message".

That failure is already documented in `calculateStoufferCombinedPvalue`, which
carries an `isfinite` backstop for exactly it. Stouffer survived this input
because of that backstop. Fisher had none, so the same NaN went straight
through the same pipeline to the same broken response.

Fixed at the source -- `_usablePvalues` now drops non-finite values, which
covers both methods -- and Fisher gains the matching backstop for anything
degenerate arriving another way.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_combined_pvalue_nan
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.Statistics import (calculateCombinedFisher, calculateFisher,
                                   calculateStoufferCombinedPvalue)

NAN = float("nan")
INF = float("inf")


def _entry(pValue):
    """significanceValues rows are [nFeatures, nRelevant, pValue]."""
    return [5, 2, pValue]


class CombinedPvalueNaNTest(unittest.TestCase):

    def assertUsable(self, value, label):
        self.assertIsInstance(value, float, label)
        self.assertTrue(math.isfinite(value),
                        "%s produced %r, which jsonify writes as an invalid "
                        "JSON token and the client refuses to parse"
                        % (label, value))

    def test_calculate_fisher_really_can_return_nan(self):
        """The source of the NaN, so this is not a hypothetical input."""
        self.assertTrue(math.isnan(calculateFisher(10, 20, 5, 8)),
                        "calculateFisher no longer returns NaN for a sample "
                        "larger than the population; if that was fixed, the "
                        "reachability note in the docstring is now stale")

    def test_fisher_with_a_nan_pvalue(self):
        result = calculateCombinedFisher([_entry(NAN), _entry(0.2)])

        self.assertUsable(result, "calculateCombinedFisher")

    def test_fisher_with_every_pvalue_nan(self):
        """Nothing usable left: the same answer as an empty list."""
        self.assertEqual(calculateCombinedFisher([_entry(NAN), _entry(NAN)]), 1.0)

    def test_fisher_with_an_infinite_pvalue(self):
        result = calculateCombinedFisher([_entry(INF), _entry(0.2)])

        self.assertUsable(result, "calculateCombinedFisher")

    def test_stouffer_with_a_nan_pvalue(self):
        result = calculateStoufferCombinedPvalue([_entry(NAN), _entry(0.2)], [1, 1])

        self.assertUsable(result, "calculateStoufferCombinedPvalue")

    def test_a_nan_is_dropped_not_treated_as_significant(self):
        """Dropping must not quietly become "strongest possible evidence".

        The -1.0 sentinel comment warns about exactly this: clamping bad input
        into the arithmetic produces a maximally significant answer. A dropped
        NaN should leave the remaining evidence alone.
        """
        withNaN = calculateCombinedFisher([_entry(NAN), _entry(0.2)])
        aloneOnly = calculateCombinedFisher([_entry(0.2)])

        self.assertAlmostEqual(withNaN, aloneOnly, places=12,
                               msg="a dropped NaN changed the result, so it is "
                                   "still contributing something")

    def test_ordinary_input_is_unchanged(self):
        """The fix must not move a legitimate combined p-value.

        Checked against scipy's own combine_pvalues rather than a number copied
        from this implementation, so it is an independent result.
        """
        from scipy.stats import combine_pvalues

        pvalues = [0.01, 0.5, 0.2]
        expected = combine_pvalues(pvalues, method="fisher")[1]

        actual = calculateCombinedFisher([_entry(p) for p in pvalues])

        self.assertAlmostEqual(actual, expected, places=12)

    def test_the_sentinel_is_still_dropped(self):
        """-1.0 means "not computed yet" and must stay excluded."""
        withSentinel = calculateCombinedFisher([_entry(0.01), _entry(-1.0), _entry(0.2)])
        without = calculateCombinedFisher([_entry(0.01), _entry(0.2)])

        self.assertAlmostEqual(withSentinel, without, places=12)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
