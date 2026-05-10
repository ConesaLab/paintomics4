"""
Unit tests for src.common.ReplicateDetection.detect_replicates.

The detector is intentionally conservative — these tests double as
documentation of *which* header patterns we agree to silently collapse
and which we deliberately refuse to.

Run from PaintomicsServer/:
    python -m src.tests.test_replicate_detection
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.common.ReplicateDetection import detect_replicates  # noqa: E402

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


# ---------------------------------------------------------------------------
# status == "complete" — accepted patterns
# ---------------------------------------------------------------------------

def test_underscore_R_uppercase():
    """Canonical bioinformatics suffix: Sample_R1 / Sample_R2."""
    res = detect_replicates(["Ctrl_R1", "Ctrl_R2", "Treat_R1", "Treat_R2"])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["Ctrl", "Treat"]
    assert res["mapping"] == [0, 0, 1, 1]
    assert res["groups"] == [[0, 1], [2, 3]]
    assert res["unmatched"] == []


def test_dot_rep_lowercase():
    """Sample.rep1 / Sample.rep2 — common in proteomics."""
    res = detect_replicates(["A.rep1", "A.rep2", "B.rep1", "B.rep2"])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["A", "B"]


def test_underscore_replicate_word():
    """Verbose form: Sample_replicate_1."""
    res = detect_replicates([
        "WT_replicate_1", "WT_replicate_2",
        "KO_replicate_1", "KO_replicate_2",
    ])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["WT", "KO"]


def test_mixed_case_tag():
    """Case-insensitive tag matching."""
    res = detect_replicates(["X_r1", "X_R2", "Y_Rep1", "Y_rEp2"])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["X", "Y"]


def test_preserves_original_sample_order():
    """sampleHeader must follow first-seen order, not lexicographic."""
    res = detect_replicates([
        "Treat_R1", "Treat_R2",
        "Ctrl_R1",  "Ctrl_R2",
    ])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["Treat", "Ctrl"], (
        "Order must reflect the column order in the file, not be re-sorted."
    )


def test_unequal_replicate_counts_still_complete():
    """Replicate counts can vary across samples (1, 2, 3 …)."""
    res = detect_replicates(["A_R1", "B_R1", "B_R2", "C_R1", "C_R2", "C_R3"])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["A", "B", "C"]
    assert res["groups"] == [[0], [1, 2], [3, 4, 5]]


def test_complex_sample_name_only_strips_last_suffix():
    """Non-greedy: keep `Ctrl_24h` intact and only strip the trailing _R1."""
    res = detect_replicates(["Ctrl_24h_R1", "Ctrl_24h_R2", "Ctrl_48h_R1", "Ctrl_48h_R2"])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["Ctrl_24h", "Ctrl_48h"]


def test_dash_separator():
    """Dash-separated suffix (less common but valid)."""
    res = detect_replicates(["s1-R1", "s1-R2", "s2-R1", "s2-R2"])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["s1", "s2"]


def test_brl3_real_world_example():
    """Sanity: the user's brl3 example collapses 16→8 cleanly."""
    header = [
        "brl3.2_22_R1", "brl3.2_22_R2",
        "brl3.2_28_R1", "brl3.2_28_R2",
        "BRL3ox_22_R1", "BRL3ox_22_R2",
        "BRL3ox_28_R1", "BRL3ox_28_R2",
        "Col.0_22_R1",  "Col.0_22_R2",
        "Col.0_28_R1",  "Col.0_28_R2",
        "pSUC2.BRL3.brl3.2_22_R1", "pSUC2.BRL3.brl3.2_22_R2",
        "pSUC2.BRL3.brl3.2_28_R1", "pSUC2.BRL3.brl3.2_28_R2",
    ]
    res = detect_replicates(header)
    assert res["status"] == "complete", res
    assert len(res["sampleHeader"]) == 8
    assert all(len(g) == 2 for g in res["groups"]), res["groups"]


# ---------------------------------------------------------------------------
# status == "none" — patterns we deliberately refuse to collapse
# ---------------------------------------------------------------------------

def test_time_points_not_collapsed():
    """T0/T1/T2 must NOT be collapsed — they are conditions, not replicates."""
    res = detect_replicates(["T0", "T1", "T2"])
    assert res["status"] == "none", (
        "T0/T1/T2 are time points; collapsing them silently would corrupt "
        "the science."
    )


def test_patient_subjects_not_collapsed():
    """Patient1/Patient2 are distinct subjects, not replicates."""
    res = detect_replicates(["Patient1", "Patient2", "Patient3"])
    assert res["status"] == "none", res


def test_bare_sample_underscore_number_not_collapsed():
    """`Sample_1` is ambiguous — could be sample 1, not replicate 1 of `Sample`."""
    res = detect_replicates(["Sample_1", "Sample_2", "Sample_3"])
    assert res["status"] == "none", (
        "Bare _N suffix is ambiguous; the regex requires an R/rep/replicate tag."
    )


def test_single_column_input():
    """logFC-style single-column file: no replicates possible."""
    res = detect_replicates(["logFC"])
    assert res["status"] == "none", res
    assert res["sampleHeader"] == []


def test_empty_input():
    """Empty list / None → status=none, no exceptions."""
    assert detect_replicates([])["status"] == "none"
    assert detect_replicates(None)["status"] == "none"


def test_all_singletons_not_collapsed():
    """If every sample has exactly one replicate, aggregation is a no-op."""
    res = detect_replicates(["A_R1", "B_R1", "C_R1"])
    assert res["status"] == "none", (
        "All-singleton matches are not useful — aggregating one column "
        "into one sample changes nothing."
    )


def test_multi_condition_named_columns_not_collapsed():
    """Real Paintomics multi-condition headers without replicate tags."""
    res = detect_replicates(["Ctrl", "Treat_2h", "Treat_6h"])
    assert res["status"] == "none", res


def test_multi_condition_logfc_columns_not_collapsed():
    """Per-condition logFC columns should pass through unchanged."""
    res = detect_replicates(["logFC_T0", "logFC_T1", "logFC_T2"])
    assert res["status"] == "none", res


# ---------------------------------------------------------------------------
# status == "partial" — some columns match, some don't
# ---------------------------------------------------------------------------

def test_partial_match_flagged():
    """If only some columns match, refuse to silently aggregate."""
    res = detect_replicates(["A_R1", "A_R2", "B_R1", "ExtraCol"])
    assert res["status"] == "partial", res
    assert 3 in res["unmatched"]
    # The detector still surfaces what it found, so the UI can render a hint.
    assert res["sampleHeader"] == ["A", "B"]


def test_partial_match_with_singleton_only_match():
    """Partial detection with no replicate sets is still 'partial', not 'none'."""
    res = detect_replicates(["A_R1", "ExtraCol1", "ExtraCol2"])
    assert res["status"] == "partial", res
    # Even though A has only one replicate, surface it for the UI hint.
    assert res["sampleHeader"] == ["A"]


# ---------------------------------------------------------------------------
# Robustness — pathological inputs
# ---------------------------------------------------------------------------

def test_whitespace_around_names_tolerated():
    """Headers with leading/trailing whitespace still match."""
    res = detect_replicates(["  A_R1 ", "A_R2"])
    assert res["status"] == "complete", res
    assert res["sampleHeader"] == ["A"]


def test_empty_string_columns_treated_as_unmatched():
    """Empty / whitespace-only column names cannot be replicates."""
    res = detect_replicates(["A_R1", "A_R2", "", "   "])
    assert res["status"] == "partial", res
    assert 2 in res["unmatched"] and 3 in res["unmatched"]


def test_pathological_pure_suffix_rejected():
    """A header that is *only* a replicate suffix has no real sample name."""
    res = detect_replicates(["_R1", "_R2"])
    assert res["status"] == "none", (
        "Stripping `_R1` from `_R1` leaves an empty sample name — reject."
    )


def test_non_string_columns_rejected_gracefully():
    """Non-string entries (None, ints) shouldn't crash the detector."""
    res = detect_replicates(["A_R1", None, "A_R2", 42])
    assert res["status"] == "partial", res
    # Index 0 and 2 matched as A; 1 and 3 are unmatched.
    assert res["unmatched"] == [1, 3]


# ---------------------------------------------------------------------------
# Mapping integrity
# ---------------------------------------------------------------------------

def test_mapping_length_always_matches_header():
    """`mapping` is always parallel to the input header for any status."""
    for header in (
        ["A_R1", "A_R2"],                              # complete
        ["A_R1", "B_R1"],                              # none (singletons)
        ["A_R1", "Extra"],                             # partial
        ["T0", "T1"],                                  # none
        [],                                            # none
    ):
        res = detect_replicates(header)
        assert len(res["mapping"]) == len(header), (
            f"mapping length mismatch for header={header}: {res}"
        )


def test_groups_indices_round_trip_with_mapping():
    """For each sample, groups[s] must contain exactly the indices i where mapping[i] == s."""
    res = detect_replicates(["X_R1", "Y_R1", "X_R2", "Y_R2", "X_R3"])
    assert res["status"] == "complete", res
    for s_idx, cols in enumerate(res["groups"]):
        for c in cols:
            assert res["mapping"][c] == s_idx, res
        # Every col with mapping == s_idx must appear in groups[s_idx].
        for c, m in enumerate(res["mapping"]):
            if m == s_idx:
                assert c in cols, res


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

print("\n── ReplicateDetection ───────────────────────────────────────")
print("  Accepted patterns")
_check("_R1/_R2 (canonical)",                          test_underscore_R_uppercase)
_check(".rep1/.rep2",                                  test_dot_rep_lowercase)
_check("_replicate_1/_replicate_2",                    test_underscore_replicate_word)
_check("Mixed case tag (r1/R2/Rep1/rEp2)",             test_mixed_case_tag)
_check("Sample order preserved (not re-sorted)",       test_preserves_original_sample_order)
_check("Unequal replicate counts (1/2/3)",             test_unequal_replicate_counts_still_complete)
_check("Non-greedy strip (Ctrl_24h_R1 → Ctrl_24h)",    test_complex_sample_name_only_strips_last_suffix)
_check("Dash separator (s1-R1)",                       test_dash_separator)
_check("brl3 real-world (16 cols → 8 samples)",        test_brl3_real_world_example)

print("  Rejected patterns (status=none)")
_check("T0/T1/T2 (time points, not replicates)",       test_time_points_not_collapsed)
_check("Patient1/Patient2 (distinct subjects)",        test_patient_subjects_not_collapsed)
_check("Sample_1/Sample_2 (ambiguous bare _N)",        test_bare_sample_underscore_number_not_collapsed)
_check("Single column (logFC)",                        test_single_column_input)
_check("Empty / None input",                           test_empty_input)
_check("All-singleton matches",                        test_all_singletons_not_collapsed)
_check("Multi-condition named (Ctrl/Treat_2h)",        test_multi_condition_named_columns_not_collapsed)
_check("Multi-condition logFC_T0/T1/T2",               test_multi_condition_logfc_columns_not_collapsed)

print("  Partial matches (status=partial)")
_check("Mostly matching with one extra column",        test_partial_match_flagged)
_check("Partial with no replicate sets",               test_partial_match_with_singleton_only_match)

print("  Robustness")
_check("Whitespace around names tolerated",            test_whitespace_around_names_tolerated)
_check("Empty-string columns treated as unmatched",    test_empty_string_columns_treated_as_unmatched)
_check("Pure-suffix header (_R1) rejected",            test_pathological_pure_suffix_rejected)
_check("Non-string entries handled gracefully",        test_non_string_columns_rejected_gracefully)

print("  Mapping integrity")
_check("mapping length == header length (any status)", test_mapping_length_always_matches_header)
_check("groups[] and mapping[] round-trip",            test_groups_indices_round_trip_with_mapping)

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
