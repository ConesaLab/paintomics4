"""JobGraph — the job's relationships as one typed graph the agent can read.

Why this exists
---------------
A finished job already holds four networks, each in its own shape: the MORE
regulation table (regulator -> target with per-condition coefficients), KEGG's
own KGML relations, OmniPath interactions where installed, pathway membership
and similarity, and metabolite hub neighbourhoods. The agent could read none
of them: the audit line is "MORE/hub/metagenes never reach the agent". What
works when a language model reads a graph store -- Neo4j's own agent tooling
is the reference -- is **schema first, then a few typed traversals**;
free-form query generation is where such agents fail. So the graph is small,
in-process (`networkx`, built once at run start), and read through seven
bounded tools (`graph_tools.py`) instead of a query language.

Node identity is the feature LABEL (the symbol a reader knows), with the
job's feature ids kept as an attribute; a molecule that is both a MORE
regulator and a measured gene is ONE node with both roles, so regulatory
cascades stay connected. Edge types:

  REGULATES     regulator -> target   MORE: coef per condition, strongest
                                      condition, target R2, omic, area,
                                      evidence in {supported, novel,
                                      unsupported, unclassified} + sources
  MEMBER_OF     gene/compound -> pathway
  KGML          gene -> gene          KEGG relation type + the map it is on
  OMNIPATH      gene -> gene          curated interaction, sources, refs
  SIMILAR_TO    pathway -- pathway    shared features + jaccard (stored once,
                                      lexicographically smaller id first)
  NEIGHBOUR_OF  compound -- gene/compound   metabolite hub neighbourhoods

Guard-rails carried as data (the MORE lessons, measured): coefficients are
unbounded regression slopes, NOT correlations, and are not comparable across
omics or targets; R2 belongs to the target's whole model, not to one edge;
MLR reports no p-values. Every tool repeats these where the numbers appear.

`build()` takes plain-python inputs so a fixture test needs no Mongo;
`from_job()` gathers those inputs from a live job and says in `notes` exactly
which sources were absent -- an empty edge type must be distinguishable from
a source that was never read.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import networkx as nx

logger = logging.getLogger(__name__)

EDGE_TYPES = ("REGULATES", "MEMBER_OF", "KGML", "OMNIPATH", "SIMILAR_TO",
              "NEIGHBOUR_OF")
NODE_TYPES = ("gene", "regulator", "compound", "pathway")
EVIDENCE_CLASSES = ("supported", "novel", "unsupported", "unclassified")

SIMILAR_MIN_SHARED = 2          # fewer shared features is noise, not similarity
SIMILAR_MAX_EDGES = 300         # a similarity clique on 800 pathways is nobody's figure


class JobGraph(object):
    """A typed MultiDiGraph plus the honest account of what it was built from."""

    def __init__(self, graph, notes=None):
        self.g: nx.MultiDiGraph = graph
        #: Human-readable lines about sources that were absent or partial.
        self.notes: List[str] = list(notes or [])

    # ------------------------------------------------------------------ build

    @classmethod
    def build(cls, regulation=None, pathways=None, kgml=None, omnipath=None,
              hub_neighbours=None, conditions=None, notes=None):
        """Assemble the graph from plain inputs.

        regulation: [{regulator, target, omic, area, coefficient, condition,
                      targetR2, coef_by_condition?, evidence?, support?}]
        pathways:   [{id, name, source, combined_pvalue, per_omic,
                      genes: [label], compounds: [label]}]
        kgml:       [(a_label, b_label, relation_type, pathway_id)]
        omnipath:   [(a_label, b_label, {sources: [...], references: int})]
        hub_neighbours: [(compound_label, neighbour_label, neighbour_kind,
                          distance)]
        """
        g = nx.MultiDiGraph()
        g.graph["conditions"] = list(conditions or [])

        def _node(label, kind, **attrs):
            label = str(label)
            if label not in g:
                g.add_node(label, kind=kind, roles={kind})
            else:
                g.nodes[label]["roles"].add(kind)
            for key, value in attrs.items():
                if value is not None:
                    g.nodes[label][key] = value
            return label

        for row in (regulation or []):
            reg = _node(row["regulator"], "regulator",
                        omic=row.get("omic"), area=row.get("area"))
            tgt = _node(row["target"], "gene")
            # Keyed by omic as well: one regulator can regulate the same
            # target through two regulatory layers, and a shared key would
            # silently keep only the last row (3 edges vanished on the first
            # real job when symbol mapping made two names identical).
            g.add_edge(reg, tgt, key="REGULATES-%s" % (row.get("omic") or ""),
                       type="REGULATES",
                       coefficient=float(row.get("coefficient") or 0.0),
                       condition=row.get("condition"),
                       coef_by_condition=dict(row.get("coef_by_condition") or {}),
                       target_r2=row.get("targetR2"),
                       omic=row.get("omic"), area=row.get("area"),
                       evidence=row.get("evidence") or "unclassified",
                       support=list(row.get("support") or []))

        for pw in (pathways or []):
            pid = _node(pw["id"], "pathway", name=pw.get("name"),
                        source=pw.get("source"),
                        combined_pvalue=pw.get("combined_pvalue"),
                        per_omic=pw.get("per_omic"))
            for gene in (pw.get("genes") or []):
                g.add_edge(_node(gene, "gene"), pid, key="MEMBER_OF",
                           type="MEMBER_OF")
            for compound in (pw.get("compounds") or []):
                g.add_edge(_node(compound, "compound"), pid, key="MEMBER_OF",
                           type="MEMBER_OF")

        for a, b, rel_type, pathway_id in (kgml or []):
            g.add_edge(_node(a, "gene"), _node(b, "gene"),
                       key="KGML-%s-%s" % (rel_type, pathway_id),
                       type="KGML", relation_type=rel_type,
                       pathway_id=pathway_id)

        for a, b, meta in (omnipath or []):
            g.add_edge(_node(a, "gene"), _node(b, "gene"), key="OMNIPATH",
                       type="OMNIPATH",
                       sources=list((meta or {}).get("sources") or []),
                       references=int((meta or {}).get("references") or 0))

        cls._add_similarity(g, pathways or [])

        for compound, neighbour, kind, distance in (hub_neighbours or []):
            g.add_edge(_node(compound, "compound"), _node(neighbour, kind),
                       key="NEIGHBOUR_OF", type="NEIGHBOUR_OF",
                       distance=distance)

        return cls(g, notes)

    @staticmethod
    def _add_similarity(g, pathways):
        """SIMILAR_TO from shared features, stored once per pair, capped."""
        sets = {}
        for pw in pathways:
            members = set(pw.get("genes") or []) | set(pw.get("compounds") or [])
            if members:
                sets[str(pw["id"])] = members
        candidates = []
        ids = sorted(sets)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                shared = len(sets[a] & sets[b])
                if shared < SIMILAR_MIN_SHARED:
                    continue
                jaccard = shared / float(len(sets[a] | sets[b]))
                candidates.append((jaccard, shared, a, b))
        candidates.sort(reverse=True)
        dropped = max(0, len(candidates) - SIMILAR_MAX_EDGES)
        for jaccard, shared, a, b in candidates[:SIMILAR_MAX_EDGES]:
            g.add_edge(a, b, key="SIMILAR_TO", type="SIMILAR_TO",
                       shared_features=shared, jaccard=round(jaccard, 4))
        if dropped:
            g.graph["similar_to_dropped"] = dropped

    # ---------------------------------------------------------------- queries

    def edges_of_type(self, edge_type):
        return [(u, v, d) for u, v, k, d in self.g.edges(keys=True, data=True)
                if d.get("type") == edge_type]

    def nodes_of_kind(self, kind):
        return [n for n, d in self.g.nodes(data=True) if kind in d.get("roles", ())]

    def summary(self):
        """Counts by type -- the numbers graph_schema prints."""
        edge_counts = {t: 0 for t in EDGE_TYPES}
        for _u, _v, d in self.g.edges(data=True):
            t = d.get("type")
            if t in edge_counts:
                edge_counts[t] += 1
        node_counts = {t: len(self.nodes_of_kind(t)) for t in NODE_TYPES}
        evidence = {c: 0 for c in EVIDENCE_CLASSES}
        for _u, _v, d in self.edges_of_type("REGULATES"):
            evidence[d.get("evidence", "unclassified")] += 1
        return {"nodes": node_counts, "edges": edge_counts,
                "evidence": evidence,
                "conditions": list(self.g.graph.get("conditions") or [])}


# --------------------------------------------------------------------------
# Gathering the inputs from a live job.
# --------------------------------------------------------------------------

def _regulation_rows(job_instance):
    """The MORE table as build() rows, with per-condition coefficients."""
    from src.classes.PathwayEvidence import _RegulationTable
    stored = getattr(job_instance, "regulationPerConditionData", None)
    if not isinstance(stored, dict):
        # adaptBSON turns None into the STRING "None" on some stored jobs;
        # a string reaches .get() and takes the whole build down.
        stored = None
    table = _RegulationTable(stored)
    if not table.usable:
        return [], [], {}
    conditions = list(table.conditionNames or [])
    # relationships(condition) re-reads the table restricted to one condition;
    # keyed join to attach every condition's coefficient to the same edge.
    per_condition = {}
    for condition in conditions:
        for rel in table.relationships(condition):
            key = (rel["regulator"], rel["target"], rel["omic"])
            per_condition.setdefault(key, {})[condition] = rel["coefficient"]
    rows = []
    for rel in table.relationships(None):
        key = (rel["regulator"], rel["target"], rel["omic"])
        rel = dict(rel)
        rel["coef_by_condition"] = per_condition.get(key, {})
        rows.append(rel)
    return rows, conditions, dict(table.symbols or {})


def _classify_regulation(job_instance, rows, id_to_label=None):
    """Attach supported/novel/unsupported + sources, job-wide (needs Mongo).

    Returns (note, omnipath_edges): the note names why classification could
    not run (or None), and omnipath_edges are the curated OmniPath
    interactions among the JOB'S OWN genes -- (label_a, label_b, meta) --
    so the graph carries them as edges of their own, not only as support
    annotations on MORE claims.
    """
    from pymongo import MongoClient
    from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
    from src.classes.PathwayEvidence import (EvidenceKnowledge,
                                             _summariseEvidence)
    from src.common.FeatureNamesToKeggIDsMapper import (resolveDatabaseIds,
                                                        findIDsByFeaturesName)
    organism = job_instance.getOrganism()
    client = MongoClient(MONGODB_HOST, MONGODB_PORT)
    try:
        database = client[organism + "-paintomics"]
        ids, _symbols = resolveDatabaseIds(organism, ["KEGG"], database)
        target_dbname = ids.get("KEGG")
        if target_dbname is None:
            return ("evidence: no KEGG id space for %s; REGULATES edges stay "
                    "unclassified" % organism), []
        names = sorted({r["regulator"] for r in rows} | {r["target"] for r in rows})
        translation = findIDsByFeaturesName(job_instance.getJobID(), names,
                                            database, target_dbname)
        knowledge = EvidenceKnowledge.forOrganism(organism, target_dbname,
                                                 job_instance.getJobID(),
                                                 database)
        if not len(knowledge):
            return ("evidence: no interaction source installed for %s; "
                    "REGULATES edges stay unclassified" % organism), []
        pathway_names = {doc.get("ID"): doc.get("name")
                         for doc in database["kegg"].find({}, {"ID": 1, "name": 1})}
        for row in rows:
            reg_ids = [str(i) for i in (translation.get(row["regulator"]) or [])]
            tgt_ids = [str(i) for i in (translation.get(row["target"]) or [])]
            hits, known_both = [], False
            for a in reg_ids:
                for b in tgt_ids:
                    hits = knowledge.interactions(a, b)
                    if hits:
                        break
                if hits:
                    break
            if not hits:
                known_both = (any(knowledge.knows(i) for i in reg_ids)
                              and any(knowledge.knows(i) for i in tgt_ids))
            if hits:
                row["evidence"] = "supported"
                row["support"] = sorted({e["source"] for e in
                                         _summariseEvidence(hits, "", pathway_names)})
            elif known_both:
                row["evidence"] = "novel"
            else:
                row["evidence"] = "unsupported"

        omnipath_edges = []
        if id_to_label:
            seen = set()
            for source in knowledge.sources:
                if source.name != "OmniPath":
                    continue
                for (a, b), provenance in source._edges.items():
                    la, lb = id_to_label.get(str(a)), id_to_label.get(str(b))
                    if la is None or lb is None or la == lb:
                        continue
                    pair = tuple(sorted((la, lb)))
                    if pair in seen:      # both directions are stored
                        continue
                    seen.add(pair)
                    refs = provenance[1] if len(provenance) > 1 else ""
                    n_refs = len([r for r in str(refs or "").split(";") if r])
                    omnipath_edges.append((la, lb,
                                           {"sources": ["OmniPath"],
                                            "references": n_refs}))
        return None, omnipath_edges
    finally:
        client.close()


def _pathway_rows(ctx_pathways):
    """ctx.pathways (the run's ranked list) as build() pathway rows."""
    rows = []
    for pw in (ctx_pathways or []):
        genes = []
        for gene in (pw.get("top_genes") or []):
            if gene.get("symbol"):
                genes.append(str(gene["symbol"]))
        for name in (pw.get("matched_genes") or []):
            if str(name) not in genes:
                genes.append(str(name))
        compounds = []
        # The run context calls them top_compounds; older fixtures said
        # top_metabolites. Read both, first key wins.
        for met in (pw.get("top_compounds") or pw.get("top_metabolites") or []):
            label = met.get("name") or met.get("symbol")
            if label:
                compounds.append(str(label))
        rows.append({"id": pw.get("id"), "name": pw.get("name"),
                     "source": pw.get("source"),
                     "combined_pvalue": pw.get("combined_pvalue"),
                     "per_omic": pw.get("per_omic"),
                     "genes": genes, "compounds": compounds})
    return rows


def _kgml_rows(job_instance, id_to_label, cap_per_pair=1):
    """KGML gene-gene edges restricted to the job's own matched genes."""
    from .neighbours import load_relations
    adjacency, read, missing = load_relations(job_instance.getOrganism())
    rows = []
    for a_id, neighbours in adjacency.items():
        a_label = id_to_label.get(str(a_id))
        if a_label is None:
            continue
        for b_id, relations in neighbours.items():
            b_label = id_to_label.get(str(b_id))
            if b_label is None or a_label == b_label:
                continue
            for rel_type, _subtype, pathway_id in relations[:cap_per_pair]:
                rows.append((a_label, b_label, rel_type, pathway_id))
    return rows, read


def from_job(job_instance, ctx_pathways=None, classify=True):
    """Build the JobGraph for a live job, saying what could not be read."""
    notes = []

    id_to_label = {}
    try:
        for fid, feature in (job_instance.getInputGenesData() or {}).items():
            id_to_label[str(fid)] = feature.getName() or str(fid)
    except Exception:
        pass

    rows, conditions, symbols = _regulation_rows(job_instance)
    if symbols:
        # The MORE table stores feature names (Ensembl ids where no symbol
        # exists) and a symbols map beside them. Nodes take the symbol: it is
        # what a reader knows, what the report writes, and an 18-character
        # Ensembl id as a node label collides with everything near it.
        for row in rows:
            row["regulator"] = symbols.get(row["regulator"], row["regulator"])
            row["target"] = symbols.get(row["target"], row["target"])
    omnipath = []
    if not rows:
        notes.append("MORE: no regulation table on this job; no REGULATES edges")
    if classify:
        try:
            note, omnipath = _classify_regulation(job_instance, rows,
                                                  id_to_label)
            if note:
                notes.append(note)
            if not omnipath:
                notes.append("OmniPath: no curated interactions among this "
                             "job's genes (source absent or not installed "
                             "for this organism)")
        except Exception as exc:
            logger.warning("JobGraph evidence classification failed: %s", exc)
            notes.append("evidence classification failed (%s); REGULATES "
                         "edges stay unclassified" % exc)

    kgml, kgml_read = [], 0
    try:
        kgml, kgml_read = _kgml_rows(job_instance, id_to_label)
        if not kgml_read:
            notes.append("KGML: no maps on disk for this organism; no KGML edges")
    except Exception as exc:
        notes.append("KGML unreadable (%s)" % exc)

    pathways = _pathway_rows(ctx_pathways)
    if not pathways:
        notes.append("no ranked pathway list supplied; no MEMBER_OF or "
                     "SIMILAR_TO edges")

    graph = JobGraph.build(regulation=rows, pathways=pathways, kgml=kgml,
                           omnipath=omnipath, conditions=conditions,
                           notes=notes)
    if not graph.nodes_of_kind("compound"):
        graph.notes.append("no compound layer; no NEIGHBOUR_OF edges")
    return graph
