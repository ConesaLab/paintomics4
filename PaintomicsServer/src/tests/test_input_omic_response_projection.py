#!/usr/bin/env python3
"""No step-1/step-2/recover response may publish a server filesystem path.

Measured in the browser: sessionStorage.jobModel held

    inputDataFile: "/Users/.../PaintomicsServer/src/examplefiles/datasets/
                    01-gene-single-condition/data/gene_expression_values.tab"

alongside relevantFeaturesFile, associationsFile and relevantAssociationsFile.
The omic entry those come from is also the job's database record -- Job.toBSON
publishes it verbatim and Job reopens a job by reading inputDataFile back -- so
the fix is a projection at the response boundary and nowhere near toBSON.

It is a whitelist. A blacklist would be one `git pull` away from leaking the
next field somebody adds for persistence, which is exactly how these four got
out.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_input_omic_response_projection
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets import PathwayAcquisitionServlet
from src.servlets.PathwayAcquisitionServlet import (
    CLIENT_VISIBLE_OMIC_FIELDS, inputOmicsForClient)

SERVLET_SOURCE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "servlets", "PathwayAcquisitionServlet.py"))

# The four fields the browser was measured holding. None of them is read by any
# client file (grepped across PaintomicsClient/public_html/app).
PATH_FIELDS = ("inputDataFile", "relevantFeaturesFile", "associationsFile",
               "relevantAssociationsFile")

# An omic entry with every key any code path is known to set on it: the upload
# path (JobInformationManager.saveFiles), the example path
# (ExampleDatasets.applyScenario) and the processing path
# (PathwayAcquisitionJob.processFilesContent / applyReplicateMappingForOmic).
FULL_OMIC = {
    "omicName": "Gene expression",
    "inputDataFile": "/srv/paintomics/PaintomicsServer/src/examplefiles/"
                     "datasets/01-gene-single-condition/data/values.tab",
    "relevantFeaturesFile": "/srv/paintomics/.../relevant.tab",
    "associationsFile": "/srv/paintomics/.../associations.tab",
    "relevantAssociationsFile": "/srv/paintomics/.../relevant_associations.tab",
    "configOptions": "Input data:/srv/paintomics/values.tab",
    "isExample": True,
    "role": "target",
    "enrichment": "genes",
    "omicSummary": [{"KEGG": 1529}, 0, -2.9],
    "omicHeader": ["# Gene name", "T00h", "T02h"],
    "replicateDetection": {"status": "none", "sampleHeader": [],
                           "mapping": [-1, -1], "groups": [], "unmatched": [0, 1]},
    "replicateSource": "off",
    "replicateMapping": [],
    "sampleHeader": [],
}


def everyString(value):
    """Every string anywhere in a nested response fragment."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            for found in everyString(item):
                yield found
    elif isinstance(value, (list, tuple)):
        for item in value:
            for found in everyString(item):
                yield found


class ProjectionTest(unittest.TestCase):

    def test_the_key_set_is_exactly_the_whitelist(self):
        projected = inputOmicsForClient([FULL_OMIC])
        self.assertEqual(len(projected), 1)
        self.assertEqual(set(projected[0]), set(CLIENT_VISIBLE_OMIC_FIELDS))

    def test_the_four_measured_fields_are_gone(self):
        projected = inputOmicsForClient([FULL_OMIC])[0]
        for field in PATH_FIELDS:
            self.assertNotIn(field, projected)

    def test_nothing_in_the_result_looks_like_a_filesystem_path(self):
        projected = inputOmicsForClient([FULL_OMIC])
        offenders = [text for text in everyString(projected)
                     if text.startswith("/") or text.startswith("\\")
                     or re.match(r"^[A-Za-z]:[\\/]", text)]
        self.assertEqual(offenders, [],
                         "these strings reach sessionStorage: %s" % offenders)

    def test_a_field_nobody_whitelisted_does_not_travel(self):
        """The point of a whitelist: tomorrow's persistence field stays home."""
        projected = inputOmicsForClient(
            [dict(FULL_OMIC, someFutureInternalField="/srv/secret")])[0]
        self.assertNotIn("someFutureInternalField", projected)

    def test_a_partially_filled_omic_only_carries_what_it_has(self):
        """Step 1 answers before processFilesContent has added omicHeader."""
        projected = inputOmicsForClient([{"omicName": "Proteomics",
                                          "inputDataFile": "/srv/x.tab"}])
        self.assertEqual(projected, [{"omicName": "Proteomics"}])

    def test_the_job_keeps_its_own_copy_intact(self):
        """The entry is the DB record; projecting must not mutate it, or the
        job could not be reopened (Job reads inputDataFile back)."""
        source = dict(FULL_OMIC)
        inputOmicsForClient([source])
        self.assertEqual(source, FULL_OMIC)

    def test_an_empty_or_missing_list_is_an_empty_list(self):
        self.assertEqual(inputOmicsForClient([]), [])
        self.assertEqual(inputOmicsForClient(None), [])

    def test_the_whitelist_covers_what_the_client_reads(self):
        """Named here so removing one is a deliberate act, not a typo.

        Each is read in PaintomicsClient/public_html/app: omicName everywhere,
        omicSummary in JobModel.getMappingSummary, omicHeader in
        getOmicHeaders, replicateDetection and sampleHeader in
        PA_Step2ReplicateDetectionView.
        """
        for field in ("omicName", "omicSummary", "omicHeader",
                      "replicateDetection", "sampleHeader"):
            self.assertIn(field, CLIENT_VISIBLE_OMIC_FIELDS)


class EveryPublishingSiteTest(unittest.TestCase):
    """A projection applied at four of five sites is not a fix.

    The servlet publishes these omics from step 1, from both branches of step 2
    and from both branches of recover-job.
    """

    @classmethod
    def setUpClass(cls):
        with open(SERVLET_SOURCE, encoding="utf-8") as handle:
            cls.source = handle.read()

    def test_every_published_omic_list_goes_through_the_projection(self):
        published = re.findall(
            r'"(?:gene|compound)BasedInputOmics"\s*:\s*(.+?),\s*\n',
            self.source)
        self.assertTrue(published, "no publishing site found -- did the "
                                   "response keys get renamed?")
        for expression in published:
            self.assertTrue(expression.startswith("inputOmicsForClient("),
                            "this site publishes the raw omic entries, "
                            "absolute paths and all: %s" % expression)

    def test_all_five_response_sites_are_still_there(self):
        """Ten expressions: five responses x gene + compound."""
        self.assertEqual(self.source.count("inputOmicsForClient(jobInstance."),
                         10)

    def test_the_database_write_still_sends_the_whole_entry(self):
        """/pa_apply_replicate_mapping persists the omic list. Projecting
        there would erase inputDataFile from the stored job and make it
        impossible to reopen."""
        self.assertIn(
            'jobDAO.update(jobInstance, {"fieldList": ["geneBasedInputOmics", '
            '"compoundBasedInputOmics"]})',
            self.source)

    def test_toBSON_was_not_touched(self):
        """Project rule: toBSON is the DB serialiser as well as the wire one."""
        self.assertNotIn("toBSON", PathwayAcquisitionServlet.inputOmicsForClient
                         .__doc__ or "")
        for field in PATH_FIELDS:
            self.assertNotIn('del ' + field, self.source)
            self.assertNotIn('pop("%s"' % field, self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
