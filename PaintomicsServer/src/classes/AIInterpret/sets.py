"""Set descriptors, multi-set tests and the comparison inventory.

Why this exists
---------------
`set_overlap.compare` takes two NAMED lists -- the agent must already hold the
symbols. But the comparisons a paper actually runs are the job's own slices:
"up in RNA at T1" against "up in protein at T1", relevant lists across
layers. This module gives those slices a grammar, so a specialist's contract
can say "test every comparison in the inventory" and the inventory is
DERIVED from the job rather than improvised per run:

    relevant in <omic>
    up in <omic> [at <condition>]
    down in <omic> [at <condition>]

`up`/`down` read the sign of the DEDUPLICATED layer's value among the user's
relevant features (at the named condition, else at each feature's strongest
condition) -- PaintOmics holds transformed values where sign is direction; the
resolution note says exactly that, so a reader can disagree with it.

The k-way test: two sets get the exact hypergeometric tail the pairwise tool
already uses; three or more get a seeded permutation of the full intersection
with the floor reported (`p >= 1/(n+1)` -- a permutation test cannot say less).
"""
from __future__ import annotations

import math
import random
import re
from typing import Dict, List, Optional

from .layer_matrix import LayerMatrix
from .set_overlap import _hypergeom_sf

MAX_SETS = 6
N_PERMUTATIONS = 10000
MAX_INVENTORY_PAIRS = 24

_DESCRIPTOR = re.compile(
    r"^\s*(relevant|up|down|changed)\s+in\s+(.+?)"
    r"(?:\s+at\s+(.+?))?\s*$", re.IGNORECASE)


def parse_descriptor(text):
    """('up', omic, condition_or_None) -- or None with the grammar in hand."""
    m = _DESCRIPTOR.match(str(text or ""))
    if not m:
        return None
    direction = m.group(1).lower()
    if direction == "changed":
        direction = "relevant"      # the user's relevant list IS the changed list
    return direction, m.group(2).strip(), (m.group(3) or "").strip() or None


def resolve_descriptor(matrix: LayerMatrix, text):
    """(labels, note) for one descriptor against the job's own layers."""
    parsed = parse_descriptor(text)
    if parsed is None:
        return None, ("cannot parse %r. The grammar is: relevant|up|down in "
                      "<omic> [at <condition>]" % text)
    direction, omic, condition = parsed
    layer = matrix.get(omic)
    if layer is None:
        for name in matrix.omics():
            if name.strip().lower() == omic.strip().lower():
                layer = matrix.get(name)
                break
    if layer is None:
        return None, ("no layer called %r (layers: %s)"
                      % (omic, ", ".join(matrix.omics()) or "none"))
    layer = layer.deduplicated()

    col = None
    if condition is not None:
        for i, c in enumerate(layer.columns):
            if c.strip().lower() == condition.strip().lower():
                col = i
                break
        if col is None:
            return None, ("no condition %r in %s (columns: %s)"
                          % (condition, layer.omic,
                             ", ".join(layer.columns)))

    labels = []
    for i, label in enumerate(layer.labels):
        if not layer.relevant[i]:
            continue
        if direction == "relevant":
            labels.append(label)
            continue
        values = layer.values[i]
        if col is not None:
            value = values[col]
        else:
            finite = [v for v in values if not math.isnan(v)]
            value = max(finite, key=abs) if finite else float("nan")
        if math.isnan(value):
            continue
        if direction == "up" and value > 0:
            labels.append(label)
        elif direction == "down" and value < 0:
            labels.append(label)

    note = ("%d feature(s): the user's relevant list of %s"
            % (len(labels), layer.omic))
    if direction in ("up", "down"):
        note = ("%d feature(s): relevant in %s with a %s value %s "
                "(sign read as direction on the transformed scale)"
                % (len(labels), layer.omic,
                   "positive" if direction == "up" else "negative",
                   "at %s" % condition if condition
                   else "at each feature's strongest condition"))
    return labels, note


# ------------------------------------------------------------------- tests

def multiset_test(named_sets, universe, n_permutations=N_PERMUTATIONS, seed=0):
    """P for the FULL intersection of k sets against one universe.

    k = 2: exact hypergeometric tail. k >= 3: seeded permutation -- draw each
    set's size uniformly from the universe, count how often the full
    intersection reaches the observed one. The floor 1/(n+1) is reported;
    'p < 1e-5' from a 10,000-permutation test is not a thing this function
    can say.
    """
    named = [(str(n), set(v)) for n, v in named_sets if v][:MAX_SETS]
    if len(named) < 2:
        return {"error": "give at least two non-empty sets"}
    universe = set(universe)
    if not universe:
        return {"error": "an empty universe tests nothing"}
    outside = {n: len(v - universe) for n, v in named}
    named = [(n, v & universe) for n, v in named]
    if any(not v for _n, v in named):
        return {"error": "a set has no members inside the universe"}

    inter = set.intersection(*[v for _n, v in named])
    observed = len(inter)
    sizes = [len(v) for _n, v in named]
    U = len(universe)

    if len(named) == 2:
        p = _hypergeom_sf(observed, U, sizes[0], sizes[1])
        method, floor = "exact hypergeometric", None
    else:
        rng = random.Random(seed)
        pool = sorted(universe)
        hits = 0
        for _ in range(n_permutations):
            drawn = [set(rng.sample(pool, k)) for k in sizes]
            if len(set.intersection(*drawn)) >= observed:
                hits += 1
        p = (hits + 1) / (n_permutations + 1)
        method = "permutation (%d draws, seed %d)" % (n_permutations, seed)
        floor = 1.0 / (n_permutations + 1)

    expected = U * math.prod(s / U for s in sizes)
    return {"sets": [{"name": n, "n": len(v),
                      "outside_universe": outside[n]} for n, v in named],
            "universe": U, "intersection": observed,
            "members": sorted(inter)[:40],
            "expected": round(expected, 2),
            "p": p, "method": method, "min_attainable_p": floor}


# --------------------------------------------------------------- inventory

def comparison_inventory(matrix: LayerMatrix, max_pairs=MAX_INVENTORY_PAIRS):
    """Every comparison this job can support, derived, ordered, capped.

    Sets first (one per resolvable descriptor), then the pairs worth testing:
    relevant lists across every pair of layers, then up/up and down/down
    across layers, then up-vs-down within a layer across conditions. The cap
    is announced in the result rather than silently applied.
    """
    sets, pairs = [], []
    omics = matrix.omics()
    for omic in omics:
        layer = matrix.get(omic).deduplicated()
        if any(layer.relevant):
            sets.append("relevant in %s" % omic)
            signed = any(v < 0 for row in layer.values
                         for v in row if not math.isnan(v))
            if signed:
                sets.append("up in %s" % omic)
                sets.append("down in %s" % omic)

    rel = [s for s in sets if s.startswith("relevant")]
    for i in range(len(rel)):
        for j in range(i + 1, len(rel)):
            pairs.append((rel[i], rel[j]))
    for direction in ("up", "down"):
        dir_sets = [s for s in sets if s.startswith(direction + " ")]
        for i in range(len(dir_sets)):
            for j in range(i + 1, len(dir_sets)):
                pairs.append((dir_sets[i], dir_sets[j]))
    for omic in omics:
        if ("up in %s" % omic) in sets:
            pairs.append(("up in %s" % omic, "down in %s" % omic))

    dropped = max(0, len(pairs) - max_pairs)
    return {"sets": sets, "pairs": pairs[:max_pairs], "dropped_pairs": dropped}


# ------------------------------------------------------------- concordance

def concordance(matrix: LayerMatrix, omic_a, omic_b, condition=None):
    """Direction agreement of two layers over their shared relevant features."""
    a = matrix.get(omic_a)
    b = matrix.get(omic_b)
    if a is None or b is None:
        return {"error": "no such layer: %s" % (omic_a if a is None else omic_b)}
    a, b = a.deduplicated(), b.deduplicated()

    def _value(layer, i):
        values = layer.values[i]
        if condition is not None:
            for j, c in enumerate(layer.columns):
                if c.strip().lower() == condition.strip().lower():
                    return values[j]
            return float("nan")
        finite = [v for v in values if not math.isnan(v)]
        return max(finite, key=abs) if finite else float("nan")

    index_b = {}
    for i, label in enumerate(b.labels):
        if b.relevant[i]:
            index_b.setdefault(label.upper(), i)

    rows, quadrants = [], {"++": 0, "--": 0, "+-": 0, "-+": 0}
    for i, label in enumerate(a.labels):
        if not a.relevant[i]:
            continue
        j = index_b.get(label.upper())
        if j is None:
            continue
        va, vb = _value(a, i), _value(b, j)
        if math.isnan(va) or math.isnan(vb) or va == 0 or vb == 0:
            continue
        key = ("+" if va > 0 else "-") + ("+" if vb > 0 else "-")
        quadrants[key] += 1
        rows.append({"feature": label, "x": round(va, 4), "y": round(vb, 4)})

    n = len(rows)
    agree = quadrants["++"] + quadrants["--"]
    return {"omic_a": omic_a, "omic_b": omic_b, "condition": condition,
            "n_shared": n, "quadrants": quadrants,
            "agreement": round(agree / n, 3) if n else None,
            "features": rows}
