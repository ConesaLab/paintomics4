#!/usr/bin/env python3
"""The agent workflow's concurrency permit must come back, whatever else fails.

Why this exists
---------------
`run_ai_agent` takes a permit from a semaphore sized by
`AI_MAX_CONCURRENT_PIPELINES` (2) and returns it in its `finally`. The
predecessor pipeline once released the permit as the *last* statement of that
block, after a phase-summary call that could raise ZeroDivisionError -- and two
such failures exhausted the semaphore, so **every later AI interpretation
blocked forever on acquire()** with no error, no timeout and no report, until
someone restarted the server.

The fix that ordering demands is pinned here for the agent workflow: the
release must be the first statement of the `finally`, so nothing added ahead
of it can ever skip it. The DAO close and the cancel-flag cleanup come after,
each unable to take the permit down with them.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_agent_semaphore_release
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class ReleaseOrderingTest(unittest.TestCase):
    """The permit must survive a failure anywhere else in the finally."""

    def test_the_release_is_the_first_statement_of_the_finally(self):
        """Ordering is the guarantee: nothing runs before the release."""
        import inspect
        from src.classes.AIInterpret import agent

        source = inspect.getsource(agent.run_ai_agent)
        finallyBlock = source.rsplit("finally:", 1)[-1]

        releaseLine = None
        firstStatementLine = None
        for index, line in enumerate(finallyBlock.splitlines()):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if firstStatementLine is None and index > 0:
                firstStatementLine = index
            if "_agent_semaphore.release()" in line:
                releaseLine = index
                break

        self.assertIsNotNone(releaseLine, "the finally no longer releases")
        # The only thing allowed before the release is the guard that checks
        # the permit was taken at all ("if acquired:").
        for index, line in enumerate(finallyBlock.splitlines()):
            if index >= releaseLine:
                break
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or index == 0:
                continue
            self.assertTrue(
                stripped.startswith("if acquired"),
                "a statement precedes the semaphore release in the finally "
                "(%r); if it raises, the permit is lost and the workflow "
                "wedges" % stripped)

    def test_a_failure_before_the_release_would_exhaust_the_permits(self):
        """The behaviour being guarded against, stated as an experiment."""
        semaphore = threading.Semaphore(2)

        def brokenOrdering():
            try:
                semaphore.acquire()
                raise RuntimeError("failed early")
            finally:
                raise ZeroDivisionError("cleanup blew up")   # release skipped

        for _ in range(2):
            try:
                brokenOrdering()
            except Exception:
                pass

        self.assertFalse(semaphore.acquire(blocking=False),
                         "this experiment no longer reproduces the wedge it "
                         "exists to describe")

    def test_releasing_first_survives_the_same_failure(self):
        """The shape the agent workflow uses."""
        semaphore = threading.Semaphore(2)

        def fixedOrdering():
            try:
                semaphore.acquire()
                raise RuntimeError("failed early")
            finally:
                try:
                    semaphore.release()
                finally:
                    raise ZeroDivisionError("cleanup blew up")

        for _ in range(3):
            try:
                fixedOrdering()
            except Exception:
                pass

        self.assertTrue(semaphore.acquire(blocking=False),
                        "permits were not returned despite releasing first")


class CancelFlagCleanupTest(unittest.TestCase):
    """A finished or failed job must not leave its cancel flag behind: a stale
    flag makes the *next* run of the same job cancel itself immediately."""

    def test_the_finally_also_clears_the_cancel_flag(self):
        import inspect
        from src.classes.AIInterpret import agent

        source = inspect.getsource(agent.run_ai_agent)
        finallyBlock = source.rsplit("finally:", 1)[-1]
        self.assertIn("_cancel_flags.pop(job_id, None)", finallyBlock,
                      "the finally no longer clears the job's cancel flag")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
