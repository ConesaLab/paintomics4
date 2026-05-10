"""
Unit tests for the applyReplicateMapping servlet helper and the
PathwayAcquisitionJob.applyReplicateMappingForOmic method.

Two layers under test:
  - ``_parseDesignFile`` (servlet): reads the user-uploaded 2-column TSV.
  - ``PathwayAcquisitionJob.applyReplicateMappingForOmic`` (job): walks
    OmicValues and writes per-sample aggregations.

Both are pure-logic — no Flask, no DB. The thin servlet wrapper around them
is exercised manually / via the client.

Run from PaintomicsServer/:
    python -m src.tests.test_apply_replicate_mapping
"""

import math
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.servlets.PathwayAcquisitionServlet import _parseDesignFile  # noqa: E402
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob  # noqa: E402
from src.classes.Feature import Gene, OmicValue  # noqa: E402

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
# _parseDesignFile
# ---------------------------------------------------------------------------

def test_design_happy_path_tab():
    body = (
        "\tsample\n"
        "Ctrl_R1\tCtrl\n"
        "Ctrl_R2\tCtrl\n"
        "Treat_R1\tTreat\n"
        "Treat_R2\tTreat\n"
    )
    header = ["Ctrl_R1", "Ctrl_R2", "Treat_R1", "Treat_R2"]
    sampleHeader, mapping, groups = _parseDesignFile(body, header)
    assert sampleHeader == ["Ctrl", "Treat"], sampleHeader
    assert mapping == [0, 0, 1, 1], mapping
    assert groups == [[0, 1], [2, 3]], groups


def test_design_comma_fallback():
    """Comma-separated body works when no tabs are present."""
    body = "Ctrl_R1,Ctrl\nCtrl_R2,Ctrl\nTreat_R1,Treat\nTreat_R2,Treat\n"
    header = ["Ctrl_R1", "Ctrl_R2", "Treat_R1", "Treat_R2"]
    sampleHeader, mapping, _ = _parseDesignFile(body, header)
    assert sampleHeader == ["Ctrl", "Treat"]
    assert mapping == [0, 0, 1, 1]


def test_design_sample_order_follows_file():
    """sampleHeader order tracks first-seen in the file, not the values header."""
    body = (
        "Treat_R1\tTreat\n"
        "Ctrl_R1\tCtrl\n"
        "Treat_R2\tTreat\n"
        "Ctrl_R2\tCtrl\n"
    )
    header = ["Ctrl_R1", "Treat_R1", "Ctrl_R2", "Treat_R2"]   # different order
    sampleHeader, mapping, _ = _parseDesignFile(body, header)
    assert sampleHeader == ["Treat", "Ctrl"], sampleHeader
    # mapping[i] follows the *header* (parallel to omicHeader[1:]):
    #   header[0]=Ctrl_R1   → Ctrl  → idx 1
    #   header[1]=Treat_R1  → Treat → idx 0
    #   header[2]=Ctrl_R2   → Ctrl  → idx 1
    #   header[3]=Treat_R2  → Treat → idx 0
    assert mapping == [1, 0, 1, 0], mapping


def test_design_skips_header_row():
    """A first row whose col-1 entry isn't a column name is skipped as a header."""
    body = (
        "sample_id\tsample\n"        # treated as header
        "Ctrl_R1\tCtrl\n"
        "Ctrl_R2\tCtrl\n"
    )
    header = ["Ctrl_R1", "Ctrl_R2"]
    sampleHeader, mapping, _ = _parseDesignFile(body, header)
    assert sampleHeader == ["Ctrl"]
    assert mapping == [0, 0]


def test_design_skips_blank_and_comment_lines():
    body = (
        "# experimental design v1\n"
        "\n"
        "Ctrl_R1\tCtrl\n"
        "Ctrl_R2\tCtrl\n"
        "\n"
    )
    header = ["Ctrl_R1", "Ctrl_R2"]
    sampleHeader, mapping, _ = _parseDesignFile(body, header)
    assert sampleHeader == ["Ctrl"]
    assert mapping == [0, 0]


def test_design_missing_column_raises():
    body = "Ctrl_R1\tCtrl\nCtrl_R2\tCtrl\n"
    header = ["Ctrl_R1", "Ctrl_R2", "Treat_R1"]   # Treat_R1 not in design
    try:
        _parseDesignFile(body, header)
    except Exception as e:
        assert "Treat_R1" in str(e), str(e)
        return
    raise AssertionError("expected exception for missing column")


def test_design_empty_label_raises():
    body = "Ctrl_R1\tCtrl\nCtrl_R2\t\n"   # second row has empty label
    header = ["Ctrl_R1", "Ctrl_R2"]
    try:
        _parseDesignFile(body, header)
    except Exception as e:
        assert "Ctrl_R2" in str(e) or "empty" in str(e).lower()
        return
    raise AssertionError("expected exception for empty label")


def test_design_empty_body_raises():
    try:
        _parseDesignFile("", ["A_R1"])
    except Exception:
        return
    raise AssertionError("expected exception for empty design body")


# ---------------------------------------------------------------------------
# PathwayAcquisitionJob.applyReplicateMappingForOmic
# ---------------------------------------------------------------------------

def _make_gene_with_two_omics(geneID):
    """Two OmicValues — one for 'Gene Expression', one for 'Proteomics'."""
    g = Gene(geneID)
    ov1 = OmicValue(geneID)
    ov1.setOmicName("Gene Expression")
    ov1.setValues([1.0, 3.0, 10.0, 20.0])           # 4 replicates
    ov1.setRelevant([True, True, False, False])
    g.addOmicValue(ov1)
    ov2 = OmicValue(geneID)
    ov2.setOmicName("Proteomics")
    ov2.setValues([99.0, 99.0])
    ov2.setRelevant([False, False])
    g.addOmicValue(ov2)
    return g


def _make_job_with_two_genes():
    """Build a minimal PathwayAcquisitionJob with two genes and a 4-rep header."""
    job = PathwayAcquisitionJob("testjob", "nologin", "/tmp/")
    job.addGeneBasedInputOmic({
        "omicName": "Gene Expression",
        "omicHeader": ["#NAME", "Ctrl_R1", "Ctrl_R2", "Treat_R1", "Treat_R2"],
        "replicateDetection": {
            "status":       "complete",
            "sampleHeader": ["Ctrl", "Treat"],
            "mapping":      [0, 0, 1, 1],
            "groups":       [[0, 1], [2, 3]],
            "unmatched":    [],
        },
    })
    for gid in ("g1", "g2"):
        job.addInputGeneData(_make_gene_with_two_omics(gid))
    return job


def test_apply_auto_only_targets_named_omic():
    """Only the OmicValue whose omicName matches gets aggregation."""
    job = _make_job_with_two_genes()
    res = job.applyReplicateMappingForOmic("Gene Expression", "auto")
    assert res["status"] == "applied"
    assert res["sampleHeader"] == ["Ctrl", "Treat"]
    assert res["featuresUpdated"] == 2

    g1 = job.getInputGenesData()["g1"]
    ge = next(ov for ov in g1.getOmicsValues() if ov.getOmicName() == "Gene Expression")
    assert ge.getSampleValues() == [2.0, 15.0]
    assert ge.getSampleRelevant() == [True, False]
    # Proteomics OmicValue is left alone.
    pr = next(ov for ov in g1.getOmicsValues() if ov.getOmicName() == "Proteomics")
    assert pr.getSampleValues() is None
    assert pr.getSampleRelevant() is None


def test_apply_writes_back_inputomic_metadata():
    """sampleHeader / replicateMapping / replicateSource land on the inputOmic dict."""
    job = _make_job_with_two_genes()
    job.applyReplicateMappingForOmic("Gene Expression", "auto")
    inputOmic = job.getGeneBasedInputOmics()[0]
    assert inputOmic["sampleHeader"]     == ["Ctrl", "Treat"]
    assert inputOmic["replicateMapping"] == [0, 0, 1, 1]
    assert inputOmic["replicateSource"]  == "auto"


def test_apply_off_resets_to_none():
    """mode='off' wipes any previous aggregation."""
    job = _make_job_with_two_genes()
    job.applyReplicateMappingForOmic("Gene Expression", "auto")
    res = job.applyReplicateMappingForOmic("Gene Expression", "off")
    assert res["status"] == "cleared"
    g1 = job.getInputGenesData()["g1"]
    ge = next(ov for ov in g1.getOmicsValues() if ov.getOmicName() == "Gene Expression")
    assert ge.getSampleValues() is None
    assert ge.getSampleRelevant() is None
    inputOmic = job.getGeneBasedInputOmics()[0]
    assert inputOmic["sampleHeader"]     == []
    assert inputOmic["replicateMapping"] == []
    assert inputOmic["replicateSource"]  == "off"


def test_apply_unknown_omic_raises():
    """Asking for an omic that isn't on the job is a hard error."""
    job = _make_job_with_two_genes()
    try:
        job.applyReplicateMappingForOmic("DNase-seq", "auto")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown omic")


def test_apply_auto_requires_complete_detection():
    """If detection.status != complete, auto-apply refuses."""
    job = _make_job_with_two_genes()
    job.getGeneBasedInputOmics()[0]["replicateDetection"] = {"status": "partial",
        "sampleHeader": [], "mapping": [], "groups": [], "unmatched": []}
    try:
        job.applyReplicateMappingForOmic("Gene Expression", "auto")
    except ValueError:
        return
    raise AssertionError("expected ValueError for partial detection in auto mode")


def test_apply_manual_requires_explicit_mapping():
    """mode='manual' without sampleHeader/mapping/groups is a programmer error."""
    job = _make_job_with_two_genes()
    try:
        job.applyReplicateMappingForOmic("Gene Expression", "manual")
    except ValueError:
        return
    raise AssertionError("expected ValueError for manual without mapping args")


def test_apply_manual_round_trip_via_design_parser():
    """End-to-end: parseDesignFile → applyReplicateMappingForOmic(manual)."""
    job = _make_job_with_two_genes()
    omicHeader = job.getGeneBasedInputOmics()[0]["omicHeader"]
    sampleHeader, mapping, groups = _parseDesignFile(
        "Ctrl_R1\tCtrl\nCtrl_R2\tCtrl\nTreat_R1\tTreat\nTreat_R2\tTreat\n",
        omicHeader[1:],
    )
    res = job.applyReplicateMappingForOmic(
        "Gene Expression", "manual",
        sampleHeader=sampleHeader, mapping=mapping, groups=groups,
    )
    assert res["status"] == "applied"
    assert res["sampleHeader"] == ["Ctrl", "Treat"]
    assert job.getGeneBasedInputOmics()[0]["replicateSource"] == "manual"


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

print("\n── applyReplicateMapping helpers ────────────────────────────")
print("  _parseDesignFile")
_check("Tab-separated happy path",                     test_design_happy_path_tab)
_check("Comma fallback when no tabs",                  test_design_comma_fallback)
_check("Sample order follows file row order",          test_design_sample_order_follows_file)
_check("Skips header row",                             test_design_skips_header_row)
_check("Skips blank and # comment lines",              test_design_skips_blank_and_comment_lines)
_check("Missing column raises with column name",       test_design_missing_column_raises)
_check("Empty label raises",                           test_design_empty_label_raises)
_check("Empty body raises",                            test_design_empty_body_raises)

print("  PathwayAcquisitionJob.applyReplicateMappingForOmic")
_check("auto mode aggregates only the named omic",     test_apply_auto_only_targets_named_omic)
_check("auto mode writes inputOmic metadata",          test_apply_writes_back_inputomic_metadata)
_check("off mode resets sampleValues to None",         test_apply_off_resets_to_none)
_check("unknown omic raises ValueError",               test_apply_unknown_omic_raises)
_check("auto mode refuses non-complete detection",     test_apply_auto_requires_complete_detection)
_check("manual mode without mapping raises",           test_apply_manual_requires_explicit_mapping)
_check("manual end-to-end via parseDesignFile",        test_apply_manual_round_trip_via_design_parser)

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
