#!/usr/bin/env python3
"""A diagnostic that is stored and never surfaced fails the same way as one that
was never stored, and costs more to build.

Rule 3 failed for three consecutive rounds. I chased it through screening
strictness, a pool ceiling, delegation attribution, the delegation window and
framing permissions -- and the answer was in `topup_added_failed`, a column added
several rounds earlier to price exactly that stage. It equalled
`failed_citations` in all twelve replicates of rounds 39-41, meaning every failed
citation came from the top-up. Nobody read it, because nothing printed it.

The verdict now prints, under each FAILING rule, the columns that explain that
rule. Passing rules stay quiet: the point is to answer the question a failure
raises, not to bury it in a wider table.

    python -m src.tests.test_failing_rules_explain_themselves
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import RULE_DIAGNOSTICS, _diagnose  # noqa: E402

_PASSED, _FAILED = [], []

AGENT = [{"failed_citations": 2, "topup_added": 14, "topup_added_failed": 4,
          "sentences_dropped": 9, "failed_refs": "3,4,7"}]
BASE = [{"failed_citations": 0, "topup_added": 6, "topup_added_failed": 0,
         "sentences_dropped": 1}]


def test_the_redaction_rule_surfaces_the_topup_columns():
    """The specific failure this exists for."""
    out = "\n".join(_diagnose("3 redactions <= base + 2", AGENT, BASE))
    assert "topup_added_failed" in out, out
    assert "failed_citations" in out


def test_each_number_is_shown_against_base():
    """'4 failed' means nothing without knowing base failed 0."""
    out = "\n".join(_diagnose("3 redactions <= base + 2", AGENT, BASE))
    assert "topup_added_failed 4.0 vs 0.0" in out, out


def test_a_string_diagnostic_is_shown_as_itself():
    """failed_refs is a list of indices, not a number to average."""
    out = "\n".join(_diagnose("3 redactions <= base + 2", AGENT, BASE))
    assert "failed_refs 3,4,7" in out, out


def test_a_missing_column_is_skipped_not_zero():
    """An absent counter must not print as 0.0 and read as a measurement."""
    out = "\n".join(_diagnose("3 redactions <= base + 2", [{"failed_citations": 1}], BASE))
    assert "topup_added_failed" not in out


def test_every_rule_has_diagnostics():
    """A rule that can fail with nothing to say sends the reader back to the
    archive, which is the situation this replaces."""
    for prefix in ("1 every replicate", "2 citations", "3 redactions",
                   "4 prose coverage", "5 length"):
        assert any(k.startswith(prefix) for k in RULE_DIAGNOSTICS), prefix


def test_an_unknown_label_is_quiet():
    assert _diagnose("6 something new", AGENT, BASE) == []


def test_base_with_no_data_still_prints_the_arm_value():
    """Early rounds and partial runs leave base columns empty; the arm's own
    number is still worth seeing."""
    out = "\n".join(_diagnose("3 redactions <= base + 2", AGENT, [{}]))
    assert "topup_added_failed 4.0" in out


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_redaction_rule_surfaces_the_topup_columns,
              test_each_number_is_shown_against_base,
              test_a_string_diagnostic_is_shown_as_itself,
              test_a_missing_column_is_skipped_not_zero,
              test_every_rule_has_diagnostics,
              test_an_unknown_label_is_quiet,
              test_base_with_no_data_still_prints_the_arm_value):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
