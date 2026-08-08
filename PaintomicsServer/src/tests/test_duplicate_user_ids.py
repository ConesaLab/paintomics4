#!/usr/bin/env python3
"""Two accounts sharing a userID must be refused, not silently picked between.

Why this exists
---------------
`UserDAO.findByID` did `collection.find_one({"userID": int(userID)})`. `find_one`
returns whichever document Mongo reaches first, so with two accounts on the same
ID it returns one of them and the caller has no way to know.

That is not hypothetical here. `getNextUserID` used to return
`len(userCollection)`, so deleting a user made the next signup collide with an
existing ID. It has since been replaced with an atomic counter -- no *new*
duplicates -- but the counter cannot undo the ones already in a deployment's
database. This machine's had two: userIDs 2 and 3 each shared by two accounts.

What that costs, demonstrated against the running server:

    looptest2 (userID 3) signs in and changes its password to ZZChanged999
    -> reply is {"success": true}
    -> guest35996's stored password becomes sha1("ZZChanged999")
    -> looptest2's own password is unchanged

So the user is told the change worked, their own password did not change, and a
**different account's** password was set to a value they chose and know. The
same lookup backs `UserSessionManager.isValidAdminUser`, where picking the wrong
document decides an administrator check.

`find_one` cannot express "there should be exactly one". Refusing is the only
honest answer: the database is in a state the code has no rule for, and acting
on an arbitrary one of the candidates is the worst available response. A
CredentialException surfaces through the handleException the three callers
already sit inside.

A unique index on userID is the structural fix, but it cannot be built while
duplicates exist, and repairing live user rows is an operator's decision rather
than something a servlet should do on the way past.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_duplicate_user_ids
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.DAO.UserDAO import UserDAO
from src.common.ServerErrorManager import CredentialException


class _FakeCollection:
    """Just the two methods findByID uses."""

    def __init__(self, documents):
        self.documents = documents
        self.lastQuery = None

    def _matching(self, query):
        return [d for d in self.documents
                if all(d.get(k) == v for k, v in query.items())]

    def find_one(self, query):
        self.lastQuery = query
        matches = self._matching(query)
        return matches[0] if matches else None

    def find(self, query, projection=None):
        self.lastQuery = query
        return _FakeCursor(self._matching(query))


class _FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def limit(self, n):
        return iter(self.documents[:n])

    def __iter__(self):
        return iter(self.documents)


class _FakeDbManager:
    def __init__(self, collection):
        self.collection = collection

    def getCollection(self, name):
        return self.collection


def _dao(documents):
    dao = UserDAO.__new__(UserDAO)          # skip __init__ and its connection
    dao.collectionName = "userCollection"
    dao.dbManager = _FakeDbManager(_FakeCollection(documents))
    return dao


def _user(userID, userName, password="pw"):
    # `_id` is present because Model.parseBSON pops it; a document without one
    # is not a shape Mongo ever returns.
    return {"_id": "oid-%s-%s" % (userID, userName), "userID": userID,
            "userName": userName, "email": "%s@x" % userName,
            "password": password}


class UniqueIdTest(unittest.TestCase):

    def test_a_single_match_is_returned(self):
        dao = _dao([_user(3, "alice")])

        found = dao.findByID("3")

        self.assertIsNotNone(found)
        self.assertEqual(found.getUserName(), "alice")

    def test_no_match_returns_none(self):
        dao = _dao([_user(3, "alice")])

        self.assertIsNone(dao.findByID("4"))

    def test_a_string_id_still_matches_an_integer_row(self):
        """Cookies carry the ID as text; the rows store it as an int."""
        dao = _dao([_user(7, "bob")])

        self.assertEqual(dao.findByID("7").getUserName(), "bob")

    def test_two_accounts_on_one_id_are_refused(self):
        """The state that let one user set another's password."""
        dao = _dao([_user(3, "guest35996"), _user(3, "looptest2")])

        with self.assertRaises(CredentialException):
            dao.findByID("3")

    def test_the_refusal_names_the_id(self):
        dao = _dao([_user(3, "guest35996"), _user(3, "looptest2")])

        try:
            dao.findByID("3")
            self.fail("duplicate IDs were accepted")
        except CredentialException as exc:
            self.assertIn("3", str(exc),
                          "the refusal does not say which ID is duplicated")

    def test_neither_duplicate_is_returned(self):
        """Refusing beats returning whichever one Mongo reached first."""
        dao = _dao([_user(3, "guest35996"), _user(3, "looptest2")])

        try:
            result = dao.findByID("3")
        except CredentialException:
            result = None

        self.assertIsNone(result)

    def test_a_password_filter_still_narrows_the_query(self):
        """findByEmail-style credential checks pass a password in otherParams."""
        dao = _dao([_user(3, "alice", password="hashA"),
                    _user(3, "bob", password="hashB")])

        found = dao.findByID("3", {"password": "hashA"})

        self.assertIsNotNone(found, "a password filter should isolate one row")
        self.assertEqual(found.getUserName(), "alice")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
