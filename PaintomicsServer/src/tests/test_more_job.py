#!/usr/bin/env python3
"""Behavioural cover for src/classes/JobInstances/MOREJob.py.

The class arrived with the MORE-v2 merge with no tests. Three of its four
methods are currently called from nowhere in the tree -- only
``addRegulatoryOmic`` has a caller (MOREServlet.py:107). That makes them easy
to get wrong unnoticed, which is exactly why they are pinned down here before
anyone wires them up.

Defects this file drove out
---------------------------
1. ``getTargetExpressionFile`` hardcoded the literal "gene expression" while
   the class also carries a ``self.targetOmicName`` attribute documented as
   the target omic. Setting ``targetOmicName`` had no effect whatsoever -- the
   attribute was written once in __init__ and read nowhere in the codebase.
   Now the lookup uses it. Default behaviour is unchanged, because
   "Gene Expression".lower() is the string that was hardcoded.

2. ``getTargetExpressionFile`` called ``.lower()`` on ``omic.get("omicName", "")``.
   The default only applies when the key is *absent*; a key present and set to
   None returned None and raised AttributeError.

3. ``getJobDescription`` indexed ``o['name']``, raising KeyError on a
   regulator dict without that key -- reachable for any job restored from a
   partial Mongo document, since parseBSON does no shape validation.

Known limitation deliberately pinned, not fixed
-----------------------------------------------
``MOREJob.results`` does not survive persistence. MOREJobDAO.insert/update
call ``toBSON(recursive=False)``, and Job.toBSON only copies non-dict
attributes in that mode; Job.parseBSON likewise skips dict values. Nothing in
the tree writes to ``results`` today, so this loses no data yet -- but it will
silently drop everything the moment someone populates it. The test below
records the trap rather than changing Job.toBSON, whose behaviour every other
job type also depends on.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_job
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.MOREJob import MOREJob


class FakeMainJob(object):
    """Stand-in for PathwayAcquisitionJob -- only the one accessor is used."""

    def __init__(self, omics):
        self._omics = omics

    def getGeneBasedInputOmics(self):
        return self._omics


def makeJob():
    return MOREJob("job123", "user1", "/tmp")


class DefaultsTest(unittest.TestCase):
    """The R backend reads these straight off the instance, so a changed
    default silently changes every user's model."""

    def test_model_defaults(self):
        job = makeJob()
        self.assertEqual(job.method, "PLS1")
        self.assertEqual(job.alpha, 0.05)
        self.assertEqual(job.vip, 0.8)
        self.assertEqual(job.filter_r2, 0.0)
        self.assertEqual(job.enrichment, "genes")
        self.assertEqual(job.targetOmicName, "Gene Expression")

    def test_collections_start_empty(self):
        job = makeJob()
        self.assertEqual(job.regulatoryOmics, [])
        self.assertEqual(job.results, {})
        self.assertIsNone(job.conditionsFile)
        self.assertIsNone(job.targetExpressionFile)
        self.assertIsNone(job.load_model_path)

    def test_two_jobs_do_not_share_mutable_state(self):
        """A list default on the class rather than in __init__ would alias."""
        a, b = makeJob(), makeJob()
        a.addRegulatoryOmic("miRNA", "m.tsv", "miRNA")
        self.assertEqual(b.regulatoryOmics, [])


class AddRegulatoryOmicTest(unittest.TestCase):

    def test_records_every_field_the_r_backend_reads(self):
        job = makeJob()
        job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA",
                              associationsFile="a.tsv", relevantFile="r.tsv",
                              minVariation=0.1)
        self.assertEqual(job.regulatoryOmics, [{
            "name": "miRNA", "file": "m.tsv", "type": "miRNA",
            "associations": "a.tsv", "relevant": "r.tsv", "minVariation": 0.1,
        }])

    def test_optional_arguments_default_to_none_for_r_null(self):
        job = makeJob()
        job.addRegulatoryOmic("TF", "tf.tsv", "TF")
        entry = job.regulatoryOmics[0]
        self.assertIsNone(entry["associations"])
        self.assertIsNone(entry["relevant"])
        self.assertEqual(entry["minVariation"], 0.0)

    def test_appends_in_call_order(self):
        job = makeJob()
        job.addRegulatoryOmic("first", "1.tsv", "TF")
        job.addRegulatoryOmic("second", "2.tsv", "miRNA")
        self.assertEqual([o["name"] for o in job.regulatoryOmics],
                         ["first", "second"])


class GetTargetExpressionFileTest(unittest.TestCase):

    def test_finds_the_gene_expression_omic(self):
        main = FakeMainJob([{"omicName": "Gene Expression",
                             "inputDataFile": "genes.tsv"}])
        self.assertEqual(makeJob().getTargetExpressionFile(main), "genes.tsv")

    def test_match_is_case_insensitive(self):
        for name in ["gene expression", "GENE EXPRESSION", "Gene Expression"]:
            with self.subTest(name=name):
                main = FakeMainJob([{"omicName": name, "inputDataFile": "g.tsv"}])
                self.assertEqual(makeJob().getTargetExpressionFile(main), "g.tsv")

    def test_returns_none_when_absent(self):
        main = FakeMainJob([{"omicName": "Metabolomics", "inputDataFile": "m.tsv"}])
        self.assertIsNone(makeJob().getTargetExpressionFile(main))

    def test_returns_none_for_a_job_without_the_accessor(self):
        self.assertIsNone(makeJob().getTargetExpressionFile(object()))

    def test_empty_omic_list(self):
        self.assertIsNone(makeJob().getTargetExpressionFile(FakeMainJob([])))

    def test_honours_targetOmicName(self):
        """The attribute exists to name the target omic; it must be read."""
        job = makeJob()
        job.targetOmicName = "Proteomics"
        main = FakeMainJob([{"omicName": "Proteomics", "inputDataFile": "p.tsv"}])
        self.assertEqual(job.getTargetExpressionFile(main), "p.tsv")

    def test_a_none_omic_name_does_not_raise(self):
        """dict.get's default only fires on an absent key, not a None value."""
        main = FakeMainJob([{"omicName": None, "inputDataFile": "x.tsv"},
                            {"omicName": "Gene Expression", "inputDataFile": "g.tsv"}])
        self.assertEqual(makeJob().getTargetExpressionFile(main), "g.tsv")

    def test_a_missing_omic_name_key_does_not_raise(self):
        main = FakeMainJob([{"inputDataFile": "x.tsv"}])
        self.assertIsNone(makeJob().getTargetExpressionFile(main))

    def test_first_match_wins(self):
        main = FakeMainJob([{"omicName": "Gene Expression", "inputDataFile": "a.tsv"},
                            {"omicName": "Gene Expression", "inputDataFile": "b.tsv"}])
        self.assertEqual(makeJob().getTargetExpressionFile(main), "a.tsv")


class GetValidationErrorsTest(unittest.TestCase):
    """Nothing calls this yet. When something does, these are the contracts."""

    def _mainWithGeneExpression(self):
        return FakeMainJob([{"omicName": "Gene Expression",
                             "inputDataFile": "genes.tsv"}])

    def test_a_fully_configured_job_has_no_errors(self):
        job = makeJob()
        job.conditionsFile = "design.tsv"
        job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA")
        self.assertEqual(job.getValidationErrors(self._mainWithGeneExpression()), [])

    def test_reports_each_missing_input_separately(self):
        errors = makeJob().getValidationErrors(FakeMainJob([]))
        self.assertEqual(len(errors), 3)

    def test_missing_target_omic(self):
        job = makeJob()
        job.conditionsFile = "design.tsv"
        job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA")
        errors = job.getValidationErrors(FakeMainJob([]))
        self.assertEqual(len(errors), 1)
        self.assertIn("Gene Expression", errors[0])

    def test_missing_conditions_file(self):
        job = makeJob()
        job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA")
        errors = job.getValidationErrors(self._mainWithGeneExpression())
        self.assertEqual(len(errors), 1)
        self.assertIn("Design", errors[0])

    def test_missing_regulatory_omics(self):
        job = makeJob()
        job.conditionsFile = "design.tsv"
        errors = job.getValidationErrors(self._mainWithGeneExpression())
        self.assertEqual(len(errors), 1)
        self.assertIn("regulatory", errors[0])


class GetJobDescriptionTest(unittest.TestCase):

    def test_includes_the_model_parameters(self):
        job = makeJob()
        job.method = "MLR"
        job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA")
        desc = job.getJobDescription()
        self.assertIn("MLR", desc)
        self.assertIn("0.05", desc)
        self.assertIn("0.8", desc)
        self.assertIn("miRNA", desc)

    def test_lists_every_regulator(self):
        job = makeJob()
        job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA")
        job.addRegulatoryOmic("TF", "t.tsv", "TF")
        self.assertIn("miRNA, TF", job.getJobDescription())

    def test_no_regulators_still_renders(self):
        self.assertIn("MORE Analysis", makeJob().getJobDescription())

    def test_a_regulator_without_a_name_does_not_raise(self):
        """parseBSON validates no shape, so a partial document reaches here."""
        job = makeJob()
        job.regulatoryOmics = [{"file": "x.tsv"}, {"name": "TF"}]
        self.assertIn("TF", job.getJobDescription())


class PersistenceContractTest(unittest.TestCase):
    """MOREJobDAO.insert/update both use toBSON(recursive=False)."""

    def test_scalar_and_list_configuration_survives(self):
        job = makeJob()
        job.conditionsFile = "design.tsv"
        job.method = "MLR"
        job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA", minVariation=0.1)

        bson = job.toBSON(recursive=False)
        for key in ("regulatoryOmics", "conditionsFile", "method", "alpha",
                    "vip", "filter_r2", "enrichment", "targetOmicName",
                    "targetExpressionFile", "load_model_path"):
            self.assertIn(key, bson, "%s must persist" % key)

    def test_round_trip_restores_configuration(self):
        job = makeJob()
        job.conditionsFile = "design.tsv"
        job.method = "MLR"
        job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA", minVariation=0.1)

        bson = job.toBSON(recursive=False)
        bson["_id"] = "irrelevant"
        restored = makeJob()
        restored.parseBSON(bson)

        self.assertEqual(restored.method, "MLR")
        self.assertEqual(restored.conditionsFile, "design.tsv")
        self.assertEqual(restored.regulatoryOmics[0]["minVariation"], 0.1)

    def test_results_is_dropped_by_persistence(self):
        """Documents a known trap, and fails loudly if it is ever fixed.

        `results` is a dict, and toBSON(recursive=False) copies only non-dict
        attributes. Nothing writes to `results` today so nothing is lost yet.
        If this test starts failing, persistence began working -- delete the
        test and the warning in the module docstring.
        """
        job = makeJob()
        job.results = {"miRNA": {"outputFile": "o.tsv"}}
        self.assertNotIn("results", job.toBSON(recursive=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
