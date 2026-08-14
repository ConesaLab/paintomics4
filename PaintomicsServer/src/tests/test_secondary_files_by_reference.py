#!/usr/bin/env python3
"""Secondary files passed by reference must register, not silently vanish.

Measured on job 66khe0vtr3 (and reproduced on kW4oCH3eV7): the region-based
example converts its regions with RGmatch, the conversion writes
B2G_output_<date>.tab AND B2G_relevant_<date>.tab, and the client then submits
step 1 with both files *by reference*:

    omic0_origin=mydata                omic0_filelocation=[MyData]/B2G_output_...
    omic0_relevant_origin=mydata       omic0_relevant_filelocation=[MyData]/B2G_relevant_...

An untouched <input type=file> still submits a part with filename="" for
omic0_relevant_file, and saveFiles gated the whole relevant-features branch on
that part being non-empty -- so the mydata path inside it was unreachable, the
omic registered relevantFeaturesFile: None, and every Fisher test in the job
degenerated to p=1.0: 829 pathways found, 0 significant, on a dataset with a
planted signal and six expected target pathways.

The data-file branch does not have this defect because it checks the origin
first; these tests pin the same shape onto the three secondary files (relevant
features, associations, relevant associations).

Usage:
    cd PaintomicsServer
    python -m src.tests.test_secondary_files_by_reference
"""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from werkzeug.datastructures import FileStorage, MultiDict

from src.common.JobInformationManager import JobInformationManager


class _JobStub:
    def __init__(self):
        self.registered = {}

    def getJobID(self):
        return "TESTJOB"

    def addGeneBasedInputOmic(self, omic):
        self.registered.update(omic)

    def addCompoundBasedInputOmic(self, omic):
        self.registered.update(omic)


def _emptyPart(name):
    """What a browser submits for an untouched <input type=file>."""
    return FileStorage(stream=io.BytesIO(b""), filename="", name=name)


def _run(files, fields):
    job = _JobStub()
    with tempfile.TemporaryDirectory() as tmp:
        JobInformationManager().saveFiles(files, fields, None, job, tmp + "/")
    return job.registered


class RelevantByReferenceTest(unittest.TestCase):
    """The exact shape the chained region example submits."""

    def submit(self):
        files = MultiDict()
        files.add("omic0_file", _emptyPart("omic0_file"))
        files.add("omic0_relevant_file", _emptyPart("omic0_relevant_file"))
        fields = MultiDict({
            "omic0_omic_name": "DNase-seq",
            "omic0_file_type": "Bed file (regions mapped to Genes)",
            "omic0_match_type": "gene",
            "omic0_origin": "mydata",
            "omic0_filelocation": "[MyData]/B2G_output_x.tab",
            "omic0_relevant_origin": "mydata",
            "omic0_relevant_filelocation": "[MyData]/B2G_relevant_x.tab",
        })
        return _run(files, fields)

    def test_the_data_file_registers(self):
        """The half that always worked; pinned so the fix cannot break it."""
        self.assertEqual(self.submit().get("inputDataFile"), "B2G_output_x.tab")

    def test_the_relevant_file_registers_too(self):
        """The defect: this was None, which turns every p-value into 1.0."""
        self.assertEqual(self.submit().get("relevantFeaturesFile"),
                         "B2G_relevant_x.tab")


class AssociationsByReferenceTest(unittest.TestCase):
    """The same shape for the pairwise-regulatory (miRNA) conversion, whose
    output is four files: values, relevant, associations, relevant
    associations."""

    def submit(self):
        files = MultiDict()
        for part in ("omic0_file", "omic0_relevant_file",
                     "omic0_associations_file",
                     "omic0_relevant_associations_file"):
            files.add(part, _emptyPart(part))
        fields = MultiDict({
            "omic0_omic_name": "miRNA-seq",
            "omic0_file_type": "miRNA-Seq quatification",
            "omic0_match_type": "gene",
            "omic0_origin": "mydata",
            "omic0_filelocation": "[MyData]/output.tab",
            "omic0_relevant_origin": "mydata",
            "omic0_relevant_filelocation": "[MyData]/relevant.tab",
            "omic0_associations_origin": "mydata",
            "omic0_associations_filelocation": "[MyData]/associations.tab",
            "omic0_relevant_associations_origin": "mydata",
            "omic0_relevant_associations_filelocation":
                "[MyData]/relevant_associations.tab",
        })
        return _run(files, fields)

    def test_the_associations_file_registers(self):
        self.assertEqual(self.submit().get("associationsFile"),
                         "associations.tab")

    def test_the_relevant_associations_file_registers(self):
        self.assertEqual(self.submit().get("relevantAssociationsFile"),
                         "relevant_associations.tab")


class UntouchedInputsStillSkipTest(unittest.TestCase):
    """The guard the gate was written for (IsADirectoryError on filename="")
    must survive the fix: no location, no upload -> no file, no crash."""

    def test_untouched_secondary_inputs_register_none(self):
        files = MultiDict()
        files.add("omic0_file", FileStorage(
            stream=io.BytesIO(b"gene\tv\nAlb\t1.0\n"), filename="values.tab",
            name="omic0_file"))
        for part in ("omic0_relevant_file", "omic0_associations_file",
                     "omic0_relevant_associations_file"):
            files.add(part, _emptyPart(part))
        fields = MultiDict({
            "omic0_omic_name": "Gene expression",
            "omic0_file_type": "Gene expression",
            "omic0_match_type": "gene",
            "omic0_origin": "client",
            "omic0_relevant_origin": "client",
        })
        registered = _run(files, fields)
        self.assertIsNone(registered.get("relevantFeaturesFile"))
        self.assertIsNone(registered.get("associationsFile"))
        self.assertIsNone(registered.get("relevantAssociationsFile"))
        self.assertTrue(str(registered.get("inputDataFile", ""))
                        .endswith("values.tab"))

    def test_an_uploaded_relevant_file_is_still_saved(self):
        files = MultiDict()
        files.add("omic0_file", FileStorage(
            stream=io.BytesIO(b"gene\tv\nAlb\t1.0\n"), filename="values.tab",
            name="omic0_file"))
        files.add("omic0_relevant_file", FileStorage(
            stream=io.BytesIO(b"Alb\n"), filename="relevant.tab",
            name="omic0_relevant_file"))
        fields = MultiDict({
            "omic0_omic_name": "Gene expression",
            "omic0_file_type": "Gene expression",
            "omic0_match_type": "gene",
            "omic0_origin": "client",
            "omic0_relevant_origin": "client",
        })
        registered = _run(files, fields)
        self.assertTrue(str(registered.get("relevantFeaturesFile", ""))
                        .endswith("relevant.tab"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
