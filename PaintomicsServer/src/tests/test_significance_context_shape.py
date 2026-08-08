#!/usr/bin/env python3
"""`Pathway.significanceValues` is a list of per-condition triples, not one triple.

Why this exists
---------------
The real structure, built by `Pathway.addSignificanceValues` and filled in by
`setSignificancePvalue`, is

    significanceValues[omicName] = [[totalMatched, totalRelevant, pValue],   # condition 1
                                    [totalMatched, totalRelevant, pValue],   # condition 2
                                    ...]

`context_builder` read it as though it were a single flat triple whose third
slot happened to be a per-condition list:

    if len(vals) < 3:            # this is the CONDITION count, not a field count
        continue
    ... _numericValues(vals[2])  # this is the THIRD CONDITION, not the p-value

Both consumers feed the AI interpretation, and both fail silently rather than
raising:

  * `_count_significant_omics` sets `significant_omic_count`, which
    `triage_pathways` uses to decide which pathways are "major" and therefore
    worth deep investigation. With one or two conditions `len(vals) < 3` is
    true for every omic, so the count is always 0 and no pathway is ever major.
    With three or more it compares the feature *counts* against the p-value
    threshold -- and a totalMatched of 0 is `< 0.05`, so a pathway with nothing
    matched scores as significant.

  * `_format_significance` builds the `per_omic` line of the prompt. With three
    or more conditions it renders

        Gene expression: p=0.9000 ([2, 0, 0.8]/[2, 1, 0.7] relevant)

    where the two "counts" are whole triples printed as lists, and the p-value
    reported is the last condition's rather than the strongest.

So on a single-condition job the model is told nothing about significance, and
on a multi-condition job it is told something false. Neither raises, which is
why it survived: the AI pipeline runs to completion and produces a report.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_significance_context_shape
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Pathway import Pathway
from src.classes.AIInterpret.context_builder import (
    _count_significant_omics, _format_significance,
)


def _pathway(omicName="Gene expression", relevantPerFeature=None, pvalues=None):
    """A Pathway carrying the structure the real pipeline builds."""
    pathway = Pathway("mmu04210")
    for relevantList in (relevantPerFeature or [[True]]):
        pathway.addSignificanceValues(omicName, relevantList)
    if pvalues is not None:
        pathway.setSignificancePvalue(omicName, pvalues)
    return pathway


class StructureTest(unittest.TestCase):
    """State the shape plainly, so the consumers below can be read against it."""

    def test_significance_values_is_one_triple_per_condition(self):
        pathway = _pathway(relevantPerFeature=[[True, False, False],
                                               [False, False, True]],
                           pvalues=[0.7, 0.8, 0.9])

        values = pathway.significanceValues["Gene expression"]
        self.assertEqual(len(values), 3, "outer length is the condition count")
        for triple in values:
            self.assertEqual(len(triple), 3,
                             "each condition is [totalMatched, totalRelevant, pValue]")
        self.assertEqual([triple[2] for triple in values], [0.7, 0.8, 0.9])


class SignificantOmicCountTest(unittest.TestCase):

    def test_a_single_condition_omic_below_the_threshold_is_counted(self):
        """The common case. `len(vals) < 3` skipped every omic outright."""
        pathway = _pathway(relevantPerFeature=[[True]], pvalues=[0.001])

        self.assertEqual(_count_significant_omics(pathway), 1,
                         "a single-condition omic at p=0.001 was not counted, "
                         "so no pathway can ever be triaged as major")

    def test_a_two_condition_omic_below_the_threshold_is_counted(self):
        pathway = _pathway(relevantPerFeature=[[True, True]],
                           pvalues=[0.001, 0.002])

        self.assertEqual(_count_significant_omics(pathway), 1)

    def test_an_omic_significant_in_only_one_condition_is_counted(self):
        """A layer that responds at one timepoint is real signal."""
        pathway = _pathway(relevantPerFeature=[[True, False, False]],
                           pvalues=[0.001, 0.6, 0.9])

        self.assertEqual(_count_significant_omics(pathway), 1)

    def test_an_omic_significant_in_no_condition_is_not_counted(self):
        pathway = _pathway(relevantPerFeature=[[True, False, False]],
                           pvalues=[0.4, 0.6, 0.9])

        self.assertEqual(_count_significant_omics(pathway), 0)

    def test_a_pathway_matching_nothing_is_not_counted(self):
        """totalMatched of 0 is `< 0.05` if counts are read as p-values."""
        pathway = Pathway("mmu04210")
        pathway.significanceValues["Gene expression"] = [[0, 0, 1.0],
                                                         [0, 0, 1.0],
                                                         [0, 0, 1.0]]

        self.assertEqual(_count_significant_omics(pathway), 0,
                         "a pathway with nothing matched counted as significant "
                         "because its zero counts were compared to the threshold")

    def test_the_uncomputed_sentinel_is_not_read_as_a_p_value(self):
        """`Pathway` fills the p-value slot with -1.0 until one is written.

        `_conditionPvaluesOf` drops anything outside (0, 1] for this reason, and
        that filter had no test: -1.0 is below every threshold, so an omic whose
        p-values were never computed counted as significant and drove triage.
        Found by deleting the filter and watching the suite stay green.
        """
        pathway = Pathway("mmu04210")
        pathway.significanceValues["Gene expression"] = [[5, 2, -1.0],
                                                         [5, 2, -1.0]]

        self.assertEqual(_count_significant_omics(pathway), 0,
                         "the -1.0 'not computed yet' sentinel was compared "
                         "against the significance threshold and passed")

    def test_the_sentinel_is_not_printed_as_a_p_value(self):
        """The same filter keeps `p=-1.0000` out of the prompt."""
        pathway = Pathway("mmu04210")
        pathway.significanceValues["Gene expression"] = [[5, 2, -1.0]]

        self.assertNotIn("-1.0", _format_significance(pathway),
                         "the sentinel was rendered into the prompt as a "
                         "negative p-value")

    def test_a_real_p_value_beside_a_sentinel_still_counts(self):
        """Dropping the sentinel must not drop the condition that has a value."""
        pathway = Pathway("mmu04210")
        pathway.significanceValues["Gene expression"] = [[5, 2, -1.0],
                                                         [5, 2, 0.001]]

        self.assertEqual(_count_significant_omics(pathway), 1)

    def test_each_significant_omic_counts_once(self):
        pathway = _pathway(relevantPerFeature=[[True, True, True]],
                           pvalues=[0.001, 0.001, 0.001])
        pathway.addSignificanceValues("Proteomics", [True, True, True])
        pathway.setSignificancePvalue("Proteomics", [0.002, 0.9, 0.9])
        pathway.addSignificanceValues("Metabolomics", [True, True, True])
        pathway.setSignificancePvalue("Metabolomics", [0.5, 0.6, 0.7])

        self.assertEqual(_count_significant_omics(pathway), 2,
                         "expected gene expression and proteomics, not metabolomics")


class FormatSignificanceTest(unittest.TestCase):

    def test_a_single_condition_omic_is_described(self):
        pathway = _pathway(relevantPerFeature=[[True]], pvalues=[0.01])

        text = _format_significance(pathway)
        self.assertIn("Gene expression", text,
                      "a single-condition omic was omitted from the prompt")
        self.assertIn("0.0100", text)

    def test_the_strongest_condition_is_reported(self):
        pathway = _pathway(relevantPerFeature=[[True, False, False]],
                           pvalues=[0.7, 0.8, 0.9])

        self.assertIn("0.7000", _format_significance(pathway),
                      "reported a condition other than the strongest")

    def test_the_counts_are_numbers_not_lists(self):
        """The garbage this fixes: whole triples printed as the counts."""
        pathway = _pathway(relevantPerFeature=[[True, False, False],
                                               [False, False, True]],
                           pvalues=[0.7, 0.8, 0.9])

        text = _format_significance(pathway)
        self.assertNotIn("[", text,
                         "a list was rendered where a feature count belongs: %r"
                         % text)

    def test_the_counts_match_the_data(self):
        """Two features matched, one relevant in condition 1."""
        pathway = _pathway(relevantPerFeature=[[True, False, False],
                                               [False, False, True]],
                           pvalues=[0.7, 0.8, 0.9])

        text = _format_significance(pathway)
        self.assertIn("2", text, "totalMatched of 2 is missing: %r" % text)

    def test_an_omic_with_no_pvalue_yet_is_skipped_not_crashed(self):
        """Slots start at the -1.0 sentinel before p-values are written."""
        pathway = _pathway(relevantPerFeature=[[True, True, True]])

        self.assertIsInstance(_format_significance(pathway), str)

    def test_every_omic_appears(self):
        pathway = _pathway(relevantPerFeature=[[True]], pvalues=[0.01])
        pathway.addSignificanceValues("Metabolomics", [True])
        pathway.setSignificancePvalue("Metabolomics", [0.02])

        text = _format_significance(pathway)
        self.assertIn("Gene expression", text)
        self.assertIn("Metabolomics", text)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
