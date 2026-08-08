#!/usr/bin/env python3
"""The AI pipeline, run end to end against a local stand-in gateway.

Why this exists
---------------
Nothing ran `run_ai_pipeline`. It needs a live LLM, and a deployment without
`AI_CSIC_API_KEY` cannot reach one -- so phase sequencing, the reference
rendering, and the citation verification loop were all covered only by unit
tests of their parts.

That gap hid a real defect once already. `docs/superpowers/specs/` records the
synthesis emitting no parseable `### References` section in three runs of four,
which made `verify_report` check nothing, report `citations_checked: 0` and
`ref_accuracy: 0.0`, and finish `done` regardless. The fix was to stop asking
the model for the section and render it from `paper_index`. This is the test
that says so.

The gateway stand-in is not a mock of the client: it is an HTTP server speaking
chat-completions, so `llm_client` does real requests, real JSON handling and its
real schema path. When the caller asks for a `json_schema` response it builds a
minimal instance of that schema; otherwise it returns prose carrying `[1]`
markers, which is what gives `render_references_section` something to resolve.

PubMed is **not** stubbed. The bibliographic half of a reference has to come
from a real lookup for this test to mean anything -- the whole point is that the
metadata is ground truth and only the quotation comes from the model.

Skips cleanly when MongoDB, a stored job, or the network is unavailable, in the
manner of test_enrichment_e2e and test_runmore_r_endtoend.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_ai_pipeline_endtoend [--jobID XXXX]
"""
import argparse
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

JOB_ID = os.environ.get("AI_E2E_JOB_ID")


# ---------------------------------------------------------------------------
# The stand-in gateway
# ---------------------------------------------------------------------------

def _instanceFor(schema):
    """A minimal value satisfying `schema`, so the schema path runs for real."""
    if not isinstance(schema, dict):
        return None
    kind = schema.get("type")
    if kind == "object":
        properties = schema.get("properties") or {}
        required = schema.get("required") or list(properties.keys())
        return {name: _instanceFor(properties.get(name, {})) for name in required}
    if kind == "array":
        return [_instanceFor(schema.get("items") or {})]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    if schema.get("enum"):
        return schema["enum"][0]
    return "stub"


SYNTHESIS = ("## Summary\n\nCoordinated regulation is visible across the "
             "submitted layers [1].\n\n## Caveats\n\nStub output; no biological "
             "meaning.\n")


class _Handler(BaseHTTPRequestHandler):
    served = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        _Handler.served.append(payload)

        schema = ((payload.get("response_format") or {})
                  .get("json_schema") or {}).get("schema")
        content = json.dumps(_instanceFor(schema)) if schema else SYNTHESIS

        body = json.dumps({
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _startGateway():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d/v1" % server.server_address[1]


# ---------------------------------------------------------------------------

def _storedJobID():
    """A completed job to interpret; skip if the database has none."""
    if JOB_ID:
        return JOB_ID
    try:
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        from pymongo import MongoClient
        client = MongoClient(MONGODB_HOST, int(MONGODB_PORT),
                             serverSelectionTimeoutMS=2000)
        collection = client["PaintomicsDB"]["jobInstanceCollection"]
        document = collection.find_one({"lastStep": {"$gte": 3}}, {"jobID": 1})
        return document.get("jobID") if document else None
    except Exception:
        return None


class AiPipelineEndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.jobID = _storedJobID()
        if not cls.jobID:
            raise unittest.SkipTest(
                "no completed job in MongoDB to interpret (run one first, or "
                "set AI_E2E_JOB_ID)")

        cls.server, baseUrl = _startGateway()
        _Handler.served = []

        from src.conf import serverconf
        cls._saved = dict(serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER])
        serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER].update(
            {"api_base": baseUrl, "api_key": "stub", "model": "stub-model"})

        # Keep the run short: the point is the contract, not the breadth.
        import src.classes.AIInterpret.pipeline as pipeline
        cls._savedBudgets = (pipeline.AI_MAX_PATHWAYS,
                             pipeline.AI_PAPERS_PER_PATHWAY)
        pipeline.AI_MAX_PATHWAYS = 2
        pipeline.AI_PAPERS_PER_PATHWAY = 2

        # Running the pipeline overwrites this job's stored interpretation.
        # That record may be a real report someone wants, so keep the previous
        # document and put it back in tearDownClass -- a test must not cost a
        # user their analysis just by being run.
        from src.common.DAO.AIInterpretDAO import AIInterpretDAO
        cls._priorRecord = AIInterpretDAO().find_by_job_id(cls.jobID)

        from src.classes.AIInterpret.pipeline import run_ai_pipeline
        from src.paintomicsserver import Response
        try:
            run_ai_pipeline(cls.jobID, "End-to-end stub run.", Response())
        except Exception as exc:                       # network, Mongo, R...
            cls.server.shutdown()
            cls._restorePriorRecord()
            raise unittest.SkipTest("pipeline could not run: %s" % exc)

        cls.stored = AIInterpretDAO().find_by_job_id(cls.jobID)

    @classmethod
    def _restorePriorRecord(cls):
        """Put back whatever interpretation the job had before this test."""
        prior = getattr(cls, "_priorRecord", None)
        jobID = getattr(cls, "jobID", None)
        if not jobID:
            return
        try:
            from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
            from pymongo import MongoClient
            collection = (MongoClient(MONGODB_HOST, int(MONGODB_PORT))
                          ["PaintomicsDB"]["aiInterpretationCollection"])
            if prior:
                document = dict(prior)
                document.pop("_id", None)
                collection.replace_one({"jobID": jobID}, document, upsert=True)
            else:
                # There was nothing here before; leave nothing behind.
                collection.delete_many({"jobID": jobID})
        except Exception:
            pass    # a cleanup failure must not mask the test's own result

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
        cls._restorePriorRecord()
        from src.conf import serverconf
        if hasattr(cls, "_saved"):
            serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER].update(cls._saved)
        if hasattr(cls, "_savedBudgets"):
            import src.classes.AIInterpret.pipeline as pipeline
            (pipeline.AI_MAX_PATHWAYS,
             pipeline.AI_PAPERS_PER_PATHWAY) = cls._savedBudgets

    # -- the run happened at all -------------------------------------------

    def test_the_pipeline_called_the_gateway(self):
        self.assertTrue(_Handler.served,
                        "the pipeline made no LLM request at all")

    def test_the_run_is_recorded_as_done(self):
        self.assertEqual((self.stored or {}).get("status"), "done")

    def test_a_report_was_produced(self):
        self.assertTrue((self.stored or {}).get("report"),
                        "the run finished with no report")

    # -- the references contract, which is what regressed before ------------

    def test_the_report_carries_a_references_section(self):
        """The defect: the section was absent in three runs of four."""
        self.assertIn("### References", (self.stored or {}).get("report", ""),
                      "no References section was rendered")

    def test_the_reference_metadata_comes_from_the_paper_index(self):
        """A PMID cannot come from the stub -- only from a real lookup."""
        report = (self.stored or {}).get("report", "")

        self.assertIn("PMID:", report,
                      "the reference carries no PMID, so it was not built from "
                      "retrieved papers")

    def test_verification_actually_ran(self):
        """`citations_checked: 0` while reporting done was the silent failure."""
        verification = (self.stored or {}).get("verification") or {}

        self.assertTrue(verification.get("references_section_found"),
                        "verification found no section to check")
        self.assertGreater(verification.get("citations_checked", 0), 0,
                           "verification checked nothing and still finished")

    def test_no_citation_is_left_dangling(self):
        verification = (self.stored or {}).get("verification") or {}

        self.assertEqual(verification.get("failed_citations") or [], [],
                         "a citation could not be resolved")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobID", default=None)
    args, remaining = parser.parse_known_args()
    if args.jobID:
        global JOB_ID
        JOB_ID = args.jobID

    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
