#!/usr/bin/env python3
"""Per-feature statistics from the replicates PaintOmics already ingests.

Why this exists
---------------
The Phase B backlog ranks "differential expression from a count matrix" and
"differential abundance from an intensity matrix" as wanted by 16 of 19 dev
studies each — the two highest-n features in the programme — and the
COMPARISON files complain, run after run, that "no per-gene logFC/p/FDR and
no DEG count appear anywhere".

The replicates were never the problem: `OmicValue.getValues()` already holds
one number per replicate column and the job's replicate mapping already says
which columns belong to which condition. They were being averaged away and
never tested.

Pinned here:
  * the arithmetic — BH against a hand-computed vector, Welch against SciPy;
  * the honesty — features with too few replicates are skipped and COUNTED,
    an omic with no replicate mapping says so rather than inventing a test,
    and the reply names the test and the n;
  * the refusal to overclaim — this is Welch on already-log-transformed
    values, not a negative-binomial count model, and it says so.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_differential_statistics_from_replicates
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import differential  # noqa: E402

OMIC = "Gene expression"
# 6 replicate columns: 0-2 = CTRL, 3-5 = TREAT
GROUPS = [[0, 1, 2], [3, 4, 5]]
HEADER = ["CTRL", "TREAT"]


class _OV(object):
    def __init__(self, values, omic=OMIC):
        self._v, self._o = values, omic

    def getOmicName(self):
        return self._o

    def getValues(self):
        return self._v


class _Feature(object):
    def __init__(self, name, values, omic=OMIC):
        self._name, self._rows = name, [_OV(values, omic)]

    def getName(self):
        return self._name

    def getOmicsValues(self):
        return self._rows


class _Job(object):
    def __init__(self, features, header=HEADER, groups=GROUPS):
        self._f = features
        self.geneBasedInputOmics = [{
            "omicName": OMIC, "sampleHeader": list(header),
            "replicateMapping": [list(g) for g in groups],
        }]
        self.compoundBasedInputOmics = []

    def getInputGenesData(self):
        return self._f


def _job(spec, **kw):
    return _Job({n: _Feature(n, v) for n, v in spec.items()}, **kw)


class ArithmeticTest(unittest.TestCase):

    def test_a_clear_difference_is_significant_and_signed(self):
        job = _job({"UP": [1.0, 1.1, 0.9, 5.0, 5.1, 4.9],
                    "DOWN": [8.0, 8.1, 7.9, 2.0, 2.1, 1.9],
                    "FLAT": [3.0, 3.1, 2.9, 3.0, 3.1, 2.9]})
        res = differential.differential_test(job, OMIC, "CTRL", "TREAT")
        by = {r["feature"]: r for r in res["rows"]}
        self.assertAlmostEqual(by["UP"]["log2FC"], 4.0, places=3)
        self.assertAlmostEqual(by["DOWN"]["log2FC"], -6.0, places=3)
        self.assertLess(by["UP"]["p"], 0.01)
        self.assertGreater(by["FLAT"]["p"], 0.05)
        self.assertEqual(res["up_in_b"], 1)
        self.assertEqual(res["down_in_b"], 1)

    def test_welch_matches_scipy(self):
        from scipy import stats
        a, b = [1.0, 2.0, 3.0], [7.0, 9.0, 11.0]
        job = _job({"G": a + b})
        res = differential.differential_test(job, OMIC, "CTRL", "TREAT")
        expected = stats.ttest_ind(a, b, equal_var=False).pvalue
        self.assertAlmostEqual(res["rows"][0]["p"], float(expected), places=12)

    def test_bh_matches_the_closed_form(self):
        p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
        q = differential._bh(p)
        # classic Benjamini-Hochberg worked example
        self.assertAlmostEqual(q[0], 0.008, places=3)
        self.assertAlmostEqual(q[1], 0.032, places=3)
        self.assertAlmostEqual(q[4], 0.0672, places=3)
        self.assertTrue(all(q[i] <= q[i + 1] + 1e-12 for i in range(len(q) - 1)),
                        "q must be monotone in p for a sorted input")

    def test_q_is_never_smaller_than_p(self):
        job = _job({"A": [1.0, 1.1, 1.2, 4.0, 4.1, 4.2],
                    "B": [2.0, 2.2, 2.1, 2.3, 2.2, 2.1],
                    "C": [5.0, 5.2, 5.1, 1.0, 1.2, 1.1]})
        res = differential.differential_test(job, OMIC, "CTRL", "TREAT")
        for r in res["rows"]:
            self.assertGreaterEqual(r["q"] + 1e-12, r["p"], r["feature"])


class HonestyTest(unittest.TestCase):

    def test_an_omic_without_replicates_refuses(self):
        job = _job({"G": [1.0, 2.0]}, header=[], groups=[])
        res = differential.differential_test(job, OMIC, "CTRL", "TREAT")
        self.assertIn("no replicate mapping", res["error"])

    def test_too_few_replicates_refuses_rather_than_guesses(self):
        job = _job({"G": [1.0, 5.0]}, header=["A", "B"], groups=[[0], [1]])
        res = differential.differential_test(job, OMIC, "A", "B")
        self.assertIn("at least 2 replicates", res["error"])

    def test_features_with_missing_values_are_skipped_and_counted(self):
        job = _job({"OK": [1.0, 1.1, 0.9, 5.0, 5.1, 4.9],
                    "SPARSE": [1.0, None, None, 5.0, None, None]})
        res = differential.differential_test(job, OMIC, "CTRL", "TREAT")
        self.assertEqual(res["tested"], 1)
        self.assertEqual(res["skipped"], 1)
        self.assertIn("1 skipped", differential.format_result(res))

    def test_an_unknown_condition_lists_the_real_ones(self):
        res = differential.differential_test(_job({"G": [1.0] * 6}), OMIC,
                                             "CTRL", "NOPE")
        self.assertIn("CTRL", res["error"])
        self.assertIn("TREAT", res["error"])

    def test_the_same_condition_twice_is_refused(self):
        res = differential.differential_test(_job({"G": [1.0] * 6}), OMIC,
                                             "CTRL", "ctrl")
        self.assertIn("same", res["error"])

    def test_the_reply_names_the_test_the_n_and_its_limits(self):
        job = _job({"UP": [1.0, 1.1, 0.9, 5.0, 5.1, 4.9]})
        text = differential.format_result(
            differential.differential_test(job, OMIC, "CTRL", "TREAT"))
        self.assertIn("CTRL (n=3)", text)
        self.assertIn("Welch", text)
        self.assertIn("Benjamini-Hochberg", text)
        self.assertIn("Not a negative-binomial", text)
        self.assertIn("Quote q, not p", text)

    def test_available_conditions_reports_replicate_counts(self):
        got = differential.available_conditions(_job({"G": [1.0] * 6}), OMIC)
        self.assertEqual(got, [{"name": "CTRL", "replicates": 3},
                               {"name": "TREAT", "replicates": 3}])


class ScaleTest(unittest.TestCase):

    def test_many_features_stay_ordered_by_q(self):
        spec = {}
        for i in range(300):
            shift = 4.0 if i < 20 else 0.0
            spec["G%03d" % i] = [1.0, 1.1, 0.9,
                                 1.0 + shift, 1.1 + shift, 0.9 + shift]
        res = differential.differential_test(_job(spec), OMIC, "CTRL", "TREAT")
        self.assertEqual(res["tested"], 300)
        self.assertEqual(res["significant"], 20)
        qs = [r["q"] for r in res["rows"]]
        self.assertEqual(qs, sorted(qs), "rows must come back ordered by q")


if __name__ == "__main__":
    unittest.main(verbosity=2)
