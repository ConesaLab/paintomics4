#!/usr/bin/env python3
"""The admin users list must not carry password hashes or reset credentials.

Why this exists
---------------
`adminServletGetAllUsers` put the `User` objects straight into the response.
`MyJSONEncoder.default` serialises anything with a `toBSON()` by calling it,
and `User` does not override the one it inherits from `Model`:

    def toBSON(self):
        return  self.__dict__

-- the whole attribute dict, by reference. So every attribute a User has went
out to the browser, including the four the panel never reads:

    password, resetToken, resetPassword, sessionToken

Measured against the live collection before the fix: `password` populated on
16 of 16 stored users, `sessionToken` on 0 of 16 (nothing calls
`setSessionToken`, which is what keeps this from being a session-hijack bug).

The hash is what makes it matter. UserManagementServlet hashes with
`sha1(password.encode('utf-8')).hexdigest()` at four call sites -- unsalted, so
a rainbow table reverses a common password immediately. One stored account
holds d033e22ae348aeb5660fc2140aef11803e5c1c2, which is SHA-1("admin").

The route is admin-gated, so this is defence in depth rather than an open door.
It is still worth closing: the hashes end up in a browser's memory and disk
cache, in anything that logs response bodies, and in the devtools of whoever
has the panel open -- for a page that displays names, e-mail addresses and disk
usage.

Fixed at the response boundary, not in `User.toBSON`, because that same method
is what `UserDAO.insert` and `update` persist -- dropping the password from it
would write accounts that can never log in. That asymmetry is the whole reason
the bug existed: one serialiser was doing duty for both the database and the
wire.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_admin_user_list_has_no_secrets
"""
import json
import os
import sys
import unittest
from json import JSONEncoder

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.User import User

# Attributes that must never reach a client, whatever the panel grows into.
SECRETS = ("password", "resetToken", "resetPassword", "sessionToken")

# What user-row.tpl.html binds. Losing one of these is a blank column.
RENDERED = ("userID", "userName", "email", "affiliation",
            "creation_date", "last_login", "is_guest", "usedSpace")


class _ServerJSONEncoder(JSONEncoder):
    """paintomicsserver.MyJSONEncoder, reproduced so the test needs no app."""

    def default(self, obj):
        if hasattr(obj, "toBSON"):
            return obj.toBSON()
        return super(_ServerJSONEncoder, self).default(obj)


def _populatedUser():
    user = User("7")
    user.setUserName("alice")
    user.setEmail("alice@example.com")
    user.setAffiliation("CSIC")
    user.setCreationDate("20260101")
    user.setLastLogin("20260808")
    user.setPassword("d033e22ae348aeb5660fc2140aef11803e5c1c2")
    user.setResetToken("d41d8cd98f00b204e9800998ecf8427e")
    user.setResetPassword("5f4dcc3b5aa765d61d8327deb882cf99")
    user.setSessionToken("live-session-token")
    return user


class AdminUserListSecretsTest(unittest.TestCase):

    def setUp(self):
        from src.servlets.AdminServlet import summarizeUserForAdmin
        self.summarize = summarizeUserForAdmin
        self.summary = summarizeUserForAdmin(_populatedUser(), 4096)

    def _serialised(self, payload):
        """Through the encoder the server actually installs."""
        return json.loads(json.dumps(payload, cls=_ServerJSONEncoder))

    def test_no_secret_reaches_the_response(self):
        leaked = [name for name in SECRETS if name in self.summary]

        self.assertEqual(leaked, [],
                         "the admin users list carries %s, which the panel "
                         "never reads" % leaked)

    def test_no_secret_value_appears_anywhere_in_the_json(self):
        """Not just absent as a key -- absent as a value, under any name."""
        user = _populatedUser()
        body = json.dumps({"userList": [self.summarize(user, 0)]},
                          cls=_ServerJSONEncoder)

        for name in SECRETS:
            value = getattr(user, name)
            with self.subTest(field=name):
                self.assertNotIn(value, body,
                                 "the value of %s appears in the response "
                                 "body" % name)

    def test_the_bug_is_real_and_this_test_would_have_caught_it(self):
        """Serialising the User itself -- what the handler used to do."""
        body = json.dumps({"userList": [_populatedUser()]},
                          cls=_ServerJSONEncoder)

        for name in SECRETS:
            with self.subTest(field=name):
                self.assertIn(name, body,
                              "serialising a User no longer exposes %s, so "
                              "either Model.toBSON changed or User gained an "
                              "override -- if so this test is now pinning "
                              "nothing and the docstring is stale" % name)

    def test_everything_the_panel_renders_survives(self):
        missing = [name for name in RENDERED if name not in self.summary]

        self.assertEqual(missing, [],
                         "user-row.tpl.html binds %s, which the response no "
                         "longer carries, so those columns render blank"
                         % missing)

    def test_the_rendered_values_are_the_users_own(self):
        """A projection that returns the right keys with wrong values is worse."""
        user = _populatedUser()

        summary = self.summarize(user, 4096)

        self.assertEqual(summary["userID"], user.getUserId())
        self.assertEqual(summary["userName"], user.getUserName())
        self.assertEqual(summary["email"], user.getEmail())
        self.assertEqual(summary["affiliation"], user.getAffiliation())
        self.assertEqual(summary["is_guest"], user.isGuest())
        self.assertEqual(summary["usedSpace"], 4096)

    def test_the_summary_is_plain_json(self):
        """It must survive jsonify without the toBSON fallback."""
        try:
            json.dumps(self.summary)
        except TypeError as exc:
            self.fail("the admin summary is not JSON serialisable: %s" % exc)

    def test_a_user_missing_an_attribute_does_not_raise(self):
        """Documents parsed from older records may not carry every field."""
        sparse = User("9")
        del sparse.__dict__["affiliation"]

        summary = self.summarize(sparse, 0)

        self.assertIn("affiliation", summary)
        self.assertIsNone(summary["affiliation"])

    def test_the_handler_uses_the_projection(self):
        """The helper being correct is no use if the handler bypasses it."""
        import ast
        import inspect
        import src.servlets.AdminServlet as adminServlet

        source = inspect.getsource(adminServlet.adminServletGetAllUsers)
        tree = ast.parse(source.lstrip())
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

        self.assertIn("summarizeUserForAdmin", called,
                      "adminServletGetAllUsers does not call the projection, "
                      "so it is putting something else on the wire")


class ModelToBSONAliasingTest(unittest.TestCase):
    """The underlying sharp edge, recorded rather than changed.

    `Model.toBSON` returns `self.__dict__` itself, so a caller that writes to
    the "BSON" writes to the object. `UserDAO.insert` does exactly that
    (`instanceBSON["userID"] = userID`), and `insert_one` then adds an `_id`
    to the same dict -- measured, the live User gains
    `_id: ObjectId(...)` and `json.dumps` on it afterwards raises TypeError.

    Nothing user-visible follows today: all three call sites discard the
    instance immediately, and both User insert paths use the returned userID
    rather than reading it back off the object. The six classes that override
    toBSON all build a fresh dict; the base is the one that does not. Left
    alone because changing it is a behaviour change to every Model subclass
    with no failing case to justify it -- this test just makes the aliasing
    explicit so the next person meets it deliberately.
    """

    def test_the_base_tobson_is_the_live_dict(self):
        user = User("1")

        self.assertIs(user.toBSON(), user.__dict__,
                      "Model.toBSON no longer aliases the instance dict -- if "
                      "that was fixed deliberately, delete this test")

    def test_writing_to_the_bson_writes_to_the_object(self):
        user = User("1")

        user.toBSON()["userID"] = 99

        self.assertEqual(user.getUserId(), 99)

    def test_the_overriding_subclasses_do_not_alias(self):
        from src.classes.Pathway import Pathway
        from src.classes.Feature import Feature

        for label, instance in (("Pathway", Pathway("map00010")),
                                ("Feature", Feature("g1"))):
            with self.subTest(cls=label):
                self.assertIsNot(instance.toBSON(), instance.__dict__)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
