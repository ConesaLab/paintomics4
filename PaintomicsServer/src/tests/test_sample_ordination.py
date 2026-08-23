#!/usr/bin/env python3
"""Do the groups separate? The question every one of these papers opens with.

Why this exists
---------------
`feature-backlog.md` ranks sample-level ordination **first** — nine dev studies
want it, effort small. In the TEST scoring it came back `not-derivable` every
time it appeared (2026-41629358 Figs 1A and 3A, 2025-41044368 Fig 1b,
2025-41111196 Fig 1B), because PaintOmics had no per-sample view at all.

It has one now that recipes can keep their replicates. What is pinned here is
the arithmetic and the honesty: a PCA of flat features is a PCA of noise, so
the most variable features are taken first; a job with no per-sample values
must say so rather than project one point per condition; and the separation
statistic is reported with its parts so a reader can disagree with it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_sample_ordination
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import ordination  # noqa: E402

OMIC = "Gene expression"
HEADERS = ["CTRL_rep1", "CTRL_rep2", "CTRL_rep3",
           "TREAT_rep1", "TREAT_rep2", "TREAT_rep3"]


class _OV(object):
    def __init__(self, values, omic=OMIC):
        self._v, self._o = values, omic

    def getOmicName(self):
        return self._o

    def getValues(self):
        return self._v


class _Feature(object):
    def __init__(self, name, values):
        self._n, self._rows = name, [_OV(values)]

    def getName(self):
        return self._n

    def getOmicsValues(self):
        return self._rows


class _Job(object):
    def __init__(self, spec):
        self._f = {n: _Feature(n, v) for n, v in spec.items()}

    def getInputGenesData(self):
        return self._f


def _separating(n_flat=40):
    spec = {"UP%02d" % i: [1.0, 1.1, 0.9, 5.0, 5.1, 4.9] for i in range(10)}
    for i in range(n_flat):
        spec["FLAT%02d" % i] = [2.0, 2.05, 1.95, 2.02, 1.98, 2.01]
    return _Job(spec)


class ArithmeticTest(unittest.TestCase):

    def test_a_separating_design_loads_on_pc1(self):
        res = ordination.ordinate(_separating(), OMIC, HEADERS)
        self.assertEqual(res["n_samples"], 6)
        self.assertGreater(res["pc1_percent"], 80.0,
                           "one dominant axis when one contrast dominates")
        by = {}
        for s in res["samples"]:
            by.setdefault(s["condition"], []).append(s["pc1"])
        self.assertEqual(sorted(by), ["CTRL", "TREAT"])
        # the two groups sit on opposite sides of the origin
        self.assertLess(max(by["CTRL"]) * max(by["TREAT"]), 0)

    def test_separation_reports_its_parts(self):
        res = ordination.ordinate(_separating(), OMIC, HEADERS)
        sep = ordination.separation(res)
        self.assertGreater(sep["ratio"], 1.0)
        self.assertIn("CTRL", sep["group_means"])
        self.assertIn("between", sep)
        self.assertIn("within", sep)

    def test_a_design_that_does_not_separate_says_so(self):
        job = _Job({"F%02d" % i: [2.0, 2.05, 1.95, 2.02, 1.98, 2.01]
                    for i in range(20)})
        sep = ordination.separation(ordination.ordinate(job, OMIC, HEADERS))
        self.assertLess(sep["ratio"], 1.0,
                        "noise must not look like separation")

    def test_variance_percentages_are_a_share(self):
        res = ordination.ordinate(_separating(), OMIC, HEADERS)
        self.assertLessEqual(res["pc1_percent"] + res["pc2_percent"], 100.01)


class HonestyTest(unittest.TestCase):

    def test_a_job_without_samples_refuses(self):
        job = _Job({"G": [1.0, 5.0]})          # one value per condition
        res = ordination.ordinate(job, OMIC, ["CTRL", "TREAT"])
        self.assertIn("no per-sample values", res["error"])
        self.assertIn("No ordination", ordination.format_result(res))

    def test_the_reply_names_the_axes_and_the_samples(self):
        res = ordination.ordinate(_separating(), OMIC, HEADERS)
        text = ordination.format_result(res, ordination.separation(res))
        self.assertIn("PC1 explains", text)
        self.assertIn("CTRL_rep1", text)
        self.assertIn("between-group / within-group", text)
        self.assertIn("if the groups do not separate, say so", text)

    def test_condition_is_read_off_the_replicate_suffix(self):
        self.assertEqual(ordination._condition_of("BAT_6C_24h_rep3"), "BAT_6C_24h")
        self.assertEqual(ordination._condition_of("CTRL"), "CTRL")

    def test_most_variable_features_come_first(self):
        job = _separating(n_flat=200)
        _cols, ids, _rows = ordination.sample_matrix(job, OMIC, max_features=10)
        self.assertTrue(all(i.startswith("UP") for i in ids),
                        "a PCA of flat features is a PCA of noise")


if __name__ == "__main__":
    unittest.main(verbosity=2)
