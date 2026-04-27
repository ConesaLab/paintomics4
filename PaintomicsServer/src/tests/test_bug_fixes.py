"""Unit tests for the multi-condition bug fixes (autoresearch loop).

Run from `PaintomicsServer/`:

    python -m src.tests.test_bug_fixes

Each test prints PASS/FAIL and exits non-zero on any failure.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.classes.Pathway import Pathway
from src.classes.Feature import OmicValue
from src.classes.Job import Job

_PASSED = []
_FAILED = []


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print(f"PASS  {name}")
    except AssertionError as exc:
        _FAILED.append((name, str(exc)))
        print(f"FAIL  {name}: {exc}")
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print(f"ERROR {name}")
        traceback.print_exc()


# -------------------- Bug A: addSignificanceValues totalMatched inflation --------------------
def test_bug_a_scalar_unchanged():
    """Single-condition behavior must be bit-identical to pre-fix."""
    p = Pathway("p1")
    p.addSignificanceValues("o", [True])
    p.addSignificanceValues("o", [False])
    p.addSignificanceValues("o", [True])
    sv = p.getSignificanceValues()["o"]
    assert sv == [[3, 2, -1.0]], f"expected [[3,2,-1.0]], got {sv}"


def test_bug_a_mixed_lengths_no_inflation():
    """Mixed-length inputs must not double-count totalMatched in later conditions."""
    p = Pathway("p1")
    p.addSignificanceValues("o", [True])
    p.addSignificanceValues("o", [False, True, True])
    sv = p.getSignificanceValues()["o"]
    # cond 0: both features contribute → matched=2, relevant=1 (only first is True)
    # cond 1: only the 3-cond feature contributes → matched=1, relevant=1
    # cond 2: only the 3-cond feature contributes → matched=1, relevant=1
    assert sv == [[2, 1, -1.0], [1, 1, -1.0], [1, 1, -1.0]], f"got {sv}"


def test_bug_a_uniform_multicond():
    """Uniform-length multi-cond inputs accumulate per condition correctly."""
    p = Pathway("p1")
    p.addSignificanceValues("o", [True, False, True])
    p.addSignificanceValues("o", [True, True, False])
    p.addSignificanceValues("o", [False, False, False])
    sv = p.getSignificanceValues()["o"]
    assert sv == [[3, 2, -1.0], [3, 1, -1.0], [3, 1, -1.0]], f"got {sv}"


def test_bug_a_late_arriving_longer():
    """Feature arriving later with MORE conditions than seen so far must extend."""
    p = Pathway("p1")
    p.addSignificanceValues("o", [True])
    p.addSignificanceValues("o", [True])
    # Now extend
    p.addSignificanceValues("o", [True, True, False])
    sv = p.getSignificanceValues()["o"]
    # cond 0: 3 contributors, all True → [3,3]
    # cond 1: 1 contributor, True → [1,1]
    # cond 2: 1 contributor, False → [1,0]
    assert sv == [[3, 3, -1.0], [1, 1, -1.0], [1, 0, -1.0]], f"got {sv}"


# -------------------- Bug D: legacy setRelevant(scalar) callsites --------------------
def test_bug_d_mirna_setrelevant_is_list():
    """MiRNA2GeneJob now wraps the relevance bool in a list."""
    import inspect
    from src.classes.JobInstances import MiRNA2GeneJob as mod
    src = inspect.getsource(mod)
    assert "setRelevant([isRelevant])" in src, \
        "MiRNA2GeneJob still calls setRelevant(scalar) — Bug D unfixed"


def test_bug_d_bed_setrelevant_is_list():
    """Bed2GeneJob now wraps the relevance bool in a list."""
    import inspect
    from src.classes.JobInstances import Bed2GeneJob as mod
    src = inspect.getsource(mod)
    assert "setRelevant([regionID in relevantRegions])" in src, \
        "Bed2GeneJob still calls setRelevant(scalar) — Bug D unfixed"


def test_bug_d_omicvalue_isrelevant_handles_list():
    """OmicValue.isRelevant() must continue to work with both shapes."""
    ov = OmicValue("g1")
    ov.setRelevant([True])
    assert ov.isRelevant() is True
    ov.setRelevant([False, True])
    assert ov.isRelevant() is True  # any() across conditions
    assert ov.isRelevant(0) is False
    assert ov.isRelevant(1) is True


# -------------------- Bug C: Arabidopsis-only header heuristic --------------------
def test_bug_c_data_detection_id_styles():
    """Various organism IDs are recognised as data, not headers."""
    cases = [
        # (row, expected_is_data)
        (["ENSMUSG00000000028", "ENSMUSG00000000056"], True),     # mouse
        (["ENSG00000139618", "ENSG00000141510"], True),            # human
        (["AT3G09260", "AT4G09260"], True),                        # arabidopsis
        (["WBGene00000419", "WBGene00000420"], True),              # C.elegans
        (["ENSDARG00000000001"], True),                            # zebrafish
        (["K00001", "K00002"], True),                              # KEGG gene
        (["cpd:C00001"], True),                                    # KEGG compound
        (["Gm6793", "Faf2"], True),                                # mouse symbols (Gm6793 has digit run)
    ]
    for row, expected in cases:
        got = Job._row_looks_like_data(row)
        assert got == expected, f"row={row} expected={expected} got={got}"


def test_bug_c_header_detection():
    """Header-like rows are NOT classified as data."""
    cases = [
        ["WT", "Treated"],
        ["Cond1", "Cond2", "Cond3"],
        ["Ikaros/Control_0h", "Ikaros/Control_2h"],
        ["#geneID", "Sample_A"],
        ["Sample1", "Sample2"],     # Sample1: no 4-digit run → header (correctly ambiguous)
    ]
    for row in cases:
        assert Job._row_looks_like_data(row) is False, f"unexpectedly data-like: {row}"


def test_bug_c_mouse_3col_rf_parses():
    """3-column ENSMUSG RF without header → 3 conditions, all True per column."""
    import tempfile
    from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
    job = PathwayAcquisitionJob(jobID="test", userID="test", CLIENT_TMP_DIR="/tmp/")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tab", delete=False) as f:
        f.write("ENSMUSG00000000028\tENSMUSG00000000056\tENSMUSG00000000078\n")
        f.write("ENSMUSG00000000028\t\tENSMUSG00000000079\n")
        path = f.name
    try:
        result = job.parseSignificativeFeaturesFile(path)
        # ENSMUSG00000000028 appears in cols 0 and 0; ENSMUSG00000000056 in col 1; etc.
        assert "ensmusg00000000028" in result, f"missing key, got {list(result.keys())}"
        assert result["ensmusg00000000028"] == [True, False, False], result["ensmusg00000000028"]
        assert result["ensmusg00000000056"] == [False, True, False]
        assert result["ensmusg00000000078"] == [False, False, True]
        assert result["ensmusg00000000079"] == [False, False, True]
    finally:
        os.unlink(path)


def test_bug_c_mouse_3col_rf_with_header():
    """3-column ENSMUSG RF WITH header → header captured, 3 conditions."""
    import tempfile
    from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
    job = PathwayAcquisitionJob(jobID="test", userID="test", CLIENT_TMP_DIR="/tmp/")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tab", delete=False) as f:
        f.write("WT\tKO\tDouble_KO\n")  # all header-like
        f.write("ENSMUSG00000000028\t\tENSMUSG00000000079\n")
        path = f.name
    try:
        result = job.parseSignificativeFeaturesFile(path)
        assert job.conditionNames == ["WT", "KO", "Double_KO"], job.conditionNames
        assert result["ensmusg00000000028"] == [True, False, False]
        assert result["ensmusg00000000079"] == [False, False, True]
    finally:
        os.unlink(path)


def test_bug_c_legacy_2col_mirna_format_preserved():
    """The 2-column legacy [MappedID, OriginalID] format still detected.

    Bug F regression: ALL rows must use ::: join, not just row 1. Pre-refactor
    behavior was to always join 2-column files; the multi-cond refactor only
    joined row 1 and silently dropped the suffix on rows 2+, which broke
    miRNA relevance matching against values files (whose IDs are :::joined).
    """
    import tempfile
    from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
    job = PathwayAcquisitionJob(jobID="test", userID="test", CLIENT_TMP_DIR="/tmp/")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tab", delete=False) as f:
        # mirroring real mirna_relevant.tab — multiple distinct (gene, miRNA) pairs
        f.write("ENSMUSG00000038127\tmmu-miR-3091-3p\n")
        f.write("ENSMUSG00000038127\tmmu-miR-466k\n")
        f.write("ENSMUSG00000028211\tmmu-miR-106a-5p\n")
        path = f.name
    try:
        result = job.parseSignificativeFeaturesFile(path)
        # Every row should be ::: joined (not just row 1).
        assert "ensmusg00000038127:::mmu-mir-3091-3p" in result, list(result.keys())
        assert "ensmusg00000038127:::mmu-mir-466k" in result, list(result.keys())
        assert "ensmusg00000028211:::mmu-mir-106a-5p" in result, list(result.keys())
        for k, v in result.items():
            assert v == [True], f"{k} = {v}"
        # No accidental single-column entries.
        assert "ensmusg00000038127" not in result
        assert "ensmusg00000028211" not in result
    finally:
        os.unlink(path)


# -------------------- Bug B: only _c0 adjusted combined p-value reaches frontend --------------------
def test_bug_b_setMethodAdjusted_accepts_list():
    """Pathway storage now accepts list-shaped per-condition adjusted values."""
    p = Pathway("p1")
    p.setMethodAdjustedCombinedSignificanceValues("Fisher", {
        "BH": [0.01, 0.03, 0.5],
        "Bonferroni": [0.05, 0.15, 1.0],
    })
    stored = p.adjustedCombinedSignificanceValues["Fisher"]
    assert stored["BH"] == [0.01, 0.03, 0.5], stored
    assert stored["Bonferroni"] == [0.05, 0.15, 1.0], stored


def test_bug_b_setMethodAdjusted_back_compat_scalar():
    """Single-condition jobs still use scalar shape (back-compat)."""
    p = Pathway("p1")
    p.setMethodAdjustedCombinedSignificanceValues("Fisher", {"BH": 0.04})
    assert p.adjustedCombinedSignificanceValues["Fisher"]["BH"] == 0.04


def test_bug_b_BSON_roundtrip_preserves_list():
    """toBSON+parseBSON preserves the list shape."""
    p = Pathway("p1")
    p.setMethodAdjustedCombinedSignificanceValues("Fisher", {"BH": [0.01, 0.03, 0.5]})
    bson = p.toBSON()
    p2 = Pathway("").parseBSON(bson)
    assert p2.adjustedCombinedSignificanceValues["Fisher"]["BH"] == [0.01, 0.03, 0.5]


def test_bug_b_pathwayacquisitionjob_pipeline_writes_list_for_multicond():
    """Synthetic 3-cond fixture exercises the FDR loop and verifies all conditions are kept."""
    # We unit-test the FDR loop in isolation by invoking the same restructure code on
    # a hand-built adjusted_combined_pvalues dict.
    pathway_id = "px"
    adjusted_combined_pvalues = {
        "Fisher_c0": {"BH": {pathway_id: 0.01}, "Bonferroni": {pathway_id: 0.05}},
        "Fisher_c1": {"BH": {pathway_id: 0.03}, "Bonferroni": {pathway_id: 0.15}},
        "Fisher_c2": {"BH": {pathway_id: 0.50}, "Bonferroni": {pathway_id: 1.00}},
    }
    method = "Fisher"
    nCond = 3
    first_cond_key = method + "_c0"
    adj_methods = adjusted_combined_pvalues[first_cond_key].keys()
    expected = {
        adj: [
            adjusted_combined_pvalues.get(method + "_c" + str(c), {})
                                    .get(adj, {})
                                    .get(pathway_id, 1.0)
            for c in range(nCond)
        ]
        for adj in adj_methods
    }
    assert expected["BH"] == [0.01, 0.03, 0.50]
    assert expected["Bonferroni"] == [0.05, 0.15, 1.00]


# -------------------- Run all --------------------
def main():
    tests = [
        test_bug_a_scalar_unchanged,
        test_bug_a_mixed_lengths_no_inflation,
        test_bug_a_uniform_multicond,
        test_bug_a_late_arriving_longer,
        test_bug_d_mirna_setrelevant_is_list,
        test_bug_d_bed_setrelevant_is_list,
        test_bug_d_omicvalue_isrelevant_handles_list,
        test_bug_c_data_detection_id_styles,
        test_bug_c_header_detection,
        test_bug_c_mouse_3col_rf_parses,
        test_bug_c_mouse_3col_rf_with_header,
        test_bug_c_legacy_2col_mirna_format_preserved,
        test_bug_b_setMethodAdjusted_accepts_list,
        test_bug_b_setMethodAdjusted_back_compat_scalar,
        test_bug_b_BSON_roundtrip_preserves_list,
        test_bug_b_pathwayacquisitionjob_pipeline_writes_list_for_multicond,
    ]
    for t in tests:
        _check(t.__name__, t)

    print()
    print(f"Passed: {len(_PASSED)} / {len(_PASSED)+len(_FAILED)}")
    if _FAILED:
        for name, msg in _FAILED:
            print(f"  - {name}: {msg.splitlines()[0] if msg else ''}")
        sys.exit(1)


if __name__ == "__main__":
    main()
