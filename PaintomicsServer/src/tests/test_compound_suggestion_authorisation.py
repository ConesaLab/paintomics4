#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Who may spend this deployment's LLM budget on compound disambiguation.

/pa_suggest_compounds enqueues a gateway call. Three separate questions gate it
and they are not the same question:

  * capability -- is the feature on and is there a token at all;
  * access     -- is this caller entitled to this job;
  * consent    -- did this JOB's record say its contents may be sent outward.

The consent one has a trap with history. test_ai_consent_enforced.py asserts at
the AST level that no AI route reads `formFields.get("aiConsent")`, because a
request-borne flag is the caller asserting their own consent. This file checks
the same rule behaviourally for the new route, and pins the source-level rule
for this file specifically so it cannot drift back.

No server, no queue thread, no gateway: the servlet is driven with fakes.
"""

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.servlets import CompoundSuggestionServlet as servlet


SERVLET_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "servlets", "CompoundSuggestionServlet.py")


class FakeResponse:
    def __init__(self):
        self.content = None
        self.status = 200

    def setContent(self, content):
        self.content = content
        return self

    def setStatus(self, status):
        # handleException calls this BEFORE setContent, so a fake without it
        # raises inside the error handler and every refusal looks like a
        # response with no content at all.
        self.status = status
        return self


class FakeRequest:
    def __init__(self, form=None, cookies=None):
        self.form = form or {}
        self.cookies = cookies or {"userID": "u1", "sessionToken": "t1"}


class FakeJob:
    def __init__(self, userID="u1", consent=True, sharing=False):
        self._userID = userID
        self._consent = consent
        self._sharing = sharing

    def getUserID(self):
        return self._userID

    def getAIConsent(self):
        return self._consent

    def getAllowSharing(self):
        return self._sharing


class FakeQueue:
    def __init__(self):
        self.enqueued = []

    def fetch_job(self, job_id):
        return None

    def enqueue(self, fn, args, timeout=None, job_id=None):
        self.enqueued.append(job_id)

    def get_result(self, job_id, remove=True):
        return None

    def check_status(self, job_id):
        from src.common.PySiQ import JobStatus
        return JobStatus.NOT_QUEUED

    def get_error_message(self, job_id):
        return None


class ServletGuardsTest(unittest.TestCase):

    def setUp(self):
        self._patched = {}
        self._patch(servlet.UserSessionManager, "isValidUser", lambda self, u, t: True)
        self._patch(servlet, "_requireCapability", lambda: None)
        self.queue = FakeQueue()

    def _patch(self, target, name, value):
        self._patched[(target, name)] = getattr(target, name, None)
        setattr(target, name, value)

    def tearDown(self):
        for (target, name), old in self._patched.items():
            if old is None:
                delattr(target, name)
            else:
                setattr(target, name, old)

    def _run(self, job, form=None):
        servlet._requireJobAccess = lambda jobID, userID: job
        response = FakeResponse()
        # `form if form is not None` and not `form or ...`: an empty form is
        # exactly the missing-jobID case, and it is falsy.
        servlet.compoundSuggestionInitiate(
            FakeRequest(form if form is not None else {"jobID": "J1"}),
            response, self.queue)
        return response.content

    def test_a_consenting_job_is_queued(self):
        content = self._run(FakeJob(consent=True))
        self.assertTrue(content["success"])
        self.assertEqual("queued", content["status"])
        self.assertEqual(["cs_J1"], self.queue.enqueued)

    def test_a_job_whose_record_withholds_consent_is_refused(self):
        content = self._run(FakeJob(consent=False))
        self.assertFalse(content.get("success"))
        self.assertEqual([], self.queue.enqueued)

    def test_consent_on_the_request_cannot_override_the_record(self):
        """The exact bypass the AST guard in test_ai_consent_enforced exists for."""
        content = self._run(FakeJob(consent=False),
                            form={"jobID": "J1", "aiConsent": "true"})
        self.assertFalse(content.get("success"))
        self.assertEqual([], self.queue.enqueued)

    def test_a_missing_jobid_is_refused_before_anything_is_queued(self):
        content = self._run(FakeJob(), form={})
        self.assertFalse(content.get("success"))
        self.assertEqual([], self.queue.enqueued)

    def test_the_queue_id_is_namespaced_away_from_the_step_2_run(self):
        """`cs_<jobID>`, so a suggestion cannot collide with step 2 itself.

        Enqueuing under the bare jobID would make the two runs the same queue
        entry -- and step 2 is the one that overwrites the job's results.
        """
        self._run(FakeJob())
        self.assertEqual(["cs_J1"], self.queue.enqueued)
        self.assertNotIn("J1", self.queue.enqueued)


class ConsentSourceRuleTest(unittest.TestCase):
    """The source-level half: this file must never read consent off the form."""

    def test_the_servlet_never_reads_aiconsent_from_the_request(self):
        with open(os.path.abspath(SERVLET_SOURCE), encoding="utf-8") as handle:
            source = handle.read()

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and argument.value == "aiConsent":
                    self.fail("CompoundSuggestionServlet reads aiConsent from a "
                              "request. Consent must be read from the stored job "
                              "record (jobInstance.getAIConsent()); a request-borne "
                              "flag is the caller asserting their own consent.")

    def test_the_servlet_does_ask_the_stored_record(self):
        with open(os.path.abspath(SERVLET_SOURCE), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("getAIConsent()", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
