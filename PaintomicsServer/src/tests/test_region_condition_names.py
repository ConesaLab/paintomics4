#!/usr/bin/env python3
"""Condition names must survive the region-to-gene conversion.

The defect, measured on scenario 07 (07-region-based) end to end,
Bed2GeneJob -> PathwayAcquisitionJob:

    values file header : #CHR start end T00h T02h T06h T12h T18h T24h
    RGMatch header     : ... PercArea name score strand thickStart thickEnd itemRgb
    B2G_output header  : Gene name  name score strand thickStart thickEnd itemRgb
    conditionNames     : ['name','score','strand','thickStart','thickEnd','itemRgb']

RGmatch (`common/bioscripts/DHS_exon_association.py`) treated the regions file
as a plain BED and relabelled its value columns with the BED specification's
optional-column names. In PaintOmics those columns are not BED optional
columns -- they are one quantification per experimental condition, and their
names exist nowhere else in the pipeline, so once RGmatch dropped them the
labels were gone. Bed2GeneJob copies the RGmatch header into B2G_output_*.tab
and the pathway job hands that to the browser, which renders it verbatim
(`conditionNames[c] || ('Cond ' + (c+1))`, PA_Step3Views.js:4351 and :5539).

Before the values-file fallback landed in Job.py these jobs showed the harmless
placeholder "Condition 1" / "Cond 2".."Cond 6"; afterwards they showed
"thickStart", which is wrong AND looks authoritative.

Two independent defences are pinned here:

  1. DHS_exon_association carries the regions file's own header through, so
     region omics finally label their conditions correctly.
  2. Job._applyValuesFileConditionNames refuses a candidate label set drawn
     from the BED reserved vocabulary, so even a converter that loses the
     header again cannot put those words in front of a user.

Usage:
    cd PaintomicsServer
    PYTHONPATH=. python -m src.tests.test_region_condition_names
"""
import os
import shutil
import sys
import tempfile
import unittest

from multiprocessing import Process, Queue

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.classes.Job import Job
from src.classes.JobInstances.Bed2GeneJob import Bed2GeneJob
from src.common.bioscripts.DHS_exon_association import run

EXAMPLE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examplefiles", "datasets",
    "07-region-based", "data"))

EXAMPLE_GTF     = os.path.join(EXAMPLE_DIR, "synthetic_mmu.gtf")
EXAMPLE_REGIONS = os.path.join(EXAMPLE_DIR, "dnase_regions_values.tab")
EXAMPLE_RELEVANT = os.path.join(EXAMPLE_DIR, "dnase_regions_relevant.tab")

BED_OPTIONAL_COLUMNS = ["name", "score", "strand", "thickStart", "thickEnd",
                        "itemRgb", "blockCount", "blockSizes", "blockStarts"]


def runInSubprocess(gtf, regions, outputFile, options, timeout=300):
    """Drive run() the way Bed2GeneJob.fromBED2Genes does.

    run() writes its settings into module globals, so it has to be exercised in
    its own process or one test leaks its configuration into the next.
    """
    managedQueue = Queue()
    worker = Process(target=run,
                     args=(gtf, regions, outputFile, None, options, managedQueue))
    worker.start()
    queueContent = managedQueue.get(True, timeout)
    worker.join(timeout)
    return queueContent


def associationHeader(outputFile):
    """The value-column names RGmatch wrote, i.e. everything past PercArea."""
    with open(outputFile, 'r') as handler:
        return handler.readline().rstrip("\n").split("\t")[11:]


def valuesFileHeader(path):
    with open(path, 'r') as handler:
        return handler.readline().rstrip("\n").split("\t")


# ----------------------------------------------------------------------------
# DEFENCE 1 -- RGmatch carries the regions file's own header through
# ----------------------------------------------------------------------------

class AssociationFileHeaderTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        for requiredFile in (EXAMPLE_GTF, EXAMPLE_REGIONS):
            if not os.path.isfile(requiredFile):
                raise unittest.SkipTest("Missing example file: " + requiredFile)

    def setUp(self):
        self.workDir = tempfile.mkdtemp(prefix="rgmatch_header_")
        self.outputFile = os.path.join(self.workDir, "RGMatch_output.txt")
        self.options = Bed2GeneJob("testJob", "testUser", self.workDir).getOptions()

    def tearDown(self):
        shutil.rmtree(self.workDir, ignore_errors=True)

    def writeRegions(self, name, *lines):
        path = os.path.join(self.workDir, name)
        with open(path, 'w') as handler:
            handler.write("\n".join(lines) + "\n")
        return path

    def test_the_example_time_course_keeps_its_six_timepoint_names(self):
        """THE regression test. Measured before: the tail of this header read
        name/score/strand/thickStart/thickEnd/itemRgb."""
        queueContent = runInSubprocess(EXAMPLE_GTF, EXAMPLE_REGIONS,
                                       self.outputFile, self.options)
        self.assertIsNone(queueContent)

        # Read the expected names back from the file rather than hard-coding
        # them: the simulated datasets are regenerated by
        # `python -m src.AdminTools.scripts.exampledata`, and a legitimate
        # rename there must not fail a test about the *carrying*.
        expected = valuesFileHeader(EXAMPLE_REGIONS)[3:]
        self.assertEqual(6, len(expected), "example data changed shape")

        self.assertEqual(expected, associationHeader(self.outputFile))

    def test_no_bed_keyword_reaches_the_association_header(self):
        runInSubprocess(EXAMPLE_GTF, EXAMPLE_REGIONS, self.outputFile,
                        self.options)
        self.assertEqual([], [column for column in associationHeader(self.outputFile)
                              if column.lower() in
                              (word.lower() for word in BED_OPTIONAL_COLUMNS)])

    def test_a_headerless_bed_file_still_degrades_to_the_bed_vocabulary(self):
        """Nothing to carry, so the previous behaviour must be intact -- the
        columns still need *some* name or the output is a ragged TSV."""
        regions = self.writeRegions(
            "headerless.tab",
            "1\t40098\t40498\t-0.1026\t0.7611\t0.6654",
            "1\t60000\t60400\t-0.0683\t0.4886\t-0.2826")

        queueContent = runInSubprocess(EXAMPLE_GTF, regions, self.outputFile,
                                       self.options)
        self.assertIsNone(queueContent)
        self.assertEqual(["name", "score", "strand"],
                         associationHeader(self.outputFile))

    def test_a_header_row_is_not_mistaken_for_a_region(self):
        """Carrying the header must not also import it as data."""
        regions = self.writeRegions(
            "withheader.tab",
            "#CHR\tstart\tend\tWT\tKO",
            "1\t40098\t40498\t1.0\t2.0")

        runInSubprocess(EXAMPLE_GTF, regions, self.outputFile, self.options)

        self.assertEqual(["WT", "KO"], associationHeader(self.outputFile))
        with open(self.outputFile, 'r') as handler:
            dataRows = handler.read().splitlines()[1:]
        self.assertEqual([], [row for row in dataRows if row.startswith("#CHR")])

    def test_a_comment_further_down_the_file_cannot_rename_the_conditions(self):
        """datasets/09 ships a stray `#CHR<TAB>start<TAB>end` mid-file."""
        regions = self.writeRegions(
            "straycomment.tab",
            "#CHR\tstart\tend\tWT\tKO",
            "1\t40098\t40498\t1.0\t2.0",
            "#CHR\tstart\tend\tJUNK1\tJUNK2",
            "1\t60000\t60400\t3.0\t4.0")

        runInSubprocess(EXAMPLE_GTF, regions, self.outputFile, self.options)
        self.assertEqual(["WT", "KO"], associationHeader(self.outputFile))

    def test_a_header_narrower_than_the_data_is_discarded_whole(self):
        """Half real names and half BED keywords in one legend would be worse
        than either. The header must cover every value column or be dropped."""
        regions = self.writeRegions(
            "shortheader.tab",
            "#CHR\tstart\tend\tWT",
            "1\t40098\t40498\t1.0\t2.0",
            "1\t60000\t60400\t3.0\t4.0")

        runInSubprocess(EXAMPLE_GTF, regions, self.outputFile, self.options)
        self.assertEqual(["name", "score"], associationHeader(self.outputFile))

    def test_a_header_with_a_blank_cell_is_discarded_whole(self):
        regions = self.writeRegions(
            "blankcell.tab",
            "#CHR\tstart\tend\tWT\t   ",
            "1\t40098\t40498\t1.0\t2.0")

        runInSubprocess(EXAMPLE_GTF, regions, self.outputFile, self.options)
        self.assertEqual(["name", "score"], associationHeader(self.outputFile))

    def test_a_bed_track_line_does_not_shadow_the_real_header(self):
        """UCSC BED files may open with a one-column `track`/`browser` line."""
        regions = self.writeRegions(
            "trackline.tab",
            "track name=dnase description=\"example\"",
            "#CHR\tstart\tend\tWT\tKO",
            "1\t40098\t40498\t1.0\t2.0")

        runInSubprocess(EXAMPLE_GTF, regions, self.outputFile, self.options)
        self.assertEqual(["WT", "KO"], associationHeader(self.outputFile))

    def test_a_regions_file_with_no_value_columns_writes_no_extra_header(self):
        """A bare three-column BED: there is nothing to name."""
        regions = self.writeRegions(
            "barebed.tab",
            "1\t40098\t40498",
            "1\t60000\t60400")

        runInSubprocess(EXAMPLE_GTF, regions, self.outputFile, self.options)
        self.assertEqual([], associationHeader(self.outputFile))


# ----------------------------------------------------------------------------
# DEFENCE 2 -- the Job.py fallback refuses the BED reserved vocabulary
# ----------------------------------------------------------------------------

class BedVocabularyGuardTest(unittest.TestCase):

    def setUp(self):
        self.job = Job("BEDGUARD01", None, "/tmp/")

    def test_the_exact_labels_the_browser_was_shown_are_refused(self):
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(
            ["Gene name", "name", "score", "strand", "thickStart",
             "thickEnd", "itemRgb"], 6)
        self.assertEqual(self.job.conditionNames, ["Condition 1"])

    def test_every_prefix_rgmatch_can_emit_is_refused(self):
        """RGmatch's fallback header is always a prefix of the BED list, one
        cell per value column, so all nine lengths have to be covered."""
        for width in range(1, len(BED_OPTIONAL_COLUMNS) + 1):
            job = Job("BEDGUARD%02d" % width, None, "/tmp/")
            job.conditionNames = ["Condition 1"]
            job._applyValuesFileConditionNames(
                ["Gene name"] + BED_OPTIONAL_COLUMNS[:width], width)
            self.assertEqual(job.conditionNames, ["Condition 1"],
                             "BED prefix of width %d reached the client" % width)

    def test_the_guard_is_case_insensitive(self):
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(
            ["#ID", "NAME", "Score", "STRAND"], 3)
        self.assertEqual(self.job.conditionNames, ["Condition 1"])

    def test_an_unlabelled_id_column_is_guarded_too(self):
        """datasets/10's shape: as many header cells as value columns."""
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(["name", "score"], 2)
        self.assertEqual(self.job.conditionNames, ["Condition 1"])

    def test_a_real_name_alongside_a_bed_word_is_still_accepted(self):
        """Only an ENTIRELY reserved set is refused: rejecting any header that
        merely contains one of these words would throw away real data."""
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(
            ["#ID", "T00h", "score"], 2)
        self.assertEqual(self.job.conditionNames, ["T00h", "score"])

    def test_the_real_condition_names_still_get_through(self):
        """The guard must not swallow the fix it backs up."""
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(
            ["Gene name", "T00h", "T02h", "T06h", "T12h", "T18h", "T24h"], 6)
        self.assertEqual(self.job.conditionNames,
                         ["T00h", "T02h", "T06h", "T12h", "T18h", "T24h"])

    def test_the_stategra_region_names_still_get_through(self):
        names = ["Ikaros/Control_0h", "Ikaros/Control_2h", "Ikaros/Control_6h",
                 "Ikaros/Control_12h", "Ikaros/Control_18h", "Ikaros/Control_24h"]
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(["Gene name"] + names, 6)
        self.assertEqual(self.job.conditionNames, names)

    def test_the_predicate_itself(self):
        self.assertTrue(Job._isBedReservedVocabulary(["name", "score"]))
        self.assertTrue(Job._isBedReservedVocabulary(["thickStart"]))
        self.assertFalse(Job._isBedReservedVocabulary([]))
        self.assertFalse(Job._isBedReservedVocabulary(["T00h", "T02h"]))
        self.assertFalse(Job._isBedReservedVocabulary(["name", "T00h"]))


# ----------------------------------------------------------------------------
# The two defences meet: the file Bed2GeneJob hands to the pathway job
# ----------------------------------------------------------------------------

class _ScratchBed2GeneJob(Bed2GeneJob):
    """Directories and inputs redirected to a scratch dir; real fromBED2Genes."""

    def __init__(self, workDir, gtf, regions, relevant):
        super(_ScratchBed2GeneJob, self).__init__("testJob", "testUser", workDir)
        self._workDir = workDir
        self._gtf = gtf
        self._regions = regions
        self._relevant = relevant

    def getInputDir(self):
        # Deliberately empty -- Bed2GeneJob builds paths by string
        # concatenation, not os.path.join, so any non-empty value would be
        # glued in front of this fixture's absolute paths. See the same note in
        # test_bed2genes_association.py. The cost is that fromBED2Genes' output
        # copy lands in the working directory, which is why this test chdirs
        # into its scratch dir first.
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


class Bed2GeneOutputHeaderTest(unittest.TestCase):
    """B2G_output_*.tab is the values file the pathway job reads next."""

    @classmethod
    def setUpClass(cls):
        for requiredFile in (EXAMPLE_GTF, EXAMPLE_REGIONS, EXAMPLE_RELEVANT):
            if not os.path.isfile(requiredFile):
                raise unittest.SkipTest("Missing example file: " + requiredFile)

    def setUp(self):
        self.workDir = tempfile.mkdtemp(prefix="b2g_header_")
        self._previousCwd = os.getcwd()
        os.chdir(self.workDir)

    def tearDown(self):
        os.chdir(self._previousCwd)
        shutil.rmtree(self.workDir, ignore_errors=True)

    def test_the_handover_file_names_the_six_timepoints(self):
        job = _ScratchBed2GeneJob(self.workDir, EXAMPLE_GTF, EXAMPLE_REGIONS,
                                  EXAMPLE_RELEVANT)
        try:
            job.fromBED2Genes()
        except Exception as stoppedBy:
            # fromBED2Genes ends by registering its outputs in the database,
            # which this test has no business reaching. Anything else is real.
            self.assertNotIn("No region could be associated", str(stoppedBy))

        produced = [name for name in os.listdir(self.workDir)
                    if name.startswith("B2G_output_")]
        self.assertEqual(1, len(produced), "expected exactly one B2G output")

        header = valuesFileHeader(os.path.join(self.workDir, produced[0]))
        expected = valuesFileHeader(EXAMPLE_REGIONS)[3:]

        self.assertEqual(["Gene name"] + expected, header)

        # And the pathway job's fallback accepts it as it stands.
        pathwayJob = Job("B2GHANDOVER01", None, "/tmp/")
        pathwayJob.conditionNames = ["Condition 1"]
        pathwayJob._applyValuesFileConditionNames(header, len(expected))
        self.assertEqual(pathwayJob.conditionNames, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
