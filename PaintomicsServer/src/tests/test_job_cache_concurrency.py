#!/usr/bin/env python3
"""Concurrent requests for one job must share one instance of it.

Why this exists
---------------
`loadJobInstance` looks in the cache, loads from MongoDB on a miss, and caches
the result. `findInCache` and `addToCache` each take the lock, but the sequence
between them does not:

    jobInstance = self.findInCache(jobID)          # locked
    if jobInstance is None:
        jobInstance = PathwayAcquisitionJobDAO().findByID(jobID)   # slow
        self.addToCache(jobInstance)               # locked

Measured with five concurrent requests for one uncached job: the DAO was hit
**five times**, five distinct objects were handed out, and the cache ended up
holding five copies. This is the same shape as the KEGG organism cache fixed in
68faf35b, in the path every job-touching request goes through.

Here it is worse than repeated work, because a `PathwayAcquisitionJob` is
mutable and gets written back. Two requests that each load, change something,
and store will change *different objects*:

    request A's object: {'visualOptions': 'A'}
    request B's object: {'sharingOptions': 'B'}

and whichever reaches MongoDB last overwrites the other's change. Being fair
about frequency: the duplicate loads and the cache filling with copies happen
whenever two requests race a cold entry, which is common; the lost update needs
two concurrent *writes* to the same job -- a save of visual options next to a
save of sharing options, say -- which is possible but rarer.

The cache holds 50 jobs and evicts, so "cold" is not only the first-ever access.

The fix is double-checked: the fast path is unchanged, and only a miss takes the
load lock and re-checks inside it, so the second caller finds what the first
loaded instead of loading its own copy. The lock is separate from `self.lock`
because it is held across a database read, and the cache's own operations must
not queue behind that.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_job_cache_concurrency
"""
import collections
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import src.common.JobInformationManager as JIM
from src.common.JobInformationManager import JobInformationManager


class _Job:
    def __init__(self, jobID):
        self.jobID = jobID
        self.fields = {}

    def getJobID(self):
        return self.jobID


class _DAO:
    """Stands in for PathwayAcquisitionJobDAO; records every load."""

    loads = []
    delay = 0.08

    def findByID(self, jobID):
        _DAO.loads.append(jobID)
        time.sleep(_DAO.delay)
        return _Job(jobID)

    def closeConnection(self):
        pass


class _ManagerCase(unittest.TestCase):

    def setUp(self):
        self.manager = JobInformationManager.__new__(JobInformationManager)
        self.manager.lock = threading.RLock()
        self.manager.jobLoadLock = threading.RLock()
        self.manager.recentJobs = collections.deque([])
        self.manager.touchAccessDate = lambda jobID: None

        _DAO.loads = []
        self._savedDAO = JIM.PathwayAcquisitionJobDAO
        JIM.PathwayAcquisitionJobDAO = _DAO

    def tearDown(self):
        JIM.PathwayAcquisitionJobDAO = self._savedDAO

    def _loadConcurrently(self, jobID, n):
        got = []
        gotLock = threading.Lock()

        def load():
            instance = self.manager.loadJobInstance(jobID)
            with gotLock:
                got.append(instance)

        threads = [threading.Thread(target=load) for _ in range(n)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return got


class SharedJobInstanceTest(_ManagerCase):

    def test_one_uncached_job_is_loaded_once(self):
        self._loadConcurrently("JOB1", 5)

        self.assertEqual(len(_DAO.loads), 1,
                         "the job was read from MongoDB %d times for 5 "
                         "concurrent requests" % len(_DAO.loads))

    def test_every_caller_gets_the_same_instance(self):
        """Different objects for one job is how an update gets lost."""
        got = self._loadConcurrently("JOB1", 5)

        self.assertEqual(len(set(id(g) for g in got)), 1,
                         "%d different objects were handed out for one job"
                         % len(set(id(g) for g in got)))

    def test_the_cache_holds_one_copy(self):
        self._loadConcurrently("JOB1", 5)

        copies = [j for j in self.manager.recentJobs
                  if j.getJobID() == "JOB1"]
        self.assertEqual(len(copies), 1,
                         "the cache holds %d copies of one job, crowding out "
                         "the other 49 slots" % len(copies))

    def test_a_change_by_one_request_is_visible_to_the_other(self):
        """The lost update, stated as the property that prevents it."""
        got = self._loadConcurrently("JOB1", 2)
        got[0].fields["visualOptions"] = "A"

        self.assertEqual(got[1].fields.get("visualOptions"), "A",
                         "two concurrent requests hold separate copies, so "
                         "whichever is stored last overwrites the other")

    def test_a_warm_cache_does_not_reload(self):
        self.manager.loadJobInstance("JOB1")
        _DAO.loads = []

        self._loadConcurrently("JOB1", 4)

        self.assertEqual(_DAO.loads, [],
                         "a cached job was re-read from the database")

    def test_different_jobs_are_all_loaded(self):
        threads = [threading.Thread(
            target=lambda j=j: self.manager.loadJobInstance(j))
            for j in ("A", "B", "C", "D")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(_DAO.loads), ["A", "B", "C", "D"])

    def test_storing_one_job_concurrently_caches_it_once(self):
        """storeJobInstance has the same check-then-act, milder consequences.

        It does

            if self.findInCache(jobID) is None:
                self.addToCache(jobInstance)

        on adjacent lines, so the window is microseconds rather than a database
        read. And it caches the instance the caller already holds, so racing
        stores duplicate *the same object* -- forced open, four concurrent
        stores left four entries that were all `is` each other. No divergent
        state and no lost update, unlike loadJobInstance; the cost is cache
        slots, a job occupying several of fifty and evicting other jobs into
        fresh database reads. Closed because it is the same pattern, not
        because anyone is losing work to it.
        """
        job = _Job("JOB1")
        started = threading.Barrier(4)

        def store():
            started.wait()
            self.manager.cacheJobInstance(job)

        threads = [threading.Thread(target=store) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        copies = [j for j in self.manager.recentJobs
                  if j.getJobID() == "JOB1"]
        self.assertEqual(len(copies), 1,
                         "one job took %d of the cache's 50 slots" % len(copies))

    def test_caching_an_already_cached_job_is_a_no_op(self):
        job = _Job("JOB1")
        self.manager.cacheJobInstance(job)
        self.manager.cacheJobInstance(job)

        self.assertEqual(len(self.manager.recentJobs), 1)

    def test_a_job_missing_from_the_database_is_not_cached(self):
        class _MissingDAO(_DAO):
            def findByID(self, jobID):
                _DAO.loads.append(jobID)
                return None

        JIM.PathwayAcquisitionJobDAO = _MissingDAO

        self.assertIsNone(self.manager.loadJobInstance("GONE"))
        self.assertEqual(len(self.manager.recentJobs), 0)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
