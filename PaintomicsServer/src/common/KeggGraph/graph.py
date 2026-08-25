"""CSR adjacency over integer-coded node names, plus hop-ring traversal.

"Store nothing" means no persisted artifact, not no index: this index is built
on every cold start and is what makes traversal possible at all. Without it each
hop would linear-scan ~96,000 edges. It is also nearly free -- 0.03 s of mmu's
1.03 s cold start, the other 0.99 s being XML parsing.
"""
from __future__ import annotations

import numpy as np

MAP_TYPE = "map"


class KeggGraph(object):
    def __init__(self, edges, types, source, precomputed_rings=None):
        """`precomputed_rings` is {compound: [ring1, ring2, ...]}, EXCLUSIVE.

        Only the legacy fallback supplies it. hubData/kegg_interaction.json
        already holds each compound's cumulative balls out to radius 4, and
        reconstructing topology from them would invent edges that KEGG never
        stated -- so the balls are used verbatim and `rings()` serves them.
        Nodes reachable only through those balls still have to exist in the
        index, so they join the node universe below.
        """
        self.source = source
        self._precomputed = precomputed_rings or {}
        # Map entries are pathway cross-links, not biological entities. The R
        # pipeline filtered them twice -- once at install and again at scoring;
        # do it once, here.
        kept = [e for e in edges
                if types.get(e.a) != MAP_TYPE and types.get(e.b) != MAP_TYPE]

        universe = {e.a for e in kept} | {e.b for e in kept}
        for seed, rings in self._precomputed.items():
            universe.add(seed)
            for ring in rings:
                universe.update(ring)
        self.names = sorted(universe)
        self._code = {name: index for index, name in enumerate(self.names)}
        self.node_type = {name: types.get(name) for name in self.names}

        count = len(kept)
        src = np.fromiter((self._code[e.a] for e in kept), np.int32, count)
        dst = np.fromiter((self._code[e.b] for e in kept), np.int32, count)
        self.edge_kind = [e.kind for e in kept]
        self.edge_subtype = [e.subtype for e in kept]
        self.edge_pathway = [e.pathway for e in kept]
        self.edge_reversible = np.fromiter(
            (bool(e.reversible) for e in kept), bool, count)
        self.edge_src, self.edge_dst = src, dst

        # Symmetric CSR. `_edge_id` lets subgraph() recover an edge's attributes.
        u = np.concatenate([src, dst])
        v = np.concatenate([dst, src])
        eid = np.concatenate([np.arange(count), np.arange(count)]).astype(np.int32)
        order = np.argsort(u, kind="stable")
        self._indices = v[order]
        self._edge_id = eid[order]
        counts = np.zeros(len(self.names) + 1, np.int64)
        np.add.at(counts, u[order].astype(np.int64) + 1, 1)
        self._indptr = np.cumsum(counts)
        self._compound_balls = {}

    def _neighbours(self, code):
        return self._indices[self._indptr[code]:self._indptr[code + 1]]

    def rings(self, seed, k=4):
        """Exclusive hop rings. `rings(v)[0]` is N(v); the seed is never in any.

        Seeding `seen` with the seed is the whole of the D-6 fix. The R code
        subtracted the seed only from the frontier and unioned the carried-
        forward set unchanged, so a compound with a self-loop never left its own
        neighbourhood -- nine mmu compounds, including C00024, the one every
        worked example used, which is why it hid.
        """
        stored = self._precomputed.get(seed)
        if stored is not None:
            out = [list(ring) for ring in stored[:k]]
            return out + [[] for _ in range(k - len(out))]
        code = self._code.get(seed)
        if code is None:
            return [[] for _ in range(k)]
        seen = np.zeros(len(self.names), dtype=bool)
        seen[code] = True
        frontier = np.array([code], dtype=np.int64)
        out = []
        for _ in range(k):
            if frontier.size == 0:
                out.append([])
                continue
            found = np.unique(np.concatenate(
                [self._neighbours(int(x)) for x in frontier]))
            found = found[~seen[found]]
            seen[found] = True
            frontier = found
            out.append([self.names[int(x)] for x in found])
        return out

    def subgraph(self, seed, k, budget, priority=None, per_ring=40):
        """The seed's k-step neighbourhood, budgeted PER RING.

        The first version ranked every candidate edge by distance from the seed
        and truncated at `budget`. Rings 1 and 2 then ate the whole allowance and
        rings 3 and 4 contributed nothing at all -- levels 2, 3 and 4 returned
        byte-identical subgraphs, so the step control had nothing to light.
        `truncated` was technically true but hid that ENTIRE RINGS were missing.

        So the budget is allocated per ring instead. Each ring keeps at most
        `per_ring` nodes; a ring that needs fewer hands the remainder to the
        rings outside it, which are the ones that actually run out. Within a
        ring, `priority` ids are kept first -- the caller passes the job's
        differentially expressed features, because DE concentration is the whole
        claim the panel exists to show, and a sample that dropped the DE genes
        would misrepresent it. Ties break on degree, then on id for determinism.

        `rings` reports shown vs total per ring so the UI can say "40 of 312"
        rather than implying it drew everything.
        """
        empty = {"seed": seed, "source": self.source, "truncated": False,
                 "nodes": [], "edges": [], "rings": []}
        code = self._code.get(seed)
        if code is None:
            return empty

        priority = priority or set()
        rings = self.rings(seed, k)

        kept_by_step, ring_report, dropped = {0: [seed]}, [], 0
        carry = 0
        for index, ring in enumerate(rings, start=1):
            allowance = per_ring + carry
            if len(ring) <= allowance:
                chosen = list(ring)
                carry = allowance - len(ring)
            else:
                carry = 0
                chosen = sorted(
                    ring,
                    key=lambda name: (0 if name in priority else 1,
                                      -int(self._indptr[self._code[name] + 1]
                                           - self._indptr[self._code[name]]),
                                      name))[:allowance]
            dropped += len(ring) - len(chosen)
            kept_by_step[index] = chosen
            ring_report.append({
                "step": index,
                "shown": len(chosen),
                "total": len(ring),
                "de_shown": sum(1 for n in chosen if n in priority),
                "de_total": sum(1 for n in ring if n in priority),
            })

        step_of = {}
        for step, names in kept_by_step.items():
            for name in names:
                step_of.setdefault(name, step)
        codes = {self._code[n] for n in step_of}

        picked = []
        for edge_id in range(len(self.edge_kind)):
            a = int(self.edge_src[edge_id])
            b = int(self.edge_dst[edge_id])
            if a in codes and b in codes:
                near = min(step_of[self.names[a]], step_of[self.names[b]])
                degree = ((self._indptr[a + 1] - self._indptr[a]) +
                          (self._indptr[b + 1] - self._indptr[b]))
                picked.append((near, -int(degree), edge_id))
        picked.sort()
        edges_truncated = len(picked) > budget
        picked = picked[:budget]

        edges = []
        for _near, _degree, edge_id in picked:
            edges.append({
                "source": self.names[int(self.edge_src[edge_id])],
                "target": self.names[int(self.edge_dst[edge_id])],
                "kind": self.edge_kind[edge_id],
                "subtype": self.edge_subtype[edge_id],
                "pathway": self.edge_pathway[edge_id],
                "reversible": bool(self.edge_reversible[edge_id]),
            })

        nodes = [{"id": name, "type": self.node_type.get(name),
                  "step": step_of[name]}
                 for name in sorted(step_of)]
        return {"seed": seed, "source": self.source,
                "truncated": bool(dropped) or edges_truncated,
                "nodes_dropped": dropped,
                "nodes": nodes, "edges": edges, "rings": ring_report}

    def compounds(self):
        return [n for n in self.names if self.node_type.get(n) == "compound"]

    def genes(self):
        return [n for n in self.names if self.node_type.get(n) == "gene"]
