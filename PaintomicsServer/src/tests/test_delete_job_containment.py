#!/usr/bin/env python3
"""A job ID from the request must not be able to name a directory to delete.

Why this exists
---------------
`dataManagementDeleteJob` took the job ID straight from the form, split it on
commas, and concatenated each piece onto the user's job directory:

    jobID = request.form.get("jobID")
    ...
    if os.path.isdir(userDir + jobID):
        shutil.rmtree(userDir + jobID)

`os.path.isdir` was the only check, and it is not a containment check -- it is
satisfied by any directory the path happens to reach, including one reached by
walking upwards. `shutil.rmtree` then removes it **and everything under it**.

This is the same defect as the file-delete and file-read routes fixed
alongside, one step worse: those act on a single file, this one recurses. A job
ID of `..` removes the whole `jobsData` directory -- every job the user has --
and a longer walk reaches other users' data and the server's own directories.
Two call sites, `jobsData/` and `tmp/`.

Like the others it needs a session, which `userManagementNewGuestSession` gives
to anyone who asks.

The tests drive `resolveWithin` with the exact strings the servlet builds,
rather than calling the handler, because the handler needs Mongo and a live
session; what is worth pinning is that the containment decision is made and
what it decides.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_delete_job_containment
"""
import inspect
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.Util import resolveWithin
from src.servlets import DataManagementServlet


class DeleteJobSourceTest(unittest.TestCase):
    """The handler must not concatenate its way to an rmtree target."""

    def test_rmtree_is_not_called_on_a_concatenated_path(self):
        source = inspect.getsource(DataManagementServlet.dataManagementDeleteJob)

        offending = [line.strip() for line in source.splitlines()
                     if re.search(r"rmtree\s*\(\s*\w*[Dd]ir\s*\+", line)]

        self.assertEqual(
            offending, [],
            "rmtree is called on a directory built by concatenating the "
            "request's jobID; a '..' in it deletes outside the user's own "
            "directory, recursively:\n  " + "\n  ".join(offending))

    def test_the_handler_resolves_before_deleting(self):
        source = inspect.getsource(DataManagementServlet.dataManagementDeleteJob)

        self.assertIn("resolveWithin", source,
                      "the delete-job handler does no containment check")


class JobIdContainmentTest(unittest.TestCase):
    """What resolveWithin decides for the strings this route sees."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="paintomics_deljob_")
        self.userDir = os.path.join(self.root, "nologin", "jobsData") + "/"
        os.makedirs(os.path.join(self.userDir, "GoodJob01"))
        # A second user, the thing a traversal would reach for.
        self.otherUser = os.path.join(self.root, "user99", "jobsData", "TheirJob")
        os.makedirs(self.otherUser)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_real_job_id_resolves(self):
        resolved = resolveWithin(self.userDir, "GoodJob01")

        self.assertIsNotNone(resolved)
        self.assertTrue(os.path.isdir(resolved))

    def test_a_job_id_of_dot_dot_is_refused(self):
        """`..` is `jobsData`'s parent: every job the user has, plus siblings."""
        self.assertIsNone(resolveWithin(self.userDir, ".."))

    def test_a_walk_to_another_user_is_refused(self):
        self.assertIsNone(
            resolveWithin(self.userDir, "../../user99/jobsData/TheirJob"),
            "a job ID reached another user's job directory")

    def test_an_absolute_path_is_refused(self):
        self.assertIsNone(resolveWithin(self.userDir, self.otherUser))

    def test_the_job_directory_itself_is_refused(self):
        """`.` resolves to jobsData; rmtree on it wipes every job."""
        self.assertIsNone(resolveWithin(self.userDir, "."))

    def test_an_empty_job_id_is_refused(self):
        """`"a,,b".split(",")` yields an empty piece, which would be the base."""
        self.assertIsNone(resolveWithin(self.userDir, ""))

    def test_each_piece_of_a_comma_list_is_judged_separately(self):
        """The route splits on commas, so one bad piece must not carry others."""
        pieces = "GoodJob01,..,../../user99".split(",")
        verdicts = [resolveWithin(self.userDir, piece) is not None
                    for piece in pieces]

        self.assertEqual(verdicts, [True, False, False])

    def test_the_target_still_exists_after_a_refusal(self):
        """The point of the exercise, stated as an outcome."""
        self.assertIsNone(resolveWithin(self.userDir, "../../user99/jobsData/TheirJob"))
        self.assertTrue(os.path.isdir(self.otherUser),
                        "the other user's job directory was reachable")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
