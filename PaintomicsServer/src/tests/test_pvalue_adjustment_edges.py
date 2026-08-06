#!/usr/bin/env python3
"""adjustPvalues must survive an analysis that matched nothing.

statsmodels' multipletests raises

    ZeroDivisionError: float division by zero

on an empty input, so a job whose features mapped to no pathway died in step 2
with a division error rather than reporting an empty result. Reached by
uploading features that are not in the organism's pathways -- a compound-only
job whose metabolites do not map will do it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_pvalue_adjustment_edges
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.Statistics import adjustPvalues


class AdjustPvaluesEdgeTest(unittest.TestCase):

    def test_empty_input_does_not_raise(self):
        self.assertEqual(adjustPvalues({}), {"FDR BH": {}, "FDR BY": {}})

    def test_empty_input_keeps_both_methods(self):
        # Callers index the result by method name; the shape must not change
        # just because there was nothing to correct.
        result = adjustPvalues({})
        self.assertIn("FDR BH", result)
        self.assertIn("FDR BY", result)

    def test_single_value_is_unchanged(self):
        result = adjustPvalues({"pw1": 0.5})
        self.assertAlmostEqual(result["FDR BH"]["pw1"], 0.5)

    def test_ordinary_input_still_corrected(self):
        # Benjamini-Hochberg on two values: the larger is p*n/rank capped at 1.
        result = adjustPvalues({"a": 0.01, "b": 0.5})
        self.assertAlmostEqual(result["FDR BH"]["a"], 0.02)
        self.assertAlmostEqual(result["FDR BH"]["b"], 0.5)

    def test_keys_are_preserved(self):
        result = adjustPvalues({"pw1": 0.01, "pw2": 0.2, "pw3": 0.9})
        self.assertEqual(sorted(result["FDR BH"]), ["pw1", "pw2", "pw3"])
        self.assertEqual(sorted(result["FDR BY"]), ["pw1", "pw2", "pw3"])

    def test_all_ones_do_not_raise(self):
        result = adjustPvalues({"a": 1.0, "b": 1.0})
        self.assertAlmostEqual(result["FDR BH"]["a"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
