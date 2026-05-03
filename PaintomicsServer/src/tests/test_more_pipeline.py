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
    assert "userID" in src_code, "remove() does not filter by userID — cross-user deletion is possible"

_check("MOREJobDAO has remove() method with userID filter", test_morejobdao_has_remove)


def test_servlet_uses_handle_exception():
    """STEP2 must use the shared handleException + cleanDirectories pattern, not a bare logging.exception,
    so the user gets a structured error response and stale output dirs are cleaned up."""
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    assert "handleException" in src_code, "STEP2 does not use shared handleException — error responses are inconsistent"
    assert "cleanDirectories" in src_code, "STEP2 does not call cleanDirectories on error — stale output left behind"

_check("MOREServlet STEP2 uses handleException + cleanDirectories", test_servlet_uses_handle_exception)


def test_servlet_returns_fourth_output_file():
    """yellow stars require a fourthOutputFileName_{i} entry pointing at MORE_relevant_pairs_*.tab."""
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    assert "fourthOutputFileName_" in src_code, "Response is missing fourthOutputFileName_{i} — yellow stars won't appear"
    assert "rel_pairs_name" in src_code or "MORE_relevant_pairs_" in src_code, \
        "Servlet does not surface the relevant_pairs file as fourth output"

_check("MOREServlet returns fourthOutputFileName_{i} for yellow stars", test_servlet_returns_fourth_output_file)


def test_servlet_expands_user_tf_to_pairs():
    """When the user supplies a relevant TF list, STEP2 must expand bare TF IDs into
    GENE:::TF pairs by scanning the values file — otherwise parseGeneBasedFiles never
    matches and red stars stay invisible."""
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    assert ":::" in src_code, "STEP2 does not build GENE:::REGULATOR pairs from user file"
    assert "split(':::', 1)" in src_code, "STEP2 does not split values file rows on ::: to extract TF column"

_check("MOREServlet expands user-relevant TFs into GENE:::TF pairs", test_servlet_expands_user_tf_to_pairs)


def test_servlet_writes_empty_relevant_reg_without_user_file():
    """Contract mirrors miRNA2Genes: red stars are user-driven, not algorithm-driven.
    If the user uploads no "Significant regulators" file for an omic, MORE_relevant_reg_*.tab
    must be created EMPTY — so parseGeneBasedFiles produces no red stars and pathway
    enrichment for that omic correctly yields p-value = 1."""
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    # The else branch (no user file) must explicitly create an empty rel_reg file.
    assert "open(rel_reg_path, 'w').close()" in src_code, \
        "STEP2 does not blank rel_reg_path when no user relevant file is supplied — spurious red stars"
    # And it must do so in an else branch, not only when R failed to produce one.
    assert "else:" in src_code.split("user_rel_file", 1)[1], \
        "STEP2 missing else-branch for the no-user-file case — would fall through and leak R-produced pairs"


_check("MOREServlet writes empty relevant_reg when user provides no file", test_servlet_writes_empty_relevant_reg_without_user_file)


def test_servlet_returns_compressed_file_name():
    """Match miRNA2Genes contract: response must include compressedFileName so the
    JobController 'Download files' link works."""
    import src.servlets.MOREServlet as ms
    src_code = inspect.getsource(ms.fromMOREtoGenes_STEP2)
    assert "compressedFileName" in src_code, "Response missing compressedFileName — Download files link will be broken"
    assert "make_archive" in src_code, "STEP2 does not zip the outputs into a downloadable bundle"

_check("MOREServlet returns compressedFileName for download bundle", test_servlet_returns_compressed_file_name)


def test_r_script_uses_full_assoc_for_values_file():
    """Match miRNA2Genes contract: the values file (and associations file) must be built
    from the FULL input association set, filtered only by regulator presence in the
    expression data — NOT from MORE's significance-filtered omic_df. Otherwise non-
    significant TFs vanish from the values file and PA Step 1 cannot map them."""
    with open(R_SCRIPT) as f:
        r_src = f.read()
    # The values file loop must iterate over full_pairs (built from associations[[name]]),
    # not over omic_df / unique_pairs (which are significance-filtered).
    assert "full_pairs" in r_src, "R script does not build a full_pairs set from the input association"
    assert "associations[[name]]" in r_src, "R script does not pull associations[[name]] for the full pair set"
    # Sanity: omic_df should still drive the relevant_pairs (yellow stars) file.
    assert "rel_pairs_file" in r_src and "omic_df" in r_src, \
        "R script must keep omic_df as the source for MORE_relevant_pairs (yellow stars)"

_check("runMORE.R writes values + assoc from full input pairs (not significance-filtered)", test_r_script_uses_full_assoc_for_values_file)


def test_frontend_fourth_file_field():
    """itemsContainerAlt must include the fourthFileFieldAlt hidden field (relevant_associations_filelocation)
    so PA Step 1 receives the fourth output and can apply yellow stars."""
    pa_step1 = os.path.join(REPO_ROOT, "PaintomicsClient", "public_html", "app",
                            "view", "PathwayAcquisitionViews", "PA_Step1Views.js")
    if not os.path.isfile(pa_step1):
        raise AssertionError(f"PA_Step1Views.js not found at {pa_step1}")
    with open(pa_step1) as f:
        js = f.read()
    assert 'itemId: "fourthFileFieldAlt"' in js, \
        "MORESubmittingPanel itemsContainerAlt missing fourthFileFieldAlt — yellow stars cannot be wired up"
    assert "_relevant_associations_filelocation_0" in js, \
        "Hidden field _relevant_associations_filelocation_0 not declared in MORESubmittingPanel"
    assert "values.fourthFile" in js, \
        "MORESubmittingPanel.setContent does not handle values.fourthFile from the response"

_check("PA_Step1Views wires up fourthFile (yellow stars)", test_frontend_fourth_file_field)


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

            # R writes 3 files per omic: values, associations, and relevant_pairs (yellow stars).
            # MORE_relevant_reg_*.tab (red stars) is intentionally NOT written by R — it's the
            # MOREServlet's responsibility, populated only when the user uploads a relevant file.
            expected = [
                "MORE_output_Transcription_Factors_test.tab",
                "MORE_relevant_assoc_Transcription_Factors_test.tab",
                "MORE_relevant_pairs_Transcription_Factors_test.tab",
            ]
            for fname in expected:
                fpath = os.path.join(out_dir, fname)
                assert os.path.isfile(fpath), f"Expected output file not found: {fname}"

            unwritten = "MORE_relevant_reg_Transcription_Factors_test.tab"
            assert not os.path.isfile(os.path.join(out_dir, unwritten)), \
                f"R script must not write {unwritten} — it would silently fabricate red stars from MORE's algorithmic output"

            # Values file must have at least a header line
            val_file = os.path.join(out_dir, "MORE_output_Transcription_Factors_test.tab")
            with open(val_file) as f:
                lines = [l for l in f if l.strip()]
            assert len(lines) >= 1, "Output values file is completely empty"

            # If MORE found any significant pair, the relevant_pairs file must contain GENE:::REGULATOR rows
            # (and therefore be in 1-column GENE:::REGULATOR format, not bare regulator IDs).
            rel_pairs_file = os.path.join(out_dir, "MORE_relevant_pairs_Transcription_Factors_test.tab")
            with open(rel_pairs_file) as f:
                rel_pairs_lines = [l.strip() for l in f if l.strip()]

            # The values file must contain at least as many data rows as the relevant_pairs file.
            # The yellow-star file is significance-filtered; the values file is the full input set
            # and must therefore be a superset (often strictly larger).
            val_data_lines = [l for l in lines if not l.startswith('#')]
            assert len(val_data_lines) >= len(rel_pairs_lines), (
                f"Values file ({len(val_data_lines)} pairs) must be a superset of relevant_pairs "
                f"({len(rel_pairs_lines)} significant pairs) — significance-filtered values file "
                f"would drop non-significant TFs and break mapping parity with miRNA2Genes."
            )

            # The associations file must mirror the values file count (same input pair set).
            assoc_file = os.path.join(out_dir, "MORE_relevant_assoc_Transcription_Factors_test.tab")
            with open(assoc_file) as f:
                assoc_data_lines = [l.strip() for l in f if l.strip()]
            assert len(assoc_data_lines) == len(val_data_lines), (
                f"Associations file ({len(assoc_data_lines)}) and values file ({len(val_data_lines)}) "
                f"must contain the same number of pairs — both are built from the full input association."
            )
            for line in rel_pairs_lines:
                assert ":::" in line, \
                    f"MORE_relevant_pairs file has rows missing ':::' separator (got {line!r}) — yellow-star lookup will fail"

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
