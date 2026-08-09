#!/usr/bin/env python3
"""Nothing leaves for the AI service unless the job's owner asked for it.

Why this exists
---------------
The upload page asks for consent in as many words -- "Enable AI pathway
interpretation (sends analysis summaries to external AI service)" -- and the
answer is stored on the job:

    jobInstance.setAIConsent(formFields.get("aiConsent", "false"))

It was then read in four places, all of them putting it into a response, and
checked in none. `aiInterpretInitiate` verified the session, the feature flag,
that a jobID was supplied and that the job existed, and started the pipeline.

Measured against a job whose stored record says aiConsent False -- a user who
had cleared the box -- posting its id to the endpoint returned success, and the
run went through triage, search planning, 8.1 seconds of literature retrieval,
interpretation and synthesis, reaching

    https://llm.iiia.es/v1/chat/completions

It stopped there only because this machine has no API key. A deployment with one
would have sent the analysis summary. The PubMed queries need no key and had
already gone out, so the 401 was not a saving grace.

Job ids are not secret -- the results page prints a shareable URL -- so the
decision has to be enforced on the server rather than by the client choosing not
to ask.

Checked statically. Standing the handler up needs a Flask request, a queue and
MongoDB; what matters is that the consent is consulted before the pipeline is
reached, and that reads off the source. Comments are stripped so a commented-out
check does not count. The behaviour itself was verified against the running
server: the declined job is now refused with a message naming the setting, while
a job that did consent still starts.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_ai_consent_enforced
"""
import ast
import io
import os
import sys
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SERVLET = os.path.join(os.path.dirname(__file__),
                       "../servlets/AIInterpretServlet.py")


def _stripComments(text):
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO(text).readline)
                  if t.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except Exception:
        return text


def _handlers():
    with open(SERVLET, "r", encoding="utf-8", errors="replace") as handle:
        source = handle.read()
    tree = ast.parse(source)
    return {node.name: ast.get_source_segment(source, node)
            for node in tree.body if isinstance(node, ast.FunctionDef)}


class AIConsentEnforcedTest(unittest.TestCase):

    def setUp(self):
        self.handlers = _handlers()
        self.initiate = self.handlers.get("aiInterpretInitiate")
        if self.initiate is None:
            self.fail("aiInterpretInitiate not found; this test is looking in "
                      "the wrong place")

    def test_the_initiate_handler_consults_the_consent(self):
        self.assertIn("getAIConsent", _stripComments(self.initiate),
                      "the AI pipeline can be started for a job whose owner "
                      "declined, sending their analysis to an external service")

    def test_the_consent_is_not_only_a_comment(self):
        """A commented-out check would read as present without doing anything."""
        stripped = _stripComments(self.initiate)

        self.assertIn("getAIConsent", stripped)
        self.assertIn("raise", stripped,
                      "consulting the consent is not enough; declining has to "
                      "stop the run")

    def test_the_check_comes_before_the_work_is_queued(self):
        """Consent after enqueue would still send the data."""
        stripped = _stripComments(self.initiate)
        consentAt = stripped.find("getAIConsent")
        enqueueAt = stripped.find("enqueue")

        self.assertNotEqual(consentAt, -1, "no consent check at all")
        if enqueueAt != -1:
            self.assertLess(consentAt, enqueueAt,
                            "the consent is checked after the pipeline is "
                            "queued, which is too late to stop anything")

    def test_the_message_names_the_setting(self):
        """So the user knows which box to tick rather than just being refused."""
        stripped = _stripComments(self.initiate)

        self.assertIn("AI pathway interpretation", stripped,
                      "the refusal should name the setting to enable")

    def test_the_stored_default_is_no(self):
        """A job that never said anything must not count as consenting."""
        from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

        job = PathwayAcquisitionJob("CONSENTTEST", None, "/tmp/")

        self.assertFalse(job.getAIConsent(),
                         "a fresh job defaults to consenting, so anything that "
                         "forgets to set it opts the user in")

    def test_only_an_explicit_yes_counts(self):
        from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

        job = PathwayAcquisitionJob("CONSENTTEST", None, "/tmp/")
        for value in ("false", "False", "", None, 0, "no", "maybe"):
            with self.subTest(value=value):
                job.setAIConsent(value)
                self.assertFalse(job.getAIConsent(),
                                 "%r was treated as consent" % (value,))

        for value in ("true", "True", True):
            with self.subTest(value=value):
                job.setAIConsent(value)
                self.assertTrue(job.getAIConsent(),
                                "%r should be consent" % (value,))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
