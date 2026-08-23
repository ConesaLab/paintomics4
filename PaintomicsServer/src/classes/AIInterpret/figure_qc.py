"""`pca` and `samplecorr` archetypes — the QC panels a paper opens with.

`pca`: one point per sample on PC1/PC2, coloured by condition, the explained
variance on each axis label. The slice carries the coordinates the QC module
computed from the job plus the raw percentages; `values_for` re-derives its
dict from the same slice by a separate path, so a writer that mangles a
coordinate on its way to disk disagrees with QA.

`samplecorr`: the sample x sample Pearson matrix as a heatmap, samples in
column order, the colourbar honest about its range (correlations plotted on
[-1, 1] only when negative values exist; [min, 1] otherwise -- an all-0.9
matrix painted on [-1, 1] hides the structure the panel exists to show).
"""
from __future__ import annotations

from . import figure_style
from .figure_templates import _legend, _num, _preamble, _tsv


def build_pca(data_slice, spec):
    samples = list(data_slice.get("samples") or [])
    header = ["sample", "pc1", "pc2"]
    rows = [[s.get("name"), _num(s.get("pc1")), _num(s.get("pc2"))]
            for s in samples]
    data = _tsv(header, rows)

    conditions = []
    for s in samples:
        c = s.get("condition") or "?"
        if c not in conditions:
            conditions.append(c)
    pc1 = float(data_slice.get("pc1_percent") or 0.0)
    pc2 = float(data_slice.get("pc2_percent") or 0.0)

    # Past a dozen samples, per-point name labels are what fails QA: 48
    # replicate names cannot avoid each other on one panel, and a paper's
    # PCA identifies groups by colour, not by naming every point.
    annotate_names = len(samples) <= 12

    script = _preamble(spec) + '''

ANNOTATE_NAMES = %r
CONDITIONS = %r
PALETTE = %r
PC1_PERCENT = %r
PC2_PERCENT = %r


def condition_of(name):
    idx = name.rfind("_rep")
    return name[:idx] if idx > 0 else name


def main():
    header, rows = read_tsv()
    fig, ax = plt.subplots()
    for i, cond in enumerate(CONDITIONS):
        xs = [float(r[1]) for r in rows if condition_of(r[0]) == cond]
        ys = [float(r[2]) for r in rows if condition_of(r[0]) == cond]
        ax.scatter(xs, ys, s=55, color=PALETTE[i %% len(PALETTE)],
                   label=cond, edgecolors="white", linewidths=0.6, zorder=3)
    if ANNOTATE_NAMES:
        for r in rows:
            ax.annotate(r[0], (float(r[1]), float(r[2])),
                        textcoords="offset points", xytext=(0, 6),
                        ha="center", fontsize=%r)
    ax.set_xlabel("PC1 (%%.1f%%%% of variance)" %% PC1_PERCENT)
    ax.set_ylabel("PC2 (%%.1f%%%% of variance)" %% PC2_PERCENT)
    ax.axhline(0, color="#cccccc", lw=0.6, zorder=1)
    ax.axvline(0, color="#cccccc", lw=0.6, zorder=1)
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=%r,
              borderaxespad=0.0)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (annotate_names, conditions, list(figure_style.PALETTE), pc1, pc2,
       figure_style.MIN_FONT_PT, figure_style.MIN_FONT_PT, _panel_label_src())

    spec = dict(spec, n=len(samples))
    legend = _legend(
        spec,
        "One point per sample, projected on the first two principal "
        "components of the %d most-variable complete features; PC1 explains "
        "%.1f%% of the variance, PC2 %.1f%%. Colour is the sample's "
        "condition; the coordinates are in data.tsv."
        % (int(data_slice.get("n_features") or 0), pc1, pc2),
        extra="Centred, unscaled PCA by SVD; axes are score units, not "
              "percentages.")
    return data, script, legend


def values_for_pca(data_slice):
    return {str(s.get("name")): {"pc1": float(s.get("pc1") or 0.0),
                                 "pc2": float(s.get("pc2") or 0.0)}
            for s in (data_slice.get("samples") or [])}


def build_samplecorr(data_slice, spec):
    names = [str(n) for n in (data_slice.get("samples") or [])]
    matrix = data_slice.get("matrix") or []
    header = ["sample"] + names
    rows = [[names[i]] + [_num(v) for v in matrix[i]]
            for i in range(len(names))]
    data = _tsv(header, rows)

    # The house sequential map, same as the heatmap archetype: correlations
    # here are almost always single-signed, and the palette check holds the
    # whole report to one ramp.
    flat = [v for row in matrix for v in row]
    cmap, _centre = figure_style.colormap_for(bool(flat and min(flat) < 0))
    # Every sample name is a y tick: give each row its own vertical room, as
    # the heatmap archetype does, or 48 replicate labels land on each other.
    height_mm = max(100.0, 3.2 * len(names) + 30.0)
    if len(names) > 16 and (spec.get("width") or "single") == "single":
        spec = dict(spec, width="double")
    script = _preamble(spec, height_mm=height_mm) + '''

def main():
    header, rows = read_tsv()
    names = header[1:]
    M = [[float(v) for v in r[1:]] for r in rows]
    flat = [v for row in M for v in row]
    vmin = -1.0 if min(flat) < 0 else min(flat)
    fig, ax = plt.subplots()
    im = ax.imshow(M, vmin=vmin, vmax=1.0, cmap=%r)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=%r)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=%r)
    bar = fig.colorbar(im, ax=ax, shrink=0.8)
    bar.set_label("Pearson r")
    bar.ax.tick_params(labelsize=%r)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (cmap, figure_style.MIN_FONT_PT, figure_style.MIN_FONT_PT,
       figure_style.MIN_FONT_PT, _panel_label_src())

    spec = dict(spec, n=len(names))
    legend = _legend(
        spec,
        "Pearson correlation between every pair of samples over the "
        "most-variable complete features, samples in the job's own column "
        "order. The full matrix is data.tsv.",
        extra="The colour scale starts at the smallest observed correlation "
              "(or -1 when negative correlations exist), not at -1 by "
              "default: an all-positive matrix painted on [-1, 1] hides its "
              "structure.")
    return data, script, legend


def values_for_samplecorr(data_slice):
    names = [str(n) for n in (data_slice.get("samples") or [])]
    matrix = data_slice.get("matrix") or []
    return {names[i]: {names[j]: float(matrix[i][j])
                       for j in range(len(names))}
            for i in range(len(names))}


def _panel_label_src():
    from .figure_templates import _panel_label
    return _panel_label()
