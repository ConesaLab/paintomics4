#!/usr/bin/env python3
"""Lightweight harness: build the example PaintomicsAcquisition job, run the
backend pipeline up to per-pathway p-value computation, and report the count
of significant pathways using the same rules as the frontend in
PA_Step3Views.js:219-241/370-395.

Designed for the autoresearch loop: zero AI-agent dependencies, JSON output
for easy diffing.

Run from `PaintomicsServer/`:

    python -m src.tests.count_significant_pathways

Optional flags:
    --databases KEGG [Reactome ...]
    --omics "Gene expression,Metabolomics"   # subset; default = all 6
    --threshold 0.05
    --output .autoresearch/last_run.json
"""
import argparse
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.conf.serverconf import CLIENT_TMP_DIR


EXAMPLE_OMICS = {
    "Gene expression": "genes",
    "Metabolomics": "features",
    "Proteomics": "features",
    "miRNA-seq": "genes",
    "DNase-seq": "genes",
    "Transcription factor": "genes",
}


def build_job(databases, selected_omics, tmp_dir):
    job = PathwayAcquisitionJob(
        jobID="autoresearch_" + uuid.uuid4().hex[:10],
        userID="autoresearch",
        CLIENT_TMP_DIR=tmp_dir,
    )
    job.initializeDirectories()
    job.setOrganism("mmu")
    job.setDatabases(databases)
    job.setName("autoresearch count harness")

    example_dir = "src/examplefiles/"
    for omic_name in selected_omics:
        if omic_name not in EXAMPLE_OMICS:
            raise ValueError(f"Unknown omic: {omic_name}")
        enrichment = EXAMPLE_OMICS[omic_name]
        slug = omic_name.replace(" ", "_").replace("-seq", "").lower()
        payload = {
            "omicName": omic_name,
            "inputDataFile": example_dir + slug + "_values.tab",
            "relevantFeaturesFile": example_dir + slug + "_relevant.tab",
            "isExample": True,
            "enrichment": enrichment,
        }
        if omic_name == "Metabolomics":
            job.addCompoundBasedInputOmic(payload)
        else:
            job.addGeneBasedInputOmic(payload)
    return job


def count_significant(job, threshold=0.05):
    """Mirror frontend rules from PA_Step3Views.js."""
    matched = job.getMatchedPathways() or {}
    total = len(matched)
    n_omics = len(job.getGeneBasedInputOmics()) + len(job.getCompoundBasedInputOmics())

    sig_fisher = 0
    sig_stouffer = 0
    sig_adj_bh = 0
    sig_combined_fisher = 0  # Cross-check: use getCombinedSignificancePvalues like pre-refactor
    pvalue_dump = []

    for pw_id, pw in matched.items():
        # Multi-omic case (frontend line 224): use totalGlobalPvalues
        # Single-omic case (frontend line 232): fall back to globalOmicPvalues
        if n_omics > 1:
            tg = pw.getTotalGlobalPvalues() or {}
            p_fisher = tg.get("Fisher", 1.0)
            p_stouffer = tg.get("Stouffer", 1.0)
        else:
            sigvals = pw.getSignificanceValues() or {}
            omic_keys = list(sigvals.keys())
            if not omic_keys:
                p_fisher = p_stouffer = 1.0
            else:
                gop = pw.getGlobalOmicPvalues() or {}
                p_fisher = gop.get(omic_keys[0])
                if p_fisher is None:
                    sd = sigvals[omic_keys[0]]
                    p_fisher = sd[0][2] if sd and isinstance(sd[0], list) else 1.0
                p_stouffer = p_fisher

        if isinstance(p_fisher, list):
            p_fisher = p_fisher[0] if p_fisher else 1.0
        if isinstance(p_stouffer, list):
            p_stouffer = p_stouffer[0] if p_stouffer else 1.0

        if p_fisher is not None and p_fisher != "-" and p_fisher <= threshold:
            sig_fisher += 1
        if p_stouffer is not None and p_stouffer != "-" and p_stouffer <= threshold:
            sig_stouffer += 1

        # Pre-refactor parity check: use getCombinedSignificancePvalues['Fisher']
        cspv = pw.getCombinedSignificancePvalues() or {}
        cs_fisher = cspv.get("Fisher")
        if isinstance(cs_fisher, list):
            cs_fisher = cs_fisher[0] if cs_fisher else None
        if cs_fisher is not None and cs_fisher != "-" and cs_fisher <= threshold:
            sig_combined_fisher += 1

        adj = pw.getAdjustedCombinedSignificancePvalues() or {}
        bh_under_thresh = False
        for method_dict in adj.values():
            if isinstance(method_dict, dict):
                bh = method_dict.get("BH")
                if isinstance(bh, list):
                    bh = bh[0] if bh else None
                if bh is not None and bh != "-" and bh <= threshold:
                    bh_under_thresh = True
                    break
        if bh_under_thresh:
            sig_adj_bh += 1

        if p_fisher is not None and p_fisher <= threshold * 2:
            pvalue_dump.append({
                "id": pw_id,
                "name": pw.getName() if hasattr(pw, "getName") else pw_id,
                "fisher": float(p_fisher) if isinstance(p_fisher, (int, float)) else None,
                "stouffer": float(p_stouffer) if isinstance(p_stouffer, (int, float)) else None,
            })

    pvalue_dump.sort(key=lambda x: (x["fisher"] if x["fisher"] is not None else 1.0))

    # Build a complete map of ALL pathways' Fisher p-values for parity checks
    all_fisher = {}
    for pw_id, pw in matched.items():
        cspv = pw.getCombinedSignificancePvalues() or {}
        f = cspv.get("Fisher")
        if isinstance(f, list):
            f = f[0] if f else None
        all_fisher[pw_id] = float(f) if isinstance(f, (int, float)) else None

    return {
        "sig_fisher": sig_fisher,
        "sig_stouffer": sig_stouffer,
        "sig_adj_bh": sig_adj_bh,
        "sig_combined_fisher": sig_combined_fisher,
        "total_pathways": total,
        "n_omics": n_omics,
        "threshold": threshold,
        "top_pathways": pvalue_dump[:20],
        "all_fisher": all_fisher,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--databases", nargs="+", default=["KEGG"])
    parser.add_argument("--omics", default=",".join(EXAMPLE_OMICS.keys()),
                        help="Comma-separated omic names (must match EXAMPLE_OMICS)")
    parser.add_argument("--threshold", type=float, default=0.05)
    parser.add_argument("--output", default=None)
    parser.add_argument("--tmp-dir", default=CLIENT_TMP_DIR)
    parser.add_argument("--assert-baseline", action="store_true",
                        help="Exit non-zero if SIG_FISHER drifts from the pre-refactor baseline (33).")
    args = parser.parse_args()

    selected = [s.strip() for s in args.omics.split(",") if s.strip()]
    job = build_job(args.databases, selected, args.tmp_dir)

    print(f"Building job_id={job.getJobID()}, omics={selected}, db={args.databases}", flush=True)
    job.validateInput()
    job.processFilesContent()
    summary = job.generatePathwaysList()
    print(f"Pipeline summary: total={summary[0]} matched={summary[1]} genes={summary[2]} compounds={summary[3]}", flush=True)

    # Debug: dump per-omic totals
    from collections import Counter
    enrichmentByOmic = {}
    for omic in job.getGeneBasedInputOmics():
        enrichmentByOmic[omic["omicName"]] = omic.get("enrichment", "genes")
    for omic in job.getCompoundBasedInputOmics():
        enrichmentByOmic[omic["omicName"]] = omic.get("enrichment", "features")
    print(f"DEBUG enrichmentByOmic={enrichmentByOmic}", flush=True)

    # Look at one specific pathway and dump significance values
    pid_check = "mmu05168"
    if pid_check in job.getMatchedPathways():
        pw = job.getMatchedPathways()[pid_check]
        print(f"DEBUG {pid_check} sigvals={dict(pw.getSignificanceValues())}", flush=True)
        print(f"DEBUG {pid_check} globalOmicPvalues={dict(pw.getGlobalOmicPvalues())}", flush=True)
        print(f"DEBUG {pid_check} totalGlobalPvalues={dict(pw.getTotalGlobalPvalues())}", flush=True)
        print(f"DEBUG {pid_check} combinedSignificancePvalues={dict(pw.getCombinedSignificancePvalues())}", flush=True)

    result = count_significant(job, args.threshold)
    result["pipeline_summary"] = {
        "total_kegg_pathways": summary[0],
        "matched_pathways": summary[1],
        "input_matched_genes": summary[2],
        "input_matched_compounds": summary[3],
    }
    result["selected_omics"] = selected
    result["databases"] = args.databases

    line = (
        f"SIG_FISHER={result['sig_fisher']} "
        f"SIG_STOUFFER={result['sig_stouffer']} "
        f"SIG_ADJ_BH={result['sig_adj_bh']} "
        f"SIG_COMBINED_FISHER={result['sig_combined_fisher']} "
        f"TOTAL={result['total_pathways']}"
    )
    print(line, flush=True)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote {args.output}", flush=True)

    job.cleanDirectories(remove_output=True, remove_input=False)

    if args.assert_baseline:
        # Pre-refactor parity baseline (commit b021f926): 6 omics, KEGG, mmu.
        # Bug F regression dropped this to 19; the fix restores 33.
        EXPECTED = {"sig_fisher": 33, "sig_stouffer": 15, "total": 364}
        actual = {
            "sig_fisher": result["sig_fisher"],
            "sig_stouffer": result["sig_stouffer"],
            "total": result["total_pathways"],
        }
        if (result["sig_fisher"] != EXPECTED["sig_fisher"]
                or result["sig_stouffer"] != EXPECTED["sig_stouffer"]
                or result["total_pathways"] != EXPECTED["total"]):
            print(f"REGRESSION: expected {EXPECTED}, got {actual}", flush=True)
            sys.exit(1)
        print("BASELINE OK", flush=True)


if __name__ == "__main__":
    main()
