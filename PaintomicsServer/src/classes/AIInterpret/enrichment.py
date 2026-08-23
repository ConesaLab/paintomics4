"""GO / Hallmark enrichment and GSEA — beyond pathways, with honest tails.

Why this exists
---------------
PaintOmics' enrichment is pathway ORA with cross-omic combination; four dev
studies wanted GO term enrichment and four wanted GSEA, and the agent had
neither. This module adds both against ANY stored gene-set collection:

* `enrich_collection` -- Fisher's exact (the same log-gamma hypergeometric
  tail the set tools use) of a job-derived list (up/down/both via the set
  descriptor grammar) against the clone-DEDUPLICATED measured universe,
  BH q-values, and, when the collection carries a DAG (GO), the **elim**
  refinement: terms are tested deepest first, and the genes of a term that
  came out significant are removed from its ancestors before the ancestors
  are tested, so "regulation of apoptosis" does not light up merely because
  "intrinsic apoptotic signaling" did (Alexa's topGO elim, reimplemented).

* `run_gsea` -- the classic weighted-KS enrichment score over ONE ranked
  list (Subramanian 2005, p = 1), significance by seeded gene-label
  permutation, NES normalised by the same-sign permutation mean, BH across
  sets, leading edge reported. The permutation scheme is gene-label, not
  phenotype -- with the few samples these jobs carry a phenotype permutation
  would have a two-digit floor -- and the result SAYS so.

Universes are what the experiment measured, never the genome; every set is
intersected with the universe before testing and the loss is reported.
Matching is by upper-cased symbol -- the same identity the set descriptors
and figure tools use.
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional

from .set_overlap import _hypergeom_sf

DEFAULT_ALPHA = 0.05
ELIM_ALPHA = 0.01              # topGO's default cutoff for pruning ancestors
MAX_RESULTS = 40
GSEA_PERMUTATIONS = 1000
MIN_SET, MAX_SET = 3, 500


def bh_qvalues(pvalues):
    """Benjamini-Hochberg, monotone, in input order."""
    n = len(pvalues)
    order = sorted(range(n), key=lambda i: pvalues[i])
    q = [0.0] * n
    best = 1.0
    for rank_from_end, idx in enumerate(reversed(order)):
        rank = n - rank_from_end
        best = min(best, pvalues[idx] * n / rank)
        q[idx] = best
    return q


class GeneSetCollection(object):
    """Named sets over upper-cased symbols, with an optional DAG for elim.

    sets:    {set_id: {"name": str, "genes": set[str]}}   (true-path already
             propagated for GO -- the installer stores them propagated)
    parents: {set_id: [parent_ids]} or None for flat collections (Hallmark).
    """

    def __init__(self, source, sets, parents=None):
        self.source = str(source)
        self.sets = {str(k): {"name": str(v.get("name") or k),
                              "genes": {str(g).upper()
                                        for g in (v.get("genes") or [])}}
                     for k, v in (sets or {}).items()}
        self.parents = {str(k): [str(p) for p in v]
                        for k, v in (parents or {}).items()} or None

    def __len__(self):
        return len(self.sets)

    def depths(self):
        """{set_id: depth} -- leaves deepest. Flat collections are depth 0."""
        if not self.parents:
            return {k: 0 for k in self.sets}
        memo = {}

        def _depth(term, seen=()):
            if term in memo:
                return memo[term]
            if term in seen:            # a cycle in a curated DAG is a bug,
                return 0                # but it must not hang the server
            parents = self.parents.get(term) or []
            memo[term] = 0 if not parents else (
                1 + max(_depth(p, seen + (term,)) for p in parents))
            return memo[term]

        return {k: _depth(k) for k in self.sets}


def enrich_collection(collection, hits, universe, alpha=DEFAULT_ALPHA,
                      elim=True, ledger=None, max_results=MAX_RESULTS):
    """Fisher enrichment of `hits` against `universe`, optional elim.

    Returns {"results": [...], "n_tested", "universe", "hits_in_universe",
    "method"}. Each result: id, name, k (hits in set), K (set size in
    universe), p, q, genes (the overlapping symbols), elim_pruned (how many
    hit genes elim removed before testing, 0 without a DAG).
    """
    universe = {str(g).upper() for g in universe}
    hits = {str(g).upper() for g in hits} & universe
    if not universe:
        return {"error": "empty universe"}
    if not hits:
        return {"error": "no hit genes inside the measured universe"}

    depths = collection.depths()
    testable = []
    for set_id, entry in collection.sets.items():
        genes = entry["genes"] & universe
        if MIN_SET <= len(genes) <= MAX_SET:
            testable.append((set_id, entry["name"], genes))
    # Deepest first: elim must see children before their ancestors.
    testable.sort(key=lambda t: (-depths.get(t[0], 0), t[0]))

    removed = {}           # set_id -> genes elim removed from it
    results = []
    significant_children = []   # (set_id, hit genes) already accepted
    ancestors_cache = {}

    def _ancestors(term):
        if term in ancestors_cache:
            return ancestors_cache[term]
        out, stack = set(), list(collection.parents.get(term, []) if
                                 collection.parents else [])
        while stack:
            p = stack.pop()
            if p in out:
                continue
            out.add(p)
            stack.extend(collection.parents.get(p, [])
                         if collection.parents else [])
        ancestors_cache[term] = out
        return out

    for set_id, name, genes in testable:
        pruned = removed.get(set_id, set())
        effective_hits = hits - pruned
        k = len(genes & effective_hits)
        K = len(genes)
        p = _hypergeom_sf(k, len(universe), K, len(effective_hits))
        results.append({"id": set_id, "name": name, "k": k, "K": K,
                        "p": p, "genes": sorted(genes & effective_hits),
                        "elim_pruned": len(genes & pruned)})
        if elim and collection.parents and p < ELIM_ALPHA:
            for ancestor in _ancestors(set_id):
                removed.setdefault(ancestor, set()).update(genes & hits)

    qvalues = bh_qvalues([r["p"] for r in results])
    for r, q in zip(results, qvalues):
        r["q"] = q
        if ledger is not None:
            scope = {"set": r["id"], "source": collection.source}
            r["p_fact"] = ledger.add("pvalue", r["p"], scope,
                                     "enrich_collection")
            r["q_fact"] = ledger.add("q", q, scope, "enrich_collection")
    results.sort(key=lambda r: r["p"])
    n_significant = sum(1 for r in results if r["q"] <= alpha)
    return {"source": collection.source,
            "results": results[:max_results],
            "n_tested": len(results), "n_significant": n_significant,
            "universe": len(universe), "hits_in_universe": len(hits),
            "method": ("Fisher exact per set against the measured universe, "
                       "BH across %d sets%s"
                       % (len(results),
                          "; elim: genes of a term significant at p<%g are "
                          "removed from its ancestors before they are tested"
                          % ELIM_ALPHA
                          if elim and collection.parents else ""))}


# ------------------------------------------------------------------- GSEA

def _enrichment_score(ranked, member_set, weights):
    """(ES, running, hit_positions) for one set over one ranked list."""
    n = len(ranked)
    hit_weight_total = sum(weights[i] for i, g in enumerate(ranked)
                           if g in member_set)
    if hit_weight_total == 0:
        return 0.0, [0.0] * n, []
    n_miss = n - sum(1 for g in ranked if g in member_set)
    if n_miss == 0:
        return 0.0, [0.0] * n, []
    miss_step = 1.0 / n_miss
    running, positions = [], []
    cursor, extreme = 0.0, 0.0
    for i, gene in enumerate(ranked):
        if gene in member_set:
            cursor += weights[i] / hit_weight_total
            positions.append(i)
        else:
            cursor -= miss_step
        running.append(cursor)
        if abs(cursor) > abs(extreme):
            extreme = cursor
    return extreme, running, positions


def run_gsea(ranked_genes, scores, collection, n_permutations=GSEA_PERMUTATIONS,
             seed=0, ledger=None, max_results=MAX_RESULTS):
    """Classic GSEA over one pre-ranked list.

    ranked_genes: symbols best-to-worst by `scores` (same length, descending).
    Weighting is |score|^1 (Subramanian's p=1). Permutation is of GENE LABELS
    (seeded); NES = ES / mean(|permuted ES|) of the same sign; q is BH across
    the collection's testable sets.
    """
    genes = [str(g).upper() for g in ranked_genes]
    if len(genes) != len(scores):
        return {"error": "ranked_genes and scores differ in length"}
    if len(genes) < 10:
        return {"error": "a ranked list of %d genes is too short for GSEA"
                         % len(genes)}
    order = sorted(range(len(genes)), key=lambda i: -float(scores[i]))
    ranked = [genes[i] for i in order]
    weights = [abs(float(scores[i])) for i in order]
    in_list = set(ranked)

    rng = random.Random(seed)
    results = []
    for set_id, entry in sorted(collection.sets.items()):
        members = entry["genes"] & in_list
        if not (MIN_SET <= len(members) <= MAX_SET):
            continue
        es, running, positions = _enrichment_score(ranked, members, weights)
        null_same_sign = []
        for _ in range(n_permutations):
            fake = set(rng.sample(ranked, len(members)))
            fake_es, _r, _p = _enrichment_score(ranked, fake, weights)
            if (fake_es >= 0) == (es >= 0):
                null_same_sign.append(abs(fake_es))
        hits = sum(1 for v in null_same_sign if v >= abs(es))
        denom = len(null_same_sign) or 1
        p = (hits + 1) / (denom + 1)
        mean_null = (sum(null_same_sign) / denom) if null_same_sign else 0.0
        nes = es / mean_null if mean_null > 0 else 0.0
        # Leading edge: members at or before the extremum, in rank order.
        extreme_at = max(range(len(running)),
                         key=lambda i: abs(running[i]))
        if es >= 0:
            leading = [ranked[i] for i in positions if i <= extreme_at]
        else:
            leading = [ranked[i] for i in positions if i >= extreme_at]
        results.append({"id": set_id, "name": entry["name"],
                        "size": len(members), "es": round(es, 4),
                        "nes": round(nes, 3), "p": p,
                        "leading_edge": leading[:30],
                        "running": None, "positions": None,
                        "_running": running, "_positions": positions})

    if not results:
        return {"error": "no set had %d-%d members in the ranked list"
                         % (MIN_SET, MAX_SET)}
    qvalues = bh_qvalues([r["p"] for r in results])
    for r, q in zip(results, qvalues):
        r["q"] = q
        if ledger is not None:
            scope = {"set": r["id"], "source": collection.source}
            r["nes_fact"] = ledger.add("stat", r["nes"], scope, "run_gsea")
            r["p_fact"] = ledger.add("pvalue", r["p"], scope, "run_gsea")
            r["q_fact"] = ledger.add("q", q, scope, "run_gsea")
    results.sort(key=lambda r: r["p"])
    floor = 1.0 / (n_permutations + 1)
    return {"source": collection.source, "results": results[:max_results],
            "n_tested": len(results),
            "min_attainable_p": floor,
            "method": ("pre-ranked GSEA, weight |score|^1, %d seeded "
                       "gene-label permutations (floor p=%g; gene-label, "
                       "not phenotype -- the sample count here would give a "
                       "phenotype permutation a two-digit floor), NES by "
                       "same-sign permutation mean, BH across sets"
                       % (n_permutations, floor))}
