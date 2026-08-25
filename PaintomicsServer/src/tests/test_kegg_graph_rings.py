#!/usr/bin/env python3
"""Hop rings must exclude the seed and be disjoint and nested.

`hubAnalysisInstall.R:204` subtracted the seed only from the frontier:

    unique(c(susinteracciones, setdiff(unique(t3$Var2), elcompound)))

The carried-forward set was unioned unchanged, so a compound with a self-loop
never left its own neighbourhood. Nine mmu compounds are affected in the shipped
data -- C00011, C00024, C00046, C00080, C00154, C00288, C00698, C22533, C22539.
C00024 is one of them, which is why every worked example hid the defect.

Radius 1 is also an OPEN neighbourhood N(v), not a closed ball, so
`igraph::ego(order=k)` is not a drop-in: it includes the seed unconditionally.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph.parser import Edge
from src.common.KeggGraph.graph import KeggGraph


def edge(a, b, kind="PPrel"):
    return Edge(a, b, kind, "", "tst00001", False)


class RingTest(unittest.TestCase):
    def setUp(self):
        #  SELF <-> SELF (self-loop),  SELF - A - B - C - D
        #  M is a map node and must never appear.
        self.graph = KeggGraph(
            [edge("SELF", "SELF"), edge("SELF", "A"), edge("A", "B"),
             edge("B", "C"), edge("C", "D"), edge("SELF", "M")],
            {"SELF": "compound", "A": "gene", "B": "gene", "C": "gene",
             "D": "gene", "M": "map"},
            source="test")

    def test_seed_is_never_in_its_own_rings(self):
        """D-6, with the exact topology that produced it."""
        for ring in self.graph.rings("SELF", 4):
            self.assertNotIn("SELF", ring)

    def test_rings_are_exclusive_and_ordered_by_distance(self):
        self.assertEqual([sorted(r) for r in self.graph.rings("SELF", 4)],
                         [["A"], ["B"], ["C"], ["D"]])

    def test_rings_are_pairwise_disjoint(self):
        seen = set()
        for ring in self.graph.rings("SELF", 4):
            self.assertFalse(seen & set(ring))
            seen |= set(ring)

    def test_map_nodes_are_excluded(self):
        flat = {n for ring in self.graph.rings("SELF", 4) for n in ring}
        self.assertNotIn("M", flat)

    def test_exhausted_graph_yields_empty_rings_not_an_error(self):
        # The chain is SELF-A-B-C-D, so from D the graph is exhausted only at
        # radius 5: ring 4 legitimately holds SELF, four hops away.
        self.assertEqual(self.graph.rings("D", 4)[3], ["SELF"])
        self.assertEqual(self.graph.rings("D", 5)[4], [])

    def test_unknown_seed_returns_empty_rings(self):
        self.assertEqual(self.graph.rings("NOPE", 4), [[], [], [], []])

    def test_compounds_and_genes_partition_by_type(self):
        self.assertEqual(self.graph.compounds(), ["SELF"])
        self.assertEqual(sorted(self.graph.genes()), ["A", "B", "C", "D"])


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
