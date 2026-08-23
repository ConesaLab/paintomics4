"""`nes_dotplot` and `gsea_running` archetypes — GSEA drawn to be read.

nes_dotplot: one dot per gene set, x = NES, y = the set, dot size = leading
edge size, colour = q below/above 0.05. Sets ordered by NES so the panel
reads as a ranking.

gsea_running: the running enrichment score of ONE set: the curve, a tick per
member gene at its rank, the extremum marked. The one panel a GSEA claim can
be checked against by eye.
"""
from __future__ import annotations

from . import figure_style
from .figure_templates import _legend, _num, _preamble, _tsv

MAX_DOTS = 20


def build_nes_dotplot(data_slice, spec):
    rows_in = sorted((data_slice.get("results") or [])[:MAX_DOTS],
                     key=lambda r: float(r.get("nes") or 0.0))
    header = ["set", "nes", "q", "size"]
    rows = [[r.get("name") or r.get("id"), _num(r.get("nes")),
             _num(r.get("q")), _num(r.get("size"))] for r in rows_in]
    data = _tsv(header, rows)

    script = _preamble(spec, height_mm=max(60.0, 6.0 * len(rows) + 25.0)) + '''

PALETTE = %r


def main():
    header, rows = read_tsv()
    names = [r[0] for r in rows]
    nes = [float(r[1]) for r in rows]
    qs = [float(r[2]) for r in rows]
    sizes = [float(r[3]) for r in rows]
    fig, ax = plt.subplots()
    ys = range(len(names))
    for y, (x, q, s) in enumerate(zip(nes, qs, sizes)):
        ax.scatter([x], [y], s=30 + 4 * s,
                   color=PALETTE[2] if q <= 0.05 else "#bbbbbb", zorder=3)
    ax.axvline(0, color="#999999", lw=0.8, zorder=1)
    ax.set_yticks(list(ys))
    ax.set_yticklabels(names, fontsize=%r)
    ax.set_xlabel("normalised enrichment score (NES)")
    handles = [plt.Line2D([0], [0], marker="o", ls="", color=PALETTE[2],
                          label="q <= 0.05"),
               plt.Line2D([0], [0], marker="o", ls="", color="#bbbbbb",
                          label="q > 0.05")]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.02, 0.5),
              fontsize=%r, borderaxespad=0.0)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (list(figure_style.PALETTE), figure_style.MIN_FONT_PT,
       figure_style.MIN_FONT_PT, _panel_label_src())

    spec = dict(spec, n=len(rows))
    legend = _legend(
        spec,
        "One dot per gene set: x is the NES, dot size tracks the leading-"
        "edge size, filled colour marks q <= 0.05 (BH). Values are in "
        "data.tsv.",
        extra="NES normalises each ES by the same-sign permutation mean, so "
              "sets of different sizes are comparable; the permutation floor "
              "bounds every p.")
    return data, script, legend


def values_for_nes_dotplot(data_slice):
    out = {}
    for r in sorted((data_slice.get("results") or [])[:MAX_DOTS],
                    key=lambda r: float(r.get("nes") or 0.0)):
        out[str(r.get("name") or r.get("id"))] = {
            "nes": float(r.get("nes") or 0.0),
            "q": float(r.get("q") or 1.0),
            "size": float(r.get("size") or 0.0)}
    return out


def build_gsea_running(data_slice, spec):
    running = [float(v) for v in (data_slice.get("running") or [])]
    positions = [int(i) for i in (data_slice.get("positions") or [])]
    set_name = str(data_slice.get("set_name") or "gene set")
    es = float(data_slice.get("es") or 0.0)
    header = ["rank", "running_es"]
    rows = [[str(i + 1), _num(v)] for i, v in enumerate(running)]
    data = _tsv(header, rows)

    script = _preamble(spec) + '''

POSITIONS = %r
ES = %r
SET_NAME = %r
PALETTE = %r


def main():
    header, rows = read_tsv()
    xs = [int(r[0]) for r in rows]
    ys = [float(r[1]) for r in rows]
    fig, (top, ticks) = plt.subplots(
        2, 1, sharex=True, height_ratios=[4, 1],
        gridspec_kw={"hspace": 0.06})
    top.plot(xs, ys, color=PALETTE[0], lw=1.6)
    top.axhline(0, color="#999999", lw=0.8)
    extreme = max(range(len(ys)), key=lambda i: abs(ys[i]))
    top.scatter([xs[extreme]], [ys[extreme]], color=PALETTE[1], zorder=3)
    top.set_ylabel("running ES")
    # The ES lives in the title, not floating at the extremum: an annotation
    # near a positive peak sits exactly where the title is, and QA (rightly)
    # failed the first render for that collision.
    top.set_title("%%s \u2014 ES = %%.3f" %% (SET_NAME, ES), fontsize=%r)
    for p in POSITIONS:
        ticks.axvline(p + 1, color=PALETTE[0], lw=0.7)
    ticks.set_yticks([])
    ticks.set_xlabel("rank in the ordered list")
    for spine in ("top", "right", "left"):
        ticks.spines[spine].set_visible(False)
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (positions, es, set_name, list(figure_style.PALETTE),
       figure_style.MIN_FONT_PT, _panel_label_src("top"))

    spec = dict(spec, n=len(positions))
    legend = _legend(
        spec,
        "The running enrichment score of %s over the ranked list; each tick "
        "below is one member gene at its rank; the marked point is the "
        "enrichment score (the extremum). The full curve is data.tsv."
        % set_name)
    return data, script, legend


def values_for_gsea_running(data_slice):
    return {str(i + 1): {"running_es": float(v)}
            for i, v in enumerate(data_slice.get("running") or [])}


def _panel_label_src(ax_expr="ax"):
    from .figure_templates import _panel_label
    return _panel_label(ax_expr)
