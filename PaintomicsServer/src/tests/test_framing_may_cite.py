#!/usr/bin/env python3
"""The agent arm was forbidden from citing the themes its delegates missed.

Round 38, same denominator on both arms: base converted **13 of 14** retrieved
themes into cited papers, this arm **7 of 14**. Not attribution (delegation
matched 3 chunks, 0 fallbacks) and not retrieval (both arms retrieved 14 themes).
It is a rule in the framing prompt:

    "Reuse [N] citation markers ONLY where they already appear above for that
     claim. Do not invent markers and do not renumber."

A theme no delegate happened to cover can therefore never be cited, however good
the paper. Base has no such rule: its batches cite NOTHING (0 of 3, 0 markers)
and its synthesis writes 31 markers fresh while holding the whole reference list.

The rule is not arbitrary, which is why this ships dark. MERGE_MODE="rewrite"
already tried letting one writer redo everything with the full list in view and
measured 4.5-11 citations, worse than stitch. The distinction this flag rests on:
rewriting text that ALREADY carries markers loses them (the same failure as the
sentence-repair marker drop), while writing fresh sections that carry none can
only add.

    python -m src.tests.test_framing_may_cite
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_PASSED, _FAILED = [], []
_CACHE = {}


def _load(flag):
    """Two variants, imported once each and cached.

    Re-importing per test made an earlier version of this file time out: each
    import rebuilds the SDK agents, and seven tests x two flags is fourteen
    rebuilds while a benchmark round competes for the same machine.
    """
    key = "1" if flag == "1" else "0"
    if key not in _CACHE:
        os.environ["AI_AGENT_FRAMING_MAY_CITE"] = key
        for name in [k for k in list(sys.modules) if "AIInterpret" in k]:
            del sys.modules[name]
        import src.classes.AIInterpret.agent_loop as loop
        _CACHE[key] = loop
    return _CACHE[key]


class _Ctx:
    paper_index = {
        1: {"ref_index": 1, "title": "A paper the delegates cited",
            "first_author": "Alpha", "year": "2020"},
        2: {"ref_index": 2, "title": "A paper nobody cited",
            "first_author": "Beta", "year": "2021"},
    }
    delegated = ["a delegated analysis citing [1]"]


def test_it_is_off_by_default():
    """A measured-worse neighbour (MERGE_MODE=rewrite) means this waits."""
    assert _load("0").FRAMING_MAY_CITE is False


def test_the_uncited_papers_come_first():
    """A theme gap is made of uncited papers, and the list is capped -- so the
    ones that would close the gap must not be the ones the cap drops."""
    listing = _load("1")._citable_reference_list(_Ctx())
    assert listing.index("[2]") < listing.index("[1]"), listing


def test_only_indexed_papers_are_offered():
    """A marker pointing at nothing is redacted anyway, but it also burns a
    verification slot a real citation could have used."""
    listing = _load("1")._citable_reference_list(_Ctx())
    assert "[1]" in listing and "[2]" in listing and "[3]" not in listing


def test_the_list_is_capped():
    class Big:
        paper_index = {i: {"ref_index": i, "title": "t%d" % i,
                           "first_author": "a", "year": "2020"}
                       for i in range(1, 80)}
        delegated = []
    out = _load("1")._citable_reference_list(Big(), limit=40)
    assert len(out.split("\n")) == 40


def test_the_permission_replaces_the_prohibition():
    """Both instructions in one prompt is the self-contradiction that
    test_tool_descriptions exists to catch."""
    src = inspect.getsource(_load("1"))
    i = src.index("FRAMING_MAY_CITE else")
    window = src[max(0, i - 800):i + 500]
    assert "Cite from the reference list below" in window
    assert "Do not invent markers" in window, "the off-branch prohibition vanished"


def test_the_delegates_own_markers_are_protected():
    """The stitched per-pathway text carries the grounding; letting the framing
    call add citations must not license it to touch that text."""
    src = inspect.getsource(_load("1"))
    i = src.index("Cite from the reference list below")
    assert "Do not touch the" in src[i:i + 400]


def test_the_flag_reaches_the_fingerprint_and_the_stamp():
    assert _load("0")._code_fingerprint() != _load("1")._code_fingerprint()
    src = inspect.getsource(_load("1"))
    # The stamp is assembled into `_config_stamp` and emitted afterwards, so
    # slicing FORWARD from the _trace_gate call reads an empty tail. Read the
    # construction. Third test in this suite to need this fix.
    _start = src.index("_config_stamp = dict(")
    stamp = src[_start:src.index('_trace_gate(ctx, "__config__"', _start)]
    assert '"framing_may_cite"' in stamp


def test_the_prompt_BUILDS_with_the_flag_off():
    """The test that was missing, and the reason a dark change broke production.

    Every other test in this file reads source text. None of them built the
    prompt -- so `base + (branch_a if flag else branch_b) % (report, detail)`
    passed them all, while % (binding tighter than +) formatted the BRANCH, which
    has no placeholders when the flag is off. TypeError, 153 s into every agent
    replicate, on the DEFAULT path.
    """
    loop = _load("0")
    out = loop._build_framing_prompt(_Ctx(), "THE DRAFT", "THE DETAIL")
    assert "THE DRAFT" in out and "THE DETAIL" in out
    assert "Do not invent markers" in out
    assert "%s" not in out, "an unfilled placeholder survived into the prompt"


def test_the_prompt_BUILDS_with_the_flag_on():
    loop = _load("1")
    out = loop._build_framing_prompt(_Ctx(), "THE DRAFT", "THE DETAIL")
    assert "THE DRAFT" in out and "THE DETAIL" in out
    assert "Cite from the reference list below" in out
    assert "[2] A paper nobody cited" in out, "the citable list is missing"
    assert "%s" not in out


def test_neither_branch_leaks_the_other():
    on = _load("1")._build_framing_prompt(_Ctx(), "d", "x")
    off = _load("0")._build_framing_prompt(_Ctx(), "d", "x")
    assert "Do not invent markers" not in on
    assert "Reference list you may cite" not in off


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_it_is_off_by_default,
              test_the_uncited_papers_come_first,
              test_only_indexed_papers_are_offered,
              test_the_list_is_capped,
              test_the_permission_replaces_the_prohibition,
              test_the_delegates_own_markers_are_protected,
              test_the_flag_reaches_the_fingerprint_and_the_stamp,
              test_the_prompt_BUILDS_with_the_flag_off,
              test_the_prompt_BUILDS_with_the_flag_on,
              test_neither_branch_leaks_the_other):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
