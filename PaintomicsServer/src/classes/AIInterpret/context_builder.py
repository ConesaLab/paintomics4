from src.conf.serverconf import (
    KEGG_DATA_DIR, AI_MAJOR_PATHWAY_MIN_OMICS, AI_MAJOR_PATHWAY_MAX_PVAL,
)
import csv
import re
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
            # _best_pval is the strongest value across conditions, which is the
            # right thing to rank by but is NOT the figure the results table
            # headlines -- that is the global p-value. Reporting the former
            # under the bare name "combined p-value" made the narrative disagree
            # with the table by orders of magnitude for the same pathway
            # (8.42e-4 against 1.80e-07 on mmu00910), with no way for a reader
            # to tell which they were looking at. Both are carried now so the
            # prompt can name each one accurately.
            "combined_pvalue": _best_pval(pw),
            "combined_pvalue_per_condition": _conditionPvalues(pw),
            "global_pvalue": _globalPval(pw),
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
    """Count how many omic layers have p < AI_MAJOR_PATHWAY_MAX_PVAL.

    The p-value slot holds one value per condition in a multi-condition job, so
    comparing it directly raised

        TypeError: '<' not supported between instances of 'list' and 'float'

    and killed the pipeline in triage before any work began. An omic counts as
    significant if it clears the threshold in *any* condition -- a layer that
    responds at one timepoint is a real signal for a report to discuss, and
    requiring every condition would discard exactly the time-resolved findings
    multi-condition analysis exists to surface.

    The earlier repair guessed the wrong shape. ``significanceValues[omic]`` is
    a *list of per-condition triples*::

        [[totalMatched, totalRelevant, pValue],   # condition 1
         [totalMatched, totalRelevant, pValue],   # condition 2
         ...]

    so ``len(vals)`` is the condition count, not a field count, and ``vals[2]``
    is the third condition rather than the p-value. Two silent consequences:
    with one or two conditions every omic was skipped, so nothing was ever
    counted and no pathway could be triaged as major; with three or more the
    feature *counts* were compared against the threshold, and a totalMatched of
    0 is below any p-value threshold, so a pathway matching nothing scored as
    significant.
    """
    count = 0
    for omic_name, vals in pw.significanceValues.items():
        if any(p < AI_MAJOR_PATHWAY_MAX_PVAL for p in _conditionPvaluesOf(vals)):
            count += 1
    return count


def _conditionPvaluesOf(vals):
    """The p-value of each condition in one omic's significance entry.

    Tolerates the legacy flat ``[totalMatched, totalRelevant, pValue]`` shape as
    well as the per-condition list of triples, because both appear in stored
    jobs. Slots that still hold the -1.0 sentinel `Pathway` initialises them
    with are dropped: a p-value is only ever in (0, 1], and a negative left in
    place would read as the most significant value there is.
    """
    if not isinstance(vals, (list, tuple)) or not vals:
        return []

    if all(isinstance(entry, (list, tuple)) for entry in vals):
        pvalues = [entry[2] for entry in vals if len(entry) >= 3]
    else:
        # Legacy flat triple; its third slot may itself be a per-condition list.
        pvalues = list(vals[2:3])

    flattened = []
    for pvalue in pvalues:
        flattened.extend(_numericValues(pvalue))
    return [p for p in flattened if 0 <= p <= 1]


def _numericValues(value):
    """Flatten a p-value that may be a scalar or a per-condition list.

    Multi-condition support changed these from a single float to one value per
    condition. min() over the raw dict values then returns a *list*, and every
    downstream f"{...:.4e}" raises
        TypeError: unsupported format string passed to list.__format__
    which is what crashed the AI pipeline on the example dataset.
    """
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, (int, float))]
    if isinstance(value, (int, float)):
        return [value]
    return []


def _best_pval(pw):
    """Smallest combined p-value across every omic and every condition."""
    cpvals = getattr(pw, "combinedSignificancePvalues", None)
    if not cpvals:
        return 1.0
    flattened = [v for value in cpvals.values() for v in _numericValues(value)]
    return min(flattened) if flattened else 1.0


def _conditionPvalues(pw):
    """Per-condition combined p-values, or [] for a single-condition job.

    Returned only when a method genuinely carries more than one value, so a
    single-condition job's prompt is unchanged.
    """
    cpvals = getattr(pw, "combinedSignificancePvalues", None) or {}
    for value in cpvals.values():
        if isinstance(value, (list, tuple)) and len(value) > 1:
            return _numericValues(value)
    return []


def _globalPval(pw):
    """The global p-value the results table headlines, or None.

    Computed across all conditions rather than within one, so it is a different
    quantity from min(per-condition) and typically much smaller.
    """
    try:
        globals_ = pw.getGlobalOmicPvalues() or {}
    except Exception:
        return None
    numbers = [v for value in globals_.values() for v in _numericValues(value)]
    return min(numbers) if numbers else None


def _format_significance(pw):
    """One line per omic for the prompt: strongest p-value and the counts.

    Indexed the same wrong shape `_count_significant_omics` did -- see
    `_conditionPvaluesOf`. `vals[1]` and `vals[0]` are whole condition triples,
    not counts, so a three-condition job rendered

        Gene expression: p=0.9000 ([2, 0, 0.8]/[2, 1, 0.7] relevant)

    with lists where the counts belong and, because `min()` then ran over
    `[totalMatched, totalRelevant, pValue]`, a "p-value" that was usually a
    feature count -- `p=0.0000` for a pathway whose real p-values were 0.7, 0.8
    and 0.9. A job with one or two conditions produced no line at all.

    Counts are taken from the strongest condition, which is the one the p-value
    reported alongside them describes.
    """
    parts = []
    for omic_name, vals in pw.significanceValues.items():
        pvalues = _conditionPvaluesOf(vals)
        if not pvalues:
            continue

        best = min(pvalues)
        matched, relevant = _countsAtBestCondition(vals, best)
        parts.append(f"{omic_name}: p={best:.4f} ({relevant}/{matched} relevant)")
    return "; ".join(parts)


def _countsAtBestCondition(vals, best):
    """(totalMatched, totalRelevant) for the condition holding `best`.

    Falls back to the first condition when the shape is the legacy flat triple
    or nothing matches, so this can never be the thing that raises.
    """
    if isinstance(vals, (list, tuple)) and vals and all(
            isinstance(entry, (list, tuple)) for entry in vals):
        for entry in vals:
            if len(entry) >= 3 and entry[2] == best:
                return entry[0], entry[1]
        first = vals[0]
        if len(first) >= 2:
            return first[0], first[1]
        return 0, 0

    if isinstance(vals, (list, tuple)) and len(vals) >= 2:
        return vals[0], vals[1]
    return 0, 0


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


def render_pathway_table(pathways, max_genes=6):
    """Render the enrichment result as a markdown table, from the data.

    Same reasoning as ``render_references_section``: this is information the job
    already holds exactly -- pathway names, p-values, which assays carry them,
    which differential genes sit in them -- so asking a model to reproduce it
    buys nothing and costs plenty. Measured: requiring the synthesis to write
    this table took that phase from ~80s to 206s and pushed runs past the time
    budget, while writing it in a separate LLM call stripped the biology out
    (score 17.00 -> 10.00). Rendered here it is complete, costs no wall-clock,
    and cannot hallucinate a pathway or a p-value.

    The model keeps the part only it can do: interpreting what the pattern
    means, in prose, in the report body.
    """
    if not pathways:
        return ""

    lines = [
        "## Enriched Pathway Summary",
        "",
        "Complete enrichment result, rendered directly from the analysis. "
        "Genes listed are those differentially expressed in this experiment.",
        "",
        "| Pathway | Source | p-value | Driving omic layers | Differential genes |",
        "|---|---|---|---|---|",
    ]
    for pw in pathways:
        genes = [g.get("symbol") for g in (pw.get("top_genes") or [])
                 if g.get("relevant") and g.get("symbol")][:max_genes]
        per_omic = str(pw.get("per_omic") or "").replace("|", "/").strip()
        pvalue = pw.get("combined_pvalue")
        try:
            pvalue = "%.2e" % float(pvalue)
        except (TypeError, ValueError):
            pvalue = str(pvalue)
        lines.append("| %s | %s | %s | %s | %s |" % (
            str(pw.get("name", "")).replace("|", "/"),
            pw.get("source", ""),
            pvalue,
            per_omic[:80] or "-",
            ", ".join(genes) or "none differential",
        ))
    return "\n".join(lines)


def build_key_regulators_block(job_instance, limit=40):
    """Features with differential signal in several omic layers.

    The pathway context reaches features through the top enriched pathways and
    their strongest members, which systematically misses regulators whose signal
    is real but sits outside those pathways' headline genes. Measured on a
    STATegra job: Ikzf1 differential in gene expression AND proteomics, Myc,
    Pax5 and Dok1 in DNase-seq, Srm and Amd1 in two layers each -- none of them
    reaching the report, which discussed apoptosis and vesicle trafficking
    instead. Corroboration across independent assays is the strongest evidence
    the experiment offers, and it was going unused.

    Selection is purely evidential -- omic-layer count, then regulator status --
    with no list of genes anyone hopes to see. Feed a curated list in here and
    the report starts reciting expectations rather than reading the data.

    Returns a markdown block, or "" when nothing qualifies.
    """
    scored, seen = [], set()
    for _gene_id, gene in job_instance.getInputGenesData().items():
        name = (gene.getName() or "").strip()
        # Skip unresolved accessions and predicted-gene placeholders: a report
        # cannot say anything useful about "ENSMUSG00000020290", and they crowd
        # out named genes purely by sorting order.
        if (not name or name.upper() in seen
                or re.match(r'^(ENS[A-Z]*\d+|Gm\d+|\d|LOC\d+)', name)
                or name.endswith("Rik")):
            continue
        layers, regulator, effect = set(), False, 0.0
        for ov in gene.getOmicsValues() or []:
            try:
                if not ov.isRelevant():
                    continue
                layers.add(ov.getOmicName())
            except Exception:
                continue
            # Separate try blocks on purpose. Sharing one meant a raising
            # isRegulator() skipped the value loop below it, so every effect
            # size came out 0.00 and the ranking silently degraded to
            # alphabetical -- the exact failure this ranking exists to fix.
            try:
                regulator = regulator or bool(ov.isRegulator())
            except Exception:
                pass
            try:
                for v in (ov.getValues() or []):
                    if isinstance(v, (int, float)):
                        effect = max(effect, abs(v))
            except Exception:
                pass
        if len(layers) >= 2 or (regulator and layers):
            seen.add(name.upper())
            scored.append((len(layers), regulator, effect, name, sorted(layers)))

    if not scored:
        return ""

    # Corroboration breadth, then effect size. Effect size is what makes this
    # ranking evidential rather than incidental: with hundreds of genes
    # differential in exactly two layers, ordering the tie by name meant the
    # block was chosen by the alphabet -- 45 slots filled from "A", and Ikzf1
    # never appeared despite being differential in gene expression AND
    # proteomics. Name survives only as a final tie-break for determinism.
    scored.sort(key=lambda r: (-r[0], not r[1], -r[2], r[3]))
    lines = ["## Cross-Layer Regulators (differential in multiple omic layers)",
             "Corroborated by independent assays -- the experiment's strongest "
             "evidence. Discuss these where they bear on the pathways below.", ""]
    for n_layers, regulator, effect, name, layers in scored[:limit]:
        lines.append("- **%s** — differential in %d layers (%s), peak |value| %.2f%s"
                     % (name, n_layers, ", ".join(layers), effect,
                        " [regulator]" if regulator else ""))
    return "\n".join(lines)


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
