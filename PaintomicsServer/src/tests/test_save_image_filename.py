#!/usr/bin/env python3
"""A saved image's filename must stay inside the job's own output directory.

Why this exists
---------------
`pathwayAcquisitionSaveImage` builds a write path by concatenation:

    fileName = "paintomics_" + requestedFileName.replace(" ", "_").replace("/", "_") + "_" + jobID
    ...
    open(path + fileName + "." + fileFormat, 'w')

`requestedFileName` comes straight off the form. The only thing keeping a `../`
in it from walking out of the job's output directory is that one
`.replace("/", "_")`, and nothing tested it -- delete that call and every test
in the suite still passes while the endpoint becomes an arbitrary file write.

This is the counterpart to the containment work in dd5ce4a5 and 6a6453af. Those
routes needed `resolveWithin` because they took a whole path; this one is safe
by a different mechanism -- it destroys the separator rather than resolving the
result -- and that mechanism deserves a test of its own precisely because it is
a single easily-deleted expression rather than a named helper.

Verified against the running server before writing this, with a control first:
a benign name really does write a file, and then `../../../../ZZESC`,
`/tmp/ZZESC` and `....//ZZESC` all landed inside the output directory with
their separators flattened. The control matters -- an earlier attempt probed a
job that had no output directory, so nothing was written and the probe could
not have detected an escape either way.

Backslashes are deliberately *not* replaced. On POSIX a backslash is an
ordinary filename character, and this deploys to Linux; on Windows it would be
a separator and this rule would be insufficient. Pinned below so the assumption
is visible rather than implied.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_save_image_filename
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def _sanitisedName(requestedFileName, jobID="JOB123"):
    """The expression from pathwayAcquisitionSaveImage, kept in step with it."""
    return "paintomics_" + requestedFileName.replace(" ", "_").replace("/", "_") + "_" + jobID


class FilenameContainmentTest(unittest.TestCase):

    def _assertContained(self, requestedFileName):
        outputDir = "/srv/jobs/JOB123/output/"
        written = os.path.normpath(outputDir + _sanitisedName(requestedFileName) + ".svg")

        self.assertTrue(
            written.startswith(os.path.normpath(outputDir) + os.sep),
            "%r escaped the output directory: wrote %s" % (requestedFileName, written))

    def test_a_plain_name_is_kept(self):
        self.assertEqual(_sanitisedName("chart"), "paintomics_chart_JOB123")

    def test_spaces_become_underscores(self):
        self.assertEqual(_sanitisedName("my chart"), "paintomics_my_chart_JOB123")

    def test_a_parent_traversal_cannot_escape(self):
        self._assertContained("../../../../etc/passwd")

    def test_an_absolute_path_cannot_escape(self):
        self._assertContained("/tmp/anywhere")

    def test_a_doubled_separator_cannot_escape(self):
        self._assertContained("....//....//anywhere")

    def test_a_url_encoded_separator_cannot_escape(self):
        """Flask decodes form values, so %2F arrives as '/' and is replaced."""
        self._assertContained("..%2F..%2Fanywhere")
        self._assertContained("../../anywhere")

    def test_every_separator_is_gone_from_the_result(self):
        for name in ("../../x", "/a/b/c", "a/b", "..//.."):
            with self.subTest(name=name):
                self.assertNotIn("/", _sanitisedName(name))

    def test_the_job_id_is_appended_after_the_user_part(self):
        """A name cannot smuggle itself past the jobID suffix."""
        self.assertTrue(_sanitisedName("x", jobID="J9").endswith("_J9"))

    def test_a_backslash_is_not_replaced(self):
        """True on POSIX, and load-bearing if this ever runs on Windows."""
        self.assertIn("\\", _sanitisedName("..\\..\\x"))
        self.assertTrue(os.sep == "/",
                        "this suite assumes a POSIX separator; on Windows the "
                        "backslash left in place above becomes a traversal")


class SourceStillSanitisesTest(unittest.TestCase):
    """The handler must keep doing what the cases above assume."""

    def test_the_handler_replaces_the_separator(self):
        import inspect
        from src.servlets import PathwayAcquisitionServlet

        source = inspect.getsource(
            PathwayAcquisitionServlet.pathwayAcquisitionSaveImage)

        self.assertIn('.replace("/", "_")', source,
                      "the separator replacement is gone from "
                      "pathwayAcquisitionSaveImage; the filename it builds is "
                      "concatenated straight into an open() for writing")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
