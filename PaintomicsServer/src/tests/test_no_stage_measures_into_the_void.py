#!/usr/bin/env python3
"""A stage can run perfectly and still measure nothing.

Round 36 was launched to test sentence repair. agent.py had written
`sentences_repaired`, `repairs_rejected` and `repair_unlocatable` since the
stage's first commit; the bench captured none of them; the archived row was
silent. The stage ran, the stats existed, and the round could not answer its own
question -- discovered on the first replicate, after the round was live.

The log could not stand in for it either: the repair line is logged at INFO and
the benchmark runs at WARNING, so the one human-readable trace of the stage was
invisible by configuration.

Two guards come out of that. The specific one: the repair stage's outcome keys
are archived. The general one: a ratchet, so any stat a stage STARTS writing
shows up until somebody archives it or marks it deliberately unkept. The frozen
list is not the point and will drift; the alert on new keys is.

    python -m src.tests.test_no_stage_measures_into_the_void
"""
from __future__ import annotations

import io
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks import ai_arm_bench as B  # noqa: E402

_PASSED, _FAILED = [], []

ARMS = ("src/classes/AIInterpret/agent.py",
        "src/classes/AIInterpret/agent_loop.py")


def _root(path):
    return os.path.join(os.path.dirname(__file__), "../..", path)


def test_the_repair_stage_outcome_is_archived():
    """The specific failure: this stage is a flagged experiment, so its outcome
    is the whole reason a round runs."""
    for key in ("sentences_repaired", "repairs_rejected", "repair_unlocatable"):
        assert key in B.STAGE_COUNTS, (
            "%s is written by the repair stage and kept by nothing" % key)


def test_a_new_unarchived_stat_is_flagged():
    assert B.unarchived_stats({"brand_new_metric": 1}) == ["brand_new_metric"]


def test_an_archived_stat_is_not_flagged():
    assert B.unarchived_stats({"sentences_repaired": 4}) == []


def test_a_deliberately_unkept_stat_is_not_flagged():
    """The ratchet must not nag about the 50 keys already decided against, or it
    will be ignored and stop working."""
    assert B.unarchived_stats({"merge_mode": "probe"}) == []


def test_private_scratch_keys_are_ignored():
    assert B.unarchived_stats({"_partial_stage": "synthesis"}) == []


def test_the_frozen_list_still_matches_what_the_arms_write():
    """If a key in the frozen list stops being written, the list is stale and
    the ratchet is protecting nothing. This fails loudly rather than rotting."""
    written = set()
    for path in ARMS:
        # `+=` counts as writing. The first version of this scan matched only
        # plain `=` and reported search_hits / search_kept -- both maintained
        # with `+=` in agent.py -- as keys no arm writes, which would have had
        # them deleted from the ratchet as stale. Counter-style stats are a
        # whole class this pattern was blind to.
        written |= set(re.findall(r'stats\["([a-z_0-9]+)"\]\s*\+?=',
                                  io.open(_root(path)).read()))
    archived = (set(B.STAGE_TIMES) | set(B.STAGE_COUNTS)
                | set(B.STAGE_NOTES) | set(B.STAGE_MAPS))
    stale = sorted(k for k in B.KNOWN_UNARCHIVED if k not in written)
    assert not stale, ("KNOWN_UNARCHIVED lists keys no arm writes any more: %s"
                       % ", ".join(stale))
    # and nothing has crept in unnoticed since the freeze
    crept = sorted(k for k in written
                   if k not in archived and k not in B.KNOWN_UNARCHIVED
                   and not k.startswith("_"))
    assert not crept, ("stats written but neither archived nor acknowledged: %s"
                       % ", ".join(crept))


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_repair_stage_outcome_is_archived,
              test_a_new_unarchived_stat_is_flagged,
              test_an_archived_stat_is_not_flagged,
              test_a_deliberately_unkept_stat_is_not_flagged,
              test_private_scratch_keys_are_ignored,
              test_the_frozen_list_still_matches_what_the_arms_write):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
