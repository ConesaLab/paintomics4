#!/usr/bin/env python3
"""The AI pipeline's handling of per-condition p-values.

Multi-condition support turned several p-value slots from a float into one value
per condition. Each place that treats such a slot as a number is a crash, and
they have surfaced one at a time:

  context_builder._best_pval          min() returned a list -> format error
  verification._check_pvalues         f"{list:.4f}" -> format error
  context_builder._count_significant_omics   list < float -> TypeError

The third was found only by running the pipeline against a real six-condition
job; the shipped example uses single-column relevant files, so every earlier run
exercised lists of length one, where every one of these bugs is invisible.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_ai_multicondition
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.context_builder import (
    _count_significant_omics, _numericValues, _best_pval,
)
from src.conf.serverconf import AI_MAJOR_PATHWAY_MAX_PVAL


class _FakePathway(object):
    def __init__(self, significanceValues, combined=None):
        self.significanceValues = significanceValues
        self.combinedSignificancePvalues = combined or {}


SIG = AI_MAJOR_PATHWAY_MAX_PVAL / 10.0        # comfortably significant
NOT_SIG = min(0.9, AI_MAJOR_PATHWAY_MAX_PVAL * 10.0)


class CountSignificantOmicsTest(unittest.TestCase):

    def test_scalar_pvalue_still_counted(self):
        pw = _FakePathway({"Gene expression": [100, 20, SIG]})
        self.assertEqual(_count_significant_omics(pw), 1)

    def test_scalar_above_threshold_not_counted(self):
        pw = _FakePathway({"Gene expression": [100, 20, NOT_SIG]})
        self.assertEqual(_count_significant_omics(pw), 0)

    def test_six_condition_list_does_not_raise(self):
        # The crash: '<' not supported between instances of 'list' and 'float'.
        pw = _FakePathway({"Gene expression": [100, 20, [NOT_SIG] * 6]})
        self.assertEqual(_count_significant_omics(pw), 0)

    def test_significant_in_any_condition_counts(self):
        # A layer that responds at one timepoint is a real finding; requiring
        # every condition would discard the time-resolved results that
        # multi-condition analysis exists to surface.
        vals = [NOT_SIG] * 6
        vals[3] = SIG
        pw = _FakePathway({"Gene expression": [100, 20, vals]})
        self.assertEqual(_count_significant_omics(pw), 1)

    def test_counts_each_omic_once_not_each_condition(self):
        pw = _FakePathway({
            "Gene expression": [100, 20, [SIG] * 6],
            "Proteomics": [50, 10, [SIG] * 6],
            "miRNA-seq": [30, 5, [NOT_SIG] * 6],
        })
        self.assertEqual(_count_significant_omics(pw), 2)

    def test_short_row_is_skipped(self):
        pw = _FakePathway({"Gene expression": [100, 20]})
        self.assertEqual(_count_significant_omics(pw), 0)

    def test_none_and_strings_do_not_raise(self):
        pw = _FakePathway({
            "A": [1, 2, None],
            "B": [1, 2, "n/a"],
            "C": [1, 2, [None, SIG]],
        })
        self.assertEqual(_count_significant_omics(pw), 1)  # only C has a number


class NumericValuesTest(unittest.TestCase):

    def test_scalar(self):
        self.assertEqual(_numericValues(0.5), [0.5])

    def test_list(self):
        self.assertEqual(_numericValues([0.1, 0.2]), [0.1, 0.2])

    def test_filters_non_numbers(self):
        self.assertEqual(_numericValues([0.1, None, "x", 0.2]), [0.1, 0.2])

    def test_none(self):
        self.assertEqual(_numericValues(None), [])


class BestPvalTest(unittest.TestCase):

    def test_picks_the_strongest_condition(self):
        pw = _FakePathway({}, combined={"Fisher": [0.4, 0.02, 0.3, 0.9, 0.5, 1.0]})
        self.assertAlmostEqual(_best_pval(pw), 0.02)

    def test_scalar_combined(self):
        pw = _FakePathway({}, combined={"Fisher": 0.03})
        self.assertAlmostEqual(_best_pval(pw), 0.03)

    def test_result_is_formattable(self):
        # The original failure mode was a list reaching an f-string.
        pw = _FakePathway({}, combined={"Fisher": [0.4, 0.02]})
        self.assertIsInstance("%.4e" % _best_pval(pw), str)



class PvalueLabellingTest(unittest.TestCase):
    """The context must distinguish best-of-conditions from the global value.

    Reporting min(per-condition) under the bare name "combined p-value" made the
    narrative disagree with the results table, which headlines the global value:
    8.42e-4 against 1.80e-07 for mmu00910, with nothing to tell them apart.
    """

    def _pathway(self, combined, globals_):
        from src.classes.AIInterpret.context_builder import _conditionPvalues, _globalPval

        class _PW(object):
            def __init__(self):
                self.combinedSignificancePvalues = combined
            def getGlobalOmicPvalues(self):
                return globals_
        pw = _PW()
        return _conditionPvalues(pw), _globalPval(pw)

    def test_per_condition_list_is_exposed(self):
        conds, _ = self._pathway({"Fisher": [0.02, 0.01, 0.5]}, {})
        self.assertEqual(conds, [0.02, 0.01, 0.5])

    def test_single_condition_reports_no_per_condition_list(self):
        # Keeps single-condition prompts byte-for-byte unchanged.
        conds, _ = self._pathway({"Fisher": [0.02]}, {})
        self.assertEqual(conds, [])

    def test_scalar_reports_no_per_condition_list(self):
        conds, _ = self._pathway({"Fisher": 0.02}, {})
        self.assertEqual(conds, [])

    def test_global_pvalue_is_separate_from_best_condition(self):
        conds, glob = self._pathway(
            {"Fisher": [0.0265, 0.0150, 0.0079, 0.0032, 0.000842, 0.135]},
            {"Gene expression": 1.8041877590172827e-07})
        self.assertAlmostEqual(min(conds), 0.000842)
        self.assertAlmostEqual(glob, 1.8041877590172827e-07)
        self.assertNotAlmostEqual(min(conds), glob)

    def test_missing_globals_yield_none(self):
        _, glob = self._pathway({"Fisher": [0.02]}, {})
        self.assertIsNone(glob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
