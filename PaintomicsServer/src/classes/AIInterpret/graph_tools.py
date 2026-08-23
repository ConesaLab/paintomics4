"""Seven bounded reads over the JobGraph — typed traversals, never a query.

Why this shape
--------------
The measured lesson from agents over graph stores (Neo4j's own tooling
included) is that schema-first plus a few typed traversals works and
free-form query generation does not. So there is no query language here:
`graph_filter` parses a deliberately tiny expression grammar (tokenised,
compared, never eval'd), and everything else is a named traversal with a cap
and a ranking the caller can see.

Every function takes the JobGraph and returns TEXT for an agent -- ranked,
bounded, and carrying the MORE guard-rails wherever a coefficient appears:
a coefficient is an unbounded regression slope, not a correlation, and is not
comparable across omics or targets; R2 belongs to the target's whole model.
When a `FactsLedger` is passed, every number the text prints registers and
shows its id beside the value, so a specialist can cite it as `{{fN}}`.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .job_graph import EDGE_TYPES, EVIDENCE_CLASSES, JobGraph

COEF_CAVEAT = ("(coefficients are regression slopes, not correlations; not "
               "comparable across omics or targets. R2 is the target's whole "
               "model, not this edge.)")

MAX_NEIGHBOURS = 20
MAX_HUBS = 15
MAX_PATHS = 5
MAX_PATH_LEN = 3
MAX_SUBGRAPH_EDGES = 40
MAX_FILTER_ROWS = 200


def _fact(ledger, kind, value, scope, tool):
    if ledger is None or value is None:
        return ""
    try:
        return " " + ledger.tag(kind, value, scope, tool)
    except (TypeError, ValueError):
        return ""


def _coef_str(d, ledger=None, tool=""):
    coef = d.get("coefficient")
    if coef is None:
        return ""
    scope = {"edge": "%s->%s" % (d.get("_u", "?"), d.get("_v", "?")),
             "condition": str(d.get("condition") or "")}
    out = "coef %.2f%s at %s" % (coef, _fact(ledger, "coef", coef, scope, tool),
                                 d.get("condition") or "?")
    r2 = d.get("target_r2")
    if r2 is not None:
        try:
            out += ", target R2 %.2f%s" % (float(r2),
                                           _fact(ledger, "r2", float(r2),
                                                 scope, tool))
        except (TypeError, ValueError):
            pass
    return out


def _no_graph(graph):
    if graph is None or graph.g.number_of_nodes() == 0:
        return ("the job graph is empty -- this job has no regulation table, "
                "no ranked pathways and no relation data to read.")
    return None


# ----------------------------------------------------------------- schema

def graph_schema(graph: JobGraph, ledger=None):
    """Node/edge counts by type, the properties each carries, three examples
    per edge type. The contract says to call this FIRST."""
    empty = _no_graph(graph)
    if empty:
        return empty
    s = graph.summary()
    lines = ["JOB GRAPH SCHEMA"]
    lines.append("nodes: " + ", ".join(
        "%s %d%s" % (k, v, _fact(ledger, "count", v, {"node": k},
                                 "graph_schema"))
        for k, v in s["nodes"].items() if v))
    lines.append("edges: " + ", ".join(
        "%s %d%s" % (k, v, _fact(ledger, "count", v, {"edge": k},
                                 "graph_schema"))
        for k, v in s["edges"].items() if v))
    if s["edges"]["REGULATES"]:
        lines.append("REGULATES evidence: " + ", ".join(
            "%s %d%s" % (c, n, _fact(ledger, "count", n, {"evidence": c},
                                     "graph_schema"))
            for c, n in s["evidence"].items() if n))
    if s["conditions"]:
        lines.append("conditions: " + ", ".join(s["conditions"]))
    props = {"REGULATES": "coefficient, condition, coef_by_condition, "
                          "target_r2, omic, area, evidence, support",
             "MEMBER_OF": "-", "KGML": "relation_type, pathway_id",
             "OMNIPATH": "sources, references",
             "SIMILAR_TO": "shared_features, jaccard",
             "NEIGHBOUR_OF": "distance"}
    for edge_type in EDGE_TYPES:
        examples = graph.edges_of_type(edge_type)[:3]
        if not examples:
            continue
        shown = "; ".join("%s -> %s" % (u, v) for u, v, _d in examples)
        lines.append("  %s (props: %s) e.g. %s"
                     % (edge_type, props[edge_type], shown))
    for note in graph.notes:
        lines.append("note: %s" % note)
    lines.append(COEF_CAVEAT)
    return "\n".join(lines)


# -------------------------------------------------------------- neighbors

def graph_neighbors(graph: JobGraph, node, edge_types=None, direction="any",
                    depth=1, condition="", top_k=MAX_NEIGHBOURS, ledger=None):
    """Ranked neighbourhood of one node; depth <= 2, output capped."""
    empty = _no_graph(graph)
    if empty:
        return empty
    g = graph.g
    node = str(node)
    if node not in g:
        close = [n for n in g.nodes if str(n).lower() == node.lower()]
        if close:
            node = close[0]
        else:
            return ("'%s' is not in the graph. Node names are feature labels "
                    "and pathway ids; graph_schema shows examples." % node)
    depth = max(1, min(2, int(depth or 1)))
    wanted = {t for t in (edge_types or []) if t} or set(EDGE_TYPES)

    def _edges_from(n):
        out = []
        if direction in ("any", "out"):
            for _u, v, d in g.out_edges(n, data=True):
                if d.get("type") in wanted:
                    out.append((n, v, d, "->"))
        if direction in ("any", "in"):
            for u, _v, d in g.in_edges(n, data=True):
                if d.get("type") in wanted:
                    out.append((u, n, d, "<-"))
        return out

    rows, seen = [], {node}
    frontier = [node]
    for _hop in range(depth):
        next_frontier = []
        for n in frontier:
            for u, v, d, arrow in _edges_from(n):
                other = v if arrow == "->" and u == n else u
                if condition and d.get("type") == "REGULATES":
                    if condition not in (d.get("coef_by_condition") or {}) \
                            and d.get("condition") != condition:
                        continue
                rows.append((u, v, d))
                if other not in seen:
                    seen.add(other)
                    next_frontier.append(other)
        frontier = next_frontier

    def _rank(row):
        d = row[2]
        coef = abs(d.get("coefficient") or 0.0)
        evidence_rank = {"supported": 0, "novel": 1,
                         "unsupported": 2}.get(d.get("evidence"), 3)
        return (-coef, evidence_rank)

    rows.sort(key=_rank)
    total = len(rows)
    lines = ["NEIGHBOURS of %s (depth %d, %d edge(s)%s)"
             % (node, depth, total,
                _fact(ledger, "count", total, {"node": node},
                      "graph_neighbors"))]
    for u, v, d in rows[:top_k]:
        d = dict(d, _u=u, _v=v)
        bits = [d.get("type", "?")]
        if d.get("type") == "REGULATES":
            bits.append(_coef_str(d, ledger, "graph_neighbors"))
            bits.append("evidence %s" % d.get("evidence"))
        elif d.get("type") == "KGML":
            bits.append("%s on %s" % (d.get("relation_type"),
                                      d.get("pathway_id")))
        elif d.get("type") == "SIMILAR_TO":
            bits.append("%d shared, jaccard %.2f"
                        % (d.get("shared_features") or 0,
                           d.get("jaccard") or 0.0))
        lines.append("  %s -> %s  [%s]" % (u, v, "; ".join(b for b in bits if b)))
    if total > top_k:
        lines.append("  ... %d more not shown (top_k=%d, ranked |coef| then "
                     "evidence)" % (total - top_k, top_k))
    lines.append(COEF_CAVEAT)
    return "\n".join(lines)


# ------------------------------------------------------------------- hubs

def graph_hubs(graph: JobGraph, node_type="regulator", edge_type="REGULATES",
               within_pathway="", top_k=MAX_HUBS, ledger=None):
    """Highest-degree nodes of one kind, with evidence split and mean |coef|."""
    empty = _no_graph(graph)
    if empty:
        return empty
    g = graph.g
    members = None
    if within_pathway:
        pid = str(within_pathway)
        if pid not in g:
            return "'%s' is not a pathway node in this graph." % pid
        members = {u for u, _v, d in g.in_edges(pid, data=True)
                   if d.get("type") == "MEMBER_OF"}
    stats = {}
    for u, v, d in g.edges(data=True):
        if d.get("type") != edge_type:
            continue
        if node_type not in g.nodes[u].get("roles", ()):
            continue
        if members is not None and v not in members and u not in members:
            continue
        entry = stats.setdefault(u, {"degree": 0, "coefs": [],
                                     "evidence": {}})
        entry["degree"] += 1
        if d.get("coefficient") is not None:
            entry["coefs"].append(abs(d["coefficient"]))
        ev = d.get("evidence", "unclassified")
        entry["evidence"][ev] = entry["evidence"].get(ev, 0) + 1
    if not stats:
        return ("no %s node carries a %s edge%s." %
                (node_type, edge_type,
                 " within %s" % within_pathway if within_pathway else ""))
    ranked = sorted(stats.items(), key=lambda kv: -kv[1]["degree"])
    lines = ["HUBS: %s by %s degree%s" %
             (node_type, edge_type,
              " within %s" % within_pathway if within_pathway else "")]
    for name, entry in ranked[:top_k]:
        mean = (sum(entry["coefs"]) / len(entry["coefs"])) if entry["coefs"] else 0.0
        split = ", ".join("%s %d" % kv for kv in sorted(entry["evidence"].items()))
        lines.append("  %s: %d target(s)%s, mean |coef| %.2f%s (%s)"
                     % (name, entry["degree"],
                        _fact(ledger, "count", entry["degree"],
                              {"hub": name}, "graph_hubs"),
                        mean,
                        _fact(ledger, "coef", mean,
                              {"hub": name, "stat": "mean_abs"},
                              "graph_hubs"),
                        split))
    if len(ranked) > top_k:
        lines.append("  ... %d more not shown" % (len(ranked) - top_k))
    lines.append(COEF_CAVEAT)
    return "\n".join(lines)


# ------------------------------------------------------------------- path

def graph_path(graph: JobGraph, a, b, max_len=MAX_PATH_LEN, edge_types=None,
               ledger=None):
    """Shortest paths a -> b (undirected walk), each hop with its evidence."""
    import networkx as nx
    empty = _no_graph(graph)
    if empty:
        return empty
    g = graph.g
    a, b = str(a), str(b)
    missing = [n for n in (a, b) if n not in g]
    if missing:
        return "not in the graph: %s" % ", ".join(missing)
    wanted = {t for t in (edge_types or []) if t} or set(EDGE_TYPES)
    view = nx.Graph()
    for u, v, d in g.edges(data=True):
        if d.get("type") in wanted:
            if not view.has_edge(u, v):
                view.add_edge(u, v, kinds=[])
            view[u][v]["kinds"].append(d)
    if a not in view or b not in view:
        return "no %s edges touch %s" % ("/".join(sorted(wanted)),
                                          a if a not in view else b)
    try:
        paths = []
        for path in nx.shortest_simple_paths(view, a, b):
            if len(path) - 1 > max(1, min(4, int(max_len or MAX_PATH_LEN))):
                break
            paths.append(path)
            if len(paths) >= MAX_PATHS:
                break
    except nx.NetworkXNoPath:
        paths = []
    if not paths:
        return ("no path from %s to %s within %d hops over %s edges."
                % (a, b, max_len, "/".join(sorted(wanted))))
    lines = ["PATHS %s -> %s (%d shown, shortest first)" % (a, b, len(paths))]
    for path in paths:
        hops = []
        for u, v in zip(path, path[1:]):
            kinds = view[u][v]["kinds"]
            best = kinds[0]
            label = best.get("type")
            if label == "REGULATES":
                label += "(%s)" % best.get("evidence")
            hops.append("%s -[%s]- %s" % (u, label, v))
        lines.append("  " + "; ".join(hops))
    return "\n".join(lines)


# --------------------------------------------------------------- subgraph

def graph_subgraph(graph: JobGraph, pathway_id, edge_types=None,
                   max_edges=MAX_SUBGRAPH_EDGES, ledger=None):
    """One pathway's regulatory subgraph: its members plus their edges."""
    empty = _no_graph(graph)
    if empty:
        return empty
    g = graph.g
    pid = str(pathway_id)
    if pid not in g or "pathway" not in g.nodes[pid].get("roles", ()):
        return "'%s' is not a pathway node in this graph." % pid
    members = {u for u, _v, d in g.in_edges(pid, data=True)
               if d.get("type") == "MEMBER_OF"}
    if not members:
        return "%s has no matched members in this job." % pid
    wanted = {t for t in (edge_types or []) if t} or {"REGULATES", "KGML"}
    rows = []
    for u, v, d in g.edges(data=True):
        if d.get("type") not in wanted:
            continue
        if u in members or v in members:
            rows.append((u, v, d))
    rows.sort(key=lambda r: -abs(r[2].get("coefficient") or 0.0))
    total = len(rows)
    shown = rows[:max(1, min(MAX_SUBGRAPH_EDGES, int(max_edges or MAX_SUBGRAPH_EDGES)))]
    regulators = {u for u, _v, d in shown if d.get("type") == "REGULATES"}
    split = {}
    signs = {"+": 0, "-": 0}
    for _u, _v, d in shown:
        if d.get("type") == "REGULATES":
            split[d.get("evidence", "unclassified")] = \
                split.get(d.get("evidence", "unclassified"), 0) + 1
            if d.get("coefficient") is not None:
                signs["+" if d["coefficient"] >= 0 else "-"] += 1
    name = g.nodes[pid].get("name") or pid
    lines = ["SUBGRAPH of %s (%s): %d member(s), %d edge(s)%s of %s"
             % (pid, name, len(members), total,
                _fact(ledger, "count", total, {"pathway": pid},
                      "graph_subgraph"),
                "/".join(sorted(wanted)))]
    if split:
        lines.append("  regulators %d; evidence %s; sign +%d/-%d"
                     % (len(regulators),
                        ", ".join("%s %d" % kv for kv in sorted(split.items())),
                        signs["+"], signs["-"]))
    for u, v, d in shown:
        d = dict(d, _u=u, _v=v)
        if d.get("type") == "REGULATES":
            lines.append("  %s -> %s [%s; %s]"
                         % (u, v, _coef_str(d, ledger, "graph_subgraph"),
                            d.get("evidence")))
        else:
            lines.append("  %s -> %s [%s %s]"
                         % (u, v, d.get("type"),
                            d.get("relation_type") or ""))
    if total > len(shown):
        lines.append("  ... %d more not shown (readable budget; ranked by "
                     "|coef|)" % (total - len(shown)))
    lines.append(COEF_CAVEAT)
    return "\n".join(lines)


# --------------------------------------------------------------- evidence

def graph_evidence(graph: JobGraph, regulator, target, ledger=None):
    """Everything the job holds about one regulator -> target claim."""
    empty = _no_graph(graph)
    if empty:
        return empty
    g = graph.g
    regulator, target = str(regulator), str(target)
    missing = [n for n in (regulator, target) if n not in g]
    if missing:
        return "not in the graph: %s" % ", ".join(missing)
    edges = [d for _u, _v, d in g.edges(data=True)
             if _u == regulator and _v == target]
    reg_edges = [d for d in edges if d.get("type") == "REGULATES"]
    if not reg_edges:
        return ("no REGULATES edge %s -> %s. graph_neighbors(%s) lists what "
                "the model does assert." % (regulator, target, regulator))
    lines = ["EVIDENCE %s -> %s" % (regulator, target)]
    for d in reg_edges:
        d = dict(d, _u=regulator, _v=target)
        by_condition = d.get("coef_by_condition") or {}
        if by_condition:
            per = ", ".join(
                "%s %.2f%s" % (c, v, _fact(ledger, "coef", v,
                                           {"edge": "%s->%s" % (regulator, target),
                                            "condition": c},
                                           "graph_evidence"))
                for c, v in by_condition.items())
            lines.append("  coefficients: %s" % per)
        else:
            lines.append("  %s" % _coef_str(d, ledger, "graph_evidence"))
        lines.append("  omic %s; area %s; evidence %s%s"
                     % (d.get("omic"), d.get("area"), d.get("evidence"),
                        (" (%s)" % ", ".join(d.get("support") or [])
                         if d.get("support") else "")))
    others = [d for d in edges if d.get("type") in ("KGML", "OMNIPATH")]
    for d in others:
        if d.get("type") == "KGML":
            lines.append("  KGML: %s on %s" % (d.get("relation_type"),
                                               d.get("pathway_id")))
        else:
            lines.append("  OmniPath: %s (%d reference(s))"
                         % (", ".join(d.get("sources") or []) or "curated",
                            d.get("references") or 0))
    lines.append(COEF_CAVEAT + " MLR reports no p-values.")
    return "\n".join(lines)


# ----------------------------------------------------------------- filter

_FILTER_TOKEN = re.compile(
    r"^\s*(abs\(coef\)|coef|r2|jaccard|shared|references|distance|type|"
    r"evidence|omic|condition|from|to|relation)\s*"
    r"(==|!=|>=|<=|>|<)\s*"
    r"('[^']*'|\"[^\"]*\"|[-+]?[\w.:>-]+)\s*$")

_NUMERIC_FIELDS = {"coef", "abs(coef)", "r2", "jaccard", "shared",
                   "references", "distance"}


def _edge_field(u, v, d, field):
    if field == "abs(coef)":
        c = d.get("coefficient")
        return None if c is None else abs(c)
    return {"coef": d.get("coefficient"), "r2": d.get("target_r2"),
            "jaccard": d.get("jaccard"), "shared": d.get("shared_features"),
            "references": d.get("references"), "distance": d.get("distance"),
            "type": d.get("type"), "evidence": d.get("evidence"),
            "omic": d.get("omic"), "condition": d.get("condition"),
            "relation": d.get("relation_type"),
            "from": u, "to": v}.get(field)


def graph_filter(graph: JobGraph, expr, ledger=None):
    """Edges matching a tiny expression: clauses joined by `and`.

    Fields: type, evidence, omic, condition, from, to, relation, coef,
    abs(coef), r2, jaccard, shared, references, distance.
    Operators: == != > >= < <=. Example:
        type == REGULATES and abs(coef) > 1 and evidence == supported
    Parsed and compared -- never evaluated as code. Output capped at %d rows.
    """ % MAX_FILTER_ROWS
    empty = _no_graph(graph)
    if empty:
        return empty
    clauses = []
    for part in re.split(r"\band\b", str(expr or "")):
        if not part.strip():
            continue
        m = _FILTER_TOKEN.match(part)
        if not m:
            return ("cannot parse clause %r. One clause is FIELD OP VALUE; "
                    "fields: type, evidence, omic, condition, from, to, "
                    "relation, coef, abs(coef), r2, jaccard, shared, "
                    "references, distance; ops: == != > >= < <=; join with "
                    "'and'." % part.strip())
        field, op, raw = m.group(1), m.group(2), m.group(3).strip("'\"")
        if field in _NUMERIC_FIELDS:
            try:
                value = float(raw)
            except ValueError:
                return "clause %r compares %s with a non-number %r" % (
                    part.strip(), field, raw)
        else:
            value = raw
        clauses.append((field, op, value))
    if not clauses:
        return "empty filter; say what to match, e.g. type == REGULATES"

    def _matches(u, v, d):
        for field, op, value in clauses:
            actual = _edge_field(u, v, d, field)
            if actual is None:
                return False
            if field in _NUMERIC_FIELDS:
                try:
                    actual = float(actual)
                except (TypeError, ValueError):
                    return False
            else:
                actual, value = str(actual), str(value)
            if op == "==" and not actual == value:
                return False
            if op == "!=" and not actual != value:
                return False
            if op == ">" and not actual > value:
                return False
            if op == ">=" and not actual >= value:
                return False
            if op == "<" and not actual < value:
                return False
            if op == "<=" and not actual <= value:
                return False
        return True

    rows = [(u, v, d) for u, v, d in graph.g.edges(data=True)
            if _matches(u, v, d)]
    rows.sort(key=lambda r: -abs(r[2].get("coefficient")
                                 or r[2].get("jaccard") or 0.0))
    total = len(rows)
    lines = ["FILTER %r: %d edge(s)%s" %
             (expr, total, _fact(ledger, "count", total, {"filter": str(expr)},
                                 "graph_filter"))]
    for u, v, d in rows[:MAX_FILTER_ROWS]:
        d2 = dict(d, _u=u, _v=v)
        detail = _coef_str(d2, ledger, "graph_filter") \
            if d.get("type") == "REGULATES" else (d.get("relation_type") or "")
        lines.append("  %s -> %s [%s%s%s]"
                     % (u, v, d.get("type"),
                        "; " + detail if detail else "",
                        "; " + str(d.get("evidence"))
                        if d.get("evidence") else ""))
    if total > MAX_FILTER_ROWS:
        lines.append("  ... %d more not shown (cap %d)"
                     % (total - MAX_FILTER_ROWS, MAX_FILTER_ROWS))
    return "\n".join(lines)
