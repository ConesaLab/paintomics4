#!/usr/bin/env python3
"""Secrets must come from `secrets`, not from `random`.

Why this exists
---------------
Three values that gate access to an account were built with `random.choice`:

  * the **session token** (`UserSessionManager.registerNewUser`) -- the whole of
    what `isValidUser` checks a request against;
  * the **password-reset token** (`userManagementResetPassword`) -- emailed as a
    link, and whoever holds it sets the password;
  * the **replacement password** generated alongside it.

`random` is the Mersenne Twister. It is fast and reproducible, which is what
makes it wrong here: the generator is fully determined by 19937 bits of state,
and that state can be reconstructed from a modest run of its outputs. Python's
own documentation is unambiguous -- "not suitable for security purposes... use
secrets". Length does not rescue it: a 50-character token drawn from a
predictable stream is as guessable as the stream, however many characters it
has. A site that hands out guest sessions freely hands out samples freely too.

`secrets` draws from the OS CSPRNG. It is a drop-in here: same alphabet, same
length, same type, no stored value changes format, so nothing needs migrating
and no existing session or token is invalidated.

The lint below reads the source of the functions themselves rather than
sampling their output, because a weak PRNG produces output that looks fine.
Statistical checks on 50-character strings cannot tell Mersenne Twister from a
CSPRNG; only the call site can.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_secret_generation
"""
import inspect
import os
import re
import string
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.UserSessionManager import UserSessionManager
from src.servlets import UserManagementServlet

# The alphabet the tokens have always used; kept so the fix cannot silently
# change what downstream code and stored rows expect.
TOKEN_ALPHABET = set(string.ascii_uppercase + string.digits)


def _sourceOf(function):
    return inspect.getsource(function)


class NoWeakPrngInSecretsTest(unittest.TestCase):
    """The call site is the only place this is visible."""

    def _assertNoRandomModule(self, source, what):
        offending = [line.strip() for line in source.splitlines()
                     if re.search(r"\brandom\.(choice|randint|randrange|random|sample)\b", line)
                     or re.search(r"^\s*(import random\b|from random import)", line)]

        self.assertEqual(
            offending, [],
            "%s is built with the `random` module (Mersenne Twister), which is "
            "predictable from its own output and must not gate account access. "
            "Use `secrets`.\n  " % what + "\n  ".join(offending))

    def test_the_session_token_does_not_use_random(self):
        self._assertNoRandomModule(
            _sourceOf(UserSessionManager().registerNewUser.__func__
                      if hasattr(UserSessionManager().registerNewUser, "__func__")
                      else UserSessionManager().registerNewUser),
            "the session token")

    def test_the_reset_token_and_password_do_not_use_random(self):
        self._assertNoRandomModule(
            _sourceOf(UserManagementServlet.userManagementResetPassword),
            "the password-reset token and replacement password")


class SessionTokenShapeTest(unittest.TestCase):
    """The fix must not change the token's observable shape."""

    def setUp(self):
        self.manager = UserSessionManager()

    def test_the_token_is_fifty_characters(self):
        token = self.manager.registerNewUser("shape-user")

        self.assertEqual(len(token), 50)

    def test_the_token_uses_the_established_alphabet(self):
        token = self.manager.registerNewUser("alphabet-user")

        self.assertTrue(set(token) <= TOKEN_ALPHABET,
                        "token characters outside the historical alphabet: %r"
                        % sorted(set(token) - TOKEN_ALPHABET))

    def test_two_tokens_are_not_the_same(self):
        first = self.manager.registerNewUser("user-a")
        second = self.manager.registerNewUser("user-b")

        self.assertNotEqual(first, second)

    def test_many_tokens_are_all_distinct(self):
        tokens = {self.manager.registerNewUser("bulk-%d" % index)
                  for index in range(200)}

        self.assertEqual(len(tokens), 200, "a token repeated within 200 draws")

    def test_the_token_is_what_validation_then_accepts(self):
        """The generator and the check must agree, whatever the source."""
        token = self.manager.registerNewUser("roundtrip-user")

        self.manager.isValidUser("roundtrip-user", token)   # raises if invalid

    def test_a_wrong_token_is_still_refused(self):
        self.manager.registerNewUser("refuse-user")

        with self.assertRaises(Exception):
            self.manager.isValidUser("refuse-user", "X" * 50)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
