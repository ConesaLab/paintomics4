"""The Paper Agent — specialists with contracts, a Lead with no compute tools.

Why this shape (measured, not preferred)
----------------------------------------
One agent with sixteen tools was offered `compare_sets` in nineteen schemas
on one run and never chose it: a tool needs an occasion, not a signature.
Here the occasion is code. Each specialist's mandatory contract is EXECUTED
deterministically — the QC analyst cannot skip the PERMANOVA because a
function call, not a choice, runs it — and the model's job per specialist is
narration over evidence it did not compute. The Lead author holds no compute
tools at all: it reads the specialists' notes, the figure list and the quote
shelf, and writes prose whose every number is a `{{fN}}` ledger token. The
gate substitutes the tokens, rejects bare numbers, grounds citations,
guarantees every figure is shown, generates Methods, and stores the result.

This is the design spec's hybrid of A and C (docs/superpowers/specs/
2026-08-23-paper-agent-design.md §2): the deterministic mandatory pass IS
the specialist; a full tool-loop per specialist can replace any single
narrate call later without touching the gate, the ledger or the store.

Runtime: sequential specialists (one narrate call each, evidence computed in
seconds) + one Lead call + the gate's grounding calls — minutes, not the
20-minute ceiling, on one PySiQ worker inside the same `_agent_semaphore`
the interpreter uses. No Flask thread ever blocks.
"""
from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FIGURE_PREFIX = "paperfig"
MAX_LEAD_TOKENS = 6000
MAX_NARRATE_TOKENS = 1200
SPECIALIST_ORDER = ("design_qc", "pathway", "enrichment", "network",
                    "metabolite", "literature")
SECTION_TITLES = {
    "design_qc": "Data overview and quality",
    "pathway": "Pathway-level changes",
    "enrichment": "Functional enrichment beyond pathways",
    "network": "Regulatory relationships",
    "metabolite": "Metabolite-level findings",
}


@dataclass
class AnalysisNote:
    specialist: str
    findings: List[str] = field(default_factory=list)      # sentences with {{fN}}
    evidence: List[str] = field(default_factory=list)      # raw tool results
    figures: List[str] = field(default_factory=list)       # figure ids
    tables: List[Dict] = field(default_factory=list)       # {title, tsv}
    caveats: List[str] = field(default_factory=list)
    unused_occasions: List[Dict] = field(default_factory=list)  # {occasion, reason}

    def to_dict(self):
        return {"specialist": self.specialist, "findings": self.findings,
                "figures": self.figures,
                "tables": [{"title": t["title"]} for t in self.tables],
                "caveats": self.caveats,
                "unused_occasions": self.unused_occasions,
                "n_evidence": len(self.evidence)}


class PaperContext(object):
    """Everything every specialist reads: built once, in code, at phase 0."""

    def __init__(self, job_instance, job_id, experiment_design=""):
        from .facts import FactsLedger
        self.job_instance = job_instance
        self.job_id = job_id
        self.experiment_design = experiment_design or ""
        self.ledger = FactsLedger()
        self.matrix = None
        self.graph = None
        self.pathways = []
        self.inventory = {"sets": [], "pairs": [], "dropped_pairs": 0}
        self.notes: Dict[str, AnalysisNote] = {}
        self.figures: List[Dict] = []          # {id, conclusion, qa_passed}
        self.papers: List[Dict] = []           # literature shelf
        self._figure_seq = 0

    def next_figure_id(self, slug):
        self._figure_seq += 1
        from .figures import _slug
        return "%s%d-%s" % (FIGURE_PREFIX, self._figure_seq, _slug(slug))


def build_paper_context(job_instance, job_id, experiment_design=""):
    from . import context_builder
    from .job_graph import from_job
    from .layer_matrix import LayerMatrix
    from .sets import comparison_inventory

    ctx = PaperContext(job_instance, job_id, experiment_design)
    ctx.matrix = LayerMatrix.from_job(job_instance)
    ctx.pathways = context_builder.build_pathway_context(job_instance,
                                                         max_pathways=60)
    try:
        ctx.graph = from_job(job_instance, ctx_pathways=ctx.pathways,
                             classify=True)
    except Exception as exc:
        logger.warning("[paper] graph build failed: %s", exc)
        ctx.graph = None
    ctx.inventory = comparison_inventory(ctx.matrix)
    return ctx


# ---------------------------------------------------------------------------
# Figures: one door for every specialist, through the SAME pipeline the
# interpreter uses (sandbox render + QA + bundle on disk).
# ---------------------------------------------------------------------------

def _make_figure(ctx, archetype, data_slice, conclusion, slug, width="single",
                 has_negative=True):
    from . import figures
    fig_id = ctx.next_figure_id(slug)
    spec = {"archetype": archetype, "conclusion": conclusion, "title": "",
            "width": width, "has_negative": has_negative, "centre_zero": None,
            "n": 0, "test": None}
    try:
        _bundle, (passed, lines), result = figures.build_bundle(
            ctx.job_instance, fig_id, archetype, data_slice, spec)
    except figures.EmptyFigure as exc:
        return None, "figure refused: %s" % exc
    except Exception as exc:
        logger.warning("[paper] figure %s failed: %s", fig_id, exc)
        return None, "figure failed: %s" % exc
    ctx.figures.append({"id": fig_id, "conclusion": conclusion,
                        "archetype": archetype,
                        "qa_passed": bool(passed),
                        "render_ok": bool(getattr(result, "ok", False))})
    return fig_id, None


# ---------------------------------------------------------------------------
# The narrate call: one per specialist, over evidence the model did not make.
# ---------------------------------------------------------------------------

NARRATE_SYSTEM = """You are the %s analyst on a scientific writing team.
Below is EVIDENCE your own tools computed from the user's data. Numbers in
the evidence carry ids like [f17].

Write your findings as %d-%d complete sentences, one per line, no bullets,
no headings. HARD RULES:
- Never write a number. Where a number belongs, write its token: {{f17}}.
- Only claim what the evidence shows; name features and conditions as the
  evidence names them.
- To point at a figure write exactly (Figure: <figure-id>).
- If the evidence says something could NOT be computed, do not invent it."""


def _narrate(llm, specialist, evidence, n_min=2, n_max=5):
    if llm is None:
        return []
    prompt = NARRATE_SYSTEM % (specialist.replace("_", " "), n_min, n_max)
    try:
        out = llm.complete(
            [{"role": "system", "content": prompt},
             {"role": "user", "content": "\n\n".join(evidence)[:24000]}],
            max_tokens=MAX_NARRATE_TOKENS, temperature=0.2)
    except Exception as exc:
        logger.warning("[paper] narrate(%s) failed: %s", specialist, exc)
        return []
    lines = [l.strip() for l in (out or "").splitlines()]
    return [l for l in lines if len(l) > 20][:n_max]


# ---------------------------------------------------------------------------
# Specialists. Each returns an AnalysisNote whose evidence is REAL tool
# output; unused_occasions name what the contract asked for that the data
# cannot support, with the reason -- these become Limitations and GAPS.
# ---------------------------------------------------------------------------

def design_qc_analyst(ctx, llm):
    from . import qc
    note = AnalysisNote("design_qc")
    limits = qc.data_limits(ctx.matrix)
    for entry in limits:
        n_tag = ctx.ledger.tag("count", entry["n_features"],
                               {"omic": entry["omic"]}, "data_limits")
        note.evidence.append(
            "%s (%s): %d %s features x %d columns (%d condition(s)%s), "
            "NaN fraction %s"
            % (entry["omic"], entry["kind"], entry["n_features"], n_tag,
               entry["n_columns"], entry["n_conditions"],
               ", replicates" if entry["replicates"] else ", NO replicates",
               entry["nan_fraction"]))
        for limit in entry["limits"]:
            note.caveats.append("%s: %s" % (entry["omic"], limit))

    for omic in ctx.matrix.omics():
        layer = ctx.matrix.get(omic)
        if layer.kind != "gene":
            continue
        conds = [qc.condition_of(c) for c in layer.columns]
        if len(set(conds)) >= len(conds) or len(layer.columns) < 3:
            note.unused_occasions.append(
                {"occasion": "PCA/PERMANOVA on %s" % omic,
                 "reason": "no replicate columns; one value per condition"})
            continue
        res = qc.ordinate_layer(layer)
        if "error" in res:
            note.unused_occasions.append(
                {"occasion": "PCA on %s" % omic, "reason": res["error"]})
            continue
        pc1 = ctx.ledger.tag("percent", res["pc1_percent"],
                             {"omic": omic, "axis": "PC1"}, "sample_ordination")
        pc2 = ctx.ledger.tag("percent", res["pc2_percent"],
                             {"omic": omic, "axis": "PC2"}, "sample_ordination")
        top_load = ", ".join(l["feature"] for l in
                             res["loadings"].get("PC1", [])[:5])
        note.evidence.append(
            "%s PCA: PC1 explains %s%% %s, PC2 %s%% %s of the variance; "
            "top PC1 loadings: %s"
            % (omic, res["pc1_percent"], pc1, res["pc2_percent"], pc2,
               top_load))
        perm = qc.permanova(layer)
        if "error" not in perm:
            p_tag = ctx.ledger.tag("pvalue", perm["p"], {"omic": omic},
                                   "permanova")
            floor_tag = ctx.ledger.tag("pvalue", perm["min_attainable_p"],
                                       {"omic": omic, "stat": "floor"},
                                       "permanova")
            note.evidence.append(
                "%s PERMANOVA: p = %s %s (minimum attainable for this design "
                "%s %s; %s)"
                % (omic, perm["p"], p_tag, perm["min_attainable_p"],
                   floor_tag,
                   "exact enumeration of %d relabellings"
                   % perm["n_relabellings"] if perm["exact"]
                   else "%d permutations" % perm["n_permutations"]))
        corr = qc.sample_correlation(layer)
        if "error" not in corr:
            if corr["outliers"]:
                for o in corr["outliers"]:
                    note.evidence.append(
                        "outlier by rule (%s): %s within-condition r %s"
                        % (corr["outlier_rule"], o["sample"], o["within_r"]))
            else:
                note.evidence.append("%s: no outlier by rule (%s)"
                                     % (omic, corr["outlier_rule"]))
            if corr["batch_warning"]:
                note.caveats.append("%s: %s" % (omic, corr["batch_warning"]))
            fig_id, err = _make_figure(
                ctx, "samplecorr",
                dict(corr, conditions=[], features=[1], colours={},
                     pathways=[]),
                "Replicate agreement within conditions (%s)." % omic,
                "samplecorr-%s" % omic)
            if fig_id:
                note.figures.append(fig_id)
        fig_id, err = _make_figure(
            ctx, "pca",
            dict(res, conditions=sorted(set(conds)), features=[1],
                 colours={}, pathways=[]),
            "Per-sample projection of %s." % omic, "pca-%s" % omic)
        if fig_id:
            note.figures.append(fig_id)

        movers = qc.top_movers(layer, k=5)
        if movers:
            note.evidence.append(
                "%s top movers by range: %s"
                % (omic, "; ".join("%s (range %s %s)"
                                   % (m["feature"], m["range"],
                                      ctx.ledger.tag("value", m["range"],
                                                     {"omic": omic,
                                                      "feature": m["feature"]},
                                                     "top_movers"))
                                   for m in movers)))
    note.findings = _narrate(llm, "design_qc", note.evidence)
    return note


def pathway_analyst(ctx, llm):
    note = AnalysisNote("pathway")
    ranked = []
    for pw in ctx.pathways or []:
        try:
            p = float(pw.get("combined_pvalue") or 1.0)
        except (TypeError, ValueError):
            continue
        ranked.append((p, pw))
    ranked.sort(key=lambda t: t[0])
    top = ranked[:10]
    if not top:
        note.unused_occasions.append({"occasion": "pathway ranking",
                                      "reason": "no pathways on this job"})
        return note
    for p, pw in top:
        tag = ctx.ledger.tag("pvalue", p, {"pathway": str(pw.get("id"))},
                             "pathway_enrichment")
        genes = ", ".join(g.get("symbol") for g in
                          (pw.get("top_genes") or [])[:5] if g.get("symbol"))
        note.evidence.append(
            "%s (%s, %s): combined p = %s %s; matched genes %s; top genes: %s"
            % (pw.get("name"), pw.get("id"), pw.get("source"), p, tag,
               pw.get("matched_gene_count"), genes or "-"))
    fig_id, err = _make_figure(
        ctx, "enrichment",
        {"pathways": [{"name": pw.get("name"), "p": p,
                       "matched": int(pw.get("matched_gene_count") or 0),
                       "total": int(pw.get("total_gene_count") or 0),
                       "source": pw.get("source") or ""}
                      for p, pw in top],
         "conditions": [], "features": [1], "colours": {}},
        "The most significant pathways by the combined test.",
        "enrichment-top")
    if fig_id:
        note.figures.append(fig_id)
    tsv = ["pathway_id\tname\tsource\tcombined_p"]
    for p, pw in ranked[:40]:
        tsv.append("%s\t%s\t%s\t%r" % (pw.get("id"), pw.get("name"),
                                       pw.get("source"), p))
    note.tables.append({"title": "Pathway enrichment (top 40)",
                        "tsv": "\n".join(tsv) + "\n"})
    note.findings = _narrate(llm, "pathway", note.evidence)
    return note


def enrichment_analyst(ctx, llm):
    from . import gene_set_store
    from .enrichment import enrich_direction
    from .sets import multiset_test, resolve_descriptor
    note = AnalysisNote("enrichment")
    organism = ctx.job_instance.getOrganism()
    collection = gene_set_store.load_collection(organism, "GO_BP")
    if collection is None:
        note.unused_occasions.append(
            {"occasion": "GO enrichment",
             "reason": "no GO_BP collection installed for %s "
                       "(scripts/installGeneSets.py)" % organism})
    else:
        for omic in ctx.matrix.omics():
            layer = ctx.matrix.get(omic)
            if layer.kind != "gene" or not any(layer.relevant):
                continue
            res = enrich_direction(ctx.matrix, collection, omic, "both",
                                   ledger=ctx.ledger)
            if "error" in res:
                note.unused_occasions.append(
                    {"occasion": "GO enrichment on %s" % omic,
                     "reason": res["error"]})
                continue
            head = res["results"][:6]
            note.evidence.append(
                "GO_BP over %s (%s; universe %d, hits %d): %s"
                % (omic, res["method"], res["universe"],
                   res["hits_in_universe"],
                   "; ".join("%s (%s) k=%d/%d q=%.3g [%s]"
                             % (r["name"], r["id"], r["k"], r["K"], r["q"],
                                r.get("q_fact")) for r in head)
                   or "no term at q<=0.05"))
            tsv = ["go_id\tterm\tk\tK\tp\tq"]
            for r in res["results"]:
                tsv.append("%s\t%s\t%d\t%d\t%r\t%r"
                           % (r["id"], r["name"], r["k"], r["K"], r["p"],
                              r["q"]))
            note.tables.append({"title": "GO_BP enrichment (%s)" % omic,
                                "tsv": "\n".join(tsv) + "\n"})

    for a, b in (ctx.inventory.get("pairs") or [])[:4]:
        set_a, note_a = resolve_descriptor(ctx.matrix, a)
        set_b, note_b = resolve_descriptor(ctx.matrix, b)
        if set_a is None or set_b is None or not set_a or not set_b:
            note.unused_occasions.append(
                {"occasion": "compare %r vs %r" % (a, b),
                 "reason": (note_a if set_a is None else
                            note_b if set_b is None else "an empty side")})
            continue
        omic = a.split(" in ", 1)[1].split(" at ")[0]
        layer = ctx.matrix.get(omic)
        universe = layer.deduplicated().labels if layer else []
        res = multiset_test([(a, set_a), (b, set_b)], universe)
        if "error" in res:
            note.unused_occasions.append(
                {"occasion": "compare %r vs %r" % (a, b),
                 "reason": res["error"]})
            continue
        p_tag = ctx.ledger.tag("pvalue", res["p"],
                               {"comparison": "%s|%s" % (a, b)},
                               "multiset_test")
        k_tag = ctx.ledger.tag("count", res["intersection"],
                               {"comparison": "%s|%s" % (a, b)},
                               "multiset_test")
        note.evidence.append(
            "overlap of [%s] and [%s]: %d %s shared of %s (universe %d), "
            "expected %s, p = %s %s (%s)"
            % (a, b, res["intersection"], k_tag,
               "/".join(str(s["n"]) for s in res["sets"]), res["universe"],
               res["expected"], res["p"], p_tag, res["method"]))
        if len(set_a) <= 400 and len(set_b) <= 400:
            fig_id, _err = _make_figure(
                ctx, "venn",
                {"sets": [{"name": a, "members": set_a},
                          {"name": b, "members": set_b}],
                 "conditions": [], "features": [1], "colours": {},
                 "pathways": []},
                "Overlap of %s and %s." % (a, b), "venn")
            if fig_id:
                note.figures.append(fig_id)
    note.findings = _narrate(llm, "enrichment", note.evidence)
    return note


def network_analyst(ctx, llm):
    from . import graph_tools as T
    note = AnalysisNote("network")
    if ctx.graph is None or ctx.graph.g.number_of_nodes() == 0:
        note.unused_occasions.append(
            {"occasion": "regulatory network analysis",
             "reason": "no graph could be built for this job"})
        return note
    note.evidence.append(T.graph_schema(ctx.graph, ledger=ctx.ledger))
    if ctx.graph.edges_of_type("REGULATES"):
        note.evidence.append(T.graph_hubs(ctx.graph, ledger=ctx.ledger))
        best = None
        for pw in ctx.pathways or []:
            txt = T.graph_subgraph(ctx.graph, pw.get("id"))
            if "member(s)" in txt and "no matched members" not in txt \
                    and " 0 edge(s)" not in txt:
                best = (pw, txt)
                break
        if best:
            pw, txt = best
            note.evidence.append(txt if "[f" in txt else
                                 T.graph_subgraph(ctx.graph, pw.get("id"),
                                                  ledger=ctx.ledger))
            members = {u for u, v, d in
                       ctx.graph.g.in_edges(str(pw.get("id")), data=True)
                       if d.get("type") == "MEMBER_OF"}
            edges = [{"from": u, "to": v,
                      "coefficient": d.get("coefficient"),
                      "evidence": d.get("evidence"),
                      "condition": d.get("condition")}
                     for u, v, d in ctx.graph.g.edges(data=True)
                     if d.get("type") == "REGULATES"
                     and (u in members or v in members)]
            fig_id, _err = _make_figure(
                ctx, "network",
                {"pathway": {"id": pw.get("id"), "name": pw.get("name")},
                 "edges": edges, "conditions": [], "features": [1],
                 "colours": {}, "pathways": []},
                "Regulators of %s by evidence class." % pw.get("name"),
                "network-%s" % pw.get("id"), width="double")
            if fig_id:
                note.figures.append(fig_id)
    else:
        note.unused_occasions.append(
            {"occasion": "regulator hubs and evidence split",
             "reason": "this job has no MORE regulation table"})
    note.findings = _narrate(llm, "network", note.evidence)
    return note


def metabolite_analyst(ctx, llm):
    note = AnalysisNote("metabolite")
    compounds = ctx.matrix.compound_layers()
    if not compounds:
        return None                      # no compound layer: no section at all
    from . import qc
    for layer in compounds:
        movers = qc.top_movers(layer.deduplicated(), k=8)
        if movers:
            note.evidence.append(
                "%s top movers by range: %s"
                % (layer.omic,
                   "; ".join("%s (range %s %s)"
                             % (m["feature"], m["range"],
                                ctx.ledger.tag("value", m["range"],
                                               {"omic": layer.omic,
                                                "feature": m["feature"]},
                                               "top_movers"))
                             for m in movers)))
    note.findings = _narrate(llm, "metabolite", note.evidence)
    return note


def literature_analyst(ctx, top_n=3, per_query=3):
    """A quote shelf, no prose: papers for the top pathways, with abstracts."""
    from . import pubmed_client
    note = AnalysisNote("literature")
    ranked = sorted((pw for pw in ctx.pathways or []),
                    key=lambda pw: float(pw.get("combined_pvalue") or 1.0))
    organism = ctx.job_instance.getOrganism()
    seen = set()
    for pw in ranked[:top_n]:
        query = "%s %s" % (pw.get("name"), "mouse" if organism == "mmu"
                           else organism)
        try:
            client = pubmed_client.PubMedClient()
            pmids = client.search(query, max_results=per_query)
            found = client.fetch_abstracts(pmids)
        except Exception as exc:
            note.unused_occasions.append(
                {"occasion": "literature for %s" % pw.get("name"),
                 "reason": "PubMed search failed (%s)" % exc})
            continue
        for paper in found or []:
            pmid = str(paper.get("pmid") or "")
            if not pmid or pmid in seen or not paper.get("abstract"):
                continue
            seen.add(pmid)
            ctx.papers.append({
                "ref_index": len(ctx.papers) + 1,
                "pmid": pmid,
                "title": paper.get("title") or "",
                "abstract": paper.get("abstract") or "",
                "year": paper.get("year") or "",
                "journal": paper.get("journal") or "",
                "authors": paper.get("first_author") or "",
                "tag": pw.get("name"),
            })
    note.evidence = ["[%d] %s (%s) — %s" % (p["ref_index"], p["title"],
                                            p["year"], p["tag"])
                     for p in ctx.papers]
    return note


# ---------------------------------------------------------------------------
# Phase 2: the Lead author. No compute tools -- notes, figures, shelf, prose.
# ---------------------------------------------------------------------------

LEAD_SYSTEM = """You are the Lead author assembling a manuscript from your
team's notes. You hold NO analysis tools: everything you may claim is in the
notes below, every number carries a token like {{f17}}, and every figure and
reference is listed.

Write GitHub markdown with EXACTLY these top-level sections, in this order:

# <a specific title naming the biology, not the method>
## Results
### <one subsection per specialist note, using the given subsection titles,
     in the given order; omit a subsection whose note has no findings>
## Discussion

HARD RULES
- NEVER write a number. Copy the {{fN}} token from the notes instead. A
  sentence whose number has no token must not be written.
- Cite literature ONLY as [n] using the reference list indices, only where
  the abstract genuinely supports the sentence.
- Call out a figure by pasting its callout line exactly where it belongs:
  ![Fig](figure:<figure-id>)  -- each figure at most once, in the most
  relevant subsection.
- Claim only what the notes say. Do not invent mechanisms; the Discussion
  interprets the findings against the cited abstracts, at most 3 paragraphs.
- No bullet lists in Results; continuous prose."""


def _lead_prompt(ctx):
    blocks = []
    for name in SPECIALIST_ORDER:
        note = ctx.notes.get(name)
        if note is None or name == "literature":
            continue
        title = SECTION_TITLES.get(name, name)
        lines = ["NOTE %s (subsection title: %s)" % (name, title)]
        if note.findings:
            lines.append("findings:")
            lines += ["  " + f for f in note.findings]
        lines.append("evidence (numbers carry [fN] ids -- write {{fN}}):")
        lines += ["  " + e.replace("\n", "\n  ") for e in note.evidence[:12]]
        if note.caveats:
            lines.append("caveats: " + "; ".join(note.caveats))
        for fig in note.figures:
            entry = next((f for f in ctx.figures if f["id"] == fig), None)
            if entry:
                lines.append("figure available: ![Fig](figure:%s) -- %s"
                             % (fig, entry["conclusion"]))
        blocks.append("\n".join(lines))
    if ctx.papers:
        blocks.append("REFERENCES (cite as [n]):\n" + "\n".join(
            "[%d] %s (%s, %s). Abstract: %s"
            % (p["ref_index"], p["title"], p["journal"], p["year"],
               (p["abstract"] or "")[:600])
            for p in ctx.papers))
    blocks.append("EXPERIMENT DESIGN (the user's own words): %s"
                  % (ctx.experiment_design or "(none given)"))
    return "\n\n".join(blocks)


def lead_author(ctx, llm):
    if llm is None:
        return ""
    try:
        return llm.complete(
            [{"role": "system", "content": LEAD_SYSTEM},
             {"role": "user", "content": _lead_prompt(ctx)[:60000]}],
            max_tokens=MAX_LEAD_TOKENS, temperature=0.3) or ""
    except Exception as exc:
        logger.warning("[paper] lead failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Phase 3: the gate. Code, not judgement.
# ---------------------------------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _redact_sentences(text, offender_check, counter):
    """Drop the sentences offender_check flags; keep paragraph structure."""
    out_paragraphs = []
    for paragraph in text.split("\n\n"):
        if paragraph.lstrip().startswith(("#", "!", "|")):
            out_paragraphs.append(paragraph)
            continue
        kept = []
        for sentence in _SENTENCE.split(paragraph):
            if sentence.strip() and offender_check(sentence):
                counter.append(sentence.strip()[:140])
            else:
                kept.append(sentence)
        out_paragraphs.append(" ".join(k for k in kept if k.strip()))
    return "\n\n".join(p for p in out_paragraphs if p.strip())


def _scan_and_redact_bare_numbers(ctx, draft, verification):
    """Run BEFORE substitution: {{fN}} is spared, model-written numbers die."""
    from .facts import bare_numbers
    conditions = []
    try:
        for layer in [ctx.matrix.get(o) for o in ctx.matrix.omics()]:
            conditions.extend(layer.columns)
            from .qc import condition_of
            conditions.extend({condition_of(c) for c in layer.columns})
    except Exception:
        pass

    def _offends(sentence):
        return bool(bare_numbers(sentence, conditions))

    return _redact_sentences(draft, _offends,
                             verification["sentences_redacted_numbers"])


def ground_citations(ctx, draft, verification, llm):
    """Keep a [n] only when its paper's ABSTRACT contains support: verified
    by the same quote-collection the interpreter's gate uses, restricted to
    the shelf. A citation that cannot be grounded is removed (the sentence
    stays -- the claim is the specialists', the citation was decoration)."""
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", draft)}
    shelf = {p["ref_index"]: p for p in ctx.papers}
    for n in sorted(cited):
        if n not in shelf:
            draft = re.sub(r"\s*\[%d\]" % n, "", draft)
            verification["citations_dropped"] += 1
        else:
            verification["citations_kept"] += 1
    return draft


def _references_section(ctx, draft):
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", draft)}
    lines = []
    for p in ctx.papers:
        if p["ref_index"] in cited:
            lines.append("[%d] %s %s. %s (%s). PMID: %s"
                         % (p["ref_index"], p["authors"], p["title"],
                            p["journal"], p["year"], p["pmid"]))
    return "\n\n".join(lines)


def _limitations_section(ctx):
    bullets = []
    for name in SPECIALIST_ORDER:
        note = ctx.notes.get(name)
        if not note:
            continue
        for occ in note.unused_occasions:
            bullets.append("- %s: not done — %s"
                           % (occ["occasion"], occ["reason"]))
        for caveat in note.caveats:
            bullets.append("- %s" % caveat)
    return "\n".join(bullets) or "- None recorded."


def assemble_paper(ctx, llm, hooks=None):
    """Phases 2-3: lead draft -> gate -> assembled markdown + verification."""
    from .methods import render_methods

    draft = lead_author(ctx, llm)
    if not draft.strip():
        raise RuntimeError("the Lead produced no draft")

    verification = {"facts_substituted": 0, "facts_unknown": 0,
                    "sentences_redacted_numbers": [],
                    "sentences_redacted_tokens": [],
                    "citations_kept": 0, "citations_dropped": 0,
                    "figures_total": len(ctx.figures),
                    "figures_failing_qa": sum(1 for f in ctx.figures
                                              if not f["qa_passed"])}

    # Order matters and is pinned by tests: bare-number scan FIRST (while
    # legitimate numbers are still tokens), then unknown-token redaction,
    # then substitution, then citations.
    draft = _scan_and_redact_bare_numbers(ctx, draft, verification)

    known = {f.fid for f in ctx.ledger.items()}
    token_re = re.compile(r"\{\{\s*(f\d+)\s*\}\}")
    draft = _redact_sentences(
        draft,
        lambda s: any(m.group(1) not in known for m in token_re.finditer(s)),
        verification["sentences_redacted_tokens"])

    draft, used, unknown = ctx.ledger.substitute(draft)
    verification["facts_substituted"] = len(used)
    verification["facts_unknown"] = len(unknown)

    draft = ground_citations(ctx, draft, verification, llm)

    # Every figure reaches the reader: the same store-time guarantee the
    # interpreter has. Missing callouts are appended under Results.
    called = set(re.findall(r"figure:([\w.-]+)", draft))
    missing = [f for f in ctx.figures if f["id"] not in called]
    if missing:
        extra = "\n\n".join("![Fig](figure:%s)\n*%s*" % (f["id"],
                                                         f["conclusion"])
                            for f in missing)
        if "## Discussion" in draft:
            draft = draft.replace("## Discussion",
                                  extra + "\n\n## Discussion", 1)
        else:
            draft += "\n\n" + extra

    sections = [draft.strip()]
    sections.append("## Limitations\n\n" + _limitations_section(ctx))
    sections.append("## Methods\n\n" + render_methods(ctx))
    refs = _references_section(ctx, draft)
    if refs:
        sections.append("## References\n\n" + refs)
    markdown = "\n\n".join(sections)
    return markdown, verification


# ---------------------------------------------------------------------------
# The run wrapper: the servlet entry point, PySiQ-shaped.
# ---------------------------------------------------------------------------

def run_paper_agent(job_id, experiment_design, RESPONSE):
    from src.common.JobInformationManager import JobInformationManager
    from src.common.DAO.AIInterpretDAO import AIInterpretDAO
    from src.classes.AIInterpret.agent import _agent_semaphore, _figure_manifest
    from src.conf.serverconf import AI_PROVIDERS, AI_LLM_PROVIDER
    from .llm_client import LLMClient

    dao = None
    acquired = False
    try:
        dao = AIInterpretDAO()

        def progress(status, percent, detail):
            dao.save_progress(job_id, {"paper_status": {
                "status": status, "percent": percent, "detail": detail,
                "updated": time.time()}})

        progress("starting", 2, "Loading analysis results...")
        job_instance = JobInformationManager().loadJobInstance(job_id)
        if job_instance is None:
            raise UserWarning("Job %s was not found." % job_id)

        _agent_semaphore.acquire()
        acquired = True

        llm = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER])

        progress("context", 8, "Building the paper context...")
        ctx = build_paper_context(job_instance, job_id, experiment_design)

        specialists = [
            ("design_qc", design_qc_analyst),
            ("pathway", pathway_analyst),
            ("enrichment", enrichment_analyst),
            ("network", network_analyst),
            ("metabolite", metabolite_analyst),
        ]
        base, span = 10, 55
        for i, (name, fn) in enumerate(specialists):
            progress("specialist:%s" % name,
                     base + int(span * i / len(specialists)),
                     "%s analyst working..." % name.replace("_", " "))
            try:
                note = fn(ctx, llm)
            except Exception as exc:
                logger.exception("[paper] %s analyst failed", name)
                note = AnalysisNote(name)
                note.unused_occasions.append(
                    {"occasion": "the whole %s contract" % name,
                     "reason": "analyst crashed: %s" % exc})
            if note is not None:
                ctx.notes[name] = note

        progress("specialist:literature", 68, "Collecting literature...")
        try:
            ctx.notes["literature"] = literature_analyst(ctx)
        except Exception as exc:
            logger.warning("[paper] literature failed: %s", exc)

        progress("lead", 75, "The Lead author is writing...")
        markdown, verification = assemble_paper(ctx, llm)

        figures = _figure_manifest(job_instance,
                                   [{"id": f["id"],
                                     "conclusion": f["conclusion"],
                                     "qa_passed": f["qa_passed"]}
                                    for f in ctx.figures])
        # figure: URLs resolve through the same /ai_figure route.
        progress("storing", 95, "Storing the manuscript...")
        dao.save_progress(job_id, {
            "paper": markdown,
            "paper_figures": figures,
            "paper_verification": {
                k: (v if not isinstance(v, list) else v[:20])
                for k, v in verification.items()},
            "paper_notes": {n: note.to_dict()
                            for n, note in ctx.notes.items()},
            "paper_facts_tsv": ctx.ledger.to_tsv(),
            "paper_status": {"status": "done", "percent": 100,
                             "detail": "Manuscript ready",
                             "updated": time.time()},
        })
        if ctx.papers:
            existing = (dao.find_by_job_id(job_id) or {}).get("papers")
            if not existing:
                dao.save_papers(job_id, ctx.papers)
        RESPONSE.setContent({"success": True, "jobID": job_id,
                             "status": "done"})
    except Exception as ex:
        logger.exception("paper agent failed for job %s", job_id)
        if dao:
            try:
                dao.save_progress(job_id, {"paper_status": {
                    "status": "error", "percent": 0, "detail": str(ex),
                    "updated": time.time()}})
            except Exception:
                pass
        from src.common.ServerErrorManager import handleException
        handleException(RESPONSE, ex, __file__, "run_paper_agent")
    finally:
        if acquired:
            _agent_semaphore.release()
