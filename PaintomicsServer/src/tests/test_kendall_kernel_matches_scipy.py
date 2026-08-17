"""miRNA2Target's Kendall kernel is bit-identical to scipy.stats.kendalltau.

The miRNA-to-gene converter scores every (miRNA, target) pair -- 97,983 in
the shipped STATegra example -- with kendalltau by default, and only reads
`.correlation`. scipy spends most of each ~58 us call on the p-value (an
exact enumeration for short tie-free rows) that is thrown away. The kernel
counts concordant/discordant/tied pairs directly and finishes with scipy's
own tau-b expression on the same integer counts, so the float -- and its
str(), which is what reaches the output file -- is the same. This test pins
that over random rows with heavy ties, constants, perfect (anti)correlation,
NaNs and lengths 1-12, plus the fallback to scipy for rows that are not all
numbers.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_kendall_kernel_matches_scipy
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import numpy as np
from scipy.stats import kendalltau

from src.common.bioscripts import miRNA2Target


def _randomRows(rng):
    k = rng.randint(1, 12)
    kind = rng.random()
    if kind < 0.3:
        x = [rng.randint(0, 3) * 1.0 for _ in range(k)]
        y = [rng.randint(0, 3) * 1.0 for _ in range(k)]
    elif kind < 0.6:
        x = [round(rng.gauss(0, 1), rng.choice([1, 2, 6])) for _ in range(k)]
        y = [round(rng.gauss(0, 1), rng.choice([1, 2, 6])) for _ in range(k)]
    elif kind < 0.7:
        x = [rng.choice([0.0, 1.0]) for _ in range(k)]
        y = [rng.random() for _ in range(k)]
    elif kind < 0.75:
        x = [0.5] * k
        y = [rng.random() for _ in range(k)]
    elif kind < 0.8:
        x = [rng.random() for _ in range(k)]
        y = list(x) if rng.random() < 0.5 else [-v for v in x]
    else:
        x = [rng.uniform(-5, 5) for _ in range(k)]
        y = [rng.uniform(-5, 5) for _ in range(k)]
    if rng.random() < 0.03:
        x[rng.randrange(k)] = float("nan")
    return x, y


class KendallKernelTest(unittest.TestCase):

    def test_bit_identical_to_scipy_over_random_rows(self):
        rng = random.Random(20260817)
        for _ in range(20000):
            x, y = _randomRows(rng)
            want = kendalltau(x, y).correlation
            got = miRNA2Target.kendallTauB(x, y)
            self.assertEqual(repr(got), repr(want), (x, y))

    def test_returns_the_same_type_as_scipy(self):
        got = miRNA2Target.kendallTauB([0.1, 0.5, 0.3], [0.2, 0.9, 0.1])
        self.assertIsInstance(got, np.floating)
        self.assertEqual(str(got), str(kendalltau([0.1, 0.5, 0.3], [0.2, 0.9, 0.1]).correlation))

    def test_getScore_uses_the_kernel_for_kendall(self):
        x = [0.1, -0.5, 0.3, 0.7, -0.2, 0.9]
        y = [0.2, 0.1, -0.4, 0.8, 0.0, -0.3]
        self.assertEqual(str(miRNA2Target.getScore(x, y, "kendall")),
                         str(kendalltau(x, y).correlation))
        # Text rows are parsed exactly as before.
        self.assertEqual(str(miRNA2Target.getScore(["0.1", "-0.5", "0.3"], ["0.2", "0.1", "-0.4"], "kendall")),
                         str(kendalltau([0.1, -0.5, 0.3], [0.2, 0.1, -0.4]).correlation))

    def test_non_numeric_rows_fall_back_to_scipy(self):
        # A row toFloats() refused stays text; scipy compares strings
        # lexicographically and so does the fallback (same call).
        x = ["NA", "0.5", "0.3"]
        y = [0.2, 0.9, 0.1]
        self.assertEqual(repr(miRNA2Target.kendallTauB(x, y)), repr(kendalltau(x, y).correlation))


if __name__ == "__main__":
    unittest.main(verbosity=2)
