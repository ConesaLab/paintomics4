#***************************************************************
#  This file is part of Paintomics v4
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomicsai@gmail.com
#**************************************************************
"""
Metabolite class activity: the statistics behind "does this chemical class
respond?", at every level of KEGG BRITE br08001.

Two tests, chosen by what the data can support
-----------------------------------------------
A class test needs a noise scale. Where it comes from decides which test can
honestly be run:

* **Binomial on the relevant list** (no replicates). For a class of ``n``
  measured metabolites of which ``k`` are in the relevant list, the p-value is
  ``P(K >= k)``, ``K ~ Binomial(n, p0)``. What ``p0`` means is the whole
  question:

  - ``p0 = alpha`` (the user's per-metabolite significance threshold): H0 is
    "no member of this class truly changed", under which each member is
    flagged only by a type-I error, with probability alpha. A
    *self-contained* test. Valid only when the relevant list came from a
    test at that threshold -- a fold-change cut-off has no alpha.
  - ``p0 = observed relevant proportion`` of the whole classified panel: H0 is
    "this class is like the rest of the panel". A *competitive* test, which is
    powerless by construction on a targeted panel where most of what was
    measured moves (STATegra: 29 of 41 classified metabolites relevant, so a
    class of 4 cannot get below p = 0.25 even with every member relevant).

* **Permutation on replicates** (a values file with one column per sample,
  plus a design mapping columns to conditions). Per metabolite, an F-test for
  the factor under study -- main effect plus its interaction with the other
  factors of the design, which serve as strata::

      full     y ~ strata + factor + factor:strata
      reduced  y ~ strata
      F = [(RSS_red - RSS_full) / df1] / [RSS_full / df2]

  Per class, the statistic is the mean F of its members, and its null
  distribution is built by re-labelling the factor within each stratum
  (``nPerm`` times) and recomputing. Samples are shuffled, never metabolites,
  so the correlation between members of a class survives into the null and
  the test does not overstate the way an independence-assuming combination
  (Stouffer, Fisher) does. Self-contained: the answer does not depend on how
  much of the panel moves.

Both tests are run at BRITE levels 1, 2 and 3, and the BH correction is
applied within a level.

Everything here is pure: NumPy in, dicts out, no job, no database. The job
(``PathwayAcquisitionJob.compundsClassification``) collects the inputs and
stores the result.
"""
import json
import math
import os
import warnings
from collections import OrderedDict, defaultdict

import numpy as np
from scipy import stats

from src.common.Statistics import adjustPvalues

__all__ = [
    "BRITE_PATH", "loadBrite", "membershipsByLevel", "binomialClassTest",
    "designFactors", "factorTest", "permutationClassTest", "maybeLog2",
    "benjaminiHochberg", "LEVEL_NAMES",
]

BRITE_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "br08001.json"))
LEVEL_NAMES = {1: "category", 2: "class", 3: "subclass"}
# Fewer non-missing columns than this and a per-metabolite F has no residual
# degrees of freedom worth reporting.
MIN_RESIDUAL_DF = 2
_BRITE_CACHE = {}


# ---------------------------------------------------------------------------
# BRITE hierarchy
# ---------------------------------------------------------------------------
def loadBrite(path=BRITE_PATH):
    """``{compoundID: [(level1, level2, level3), ...]}`` for br08001.

    A compound can sit under more than one leaf (GABA is an Amine, an Amino
    acid and a Neurotransmitter), so the value is a list of paths. Cached per
    path: the file is 660 entries and every step-2 run reads it.
    """
    if path in _BRITE_CACHE:
        return _BRITE_CACHE[path]
    with open(path, "r") as handle:
        tree = json.load(handle)
    paths = defaultdict(list)
    for level1 in tree.get("children", []):
        for level2 in level1.get("children", []):
            for level3 in level2.get("children", []):
                for compound in level3.get("children", []):
                    compoundID = compound["name"].split()[0]
                    paths[compoundID].append((level1["name"], level2["name"], level3["name"]))
    _BRITE_CACHE[path] = dict(paths)
    return _BRITE_CACHE[path]


def membershipsByLevel(compoundIDsByFeature, brite):
    """Class memberships at every level, keyed by the measured feature.

    ``compoundIDsByFeature``: ``{featureKey: [compoundID, ...]}`` -- one
    measured metabolite may have been ticked under two KEGG ids in step 2, and
    it is one measurement, so it is one trial in every class it reaches.

    Returns ``{level: OrderedDict(classKey -> {"name", "parent", "path",
    "members": set(featureKey)})}`` for levels 1..3, with ``classKey`` the
    path joined by ``" > "`` so a level-3 name reused under two level-2
    classes (BRITE has several "Amino acids") stays two classes. Classes are
    ordered by first appearance in the hierarchy so the output is stable.
    """
    levels = {1: OrderedDict(), 2: OrderedDict(), 3: OrderedDict()}
    for featureKey, compoundIDs in compoundIDsByFeature.items():
        seen = set()
        for compoundID in compoundIDs:
            for path in brite.get(compoundID, []):
                for level in (1, 2, 3):
                    partial = path[:level]
                    if (level, partial) in seen:
                        continue
                    seen.add((level, partial))
                    key = " > ".join(partial)
                    entry = levels[level].get(key)
                    if entry is None:
                        entry = {"name": partial[-1], "parent": partial[-2] if level > 1 else "",
                                 "path": list(partial), "members": set()}
                        levels[level][key] = entry
                    entry["members"].add(featureKey)
    return levels


# ---------------------------------------------------------------------------
# Multiple testing
# ---------------------------------------------------------------------------
def benjaminiHochberg(pByKey):
    """``{key: BH-adjusted p}`` through the app's own adjustPvalues."""
    if not pByKey:
        return {}
    return dict(adjustPvalues(dict(pByKey)).get("FDR BH", {}))


# ---------------------------------------------------------------------------
# Binomial test on the relevant list
# ---------------------------------------------------------------------------
def binomialClassTest(classes, relevant, nConditions, nullPerCondition):
    """One-sided binomial per class and condition.

    ``classes``: ``{classKey: {"members": set(featureKey), ...}}``.
    ``relevant``: ``{featureKey: [bool] * nConditions}``.
    ``nullPerCondition``: the ``p0`` of each condition (alpha, or the observed
    proportion for the competitive variant).

    Returns ``{classKey: {"n", "k": [per condition], "p": [...], "bh": [...]}}``
    with BH applied across the classes of each condition.
    """
    results = OrderedDict()
    for key, entry in classes.items():
        members = entry["members"]
        n = len(members)
        k = [0] * nConditions
        for featureKey in members:
            flags = relevant.get(featureKey) or []
            for c in range(min(nConditions, len(flags))):
                if flags[c]:
                    k[c] += 1
        pvals = []
        for c in range(nConditions):
            p0 = nullPerCondition[c] if c < len(nullPerCondition) else None
            if not n or p0 is None or not (0 < p0 < 1):
                # p0 = 1 (every classified compound relevant) or 0: the test
                # says nothing, and binomtest rejects p outside (0, 1).
                pvals.append(1.0)
                continue
            pvals.append(float(stats.binomtest(k[c], n=n, p=p0, alternative="greater").pvalue))
        results[key] = {"n": n, "k": k, "p": pvals, "bh": [1.0] * nConditions}
    for c in range(nConditions):
        adjusted = benjaminiHochberg({key: res["p"][c] for key, res in results.items()})
        for key, res in results.items():
            res["bh"][c] = float(adjusted.get(key, 1.0))
    return results


# ---------------------------------------------------------------------------
# Design factors
# ---------------------------------------------------------------------------
def designFactors(sampleHeader, mapping):
    """The factors a design's condition names encode, and how to stratify.

    ``sampleHeader`` are the condition labels of a parsed design (``Ctr_0H``,
    ``Ik_24H``) and ``mapping[i]`` the condition index of replicate column
    ``i``. A name that splits into the same number of tokens for every
    condition, with a position that takes more than one value but fewer than
    all, is a crossed factor (the ``_factor_positions`` rule of DesignFile).

    Returns a list of factors, one per usable position, plus one for the
    design itself when no position qualifies (a plain two-group comparison)::

        {"id": "factor0", "label": "Ctr, Ik", "levels": ["Ctr", "Ik"],
         "columnLevel": [level index per column],
         "strata": [stratum index per column], "strataLabels": ["0H", ...]}

    ``strata`` groups columns by the values of every OTHER factor position,
    so a permutation can shuffle the factor inside them. With one factor the
    stratum is the same for every column.
    """
    from src.common.DesignFile import factorPositions

    nColumns = len(mapping)
    factors = []
    positions = factorPositions(list(sampleHeader))
    for sep, position, values in positions:
        valueIndex = {value: idx for idx, value in enumerate(values)}
        tokensByCondition = [name.split(sep) for name in sampleHeader]
        conditionLevel = [valueIndex[tokens[position]] for tokens in tokensByCondition]
        # Everything that is not this factor is the stratum.
        strataKeys = []
        for tokens in tokensByCondition:
            strataKeys.append(sep.join(t for i, t in enumerate(tokens) if i != position))
        strataLabels = list(OrderedDict.fromkeys(strataKeys))
        strataIndex = {label: idx for idx, label in enumerate(strataLabels)}
        conditionStratum = [strataIndex[k] for k in strataKeys]
        factors.append({
            "id": "factor%d" % position,
            "label": ", ".join(values[:4]) + ("…" if len(values) > 4 else ""),
            "levels": list(values),
            "columnLevel": [conditionLevel[mapping[i]] for i in range(nColumns)],
            "strata": [conditionStratum[mapping[i]] for i in range(nColumns)],
            "strataLabels": strataLabels,
        })
    if not factors:
        factors.append({
            "id": "design",
            "label": ", ".join(list(sampleHeader)[:4]) + ("…" if len(sampleHeader) > 4 else ""),
            "levels": list(sampleHeader),
            "columnLevel": list(mapping),
            "strata": [0] * nColumns,
            "strataLabels": [""],
        })
    return factors


# ---------------------------------------------------------------------------
# Per-metabolite F-test with stratified permutation
# ---------------------------------------------------------------------------
def maybeLog2(Y):
    """Log2 a matrix that looks like raw intensities.

    The F-test wants a roughly symmetric scale. Values that are all positive
    and span more than 50-fold are intensities, not log ratios, and are
    transformed; anything else is left alone. Returns ``(Y, transformed)``.
    """
    finite = Y[np.isfinite(Y)]
    if finite.size == 0:
        return Y, False
    lo, hi = float(finite.min()), float(finite.max())
    if lo > 0 and hi / lo > 50:
        return np.log2(Y), True
    return Y, False


def _designMatrices(columnLevel, strata, nLevelsFactor, nStrata):
    """(X_reduced, X_full) for ``y ~ strata`` and ``y ~ strata * factor``."""
    n = len(columnLevel)
    reduced = [np.ones(n)]
    for s in range(1, nStrata):
        reduced.append((strata == s).astype(float))
    Xr = np.column_stack(reduced)
    factorCols = [(columnLevel == l).astype(float) for l in range(1, nLevelsFactor)]
    full = [Xr] + [c[:, None] for c in factorCols]
    for s in range(1, nStrata):
        sMask = (strata == s).astype(float)
        for c in factorCols:
            full.append((c * sMask)[:, None])
    Xf = np.column_stack(full)
    return Xr, Xf


def _rss(Y, X):
    """Residual sum of squares of every row of Y regressed on X."""
    beta = np.linalg.pinv(X) @ Y.T          # p x m
    resid = Y - (X @ beta).T                # m x n
    return (resid ** 2).sum(axis=1)


def factorTest(Y, columnLevel, strata):
    """F-test for ``factor`` (main effect + interaction with strata) per row.

    ``Y`` is features x columns and may contain NaN; rows are grouped by
    their missingness pattern and each group is fitted on its complete
    columns, so a matrix with a handful of gaps costs a handful of extra
    fits rather than a Python loop over features.

    Returns ``(F, p, df1, df2)`` as arrays over rows; a row that cannot be
    tested (too few complete columns, a level or stratum lost entirely,
    zero residual variance) carries NaN.
    """
    Y = np.asarray(Y, dtype=float)
    columnLevel = np.asarray(columnLevel)
    strata = np.asarray(strata)
    m, n = Y.shape
    F = np.full(m, np.nan)
    P = np.full(m, np.nan)
    DF1 = np.full(m, np.nan)
    DF2 = np.full(m, np.nan)

    masks = ~np.isnan(Y)
    patterns = defaultdict(list)
    for i in range(m):
        patterns[masks[i].tobytes()].append(i)
    for rows in patterns.values():
        keep = masks[rows[0]]
        if keep.sum() < 3:
            continue
        cl = columnLevel[keep]
        st = strata[keep]
        # Re-index levels/strata that survive the missing columns so the
        # design matrix has no all-zero column.
        levelMap = {l: i for i, l in enumerate(sorted(set(cl.tolist())))}
        strataMap = {s: i for i, s in enumerate(sorted(set(st.tolist())))}
        if len(levelMap) < 2:
            continue
        cl = np.array([levelMap[l] for l in cl])
        st = np.array([strataMap[s] for s in st])
        Xr, Xf = _designMatrices(cl, st, len(levelMap), len(strataMap))
        rankR = np.linalg.matrix_rank(Xr)
        rankF = np.linalg.matrix_rank(Xf)
        df1 = rankF - rankR
        df2 = int(keep.sum()) - rankF
        if df1 < 1 or df2 < MIN_RESIDUAL_DF:
            continue
        sub = Y[np.ix_(rows, np.where(keep)[0])]
        rssR = _rss(sub, Xr)
        rssF = _rss(sub, Xf)
        with np.errstate(divide="ignore", invalid="ignore"):
            f = ((rssR - rssF) / df1) / (rssF / df2)
        f = np.where(rssF > 0, f, np.nan)
        F[rows] = f
        P[rows] = stats.f.sf(f, df1, df2)
        DF1[rows] = df1
        DF2[rows] = df2
    return F, P, DF1, DF2


def _shuffleWithinStrata(columnLevel, strata, rng):
    shuffled = columnLevel.copy()
    for s in np.unique(strata):
        idx = np.where(strata == s)[0]
        shuffled[idx] = columnLevel[rng.permutation(idx)]
    return shuffled


def _effects(Y, columnLevel, strata, nLevels, strataLabels, levels):
    """Per-row signed effects for the direction strip.

    Two-level factor: per stratum, ``mean(level 1) - mean(level 0)``, labelled
    by the stratum ("0H", "2H", ...). More levels: every non-reference level
    against level 0, per stratum, labelled ``"<level> vs <ref> @ <stratum>"``
    (or just ``"<level> vs <ref>"`` with a single stratum).
    """
    labels = []
    columns = []
    nStrata = len(strataLabels)
    with warnings.catch_warnings():
        # An all-NaN member row makes nanmean warn about an empty slice; the
        # NaN it returns is the right answer and _finite() turns it into null.
        warnings.simplefilter("ignore", RuntimeWarning)
        for s in range(nStrata):
            refMask = (columnLevel == 0) & (strata == s)
            if not refMask.any():
                continue
            ref = np.nanmean(Y[:, refMask], axis=1)
            for l in range(1, nLevels):
                mask = (columnLevel == l) & (strata == s)
                if not mask.any():
                    continue
                columns.append(np.nanmean(Y[:, mask], axis=1) - ref)
                if nLevels == 2:
                    labels.append(strataLabels[s] or ("%s vs %s" % (levels[1], levels[0])))
                else:
                    labels.append("%s vs %s" % (levels[l], levels[0])
                                  + (" @ " + strataLabels[s] if strataLabels[s] else ""))
    if not columns:
        return labels, np.zeros((Y.shape[0], 0))
    return labels, np.column_stack(columns)


def permutationClassTest(Y, factor, classesByLevel, featureRows, nPerm=2000, seed=0):
    """The replicate-based class test at every level.

    ``Y``: features x replicate columns (NaN allowed). ``factor``: one entry
    of :func:`designFactors`. ``classesByLevel``: :func:`membershipsByLevel`
    output. ``featureRows``: ``{featureKey: row index in Y}``.

    Returns::

        {"features": {"F", "p", "bh", "df1", "df2", "tested"}  (arrays over rows),
         "effects": {"labels": [...], "values": m x e array},
         "levels": {level: {classKey: {"n", "members", "meanF", "p", "bh",
                                       "nullMedian", "nullQ95", "nullMax",
                                       "nsig", "eff": [...], "E": float}}},
         "nPerm": nPerm, "transformed": bool}
    """
    Y = np.asarray(Y, dtype=float)
    Y, transformed = maybeLog2(Y)
    columnLevel = np.asarray(factor["columnLevel"])
    strata = np.asarray(factor["strata"])
    nLevels = len(factor["levels"])
    rng = np.random.default_rng(seed)

    F, P, DF1, DF2 = factorTest(Y, columnLevel, strata)
    tested = np.isfinite(F)
    bh = np.full(Y.shape[0], np.nan)
    if tested.any():
        adjusted = benjaminiHochberg({int(i): float(P[i]) for i in np.where(tested)[0]})
        for i, value in adjusted.items():
            bh[i] = value
    effectLabels, effects = _effects(Y, columnLevel, strata, nLevels, factor["strataLabels"], factor["levels"])

    # Rows each class can use: members with a finite F.
    classRows = {}
    for level, classes in classesByLevel.items():
        for key, entry in classes.items():
            rows = sorted(featureRows[f] for f in entry["members"]
                          if f in featureRows and tested[featureRows[f]])
            classRows[(level, key)] = rows

    # One permutation loop serves every level: the null of a class is the mean
    # of the permuted F over its rows, read off the same permuted vector.
    observed = {k: float(F[rows].mean()) if rows else float("nan") for k, rows in classRows.items()}
    counts = {k: 0 for k in classRows}
    nullValues = {k: [] for k in classRows}
    for _ in range(int(nPerm)):
        permuted = _shuffleWithinStrata(columnLevel, strata, rng)
        Fp, _, _, _ = factorTest(Y, permuted, strata)
        for k, rows in classRows.items():
            if not rows:
                continue
            value = float(Fp[rows].mean())
            nullValues[k].append(value)
            if value >= observed[k]:
                counts[k] += 1

    levelsOut = {}
    for level, classes in classesByLevel.items():
        out = OrderedDict()
        for key, entry in classes.items():
            rows = classRows[(level, key)]
            members = sorted(entry["members"])
            if rows:
                null = np.array(nullValues[(level, key)])
                p = (1.0 + counts[(level, key)]) / (1.0 + nPerm)
                eff = effects[rows].mean(axis=0).tolist() if effects.shape[1] else []
                out[key] = {
                    "name": entry["name"], "parent": entry["parent"], "path": entry["path"],
                    "n": len(members), "tested": len(rows), "members": members,
                    "meanF": observed[(level, key)], "p": float(p), "bh": 1.0,
                    "nullMedian": float(np.median(null)) if null.size else None,
                    "nullQ95": float(np.percentile(null, 95)) if null.size else None,
                    "nullMax": float(null.max()) if null.size else None,
                    "nsig": int(np.sum(bh[rows] < 0.05)),
                    "eff": [_finite(v) for v in eff],
                    "E": _finite(float(np.nanmean(np.abs(effects[rows])))) if effects.shape[1] else None,
                }
            else:
                out[key] = {
                    "name": entry["name"], "parent": entry["parent"], "path": entry["path"],
                    "n": len(members), "tested": 0, "members": members,
                    "meanF": None, "p": None, "bh": None, "nullMedian": None,
                    "nullQ95": None, "nullMax": None, "nsig": 0, "eff": [], "E": None,
                }
        adjusted = benjaminiHochberg({key: res["p"] for key, res in out.items() if res["p"] is not None})
        for key, res in out.items():
            if res["p"] is not None:
                res["bh"] = float(adjusted.get(key, 1.0))
        levelsOut[level] = out

    return {
        "features": {"F": F, "p": P, "bh": bh, "df1": DF1, "df2": DF2, "tested": tested},
        "effects": {"labels": effectLabels, "values": effects},
        "levels": levelsOut,
        "nPerm": int(nPerm),
        "transformed": transformed,
    }


def _finite(value):
    """JSON-safe float: NaN/inf become None (json.dumps would emit a bare NaN)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None
