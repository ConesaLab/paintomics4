from src.conf.serverconf import KEGG_DATA_DIR
import csv
import os


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
