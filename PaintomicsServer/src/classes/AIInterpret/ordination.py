"""Sample-level ordination: does the design separate, before anything is claimed?

Why this exists
---------------
`proposals/feature-backlog.md` ranks "PCA / sample-level ordination and matrix
QC" **first** — nine dev studies want it and the effort is small. It is also
the analysis that opens most of the papers this corpus contains: a PCA or MDS
plot showing the groups apart, before any pathway is discussed. In the TEST
scoring it came back `not-derivable` every time it appeared, because PaintOmics
had no per-sample view at all.

It does now. When a recipe keeps its replicates the job carries one column per
sample, so the samples can be projected and the question a reader asks first —
*do the groups actually separate, and is any sample an outlier?* — can be
answered from the same data the report is written from.

Deliberately small: centred PCA by SVD on the relevant features, the first two
components, the variance each explains, and which condition each sample sits
in. No rotation options, no UMAP, no cluster inference. The claim it supports
is "the design separates" or "it does not", and over-reading that is the
failure mode this whole session kept finding.
"""
import math

MAX_FEATURES = 5000        # SVD on a tall matrix, kept cheap
MIN_SAMPLES = 3


def _condition_of(column):
    """`CTRL_rep2` -> `CTRL`. The convention the harness emits."""
    name = str(column or "")
    idx = name.rfind("_rep")
    return name[:idx] if idx > 0 else name


def sample_matrix(job_instance, omic_name, max_features=MAX_FEATURES):
    """(columns, feature_ids, rows) for one omic, most-variable features first."""
    rows, ids = [], []
    columns = None
    for _fid, feature in (job_instance.getInputGenesData() or {}).items():
        for ov in (feature.getOmicsValues() or []):
            if (ov.getOmicName() or "") != omic_name:
                continue
            vals = [v for v in (ov.getValues() or []) if isinstance(v, (int, float))]
            if len(vals) < MIN_SAMPLES:
                continue
            if columns is None:
                columns = len(vals)
            if len(vals) != columns:
                continue
            ids.append(feature.getName() or _fid)
            rows.append(vals)
    if not rows:
        return [], [], []
    # most variable first: a PCA of flat features is a PCA of noise
    order = sorted(range(len(rows)),
                   key=lambda i: -_variance(rows[i]))[:max_features]
    return list(range(columns)), [ids[i] for i in order], [rows[i] for i in order]


def _variance(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return sum((v - m) ** 2 for v in vals) / (n - 1)


def ordinate(job_instance, omic_name, headers=None):
    """Two-component PCA over the samples of one omic."""
    import numpy as np

    _cols, _ids, rows = sample_matrix(job_instance, omic_name)
    if not rows:
        return {"error": "omic '%s' carries no per-sample values in this job; "
                         "it was uploaded with one value per condition, so there "
                         "are no samples to project." % omic_name}
    X = np.asarray(rows, dtype=float).T          # samples x features
    n_samples = X.shape[0]
    if n_samples < MIN_SAMPLES:
        return {"error": "need at least %d samples to project; this omic has %d"
                         % (MIN_SAMPLES, n_samples)}
    X = X[:, ~np.isnan(X).any(axis=0)]
    if X.shape[1] < 2:
        return {"error": "too few complete features to project"}
    X = X - X.mean(axis=0, keepdims=True)
    # SVD rather than a covariance eigendecomposition: samples << features here
    # and the covariance matrix would be the larger object by far.
    U, S, _Vt = np.linalg.svd(X, full_matrices=False)
    var = (S ** 2) / max(float((S ** 2).sum()), 1e-12)
    scores = U * S
    names = list(headers or [])
    if len(names) != n_samples:
        names = ["sample%d" % (i + 1) for i in range(n_samples)]
    conds = [_condition_of(n) for n in names]
    return {
        "omic": omic_name,
        "n_samples": n_samples,
        "n_features": int(X.shape[1]),
        "pc1_percent": round(float(var[0]) * 100, 1),
        "pc2_percent": round(float(var[1]) * 100, 1) if len(var) > 1 else 0.0,
        "samples": [{"name": names[i], "condition": conds[i],
                     "pc1": round(float(scores[i, 0]), 3),
                     "pc2": round(float(scores[i, 1]), 3) if scores.shape[1] > 1 else 0.0}
                    for i in range(n_samples)],
    }


def separation(res):
    """Does PC1 separate the conditions? Between-group spread over within-group.

    Reported as a ratio with its parts, never as a verdict: 'the groups
    separate on PC1' is a claim a reader can check, 'the groups are different'
    is not.
    """
    if res.get("error"):
        return None
    by = {}
    for s in res["samples"]:
        by.setdefault(s["condition"], []).append(s["pc1"])
    if len(by) < 2:
        return None
    means = {c: sum(v) / len(v) for c, v in by.items()}
    grand = sum(means.values()) / len(means)
    between = sum((m - grand) ** 2 for m in means.values()) / max(len(means) - 1, 1)
    within = 0.0
    n = 0
    for c, v in by.items():
        for x in v:
            within += (x - means[c]) ** 2
            n += 1
    within = within / max(n - len(by), 1)
    return {"between": round(between, 3), "within": round(within, 3),
            "ratio": round(between / within, 2) if within > 0 else None,
            "group_means": {c: round(m, 3) for c, m in means.items()}}


def format_result(res, sep=None):
    if res.get("error"):
        return "No ordination: %s" % res["error"]
    lines = [
        "Sample ordination — %s: %d samples, %d features (most variable first)"
        % (res["omic"], res["n_samples"], res["n_features"]),
        "  PC1 explains %.1f%% of the variance, PC2 %.1f%%."
        % (res["pc1_percent"], res["pc2_percent"]),
    ]
    for s in res["samples"]:
        lines.append("    %-22s %-16s PC1 %8.3f  PC2 %8.3f"
                     % (s["name"], s["condition"], s["pc1"], s["pc2"]))
    if sep and sep.get("ratio") is not None:
        lines.append("  PC1 group means: %s"
                     % ", ".join("%s %.2f" % kv for kv in sorted(sep["group_means"].items())))
        lines.append("  between-group / within-group spread on PC1 = %.2f "
                     "(above ~1 the conditions separate on this axis; below, they "
                     "overlap and any per-gene story rests on less than it looks)"
                     % sep["ratio"])
    lines.append("  Say what this shows before interpreting pathways: if the "
                 "groups do not separate, say so.")
    return "\n".join(lines)
