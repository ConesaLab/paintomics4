#!/usr/bin/env python3
"""A run must be able to say which pipeline produced it.

The config stamp was a hand-written dict of ~15 keys, so a flag reached the
archive only if someone remembered to add it. Audited: 35 AI_AGENT_* flags exist
in agent_loop.py and 12 had ever appeared in an archived stamp. Round 49 ran with
FRAMING_REUSE_LEAD=1 and its own stamp did not record it -- so a trace could not
be asked, afterwards, which pipeline it came from.

`_code_fingerprint` already refuses a hand-kept list for this reason and hashes
the module instead, but a hash answers "same code or not", never "what differs".

    python -m src.tests.test_a_run_records_every_flag
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402

_PASSED, _FAILED = [], []
_SRC = open(L.__file__.replace(".pyc", ".py")).read()


def _declared_flags():
    return set(re.findall(r'os\.getenv\(\s*"(AI_AGENT_[A-Z_]+)"', _SRC))


def test_every_declared_flag_is_in_the_snapshot():
    snap = L._flag_snapshot()
    missing = sorted(f for f in _declared_flags()
                     if f[len("AI_AGENT_"):].lower() not in snap)
    # RUN_LABEL is read inline for the stamp itself rather than bound to a
    # module constant, and is already recorded under its own key.
    missing = [m for m in missing if m != "AI_AGENT_RUN_LABEL"]
    assert not missing, "flags a run cannot report: %s" % missing


def test_the_flags_this_session_added_are_covered():
    """The four added in the last few iterations -- exactly the ones a hand-kept
    list would have missed, and did."""
    snap = L._flag_snapshot()
    for key in ("framing_reuse_lead", "lean_profiles", "topup_abstract",
                "citation_target"):
        assert key in snap, "%s is not recorded: %s" % (key, sorted(snap))


def test_the_snapshot_reports_live_values_not_defaults():
    before = L.FRAMING_REUSE_LEAD
    L.FRAMING_REUSE_LEAD = True
    try:
        assert L._flag_snapshot()["framing_reuse_lead"] is True
    finally:
        L.FRAMING_REUSE_LEAD = before
    assert L._flag_snapshot()["framing_reuse_lead"] is before


def test_the_snapshot_is_json_serialisable():
    """The stamp is written with json.dumps, and a stamp that raises there
    silently loses the whole run's configuration."""
    json.dumps(L._flag_snapshot())


def test_the_old_hand_named_keys_survive():
    """Every round measured so far is parsed by tools that read these exact
    spellings; the derived keys are added beside them, not instead."""
    for key in ('"merge_mode":', '"search_hits":', '"delegate_chunk":',
                '"screen_papers":', '"verify_topup":', '"code":'):
        assert key in _SRC, "the stamp dropped %s" % key


def test_a_broken_snapshot_cannot_kill_a_run():
    """Telemetry must never be the reason an interpretation fails."""
    i = _SRC.index("def _flag_snapshot")
    body = _SRC[i:_SRC.index("def _code_fingerprint")]
    assert "except Exception" in body and "return {}" in body, body[-300:]


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_every_declared_flag_is_in_the_snapshot,
              test_the_flags_this_session_added_are_covered,
              test_the_snapshot_reports_live_values_not_defaults,
              test_the_snapshot_is_json_serialisable,
              test_the_old_hand_named_keys_survive,
              test_a_broken_snapshot_cannot_kill_a_run):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
