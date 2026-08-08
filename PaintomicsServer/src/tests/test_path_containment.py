#!/usr/bin/env python3
"""A file name from a request must not be able to name a file outside its directory.

Why this exists
---------------
Two routes in `DataManagementServlet` built a path by concatenating a request
field onto a directory and then acted on the result:

    os.remove(DESTINATION_DIR + fileName)                 # dataManagementDeleteFile
    with open("{path}/{file}".format(...)) as f:          # dataManagementDownloadFile, serve=True

`fileName` is `request.form.get("fileName")` / `request.args.get("fileName")`,
split on commas in the delete case. Neither resolved the result or checked
where it landed, so `../` in the name walked straight out of the user's
directory: arbitrary file **deletion** on one route and arbitrary file **read**
on the other.

The download route's other branch calls `send_from_directory`, which refuses
traversal itself -- so the same handler was safe when it served an attachment
and unsafe when it streamed. That is the kind of difference nothing notices.

Both routes require a valid session. That is a smaller mitigation than it
sounds: `userManagementNewGuestSession` issues a working session to anyone who
asks, with no email confirmation, so "authenticated" here means "able to make
one extra request".

`resolveWithin` is the shared fix. It resolves the joined path with `realpath`
-- which collapses `..` *and* follows symlinks, so a symlink planted inside the
directory cannot be used to step outside it either -- and returns None unless
the result is genuinely under the base.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_path_containment
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.Util import resolveWithin


class ResolveWithinTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="paintomics_paths_")
        self.userDir = os.path.join(self.root, "user42", "inputData")
        os.makedirs(self.userDir)
        # realpath: on macOS /var is a symlink to /private/var, and
        # resolveWithin resolves links by design, so the expected values
        # have to be resolved too or the comparison tests the platform.
        self.secret = os.path.join(self.root, "victim.txt")
        with open(self.secret, "w") as handle:
            handle.write("another user's data")
        self.mine = os.path.realpath(os.path.join(self.userDir, "mine.tab"))
        with open(self.mine, "w") as handle:
            handle.write("my data")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # -- what must keep working --------------------------------------------

    def test_a_plain_file_name_resolves(self):
        self.assertEqual(resolveWithin(self.userDir, "mine.tab"), self.mine)

    def test_a_name_that_does_not_exist_yet_still_resolves(self):
        """Containment is about where the path points, not whether it exists."""
        resolved = resolveWithin(self.userDir, "not_created_yet.tab")

        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.startswith(os.path.realpath(self.userDir)))

    def test_a_name_in_a_subdirectory_resolves(self):
        os.makedirs(os.path.join(self.userDir, "sub"))

        self.assertIsNotNone(resolveWithin(self.userDir, "sub/inner.tab"))

    def test_a_trailing_slash_on_the_base_is_tolerated(self):
        """Callers build these by concatenation and the slash count varies."""
        self.assertEqual(resolveWithin(self.userDir + "/", "mine.tab"), self.mine)

    def test_names_with_spaces_and_dots_are_fine(self):
        for name in ("my file.tab", "a.b.c.tab", "...leading.tab"):
            with self.subTest(name=name):
                self.assertIsNotNone(resolveWithin(self.userDir, name))

    # -- what must be refused ----------------------------------------------

    def test_a_parent_traversal_is_refused(self):
        self.assertIsNone(resolveWithin(self.userDir, "../../victim.txt"),
                          "../ walked out of the user's directory")

    def test_a_deep_traversal_is_refused(self):
        self.assertIsNone(resolveWithin(self.userDir, "../../../../../../etc/passwd"))

    def test_a_traversal_that_returns_inside_is_still_allowed(self):
        """`sub/../mine.tab` lands in the directory, so it is not an escape."""
        os.makedirs(os.path.join(self.userDir, "sub"))

        self.assertEqual(resolveWithin(self.userDir, "sub/../mine.tab"), self.mine)

    def test_an_absolute_path_is_refused(self):
        """os.path.join discards the base entirely when handed an absolute."""
        self.assertIsNone(resolveWithin(self.userDir, self.secret))

    def test_an_absolute_path_to_a_system_file_is_refused(self):
        self.assertIsNone(resolveWithin(self.userDir, "/etc/passwd"))

    def test_a_symlink_pointing_outside_is_refused(self):
        """realpath follows links, so a planted link is not a way around."""
        link = os.path.join(self.userDir, "escape")
        os.symlink(self.secret, link)

        self.assertIsNone(resolveWithin(self.userDir, "escape"),
                          "a symlink inside the directory reached outside it")

    def test_a_sibling_directory_sharing_a_name_prefix_is_refused(self):
        """A plain string prefix check would accept `user42_evil`."""
        sibling = os.path.join(self.root, "user42", "inputData_evil")
        os.makedirs(sibling)

        self.assertIsNone(resolveWithin(self.userDir, "../inputData_evil/x.tab"),
                          "containment was decided by string prefix, so a "
                          "directory whose name merely starts the same passed")

    def test_an_empty_name_is_refused(self):
        for name in ("", None, "   "):
            with self.subTest(name=name):
                self.assertIsNone(resolveWithin(self.userDir, name))

    def test_the_bare_directory_itself_is_refused(self):
        """`.` resolves to the base, which is not a file the caller may act on."""
        self.assertIsNone(resolveWithin(self.userDir, "."))

    def test_a_null_byte_is_refused(self):
        """Truncation tricks against C-level path handling."""
        self.assertIsNone(resolveWithin(self.userDir, "mine.tab\x00.png"))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
