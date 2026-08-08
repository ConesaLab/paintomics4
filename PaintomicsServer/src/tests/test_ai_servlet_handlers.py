#!/usr/bin/env python3
"""The per-pathway and chat AI handlers, driven against a stand-in gateway.

Why this exists
---------------
`aiInterpretPathway` and `aiInterpretChat` had no test. Both need an LLM, which
is why -- but the behaviour worth pinning in them is not the model's output. It
is the surrounding contract:

  * a pathway report is generated lazily and **cached**, so opening the same
    pathway twice must cost one LLM call, not two. The docstring says the cache
    exists precisely so "opening the same one twice is free"; nothing checked
    that it is.
  * a pathway that was not part of the analysis must be refused by name, not
    interpreted anyway. The report's citations are limited to the papers the
    pipeline retrieved for that pathway, so answering for an unanalysed one
    would produce a report with nothing behind it.
  * chatting before the report exists must be refused, since the chat is
    grounded in the report.

The gateway stand-in is the one from test_ai_pipeline_endtoend: a real HTTP
server speaking chat-completions, so `llm_client` does real requests rather than
being mocked out. What it returns does not matter here; that a call happened,
and how many, is what these tests are about.

Skips cleanly when MongoDB has no job carrying a stored AI pathway index --
i.e. when the main pipeline has not been run.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_ai_servlet_handlers
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _Handler(BaseHTTPRequestHandler):
    served = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        _Handler.served.append(1)

        body = json.dumps({
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": "Stub pathway commentary."}}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Request:
    """The slice of a Flask request these handlers read."""

    def __init__(self, form=None, cookies=None):
        self.form = form or {}
        self.cookies = cookies or {}


def _jobWithPathwayIndex():
    """A job whose AI interpretation has already been run, or None."""
    try:
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        from pymongo import MongoClient
        collection = (MongoClient(MONGODB_HOST, int(MONGODB_PORT),
                                  serverSelectionTimeoutMS=2000)
                      ["PaintomicsDB"]["aiInterpretationCollection"])
        document = collection.find_one({"pathwayIndex": {"$exists": True,
                                                         "$ne": []}},
                                       {"jobID": 1, "pathwayIndex": 1})
        if not document:
            return None, None
        index = document.get("pathwayIndex") or []
        return document.get("jobID"), (index[0].get("id") if index else None)
    except Exception:
        return None, None


class _GatewayCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.jobID, cls.pathwayID = _jobWithPathwayIndex()
        if not cls.jobID or not cls.pathwayID:
            raise unittest.SkipTest(
                "no job with a stored AI pathway index; run the AI "
                "interpretation for a job first")

        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        baseUrl = "http://127.0.0.1:%d/v1" % cls.server.server_address[1]

        from src.conf import serverconf
        cls._saved = dict(serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER])
        serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER].update(
            {"api_base": baseUrl, "api_key": "stub", "model": "stub-model"})

        # These tests cache stub pathway reports against a real job. Those may
        # be reports someone wants, so keep what was there and put it back --
        # a test must not cost a user their analysis just by being run.
        cls._priorReports = cls._readPathwayReports()

    @classmethod
    def _pathwayCollection(cls):
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        from pymongo import MongoClient
        return (MongoClient(MONGODB_HOST, int(MONGODB_PORT))
                ["PaintomicsDB"]["aiInterpretationCollection"])

    @classmethod
    def _readPathwayReports(cls):
        try:
            document = cls._pathwayCollection().find_one(
                {"jobID": cls.jobID}, {"pathwayReports": 1})
            return (document or {}).get("pathwayReports")
        except Exception:
            return None

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
        from src.conf import serverconf
        if hasattr(cls, "_saved"):
            serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER].update(cls._saved)

        try:
            prior = getattr(cls, "_priorReports", None)
            if prior is None:
                # Nothing was cached before; leave nothing behind.
                cls._pathwayCollection().update_one(
                    {"jobID": cls.jobID}, {"$unset": {"pathwayReports": ""}})
            else:
                cls._pathwayCollection().update_one(
                    {"jobID": cls.jobID}, {"$set": {"pathwayReports": prior}})
        except Exception:
            pass    # a cleanup failure must not mask the tests' own result

    def setUp(self):
        _Handler.served = []

    def _response(self):
        # Response.content is read directly rather than via getResponse():
        # that calls jsonify(), which needs a Flask application context the
        # handlers themselves never require.
        from src.paintomicsserver import Response
        return Response()


class PathwayHandlerTest(_GatewayCase):

    def _call(self, **form):
        from src.servlets.AIInterpretServlet import aiInterpretPathway
        return aiInterpretPathway(_Request(form=form), self._response())

    def test_a_pathway_in_the_analysis_is_interpreted(self):
        result = self._call(jobID=self.jobID, pathwayID=self.pathwayID,
                            regenerate="true").content

        self.assertTrue(result.get("success"), result.get("message"))
        self.assertTrue(result.get("report"))

    def test_the_second_request_is_served_from_cache(self):
        """The docstring's claim: opening the same pathway twice is free."""
        self._call(jobID=self.jobID, pathwayID=self.pathwayID,
                   regenerate="true")
        callsAfterFirst = len(_Handler.served)

        second = self._call(jobID=self.jobID,
                            pathwayID=self.pathwayID).content

        self.assertTrue(second.get("cached"),
                        "the second request was not served from cache")
        self.assertEqual(len(_Handler.served), callsAfterFirst,
                         "a cached pathway still cost an LLM call")

    def test_regenerate_bypasses_the_cache(self):
        self._call(jobID=self.jobID, pathwayID=self.pathwayID)
        before = len(_Handler.served)

        self._call(jobID=self.jobID, pathwayID=self.pathwayID,
                   regenerate="true")

        self.assertGreater(len(_Handler.served), before,
                           "regenerate=true did not reach the model")

    def test_a_pathway_outside_the_analysis_is_refused(self):
        """Its citations would have no retrieved literature behind them."""
        result = self._call(jobID=self.jobID,
                            pathwayID="zzz_not_analysed").content

        self.assertFalse(result.get("success"))
        self.assertIn("zzz_not_analysed", str(result.get("message", "")))

    def test_a_missing_pathway_id_is_named(self):
        result = self._call(jobID=self.jobID).content

        self.assertFalse(result.get("success"))
        self.assertIn("pathwayID", str(result.get("message", "")))

    def test_an_unknown_job_is_refused(self):
        result = self._call(jobID="zzz_no_such_job",
                            pathwayID=self.pathwayID).content

        self.assertFalse(result.get("success"))


class ChatHandlerTest(_GatewayCase):

    def _call(self, **form):
        from src.servlets.AIInterpretServlet import aiInterpretChat
        return aiInterpretChat(_Request(form=form), self._response())

    def test_an_empty_message_is_refused(self):
        result = self._call(jobID=self.jobID, message="").content

        self.assertFalse(result.get("success"))
        self.assertIn("mpty", str(result.get("message", "")))

    def test_a_missing_job_id_is_refused(self):
        result = self._call(message="what does this mean?").content

        self.assertFalse(result.get("success"))
        self.assertIn("jobID", str(result.get("message", "")))

    def test_chatting_about_an_unknown_job_is_refused(self):
        """The chat is grounded in a report; without one there is nothing to say."""
        result = self._call(jobID="zzz_no_such_job",
                            message="summarise this").content

        self.assertFalse(result.get("success"))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
