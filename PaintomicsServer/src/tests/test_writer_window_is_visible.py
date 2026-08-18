#!/usr/bin/env python3
"""The constraint that actually binds retrieval was invisible to the agent.

Delegation chunks pathways DELEGATE_CHUNK at a time and hands each chunk at most
DELEGATE_PAPERS papers, so a whole run can only ever put chunks x DELEGATE_PAPERS
papers in front of a writer -- 40 at shipped settings. A paper outside that window
has NO path to a citation, whatever it says.

Measured across 72 archived runs: 3 189 papers retrieved, 872 cited, and 1 501 of
them (47%) fetched beyond any writer's window. By pool size, citations of what is
REACHABLE run 92% for pools of 30 or fewer against 32-38% for pools over 60 --
so the arm cites nearly everything it can reach, and quadrupling retrieval buys
about three citations while wasting half the fetch.

The ledger has always told the agent what it MAY spend: searches left, seconds
left, tool-output characters, clusters still unlit. It never told it the pool was
full. This adds that, and only that.

    python -m src.tests.test_writer_window_is_visible
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_PASSED, _FAILED = [], []
_CACHE = {}


def _load(flag):
    key = "1" if flag == "1" else "0"
    if key not in _CACHE:
        os.environ["AI_AGENT_SHOW_WINDOW"] = key
        for name in [k for k in list(sys.modules) if "AIInterpret" in k]:
            del sys.modules[name]
        import src.classes.AIInterpret.agent_loop as loop
        _CACHE[key] = loop
    return _CACHE[key]


def _ctx(loop, n_pathways=15, n_papers=0):
    import time
    c = loop.LoopContext(job_instance=None, job_id="T", organism_name="mmu",
                         experiment_design="", started_at=time.time(),
                         hard_deadline=time.time() + 600)
    c.pathways = [{"id": "p%d" % i} for i in range(n_pathways)]
    c.paper_index = {i: {"ref_index": i} for i in range(1, n_papers + 1)}
    return c


def test_the_window_is_chunks_times_papers_per_chunk():
    loop = _load("1")
    # 15 pathways at 5 per chunk = 3 writers x 10 papers
    assert loop._writer_window(_ctx(loop, 15)) == 30


def test_the_window_is_capped_by_max_pathways():
    """102 significant pathways do not buy 21 writers: DELEGATE_MAX_PATHWAYS
    bounds it, which is why the ceiling is 40 and not the pathway count."""
    loop = _load("1")
    assert loop._writer_window(_ctx(loop, 102)) == 40


def test_one_pathway_still_gets_a_writer():
    loop = _load("1")
    assert loop._writer_window(_ctx(loop, 1)) == 10


def test_a_full_pool_says_more_searching_cannot_help():
    """The actionable half: the agent should learn that better targeting, not
    more volume, is what is left."""
    loop = _load("1")
    note = loop._ledger_note(_ctx(loop, 15, n_papers=90))
    assert "more searching cannot add a citation" in note, note
    assert "90 papers held" in note


def test_room_left_is_reported_as_room():
    """Before the window fills, the same notice must not read as a warning."""
    loop = _load("1")
    note = loop._ledger_note(_ctx(loop, 15, n_papers=5))
    assert "room for about 25 more" in note, note
    assert "cannot add a citation" not in note


def test_it_says_nothing_when_off():
    loop = _load("0")
    note = loop._ledger_note(_ctx(loop, 15, n_papers=90))
    assert "papers held" not in note


def test_the_existing_ledger_fields_survive():
    """It is an addition to the note the agent already reads every turn, not a
    replacement -- the searches and seconds are what bound the run."""
    loop = _load("1")
    note = loop._ledger_note(_ctx(loop, 15, n_papers=90))
    assert "searches left" in note and "s left" in note and "tool-output chars" in note


def test_the_flag_reaches_the_fingerprint():
    off, on = _load("0"), _load("1")
    assert off._code_fingerprint() != on._code_fingerprint()


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_the_window_is_chunks_times_papers_per_chunk,
              test_the_window_is_capped_by_max_pathways,
              test_one_pathway_still_gets_a_writer,
              test_a_full_pool_says_more_searching_cannot_help,
              test_room_left_is_reported_as_room,
              test_it_says_nothing_when_off,
              test_the_existing_ledger_fields_survive,
              test_the_flag_reaches_the_fingerprint):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
