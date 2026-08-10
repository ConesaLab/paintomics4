#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Regression tests for the Regions2Genes (BED -> genes) association.

Run with:
    cd <repo root> && PYTHONPATH=PaintomicsServer \
        python3 PaintomicsServer/src/tests/test_bed2genes_association.py

The defect these tests pin: DHS_exon_association.run() reads its settings out
of an options dict with .get(key, default), so every key the caller spelled
differently was dropped in silence. Bed2GeneJob sent three such keys, and the
worst of them was "distance": the form asks for kb, run() compares bp, and the
kb->bp conversion existed only on the getopt path. Measured against the bundled
example data, distance=10 finds 0 associations and distance=10000 finds 900.
"""

import os
import shutil
import sys
import tempfile
import unittest

from multiprocessing import Process, Queue

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.classes.JobInstances.Bed2GeneJob import Bed2GeneJob
from src.common.bioscripts import DHS_exon_association
from src.common.bioscripts.DHS_exon_association import Candidate, RUN_OPTION_KEYS, run

EXAMPLE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examplefiles", "datasets",
    "07-region-based", "data"))

EXAMPLE_GTF      = os.path.join(EXAMPLE_DIR, "synthetic_mmu.gtf")
EXAMPLE_REGIONS  = os.path.join(EXAMPLE_DIR, "dnase_regions_values.tab")

# Measured on the bundled example: a 10 kb window associates 900 regions.
# Asserted as a floor rather than an equality so a future tweak to the example
# data does not fail the test for the wrong reason -- what matters is that the
# number is nowhere near zero.
EXPECTED_ASSOCIATION_ROWS = 900


def runInSubprocess(gtf, regions, outputFile, options, timeout=300):
    """Drive run() exactly the way Bed2GeneJob.fromBED2Genes does.

    run() writes its settings into module globals, so it has to be exercised in
    its own process or one test leaks its configuration into the next -- which
    is also why the production code runs it under multiprocessing.
    """
    managedQueue = Queue()
    worker = Process(target=run,
                     args=(gtf, regions, outputFile, None, options, managedQueue))
    worker.start()
    queueContent = managedQueue.get(True, timeout)
    worker.join(timeout)

    return queueContent


class TestBed2GeneJobOptions(unittest.TestCase):
    """Bed2GeneJob.getOptions() has to speak run()'s vocabulary."""

    def setUp(self):
        self.job = Bed2GeneJob("testJob", "testUser", tempfile.gettempdir())

    def test_distance_is_converted_from_kb_to_bp(self):
        # The form is labelled "Distance (kb)" and defaults to 10; run()
        # compares the value against genomic coordinates, in bp.
        self.job.distance = 10
        self.assertEqual(10000, self.job.getOptions()["distance"])

    def test_distance_conversion_survives_a_string_from_the_form(self):
        # formFields.get() hands back strings, and validateInput may not have
        # run yet when getOptions() is called from a test or a script.
        self.job.distance = "2"
        self.assertEqual(2000, self.job.getOptions()["distance"])

    def test_zero_distance_stays_zero(self):
        # 0 kb is a legitimate "overlap only" request, not a missing value.
        self.job.distance = 0
        self.assertEqual(0, self.job.getOptions()["distance"])

    def test_every_option_key_is_one_run_understands(self):
        # The bug in one assertion: "report" and "gene" are getopt flag names,
        # not option keys, so run() never saw the Report or GTF-tag settings.
        unknown = set(self.job.getOptions().keys()) - set(RUN_OPTION_KEYS)
        self.assertEqual(set(), unknown)

    def test_report_and_gene_tag_reach_run_under_the_names_it_reads(self):
        self.job.report = "transcript"
        self.job.geneIDtag = "gene_name"
        options = self.job.getOptions()

        self.assertEqual("transcript", options["level"])
        self.assertEqual("gene_name", options["gene_id_tag"])
        self.assertNotIn("report", options)
        self.assertNotIn("gene", options)

    def test_validateInput_rejects_an_unknown_report_level(self):
        self.job.report = "chromosome"
        self.job.geneBasedInputOmics = [{"inputDataFile": "missing.tab",
                                         "omicName": "DNase-seq",
                                         "isExample": True}]

        with self.assertRaises(Exception) as caught:
            self.job.validateInput()
        self.assertIn("Report must be one of", str(caught.exception))

    def test_validateInput_rejects_a_negative_distance(self):
        self.job.distance = -5
        self.job.geneBasedInputOmics = [{"inputDataFile": "missing.tab",
                                         "omicName": "DNase-seq",
                                         "isExample": True}]

        with self.assertRaises(Exception) as caught:
            self.job.validateInput()
        self.assertIn("Distance must be a positive", str(caught.exception))


class TestRunOptionGuard(unittest.TestCase):
    """An option run() does not honour must be an error, not a shrug."""

    def test_a_getopt_style_key_is_rejected(self):
        # Called in-process on purpose: the guard runs before run() touches any
        # global or opens any file, so there is nothing to isolate.
        with self.assertRaises(Exception) as caught:
            run(EXAMPLE_GTF, EXAMPLE_REGIONS, os.devnull, None,
                {"report": "gene", "gene": "gene_id"}, None)

        message = str(caught.exception)
        self.assertIn("Unknown option", message)
        self.assertIn("report", message)
        self.assertIn("gene", message)

    def test_an_unknown_level_is_rejected(self):
        with self.assertRaises(Exception) as caught:
            run(EXAMPLE_GTF, EXAMPLE_REGIONS, os.devnull, None,
                {"level": "chromosome"}, None)
        self.assertIn("Unknown report level", str(caught.exception))

    def test_the_guard_reports_through_the_queue_too(self):
        # Bed2GeneJob only ever sees what came back on the queue, so the guard
        # is useless if the exception does not make the trip.
        queueContent = runInSubprocess(EXAMPLE_GTF, EXAMPLE_REGIONS, os.devnull,
                                       {"report": "gene"})
        self.assertIsInstance(queueContent, Exception)
        self.assertIn("Unknown option", str(queueContent))

    def test_every_key_getOptions_sends_is_accepted(self):
        # Complements the set-difference test above by proving the guard itself
        # agrees: the production options dict must get all the way through.
        job = Bed2GeneJob("testJob", "testUser", tempfile.gettempdir())
        self.assertEqual(set(), set(job.getOptions().keys()) - set(RUN_OPTION_KEYS))


class TestAssociationAgainstExampleData(unittest.TestCase):
    """End-to-end through the same call path Bed2GeneJob.fromBED2Genes uses."""

    @classmethod
    def setUpClass(cls):
        for requiredFile in (EXAMPLE_GTF, EXAMPLE_REGIONS):
            if not os.path.isfile(requiredFile):
                raise unittest.SkipTest("Missing example file: " + requiredFile)

    def setUp(self):
        self.workDir = tempfile.mkdtemp(prefix="b2g_test_")
        self.outputFile = os.path.join(self.workDir, "RGMatch_output.txt")

    def tearDown(self):
        shutil.rmtree(self.workDir, ignore_errors=True)

    def test_default_job_settings_associate_the_example_regions(self):
        # THE regression test: a stock job (Distance 10 kb, report at gene
        # level) used to write a header and nothing else.
        job = Bed2GeneJob("testJob", "testUser", self.workDir)

        queueContent = runInSubprocess(EXAMPLE_GTF, EXAMPLE_REGIONS,
                                       self.outputFile, job.getOptions())

        self.assertIsNone(queueContent)
        self.assertGreaterEqual(Bed2GeneJob.countAssociationRows(self.outputFile),
                                EXPECTED_ASSOCIATION_ROWS)

    def test_a_ten_bp_window_is_what_the_bug_used_to_search(self):
        # Pins the measurement the diagnosis rests on: the difference between
        # 10 and 10000 is the whole defect, not an unlucky dataset.
        options = Bed2GeneJob("testJob", "testUser", self.workDir).getOptions()
        options["distance"] = 10

        queueContent = runInSubprocess(EXAMPLE_GTF, EXAMPLE_REGIONS,
                                       self.outputFile, options)

        self.assertIsNone(queueContent)
        self.assertEqual(0, Bed2GeneJob.countAssociationRows(self.outputFile))

    def test_a_gtf_tag_other_than_gene_id_is_honoured(self):
        # run() accepted gene_id_tag but never recompiled the regex that
        # actually reads it, so the tag was decorative.
        renamedGTF = os.path.join(self.workDir, "renamed.gtf")
        with open(EXAMPLE_GTF, 'r') as source, open(renamedGTF, 'w') as target:
            for line in source:
                target.write(line.replace("gene_id ", "locus_tag "))

        options = Bed2GeneJob("testJob", "testUser", self.workDir).getOptions()
        options["gene_id_tag"] = "locus_tag"

        queueContent = runInSubprocess(renamedGTF, EXAMPLE_REGIONS,
                                       self.outputFile, options)

        self.assertIsNone(queueContent)
        self.assertGreaterEqual(Bed2GeneJob.countAssociationRows(self.outputFile),
                                EXPECTED_ASSOCIATION_ROWS)


class TestCountAssociationRows(unittest.TestCase):
    """The zero-result detector Bed2GeneJob leans on."""

    def setUp(self):
        self.workDir = tempfile.mkdtemp(prefix="b2g_count_")
        self.outputFile = os.path.join(self.workDir, "RGMatch_output.txt")

    def tearDown(self):
        shutil.rmtree(self.workDir, ignore_errors=True)

    def test_a_header_only_file_counts_zero(self):
        with open(self.outputFile, 'w') as handler:
            handler.write("#Region\tMidpoint\tGene\n")
        self.assertEqual(0, Bed2GeneJob.countAssociationRows(self.outputFile))

    def test_a_missing_file_counts_zero(self):
        self.assertEqual(0, Bed2GeneJob.countAssociationRows(self.outputFile))

    def test_data_rows_are_counted_and_blank_lines_are_not(self):
        with open(self.outputFile, 'w') as handler:
            handler.write("#Region\tMidpoint\tGene\n")
            handler.write("r1\t100\tG1\n")
            handler.write("\n")
            handler.write("r2\t200\tG2\n")
        self.assertEqual(2, Bed2GeneJob.countAssociationRows(self.outputFile))


class _ScratchJob(Bed2GeneJob):
    """A Bed2GeneJob whose directories and inputs point at a scratch dir.

    Subclassed rather than mocked so the real fromBED2Genes runs; only the path
    lookups and the input registry are redirected.
    """

    def __init__(self, workDir, gtf, regions, relevant):
        super(_ScratchJob, self).__init__("testJob", "testUser", workDir)
        self._workDir = workDir
        self._gtf = gtf
        self._regions = regions
        self._relevant = relevant

    def getInputDir(self):
        # Deliberately empty. Bed2GeneJob builds paths by string concatenation
        # ("{path}/{file}", Bed2GeneJob.py:196-197, :397-398), not os.path.join,
        # so any non-empty value here would be glued in front of this fixture's
        # absolute input paths and nothing would resolve.
        #
        # The cost is that the OUTPUT copy at :574/:581 also lands here, i.e.
        # relative to the working directory -- which is why the test class below
        # runs from its own scratch dir. Seven B2G_output_<stamp>.tab files had
        # collected in the repository root before that was noticed.
        return ""

    def getTemporalDir(self):
        return self._workDir

    def getReferenceInputs(self):
        return [{"inputDataFile": self._gtf}]

    def getGeneBasedInputOmics(self):
        return [{"inputDataFile": self._regions,
                 "relevantFeaturesFile": self._relevant,
                 "omicName": "DNase-seq",
                 "isExample": True}]


class TestZeroAssociationsAreRefused(unittest.TestCase):
    """A header-only association file must stop the job here, with a reason."""

    def setUp(self):
        self.workDir = tempfile.mkdtemp(prefix="b2g_zero_")
        # _ScratchJob.getInputDir() has to stay empty (see the note there), and
        # fromBED2Genes copies its output file to that directory -- i.e. to the
        # working directory. Run from the scratch dir so the copy is cleaned up
        # with it instead of being left wherever the suite was invoked from.
        self._previousCwd = os.getcwd()
        os.chdir(self.workDir)

    def tearDown(self):
        os.chdir(self._previousCwd)
        shutil.rmtree(self.workDir, ignore_errors=True)

    def test_a_run_that_matches_nothing_names_the_distance_setting(self):
        job = _ScratchJob(self.workDir, EXAMPLE_GTF, EXAMPLE_REGIONS,
                          os.path.join(EXAMPLE_DIR, "dnase_regions_relevant.tab"))
        # 0.01 kb == the 10 bp window the kb bug used to search.
        job.distance = 0.01

        with self.assertRaises(Exception) as caught:
            job.fromBED2Genes()

        message = str(caught.exception)
        self.assertIn("No region could be associated", message)
        self.assertIn("0.01 kb", message)
        self.assertIn("gene", message)

    def test_the_example_data_gets_past_the_guard(self):
        # The same guard must not fire on a job that did find associations, or
        # it becomes the new blocker. fromBED2Genes goes on to register its
        # output files in the database, which this test has no business
        # reaching, so the assertion is that whatever stops it is not the
        # guard -- and that the association file it checked was not empty.
        job = _ScratchJob(self.workDir, EXAMPLE_GTF, EXAMPLE_REGIONS,
                          os.path.join(EXAMPLE_DIR, "dnase_regions_relevant.tab"))

        try:
            job.fromBED2Genes()
        except Exception as stoppedBy:
            self.assertNotIn("No region could be associated", str(stoppedBy))

        self.assertGreaterEqual(
            Bed2GeneJob.countAssociationRows(
                os.path.join(self.workDir, "RGMatch_output.txt")),
            EXPECTED_ASSOCIATION_ROWS)


class TestSelectTranscriptTieBreak(unittest.TestCase):
    """Reporting at gene level activates selectTranscript() for the first time."""

    @staticmethod
    def buildCandidate(transcript, area="TSS", exon="1"):
        return Candidate(100, 200, "+", exon, area, transcript, "GENE1",
                         0, 80.0, 95.0, 10, 20)

    def test_two_tied_transcripts_are_merged_instead_of_crashing(self):
        # The merged Candidate was built with 11 of its 12 arguments, so this
        # raised TypeError the first time two transcripts of one gene tied --
        # unreachable while the app was stuck at the "exon" default.
        candidates = [self.buildCandidate("T1"), self.buildCandidate("T2")]

        reported = DHS_exon_association.selectTranscript(candidates,
                                                         {"GENE1": [0, 1]})

        self.assertEqual(1, len(reported))
        self.assertEqual("T1,T2", reported[0].getTranscript())
        self.assertEqual(20, reported[0].getTTSdistance())

    def test_an_area_missing_from_the_rules_table_does_not_crash(self):
        # `rules` is caller-supplied, so it need not rank every area the code
        # emits; the lookup used to be myAreas[None].
        originalRules = DHS_exon_association.rules
        DHS_exon_association.rules = ["DOWNSTREAM"]
        try:
            candidates = [self.buildCandidate("T1", area="TSS"),
                          self.buildCandidate("T2", area="TSS")]
            reported = DHS_exon_association.selectTranscript(candidates,
                                                             {"GENE1": [0, 1]})
        finally:
            DHS_exon_association.rules = originalRules

        self.assertEqual(1, len(reported))
        self.assertEqual("T1,T2", reported[0].getTranscript())

    def test_applyRules_keeps_a_candidate_whose_area_is_unranked(self):
        originalRules = DHS_exon_association.rules
        DHS_exon_association.rules = ["DOWNSTREAM"]
        try:
            # Two candidates of the same transcript, both below perc_region and
            # perc_area so the tie reaches the rules table.
            candidates = [
                Candidate(100, 200, "+", "1", "TSS", "T1", "GENE1", 0, 1.0, 1.0, 10, 20),
                Candidate(300, 400, "+", "2", "TSS", "T1", "GENE1", 0, 1.0, 1.0, 10, 20),
            ]
            reported = DHS_exon_association.applyRules(candidates, {"T1": [0, 1]})
        finally:
            DHS_exon_association.rules = originalRules

        self.assertEqual(1, len(reported))


if __name__ == "__main__":
    unittest.main(verbosity=2)
