#!/usr/bin/env python3
"""The largest workflow remnant in the agent arm, made removable.

Measured over round 36, the agent arm spends its wall clock like this:

    Lead loop          173.0 s  56.8%   <- the agentic shape
    Verifier + repair   10.3 s   3.4%   <- the agentic shape
    full-text fetch      5.9 s   1.9%   <- gate machinery
    MERGE               15.7 s   5.2%   <- workflow remnant
    TOPUP               99.0 s  32.5%   <- workflow remnant

Two stages outside the Lead-then-Verifier shape cost 37.7% of the run, and
top-up is nearly all of it. It fires on EVERY run: the trigger is "citations
under MIN_CITATIONS" and this arm is always under it, which the constant's own
docstring records.

It is also a bet with asymmetric stakes -- it adds [N] to sentences that already
stood on their own, so a marker that verifies buys one citation and one that
fails costs the whole sentence -- and the Lead already owns the job through
check_my_citations, which every run calls.

This does not delete it. It makes the alternative measurable, which is the only
way it gets deleted honestly.

    python -m src.tests.test_topup_can_be_removed
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_NOTES, _stage_budget  # noqa: E402

_PASSED, _FAILED = [], []


def _load(**env):
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    for name in [k for k in list(sys.modules) if "AIInterpret" in k]:
        del sys.modules[name]
    import src.classes.AIInterpret.agent_loop as loop
    try:
        return loop
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_topup_is_on_by_default():
    """Removing a stage is the experiment, not the starting point.

    An exported-but-empty variable counts as unset. `AI_AGENT_TOPUP=` in a shell
    profile or a systemd env-file is an accident, and on a default-ON flag the
    naive `getenv(...) == "1"` turns that accident into a silently removed
    pipeline stage -- which is how this arm would have shipped without a
    citation pass and nothing in the record saying why.
    """
    assert _load(AI_AGENT_TOPUP="").TOPUP_ENABLED is True
    assert _load(AI_AGENT_TOPUP="   ").TOPUP_ENABLED is True


def test_the_off_switch_accepts_the_obvious_spellings():
    """A flag that only understands "0" invites AI_AGENT_TOPUP=false to be read
    as ON, which is the failure in the opposite direction."""
    for value in ("0", "false", "FALSE", "no", " 0 "):
        assert _load(AI_AGENT_TOPUP=value).TOPUP_ENABLED is False, value


def test_the_switch_turns_it_off():
    assert _load(AI_AGENT_TOPUP="0").TOPUP_ENABLED is False


def test_the_two_pipelines_have_different_fingerprints():
    """The lesson from round 36: a flag that changes behaviour and not the
    fingerprint makes two different pipelines average together in the archive."""
    on = _load(AI_AGENT_TOPUP="1")._code_fingerprint()
    off = _load(AI_AGENT_TOPUP="0")._code_fingerprint()
    assert on != off, "topup on and off stamp the same fingerprint"


def test_the_config_stamp_says_which_ran_in_plain_text():
    import inspect
    loop = _load(AI_AGENT_TOPUP="0")
    src = inspect.getsource(loop)
    # The stamp is assembled into `_config_stamp` and emitted afterwards, so
    # slicing FORWARD from the _trace_gate call reads an empty tail. Read the
    # construction. Third test in this suite to need this fix.
    _start = src.index("_config_stamp = dict(")
    stamp = src[_start:src.index('_trace_gate(ctx, "__config__"', _start)]
    assert '"topup_enabled"' in stamp


def test_a_disabled_stage_says_so_in_the_record():
    """An absent topup_s must not read as 'it ran and cost nothing'."""
    assert "topup_disabled" in STAGE_NOTES
    assert _stage_budget({"topup_disabled": True})["topup_disabled"] == "True"


def test_disabling_it_does_not_disable_the_gate():
    """The top-up is optional; the citation gate is not. Removing a convenience
    must not remove the guarantee."""
    import inspect
    loop = _load(AI_AGENT_TOPUP="0")
    src = inspect.getsource(loop)
    for step in ("verify_report_v2(", "redact_unverified_v2(",
                 "renumber_citations(", "sort_references_section("):
        assert step in src, "%s left the pipeline with the top-up" % step


def test_the_lead_still_has_its_own_citation_pass():
    """The argument for removing topup is that check_my_citations does the job.
    If that tool ever leaves the belt, this experiment loses its premise."""
    loop = _load(AI_AGENT_TOPUP="0")
    assert "check_my_citations" in {t.name for t in loop.TOOLBELT}


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_topup_is_on_by_default,
              test_the_off_switch_accepts_the_obvious_spellings,
              test_the_switch_turns_it_off,
              test_the_two_pipelines_have_different_fingerprints,
              test_the_config_stamp_says_which_ran_in_plain_text,
              test_a_disabled_stage_says_so_in_the_record,
              test_disabling_it_does_not_disable_the_gate,
              test_the_lead_still_has_its_own_citation_pass):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
