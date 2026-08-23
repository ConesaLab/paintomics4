"""The Methods section — rendered from the job, never written by a model.

A Methods section is a factual record of what ran: organism, databases,
enrichment machinery, MORE parameters, gene-set releases, figure pipeline,
model and date. Every one of those is knowable from the job and the run, so
generating it is a template over facts — the one part of a paper where
"generated, never written" is strictly better than any prose a model could
produce, because a model can only get it wrong.
"""
from __future__ import annotations

import time


def _more_parameters(job_instance):
    table = getattr(job_instance, "regulationPerConditionData", None)
    if not table or not (table.get("rows") or []):
        return None
    columns = table.get("columns") or []
    conditions = [c[len("Group_"):] for c in columns
                  if str(c).startswith("Group_")]
    return {"rows": len(table.get("rows") or []),
            "conditions": conditions,
            "has_r2": "R2" in columns}


def render_methods(ctx):
    job = ctx.job_instance
    lines = []
    lines.append(
        "**Multi-omic pathway analysis.** Data were analysed with PaintOmics "
        "4 for organism `%s`. Features were matched against %s; each pathway "
        "was scored per omic by over-representation of the user's relevant "
        "features against the features that omic measured, and per-pathway "
        "p-values were combined across omics with the job's selected "
        "combination method (Fisher or Stouffer, as stored with the job)."
        % (job.getOrganism(),
           ", ".join(sorted({str(pw.get("source")) for pw in
                             (ctx.pathways or []) if pw.get("source")}))
           or "the installed pathway databases"))

    omics = []
    for omic in ctx.matrix.omics():
        layer = ctx.matrix.get(omic)
        omics.append("%s (%s; %d features)"
                     % (omic, layer.kind, layer.n_features))
    lines.append("**Input layers.** " + "; ".join(omics) + ".")

    lines.append(
        "**Sample-level statistics.** Where replicate columns were present, "
        "principal components were computed by SVD on centred, unscaled "
        "values of the most-variable complete features; group separation was "
        "tested by one-way PERMANOVA on Euclidean distances (exact "
        "enumeration of relabellings for small designs, seeded permutations "
        "otherwise, minimum attainable p reported); replicate agreement was "
        "assessed by Pearson correlation with a stated outlier rule.")

    lines.append(
        "**Gene-set enrichment.** GO term enrichment used Fisher's exact "
        "test against the clone-deduplicated measured universe of the same "
        "layer, Benjamini-Hochberg correction across terms, and the elim "
        "refinement (genes of a term significant at p<0.01 removed from its "
        "ancestors before testing). Set overlaps were tested against the "
        "experiment's own measured universe (exact hypergeometric for pairs; "
        "seeded permutations for higher orders).")

    more = _more_parameters(job)
    if more:
        lines.append(
            "**Regulatory analysis.** MORE regulator-target relationships "
            "(%d rows; per-condition coefficients over %d condition(s)%s) "
            "were classified against curated interaction sources (KEGG "
            "relations, Reactome, OmniPath where installed) as supported, "
            "novel (both endpoints known) or unsupported. Coefficients are "
            "regression slopes, not correlations; R-squared belongs to each "
            "target's model; MLR reports no p-values."
            % (more["rows"], len(more["conditions"]),
               "; target R2 available" if more["has_r2"] else ""))

    lines.append(
        "**Figures.** Every figure was drawn by a deterministic archetype "
        "from a data slice resolved from the job (no model-supplied values), "
        "rendered by matplotlib in an isolated subprocess, and checked "
        "against the plotted data before storage; each figure's bundle "
        "(data.tsv, figure.py, legend) reproduces it exactly.")

    lines.append(
        "**Manuscript assembly.** Specialist analyses were computed "
        "deterministically; a language model narrated each specialist's "
        "evidence and assembled the manuscript, with every number entering "
        "prose as a ledger token substituted from the recorded tool results "
        "at the verification gate (run %s)."
        % time.strftime("%Y-%m-%d"))

    return "\n\n".join(lines)
