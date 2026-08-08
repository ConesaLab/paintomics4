#!/usr/bin/env python3
"""A password with an accent in it must work, and old hashes must still match.

Why this exists
---------------
Every password in UserManagementServlet went through

    sha1(password.encode('ascii')).hexdigest()

at five sites: sign-in, sign-up, the guest session, change-password and the
reset. `encode('ascii')` raises on anything outside ASCII:

    UnicodeEncodeError: 'ascii' codec can't encode character '\\xf1' in position 2

That is not a CredentialException, so it fell to the generic handler and the
user was shown "Oops..Internal error!". The effect is that a password
containing ñ, an accent, Cyrillic or CJK could not be registered, and if one
ever reached the database it could not be used to sign in either. For a tool
maintained and used at CIPF/CSIC, a password with ñ or á is not an exotic case.

The fix is utf-8, and the reason it is safe rather than a migration is that
UTF-8 encodes every ASCII string to exactly the same bytes. Every password
already stored is necessarily ASCII -- nothing else could have been written --
so every stored hash still matches and nobody is locked out.

That claim is the one worth testing, so it is checked exhaustively here rather
than asserted: all 128 one-character ASCII strings and all 16384 two-character
combinations, plus longer samples, hash identically under both encodings.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_password_encoding
"""
import itertools
import os
import re
import string
import sys
import unittest
from hashlib import sha1

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SERVLET = os.path.join(os.path.dirname(__file__),
                       "../servlets/UserManagementServlet.py")

NON_ASCII_PASSWORDS = ["señor", "café", "naïve", "пароль", "密码", "Ωmega", "smörgås"]


class PasswordEncodingTest(unittest.TestCase):

    def _source(self):
        with open(SERVLET, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()

    def test_no_password_is_encoded_as_ascii(self):
        """The whole bug, expressed as the thing that must not come back.

        Comment lines are skipped: the fix's own comment quotes the old call
        to explain what it replaced, and flagging that would mean the code
        cannot describe its own history.
        """
        offenders = [line.strip()
                     for line in self._source().splitlines()
                     if ("encode('ascii')" in line or 'encode("ascii")' in line)
                     and not line.strip().startswith("#")]

        self.assertEqual(offenders, [],
                         "a password is still ascii-encoded, so a non-ASCII "
                         "password raises UnicodeEncodeError and reaches the "
                         "user as an internal error: %s" % offenders)

    def test_every_password_site_is_utf8(self):
        """All five, so one does not get missed and fail only on that route."""
        hashed = re.findall(r"sha1\((.*?)\.encode\('([^']+)'\)\)",
                            self._source())

        self.assertGreaterEqual(len(hashed), 5,
                                "expected the five password hashing sites, "
                                "found %d" % len(hashed))
        self.assertEqual({encoding for _expr, encoding in hashed}, {"utf-8"},
                         "mixed encodings across the password sites: %s"
                         % sorted({e for _x, e in hashed}))

    def test_a_non_ascii_password_can_be_hashed(self):
        for password in NON_ASCII_PASSWORDS:
            with self.subTest(password=password):
                digest = sha1(password.encode("utf-8")).hexdigest()
                self.assertEqual(len(digest), 40)

    def test_a_non_ascii_password_would_have_failed_before(self):
        """Confirms these samples actually exercise the bug."""
        for password in NON_ASCII_PASSWORDS:
            with self.subTest(password=password):
                with self.assertRaises(UnicodeEncodeError):
                    password.encode("ascii")

    def test_every_existing_hash_still_matches(self):
        """The compatibility guarantee, checked rather than assumed.

        Exhaustive over one- and two-character ASCII, which is what makes this
        a proof for stored passwords rather than a spot check: any ASCII string
        is a sequence of those bytes, and UTF-8 encodes each of them
        identically.
        """
        characters = [chr(code) for code in range(128)]

        mismatches = []
        for character in characters:
            if sha1(character.encode("ascii")).hexdigest() != \
               sha1(character.encode("utf-8")).hexdigest():
                mismatches.append(repr(character))

        for first, second in itertools.product(characters, repeat=2):
            pair = first + second
            if sha1(pair.encode("ascii")).hexdigest() != \
               sha1(pair.encode("utf-8")).hexdigest():
                mismatches.append(repr(pair))

        self.assertEqual(mismatches, [],
                         "%d ASCII passwords would hash differently under "
                         "utf-8, so changing the encoding would lock those "
                         "accounts out" % len(mismatches))

    def test_longer_ascii_samples_are_unchanged_too(self):
        samples = ["password", "P@ssw0rd!", string.printable, " ",
                   "1234567890", "~!@#$%^&*()_+`-={}|[]\\:\";'<>?,./"]

        for sample in samples:
            with self.subTest(sample=sample[:20]):
                self.assertEqual(sha1(sample.encode("ascii")).hexdigest(),
                                 sha1(sample.encode("utf-8")).hexdigest())


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
