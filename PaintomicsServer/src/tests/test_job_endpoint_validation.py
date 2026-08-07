#!/usr/bin/env python3
"""Job endpoints must name what was wrong, not raise TypeError/AttributeError.

Every endpoint that acts on an existing job reads a jobID off the request and
then immediately either concatenates it into a log line or calls a method on
the loaded instance. Neither step tolerates a missing or unknown ID:

    jobID = request.form.get("jobID")
    jobInstance = JobInformationManager().loadJobInstance(jobID)
    if jobInstance.getReadOnly() and ...        # None -> AttributeError

    logging.info("STEP3 - LOADING JOB " + jobID + "...")   # None -> TypeError

Probed against the deployed server, 9 of 13 malformed requests across
/pa_step3, /pa_save_image, /pa_save_visual_options, /pa_save_sharing_options
and /pa_get_clusters came back as raw Python exceptions naming neither the
field nor the job:

    TypeError: can only concatenate str (not "NoneType") to str
    AttributeError: 'NoneType' object has no attribute 'getReadOnly'

loadRequestedJob() centralises the two checks so each endpoint reports the
actual problem. This is the same defect class as the missing *_origin field in
saveFiles (see test_missing_origin_field.py).

Usage:
    cd PaintomicsServer
    python -m src.tests.test_job_endpoint_validation
"""
import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets import PathwayAcquisitionServlet as servlet


def loadRequestedJob(*args):
    """Resolve at call time so a missing helper fails loudly, not on import."""
    helper = getattr(servlet, "loadRequestedJob", None)
    if helper is None:
        raise AssertionError(
            "PathwayAcquisitionServlet.loadRequestedJob is gone, so the job "
            "endpoints are back to using an unvalidated jobID -- a malformed "
            "request becomes TypeError/AttributeError instead of a message.")
    return helper(*args)


# Endpoints that act on an existing job; each was probed against the server.
GUARDED_FUNCTIONS = [
    "pathwayAcquisitionStep3",
    "pathwayAcquisitionSaveImage",
    "pathwayAcquisitionSaveVisualOptions",
    "pathwayAcquisitionSaveSharingOptions",
    # /pa_get_clusters is served by the metagenes handler, not a name matching
    # its route.
    "pathwayAcquisitionMetagenes_PART1",
]


class MissingJobIDTest(unittest.TestCase):

    def test_missing_jobID_raises_a_message(self):
        for missing in (None, ""):
            with self.subTest(jobID=missing):
                with self.assertRaises(Exception) as caught:
                    loadRequestedJob(missing, "step 3")

                self.assertNotIsInstance(caught.exception, TypeError)
                self.assertIn("jobID", str(caught.exception))

    def test_message_names_the_action(self):
        """So the user learns which operation failed, not just that one did."""
        with self.assertRaises(Exception) as caught:
            loadRequestedJob(None, "saving the image")

        self.assertIn("saving the image", str(caught.exception))

    def test_the_expressions_that_produced_the_raw_errors(self):
        """Pins both failure modes, so the reason for the helper stays legible."""
        jobID = None
        with self.assertRaises(TypeError):
            "STEP3 - LOADING JOB " + jobID + "..."

        jobInstance = None
        with self.assertRaises(AttributeError):
            jobInstance.getReadOnly()


class SourceStructureTest(unittest.TestCase):
    """Each endpoint must go through the helper rather than load directly."""

    def _source(self, name):
        function = getattr(servlet, name, None)
        self.assertIsNotNone(function, "%s no longer exists" % name)
        return inspect.getsource(function)

    def test_no_endpoint_loads_a_job_without_validating(self):
        offending = []
        for name in GUARDED_FUNCTIONS:
            source = self._source(name)
            if re.search(r"JobInformationManager\(\)\.loadJobInstance\(", source):
                offending.append(name)

        self.assertEqual(
            offending, [],
            "these endpoints call loadJobInstance directly, so an unknown "
            "jobID yields None and the next attribute access raises "
            "AttributeError: %s" % offending)

    def test_each_endpoint_uses_the_helper(self):
        missing = [name for name in GUARDED_FUNCTIONS
                   if "loadRequestedJob" not in self._source(name)]

        self.assertEqual(missing, [],
                         "these endpoints validate no jobID at all: %s" % missing)

    def test_unknown_pathway_is_not_dereferenced(self):
        """A pathway the job never matched has no instance.

        generateSelectedPathwaysInformation looked it up with .get() and used
        the result immediately, so an ID absent from the job raised
        AttributeError: 'NoneType' object has no attribute 'getSource'.
        """
        from src.classes.JobInstances import PathwayAcquisitionJob as jobModule

        source = inspect.getsource(
            jobModule.PathwayAcquisitionJob.generateSelectedPathwaysInformation)

        lookup = source.index("self.getMatchedPathways().get(pathwayID)")
        # Search from the lookup onwards: the explanatory comment above it also
        # mentions getSource(), and matching that would test nothing.
        firstUse = source.index("pathwayInstance.getSource()", lookup)
        between = source[lookup:firstUse]

        self.assertIn(
            "if pathwayInstance is None", between,
            "the pathway instance is used before it is checked for None; an "
            "unknown pathway ID raises AttributeError instead of being skipped")

    def test_save_image_guards_its_filename(self):
        """fileName had .replace() called on it straight off the form."""
        source = self._source("pathwayAcquisitionSaveImage")

        self.assertIsNone(
            re.search(r'request\.form\.get\("fileName"\)\.replace', source),
            "fileName is used with .replace() again; a request omitting it "
            "raises AttributeError instead of naming the field")


if __name__ == "__main__":
    unittest.main(verbosity=2)
