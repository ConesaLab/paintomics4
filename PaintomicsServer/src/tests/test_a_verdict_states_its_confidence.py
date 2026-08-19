#!/usr/bin/env python3
"""A PASS must say whether the round could tell the difference from noise.

The five rules compare two means and print PASS or FAIL. Neither says whether
four replicates were enough to separate the arms from run-to-run spread -- and
measured over rounds 46-48, eleven replicates per arm, they are not:

    coverage    agent 14.6 +- 2.3   base 13.3 +- 1.9   gap +1.36   needs n~19
    citations   agent 21.5 +- 3.6   base 18.3 +- 3.9   gap +3.18   needs n~11
    redactions  agent  0.0 +- 0.0   base  5.1 +- 6.8   gap -5.09   needs n~7

Base is FIXED code and still ranges 10-15 on coverage and 10-24 on citations, so
the incumbent's own noise is larger than most effects being chased. Rounds 47 and
48 ran effectively identical agent code (LEAN_PROFILES was a no-op: genes_flat
was 0 in every replicate) and produced coverage 14.0 vs 13.0 -- a pass -- then
12.7 vs 15.0 -- a fail.

The thresholds are pre-registered and untouched. This pins the CONFIDENCE
annotation only.

    python -m src.tests.test_a_verdict_states_its_confidence
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks import ai_arm_bench as B                 # noqa: E402

_PASSED, _FAILED = [], []


def _rows(cov, cites=20, red=0, chars=40000, wall=300):
    return [{"prose_pathways_covered": c, "citations_in_body": cites,
             "redacted": red, "report_chars": chars, "wall_s": wall,
             "status": "done"} for c in cov]


def test_a_margin_inside_the_noise_is_called_noise():
    agent = _rows([15, 12, 16, 11])          # mean 13.5, wide
    base = _rows([13, 14, 12, 15])           # mean 13.5 -> tiny margin
    agent[0]["prose_pathways_covered"] = 16  # nudge the mean just over
    rules, _ = B.judge(agent, base)
    cov = [d for lbl, _p, d in rules if lbl.startswith("4 prose")][0]
    assert "NOISE" in cov, "a margin inside the spread was reported as settled: %s" % cov
    assert "needs n~" in cov, "it does not say how many replicates would settle it"


def test_a_clear_margin_is_called_resolved():
    agent = _rows([19, 19, 20, 19])
    base = _rows([11, 12, 11, 12])
    rules, _ = B.judge(agent, base)
    cov = [d for lbl, _p, d in rules if lbl.startswith("4 prose")][0]
    assert "resolved" in cov and "NOISE" not in cov, cov


def test_the_thresholds_are_untouched():
    """The annotation must not change a single verdict. Same rows, the pass/fail
    booleans must be exactly what the pre-registered comparison gives."""
    agent = _rows([15, 12, 16, 11], cites=25, red=0)
    base = _rows([13, 14, 12, 15], cites=18, red=6)
    rules, overall = B.judge(agent, base)
    by = {lbl.split()[0]: passed for lbl, passed, _d in rules}
    assert by["2"] is True, "citations 25 vs 18 should pass"
    assert by["3"] is True, "redactions 0 vs 6 should pass"
    assert by["4"] is True, "coverage 13.5 vs 13.5 -- >= holds"
    assert overall is True


def test_a_failing_rule_is_still_failing_however_noisy():
    agent = _rows([9, 9, 9, 9])
    base = _rows([15, 15, 15, 15])
    rules, overall = B.judge(agent, base)
    by = {lbl.split()[0]: passed for lbl, passed, _d in rules}
    assert by["4"] is False, "coverage 9 vs 15 must fail regardless of annotation"
    assert overall is False


def test_one_replicate_annotates_nothing_rather_than_guessing():
    """A single run has no spread to estimate. Silence beats a fabricated se."""
    assert B.resolvable(_rows([15]), _rows([13]), "prose_pathways_covered", 2) is None


def test_zero_variance_on_both_sides_is_resolved_not_noise():
    """Agent redactions are 0.0 with zero spread across every recent replicate;
    that is the strongest result in the suite and must not read as unresolved."""
    out = B.resolvable(_rows([15, 15], red=0), _rows([13, 13], red=0),
                       "redacted", 2.0)
    assert out and out[0] == "resolved", out


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_margin_inside_the_noise_is_called_noise,
              test_a_clear_margin_is_called_resolved,
              test_the_thresholds_are_untouched,
              test_a_failing_rule_is_still_failing_however_noisy,
              test_one_replicate_annotates_nothing_rather_than_guessing,
              test_zero_variance_on_both_sides_is_resolved_not_noise):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
