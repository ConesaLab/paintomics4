"""Per-feature differential statistics from the replicates already uploaded.

Why this exists
---------------
`proposals/feature-backlog.md` ranks "differential expression from a count
matrix + design" and "differential abundance from an intensity matrix" as the
two features wanted by **16 of 19 dev studies each**, and says of them: *"the
map notes of 13 studies say explicitly that nothing in the deposit is in
PaintOmics input shape, so without them PaintOmics cannot start on the study
at all."* The COMPARISON files say the same thing from the other end -- the
recurring complaint is "no per-gene logFC/p/FDR and no DEG count appear
anywhere".

What was missing was NOT the replicates. PaintOmics already ingests them:
`OmicValue.getValues()` holds one number per replicate column, the job's
replicate mapping gives `groups[s]` = the column indices of sample *s*, and
`aggregate_replicates` collapses them to the per-condition means everything
downstream uses. The uploaded replicate structure was being averaged away and
never tested.

So this module does the one missing step: Welch's t between two conditions'
replicate columns, Benjamini-Hochberg across features. Welch rather than
Student because omics groups routinely have unequal variance and unequal n,
and it costs nothing when they do not.

It is deliberately NOT a negative-binomial GLM. Those need raw counts, and by
the time data reaches an OmicValue it has already been transformed (log2 CPM
or log intensity). Fitting an NB model to logged data would be worse than
useless -- it would look authoritative. What this gives is the honest test
for the data actually present, and it says so in its own output.
"""
import math

MAX_REPORTED = 40          # rows echoed to the caller
MIN_REPLICATES = 2         # a t-test needs two per side


def _groups_for(job_instance, omic_name):
    """(sampleHeader, groups) for one omic, or (None, None) if not replicated."""
    for bucket in ("geneBasedInputOmics", "compoundBasedInputOmics"):
        for omic in (getattr(job_instance, bucket, None) or []):
            if (omic.get("omicName") or "").strip() != (omic_name or "").strip():
                continue
            header = list(omic.get("sampleHeader") or [])
            mapping = omic.get("replicateMapping") or []
            # replicateMapping is groups[s] -> [column indices]
            groups = [list(g) for g in mapping] if mapping else []
            if header and groups and len(header) == len(groups):
                return header, groups
            return header or None, groups or None
    return None, None


def available_conditions(job_instance, omic_name):
    """What can be compared, and with how many replicates each."""
    header, groups = _groups_for(job_instance, omic_name)
    if not header or not groups:
        return []
    return [{"name": header[i], "replicates": len(groups[i])}
            for i in range(len(groups))]


def _bh(pvals):
    """Benjamini-Hochberg q-values, order preserved."""
    n = len(pvals)
    if not n:
        return []
    order = sorted(range(n), key=lambda i: pvals[i])
    q = [1.0] * n
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        i = n - rank + 1                       # 1-based rank of this p
        val = pvals[idx] * n / i
        prev = min(prev, val)
        q[idx] = min(1.0, prev)
    return q


def differential_test(job_instance, omic_name, condition_a, condition_b,
                      alpha=0.05, top=MAX_REPORTED):
    """Welch's t per feature between two conditions, BH across features.

    Returns a dict; `rows` are sorted by q then |log2FC|.
    """
    import numpy as np
    from scipy import stats

    header, groups = _groups_for(job_instance, omic_name)
    if not header or not groups:
        return {"error": "omic '%s' has no replicate mapping in this job, so "
                         "there is nothing to test: it was uploaded with one "
                         "value per condition." % omic_name}
    names = {str(h).strip().lower(): i for i, h in enumerate(header)}
    ia = names.get(str(condition_a or "").strip().lower())
    ib = names.get(str(condition_b or "").strip().lower())
    if ia is None or ib is None:
        return {"error": "conditions must be two of: %s" % ", ".join(header)}
    if ia == ib:
        return {"error": "the two conditions are the same"}
    cols_a, cols_b = groups[ia], groups[ib]
    if len(cols_a) < MIN_REPLICATES or len(cols_b) < MIN_REPLICATES:
        return {"error": "need at least %d replicates on each side; %s has %d "
                         "and %s has %d" % (MIN_REPLICATES, header[ia],
                                            len(cols_a), header[ib], len(cols_b))}

    ids, mat_a, mat_b = [], [], []
    features = job_instance.getInputGenesData() or {}
    for _fid, feature in features.items():
        for ov in (feature.getOmicsValues() or []):
            if (ov.getOmicName() or "") != omic_name:
                continue
            vals = ov.getValues() or []
            if len(vals) <= max(max(cols_a), max(cols_b)):
                continue                      # already aggregated, or ragged
            a = [vals[i] for i in cols_a]
            b = [vals[i] for i in cols_b]
            ids.append(feature.getName() or _fid)
            mat_a.append([float(x) if isinstance(x, (int, float)) else np.nan for x in a])
            mat_b.append([float(x) if isinstance(x, (int, float)) else np.nan for x in b])
    if not ids:
        return {"error": "no feature in '%s' carries per-replicate values; the "
                         "upload was already collapsed to condition means."
                         % omic_name}

    A = np.asarray(mat_a, dtype=float)
    B = np.asarray(mat_b, dtype=float)
    # Vectorised: one Welch test per row, NaNs excluded per row.
    with np.errstate(invalid="ignore", divide="ignore"):
        res = stats.ttest_ind(A, B, axis=1, equal_var=False,
                              nan_policy="omit")
        p = np.asarray(res.pvalue, dtype=float)
        mean_a = np.nanmean(A, axis=1)
        mean_b = np.nanmean(B, axis=1)
    n_a = np.sum(~np.isnan(A), axis=1)
    n_b = np.sum(~np.isnan(B), axis=1)
    testable = (n_a >= MIN_REPLICATES) & (n_b >= MIN_REPLICATES) & np.isfinite(p)
    p = np.where(testable, p, 1.0)
    lfc = np.where(testable, mean_b - mean_a, 0.0)

    q = _bh([float(x) for x in p])
    rows = []
    for i, fid in enumerate(ids):
        if not testable[i]:
            continue
        rows.append({"feature": fid, "log2FC": round(float(lfc[i]), 4),
                     "mean_a": round(float(mean_a[i]), 4),
                     "mean_b": round(float(mean_b[i]), 4),
                     "p": float(p[i]), "q": float(q[i]),
                     "n_a": int(n_a[i]), "n_b": int(n_b[i])})
    rows.sort(key=lambda r: (r["q"], -abs(r["log2FC"])))
    sig = [r for r in rows if r["q"] < alpha]
    return {
        "omic": omic_name, "a": header[ia], "b": header[ib],
        "n_a": len(cols_a), "n_b": len(cols_b),
        "tested": len(rows), "skipped": len(ids) - len(rows),
        "alpha": alpha,
        "significant": len(sig),
        "up_in_b": sum(1 for r in sig if r["log2FC"] > 0),
        "down_in_b": sum(1 for r in sig if r["log2FC"] < 0),
        "rows": rows[:top],
        "note": "Welch's t on the values as uploaded (already log-transformed "
                "by the time PaintOmics sees them), Benjamini-Hochberg across "
                "%d features. Not a negative-binomial count model." % len(rows),
    }


def format_result(res):
    if res.get("error"):
        return "No differential test was run: %s" % res["error"]
    lines = [
        "Differential test — %s: %s (n=%d) vs %s (n=%d)"
        % (res["omic"], res["a"], res["n_a"], res["b"], res["n_b"]),
        "  %d features tested, %d skipped for too few replicates."
        % (res["tested"], res["skipped"]),
        "  %d significant at BH q < %.2g — %d up in %s, %d down."
        % (res["significant"], res["alpha"], res["up_in_b"], res["b"],
           res["down_in_b"]),
    ]
    if res["rows"]:
        lines.append("  top by q:")
        for r in res["rows"][:20]:
            lines.append("    %-18s log2FC %+7.3f  p %.3g  q %.3g  (n %d/%d)"
                         % (r["feature"][:18], r["log2FC"], r["p"], r["q"],
                            r["n_a"], r["n_b"]))
    lines.append("  " + res["note"])
    lines.append("  Quote q, not p, when you call something differential, and "
                 "say the test and the n.")
    return "\n".join(lines)
