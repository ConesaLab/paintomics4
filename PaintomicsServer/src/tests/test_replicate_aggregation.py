"""
Unit tests for src.common.ReplicateDetection.aggregate_replicates.

Pinned behaviour:
- Mean over replicate columns per sample (NaN-safe).
- Relevance OR-collapses across replicates of a sample.
- Unequal replicate counts, singleton samples, and empty / all-NaN samples
  are all handled without raising.
- ``relevant`` accepts list[bool], scalar bool, ``None``, and stringified
  booleans (legacy serializer compatibility).

Run from PaintomicsServer/:
    python -m src.tests.test_replicate_aggregation
"""

import math
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.common.ReplicateDetection import (  # noqa: E402
    aggregate_replicates,
    detect_replicates,
)

_PASS, _FAIL = [], []


def _check(name, fn):
    try:
        fn()
        _PASS.append(name)
        print(f"  PASS  {name}")
    except AssertionError as e:
        _FAIL.append((name, str(e)))
        print(f"  FAIL  {name}: {e}")
    except Exception:
        _FAIL.append((name, traceback.format_exc()))
        print(f"  ERROR {name}")
        traceback.print_exc()


def _close(actual, expected, tol=1e-9):
    """Floating-point closeness with NaN equality."""
    if math.isnan(expected):
        return math.isnan(actual)
    return abs(actual - expected) < tol


# ---------------------------------------------------------------------------
# Mean computation
# ---------------------------------------------------------------------------

def test_mean_two_samples_two_replicates_each():
    """Canonical 4-replicate file → 2 samples."""
    vals, rel = aggregate_replicates(
        values=[1.0, 3.0, 10.0, 20.0],
        relevant=[True, True, False, False],
        groups=[[0, 1], [2, 3]],
        n_samples=2,
    )
    assert _close(vals[0], 2.0), vals
    assert _close(vals[1], 15.0), vals
    assert rel == [True, False]


def test_unequal_replicate_counts():
    """1, 2, 3 replicates per sample — all means correct."""
    vals, rel = aggregate_replicates(
        values=[5.0, 10.0, 12.0, 0.0, 6.0, 12.0],
        relevant=[True, False, False, False, False, True],
        groups=[[0], [1, 2], [3, 4, 5]],
        n_samples=3,
    )
    assert _close(vals[0], 5.0), vals
    assert _close(vals[1], 11.0), vals
    assert _close(vals[2], 6.0), vals
    assert rel == [True, False, True]


def test_singleton_sample_is_pass_through():
    """A sample with one replicate returns that exact value."""
    vals, rel = aggregate_replicates(
        values=[42.0],
        relevant=[True],
        groups=[[0]],
        n_samples=1,
    )
    assert _close(vals[0], 42.0)
    assert rel == [True]


def test_brl3_real_world_aggregation():
    """End-to-end with detect_replicates → aggregate_replicates."""
    header = [
        "brl3.2_22_R1", "brl3.2_22_R2",
        "brl3.2_28_R1", "brl3.2_28_R2",
        "BRL3ox_22_R1", "BRL3ox_22_R2",
        "BRL3ox_28_R1", "BRL3ox_28_R2",
    ]
    det = detect_replicates(header)
    assert det["status"] == "complete", det

    # Synthetic per-replicate values: each replicate pair has values (i, i+1)
    # so the mean is i + 0.5 for sample i.
    values = []
    for i in range(len(det["sampleHeader"])):
        values.extend([float(i), float(i + 1)])
    relevant = [(i % 3 == 0) for i in range(len(values))]

    sample_vals, sample_rel = aggregate_replicates(
        values=values,
        relevant=relevant,
        groups=det["groups"],
        n_samples=len(det["sampleHeader"]),
    )
    assert len(sample_vals) == 4
    for i, v in enumerate(sample_vals):
        assert _close(v, i + 0.5), (i, v)


# ---------------------------------------------------------------------------
# NaN handling
# ---------------------------------------------------------------------------

def test_nan_within_group_uses_nanmean():
    """One NaN among non-NaN replicates: mean over the rest."""
    vals, _ = aggregate_replicates(
        values=[1.0, float("nan"), 3.0],
        relevant=[True, False, True],
        groups=[[0, 1, 2]],
        n_samples=1,
    )
    assert _close(vals[0], 2.0), (
        "nanmean([1, nan, 3]) must be 2.0"
    )


def test_all_nan_group_yields_nan():
    """Every replicate NaN → sample value is NaN, not 0 or an exception."""
    vals, _ = aggregate_replicates(
        values=[float("nan"), float("nan")],
        relevant=[False, False],
        groups=[[0, 1]],
        n_samples=1,
    )
    assert math.isnan(vals[0]), vals


def test_empty_group_yields_nan():
    """A sample with zero replicates returns NaN, not an exception."""
    vals, rel = aggregate_replicates(
        values=[1.0, 2.0],
        relevant=[True, True],
        groups=[[0, 1], []],   # second sample has no replicates
        n_samples=2,
    )
    assert _close(vals[0], 1.5)
    assert math.isnan(vals[1])
    assert rel == [True, False]


# ---------------------------------------------------------------------------
# Relevance shapes
# ---------------------------------------------------------------------------

def test_or_collapse_relevance():
    """A sample is relevant iff *any* of its replicates is relevant."""
    _, rel = aggregate_replicates(
        values=[0.0, 0.0, 0.0, 0.0],
        relevant=[False, True, False, False],
        groups=[[0, 1], [2, 3]],
        n_samples=2,
    )
    assert rel == [True, False]


def test_scalar_bool_relevance_emits_feature_level():
    """A scalar bool carries the 'feature-level' semantic — emit length-1.

    The renderer's existing `length <= 1` guard treats this as a row-label
    flag, not per-cell stars, so a 'this gene is significant overall' input
    doesn't accidentally light up every cell after aggregation.
    """
    _, rel = aggregate_replicates(
        values=[1.0, 2.0, 3.0, 4.0],
        relevant=True,
        groups=[[0, 1], [2, 3]],
        n_samples=2,
    )
    assert rel == [True], rel


def test_length_one_relevance_emits_feature_level():
    """A length-1 list ≡ feature-level (the existing PaintOmics convention)."""
    _, rel = aggregate_replicates(
        values=[1.0, 2.0, 3.0, 4.0],
        relevant=[True],
        groups=[[0, 1], [2, 3]],
        n_samples=2,
    )
    assert rel == [True], rel
    # Same shape for the False case so the guard fires consistently.
    _, rel = aggregate_replicates(
        values=[1.0, 2.0, 3.0, 4.0],
        relevant=[False],
        groups=[[0, 1], [2, 3]],
        n_samples=2,
    )
    assert rel == [False], rel


def test_single_column_relevance_does_not_light_up_one_sample():
    """Regression test for the white-star bug.

    Reproduction: a 16-replicate values file plus a single-column relevant-
    features file (the gene is "relevant overall"). Before the fix the
    aggregator broadcast `[True]` to length 16 (with False fill), then
    OR-collapsed across 8 sample groups, producing `[True, F, F, F, F, F,
    F, F]` — which made *only the first sample's cell* show a star.
    The intended behaviour is no per-cell stars (length-1 sampleRelevant
    triggers the renderer's row-label guard).
    """
    _, rel = aggregate_replicates(
        values=[float(i) for i in range(16)],
        relevant=[True],                           # feature-level RF
        groups=[[2*i, 2*i+1] for i in range(8)],   # 8 samples × 2 reps
        n_samples=8,
    )
    assert rel == [True], rel
    assert len(rel) == 1, (
        "feature-level input must produce length-1 sampleRelevant, not " +
        str(len(rel))
    )


def test_none_relevance_is_feature_level_false():
    """``relevant=None`` defaults to feature-level False (length 1)."""
    _, rel = aggregate_replicates(
        values=[1.0, 2.0],
        relevant=None,
        groups=[[0, 1]],
        n_samples=1,
    )
    assert rel == [False]


def test_empty_relevance_is_feature_level_false():
    """Empty list ≡ no flags ≡ feature-level False."""
    _, rel = aggregate_replicates(
        values=[1.0, 2.0],
        relevant=[],
        groups=[[0, 1]],
        n_samples=1,
    )
    assert rel == [False]


def test_stringified_booleans_in_relevance():
    """BSON round-trips occasionally produce '\"True\"'/'\"False\"' strings."""
    _, rel = aggregate_replicates(
        values=[1.0, 2.0, 3.0, 4.0],
        relevant=["True", "False", "False", "True"],
        groups=[[0, 1], [2, 3]],
        n_samples=2,
    )
    assert rel == [True, True]


# ---------------------------------------------------------------------------
# Defensive cases
# ---------------------------------------------------------------------------

def test_n_samples_must_match_len_groups():
    """Mismatched n_samples and len(groups) raises early."""
    try:
        aggregate_replicates(
            values=[1.0, 2.0],
            relevant=[True, False],
            groups=[[0, 1]],
            n_samples=2,        # but len(groups) == 1
        )
    except ValueError:
        return
    raise AssertionError("expected ValueError for shape mismatch")


def test_misaligned_relevance_does_not_crash():
    """Defensive padding keeps a too-short `relevant` from raising."""
    _, rel = aggregate_replicates(
        values=[1.0, 2.0, 3.0, 4.0],
        relevant=[True, True],   # only 2 flags for 4 replicates
        groups=[[0, 1], [2, 3]],
        n_samples=2,
    )
    # First sample: both flags map to True → True.
    # Second sample: indices 2/3 fall outside the supplied flags → defaulted
    # to False by the broadcast helper.
    assert rel == [True, False], rel


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

print("\n── Replicate aggregation ────────────────────────────────────")
print("  Mean computation")
_check("2 samples × 2 replicates",                     test_mean_two_samples_two_replicates_each)
_check("Unequal replicate counts (1/2/3)",             test_unequal_replicate_counts)
_check("Singleton sample is pass-through",             test_singleton_sample_is_pass_through)
_check("brl3 detect→aggregate end-to-end",             test_brl3_real_world_aggregation)

print("  NaN handling")
_check("Partial NaNs use nanmean",                     test_nan_within_group_uses_nanmean)
_check("All-NaN group yields NaN",                     test_all_nan_group_yields_nan)
_check("Empty group yields NaN",                       test_empty_group_yields_nan)

print("  Relevance shapes")
_check("Per-replicate flags OR-collapse",              test_or_collapse_relevance)
_check("Scalar bool → length-1 (feature-level)",       test_scalar_bool_relevance_emits_feature_level)
_check("Length-1 list → length-1 (feature-level)",     test_length_one_relevance_emits_feature_level)
_check("Single-column RF doesn't light up sample 0",   test_single_column_relevance_does_not_light_up_one_sample)
_check("None relevance → feature-level False",         test_none_relevance_is_feature_level_false)
_check("Empty list relevance → feature-level False",   test_empty_relevance_is_feature_level_false)
_check("Stringified bools coerced",                    test_stringified_booleans_in_relevance)

print("  Defensive cases")
_check("Shape mismatch raises ValueError",             test_n_samples_must_match_len_groups)
_check("Misaligned relevance does not crash",          test_misaligned_relevance_does_not_crash)

print(f"\n{'─'*55}")
print(f"  Results: {len(_PASS)} passed, {len(_FAIL)} failed")
if _FAIL:
    print("\nFailed tests:")
    for name, msg in _FAIL:
        print(f"  ✗ {name}")
        first_line = msg.splitlines()[0] if msg else ""
        if first_line:
            print(f"    {first_line}")

sys.exit(1 if _FAIL else 0)
