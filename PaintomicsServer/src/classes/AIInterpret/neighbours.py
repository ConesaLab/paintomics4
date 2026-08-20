"""Gene neighbours, read from the KGML the organism install already ships.

Why this file exists. `get_pathway_details` answers "what does this pathway
do"; `gene_measurements` answers "what did this gene do". Neither answers the
question a biologist actually asks next -- *what sits next to it* -- and that
question is the one a pathway diagram is drawn to answer. The agent could see
that Ret is up and never learn that the DOK adaptors immediately downstream of
it are down, because nothing in the context connects the two.

The edges are already on disk. Every KEGG organism install carries
`KEGG_DATA/current/<org>/kgml/<pathway>.kgml`, and each file holds `entry`
elements (a node, holding one or MORE gene ids -- KEGG collapses families and
complexes into one box) and `relation` elements (entry1 -> entry2, with a type
like PPrel/GErel and subtypes like activation, inhibition, expression). 364
files for mmu; `mmu04110` alone has 134 entries and 79 relations.

Two honest limits, both reported rather than hidden:

  * **KEGG only.** Reactome and OmniPath pathways have no KGML, so a gene that
    is significant only there has no neighbours here. Saying "no neighbours" for
    a gene whose pathways were never searchable is a lie by omission.
  * **Entries are sets.** One relation between two family boxes can expand to
    dozens of gene pairs. The expansion is capped and the cap is announced,
    because a silently trimmed neighbourhood is indistinguishable from a sparse
    one -- the same failure this arm has already paid for twice.
"""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# One relation between two KEGG family boxes can be dozens of gene pairs.
MAX_GENES_PER_ENTRY = int(os.getenv("AI_AGENT_KGML_ENTRY_GENES", "12"))


def _kgml_dir(organism):
    try:
        from src.conf.serverconf import KEGG_DATA_DIR
    except Exception:
        return None
    path = os.path.join(KEGG_DATA_DIR, "current", str(organism), "kgml")
    return path if os.path.isdir(path) else None


def load_relations(organism, pathway_ids=None):
    """(adjacency, pathways_read, files_missing).

    adjacency: gene id -> {neighbour gene id: [(relation type, subtype, pathway)]}

    Gene ids are stripped of the `mmu:` prefix so they join the job's own ids
    directly. Undirected on purpose: the agent is asking "what is next to this",
    and a report that missed an upstream regulator because the arrow pointed the
    other way would be wrong for a reason no reader could see.
    """
    base = _kgml_dir(organism)
    adjacency, read, missing = {}, 0, 0
    if not base:
        return adjacency, 0, 0
    wanted = [str(p) for p in (pathway_ids or [])] or None
    files = ([os.path.join(base, "%s.kgml" % p) for p in wanted] if wanted
             else [os.path.join(base, f) for f in sorted(os.listdir(base))
                   if f.endswith(".kgml")])
    for path in files:
        if not os.path.exists(path):
            missing += 1
            continue
        try:
            root = ET.parse(path).getroot()
        except Exception as exc:
            logger.warning("[neighbours] unreadable KGML %s: %s", path, exc)
            missing += 1
            continue
        read += 1
        pid = os.path.basename(path)[:-5]
        entries = {}
        for entry in root.findall("entry"):
            if entry.get("type") != "gene":
                continue
            ids = [n.split(":", 1)[-1] for n in (entry.get("name") or "").split()]
            if ids:
                entries[entry.get("id")] = ids[:MAX_GENES_PER_ENTRY]
        for rel in root.findall("relation"):
            a, b = entries.get(rel.get("entry1")), entries.get(rel.get("entry2"))
            if not a or not b:
                continue
            kind = rel.get("type") or "?"
            subs = ",".join(s.get("name") or "" for s in rel.findall("subtype")) or kind
            for ga in a:
                for gb in b:
                    if ga == gb:
                        continue
                    adjacency.setdefault(ga, {}).setdefault(gb, []).append((kind, subs, pid))
                    adjacency.setdefault(gb, {}).setdefault(ga, []).append((kind, subs, pid))
    return adjacency, read, missing


def expand(adjacency, seed_ids, steps=1, cap=60):
    """Breadth-first from the seeds. Returns [(gene id, step, [(via, subtype, pathway)])].

    Ordered by step then by how many distinct edges reach it, so a trim at `cap`
    keeps the best-connected neighbours rather than whichever the dict yielded
    first -- the same lesson as the rank-ordered truncation this arm removed
    from get_pathway_details.
    """
    seen = {str(g) for g in seed_ids}
    frontier = list(seen)
    out = []
    for step in range(1, max(0, int(steps)) + 1):
        found = {}
        for node in frontier:
            for nb, edges in (adjacency.get(node) or {}).items():
                if nb in seen:
                    continue
                found.setdefault(nb, []).extend(edges)
        if not found:
            break
        ranked = sorted(found.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for nb, edges in ranked:
            out.append((nb, step, edges))
            seen.add(nb)
        frontier = [nb for nb, _e in ranked]
        if len(out) >= cap:
            break
    return out[:cap], len(out) > cap
