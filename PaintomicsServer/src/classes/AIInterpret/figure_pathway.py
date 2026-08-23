"""`pathway_diagram` — the pathway PAINTED, cropped to the region under discussion.

Why this exists
---------------
The first reader of a Paper-agent manuscript said it plainly: when the text
explains a pathway, show THAT pathway, painted, zoomed to the region the
sentences are about — not a bar chart about it. PaintOmics' own KEGG diagrams
and per-gene box geometry are already on disk (the Mongo pathway document
stores each gene's x/y/width/height; the PNG lives under
`KEGG_DATA/current/common/png/`), so the figure is a composition, not a new
renderer: the base map, a coloured box per matched gene, and a crop chosen
from the genes the narrative names.

The slice carries ONLY job numbers (one value per painted gene) plus the box
geometry copied from the installed pathway document; the base PNG is copied
INTO the bundle so `python figure.py` reproduces the panel offline. KGML
x/y are box centres, so boxes are drawn centred — the same convention the
interactive view paints with.
"""
from __future__ import annotations

import os
import shutil

from . import figure_style
from .figure_templates import _legend, _num, _preamble, _tsv

MAX_PAINTED = 60          # a diagram with every box coloured is decoration
CROP_PAD = 60             # pixels of context around the named genes


def _row_id(box):
    return "%s|%s|%s|%s|%s" % (box["label"], box["x"], box["y"],
                               box["w"], box["h"])


def build_pathway_diagram(data_slice, spec):
    boxes = list(data_slice.get("boxes") or [])[:MAX_PAINTED]
    png_source = data_slice.get("png_path") or ""
    if not boxes or not png_source or not os.path.isfile(png_source):
        from .figures import EmptyFigure
        raise EmptyFigure("no painted boxes or no diagram PNG for this "
                          "pathway; name a pathway whose diagram is installed")

    header = ["gene", "value"]
    rows = [[_row_id(b), _num(b.get("value"))] for b in boxes]
    data = _tsv(header, rows)

    values = [float(b.get("value") or 0.0) for b in boxes]
    has_negative = any(v < 0 for v in values)
    cmap, centre_zero = figure_style.colormap_for(has_negative,
                                                  spec.get("centre_zero"))
    spec = dict(spec, cmap=cmap, centre_zero=centre_zero)

    crop = data_slice.get("crop")          # [x0, y0, x1, y1] or None

    script = _preamble(spec, height_mm=120) + '''

CROP = %r
CMAP = %r
CENTRE_ZERO = %r
FONT_PT = %r


def main():
    header, rows = read_tsv()
    import matplotlib.image as mpimg
    import matplotlib.patches as patches
    base = mpimg.imread(os.path.join(HERE, "map.png"))
    boxes = []
    for gene_id, value in rows:
        label, x, y, w, h = gene_id.split("|")
        boxes.append((label, float(x), float(y), float(w), float(h),
                      float(value)))
    values = [b[5] for b in boxes]
    if CENTRE_ZERO:
        bound = max(abs(min(values)), abs(max(values))) or 1.0
        vmin, vmax = -bound, bound
    else:
        vmin, vmax = min(values), max(values) or 1.0
        if vmin == vmax:
            vmax = vmin + 1.0
    cmap = plt.get_cmap(CMAP)
    norm = plt.Normalize(vmin=vmin, vmax=vmax)

    fig, ax = plt.subplots()
    ax.imshow(base)
    # The base map already prints every gene's name inside its box; extra
    # labels exist only to flag the strongest signals. Label the top few by
    # |value|, alternating above/below so neighbours cannot collide.
    # Greedy spacing: a candidate too close to an already-labelled box is
    # skipped rather than drawn into it (Gnb4 sat directly above Gng5 on
    # mmu04725 and alternating sides could not save them).
    labelled_ids, placed = set(), []
    for b in sorted(boxes, key=lambda bb: -abs(bb[5])):
        if len(labelled_ids) >= 8:
            break
        if any(abs(b[1] - px) < 70 and abs(b[2] - py) < 34
               for px, py in placed):
            continue
        labelled_ids.add(b[0])
        placed.append((b[1], b[2]))
    side = 1
    for label, x, y, w, h, value in boxes:
        # KGML x/y are box centres.
        # rasterized: the painted boxes join the base map's raster layer in
        # the SVG, exactly as a heatmap's cells do -- the palette check
        # audits vector fills, and a colormap ramp is not the house palette.
        ax.add_patch(patches.Rectangle(
            (x - w / 2.0, y - h / 2.0), w, h,
            facecolor=cmap(norm(value)), edgecolor="#222222",
            linewidth=0.7, alpha=0.85, zorder=3, rasterized=True))
        if label in labelled_ids:
            above = side > 0
            side = -side
            ax.annotate(label,
                        (x, y - h / 2.0 - 2 if above else y + h / 2.0 + 2),
                        ha="center", va="bottom" if above else "top",
                        fontsize=FONT_PT, zorder=4,
                        bbox=dict(boxstyle="round,pad=0.12", fc="white",
                                  ec="none", alpha=0.8))
    if CROP:
        x0, y0, x1, y1 = CROP
        ax.set_xlim(x0, x1)
        ax.set_ylim(y1, y0)          # image coordinates: y grows downward
    ax.set_axis_off()
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    bar = fig.colorbar(sm, ax=ax, shrink=0.7)
    bar.set_label("strongest value across conditions")
    bar.ax.tick_params(labelsize=FONT_PT)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (crop, cmap, bool(centre_zero), figure_style.MIN_FONT_PT,
       _panel_label_src())

    pathway = data_slice.get("pathway") or {}
    what = ("The KEGG diagram of %s with each matched gene's box painted by "
            "the job's own value (each gene's strongest value across the "
            "conditions, sign preserved)%s. The base map and every painted "
            "value are reproduced in the bundle."
            % (pathway.get("name") or pathway.get("id") or "the pathway",
               ", cropped to the region the text discusses" if crop else ""))
    spec = dict(spec, n=len(boxes))
    legend = _legend(spec, what,
                     extra="Colour is %s%s; grey boxes on the base map are "
                           "unmatched features." %
                           (cmap, ", centred on zero" if centre_zero else ""))
    return data, script, legend, png_source


def values_for_pathway_diagram(data_slice):
    return {_row_id(b): {"value": float(b.get("value") or 0.0)}
            for b in (data_slice.get("boxes") or [])[:MAX_PAINTED]}


def _panel_label_src(ax_expr="ax"):
    from .figure_templates import _panel_label
    return _panel_label(ax_expr)
