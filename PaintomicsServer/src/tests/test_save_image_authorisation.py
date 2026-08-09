#!/usr/bin/env python3
"""Saving an image into a read-only job must obey the same rule as its siblings.

Why this exists
---------------
`pathwayAcquisitionSaveImage` loaded the job a request named and wrote a file
into `jobInstance.getOutputDir()` without ever asking whether the caller was
allowed to. Every other handler in its family asks:

    if jobInstance.getReadOnly() and str(jobInstance.getUserID()) != str(userID):
        raise Exception(...)

-- pathwayAcquisitionSaveVisualOptions, pathwayAcquisitionRecoverJob,
pathwayAcquisitionApplyReplicateMapping, pathwayAcquisitionMetagenes_PART1 all
carry it, and pathwayAcquisitionSaveSharingOptions carries a stricter
ownership check. SaveImage was the one that did not.

That matters more here than in the handler it was copied from. `outputDir` is
built from the *job owner's* userID:

    self.outputDir = CLIENT_TMP_DIR + userDir + "/jobsData/" + self.jobID + "/output/"

so the bytes land under whoever owns the job, not whoever sent the request. And
`isValidUser` deliberately admits the anonymous "nologin" case, so the session
check in front of it stops very little.

Measured against a running server before the fix -- one guest session, one job
owned by somebody else and marked readOnly, the two sibling endpoints:

    pa_save_visual_options  success=None   (refused)
    pa_save_image           success=True

    wrote into the owner's directory: paintomics_zzProbeAuth2_5z5wjuZ5RS.svg

The svg branch writes `request.form["svgCode"]` verbatim, and
/get_cluster_image serves that directory via send_from_directory, which types a
.svg as image/svg+xml from the application's own origin. So what a stranger
plants there is same-origin markup rather than merely wasted disk.

After the fix, the same three cases against the same running server:

    readOnly job, non-owner   refused,  nothing written
    readOnly job, the owner   success,  file written
    open job,     non-owner   success,  file written

Scope: this restores the readOnly rule, it does not tighten it. The third line
is the point -- a job that is not readOnly stays writable by anyone holding its
ID, which is how sharing works in this application. Changing that is a product
decision, not a bug fix.

(Checking that third case needs a job the server process has not cached.
`JobInformationManager.loadJobInstance` serves from an in-memory cache, so
flipping `readOnly` straight in MongoDB is invisible to a running server and
the case appears to fail when nothing is wrong.)

Usage:
    cd PaintomicsServer
    python -m src.tests.test_save_image_authorisation
"""
import ast
import io
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SERVLET = os.path.join(os.path.dirname(__file__),
                       "../servlets/PathwayAcquisitionServlet.py")

# Handlers that load a job and then modify something belonging to it.
#
# pathwayAcquisitionStep2_PART1 is here for the same reason and was found the
# same way -- see test_step2_authorisation.py for that one's measurements.
# pathwayAcquisitionStep3 is deliberately absent: it is what the client calls
# to *view* a pathway, and it persists nothing.
GUARDED_HANDLERS = (
    "pathwayAcquisitionSaveImage",
    "pathwayAcquisitionSaveVisualOptions",
    "pathwayAcquisitionRecoverJob",
    "pathwayAcquisitionApplyReplicateMapping",
    "pathwayAcquisitionStep2_PART1",
)


def _stripComments(text):
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
                  if t.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except Exception:
        return text


def _handlerSources():
    with open(SERVLET, "r", encoding="utf-8", errors="replace") as handle:
        source = handle.read()
    tree = ast.parse(source)
    return {node.name: ast.get_source_segment(source, node)
            for node in tree.body if isinstance(node, ast.FunctionDef)}


class SaveImageAuthorisationTest(unittest.TestCase):

    def setUp(self):
        self.handlers = _handlerSources()

    def test_the_handlers_were_actually_found(self):
        """An empty parse would make every check below vacuous."""
        for name in GUARDED_HANDLERS:
            with self.subTest(handler=name):
                self.assertIsNotNone(self.handlers.get(name),
                                     "%s not found in the servlet" % name)

    def test_save_image_checks_authorisation(self):
        source = _stripComments(self.handlers["pathwayAcquisitionSaveImage"])

        self.assertIn("getReadOnly()", source,
                      "pathwayAcquisitionSaveImage writes a file into the job "
                      "owner's output directory without checking whether the "
                      "caller may modify that job")

    def test_the_check_is_not_only_a_comment(self):
        """The explanation above the guard would satisfy a plain substring test."""
        node = ast.parse(_stripComments(
            self.handlers["pathwayAcquisitionSaveImage"]).lstrip())
        calls = {n.func.attr for n in ast.walk(node)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}

        self.assertIn("getReadOnly", calls,
                      "getReadOnly appears in the source but is never called, "
                      "so the guard is prose rather than code")

    def test_the_guard_compares_against_the_requesting_user(self):
        source = _stripComments(self.handlers["pathwayAcquisitionSaveImage"])

        self.assertIn("getUserID()", source,
                      "the readOnly flag is consulted without comparing the "
                      "job's owner to the caller, so the owner is locked out "
                      "of their own job or nobody is")

    def test_the_guard_precedes_the_write(self):
        """A check after the file is written protects nothing."""
        source = _stripComments(self.handlers["pathwayAcquisitionSaveImage"])

        guardAt = source.find("getReadOnly()")
        self.assertNotEqual(guardAt, -1, "no guard at all")

        # renderSvgToPng, not svg2png: the rasterisation moved into a helper so
        # the CairoSVG call could be sandboxed (see renderSvgToPng and
        # test_svg_export_is_sandboxed). The write it performs is the same one,
        # and it is still what has to happen after the guard -- this test
        # caught the rename rather than being defeated by it, which is the
        # point of the "-1" assertion below.
        for writer in ("renderSvgToPng", "open("):
            with self.subTest(write=writer):
                writeAt = source.find(writer)
                self.assertNotEqual(writeAt, -1,
                                    "%s is gone from the handler; if the write "
                                    "moved, this test is checking nothing"
                                    % writer)
                self.assertLess(guardAt, writeAt,
                                "the authorisation check happens after %s"
                                % writer)

    def test_every_sibling_still_carries_it(self):
        """The rule is a family invariant, not a one-off patch."""
        missing = [name for name in GUARDED_HANDLERS
                   if "getReadOnly()" not in _stripComments(self.handlers.get(name, ""))]

        self.assertEqual(missing, [],
                         "these load a job and modify it without checking "
                         "whether the caller may: %s" % missing)

    def test_sharing_options_keeps_its_stricter_check(self):
        """It sets readOnly, so a readOnly-conditional guard would be circular."""
        source = _stripComments(
            self.handlers["pathwayAcquisitionSaveSharingOptions"])

        self.assertIn("getUserID()", source)
        self.assertIn("!=", source,
                      "pathwayAcquisitionSaveSharingOptions no longer requires "
                      "ownership, so a stranger can clear readOnly on a job "
                      "and then modify it through the handlers above")


class OutputDirectoryOwnershipTest(unittest.TestCase):
    """The reason the guard matters: the path is the owner's, not the caller's."""

    def test_output_dir_is_keyed_on_the_job_owner(self):
        from src.classes.Job import Job

        job = Job("JOB1", "500", "/tmp/paintomics/")

        self.assertIn("/500/", job.getOutputDir(),
                      "outputDir is no longer derived from the job's userID; "
                      "if it now follows the caller, re-read the guard above")
        self.assertTrue(job.getOutputDir().endswith("/jobsData/JOB1/output/"))

    def test_an_ownerless_job_lands_under_nologin(self):
        from src.classes.Job import Job

        job = Job("JOB2", None, "/tmp/paintomics/")

        self.assertIn("/nologin/", job.getOutputDir())


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
