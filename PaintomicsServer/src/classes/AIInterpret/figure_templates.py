"""One pure function per figure archetype: (slice, spec) -> (data.tsv, figure.py).

No side effects, no matplotlib import here. Each builder returns two strings:
the exact data slice as TSV, and a **standalone** script that reads that TSV
from its own directory and draws the panel. Standalone is the point —
`figure-standards.md` requires that re-running the script regenerates the
figure, so the bundle a user downloads must not import this package. The house
style is therefore *rendered into* the script as a literal rcParams dict
(`figure_style.rc_params_source`) rather than imported by it.

Two invariants hold across every builder, and both are checked by
`figure_qa` afterwards rather than trusted here:

  * **Every number the script draws comes from data.tsv.** Nothing is
    recomputed in the legend text from a different source, so the figure and
    its caption cannot disagree.
  * **The colour map is decided from the data**, via
    `figure_style.colormap_for`, never from the request: a zero-centred
    diverging map on all-positive values is the heatmap defect this product
    already shipped once.

Determinism matters as much as correctness: the same slice and spec must
produce byte-identical outputs, so a figure can be regenerated and compared.
Nothing here iterates a set or a dict whose order is not fixed by the caller.
"""

from __future__ import annotations

from . import figure_style

# The panel label the standards ask for on every figure ("a", bold lowercase).
PANEL_LABEL = "a"


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------

def _row_id(feature):
    """The TSV's first column: unique per ROW, not per gene.

    A gene measured in two layers is two rows; keying them both on the symbol
    would make the values check compare a protein value against a transcript
    one. `Fos|Proteomics` is unique and still readable, and the scripts strip
    the suffix for display.
    """
    omic = feature.get("omic")
    return "%s|%s" % (feature["label"], omic) if omic else str(feature["label"])


def values_for(archetype, data_slice):
    """{row id: {column: float}} — what the TSV SHOULD contain, from the slice.

    Built from the slice by a different code path than the one that writes the
    file, so `figure_qa`'s "every value in data.tsv is the job's" check is a
    real comparison rather than a tautology: a builder that mangles a value on
    its way to disk disagrees with this.
    """
    if archetype == "enrichment":
        return {p.get("name"): {"p": float(p.get("p") or 1.0),
                                "matched": float(p.get("matched") or 0),
                                "total": float(p.get("total") or 0)}
                for p in data_slice.get("pathways") or []}
    features = data_slice.get("features") or []
    if archetype == "scatter":
        layers, by_label, order = [], {}, []
        for f in features:
            by_label.setdefault(f["label"], []).append(f)
            if f["label"] not in order:
                order.append(f["label"])
            if f.get("omic") and f["omic"] not in layers:
                layers.append(f["omic"])
        x_omic = layers[0] if layers else ""
        y_omic = layers[1] if len(layers) > 1 else ""
        out = {}
        for label in order:
            entries = {e.get("omic"): e for e in by_label[label]}
            xs = entries.get(x_omic, {}).get("values") or []
            ys = entries.get(y_omic, {}).get("values") or []
            if xs and ys:
                out[label] = {"x_mean": sum(xs) / len(xs),
                              "y_mean": sum(ys) / len(ys)}
        return out
    conditions = list(data_slice.get("conditions") or [])
    return {_row_id(f): dict(zip(conditions,
                                 [float(v) for v in f.get("values") or []]))
            for f in features}


def _tsv(header, rows):
    """A TSV block. `rows` are already stringified in the caller's order."""
    out = ["\t".join(str(h) for h in header)]
    for row in rows:
        out.append("\t".join(str(cell) for cell in row))
    return "\n".join(out) + "\n"


def _num(value):
    """A float rendered so the TSV round-trips exactly through float().

    `repr` keeps full double precision; `%f` would silently truncate the
    sixth decimal, and the QA check that compares data.tsv against the job's
    own values would then fail on the file's own rounding rather than on a
    real mismatch.
    """
    return repr(float(value))


def _legend(spec, what, extra=None):
    """The legend file: conclusion sentence first, then what/n/stats/scale.

    150-300 words is the standards' target for a published legend. What is
    generated here is the skeleton with everything the spec actually knows;
    the sentences that need the biology are the agent's to add in the report
    text, and the legend says so rather than inventing them.
    """
    lines = [str(spec.get("conclusion") or "").strip(), ""]
    lines.append("**What is shown.** %s" % what)
    n = spec.get("n")
    if n:
        lines.append("**n.** %s feature(s) drawn; every value is the job's own "
                     "per-condition value, reproduced in `data.tsv`." % n)
    if spec.get("test"):
        lines.append("**Statistics.** %s" % spec["test"])
    else:
        lines.append("**Statistics.** None computed for this panel: the values "
                     "are the measured per-condition values, not a test "
                     "statistic. Do not report a p-value from this figure.")
    lines.append("**Scale.** %s" % (extra or "Values are on the scale the job "
                                    "holds them in (log2 unless the upload "
                                    "says otherwise)."))
    lines.append("")
    lines.append("Regenerate with `python figure.py` in this directory "
                 "(requires matplotlib); `data.tsv` is the exact slice drawn.")
    return "\n".join(lines) + "\n"


def _preamble(spec, height_mm=None):
    """The head of every generated script: Agg, the style literal, the reader."""
    return '''#!/usr/bin/env python3
"""%s

Generated by PaintOmics AI. Self-contained on purpose: it reads data.tsv from
its own directory and needs nothing but matplotlib and the standard library,
so the figure can be regenerated by whoever receives the bundle.
"""
import csv
import os

import matplotlib
matplotlib.use("Agg")          # no display, and none wanted: this runs headless
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
plt.rcParams.update(%s)

PANEL_LABEL = %r


def read_tsv(name="data.tsv"):
    with open(os.path.join(HERE, name)) as fh:
        rows = list(csv.reader(fh, delimiter="\\t"))
    return rows[0], rows[1:]


def save(fig):
    for ext in ("svg", "pdf", "png"):
        fig.savefig(os.path.join(HERE, "figure." + ext))
    plt.close(fig)
''' % ((spec.get("conclusion") or "figure").replace('"""', "'''"),
       figure_style.rc_params_source(spec.get("width") or "single", height_mm),
       PANEL_LABEL)


def _panel_label(ax_expr="ax"):
    """The bold lowercase panel label, placed outside the axes at top left."""
    return ('%s.text(-0.12, 1.06, PANEL_LABEL, transform=%s.transAxes,\n'
            '        fontsize=%r, fontweight="bold", va="bottom", ha="left")\n'
            % (ax_expr, ax_expr, figure_style.PANEL_LABEL_PT))


# ---------------------------------------------------------------------------
# timecourse -- one line per feature across the job's conditions
# ---------------------------------------------------------------------------

def build_timecourse(data_slice, spec):
    conditions = list(data_slice.get("conditions") or [])
    features = list(data_slice.get("features") or [])
    header = ["feature"] + conditions
    rows = [[_row_id(f), *[_num(v) for v in f.get("values") or []]]
            for f in features]
    data = _tsv(header, rows)

    # Colour by FEATURE here (the conditions are the x axis), from the same
    # palette, so a reader who has seen the heatmap recognises the ink.
    script = _preamble(spec) + '''

def main():
    header, rows = read_tsv()
    conditions = header[1:]
    palette = %r
    fig, ax = plt.subplots()
    x = list(range(len(conditions)))
    for i, row in enumerate(rows):
        label, values = row[0].split("|")[0], [float(v) for v in row[1:]]
        ax.plot(x, values, marker="o", color=palette[i %% len(palette)],
                label=label)
    ax.set_xticks(x)
    ax.set_xticklabels(conditions, rotation=45, ha="right")
    ax.set_ylabel("value")
    # Individual points are already drawn (marker="o"): the standards ask for
    # them whenever n < 10, and a time course has no error bar to hide behind.
    if len(rows) <= 8:
        ax.legend(loc="best", ncol=1)
    else:
        ax.legend(loc="best", ncol=2, fontsize=%r)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (list(figure_style.PALETTE), figure_style.MIN_FONT_PT,
       _panel_label())
    legend = _legend(spec,
                     "One line per feature across the %d condition(s) of this "
                     "job, in the job's own column order; markers are the "
                     "measured values, not a fit." % len(conditions))
    return data, script, legend


# ---------------------------------------------------------------------------
# heatmap -- features x conditions
# ---------------------------------------------------------------------------

def build_heatmap(data_slice, spec):
    conditions = list(data_slice.get("conditions") or [])
    features = list(data_slice.get("features") or [])
    header = ["feature"] + conditions
    rows = [[_row_id(f), *[_num(v) for v in f.get("values") or []]]
            for f in features]
    data = _tsv(header, rows)

    has_negative = any(float(v) < 0 for f in features
                       for v in f.get("values") or [])
    cmap, centre_zero = figure_style.colormap_for(has_negative,
                                                  spec.get("centre_zero"))
    # Recorded back onto the spec so figure_qa checks the bundle against the
    # decision the DATA forced, not against what the caller asked for.
    spec["centre_zero"] = centre_zero
    spec["cmap"] = cmap

    script = _preamble(spec) + '''

def main():
    header, rows = read_tsv()
    conditions = header[1:]
    labels = [r[0].replace("|", " ") for r in rows]
    matrix = [[float(v) for v in r[1:]] for r in rows]
    flat = [v for row in matrix for v in row]
    fig, ax = plt.subplots()
    kwargs = {"cmap": %r, "aspect": "auto"}
    if %r:
        # Signed data only: a symmetric range so zero sits at the midpoint of
        # a diverging map. On single-signed data this branch is never taken.
        bound = max(abs(min(flat)), abs(max(flat))) or 1.0
        kwargs["vmin"], kwargs["vmax"] = -bound, bound
    im = ax.imshow(matrix, **kwargs)
    ax.set_xticks(range(len(conditions)))
    ax.set_xticklabels(conditions, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.ax.tick_params(labelsize=%r)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (cmap, bool(centre_zero), figure_style.MIN_FONT_PT, _panel_label())
    legend = _legend(
        spec,
        "%d feature(s) (rows) across %d condition(s) (columns), in the job's "
        "own order." % (len(features), len(conditions)),
        "Colour is %s%s." % (cmap,
                             ", centred on zero because the slice carries both "
                             "signs" if centre_zero else
                             ", a sequential map because every value has the "
                             "same sign"))
    return data, script, legend


# ---------------------------------------------------------------------------
# enrichment -- -log10(p) bars for the significant pathways
# ---------------------------------------------------------------------------

def build_enrichment(data_slice, spec):
    pathways = list(data_slice.get("pathways") or [])
    # Text columns would be read as conditions by the QA parser (and are not
    # data anyway): the source goes in the legend, not the table.
    header = ["pathway", "p", "matched", "total"]
    rows = [[p.get("name"), _num(p.get("p") or 1.0),
             _num(p.get("matched") or 0), _num(p.get("total") or 0)]
            for p in pathways]
    data = _tsv(header, rows)

    script = _preamble(spec, height_mm=max(50.0, 6.0 * len(rows) + 20.0)) + '''

def main():
    import math
    header, rows = read_tsv()
    # Strongest at the TOP: a reader's eye starts there, and the bar order is
    # the claim. Ties keep the file's order, so the figure is deterministic.
    rows = sorted(rows, key=lambda r: float(r[1]))
    names = [r[0] for r in rows][::-1]
    scores = [-math.log10(max(float(r[1]), 1e-300)) for r in rows][::-1]
    counts = ["%%d/%%d" %% (float(r[2]), float(r[3])) for r in rows][::-1]
    fig, ax = plt.subplots()
    y = list(range(len(names)))
    ax.barh(y, scores, color=%r, height=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.set_xlabel("-log10(combined p)")
    for i, (score, count) in enumerate(zip(scores, counts)):
        ax.text(score, i, " " + count, va="center", ha="left", fontsize=%r)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (figure_style.SIGNIFICANT_COLOUR, figure_style.MIN_FONT_PT,
       _panel_label())
    legend = _legend(
        spec,
        "The %d pathway(s) clearing p < 0.05, as -log10 of the combined "
        "p-value; the label at the end of each bar is matched/total features."
        % len(pathways),
        "The p-value is the job's own combined (Fisher) p across omic layers; "
        "no correction beyond what the job applied is added here.")
    return data, script, legend


# ---------------------------------------------------------------------------
# scatter -- two omic layers on one feature set
# ---------------------------------------------------------------------------

def build_scatter(data_slice, spec):
    """One point per feature: layer A on x, layer B on y, per condition mean.

    The two layers are taken in the order they appear in the slice, which is
    the job's order; a feature carried by only one layer cannot be a point and
    is left out, counted in the legend rather than dropped in silence.
    """
    features = list(data_slice.get("features") or [])
    by_label = {}
    order = []
    for f in features:
        by_label.setdefault(f["label"], []).append(f)
        if f["label"] not in order:
            order.append(f["label"])
    layers = []
    for f in features:
        if f.get("omic") and f["omic"] not in layers:
            layers.append(f["omic"])
    x_omic = layers[0] if layers else ""
    y_omic = layers[1] if len(layers) > 1 else ""

    header = ["feature", "x_mean", "y_mean"]
    rows, dropped = [], 0
    for label in order:
        entries = {e.get("omic"): e for e in by_label[label]}
        xs = entries.get(x_omic, {}).get("values") or []
        ys = entries.get(y_omic, {}).get("values") or []
        if not xs or not ys:
            dropped += 1
            continue
        rows.append([label, _num(sum(xs) / len(xs)),
                     _num(sum(ys) / len(ys))])
    data = _tsv(header, rows)

    script = _preamble(spec) + '''

def main():
    header, rows = read_tsv()
    labels = [r[0] for r in rows]
    xs = [float(r[1]) for r in rows]
    ys = [float(r[2]) for r in rows]
    fig, ax = plt.subplots()
    ax.scatter(xs, ys, color=%r, s=12, edgecolor="none")
    if xs and ys:
        lo = min(min(xs), min(ys))
        hi = max(max(xs), max(ys))
        # Identity line: the reference a reader needs to see concordance, drawn
        # in grey so it never reads as a fit.
        ax.plot([lo, hi], [lo, hi], color="#999999", linewidth=0.6, zorder=0)
        # Label the outliers only -- every point labelled is an unreadable
        # panel, and the standards fail a figure whose text collides.
        spread = sorted(range(len(xs)), key=lambda i: -abs(ys[i] - xs[i]))
        for i in spread[:6]:
            ax.annotate(labels[i], (xs[i], ys[i]), fontsize=%r,
                        xytext=(2, 2), textcoords="offset points")
    ax.set_xlabel(%r)
    ax.set_ylabel(%r)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (figure_style.PALETTE[0], figure_style.MIN_FONT_PT,
       x_omic or "layer A", y_omic or "layer B", _panel_label())
    legend = _legend(
        spec,
        "One point per feature measured in both layers (%s on x, %s on y), "
        "each the mean across conditions; the grey line is identity, and only "
        "the six largest departures from it are labelled.%s"
        % (x_omic or "layer A", y_omic or "layer B",
           " %d feature(s) carried by only one layer are not shown." % dropped
           if dropped else ""))
    return data, script, legend
