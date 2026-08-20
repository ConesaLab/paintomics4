#!/usr/bin/env python3
"""The number in the tool's description is the number the Lead obeys.

`delegate_interpretation` takes the pathways the LEAD NAMES;
`DELEGATE_MAX_PATHWAYS` only truncates that list. Measured over round 53, coverage
is 15-18 against a cap of 20, so **the cap has never bound** -- the constraint is
the description, which said "up to ~20 named pathways". The Lead was told twenty
and asked for seventeen.

That matters because the missing coverage is not random. Scoring against the
published paper item by item, cluster-mode base gains exactly three items over
this arm, and two of them are class-level: B1 "metabolic and genetic-information
pathways downregulated" and E1 "amino-acid class activity higher at early
timepoints". The agent's seventeen pathways are the top of the p-value ranking and
signalling-heavy, so it never discusses a metabolic pathway at all.

    python -m src.tests.test_the_delegation_tool_states_its_real_capacity
"""
from __future__ import annotations

import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402

_PASSED, _FAILED = [], []


def _description():
    tool = [t for t in L.TOOLBELT if t.name == "delegate_interpretation"][0]
    return tool.description or ""


def test_the_description_is_not_empty():
    """It was, for one commit. `\"\"\"...\"\"\" % X` is an expression statement, not a
    docstring, so __doc__ became None and function_tool captured an EMPTY
    description -- the tool silently lost its entire instruction. Same
    %-precedence family as two earlier bugs in this project."""
    assert len(_description()) > 300, (
        "the delegation tool has no description: %r" % _description()[:80])


def test_the_description_states_no_fixed_quota():
    """The number went 10 -> 20 -> 60 and never bound once. Each time, the fix
    was to pick a better constant and make the description agree with it; each
    time the Lead went on naming fifteen. A stated ceiling is a suggestion the
    agent reads as a target, and the honest answer -- how many fit in the time
    that is left -- is not a constant at all.

    So the description must promise NO number of pathways. It may still price a
    wave, because that is a measured cost and not a limit."""
    d = _description()
    stated = re.search(r"up to (\d+) pathways", d)
    assert not stated, (
        "the description states a fixed capacity again: %r" % (stated.group(0),))
    assert "no fixed quota" in d, d


def test_it_prices_the_cost_by_wave_not_by_pathway():
    """The old text said "covering twenty pathways costs what three would", which
    is true and stops at twenty. Cost is ceil(ceil(n/CHUNK)/WORKERS) waves at
    ~35 s, so sixty pathways is three waves, not three times the price."""
    d = _description()
    assert "per WAVE" in d, d
    assert "four at a time" in d, d


def test_the_class_breadth_clause_was_tried_and_removed():
    """It was in this description for one round and measured as a no-op.

    Round 54 added "Span the KINDS of pathway your data shows, not only the top
    of the p-value ranking". Against round 53 the pathway set came back
    IDENTICAL -- none added, none dropped -- and the metabolic share was 5% in
    both. It also pushed the description to 731 characters against the 700-char
    per-turn budget in test_tool_descriptions, so it cost a measurable amount and
    bought nothing measurable.

    Asserted absent rather than deleted, so the next person to reach for it finds
    the result instead of the idea.
    """
    d = _description()
    assert "KINDS" not in d, "the clause is back; round 54 measured it as inert"
    assert "p-value ranking" not in d, d


def test_it_still_forbids_one_call_per_pathway():
    """The behaviour the old description bought and must not lose: a delegation
    per pathway costs a wave each."""
    assert "ONE call" in _description()


def test_the_cap_is_off_by_default_and_still_pinnable():
    """0 means "ask the clock". A positive value pins a ceiling for a benchmark
    round, which is the only use the constant ever had."""
    assert isinstance(L.DELEGATE_MAX_PATHWAYS, int)
    assert L.DELEGATE_MAX_PATHWAYS == 0, (
        "a fixed delegation ceiling is back at %d" % L.DELEGATE_MAX_PATHWAYS)


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_description_is_not_empty,
              test_the_description_states_no_fixed_quota,
              test_it_prices_the_cost_by_wave_not_by_pathway,
              test_the_class_breadth_clause_was_tried_and_removed,
              test_it_still_forbids_one_call_per_pathway,
              test_the_cap_is_off_by_default_and_still_pinnable):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
