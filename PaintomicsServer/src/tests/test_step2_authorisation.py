#!/usr/bin/env python3
"""Re-running step 2 on a read-only job must be refused for a non-owner.

Why this exists
---------------
`pathwayAcquisitionStep2_PART1` validated the session and then enqueued the
work without ever asking whether the caller was allowed to touch that job:

    UserSessionManager().isValidUser(userID, sessionToken)
    jobID = formFields.get("jobID")
    ...
    QUEUE_INSTANCE.enqueue(fn=pathwayAcquisitionStep2_PART2, args=(jobID, userID, ...))

Step 2 is the most destructive thing a caller can ask for. Its store branch
(`JobInformationManager.storeJobInstance`, stepNumber 2) overwrites summary,
lastStep, adjustPvalue and the rest of a long field list, and then does
removeAll + insertAll over the job's compounds, its matched metabolites and its
pathways. Re-running it with a different `selectedCompounds` replaces the
owner's results wholesale -- this is not a stray file appearing in a directory,
it is the analysis being recomputed to somebody else's parameters.

Measured against a running server before the fix, one guest session against a
job it did not own and that was marked readOnly:

    pa_step2                success=True    (work enqueued)
    pa_save_visual_options  success=None    (refused)

Same caller, same job, same flag; only the missing check differed.

After the fix, four cases:

    readOnly job, non-owner   refused
    readOnly job, the owner   accepted
    open job,     non-owner   accepted
    unknown jobID             refused, and named

The third is deliberate. This restores the readOnly rule rather than tightening
it: a job that is not readOnly stays writable by anyone holding its ID, which
is how sharing works in this application.

The fourth is a side effect worth keeping. PART1 used to enqueue an unknown
jobID blindly, so a bad ID failed asynchronously inside the worker where the
user saw only a job that never progressed. `loadRequestedJob` fails in the
request instead, naming the job.

Note on where the check lives: PART1, not PART2. PART2 receives `userID` as an
argument that has already been trusted, and by then the work is queued.

Not every job handler belongs under this rule. `pathwayAcquisitionStep3` has no
guard on purpose -- it is what the client calls when a user *clicks a pathway
to view it* (JobController.step3OnFormSubmitHandler), so guarding it would
break viewing a shared job. It also persists nothing: storeJobInstance
implements stepNumber 1 and 2 only, so its `storeJobInstance(jobInstance, 3)`
just refreshes the in-memory cache, and the graphical options it builds are
derived data regenerated on demand.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_step2_authorisation
"""
import ast
import io
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SERVLET = os.path.join(os.path.dirname(__file__),
                       "../servlets/PathwayAcquisitionServlet.py")


def _stripComments(text):
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
                  if t.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except Exception:
        return text


def _handlerSources():
    with open(SERVLET, "r", encoding="utf-8", errors="replace") as handle:
        source = handle.read()
    tree = ast.parse(source)
    return {node.name: ast.get_source_segment(source, node)
            for node in tree.body if isinstance(node, ast.FunctionDef)}


class Step2AuthorisationTest(unittest.TestCase):

    def setUp(self):
        self.handlers = _handlerSources()
        self.part1 = self.handlers.get("pathwayAcquisitionStep2_PART1")
        self.assertIsNotNone(self.part1,
                             "pathwayAcquisitionStep2_PART1 not found; every "
                             "check below would pass vacuously")
        self.source = _stripComments(self.part1)

    def test_step2_checks_authorisation(self):
        self.assertIn("getReadOnly()", self.source,
                      "pathwayAcquisitionStep2_PART1 queues a destructive "
                      "rewrite of the job without checking whether the caller "
                      "may modify it")

    def test_the_check_is_not_only_a_comment(self):
        """The rationale above the guard would satisfy a substring test."""
        node = ast.parse(self.source.lstrip())
        calls = {n.func.attr for n in ast.walk(node)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}

        self.assertIn("getReadOnly", calls,
                      "getReadOnly appears in the source but is never called")

    def test_the_guard_compares_against_the_requesting_user(self):
        self.assertIn("getUserID()", self.source,
                      "the readOnly flag is consulted without comparing the "
                      "job's owner to the caller, so either the owner is "
                      "locked out of their own job or nobody is")

    def test_the_guard_precedes_the_enqueue(self):
        """A check after the work is queued protects nothing."""
        guardAt = self.source.find("getReadOnly()")
        enqueueAt = self.source.find("enqueue")

        self.assertNotEqual(guardAt, -1, "no guard at all")
        self.assertNotEqual(enqueueAt, -1,
                            "PART1 no longer enqueues; if the flow changed, "
                            "re-read what this test is pinning")
        self.assertLess(guardAt, enqueueAt,
                        "the authorisation check happens after the work is "
                        "queued, so it stops nothing")

    def test_the_job_is_resolved_before_being_queued(self):
        """An unknown jobID must fail here, not asynchronously in the worker."""
        self.assertIn("loadRequestedJob", self.source,
                      "PART1 enqueues a jobID it never resolved, so a bad ID "
                      "fails inside the worker where the user sees only a job "
                      "that never progresses")

    def test_the_destructive_branch_is_still_what_step_2_runs(self):
        """If step 2 stopped rewriting the job, the rationale would be stale."""
        managerPath = os.path.join(os.path.dirname(__file__),
                                   "../common/JobInformationManager.py")
        with open(managerPath, "r", encoding="utf-8", errors="replace") as handle:
            managerSource = handle.read()

        tree = ast.parse(managerSource)
        store = next((n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "storeJobInstance"), None)
        self.assertIsNotNone(store, "storeJobInstance not found")

        body = _stripComments(ast.get_source_segment(managerSource, store))
        self.assertIn("removeAll", body,
                      "storeJobInstance no longer deletes the job's existing "
                      "records, so the 'destructive' claim above is stale")
        self.assertIn("stepNumber == 2", body)


class Step3IsDeliberatelyUnguardedTest(unittest.TestCase):
    """Step 3 must stay open, and this records why so it is not 'fixed'."""

    def setUp(self):
        self.handlers = _handlerSources()

    def test_step3_persists_nothing(self):
        """storeJobInstance implements steps 1 and 2 only."""
        managerPath = os.path.join(os.path.dirname(__file__),
                                   "../common/JobInformationManager.py")
        with open(managerPath, "r", encoding="utf-8", errors="replace") as handle:
            managerSource = handle.read()

        tree = ast.parse(managerSource)
        store = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)
                     and n.name == "storeJobInstance")
        body = _stripComments(ast.get_source_segment(managerSource, store))

        self.assertNotIn("stepNumber == 3", body,
                         "storeJobInstance now handles step 3, so step 3 does "
                         "persist something and its missing authorisation "
                         "check needs re-examining")

    def test_step3_still_only_calls_store_with_three(self):
        source = _stripComments(self.handlers["pathwayAcquisitionStep3"])

        self.assertIn("storeJobInstance(jobInstance, 3)", source,
                      "step 3 no longer stores with stepNumber 3; if it now "
                      "uses a persisted step, it needs the guard the other "
                      "mutating handlers carry")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
