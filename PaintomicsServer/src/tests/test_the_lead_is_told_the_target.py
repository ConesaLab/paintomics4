#!/usr/bin/env python3
"""The agent held to a number must be told the number.

MIN_CITATIONS is 22 and this arm's median is ~20, so the citation top-up fires on
EVERY run by construction: 101 s, 28% of the clock, ~43% precision, bolting
markers onto sentences written without them.

`check_my_citations` is at 100% adoption and runs while the draft can still
change -- and it reports STATUS, never the TARGET. "17 citations will ship, 15
have a supporting quote" gives the Lead no way to know it is five short. So it
submits, and a stage with no quotes in hand makes up the difference badly.

This pins the message, and pins the thing that could go wrong with it: an agent
told to reach a number may invent markers, which is the exact failure the top-up
already demonstrates.

    python -m src.tests.test_the_lead_is_told_the_target
"""
from __future__ import annotations

import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402

_PASSED, _FAILED = [], []


def _headline(grounded, shipped=20, target=22, on=True):
    """Rebuild the tool's summary lines for a given state, as the tool does."""
    lines = ["%d citation(s) will ship (%d in this draft, the rest in the "
             "delegated analyses the gate merges in); %d have a supporting quote."
             % (shipped, shipped, grounded)]
    if on:
        short = target - grounded
        if short > 0:
            lines.append(
                "A finished report is expected to carry about %d GROUNDED "
                "citations and you have %d, so you are %d short. The gap is "
                "usually a paper you retrieved and never opened: read_paper, "
                "then cite the sentence you actually find. Do NOT add a marker "
                "you cannot quote to reach the number -- an unsupported "
                "citation costs the whole sentence it sits on, and you lose the "
                "finding as well as the marker." % (target, grounded, short))
        else:
            lines.append("That meets the ~%d grounded citations a finished "
                         "report is expected to carry." % target)
    return "\n".join(lines)


def test_the_source_matches_this_fixture():
    """The fixture above must be the code's own text, or this file tests itself.
    A prompt bug in this project survived ten tests that inspected source
    instead of building the string."""
    src = open(L.__file__.replace(".pyc", ".py")).read()
    for phrase in ("expected to carry about %d GROUNDED",
                   "read_paper, ",
                   "costs the whole sentence it sits on"):
        assert phrase in src, "fixture drifted from the code: %r" % phrase


def test_a_short_draft_is_told_how_short():
    out = _headline(grounded=15)
    assert "7 short" in out, out
    assert "about 22 GROUNDED" in out


def test_it_counts_GROUNDED_citations_not_markers():
    """The target must be measured in citations that survive, or the advice is
    'add more brackets' -- which is what the top-up already does badly."""
    src = open(L.__file__.replace(".pyc", ".py")).read()
    i = src.index("SHOW_CITATION_TARGET:")
    block = src[i:i + 500]
    assert "len(quotes)" in block, (
        "the shortfall is computed from something other than quoted citations")
    assert "len(cited)" not in block.split("short =")[1][:40], (
        "the shortfall is counting markers, not grounded citations")


def test_it_names_the_mechanism_measurement_supports():
    """Reading papers is worth +3 citations (0 -> 9 reads) against +1 for
    retrieving 2.3x as many papers. The advice should point at the lever that
    works, not at 'search more'."""
    out = _headline(grounded=15)
    assert "read_paper" in out, out
    assert "search" not in out.lower(), "it points at the weakest lever: %s" % out


def test_it_warns_against_forcing_a_marker():
    out = _headline(grounded=15)
    assert "Do NOT add a marker you cannot quote" in out
    assert "costs the whole sentence" in out


def test_a_sufficient_draft_is_not_nagged():
    out = _headline(grounded=22)
    assert "short" not in out, out
    assert "meets the ~22" in out


def test_the_flag_defaults_off():
    assert L.SHOW_CITATION_TARGET is False


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_source_matches_this_fixture,
              test_a_short_draft_is_told_how_short,
              test_it_counts_GROUNDED_citations_not_markers,
              test_it_names_the_mechanism_measurement_supports,
              test_it_warns_against_forcing_a_marker,
              test_a_sufficient_draft_is_not_nagged,
              test_the_flag_defaults_off):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
