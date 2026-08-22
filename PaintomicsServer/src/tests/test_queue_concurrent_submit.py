#!/usr/bin/env python3
"""Two jobs submitted at once must both run, once each.

Why this exists
---------------
`Worker.notify()` decided whether to take work with an unsynchronised
check-then-act:

    if self.status != WorkerStatus.WORKING:
        job = self.queue.dequeue()      # locks internally
        if job != None:
            self.job = job              # single slot
            WorkerThread(self).start()

`Queue.dequeue()` takes the queue lock, but the sequence around it is not
atomic and `self.job` is one slot on a shared Worker. `Queue.enqueue()` calls
`notify_workers()` after releasing its own lock, so two submissions arriving
together produce two concurrent `notify()` calls on the *same* worker. Both see
a non-WORKING status, both dequeue -- taking two different jobs -- and the
second assignment to `self.job` discards the first.

Observed on the running server, submitting two example jobs simultaneously:

    NEW JOB v5tf1qB33w ADDED TO QUEUE      (A)
    NEW JOB NwR7xub435 ADDED TO QUEUE      (B)
    Worker wQIp4Wsy4HV starts working...
    Worker wQIp4Wsy4HV starts working...   <- same worker, two threads
    CREATING THE TEMPORAL CACHE FOR JOB NwR7xub435
    CREATING THE TEMPORAL CACHE FOR JOB NwR7xub435   <- B, twice

Two failures at once. **A was lost**: taken off the deque, never executed, left
reporting QUEUED indefinitely with no error the user could see -- it sat that
way for 205 seconds before I stopped waiting. **B ran twice concurrently**, two
threads writing one output directory, which is what produced

    ERROR ... pathwayAcquisitionStep1_PART2 - Failed while compressing directory
    AttributeError: 'NoneType' object has no attribute 'result'

the second from one thread's `finally` clearing `self.job` while the other was
still using it.

This is reachable by two users pressing "Run PaintOmics" in the same moment,
which on a shared server is ordinary rather than adversarial.

These tests drive `Queue` and `Worker` directly, because the race is in them and
because reproducing it through HTTP depends on timing that a test should not
rely on. The margin is widened deliberately -- many jobs, many concurrent
notifies -- so the assertion is about the invariant (every job runs exactly
once) rather than about hitting a window.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_queue_concurrent_submit
"""
import collections
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.PySiQ import JobStatus, Queue, Worker


def _bareQueue():
    """A Queue without the singleton metaclass, so tests do not share one."""
    queue = Queue.__new__(Queue)
    queue.lock = threading.Lock()
    queue.queue = collections.deque([])
    queue.jobs = {}
    queue.workers = []
    return queue


class ConcurrentSubmissionTest(unittest.TestCase):

    def setUp(self):
        self.queue = _bareQueue()
        self.ran = []
        self.ranLock = threading.Lock()

    def _record(self, tag):
        # A little work, so two threads on one worker actually overlap.
        time.sleep(0.02)
        with self.ranLock:
            self.ran.append(tag)
        return tag

    def _drain(self, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            pending = [job for job in self.queue.jobs.values()
                       if job.status in (JobStatus.QUEUED, JobStatus.STARTED)]
            if not pending:
                return True
            time.sleep(0.05)
        return False

    def test_two_simultaneous_submissions_both_run(self):
        """The reported case: two users pressing Run at the same moment."""
        worker = Worker("w1", self.queue)
        self.queue.workers.append(worker)

        def submit(tag):
            self.queue.enqueue(self._record, (tag,), job_id=tag)

        threads = [threading.Thread(target=submit, args=("job%d" % i,))
                   for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertTrue(self._drain(), "a job never finished: %s" % [
            (jid, str(j.status)) for jid, j in self.queue.jobs.items()])
        self.assertEqual(sorted(self.ran), ["job0", "job1"],
                         "both jobs should have run exactly once; ran: %s"
                         % sorted(self.ran))

    def test_no_job_is_left_queued_after_the_queue_drains(self):
        worker = Worker("w1", self.queue)
        self.queue.workers.append(worker)

        threads = [threading.Thread(
            target=lambda i=i: self.queue.enqueue(self._record, ("j%d" % i,),
                                                  job_id="j%d" % i))
            for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self._drain()

        stranded = [jid for jid, job in self.queue.jobs.items()
                    if job.status == JobStatus.QUEUED]
        self.assertEqual(stranded, [],
                         "jobs were taken off the deque and never executed: %s"
                         % stranded)

    def test_no_job_runs_twice(self):
        """B ran twice, two threads writing one output directory."""
        worker = Worker("w1", self.queue)
        self.queue.workers.append(worker)

        for index in range(8):
            self.queue.enqueue(self._record, ("k%d" % index,),
                               job_id="k%d" % index)
        self._drain()

        counts = collections.Counter(self.ran)
        repeated = {tag: n for tag, n in counts.items() if n > 1}
        self.assertEqual(repeated, {},
                         "a job was executed more than once: %s" % repeated)

    def test_concurrent_notify_does_not_double_start_one_worker(self):
        """The race in isolation: many notifies, one worker, one job slot."""
        worker = Worker("w1", self.queue)
        self.queue.workers.append(worker)
        for index in range(6):
            self.queue.enqueue(self._record, ("n%d" % index,),
                               job_id="n%d" % index)

        threads = [threading.Thread(target=worker.notify) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self._drain()

        counts = collections.Counter(self.ran)
        self.assertEqual(sorted(counts), ["n0", "n1", "n2", "n3", "n4", "n5"],
                         "not every job ran: %s" % sorted(counts))
        self.assertTrue(all(n == 1 for n in counts.values()),
                        "a job ran more than once: %s" % dict(counts))

    def test_a_failing_job_does_not_strand_the_next_one(self):
        """B's failure must not take the queue with it."""
        worker = Worker("w1", self.queue)
        self.queue.workers.append(worker)

        def boom():
            raise RuntimeError("job failed")

        self.queue.enqueue(boom, (), job_id="bad")
        self.queue.enqueue(self._record, ("after",), job_id="after")
        self._drain()

        self.assertIn("after", self.ran,
                      "a job queued behind a failing one never ran")
        self.assertEqual(self.queue.jobs["bad"].status, JobStatus.FAILED)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
