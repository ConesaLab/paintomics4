#!/usr/bin/env python3
"""Administrative routes must refuse anonymous callers by decision, not by crash.

isValidUser() deliberately returns True for the anonymous case -- PaintOmics
supports "nologin" jobs that belong to nobody:

    if (user_id == 'None' and sessionToken == None):
        return True

isValidAdminUser() called that and then went straight on to
UserDAO.findByID(user_id), which does int(user_id). For an unauthenticated
request that meant

    TypeError: int() argument must be a string, a bytes-like object or a
    number, not 'NoneType'

Probed against the deployed server on /api/admin/users/, /api/admin/system-info/,
/api/admin/databases/ and /api/admin/databases/available: all four returned
HTTP 400 carrying that TypeError.

Access was still denied, so this was never an authentication bypass -- but it
was denied *accidentally*, as a side effect of a crash on the way to the
ADMIN_ACCOUNTS check, which is a fragile thing to depend on. The reply also
handed an unauthenticated caller a servlet file name, line number and exception
type instead of stating what was required.

Note the two /api/admin/ routes that legitimately answer anonymously and must
keep doing so: GET /api/admin/messages/ shares its handler with the public
/um_get_message (site announcements), and GET /api/admin/files/ returns the
reference-GTF listing the region-based omic form needs.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_admin_gate
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.UserSessionManager import UserSessionManager


def adminCheck():
    return UserSessionManager().isValidAdminUser


class AnonymousAdminAccessTest(unittest.TestCase):

    def _assertRefused(self, user_id, user_name, sessionToken, label):
        with self.assertRaises(Exception) as caught:
            adminCheck()(user_id, user_name, sessionToken)

        self.assertNotIsInstance(
            caught.exception, TypeError,
            "%s is refused only because something crashed on the way" % label)
        self.assertNotIsInstance(
            caught.exception, AttributeError,
            "%s is refused only because something crashed on the way" % label)
        return caught.exception

    def test_fully_anonymous_request_is_refused_deliberately(self):
        """The exact shape the deployed server answered with a TypeError."""
        self._assertRefused(None, None, None, "a fully anonymous request")

    def test_missing_username_is_refused(self):
        self._assertRefused(None, None, "some-token", "a request with no user name")

    def test_message_says_what_is_required(self):
        error = self._assertRefused(None, None, None, "a fully anonymous request")

        message = str(error).lower()
        self.assertTrue(
            "administrator" in message or "not valid" in message,
            "the refusal should say administrator access is needed; got: %s" % error)

    def test_message_does_not_leak_internals(self):
        error = str(self._assertRefused(None, None, None, "a fully anonymous request"))

        for leak in ("Traceback", ".py", "int()", "NoneType"):
            self.assertNotIn(leak, error,
                             "refusal message exposes internals: %s" % error)


class SourceStructureTest(unittest.TestCase):

    def test_user_is_checked_before_the_database_lookup(self):
        source = inspect.getsource(UserSessionManager().isValidAdminUser)

        code = "\n".join(line.split("#", 1)[0] for line in source.splitlines())

        guard = code.find("raise CredentialException")
        lookup = code.find("UserDAO().findByID")

        self.assertNotEqual(guard, -1,
                            "the anonymous case is no longer rejected explicitly")
        self.assertLess(
            guard, lookup,
            "findByID runs before the anonymous check, so an unauthenticated "
            "request still reaches int(None)")

    def test_personal_file_listing_refuses_anonymous_like_its_siblings(self):
        """dm_get_myfiles did `DESTINATION_DIR += userID` with userID None.

        dm_get_myjobs and dm_delete_job in the same file already answer
        "Log in required"; the file listing was the odd one out and raised
        TypeError instead. The reference/GTF listing stays public.
        """
        from src.servlets import DataManagementServlet

        code = "\n".join(
            line.split("#", 1)[0] for line in
            inspect.getsource(DataManagementServlet.dataManagementGetMyFiles).splitlines())

        guard = code.find("userID is None")
        concatenation = code.find("DESTINATION_DIR += userID")

        self.assertNotEqual(guard, -1,
                            "no anonymous guard before the path concatenation")
        self.assertLess(
            guard, concatenation,
            "userID is concatenated before the anonymous case is handled, so an "
            "unauthenticated request raises TypeError instead of being told to log in")

    def test_missing_user_record_is_handled(self):
        code = inspect.getsource(UserSessionManager().isValidAdminUser)

        self.assertIn(
            "_user is None", code,
            "an unknown user ID makes findByID return None and _user.userName "
            "then raises AttributeError")


if __name__ == "__main__":
    unittest.main(verbosity=2)
