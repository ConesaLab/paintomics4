#!/usr/bin/env python3
"""Two well-formed omics of different widths are refused by NAME, once.

The behaviour this guards
-------------------------
PaintOmics paints every omic on one set of conditions, so
`PathwayAcquisitionJob.validateInput` fixes `nConditions` from the first
values file it reads and then holds every other omic to it. That rule is
right. What it said was not: a guest on 2026-08-27 (job q603AOxICD) submitted a
proteomics table of `proteinID, FC` beside a lipidomics table of twelve samples
and two means, and was refused with

    Errors detected while processing lipidomica_samples.tab:
      Line 1:Expected 2 columns but found 15;
      Line 2:Expected 2 columns but found 15;
      ... (ten of them)
    Too many errors detected while processing lipidomica_samples.tab, skipping remaining lines...

-- which names neither the rule nor the omic the "2" came from, and blames a
file that has nothing wrong with it. The client's per-file check had passed
both files with a green tick, so from where the user stood the server had
refused a valid file for no reason. Reproduced locally and on paintomics.uv.es.

Now the ten lines become one sentence that names both omics, both files and
both widths. Everything else is unchanged: a file whose OWN lines vary in width
is ragged, and still gets its per-line report; the file that fixed the width
can only be ragged, never "disagreeing with itself".

Usage:
    cd PaintomicsServer
    python -m src.tests.test_mixed_width_omics_are_named
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.tests import fake_omics


class _JobCase(unittest.TestCase):

    def setUp(self):
        self._tmpRoot = tempfile.mkdtemp(prefix="paintomics_widths_") + "/"
        self.job = PathwayAcquisitionJob(jobID="widths", userID=None,
                                         CLIENT_TMP_DIR=self._tmpRoot)
        self.inputDir = self.job.getInputDir()
        os.makedirs(self.inputDir, exist_ok=True)
        self.job.geneBasedInputOmics = []
        self.job.compoundBasedInputOmics = []

    def tearDown(self):
        shutil.rmtree(self._tmpRoot, ignore_errors=True)

    def _error(self):
        try:
            self.job.validateInput()
            return ""
        except Exception as exc:
            return str(exc)


class MixedWidthOmicsAreNamedTest(_JobCase):

    def _reportedCase(self):
        """Proteomics id+FC (2 columns) beside Metabolomics id+14 (15 columns)."""
        proteomics = fake_omics.proteomicsFile(self.inputDir, "vp_fc_values.tab",
                                               nFeatures=12, nConditions=1)
        lipids = fake_omics.metabolomicsFile(self.inputDir, "lipidomica_samples.tab",
                                             nFeatures=12, nConditions=14)
        self.job.geneBasedInputOmics = [
            fake_omics.omicInput(proteomics, omicName="Proteomics")]
        self.job.compoundBasedInputOmics = [
            fake_omics.omicInput(lipids, omicName="Metabolomics")]

    def test_the_rule_and_both_omics_are_named(self):
        self._reportedCase()
        error = self._error()
        self.assertIn("same number of conditions", error)
        self.assertIn("[b]Proteomics[/b] (vp_fc_values.tab) has 1 condition column", error)
        self.assertIn("[b]Metabolomics[/b] (lipidomica_samples.tab) has 14 condition columns", error)

    def test_the_per_line_wall_is_gone(self):
        self._reportedCase()
        error = self._error()
        self.assertNotIn("Expected 2 columns but found 15", error)
        self.assertNotIn("Too many errors", error)
        self.assertNotIn("[li]", error)

    def test_order_does_not_change_who_is_named_first(self):
        """The omic that fixed the width is always the reference, whichever
        loop it sits in: with the wide file first the narrow one disagrees."""
        lipids = fake_omics.geneExpressionFile(self.inputDir, "wide.tab",
                                               nFeatures=12, nConditions=14)
        proteomics = fake_omics.metabolomicsFile(self.inputDir, "narrow.tab",
                                                 nFeatures=12, nConditions=1)
        self.job.geneBasedInputOmics = [fake_omics.omicInput(lipids, omicName="Gene expression")]
        self.job.compoundBasedInputOmics = [fake_omics.omicInput(proteomics, omicName="Metabolomics")]
        error = self._error()
        self.assertIn("[b]Gene expression[/b] (wide.tab) has 14 condition columns, but "
                      "[b]Metabolomics[/b] (narrow.tab) has 1 condition column", error)

    def test_a_ragged_file_keeps_its_per_line_report(self):
        """Varying widths inside ONE file are a broken file, not a disagreement."""
        first = fake_omics.geneExpressionFile(self.inputDir, "first.tab", nConditions=3)
        ragged = fake_omics.raggedFile(self.inputDir, "ragged.tab", nConditions=3)
        self.job.geneBasedInputOmics = [
            fake_omics.omicInput(first, omicName="Gene expression"),
            fake_omics.omicInput(ragged, omicName="Proteomics")]
        error = self._error()
        self.assertIn("Expected 4 columns but found 3", error)
        self.assertNotIn("same number of conditions", error)

    def test_the_file_that_fixed_the_width_cannot_disagree_with_itself(self):
        ragged = fake_omics.raggedFile(self.inputDir, "ragged.tab", nConditions=3)
        self.job.geneBasedInputOmics = [fake_omics.omicInput(ragged, omicName="Gene expression")]
        error = self._error()
        self.assertIn("Expected 4 columns but found 3", error)
        self.assertNotIn("same number of conditions", error)

    def test_a_value_fault_on_a_disagreeing_line_is_still_reported(self):
        """Collapsing the width fault must not swallow a different fault on
        the same line."""
        first = fake_omics.geneExpressionFile(self.inputDir, "first.tab", nConditions=1)
        bad = fake_omics.nonNumericValuesFile(self.inputDir, "bad.tab", nConditions=3)
        self.job.geneBasedInputOmics = [
            fake_omics.omicInput(first, omicName="Gene expression"),
            fake_omics.omicInput(bad, omicName="Proteomics")]
        error = self._error()
        self.assertIn("same number of conditions", error)
        self.assertIn("Line contains invalid values or symbols", error)
        self.assertNotIn("Expected 2 columns but found 4", error)

    def test_agreeing_omics_are_still_accepted(self):
        a = fake_omics.geneExpressionFile(self.inputDir, "a.tab", nConditions=3)
        b = fake_omics.metabolomicsFile(self.inputDir, "b.tab", nConditions=3)
        self.job.geneBasedInputOmics = [fake_omics.omicInput(a, omicName="Gene expression")]
        self.job.compoundBasedInputOmics = [fake_omics.omicInput(b, omicName="Metabolomics")]
        self.assertEqual(self._error(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
