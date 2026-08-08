#!/usr/bin/env python3
"""Regions2Genes must say what is wrong when its annotations file is missing.

Why this exists
---------------
`Bed2GeneJob.fromBED2Genes` opened with

    gtfFile = self.getInputDir() + self.getReferenceInputs()[0].get("inputDataFile")

Two separate problems, both of which end up in front of a user.

1. That `[0]` assumes a reference input exists. An upload only registers one
   when a file was actually sent -- JobInformationManager adds it under
   `matchingType.lower() == "reference_file"` -- so submitting Regions2Genes
   without an annotations file left the list empty and raised

       IndexError: list index out of range

   `handleException` formats the reply as "ERROR MESSAGE: " + str(ex), so that
   sentence *was* the entire error message shown in the browser. Reproduced
   against a job with no reference inputs before the change.

2. When the file simply is not on disk, the message was "Reference file not
   found." and nothing else -- neither of the two paths it had just tried.

The second is not hypothetical, and it is the reason for the wording now used.
Running the bundled Regions2Genes example on this machine fails exactly here,
because `examplefiles/GTF/` holds only a zero-byte `.dummy`: the real
`sorted_mmu.gtf` is built by `deploy/fetch-example-gtf.sh`, which is a manual
step referenced only from deploy/README.md and wired into no automated deploy.
A release that skips it leaves every user of that example looking at
"Oops..Internal error! ... Reference file not found." with nothing to act on,
and no hint that the fault is missing example data rather than their own upload.

Naming both candidate paths turns that into a one-line diagnosis.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_regions2genes_missing_gtf
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.Bed2GeneJob import Bed2GeneJob

MISSING_GTF = "/nonexistent/GTF/sorted_mmu.gtf"


class MissingAnnotationsTest(unittest.TestCase):

    def _job(self, jobID="PROBE"):
        job = Bed2GeneJob(jobID, None, "/tmp/")
        job.setDirectories("/tmp/")
        return job

    def _failureFor(self, job):
        try:
            job.fromBED2Genes()
        except Exception as exc:
            return exc
        self.fail("expected a failure, none was raised")

    def test_no_annotations_file_is_not_an_index_error(self):
        """The bare IndexError went to the browser as the whole message."""
        failure = self._failureFor(self._job())

        self.assertNotIsInstance(failure, IndexError,
                                 "an empty reference-input list still raises "
                                 "IndexError, which reaches the user as "
                                 "'list index out of range'")

    def test_no_annotations_file_says_what_is_missing(self):
        failure = self._failureFor(self._job())
        message = str(failure)

        self.assertIn("GTF", message,
                      "the message should name what was not supplied: %r" % message)
        self.assertNotIn("list index out of range", message)

    def test_a_missing_file_names_both_paths_tried(self):
        """The deployment case: the example GTF was never fetched."""
        job = self._job("PROBE2")
        job.addReferenceInput({"omicName": "DNase unmapped",
                               "fileType": "Reference file",
                               "inputDataFile": MISSING_GTF})

        message = str(self._failureFor(job))

        self.assertIn("Reference file not found", message)
        self.assertIn(MISSING_GTF, message,
                      "the path that was looked for should appear, or there is "
                      "nothing to act on: %r" % message)
        self.assertIn(job.getInputDir(), message,
                      "the uploaded-file candidate should appear too, so it is "
                      "clear both were tried: %r" % message)

    def test_the_example_gtf_is_absent_here_which_is_why_this_matters(self):
        """Documents the environment rather than asserting a fix.

        Skips where the file has been fetched, so this does not fail on a
        machine that ran deploy/fetch-example-gtf.sh.
        """
        # EXAMPLE_FILES_DIR is not a config constant -- the Application builds
        # it at runtime as ROOT_DIRECTORY + "examplefiles/" and passes it down
        # -- so the path is derived from the tree here instead.
        exampleGTF = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "examplefiles", "GTF",
            "sorted_mmu.gtf"))
        if os.path.isfile(exampleGTF):
            self.skipTest("the example GTF has been fetched on this machine")

        self.assertFalse(os.path.isfile(exampleGTF))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
