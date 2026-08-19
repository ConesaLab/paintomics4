#!/usr/bin/env python3
"""A round must load both arms at launch, or a mid-round edit kills one of them.

agent.py imports agent_loop LAZILY -- inside run_ai_agent, only when
AI_FULL_AGENT=1. So a round loads the shipped arm at launch and the agent arm
minutes later, and an edit in between leaves the process holding a NEW
agent_loop against the ALREADY-LOADED old verification module.

Measured, round 37: verification.py gained quote_provenance after launch. Both
agent replicates died at wall 0 with "cannot import name 'quote_provenance'",
while both base replicates ran perfectly and produced the round's best result.
Two replicates lost.

This invalidates a rule I had relied on all session -- "the bench runs
in-process, so a mid-round edit cannot contaminate a running round". True only
for modules already imported. Importing both arms up front makes a round's code
the snapshot at launch that the config fingerprint always claimed it was.

    python -m src.tests.test_a_round_pins_its_code
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks import ai_arm_bench as B  # noqa: E402

_PASSED, _FAILED = [], []


def test_both_arms_are_importable_together():
    """The direct check: pinning must not itself raise, whatever the flags say."""
    B.pin_both_arms()
    for name in ("src.classes.AIInterpret.agent",
                 "src.classes.AIInterpret.agent_loop"):
        assert name in sys.modules, "%s was not pinned" % name


def test_pinning_happens_before_any_command_runs():
    """After the first replicate is too late -- that is the failure."""
    src = inspect.getsource(B.main)
    assert "pin_both_arms()" in src, "main() does not pin the arms"
    pinned = src.index("pin_both_arms()")
    dispatch = src.index("add_parser(")
    assert pinned < dispatch, "the arms are pinned after argument dispatch"


def test_pinning_never_changes_which_arm_runs():
    """Pinning is an import, not a switch.

    This used to assert the arm was entered behind AI_FULL_AGENT. The six-phase
    workflow was removed, so there is no longer a second arm to choose between
    and no flag to choose with -- but the property that matters is unchanged and
    is now stronger: nothing pinning does may introduce a branch on which arm
    runs, because every archived comparison assumes one.
    """
    src = inspect.getsource(sys.modules["src.classes.AIInterpret.agent"])
    assert "run_agent_loop_workflow(" in src, (
        "run_ai_agent no longer dispatches to the interpreter loop")
    assert "run_agent_workflow(" not in src, (
        "a second arm reappeared; archived rounds assume exactly one")


def test_pinning_is_idempotent():
    B.pin_both_arms()
    B.pin_both_arms()


def test_the_shared_module_exports_what_both_arms_import():
    """The specific breakage: agent_loop imports names from verification, and a
    stale verification module in the same process cannot supply new ones. If a
    name is missing here, a round would die minutes in rather than at launch."""
    from src.classes.AIInterpret import verification as V
    import re
    src = inspect.getsource(sys.modules["src.classes.AIInterpret.agent_loop"])
    block = re.search(r"from src\.classes\.AIInterpret\.verification import \((.*?)\)",
                      src, re.S)
    assert block, "the import block moved; update this test"
    names = [n.strip() for n in block.group(1).replace("\n", " ").split(",")]
    missing = [n for n in names if n and not hasattr(V, n)]
    assert not missing, "verification.py does not export: %s" % ", ".join(missing)


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    # Collected, not hand-listed: a renamed or removed test used to leave a
    # NameError here and the suite died instead of running.
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith('test_') and callable(o)]
    assert tests, 'no tests collected'
    for name, t in tests:
        _check(name, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
