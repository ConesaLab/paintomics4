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


def test_the_stated_capacity_matches_the_constant():
    """A description that promises more than the code honours would have the Lead
    name pathways that are then silently truncated."""
    stated = re.search(r"up to (\d+) pathways", _description())
    assert stated, "the description no longer states a capacity: %s" % _description()[:120]
    assert int(stated.group(1)) == L.DELEGATE_MAX_PATHWAYS, (
        "description says %s, DELEGATE_MAX_PATHWAYS is %d"
        % (stated.group(1), L.DELEGATE_MAX_PATHWAYS))


def test_it_prices_the_cost_by_wave_not_by_pathway():
    """The old text said "covering twenty pathways costs what three would", which
    is true and stops at twenty. Cost is ceil(ceil(n/CHUNK)/WORKERS) waves at
    ~35 s, so sixty pathways is three waves, not three times the price."""
    d = _description()
    assert "per WAVE" in d, d
    assert "four at a time" in d, d


def test_it_asks_for_class_breadth_not_just_more():
    """Naming more of the same top-ranked signalling pathways is not what the
    rubric rewards -- within cluster-mode base, r(coverage, rubric) is -0.68."""
    d = _description()
    assert "KINDS" in d or "kinds" in d, d
    assert "metabolic" in d, d
    assert "p-value ranking" in d, d


def test_it_still_forbids_one_call_per_pathway():
    """The behaviour the old description bought and must not lose: a delegation
    per pathway costs a wave each."""
    assert "ONE call" in _description()


def test_the_cap_is_configurable():
    assert isinstance(L.DELEGATE_MAX_PATHWAYS, int)


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
              test_the_stated_capacity_matches_the_constant,
              test_it_prices_the_cost_by_wave_not_by_pathway,
              test_it_asks_for_class_breadth_not_just_more,
              test_it_still_forbids_one_call_per_pathway,
              test_the_cap_is_configurable):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
