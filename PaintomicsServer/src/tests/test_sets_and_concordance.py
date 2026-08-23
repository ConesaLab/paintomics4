#!/usr/bin/env python3
"""The comparisons a paper runs, derived from the job and tested honestly.

Why this exists
---------------
compare_sets needed the agent to already hold two symbol lists. The
descriptor grammar makes the job's own slices addressable ("up in RNA at
T1"), the inventory derives every comparison the job can support, the k-way
test reports its floor, and concordance counts sign agreement over shared
relevant features. Fixtures are small enough that every number is checkable
by hand.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_sets_and_concordance
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import sets as S               # noqa: E402
from src.classes.AIInterpret.layer_matrix import Layer, LayerMatrix  # noqa: E402


def _layer(omic, rows, columns=("T1", "T2"), kind="gene"):
    """rows: [(label, values, relevant)]"""
    layer = Layer(omic, kind, list(columns))
    for i, (label, values, relevant) in enumerate(rows):
        layer.feature_ids.append("%s-%d" % (omic, i))
        layer.labels.append(label)
        layer.values.append(list(values))
        layer.relevant.append(relevant)
    return layer


def _matrix():
    rna = _layer("RNA", [
        ("FOS", [2.0, 1.0], True),      # up at T1 and T2
        ("JUN", [-1.5, 0.5], True),     # down at T1, up at T2
        ("MYC", [0.5, -2.0], True),     # up at T1, down at T2 (strongest T2)
        ("ACTB", [0.1, 0.1], False),    # not relevant
    ])
    prot = _layer("Protein", [
        ("FOS", [1.0, 2.0], True),
        ("JUN", [1.2, 0.3], True),      # sign DISAGREES with RNA at T1
        ("EGFR", [-0.7, -0.1], True),
    ])
    return LayerMatrix({"RNA": rna, "Protein": prot})


class DescriptorTest(unittest.TestCase):

    def test_relevant_in_layer(self):
        labels, note = S.resolve_descriptor(_matrix(), "relevant in RNA")
        self.assertEqual(sorted(labels), ["FOS", "JUN", "MYC"])
        self.assertIn("relevant list", note)

    def test_up_at_a_condition_reads_the_sign_there(self):
        labels, _ = S.resolve_descriptor(_matrix(), "up in RNA at T1")
        self.assertEqual(sorted(labels), ["FOS", "MYC"])
        labels, _ = S.resolve_descriptor(_matrix(), "down in RNA at T1")
        self.assertEqual(labels, ["JUN"])

    def test_without_a_condition_the_strongest_one_decides(self):
        labels, note = S.resolve_descriptor(_matrix(), "down in RNA")
        # MYC's strongest value is -2.0 at T2; JUN's is -1.5 at T1.
        self.assertEqual(sorted(labels), ["JUN", "MYC"])
        self.assertIn("strongest condition", note)

    def test_bad_grammar_teaches_the_grammar(self):
        labels, note = S.resolve_descriptor(_matrix(), "sideways in RNA")
        self.assertIsNone(labels)
        self.assertIn("relevant|up|down in", note)

    def test_unknown_layer_and_condition_are_named(self):
        labels, note = S.resolve_descriptor(_matrix(), "up in Metabolome")
        self.assertIsNone(labels)
        self.assertIn("Metabolome", note)
        labels, note = S.resolve_descriptor(_matrix(), "up in RNA at T9")
        self.assertIsNone(labels)
        self.assertIn("T9", note)

    def test_case_slips_are_forgiven(self):
        labels, _ = S.resolve_descriptor(_matrix(), "UP in rna at t1")
        self.assertEqual(sorted(labels), ["FOS", "MYC"])


class MultisetTest(unittest.TestCase):

    UNIVERSE = {"A%d" % i for i in range(50)} | {"FOS", "JUN", "MYC"}

    def test_two_sets_get_the_exact_tail(self):
        res = S.multiset_test([("x", {"FOS", "JUN", "A1"}),
                               ("y", {"FOS", "JUN", "A2"})], self.UNIVERSE)
        self.assertEqual(res["intersection"], 2)
        self.assertEqual(res["method"], "exact hypergeometric")
        self.assertLess(res["p"], 0.01)

    def test_three_sets_report_the_permutation_floor(self):
        res = S.multiset_test([("x", {"FOS", "JUN"}), ("y", {"FOS", "JUN"}),
                               ("z", {"FOS", "JUN"})], self.UNIVERSE,
                              n_permutations=999, seed=1)
        self.assertIn("permutation", res["method"])
        self.assertAlmostEqual(res["min_attainable_p"], 1 / 1000)
        self.assertGreaterEqual(res["p"], res["min_attainable_p"])
        self.assertLess(res["p"], 0.05)

    def test_members_outside_the_universe_are_counted_not_hidden(self):
        res = S.multiset_test([("x", {"FOS", "NOTMEASURED"}),
                               ("y", {"FOS"})], self.UNIVERSE)
        by_name = {s["name"]: s for s in res["sets"]}
        self.assertEqual(by_name["x"]["outside_universe"], 1)

    def test_the_same_seed_gives_the_same_p(self):
        args = ([("x", {"FOS"}), ("y", {"FOS"}), ("z", {"FOS"})],
                self.UNIVERSE)
        a = S.multiset_test(*args, n_permutations=500, seed=7)
        b = S.multiset_test(*args, n_permutations=500, seed=7)
        self.assertEqual(a["p"], b["p"])


class InventoryTest(unittest.TestCase):

    def test_the_inventory_is_derived_and_ordered(self):
        inv = S.comparison_inventory(_matrix())
        self.assertIn("relevant in RNA", inv["sets"])
        self.assertIn("up in Protein", inv["sets"])
        self.assertIn(("relevant in RNA", "relevant in Protein"),
                      inv["pairs"])
        self.assertIn(("up in RNA", "down in RNA"), inv["pairs"])
        self.assertEqual(inv["dropped_pairs"], 0)

    def test_every_inventory_entry_resolves(self):
        matrix = _matrix()
        inv = S.comparison_inventory(matrix)
        for descriptor in inv["sets"]:
            labels, note = S.resolve_descriptor(matrix, descriptor)
            self.assertIsNotNone(labels, note)


class ConcordanceTest(unittest.TestCase):

    def test_quadrants_and_agreement_are_hand_checkable(self):
        res = S.concordance(_matrix(), "RNA", "Protein", condition="T1")
        # Shared relevant: FOS (2.0, 1.0) ++ and JUN (-1.5, 1.2) -+.
        self.assertEqual(res["n_shared"], 2)
        self.assertEqual(res["quadrants"]["++"], 1)
        self.assertEqual(res["quadrants"]["-+"], 1)
        self.assertEqual(res["agreement"], 0.5)

    def test_a_missing_layer_is_an_error_not_a_crash(self):
        self.assertIn("error", S.concordance(_matrix(), "RNA", "Lipidome"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
