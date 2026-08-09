#!/usr/bin/env python3
"""Signing in must accept the address the user typed at registration.

Why this exists
---------------
`userManagementSignUp` lowercases before storing:

    email = email.lower()

`userManagementSignIn` and `userManagementResetPassword` did not lowercase
before looking up. So an account registered as Bob@Example.com was stored as
bob@example.com, and signing in with Bob@Example.com -- the address the user
had just typed -- found nothing.

The user was told "The email or password you entered is incorrect" about an
account created seconds earlier, and password reset answered "The entered
e-mail is not registered in the database", which was false. Both escape hatches
gave a wrong answer, so there was no way back into the account short of
guessing that lowercasing it helps.

Measured against a running server before the fix, one address throughout:

    sign up  TestUser_...@Example.COM   -> success
    sign in  TestUser_...@Example.COM   -> failed
    sign in  testuser_...@example.com   -> success
    reset    TestUser_...@EXAMPLE.COM   -> "not registered"

and after it, sign-in and reset both succeed with the mixed-case form while a
wrong password is still refused.

The fix is safe for accounts that already exist precisely because sign-up has
always lowercased: every stored address is already lowercase -- checked, 17 of
17 -- so lowercasing the lookup can only add matches, never remove one. That is
the property this file pins, along with the asymmetry itself.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_email_case_insensitivity
"""
import ast
import io
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SERVLET = os.path.join(os.path.dirname(__file__),
                       "../servlets/UserManagementServlet.py")

# Handlers that look an account up by e-mail address.
LOOKUP_HANDLERS = ("userManagementSignIn", "userManagementResetPassword")


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


class EmailCaseInsensitivityTest(unittest.TestCase):

    def setUp(self):
        self.handlers = _handlerSources()

    def test_every_lookup_handler_normalises_the_case(self):
        missing = [name for name in LOOKUP_HANDLERS
                   if ".lower()" not in _stripComments(self.handlers.get(name, ""))]

        self.assertEqual(missing, [],
                         "these look an account up by e-mail without lowering "
                         "the case, so an address registered with a capital "
                         "letter cannot be used to sign in or to reset: %s"
                         % missing)

    def test_signup_still_stores_it_lowercased(self):
        """The other half of the pair: if this stops, the lookups are wrong again."""
        source = _stripComments(self.handlers.get("userManagementSignUp", ""))

        self.assertIn("email.lower()", source,
                      "sign-up no longer lowercases before storing, so stored "
                      "addresses and the lookups above no longer agree")

    def test_the_normalisation_is_not_only_a_comment(self):
        for name in LOOKUP_HANDLERS:
            with self.subTest(handler=name):
                self.assertIn(".lower()", _stripComments(self.handlers[name]))

    def test_the_handlers_were_actually_found(self):
        """An empty parse would let the checks above pass vacuously."""
        for name in LOOKUP_HANDLERS + ("userManagementSignUp",):
            with self.subTest(handler=name):
                self.assertIsNotNone(self.handlers.get(name),
                                     "%s not found in the servlet" % name)

    def test_lowering_cannot_break_an_existing_account(self):
        """Every stored address is already lowercase, so this only adds matches.

        Skipped when MongoDB is unreachable -- the claim is about the data, so
        it is checked against the data rather than asserted.
        """
        try:
            from pymongo import MongoClient
            from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
            client = MongoClient(MONGODB_HOST, MONGODB_PORT,
                                 serverSelectionTimeoutMS=2000)
            client.admin.command("ping")
        except Exception as exc:
            self.skipTest("MongoDB not reachable: %s" % exc)

        try:
            collection = client["PaintomicsDB"]["userCollection"]
            offenders = [d.get("email") for d in collection.find({}, {"email": 1})
                         if d.get("email") and d["email"] != d["email"].lower()]
        finally:
            client.close()

        self.assertEqual(offenders, [],
                         "%d stored addresses are not lowercase, so lowering "
                         "the lookup would stop matching them: %s"
                         % (len(offenders), offenders[:3]))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
