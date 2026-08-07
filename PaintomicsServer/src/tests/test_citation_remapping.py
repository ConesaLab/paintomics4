"""Local-to-global citation remapping.

Batches are numbered [1..n] and remapped afterwards because models renumber
citations from 1 regardless of the indices they are handed. Both the threaded
pipeline and the SDK pipeline now depend on this, and nothing covered it.

The failure it guards against is silent and total: a batch handed its global
indices ([7], [12], [15]) either gets renumbered anyway -- so every marker
points at the wrong paper -- or the model stops citing altogether. A measured
SDK run produced a 19,602-character report with zero citation markers that way.

The swap is two-pass for a reason, and that reason is the interesting test:
mapping 1->3 and 3->7 in one pass turns [1] into [3] and then into [7].
"""
import os
import sys
import traceback

SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(SERVER_ROOT, "src"))
sys.path.insert(0, SERVER_ROOT)

from src.classes.AIInterpret.pipeline import (
    _build_local_paper_index, _remap_citation_indices,
)

_PASSED, _FAILED = [], []


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  " + name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  " + name)


def test_local_index_is_contiguous_from_one():
    papers = [{"pmid": "a", "ref_index": 7}, {"pmid": "b", "ref_index": 12},
              {"pmid": "c", "ref_index": 15}]
    local, mapping = _build_local_paper_index(papers)
    assert [p["ref_index"] for p in local] == [1, 2, 3], local
    assert mapping == {1: 7, 2: 12, 3: 15}, mapping
    # The originals must not be mutated -- they are the global index everyone
    # else reads.
    assert [p["ref_index"] for p in papers] == [7, 12, 15], papers


def test_chained_mapping_does_not_cascade():
    """1->3 and 3->7 in one pass would turn [1] into [7]."""
    text = "First claim [1]. Third claim [3]."
    out = _remap_citation_indices(text, {1: 3, 3: 7})
    assert out == "First claim [3]. Third claim [7].", out


def test_swap_is_not_lost():
    """A straight swap is the tightest case: 1<->2."""
    out = _remap_citation_indices("[1] and [2]", {1: 2, 2: 1})
    assert out == "[2] and [1]", out


def test_two_digit_indices_are_not_eaten_by_one_digit_ones():
    """Replacing [1] before [12] would corrupt [12] into [<mapped>]2."""
    text = "See [1], [12], and [2]."
    out = _remap_citation_indices(text, {1: 5, 2: 6, 12: 9})
    assert out == "See [5], [9], and [6].", out


def test_multi_citation_groups_survive():
    out = _remap_citation_indices("Supported by [1, 2] and [3].", {1: 4, 2: 5, 3: 6})
    assert out == "Supported by [4, 5] and [6].", out


def test_unmapped_indices_are_left_alone():
    out = _remap_citation_indices("[1] and [9]", {1: 2})
    assert out == "[2] and [9]", out


def test_empty_mapping_is_identity():
    text = "Nothing to remap [1]."
    assert _remap_citation_indices(text, {}) == text


def test_empty_batch_yields_empty_index():
    local, mapping = _build_local_paper_index([])
    assert local == [] and mapping == {}, (local, mapping)


def test_round_trip_through_a_realistic_batch():
    papers = [{"pmid": str(p), "ref_index": p} for p in (3, 9, 14)]
    local, mapping = _build_local_paper_index(papers)
    # What the model writes, using the local numbering it was given.
    model_output = "Ikaros represses Myc [1]. Polyamines fall [2, 3]."
    out = _remap_citation_indices(model_output, mapping)
    assert out == "Ikaros represses Myc [3]. Polyamines fall [9, 14].", out


def main():
    for t in (test_local_index_is_contiguous_from_one,
              test_chained_mapping_does_not_cascade,
              test_swap_is_not_lost,
              test_two_digit_indices_are_not_eaten_by_one_digit_ones,
              test_multi_citation_groups_survive,
              test_unmapped_indices_are_left_alone,
              test_empty_mapping_is_identity,
              test_empty_batch_yields_empty_index,
              test_round_trip_through_a_realistic_batch):
        _check(t.__name__, t)

    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
