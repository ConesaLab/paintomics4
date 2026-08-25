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
        """Both hub routes go through the one guarded loader.

        The check used to be inlined here. It moved into _hubOwnedJob when the
        second route arrived, precisely so a new route cannot ship without it --
        so the assertion is now "the route delegates" plus "the delegate
        checks", which is what actually has to hold.
        """
        source = self._read("servlets", "PathwayAcquisitionServlet.py")
        start = source.index("def pathwayAcquisitionHubSubgraph")
        body = source[start:start + 3000]
        self.assertIn("_hubOwnedJob(", body)

        guard = source[source.index("def _hubOwnedJob"):]
        guard = guard[:guard.index("def pathwayAcquisitionHubSubgraph")]
        self.assertIn("getUserID", guard)
        self.assertIn("getAllowSharing", guard)

    def test_the_feature_route_is_guarded_the_same_way(self):
        source = self._read("servlets", "PathwayAcquisitionServlet.py")
        start = source.index("def pathwayAcquisitionHubFeature")
        body = source[start:start + 3000]
        self.assertIn("_hubOwnedJob(", body)

    def test_the_feature_route_is_registered_and_imported(self):
        server = self._read("paintomicsserver.py")
        self.assertIn("/pa_hub_feature", server)
        self.assertIn("pathwayAcquisitionHubFeature", server)

    def test_the_feature_route_ships_every_omic(self):
        """globalExpressionData carries omicsValues[0] only; this route is the
        rest of the feature, so it must iterate the whole list.

        Read from the CODE, not the whole function: this docstring and the
        route's own explain why omicsValues[0] is not enough, and an assertion
        that matched prose would pass on a comment while the code did the
        wrong thing. That has caught me three times on this branch.
        """
        source = self._read("servlets", "PathwayAcquisitionServlet.py")
        start = source.index("def pathwayAcquisitionHubFeature")
        body = source[start:start + 3000]
        code = body[body.index("    try:"):]
        self.assertIn("feature.omicsValues", code)
        self.assertNotIn("omicsValues[0]", code)
        self.assertIn('"omicName"', code)

    def test_a_feature_that_was_never_measured_is_not_an_error(self):
        """Most nodes in a radius-4 ring were never measured, and the client
        draws a "how it connects" panel for those."""
        source = self._read("servlets", "PathwayAcquisitionServlet.py")
        start = source.index("def pathwayAcquisitionHubFeature")
        body = source[start:start + 3000]
        window = body[body.index("if feature is None"):]
        self.assertIn('"success": True', window[:400])

    def test_level_and_budget_are_clamped(self):
        source = self._read("servlets", "PathwayAcquisitionServlet.py")
        start = source.index("def pathwayAcquisitionHubSubgraph")
        body = source[start:start + 3000]
        self.assertIn("min(4", body)
        self.assertIn("min(2000", body)



class PerRingBudgetTest(unittest.TestCase):
    """Every ring must be represented, and DE nodes must survive the sample.

    The first version ranked all candidate edges by distance from the seed and
    truncated at `budget`. Rings 1 and 2 ate the whole allowance, so levels 2, 3
    and 4 returned BYTE-IDENTICAL subgraphs -- measured on job fh304774Lw,
    C00097: 147 nodes and {step 0:1, 1:17, 2:129} at every one of those levels,
    with no step-3 or step-4 node at all. `truncated` was true, which was
    technically honest and completely hid that entire rings were missing.
    """

    def _wide(self):
        """A seed with a small ring 1 and a ring 2 far larger than any quota."""
        edges = [Edge("C1", "hub", "PPrel", "", "p", False)]
        types = {"C1": "compound", "hub": "gene"}
        for index in range(100):
            name = "g%03d" % index
            edges.append(Edge("hub", name, "PPrel", "", "p", False))
            types[name] = "gene"
        return KeggGraph(edges, types, "test")

    def test_each_level_adds_its_own_ring(self):
        graph = self._wide()
        seen = []
        for level in (1, 2):
            out = graph.subgraph("C1", level, 500, per_ring=10)
            seen.append(max(n["step"] for n in out["nodes"]))
        self.assertEqual(seen, [1, 2])

    def test_a_big_ring_is_sampled_not_dropped(self):
        out = self._wide().subgraph("C1", 2, 500, per_ring=10)
        ring2 = [r for r in out["rings"] if r["step"] == 2][0]
        self.assertEqual(ring2["total"], 100)
        self.assertGreater(ring2["shown"], 0)
        self.assertLess(ring2["shown"], 100)

    def test_de_nodes_are_kept_first(self):
        """The sample must preserve the signal the panel exists to show."""
        graph = self._wide()
        priority = {"g0%02d" % i for i in range(90, 100)}
        out = graph.subgraph("C1", 2, 500, priority=priority, per_ring=5)
        shown = {n["id"] for n in out["nodes"] if n["step"] == 2}
        self.assertTrue(shown.issubset(priority),
                        "a non-DE node displaced a DE one: %s" % (shown - priority))

    def test_unused_quota_carries_outward(self):
        """Ring 1 needs one slot; ring 2 should get the rest."""
        out = self._wide().subgraph("C1", 2, 500, per_ring=10)
        ring1 = [r for r in out["rings"] if r["step"] == 1][0]
        ring2 = [r for r in out["rings"] if r["step"] == 2][0]
        self.assertEqual(ring1["shown"], 1)
        self.assertGreater(ring2["shown"], 10)

    def test_rings_report_shown_against_total(self):
        out = self._wide().subgraph("C1", 2, 500, per_ring=10)
        for ring in out["rings"]:
            self.assertIn("shown", ring)
            self.assertIn("total", ring)
            self.assertIn("de_shown", ring)
            self.assertIn("de_total", ring)
            self.assertLessEqual(ring["shown"], ring["total"])

    def test_sampling_sets_truncated_even_when_edges_fit(self):
        out = self._wide().subgraph("C1", 2, 5000, per_ring=10)
        self.assertTrue(out["truncated"])
        self.assertGreater(out["nodes_dropped"], 0)

    def test_nothing_dropped_means_not_truncated(self):
        out = self._wide().subgraph("C1", 2, 5000, per_ring=500)
        self.assertFalse(out["truncated"])
        self.assertEqual(out["nodes_dropped"], 0)

    def test_the_servlet_passes_a_de_priority_set(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "servlets",
            "PathwayAcquisitionServlet.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("def pathwayAcquisitionHubSubgraph")
        body = source[start:start + 4000]
        self.assertIn("priority=priority", body)
        self.assertIn("isRelevantAssociation()", body)

    def test_the_priority_set_is_not_limited_to_one_omic_name(self):
        """It asked for omicName == "Gene expression" and nothing else.

        That name is only the default the upload form suggests for the first
        omic; a job whose omics are called "RNA-seq" and "Proteomics" is not a
        job without differential expression, and its priority set came out
        empty -- so every large ring was sampled by degree alone and the DE
        genes the panel exists to show were the ones dropped.
        """
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "servlets",
            "PathwayAcquisitionServlet.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("def pathwayAcquisitionHubSubgraph")
        body = source[start:start + 4000]
        window = body[body.index("priority = set()"):body.index("payload = graph.subgraph")]
        self.assertNotIn('"Gene expression"', window)

    def test_the_priority_set_asks_isRelevant_not_the_list(self):
        """`relevant` is a LIST, and a list of all-False is truthy."""
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "servlets",
            "PathwayAcquisitionServlet.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("def pathwayAcquisitionHubSubgraph")
        body = source[start:start + 4000]
        window = body[body.index("priority = set()"):body.index("payload = graph.subgraph")]
        self.assertIn("isRelevant()", window)
        self.assertNotIn("values.relevant or", window)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
