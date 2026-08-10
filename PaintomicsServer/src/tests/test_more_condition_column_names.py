#!/usr/bin/env python3
"""The condition menu must show condition names, not indicator patterns.

MORE names the per-condition coefficient columns of its RegulationPerCondition
table after the *experimental design's indicator pattern* rather than after the
group, so a four-group design produces

    Group_1_0_0_0   Group_0_1_0_0   Group_0_0_1_0   Group_0_0_0_1

and the client, which only strips the `Group_` prefix, offers a condition menu
reading "1_0_0_0". Verified identical from both engines on the bundled
06-regulatory-more example, so this is MORE's own behaviour and not a
difference between R and the Rust port.

It gets worse as the design grows. The bundled real dataset has twelve groups,
which makes every menu entry a twelve-token string differing from its
neighbours in two characters.

The names are in the design file, so MOREServlet renames the columns once, at
the file, right after the backend writes it. Once, at the file, because the
regulation table, the network view and any later reader of the stored job all
consume the same header -- undoing the encoding in each of them would be three
chances to disagree.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_condition_column_names
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets import MOREServlet

DESIGN = (
    "Sample\tControl\tEarly\tMid\tLate\n"
    "Control_R1\t1\t0\t0\t0\n"
    "Control_R2\t1\t0\t0\t0\n"
    "Early_R1\t0\t1\t0\t0\n"
    "Early_R2\t0\t1\t0\t0\n"
    "Mid_R1\t0\t0\t1\t0\n"
    "Late_R1\t0\t0\t0\t1\n"
)

RPC = (
    "targetF\tregulator\tomic\tarea\tGroup_1_0_0_0\tGroup_0_1_0_0\t"
    "Group_0_0_1_0\tGroup_0_0_0_1\tR2\n"
    "GENE1\tTF1\tTranscription_factor\t\t0.5\t0.6\t0.7\t0.8\t0.91\n"
    "GENE2\tTF2\tTranscription_factor\t\t-0.5\t\t0.2\t0.3\t0.44\n"
)


class ConditionColumnNamingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="more_cond_")
        self.design = os.path.join(self.tmp, "experimental_design.tab")
        self.rpc = os.path.join(self.tmp, "MORE_rpc_test.tab")
        with open(self.design, "w") as handle:
            handle.write(DESIGN)
        with open(self.rpc, "w") as handle:
            handle.write(RPC)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _header(self):
        with open(self.rpc) as handle:
            return handle.readline().rstrip("\n").split("\t")

    def _body(self):
        with open(self.rpc) as handle:
            handle.readline()
            return handle.read()

    def test_the_patterns_become_the_design_group_names(self):
        self.assertTrue(MOREServlet._nameConditionColumns(self.rpc, self.design))
        self.assertEqual(
            self._header(),
            ["targetF", "regulator", "omic", "area", "Group_Control",
             "Group_Early", "Group_Mid", "Group_Late", "R2"])

    def test_the_group_prefix_survives(self):
        """Every consumer finds condition columns by that prefix -- the client
        filters on `indexOf("Group_") === 0` in two views. Renaming the column
        outright would empty the condition menu instead of labelling it."""
        MOREServlet._nameConditionColumns(self.rpc, self.design)
        conditions = [c for c in self._header() if c.startswith("Group_")]
        self.assertEqual(len(conditions), 4)

    def test_the_data_is_untouched(self):
        """Only the first line changes. This file is a few megabytes on the
        bundled example, and it is the analysis result."""
        MOREServlet._nameConditionColumns(self.rpc, self.design)
        self.assertEqual(self._body(), RPC.split("\n", 1)[1])

    def test_the_non_condition_columns_are_left_alone(self):
        MOREServlet._nameConditionColumns(self.rpc, self.design)
        header = self._header()
        self.assertEqual(header[:4], ["targetF", "regulator", "omic", "area"])
        self.assertEqual(header[-1], "R2")

    def test_a_missing_design_leaves_the_file_exactly_as_it_was(self):
        """Non-fatal: ugly headers are what shipped, an empty results table is
        not. A rename is a convenience and must never be able to cost data."""
        self.assertFalse(MOREServlet._nameConditionColumns(
            self.rpc, os.path.join(self.tmp, "nope.tab")))
        with open(self.rpc) as handle:
            self.assertEqual(handle.read(), RPC)

    def test_an_unreadable_rpc_does_not_raise(self):
        self.assertFalse(MOREServlet._nameConditionColumns(
            os.path.join(self.tmp, "nope.tab"), self.design))

    def test_a_header_that_does_not_match_is_left_alone(self):
        """A future MORE that already names its columns must not be rewritten
        into something else, and must not leave a stray temporary file."""
        named = ("targetF\tregulator\tomic\tarea\tGroup_Control\tR2\n"
                 "GENE1\tTF1\tTF\t\t0.5\t0.9\n")
        with open(self.rpc, "w") as handle:
            handle.write(named)

        self.assertFalse(MOREServlet._nameConditionColumns(self.rpc, self.design))
        with open(self.rpc) as handle:
            self.assertEqual(handle.read(), named)
        self.assertFalse(os.path.exists(self.rpc + ".named"))

    def test_a_twelve_group_design_is_the_case_that_matters(self):
        """The bundled real dataset. Twelve groups make every pattern a
        twelve-token string differing from its neighbours in two characters,
        which is unreadable as a menu entry in a way four groups only hints
        at."""
        groups = ["Ctr_0H", "Ctr_2H", "Ctr_6H", "Ctr_12H", "Ctr_18H", "Ctr_24H",
                  "Ik_0H", "Ik_2H", "Ik_6H", "Ik_12H", "Ik_18H", "Ik_24H"]
        rows = []
        for index, group in enumerate(groups):
            indicators = ["1" if position == index else "0"
                          for position in range(len(groups))]
            rows.append("S%d\t%s" % (index, "\t".join(indicators)))
        with open(self.design, "w") as handle:
            handle.write("Sample\t" + "\t".join(groups) + "\n")
            handle.write("\n".join(rows) + "\n")

        columns = ["targetF", "regulator", "omic", "area"]
        for index in range(len(groups)):
            columns.append("Group_" + "_".join(
                "1" if position == index else "0" for position in range(len(groups))))
        columns.append("R2")
        with open(self.rpc, "w") as handle:
            handle.write("\t".join(columns) + "\n")
            handle.write("\t".join(["G1", "TF1", "TF", ""] +
                                   ["0.1"] * len(groups) + ["0.5"]) + "\n")

        self.assertTrue(MOREServlet._nameConditionColumns(self.rpc, self.design))
        self.assertEqual([c for c in self._header() if c.startswith("Group_")],
                         ["Group_" + group for group in groups])

    def test_a_row_marking_two_groups_is_named_rather_than_dropped(self):
        """Not a shape the interface produces, but a hand-written design can
        carry one, and losing the column's name is worse than an odd name."""
        with open(self.design, "w") as handle:
            handle.write("Sample\tA\tB\n"
                         "S1\t1\t1\n"
                         "S2\t0\t1\n")
        with open(self.rpc, "w") as handle:
            handle.write("targetF\tGroup_1_1\tGroup_0_1\n"
                         "G1\t0.2\t0.3\n")

        self.assertTrue(MOREServlet._nameConditionColumns(self.rpc, self.design))
        self.assertEqual(self._header(), ["targetF", "Group_A+B", "Group_B"])


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
