from src.conf.serverconf import KEGG_DATA_DIR, AI_MAJOR_PATHWAY_MAX_PVAL
import csv
import os
import re


def _classify_temporal_pattern(values):
    """Classify a numeric series into a temporal expression pattern.

    Categories: monotonic-up, monotonic-down, transient-peak,
    transient-dip, biphasic, flat.
    """
    if not values or len(values) < 2:
        return "flat"

    val_range = max(values) - min(values)
    if val_range < 0.3:
        return "flat"

    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]

    # Count sign changes (ignoring zero diffs)
    sign_changes = 0
    prev_sign = None
    for d in diffs:
        if d > 0:
            s = 1
        elif d < 0:
            s = -1
        else:
            continue
        if prev_sign is not None and s != prev_sign:
            sign_changes += 1
        prev_sign = s

    # Monotonic: allow at most 1 reversal for noise
    if sign_changes <= 1:
        net = values[-1] - values[0]
        if net > 0:
            return "monotonic-up"
        elif net < 0:
            return "monotonic-down"
        # Net zero but range >= 0.3 — fall through to peak/dip check

    # Transient peak/dip: single interior extremum
    peak_idx = max(range(len(values)), key=lambda i: values[i])
    dip_idx = min(range(len(values)), key=lambda i: values[i])

    if 0 < peak_idx < len(values) - 1 and sign_changes <= 2:
        return "transient-peak"
    if 0 < dip_idx < len(values) - 1 and sign_changes <= 2:
        return "transient-dip"

    if sign_changes >= 2:
        return "biphasic"

    return "flat"


def _count_significant_omics(pw):
    """Count how many omic layers have p < AI_MAJOR_PATHWAY_MAX_PVAL."""
    count = 0
    for omic_name, vals in pw.significanceValues.items():
        # vals layout: [total_genes, relevant_genes, p_value, ...]
        if len(vals) >= 3 and vals[2] < AI_MAJOR_PATHWAY_MAX_PVAL:
            count += 1
    return count


def _best_pval(pw):
    cpvals = pw.combinedSignificancePvalues
    if cpvals:
        return min(cpvals.values())
    return 1.0


def get_organism_name(organism_code):
    """Parse organisms_all.list to get full name."""
    filepath = os.path.join(KEGG_DATA_DIR, "current", "common", "organisms_all.list")
    try:
        with open(filepath) as f:
            for row in csv.reader(f, delimiter='\t'):
                if len(row) >= 3 and row[1] == organism_code:
                    return row[2].split("(")[0].strip()
    except FileNotFoundError:
        pass
    return organism_code


def detect_design_type(job_instance, experiment_design=""):
    """Detect experimental design type from omic headers and experiment description.

    Returns: "time_series" | "case_control" | "dose_response" | "single_condition" | "multi_group"
    """
    # Collect all column labels across gene-based and compound-based omics
    all_labels = []
    for omic in job_instance.getGeneBasedInputOmics():
        headers = omic.get("omicHeader")
        if headers and isinstance(headers, list) and len(headers) > 1:
            all_labels.extend(str(h).strip() for h in headers[1:])
    for omic in job_instance.getCompoundBasedInputOmics():
        headers = omic.get("omicHeader")
        if headers and isinstance(headers, list) and len(headers) > 1:
            all_labels.extend(str(h).strip() for h in headers[1:])

    n_columns = len(all_labels)
    label_text = " ".join(all_labels).lower()
    design_text = (experiment_design or "").lower()

    # Check experiment_design string for explicit keywords
    if any(kw in design_text for kw in ["time series", "time-series", "time course", "timecourse", "temporal"]):
        return "time_series"
    if any(kw in design_text for kw in ["case control", "case-control", "case vs control", "treated vs untreated"]):
        return "case_control"
    if any(kw in design_text for kw in ["dose response", "dose-response", "concentration"]):
        return "dose_response"

    # Check column labels for time patterns (0h, 2h, 6h, 12h, 1d, 2d, etc.)
    time_pattern = re.compile(r'\d+\s*(h|hr|hrs|hour|hours|d|day|days|min|m|wk|week|weeks)\b', re.I)
    time_matches = [l for l in all_labels if time_pattern.search(l)]
    if len(time_matches) >= 2:
        return "time_series"

    # Check for dose patterns (0mg, 1mg, 5ug, 10nM, etc.)
    dose_pattern = re.compile(r'\d+\s*(mg|ug|ng|nm|um|mm|mol|μm|μg)\b', re.I)
    dose_matches = [l for l in all_labels if dose_pattern.search(l)]
    if len(dose_matches) >= 2:
        return "dose_response"

    # Check for case/control keywords in labels
    cc_keywords = {"control", "ctrl", "case", "treated", "untreated", "wt", "ko", "wildtype", "mutant"}
    cc_matches = [l for l in all_labels if any(kw in l.lower() for kw in cc_keywords)]
    if len(cc_matches) >= 1 and n_columns <= 4:
        return "case_control"

    # Fallback by column count
    if n_columns == 0:
        return "single_condition"
    if n_columns <= 2:
        return "case_control"
    if n_columns <= 4:
        return "multi_group"

    return "multi_group"


def build_enrichment_table(job_instance, max_pathways=30):
    """Build lightweight enrichment data for triage — no gene/compound details.

    Returns list of dicts with per-omic p-values, feature counts, etc.
    """
    matched = job_instance.getMatchedPathways()
    sorted_pws = sorted(matched.values(), key=lambda pw: _best_pval(pw))[:max_pathways]

    table = []
    for pw in sorted_pws:
        per_omic = {}
        for omic_name, vals in pw.significanceValues.items():
            if len(vals) >= 3:
                per_omic[omic_name] = round(vals[2], 6)

        table.append({
            "id": pw.ID,
            "name": pw.name,
            "source": pw.source,
            "combined_pvalue": _best_pval(pw),
            "per_omic_pvalues": per_omic,
            "significant_omic_count": _count_significant_omics(pw),
            "matched_gene_count": len(pw.matchedGenes),
            "matched_compound_count": len(pw.matchedCompounds),
        })
    return table


def build_feature_name_whitelist(job_instance):
    """Build case-insensitive whitelist from all input genes AND compounds."""
    whitelist = set()
    # Gene names
    for gene_id, gene_obj in job_instance.getInputGenesData().items():
        name = gene_obj.getName()
        if name:
            whitelist.add(name.upper())
        for ov in gene_obj.getOmicsValues():
            orig = ov.originalName if hasattr(ov, 'originalName') else ""
            if orig:
                whitelist.add(orig.upper())
    # Compound names
    for cpd_id, cpd_obj in job_instance.getInputCompoundsData().items():
        name = cpd_obj.getName()
        if name:
            whitelist.add(name.upper())
    return whitelist
