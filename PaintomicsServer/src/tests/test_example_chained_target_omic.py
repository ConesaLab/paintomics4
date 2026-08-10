#!/usr/bin/env python3
"""The miRNA example must analyse both of its omics, not just the converted one.

Measured before this: job 3Z1q20I1rC registered `['miRNA-seq']` and returned
357 pathways, 0 of them significant. The manifest declares two omics for
`regulatory-mirna`,

    miRNA-seq        role=regulator  -> mirna_values.tab
    Gene expression  role=target     -> gene_expression_values.tab

but step 1 of a chained example is an ordinary upload of the conversion output
-- deliberately, see the guard in step1OnFormSubmitHandler and
test_example_mode_client_wiring -- so the target omic has no form field to
travel in and was silently dropped.

`ExampleDatasets.attachChainedExampleTargets` puts it back from the manifest.
These tests pin the three things that can go wrong with that:

  * it fires for a real miRNA-example conversion, using the description that
    MiRNA2GeneJob actually writes (built here by calling the real method, so a
    change to that format fails this test instead of silently disabling the fix)
  * it picks the RIGHT scenario -- both miRNA examples have a target file
    called gene_expression_values.tab, in different directories
  * it does nothing at all for an ordinary upload, for MORE and for the region
    example

Usage:
    cd PaintomicsServer
    python -m src.tests.test_example_chained_target_omic
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Job import Job
from src.classes.JobInstances.MiRNA2GeneJob import MiRNA2GeneJob
from src.common import ExampleDatasets

EXAMPLE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examplefiles")) + os.sep


def scenarioById(scenarioId):
    return ExampleDatasets.getScenario(EXAMPLE_DIR, scenarioId)


def omicByRole(scenario, role):
    return next(omic for omic in scenario["omics"] if omic.get("role") == role)


def conversionDescriptionFor(scenarioId):
    """The `configOptions` a real conversion of this scenario leaves behind.

    Built by the real MiRNA2GeneJob, from the real bundled paths, because the
    recognition in ExampleDatasets reads exactly this string: the client posts
    the conversion job's description back as `<omic>_config_args_N` and
    saveFiles stores it on the omic. If MiRNA2GeneJob ever stops naming the
    files it read, the fix stops working and this is where it shows up.
    """
    scenario = scenarioById(scenarioId)
    regulator = omicByRole(scenario, "regulator")
    target = omicByRole(scenario, "target")
    reference = scenario["references"][0]

    job = MiRNA2GeneJob("CONVERT01", None, "/tmp/")
    return job.getJobDescription(
        True,
        ExampleDatasets.absolutePath(EXAMPLE_DIR, regulator["dataFile"]),
        ExampleDatasets.absolutePath(EXAMPLE_DIR, regulator["relevantFile"]),
        ExampleDatasets.absolutePath(EXAMPLE_DIR, reference["dataFile"]),
        ExampleDatasets.absolutePath(EXAMPLE_DIR, target["dataFile"]))


def jobAfterConversion(omicName, configOptions,
                       dataFile="CONVERT01_regulator2Gene_output_202608091547_696.tab"):
    """A step-1 job as saveFiles leaves it for a chained submission."""
    job = Job("STEP1JOB01", None, "/tmp/")
    job.addGeneBasedInputOmic({
        "omicName": omicName,
        "inputDataFile": dataFile,
        "relevantFeaturesFile": "CONVERT01_regulator2Gene_relevant_202608091547_696.tab",
        "associationsFile": "CONVERT01_regulator_associations202608091547_696.tab",
        "relevantAssociationsFile": "CONVERT01_regulator_relevant_associations202608091547_696.tab",
        "configOptions": configOptions,
        "enrichment": "genes",
    })
    return job


class ManifestDeclaresTheRolesTest(unittest.TestCase):
    """Premise: the fix reads `role`, which nothing read before it."""

    def test_both_mirna_scenarios_declare_a_regulator_and_a_target(self):
        for scenarioId in ("regulatory-mirna", "stategra-mirna"):
            scenario = scenarioById(scenarioId)
            roles = [omic.get("role") for omic in scenario["omics"]]
            self.assertIn("regulator", roles, scenarioId)
            self.assertIn("target", roles, scenarioId)

    def test_applyScenario_now_carries_the_role_onto_the_job(self):
        job = MiRNA2GeneJob("CONVERT01", None, "/tmp/")
        ExampleDatasets.applyScenario(job, EXAMPLE_DIR, "regulatory-mirna")
        roles = {omic["omicName"]: omic.get("role")
                 for omic in job.getGeneBasedInputOmics()}
        self.assertEqual(roles, {"miRNA-seq": "regulator",
                                 "Gene expression": "target"})


# Copied out of the geneBasedInputOmics of job 3Z1q20I1rC, the job this defect
# was measured on. Not reconstructed: the client posts the description through
# a single-line text field, which drops the newlines MiRNA2GeneJob writes, so
# every basename but the first runs into the following label. Matching has to
# survive that, and this is the only place the real shape is written down.
MEASURED_CONFIG_OPTIONS = (
    "Input data:mirna_values.tab"
    "Input targets:mirna_relevant.tab"
    "Input gene expression:mirna_to_gene_associations.tab"
    "Input gene expression:gene_expression_values.tab"
    "Params:;Report=all;Score method=kendall;"
    "Selection method=negative_correlation;Cutoff=0.5;")


class ReattachTest(unittest.TestCase):

    def test_the_measured_job_would_now_get_two_omics(self):
        """The exact payload of job 3Z1q20I1rC: 357 pathways, 0 significant."""
        job = jobAfterConversion("miRNA-seq", MEASURED_CONFIG_OPTIONS,
                                 dataFile="G2NazEk1yY_regulator2Gene_output_"
                                          "202608091547_696.tab")
        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR),
            ["Gene expression"])
        self.assertEqual(
            [omic["omicName"] for omic in job.getGeneBasedInputOmics()],
            ["miRNA-seq", "Gene expression"])

    def test_the_regulatory_mirna_example_gets_its_target_back(self):
        job = jobAfterConversion("miRNA-seq",
                                 conversionDescriptionFor("regulatory-mirna"))

        attached = ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR)

        self.assertEqual(attached, ["Gene expression"])
        self.assertEqual([omic["omicName"] for omic in job.getGeneBasedInputOmics()],
                         ["miRNA-seq", "Gene expression"])

        target = job.getGeneBasedInputOmics()[1]
        expected = ExampleDatasets.absolutePath(
            EXAMPLE_DIR,
            "datasets/05-regulatory-mirna/data/gene_expression_values.tab")
        self.assertEqual(target["inputDataFile"], expected)
        self.assertTrue(os.path.isfile(target["inputDataFile"]))
        self.assertTrue(target["isExample"],
                        "without isExample the job looks for the file inside "
                        "its own input directory and finds nothing")
        self.assertEqual(target["role"], "target")
        self.assertTrue(os.path.isfile(target["relevantFeaturesFile"]))

    def test_the_stategra_example_gets_its_own_target_not_the_other_one(self):
        """Both targets are called gene_expression_values.tab.

        They live in different directories (05-regulatory-mirna and
        08-stategra-multiomics), so matching on that basename alone would
        attach whichever scenario the manifest happened to list first.
        """
        job = jobAfterConversion("miRNA unmapped",
                                 conversionDescriptionFor("stategra-mirna"))

        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR),
            ["Gene expression"])
        self.assertEqual(
            job.getGeneBasedInputOmics()[1]["inputDataFile"],
            ExampleDatasets.absolutePath(
                EXAMPLE_DIR,
                "datasets/08-stategra-multiomics/data/gene_expression_values.tab"))

    def test_an_omic_the_job_already_carries_is_not_replaced(self):
        job = jobAfterConversion("miRNA-seq",
                                 conversionDescriptionFor("regulatory-mirna"))
        job.addGeneBasedInputOmic({"omicName": "Gene expression",
                                   "inputDataFile": "my_own_values.tab"})

        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR), [])
        self.assertEqual(len(job.getGeneBasedInputOmics()), 2)
        self.assertEqual(job.getGeneBasedInputOmics()[1]["inputDataFile"],
                         "my_own_values.tab")

    def test_running_it_twice_does_not_duplicate_the_omic(self):
        """PART1 runs once per submission, but a duplicate omic name collides
        downstream (findInputOmicByName returns the first match)."""
        job = jobAfterConversion("miRNA-seq",
                                 conversionDescriptionFor("regulatory-mirna"))
        ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR)
        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR), [])
        self.assertEqual(len(job.getGeneBasedInputOmics()), 2)


class NoOpTest(unittest.TestCase):
    """Everything that is not a chained miRNA example must come out unchanged."""

    def test_an_ordinary_upload_is_untouched(self):
        job = Job("STEP1JOB01", None, "/tmp/")
        job.addGeneBasedInputOmic({
            "omicName": "Gene expression",
            "inputDataFile": "my_values.tab",
            "relevantFeaturesFile": "my_relevant.tab",
            "configOptions": "",
        })
        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR), [])
        self.assertEqual(len(job.getGeneBasedInputOmics()), 1)

    def test_a_users_own_mirna_conversion_is_untouched(self):
        """Same conversion, real data: the description names their files."""
        job = MiRNA2GeneJob("CONVERT02", "u1", "/tmp/")
        here = os.path.abspath(__file__)
        description = job.getJobDescription(True, here, here, here, here)

        step1 = jobAfterConversion("miRNA-seq", description)
        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(step1, EXAMPLE_DIR), [])
        self.assertEqual(len(step1.getGeneBasedInputOmics()), 1)

    def test_a_file_named_like_the_example_but_saved_under_a_job_prefix(self):
        """Guest uploads are saved as <jobID>_<name>, so the basenames differ.

        Whole-token matching is what keeps "X1_mirna_values.tab" from counting
        as "mirna_values.tab" and pulling the example's gene expression into
        somebody's own analysis.
        """
        scenario = scenarioById("regulatory-mirna")
        prefixed = " ".join(
            "Input:X1_" + os.path.basename(path)
            for path in ExampleDatasets.declaredFiles(scenario))
        job = jobAfterConversion("miRNA-seq", prefixed)
        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR), [])

    def test_the_more_example_never_attaches_its_target(self):
        """MORE's target is a per-sample matrix, an input to the joint model.

        It is declared under scenario["target"], not as an omic with
        role="target", so it cannot be reached from here -- and MORE's own
        output file is not a regulator2Gene_output_* one either.
        """
        scenario = scenarioById("regulatory-more")
        self.assertNotIn("target",
                         [omic.get("role") for omic in scenario["omics"]])
        self.assertEqual(ExampleDatasets._chainedFingerprint(scenario),
                         frozenset())

        job = Job("STEP1JOB01", None, "/tmp/")
        job.addGeneBasedInputOmic({
            "omicName": "Gene expression",
            "inputDataFile": "MORE_output_Gene_expression_202608091547.tab",
            "configOptions": "gene_expression_targets.tab;experimental_design.tab",
        })
        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR), [])

    def test_the_region_example_has_no_target_to_attach(self):
        scenario = scenarioById("region-based")
        self.assertEqual([omic.get("role") for omic in scenario["omics"]],
                         [None])
        self.assertEqual(ExampleDatasets._chainedFingerprint(scenario),
                         frozenset())

        job = Job("STEP1JOB01", None, "/tmp/")
        job.addGeneBasedInputOmic({
            "omicName": "DNase-seq",
            "inputDataFile": "CONVERT03_bed2genes_output_202608091547_1.tab",
            "configOptions": "dnase_regions_values.tab;synthetic_mmu.gtf",
        })
        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR), [])


class NeverFailsTheSubmissionTest(unittest.TestCase):
    """Not recognising an example must never break an ordinary job."""

    def test_a_missing_example_tree_is_survived(self):
        job = jobAfterConversion("miRNA-seq",
                                 conversionDescriptionFor("regulatory-mirna"))
        ExampleDatasets.clearCache()
        try:
            self.assertEqual(
                ExampleDatasets.attachChainedExampleTargets(
                    job, "/nonexistent/examplefiles/"),
                [])
        finally:
            ExampleDatasets.clearCache()

    def test_a_job_whose_omics_are_malformed_is_survived(self):
        job = Job("STEP1JOB01", None, "/tmp/")
        job.addGeneBasedInputOmic({"omicName": None, "inputDataFile": None})
        job.addGeneBasedInputOmic({})
        self.assertEqual(
            ExampleDatasets.attachChainedExampleTargets(job, EXAMPLE_DIR), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
