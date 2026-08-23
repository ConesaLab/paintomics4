"""`network` archetype — one pathway's regulatory subgraph, drawn to be read.

Why this exists
---------------
The JobGraph gives the Network analyst regulator -> target edges with
evidence classes, but a Results section needs the picture: which regulators
converge on this pathway, which claims the literature already supports and
which are this dataset's own. The readable budget measured on the diagram
overlay work is 5-8 edges per map; a network PANEL can carry more because it
draws nothing else, but 30 is the ceiling before it becomes decoration, so
the builder keeps the strongest 30 by |coefficient| and the legend says what
was cut.

The slice carries ONLY job numbers (from, to, coefficient, evidence,
condition); the LAYOUT is computed inside the generated script with a seeded
spring embedding, so re-running `figure.py` reproduces the figure to the
pixel. Colour is by evidence class from the shared Okabe-Ito palette; a
coefficient's sign is the arrowhead's fill (filled = positive, open =
negative), because red/green for sign would collide with the evidence hues.
"""
from __future__ import annotations

from . import figure_style
from .figure_templates import _legend, _preamble, _tsv, _num

MAX_EDGES = 30

# Okabe-Ito assignments, fixed so every network panel in a paper agrees.
EVIDENCE_COLOURS = {"supported": "#009E73",      # bluish green
                    "novel": "#E69F00",          # orange
                    "unsupported": "#999999",    # grey
                    "unclassified": "#56B4E9"}   # sky blue


def _edge_id(e):
    """`miR-1->Fos|supported|T1` -- endpoints, evidence, condition, one cell."""
    return "%s->%s|%s|%s" % (e.get("from"), e.get("to"),
                             e.get("evidence") or "unclassified",
                             e.get("condition") or "")


def _edge_rows(data_slice):
    edges = list(data_slice.get("edges") or [])
    edges.sort(key=lambda e: -abs(float(e.get("coefficient") or 0.0)))
    return edges


def build_network(data_slice, spec):
    """(data_tsv, script, legend) for one regulatory subgraph."""
    edges = _edge_rows(data_slice)
    dropped = max(0, len(edges) - MAX_EDGES)
    edges = edges[:MAX_EDGES]

    # One row per edge, ONE numeric column. The edge's identity -- endpoints,
    # evidence class, condition -- lives in column 0, because figure_qa treats
    # every later cell as a numeric data claim and re-checks it against the
    # job; evidence written as its own column would be "not a number" and the
    # check would (rightly) fail the figure.
    header = ["edge", "coefficient"]
    rows = [[_edge_id(e), _num(e.get("coefficient"))] for e in edges]
    data = _tsv(header, rows)

    if len(edges) > 12 and (spec.get("width") or "single") == "single":
        spec = dict(spec, width="double")

    # Canvas grows with the node count: 30 edges over 40 nodes on a fixed
    # 110 mm canvas put 'Jun' on top of 'Myc' on the first real subgraph and
    # QA (rightly) failed the figure. Height and spring spread both scale.
    nodes = {e.get("from") for e in edges} | {e.get("to") for e in edges}
    height_mm = min(210, 90 + 3 * len(nodes))

    script = _preamble(spec, height_mm=height_mm) + '''

import networkx as nx

EVIDENCE_COLOURS = %r


def main():
    header, rows = read_tsv()
    g = nx.DiGraph()
    for edge_id, coefficient in rows:
        endpoints, evidence, _condition = edge_id.split("|", 2)
        source, target = endpoints.split("->", 1)
        g.add_edge(source, target, coefficient=float(coefficient),
                   evidence=evidence)
    # Seeded so the same data always lands in the same embedding; k spreads
    # nodes enough that default-size labels do not collide on 30 edges.
    pos = nx.spring_layout(g, seed=42, k=2.4 / max(1, len(g)) ** 0.5,
                           iterations=100)
    fig, ax = plt.subplots()
    regulators = {s for s, _t in g.edges()}
    for node, (x, y) in pos.items():
        is_regulator = node in regulators
        ax.scatter([x], [y], s=110 if is_regulator else 70,
                   c="#0072B2" if is_regulator else "#D55E00",
                   zorder=3, edgecolors="white", linewidths=0.8)
        # A label longer than 14 characters (an unmapped Ensembl id) is
        # truncated with an ellipsis: the full id stays in data.tsv, and two
        # full-length ids side by side cannot avoid colliding.
        shown = node if len(node) <= 14 else node[:11] + "..."
        ax.annotate(shown, (x, y), textcoords="offset points",
                    xytext=(0, 7), ha="center", fontsize=%r, zorder=4)
    for source, target, d in g.edges(data=True):
        colour = EVIDENCE_COLOURS.get(d["evidence"], "#56B4E9")
        x0, y0 = pos[source]
        x1, y1 = pos[target]
        ax.annotate("", (x1, y1), (x0, y0), zorder=2,
                    arrowprops=dict(arrowstyle="-|>" if d["coefficient"] >= 0
                                    else "->",
                                    color=colour,
                                    lw=0.9 + 1.6 * min(1.0, abs(d["coefficient"]) / 3.0),
                                    shrinkA=8, shrinkB=8))
    handles = [plt.Line2D([0], [0], color=c, lw=2, label=e)
               for e, c in EVIDENCE_COLOURS.items()
               if any(d["evidence"] == e for _s, _t, d in g.edges(data=True))]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.02, 0.5),
              fontsize=%r, borderaxespad=0.0, title="evidence")
    ax.set_axis_off()
    %s    fig.tight_layout()
    save(fig)


if __name__ == "__main__":
    main()
''' % (EVIDENCE_COLOURS, figure_style.MIN_FONT_PT, figure_style.MIN_FONT_PT,
       _panel_label_src())

    pathway = data_slice.get("pathway") or {}
    what = ("The regulatory subgraph of %s: MORE regulator -> target edges, "
            "coloured by evidence class (Okabe-Ito); blue nodes regulate, "
            "vermilion nodes are targets; line width tracks |coefficient|; a "
            "filled arrowhead is a positive coefficient, an open one "
            "negative. Layout is a seeded spring embedding (seed 42) and "
            "carries no meaning beyond adjacency."
            % (pathway.get("name") or pathway.get("id") or "the pathway"))
    if dropped:
        what += (" The strongest %d of %d edges by |coefficient| are drawn; "
                 "%d weaker edges are omitted."
                 % (len(edges), len(edges) + dropped, dropped))
    spec = dict(spec, n=len(edges),
                test=spec.get("test") or
                "Coefficients are MORE regression slopes, not correlations; "
                "R2 belongs to each target's model; MLR reports no p-values.")
    legend = _legend(spec, what,
                     extra="Edge widths scale with |coefficient| capped at 3; "
                           "coefficients are unbounded slopes on the model's "
                           "scale.")
    return data, script, legend


def _panel_label_src():
    from .figure_templates import _panel_label
    return _panel_label()


def values_for_network(data_slice):
    """{edge id: {coefficient}} — re-derived for QA by a separate path."""
    out = {}
    for e in _edge_rows(data_slice)[:MAX_EDGES]:
        out[_edge_id(e)] = {"coefficient": float(e.get("coefficient") or 0.0)}
    return out
