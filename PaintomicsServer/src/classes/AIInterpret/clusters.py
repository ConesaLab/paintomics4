"""Pathway clusters over the shared-feature network, for the AI interpreter.

The Step 3 pathway network draws one node per significant pathway and, in
"shared biological features" mode, an edge wherever two pathways have matched
genes or compounds in common (Sorensen-Dice similarity, PA_Step3Views.js). This
module recovers that structure server-side and partitions it so the AI can
interpret biologically related pathways together instead of in arbitrary
p-value chunks, and so every significant pathway -- not only the top 15 --
reaches the report.

Everything here is pure computation over the four job methods the evolve
harness's frozen context also exposes (getMatchedPathways, getInputGenesData,
getGeneBasedInputOmics, getOrganism): no LLM, no MongoDB. Same input -> same
partition, byte for byte, in any process; there is no random seed anywhere.

Two rules the partition must respect, both measured:

* A cluster has at least two members. A size-1 group is not a cluster; it is
  an isolate and goes through the isolate rule below.
* Clustering decides CONTEXT (which pathways are discussed together, which
  shared genes glue them), never ORDER. Round 1 of the stategra-v4 evolve loop
  reordered the interpretation batches by theme and the rank score collapsed
  (-0.108 train); round 2 kept the rank presentation and only annotated shared
  genes and was KEPT. Members are therefore always listed in global rank order
  with their rank shown, and the caller keeps the rank-ordered pathway table.

Isolate rule (a significant pathway no cluster claims):
  1. satellite -- mean Dice to a cluster's members >= ``attach`` (default 0.10):
     joins that cluster flagged as loosely connected, at most ``satellites_per``
     per cluster;
  2. standalone -- major (>= 2 significant omic layers) or in the global top
     ``standalone_top`` by combined p: its own interpretation unit;
  3. further -- everything else: rendered deterministically and interpreted in
     one pooled batch, so nothing significant is silently dropped.

Cross-database identity: KEGG stores matchedGenes as Entrez ids and Reactome as
gene symbols / entity names, so the raw sets never overlap. Both are clones of
the same input feature carrying the same ``omicsValues[*].inputName``; joining
clones through their input names gives one key per input feature (compounds
already share the KEGG C-id in both databases). Reactome modified-entity
variants (``PHOSPHO-P-S259-RAF1``, ``RAF1``) collapse onto one key, which is a
correction: they are one input gene.
"""
import json
import logging
import math
import os

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from .context_builder import (
    _best_pval, _conditionPvaluesOf, _count_significant_omics, _numericValues,
)

logger = logging.getLogger(__name__)

# All knobs are environment-overridable, like the AI_SDK_* settings in agent.py,
# so the base arm stays reproducible for A/B: the whole feature is off unless
# AI_CLUSTER_MODE=1.
CLUSTER_MODE = os.getenv("AI_CLUSTER_MODE", "0") == "1"

DEFAULT_PARAMS = {
    # Node universe: what the Step 3 network draws under its default filters.
    "min_pvalue": float(os.getenv("AI_CLUSTER_MIN_PVALUE", "0.05")),
    "min_features": float(os.getenv("AI_CLUSTER_MIN_FEATURES", "0.5")),
    "max_nodes": int(os.getenv("AI_CLUSTER_MAX_NODES", "150")),
    # Partition. Dice 0.25 rather than the slider's 0.10: at 0.10 the top raw
    # group on the STATegra example is 47 pathways of hub-gene overlap and any
    # split of it is arbitrary; at 0.25 the raw groups are <= 23 and 21 of 22
    # clusters carry a strict-majority core of >= 5 shared features.
    "cut": float(os.getenv("AI_CLUSTER_CUT", "0.25")),
    "cap": int(os.getenv("AI_CLUSTER_CAP", "10")),
    "min_size": 2,
    "attach": float(os.getenv("AI_CLUSTER_ATTACH", "0.10")),
    "satellites_per": int(os.getenv("AI_CLUSTER_SATELLITES", "2")),
    "standalone_top": int(os.getenv("AI_CLUSTER_STANDALONE_TOP", "10")),
    "hub_fraction": float(os.getenv("AI_CLUSTER_HUB_FRACTION", "0.25")),
    "core_limit": 12,
    # PubMed queries per cluster (1 = core genes + experimental system; 2 adds
    # a second core-gene set). Each query costs a search and a screener call.
    "queries_per_cluster": int(os.getenv("AI_CLUSTER_QUERIES", "1")),
}
METHOD = "hier-average-dice"
VERSION = 1


# ---------------------------------------------------------------------------
# Feature identity
# ---------------------------------------------------------------------------

def _ugly(symbol):
    s = str(symbol or "")
    return (not s) or s.isdigit() or s.upper().startswith(("ENSMUSG", "ENSG",
                                                            "ENSRNOG", "ENSDARG"))


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        # Deterministic representative: the lexically smaller root.
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra


def canonical_feature_map(job_instance):
    """gene clone id -> (canonical key, display symbol).

    Clones (one per database that resolved the input row) are joined through
    the input names they carry; the canonical key is the smallest clone id of
    the joined group prefixed ``F:``. The display symbol prefers a real gene
    symbol from any clone in the group (KEGG clones carry it as ``name``;
    Reactome clones carry the raw input id there and the symbol as ``ID``).
    Features with no omics values (should not happen) map to themselves.
    """
    genes = job_instance.getInputGenesData() or {}
    uf = _UnionFind()
    by_input = {}
    for gid, gene in genes.items():
        gid = str(gid)
        uf.find(gid)
        try:
            ovs = gene.getOmicsValues() or []
        except Exception:
            ovs = []
        for ov in ovs:
            try:
                name = ov.getInputName()
            except Exception:
                name = getattr(ov, "inputName", None)
            if not name:
                continue
            name = str(name)
            first = by_input.get(name)
            if first is None:
                by_input[name] = gid
            else:
                uf.union(first, gid)

    # Symbol per group: best candidate across the group's clones.
    groups = {}
    for gid in genes:
        groups.setdefault(uf.find(str(gid)), []).append(str(gid))
    symbol_of_group = {}
    for root, members in groups.items():
        best = None
        for gid in sorted(members):
            gene = genes.get(gid)
            candidates = []
            try:
                candidates.append(gene.getName())
            except Exception:
                pass
            candidates.append(gid)
            for c in candidates:
                if c and not _ugly(c):
                    # Prefer a mixed-case symbol (KEGG's "Csf2rb") over an
                    # all-caps Reactome entity id when both exist.
                    if best is None or (best.isupper() and not str(c).isupper()):
                        best = str(c)
        symbol_of_group[root] = best or sorted(members)[0]

    out = {}
    for gid in genes:
        root = uf.find(str(gid))
        out[str(gid)] = ("F:" + root, symbol_of_group[root])
    return out


def pathway_feature_sets(job_instance, pathway_ids, feature_map=None):
    """pathway id -> frozenset of canonical feature keys (genes + compounds)."""
    matched = job_instance.getMatchedPathways()
    feature_map = feature_map if feature_map is not None else canonical_feature_map(job_instance)
    sets = {}
    for pid in pathway_ids:
        pw = matched.get(pid)
        if pw is None:
            sets[pid] = frozenset()
            continue
        keys = set()
        for g in (getattr(pw, "matchedGenes", None) or []):
            entry = feature_map.get(str(g))
            keys.add(entry[0] if entry else "G:" + str(g))
        for c in (getattr(pw, "matchedCompounds", None) or []):
            keys.add("C:" + str(c))
        sets[pid] = frozenset(keys)
    return sets


# ---------------------------------------------------------------------------
# Node universe
# ---------------------------------------------------------------------------

def _fisher_min_pvalue(pw):
    """The p-value the network view filters on: combined Fisher, min over
    conditions. Falls back to the strongest combined value of any method."""
    cp = getattr(pw, "combinedSignificancePvalues", None) or {}
    vals = _numericValues(cp.get("Fisher")) if isinstance(cp, dict) else []
    if vals:
        return min(vals)
    return _best_pval(pw)


def _load_total_features(organism):
    """pathway id -> total feature count from the installed network file.

    Mirrors the client's "min features in pathway" filter. Missing file or
    unexpected shape -> {} and the filter is simply not applied.
    """
    try:
        from src.conf.serverconf import KEGG_DATA_DIR
    except Exception:
        return {}
    totals = {}
    base = os.path.join(KEGG_DATA_DIR, "current", str(organism))
    for fn in ("pathways_network.json", "pathways_network_Reactome.json"):
        path = os.path.join(base, fn)
        if not os.path.exists(path):
            continue
        try:
            with open(path) as fh:
                data = json.load(fh)
        except Exception:
            continue
        blocks = []
        if isinstance(data, dict) and "nodes" in data:
            blocks.append(data)
        elif isinstance(data, dict):
            blocks.extend(v for v in data.values() if isinstance(v, dict) and "nodes" in v)
        for block in blocks:
            for node in block.get("nodes") or []:
                d = node.get("data") or {}
                if d.get("is_classification") is not None:
                    continue
                pid, total = d.get("id"), d.get("total_features")
                if pid and isinstance(total, (int, float)):
                    totals.setdefault(pid, int(total))
    return totals


def select_network_nodes(job_instance, params=None):
    """The significant pathways the network draws, ranked by combined p.

    Returns a list of (pathway_id, pathway) in rank order (best p first, ties
    by id). Applies the network view's defaults: combined Fisher p <= min_pvalue
    (min over conditions), matched features >= min_features x pathway total
    when the pathway total is known, and drops the organism-wide map
    (<org>01100). Capped at max_nodes by rank.
    """
    p = dict(DEFAULT_PARAMS, **(params or {}))
    matched = job_instance.getMatchedPathways() or {}
    organism = str(job_instance.getOrganism() or "")
    totals = _load_total_features(organism) if p["min_features"] > 0 else {}
    rows = []
    for pid, pw in matched.items():
        pid = str(pid)
        if pid == organism + "01100":
            continue
        pval = _fisher_min_pvalue(pw)
        if pval is None or pval > p["min_pvalue"]:
            continue
        n_matched = len(getattr(pw, "matchedGenes", None) or []) + \
            len(getattr(pw, "matchedCompounds", None) or [])
        total = totals.get(pid)
        if total and total * p["min_features"] > n_matched:
            continue
        rows.append((pval, pid, pw))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [(pid, pw) for _p, pid, pw in rows[:p["max_nodes"]]]


# ---------------------------------------------------------------------------
# Partition
# ---------------------------------------------------------------------------

def _dice(a, b):
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def dice_matrix(ids, sets):
    n = len(ids)
    m = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        m[i, i] = 1.0
        for j in range(i + 1, n):
            m[i, j] = m[j, i] = _dice(sets[ids[i]], sets[ids[j]])
    return m


def _cut_groups(index_list, dist, cut_distance):
    """Average-linkage cut of the sub-matrix over index_list -> list of lists."""
    if len(index_list) < 2:
        return [list(index_list)]
    sub = dist[np.ix_(index_list, index_list)]
    labels = fcluster(linkage(squareform(sub, checks=False), method="average"),
                      t=cut_distance, criterion="distance")
    groups = {}
    for idx, lab in zip(index_list, labels):
        groups.setdefault(int(lab), []).append(idx)
    return [groups[k] for k in sorted(groups)]


def _split_to_cap(index_list, dist, cap):
    """Re-cut an over-cap group on its own sub-matrix until every part <= cap.

    Splits with maxclust=2 at each level (the top merge of the sub-dendrogram)
    and recurses into any part still over the cap. Deterministic; terminates
    because every level strictly reduces the part size or ends in singletons.
    """
    if len(index_list) <= cap:
        return [list(index_list)]
    sub = dist[np.ix_(index_list, index_list)]
    labels = fcluster(linkage(squareform(sub, checks=False), method="average"),
                      t=2, criterion="maxclust")
    parts = {}
    for idx, lab in zip(index_list, labels):
        parts.setdefault(int(lab), []).append(idx)
    parts = [parts[k] for k in sorted(parts)]
    if len(parts) < 2:
        # Degenerate (all distances equal): cut by rank into cap-sized chunks.
        return [list(index_list[i:i + cap]) for i in range(0, len(index_list), cap)]
    out = []
    for part in parts:
        out.extend(_split_to_cap(part, dist, cap))
    return out


def build_partition(job_instance, params=None, feature_map=None):
    """Compute the deterministic partition. Returns a plain dict:

    {
      "method", "version", "params",
      "nodes": [ids in rank order], "ranks": {id: 1-based rank},
      "pvalues": {id: combined Fisher p}, "major": {id: n significant omics},
      "clusters": [ {id, label, members:[ids rank-ordered], satellites:[ids],
                     core:[{symbol, key, count}], hub_core:[...], hub_driven,
                     sources:[...], best_pvalue, size} ],
      "standalone": [ids], "further": [ids],
      "unit_of": {id: cluster id | "standalone" | "further"},
    }
    An empty universe returns clusters=[] with the other fields empty.
    """
    p = dict(DEFAULT_PARAMS, **(params or {}))
    ranked = select_network_nodes(job_instance, p)
    ids = [pid for pid, _pw in ranked]
    pw_by_id = dict(ranked)
    ranks = {pid: i + 1 for i, pid in enumerate(ids)}
    pvalues = {pid: _fisher_min_pvalue(pw) for pid, pw in ranked}
    major = {}
    for pid, pw in ranked:
        try:
            major[pid] = _count_significant_omics(pw)
        except Exception:
            major[pid] = 0

    result = {"method": METHOD, "version": VERSION, "params": p,
              "nodes": ids, "ranks": ranks, "pvalues": pvalues, "major": major,
              "clusters": [], "standalone": [], "further": [], "unit_of": {}}
    if not ids:
        return result

    feature_map = feature_map if feature_map is not None else canonical_feature_map(job_instance)
    sets = pathway_feature_sets(job_instance, ids, feature_map)
    symbol_of_key = {}
    for _gid, (key, symbol) in feature_map.items():
        symbol_of_key.setdefault(key, symbol)

    # Cluster over the ids in a fixed (sorted) order so the linkage input is
    # independent of dict iteration; ranks are re-applied afterwards.
    order = sorted(ids)
    if len(order) >= 2:
        sim = dice_matrix(order, sets)
        dist = 1.0 - sim
        np.fill_diagonal(dist, 0.0)
        raw_groups = _cut_groups(list(range(len(order))), dist, 1.0 - p["cut"])
    else:
        sim = np.ones((1, 1))
        raw_groups = [[0]]

    groups, isolates = [], []
    for g in raw_groups:
        for part in _split_to_cap(g, dist, p["cap"]) if len(g) > p["cap"] else [g]:
            if len(part) >= p["min_size"]:
                groups.append(part)
            else:
                isolates.extend(part)

    # Satellite attachment: single pass against the pre-attach clusters, so
    # the outcome does not depend on the order isolates are visited.
    satellites = {gi: [] for gi in range(len(groups))}
    still_isolated = []
    for idx in sorted(isolates, key=lambda i: ranks[order[i]]):
        best_gi, best_mean = None, 0.0
        for gi, g in enumerate(groups):
            mean = float(np.mean([sim[idx, j] for j in g]))
            if mean >= p["attach"] and mean > best_mean and \
                    len(satellites[gi]) < p["satellites_per"]:
                best_gi, best_mean = gi, mean
        if best_gi is None:
            still_isolated.append(idx)
        else:
            satellites[best_gi].append(idx)

    # Hub features: present in >= hub_fraction of all nodes; a core made only
    # of these is overlap the whole network shares, not this cluster's biology.
    n_nodes = len(ids)
    key_counts = {}
    for pid in ids:
        for k in sets[pid]:
            key_counts[k] = key_counts.get(k, 0) + 1
    hub_keys = {k for k, c in key_counts.items()
                if n_nodes >= 4 and c >= math.ceil(p["hub_fraction"] * n_nodes)}

    def _label_for(key):
        if key.startswith("C:"):
            return key[2:]
        return symbol_of_key.get(key, key.split(":", 1)[-1])

    clusters = []
    for gi, g in enumerate(groups):
        members = sorted((order[i] for i in g), key=lambda pid: ranks[pid])
        sats = sorted((order[i] for i in satellites[gi]), key=lambda pid: ranks[pid])
        # Strict-majority core over the core members (pairs -> intersection).
        need = len(members) // 2 + 1
        counts = {}
        for pid in members:
            for k in sets[pid]:
                counts[k] = counts.get(k, 0) + 1
        core_all = sorted(((k, c) for k, c in counts.items() if c >= need),
                          key=lambda kc: (-kc[1], _label_for(kc[0]).lower(), kc[0]))
        specific = [{"symbol": _label_for(k), "key": k, "count": c}
                    for k, c in core_all if k not in hub_keys]
        hub_core = [{"symbol": _label_for(k), "key": k, "count": c}
                    for k, c in core_all if k in hub_keys]
        clusters.append({
            "members": members, "satellites": sats,
            "core": specific[:p["core_limit"]], "core_size": len(specific),
            "hub_core": hub_core[:p["core_limit"]], "hub_core_size": len(hub_core),
            "hub_driven": bool(core_all) and not specific,
            "sources": sorted({getattr(pw_by_id[pid], "source", "?") for pid in members + sats}),
            "best_pvalue": pvalues[members[0]],
            "size": len(members) + len(sats),
        })
    # Cluster order = rank of the best member; ids follow that order.
    clusters.sort(key=lambda c: (ranks[c["members"][0]], c["members"][0]))
    for i, c in enumerate(clusters, 1):
        c["id"] = "C%02d" % i
        best = pw_by_id[c["members"][0]]
        if len(c["members"]) == 2 and not c["satellites"]:
            c["label"] = "%s & %s" % (best.name, pw_by_id[c["members"][1]].name)
        else:
            c["label"] = "%s (+%d related)" % (best.name, c["size"] - 1)
        for pid in c["members"] + c["satellites"]:
            result["unit_of"][pid] = c["id"]

    standalone, further = [], []
    for idx in sorted(still_isolated, key=lambda i: ranks[order[i]]):
        pid = order[idx]
        if major.get(pid, 0) >= 2 or ranks[pid] <= p["standalone_top"]:
            standalone.append(pid)
            result["unit_of"][pid] = "standalone"
        else:
            further.append(pid)
            result["unit_of"][pid] = "further"

    result["clusters"] = clusters
    result["standalone"] = standalone
    result["further"] = further
    return result


def partition_member_ids(partition):
    """Every pathway the partition covers, in global rank order."""
    ranks = partition.get("ranks") or {}
    ids = set(partition.get("unit_of") or {})
    return sorted(ids, key=lambda pid: (ranks.get(pid, 10 ** 9), pid))


def partition_summary(partition):
    """One human line, for logs and the report header."""
    n = len(partition.get("nodes") or [])
    return ("%d significant pathways -> %d clusters (%d pathways), %d standalone, "
            "%d further" % (
                n, len(partition.get("clusters") or []),
                sum(c["size"] for c in partition.get("clusters") or []),
                len(partition.get("standalone") or []),
                len(partition.get("further") or [])))


# ---------------------------------------------------------------------------
# Units and batches for the interpreter
# ---------------------------------------------------------------------------

def build_units(partition, pathway_ctx_by_id):
    """Interpretation units in rank order of their best member.

    Each unit: {"kind": "cluster"|"standalone"|"further", "id", "label",
    "pathways": [context dicts, rank order], "cluster": cluster dict or None}.
    Pathways missing from the context (should not happen) are skipped; a
    cluster left with < 2 pathways is demoted to standalone units.
    """
    units = []
    for c in partition.get("clusters") or []:
        pws = [pathway_ctx_by_id[pid] for pid in c["members"] + c["satellites"]
               if pid in pathway_ctx_by_id]
        if len(pws) >= 2:
            units.append({"kind": "cluster", "id": c["id"], "label": c["label"],
                          "pathways": pws, "cluster": c})
        else:
            for pw in pws:
                units.append({"kind": "standalone", "id": pw["id"],
                              "label": pw["name"], "pathways": [pw], "cluster": None})
    for pid in partition.get("standalone") or []:
        pw = pathway_ctx_by_id.get(pid)
        if pw:
            units.append({"kind": "standalone", "id": pid, "label": pw["name"],
                          "pathways": [pw], "cluster": None})
    further = [pathway_ctx_by_id[pid] for pid in partition.get("further") or []
               if pid in pathway_ctx_by_id]
    if further:
        units.append({"kind": "further", "id": "further",
                      "label": "Further significant pathways",
                      "pathways": further, "cluster": None})
    ranks = partition.get("ranks") or {}
    units.sort(key=lambda u: (u["kind"] == "further",
                              min(ranks.get(pw["id"], 10 ** 9) for pw in u["pathways"])))
    return units


def pack_units(units, max_pathways=8):
    """Group units into interpretation batches without ever splitting a unit.

    Greedy in unit order (rank of best member): a batch takes the next unit
    while its pathway total stays within ``max_pathways``; a unit larger than
    the limit travels alone. The "further" pool is chunked on its own.
    """
    batches, current, count = [], [], 0
    for u in units:
        if u["kind"] == "further":
            if current:
                batches.append(current)
                current, count = [], 0
            pws = u["pathways"]
            for i in range(0, len(pws), max_pathways):
                batches.append([dict(u, pathways=pws[i:i + max_pathways])])
            continue
        n = len(u["pathways"])
        if current and count + n > max_pathways:
            batches.append(current)
            current, count = [], 0
        current.append(u)
        count += n
    if current:
        batches.append(current)
    return batches


def batch_pathways(batch):
    """All pathway context dicts of a batch, in global rank order (by
    combined p, the order build_pathway_context returns)."""
    seen, out = set(), []
    for u in batch:
        for pw in u["pathways"]:
            if pw["id"] not in seen:
                seen.add(pw["id"])
                out.append(pw)
    out.sort(key=lambda pw: (pw.get("combined_pvalue") or 1.0, pw.get("id")))
    return out


# ---------------------------------------------------------------------------
# Prompt and report rendering (deterministic text; the model never
# recomputes any of it)
# ---------------------------------------------------------------------------

def _fmt_p(p):
    try:
        return "%.2e" % float(p)
    except Exception:
        return "n/a"


def _member_line(pw, partition, mark=""):
    ranks = partition.get("ranks") or {}
    major = partition.get("major") or {}
    return "- #%s %s (%s, %s; combined p=%s; significant omic layers: %s)%s" % (
        ranks.get(pw["id"], "?"), pw["name"], pw["id"], pw.get("source", "?"),
        _fmt_p(pw.get("combined_pvalue")), major.get(pw["id"], pw.get("significant_omic_count", "?")),
        mark)


def render_units_block(batch, partition, total_nodes=None):
    """The cluster context prepended to an interpretation batch prompt.

    Names each unit, its members with GLOBAL rank (#k of N), the shared core
    (with member counts), hub-shared features separately, satellites, and how
    to treat the unit. Ranks are the reader's anchor: the report's emphasis
    must follow them, the clusters only say what belongs together.
    """
    n = total_nodes or len(partition.get("nodes") or [])
    lines = ["## Pathway clusters in this batch (computed from shared matched features)",
             "Rank #k is the pathway's position among the %d significant pathways of this "
             "analysis by combined p-value (1 = most significant). Give the most attention "
             "to the highest-ranked pathways wherever they sit." % n]
    for u in batch:
        if u["kind"] == "cluster":
            c = u["cluster"]
            lines.append("")
            lines.append("### %s: %s -- %d pathways, %s" % (
                c["id"], c["label"], c["size"], "/".join(c["sources"])))
            sat_ids = set(c.get("satellites") or [])
            for pw in u["pathways"]:
                lines.append(_member_line(pw, partition,
                                          "  [loosely connected]" if pw["id"] in sat_ids else ""))
            core = c.get("core") or []
            if core:
                lines.append("Shared core (features matched in a majority of the members; "
                             "count = members carrying it): " +
                             ", ".join("%s(%d)" % (f["symbol"], f["count"]) for f in core) +
                             (" ... +%d more" % (c["core_size"] - len(core))
                              if c.get("core_size", 0) > len(core) else ""))
            hub = c.get("hub_core") or []
            if hub:
                lines.append("Also shared, but common across the whole network (hub features, "
                             "not specific to this cluster): " +
                             ", ".join(f["symbol"] for f in hub[:8]))
            if c.get("hub_driven"):
                lines.append("NOTE: this cluster is held together only by hub features shared "
                             "across the network -- treat it as overlap, not as one biological "
                             "module, and say so.")
            lines.append("Interpret this cluster as one unit: first what unites the members "
                         "(shared core = coordinated biology, or hub-gene overlap = annotation "
                         "artefact -- judge from the data), then each member briefly, "
                         "highest-ranked first, naming every member.")
        elif u["kind"] == "standalone":
            pw = u["pathways"][0]
            lines.append("")
            lines.append("### Standalone pathway (no shared-feature cluster)")
            lines.append(_member_line(pw, partition))
            lines.append("Interpret it on its own; do not invent links to other pathways.")
        else:
            lines.append("")
            lines.append("### Further significant pathways (no shared-feature cluster, "
                         "single-layer evidence)")
            for pw in u["pathways"]:
                lines.append(_member_line(pw, partition))
            lines.append("Give each one or two sentences on what its enrichment means for "
                         "this experiment, naming the layer that carries it; do not group them.")
    return "\n".join(lines)


def render_synthesis_block(partition, pathway_ctx_by_id):
    """Cluster map for the synthesis prompt: every cluster with rank-ordered
    members, standalone and further pathways, and the writing rules that keep
    the rank presentation intact."""
    ranks = partition.get("ranks") or {}
    n = len(partition.get("nodes") or [])
    lines = ["## Pathway clusters (from the data)",
             "The %d significant pathways were clustered by shared matched features "
             "(Sorensen-Dice on genes and compounds). %s. Members are listed by global "
             "rank (#k = k-th most significant)." % (n, partition_summary(partition))]
    for c in partition.get("clusters") or []:
        names = []
        for pid in c["members"] + c["satellites"]:
            pw = pathway_ctx_by_id.get(pid)
            nm = pw["name"] if pw else pid
            names.append("#%s %s%s" % (ranks.get(pid, "?"), nm,
                                       " (loose)" if pid in c["satellites"] else ""))
        core = ", ".join(f["symbol"] for f in (c.get("core") or [])[:8])
        lines.append("- %s %s: %s%s%s" % (
            c["id"], c["label"], "; ".join(names),
            (" | shared core: " + core) if core else "",
            " | HUB-DRIVEN (overlap, not a module)" if c.get("hub_driven") else ""))
    if partition.get("standalone"):
        lines.append("- Standalone: " + "; ".join(
            "#%s %s" % (ranks.get(pid, "?"), (pathway_ctx_by_id.get(pid) or {}).get("name", pid))
            for pid in partition["standalone"]))
    if partition.get("further"):
        lines.append("- Further significant pathways (single-layer, unclustered): " + "; ".join(
            "#%s %s" % (ranks.get(pid, "?"), (pathway_ctx_by_id.get(pid) or {}).get("name", pid))
            for pid in partition["further"]))
    lines += [
        "",
        "Writing rules for the clusters:",
        "- Key Findings lead with the highest-RANKED pathways and their clusters; rank, "
        "not cluster size, decides emphasis.",
        "- Use the clusters as the themes of 'Cross-Pathway Themes' and group 'Detailed "
        "Pathway Analysis' by cluster, in the order given (best-ranked member first), "
        "heading each as '### Cxx -- <label>' and naming every member (a member with little "
        "to add gets one clause, not silence).",
        "- Add a 'Standalone pathways' subsection for the standalone ones and a one-line "
        "reading for each further pathway; nothing significant is dropped.",
        "- A HUB-DRIVEN cluster is shared-gene overlap: say so; do not narrate it as one "
        "coordinated module.",
    ]
    return "\n".join(lines)


def render_partition_table(partition, pathway_ctx_by_id):
    """Appended to the report after the pathway table: the partition as data."""
    ranks = partition.get("ranks") or {}
    lines = ["## Pathway Clusters (shared matched features)",
             "*%s. Clusters: average-linkage on Sorensen-Dice similarity of matched "
             "features, cut at Dice >= %.2f, at most %d core members; loosely connected "
             "= attached at mean Dice >= %.2f.*" % (
                 partition_summary(partition), partition["params"]["cut"],
                 partition["params"]["cap"], partition["params"]["attach"]),
             "", "| Cluster | Pathways (global rank) | Shared core |", "|---|---|---|"]
    for c in partition.get("clusters") or []:
        names = []
        for pid in c["members"] + c["satellites"]:
            pw = pathway_ctx_by_id.get(pid)
            names.append("%s (#%s%s)" % (pw["name"] if pw else pid, ranks.get(pid, "?"),
                                          ", loose" if pid in c["satellites"] else ""))
        core = ", ".join(f["symbol"] for f in (c.get("core") or [])[:10])
        if c.get("hub_driven"):
            core = (core + "; " if core else "") + "hub features only"
        lines.append("| %s %s | %s | %s |" % (c["id"], c["label"].replace("|", "/"),
                                            "; ".join(names).replace("|", "/"),
                                            core.replace("|", "/") or "-"))
    for kind, title in (("standalone", "Standalone"), ("further", "Further")):
        for pid in partition.get(kind) or []:
            pw = pathway_ctx_by_id.get(pid)
            lines.append("| %s | %s (#%s) | - |" % (
                title, (pw["name"] if pw else pid).replace("|", "/"), ranks.get(pid, "?")))
    return "\n".join(lines)


def cluster_search_queries(partition, pathway_ctx_by_id, organism_name, system_angle=""):
    """Gene-anchored PubMed queries per unit, replacing the per-pathway backfill.

    Yields (query, attribution_key, member_names, rationale). One or two
    queries per cluster from its specific core (or its best member's top genes
    when the core is thin), one per standalone pathway, one per further
    pathway. Attribution key is the cluster id (mapped to member names by the
    caller) so retrieved papers reach every member's drill-down.
    """
    def _genes_of(pw):
        return [g["symbol"] for g in (pw.get("top_genes") or []) if g.get("relevant")
                and not _ugly(g.get("symbol"))]

    for c in partition.get("clusters") or []:
        members = [pathway_ctx_by_id[pid] for pid in c["members"] if pid in pathway_ctx_by_id]
        if not members:
            continue
        names = [pw["name"] for pw in members] + [
            pathway_ctx_by_id[pid]["name"] for pid in c["satellites"] if pid in pathway_ctx_by_id]
        genes = [f["symbol"] for f in (c.get("core") or []) if not _ugly(f["symbol"])
                 and not f["key"].startswith("C:")]
        if len(genes) < 2:
            genes = genes + [g for g in _genes_of(members[0]) if g not in genes]
        genes = genes[:6]
        if not genes:
            continue
        n_q = int((partition.get("params") or {}).get("queries_per_cluster", 1) or 1)
        first = ("(%s) AND %s" % (" OR ".join(genes[:3]), system_angle) if system_angle
                 else "(%s) AND (%s)" % (" OR ".join(genes[:3]), organism_name))
        yield (first, c["id"], names, "cluster core genes")
        if n_q >= 2:
            if system_angle:
                yield ("(%s) AND (%s)" % (" OR ".join(genes[:3]), organism_name), c["id"], names,
                       "cluster core genes, organism")
            elif len(genes) > 3:
                yield ("(%s) AND (%s)" % (" OR ".join(genes[3:6]), organism_name), c["id"], names,
                       "cluster core genes (second set)")
    for kind in ("standalone", "further"):
        for pid in partition.get(kind) or []:
            pw = pathway_ctx_by_id.get(pid)
            if not pw:
                continue
            genes = _genes_of(pw)[:3]
            if genes:
                q = "(%s) AND (%s)" % (" OR ".join(genes), system_angle or organism_name)
            else:
                q = '"%s"[Title/Abstract]' % pw["name"]
            yield (q, pw["name"], [pw["name"]], "%s pathway" % kind)
