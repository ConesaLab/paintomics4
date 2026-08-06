#!/usr/bin/env python3
"""Input validation must accept the multi-condition files it also demands.

validateFile enforced two rules on a relevant-features file that could not both
be satisfied:

  * the number of columns must equal the number of conditions in the values file
  * no line may exceed 80 characters

A relevant-features file for N conditions holds one identifier per condition per
row. With Ensembl gene IDs (18 characters) that is 18N + (N-1) characters:

    4 conditions ->  75  (passes)
    5 conditions ->  94  (rejected)
    6 conditions -> 113  (rejected)

so multi-condition analyses were impossible from five conditions upward with
ordinary identifiers -- the length rule was written when these files had a
single column and a line was one ID. The check is now applied per field, which
is what "this should look like a list of identifiers" actually means.

Confirmed against the deployed server: a real 6-condition job was rejected
before the change and afterwards produced 365 matched pathways, every one
carrying six distinct per-condition p-values.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_multicondition_validation
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

ENSEMBL_ID_WIDTH = 18  # ENSMUSG00000000001


def ensemblID(n):
    return "ENSMUSG%011d" % n


class RelevantFileLengthRuleTest(unittest.TestCase):

    def setUp(self):
        # validateFile resolves every filename against the job's input dir and
        # returns immediately for isExample omics, so the files have to live
        # there and the omic must not be flagged as an example -- otherwise the
        # assertions below pass without the checks ever running.
        self._tmpRoot = tempfile.mkdtemp() + "/"
        self.job = PathwayAcquisitionJob(jobID="validation", userID=None,
                                         CLIENT_TMP_DIR=self._tmpRoot)
        self._inputDir = self.job.getInputDir()
        os.makedirs(self._inputDir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpRoot, ignore_errors=True)

    def _relevantFile(self, nConditions, nRows=5, idWidth=ENSEMBL_ID_WIDTH):
        name = "rf_%dc_%dw.tab" % (nConditions, idWidth)
        with open(os.path.join(self._inputDir, name), "w") as handle:
            handle.write("\t".join("Cond%d" % c for c in range(nConditions)) + "\n")
            for r in range(nRows):
                row = []
                for c in range(nConditions):
                    base = ensemblID(r * nConditions + c)
                    row.append(base.ljust(idWidth, "X") if idWidth > len(base) else base)
                handle.write("\t".join(row) + "\n")
        return name

    def _validate(self, name, nConditions):
        """nConditions is the number of conditions in the values file."""
        inputOmic = {
            "omicName": "Gene expression",
            "relevantFeaturesFile": name,
            "inputDataFile": "",
        }
        return self.job.validateFile(inputOmic, nConditions + 1, "")

    def _lineWidth(self, nConditions):
        return nConditions * ENSEMBL_ID_WIDTH + (nConditions - 1)

    def test_six_conditions_exceeds_eighty_characters(self):
        # The premise: this file genuinely has lines over the old limit, so the
        # test below is exercising the rule rather than passing by accident.
        self.assertGreater(self._lineWidth(6), 80)

    def test_six_condition_file_is_accepted(self):
        _, error = self._validate(self._relevantFile(6), 6)
        self.assertNotIn("longer than 80", error)

    def test_five_condition_file_is_accepted(self):
        self.assertGreater(self._lineWidth(5), 80)
        _, error = self._validate(self._relevantFile(5), 5)
        self.assertNotIn("longer than 80", error)

    def test_four_condition_file_still_accepted(self):
        # Under the old limit too, so this guards against a regression the
        # other way.
        self.assertLess(self._lineWidth(4), 80)
        _, error = self._validate(self._relevantFile(4), 4)
        self.assertNotIn("longer than 80", error)

    def test_single_column_file_still_accepted(self):
        _, error = self._validate(self._relevantFile(1), 1)
        self.assertNotIn("longer than 80", error)

    def test_an_over_long_identifier_is_still_rejected(self):
        # The rule still does its job: one implausible field fails the file,
        # even though every line would have been short enough per column.
        path = self._relevantFile(2, nRows=3, idWidth=200)
        _, error = self._validate(path, 2)
        self.assertIn("longer than 80", error)

    def test_column_count_mismatch_is_still_reported(self):
        # The companion rule must keep working -- it is what catches someone
        # uploading a values file by mistake.
        _, error = self._validate(self._relevantFile(3), 6)
        self.assertIn("does not match the number of conditions", error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
