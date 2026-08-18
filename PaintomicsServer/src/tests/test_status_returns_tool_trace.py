#!/usr/bin/env python3
"""The status endpoint must return what the agent has been doing.

The full-agent arm records every tool call, `AIInterpretDAO.append_tool_event`
stores it, and until now the trace reached MongoDB and stopped there: the status
response carried status, percent and a sentence. A ten-minute run therefore
showed the user a progress bar and nothing about which pathways the agent
examined, what it searched for, or when it delegated -- data that existed the
whole time, one field away from the client.

    python -m src.tests.test_status_returns_tool_trace
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import src.servlets.AIInterpretServlet as S            # noqa: E402
from src.common.DAO.AIInterpretDAO import AIInterpretDAO  # noqa: E402

_PASSED, _FAILED = [], []
JOB = "TRACEPROBE_TEST"


class _Session:
    def isValidUser(self, *a, **kw):
        return True


class _Request:
    cookies = {"userID": "u", "sessionToken": "t"}
    form = {"jobID": JOB}


class _Response:
    def __init__(self):
        self.content = None

    def setContent(self, content):
        self.content = content


def _seed(events):
    dao = AIInterpretDAO()
    try:
        dao.save_progress(JOB, {"status": "running", "percent": 40,
                                "detail": "working"})
        for event in events:
            dao.append_tool_event(JOB, event)
    finally:
        dao.closeConnection()


def _cleanup():
    dao = AIInterpretDAO()
    try:
        dao.dbManager.getCollection(dao.collectionName).delete_one({"jobID": JOB})
    finally:
        dao.closeConnection()


def _status():
    original = S.UserSessionManager
    S.UserSessionManager = lambda: _Session()
    try:
        response = _Response()
        S.aiInterpretStatus(_Request(), response)
        return response.content or {}
    finally:
        S.UserSessionManager = original


def test_the_trace_reaches_the_client():
    _seed([{"tool": "search_literature", "args": "q%d" % i, "result": "5 papers",
            "ms": 2000, "t": float(i)} for i in range(3)])
    try:
        body = _status()
        assert "toolTrace" in body, ("the status payload has no toolTrace: %s"
                                     % sorted(body))
        assert len(body["toolTrace"]) == 3
        assert body["toolTrace"][0]["tool"] == "search_literature"
        assert body.get("toolCalls") == 3, "the total call count is missing"
    finally:
        _cleanup()


def test_a_long_run_is_trimmed_to_the_tail():
    """A ten-minute run makes hundreds of calls; the widget shows a short feed,
    and the total is reported separately so nothing looks lost."""
    _seed([{"tool": "notebook_write", "args": "note %d" % i, "result": "ok",
            "ms": 3, "t": float(i)} for i in range(40)])
    try:
        body = _status()
        assert len(body["toolTrace"]) == 12, (
            "expected the last 12 events, got %d" % len(body["toolTrace"]))
        assert body["toolTrace"][-1]["args"] == "note 39", "not the tail"
        assert body["toolCalls"] == 40, "the total should count everything"
    finally:
        _cleanup()


def test_a_failed_tool_call_is_visible_to_the_client():
    """Failures are the events a user most needs to see, and they are ordinary
    trace events carrying an ERROR result."""
    _seed([{"tool": "compare_gene_profiles", "args": "['A']",
            "result": "ERROR KeyError: 'source'", "ms": 4, "t": 9.0}])
    try:
        body = _status()
        assert body["toolTrace"][-1]["result"].startswith("ERROR"), (
            "the failure did not survive to the client: %r" % body["toolTrace"])
    finally:
        _cleanup()


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_trace_reaches_the_client,
              test_a_long_run_is_trimmed_to_the_tail,
              test_a_failed_tool_call_is_visible_to_the_client):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
