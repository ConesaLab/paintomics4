#!/usr/bin/env python3
"""Full behavioural cover for src/common/ReplicateDetection.py.

The module arrived with the MORE-v2 merge and had no tests at all. It is pure
logic -- no MongoDB, no network, no R -- so every branch is reachable from a
plain unit test, which makes "untested" hard to justify.

The bug this file was written around
------------------------------------
``aggregate_replicates`` indexes ``values`` with the column indices in
``groups``::

    slice_vals = arr[cols] if n_reps else arr

``groups`` is built from the *header* -- ``detect_replicates(omicHeader[1:])``
in PathwayAcquisitionJob._detectReplicatesForOmic, or ``_parseDesignFile``,
which likewise walks ``replicateHeader``. But ``values`` is built per row, in
Job.py::

    numericValues = list(map(float, line[1:len(line)]))

Nothing pads that to the header width. So a row narrower than the header makes
``arr[cols]`` index past the end and the job dies with

    IndexError: index 2 is out of bounds for axis 0 with size 2

The input validator does check row width (PathwayAcquisitionJob step 2.3) but
it compares each row against the *first data row*, not against the header, so
a file whose header is wider than every data row passes validation and only
falls over later, during replicate aggregation.

Note the two guards that were already there, which is what makes the omission
look like an oversight rather than a decision: the fully-empty row is handled
(``if n_reps else arr``), and the *relevance* path clamps the very same
indices (``for c in cols if c < rel_arr.size``). Only the values path was
unguarded.

Deliberate behaviour locked down here, so a later "cleanup" cannot silently
change it:
  - a length-1 ``sampleRelevant`` is the feature-level signal the renderer
    keys on (OmicValue.isRelevant's ``relevant.length <= 1`` guard); it is
    NOT required to match ``len(sampleValues)``.
  - ``status="partial"`` refuses to aggregate rather than guessing.
  - a file that is already one column per sample yields ``status="none"``.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_replicate_detection
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.ReplicateDetection import (
    _broadcast_relevant,
    _none_result,
    _strip_replicate_suffix,
    aggregate_replicates,
    detect_replicates,
)


class StripReplicateSuffixTest(unittest.TestCase):
    """The regex is a deliberate whitelist -- a false positive silently merges
    two biologically distinct columns, which is worse than not detecting."""

    def test_accepts_the_documented_suffix_spellings(self):
        for header, expected in [
            ("Liver_R1",        ("Liver", 1)),
            ("Liver_r2",        ("Liver", 2)),
            ("Liver.rep3",      ("Liver", 3)),
            ("Liver-Rep4",      ("Liver", 4)),
            ("WT_replicate_1",  ("WT", 1)),
            ("WT_REPLICATE 2",  ("WT", 2)),
            ("Cond_1_R2",       ("Cond_1", 2)),
        ]:
            with self.subTest(header=header):
                self.assertEqual(_strip_replicate_suffix(header), expected)

    def test_rejects_names_that_merely_end_in_a_number(self):
        """Gene- and condition-style names must not be mistaken for replicates."""
        for header in ["Time_2", "TP53", "Mut_rad51", "Sample2", "cond1"]:
            with self.subTest(header=header):
                self.assertEqual(_strip_replicate_suffix(header), (None, None))

    def test_rejects_degenerate_and_non_string_input(self):
        for header in ["", "   ", "_R1", ".rep1", None, 42, [], b"S_R1"]:
            with self.subTest(header=header):
                self.assertEqual(_strip_replicate_suffix(header), (None, None))

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(_strip_replicate_suffix("  Liver_R1  "), ("Liver", 1))


class DetectReplicatesTest(unittest.TestCase):

    def test_all_columns_matched_gives_complete(self):
        result = detect_replicates(["S1_R1", "S1_R2", "S2_R1", "S2_R2"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["sampleHeader"], ["S1", "S2"])
        self.assertEqual(result["mapping"], [0, 0, 1, 1])
        self.assertEqual(result["groups"], [[0, 1], [2, 3]])
        self.assertEqual(result["unmatched"], [])

    def test_sample_order_follows_first_appearance_not_sorting(self):
        """Reordering a user's columns would silently relabel their data."""
        result = detect_replicates(["Zebra_R1", "Alpha_R1", "Zebra_R2", "Alpha_R2"])
        self.assertEqual(result["sampleHeader"], ["Zebra", "Alpha"])

    def test_mixed_columns_give_partial_and_do_not_aggregate(self):
        result = detect_replicates(["S1_R1", "S1_R2", "Control"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["unmatched"], [2])
        self.assertEqual(result["sampleHeader"], ["S1"])

    def test_one_column_per_sample_is_none_because_aggregating_is_a_no_op(self):
        result = detect_replicates(["S1_R1", "S2_R1"])
        self.assertEqual(result["status"], "none")

    def test_nothing_matching_is_none(self):
        result = detect_replicates(["Control", "Treated"])
        self.assertEqual(result["status"], "none")
        self.assertEqual(result["mapping"], [-1, -1])
        self.assertEqual(result["unmatched"], [0, 1])

    def test_degenerate_headers_are_none_not_crashes(self):
        for header in [None, [], ["only_one_column"]]:
            with self.subTest(header=header):
                self.assertEqual(detect_replicates(header)["status"], "none")

    def test_result_shape_is_always_complete(self):
        """Callers index every key unconditionally; a missing one is an
        AttributeError deep inside the Step 2 response builder."""
        for header in [None, [], ["a"], ["S_R1", "S_R2"], ["S_R1", "x"]]:
            with self.subTest(header=header):
                result = detect_replicates(header)
                self.assertEqual(
                    set(result),
                    {"status", "sampleHeader", "mapping", "groups", "unmatched"})

    def test_mapping_is_parallel_to_the_input_header(self):
        header = ["S1_R1", "junk", "S1_R2"]
        self.assertEqual(len(detect_replicates(header)["mapping"]), len(header))

    def test_uneven_replicate_counts_still_complete(self):
        result = detect_replicates(["S1_R1", "S1_R2", "S1_R3", "S2_R1"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["groups"], [[0, 1, 2], [3]])


class NoneResultTest(unittest.TestCase):

    def test_marks_every_column_unmatched(self):
        result = _none_result(["a", "b", "c"])
        self.assertEqual(result["status"], "none")
        self.assertEqual(result["mapping"], [-1, -1, -1])
        self.assertEqual(result["unmatched"], [0, 1, 2])
        self.assertEqual(result["groups"], [])

    def test_empty_input(self):
        self.assertEqual(_none_result([])["unmatched"], [])


class AggregateReplicatesTest(unittest.TestCase):

    def assertNaN(self, value):
        self.assertTrue(math.isnan(value), "expected NaN, got %r" % (value,))

    def test_means_are_taken_per_sample(self):
        values, relevant = aggregate_replicates(
            values=[1.0, 3.0, 10.0, 20.0], relevant=[False, False, False, False],
            groups=[[0, 1], [2, 3]], n_samples=2)
        self.assertEqual(values, [2.0, 15.0])
        self.assertEqual(relevant, [False, False])

    def test_nan_replicates_are_ignored_by_the_mean(self):
        values, _ = aggregate_replicates(
            values=[1.0, float("nan"), 3.0], relevant=[False, False, False],
            groups=[[0, 1], [2]], n_samples=2)
        self.assertEqual(values, [1.0, 3.0])

    def test_all_nan_group_stays_nan_rather_than_becoming_zero(self):
        """A silent 0.0 would be plotted as a real measurement."""
        values, _ = aggregate_replicates(
            values=[float("nan"), float("nan")], relevant=[False, False],
            groups=[[0, 1]], n_samples=1)
        self.assertNaN(values[0])

    def test_empty_group_is_nan(self):
        values, _ = aggregate_replicates(
            values=[1.0], relevant=[True], groups=[[0], []], n_samples=2)
        self.assertEqual(values[0], 1.0)
        self.assertNaN(values[1])

    def test_relevance_or_collapses_across_replicates(self):
        _, relevant = aggregate_replicates(
            values=[1.0, 2.0, 3.0, 4.0], relevant=[True, False, False, False],
            groups=[[0, 1], [2, 3]], n_samples=2)
        self.assertEqual(relevant, [True, False])

    def test_n_samples_must_match_groups(self):
        with self.assertRaises(ValueError):
            aggregate_replicates(values=[1.0], relevant=[True],
                                 groups=[[0]], n_samples=2)

    def test_string_values_are_coerced(self):
        """Values arrive from a parsed text file in some code paths."""
        values, _ = aggregate_replicates(
            values=["1.0", "3.0"], relevant=[True, True],
            groups=[[0, 1]], n_samples=1)
        self.assertEqual(values, [2.0])

    # -- the regression this file exists for --------------------------------

    def test_row_narrower_than_the_header_does_not_raise(self):
        """A row with fewer values than the header has columns.

        groups comes from the header; values comes from the row. Job.py pads
        neither, so this combination reaches aggregate_replicates intact and
        used to raise IndexError, killing the whole Step 2 request.
        """
        values, relevant = aggregate_replicates(
            values=[1.0, 3.0], relevant=[True, False, True, False],
            groups=[[0, 1], [2, 3]], n_samples=2)
        self.assertEqual(values[0], 2.0)
        self.assertNaN(values[1])          # no data for sample 2 -> NaN, not 0
        self.assertEqual(relevant, [True, False])

    def test_partially_out_of_range_group_uses_the_values_it_has(self):
        """Only some of a sample's replicate columns are missing from the row."""
        values, _ = aggregate_replicates(
            values=[2.0, 4.0, 6.0], relevant=[False] * 4,
            groups=[[0, 1], [2, 3]], n_samples=2)
        self.assertEqual(values, [3.0, 6.0])

    def test_empty_row_is_all_nan(self):
        values, relevant = aggregate_replicates(
            values=[], relevant=[], groups=[[0, 1], [2, 3]], n_samples=2)
        self.assertNaN(values[0])
        self.assertNaN(values[1])
        self.assertEqual(relevant, [False])

    # -- feature-level relevance contract -----------------------------------

    def test_scalar_relevant_yields_the_length_one_feature_level_signal(self):
        """Length 1 is meaningful: the renderer draws a row-label star instead
        of per-cell stars. It deliberately does not match len(sampleValues)."""
        values, relevant = aggregate_replicates(
            values=[1.0, 2.0, 3.0, 4.0], relevant=True,
            groups=[[0, 1], [2, 3]], n_samples=2)
        self.assertEqual(len(values), 2)
        self.assertEqual(relevant, [True])

    def test_none_relevant_is_not_relevant(self):
        _, relevant = aggregate_replicates(
            values=[1.0, 2.0], relevant=None, groups=[[0, 1]], n_samples=1)
        self.assertEqual(relevant, [False])

    def test_empty_relevant_list_is_not_relevant(self):
        _, relevant = aggregate_replicates(
            values=[1.0, 2.0], relevant=[], groups=[[0, 1]], n_samples=1)
        self.assertEqual(relevant, [False])

    def test_per_replicate_relevance_is_per_sample(self):
        _, relevant = aggregate_replicates(
            values=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            relevant=[True, False, False, False, False, True],
            groups=[[0, 1], [2, 3], [4, 5]], n_samples=3)
        self.assertEqual(relevant, [True, False, True])


class BroadcastRelevantTest(unittest.TestCase):

    def test_none_is_all_false(self):
        self.assertEqual(list(_broadcast_relevant(None, 3)), [False, False, False])

    def test_bool_broadcasts(self):
        self.assertEqual(list(_broadcast_relevant(True, 2)), [True, True])
        self.assertEqual(list(_broadcast_relevant(False, 2)), [False, False])

    def test_the_string_forms_mongo_round_trips(self):
        self.assertEqual(list(_broadcast_relevant("True", 2)), [True, True])
        self.assertEqual(list(_broadcast_relevant("False", 2)), [False, False])

    def test_exact_length_list_passes_through(self):
        self.assertEqual(list(_broadcast_relevant([True, False], 2)), [True, False])

    def test_short_list_is_padded_with_false(self):
        self.assertEqual(list(_broadcast_relevant([True], 3)), [True, False, False])

    def test_long_list_is_truncated(self):
        self.assertEqual(list(_broadcast_relevant([True, True, True], 2)), [True, True])

    def test_result_is_always_the_requested_length(self):
        for relevant in [None, True, "True", [], [True], [True] * 9]:
            with self.subTest(relevant=relevant):
                self.assertEqual(len(_broadcast_relevant(relevant, 4)), 4)


class EndToEndTest(unittest.TestCase):
    """detect_replicates -> aggregate_replicates, the way Step 2 chains them."""

    def test_a_typical_two_sample_triplicate_file(self):
        header = ["WT_R1", "WT_R2", "WT_R3", "KO_R1", "KO_R2", "KO_R3"]
        detected = detect_replicates(header)
        self.assertEqual(detected["status"], "complete")

        values, relevant = aggregate_replicates(
            values=[1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
            relevant=[False, False, False, True, False, False],
            groups=detected["groups"],
            n_samples=len(detected["sampleHeader"]))

        self.assertEqual(detected["sampleHeader"], ["WT", "KO"])
        self.assertEqual(values, [2.0, 20.0])
        self.assertEqual(relevant, [False, True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
