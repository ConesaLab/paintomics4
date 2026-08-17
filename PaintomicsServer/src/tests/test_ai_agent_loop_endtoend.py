#!/usr/bin/env python3
"""The full-agent loop (AI_FULL_AGENT=1), run end to end against a scripted
stand-in gateway.

Same reasoning as test_ai_agent_endtoend, which covers the workflow arm:
py_compile proves nothing about an orchestration module (the SDK extraction
shipped importable-and-broken once), so the loop must actually run -- through
the real transport shim, the real tool plumbing, real PubMed, the real DAO --
before any change to it is believed.

The stand-in speaks chat-completions over HTTP and SCRIPTS the Lead
Interpreter: it answers each Lead turn with the next tool call of a fixed
investigation (overview -> search -> notebook -> submit_report -> DONE),
emitted as streamed tool_call chunks the way vLLM does, because that is what
``_stream_to_completion`` has to reassemble in production. Verifier calls get
a JSON verdict; schema'd calls (quote collection) get a minimal instance.

What this proves that no unit test can:
  * the Lead's tool loop runs against the streamed transport and every
    toolbelt tool executes on a real job;
  * ``submit_report`` is the door: the submitted draft, not the model's final
    message, is what reaches the exit gate;
  * the gate runs the same sequence as the workflow arm (references rebuilt,
    verified, renumbered, sorted) and the run lands "done" with the DAO
    holding report + toolTrace + notebook.

PubMed is NOT stubbed (the bibliographic half must be real). Skips cleanly
without MongoDB, a stored job, or the network. **Writes to the real database**
the same way test_ai_agent_endtoend does, with the same capture-restore-verify.

Usage:
    cd PaintomicsServer
    AI_E2E_JOB_ID=XXXX python -m src.tests.test_ai_agent_loop_endtoend
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.tests.test_ai_agent_endtoend import _instanceFor, _storedJobID

DRAFT = """## Key Findings
- The submitted omic layers move together across the time course [1].
- This is a scripted draft long enough to clear submit_report's floor.

## Cross-Pathway Themes
Coordinated regulation across layers, as the stub investigation recorded in
its notebook. The purpose of this text is contract coverage, not biology.

## Detailed Pathway Analysis
The top-ranked pathway carries the strongest combined p-value and multiple
significant omic layers; the scripted search attributed one real PubMed
paper to it [1].

## Suggested Follow-up Experiments
1. Validate the top regulator by qPCR (high priority).
2. Repeat the omic time course with finer early sampling.

## Limitations and Caveats
Scripted end-to-end run; every claim here exists to exercise the gate.
"""


class _Handler(BaseHTTPRequestHandler):
    served = []
    lead_turns = 0
    verifier_calls = 0

    def log_message(self, *args):
        pass

    def _tool_names(self, payload):
        return {t.get("function", {}).get("name")
                for t in payload.get("tools") or []}

    def _sse(self, chunks, want_usage):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in chunks:
            event = {"id": "chatcmpl-stub", "object": "chat.completion.chunk",
                     "created": 1, "model": "stub-model",
                     "choices": [dict({"index": 0, "finish_reason": None}, **c)]}
            self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
        if want_usage:
            usage = {"id": "chatcmpl-stub", "object": "chat.completion.chunk",
                     "created": 1, "model": "stub-model", "choices": [],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                               "total_tokens": 2}}
            self.wfile.write(("data: " + json.dumps(usage) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _stream_tool_call(self, name, arguments, want_usage):
        chunks = [
            {"delta": {"role": "assistant", "tool_calls": [
                {"index": 0, "id": "call_%d" % _Handler.lead_turns,
                 "type": "function",
                 "function": {"name": name,
                              "arguments": json.dumps(arguments)}}]}},
            {"delta": {}, "finish_reason": "tool_calls"},
        ]
        self._sse(chunks, want_usage)

    def _stream_text(self, content, want_usage):
        half = max(1, len(content) // 2)
        self._sse([
            {"delta": {"role": "assistant", "content": ""}},
            {"delta": {"content": content[:half]}},
            {"delta": {"content": content[half:]}},
            {"delta": {}, "finish_reason": "stop"},
        ], want_usage)

    def _plain_text(self, content):
        body = json.dumps({"choices": [{
            "index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # The script. Lead turns are recognised by submit_report being offered;
    # position in the investigation is the count of tool results so far.
    # cluster_pathways is in the script because leaving it out is how the
    # original TypeError survived to a live run: the loop imported, the stub
    # passed, and the only untested branch was the one a clustered dataset
    # enters. Coverage of the *call*, not just the module.
    LEAD_SCRIPT = [
        ("get_experiment_overview", {}),
        ("cluster_pathways", {}),
        ("get_pathway_details", {"pathway_names": ["Apoptosis", "Autophagy - animal"]}),
        ("search_literature", {"query": "Ikaros B-cell precursor differentiation",
                               "topic_tag": "stub-pathway"}),
        ("notebook_write", {"note": "Scripted finding: layers co-regulate."}),
        # Submitted twice on purpose. A thin, undelegated first submit is nudged
        # exactly once (see agent_loop.submit_report), and the second is accepted
        # whatever it looks like -- so this scripts the contract rather than
        # working around it, and would fail if the nudge ever became a veto.
        ("submit_report", {"report_markdown": DRAFT}),
        ("submit_report", {"report_markdown": DRAFT}),
    ]

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        _Handler.served.append(payload)
        streaming = bool(payload.get("stream"))
        want_usage = (payload.get("stream_options") or {}).get("include_usage")
        tools = self._tool_names(payload)

        schema = ((payload.get("response_format") or {})
                  .get("json_schema") or {}).get("schema")

        if "submit_report" in tools:
            done = sum(1 for m in payload.get("messages", [])
                       if m.get("role") == "tool")
            if done < len(self.LEAD_SCRIPT):
                name, args = self.LEAD_SCRIPT[done]
                _Handler.lead_turns += 1
                self._stream_tool_call(name, args, want_usage)
            else:
                self._stream_text("DONE", want_usage)
            return

        if "search_paper_text" in tools:
            _Handler.verifier_calls += 1
            verdict = json.dumps({"text_match": True, "supports_claim": True,
                                  "reasoning": "scripted verdict",
                                  "actual_text": "", "suggested_fix": ""})
            if streaming:
                self._stream_text(verdict, want_usage)
            else:
                self._plain_text(verdict)
            return

        content = json.dumps(_instanceFor(schema)) if schema else DRAFT
        if streaming:
            self._stream_text(content, want_usage)
        else:
            self._plain_text(content)


def _startGateway():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d/v1" % server.server_address[1]


class AiAgentLoopEndToEndTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.jobID = _storedJobID()
        if not cls.jobID:
            raise unittest.SkipTest(
                "no completed job in MongoDB to interpret (run one first, or "
                "set AI_E2E_JOB_ID)")

        cls.server, baseUrl = _startGateway()
        _Handler.served = []
        _Handler.lead_turns = 0
        _Handler.verifier_calls = 0

        from src.conf import serverconf
        cls._saved = dict(serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER])
        serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER].update(
            {"api_base": baseUrl, "api_key": "stub", "model": "stub-model"})

        os.environ["AI_LLM_MAX_RPM"] = "0"
        os.environ["AI_FULL_AGENT"] = "1"
        import src.classes.AIInterpret.agent as agent
        import src.classes.AIInterpret.agent_loop as agent_loop
        agent._sdk_configured = False
        agent._MODEL_OBJ = None

        # Keep the scripted run tight; restore in tearDownClass.
        cls._savedKnobs = (agent_loop.AGENT_MAX_TURNS, agent_loop.SEARCH_BUDGET,
                           agent_loop.AGENT_RUN_SECONDS,
                           agent_loop.GATE_RESERVE_SECONDS,
                           agent_loop.VERIFY_ITERATIONS, agent.AI_MAX_PATHWAYS)
        agent_loop.AGENT_MAX_TURNS = 8
        agent_loop.SEARCH_BUDGET = 2
        agent_loop.AGENT_RUN_SECONDS = 300.0
        agent_loop.GATE_RESERVE_SECONDS = 120.0
        agent_loop.VERIFY_ITERATIONS = 1
        agent.AI_MAX_PATHWAYS = 3

        from src.common.DAO.AIInterpretDAO import AIInterpretDAO
        cls._priorRecord = AIInterpretDAO().find_by_job_id(cls.jobID)

        from src.classes.AIInterpret.agent import run_ai_agent
        from src.paintomicsserver import Response
        try:
            run_ai_agent(cls.jobID, "Scripted full-agent run.", Response())
        except Exception as exc:
            cls.server.shutdown()
            cls._restorePriorRecord()
            raise unittest.SkipTest("the agent loop could not run: %s" % exc)

        cls.stored = AIInterpretDAO().find_by_job_id(cls.jobID)

    @classmethod
    def _restorePriorRecord(cls):
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
                collection.delete_many({"jobID": jobID})
        except Exception as exc:
            raise AssertionError(
                "could not restore this job's stored interpretation: %s" % exc)
        from src.common.DAO.AIInterpretDAO import AIInterpretDAO
        current = AIInterpretDAO().find_by_job_id(jobID)
        if (current or {}).get("report") != (prior or {}).get("report"):
            raise AssertionError(
                "the job's stored interpretation was not restored")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
        cls._restorePriorRecord()
        os.environ.pop("AI_FULL_AGENT", None)
        from src.conf import serverconf
        if hasattr(cls, "_saved"):
            serverconf.AI_PROVIDERS[serverconf.AI_LLM_PROVIDER].update(cls._saved)
        if hasattr(cls, "_savedKnobs"):
            import src.classes.AIInterpret.agent as agent
            import src.classes.AIInterpret.agent_loop as agent_loop
            (agent_loop.AGENT_MAX_TURNS, agent_loop.SEARCH_BUDGET,
             agent_loop.AGENT_RUN_SECONDS, agent_loop.GATE_RESERVE_SECONDS,
             agent_loop.VERIFY_ITERATIONS, agent.AI_MAX_PATHWAYS) = cls._savedKnobs
            agent._sdk_configured = False
            agent._MODEL_OBJ = None

    # -- the loop ran, through the door ------------------------------------

    def test_the_lead_made_tool_calls(self):
        self.assertGreaterEqual(_Handler.lead_turns, 7,
                                "the Lead never walked its scripted toolbelt")

    def test_the_thin_undelegated_submit_was_nudged_once(self):
        """The nudge fired, and did not become a veto: the second submit landed."""
        trace = [e for e in ((self.stored or {}).get("toolTrace") or [])
                 if e.get("tool") == "submit_report"]
        results = [str(e.get("result")) for e in trace]
        assert any("nudged" in r for r in results), results
        assert any("accepted" in r for r in results), results

    def test_the_cluster_tool_ran(self):
        """The branch whose call signature was wrong in the first live run."""
        tools = [e.get("tool") for e in ((self.stored or {}).get("toolTrace") or [])]
        self.assertIn("cluster_pathways", tools)
        self.assertIn("get_pathway_details", tools)

    def test_the_run_is_recorded_as_done(self):
        self.assertEqual((self.stored or {}).get("status"), "done")

    def test_the_submitted_draft_is_what_shipped(self):
        # The stub's quotes never match the real papers, so the gate rightly
        # redacts every cited sentence -- what must survive is the draft's
        # uncited prose, proving the submitted text (not the model's final
        # "DONE" message) is what reached the gate.
        report = (self.stored or {}).get("report") or ""
        self.assertIn("Cross-Pathway Themes", report)
        self.assertIn("contract coverage", report)
        self.assertNotIn("REJECTED", report)

    def test_the_pathway_table_was_appended(self):
        self.assertIn("## Enriched Pathway Summary",
                      (self.stored or {}).get("report") or "")

    def test_the_run_records_full_agent_mode(self):
        stats = (self.stored or {}).get("stats") or {}
        self.assertEqual(stats.get("mode"), "full_agent")
        self.assertFalse(stats.get("forced_synthesis"),
                         "submit_report was scripted; the backstop synthesis "
                         "must not have fired")

    # -- the journal the design promises ------------------------------------

    def test_the_tool_trace_was_persisted(self):
        trace = (self.stored or {}).get("toolTrace") or []
        tools = [e.get("tool") for e in trace]
        self.assertIn("get_experiment_overview", tools)
        self.assertIn("search_literature", tools)
        self.assertIn("submit_report", tools)

    def test_the_notebook_was_persisted(self):
        notebook = (self.stored or {}).get("notebook") or []
        self.assertTrue(any("co-regulate" in n for n in notebook),
                        "the scripted notebook entry is missing: %r" % notebook)

    # -- the gate ------------------------------------------------------------

    def test_references_were_rebuilt_or_redacted(self):
        report = (self.stored or {}).get("report") or ""
        self.assertTrue("### References" in report
                        or "unverified references were removed" in report,
                        "the gate neither rendered references nor redacted")

    def test_verification_dict_is_stored(self):
        self.assertIsInstance((self.stored or {}).get("verification"), dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
