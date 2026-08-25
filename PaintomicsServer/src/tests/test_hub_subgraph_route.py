#!/usr/bin/env python3
"""The induced subgraph a network view draws, and who is allowed to ask for it.

The graph has always existed on the server and never reached the browser:
`compoundRegulateFeatures` ships node SETS with no pairs, no direction, no edge
types and no intermediate hops, so a client cannot tell whether a radius-3 gene
reaches the metabolite via gene X or gene Y. That is why no network was ever
drawn in this application.

Two things the route must get right:
  * a cap must never read as "this is all there is" -- hence `truncated`;
  * /check_job_status ships hub payloads with NO session and NO ownership check
    (paintomicsserver.py:589-591). The new route does not repeat that.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph.graph import KeggGraph
from src.common.KeggGraph.parser import Edge


def build():
    edges = [Edge("C1", "g1", "PPrel", "activation", "p1", False),
             Edge("C1", "g2", "reaction", "rn:R1", "p1", True),
             Edge("g1", "g3", "PPrel", "inhibition", "p2", False),
             Edge("g3", "g4", "PPrel", "", "p2", False)]
    types = {"C1": "compound", "g1": "gene", "g2": "gene",
             "g3": "gene", "g4": "gene"}
    return KeggGraph(edges, types, "test")


class SubgraphTest(unittest.TestCase):
    def setUp(self):
        self.graph = build()

    def test_seed_is_present_at_step_zero(self):
        out = self.graph.subgraph("C1", 2, 100)
        seed = [n for n in out["nodes"] if n["id"] == "C1"]
        self.assertEqual(len(seed), 1)
        self.assertEqual(seed[0]["step"], 0)

    def test_every_node_carries_its_hop_distance(self):
        steps = {n["id"]: n["step"]
                 for n in self.graph.subgraph("C1", 3, 100)["nodes"]}
        self.assertEqual(steps["g1"], 1)
        self.assertEqual(steps["g2"], 1)
        self.assertEqual(steps["g3"], 2)
        self.assertEqual(steps["g4"], 3)

    def test_level_bounds_the_subgraph(self):
        ids = {n["id"] for n in self.graph.subgraph("C1", 1, 100)["nodes"]}
        self.assertEqual(ids, {"C1", "g1", "g2"})

    def test_edges_are_induced_on_the_returned_nodes(self):
        out = self.graph.subgraph("C1", 1, 100)
        ids = {n["id"] for n in out["nodes"]}
        for edge in out["edges"]:
            self.assertIn(edge["source"], ids)
            self.assertIn(edge["target"], ids)

    def test_edge_attributes_survive(self):
        out = self.graph.subgraph("C1", 1, 100)
        found = {(e["source"], e["target"]): e for e in out["edges"]}
        pair = found.get(("C1", "g2")) or found.get(("g2", "C1"))
        self.assertIsNotNone(pair)
        self.assertEqual(pair["kind"], "reaction")
        self.assertTrue(pair["reversible"])
        self.assertEqual(pair["pathway"], "p1")

    def test_budget_truncates_and_says_so(self):
        out = self.graph.subgraph("C1", 3, 2)
        self.assertTrue(out["truncated"])
        self.assertLessEqual(len(out["edges"]), 2)

    def test_untruncated_result_says_so(self):
        self.assertFalse(self.graph.subgraph("C1", 1, 100)["truncated"])

    def test_truncation_keeps_the_edges_nearest_the_seed(self):
        out = self.graph.subgraph("C1", 3, 2)
        for edge in out["edges"]:
            self.assertIn("C1", (edge["source"], edge["target"]))

    def test_unknown_seed_returns_an_empty_subgraph_not_an_error(self):
        out = self.graph.subgraph("NOPE", 2, 100)
        self.assertEqual(out["nodes"], [])
        self.assertEqual(out["edges"], [])

    def test_source_is_reported(self):
        self.assertEqual(self.graph.subgraph("C1", 1, 100)["source"], "test")


class RouteWiringTest(unittest.TestCase):
    """The route exists and is guarded. Read from source, the way the two
    field-list tests in test_hub_analysis_survives_reopen.py do."""

    def _read(self, *parts):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), *parts)
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_route_is_registered(self):
        self.assertIn("/pa_hub_subgraph", self._read("paintomicsserver.py"))

    def test_handler_is_imported(self):
        self.assertIn("pathwayAcquisitionHubSubgraph",
                      self._read("paintomicsserver.py"))

    def test_handler_checks_ownership(self):
        source = self._read("servlets", "PathwayAcquisitionServlet.py")
        start = source.index("def pathwayAcquisitionHubSubgraph")
        body = source[start:start + 3000]
        self.assertIn("getUserID", body)
        self.assertIn("getAllowSharing", body)

    def test_level_and_budget_are_clamped(self):
        source = self._read("servlets", "PathwayAcquisitionServlet.py")
        start = source.index("def pathwayAcquisitionHubSubgraph")
        body = source[start:start + 3000]
        self.assertIn("min(4", body)
        self.assertIn("min(2000", body)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
