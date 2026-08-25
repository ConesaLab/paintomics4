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
    def __init__(self, edges, types, source):
        self.source = source
        # Map entries are pathway cross-links, not biological entities. The R
        # pipeline filtered them twice -- once at install and again at scoring;
        # do it once, here.
        kept = [e for e in edges
                if types.get(e.a) != MAP_TYPE and types.get(e.b) != MAP_TYPE]

        self.names = sorted({e.a for e in kept} | {e.b for e in kept})
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

    def subgraph(self, seed, k, budget):
        """The induced subgraph of the seed's k-step ball, ranked and capped.

        Ranking is by hop distance then by endpoint degree, so a cap keeps the
        edges nearest the seed and drops the periphery -- the rank-then-cap
        discipline the OmniPath and RegTarget views already use. `truncated`
        exists so a cap can never read as "this is all there is".
        """
        empty = {"seed": seed, "source": self.source, "truncated": False,
                 "nodes": [], "edges": []}
        code = self._code.get(seed)
        if code is None:
            return empty

        step_of = {seed: 0}
        for radius, ring in enumerate(self.rings(seed, k), start=1):
            for name in ring:
                step_of.setdefault(name, radius)

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
        truncated = len(picked) > budget
        picked = picked[:budget]

        kept = {seed}
        edges = []
        for _near, _degree, edge_id in picked:
            a = self.names[int(self.edge_src[edge_id])]
            b = self.names[int(self.edge_dst[edge_id])]
            kept.add(a)
            kept.add(b)
            edges.append({
                "source": a, "target": b,
                "kind": self.edge_kind[edge_id],
                "subtype": self.edge_subtype[edge_id],
                "pathway": self.edge_pathway[edge_id],
                "reversible": bool(self.edge_reversible[edge_id]),
            })
        nodes = [{"id": name, "type": self.node_type.get(name),
                  "step": step_of.get(name, k)}
                 for name in sorted(kept)]
        return {"seed": seed, "source": self.source, "truncated": truncated,
                "nodes": nodes, "edges": edges}

    def compounds(self):
        return [n for n in self.names if self.node_type.get(n) == "compound"]

    def genes(self):
        return [n for n in self.names if self.node_type.get(n) == "gene"]
