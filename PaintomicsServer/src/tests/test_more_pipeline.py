"""
Offline verification suite for the MORE pipeline implementation.

Covers everything that can be checked without a running Flask server:
  - Tier 1: pure Python (no DB, no R)
  - Tier 2: R script end-to-end with synthetic data (requires Rscript + MORE package)
  - Tier 3: MongoDB DAO round-trip (skipped gracefully if DB is not reachable)

Run from the PaintomicsServer/ directory:

    python -m src.tests.test_more_pipeline

Exit code 0 = all non-skipped tests passed.
"""

import os
import sys
import subprocess
import inspect
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_PASS = []
_FAIL = []
_SKIP = []

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
FAST_DATA  = os.path.join(REPO_ROOT, "more_tests", "fast_test_data")
R_SCRIPT   = os.path.join(REPO_ROOT, "PaintomicsServer", "src", "common", "bioscripts", "runMORE.R")


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


def _skip(name, reason):
    _SKIP.append((name, reason))
    print(f"  SKIP  {name} ({reason})")


# ─────────────────────────────────────────────────────────────
# TIER 1 — Pure Python, no external dependencies
# ─────────────────────────────────────────────────────────────

print("\n── Tier 1: Python structure checks ──────────────────────────")

def test_morejob_attribute():
    from src.classes.JobInstances.MOREJob import MOREJob
    j = MOREJob("job1", "user1", "/tmp/")
    assert hasattr(j, "targetExpressionFile"), "targetExpressionFile not declared in __init__"
    j.targetExpressionFile = "somefile.txt"
    bson = j.toBSON(recursive=False)
    assert "targetExpressionFile" in bson, "targetExpressionFile not serialised by toBSON"

_check("MOREJob.targetExpressionFile declared and serialises", test_morejob_attribute)


def test_morejob_add_regulatory_omic():
    from src.classes.JobInstances.MOREJob import MOREJob
    j = MOREJob("job2", "user1", "/tmp/")
    j.addRegulatoryOmic("TF", "tf.txt", "Regulatory Data", "assoc.txt")
    assert len(j.regulatoryOmics) == 1
    assert j.regulatoryOmics[0]["name"] == "TF"
    assert j.regulatoryOmics[0]["associations"] == "assoc.txt"

_check("MOREJob.addRegulatoryOmic stores omic correctly", test_morejob_add_regulatory_omic)


def test_jobdao_remove_dispatch():
    import src.common.DAO.JobDAO as jd
    src_code = inspect.getsource(jd.JobDAO.remove)
    assert "MOREJob" in src_code, "MOREJob branch missing from JobDAO.remove"

_check("JobDAO.remove dispatches MOREJob", test_jobdao_remove_dispatch)


def test_jobinformationmanager_dispatch():
    import src.common.JobInformationManager as jim
    src_code = inspect.getsource(jim.JobInformationManager.storeJobInstance)
    assert "MOREJob" in src_code, "MOREJob branch missing from storeJobInstance"

_check("JobInformationManager.storeJobInstance dispatches MOREJob", test_jobinformationmanager_dispatch)


def test_servlet_uses_check_output():
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    assert "check_output" in src_code, "subprocess.check_output not used — R errors won't be captured"
    assert "check_call" not in src_code, "subprocess.check_call still present"

_check("MOREServlet uses check_output (not check_call)", test_servlet_uses_check_output)


def test_servlet_uses_job_information_manager():
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    assert "JobInformationManager" in src_code, "Servlet bypasses JobInformationManager — jobs won't be listable"
    assert "MOREJobDAO" not in src_code, "Servlet still calls MOREJobDAO directly"

_check("MOREServlet stores job via JobInformationManager", test_servlet_uses_job_information_manager)


def test_servlet_uses_client_tmp_dir_for_r_script():
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    assert "CLIENT_TMP_DIR" in src_code, "R script path should be derived from CLIENT_TMP_DIR, not __file__"

_check("MOREServlet derives R script path from CLIENT_TMP_DIR", test_servlet_uses_client_tmp_dir_for_r_script)


def test_servlet_returns_basenames():
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    assert 'results_summary[name]["outputFile"]' in src_code, "Response should use basename, not full output_dir path"
    assert 'os.path.join(output_dir, results_summary' not in src_code, "Response must not return absolute output_dir paths — saveFiles/parseGeneBasedFiles will double-prefix them"

_check("MOREServlet response uses basenames (not absolute paths)", test_servlet_returns_basenames)


def test_morejobdao_has_remove():
    from src.common.DAO.MOREJobDAO import MOREJobDAO
    assert hasattr(MOREJobDAO, "remove"), "MOREJobDAO is missing remove() method"
    src_code = inspect.getsource(MOREJobDAO.remove)
    assert "jobID" in src_code, "remove() does not filter by jobID"

_check("MOREJobDAO has remove() method", test_morejobdao_has_remove)


def test_r_script_name_sanitisation():
    with open(R_SCRIPT) as f:
        r_src = f.read()
    assert 'gsub(" ", "_"' in r_src, "R script does not sanitise omic names with gsub — filename mismatch with Python"

_check("runMORE.R sanitises omic names to match Python safe_name", test_r_script_name_sanitisation)


def test_frontend_origin_field_names():
    """saveFiles builds origin keys as `{prefix}_relevant_{i}_origin`, not `{prefix}_relevant_origin_{i}`.
    The MORESubmittingPanel hidden fields must follow that convention or saveFiles gets None and crashes."""
    pa_step1 = os.path.join(REPO_ROOT, "PaintomicsClient", "public_html", "app",
                            "view", "PathwayAcquisitionViews", "PA_Step1Views.js")
    if not os.path.isfile(pa_step1):
        raise AssertionError(f"PA_Step1Views.js not found at {pa_step1}")
    with open(pa_step1) as f:
        js = f.read()
    assert "_relevant_origin_0'" not in js and "_relevant_origin_' + i" not in js, \
        "Found _relevant_origin_0 — should be _relevant_0_origin (saveFiles key order)"
    assert "_associations_origin_0'" not in js and "_associations_origin_' + i" not in js, \
        "Found _associations_origin_0 — should be _associations_0_origin (saveFiles key order)"

_check("PA_Step1Views origin field names match saveFiles key convention", test_frontend_origin_field_names)


# ─────────────────────────────────────────────────────────────
# TIER 2 — R script end-to-end
# ─────────────────────────────────────────────────────────────

print("\n── Tier 2: R script end-to-end ──────────────────────────────")

def _rscript_available():
    try:
        subprocess.check_output(["Rscript", "--version"], stderr=subprocess.STDOUT)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

def _more_package_available():
    try:
        subprocess.check_output(
            ["Rscript", "-e", "library(MORE); cat('OK')"],
            stderr=subprocess.STDOUT
        )
        return True
    except subprocess.CalledProcessError:
        return False

def _fast_data_available():
    needed = ["mini_target.txt", "mini_tf.txt", "Condition.txt", "Associations_logFC.txt"]
    return all(os.path.isfile(os.path.join(FAST_DATA, f)) for f in needed)


if not _rscript_available():
    _skip("R script smoke test", "Rscript not found")
elif not _more_package_available():
    _skip("R script smoke test", "MORE R package not installed")
elif not _fast_data_available():
    _skip("R script smoke test", f"synthetic data missing from {FAST_DATA}")
else:
    def test_r_script_runs():
        with tempfile.TemporaryDirectory() as out_dir:
            cmd = [
                "Rscript", R_SCRIPT,
                "--target_file",    os.path.join(FAST_DATA, "mini_target.txt"),
                "--condition_file", os.path.join(FAST_DATA, "Condition.txt"),
                "--omic_names",     "Transcription Factors",
                "--data_files",     os.path.join(FAST_DATA, "mini_tf.txt"),
                "--assoc_files",    os.path.join(FAST_DATA, "Associations_logFC.txt"),
                "--method",         "PLS1",
                "--alpha",          "0.05",
                "--vip",            "0.8",
                "--filter_r2",      "0.0",
                "--output_dir",     out_dir,
                "--date_seed",      "test",
            ]
            try:
                out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                raise AssertionError(f"Rscript exited non-zero:\n{e.output.decode(errors='replace')}")

            # Verify the three expected output files are written with underscored names
            expected = [
                "MORE_output_Transcription_Factors_test.tab",
                "MORE_relevant_assoc_Transcription_Factors_test.tab",
                "MORE_relevant_reg_Transcription_Factors_test.tab",
            ]
            for fname in expected:
                fpath = os.path.join(out_dir, fname)
                assert os.path.isfile(fpath), f"Expected output file not found: {fname}"

            # Values file must have at least a header line
            val_file = os.path.join(out_dir, "MORE_output_Transcription_Factors_test.tab")
            with open(val_file) as f:
                lines = [l for l in f if l.strip()]
            assert len(lines) >= 1, "Output values file is completely empty"

    _check("runMORE.R completes and writes all output files", test_r_script_runs)


# ─────────────────────────────────────────────────────────────
# TIER 3 — MongoDB DAO round-trip (skipped if DB unreachable)
# ─────────────────────────────────────────────────────────────

print("\n── Tier 3: MongoDB DAO round-trip ───────────────────────────")

def _mongo_available():
    try:
        from pymongo import MongoClient
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        c = MongoClient(MONGODB_HOST, MONGODB_PORT, serverSelectionTimeoutMS=1500)
        c.server_info()
        return True
    except Exception:
        return False

if not _mongo_available():
    _skip("MOREJobDAO insert/remove", "MongoDB not reachable")
else:
    def test_dao_insert_remove():
        from src.classes.JobInstances.MOREJob import MOREJob
        from src.common.DAO.MOREJobDAO import MOREJobDAO
        from src.conf.serverconf import CLIENT_TMP_DIR

        job = MOREJob("_more_test_tmp_", "_test_user_", CLIENT_TMP_DIR)
        job.method = "PLS1"
        job.addRegulatoryOmic("TF", "fake.txt", "Regulatory Data")

        dao = MOREJobDAO()
        dao.insert(job)

        found = dao.findByID("_more_test_tmp_")
        assert found is not None, "findByID returned None after insert"
        assert found.getJobID() == "_more_test_tmp_"
        assert found.method == "PLS1"

        dao.remove("_more_test_tmp_")
        gone = dao.findByID("_more_test_tmp_")
        assert gone is None, "Document still present after remove"

        dao.closeConnection()

    _check("MOREJobDAO insert → findByID → remove round-trip", test_dao_insert_remove)


# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────

print(f"\n{'─'*55}")
print(f"  Results: {len(_PASS)} passed, {len(_FAIL)} failed, {len(_SKIP)} skipped")
if _FAIL:
    print("\nFailed tests:")
    for name, msg in _FAIL:
        print(f"  ✗ {name}")
        print(f"    {msg.splitlines()[0]}")
if _SKIP:
    print("\nSkipped tests:")
    for name, reason in _SKIP:
        print(f"  - {name}: {reason}")

sys.exit(1 if _FAIL else 0)
