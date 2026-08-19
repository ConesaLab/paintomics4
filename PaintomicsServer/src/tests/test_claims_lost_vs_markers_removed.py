#!/usr/bin/env python3
"""`redacted` counts markers, not claims, and the difference is a factor of three.

Rule 3 -- "redactions <= base + 2" -- is the rule the agent arm currently fails,
and until now nobody could say what it was failing on. `redact_unverified_v2`
returns the number of bad MARKERS taken out of the body plus the reference
entries dropped. This project's own notes called that "sentences lost", and once
recorded "1 failed citation = 15 lost sentences" when it meant 15 markers.

A sentence that also cites something verified keeps its place with only the bad
marker stripped -- 39% of citation-bearing sentences carry two or more citations
-- so the count of claims actually destroyed can be a third of the count of
markers removed.

    python -m src.tests.test_claims_lost_vs_markers_removed
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS  # noqa: E402
from src.classes.AIInterpret.verification import (  # noqa: E402
    last_sentences_dropped, redact_unverified_v2)

_PASSED, _FAILED = [], []

REPORT = ("Alpha claim [3] and more. Beta claim [3][7] here. Gamma claim [7] alone.\n"
          "\n### References\n[3] a paper\n[7] another paper\n")


def test_a_sentence_with_a_surviving_citation_is_not_a_lost_claim():
    out, removed = redact_unverified_v2(REPORT, [{"ref_index": 3}])
    assert "Beta claim [7] here." in out, out
    assert last_sentences_dropped() == 1, "only the [3]-only sentence should go"
    assert removed == 3, "markers plus the reference entry"


def test_the_two_numbers_are_allowed_to_differ_widely():
    """The point: rule 3 reads the larger number."""
    out, removed = redact_unverified_v2(REPORT, [{"ref_index": 3}])
    assert removed > last_sentences_dropped()


def test_a_clean_report_loses_nothing():
    out, removed = redact_unverified_v2(REPORT, [])
    assert out == REPORT and removed == 0


def test_every_sentence_failing_destroys_every_claim():
    out, removed = redact_unverified_v2(
        REPORT, [{"ref_index": 3}, {"ref_index": 7}])
    assert last_sentences_dropped() == 3, "all three claims cite only failures"


def test_the_claim_count_reaches_the_archive():
    assert "sentences_dropped" in STAGE_COUNTS


def test_both_arms_record_it():
    import inspect
    from src.classes.AIInterpret import agent, agent_loop
    for module in (agent, agent_loop):
        src = inspect.getsource(module)
        assert 'stats["sentences_dropped"] = last_sentences_dropped()' in src, (
            module.__name__)


def test_it_is_read_immediately_after_the_redaction():
    """The count lives beside the function rather than in its return type, so a
    caller that reads it late reads another run's number."""
    import inspect
    from src.classes.AIInterpret import agent_loop
    src = inspect.getsource(agent_loop)
    red = src.index("redact_unverified_v2(report, final[")
    read = src.index('stats["sentences_dropped"]')
    assert 0 < read - red < 700, "the diagnostic is read far from its redaction"


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_sentence_with_a_surviving_citation_is_not_a_lost_claim,
              test_the_two_numbers_are_allowed_to_differ_widely,
              test_a_clean_report_loses_nothing,
              test_every_sentence_failing_destroys_every_claim,
              test_the_claim_count_reaches_the_archive,
              test_both_arms_record_it,
              test_it_is_read_immediately_after_the_redaction):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
