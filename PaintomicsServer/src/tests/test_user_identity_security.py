#!/usr/bin/env python3
"""Tests for the two defects that made user identity forgeable.

isValidUser accepted the literal user ID "0" with any session token, under a
comment reading "TODO: security breach? (== 0)". It was one: UserDAO handed out
IDs as len(userCollection), so the first person to register became user 0, and
from that moment anyone could act as them by sending the cookie userID=0 -- no
password, no token. Confirmed against a running server, where userID=0 with a
garbage token returned that user's job list and was accepted by dm_delete_job.

The same allocator reused IDs, because a count is not a sequence: with users
0,1,2 present, deleting user 1 leaves a count of 2, so the next signup is handed
ID 2 and collides with the existing account.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_user_identity_security
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.ServerErrorManager import CredentialException
from src.common.UserSessionManager import UserSessionManager


class SessionValidationTest(unittest.TestCase):

    def setUp(self):
        self.sessions = UserSessionManager()

    def test_user_zero_is_no_longer_a_free_pass(self):
        with self.assertRaises(CredentialException):
            self.sessions.isValidUser("0", "GARBAGE")

    def test_user_zero_rejected_even_with_no_token(self):
        with self.assertRaises(CredentialException):
            self.sessions.isValidUser("0", None)

    def test_integer_zero_rejected_too(self):
        # The cookie arrives as a string, but isValidUser str()s whatever it is
        # given -- so the numeric form must not slip past either.
        with self.assertRaises(CredentialException):
            self.sessions.isValidUser(0, "GARBAGE")

    def test_anonymous_nologin_mode_still_works(self):
        # Jobs submitted without an account are a supported mode, not a bypass:
        # they live under CLIENT_TMP/nologin and belong to nobody.
        self.assertTrue(self.sessions.isValidUser(None, None))

    def test_real_session_still_validates(self):
        token = self.sessions.registerNewUser(4242)
        self.assertIsNone(self.sessions.isValidUser("4242", token))
        with self.assertRaises(CredentialException):
            self.sessions.isValidUser("4242", token + "x")
        self.sessions.removeUser(4242, token)

    def test_known_id_with_wrong_token_is_rejected(self):
        token = self.sessions.registerNewUser(4243)
        with self.assertRaises(CredentialException):
            self.sessions.isValidUser("4243", "GARBAGE")
        self.sessions.removeUser(4243, token)


class UserIDAllocationTest(unittest.TestCase):
    """Exercises the allocator against a real MongoDB, skipping if none is up."""

    COUNTER_COLLECTION = "counters"

    @classmethod
    def setUpClass(cls):
        try:
            from pymongo import MongoClient
            from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
            cls.client = MongoClient(MONGODB_HOST, MONGODB_PORT,
                                     serverSelectionTimeoutMS=2000)
            cls.client.admin.command("ping")
        except Exception as ex:
            raise unittest.SkipTest("no MongoDB available: %s" % ex)
        cls.db = cls.client["PaintomicsUserIDAllocationTest"]

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "client"):
            cls.client.drop_database("PaintomicsUserIDAllocationTest")
            cls.client.close()

    def setUp(self):
        self.db.drop_collection("userCollection")
        self.db.drop_collection(self.COUNTER_COLLECTION)
        self.dao = self._makeDAO()

    def _makeDAO(self):
        from src.common.DAO.UserDAO import UserDAO
        dao = UserDAO.__new__(UserDAO)
        dao.collectionName = "userCollection"

        db = self.db

        class _Manager(object):
            @staticmethod
            def getCollection(name):
                return db[name]

        dao.dbManager = _Manager()
        return dao

    def test_first_id_is_never_zero(self):
        self.assertNotEqual(self.dao.getNextUserID(), 0)

    def test_ids_are_unique_and_increasing(self):
        issued = [self.dao.getNextUserID() for _ in range(5)]
        self.assertEqual(len(set(issued)), 5)
        self.assertEqual(issued, sorted(issued))
        self.assertNotIn(0, issued)

    def test_deleting_a_user_does_not_recycle_their_id(self):
        first, second, third = (self.dao.getNextUserID() for _ in range(3))
        for uid in (first, second, third):
            self.db["userCollection"].insert_one({"userID": uid})
        self.db["userCollection"].delete_one({"userID": second})

        following = self.dao.getNextUserID()
        self.assertNotIn(following, (first, second, third),
                         "a deleted user's ID was handed to the next signup")

    def test_counter_seeds_above_ids_from_an_existing_install(self):
        # Simulates upgrading a deployment whose users were numbered by the old
        # len()-based scheme; the counter must not re-issue any of them.
        for uid in (0, 1, 2, 3):
            self.db["userCollection"].insert_one({"userID": uid})
        self.assertGreater(self.dao.getNextUserID(), 3)

    def test_malformed_existing_ids_do_not_break_seeding(self):
        self.db["userCollection"].insert_one({"userID": None})
        self.db["userCollection"].insert_one({"noUserIDField": True})
        self.db["userCollection"].insert_one({"userID": 9})
        self.assertGreater(self.dao.getNextUserID(), 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
