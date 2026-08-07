#!/usr/bin/env python3
"""Cover for _parseDesignFile in src/servlets/PathwayAcquisitionServlet.py.

The MORE-v2 merge added a manual route for replicate grouping: when automatic
detection returns "partial" (some columns look like replicates, some do not)
the user uploads a two-column design file mapping each values-file column to a
biological sample. This parses it.

It is worth pinning because it is the one place a user hand-writes structure
that the aggregation code then trusts. Its output -- (sampleHeader, mapping,
groups) -- feeds aggregate_replicates, which indexes `values` with the column
indices in `groups`. A wrong index there is a wrong mean silently attributed
to the wrong sample, not a crash.

Separator handling is inherited convention: tab is canonical, comma is the
fallback when the body contains no tab at all, matching how the rest of
PaintOmics auto-detects delimiters.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_design_file_parsing
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets.PathwayAcquisitionServlet import _parseDesignFile

HEADER = ["S1_R1", "S1_R2", "S2_R1", "S2_R2"]


def body(*rows, **kwargs):
    sep = kwargs.get("sep", "\t")
    return "\n".join(sep.join(r) for r in rows)


class HappyPathTest(unittest.TestCase):

    def test_groups_columns_into_samples(self):
        sampleHeader, mapping, groups = _parseDesignFile(
            body(("S1_R1", "WT"), ("S1_R2", "WT"),
                 ("S2_R1", "KO"), ("S2_R2", "KO")), HEADER)
        self.assertEqual(sampleHeader, ["WT", "KO"])
        self.assertEqual(mapping, [0, 0, 1, 1])
        self.assertEqual(groups, [[0, 1], [2, 3]])

    def test_sample_order_follows_the_file_not_the_values_header(self):
        """Row order is how the user controls display order."""
        sampleHeader, mapping, _ = _parseDesignFile(
            body(("S2_R1", "KO"), ("S2_R2", "KO"),
                 ("S1_R1", "WT"), ("S1_R2", "WT")), HEADER)
        self.assertEqual(sampleHeader, ["KO", "WT"])
        # mapping stays parallel to the values header, not the design file.
        self.assertEqual(mapping, [1, 1, 0, 0])

    def test_comma_separated_file(self):
        sampleHeader, _, groups = _parseDesignFile(
            body(("S1_R1", "WT"), ("S1_R2", "WT"),
                 ("S2_R1", "KO"), ("S2_R2", "KO"), sep=","), HEADER)
        self.assertEqual(sampleHeader, ["WT", "KO"])
        self.assertEqual(groups, [[0, 1], [2, 3]])

    def test_a_leading_header_row_is_skipped(self):
        sampleHeader, _, _ = _parseDesignFile(
            body(("Column", "Sample"), ("S1_R1", "WT"), ("S1_R2", "WT"),
                 ("S2_R1", "KO"), ("S2_R2", "KO")), HEADER)
        self.assertEqual(sampleHeader, ["WT", "KO"])

    def test_blank_and_comment_lines_are_ignored(self):
        text = ("# my design\n"
                "S1_R1\tWT\n"
                "\n"
                "S1_R2\tWT\n"
                "S2_R1\tKO\n"
                "S2_R2\tKO\n")
        sampleHeader, _, _ = _parseDesignFile(text, HEADER)
        self.assertEqual(sampleHeader, ["WT", "KO"])

    def test_surrounding_whitespace_is_stripped(self):
        text = "  S1_R1 \t WT \n S1_R2\tWT\nS2_R1\tKO\nS2_R2\tKO\n"
        sampleHeader, mapping, _ = _parseDesignFile(text, HEADER)
        self.assertEqual(sampleHeader, ["WT", "KO"])
        self.assertEqual(mapping, [0, 0, 1, 1])

    def test_all_columns_in_one_sample(self):
        sampleHeader, mapping, groups = _parseDesignFile(
            body(("S1_R1", "All"), ("S1_R2", "All"),
                 ("S2_R1", "All"), ("S2_R2", "All")), HEADER)
        self.assertEqual(sampleHeader, ["All"])
        self.assertEqual(mapping, [0, 0, 0, 0])
        self.assertEqual(groups, [[0, 1, 2, 3]])

    def test_one_column_per_sample(self):
        sampleHeader, _, groups = _parseDesignFile(
            body(("S1_R1", "A"), ("S1_R2", "B"),
                 ("S2_R1", "C"), ("S2_R2", "D")), HEADER)
        self.assertEqual(sampleHeader, ["A", "B", "C", "D"])
        self.assertEqual(groups, [[0], [1], [2], [3]])


class StructuralInvariantTest(unittest.TestCase):
    """aggregate_replicates indexes `values` with these; a bad index is a wrong
    mean attributed to the wrong sample, not a crash."""

    def test_mapping_is_parallel_to_the_values_header(self):
        _, mapping, _ = _parseDesignFile(
            body(("S1_R1", "WT"), ("S1_R2", "WT"),
                 ("S2_R1", "KO"), ("S2_R2", "KO")), HEADER)
        self.assertEqual(len(mapping), len(HEADER))

    def test_groups_partition_every_column_exactly_once(self):
        _, _, groups = _parseDesignFile(
            body(("S1_R1", "WT"), ("S1_R2", "KO"),
                 ("S2_R1", "WT"), ("S2_R2", "KO")), HEADER)
        flat = sorted(i for g in groups for i in g)
        self.assertEqual(flat, list(range(len(HEADER))))

    def test_groups_and_sampleHeader_are_the_same_length(self):
        sampleHeader, _, groups = _parseDesignFile(
            body(("S1_R1", "WT"), ("S1_R2", "KO"),
                 ("S2_R1", "WT"), ("S2_R2", "KO")), HEADER)
        self.assertEqual(len(groups), len(sampleHeader))

    def test_every_mapping_entry_indexes_a_real_sample(self):
        sampleHeader, mapping, _ = _parseDesignFile(
            body(("S1_R1", "WT"), ("S1_R2", "KO"),
                 ("S2_R1", "WT"), ("S2_R2", "KO")), HEADER)
        for idx in mapping:
            self.assertTrue(0 <= idx < len(sampleHeader))


class RejectionTest(unittest.TestCase):
    """Hard errors: silently guessing would mis-attribute a user's data."""

    def test_empty_body(self):
        with self.assertRaises(Exception):
            _parseDesignFile("", HEADER)

    def test_a_column_with_no_row_is_rejected(self):
        """Aggregating with a column unassigned would drop it silently."""
        with self.assertRaises(Exception) as ctx:
            _parseDesignFile(body(("S1_R1", "WT"), ("S1_R2", "WT"),
                                  ("S2_R1", "KO")), HEADER)
        self.assertIn("S2_R2", str(ctx.exception))

    def test_an_empty_sample_label_is_rejected(self):
        with self.assertRaises(Exception):
            _parseDesignFile("S1_R1\tWT\nS1_R2\t\nS2_R1\tKO\nS2_R2\tKO", HEADER)

    def test_the_error_names_the_missing_columns(self):
        with self.assertRaises(Exception) as ctx:
            _parseDesignFile(body(("S1_R1", "WT")), HEADER)
        message = str(ctx.exception)
        self.assertTrue(any(c in message for c in ("S1_R2", "S2_R1", "S2_R2")),
                        "error should name what to fix: %s" % message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
