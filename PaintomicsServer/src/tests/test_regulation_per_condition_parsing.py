#!/usr/bin/env python3
"""Cover for PathwayAcquisitionJob.parseRegulationPerCondition.

This is the seam between MORE's R output and the Step-3 Regulator-Target
Network panel. It finds MORE's combined RegulationPerCondition table by
reconstructing its filename from a date seed scraped off the job's own omic
filenames, parses it, and hands the client {columns, rows, filters}.

Two things make it worth pinning:

* It self-skips when MORE was not run. Every non-MORE job calls this, so a
  skip that turned into an exception would break ordinary pathway analyses
  that have nothing to do with MORE.
* It must stay schema-agnostic. MLR's rpc table carries an extra
  "representative" column that PLS1's does not, and the number of Group_*
  columns varies with the experimental design. Anything that hard-codes a
  column list breaks one method or the other -- silently, since the panel
  just renders whatever columns it is handed.

The NaN convention is deliberate and easy to "tidy" into a bug: string cells
emit "" while Group_* cells emit None. None on a string column would be run
through str() by DAO.adaptBSON and reach the UI as the literal "None".

Usage:
    cd PaintomicsServer
    python -m src.tests.test_regulation_per_condition_parsing
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

DATE = "202601011200"


def hasPandas():
    try:
        import pandas  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(hasPandas(), "pandas is required by the parser under test")
class RegulationPerConditionTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rpc_")
        self.job = PathwayAcquisitionJob("JOB1", "u1", self.tmp + os.sep)
        self.job.initializeDirectories()
        self.inputDir = self.job.getInputDir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def declareMoreOmic(self, fileName="MORE_output_TF_%s.tab" % DATE):
        """Give the job an omic whose filename carries the MORE date seed."""
        self.job.geneBasedInputOmics = [{
            "omicName": "TF", "inputDataFile": fileName,
        }]

    def writeRpc(self, header, *rows):
        path = os.path.join(self.inputDir, "MORE_rpc_%s.tab" % DATE)
        with open(path, "w") as fh:
            fh.write("\t".join(header) + "\n")
            for row in rows:
                fh.write("\t".join(row) + "\n")
        return path

    def parse(self):
        self.job.parseRegulationPerCondition()
        return self.job.regulationPerConditionData

    # -- self-skip -------------------------------------------------------
    def test_a_job_without_more_is_skipped_silently(self):
        """Every ordinary pathway analysis reaches this call."""
        self.job.geneBasedInputOmics = [
            {"omicName": "Gene expression", "inputDataFile": "genes.tab"}]
        self.assertIsNone(self.parse())

    def test_no_omics_at_all_is_skipped(self):
        self.job.geneBasedInputOmics = []
        self.assertIsNone(self.parse())

    def test_a_missing_rpc_file_is_skipped_not_raised(self):
        """STEP2 omits the rpc when MORE found no regulations."""
        self.declareMoreOmic()
        self.assertIsNone(self.parse())

    def test_the_date_seed_is_recognised_on_any_more_filename(self):
        for fname in ("MORE_output_TF_%s.tab" % DATE,
                      "MORE_relevant_pairs_TF_%s.tab" % DATE,
                      "MORE_relevant_assoc_TF_%s.tab" % DATE,
                      "MORE_relevant_reg_TF_%s.tab" % DATE):
            with self.subTest(fname=fname):
                self.setUp()
                self.declareMoreOmic(fname)
                self.writeRpc(["targetF", "regulator", "omic", "R2"],
                              ["G1", "TFA", "TF", "0.9"])
                self.assertIsNotNone(self.parse())

    # -- parsing ---------------------------------------------------------
    def test_reads_rows_and_columns(self):
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "omic", "Group_1_0", "R2"],
                      ["G1", "TFA", "TF", "0.5", "0.9"],
                      ["G2", "TFB", "TF", "-1.5", "0.8"])
        data = self.parse()
        self.assertEqual(data["columns"],
                         ["targetF", "regulator", "omic", "Group_1_0", "R2"])
        self.assertEqual(len(data["rows"]), 2)
        self.assertFalse(data["truncated"])

    def test_group_columns_become_numeric(self):
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "Group_1_0"],
                      ["G1", "TFA", "0.5"])
        data = self.parse()
        value = data["rows"][0][data["columns"].index("Group_1_0")]
        self.assertIsInstance(value, float)
        self.assertAlmostEqual(value, 0.5)

    def test_an_mlr_table_with_its_extra_column_is_accepted(self):
        """MLR adds "representative"; PLS1 has no such column."""
        self.declareMoreOmic()
        self.writeRpc(
            ["targetF", "regulator", "omic", "area", "representative",
             "Group_1_0", "Group_0_1", "R2"],
            ["G1", "TFA", "TF", "", "yes", "0.5", "0.6", "0.9"])
        data = self.parse()
        self.assertIn("representative", data["columns"])
        self.assertEqual(len(data["rows"]), 1)

    def test_any_number_of_group_columns_is_accepted(self):
        """One Group_* column per experimental design contrast."""
        self.declareMoreOmic()
        header = ["targetF", "regulator"] + ["Group_%d_0" % i for i in range(6)]
        self.writeRpc(header, ["G1", "TFA"] + ["0.1"] * 6)
        data = self.parse()
        self.assertEqual(len(data["columns"]), len(header))

    def test_rows_missing_a_target_or_regulator_are_dropped(self):
        """Those two are what the panel joins on; a blank one is unusable."""
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "R2"],
                      ["G1", "TFA", "0.9"],
                      ["", "TFB", "0.8"],
                      ["G3", "", "0.7"])
        data = self.parse()
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0][0], "G1")

    def test_an_empty_table_yields_an_empty_row_set_not_none(self):
        """The panel distinguishes 'MORE ran and found nothing' from 'no MORE'."""
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "R2"])
        data = self.parse()
        self.assertIsNotNone(data)
        self.assertEqual(data["rows"], [])

    # -- NaN convention --------------------------------------------------
    def test_a_missing_string_cell_becomes_empty_string_not_none(self):
        """None would come back from adaptBSON as the literal "None"."""
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "area", "Group_1_0"],
                      ["G1", "TFA", "", "0.5"])
        data = self.parse()
        self.assertEqual(data["rows"][0][data["columns"].index("area")], "")

    def test_a_missing_numeric_cell_becomes_none(self):
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "Group_1_0"],
                      ["G1", "TFA", ""])
        data = self.parse()
        self.assertIsNone(data["rows"][0][data["columns"].index("Group_1_0")])

    # -- filters sidecar -------------------------------------------------
    def test_the_filters_sidecar_is_attached_when_present(self):
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "R2"], ["G1", "TFA", "0.9"])
        with open(os.path.join(self.inputDir, "MORE_filters_%s.json" % DATE), "w") as fh:
            json.dump({"filter_r2": 0.35, "alpha": 0.05,
                       "vip": 0.8, "method": "PLS1"}, fh)
        data = self.parse()
        self.assertEqual(data["filters"]["filter_r2"], 0.35)
        self.assertEqual(data["filters"]["method"], "PLS1")

    def test_an_absent_sidecar_leaves_filters_none(self):
        """Jobs predating the sidecar must still open; view uses defaults."""
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "R2"], ["G1", "TFA", "0.9"])
        self.assertIsNone(self.parse()["filters"])

    def test_a_corrupt_sidecar_does_not_break_the_table(self):
        self.declareMoreOmic()
        self.writeRpc(["targetF", "regulator", "R2"], ["G1", "TFA", "0.9"])
        with open(os.path.join(self.inputDir, "MORE_filters_%s.json" % DATE), "w") as fh:
            fh.write("{not json")
        data = self.parse()
        self.assertIsNotNone(data)
        self.assertEqual(len(data["rows"]), 1)
        self.assertIsNone(data["filters"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
