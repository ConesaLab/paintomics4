#!/usr/bin/env python3
"""The writers should see the text the verifier will judge them against.

Measured over round 50: of 35 cited papers, 34 were abstract-only when the report
was written. Full text is fetched at the GATE, for papers already cited, and its
only consumer is the verifier -- so the pipeline pays to retrieve it and spends
all of it checking work done without it.

`_quote_shelf` is the delegates' entire evidence and runs `search_paper_text`
over each paper's `sections`, which for a thin paper is just the abstract.

    python -m src.tests.test_delegates_get_full_text
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402

_PASSED, _FAILED = [], []


class _PubMed:
    """Returns full text for one pmid and nothing for the other."""
    calls = []

    def fetch_papers(self, pmids):
        _PubMed.calls.append(list(pmids))
        out = []
        for pmid in pmids:
            if str(pmid) == "111":
                out.append({"pmid": "111", "fetch_tier": "pmc",
                            "sections": {"results": "Cathelicidin rose 4.2-fold."},
                            "title": "T1"})
        return out


class _Boom:
    def fetch_papers(self, pmids):
        raise RuntimeError("europe pmc down")


def _ctx(pubmed):
    c = L.LoopContext(job_instance=None, job_id="FTPROBE",
                      organism_name="mmu", experiment_design="")
    c.pubmed = pubmed
    c.paper_index = {1: {"pmid": "111", "ref_index": 1, "fetch_tier": "abstract_only"},
                     2: {"pmid": "222", "ref_index": 2, "fetch_tier": "abstract_only"}}
    return c


def _papers(c):
    return [c.paper_index[1], c.paper_index[2]]


def test_thin_papers_are_upgraded_before_the_shelf_is_built():
    _PubMed.calls = []
    c = _ctx(_PubMed())
    out = asyncio.run(L._upgrade_chunk_papers(c, _papers(c)))
    got = {p["ref_index"]: p for p in out}
    assert got[1]["fetch_tier"] == "pmc", got[1]
    assert "results" in got[1]["sections"], got[1]


def test_a_paper_with_no_full_text_is_kept_as_is():
    """Fail soft: the delegate writes from the abstract rather than losing the
    paper entirely."""
    c = _ctx(_PubMed())
    out = asyncio.run(L._upgrade_chunk_papers(c, _papers(c)))
    got = {p["ref_index"]: p for p in out}
    assert got[2]["fetch_tier"] == "abstract_only"
    assert len(out) == 2, "a paper disappeared: %r" % out


def test_the_index_is_updated_so_later_chunks_and_the_gate_reuse_it():
    c = _ctx(_PubMed())
    asyncio.run(L._upgrade_chunk_papers(c, _papers(c)))
    assert c.paper_index[1]["fetch_tier"] == "pmc", (
        "the upgrade did not reach the shared index, so every chunk citing this "
        "paper would fetch it again")
    assert c.paper_index[1]["ref_index"] == 1, "the reference number was lost"


def test_a_fetch_failure_never_stops_a_delegation():
    c = _ctx(_Boom())
    out = asyncio.run(L._upgrade_chunk_papers(c, _papers(c)))
    assert len(out) == 2, out
    assert "delegate_fulltext_failed" in c.extra_stats


def test_nothing_thin_means_no_call_at_all():
    _PubMed.calls = []
    c = _ctx(_PubMed())
    for p in c.paper_index.values():
        p["fetch_tier"] = "pmc"
    asyncio.run(L._upgrade_chunk_papers(c, _papers(c)))
    assert _PubMed.calls == [], "fetched papers that already had full text"


def test_the_gain_is_counted():
    c = _ctx(_PubMed())
    asyncio.run(L._upgrade_chunk_papers(c, _papers(c)))
    assert c.extra_stats.get("delegate_fulltext_gained") == 1, c.extra_stats


def test_the_flag_defaults_off_and_gates_the_call_site():
    assert L.DELEGATE_FULLTEXT is False
    src = open(L.__file__.replace(".pyc", ".py")).read()
    i = src.index("chunk_papers = _papers_for(chunk)")
    block = src[i:i + 240]
    assert "DELEGATE_FULLTEXT" in block, "the upgrade is not flag-gated"
    assert block.index("DELEGATE_FULLTEXT") < block.index("_quote_shelf"), (
        "the upgrade must run BEFORE the shelf is built, or it changes nothing")


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_thin_papers_are_upgraded_before_the_shelf_is_built,
              test_a_paper_with_no_full_text_is_kept_as_is,
              test_the_index_is_updated_so_later_chunks_and_the_gate_reuse_it,
              test_a_fetch_failure_never_stops_a_delegation,
              test_nothing_thin_means_no_call_at_all,
              test_the_gain_is_counted,
              test_the_flag_defaults_off_and_gates_the_call_site):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
