#!/usr/bin/env python3
"""Behavioural cover for src/common/DAO/MOREJobDAO.py.

MOREJobDAO arrived with the MORE-v2 merge written against the pymongo 3 API --
Collection.insert / update / remove, all three removed in pymongo 4.0. The
merge commit migrated them to insert_one / replace_one / delete_many, but
test_pymongo4_compat only greps the source for the banned names. Nothing
checked that the replacements were given the right *arguments*, and the three
substitutions are not interchangeable:

  - update()  replaced the matched document wholesale, so replace_one is the
    equivalent, not update_one (which would demand $ operators and raise
    "update only works with $ operators" on a bare document).
  - remove()  deleted every match, so delete_many is the equivalent, not
    delete_one.
  - neither old call upserted by default, so upsert must stay off.

These tests drive a fake collection, so they need neither a mongod nor the
network. The fake raises on the removed pymongo-3 names, which turns any
regression back to the old API into a test failure rather than a runtime
AttributeError on a production write.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_job_dao
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.MOREJob import MOREJob
from src.common.DAO.MOREJobDAO import MOREJobDAO


class RemovedPymongoAPI(AssertionError):
    """Raised if the DAO reaches for an API pymongo 4 deleted."""


class FakeCollection(object):
    """Records calls; refuses the pymongo-3 API the migration removed."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.calls = []

    # -- the pymongo 4 API the DAO is supposed to use --------------------
    def insert_one(self, document):
        self.calls.append(("insert_one", document))
        self.docs.append(dict(document))

    def find_one(self, query):
        self.calls.append(("find_one", query))
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def replace_one(self, query, replacement, upsert=False):
        self.calls.append(("replace_one", query, replacement, upsert))
        for idx, doc in enumerate(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                self.docs[idx] = dict(replacement)
                return
        if upsert:
            self.docs.append(dict(replacement))

    def delete_many(self, query):
        self.calls.append(("delete_many", query))
        before = len(self.docs)
        self.docs = [d for d in self.docs
                     if not all(d.get(k) == v for k, v in query.items())]
        return before - len(self.docs)

    # -- removed in pymongo 4.0 ------------------------------------------
    def insert(self, *a, **k):
        raise RemovedPymongoAPI("Collection.insert was removed in pymongo 4.0")

    def update(self, *a, **k):
        raise RemovedPymongoAPI("Collection.update was removed in pymongo 4.0")

    def remove(self, *a, **k):
        raise RemovedPymongoAPI("Collection.remove was removed in pymongo 4.0")

    def delete_one(self, *a, **k):
        raise AssertionError("delete_one drops only one match; remove() dropped all")

    def update_one(self, *a, **k):
        raise AssertionError("update_one needs $ operators; the payload is a whole doc")

    def names(self):
        return [c[0] for c in self.calls]


class FakeDBManager(object):
    def __init__(self, collection):
        self.collection = collection
        self.requested = []

    def getCollection(self, collectionName):
        self.requested.append(collectionName)
        return self.collection

    def closeConnection(self):
        pass


def makeDAO(docs=None):
    collection = FakeCollection(docs)
    dao = MOREJobDAO(dbManager=FakeDBManager(collection))
    return dao, collection


def makeJob(jobID="job123", userID="user1"):
    job = MOREJob(jobID, userID, "/tmp")
    job.conditionsFile = "design.tsv"
    job.method = "MLR"
    job.addRegulatoryOmic("miRNA", "m.tsv", "miRNA", minVariation=0.1)
    return job


class WiringTest(unittest.TestCase):

    def test_uses_the_shared_job_collection(self):
        """MOREJobDAO sets no collectionName of its own; it must inherit
        JobDAO's, or every MORE job lands in a collection called ""."""
        dao, _ = makeDAO()
        self.assertEqual(dao.collectionName, "jobInstanceCollection")
        dao.insert(makeJob())
        self.assertEqual(dao.dbManager.requested, ["jobInstanceCollection"])

    def test_clazz_is_morejob(self):
        dao, _ = makeDAO()
        self.assertIs(dao.clazz, MOREJob)


class InsertTest(unittest.TestCase):

    def test_uses_insert_one(self):
        dao, collection = makeDAO()
        self.assertTrue(dao.insert(makeJob()))
        self.assertEqual(collection.names(), ["insert_one"])

    def test_stamps_the_job_type_so_jobdao_can_dispatch_deletes(self):
        """JobDAO.remove routes on jobType; an unstamped doc goes to the
        PathwayAcquisition DAO instead."""
        dao, collection = makeDAO()
        dao.insert(makeJob())
        self.assertEqual(collection.docs[0]["jobType"], "MOREJob")

    def test_persists_the_model_configuration(self):
        dao, collection = makeDAO()
        dao.insert(makeJob())
        stored = collection.docs[0]
        self.assertEqual(stored["jobID"], "job123")
        self.assertEqual(stored["method"], "MLR")
        self.assertEqual(stored["conditionsFile"], "design.tsv")
        self.assertEqual(stored["regulatoryOmics"][0]["name"], "miRNA")


class FindByIDTest(unittest.TestCase):

    def _storedJob(self):
        dao, collection = makeDAO()
        dao.insert(makeJob())
        collection.docs[0]["_id"] = "objectid-stand-in"
        return collection

    def test_returns_none_when_absent(self):
        dao, _ = makeDAO()
        self.assertIsNone(dao.findByID("nope"))

    def test_queries_on_the_jobID_key_documents_are_stored_under(self):
        """Job.toBSON writes self.jobID as "jobID"; a "jobId" query (as two
        sibling DAOs use) silently matches nothing."""
        dao, collection = makeDAO()
        dao.findByID("job123")
        self.assertEqual(collection.calls[-1], ("find_one", {"jobID": "job123"}))

    def test_returns_a_populated_morejob(self):
        dao = MOREJobDAO(dbManager=FakeDBManager(self._storedJob()))
        job = dao.findByID("job123")
        self.assertIsInstance(job, MOREJob)
        self.assertEqual(job.getJobID(), "job123")
        self.assertEqual(job.method, "MLR")
        self.assertEqual(job.conditionsFile, "design.tsv")

    def test_restores_the_regulatory_omics_list(self):
        dao = MOREJobDAO(dbManager=FakeDBManager(self._storedJob()))
        job = dao.findByID("job123")
        self.assertEqual(len(job.regulatoryOmics), 1)
        self.assertEqual(job.regulatoryOmics[0]["name"], "miRNA")
        self.assertEqual(job.regulatoryOmics[0]["minVariation"], 0.1)

    def test_round_trip_preserves_the_owner(self):
        dao = MOREJobDAO(dbManager=FakeDBManager(self._storedJob()))
        self.assertEqual(dao.findByID("job123").getUserID(), "user1")


class UpdateTest(unittest.TestCase):

    def test_uses_replace_one_not_update_one(self):
        dao, collection = makeDAO()
        dao.insert(makeJob())
        job = makeJob()
        job.method = "PLS1"
        self.assertTrue(dao.update(job))
        self.assertIn("replace_one", collection.names())

    def test_replaces_the_matching_document(self):
        dao, collection = makeDAO()
        dao.insert(makeJob())
        job = makeJob()
        job.method = "PLS1"
        dao.update(job)
        self.assertEqual(len(collection.docs), 1)
        self.assertEqual(collection.docs[0]["method"], "PLS1")

    def test_matches_on_jobID(self):
        dao, collection = makeDAO()
        dao.update(makeJob())
        call = [c for c in collection.calls if c[0] == "replace_one"][0]
        self.assertEqual(call[1], {"jobID": "job123"})

    def test_does_not_upsert(self):
        """The removed update() did not upsert; turning it on would let an
        update of a deleted job silently resurrect it."""
        dao, collection = makeDAO()
        dao.update(makeJob())
        call = [c for c in collection.calls if c[0] == "replace_one"][0]
        self.assertFalse(call[3], "replace_one must not upsert")
        self.assertEqual(collection.docs, [])


class RemoveTest(unittest.TestCase):

    def test_uses_delete_many(self):
        dao, collection = makeDAO()
        dao.insert(makeJob())
        self.assertTrue(dao.remove("job123"))
        self.assertIn("delete_many", collection.names())
        self.assertEqual(collection.docs, [])

    def test_scopes_to_the_owner_when_given_one(self):
        """Without the userID clause any user could delete another's job."""
        dao, collection = makeDAO()
        dao.insert(makeJob())
        dao.remove("job123", {"userID": "user1"})
        call = [c for c in collection.calls if c[0] == "delete_many"][0]
        self.assertEqual(call[1], {"jobID": "job123", "userID": "user1"})
        self.assertEqual(collection.docs, [])

    def test_a_foreign_owner_deletes_nothing(self):
        dao, collection = makeDAO()
        dao.insert(makeJob())
        dao.remove("job123", {"userID": "someone-else"})
        self.assertEqual(len(collection.docs), 1)

    def test_without_otherParams_it_matches_on_job_alone(self):
        dao, collection = makeDAO()
        dao.remove("job123")
        call = [c for c in collection.calls if c[0] == "delete_many"][0]
        self.assertEqual(call[1], {"jobID": "job123"})

    def test_an_empty_otherParams_dict_is_treated_as_absent(self):
        dao, collection = makeDAO()
        dao.remove("job123", {})
        call = [c for c in collection.calls if c[0] == "delete_many"][0]
        self.assertEqual(call[1], {"jobID": "job123"})

    def test_removing_a_missing_job_is_not_an_error(self):
        dao, _ = makeDAO()
        self.assertTrue(dao.remove("nope", {"userID": "user1"}))


class NoRemovedPymongoAPITest(unittest.TestCase):
    """The fake raises on insert/update/remove, so reaching for the pymongo-3
    API fails here instead of on a production write."""

    def test_every_write_path_uses_the_pymongo4_api(self):
        dao, _ = makeDAO()
        dao.insert(makeJob())
        dao.update(makeJob())
        dao.remove("job123", {"userID": "user1"})
        dao.findByID("job123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
