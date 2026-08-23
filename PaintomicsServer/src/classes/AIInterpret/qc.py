"""QC v2 — the questions a reader asks before believing any pathway.

Why this exists
---------------
`ordination.py` answers "do the groups separate on PC1", and that was the
whole per-sample story. A Results section needs the rest of the opening
paragraph: which features DRIVE the separation (loadings), whether the
separation survives a test that respects the permutation structure (PERMANOVA,
with its minimum attainable p said out loud on small designs), whether any
sample disagrees with its own replicates (correlation + clustering, an outlier
rule stated as a rule), and what the data can and cannot support at all
(`data_limits`). Everything here reads the `LayerMatrix` -- the same walk
every other tool reads -- and returns plain dicts whose numbers a FactsLedger
can register.

Statistical honesty, pinned by tests: PERMANOVA on a design with three
replicates per group cannot give p < 1/(number of distinct relabellings), so
tiny designs are enumerated EXACTLY and the floor is reported beside the p;
an outlier is named by the rule that caught it, never by eye; a batch signal
is a statement about replicate indices, only testable when the columns carry
them.
"""
from __future__ import annotations

import itertools
import math
import random
from typing import Dict, List, Optional

MIN_SAMPLES = 3
MAX_PERMUTATIONS = 999
EXACT_ENUMERATION_LIMIT = 5000        # enumerate relabellings exactly below this
TOP_LOADINGS = 8
OUTLIER_MIN_R = 0.5                   # absolute floor for within-condition r
OUTLIER_SD = 2.5                      # ...or this many sd below the mean


def condition_of(column):
    """`CTRL_rep2` -> `CTRL`; a column with no _rep suffix is its own group."""
    name = str(column or "")
    idx = name.rfind("_rep")
    return name[:idx] if idx > 0 else name


def _complete_columns(layer):
    """samples x features matrix (lists), NaN-free features only."""
    import numpy as np
    if layer is None or not layer.values:
        return None, []
    X = np.asarray(layer.values, dtype=float).T      # samples x features
    keep = ~np.isnan(X).any(axis=0)
    X = X[:, keep]
    return X, list(layer.columns)


def ordinate_layer(layer, top_loadings=TOP_LOADINGS):
    """PCA over one layer's samples, with the loadings that drive each PC."""
    import numpy as np
    X, names = _complete_columns(layer)
    if X is None or X.shape[0] < MIN_SAMPLES:
        return {"error": "need at least %d samples; %r has %d"
                         % (MIN_SAMPLES, getattr(layer, "omic", "?"),
                            0 if X is None else X.shape[0])}
    if X.shape[1] < 2:
        return {"error": "too few complete features to project"}
    keep_idx = [i for i, row in enumerate(layer.values)
                if not any(math.isnan(v) for v in row)]
    labels = [layer.labels[i] for i in keep_idx]
    Xc = X - X.mean(axis=0, keepdims=True)
    U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    var = (S ** 2) / max(float((S ** 2).sum()), 1e-12)
    scores = U * S
    conds = [condition_of(n) for n in names]
    out = {
        "omic": layer.omic,
        "n_samples": int(X.shape[0]), "n_features": int(X.shape[1]),
        "pc1_percent": round(float(var[0]) * 100, 1),
        "pc2_percent": round(float(var[1]) * 100, 1) if len(var) > 1 else 0.0,
        "samples": [{"name": names[i], "condition": conds[i],
                     "pc1": round(float(scores[i, 0]), 3),
                     "pc2": round(float(scores[i, 1]), 3)
                     if scores.shape[1] > 1 else 0.0}
                    for i in range(X.shape[0])],
        "loadings": {},
    }
    for pc in (0, 1):
        if pc >= Vt.shape[0]:
            break
        component = Vt[pc]
        order = sorted(range(len(component)),
                       key=lambda i: -abs(component[i]))[:top_loadings]
        out["loadings"]["PC%d" % (pc + 1)] = [
            {"feature": labels[i], "loading": round(float(component[i]), 3)}
            for i in order]
    return out


# ---------------------------------------------------------------- PERMANOVA

def _distinct_relabellings(counts):
    """How many distinct group relabellings exist: the multinomial coefficient."""
    n = sum(counts)
    total = math.factorial(n)
    for c in counts:
        total //= math.factorial(c)
    return total


def _pseudo_f(D2, groups_idx, group_sizes):
    """Anderson's pseudo-F from a squared-distance matrix."""
    n = len(groups_idx)
    k = len(group_sizes)
    total = sum(D2[i][j] for i in range(n) for j in range(i + 1, n)) / n
    within = 0.0
    members = {}
    for i, g in enumerate(groups_idx):
        members.setdefault(g, []).append(i)
    for g, idx in members.items():
        m = len(idx)
        if m < 2:
            continue
        ss = sum(D2[i][j] for a, i in enumerate(idx) for j in idx[a + 1:])
        within += ss / m
    between = total - within
    df_b, df_w = k - 1, n - k
    if df_w <= 0 or within <= 0:
        return None
    return (between / df_b) / (within / df_w)


def permanova(layer, n_permutations=MAX_PERMUTATIONS, seed=0):
    """One-way PERMANOVA on Euclidean distances between samples.

    Small designs are enumerated exactly (every distinct relabelling), so the
    p is exact and its floor is 1/#relabellings; larger designs use seeded
    permutations and the floor is 1/(n+1). The floor is always reported:
    'p = 0.1' from a 3v3 design (10 relabellings) is the SMALLEST value the
    design can produce, and a sentence that hides that overstates the data.
    """
    import numpy as np
    X, names = _complete_columns(layer)
    if X is None or X.shape[0] < MIN_SAMPLES:
        return {"error": "need at least %d samples" % MIN_SAMPLES}
    conds = [condition_of(n) for n in names]
    levels = sorted(set(conds))
    if len(levels) < 2:
        return {"error": "one condition; nothing to test"}
    if len(levels) == len(conds):
        return {"error": "no replicates: one sample per condition, PERMANOVA "
                         "has nothing to permute"}
    index = {c: i for i, c in enumerate(levels)}
    groups_idx = [index[c] for c in conds]
    counts = [conds.count(c) for c in levels]

    diff = X[:, None, :] - X[None, :, :]
    D2 = (diff ** 2).sum(axis=2)
    observed = _pseudo_f(D2, groups_idx, counts)
    if observed is None:
        return {"error": "degenerate design (no within-group spread)"}

    n_distinct = _distinct_relabellings(counts)
    n = len(groups_idx)
    hits, tested, exact = 0, 0, False
    if n_distinct <= EXACT_ENUMERATION_LIMIT:
        exact = True
        seen = set()
        for perm in itertools.permutations(groups_idx):
            if perm in seen:
                continue
            seen.add(perm)
            f = _pseudo_f(D2, list(perm), counts)
            if f is not None:
                tested += 1
                if f >= observed - 1e-12:
                    hits += 1
        p = hits / tested if tested else 1.0
        floor = 1.0 / n_distinct
    else:
        rng = random.Random(seed)
        base = list(groups_idx)
        for _ in range(n_permutations):
            rng.shuffle(base)
            f = _pseudo_f(D2, base, counts)
            if f is not None:
                tested += 1
                if f >= observed - 1e-12:
                    hits += 1
        p = (hits + 1) / (tested + 1) if tested else 1.0
        floor = 1.0 / (n_permutations + 1)

    return {"omic": layer.omic, "f": round(float(observed), 3),
            "p": p, "min_attainable_p": floor, "exact": exact,
            "n_samples": n, "groups": {c: conds.count(c) for c in levels},
            "n_relabellings": n_distinct if exact else None,
            "n_permutations": tested if not exact else None}


# ------------------------------------------------- correlation + clustering

def sample_correlation(layer, max_features=2000):
    """Pearson correlation between samples, clustering, outlier and batch rules."""
    import numpy as np
    X, names = _complete_columns(layer)
    if X is None or X.shape[0] < MIN_SAMPLES:
        return {"error": "need at least %d samples" % MIN_SAMPLES}
    variances = X.var(axis=0)
    order = np.argsort(-variances)[:max_features]
    Xv = X[:, order]
    R = np.corrcoef(Xv)
    conds = [condition_of(n) for n in names]

    within = {}
    for i in range(len(names)):
        mates = [j for j in range(len(names))
                 if j != i and conds[j] == conds[i]]
        if mates:
            within[names[i]] = float(np.mean([R[i, j] for j in mates]))
    outliers = []
    if within:
        values = list(within.values())
        mean_r = float(np.mean(values))
        sd_r = float(np.std(values)) or 1e-9
        threshold = max(OUTLIER_MIN_R, mean_r - OUTLIER_SD * sd_r)
        for name, r in within.items():
            if r < threshold:
                outliers.append({"sample": name, "within_r": round(r, 3),
                                 "threshold": round(threshold, 3)})

    clusters, batch = None, None
    try:
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import squareform
        D = 1.0 - R
        np.fill_diagonal(D, 0.0)
        D = (D + D.T) / 2.0
        Z = linkage(squareform(D, checks=False), method="average")
        k = len(set(conds))
        assignment = fcluster(Z, t=k, criterion="maxclust")
        clusters = {names[i]: int(assignment[i]) for i in range(len(names))}
        # Purity of clusters against conditions vs against replicate index.
        def _purity(labels):
            by = {}
            for i, cl in enumerate(assignment):
                by.setdefault(cl, []).append(labels[i])
            pure = sum(max(members.count(x) for x in set(members))
                       for members in by.values())
            return pure / float(len(labels))
        cond_purity = _purity(conds)
        reps = [n[n.rfind("_rep"):] if "_rep" in n else "" for n in names]
        batch = None
        if any(reps):
            rep_purity = _purity(reps)
            if rep_purity > cond_purity and rep_purity > 0.6:
                batch = ("clustering follows replicate index (purity %.2f) "
                         "more than condition (purity %.2f) -- a batch "
                         "signal; treat per-condition claims with caution"
                         % (rep_purity, cond_purity))
    except Exception:
        pass

    return {"omic": layer.omic, "samples": names, "conditions": conds,
            "matrix": [[round(float(R[i, j]), 3) for j in range(len(names))]
                       for i in range(len(names))],
            "within_condition_r": {n: round(r, 3) for n, r in within.items()},
            "outliers": outliers,
            "outlier_rule": "within-condition mean r below max(%.2f, mean - "
                            "%.1f sd)" % (OUTLIER_MIN_R, OUTLIER_SD),
            "clusters": clusters, "batch_warning": batch}


# ---------------------------------------------------------------- movers

def top_movers(layer, k=5):
    """Features with the largest range across this layer's columns."""
    rows = []
    for i, values in enumerate(layer.values):
        clean = [v for v in values if not math.isnan(v)]
        if len(clean) < 2:
            continue
        rows.append({"feature": layer.labels[i],
                     "range": round(max(clean) - min(clean), 3),
                     "min": round(min(clean), 3), "max": round(max(clean), 3),
                     "relevant": bool(layer.relevant[i])
                     if i < len(layer.relevant) else False})
    rows.sort(key=lambda r: -r["range"])
    return rows[:max(1, int(k))]


# ------------------------------------------------------------- data limits

def data_limits(matrix):
    """What each layer can and cannot support -- Limitations, as data."""
    out = []
    for omic in matrix.omics():
        layer = matrix.get(omic)
        conds = [condition_of(c) for c in layer.columns]
        has_reps = len(set(conds)) < len(conds)
        n_cells = sum(len(r) for r in layer.values) or 1
        n_nan = sum(1 for row in layer.values for v in row if math.isnan(v))
        flat = [v for row in layer.values for v in row if not math.isnan(v)]
        out.append({
            "omic": omic, "kind": layer.kind,
            "n_features": layer.n_features,
            "n_columns": layer.n_conditions,
            "n_conditions": len(set(conds)),
            "replicates": has_reps,
            "nan_fraction": round(n_nan / n_cells, 4),
            "has_negative": bool(flat and min(flat) < 0),
            "dropped_ragged": layer.n_dropped_ragged,
            "limits": [line for line in (
                None if has_reps else
                "one value per condition: no within-condition variance, no "
                "sample-level statistics, no PERMANOVA",
                None if layer.n_features else "no usable rows",
            ) if line],
        })
    return out
