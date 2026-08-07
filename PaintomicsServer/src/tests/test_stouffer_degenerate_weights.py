#!/usr/bin/env python3
"""A degenerate Stouffer weighting must not put NaN into a JSON response.

The Step 3 toolbar lets a user set a weight per omic before recombining
p-values. Those sliders are declared with minValue 0 (PA_Step3Views.js), so
every omic can be dragged to zero.

Stouffer's method divides by sqrt(sum(w**2)). With an all-zero weight vector
that is 0/0, and scipy returns NaN. The NaN reached jsonify, which writes it
as the bare token `NaN`:

    {"adjustedStoufferPvalues":{"KEGG":{"FDR BH":{"mmu04210":NaN}}},...}

`NaN` is not valid JSON (RFC 8259 admits no such literal). While the client
used eval() this parsed anyway; after the move to JSON.parse() the entire
response is rejected and the user gets

    Oops..Internal error! Unable to parse the error message.

Confirmed against the deployed server by POSTing all-zero weights to
/pa_adjust_pvalues and checking the raw bytes.

The guard returns 1.0 -- with no weight on any omic there is no evidence to
combine, and an absent p-value is stored as 1.0 elsewhere in the pipeline.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_stouffer_degenerate_weights
"""
import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.Statistics import calculateStoufferCombinedPvalue

PVALUES = [0.001, 0.02, 0.3]


class DegenerateWeightsTest(unittest.TestCase):

    def assertJsonSerialisable(self, value):
        """Strict JSON, the way a browser's JSON.parse reads it."""
        encoded = json.dumps({"p": value})

        def reject(constant):
            raise AssertionError(
                "response contains the bare token %s, which is not valid JSON "
                "and makes the client's JSON.parse reject the whole payload"
                % constant)

        json.loads(encoded, parse_constant=reject)

    def test_all_zero_weights_do_not_yield_NaN(self):
        """The exact case a user reaches by zeroing every slider."""
        result = calculateStoufferCombinedPvalue(PVALUES, [0.0, 0.0, 0.0])

        self.assertFalse(math.isnan(result), "all-zero weights still produce NaN")
        self.assertJsonSerialisable(result)
        self.assertEqual(result, 1.0)

    def test_single_omic_zero_weight(self):
        result = calculateStoufferCombinedPvalue([0.001], [0.0])

        self.assertFalse(math.isnan(result))
        self.assertJsonSerialisable(result)

    def test_no_pvalues_at_all(self):
        """Every omic in the pathway reported '-'."""
        result = calculateStoufferCombinedPvalue([], [1.0])

        self.assertFalse(math.isnan(result))
        self.assertJsonSerialisable(result)

    def test_ordinary_weights_are_unchanged(self):
        """The guard must not touch the normal path."""
        result = calculateStoufferCombinedPvalue(PVALUES, [1.0, 1.0, 1.0])

        self.assertTrue(0.0 <= result <= 1.0)
        self.assertNotEqual(result, 1.0, "a real combination should not hit the guard")
        self.assertJsonSerialisable(result)

    def test_one_zero_weight_among_others_still_combines(self):
        """Only a wholly-zero vector is degenerate."""
        result = calculateStoufferCombinedPvalue(PVALUES, [1.0, 0.0, 1.0])

        self.assertTrue(0.0 <= result < 1.0)
        self.assertJsonSerialisable(result)

    def test_pvalues_of_one_still_guarded(self):
        """The pre-existing NaN guard (p == 1) must survive."""
        result = calculateStoufferCombinedPvalue([1.0, 1.0], [1.0, 1.0])

        self.assertFalse(math.isnan(result))
        self.assertJsonSerialisable(result)

    def test_triplet_form_pvalues_are_accepted(self):
        """significanceValues arrive as [nFeatures, nRelevant, pValue]."""
        result = calculateStoufferCombinedPvalue(
            [[10, 2, 0.001], [10, 3, 0.02]], [0.0, 0.0])

        self.assertFalse(math.isnan(result))
        self.assertJsonSerialisable(result)

    def test_every_result_is_finite_across_a_weight_sweep(self):
        """No weight combination a slider can produce may break the response."""
        for weights in ([0, 0], [0, 1], [1, 0], [10, 0], [0, 10], [10, 10], [1, 1]):
            with self.subTest(weights=weights):
                result = calculateStoufferCombinedPvalue([0.001, 0.5], list(weights))
                self.assertTrue(math.isfinite(result),
                                "weights %s produced %r" % (weights, result))
                self.assertJsonSerialisable(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
