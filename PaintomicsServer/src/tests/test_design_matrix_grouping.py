#!/usr/bin/env python3
"""Cover for src/common/DesignFile.py -- the indicator-matrix reader and the
coarser groupings derived from a design's condition names.

Why this is separate from test_design_file_parsing
--------------------------------------------------
That file pins the *servlet* entry point, `_parseDesignFile`, which is now a
one-line delegation. Keeping it pointed at the servlet is deliberate: it pins
that the public route stays behaviour-compatible, which is exactly what breaks
when someone later tidies a delegation away. This file covers the module the
delegation reaches, including the shape the servlet route never sees.

What the module is for
----------------------
MORE requires its experimental design as an INDICATOR MATRIX -- one column per
condition, a 1 in the column each sample belongs to:

    Sample            Ctr_0H  Ctr_2H  ...  Ik_24H
    Batch_1_Ctr_0H    1       0       ...  0

The long-form reader takes two columns, `column<TAB>label`. Feeding it a matrix
is not an error, and that is the danger: column 1 of a matrix row is an
indicator, so every sample collapses into two groups named "1" and "0" and the
job proceeds with a confidently wrong grouping. Shape detection is therefore
the load-bearing part, and it is what most of these tests exercise.

The regression that motivated the module: the bundled `11-stategra-more`
example ships 36 columns named `Batch_N_<condition>`, whose replicate tag is a
PREFIX. `detect_replicates` only recognises a trailing `_R1`/`_rep2`, so it
returned status="none" and every heatmap drew 36 columns with unreadable
labels -- while the grouping sat, stated exactly, in the design file the job
already had.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_design_matrix_grouping
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.DesignFile import parse_design, derive_groupings, looks_like_indicator_matrix


def matrix(conditions, rows):
    """A tab-separated indicator matrix: header row, then (sample, marks)."""
    lines = ["\t".join(["Sample"] + list(conditions))]
    for sample, marks in rows:
        lines.append("\t".join([sample] + [str(m) for m in marks]))
    return "\n".join(lines)


# Two conditions, two samples each -- the smallest matrix that groups anything.
SMALL_HEADER = ["a_r1", "a_r2", "b_r1", "b_r2"]
SMALL_BODY = matrix(
    ["CondA", "CondB"],
    [("a_r1", [1, 0]), ("a_r2", [1, 0]),
     ("b_r1", [0, 1]), ("b_r2", [0, 1])])


class ShapeDetectionTest(unittest.TestCase):
    """Which reading a file gets is decided before any of it is trusted."""

    def test_a_wide_zero_one_file_is_a_matrix(self):
        rows = [line.split("\t") for line in SMALL_BODY.splitlines()]
        self.assertTrue(looks_like_indicator_matrix(rows))

    def test_a_two_column_file_is_never_a_matrix(self):
        # Even when its labels are literally "1" and "0": with one condition
        # column the two readings are indistinguishable, and the long-form one
        # is the harmless mistake.
        rows = [["a_r1", "1"], ["a_r2", "0"]]
        self.assertFalse(looks_like_indicator_matrix(rows))

    def test_a_wide_file_with_a_real_value_is_not_a_matrix(self):
        rows = [["Sample", "CondA", "CondB"],
                ["a_r1", "1", "0"],
                ["a_r2", "0.73", "0"]]      # a measurement, not an indicator
        self.assertFalse(looks_like_indicator_matrix(rows))

    def test_ragged_rows_are_not_a_matrix(self):
        rows = [["Sample", "CondA", "CondB"],
                ["a_r1", "1", "0"],
                ["a_r2", "1"]]
        self.assertFalse(looks_like_indicator_matrix(rows))

    def test_a_header_alone_is_not_a_matrix(self):
        self.assertFalse(looks_like_indicator_matrix([["Sample", "CondA", "CondB"]]))


class MatrixReadingTest(unittest.TestCase):

    def test_collapses_columns_into_the_marked_conditions(self):
        sampleHeader, mapping, groups = parse_design(SMALL_BODY, SMALL_HEADER)
        self.assertEqual(sampleHeader, ["CondA", "CondB"])
        self.assertEqual(mapping, [0, 0, 1, 1])
        self.assertEqual(groups, [[0, 1], [2, 3]])

    def test_condition_order_follows_the_header_row(self):
        body = matrix(["Late", "Early"],
                      [("a_r1", [1, 0]), ("a_r2", [1, 0]),
                       ("b_r1", [0, 1]), ("b_r2", [0, 1])])
        sampleHeader, _mapping, _groups = parse_design(body, SMALL_HEADER)
        self.assertEqual(sampleHeader, ["Late", "Early"])

    def test_accepts_spreadsheet_round_tripped_cells(self):
        body = matrix(["CondA", "CondB"],
                      [("a_r1", ["1.0", "0.0"]), ("a_r2", ["1.0", "0.0"]),
                       ("b_r1", ["0.0", "1.0"]), ("b_r2", ["0.0", "1.0"])])
        sampleHeader, mapping, _groups = parse_design(body, SMALL_HEADER)
        self.assertEqual(sampleHeader, ["CondA", "CondB"])
        self.assertEqual(mapping, [0, 0, 1, 1])

    def test_extra_samples_in_the_design_are_ignored(self):
        # A design may describe a larger experiment than this omic was measured
        # on; only the omic's own columns have to be covered.
        body = matrix(["CondA", "CondB"],
                      [("a_r1", [1, 0]), ("a_r2", [1, 0]),
                       ("b_r1", [0, 1]), ("b_r2", [0, 1]),
                       ("c_r1", [1, 0])])
        sampleHeader, mapping, _groups = parse_design(body, SMALL_HEADER)
        self.assertEqual(sampleHeader, ["CondA", "CondB"])
        self.assertEqual(len(mapping), len(SMALL_HEADER))


class MatrixRejectionTest(unittest.TestCase):
    """A sample that cannot be placed is an error, never a guess.

    Averaging a column into the wrong condition is silent and permanent: it
    produces a plausible number attributed to the wrong biology.
    """

    def test_a_sample_marking_no_condition_is_rejected(self):
        body = matrix(["CondA", "CondB"],
                      [("a_r1", [1, 0]), ("a_r2", [0, 0]),
                       ("b_r1", [0, 1]), ("b_r2", [0, 1])])
        with self.assertRaises(Exception) as caught:
            parse_design(body, SMALL_HEADER)
        self.assertIn("a_r2", str(caught.exception))

    def test_a_sample_marking_two_conditions_is_rejected(self):
        body = matrix(["CondA", "CondB"],
                      [("a_r1", [1, 1]), ("a_r2", [1, 0]),
                       ("b_r1", [0, 1]), ("b_r2", [0, 1])])
        with self.assertRaises(Exception) as caught:
            parse_design(body, SMALL_HEADER)
        self.assertIn("a_r1", str(caught.exception))

    def test_a_column_absent_from_the_design_is_rejected(self):
        with self.assertRaises(Exception) as caught:
            parse_design(SMALL_BODY, SMALL_HEADER + ["c_r1"])
        self.assertIn("c_r1", str(caught.exception))


class LongFormStillWorksTest(unittest.TestCase):
    """The shape the servlet route has always taken must be untouched."""

    def test_two_column_long_form(self):
        body = "\n".join(["a_r1\tWT", "a_r2\tWT", "b_r1\tKO", "b_r2\tKO"])
        sampleHeader, mapping, groups = parse_design(body, SMALL_HEADER)
        self.assertEqual(sampleHeader, ["WT", "KO"])
        self.assertEqual(mapping, [0, 0, 1, 1])
        self.assertEqual(groups, [[0, 1], [2, 3]])


class DeriveGroupingsTest(unittest.TestCase):
    """Coarser axes, offered only when the names actually carry one."""

    def setUp(self):
        self.conditions = ["Ctr_0H", "Ctr_2H", "Ctr_6H", "Ik_0H", "Ik_2H", "Ik_6H"]
        self.replicates = []
        self.mapping = []
        for idx, condition in enumerate(self.conditions):
            for rep in (1, 2):
                self.replicates.append("Batch_%d_%s" % (rep, condition))
                self.mapping.append(idx)

    def groupings(self):
        return derive_groupings(self.replicates, self.conditions, self.mapping)

    def test_offers_identity_design_and_each_factor(self):
        ids = [g["id"] for g in self.groupings()]
        self.assertEqual(ids, ["columns", "design", "factor0", "factor1"])

    def test_the_factors_are_the_crossed_axes(self):
        byId = dict((g["id"], g) for g in self.groupings())
        self.assertEqual(byId["factor0"]["sampleHeader"], ["Ctr", "Ik"])
        self.assertEqual(byId["factor1"]["sampleHeader"], ["0H", "2H", "6H"])

    def test_a_factor_maps_every_replicate_column(self):
        byId = dict((g["id"], g) for g in self.groupings())
        treatment = byId["factor0"]
        self.assertEqual(len(treatment["mapping"]), len(self.replicates))
        # Six Ctr replicates, six Ik replicates.
        self.assertEqual([len(g) for g in treatment["groups"]], [6, 6])

    def test_timepoint_order_follows_first_appearance_not_sorting(self):
        # "12H" must not sort before "2H"; the design's own order is the answer.
        self.conditions = ["Ctr_0H", "Ctr_2H", "Ctr_12H", "Ik_0H", "Ik_2H", "Ik_12H"]
        self.mapping = [i // 2 for i in range(12)]
        self.replicates = ["c%d" % i for i in range(12)]
        byId = dict((g["id"], g) for g in self.groupings())
        self.assertEqual(byId["factor1"]["sampleHeader"], ["0H", "2H", "12H"])

    def test_names_without_structure_offer_no_factors(self):
        self.conditions = ["WT", "KO"]
        self.mapping = [0, 0, 1, 1]
        self.replicates = SMALL_HEADER
        self.assertEqual([g["id"] for g in self.groupings()], ["columns", "design"])

    def test_ragged_names_offer_no_factors(self):
        self.conditions = ["Ctr_0H", "Ik"]
        self.mapping = [0, 0, 1, 1]
        self.replicates = SMALL_HEADER
        self.assertEqual([g["id"] for g in self.groupings()], ["columns", "design"])

    def test_a_constant_token_is_not_a_factor(self):
        # Position 0 is "Exp" everywhere: grouping by it groups nothing.
        self.conditions = ["Exp_A", "Exp_B"]
        self.mapping = [0, 0, 1, 1]
        self.replicates = SMALL_HEADER
        ids = [g["id"] for g in self.groupings()]
        self.assertNotIn("factor0", ids)

    def test_every_grouping_partitions_the_columns_exactly_once(self):
        for grouping in self.groupings():
            seen = sorted(idx for group in grouping["groups"] for idx in group)
            self.assertEqual(seen, list(range(len(self.replicates))),
                             "grouping %s does not partition the columns" % grouping["id"])
            self.assertEqual(len(grouping["groups"]), len(grouping["sampleHeader"]))


class BundledExampleTest(unittest.TestCase):
    """The real file this was written for, if it is present."""

    DATA = os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        "../examplefiles/datasets/11-stategra-more/data"))

    def setUp(self):
        self.design = os.path.join(self.DATA, "experimental_design.tab")
        self.values = os.path.join(self.DATA, "transcription_factor_regulators.tab")
        if not (os.path.exists(self.design) and os.path.exists(self.values)):
            self.skipTest("the 11-stategra-more example is not installed here")

    def test_collapses_thirty_six_columns_to_twelve_conditions(self):
        with open(self.design) as handle:
            body = handle.read()
        with open(self.values) as handle:
            replicateHeader = handle.readline().rstrip("\n").split("\t")[1:]

        self.assertEqual(len(replicateHeader), 36)
        sampleHeader, mapping, groups = parse_design(body, replicateHeader)

        self.assertEqual(sampleHeader,
                         ["Ctr_0H", "Ctr_2H", "Ctr_6H", "Ctr_12H", "Ctr_18H", "Ctr_24H",
                          "Ik_0H", "Ik_2H", "Ik_6H", "Ik_12H", "Ik_18H", "Ik_24H"])
        self.assertEqual([len(g) for g in groups], [3] * 12)
        self.assertEqual(len(mapping), 36)

    def test_offers_the_treatment_and_timepoint_axes(self):
        with open(self.design) as handle:
            body = handle.read()
        with open(self.values) as handle:
            replicateHeader = handle.readline().rstrip("\n").split("\t")[1:]

        sampleHeader, mapping, _groups = parse_design(body, replicateHeader)
        byId = dict((g["id"], g)
                    for g in derive_groupings(replicateHeader, sampleHeader, mapping))
        self.assertEqual(byId["factor0"]["sampleHeader"], ["Ctr", "Ik"])
        self.assertEqual(byId["factor1"]["sampleHeader"],
                         ["0H", "2H", "6H", "12H", "18H", "24H"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
