#!/usr/bin/env python3
"""One omic with nothing relevant must not silence every other omic.

Why this exists
---------------
`calculateStoufferCombinedPvalue` clamps each input with

    min(val, 0.9999999999)

because Stouffer's method converts a p-value with `norm.isf`, and `isf(1.0)` is
-inf. One such value drags the weighted sum to -inf and the combination comes
back NaN.

That clamp had no test. Removing it leaves the whole suite green -- and it is
not a cosmetic guard, because `calculateFisher` returns **exactly 1.0** whenever
an omic has no relevant features in a pathway:

    if foundSignificative == 0:
        return 1.0

which is an ordinary situation in a six-omic job. Measured, on the code as it
stands versus with that one expression deleted:

    five omics at p=0.001 plus one empty omic
        with the clamp     0.00010326
        without            1.00000000

    five omics at p=0.02 plus one empty omic
        with the clamp     0.05533478
        without            1.00000000

So deleting it takes a pathway from decisively significant to not significant at
all, silently, for exactly the pathways a multi-omics tool exists to find. The
NaN never surfaces because `calculateStoufferCombinedPvalue` has an `isfinite`
backstop that turns it into 1.0 -- the backstop keeps the response valid JSON,
which is what it is for, and in doing so hides the arithmetic failure behind a
plausible number.

These tests pin the behaviour rather than the implementation: a p-value of 1.0
must be absorbed without destroying the evidence around it, and the result must
stay finite and inside (0, 1].

Usage:
    cd PaintomicsServer
    python -m src.tests.test_stouffer_unit_pvalue_clamp
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.Statistics import (
    calculateFisher,
    calculateStoufferCombinedPvalue,
)


def _combine(pvalues):
    return calculateStoufferCombinedPvalue(pvalues, [1] * len(pvalues))


class UnitPvalueTest(unittest.TestCase):
    """p == 1.0 is what an omic with no relevant features contributes."""

    def test_an_omic_with_nothing_relevant_reports_exactly_one(self):
        """The premise: this is where the 1.0s come from."""
        self.assertEqual(calculateFisher(1000, 50, 100, 0), 1.0)

    def test_one_empty_omic_does_not_silence_five_strong_ones(self):
        combined = _combine([1.0, 0.001, 0.001, 0.001, 0.001, 0.001])

        self.assertLess(combined, 0.05,
                        "a single p=1.0 collapsed the combination to %r, "
                        "discarding five omics at p=0.001" % combined)

    def test_one_empty_omic_does_not_silence_five_moderate_ones(self):
        combined = _combine([1.0, 0.02, 0.02, 0.02, 0.02, 0.02])

        self.assertLess(combined, 1.0)
        self.assertGreater(combined, 0.0)

    def test_two_empty_omics_still_leave_a_usable_number(self):
        combined = _combine([1.0, 1.0, 0.001, 0.001, 0.001, 0.001])

        self.assertTrue(math.isfinite(combined))
        self.assertLess(combined, 1.0)

    def test_every_omic_empty_is_not_significant(self):
        self.assertAlmostEqual(_combine([1.0, 1.0, 1.0]), 1.0, places=6)

    def test_the_result_is_always_finite(self):
        """NaN reaches jsonify as the bare token NaN, which is not valid JSON."""
        for pvalues in ([1.0], [1.0, 1.0], [1.0, 0.5],
                        [1.0, 0.001, 1.0], [0.9999999999, 1.0]):
            with self.subTest(pvalues=pvalues):
                combined = _combine(pvalues)

                self.assertTrue(math.isfinite(combined),
                                "%r produced %r" % (pvalues, combined))

    def test_the_result_stays_in_range(self):
        for pvalues in ([1.0, 0.001], [1.0, 1.0], [0.5, 0.5], [1.0, 0.0]):
            with self.subTest(pvalues=pvalues):
                combined = _combine(pvalues)

                self.assertGreaterEqual(combined, 0.0)
                self.assertLessEqual(combined, 1.0)

    def test_more_evidence_still_moves_the_answer(self):
        """Ordering, not exact values: the guard must not flatten everything."""
        weak = _combine([1.0, 0.5, 0.5])
        strong = _combine([1.0, 0.001, 0.001])

        self.assertLess(strong, weak,
                        "stronger evidence did not produce a smaller combined "
                        "p-value; the unit clamp may be flattening the input")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
