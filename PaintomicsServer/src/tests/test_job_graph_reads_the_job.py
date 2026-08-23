#!/usr/bin/env python3
"""The graph the network analyst reads must say what the job says. Exactly.

Why this exists
---------------
MORE relationships, KGML relations, pathway membership and similarity each
live in their own shape, and none of them ever reached the agent. JobGraph
folds them into one typed graph and seven bounded tools. These tests pin the
whole contract on a fixture whose right answers are known by hand: the MORE
table in the exact {columns, rows, symbols} shape a real job stores, a hub
whose degree is known, a path whose hops are known, the evidence split, the
filter DSL (parsed, never evaluated), and the FactsLedger ids beside every
number a tool prints.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_job_graph_reads_the_job
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import graph_tools as T          # noqa: E402
from src.classes.AIInterpret.facts import FactsLedger         # noqa: E402
from src.classes.AIInterpret.job_graph import (               # noqa: E402
    JobGraph, _regulation_rows)


def _fixture():
    """Six nodes, known degrees and paths.

    miR-9 regulates Fos (supported), Jun (novel), Ccnd2 (unsupported);
    Ikzf1 regulates Ccnd2 (supported). Fos and Jun sit in mmu04110 with
    Ccnd2; Fos and Ccnd2 also share mmu04151. KGML joins Fos -> Jun.
    Hub by REGULATES out-degree: miR-9 with 3.
    """
    regulation = [
        {"regulator": "miR-9", "target": "Fos", "omic": "miRNA", "area": "a",
         "coefficient": -2.1, "condition": "T1", "targetR2": 0.81,
         "coef_by_condition": {"T1": -2.1, "T2": -0.4},
         "evidence": "supported", "support": ["KEGG", "OmniPath"]},
        {"regulator": "miR-9", "target": "Jun", "omic": "miRNA", "area": "a",
         "coefficient": 1.4, "condition": "T2", "targetR2": 0.55,
         "evidence": "novel"},
        {"regulator": "miR-9", "target": "Ccnd2", "omic": "miRNA", "area": "a",
         "coefficient": 0.3, "condition": "T1", "targetR2": 0.40,
         "evidence": "unsupported"},
        {"regulator": "Ikzf1", "target": "Ccnd2", "omic": "TF", "area": "b",
         "coefficient": 2.6, "condition": "T1", "targetR2": 0.72,
         "evidence": "supported", "support": ["KEGG"]},
    ]
    pathways = [
        {"id": "mmu04110", "name": "Cell cycle", "source": "KEGG",
         "combined_pvalue": 1e-4, "per_omic": {},
         "genes": ["Fos", "Jun", "Ccnd2"], "compounds": []},
        {"id": "mmu04151", "name": "PI3K-Akt", "source": "KEGG",
         "combined_pvalue": 2e-3, "per_omic": {},
         "genes": ["Fos", "Ccnd2"], "compounds": []},
    ]
    kgml = [("Fos", "Jun", "GErel", "mmu04110")]
    return JobGraph.build(regulation=regulation, pathways=pathways, kgml=kgml,
                          conditions=["T1", "T2"])


class BuildTest(unittest.TestCase):

    def test_counts_are_the_fixtures_counts(self):
        s = _fixture().summary()
        self.assertEqual(s["edges"]["REGULATES"], 4)
        self.assertEqual(s["edges"]["MEMBER_OF"], 5)
        self.assertEqual(s["edges"]["KGML"], 1)
        self.assertEqual(s["evidence"],
                         {"supported": 2, "novel": 1, "unsupported": 1,
                          "unclassified": 0})

    def test_a_molecule_with_two_roles_is_one_node(self):
        g = _fixture()
        # Ikzf1 regulates; if it were also a measured gene the cascade must
        # stay connected. Simulate by adding a REGULATES edge INTO Ikzf1.
        g.g.add_edge("miR-9", "Ikzf1", key="REGULATES", type="REGULATES",
                     coefficient=0.5, evidence="novel")
        self.assertIn("regulator", g.g.nodes["Ikzf1"]["roles"])
        out = T.graph_path(g, "miR-9", "Ccnd2")
        self.assertIn("PATHS", out)

    def test_similarity_needs_two_shared_features(self):
        s = _fixture().summary()
        # mmu04110 and mmu04151 share Fos and Ccnd2 -> exactly one edge.
        self.assertEqual(s["edges"]["SIMILAR_TO"], 1)

    def test_the_more_table_shape_a_real_job_stores(self):
        class _Job(object):
            regulationPerConditionData = {
                "columns": ["targetF", "regulator", "omic", "area", "R2",
                            "Group_T1", "Group_T2"],
                "rows": [["Fos", "miR-9", "miRNA", "a", "0.81", "-2.1", "-0.4"],
                         ["Jun", "miR-9", "miRNA", "a", "0.55", "0.2", "1.4"]],
                "symbols": {},
            }
        rows, conditions, _symbols = _regulation_rows(_Job())
        self.assertEqual(conditions, ["T1", "T2"])
        by_target = {r["target"]: r for r in rows}
        self.assertEqual(by_target["Fos"]["coefficient"], -2.1)
        self.assertEqual(by_target["Fos"]["condition"], "T1")
        self.assertEqual(by_target["Fos"]["coef_by_condition"],
                         {"T1": -2.1, "T2": -0.4})
        self.assertEqual(by_target["Jun"]["condition"], "T2")


class SchemaTest(unittest.TestCase):

    def test_schema_names_counts_evidence_and_caveat(self):
        out = T.graph_schema(_fixture())
        self.assertIn("REGULATES 4", out)
        self.assertIn("supported 2", out)
        self.assertIn("not correlations", out)

    def test_an_empty_graph_says_so(self):
        out = T.graph_schema(JobGraph.build())
        self.assertIn("empty", out)


class NeighborsTest(unittest.TestCase):

    def test_ranked_by_coefficient_then_evidence(self):
        out = T.graph_neighbors(_fixture(), "miR-9", direction="out",
                                edge_types=["REGULATES"])
        lines = [l for l in out.splitlines() if "->" in l]
        self.assertIn("Fos", lines[0])          # |−2.1| ranks first
        self.assertIn("Jun", lines[1])
        self.assertIn("Ccnd2", lines[2])

    def test_an_unknown_node_gets_a_usable_message(self):
        out = T.graph_neighbors(_fixture(), "Nonexistium")
        self.assertIn("not in the graph", out)
        self.assertIn("graph_schema", out)

    def test_case_slip_is_forgiven(self):
        out = T.graph_neighbors(_fixture(), "mir-9")
        self.assertIn("NEIGHBOURS of miR-9", out)

    def test_the_cap_is_announced(self):
        out = T.graph_neighbors(_fixture(), "miR-9", top_k=1)
        self.assertIn("more not shown", out)


class HubsTest(unittest.TestCase):

    def test_the_known_hub_ranks_first_with_its_split(self):
        out = T.graph_hubs(_fixture())
        first = [l for l in out.splitlines() if "target(s)" in l][0]
        self.assertIn("miR-9", first)
        self.assertIn("3 target(s)", first)
        self.assertIn("supported 1", first)

    def test_within_pathway_restricts_to_members(self):
        out = T.graph_hubs(_fixture(), within_pathway="mmu04151")
        self.assertNotIn("Jun", out)            # Jun is not in mmu04151
        self.assertIn("miR-9", out)


class PathTest(unittest.TestCase):

    def test_the_known_two_hop_path_is_found_with_evidence(self):
        out = T.graph_path(_fixture(), "Ikzf1", "miR-9")
        self.assertIn("PATHS", out)
        self.assertIn("REGULATES(supported)", out)   # Ikzf1 -> Ccnd2 hop

    def test_no_path_is_a_sentence_not_an_error(self):
        g = _fixture()
        g.g.add_node("Lonely", kind="gene", roles={"gene"})
        out = T.graph_path(g, "Lonely", "Fos")
        self.assertIn("no ", out.lower())


class SubgraphTest(unittest.TestCase):

    def test_members_edges_and_split_are_reported(self):
        out = T.graph_subgraph(_fixture(), "mmu04110")
        self.assertIn("3 member(s)", out)
        self.assertIn("evidence", out)
        self.assertIn("supported", out)
        self.assertIn("sign +", out)

    def test_a_non_pathway_is_refused_by_name(self):
        out = T.graph_subgraph(_fixture(), "Fos")
        self.assertIn("not a pathway", out)


class EvidenceTest(unittest.TestCase):

    def test_per_condition_coefficients_and_sources(self):
        out = T.graph_evidence(_fixture(), "miR-9", "Fos")
        self.assertIn("T1 -2.10", out)
        self.assertIn("T2 -0.40", out)
        self.assertIn("KEGG, OmniPath", out)
        self.assertIn("no p-values", out)

    def test_a_missing_claim_points_at_neighbors(self):
        out = T.graph_evidence(_fixture(), "Fos", "Jun")
        self.assertIn("no REGULATES edge", out)
        self.assertIn("graph_neighbors", out)


class FilterTest(unittest.TestCase):

    def test_the_documented_example_works(self):
        out = T.graph_filter(_fixture(),
                             "type == REGULATES and abs(coef) > 1 "
                             "and evidence == supported")
        self.assertIn("2 edge(s)", out)
        self.assertIn("Ikzf1", out)
        self.assertIn("Fos", out)
        self.assertNotIn("Jun ", out)

    def test_a_bad_clause_teaches_the_grammar(self):
        out = T.graph_filter(_fixture(), "coef ~ 1")
        self.assertIn("cannot parse", out)
        self.assertIn("FIELD OP VALUE", out)

    def test_code_is_data_here_not_execution(self):
        # If any eval existed, this would raise or execute; it must simply
        # fail to parse.
        out = T.graph_filter(_fixture(), "__import__('os').system('true') == 1")
        self.assertIn("cannot parse", out)

    def test_numeric_fields_refuse_words(self):
        out = T.graph_filter(_fixture(), "coef > strong")
        self.assertIn("non-number", out)


class LedgerTest(unittest.TestCase):

    def test_every_printed_number_gets_an_id(self):
        ledger = FactsLedger()
        out = T.graph_hubs(_fixture(), ledger=ledger)
        self.assertIn("[f", out)
        self.assertGreater(len(ledger), 0)
        kinds = {f.kind for f in ledger.items()}
        self.assertIn("count", kinds)
        self.assertIn("coef", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
