#!/usr/bin/env python3
"""The unit-test shards must be split by cost, not by filename spelling.

The behaviour this guards
-------------------------
scripts/ci/run_suites.py splits the sweep across the pr.yml matrix. It used to
do it with

    names = [name for position, name in enumerate(names)
             if position % count == index - 1]

over the ALPHABETICALLY sorted filenames -- which is arbitrary with respect to
what a suite costs, and the cost is extremely concentrated: the six slowest
suites are 52% of the whole budget. So which shard carried them was decided by
how the files happened to be spelled, and adding or renaming ONE file re-dealt
every suite in the repository.

What that cost, measured:

  * parity split on the recorded times: 264 s / 198 s, ratio 1.33;
  * in CI the same lottery reached 395 s against 81 s (run 32859901451);
  * shard 1/2 of run 33010348812 attempt 1 was killed at 601 s against the
    600 s cap, and two of the three timeout kills in the window are
    attributable to a bad draw.

Longest-processing-time first over committed timings gives 231 s / 231 s on
the same numbers.

What this file asserts
----------------------
The properties a split must have, which parity did not:

1. it is a PARTITION -- every suite runs exactly once across the shards;
2. it is balanced within a stated tolerance on the recorded costs;
3. it is deterministic, so runners agree without talking to each other;
4. a suite with no recorded time is charged the median, never zero, so a new
   suite cannot be quietly assumed free;
5. with no timings file at all it falls back to parity rather than failing;
6. it beats parity on the tree as it stands -- the regression itself.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_shard_split_is_balanced
"""
import glob
import io
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "ci"))

import run_suites  # noqa: E402

SUITES = sorted(os.path.basename(path)[:-3]
                for path in glob.glob(os.path.join(
                    REPO, "PaintomicsServer", "src", "tests", "test_*.py")))


def parity(names, index, count):
    return [name for position, name in enumerate(names)
            if position % count == index - 1]


def cost_of(shard, times, median):
    return sum(times.get(name, median) for name in shard)


class ShardSplitIsBalancedTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.times = run_suites.recorded_times()
        known = sorted(cls.times.values())
        cls.median = known[len(known) // 2] if known else 0.0

    def shards(self, count):
        return [run_suites.split(list(SUITES), i + 1, count)
                for i in range(count)]

    def test_the_timings_file_is_readable_and_covers_the_tree(self):
        self.assertTrue(self.times, "suite_times.txt could not be read")
        missing = [s for s in SUITES if s not in self.times]
        # Not required to be empty -- a new suite is charged the median -- but
        # a file that has drifted from the tree is worth seeing.
        self.assertLess(len(missing), max(10, len(SUITES) // 10),
                        "suite_times.txt has drifted: %d suites unrecorded, "
                        "refresh it (%s)" % (len(missing), missing[:5]))

    def test_every_suite_runs_exactly_once(self):
        """A split that drops a suite is a gate that stops testing it."""
        for count in (2, 3, 4):
            seen = [name for shard in self.shards(count) for name in shard]
            self.assertEqual(sorted(seen), SUITES,
                             "%d shards do not partition the tree" % count)
            self.assertEqual(len(seen), len(set(seen)), "a suite runs twice")

    def test_the_shards_are_balanced(self):
        for count in (2, 3):
            loads = [cost_of(s, self.times, self.median)
                     for s in self.shards(count)]
            ratio = max(loads) / max(min(loads), 0.001)
            self.assertLess(ratio, 1.15,
                            "%d shards are %.2fx apart: %s"
                            % (count, ratio, [round(x) for x in loads]))

    def test_it_beats_the_parity_split_it_replaces(self):
        """The regression: parity is 1.33x apart on this very tree."""
        theirs = [cost_of(parity(SUITES, i + 1, 2), self.times, self.median)
                  for i in range(2)]
        ours = [cost_of(s, self.times, self.median) for s in self.shards(2)]
        self.assertLess(max(ours), max(theirs),
                        "worst shard: %.0f s ours vs %.0f s parity"
                        % (max(ours), max(theirs)))

    def test_it_is_deterministic(self):
        """Each runner computes its own shard; they must agree without talking."""
        for _ in range(3):
            self.assertEqual(run_suites.split(list(SUITES), 1, 2),
                             run_suites.split(list(reversed(SUITES)), 1, 2),
                             "the split depends on the input order")

    def test_an_unrecorded_suite_is_charged_the_median_not_zero(self):
        """Or a batch of new suites all lands in one shard, being free."""
        invented = ["test_zzz_brand_new_%d" % n for n in range(8)]
        shards = [run_suites.split(SUITES + invented, i + 1, 2) for i in range(2)]
        landed = [len([n for n in s if n.startswith("test_zzz_")]) for s in shards]
        self.assertEqual(sum(landed), len(invented))
        self.assertTrue(all(n > 0 for n in landed),
                        "all %d unrecorded suites landed in one shard: %s"
                        % (len(invented), landed))

    def test_it_falls_back_to_parity_with_no_timings(self):
        """A missing or unreadable file must not take the gate down with it."""
        original = run_suites.SUITE_TIMES
        try:
            run_suites.SUITE_TIMES = os.path.join(REPO, "no", "such", "file.txt")
            self.assertEqual(run_suites.split(list(SUITES), 1, 2),
                             parity(SUITES, 1, 2))
            self.assertEqual(run_suites.split(list(SUITES), 2, 2),
                             parity(SUITES, 2, 2))
        finally:
            run_suites.SUITE_TIMES = original

    def test_the_parity_split_is_gone_from_the_shard_path(self):
        with io.open(os.path.join(REPO, "scripts", "ci", "run_suites.py"),
                     encoding="utf-8") as handle:
            source = handle.read()
        body = source[source.index("if args.shard:"):]
        self.assertNotIn("% count == index - 1", body,
                         "the shard path still splits by position")


if __name__ == "__main__":
    unittest.main(verbosity=2)
