"""`venn`, `upset` and `concordance` archetypes — comparisons drawn honestly.

venn (2-3 sets): exclusive region counts inside fixed circles. Above three
sets a Venn is unreadable and the builder says to use upset instead.

upset (2-6 sets): exclusive intersection sizes as bars over a membership dot
matrix -- the k-set picture a Venn cannot draw.

concordance (two layers): each shared relevant feature at (value_A, value_B),
quadrant counts and the agreement fraction stated on the panel. Direction
agreement is a claim about SIGNS, so the axes cross at zero by construction.

Every count is re-derived from the slice's member lists by `values_for`, so
QA compares the file against a second derivation, not against itself.
"""
from __future__ import annotations

import itertools

from . import figure_style
from .figure_templates import _legend, _num, _preamble, _tsv

MAX_VENN_SETS = 3
MAX_UPSET_SETS = 6


def _named_sets(data_slice, cap):
    named = []
    for entry in (data_slice.get("sets") or [])[:cap]:
        name = str(entry.get("name") or "set%d" % (len(named) + 1))
        named.append((name, {str(m).upper() for m in (entry.get("members") or [])}))
    return named


def _regions(named):
    """Exclusive region counts: {frozenset(names): count}."""
    out = {}
    all_names = [n for n, _v in named]
    for r in range(1, len(named) + 1):
        for combo in itertools.combinations(range(len(named)), r):
            inside = set.intersection(*[named[i][1] for i in combo])
            for i in range(len(named)):
                if i not in combo:
                    inside = inside - named[i][1]
            key = "&".join(all_names[i] for i in combo)
            out[key] = len(inside)
    return out


# ---------------------------------------------------------------- venn

def build_venn(data_slice, spec):
    named = _named_sets(data_slice, MAX_VENN_SETS)
    if len(data_slice.get("sets") or []) > MAX_VENN_SETS:
        raise ValueError("a Venn beyond %d sets is unreadable; use the upset "
                         "archetype" % MAX_VENN_SETS)
    regions = _regions(named)
    header = ["region", "count"]
    rows = [[k, _num(v)] for k, v in sorted(regions.items())]
    data = _tsv(header, rows)

    names = [n for n, _v in named]
    # Fixed geometry: two circles side by side, or three in a triangle. The
    # region label positions are precomputed here, not solved in the child.
    if len(named) == 2:
        centres = {names[0]: (-0.35, 0.0), names[1]: (0.35, 0.0)}
        label_at = {names[0]: (-0.62, 0.0), names[1]: (0.62, 0.0),
                    "&".join(names): (0.0, 0.0)}
    else:
        centres = {names[0]: (-0.35, -0.2), names[1]: (0.35, -0.2),
                   names[2]: (0.0, 0.4)}
        label_at = {
            names[0]: (-0.62, -0.35), names[1]: (0.62, -0.35),
            names[2]: (0.0, 0.75),
            "&".join([names[0], names[1]]): (0.0, -0.3),
            "&".join([names[0], names[2]]): (-0.3, 0.15),
            "&".join([names[1], names[2]]): (0.3, 0.15),
            "&".join(names): (0.0, -0.02),
        }
    script = _preamble(spec) + '''

CENTRES = %r
LABEL_AT = %r
PALETTE = %r


def main():
    header, rows = read_tsv()
    counts = {r[0]: int(float(r[1])) for r in rows}
    fig, ax = plt.subplots()
    for i, (name, (x, y)) in enumerate(CENTRES.items()):
        ax.add_patch(plt.Circle((x, y), 0.5, alpha=0.35,
                                color=PALETTE[i %% len(PALETTE)],
                                ec="none"))
        ax.annotate(name, (x, y + (0.58 if y >= 0 else -0.58)),
                    ha="center", va="center", fontsize=%r,
                    fontweight="bold")
    for region, (x, y) in LABEL_AT.items():
        if region in counts:
            ax.annotate(str(counts[region]), (x, y), ha="center",
                        va="center", fontsize=%r)
    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-1.1, 1.2)
    ax.set_aspect("equal")
    ax.set_axis_off()
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (centres, label_at, list(figure_style.PALETTE),
       figure_style.MIN_FONT_PT, figure_style.MIN_FONT_PT, _panel_label_src())

    spec = dict(spec, n=sum(regions.values()))
    legend = _legend(
        spec,
        "Exclusive region counts for %s; every member is counted in exactly "
        "one region. Counts are in data.tsv." % ", ".join(names),
        extra="Circle areas are NOT proportional to set sizes; read the "
              "numbers, not the geometry.")
    return data, script, legend


def values_for_venn(data_slice):
    named = _named_sets(data_slice, MAX_VENN_SETS)
    return {k: {"count": float(v)} for k, v in _regions(named).items()}


# ---------------------------------------------------------------- upset

def build_upset(data_slice, spec):
    named = _named_sets(data_slice, MAX_UPSET_SETS)
    regions = {k: v for k, v in _regions(named).items() if v > 0}
    ordered = sorted(regions.items(), key=lambda kv: -kv[1])
    header = ["pattern", "count"]
    rows = [[k, _num(v)] for k, v in ordered]
    data = _tsv(header, rows)
    names = [n for n, _v in named]

    script = _preamble(spec, height_mm=95) + '''

SET_NAMES = %r
PALETTE = %r


def main():
    header, rows = read_tsv()
    patterns = [r[0] for r in rows]
    counts = [int(float(r[1])) for r in rows]
    fig, (top, bottom) = plt.subplots(
        2, 1, sharex=True, height_ratios=[3, 1],
        gridspec_kw={"hspace": 0.05})
    xs = range(len(patterns))
    top.bar(xs, counts, color=PALETTE[0])
    for x, c in zip(xs, counts):
        top.annotate(str(c), (x, c), ha="center", va="bottom", fontsize=%r)
    top.set_ylabel("features")
    top.set_xticks([])
    for x, pattern in enumerate(patterns):
        inside = set(pattern.split("&"))
        for y, name in enumerate(SET_NAMES):
            member = name in inside
            bottom.scatter([x], [y], s=45,
                           c=PALETTE[0] if member else "#dddddd", zorder=3)
        ys = [y for y, name in enumerate(SET_NAMES) if name in inside]
        if len(ys) > 1:
            bottom.plot([x, x], [min(ys), max(ys)], color=PALETTE[0],
                        lw=1.4, zorder=2)
    bottom.set_yticks(range(len(SET_NAMES)))
    bottom.set_yticklabels(SET_NAMES, fontsize=%r)
    bottom.set_xticks([])
    bottom.set_ylim(-0.6, len(SET_NAMES) - 0.4)
    for spine in ("top", "right", "bottom"):
        bottom.spines[spine].set_visible(False)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (names, list(figure_style.PALETTE), figure_style.MIN_FONT_PT,
       figure_style.MIN_FONT_PT, _panel_label_src("top"))

    spec = dict(spec, n=sum(regions.values()))
    legend = _legend(
        spec,
        "Exclusive intersection sizes for %s, largest first; the dot matrix "
        "below each bar says which sets that bar's features belong to (and "
        "only those). Empty intersections are omitted."
        % ", ".join(names))
    return data, script, legend


def values_for_upset(data_slice):
    named = _named_sets(data_slice, MAX_UPSET_SETS)
    return {k: {"count": float(v)}
            for k, v in _regions(named).items() if v > 0}


# ------------------------------------------------------------ concordance

def build_concordance(data_slice, spec):
    features = list(data_slice.get("features") or [])
    header = ["feature", "x", "y"]
    rows = [[f.get("feature"), _num(f.get("x")), _num(f.get("y"))]
            for f in features]
    data = _tsv(header, rows)
    omic_a = str(data_slice.get("omic_a") or "layer A")
    omic_b = str(data_slice.get("omic_b") or "layer B")
    quadrants = dict(data_slice.get("quadrants") or {})
    agreement = data_slice.get("agreement")

    script = _preamble(spec) + '''

QUADRANTS = %r
AGREEMENT = %r
X_LABEL = %r
Y_LABEL = %r
PALETTE = %r


def main():
    header, rows = read_tsv()
    xs = [float(r[1]) for r in rows]
    ys = [float(r[2]) for r in rows]
    agree = [(x > 0) == (y > 0) for x, y in zip(xs, ys)]
    fig, ax = plt.subplots()
    ax.scatter([x for x, a in zip(xs, agree) if a],
               [y for y, a in zip(ys, agree) if a],
               s=28, color=PALETTE[2], label="agree", zorder=3)
    ax.scatter([x for x, a in zip(xs, agree) if not a],
               [y for y, a in zip(ys, agree) if not a],
               s=28, color=PALETTE[1], label="disagree", zorder=3)
    ax.axhline(0, color="#999999", lw=0.8, zorder=1)
    ax.axvline(0, color="#999999", lw=0.8, zorder=1)
    ax.set_xlabel(X_LABEL)
    ax.set_ylabel(Y_LABEL)
    corners = {"++": (0.97, 0.97, "right", "top"),
               "--": (0.03, 0.03, "left", "bottom"),
               "+-": (0.97, 0.03, "right", "bottom"),
               "-+": (0.03, 0.97, "left", "top")}
    for key, (x, y, ha, va) in corners.items():
        if key in QUADRANTS:
            ax.annotate("n=%%d" %% QUADRANTS[key], xy=(x, y),
                        xycoords="axes fraction", ha=ha, va=va, fontsize=%r)
    title = "agreement %%.0f%%%%" %% (AGREEMENT * 100) if AGREEMENT is not None else ""
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=%r,
              borderaxespad=0.0, title=title)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (quadrants, agreement, omic_a, omic_b, list(figure_style.PALETTE),
       figure_style.MIN_FONT_PT, figure_style.MIN_FONT_PT, _panel_label_src())

    spec = dict(spec, n=len(features))
    legend = _legend(
        spec,
        "Each point is one feature relevant in BOTH %s (x) and %s (y); "
        "quadrant counts are printed in the corners and 'agreement' is the "
        "fraction of features whose values share a sign. Values are the "
        "job's own, reproduced in data.tsv." % (omic_a, omic_b),
        extra="Sign is read as direction on the transformed scale; a feature "
              "at zero in either layer is excluded.")
    return data, script, legend


def values_for_concordance(data_slice):
    return {str(f.get("feature")): {"x": float(f.get("x") or 0.0),
                                    "y": float(f.get("y") or 0.0)}
            for f in (data_slice.get("features") or [])}


def _panel_label_src(ax_expr="ax"):
    from .figure_templates import _panel_label
    return _panel_label(ax_expr)
