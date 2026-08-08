#!/usr/bin/env python3
"""Polling a finished job twice at once must not 500.

Why this exists
---------------
`checkJobStatus` reads the job, then consumes it, in two unsynchronised steps:

    jobInstance = self.queue.fetch_job(jobID)          # (1)
    ...
    elif jobInstance.is_finished():
        return self.queue.get_result(jobID).getResponse()   # (2) pops

`get_result` removes a finished job from `self.jobs` and returns its result --
but when the job is already gone it returns the *enum* `JobStatus.NOT_QUEUED`,
which has no `getResponse`. Two clients that both get past (1) before either
reaches (2) therefore produce one normal response and one

    AttributeError: 'JobStatus' object has no attribute 'getResponse'

which reaches the browser as a 500 with nothing useful in it. Reproduced by
forcing that interleaving with a barrier; the first attempt without one hit the
benign order and looked fine, which is why the barrier is in the test.

The window is small but the client polls `/check_job_status/<jobID>` every six
seconds, so two tabs open on the same job -- or a refresh landing next to a
poll -- is enough. A job that *succeeded* is the case that breaks, which makes
it worse than it sounds: the user is told the analysis failed at the moment it
finished.

The fix is in two places. `get_result` does its lookup and removal under the
queue lock rather than as a bare check-then-act on a shared dict, and the
handler treats "already consumed" the same way it treats a job that was never
there -- the honest answer, since another poller has taken the result.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_job_status_concurrent_poll
"""
import collections
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.PySiQ import Job, JobStatus, Queue


class _Result:
    def getResponse(self):
        return "OK"


def _queueWithFinishedJob(jobID="J1"):
    queue = Queue.__new__(Queue)
    queue.lock = threading.Lock()
    queue.queue = collections.deque([])
    queue.jobs = {}
    queue.workers = []

    job = Job(lambda: None, ())
    job.set_id(jobID)
    job.status = JobStatus.FINISHED
    job.result = _Result()
    queue.jobs[jobID] = job
    return queue


class ConcurrentPollTest(unittest.TestCase):

    def test_two_pollers_past_the_fetch_do_not_raise(self):
        """The interleaving the handler leaves open, forced deliberately."""
        queue = _queueWithFinishedJob()
        barrier = threading.Barrier(2)
        errors, served = [], []

        def poll():
            try:
                job = queue.fetch_job("J1")
                barrier.wait()                  # both past (1) before either pops
                if job is not None and job.status == JobStatus.FINISHED:
                    result = queue.get_result("J1")
                    if hasattr(result, "getResponse"):
                        served.append(result.getResponse())
                    else:
                        served.append("already-consumed")
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=poll) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [], "a concurrent poll raised: %s" % errors)
        self.assertEqual(len(served), 2)
        self.assertIn("OK", served, "neither poller got the result")

    def test_the_result_is_handed_out_once(self):
        queue = _queueWithFinishedJob()
        got = []

        for _ in range(3):
            got.append(queue.get_result("J1"))

        real = [r for r in got if hasattr(r, "getResponse")]
        self.assertEqual(len(real), 1,
                         "the finished job's result was handed out %d times"
                         % len(real))

    def test_a_consumed_job_reports_not_queued_rather_than_raising(self):
        queue = _queueWithFinishedJob()
        queue.get_result("J1")

        self.assertEqual(queue.get_result("J1"), JobStatus.NOT_QUEUED)

    def test_get_result_is_safe_under_parallel_callers(self):
        """Many pollers, one finished job: exactly one result, no exceptions."""
        queue = _queueWithFinishedJob()
        errors, real = [], []
        start = threading.Barrier(8)

        def take():
            try:
                start.wait()
                result = queue.get_result("J1")
                if hasattr(result, "getResponse"):
                    real.append(result)
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=take) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(real), 1,
                         "the result was handed to %d callers" % len(real))

    def test_an_unknown_job_is_not_queued(self):
        queue = _queueWithFinishedJob()

        self.assertEqual(queue.get_result("no-such-job"), JobStatus.NOT_QUEUED)


class HandlerGuardTest(unittest.TestCase):
    """The handler must not call getResponse on whatever comes back."""

    def test_the_handler_checks_what_get_result_returned(self):
        import inspect
        from src import paintomicsserver

        source = inspect.getsource(paintomicsserver.Application.__init__)
        marker = "def checkJobStatus"
        self.assertIn(marker, source)
        body = source.split(marker, 1)[1].split("def ", 1)[0]

        self.assertNotIn("self.queue.get_result(jobID).getResponse()", body,
                         "the handler calls getResponse() directly on "
                         "get_result(), which returns the JobStatus enum when "
                         "another poller has already consumed the job")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
