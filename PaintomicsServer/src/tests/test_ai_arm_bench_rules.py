#!/usr/bin/env python3
"""The pre-registered rule must keep saying what it said before the data.

`judge()` decides whether the agent arm replaces the shipped workflow arm. It
was written before any arm ran, and the whole value of that is lost if it
quietly drifts -- a rule edited after seeing the numbers is not a rule. These
tests pin each of the five conditions, including the ones the agent arm has
been failing.

Also pins the prose cut, which is the metric that has already been wrong once:
counting a pathway as "covered" anywhere in the report let the agent arm score
102/102 by printing a table of pathway names it had not analysed.

    python -m src.tests.test_ai_arm_bench_rules
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import judge, prose_of  # noqa: E402

_PASSED, _FAILED = [], []


def _row(**kw):
    row = {"status": "done", "wall_s": 400.0, "citations_in_body": 20,
           "redacted": 4, "prose_pathways_covered": 15, "report_chars": 40000}
    row.update(kw)
    return row


def _verdict(agent, base=None):
    return judge(agent, base or [_row()])[1]


def test_a_matching_arm_passes_every_rule():
    assert _verdict([_row()]) is True, "an arm equal to base on every metric failed"


def test_a_replicate_over_the_ceiling_fails():
    assert _verdict([_row(wall_s=612.0)]) is False, "a 612 s run was accepted"


def test_an_errored_replicate_fails_even_if_the_others_are_good():
    assert _verdict([_row(), _row(status="error")]) is False, (
        "an errored replicate did not sink the round")


def test_fewer_citations_than_base_fails():
    """The rule the agent arm has failed in every round so far."""
    assert _verdict([_row(citations_in_body=18)]) is False


def test_two_extra_redactions_are_tolerated_three_are_not():
    assert _verdict([_row(redacted=6)]) is True, "base+2 redactions should pass"
    assert _verdict([_row(redacted=7)]) is False, "base+3 redactions should fail"


def test_less_coverage_than_base_fails():
    assert _verdict([_row(prose_pathways_covered=14)]) is False


def test_a_degenerate_report_fails_the_length_guard():
    assert _verdict([_row(report_chars=20000)]) is False, "0.5x base was accepted"
    assert _verdict([_row(report_chars=90000)]) is False, "2.25x base was accepted"
    assert _verdict([_row(report_chars=25000)]) is True, "0.625x base should pass"


def test_no_replicates_is_not_a_pass():
    assert _verdict([]) is False, "an empty arm must not be declared better"


def test_the_prose_cut_excludes_appended_tables():
    report = ("Real analysis of Glycolysis here.\n\n"
              "## Enriched Pathway Summary\n\n| Citrate cycle | 0.01 |\n"
              "### References\n\n[1] X.\n")
    prose = prose_of(report)
    assert "Real analysis" in prose
    assert "Citrate cycle" not in prose, (
        "the appended table is inside the prose cut; coverage will be inflated")
    assert "[1] X." not in prose


def test_the_prose_cut_takes_the_earliest_marker():
    report = "Analysis.\n## Pathway Clusters\ncluster rows\n### References\n[1] X."
    assert prose_of(report).strip() == "Analysis."


def test_a_round_refuses_to_start_when_the_gateway_is_down():
    """The guard that exists because two replicates once burned ten minutes
    each against a gateway returning 504 and produced two outage reports
    dressed as results."""
    import argparse
    import src.benchmarks.ai_arm_bench as B
    ran = []
    original_ready, original_run = B.cmd_ready, B.cmd_run
    B.cmd_ready = lambda _a: 1                       # gateway down
    B.cmd_run = lambda a: ran.append(a.label)
    try:
        code = B.cmd_round(argparse.Namespace(
            jobs="JOB1", outdir="/tmp/does-not-matter", label="agent-v25",
            design="d"))
    finally:
        B.cmd_ready, B.cmd_run = original_ready, original_run
    assert code == 2, "a round with no gateway must not exit 0, got %r" % code
    assert ran == [], "replicates ran against a dead gateway: %s" % ran


def test_a_round_interleaves_the_arms():
    """Gateway throughput drifts over tens of minutes. Running one arm's
    replicates back to back lets that weather land on one side of the
    comparison."""
    import argparse
    import src.benchmarks.ai_arm_bench as B
    ran = []
    original_ready, original_run, original_score = B.cmd_ready, B.cmd_run, B.cmd_score
    B.cmd_ready = lambda _a: 0
    B.cmd_run = lambda a: ran.append((a.arm, a.label))
    B.cmd_score = lambda _a: 0
    try:
        B.cmd_round(argparse.Namespace(jobs="JOB1,JOB2", outdir="/tmp/x",
                                       label="agent-v25", design="d"))
    finally:
        B.cmd_ready, B.cmd_run, B.cmd_score = original_ready, original_run, original_score
    arms = [arm for arm, _ in ran]
    assert arms == ["base", "agent", "base", "agent"], (
        "arms were not interleaved: %s" % arms)
    assert [l for _, l in ran] == ["base-r1", "agent-v25-r1",
                                   "base-r2", "agent-v25-r2"]



def _probe(status=None, connect_error=None, timeout=False, key="k"):
    """Drive cmd_ready with the network stubbed, capturing what it says."""
    import io, socket, contextlib
    import requests
    import src.benchmarks.ai_arm_bench as B
    from src.conf import serverconf

    class _Resp:
        status_code = status
        text = "<html>504</html>"

    real_conn, real_post = socket.create_connection, requests.post
    real_providers = serverconf.AI_PROVIDERS
    provider = serverconf.AI_LLM_PROVIDER
    serverconf.AI_PROVIDERS = dict(real_providers)
    serverconf.AI_PROVIDERS[provider] = dict(real_providers[provider], api_key=key)

    def conn(*_a, **_kw):
        if connect_error:
            raise OSError(connect_error)
        class _S:
            def close(self):
                pass
        return _S()

    def post(*_a, **_kw):
        if timeout:
            raise requests.Timeout("read timed out")
        return _Resp()

    socket.create_connection, requests.post = conn, post
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = B.cmd_ready(None)
    finally:
        socket.create_connection, requests.post = real_conn, real_post
        serverconf.AI_PROVIDERS = real_providers
    return code, buf.getvalue()


def test_a_healthy_gateway_is_ready():
    code, said = _probe(status=200)
    assert code == 0 and "ready" in said, (code, said)


def test_a_504_names_the_upstream_not_the_network():
    """Two and a half hours of outage were reported as "unreachable", which
    points at the wrong thing: the host resolved, TCP connected in 0.02 s and
    TLS handshook. Only the model service behind the proxy was down."""
    code, said = _probe(status=504)
    assert code == 1
    assert "behind it is down" in said, said
    assert "unreachable" not in said.lower(), (
        "still blaming the network for an upstream failure: %s" % said)


def test_a_refused_connection_names_the_network():
    code, said = _probe(connect_error="Connection refused")
    assert code == 1
    assert "not the model service" in said, said


def test_a_hang_is_distinguished_from_a_refusal():
    code, said = _probe(timeout=True)
    assert code == 1
    assert "hanging" in said, said


def test_a_missing_key_is_not_reported_as_an_outage():
    code, said = _probe(key="")
    assert code == 1
    assert "no API key" in said, said



def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_matching_arm_passes_every_rule,
              test_a_replicate_over_the_ceiling_fails,
              test_an_errored_replicate_fails_even_if_the_others_are_good,
              test_fewer_citations_than_base_fails,
              test_two_extra_redactions_are_tolerated_three_are_not,
              test_less_coverage_than_base_fails,
              test_a_degenerate_report_fails_the_length_guard,
              test_no_replicates_is_not_a_pass,
              test_the_prose_cut_excludes_appended_tables,
              test_the_prose_cut_takes_the_earliest_marker,
              test_a_round_refuses_to_start_when_the_gateway_is_down,
              test_a_round_interleaves_the_arms,
              test_a_healthy_gateway_is_ready,
              test_a_504_names_the_upstream_not_the_network,
              test_a_refused_connection_names_the_network,
              test_a_hang_is_distinguished_from_a_refusal,
              test_a_missing_key_is_not_reported_as_an_outage):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
