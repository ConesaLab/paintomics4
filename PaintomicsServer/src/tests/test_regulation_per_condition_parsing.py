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
class FakeGene(object):
    """Enough of Gene for the symbol pass: an ID, a name, and omicsValues."""

    def __init__(self, geneID, name):
        self.geneID = geneID
        self._name = name
        self.omicsValues = []

    def getName(self):
        return self._name


class FakeOmicValue(object):
    """One omicsValue hanging off a gene.

    The field naming is misleading and the code says so: on a *regulator*
    value, `inputName` is the TARGET's user-input ID, `originalName` is the
    regulator's display symbol, and `regulatorID` is its canonical ID (empty
    when the mapper resolved nothing). Only regulatorID -> originalName is a
    regulator symbol; keying off inputName would put the regulator's symbol on
    the target.
    """

    def __init__(self, inputName="", originalName="", regulatorID="",
                 isRegulator=False):
        self.inputName = inputName
        self.originalName = originalName
        self.regulatorID = regulatorID
        self.isRegulator = isRegulator


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

    def test_symbols_map_target_ids_to_gene_names(self):
        """Step 7 builds an ID -> symbol map so the panel shows names.

        The rpc table is verbatim from R and carries whatever IDs the user
        supplied. Without this map the Step-3 Regulator-Target Network renders
        raw identifiers, which is a usable-but-poor panel -- so the failure is
        quiet, and worth pinning.
        """
        self.declareMoreOmic()
        self.job.inputGenesData = {"G1": FakeGene("G1", "BRCA1")}
        self.writeRpc(["targetF", "regulator", "omic", "R2"],
                      ["G1", "TFA", "TF", "0.9"])
        data = self.parse()
        self.assertEqual(data["symbols"].get("G1"), "BRCA1")

    def test_symbols_cover_regulators_carried_as_omics_values(self):
        """Regulators arrive as omicsValues hanging off a gene, not as
        top-level entries. An earlier version walked only the top-level dict
        and missed them wholesale -- typically over half the rpc IDs."""
        self.declareMoreOmic()
        gene = FakeGene("G1", "BRCA1")
        gene.omicsValues = [FakeOmicValue(inputName="G1", originalName="STAT3",
                                          regulatorID="TFA", isRegulator=True)]
        self.job.inputGenesData = {"G1": gene}
        self.writeRpc(["targetF", "regulator", "omic", "R2"],
                      ["G1", "TFA", "TF", "0.9"])
        data = self.parse()
        self.assertEqual(data["symbols"].get("TFA"), "STAT3")

    def test_an_unresolved_regulator_contributes_no_symbol(self):
        """regulatorID == "" means the mapper found no symbol; emitting it
        would only produce an identity entry."""
        gene = FakeGene("G1", "BRCA1")
        gene.omicsValues = [FakeOmicValue(inputName="G1", originalName="TFA",
                                          regulatorID="", isRegulator=True)]
        self.declareMoreOmic()
        self.job.inputGenesData = {"G1": gene}
        self.writeRpc(["targetF", "regulator", "omic", "R2"],
                      ["G1", "TFA", "TF", "0.9"])
        self.assertNotIn("TFA", self.parse()["symbols"])

    def test_a_non_regulator_omics_value_maps_the_target_not_a_regulator(self):
        """7.a-ii: inputName is the TARGET id as the user typed it, so it maps
        to the gene's own name -- mapping it to a regulator symbol would put
        the wrong label in the Target column."""
        gene = FakeGene("71706", "BRCA1")
        gene.omicsValues = [FakeOmicValue(inputName="ENSMUSG00000029650")]
        self.declareMoreOmic()
        self.job.inputGenesData = {"71706": gene}
        self.writeRpc(["targetF", "regulator", "omic", "R2"],
                      ["ENSMUSG00000029650", "TFA", "TF", "0.9"])
        self.assertEqual(self.parse()["symbols"].get("ENSMUSG00000029650"), "BRCA1")

    def test_symbols_are_restricted_to_ids_the_rpc_mentions(self):
        """The map is embedded in the Mongo document, so an organism with a
        large inputGenesData must not drag every gene in with it."""
        self.declareMoreOmic()
        self.job.inputGenesData = {
            "G1": FakeGene("G1", "BRCA1"),
            "G2": FakeGene("G2", "TP53"),
        }
        self.writeRpc(["targetF", "regulator", "omic", "R2"],
                      ["G1", "TFA", "TF", "0.9"])
        data = self.parse()
        self.assertIn("G1", data["symbols"])
        self.assertNotIn("G2", data["symbols"])

    def test_a_gene_without_a_name_contributes_no_symbol(self):
        self.declareMoreOmic()
        self.job.inputGenesData = {"G1": FakeGene("G1", None)}
        self.writeRpc(["targetF", "regulator", "omic", "R2"],
                      ["G1", "TFA", "TF", "0.9"])
        data = self.parse()
        self.assertNotIn("G1", data["symbols"])

    def test_a_row_cap_protects_the_mongo_document(self):
        """Step 6 caps the table at 100_000 rows and flags it.

        The cap exists because the whole table is embedded in the job's Mongo
        document, and a runaway model -- every target against every regulator
        -- can produce far more rows than that. Existing tests only ever assert
        `truncated` is False, so the cap itself and the flag that tells the
        client the view is partial were never executed. Silently exceeding the
        document limit fails the job at save time, long after the analysis.
        """
        self.declareMoreOmic()
        path = os.path.join(self.inputDir, "MORE_rpc_%s.tab" % DATE)
        with open(path, "w") as fh:
            fh.write("targetF\tregulator\tomic\tR2\n")
            for i in range(100_001):
                fh.write("G%d\tTF%d\tTF\t0.9\n" % (i, i))
        data = self.parse()
        self.assertEqual(len(data["rows"]), 100_000)
        self.assertTrue(data["truncated"])

    def test_exactly_the_cap_is_not_reported_as_truncated(self):
        # The comparison is strictly greater-than, so the boundary row count
        # must come through whole and unflagged.
        self.declareMoreOmic()
        path = os.path.join(self.inputDir, "MORE_rpc_%s.tab" % DATE)
        with open(path, "w") as fh:
            fh.write("targetF\tregulator\tomic\tR2\n")
            for i in range(100_000):
                fh.write("G%d\tTF%d\tTF\t0.9\n" % (i, i))
        data = self.parse()
        self.assertEqual(len(data["rows"]), 100_000)
        self.assertFalse(data["truncated"])

    def test_an_unparseable_rpc_file_is_logged_not_raised(self):
        """A malformed table must not take the pathway analysis down with it.

        This runs at the end of a completed pathway job; letting the exception
        escape would discard work that already succeeded, to lose a panel that
        is supplementary. The row counts here differ per line, which is what
        makes the C parser give up rather than silently pad.
        """
        self.declareMoreOmic()
        path = os.path.join(self.inputDir, "MORE_rpc_%s.tab" % DATE)
        with open(path, "w") as fh:
            fh.write("targetF\tregulator\tomic\tR2\n")
            fh.write("G1\tTFA\tTF\t0.9\n")
            fh.write("G2\tTFB\tTF\t0.8\textra\tcolumns\there\n")
        self.assertIsNone(self.parse())
        self.assertIsNone(getattr(self.job, "regulationPerConditionData", None))

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
