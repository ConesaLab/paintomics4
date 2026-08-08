#!/usr/bin/env python
"""Tests for src/common/JobProgress.py — the in-process job progress ledger.

Run:
    cd PaintomicsServer
    PYTHONPATH=$PWD python src/tests/test_job_progress.py

The properties worth protecting are the ones the previous progress bar got
wrong on a measured run: it went backwards, it reported nothing for the first
18 seconds, it read 62% when the job was 98.7% done, and it claimed 49s left
with 1s to go.
"""
import os
import sys
import unittest
from multiprocessing import RawArray

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.common import JobProgress


# Weights deliberately uneven, mirroring the measured step-2 split
# (pathways 4.6%, classification 40.2%, metagenes 49.9%, store 3.7%).
PLAN = [
    ("pathways", "Building pathway list", 4.6),
    ("classify", "Classifying compounds", 40.2),
    ("metagenes", "Computing metagenes", 49.9),
    ("store", "Saving results", 3.7),
]

# The ledger normalises weights, so a plan may be expressed in measured seconds,
# relative sizes or percentages. These four sum to 98.4 rather than 100 — which
# is exactly why the expected values below are computed rather than written out.
_TOTAL_WEIGHT = float(sum(w for _n, _l, w in PLAN))


def weightOf(phaseName):
    return next(w for n, _l, w in PLAN if n == phaseName) / _TOTAL_WEIGHT


def startOf(phaseName):
    """Fraction at the moment `phaseName` is entered."""
    acc = 0.0
    for n, _l, w in PLAN:
        if n == phaseName:
            return acc
        acc += w / _TOTAL_WEIGHT
    raise KeyError(phaseName)


class JobProgressTest(unittest.TestCase):

    def setUp(self):
        JobProgress.finish("job1")

    def tearDown(self):
        JobProgress.finish("job1")

    # -- basic contract ----------------------------------------------------

    def test_untracked_job_returns_none_not_an_error(self):
        """Jobs from other servlets have no record; that is not a failure."""
        self.assertIsNone(JobProgress.snapshot("never-started"))

    def test_no_snapshot_before_first_phase(self):
        JobProgress.begin("job1", "step2", PLAN)
        self.assertIsNone(JobProgress.snapshot("job1"))

    def test_reports_from_the_very_first_phase(self):
        """The old bar showed nothing for the first 18s of an 83s job."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "pathways")
        snap = JobProgress.snapshot("job1")
        self.assertIsNotNone(snap)
        self.assertEqual(snap["phaseIndex"], 1)
        self.assertEqual(snap["phaseCount"], 4)
        self.assertEqual(snap["label"], "Building pathway list")

    # -- monotonicity ------------------------------------------------------

    def test_fraction_never_decreases_across_phases(self):
        JobProgress.begin("job1", "step2", PLAN)
        seen = []
        for name, _label, _w in PLAN:
            JobProgress.enter("job1", name)
            seen.append(JobProgress.snapshot("job1")["fraction"])
        self.assertEqual(seen, sorted(seen), "fraction went backwards: %s" % seen)

    def test_out_of_order_phase_does_not_rewind(self):
        """A repeated or stale enter() must not make the bar retreat."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "metagenes")
        ahead = JobProgress.snapshot("job1")["fraction"]
        JobProgress.enter("job1", "pathways")          # stale, arrives late
        self.assertEqual(JobProgress.snapshot("job1")["fraction"], ahead)

    def test_units_never_decrease(self):
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "metagenes", total=10)
        JobProgress.units("job1", 7)
        JobProgress.units("job1", 3)
        self.assertEqual(JobProgress.snapshot("job1")["unitsDone"], 7)

    # -- the fraction actually means something -----------------------------

    def test_phase_weights_place_the_fraction(self):
        """Entering metagenes means pathways+classify are behind us."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "metagenes")
        self.assertAlmostEqual(JobProgress.snapshot("job1")["fraction"],
                               startOf("metagenes"), places=4)

    def test_units_move_the_fraction_within_the_phase(self):
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "metagenes", total=10)
        JobProgress.units("job1", 5)
        snap = JobProgress.snapshot("job1")
        # halfway through the metagenes phase
        self.assertAlmostEqual(snap["fraction"],
                               startOf("metagenes") + weightOf("metagenes") / 2,
                               places=4)
        self.assertTrue(snap["exact"], "a real unit count should be reported as exact")

    def test_fraction_never_reaches_one_while_running(self):
        """A bar pinned at 100% that keeps not finishing reads as a hang."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "store", total=5)
        JobProgress.units("job1", 5)
        self.assertLess(JobProgress.snapshot("job1")["fraction"], 1.0)

    def test_interpolation_cannot_reach_the_next_phase_boundary(self):
        """With nothing to count, the bar must not arrive before the work does."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "pathways")          # no total, no anchors
        snap = JobProgress.snapshot("job1")
        self.assertFalse(snap["exact"])
        self.assertLess(snap["fraction"], startOf("classify"))

    # -- shared counters written by forked children ------------------------

    def test_anchors_from_children_produce_an_exact_fraction(self):
        JobProgress.begin("job1", "step1", PLAN)
        JobProgress.enter("job1", "classify")
        anchors = RawArray("i", 6)                      # 6 children
        JobProgress.attachAnchors("job1", anchors, perWorker=12)
        for slot in range(6):
            anchors[slot] = 6                           # each halfway
        snap = JobProgress.snapshot("job1")
        self.assertTrue(snap["exact"])
        self.assertAlmostEqual(snap["fraction"],
                               startOf("classify") + weightOf("classify") / 2,
                               places=4)

    def test_units_take_precedence_over_anchors(self):
        JobProgress.begin("job1", "step1", PLAN)
        JobProgress.enter("job1", "classify", total=100)
        anchors = RawArray("i", 6)
        JobProgress.attachAnchors("job1", anchors, perWorker=12)
        JobProgress.units("job1", 100)
        self.assertAlmostEqual(JobProgress.snapshot("job1")["fraction"],
                               startOf("metagenes"), places=4)

    # -- regressions found by running a real job ---------------------------

    def test_a_new_unit_discards_the_previous_units_anchors(self):
        """Measured: the bar ran to 54% and rewound to 37% between omics.

        Anchors describe one in-flight unit. When the next unit starts they are
        still sitting at 100%, so counting them credits the new unit as already
        done — until the workers re-attach and it visibly rewinds.
        """
        JobProgress.begin("job1", "step1", PLAN)
        JobProgress.enter("job1", "classify", total=100)
        anchors = RawArray("i", 4)
        JobProgress.attachAnchors("job1", anchors, perWorker=100)
        for slot in range(4):
            anchors[slot] = 100                      # previous unit finished
        JobProgress.units("job1", 10, span=10)
        peak = JobProgress.snapshot("job1")["fraction"]

        # Workers for the NEW unit attach a fresh array starting at zero.
        fresh = RawArray("i", 4)
        JobProgress.attachAnchors("job1", fresh, perWorker=100)
        self.assertGreaterEqual(JobProgress.snapshot("job1")["fraction"], peak,
                                "fraction rewound when the next unit started")

    def test_an_uncountable_phase_still_advances(self):
        """Measured: step 2 sat at 0% for 15s, then 7.9% for the rest of 31.6s."""
        JobProgress.begin("job1", "step2", PLAN, expectedTotal=100.0)
        JobProgress.enter("job1", "pathways")
        rec = JobProgress._records["job1"]
        atEntry = JobProgress.snapshot("job1")["fraction"]
        rec.phaseStarted -= 2.0                      # 2s into the phase
        later = JobProgress.snapshot("job1")
        self.assertGreater(later["fraction"], atEntry)
        self.assertFalse(later["exact"], "a clock-based guess must not claim exactness")

    def test_a_fast_phase_does_not_collapse_the_estimate(self):
        """A boundary crossed in milliseconds must not saturate the next phase."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "pathways")
        JobProgress.enter("job1", "classify")        # instantly
        JobProgress.enter("job1", "metagenes")       # instantly
        self.assertAlmostEqual(JobProgress.snapshot("job1")["fraction"],
                               startOf("metagenes"), places=4)

    def test_expected_total_is_recalibrated_from_the_job_itself(self):
        JobProgress.begin("job1", "step2", PLAN, expectedTotal=1000.0)
        JobProgress.enter("job1", "pathways")
        JobProgress.enter("job1", "classify")
        rec = JobProgress._records["job1"]
        rec.started -= 30.0                          # 30s to get through classify
        JobProgress.enter("job1", "metagenes")
        # 30s bought 45.5% of the work, so the total is nearer 66s than 1000s.
        # Blended half-and-half with the prior, so it lands between the two.
        self.assertLess(rec.expectedTotal, 1000.0)
        self.assertGreater(rec.expectedTotal, 30.0)

    def test_a_tiny_first_phase_is_not_extrapolated_from(self):
        """4.6% of the work is too small a sample to predict the other 95%."""
        JobProgress.begin("job1", "step2", PLAN, expectedTotal=1000.0)
        JobProgress.enter("job1", "pathways")
        rec = JobProgress._records["job1"]
        rec.started -= 10.0
        JobProgress.enter("job1", "classify")
        self.assertEqual(rec.expectedTotal, 1000.0)

    # -- the ETA is a band, and honest about it ----------------------------

    def test_eta_is_a_band_not_a_point(self):
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "metagenes", total=10)
        JobProgress.units("job1", 5)
        JobProgress._records["job1"].started -= 60      # pretend 60s elapsed
        snap = JobProgress.snapshot("job1")
        self.assertIn("remainingLow", snap)
        self.assertLess(snap["remainingLow"], snap["remainingHigh"])

    def test_no_eta_before_there_is_anything_to_extrapolate_from(self):
        """Dividing by a fraction pinned near zero produced 15x overestimates."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "pathways")
        self.assertNotIn("remainingLow", JobProgress.snapshot("job1"))

    # -- lifecycle ---------------------------------------------------------

    def test_finish_removes_the_record(self):
        """One long-lived process: a leaked entry is permanent."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "pathways")
        JobProgress.finish("job1")
        self.assertIsNone(JobProgress.snapshot("job1"))
        self.assertNotIn("job1", JobProgress._records)

    def test_begin_restarts_for_the_next_step_of_the_same_job(self):
        """step 1, step 2 and metagenes all enqueue under the same jobID."""
        JobProgress.begin("job1", "step1", PLAN)
        JobProgress.enter("job1", "metagenes")
        JobProgress.begin("job1", "step2", PLAN)
        self.assertIsNone(JobProgress.snapshot("job1"))
        JobProgress.enter("job1", "pathways")
        self.assertEqual(JobProgress.snapshot("job1")["phaseIndex"], 1)

    def test_unknown_phase_is_ignored_not_raised(self):
        """Progress reporting must never be able to fail a job."""
        JobProgress.begin("job1", "step2", PLAN)
        JobProgress.enter("job1", "pathways")
        before = JobProgress.snapshot("job1")["fraction"]
        JobProgress.enter("job1", "a-phase-someone-added-later")
        self.assertEqual(JobProgress.snapshot("job1")["fraction"], before)

    def test_calls_on_a_finished_job_are_harmless(self):
        JobProgress.finish("job1")
        JobProgress.enter("job1", "pathways")
        JobProgress.units("job1", 5)
        JobProgress.attachAnchors("job1", RawArray("i", 2), 4)
        self.assertIsNone(JobProgress.snapshot("job1"))

    def test_zero_weight_phase_does_not_divide_by_zero(self):
        JobProgress.begin("job1", "step2", [("a", "A", 0.0), ("b", "B", 0.0)])
        JobProgress.enter("job1", "a")
        self.assertIsNotNone(JobProgress.snapshot("job1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
