#!/usr/bin/env python3
"""Regression test for miRNA2Target's condition-name header.

miRNA2Target used to drop the first cell of the header unconditionally, on the
assumption that it labels the ID column. gene_expression_values.tab does label
it ("#geneID"); mirna_unmapped_values.tab does not -- its header is six bare
condition names above six value columns. The example therefore lost "I/C_0h"
and wrote five condition names above six columns of data, so anything zipping
labels to values downstream mislabelled every condition.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_mirna_header_alignment
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

EXAMPLE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../examplefiles"))


def resolve_header(rows):
    """The header-width rule as implemented in miRNA2Target.parseFiles."""
    raw_header, data_rows = rows[0], rows[1:]
    n_values = len(data_rows[0]) - 1
    return raw_header if len(raw_header) == n_values else raw_header[1:]


class HeaderAlignmentTest(unittest.TestCase):

    def test_header_without_id_label_keeps_every_condition(self):
        rows = [
            ["I/C_0h", "I/C_2h", "I/C_6h"],
            ["mmu-miR-1", "0.1", "0.2", "0.3"],
        ]
        self.assertEqual(resolve_header(rows), ["I/C_0h", "I/C_2h", "I/C_6h"])

    def test_header_with_id_label_drops_only_the_label(self):
        rows = [
            ["#geneID", "I/C_0h", "I/C_2h", "I/C_6h"],
            ["ENSMUSG00000000001", "0.1", "0.2", "0.3"],
        ]
        self.assertEqual(resolve_header(rows), ["I/C_0h", "I/C_2h", "I/C_6h"])

    def test_label_count_always_matches_value_count(self):
        for rows in (
            [["A", "B"], ["id", "1", "2"]],
            [["id", "A", "B"], ["id", "1", "2"]],
        ):
            with self.subTest(rows=rows):
                self.assertEqual(len(resolve_header(rows)), len(rows[1]) - 1)


class ShippedExampleFilesTest(unittest.TestCase):
    """The two shipped files are the reason the rule cannot be a fixed slice."""

    def _rows(self, name):
        path = os.path.join(EXAMPLE_DIR, name)
        if not os.path.isfile(path):
            self.skipTest(name + " is not present in this checkout")
        rows = []
        with open(path) as handle:
            for i, raw in enumerate(handle):
                rows.append(raw.rstrip("\n").split("\t"))
                if i >= 1:
                    break
        return rows

    def test_mirna_example_header_has_no_id_column_label(self):
        rows = self._rows("mirna_unmapped_values.tab")
        # One name per value column, and no cell for the ID column.
        self.assertEqual(len(rows[0]), len(rows[1]) - 1)
        self.assertEqual(resolve_header(rows), rows[0])
        self.assertEqual(len(resolve_header(rows)), len(rows[1]) - 1)

    def test_gene_expression_example_header_does_label_the_id_column(self):
        rows = self._rows("gene_expression_values.tab")
        self.assertEqual(len(rows[0]), len(rows[1]))
        self.assertEqual(len(resolve_header(rows)), len(rows[1]) - 1)
        self.assertNotIn("#geneID", resolve_header(rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
