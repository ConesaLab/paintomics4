#!/usr/bin/env python3
"""The region-based omic's input guard, which nothing exercised.

Why this exists
---------------
`Bed2GeneJob.validateInput` is the only thing standing between a malformed
region file and RGmatch. It was never named by any test, and neither was
`validateFile`. That matters more here than it looks, because of how the guard
reports: it does not raise on the first bad line, it *appends to a string* and
raises at the end only `if error != ""`. Any path that forgets to append is
therefore not a crash -- it is silent acceptance, and the job goes on to map
regions to genes from a file nobody checked.

The bundled example cannot test this. Example files are valid by construction,
and `validateFile` returns immediately when `isExample` is set, so the example
never even reaches the parsing code. Every case below is built from
`fake_omics`, which is the only way to reach it.

What is pinned:

  * the four numeric parameters, including the 0-100 bounds on the two
    percentages -- these reach RGmatch as region geometry
  * the >= 4 column floor on the values file (id, chr, start, then values)
  * ragged rows, non-numeric values, and a header missing its '#'
  * the relevant-features file's exact 3-column width
  * the 10-error cap, which exists so a badly formatted file does not build a
    megabyte-long message
  * a missing values file naming the omic, not raising KeyError

Usage:
    cd PaintomicsServer
    python -m src.tests.test_bed2genes_validation
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.Bed2GeneJob import Bed2GeneJob
from src.tests import fake_omics


class _Job(Bed2GeneJob):
    """A Bed2GeneJob whose input directory is a scratch dir we control.

    Subclassing rather than mocking keeps the real `validateInput` and
    `validateFile` under test; only the directory lookup is redirected.
    """

    def __init__(self, inputDir):
        self._inputDir = inputDir
        self.geneBasedInputOmics = []
        self.distance = 10000
        self.tss = 200
        self.promoter = 1300
        self.geneAreaPercentage = 50
        self.regionAreaPercentage = 50

    def getInputDir(self):
        return self._inputDir


class RegionOmicValidationTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="paintomics_bed_")
        self.job = _Job(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _use(self, dataFile, relevantFile=None):
        self.job.geneBasedInputOmics = [
            fake_omics.omicInput(dataFile, relevantFile, omicName="DNase-seq")]

    def _error(self):
        """Run the guard and return the message it refused with, or ''."""
        try:
            self.job.validateInput()
            return ""
        except Exception as exc:
            return str(exc)

    # -- the happy path, so a false rejection is caught too -----------------

    def test_a_well_formed_region_file_is_accepted(self):
        self._use(fake_omics.regionBasedFile(self.dir),
                  fake_omics.regionRelevantFile(self.dir))

        self.assertEqual(self._error(), "",
                         "a valid region-based omic was rejected")

    def test_a_values_file_with_no_relevant_sidecar_is_accepted(self):
        """The relevant-features file is optional."""
        self._use(fake_omics.regionBasedFile(self.dir))

        self.assertEqual(self._error(), "")

    # -- the numeric parameters --------------------------------------------

    def test_a_non_numeric_distance_is_refused(self):
        self._use(fake_omics.regionBasedFile(self.dir))
        self.job.distance = "not a number"

        self.assertIn("Distance", self._error())

    def test_a_non_numeric_tss_is_refused(self):
        self._use(fake_omics.regionBasedFile(self.dir))
        self.job.tss = ""

        self.assertIn("TSS", self._error())

    def test_a_non_numeric_promoter_distance_is_refused(self):
        self._use(fake_omics.regionBasedFile(self.dir))
        self.job.promoter = None

        self.assertIn("Promoter", self._error())

    def test_a_gene_area_percentage_above_100_is_refused(self):
        """A percentage is not merely a number; RGmatch reads it as a fraction."""
        self._use(fake_omics.regionBasedFile(self.dir))
        self.job.geneAreaPercentage = 150

        self.assertIn("Overlapped gene area", self._error())

    def test_a_negative_gene_area_percentage_is_refused(self):
        self._use(fake_omics.regionBasedFile(self.dir))
        self.job.geneAreaPercentage = -1

        self.assertIn("Overlapped gene area", self._error())

    def test_a_region_area_percentage_above_100_is_refused(self):
        self._use(fake_omics.regionBasedFile(self.dir))
        self.job.regionAreaPercentage = 101

        self.assertIn("Overlapped region area", self._error())

    def test_the_bounds_are_inclusive_at_both_ends(self):
        """0 and 100 are legal; only outside the range is not."""
        for value in (0, 100):
            self._use(fake_omics.regionBasedFile(self.dir))
            self.job.geneAreaPercentage = value
            self.job.regionAreaPercentage = value

            self.assertEqual(self._error(), "",
                             "%s%% was refused but is in range" % value)

    def test_every_bad_parameter_is_reported_not_just_the_first(self):
        """The guard accumulates, so a user fixes one round-trip, not four."""
        self._use(fake_omics.regionBasedFile(self.dir))
        self.job.distance = "x"
        self.job.tss = "y"

        error = self._error()
        self.assertIn("Distance", error)
        self.assertIn("TSS", error)

    # -- the values file ----------------------------------------------------

    def test_a_region_file_narrower_than_four_columns_is_refused(self):
        """id, chr, start and at least one value is the minimum shape."""
        self._use(fake_omics.regionFileWithTwoColumns(self.dir))

        self.assertIn("4 columns", self._error())

    def test_a_ragged_row_is_refused_and_names_its_line(self):
        self._use(fake_omics.raggedFile(self.dir, nConditions=5))

        error = self._error()
        self.assertIn("expected", error)
        self.assertIn("Line", error, "the message does not say which line")

    def test_a_non_numeric_value_is_refused(self):
        self._use(fake_omics.nonNumericValuesFile(self.dir, nConditions=5))

        self.assertIn("invalid values", self._error())

    def test_a_header_without_a_hash_is_refused(self):
        """The parser needs the hash to tell a header from a feature row."""
        self._use(fake_omics.headerWithoutHash(self.dir, nConditions=5))

        self.assertIn("HASH", self._error())

    def test_a_missing_values_file_is_refused_by_name(self):
        """A path typo must be a message, not a KeyError from the servlet."""
        self.job.geneBasedInputOmics = [{"omicName": "DNase-seq",
                                         "inputDataFile": "absent.tab",
                                         "isExample": False}]

        error = self._error()
        self.assertIn("absent.tab", error)
        self.assertIn("not found", error)

    def test_the_error_list_is_capped(self):
        """A wholly malformed file must not build an unbounded message."""
        self._use(fake_omics.manyBrokenLinesFile(self.dir, nConditions=6, nBroken=40))

        error = self._error()
        self.assertIn("Too many errors", error)
        self.assertLess(len(error), 4000,
                        "the refusal message grew without bound")

    # -- the relevant-features sidecar --------------------------------------

    def test_a_relevant_region_row_that_is_not_three_columns_is_refused(self):
        path = os.path.join(self.dir, "bad_relevant.tab")
        with open(path, "w") as handle:
            handle.write("region_1\tchr1\t1000\n")
            handle.write("region_2\tchr1\n")          # two columns
        self._use(fake_omics.regionBasedFile(self.dir), path)

        error = self._error()
        self.assertIn("expected 3 columns", error)

    def test_an_example_omic_skips_parsing_entirely(self):
        """isExample short-circuits; the file need not even exist."""
        self.job.geneBasedInputOmics = [{"omicName": "DNase-seq",
                                         "inputDataFile": "nothing_here.tab",
                                         "isExample": True}]

        self.assertEqual(self._error(), "",
                         "an example omic was parsed instead of trusted")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
