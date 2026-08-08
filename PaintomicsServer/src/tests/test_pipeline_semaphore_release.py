#!/usr/bin/env python3
"""The pipeline's concurrency permit must come back, whatever else goes wrong.

Why this exists
---------------
`run_ai_pipeline` takes a permit from a semaphore sized by
`AI_MAX_CONCURRENT_PIPELINES` (2) and returns it in its `finally`. But the
release is the *last* statement of that block:

    finally:
        phaseSummary = timer.summary()      # <- can raise
        if phaseSummary:
            logger.info(...)
        heartbeat.stop()
        _pipeline_semaphore.release()       # <- never reached if it did

and `_PhaseTimer.summary()` divides by the total elapsed time:

    total = sum(t for _, t in self.timings)
    ... f"({100 * seconds / total:.0f}%)"

With at least one phase recorded and every recorded phase measuring 0.0, that
total is 0.0 and the division raises ZeroDivisionError. A phase measuring
exactly zero is not exotic: `time.time()` has roughly 15ms resolution on
Windows, so any phase that finishes faster than one tick reads as 0.0.

The consequence is not a lost log line. The permit is never returned and the
heartbeat thread is never stopped, so **two such runs exhaust the semaphore and
every later AI interpretation blocks forever on acquire()** -- no error, no
timeout, no report, until someone restarts the server. Demonstrated directly:
after two early failures the permit count is 0 and a third `acquire()` returns
False.

Two things are fixed and both are pinned here. `summary()` no longer divides by
zero, and the release happens in its own `finally` so nothing ahead of it can
skip it -- the ordering, not just the arithmetic, because the next statement
added to that block would otherwise reintroduce the same failure.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_pipeline_semaphore_release
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.pipeline import _PhaseTimer


class PhaseSummaryTest(unittest.TestCase):
    """summary() is called in a finally; it must not be the thing that raises."""

    def _timer(self, timings):
        timer = _PhaseTimer("probe")
        timer.timings = list(timings)
        return timer

    def test_no_phases_summarises_to_nothing(self):
        self.assertEqual(self._timer([]).summary(), "")

    def test_a_single_zero_length_phase_does_not_raise(self):
        """The reachable case: one phase, measured 0.0, total 0.0."""
        try:
            self._timer([("triage", 0.0)]).summary()
        except ZeroDivisionError:
            self.fail("summary() divided by a zero total; in the pipeline's "
                      "finally this skips the semaphore release")

    def test_several_zero_length_phases_do_not_raise(self):
        try:
            self._timer([("triage", 0.0), ("search", 0.0),
                         ("synthesis", 0.0)]).summary()
        except ZeroDivisionError:
            self.fail("summary() divided by a zero total")

    def test_the_summary_still_names_every_phase(self):
        summary = self._timer([("triage", 1.0), ("search", 3.0)]).summary()

        self.assertIn("triage", summary)
        self.assertIn("search", summary)

    def test_percentages_are_right_when_the_total_is_positive(self):
        summary = self._timer([("triage", 1.0), ("search", 3.0)]).summary()

        self.assertIn("25%", summary)
        self.assertIn("75%", summary)

    def test_a_zero_total_still_produces_a_usable_line(self):
        """Losing the percentages is fine; losing the line is not."""
        summary = self._timer([("triage", 0.0), ("search", 0.0)]).summary()

        self.assertIn("triage", summary)
        self.assertIn("search", summary)


class ReleaseOrderingTest(unittest.TestCase):
    """The permit must survive a failure anywhere else in the finally."""

    def test_the_release_is_not_the_last_statement_of_the_finally(self):
        """Ordering is the fix; arithmetic alone would leave this fragile."""
        import inspect
        from src.classes.AIInterpret import pipeline

        source = inspect.getsource(pipeline.run_ai_pipeline)
        finallyBlock = source.rsplit("finally:", 1)[-1]

        releaseLine = None
        summaryLine = None
        for index, line in enumerate(finallyBlock.splitlines()):
            if "_pipeline_semaphore.release()" in line:
                releaseLine = index
            if "timer.summary()" in line:
                summaryLine = index

        self.assertIsNotNone(releaseLine, "the finally no longer releases")
        if summaryLine is not None:
            self.assertLess(
                releaseLine, summaryLine,
                "the permit is released after the phase summary, so a failure "
                "in the summary skips the release and wedges the pipeline")

    def test_a_failure_before_the_release_would_exhaust_the_permits(self):
        """The behaviour being guarded against, stated as an experiment."""
        semaphore = threading.Semaphore(2)

        def brokenOrdering():
            try:
                semaphore.acquire()
                raise RuntimeError("failed early")
            finally:
                raise ZeroDivisionError("summary blew up")   # release skipped

        for _ in range(2):
            try:
                brokenOrdering()
            except Exception:
                pass

        self.assertFalse(semaphore.acquire(blocking=False),
                         "this experiment no longer reproduces the wedge it "
                         "exists to describe")

    def test_releasing_first_survives_the_same_failure(self):
        """The shape the fix uses."""
        semaphore = threading.Semaphore(2)

        def fixedOrdering():
            try:
                semaphore.acquire()
                raise RuntimeError("failed early")
            finally:
                try:
                    semaphore.release()
                finally:
                    raise ZeroDivisionError("summary blew up")

        for _ in range(3):
            try:
                fixedOrdering()
            except Exception:
                pass

        self.assertTrue(semaphore.acquire(blocking=False),
                        "permits were not returned despite releasing first")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
