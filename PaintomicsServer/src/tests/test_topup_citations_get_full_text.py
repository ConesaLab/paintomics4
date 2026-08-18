#!/usr/bin/env python3
"""The top-up cites exactly the papers the full-text upgrade skipped.

The upgrade selects `thin` = papers ALREADY cited that are abstract-only. The
top-up then cites papers that were NOT cited -- by definition the ones the
upgrade passed over -- so every citation it adds points at an abstract, and a
specific mechanistic claim rarely has a quotable sentence in one.

That is rule 3's failure in full. Across rounds 39-41, `topup_added_failed`
EQUALS `failed_citations` in every replicate: every failed citation was one the
top-up added, and the two replicates where the top-up never fired shipped zero
failures and zero redactions. The shipped arm has no such problem -- it
batch-fetches full text for everything it retrieves, and its top-up fails 0.0.

    python -m src.tests.test_topup_citations_get_full_text
"""
from __future__ import annotations

import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_arm_bench import STAGE_COUNTS, STAGE_NOTES, STAGE_TIMES  # noqa: E402
from src.classes.AIInterpret import agent_loop as L  # noqa: E402

_PASSED, _FAILED = [], []


def test_the_upgrade_runs_on_what_the_topup_just_cited():
    src = inspect.getsource(L)
    # the CALL, not the def: searching the bare name finds `async def` first,
    # which sits ~93 000 characters earlier in this module.
    i = src.index('stats["topup_added_refs"] = sorted')
    window = src[i:i + 1600]
    assert "await _upgrade_new_citations(" in window, (
        "the top-up's new citations never get full text")
    assert 'stats["topup_added_refs"])' in window, (
        "the upgrade is not given the references the top-up just added")


def test_only_abstract_only_papers_are_fetched():
    """A paper that already has full text must not be re-fetched: the round has
    a clock and this runs at the end of it."""
    src = inspect.getsource(L._upgrade_new_citations)
    assert 'get("fetch_tier") == "abstract_only"' in src


def test_it_is_bounded_by_the_gate_reserve():
    """Every optional step here is: what it does not reach stays an abstract and
    the gate redacts what cannot be quoted, which is the behaviour it exists to
    reduce rather than replace."""
    src = inspect.getsource(L._upgrade_new_citations)
    assert "GATE_MIN_SECONDS" in src and "bounded(" in src
    assert "topup_fulltext_skipped" in src, "a skipped upgrade says nothing"


def test_a_failed_fetch_does_not_lose_the_citations():
    """The papers stay cited with their abstracts; the gate decides. An exception
    here must not cost the report its top-up."""
    src = inspect.getsource(L._upgrade_new_citations)
    assert "topup_fulltext_failed" in src
    i = src.index("except")
    assert "raise" not in src[i:i + 200]


def test_the_upgraded_paper_keeps_its_index_and_themes():
    """ref_index is the citation's identity and pathways are the attribution key;
    fetch_papers knows neither."""
    src = inspect.getsource(L._upgrade_new_citations)
    assert 'fresh["ref_index"] = paper["ref_index"]' in src
    assert 'fresh["pathways"] = paper.get("pathways", [])' in src


def test_the_outcome_is_archived():
    assert "topup_fulltext_gained" in STAGE_COUNTS
    assert "topup_fulltext_s" in STAGE_TIMES
    for note in ("topup_fulltext_skipped", "topup_fulltext_failed"):
        assert note in STAGE_NOTES, note


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_upgrade_runs_on_what_the_topup_just_cited,
              test_only_abstract_only_papers_are_fetched,
              test_it_is_bounded_by_the_gate_reserve,
              test_a_failed_fetch_does_not_lose_the_citations,
              test_the_upgraded_paper_keeps_its_index_and_themes,
              test_the_outcome_is_archived):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
