"""Is the transcriptional response concentrated around this metabolite?

For each measured compound, the genes within k = 1..4 steps are tested for
enrichment in differentially expressed genes against the DE rate among all
measured KEGG genes. This is not topological hubness: no centrality is computed.

Replaces hubAnalysis.R (333 lines) with three library calls. The R version
re-read a 13 MB CSV and 1,865 .RData files on every job -- I/O proportional to
the species, not to the user's dataset -- for a measured 2.7-3.0 s per job.
"""
from __future__ import annotations

import logging

import numpy as np
from scipy.stats import binomtest
from statsmodels.stats.multitest import multipletests

logger = logging.getLogger(__name__)

HUB_SCHEMA_VERSION = 2
_QUINTILES = 5


def _percentile_stratified_by_size(densities, sizes, background_mask):
    """Rank each density against background compounds of similar ball size.

    An unstratified ECDF ranks a hub metabolite whose radius-4 ball covers half
    the network against compounds with a handful of neighbours. Power scales
    with ball size, so that comparison mostly measures connectivity. Quintiles
    of ball size make it like-for-like; a stratum with fewer than two background
    members falls back to the global background rather than returning nothing.
    """
    out = np.zeros(len(densities))
    if not background_mask.any():
        return out
    edges = np.quantile(sizes, np.linspace(0, 1, _QUINTILES + 1)[1:-1])
    stratum = np.searchsorted(edges, sizes, side="right")
    global_bg = np.sort(densities[background_mask])
    for index in range(len(densities)):
        local = background_mask & (stratum == stratum[index])
        pool = np.sort(densities[local]) if local.sum() >= 2 else global_bg
        if pool.size == 0:
            continue
        out[index] = np.searchsorted(pool, densities[index], side="right") / pool.size
    return out


def score(graph, measured, relevant, steps=4):
    """One row per (compound, radius). See HUB_SCHEMA_VERSION for the contract."""
    measured, relevant = set(measured), set(relevant)
    kegg_genes = [g for g in graph.genes() if g in measured]
    if not kegg_genes:
        logger.info("[hub] no measured gene is in the KEGG graph; no hub rows")
        return []
    de_genes = {g for g in kegg_genes if g in relevant}
    global_rate = len(de_genes) / float(len(kegg_genes))

    all_compounds = graph.compounds()
    measured_compounds = [c for c in all_compounds if c in measured]
    focus = [c for c in measured_compounds if c in relevant]
    if not focus:
        # Same fallback the R code had: with no relevant metabolite, treat every
        # measured one as of interest rather than returning an empty table.
        focus = measured_compounds
    if not focus:
        return []

    # Masks over the graph's whole node space, so scoring is numpy indexing.
    measured_gene = np.zeros(len(graph.names), dtype=bool)
    de_gene = np.zeros(len(graph.names), dtype=bool)
    codes = graph._code
    for gene in kegg_genes:
        measured_gene[codes[gene]] = True
    for gene in de_genes:
        de_gene[codes[gene]] = True
    node_total = float(len(graph.names)) or 1.0

    # Cumulative balls as integer arrays: a pure function of the graph, memoised
    # on it, so only the first job of a process pays for them.
    balls = graph.compound_balls(steps)

    rows, focus_set = [], set(focus)
    for step in range(1, steps + 1):
        names, density, den, no_den, ball = [], [], [], [], []
        for compound in all_compounds:
            ids = balls[compound][step - 1]
            selected = ids[measured_gene[ids]] if ids.size else ids
            hits = int(de_gene[selected].sum()) if selected.size else 0
            total = int(selected.size)
            names.append(compound)
            den.append(hits)
            no_den.append(total - hits)
            density.append(hits / float(total) if total else 0.0)
            ball.append(int(ids.size))
        density = np.asarray(density)
        sizes = np.asarray(ball, dtype=float)
        background = np.array([n not in focus_set for n in names])
        percentile = _percentile_stratified_by_size(density, sizes, background)
        for index, compound in enumerate(names):
            if compound not in focus_set:
                continue
            total = den[index] + no_den[index]
            pvalue = (binomtest(den[index], total, global_rate,
                                alternative="greater").pvalue
                      if total else 1.0)
            rows.append({
                "schema": HUB_SCHEMA_VERSION,
                "name": compound,
                "step": step,
                "density": round(float(density[index]), 4),
                "percentile": float(percentile[index]),
                "pvalue": float(pvalue),
                "pvalue_adjust": None,          # filled below, ONE family
                "DEN": den[index],
                "noDEN": no_den[index],
                "ball_size": ball[index],
                "ball_fraction": round(ball[index] / node_total, 4),
            })

    # D-4: ONE BH family over all four radii. The R code adjusted inside
    # processData(), which ran once per step, so four nested and near-perfectly
    # dependent tests became four families and were then shown in one grid.
    if rows:
        adjusted = multipletests([r["pvalue"] for r in rows], method="fdr_bh")[1]
        for row, value in zip(rows, adjusted):
            row["pvalue_adjust"] = float(value)
    return rows
