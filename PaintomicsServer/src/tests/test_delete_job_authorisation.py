#!/usr/bin/env python3
"""Deleting a job must not delete someone else's features and pathways.

Why this exists
---------------
`PathwayAcquisitionJobDAO.remove` scoped the job document to its owner and then
cascaded on the job id alone:

    collection.delete_many({"jobID": id, "userID": otherParams.get("userID")})

    FeatureDAO().removeAll({"jobID": id})
    PathwayDAO(...).removeAll({"jobID": id})

So a request to delete a job belonging to someone else removed nothing from
jobInstanceCollection -- correctly -- and then deleted every feature and every
pathway of that job anyway. The owner keeps a job record whose contents are
gone: opening it shows no pathways and no features.

No authentication was needed either. `dm_delete_job` asks only for
`isValidUser`, and that deliberately lets the anonymous "nologin" case through,
so a request with no cookies at all reached the cascade. Measured against a
running server before the fix:

    before                  job=1 features=5 pathways=3
    after anonymous delete  job=1 features=0 pathways=0
    HTTP response           success: True

and after it:

    attack  after   job=1 features=5 pathways=3   (unchanged)
    owner   after   job=0 features=0 pathways=0   (deleted, as it should be)

Job ids are not secret. The results page prints "You can access this job using
the URL ...?jobID=...", and there is a sharing feature, so anyone ever given a
link had everything needed.

The fix ties the cascade to the ownership check that was already there: if the
scoped delete matched no document, the caller does not own the job and nothing
further is removed. Anonymous jobs store `userID: None` and match that filter
normally -- every job on this machine is one of those -- so ordinary deletion is
untouched, which the second test below pins.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_delete_job_authorisation
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

JOBS = "jobInstanceCollection"
FEATURES = "featuresCollection"
PATHWAYS = "pathwaysCollection"


def _database():
    from pymongo import MongoClient
    from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
    client = MongoClient(MONGODB_HOST, MONGODB_PORT, serverSelectionTimeoutMS=2000)
    client.admin.command("ping")
    return client, client["PaintomicsDB"]


class DeleteJobAuthorisationTest(unittest.TestCase):

    JOB_ID = "ZZTEST_DELETE_AUTH"

    @classmethod
    def setUpClass(cls):
        try:
            cls.client, cls.db = _database()
        except Exception as exc:
            raise unittest.SkipTest("MongoDB not reachable: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "db", None) is not None:
            cls._purge(cls.db, cls.JOB_ID)
            cls.client.close()

    @staticmethod
    def _purge(db, jobID):
        for name in (JOBS, FEATURES, PATHWAYS):
            db[name].delete_many({"jobID": jobID})

    def _plant(self, owner):
        self._purge(self.db, self.JOB_ID)
        self.db[JOBS].insert_one({"jobID": self.JOB_ID, "userID": owner, "lastStep": 3})
        self.db[FEATURES].insert_many(
            [{"jobID": self.JOB_ID, "ID": "g%d" % i} for i in range(5)])
        self.db[PATHWAYS].insert_many(
            [{"jobID": self.JOB_ID, "ID": "p%d" % i} for i in range(3)])

    def _counts(self):
        return (self.db[JOBS].count_documents({"jobID": self.JOB_ID}),
                self.db[FEATURES].count_documents({"jobID": self.JOB_ID}),
                self.db[PATHWAYS].count_documents({"jobID": self.JOB_ID}))

    def _remove(self, asUser):
        from src.common.DAO.PathwayAcquisitionJobDAO import PathwayAcquisitionJobDAO
        dao = PathwayAcquisitionJobDAO()
        try:
            return dao.remove(self.JOB_ID, {"userID": asUser})
        finally:
            dao.closeConnection()

    def tearDown(self):
        self._purge(self.db, self.JOB_ID)

    def test_another_user_cannot_delete_the_features(self):
        self._plant(owner="9001")

        self._remove(asUser="9002")

        _jobs, features, _pathways = self._counts()
        self.assertEqual(features, 5,
                         "a different user's delete removed %d of 5 features"
                         % (5 - features))

    def test_another_user_cannot_delete_the_pathways(self):
        self._plant(owner="9001")

        self._remove(asUser="9002")

        _jobs, _features, pathways = self._counts()
        self.assertEqual(pathways, 3,
                         "a different user's delete removed %d of 3 pathways"
                         % (3 - pathways))

    def test_an_unauthenticated_caller_cannot_either(self):
        """isValidUser lets the anonymous case through, so this is the real one."""
        self._plant(owner="9001")

        self._remove(asUser=None)

        self.assertEqual(self._counts(), (1, 5, 3),
                         "an unauthenticated delete changed an owned job")

    def test_the_refusal_is_reported(self):
        self._plant(owner="9001")

        self.assertFalse(self._remove(asUser="9002"),
                         "remove() reported success for a job the caller does "
                         "not own")

    def test_the_owner_can_still_delete_everything(self):
        """The fix must not make deletion stop working."""
        self._plant(owner="9001")

        self.assertTrue(self._remove(asUser="9001"))
        self.assertEqual(self._counts(), (0, 0, 0),
                         "the owner's delete left something behind")

    def test_an_anonymous_job_can_still_be_deleted(self):
        """Every job on this machine has userID None, so this is the common case."""
        self._plant(owner=None)

        self.assertTrue(self._remove(asUser=None))
        self.assertEqual(self._counts(), (0, 0, 0),
                         "an anonymous job could no longer be deleted, which "
                         "would break ordinary use")


class DataManagementJobDeletionTest(unittest.TestCase):
    """Deleting a Regions2Genes or miRNA2Genes job must actually delete it.

    Both DAOs filtered on "jobId" while every document in
    jobInstanceCollection stores "jobID". Nothing has ever written the
    lowercase form -- checked across every collection in the database, zero
    documents carry it -- so the filter matched nothing, `delete_many` removed
    no rows, and `remove` still returned True. The job stayed in the database
    and the caller was told it had gone.
    """

    JOB_ID = "ZZTEST_DM_DELETE"

    @classmethod
    def setUpClass(cls):
        try:
            cls.client, cls.db = _database()
        except Exception as exc:
            raise unittest.SkipTest("MongoDB not reachable: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "db", None) is not None:
            cls.db[JOBS].delete_many({"jobID": cls.JOB_ID})
            cls.client.close()

    def tearDown(self):
        self.db[JOBS].delete_many({"jobID": self.JOB_ID})

    def _daos(self):
        from src.common.DAO.Bed2GeneJobDAO import Bed2GeneJobDAO
        from src.common.DAO.MiRNA2GeneJobDAO import MiRNA2GeneJobDAO
        return (("Bed2GeneJobDAO", Bed2GeneJobDAO),
                ("MiRNA2GeneJobDAO", MiRNA2GeneJobDAO))

    def _plant(self, owner):
        self.db[JOBS].delete_many({"jobID": self.JOB_ID})
        self.db[JOBS].insert_one({"jobID": self.JOB_ID, "userID": owner,
                                  "jobType": "MiRNA2GeneJob"})

    def _remove(self, daoClass, asUser):
        dao = daoClass()
        try:
            return dao.remove(self.JOB_ID, {"userID": asUser})
        finally:
            dao.closeConnection()

    def test_the_owner_can_delete_the_job(self):
        for label, daoClass in self._daos():
            with self.subTest(dao=label):
                self._plant(owner=None)

                self._remove(daoClass, asUser=None)

                self.assertEqual(
                    self.db[JOBS].count_documents({"jobID": self.JOB_ID}), 0,
                    "%s reported success but the job is still in the database "
                    "-- check the field name in its delete filter" % label)

    def test_another_user_still_cannot(self):
        """The field fix must not widen what the delete reaches."""
        for label, daoClass in self._daos():
            with self.subTest(dao=label):
                self._plant(owner="9001")

                self._remove(daoClass, asUser="9002")

                self.assertEqual(
                    self.db[JOBS].count_documents({"jobID": self.JOB_ID}), 1,
                    "%s deleted a job belonging to someone else" % label)

    def test_no_document_uses_the_lowercase_field(self):
        """The premise of the fix, checked rather than assumed."""
        offenders = {name: self.db[name].count_documents({"jobId": {"$exists": True}})
                     for name in self.db.list_collection_names()}

        self.assertEqual({k: v for k, v in offenders.items() if v}, {},
                         "some documents do use 'jobId', so the field name is "
                         "not simply a typo and this fix needs revisiting")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
