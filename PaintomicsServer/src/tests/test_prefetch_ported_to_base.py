#!/usr/bin/env python3
"""A measured fix sat in one arm for many rounds while the other bled from it.

The agent arm hands its verifier the paper's own words instead of making it hunt
with tool calls. That was measured when it landed: 29 of 29 calls returned a
verdict at a median 2 464 ms, redactions fell 12 -> 2, the verify loop 291 s ->
117 s, the run 485 s -> 338 s. The comment shipped with it even said "the same
warning appears in the workflow arm's logs".

Counted since, across rounds 34-36: **53** "Max turns (6) exceeded" verifier
failures, ALL of them in the base arm and NONE in the agent arm -- about five per
base run. A verifier that raises counts as a failure, so each one redacts a real
citation for a tooling reason. That is most of why base redacts 10 sentences a
run against the agent arm's 5.75, and why base's verify loop costs 175-250 s
against the agent arm's 10.

    python -m src.tests.test_prefetch_ported_to_base
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS  # noqa: E402
from src.classes.AIInterpret import agent as A  # noqa: E402

_PASSED, _FAILED = [], []


def _paper(ref=3, text="Glycolytic flux was elevated in treated mice."):
    return {ref: {"ref_index": ref, "title": "A paper", "abstract": text,
                  "sections": {"abstract": text}, "pmid": "1"}}


def test_the_passage_reaches_the_prompt():
    block = A._prefetched_evidence_block(
        _paper(), {"ref_index": 3, "cited_text": "flux was elevated"})
    assert "What paper [3] actually says" in block
    assert "Glycolytic flux was elevated" in block, block


def test_the_model_is_told_not_to_ask_for_more():
    """The point is to remove the tool round-trips, so the prompt must close
    that door explicitly or a 2-turn agent just fails differently."""
    block = A._prefetched_evidence_block(
        _paper(), {"ref_index": 3, "cited_text": "flux"})
    assert "Do not ask for more" in block


def test_a_paper_that_cannot_be_searched_does_not_raise():
    """Failing to find the passage must not fail the citation: the deterministic
    quote check in verify_report_v2 still runs afterwards."""
    block = A._prefetched_evidence_block(
        {}, {"ref_index": 99, "cited_text": "anything"})
    assert isinstance(block, str) and "[99]" in block


def test_a_missing_cited_text_does_not_raise():
    block = A._prefetched_evidence_block(_paper(), {"ref_index": 3})
    assert isinstance(block, str)


def test_the_passage_is_capped():
    """It rides in one prompt per citation per iteration."""
    long_text = "x" * 20000
    block = A._prefetched_evidence_block(
        _paper(text=long_text), {"ref_index": 3, "cited_text": "xxx"})
    assert len(block) < 6500, "an uncapped paper body entered the prompt"


def test_prefetch_drops_the_turn_budget_to_two():
    """Six turns is what let the verifier spend its budget on round-trips; with
    the evidence in the prompt there is nothing to spend it on."""
    src = inspect.getsource(A)
    i = src.index("if VERIFY_PREFETCH:")
    window = src[i:i + 320]
    assert "2" in window and "verify_solo" in window, (
        "prefetch leaves the six-turn budget in place, so the failure mode it "
        "exists to remove can still happen")
    assert "turns = 6" not in window, "the six-turn default leaked into the prefetch path"


def test_a_verifier_death_is_counted_now():
    """53 of them were only ever visible by grepping a log."""
    assert "verifier_raised" in STAGE_COUNTS
    src = inspect.getsource(A)
    assert 'stats["verifier_raised"]' in src


def test_it_is_on_by_default_now():
    """Round 37 measured it over 4 replicates: verifier deaths ~5/run -> 0,
    redactions 10.0 -> 3.0, verify loop 259.5 s -> 135.8 s, gateway retries
    10.0 -> 0.0. An exported-but-empty flag counts as unset, the same footgun
    the top-up switch had."""
    assert A.VERIFY_PREFETCH is True


def test_the_call_site_passes_something_that_exists():
    """The failure this file did not catch the first time.

    The helper originally took `ctx` and read `ctx.context.paper_index`, copied
    from a @function_tool where ctx IS a RunContextWrapper. This arm's
    _verify_one is handed a bare AgentContext, which has `paper_index` and no
    `context` -- so every verification raised AttributeError and round 37 died
    with status=error on replicate one, 170 s in.

    The unit tests all passed, because the stub was hand-rolled to match the
    wrong assumption. A stub cannot falsify a belief about its own caller. So
    this checks the caller against the REAL dataclass instead.
    """
    from dataclasses import fields
    names = {f.name for f in fields(A.AgentContext)}
    assert "paper_index" in names
    assert "context" not in names, (
        "AgentContext grew a .context; re-check what the call site should pass")

    src = inspect.getsource(A)
    # the CALL, not the def -- searching for the bare name finds the definition
    i = src.index("prompt += _prefetched_evidence_block(")
    call = src[i:src.index(")", i) + 1]
    attr = call.split("(", 1)[1].split(",")[0].strip()
    assert attr.startswith("ctx."), "unexpected call form: %s" % call
    assert attr.split(".", 1)[1] in names, (
        "the call site passes %s, which AgentContext does not have" % attr)


def test_the_signature_takes_an_index_not_a_context():
    """An index has one shape; a context has two and they are easy to confuse."""
    import inspect as _i
    params = list(_i.signature(A._prefetched_evidence_block).parameters)
    assert params[0] == "paper_index", params


def test_the_prefetch_verifier_has_no_tools():
    """Porting the prompt alone made it worse, not better.

    Measured on a smoke run: prefetch with the tool-carrying verifier still
    produced "Max turns (2) exceeded" four times. The model can still CHOOSE to
    call a tool, and with two turns it exhausts faster than with six -- so the
    fix that was supposed to remove the failure mode accelerated it. The evidence
    has to be in the prompt AND the tools have to be gone.
    """
    src = inspect.getsource(A)
    i = src.index('name="Claim Verifier (prefetched)"')
    block = src[i:i + 300]
    assert "tools=[]" in block, "the prefetch verifier still carries tools"


def test_prefetch_selects_the_toolless_verifier():
    src = inspect.getsource(A)
    i = src.index("if VERIFY_PREFETCH:")
    window = src[i:i + 420]
    assert 'agents["verify_solo"]' in window, (
        "prefetch still runs the tool-carrying verifier")


def test_the_default_path_keeps_its_tools():
    """Without prefetch the verifier must still be able to search the paper --
    removing its tools there would leave it with no way to check anything."""
    src = inspect.getsource(A)
    i = src.index('name="Claim Verifier"')
    block = src[i:i + 300]
    assert "tools=VERIFY_TOOLS" in block


def test_the_two_arms_read_DIFFERENT_prefetch_env_vars():
    """A trap found by auditing the flag surface.

    Both arms define a constant called VERIFY_PREFETCH, and they read different
    environment variables: the shipped arm AI_VERIFY_PREFETCH, the agent arm
    AI_AGENT_VERIFY_PREFETCH. Setting one does not touch the other, so
    "AI_VERIFY_PREFETCH=0" disables prefetch in base alone and leaves the agent
    arm prefetching -- producing what looks like an arm difference and is a flag
    difference.

    This pins the names so the trap is at least documented, and pins that both
    default ON, since an unset flag is how every round has actually run.
    """
    import inspect
    from src.classes.AIInterpret import agent, agent_loop
    assert 'os.getenv("AI_VERIFY_PREFETCH")' in inspect.getsource(agent)
    assert 'os.getenv("AI_AGENT_VERIFY_PREFETCH")' in inspect.getsource(agent_loop)
    assert agent.VERIFY_PREFETCH is True and agent_loop.VERIFY_PREFETCH is True


def test_an_empty_prefetch_flag_counts_as_unset_in_both_arms():
    """The footgun the top-up switch already had: an exported-but-empty variable
    silently disabling a default-ON stage."""
    import os, sys
    for var, module in (("AI_VERIFY_PREFETCH", "src.classes.AIInterpret.agent"),
                        ("AI_AGENT_VERIFY_PREFETCH", "src.classes.AIInterpret.agent_loop")):
        previous = os.environ.get(var)
        os.environ[var] = ""
        for name in [k for k in list(sys.modules) if "AIInterpret" in k]:
            del sys.modules[name]
        mod = __import__(module, fromlist=["VERIFY_PREFETCH"])
        try:
            assert mod.VERIFY_PREFETCH is True, "%s='' disabled prefetch" % var
        finally:
            if previous is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = previous


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_passage_reaches_the_prompt,
              test_the_model_is_told_not_to_ask_for_more,
              test_a_paper_that_cannot_be_searched_does_not_raise,
              test_a_missing_cited_text_does_not_raise,
              test_the_passage_is_capped,
              test_prefetch_drops_the_turn_budget_to_two,
              test_a_verifier_death_is_counted_now,
              test_it_is_on_by_default_now,
              test_the_call_site_passes_something_that_exists,
              test_the_signature_takes_an_index_not_a_context,
              test_the_two_arms_read_DIFFERENT_prefetch_env_vars,
              test_an_empty_prefetch_flag_counts_as_unset_in_both_arms,
              test_the_prefetch_verifier_has_no_tools,
              test_prefetch_selects_the_toolless_verifier,
              test_the_default_path_keeps_its_tools):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
