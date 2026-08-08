#!/usr/bin/env python3
"""Creating a user's directories must not fail because they already exist.

Why this exists
---------------
`userManagementSignUp` inserts the user, sends the welcome email, and *then*
calls `initializeUserDirectories`. That last step used bare `os.mkdir`:

    os.mkdir(CLIENT_TMP_DIR + userID)
    os.mkdir(CLIENT_TMP_DIR + userID + "/inputData")
    ...

`os.mkdir` raises `FileExistsError` when the directory is already there, the
exception escapes to `handleException`, and the reply is `success: false`. But
the account has already been written to MongoDB by that point and works.

Observed against the running server: signing up returned

    FileExistsError: AT UserManagementServlet.py: userManagementSignUp.
    ERROR MESSAGE: [Errno 17] File exists: '.../CLIENT_TMP/2'

and the very next `um_signin` with those credentials succeeded, returning
userID 2 and a session token. So the user is told their registration failed
for an account that exists. Retrying reports the email is already registered,
which leaves them believing they have no account and no way to get one.

Directory IDs come from `UserDAO.getNextUserID`, so a leftover directory from a
previously deleted user is enough to trigger it -- the numbering is not aware
of what is on disk.

The second defect here is a typo:

    if os.path.isfile(CLIENT_TMP_DIR + userID):
        shutil.rmtree(CLIENT_TMP_DIR + 'userID')   # <- quoted

The guard tests the user's path; the `rmtree` deletes a directory named
literally `userID`. It is near-dead code -- `isfile` is false for a directory,
which is what that path is -- but it is an `rmtree` aimed at the wrong target,
and "never fires" is not a property worth relying on in a recursive delete.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_user_directory_setup
"""
import inspect
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets import UserManagementServlet
from src.servlets.UserManagementServlet import initializeUserDirectories

SUBDIRECTORIES = ("inputData", "jobsData", "tmp")


class _TmpClientDir(unittest.TestCase):
    """Point CLIENT_TMP_DIR at a scratch directory for the duration."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="paintomics_userdirs_") + "/"
        self._saved = UserManagementServlet.CLIENT_TMP_DIR
        UserManagementServlet.CLIENT_TMP_DIR = self.root

    def tearDown(self):
        UserManagementServlet.CLIENT_TMP_DIR = self._saved
        shutil.rmtree(self.root, ignore_errors=True)

    def _assertComplete(self, userID):
        base = os.path.join(self.root, userID)
        self.assertTrue(os.path.isdir(base), "%s was not created" % base)
        for name in SUBDIRECTORIES:
            self.assertTrue(os.path.isdir(os.path.join(base, name)),
                            "%s/%s missing" % (userID, name))


class FreshUserTest(_TmpClientDir):

    def test_a_new_user_gets_all_directories(self):
        initializeUserDirectories("42")

        self._assertComplete("42")

    def test_the_anonymous_nologin_directory_is_created(self):
        initializeUserDirectories(None)

        base = os.path.join(self.root, "nologin")
        self.assertTrue(os.path.isdir(base))
        for name in SUBDIRECTORIES:
            self.assertTrue(os.path.isdir(os.path.join(base, name)),
                            "nologin/%s missing" % name)


class ExistingDirectoryTest(_TmpClientDir):
    """The case that made sign-up report failure for an account that exists."""

    def test_an_existing_user_directory_is_not_an_error(self):
        os.makedirs(os.path.join(self.root, "7"))

        try:
            initializeUserDirectories("7")
        except FileExistsError as exc:
            self.fail("a leftover directory made sign-up fail after the "
                      "account was already written to MongoDB: %s" % exc)

        self._assertComplete("7")

    def test_a_fully_populated_directory_is_not_an_error(self):
        for name in SUBDIRECTORIES:
            os.makedirs(os.path.join(self.root, "8", name))

        initializeUserDirectories("8")     # must not raise

        self._assertComplete("8")

    def test_missing_subdirectories_are_filled_in(self):
        """Half-created state, e.g. a previous run that died midway."""
        os.makedirs(os.path.join(self.root, "9", "inputData"))

        initializeUserDirectories("9")

        self._assertComplete("9")

    def test_calling_twice_is_safe(self):
        initializeUserDirectories("10")
        initializeUserDirectories("10")     # must not raise

        self._assertComplete("10")

    def test_an_existing_nologin_directory_missing_subdirs_is_repaired(self):
        """The original only made the subdirs inside `if not exists`."""
        os.makedirs(os.path.join(self.root, "nologin"))

        initializeUserDirectories(None)

        for name in SUBDIRECTORIES:
            self.assertTrue(
                os.path.isdir(os.path.join(self.root, "nologin", name)),
                "nologin/%s was never created because the parent existed" % name)


class NoQuotedUserIdTest(unittest.TestCase):
    """The rmtree typo, pinned by reading the source."""

    def test_rmtree_does_not_target_the_literal_string_userID(self):
        source = inspect.getsource(initializeUserDirectories)

        offending = [line.strip() for line in source.splitlines()
                     if re.search(r"rmtree\s*\(.*['\"]userID['\"]", line)]

        self.assertEqual(
            offending, [],
            "rmtree targets a directory named literally 'userID' rather than "
            "the user's own:\n  " + "\n  ".join(offending))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
