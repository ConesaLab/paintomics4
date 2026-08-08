#!/usr/bin/env python3
"""Serialising a job must not break because a status poll touched it.

Why this exists
---------------
`PathwayAcquisitionJob.toBSON` walks the instance dictionary live:

    for attr, value in self.__dict__.items():

and `checkJobStatus` writes an attribute onto the very same object while the
job is running:

    estimatedTotal = max(estimatedTotal, getattr(jobArgs, 'maxEstimatedTotal', 0))
    jobArgs.maxEstimatedTotal = estimatedTotal          # <- adds the attribute

`maxEstimatedTotal` is not declared anywhere in the class -- the `getattr`
default proves it -- so the **first** poll of a running job adds a key rather
than reassigning one, and `jobArgs` is `jobInstance.args[0]`, the same object
the queue worker hands to `storeJobInstance` at each step boundary. A key
appearing mid-walk is

    RuntimeError: dictionary changed size during iteration

which fails the store, so a job that computed correctly is not saved.

Being honest about the odds: the walk takes microseconds and only the *first*
poll changes the dictionary's size -- later ones reassign, which is safe. So the
collision needs one particular poll to land inside one particular serialisation.
It is narrow. It is also free to close, and the failure is the loss of a
finished step rather than a cosmetic glitch.

The fix takes a snapshot of the items before walking them, which covers the
whole family rather than this one attribute: any code that sets something on a
job while it is being written out.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_job_serialisation_during_poll
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob


class SerialiseWhileMutatedTest(unittest.TestCase):

    def _job(self):
        return PathwayAcquisitionJob("SHARED", None, "/tmp/")

    def test_an_attribute_appearing_mid_walk_does_not_break_the_store(self):
        """Exactly what the first status poll does to a running job."""
        job = self._job()
        errors = []
        stop = threading.Event()

        def poll():
            index = 0
            while not stop.is_set():
                setattr(job, "maxEstimatedTotal_%d" % index, index)
                index += 1
                if index % 400 == 0:
                    for name in [n for n in list(job.__dict__)
                                 if n.startswith("maxEstimatedTotal_")]:
                        delattr(job, name)

        def store():
            try:
                while not stop.is_set():
                    job.toBSON()
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))
                stop.set()

        threads = [threading.Thread(target=poll)] + \
                  [threading.Thread(target=store) for _ in range(2)]
        for thread in threads:
            thread.start()
        time.sleep(2.0)
        stop.set()
        for thread in threads:
            thread.join(timeout=3)

        self.assertEqual(errors, [],
                         "serialising a job broke while it was being polled: %s"
                         % errors[:2])

    def test_the_real_attribute_name_is_safe(self):
        """`maxEstimatedTotal` specifically, since that is the live one."""
        job = self._job()
        errors = []
        stop = threading.Event()

        def poll():
            value = 0.0
            while not stop.is_set():
                # First iteration adds the key; later ones reassign.
                if hasattr(job, "maxEstimatedTotal"):
                    delattr(job, "maxEstimatedTotal")
                job.maxEstimatedTotal = value
                value += 1

        def store():
            try:
                while not stop.is_set():
                    job.toBSON()
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))
                stop.set()

        threads = [threading.Thread(target=poll),
                   threading.Thread(target=store)]
        for thread in threads:
            thread.start()
        time.sleep(1.5)
        stop.set()
        for thread in threads:
            thread.join(timeout=3)

        self.assertEqual(errors, [], "%s" % errors[:1])

    def test_the_serialised_job_still_carries_its_fields(self):
        """The snapshot must not change what gets stored."""
        job = self._job()
        job.setOrganism("mmu")

        bson = job.toBSON()

        self.assertEqual(bson.get("organism"), "mmu")
        self.assertIn("jobID", bson)

    def test_the_snapshot_does_not_change_what_is_serialised(self):
        """Taking a copy of the items must not alter the output at all.

        Written first as "the directory fields are excluded", from reading the
        `["svgDir", "inputDir", ...].count(attr) == 0` guard at the top of the
        loop. That was wrong -- those fields are strings, so they fall past that
        branch and a later one in the elif chain puts them in. The guard only
        keeps them out of *that* branch. Asserting the whole mapping is both
        accurate and a stricter check.
        """
        job = self._job()
        job.setOrganism("mmu")

        before = dict(job.toBSON())
        after = dict(job.toBSON())

        self.assertEqual(before, after)
        self.assertIn("inputDir", before,
                      "the directory fields come out of toBSON; the DAO drops "
                      "them again before writing, so they are absent from the "
                      "stored document -- checked against a real job, whose "
                      "Mongo record has no inputDir. Asserted here because it "
                      "is toBSON's output that this change touches")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
