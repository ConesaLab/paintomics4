"""
Integration check for MORE -> PA Step 1 propagation with N regulatory omics.

Reproduces the form payload that MORESubmittingPanel produces when the user
adds two regulatory omics:
  - itemsContainerAlt holds hidden static fields for index 0
  - the dynamic block in setContent() adds matching hidden fields for index 1+

We feed that payload to JobInformationManager.saveFiles and assert the
PathwayAcquisitionJob ends up with one geneBasedInputOmic *per* regulatory
omic (not just the first one).

Run:
    python -m src.tests.test_more_multiomic_propagation
"""
import os
import sys
import shutil
import tempfile
import traceback
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Werkzeug is a Flask dependency, available wherever the server runs.
from werkzeug.datastructures import FileStorage, MultiDict, ImmutableMultiDict

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.common.JobInformationManager import JobInformationManager


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


def _empty_file(name):
    """A FileStorage that mimics an empty hidden filefield in the form."""
    return FileStorage(stream=BytesIO(b""), filename="", name=name)


def _build_form(prefix, omics):
    """
    Build (uploadedFiles, formFields) the way MORESubmittingPanel posts when
    each regulatory omic has been pre-processed through MORE (origin=mydata).

    omics: list of dicts with keys: name, mainFile, secondFile, thirdFile, fourthFile
    """
    files = MultiDict()
    fields = MultiDict()

    for i, omic in enumerate(omics):
        # Empty hidden filefields — register the keys so saveFiles iterates over them.
        files.add(f"{prefix}_file_{i}",                       _empty_file(f"{prefix}_file_{i}"))
        files.add(f"{prefix}_relevant_file_{i}",              _empty_file(f"{prefix}_relevant_file_{i}"))
        files.add(f"{prefix}_associations_file_{i}",          _empty_file(f"{prefix}_associations_file_{i}"))
        files.add(f"{prefix}_relevant_associations_file_{i}", _empty_file(f"{prefix}_relevant_associations_file_{i}"))

        # Origins (everything is "mydata" — files were saved during MORE STEP1)
        fields.add(f"{prefix}_origin_{i}",                       "mydata")
        fields.add(f"{prefix}_relevant_{i}_origin",              "mydata")
        fields.add(f"{prefix}_associations_{i}_origin",          "mydata")
        fields.add(f"{prefix}_relevant_associations_{i}_origin", "mydata")

        # File types (cosmetic)
        fields.add(f"{prefix}_file_type_{i}",                       "Gene Expression file")
        fields.add(f"{prefix}_relevant_file_type_{i}",              "Relevant gene list")
        fields.add(f"{prefix}_associations_file_type_{i}",          "Associations file")
        fields.add(f"{prefix}_relevant_associations_file_type_{i}", "Relevant associations file")

        # Omic name + filelocations from MORE response
        fields.add(f"{prefix}_omic_name_{i}",                        omic["name"])
        fields.add(f"{prefix}_filelocation_{i}",                     omic["mainFile"])
        fields.add(f"{prefix}_relevant_filelocation_{i}",            omic["secondFile"])
        fields.add(f"{prefix}_associations_filelocation_{i}",        omic["thirdFile"])
        fields.add(f"{prefix}_relevant_associations_filelocation_{i}", omic["fourthFile"])

        fields.add(f"{prefix}_match_type_{i}",  "gene")
        fields.add(f"{prefix}_enrichment_{i}",  "genes")
        fields.add(f"{prefix}_config_args_{i}", "MORE Analysis (PLS1)")

    return ImmutableMultiDict(files), ImmutableMultiDict(fields)


# ---------------------------------------------------------------
print("\n── MORE multi-omic propagation through saveFiles ─────────────")

def test_two_omics_both_register():
    tmp_dir = tempfile.mkdtemp(prefix="more_propagation_")
    try:
        prefix = "omic1"
        omics = [
            {"name": "Transcription Factors",
             "mainFile":   "MORE_output_Transcription_Factors_t.tab",
             "secondFile": "MORE_relevant_reg_Transcription_Factors_t.tab",
             "thirdFile":  "MORE_relevant_assoc_Transcription_Factors_t.tab",
             "fourthFile": "MORE_relevant_pairs_Transcription_Factors_t.tab"},
            {"name": "miRNA",
             "mainFile":   "MORE_output_miRNA_t.tab",
             "secondFile": "MORE_relevant_reg_miRNA_t.tab",
             "thirdFile":  "MORE_relevant_assoc_miRNA_t.tab",
             "fourthFile": "MORE_relevant_pairs_miRNA_t.tab"},
        ]
        uploaded, form = _build_form(prefix, omics)

        # PathwayAcquisitionJob constructor signature: (jobID, userID, CLIENT_TMP_DIR)
        job = PathwayAcquisitionJob("propagation_test_job", "_test_user_", tmp_dir + "/")
        # saveFiles needs the user's inputData dir to exist for any 'client' branch;
        # the 'mydata' branch we use here only reads form fields, so we don't have
        # to actually create the directory. But create it anyway to match runtime.
        os.makedirs(os.path.join(tmp_dir, "_test_user_", "inputData"), exist_ok=True)

        JobInformationManager().saveFiles(uploaded, form, "_test_user_", job, tmp_dir + "/")

        gene_omics = job.getGeneBasedInputOmics()
        names = [o["omicName"] for o in gene_omics]

        assert len(gene_omics) == 2, (
            f"Expected 2 gene-based input omics after saveFiles, got {len(gene_omics)}: {names}"
        )
        assert "Transcription Factors" in names, f"TF omic missing from {names}"
        assert "miRNA" in names, f"miRNA omic missing from {names}"

        # Each omic must carry its own four files
        by_name = {o["omicName"]: o for o in gene_omics}
        for spec in omics:
            o = by_name[spec["name"]]
            assert o["inputDataFile"]            == spec["mainFile"],   f"{spec['name']}: wrong inputDataFile"
            assert o["relevantFeaturesFile"]     == spec["secondFile"], f"{spec['name']}: wrong relevantFeaturesFile"
            assert o["associationsFile"]         == spec["thirdFile"],  f"{spec['name']}: wrong associationsFile"
            assert o["relevantAssociationsFile"] == spec["fourthFile"], f"{spec['name']}: wrong relevantAssociationsFile"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


_check("2 regulatory omics in MORE alt-block → both registered as gene-based input omics", test_two_omics_both_register)


def test_three_omics_all_register():
    tmp_dir = tempfile.mkdtemp(prefix="more_propagation_3_")
    try:
        prefix = "omic1"
        omics = [
            {"name": f"Reg{n}",
             "mainFile":   f"MORE_output_Reg{n}_t.tab",
             "secondFile": f"MORE_relevant_reg_Reg{n}_t.tab",
             "thirdFile":  f"MORE_relevant_assoc_Reg{n}_t.tab",
             "fourthFile": f"MORE_relevant_pairs_Reg{n}_t.tab"}
            for n in range(1, 4)
        ]
        uploaded, form = _build_form(prefix, omics)
        job = PathwayAcquisitionJob("propagation_test_3", "_test_user_", tmp_dir + "/")
        os.makedirs(os.path.join(tmp_dir, "_test_user_", "inputData"), exist_ok=True)
        JobInformationManager().saveFiles(uploaded, form, "_test_user_", job, tmp_dir + "/")
        gene_omics = job.getGeneBasedInputOmics()
        names = sorted([o["omicName"] for o in gene_omics])
        assert names == ["Reg1", "Reg2", "Reg3"], f"Expected all three omics, got {names}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


_check("3 regulatory omics in MORE alt-block → all three register", test_three_omics_all_register)


def test_undefined_prefix_fallback_does_not_collide_with_real_omic():
    """Regression guard for the original JS bug: if the dynamic block ever again
    reverts to `this.namePrefix` (which resolves to undefined inside the inline
    setContent method), the second omic's field names start with 'undefined_'.
    Even though saveFiles still registers them as a separate omic, the names
    collide if there happen to be TWO MORE panels on the page (each panel's
    dynamic block would emit "undefined_file_1" and clobber the other's data).
    This test pins the contract: saveFiles must not silently merge or drop omics
    when given mixed prefixes — and the JS-side fix (use `me.namePrefix`)
    guarantees no two panels emit the same `undefined_*` names.
    """
    tmp_dir = tempfile.mkdtemp(prefix="more_propagation_mixed_")
    try:
        # Simulate the broken state: panel-prefix `omic1` for index 0 (built by
        # initComponent where `this` is correct) + bare `undefined` for index 1
        # (the dynamic block under the JS scoping bug).
        files = MultiDict()
        fields = MultiDict()

        for prefix, idx, omic in [
            ("omic1",     0, {"name": "TF",    "main": "out_TF.tab",    "second": "rel_TF.tab",    "third": "assoc_TF.tab",    "fourth": "pairs_TF.tab"}),
            ("undefined", 1, {"name": "miRNA", "main": "out_miRNA.tab", "second": "rel_miRNA.tab", "third": "assoc_miRNA.tab", "fourth": "pairs_miRNA.tab"}),
        ]:
            files.add(f"{prefix}_file_{idx}",                       _empty_file(f"{prefix}_file_{idx}"))
            files.add(f"{prefix}_relevant_file_{idx}",              _empty_file(f"{prefix}_relevant_file_{idx}"))
            files.add(f"{prefix}_associations_file_{idx}",          _empty_file(f"{prefix}_associations_file_{idx}"))
            files.add(f"{prefix}_relevant_associations_file_{idx}", _empty_file(f"{prefix}_relevant_associations_file_{idx}"))
            fields.add(f"{prefix}_origin_{idx}",                       "mydata")
            fields.add(f"{prefix}_relevant_{idx}_origin",              "mydata")
            fields.add(f"{prefix}_associations_{idx}_origin",          "mydata")
            fields.add(f"{prefix}_relevant_associations_{idx}_origin", "mydata")
            fields.add(f"{prefix}_file_type_{idx}",                       "Gene Expression file")
            fields.add(f"{prefix}_relevant_file_type_{idx}",              "Relevant gene list")
            fields.add(f"{prefix}_associations_file_type_{idx}",          "Associations file")
            fields.add(f"{prefix}_relevant_associations_file_type_{idx}", "Relevant associations file")
            fields.add(f"{prefix}_omic_name_{idx}",                        omic["name"])
            fields.add(f"{prefix}_filelocation_{idx}",                     omic["main"])
            fields.add(f"{prefix}_relevant_filelocation_{idx}",            omic["second"])
            fields.add(f"{prefix}_associations_filelocation_{idx}",        omic["third"])
            fields.add(f"{prefix}_relevant_associations_filelocation_{idx}", omic["fourth"])
            fields.add(f"{prefix}_match_type_{idx}",  "gene")
            fields.add(f"{prefix}_enrichment_{idx}",  "genes")
            fields.add(f"{prefix}_config_args_{idx}", "MORE Analysis (PLS1)")

        job = PathwayAcquisitionJob("propagation_mixed", "_test_user_", tmp_dir + "/")
        os.makedirs(os.path.join(tmp_dir, "_test_user_", "inputData"), exist_ok=True)
        JobInformationManager().saveFiles(
            ImmutableMultiDict(files), ImmutableMultiDict(fields),
            "_test_user_", job, tmp_dir + "/"
        )
        names = sorted([o["omicName"] for o in job.getGeneBasedInputOmics()])
        # The legacy bug doesn't drop the second omic — it merely names it weirdly.
        # This test pins that observation, AND documents the failure mode that the
        # JS fix prevents (two MORE panels each producing "undefined_*" would alias).
        assert names == ["TF", "miRNA"], (
            f"saveFiles unexpectedly dropped/merged omics under mixed prefixes: {names}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


_check("Mixed-prefix payload still registers both omics (guards against legacy JS scoping bug)",
       test_undefined_prefix_fallback_does_not_collide_with_real_omic)


# ---------------------------------------------------------------
print(f"\n  Results: {len(_PASS)} passed, {len(_FAIL)} failed")
if _FAIL:
    for name, msg in _FAIL:
        print(f"  ✗ {name}: {msg.splitlines()[0] if msg else ''}")
sys.exit(1 if _FAIL else 0)
