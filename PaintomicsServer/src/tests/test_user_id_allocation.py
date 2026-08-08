#!/usr/bin/env python3
"""An allocated user ID must not already belong to somebody.

Why this exists
---------------
`getNextUserID` allocates from an atomic `$inc` counter, which fixed the old
`len(userCollection)` allocator. The counter is seeded once, from the highest ID
then present:

    if counters.find_one({"_id": "userID"}) is None:
        ... seed at highestExisting ...

Seeding once is the gap. If the counter ever sits *below* the collection --
because it was seeded while the collection held fewer users, or rows arrived by
another route, or a database was restored over it -- `$inc` hands out IDs that
already belong to somebody, and it keeps doing so. Nothing notices, because
`insert_one` is happy to write a second row with the same `userID`: the index on
that field is not unique.

This was found live, not theorised. On this machine the counter read
`sequence_value: 4` while accounts existed at IDs 1-5, so a fresh signup was
issued ID 4 and collided with an existing account. Three IDs -- 2, 3 and 4 --
each ended up shared by two accounts.

What a shared ID costs is in test_duplicate_user_ids.py: `findByID` returned an
arbitrary one of the two, so changing your password changed *someone else's*.
That is the symptom; this is the cause.

The fix keeps the counter as the fast path and verifies the result: if the ID it
returns is taken, step past it. Bounded, so a pathological collection cannot
spin forever, and it raises rather than returning a known-colliding ID.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_user_id_allocation
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.DAO.UserDAO import UserDAO


class _FakeCounters:
    def __init__(self, value=None):
        self.document = None if value is None else {"_id": "userID",
                                                   "sequence_value": value}

    def find_one(self, query):
        return self.document

    def insert_one(self, document):
        self.document = dict(document)

    def find_one_and_update(self, query, update, return_document=None):
        self.document["sequence_value"] += update["$inc"]["sequence_value"]
        return dict(self.document)


class _FakeUsers:
    def __init__(self, existingIDs):
        self.documents = [{"userID": i} for i in existingIDs]

    def find(self, query=None, projection=None):
        if not query:
            return list(self.documents)
        return [d for d in self.documents
                if all(d.get(k) == v for k, v in query.items())]

    def count_documents(self, query):
        return len(self.find(query))

    def find_one(self, query):
        matches = self.find(query)
        return matches[0] if matches else None


class _FakeDbManager:
    def __init__(self, users, counters):
        self.users = users
        self.counters = counters

    def getCollection(self, name):
        return self.counters if name == "counters" else self.users


def _dao(existingIDs, counterValue=None):
    dao = UserDAO.__new__(UserDAO)
    dao.collectionName = "userCollection"
    dao.dbManager = _FakeDbManager(_FakeUsers(existingIDs),
                                   _FakeCounters(counterValue))
    return dao


class FreshCounterTest(unittest.TestCase):

    def test_an_empty_collection_starts_at_one(self):
        """Never 0: isValidUser used to accept "0" with any session token."""
        self.assertEqual(_dao([]).getNextUserID(), 1)

    def test_the_counter_is_seeded_above_the_highest_existing_id(self):
        self.assertEqual(_dao([1, 2, 5]).getNextUserID(), 6)

    def test_successive_calls_do_not_repeat(self):
        dao = _dao([1, 2])
        issued = [dao.getNextUserID() for _ in range(4)]

        self.assertEqual(len(set(issued)), 4, "an ID was issued twice: %s" % issued)


class DriftedCounterTest(unittest.TestCase):
    """The live failure: the counter sits below the collection."""

    def test_an_id_already_taken_is_not_issued(self):
        """Counter at 3, accounts at 1-5: naive $inc returns 4, which is taken."""
        allocated = _dao([1, 2, 3, 4, 5], counterValue=3).getNextUserID()

        self.assertNotIn(allocated, {1, 2, 3, 4, 5},
                         "allocated ID %s already belongs to an account"
                         % allocated)

    def test_it_steps_past_a_run_of_taken_ids(self):
        allocated = _dao(list(range(1, 20)), counterValue=1).getNextUserID()

        self.assertNotIn(allocated, set(range(1, 20)))

    def test_repeated_allocation_stays_collision_free(self):
        dao = _dao([1, 2, 3, 4, 5], counterValue=2)
        issued = []
        for _ in range(5):
            newID = dao.getNextUserID()
            issued.append(newID)
            dao.dbManager.users.documents.append({"userID": newID})

        self.assertEqual(len(set(issued)), len(issued),
                         "duplicate issued across calls: %s" % issued)
        self.assertFalse(set(issued) & {1, 2, 3, 4, 5},
                         "issued an ID that was already taken: %s" % issued)

    def test_a_counter_far_ahead_is_left_alone(self):
        """Being ahead is harmless; only being behind collides."""
        self.assertEqual(_dao([1, 2], counterValue=100).getNextUserID(), 101)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
