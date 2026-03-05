from src.conf.serverconf import (
    KEGG_DATA_DIR, AI_MAJOR_PATHWAY_MIN_OMICS, AI_MAJOR_PATHWAY_MAX_PVAL,
)
import csv
import os
import re


def build_pathway_context(job_instance, max_pathways=15):
    """Extract curated data for LLM. Target: <5,000 tokens for pathway section."""
    matched = job_instance.getMatchedPathways()
    input_genes = job_instance.getInputGenesData()
    header_map = _build_omic_header_map(job_instance)

    # Sort by best combined p-value
    sorted_pws = sorted(matched.values(), key=lambda pw: _best_pval(pw))[:max_pathways]

    pathways = []
    for pw in sorted_pws:
        top_genes = _get_top_genes(pw, input_genes, header_map, limit=10)
        pathways.append({
            "name": pw.name, "id": pw.ID, "source": pw.source,
            "combined_pvalue": _best_pval(pw),
            "per_omic": _format_significance(pw),
            "top_genes": top_genes,
            "matched_gene_count": len(pw.matchedGenes),
            "significant_omic_count": _count_significant_omics(pw),
        })
    return pathways


def _build_omic_header_map(job_instance):
    """Map omicName -> [timepoint_labels] from input omic headers.

    Each inputOmic dict has "omicHeader" (list where [0] is gene ID column,
    [1:] are timepoint/condition labels) and "omicName".
    Labels are simplified by extracting the part after the last underscore
    (e.g., "Ikaros/Control_0h" -> "0h"), falling back to the full string.
    """
    header_map = {}
    for input_omic in job_instance.getGeneBasedInputOmics():
        omic_name = input_omic.get("omicName", "")
        raw_header = input_omic.get("omicHeader")
        if not raw_header or not isinstance(raw_header, list) or len(raw_header) < 2:
            continue
        # [1:] skips the gene ID column
        labels = []
        for col in raw_header[1:]:
            col_str = str(col).strip()
            # Simplify: take part after last underscore if present
            parts = col_str.rsplit("_", 1)
            labels.append(parts[-1] if len(parts) == 2 and parts[-1] else col_str)
        header_map[omic_name] = labels
    return header_map


def _find_matching_labels(header_map, n):
    """Find labels from another omic with matching length, else generate indices."""
    for labels in header_map.values():
        if labels and len(labels) == n:
            return labels
    return [str(i) for i in range(n)]


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


def _get_top_genes(pw, input_genes, header_map, limit=10):
    """Build gene entries with per-omic temporal profiles.

    Each gene entry includes omic_profiles (one per omic type) with
    temporal values, peak info, and pattern classification.
    """
    genes = []
    for gid in pw.matchedGenes:
        gene = input_genes.get(gid)
        if gene is None:
            continue
        symbol = gene.getName()
        if not symbol:
            continue

        omics = gene.getOmicsValues()
        if not omics:
            genes.append({
                "symbol": symbol, "relevant": False,
                "effect_size": 0, "omic_profiles": []
            })
            continue

        is_relevant = any(ov.isRelevant() for ov in omics)
        omic_profiles = []
        max_effect = 0.0

        for ov in omics:
            omic_name = ov.getOmicName()
            values = ov.getValues()
            if not values:
                continue

            # Get labels from header_map; if missing, borrow from another
            # omic with the same number of values (e.g. miRNA-seq has no
            # header but shares timepoints with Gene expression)
            labels = header_map.get(omic_name)
            if not labels or len(labels) != len(values):
                labels = _find_matching_labels(header_map, len(values))

            # Peak value (largest by absolute value)
            abs_vals = [abs(v) for v in values]
            peak_idx = max(range(len(abs_vals)), key=lambda i: abs_vals[i])
            peak_value = round(values[peak_idx], 3)
            peak_timepoint = labels[peak_idx]

            # Start-to-end fold change
            start_end_fc = round(values[-1] - values[0], 3)

            # Pattern classification
            pattern = _classify_temporal_pattern(values)

            # Build value_pairs: "0.01@0h, 0.52@2h, ..."
            value_pairs = _format_value_pairs(values, labels)

            omic_profiles.append({
                "omic_name": omic_name,
                "values": value_pairs,
                "peak_value": peak_value,
                "peak_timepoint": peak_timepoint,
                "start_end_fc": start_end_fc,
                "pattern": pattern,
            })

            # Track max effect across all omics for this gene
            if abs_vals[peak_idx] > max_effect:
                max_effect = abs_vals[peak_idx]

        genes.append({
            "symbol": symbol,
            "relevant": is_relevant,
            "effect_size": round(max_effect, 2),
            "omic_profiles": omic_profiles,
        })

    genes.sort(key=lambda g: (-g["relevant"], -g["effect_size"]))
    return genes[:limit]


def _format_value_pairs(values, labels):
    """Format values with timepoint labels, truncating long series.

    For >12 timepoints: first 3 + peak + last 3 (with '...' separator).
    """
    n = len(values)
    if n <= 12:
        return ", ".join(f"{round(v, 2)}@{l}" for v, l in zip(values, labels))

    # Find peak index for inclusion in truncated output
    abs_vals = [abs(v) for v in values]
    peak_idx = max(range(n), key=lambda i: abs_vals[i])

    # Indices to include: first 3, peak (if not already included), last 3
    indices = list(range(3))
    if peak_idx not in indices and peak_idx not in range(n - 3, n):
        indices.append(peak_idx)
    indices.extend(range(n - 3, n))
    indices = sorted(set(indices))

    parts = []
    prev_i = -1
    for i in indices:
        if prev_i >= 0 and i > prev_i + 1:
            parts.append("...")
        parts.append(f"{round(values[i], 2)}@{labels[i]}")
        prev_i = i

    return ", ".join(parts)


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


def _format_significance(pw):
    parts = []
    for omic_name, vals in pw.significanceValues.items():
        if len(vals) >= 3:
            parts.append(f"{omic_name}: p={vals[2]:.4f} ({vals[1]}/{vals[0]} relevant)")
    return "; ".join(parts)


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


def build_gene_symbol_whitelist(job_instance):
    """Build case-insensitive whitelist from all input genes."""
    whitelist = set()
    for gene_id, gene_obj in job_instance.getInputGenesData().items():
        name = gene_obj.getName()
        if name:
            whitelist.add(name.upper())
        for ov in gene_obj.getOmicsValues():
            orig = ov.originalName if hasattr(ov, 'originalName') else ""
            if orig:
                whitelist.add(orig.upper())
    return whitelist


# ---------------------------------------------------------------------------
# Phase 1 helpers: Triage + Cross-Omic Matrix
# ---------------------------------------------------------------------------

def triage_pathways(pathways):
    """Split pathways into major (multi-omic) and minor (single-omic) lists.

    Uses the `significant_omic_count` field added by build_pathway_context().

    Returns:
        (major_pathways, minor_pathways) — both lists of context dicts.
    """
    major, minor = [], []
    for pw in pathways:
        if pw.get("significant_omic_count", 0) >= AI_MAJOR_PATHWAY_MIN_OMICS:
            major.append(pw)
        else:
            minor.append(pw)
    return major, minor


def build_cross_omic_matrix(pathways):
    """Build a compact markdown table of top genes across major pathways.

    Iterates top genes, deduplicates by symbol, reads all omic_profiles, and
    produces a row per gene with direction arrow + pattern + peak timepoint
    per omic layer.

    Returns:
        Markdown table string (empty string if no multi-omic data).
    """
    # Collect all omic names across pathways for column headers
    omic_names = []
    omic_set = set()
    gene_data = {}  # symbol -> {omic_name: profile_dict}

    for pw in pathways:
        for g in pw.get("top_genes", []):
            sym = g["symbol"]
            for prof in g.get("omic_profiles") or []:
                omic = prof["omic_name"]
                if omic not in omic_set:
                    omic_set.add(omic)
                    omic_names.append(omic)
                # Keep the profile with highest effect for this gene+omic
                if sym not in gene_data:
                    gene_data[sym] = {"_effect": g.get("effect_size", 0)}
                gene_data[sym][omic] = prof
                # Track max effect across all appearances
                gene_data[sym]["_effect"] = max(
                    gene_data[sym]["_effect"], g.get("effect_size", 0))

    if not gene_data or not omic_names:
        return ""

    # Sort genes by effect size, cap at 30
    sorted_genes = sorted(gene_data.items(), key=lambda x: -x[1]["_effect"])[:30]

    # Build markdown table
    header = "| Gene | " + " | ".join(omic_names) + " |"
    sep = "|------|" + "|".join("------" for _ in omic_names) + "|"
    rows = [header, sep]

    for sym, data in sorted_genes:
        cells = []
        for omic in omic_names:
            prof = data.get(omic)
            if prof is None:
                cells.append("—")
            else:
                arrow = _direction_arrow(prof.get("peak_value", 0))
                pattern = prof.get("pattern", "flat")
                peak_tp = prof.get("peak_timepoint", "?")
                cells.append(f"{arrow} {pattern} @{peak_tp}")
        rows.append(f"| {sym} | " + " | ".join(cells) + " |")

    return "\n".join(rows)


def _direction_arrow(peak_value):
    """Map a peak value to a direction arrow: ↑ (positive), ↓ (negative), → (flat)."""
    if peak_value > 0.3:
        return "↑"
    elif peak_value < -0.3:
        return "↓"
    return "→"


# ---------------------------------------------------------------------------
# V2 Pipeline: Design detection, enrichment table, compound support
# ---------------------------------------------------------------------------

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


def _build_compound_header_map(job_instance):
    """Map omicName -> [condition_labels] from compound-based input omic headers."""
    header_map = {}
    for input_omic in job_instance.getCompoundBasedInputOmics():
        omic_name = input_omic.get("omicName", "")
        raw_header = input_omic.get("omicHeader")
        if not raw_header or not isinstance(raw_header, list) or len(raw_header) < 2:
            continue
        labels = []
        for col in raw_header[1:]:
            col_str = str(col).strip()
            parts = col_str.rsplit("_", 1)
            labels.append(parts[-1] if len(parts) == 2 and parts[-1] else col_str)
        header_map[omic_name] = labels
    return header_map


def _get_top_compounds(pw, input_compounds, header_map, limit=10):
    """Build compound entries with per-omic profiles (mirrors _get_top_genes)."""
    compounds = []
    for cid in pw.matchedCompounds:
        cpd = input_compounds.get(cid)
        if cpd is None:
            continue
        name = cpd.getName()
        if not name:
            continue

        omics = cpd.getOmicsValues()
        if not omics:
            compounds.append({
                "name": name, "relevant": False,
                "effect_size": 0, "omic_profiles": [],
            })
            continue

        is_relevant = any(ov.isRelevant() for ov in omics)
        omic_profiles = []
        max_effect = 0.0

        for ov in omics:
            omic_name = ov.getOmicName()
            values = ov.getValues()
            if not values:
                continue

            labels = header_map.get(omic_name)
            if not labels or len(labels) != len(values):
                labels = _find_matching_labels(header_map, len(values))

            abs_vals = [abs(v) for v in values]
            peak_idx = max(range(len(abs_vals)), key=lambda i: abs_vals[i])
            peak_value = round(values[peak_idx], 3)
            peak_label = labels[peak_idx] if labels else str(peak_idx)
            pattern = _classify_temporal_pattern(values)
            value_pairs = _format_value_pairs(values, labels)

            omic_profiles.append({
                "omic_name": omic_name,
                "values": value_pairs,
                "peak_value": peak_value,
                "peak_timepoint": peak_label,
                "pattern": pattern,
            })

            if abs_vals[peak_idx] > max_effect:
                max_effect = abs_vals[peak_idx]

        compounds.append({
            "name": name,
            "relevant": is_relevant,
            "effect_size": round(max_effect, 2),
            "omic_profiles": omic_profiles,
        })

    compounds.sort(key=lambda c: (-c["relevant"], -c["effect_size"]))
    return compounds[:limit]


def classify_expression_pattern(values, design_type):
    """Design-aware wrapper for expression pattern classification.

    Returns a pattern string appropriate for the design type.
    """
    if not values or len(values) < 2:
        return "flat" if design_type == "time_series" else "unchanged"

    if design_type in ("time_series", "dose_response"):
        return _classify_temporal_pattern(values)

    if design_type == "case_control":
        fc = values[-1] - values[0]
        if fc > 0.3:
            return "upregulated"
        elif fc < -0.3:
            return "downregulated"
        return "unchanged"

    # multi_group, single_condition
    val_range = max(values) - min(values)
    return "variable" if val_range > 0.3 else "stable"
