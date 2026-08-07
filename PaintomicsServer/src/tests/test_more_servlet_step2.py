#!/usr/bin/env python3
"""Cover for fromMOREtoGenes_STEP2 in src/servlets/MOREServlet.py.

STEP2 is the half that shells out to R. Until the MORE packaging was fixed it
could not be meaningfully tested -- every path led to an R call that could
never succeed -- so the behaviour worth pinning is what STEP2 does *around*
that call: pre-flight validation, the command it builds, how it reacts to a
non-zero exit, and how it turns R's output files into the basenames PA Step 1
consumes.

subprocess.Popen is replaced with a double that writes the files a real MORE
run would produce, so the whole post-processing path executes for real against
a temporary job directory. No R is involved and nothing touches the client
data tree.

Contracts pinned here
---------------------
* The R command carries one --min_variation token per omic, in --omic_names
  order. A misalignment would silently apply one omic's filter to another.
* A non-zero exit raises with R's captured output in the message; the operator
  needs the R error, not "exit 1".
* An omic whose file is None is rejected with a readable message rather than
  a TypeError out of os.path.join.
* Red stars are user-driven: with no user relevant-regulators file the
  relevant-regulator file must be written and EMPTY, matching miRNA2Genes.
  A non-empty file here would paint stars MORE never justified.
* The filters sidecar is written only alongside the rpc table, and carries the
  settings the Step-3 R2 slider locks onto.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_servlet_step2
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.MOREJob import MOREJob
from src.servlets import MOREServlet


class FakeResponse(object):
    """setStatus matters: handleException calls it before setContent, and the
    servlet's `finally: return RESPONSE` would swallow the AttributeError,
    leaving the failure invisible."""

    def __init__(self):
        self.content = None
        self.status = None

    def setContent(self, content):
        self.content = content

    def setStatus(self, status):
        self.status = status


class FakePopen(object):
    """Stands in for the Rscript process.

    `script` receives the parsed command and the output dir, so a test can make
    the fake "R run" produce whatever files it needs.
    """
    lastCommand = None
    returncode_to_use = 0
    output_lines = ["MORE: Analysis complete."]
    writer = None

    def __init__(self, cmd, **kwargs):
        FakePopen.lastCommand = list(cmd)
        self.returncode = FakePopen.returncode_to_use
        if FakePopen.writer:
            FakePopen.writer(list(cmd))
        self._lines = list(FakePopen.output_lines) + [""]
        self.stdout = self

    # -- minimal file-like behaviour the servlet uses --
    def readline(self):
        return self._lines.pop(0) if self._lines else ""

    def close(self):
        pass

    def wait(self):
        return self.returncode


class Step2TestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="more2_")
        self._realPopen = MOREServlet.subprocess.Popen
        self._realJIM = MOREServlet.JobInformationManager
        MOREServlet.subprocess.Popen = FakePopen
        MOREServlet.JobInformationManager = lambda: self

        FakePopen.lastCommand = None
        FakePopen.returncode_to_use = 0
        FakePopen.output_lines = ["MORE: Analysis complete."]
        FakePopen.writer = self.writeTypicalOutputs

        self.stored = []
        self.response = FakeResponse()
        self.job = self.makeJob()

    # JobInformationManager() stand-in
    def storeJobInstance(self, jobInstance, step):
        self.stored.append((jobInstance, step))

    def tearDown(self):
        MOREServlet.subprocess.Popen = self._realPopen
        MOREServlet.JobInformationManager = self._realJIM
        shutil.rmtree(self.tmp, ignore_errors=True)

    def makeJob(self, omics=None):
        job = MOREJob("JOB2", "u1", self.tmp + os.sep)
        job.initializeDirectories()
        job.date = "202601011200"
        job.method = "PLS1"
        job.alpha = 0.05
        job.vip = 0.8
        job.filter_r2 = 0.0

        inputDir = job.getInputDir()
        for fn in ("GeneExpression.tab", "Conditions.tab", "TF.tab"):
            with open(os.path.join(inputDir, fn), "w") as fh:
                fh.write("id\tS1\tS2\nA\t1\t2\n")
        job.targetExpressionFile = "GeneExpression.tab"
        job.conditionsFile = "Conditions.tab"
        for omic in (omics if omics is not None else [("TF", "TF.tab", None, "NA")]):
            name, dataFile, relevantFile, minVar = omic
            job.addRegulatoryOmic(name, dataFile, name,
                                  associationsFile=None, relevantFile=relevantFile,
                                  minVariation=minVar)
        return job

    def writeTypicalOutputs(self, cmd):
        """What a successful MORE run leaves in output_dir."""
        outDir = cmd[cmd.index("--output_dir") + 1]
        date = self.job.date
        for name in [o["name"].replace(" ", "_") for o in self.job.regulatoryOmics]:
            with open(os.path.join(outDir, "MORE_output_%s_%s.tab" % (name, date)), "w") as fh:
                fh.write("GENEA:::STAT3\t1.0\nGENEB:::NFKB1\t2.0\n")
            for prefix in ("MORE_relevant_assoc", "MORE_relevant_pairs"):
                open(os.path.join(outDir, "%s_%s_%s.tab" % (prefix, name, date)), "w").close()
        with open(os.path.join(outDir, "MORE_rpc_%s.tab" % date), "w") as fh:
            fh.write("targetF\tregulator\tomic\tR2\nGENEA\tSTAT3\tTF\t0.9\n")

    def run_step2(self):
        MOREServlet.fromMOREtoGenes_STEP2(self.job, "u1", self.response, {})
        return self.response.content


class PreflightValidationTest(Step2TestCase):

    def test_missing_target_file_is_reported(self):
        os.remove(os.path.join(self.job.getInputDir(), "GeneExpression.tab"))
        content = self.run_step2()
        self.assertFalse(content.get("success", False))
        self.assertIsNone(FakePopen.lastCommand, "R must not be invoked")

    def test_missing_conditions_file_is_reported(self):
        os.remove(os.path.join(self.job.getInputDir(), "Conditions.tab"))
        self.run_step2()
        self.assertIsNone(FakePopen.lastCommand)

    def test_missing_regulatory_file_is_reported(self):
        os.remove(os.path.join(self.job.getInputDir(), "TF.tab"))
        self.run_step2()
        self.assertIsNone(FakePopen.lastCommand)

    def test_empty_regulatory_file_is_rejected(self):
        """An empty upload would make MORE fail deep inside R instead."""
        open(os.path.join(self.job.getInputDir(), "TF.tab"), "w").close()
        self.run_step2()
        self.assertIsNone(FakePopen.lastCommand)

    def test_a_none_data_file_gives_a_message_not_a_typeerror(self):
        """STEP1 leaves "file" as None when neither upload nor location given."""
        self.job = self.makeJob(omics=[])
        self.job.addRegulatoryOmic("TF", None, "TF", minVariation="NA")
        self.run_step2()
        self.assertIsNone(FakePopen.lastCommand)


class OmicNameValidationTest(Step2TestCase):
    """--omic_names is a comma-joined list that runMORE.R splits on comma and
    pairs with --data_files, --assoc_files and --min_variation BY POSITION.

    Nothing checked the names against that encoding, and every way of breaking
    it failed badly:

      a comma in a name   R sees more omics than data files, indexes past the
                          end of data_paths, and dies on read_matrix(NA) with
                          "missing value where TRUE/FALSE needed"
      a blank name        strsplit drops a trailing empty field, so the last
                          omic disappears and its data file is never read --
                          a silently smaller analysis, not an error
      duplicate names     both omics write MORE_output_<name>_<date>.tab and
                          the second overwrites the first

    All three are now refused before R is invoked, which is what these assert:
    the message matters less than lastCommand staying None.
    """

    def addFile(self, name):
        path = os.path.join(self.job.getInputDir(), name)
        with open(path, "w") as fh:
            fh.write("id\tS1\tS2\nA\t1\t2\n")
        return name

    def test_a_comma_in_an_omic_name_is_refused(self):
        self.job = self.makeJob(omics=[("TF, ChIP", "TF.tab", None, "NA")])
        content = self.run_step2()
        self.assertFalse(content.get("success", False))
        self.assertIsNone(FakePopen.lastCommand, "R must not be invoked")

    def test_the_comma_message_names_the_offending_omic(self):
        self.job = self.makeJob(omics=[("TF, ChIP", "TF.tab", None, "NA")])
        content = self.run_step2()
        self.assertIn("TF, ChIP", str(content))

    def test_a_blank_omic_name_is_refused(self):
        self.job = self.makeJob(omics=[("", "TF.tab", None, "NA")])
        self.run_step2()
        self.assertIsNone(FakePopen.lastCommand)

    def test_a_whitespace_only_omic_name_is_refused(self):
        """runMORE.R trims, so "   " and "" reach R identically."""
        self.job = self.makeJob(omics=[("   ", "TF.tab", None, "NA")])
        self.run_step2()
        self.assertIsNone(FakePopen.lastCommand)

    def test_duplicate_omic_names_are_refused(self):
        self.job = self.makeJob(omics=[])
        self.addFile("TF2.tab")
        for dataFile in ("TF.tab", "TF2.tab"):
            self.job.addRegulatoryOmic("TF", dataFile, "TF", minVariation="NA")
        self.run_step2()
        self.assertIsNone(FakePopen.lastCommand)

    def test_names_colliding_only_after_sanitising_are_refused(self):
        """Both sides put gsub(" ", "_", name) in the filename, so "TF A" and
        "TF_A" are distinct names that produce the same output file."""
        self.job = self.makeJob(omics=[])
        self.addFile("TFA.tab")
        for name, dataFile in (("TF A", "TF.tab"), ("TF_A", "TFA.tab")):
            self.job.addRegulatoryOmic(name, dataFile, name, minVariation="NA")
        content = self.run_step2()
        self.assertIsNone(FakePopen.lastCommand)
        self.assertIn("TF_A", str(content))

    def test_distinct_names_still_run(self):
        """The guard must not reject the ordinary multi-omic job."""
        self.job = self.makeJob(omics=[])
        self.addFile("MIR.tab")
        for name, dataFile in (("TF", "TF.tab"), ("miRNA", "MIR.tab")):
            self.job.addRegulatoryOmic(name, dataFile, name, minVariation="NA")
        self.run_step2()
        self.assertIsNotNone(FakePopen.lastCommand)
        names = FakePopen.lastCommand[FakePopen.lastCommand.index("--omic_names") + 1]
        self.assertEqual(names, "TF,miRNA")

    def test_a_name_with_an_internal_space_still_runs(self):
        """Spaces are legal -- both sides map them to underscores identically.
        Only commas break the encoding."""
        self.job = self.makeJob(omics=[("Transcription Factors", "TF.tab", None, "NA")])
        self.run_step2()
        self.assertIsNotNone(FakePopen.lastCommand)


class CommandConstructionTest(Step2TestCase):

    def test_invokes_rscript_with_runmore(self):
        self.run_step2()
        self.assertEqual(FakePopen.lastCommand[0], "Rscript")
        self.assertTrue(FakePopen.lastCommand[1].endswith("runMORE.R"))

    def test_passes_the_model_parameters(self):
        self.run_step2()
        cmd = FakePopen.lastCommand
        self.assertEqual(cmd[cmd.index("--method") + 1], "PLS1")
        self.assertEqual(cmd[cmd.index("--alpha") + 1], "0.05")
        self.assertEqual(cmd[cmd.index("--vip") + 1], "0.8")

    def test_one_min_variation_token_per_omic_in_omic_name_order(self):
        """A misalignment silently applies one omic's filter to another."""
        self.job = self.makeJob(omics=[])
        inputDir = self.job.getInputDir()
        for fn in ("A.tab", "B.tab"):
            with open(os.path.join(inputDir, fn), "w") as fh:
                fh.write("id\tS1\nA\t1\n")
        self.job.addRegulatoryOmic("Aomic", "A.tab", "Aomic", minVariation="NA")
        self.job.addRegulatoryOmic("Bomic", "B.tab", "Bomic", minVariation=0.25)
        self.run_step2()
        cmd = FakePopen.lastCommand
        self.assertEqual(cmd[cmd.index("--omic_names") + 1], "Aomic,Bomic")
        self.assertEqual(cmd[cmd.index("--min_variation") + 1], "NA,0.25")

    def test_absent_association_file_is_passed_as_the_null_token(self):
        self.run_step2()
        cmd = FakePopen.lastCommand
        self.assertEqual(cmd[cmd.index("--assoc_files") + 1], "NULL")


class RFailureTest(Step2TestCase):

    def test_a_nonzero_exit_does_not_report_success(self):
        FakePopen.returncode_to_use = 1
        FakePopen.output_lines = ["MORE ERROR: something went wrong in R"]
        FakePopen.writer = None
        content = self.run_step2()
        self.assertFalse(content.get("success", False))

    def test_the_r_output_is_carried_into_the_failure(self):
        """"exit 1" alone is useless; the R text is the diagnostic."""
        FakePopen.returncode_to_use = 1
        FakePopen.output_lines = ["MORE ERROR: unused arguments"]
        FakePopen.writer = None
        content = self.run_step2()
        self.assertIn("unused arguments", json.dumps(content))

    def test_nothing_is_stored_when_r_fails(self):
        FakePopen.returncode_to_use = 1
        FakePopen.writer = None
        self.run_step2()
        self.assertEqual(self.stored, [])


class OutputProcessingTest(Step2TestCase):

    def test_reports_success_and_the_job_id(self):
        content = self.run_step2()
        self.assertTrue(content["success"])
        self.assertEqual(content["jobID"], "JOB2")

    def test_returns_basenames_not_paths(self):
        """saveFiles/parseGeneBasedFiles prepend inputDir themselves."""
        content = self.run_step2()
        for key in ("mainOutputFileName_0", "secondOutputFileName_0",
                    "thirdOutputFileName_0", "fourthOutputFileName_0"):
            self.assertNotIn(os.sep, content[key], key)

    def test_copies_r_outputs_into_inputdata(self):
        content = self.run_step2()
        self.assertTrue(os.path.exists(os.path.join(
            self.job.getInputDir(), content["mainOutputFileName_0"])))

    def test_names_each_omic_in_the_response(self):
        content = self.run_step2()
        self.assertEqual(content["omicName_0"], "TF")
        self.assertEqual(content["omicsCount"], 1)

    def test_no_user_relevant_file_yields_an_empty_relevant_regulator_file(self):
        """Red stars are user-driven. A non-empty file here paints stars MORE
        never justified, and skews the pathway enrichment for the omic."""
        content = self.run_step2()
        path = os.path.join(self.job.getInputDir(), content["secondOutputFileName_0"])
        self.assertTrue(os.path.exists(path))
        self.assertEqual(os.path.getsize(path), 0)

    def test_a_user_relevant_file_expands_to_gene_regulator_pairs(self):
        self.job = self.makeJob(omics=[("TF", "TF.tab", "userrel.txt", "NA")])
        with open(os.path.join(self.job.getInputDir(), "userrel.txt"), "w") as fh:
            fh.write("STAT3\n")
        content = self.run_step2()
        path = os.path.join(self.job.getInputDir(), content["secondOutputFileName_0"])
        with open(path) as fh:
            written = [l.strip() for l in fh if l.strip()]
        self.assertEqual(written, ["GENEA:::STAT3"],
                         "only pairs whose regulator the user flagged")

    def test_the_rpc_table_is_exposed_when_r_produced_it(self):
        content = self.run_step2()
        self.assertIn("regulationPerConditionFile", content)

    def test_the_rpc_field_is_omitted_when_r_produced_nothing(self):
        """The Step 3 panel keys off the field's absence to stay hidden."""
        def noRpc(cmd):
            self.writeTypicalOutputs(cmd)
            os.remove(os.path.join(cmd[cmd.index("--output_dir") + 1],
                                   "MORE_rpc_%s.tab" % self.job.date))
        FakePopen.writer = noRpc
        content = self.run_step2()
        self.assertNotIn("regulationPerConditionFile", content)

    def test_writes_the_filters_sidecar_next_to_the_rpc_table(self):
        self.job.filter_r2 = 0.35
        self.run_step2()
        path = os.path.join(self.job.getInputDir(),
                            "MORE_filters_%s.json" % self.job.date)
        self.assertTrue(os.path.exists(path))
        with open(path) as fh:
            meta = json.load(fh)
        self.assertEqual(meta["filter_r2"], 0.35)
        self.assertEqual(meta["method"], "PLS1")

    def test_bundles_a_results_archive(self):
        content = self.run_step2()
        self.assertTrue(content["compressedFileName"].endswith(".zip"))
        self.assertTrue(os.path.exists(os.path.join(
            self.job.getOutputDir(), content["compressedFileName"])))

    def test_stores_the_job_so_it_is_listable(self):
        self.run_step2()
        self.assertEqual(len(self.stored), 1)
        self.assertIs(self.stored[0][0], self.job)


if __name__ == "__main__":
    unittest.main(verbosity=2)
