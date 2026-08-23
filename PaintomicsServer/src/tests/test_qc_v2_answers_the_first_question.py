#!/usr/bin/env python3
"""Do the groups separate, which features drive it, and can the design say so?

Why this exists
---------------
ordination v1 stopped at "PC1 separates". A Results opening needs the
loadings, a test that respects the permutation structure, an outlier rule
stated as a rule, and the design's own floor: a 3v3 PERMANOVA has exactly 20
distinct relabellings, so p can never go below 0.05 and a report that prints
"p < 0.05" from that design is overstating its data. These fixtures are built
so every right answer is known by hand.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_qc_v2_answers_the_first_question
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import qc                      # noqa: E402
from src.classes.AIInterpret.layer_matrix import Layer, LayerMatrix  # noqa: E402

SAMPLES = ["A_rep1", "A_rep2", "A_rep3", "B_rep1", "B_rep2", "B_rep3"]


def _layer(rows, labels=None, columns=None, omic="RNA"):
    layer = Layer(omic, "gene", list(columns or SAMPLES))
    for i, values in enumerate(rows):
        layer.feature_ids.append("g%d" % i)
        layer.labels.append((labels or ["F%d" % j for j in range(len(rows))])[i])
        layer.values.append(list(values))
        layer.relevant.append(False)
    return layer


def _separating_layer():
    """DRIVER shifts by 50 in B; the other features are a shared ramp.

    Correlation is scale- and shift-invariant, so replicates must share a
    feature-varying SHAPE (the ramp b_j = j), not merely small numbers: the
    first version of this fixture gave replicates alternating-sign noise and
    the outlier rule flagged every sample -- correctly.
    """
    jitter = [0.00, 0.02, -0.01, 0.01, -0.02, 0.03]
    rows = [[0 + jitter[i] + (50.0 if i >= 3 else 0.0) for i in range(6)]]
    for j in range(1, 10):
        rows.append([float(j) + jitter[i] * (1 + j % 3) for i in range(6)])
    return _layer(rows, labels=["DRIVER"] + ["ramp%d" % j for j in range(1, 10)])


class OrdinationTest(unittest.TestCase):

    def test_pc1_separates_and_the_driver_loads_first(self):
        res = qc.ordinate_layer(_separating_layer())
        self.assertNotIn("error", res)
        self.assertGreater(res["pc1_percent"], 90)
        by_cond = {}
        for s in res["samples"]:
            by_cond.setdefault(s["condition"], []).append(s["pc1"])
        self.assertEqual(sorted(by_cond), ["A", "B"])
        # Every A on one side, every B on the other.
        self.assertTrue(max(by_cond["A"]) < min(by_cond["B"])
                        or min(by_cond["A"]) > max(by_cond["B"]))
        self.assertEqual(res["loadings"]["PC1"][0]["feature"], "DRIVER")

    def test_too_few_samples_is_an_error_not_a_projection(self):
        layer = _layer([[1.0, 2.0]], columns=["A", "B"])
        self.assertIn("error", qc.ordinate_layer(layer))


class PermanovaTest(unittest.TestCase):

    def test_3v3_is_enumerated_exactly_with_its_floor(self):
        res = qc.permanova(_separating_layer())
        self.assertNotIn("error", res)
        self.assertTrue(res["exact"])
        self.assertEqual(res["n_relabellings"], 20)     # 6!/(3!3!)
        self.assertAlmostEqual(res["min_attainable_p"], 0.05)
        # The true labelling and its mirror share the maximal F: p = 2/20.
        self.assertLessEqual(res["p"], 0.1 + 1e-9)
        self.assertGreaterEqual(res["p"], res["min_attainable_p"] - 1e-9)

    def test_no_replicates_means_nothing_to_permute(self):
        layer = _layer([[0.0, 5.0, 2.0]], columns=["A", "B", "C"])
        res = qc.permanova(layer)
        self.assertIn("error", res)
        self.assertIn("permute", res["error"])

    def test_the_floor_never_undercuts_the_design(self):
        res = qc.permanova(_separating_layer())
        self.assertGreaterEqual(res["p"], res["min_attainable_p"] - 1e-12)


class CorrelationTest(unittest.TestCase):

    def _with_outlier(self):
        # 20 ramp features; A_rep3's ramp runs BACKWARDS, so it anti-
        # correlates with its own condition's replicates.
        rows = []
        for j in range(20):
            a = float(j)
            rows.append([a, a + 0.01, 19.0 - a,            # A_rep3 reversed
                         a * 0.5, a * 0.5 + 0.01, a * 0.5 - 0.01])
        return _layer(rows)

    def test_the_flipped_replicate_is_named_by_the_rule(self):
        res = qc.sample_correlation(self._with_outlier())
        self.assertNotIn("error", res)
        names = [o["sample"] for o in res["outliers"]]
        self.assertIn("A_rep3", names)
        self.assertIn("within-condition mean r", res["outlier_rule"])

    def test_clean_replicates_raise_no_outlier(self):
        res = qc.sample_correlation(_separating_layer())
        self.assertEqual(res["outliers"], [])

    def test_a_replicate_batch_is_called_out(self):
        # rep1 of BOTH conditions carries a REVERSED ramp -- a shared
        # artefact with a different shape, so clustering (correlation
        # distance) groups the rep1s together across conditions.
        rows = []
        for j in range(20):
            a = 0.5 * j
            artefact = 10.0 - 0.5 * j
            rows.append([artefact, a, a + 0.02,
                         artefact + 0.01, a + 0.01, a + 0.03])
        res = qc.sample_correlation(_layer(rows))
        self.assertIsNotNone(res["batch_warning"])
        self.assertIn("replicate index", res["batch_warning"])


class MoversAndLimitsTest(unittest.TestCase):

    def test_movers_rank_by_range(self):
        layer = _layer([[0.0, 0.0, 0.0, 9.0, 9.0, 9.0],
                        [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]],
                       labels=["BIG", "SMALL"])
        movers = qc.top_movers(layer, k=2)
        self.assertEqual([m["feature"] for m in movers], ["BIG", "SMALL"])
        self.assertEqual(movers[0]["range"], 9.0)

    def test_limits_name_the_no_replicate_design(self):
        layer = _layer([[1.0, 2.0, 3.0]], columns=["A", "B", "C"])
        matrix = LayerMatrix({"RNA": layer})
        limits = qc.data_limits(matrix)[0]
        self.assertFalse(limits["replicates"])
        self.assertTrue(any("no within-condition variance" in l
                            for l in limits["limits"]))

    def test_limits_see_replicates_when_present(self):
        matrix = LayerMatrix({"RNA": _separating_layer()})
        limits = qc.data_limits(matrix)[0]
        self.assertTrue(limits["replicates"])
        self.assertEqual(limits["n_conditions"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
