"""`make_figure` — the agent asks for a figure; this resolves, draws and checks it.

A report of this pipeline has never carried a figure. Every stored run of the
corpus program says so in its own words ("figures: none — the agent has no
figure path; every claim is text-only", 9 of 9 dev studies), and a Results
section without one is not a Results section.

The rule that shapes this module: **the model never supplies a number and
never writes plotting code.** It names an archetype and a slice of data it
already has the right to see — genes, a pathway, a cluster — and this module
resolves that slice from the job itself, writes the data out, generates a
deterministic script, runs it in a subprocess sandbox, and checks the result
against `figure-standards.md` before it says the figure exists. So "every
number on a figure is a data claim" is satisfied by construction rather than
by a second verification pass: there is no path by which a value the job does
not hold can reach the canvas.

What the agent gets back is a short markdown block: the figure id, a callout
sentence, the legend skeleton, and the QA verdict. A figure that FAILS QA is
still stored and still returned, with its failures named — the corpus program
exists to see how the thing fails, and a silently dropped figure teaches
nobody. `GAPS.md` collects the failures across runs.

Budget: `FIGURE_CAP` per run, `RENDER_TIMEOUT` per figure, both reported when
they bite (a silent cap reads as "the agent chose not to make more").

The bundle, under the job's own output directory so the existing
`/CLIENT_TMP/<...>` route can serve it with no new plumbing::

    output/figures/<fig-id>/figure.svg  figure.pdf  figure.png
                            figure.py   data.tsv    legend.md
                            render.log  qa.json
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# One report's worth. Eight panels is already a large Results section; the cap
# exists so a loop cannot spend its whole budget drawing.
FIGURE_CAP = 8
RENDER_TIMEOUT = 90

# ---------------------------------------------------------------------------
# The archetype registry. An archetype is a pair of functions:
#
#   builder(data_slice, spec) -> (data_tsv, script, legend)
#   values_for(data_slice)    -> {row_id: {column: float}}
#
# `values_for` re-derives what the TSV should contain BY A DIFFERENT PATH than
# the builder that writes it, which is what makes figure_qa's "every value on
# the canvas is the job's" check a comparison instead of a tautology. Every
# new figure kind -- network, pca, venn, nes_dotplot -- registers here and
# gets the whole pipeline (sandbox render, QA, store-time guarantee, cap)
# without touching it. `ARCHETYPES` stays a module attribute because the
# make_figure tool validates against it; it is rebuilt on every registration.
# ---------------------------------------------------------------------------

_REGISTRY = {}

ARCHETYPES = ()


def register_archetype(name, builder, values_for):
    """Add (or re-affirm) one archetype. Collisions with a DIFFERENT builder
    are refused: two modules silently fighting over a name would make the
    rendered figure depend on import order."""
    global ARCHETYPES
    key = str(name).strip().lower()
    if not key:
        raise ValueError("an archetype needs a name")
    if not callable(builder) or not callable(values_for):
        raise ValueError("archetype %r needs callable (builder, values_for)"
                         % key)
    existing = _REGISTRY.get(key)
    if existing is not None and (existing[0] is not builder
                                 or existing[1] is not values_for):
        raise ValueError("archetype %r is already registered with a "
                         "different builder" % key)
    _REGISTRY[key] = (builder, values_for)
    ARCHETYPES = tuple(_REGISTRY)


def archetype_names():
    return tuple(_REGISTRY)


def _archetype(name):
    entry = _REGISTRY.get(str(name).strip().lower())
    if entry is None:
        raise KeyError("unknown archetype %r (registered: %s)"
                       % (name, ", ".join(_REGISTRY) or "none"))
    return entry

# Kept in one place because three different callers need to agree on it.
_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text, limit=32):
    """A readable, bounded id for a figure directory.

    Bounded because it becomes a path component; cut at the last word boundary
    inside the limit rather than mid-word, so `fig3-cholesterol-biosynthesis`
    beats `fig3-cholesterol-biosynthesis-ris` in a run log a human has to read.
    """
    slug = _SLUG.sub("-", str(text).strip().lower()).strip("-")
    if len(slug) > limit:
        cut = slug[:limit]
        slug = cut.rsplit("-", 1)[0] if "-" in cut[1:] else cut
    return slug.strip("-") or "figure"


# ---------------------------------------------------------------------------
# Resolving what the agent named into values the job actually holds.
# ---------------------------------------------------------------------------

def _conditions(job_instance):
    """The condition labels, in the job's own column order.

    Reuses the context builder's header map so a figure axis and a sentence in
    the report cannot disagree about what a condition is called -- including
    the rule that a label is only shortened while it stays unique.
    """
    from .context_builder import _build_omic_header_map
    header_map = _build_omic_header_map(job_instance) or {}
    for labels in header_map.values():
        if labels:
            return list(labels)
    return []


def resolve_genes(job_instance, symbols, omics=None):
    """[{id,label,omic,values}] for named genes, plus the ones not found.

    Symbol resolution reuses `gene_measurements` -- the same accessor the
    agent's own tool reads, so a figure can only show genes the agent could
    have quoted -- but the VALUES are read raw from the job, never from the
    rendered profile string. That string is what the agent sees, and it is
    lossy in two ways that a figure must not inherit: it rounds to two
    decimals, and above twelve conditions it prints first-three + peak +
    last-three with an ellipsis. Plotting the rendered form would silently
    drop conditions from a long design and call the result the data.

    Symbols that do not resolve are returned rather than dropped: absent and
    unchanged are different facts, and a figure drawn from six of the ten
    genes asked for, silently, is a misleading figure.
    """
    from .context_builder import gene_measurements
    found, missing = gene_measurements(job_instance, list(symbols or []))
    genes = job_instance.getInputGenesData() or {}
    wanted = {str(o).strip().lower() for o in (omics or []) if str(o).strip()}
    rows = []
    for entry in found:
        gene = genes.get(entry.get("id"))
        if gene is None:
            missing.append(str(entry.get("symbol")))
            continue
        symbol = entry.get("symbol")
        for ov in (gene.getOmicsValues() or []):
            omic = ov.getOmicName() or "omic"
            if wanted and omic.strip().lower() not in wanted:
                continue
            values = ov.getValues()
            if not values:
                continue
            try:
                numeric = [float(v) for v in values]
            except (TypeError, ValueError):
                # A non-numeric cell is a fact about the upload, not something
                # to guess a value for; the layer is skipped and the caller
                # sees fewer rows than it asked for.
                continue
            rows.append({"id": "%s|%s" % (symbol, omic), "label": symbol,
                         "omic": omic, "values": numeric})
    return rows, missing


def resolve_pathway(ctx, pathway_id):
    """One pathway's context dict from the run's own ranked list."""
    for pw in ctx.pathways or []:
        if str(pw.get("id")) == str(pathway_id):
            return pw
    return None


def resolve_pathway_genes(job_instance, pathway, limit=40):
    """The matched genes of one pathway, as figure rows."""
    symbols = []
    for gene in (pathway.get("top_genes") or []):
        symbol = gene.get("symbol")
        if symbol:
            symbols.append(symbol)
    if not symbols:
        symbols = [str(s) for s in (pathway.get("matched_genes") or [])]
    rows, _missing = resolve_genes(job_instance, symbols[:limit])
    return rows


def resolve_enrichment(ctx, limit=15):
    """The significant pathways, strongest first, for a bar figure."""
    rows = []
    for pw in ctx.pathways or []:
        try:
            p = float(pw.get("combined_pvalue") or 1.0)
        except (TypeError, ValueError):
            continue
        if p >= 0.05:
            continue
        rows.append({"name": pw.get("name") or pw.get("id"),
                     "p": p,
                     "matched": int(pw.get("matched_genes_count") or
                                    len(pw.get("top_genes") or [])),
                     "total": int(pw.get("total_genes") or 0),
                     "source": pw.get("source") or ""})
    rows.sort(key=lambda r: r["p"])
    return rows[:limit]


# ---------------------------------------------------------------------------
# Building one bundle.
# ---------------------------------------------------------------------------

def _bundle_dir(job_instance, fig_id):
    base = os.path.join(job_instance.getOutputDir(), "figures", fig_id)
    os.makedirs(base, exist_ok=True)
    return base


class EmptyFigure(Exception):
    """No row survived the slice -- there is nothing to draw."""


def _empty_reason(archetype, data_slice):
    """Say which way the slice came out empty, in terms the agent can act on."""
    n = len((data_slice or {}).get("features") or [])
    if archetype == "scatter":
        return ("a scatter needs features measured in BOTH layers, and none of "
                "the %d you named are in both. Name features that carry a value "
                "in each layer, or use timecourse/heatmap for a single layer." % n)
    if archetype == "enrichment":
        return ("no pathway in this slice has the counts an enrichment panel "
                "needs. Name pathways from the enrichment results.")
    if not n:
        return ("no feature in this job matched the ones you named, so there is "
                "nothing to draw. Check the names against the data tools' output.")
    return ("the %d feature(s) you named carry no values in the conditions of "
            "this slice, so there is nothing to draw." % n)


def build_bundle(job_instance, fig_id, archetype, data_slice, spec):
    """Write data.tsv + figure.py, render, QA. Returns (bundle_dir, qa, result)."""
    from . import figure_qa, figure_sandbox

    builder, _values_for = _archetype(archetype)
    data_tsv, script, legend = builder(data_slice, spec)

    # An empty panel is worse than no panel: the store-time guarantee shows
    # every figure to the reader, so a bundle with a header and no rows is
    # now certain to reach them. It happened for real -- a scatter over ten
    # genes where not one was measured in BOTH layers, rendered as 23 kB of
    # empty axes. Refuse here, where the agent can still choose differently,
    # instead of letting QA report it after the slot is spent.
    if len([r for r in (data_tsv or "").strip().splitlines()[1:] if r.strip()]) == 0:
        raise EmptyFigure(_empty_reason(archetype, data_slice))

    bundle = _bundle_dir(job_instance, fig_id)
    with open(os.path.join(bundle, "data.tsv"), "w") as fh:
        fh.write(data_tsv)
    with open(os.path.join(bundle, "figure.py"), "w") as fh:
        fh.write(script)
    # Written here rather than by the script: the legend must exist even when
    # the render dies, so a failed figure still says what it was going to show.
    with open(os.path.join(bundle, "legend.md"), "w") as fh:
        fh.write(legend)

    result = figure_sandbox.render(bundle, timeout=RENDER_TIMEOUT)
    # From the SLICE, by a different code path than the writer -- so the check
    # "every value in data.tsv is the job's" compares two derivations instead
    # of comparing the file with itself.
    values = _values_for(data_slice)
    passed, lines = figure_qa.check(bundle, spec, values)
    with open(os.path.join(bundle, "qa.json"), "w") as fh:
        json.dump({"passed": passed, "checks": lines,
                   "render_ok": bool(getattr(result, "ok", False)),
                   "seconds": getattr(result, "seconds", None)}, fh, indent=1)
    return bundle, (passed, lines), result


def figure_block(fig_id, index, spec, passed, lines, result, note=""):
    """The markdown the agent reads back — a callout it can paste, and the truth."""
    out = ["**Fig. %d** — %s" % (index, spec.get("conclusion") or ""),
           "id: `%s`  ·  archetype: %s" % (fig_id, spec.get("archetype")),
           "callout to paste in the report: `![Fig. %d](figure:%s)`" % (index, fig_id)]
    if not getattr(result, "ok", False):
        out.append("RENDER FAILED (%s) — the bundle is stored with render.log; "
                   "say so in the report rather than citing this figure."
                   % (getattr(result, "stderr_tail", "") or "no stderr")[:200])
    out.append("QA: %s" % ("passes" if passed else "FAILS"))
    if not passed:
        out.extend("  - %s" % line for line in lines if "FAIL" in line.upper())
    if note:
        out.append(note)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The four built-in archetypes. Registered at import so ARCHETYPES is complete
# before any tool validates against it; the partial binds the archetype name
# into figure_templates' shared values_for.
# ---------------------------------------------------------------------------

def _register_builtins():
    import functools
    from . import figure_templates as t
    for name, builder in (("timecourse", t.build_timecourse),
                          ("heatmap", t.build_heatmap),
                          ("enrichment", t.build_enrichment),
                          ("scatter", t.build_scatter)):
        register_archetype(name, builder,
                           functools.partial(t.values_for, name))
    from . import figure_network as n
    register_archetype("network", n.build_network, n.values_for_network)


_register_builtins()
