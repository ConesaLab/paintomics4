#!/usr/bin/env python3
"""Two runs of different pipelines stamped the same fingerprint.

_code_fingerprint exists because the config stamp could not see a behaviour
change: its own docstring says a cache, a nudge or a reworded tool description
leaves the tunable constants identical, so "two runs of genuinely different
agents stamp the same line and get averaged together".

It hashed module source, the Lead prompt and the tool descriptions -- and left
the hole open for the one kind of change that alters behaviour without altering
a byte of source: an environment flag. AI_SENTENCE_REPAIR=1 and =0 run different
verify loops and hashed identically, so round 36's repair runs and round 35's
rewrite runs were indistinguishable in the archive by exactly the mechanism
built to distinguish them.

    python -m src.tests.test_fingerprint_sees_behaviour_flags
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_PASSED, _FAILED = [], []


def _reload_with(**env):
    """Re-import the arm under a given environment; flags are read at import."""
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update({k: v for k, v in env.items()})
    for name in [k for k in list(sys.modules) if "AIInterpret" in k]:
        del sys.modules[name]
    import src.classes.AIInterpret.agent_loop as loop
    try:
        return loop._code_fingerprint(), loop.SENTENCE_REPAIR, loop
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_the_repair_flag_changes_the_fingerprint():
    off, off_flag, _ = _reload_with(AI_SENTENCE_REPAIR="0")
    on, on_flag, _ = _reload_with(AI_SENTENCE_REPAIR="1")
    assert off_flag is False and on_flag is True, "the flag did not take effect"
    assert off != on, (
        "two different verify loops stamp the same fingerprint (%s); a round "
        "cannot be told apart from the round before it" % off)


def test_the_same_configuration_is_still_stable():
    """A fingerprint that changed run to run would be just as useless."""
    first, _, _ = _reload_with(AI_SENTENCE_REPAIR="1")
    second, _, _ = _reload_with(AI_SENTENCE_REPAIR="1")
    assert first == second, "the fingerprint is not reproducible"


def test_the_mode_is_also_readable_in_plain_text():
    """The hash proves two runs differ; a human needs to know HOW."""
    import inspect
    _, _, loop = _reload_with(AI_SENTENCE_REPAIR="1")
    src = inspect.getsource(loop)
    stamp = src[src.index('_trace_gate(ctx, "__config__"'):][:1400]
    assert '"sentence_repair"' in stamp, (
        "the config stamp records the flag nowhere in readable form")


def test_the_flag_is_off_by_default():
    _, flag, _ = _reload_with(AI_SENTENCE_REPAIR="")
    assert flag is False


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_repair_flag_changes_the_fingerprint,
              test_the_same_configuration_is_still_stable,
              test_the_mode_is_also_readable_in_plain_text,
              test_the_flag_is_off_by_default):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
