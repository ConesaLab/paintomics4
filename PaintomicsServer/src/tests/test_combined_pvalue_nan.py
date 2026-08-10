#!/usr/bin/env python3
"""A NaN p-value must not become a NaN combined p-value.

Why this exists
---------------
`_usablePvalues` promises "the p-values in [0, 1]; anything else is not
evidence and is dropped", and it dropped everything except NaN. NaN is a float,
so it passed the type check, and both range comparisons are False for it --
`nan < 0` and `nan > 1` -- so it passed the range check too and came out the
other side as a usable p-value.

It WAS reachable from `calculateFisher`, which returned `hypergeom.sf(...)`
unfiltered, and that is NaN whenever the sample is larger than the population:

    calculateFisher(10, 20, 5, 8)  ->  nan      # before the domain clamp

`calculateFisher` no longer produces it: out-of-domain counts are clamped into
the hypergeometric domain and logged, because arriving there at all means two
of the four counts were tallied in different units, which is a bug in the
caller rather than in the user's data. The test below pins that new contract.

Everything else in this file stays. The clamp closes the one route that was
measured, not the class: `_usablePvalues` is the shared floor for a NaN
arriving from any other source, and removing its coverage because today's only
known producer was fixed is how the bug comes back.

That value was stored in the pathway's significanceValues and later combined.
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

    def test_calculate_fisher_no_longer_emits_the_nan_it_used_to(self):
        """The input that produced the NaN, now pinned to the new contract.

        A sample larger than the population is not a p-value question, it is a
        counting bug upstream. `calculateFisher` clamps such counts into the
        hypergeometric domain and returns a usable value rather than handing a
        NaN to jsonify, which would take the whole step-2 response down.
        """
        value = calculateFisher(10, 20, 5, 8)
        self.assertUsable(value, "calculateFisher(10, 20, 5, 8)")
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_out_of_domain_counts_are_not_silently_maximally_significant(self):
        """The other bad answer scipy gives: sf == 0, i.e. strongest evidence.

        More successes in the sample than exist in the population used to floor
        to 1e-300 and send a meaningless pathway to the top of the table, which
        is worse than the NaN because nothing downstream notices.
        """
        value = calculateFisher(2, 10, 1, 5)
        self.assertUsable(value, "calculateFisher(2, 10, 1, 5)")
        self.assertGreater(value, 1e-300,
                           "out-of-domain counts still produce the strongest "
                           "possible evidence instead of no evidence")

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


class FDRCorrectionNaNTest(unittest.TestCase):
    """The other half of the same bug, in the correction rather than the combine.

    `_usablePvalues` guards the combining functions. `adjustPvalues` is a
    separate path -- it hands the raw dict to statsmodels' multipletests, which
    propagates a NaN into every corrected value. One NaN among three p-values
    produced six non-finite numbers, both methods, all entries. Same
    consequence: jsonify writes them as the bare token `NaN` and the client
    rejects the whole response.

    Keys are kept rather than dropped because the caller subscripts them --
    `{adjust_method: pvalues[pathway_id] for ...}` would raise KeyError -- and
    come back as 1.0, which is what the rest of the module returns when there
    is nothing to go on.
    """

    def _adjust(self, mapping):
        from src.common.Statistics import adjustPvalues
        return adjustPvalues(mapping)

    def _values(self, result):
        return [v for method in result.values() for v in method.values()]

    def test_a_nan_does_not_reach_the_corrected_values(self):
        result = self._adjust({"a": 0.01, "b": NAN, "c": 0.5})

        offenders = [v for v in self._values(result)
                     if isinstance(v, float) and not math.isfinite(v)]
        self.assertEqual(offenders, [],
                         "%d corrected p-values are non-finite and would be "
                         "serialised as invalid JSON" % len(offenders))

    def test_every_key_survives(self):
        """The caller indexes the result by pathway id."""
        mapping = {"a": 0.01, "b": NAN, "c": 0.5}

        result = self._adjust(mapping)

        for method, corrected in result.items():
            with self.subTest(method=method):
                self.assertEqual(set(corrected), set(mapping),
                                 "a pathway disappeared from the correction, "
                                 "which raises KeyError in the caller")

    def test_an_unusable_pvalue_becomes_not_significant(self):
        result = self._adjust({"a": 0.01, "b": NAN})

        for method, corrected in result.items():
            with self.subTest(method=method):
                self.assertEqual(corrected["b"], 1.0,
                                 "an uncorrectable p-value should read as not "
                                 "significant, never as evidence")

    def test_dropping_a_nan_does_not_move_the_others(self):
        """The correction of the good values must be unaffected."""
        clean = self._adjust({"a": 0.01, "b": 0.5})["FDR BH"]
        withNaN = self._adjust({"a": 0.01, "b": 0.5, "c": NAN})["FDR BH"]

        for key in ("a", "b"):
            with self.subTest(key=key):
                self.assertAlmostEqual(clean[key], withNaN[key], places=12)

    def test_the_usable_subset_matches_statsmodels(self):
        """Checked against the library, not against this implementation."""
        from statsmodels.sandbox.stats.multicomp import multipletests

        expected = multipletests([0.01, 0.5], method="fdr_bh")[1].tolist()
        actual = self._adjust({"a": 0.01, "b": 0.5, "c": NAN})["FDR BH"]

        for key, value in zip(("a", "b"), expected):
            with self.subTest(key=key):
                self.assertAlmostEqual(actual[key], value, places=12)

    def test_all_unusable_is_not_an_error(self):
        result = self._adjust({"a": NAN, "b": INF})

        self.assertEqual(set(result["FDR BH"]), {"a", "b"})
        self.assertEqual(set(self._values(result)), {1.0})

    def test_an_empty_correction_is_still_empty(self):
        """The pre-existing ZeroDivisionError guard must keep working."""
        self.assertEqual(self._adjust({}), {"FDR BH": {}, "FDR BY": {}})



def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
