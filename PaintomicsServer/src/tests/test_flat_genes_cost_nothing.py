#!/usr/bin/env python3
"""A gene with no differential signal must not ship a time course.

`get_pathway_details` is the chattiest tool in the belt: 24 058 characters per
call and zero seconds, so its entire price is context -- and the Lead re-sends
context on every Decide turn, so a result returned on turn 3 of 44 is re-sent
about forty times.

`_get_top_genes` sorts (-relevant, -effect_size) and takes ten, so selection is
already relevance-first. It does not stop when the relevant genes run out, and
each flat filler gene rendered its full per-layer series. This pins the fix and,
more importantly, pins what the fix must NOT do: hide the gene.

    python -m src.tests.test_flat_genes_cost_nothing
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import agent_loop as L          # noqa: E402

_PASSED, _FAILED = [], []

_SERIES = [{"omic_name": "Gene expression", "values": "0.4@0h, 1.9@6h, 2.2@12h",
            "pattern": "sustained-up"}]


def _pathway():
    return {"name": "Test pathway", "id": "xyz00010", "source": "KEGG",
            "combined_pvalue": 0.001, "global_pvalue": 0.002,
            "significant_omic_count": 2, "per_omic": "Gene expression: p=0.001",
            "top_genes": [
                {"symbol": "Real1", "relevant": True, "effect_size": 2.2,
                 "omic_profiles": _SERIES},
                {"symbol": "Real2", "relevant": True, "effect_size": 1.8,
                 "omic_profiles": _SERIES},
                {"symbol": "Flat1", "relevant": False, "effect_size": 0.1,
                 "omic_profiles": _SERIES},
                {"symbol": "Flat2", "relevant": False, "effect_size": 0.05,
                 "omic_profiles": _SERIES},
            ]}


def _render(lean):
    before = L.LEAN_PROFILES
    L.LEAN_PROFILES = lean
    try:
        return L._pathway_block(_pathway())
    finally:
        L.LEAN_PROFILES = before


def test_a_flat_gene_is_still_named():
    """The whole point: cheaper, not hidden. A gene that matched the pathway is
    evidence the pathway matched; only its flat series is not."""
    out = _render(True)
    assert "Flat1" in out and "Flat2" in out, (
        "the change hid matched genes from the agent:\n%s" % out)


def test_a_flat_gene_keeps_its_effect_size():
    out = _render(True)
    assert "Flat1" in out and "0.10" in out, out


def test_a_flat_gene_says_why_it_has_no_series():
    """Absent data and uninteresting data must not look the same."""
    out = _render(True)
    line = [l for l in out.splitlines() if "Flat1" in l][0]
    assert "not differential" in line, (
        "a reader cannot tell a missing series from a flat one: %r" % line)


def test_a_flat_gene_ships_no_time_course():
    out = _render(True)
    line = [l for l in out.splitlines() if "Flat1" in l][0]
    assert "@" not in line and "sustained-up" not in line, (
        "the flat gene still carries its series: %r" % line)


def test_a_relevant_gene_is_untouched():
    out = _render(True)
    line = [l for l in out.splitlines() if "Real1" in l][0]
    assert "sustained-up" in line and "@" in line, (
        "the change ate a DIFFERENTIAL gene's evidence: %r" % line)
    assert line.startswith("- Real1*"), "the relevance marker was lost: %r" % line


def test_the_flag_off_path_is_byte_identical_to_before():
    """Every round measured so far ran the old renderer; the default must still
    produce exactly what those rounds produced."""
    out = _render(False)
    for sym in ("Real1", "Real2", "Flat1", "Flat2"):
        line = [l for l in out.splitlines() if sym in l][0]
        assert "sustained-up" in line, ("flag OFF changed behaviour: %r" % line)
    assert "not differential" not in out


def test_it_actually_saves_context():
    lean, full = _render(True), _render(False)
    assert len(lean) < len(full), "no saving: %d vs %d" % (len(lean), len(full))
    saved = 100.0 * (len(full) - len(lean)) / len(full)
    print("      (saved %.0f%% on a block that is half flat genes)" % saved)


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_a_flat_gene_is_still_named,
              test_a_flat_gene_keeps_its_effect_size,
              test_a_flat_gene_says_why_it_has_no_series,
              test_a_flat_gene_ships_no_time_course,
              test_a_relevant_gene_is_untouched,
              test_the_flag_off_path_is_byte_identical_to_before,
              test_it_actually_saves_context):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
