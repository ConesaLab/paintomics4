#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
"Choose for me" batches must not hold a queue worker one gateway call at a time.

The residual sets of a job go to the gateway thirty per call. Those calls
used to run strictly one after another, inside ONE of the four queue workers
every user's step 1/2/3 also runs on, with no cap on how many there could be
and a per-call budget of 180 s: a job with 300 ambiguous names was ten
sequential calls, up to half an hour holding a worker, and four such clicks
left no worker for anyone's analysis. The batches are independent -- an
answer is matched to its question by input name, never by position -- and
the worker is idle on I/O for the whole call, so they fan out over a small
pool and a run sends at most a fixed number of sets, leaving the rest to the
user rather than to the clock.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_ai_batches_share_the_queue
"""
import json
import os
import sys
import threading
import time
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", ".."))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from src.classes.CompoundDisambiguation import resolver  # noqa: E402


def _decisions(names):
    return [{"title": name, "candidates": [{"keggID": "C%05d" % (i + 1), "names": [name]},
                                            {"keggID": "C%05d" % (i + 101), "names": [name + " isomer"]}]}
            for i, name in enumerate(names)]


class FakeGateway(object):
    """Answers every name in the batch with its first candidate, after a
    pause, and records how many calls were in flight at once."""

    model = "fake-model"

    def __init__(self, delay=0.3, failFor=(), delays=None):
        self.delay = delay
        self.delays = delays or {}
        self.failFor = set(failFor)
        self.calls = []
        self.inFlight = 0
        self.maxInFlight = 0
        self._lock = threading.Lock()

    def complete(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        names = [line[len("Input name: "):].strip() for line in prompt.split("\n")
                 if line.startswith("Input name: ")]
        with self._lock:
            self.calls.append(names)
            self.inFlight += 1
            self.maxInFlight = max(self.maxInFlight, self.inFlight)
        try:
            time.sleep(self.delays.get(names[0], self.delay))
            if self.failFor & set(names):
                raise RuntimeError("gateway down")
            return json.dumps({"choices": [
                {"input_name": name, "kegg_id": "C%05d" % (i + 1), "confidence": "high", "reason": "first"}
                for i, name in [(int(n.split("-")[1]) - 1, n) for n in names]]})
        finally:
            with self._lock:
                self.inFlight -= 1


class BatchesFanOutTest(unittest.TestCase):

    def test_batches_run_in_parallel(self):
        gateway = FakeGateway(delay=0.3)
        decisions = _decisions(["name-%d" % i for i in range(1, 7)])
        started = time.monotonic()
        result = resolver.suggestCompounds(decisions, {}, client=gateway, batchSize=2, workers=3)
        elapsed = time.monotonic() - started
        self.assertEqual(result["batches"], 3)
        self.assertEqual(len(gateway.calls), 3)
        self.assertGreaterEqual(gateway.maxInFlight, 2, "batches ran one after another")
        self.assertLess(elapsed, 0.75, "three 0.3 s batches took %.2f s" % elapsed)
        self.assertEqual(len(result["accepted"]), 6)

    def test_results_keep_the_order_of_the_decisions(self):
        # The first batch is the slowest, so it finishes last; the audit log
        # and the browser must still see the sets in the order they were sent.
        gateway = FakeGateway(delay=0.05, delays={"name-1": 0.4})
        decisions = _decisions(["name-%d" % i for i in range(1, 7)])
        result = resolver.suggestCompounds(decisions, {}, client=gateway, batchSize=2, workers=3)
        self.assertEqual([e["title"] for e in result["accepted"]],
                         ["name-%d" % i for i in range(1, 7)])

    def test_a_failing_batch_does_not_sink_the_others(self):
        gateway = FakeGateway(delay=0.05, failFor={"name-3"})
        decisions = _decisions(["name-%d" % i for i in range(1, 7)])
        result = resolver.suggestCompounds(decisions, {}, client=gateway, batchSize=2, workers=3)
        self.assertEqual(sorted(e["title"] for e in result["accepted"]),
                         ["name-1", "name-2", "name-5", "name-6"])
        self.assertEqual(sorted(e["title"] for e in result["abstained"]), ["name-3", "name-4"])
        self.assertTrue(all("could not be reached" in e["detail"] for e in result["abstained"]))


class ResidualCapTest(unittest.TestCase):

    def test_a_run_sends_at_most_max_sets_and_leaves_the_rest_to_the_user(self):
        gateway = FakeGateway(delay=0.01)
        decisions = _decisions(["name-%d" % i for i in range(1, 6)])
        result = resolver.suggestCompounds(decisions, {}, client=gateway, batchSize=1, workers=2, maxSets=2)
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(result["batches"], 2)
        self.assertEqual([e["title"] for e in result["accepted"]], ["name-1", "name-2"])
        left = [e for e in result["abstained"]]
        self.assertEqual([e["title"] for e in left], ["name-3", "name-4", "name-5"])
        for entry in left:
            self.assertEqual(entry["tier"], "ai")
            self.assertIsNone(entry["keggID"])
            self.assertIn("first 2", entry["detail"])
            self.assertEqual(len(entry["candidates"]), 2)

    def test_the_cap_and_the_pool_have_sane_defaults(self):
        self.assertGreaterEqual(resolver.DEFAULT_WORKERS, 2)
        self.assertLessEqual(resolver.DEFAULT_WORKERS, 4)
        # At most a handful of batches per click: the worst case is bounded by
        # ceil(MAX_SETS / BATCH_SIZE / WORKERS) rounds of one batch budget.
        self.assertLessEqual(resolver.DEFAULT_MAX_SETS, 4 * resolver.DEFAULT_BATCH_SIZE)


if __name__ == "__main__":
    unittest.main()
