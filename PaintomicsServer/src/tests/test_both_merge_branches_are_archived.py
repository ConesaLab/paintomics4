#!/usr/bin/env python3
"""A decision stage must record what it did, not only what it refused.

The stitch guard writes `merge_rejected` when it declines and
`merge_citations` / `merge_grounded` / `merge_gain_chars` when it accepts. Only
the refusal was archived: the other five keys sat in KNOWN_UNARCHIVED, the list
that exists to stop the ratchet complaining about stats nothing keeps.

The effect is worse than a missing number. The guard rejects PRECISELY when
grounded citations fall, so the surviving records are a biased sample -- six
rejections across rounds 40-47, every one of them showing grounding drop, which
is a tautology rather than evidence. Whether delegation (this arm's central
design choice) helps or hurts citation grounding could not be answered from any
completed round, because the accepted merges were the half being discarded.

    python -m src.tests.test_both_merge_branches_are_archived
"""
from __future__ import annotations

import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks import ai_arm_bench as B                 # noqa: E402

_PASSED, _FAILED = [], []
_LOOP = os.path.join(os.path.dirname(__file__),
                     "../classes/AIInterpret/agent_loop.py")


def _kept():
    return (set(B.STAGE_TIMES) | set(B.STAGE_COUNTS)
            | set(B.STAGE_NOTES) | set(B.STAGE_MAPS))


def _merge_keys_written():
    """Every stats key the merge stage actually writes, read from the source."""
    src = open(os.path.abspath(_LOOP)).read()
    return set(re.findall(r'stats\["(merge_[a-z_]+)"\]', src))


def test_every_merge_key_the_code_writes_is_archived():
    written, kept = _merge_keys_written(), _kept()
    missing = sorted(written - kept)
    assert not missing, (
        "the merge stage writes these and nothing keeps them: %s" % missing)


def test_no_merge_key_hides_in_the_ratchet():
    """KNOWN_UNARCHIVED silences the ratchet. A whole decision stage must never
    be in it, or the ratchet reports success while the stage goes unmeasured."""
    hidden = sorted(k for k in B.KNOWN_UNARCHIVED if k.startswith("merge_"))
    assert not hidden, "merge keys are being knowingly dropped: %s" % hidden


def test_the_accepted_branch_survives_a_round():
    """The branch that was missing. An accepted stitch reports what it bought."""
    left = B.unarchived_stats({"merge_citations": "18->21",
                               "merge_grounded": "15->19",
                               "merge_gain_chars": 34390,
                               "merge_coverage": "12->15",
                               "merge_mode": "stitch"})
    assert left == [], "an accepted merge would still vanish: %r" % left


def test_the_rejected_branch_still_survives():
    """The half that already worked must not regress while fixing the other."""
    left = B.unarchived_stats({"merge_rejected":
                               "len 9555->43945, cites 25->12, GROUNDED 21->12"})
    assert left == [], "the rejection reason stopped being archived: %r" % left


def test_both_branches_land_in_the_same_record():
    """A round must be able to tell accept from reject without a second file."""
    budget = B._stage_budget({"merge_citations": "18->21", "merge_gain_chars": 100})
    assert budget.get("merge_citations") == "18->21", budget
    assert budget.get("merge_gain_chars") == 100, budget


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_every_merge_key_the_code_writes_is_archived,
              test_no_merge_key_hides_in_the_ratchet,
              test_the_accepted_branch_survives_a_round,
              test_the_rejected_branch_still_survives,
              test_both_branches_land_in_the_same_record):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
