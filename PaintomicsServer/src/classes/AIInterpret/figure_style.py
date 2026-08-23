"""The house style every figure this agent produces is drawn in.

One module so that a report's figures read as one set: same palette, same
type, same physical size, and — the part that is easy to lose — the same
colour for the same condition in every panel of a report.

The rules come from `figure-standards.md` (the corpus program's portable copy
of the Nature figure bar) and are stated here as data rather than prose so
`figure_qa` can check them:

  * **Size is physical, decided before anything is drawn.** 89 mm single
    column or 183 mm double. A figure sized in pixels and shrunk on the page
    is how 5 pt text becomes 3 pt text.
  * **Text never goes below 5 pt at final size**, target 6-7 pt, one typeface.
    Matplotlib's defaults are 10-12 pt on a 6x4 inch canvas; at 89 mm that is
    a different figure from the one you previewed.
  * **Colour is categorical unless the data is continuous.** The default set
    is Okabe-Ito, which stays distinguishable under the three common colour
    vision deficiencies; rainbow/jet is never used, and red-green alone never
    carries a distinction.
  * **A diverging map is for signed data only.** All-positive values on a
    zero-centred diverging map paint half the range in a colour that means
    "below the middle" — the heatmap defect that shipped in this product once
    already (`heatmap-colour-range-clamped-to-zero`).

Nothing here imports matplotlib: this module is read by the figure *builder*
(which writes a standalone script) and by `figure_qa` (which has no plotting
dependency at all). The rcParams live here as a plain dict and are rendered
into the generated script, so the script that ships in a figure bundle is
self-contained and reproduces the figure without this package.
"""

from __future__ import annotations

# --- Physical size -------------------------------------------------------
# Nature's two column widths, in millimetres, and the mm->inch factor
# matplotlib wants. Height is chosen per archetype but never exceeds
# MAX_HEIGHT_MM (a figure taller than the type area gets scaled down by the
# typesetter, which shrinks the text below the floor).
SINGLE_COLUMN_MM = 89.0
DOUBLE_COLUMN_MM = 183.0
MAX_HEIGHT_MM = 240.0
MM_PER_INCH = 25.4

WIDTHS_MM = {"single": SINGLE_COLUMN_MM, "double": DOUBLE_COLUMN_MM}

# --- Type ----------------------------------------------------------------
# One family, with a stack that degrades to whatever the host has. The floor
# is what figure_qa enforces on the rendered SVG; BASE_PT is what the script
# actually sets, chosen a point above the floor so a shrink of one point in
# an editor does not break the standard.
FONT_FAMILY = ["Helvetica", "Arial", "DejaVu Sans", "sans-serif"]
MIN_FONT_PT = 5.0
BASE_FONT_PT = 7.0
SMALL_FONT_PT = 6.0
PANEL_LABEL_PT = 8.0          # bold lowercase a, b, c

# --- Colour --------------------------------------------------------------
# Okabe-Ito, in the order that keeps the first two maximally distinct. Black
# is last on purpose: it reads as "the other one" and is better spent on a
# reference line than on the first series.
PALETTE = (
    "#0072B2",   # blue
    "#D55E00",   # vermillion
    "#009E73",   # bluish green
    "#CC79A7",   # reddish purple
    "#E69F00",   # orange
    "#56B4E9",   # sky blue
    "#F0E442",   # yellow
    "#000000",   # black
)

# Greys a plot may use for structure (axes, gridlines, unhighlighted points)
# without counting as a colour choice.
GREYS = ("#000000", "#333333", "#666666", "#999999", "#CCCCCC", "#E5E5E5",
         "#FFFFFF")

# Continuous data. `SEQUENTIAL` for all-positive or all-negative values,
# `DIVERGING` only when the slice actually has both signs — figure_qa fails a
# bundle whose spec asks for a zero-centred map on single-signed data.
SEQUENTIAL_CMAP = "viridis"
DIVERGING_CMAP = "RdBu_r"

# Never, under any spec: perceptually non-uniform, and jet in particular
# invents edges that are not in the data.
FORBIDDEN_CMAPS = ("jet", "rainbow", "hsv", "gist_rainbow", "nipy_spectral",
                   "flag", "prism")

SIGNIFICANT_COLOUR = PALETTE[1]      # the one thing a reader should find first
MUTED_COLOUR = "#999999"


def figure_size_inches(width="single", height_mm=None):
    """(w, h) in inches for matplotlib, from a physical width name.

    Defaults to the golden-ish 0.62 of the width, which keeps a single-column
    figure inside the type area and leaves room for the legend below it.
    """
    mm = WIDTHS_MM.get(str(width), SINGLE_COLUMN_MM)
    h = float(height_mm) if height_mm else mm * 0.62
    h = min(h, MAX_HEIGHT_MM)
    return (mm / MM_PER_INCH, h / MM_PER_INCH)


def condition_colours(conditions):
    """{condition: colour}, stable for the life of a run.

    The same condition must be the same colour in every figure of a report;
    assigning per figure is how panel b ends up disagreeing with panel a. The
    caller holds this dict on the run context and passes it to every build.
    Conditions beyond the palette cycle rather than fail — a 12-condition job
    exists (a genotype x diet x age design in the corpus) and a figure with
    repeated colours is a worse figure, not a crashed one, so the builder
    warns instead of raising.
    """
    out = {}
    for i, cond in enumerate(conditions or []):
        out[str(cond)] = PALETTE[i % len(PALETTE)]
    return out


def rc_params(width="single", height_mm=None):
    """The rcParams the generated script sets before it draws anything."""
    w, h = figure_size_inches(width, height_mm)
    return {
        "figure.figsize": [round(w, 4), round(h, 4)],
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        # Text as text in the vector outputs -- a figure whose labels are
        # paths cannot be corrected by a copy editor and fails the standards.
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.family": "sans-serif",
        "font.sans-serif": list(FONT_FAMILY),
        "font.size": BASE_FONT_PT,
        "axes.titlesize": BASE_FONT_PT,
        "axes.labelsize": BASE_FONT_PT,
        "xtick.labelsize": SMALL_FONT_PT,
        "ytick.labelsize": SMALL_FONT_PT,
        "legend.fontsize": SMALL_FONT_PT,
        "legend.frameon": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 2.0,
        "ytick.major.size": 2.0,
        "lines.linewidth": 1.0,
        "lines.markersize": 3.0,
        "axes.grid": False,
    }


def rc_params_source(width="single", height_mm=None):
    """The rcParams as a literal for the generated `figure.py`.

    Rendered rather than imported so a figure bundle stays self-contained:
    someone who receives `figure.py` + `data.tsv` can re-run it with nothing
    but matplotlib installed, which is what "re-running the script regenerates
    the figure" in the standards means.
    """
    items = rc_params(width, height_mm)
    lines = ["{"]
    for key in sorted(items):
        lines.append("    %r: %r," % (key, items[key]))
    lines.append("}")
    return "\n".join(lines)


def colormap_for(has_negative, centre_zero=None):
    """(cmap_name, centre_zero) for a heatmap, deciding from the DATA.

    `centre_zero` is an override the caller may pass; it is refused when the
    slice has no negative values, because a zero-centred diverging map on
    all-positive data is the defect this rule exists for. Returning the
    decision (rather than trusting the caller) is what lets figure_qa check
    the bundle against the data instead of against the request.
    """
    if has_negative:
        return DIVERGING_CMAP, True
    return SEQUENTIAL_CMAP, False
