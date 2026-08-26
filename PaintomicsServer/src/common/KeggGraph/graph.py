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

        # Symmetric CSR, for _neighbours() alone. It carries no edge id:
        # subgraph() walks the unsorted edge arrays and indexes them directly,
        # so a CSR-order id would be a second numbering nothing reads.
        u = np.concatenate([src, dst])
        v = np.concatenate([dst, src])
        order = np.argsort(u, kind="stable")
        self._indices = v[order]
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

        candidates = []
        for edge_id in range(len(self.edge_kind)):
            a = int(self.edge_src[edge_id])
            b = int(self.edge_dst[edge_id])
            if a in codes and b in codes:
                step_a = step_of[self.names[a]]
                step_b = step_of[self.names[b]]
                degree = ((self._indptr[a + 1] - self._indptr[a]) +
                          (self._indptr[b + 1] - self._indptr[b]))
                candidates.append((min(step_a, step_b), -int(degree), edge_id,
                                   a, b, step_a, step_b))
        candidates.sort()

        # Every drawn node keeps the edge that explains why it is in its ring.
        #
        # Ranking edges by distance and truncating at `budget` spent the whole
        # allowance on rings 1-2: measured on C02686 at radius 4, 50 of 161
        # nodes (31%) came back with NO edge at all. A node drawn in ring 4
        # with nothing attached to it is a claim the panel cannot support --
        # "four steps away" is a statement about a path -- and the card's "how
        # it connects" list, the one thing no earlier view could show, silently
        # vanished for a third of the graph.
        #
        # So a parent edge per node is reserved first (to a kept node one step
        # closer to the seed; any kept neighbour if the real parents were
        # sampled away), and only the remaining budget is ranked. At most
        # len(nodes) - 1 edges are reserved, so the reservation cannot itself
        # exhaust a sane budget.
        required, rank = {}, {}
        for near, neg_degree, edge_id, a, b, step_a, step_b in candidates:
            rank[edge_id] = (near, neg_degree, edge_id)
            if step_a == step_b:
                continue                    # a sibling edge explains nothing
            child = a if step_a > step_b else b
            if step_of[self.names[child]] and child not in required:
                required[child] = edge_id
        for near, neg_degree, edge_id, a, b, step_a, step_b in candidates:
            for node in (a, b):
                if step_of[self.names[node]] and node not in required:
                    required[node] = edge_id

        # `budget` stays a hard cap -- it is a payload-size guard, and quietly
        # exceeding it would trade one silent behaviour for another. What
        # changes is the ORDER it is spent in: the explanatory edges first,
        # each still ranked nearest-the-seed, then everything else.
        required_ids = sorted(dict.fromkeys(required.values()),
                              key=lambda edge_id: rank[edge_id])
        reserved = set(required_ids)
        extras = [edge_id for _n, _d, edge_id, _a, _b, _sa, _sb in candidates
                  if edge_id not in reserved]
        ordered = required_ids + extras
        edges_truncated = len(ordered) > budget
        chosen = ordered[:budget]

        edges, attached = [], set()
        for edge_id in chosen:
            source = self.names[int(self.edge_src[edge_id])]
            target = self.names[int(self.edge_dst[edge_id])]
            attached.add(source)
            attached.add(target)
            edges.append({
                "source": source,
                "target": target,
                "kind": self.edge_kind[edge_id],
                "subtype": self.edge_subtype[edge_id],
                "pathway": self.edge_pathway[edge_id],
                "reversible": bool(self.edge_reversible[edge_id]),
            })

        # A node whose every neighbour was sampled away cannot be explained by
        # anything on screen, so it is not drawn and its ring says so.
        isolated = {name for name, step in step_of.items()
                    if step and name not in attached}
        if isolated:
            for report in ring_report:
                report["shown"] -= sum(1 for name in isolated
                                       if step_of[name] == report["step"])
            dropped += len(isolated)

        nodes = [{"id": name, "type": self.node_type.get(name),
                  "step": step_of[name]}
                 for name in sorted(step_of) if name not in isolated]
        return {"seed": seed, "source": self.source,
                "truncated": bool(dropped) or edges_truncated,
                "nodes_dropped": dropped,
                "nodes": nodes, "edges": edges, "rings": ring_report}

    def compound_balls(self, k=4):
        """Cumulative k-step balls for EVERY compound, as integer code arrays,
        memoised on the graph.

        The scorer needs the whole background on every job, and these are a pure
        function of the graph -- so they belong to the graph's lifetime, not the
        job's. Returned as node codes rather than names so scoring is numpy
        masking rather than millions of dict lookups: that is the difference
        between ~2.3 s per job (what the R scorer also paid) and milliseconds.

        `balls[compound][i]` is the cumulative ball out to radius i+1, unique and
        seed-free. Rings are disjoint, so the cumulative count is also the node
        count -- which is what `ball_size` reports.
        """
        cached = self._compound_balls.get(k)
        if cached is not None:
            return cached
        out = {}
        for compound in self.compounds():
            running, cumulative = [], []
            for ring in self.rings(compound, k):
                running.extend(self._code[n] for n in ring)
                cumulative.append(np.array(running, dtype=np.int32))
            out[compound] = cumulative
        self._compound_balls[k] = out
        return out

    def compounds(self):
        return [n for n in self.names if self.node_type.get(n) == "compound"]

    def genes(self):
        return [n for n in self.names if self.node_type.get(n) == "gene"]
