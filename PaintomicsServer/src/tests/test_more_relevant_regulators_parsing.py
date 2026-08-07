#!/usr/bin/env python3
"""The "significant regulators" file is parsed leniently, and silently.

`_parseRelevantRegulators` was the one function in MOREServlet with no test
naming it. It is worth covering precisely because its failure mode is
invisible: the IDs it returns are matched against the GENE:::REGULATOR column
of the values file to decide which pairs get a red star. If parsing yields
nothing usable, no exception is raised and no warning is logged -- the job
completes, reports success, and simply has no red stars. Nobody looking at the
result can tell the difference between "the parse failed" and "nothing was
significant".

Users build these files by exporting rows out of a statistics table, so the
input arrives in whatever shape the export produced: a trailing p-value
column, Excel's quoting, a header row, semicolons where tabs were expected.
Each of those, read naively, makes every ID match nothing.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_relevant_regulators_parsing
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets.MOREServlet import _REGULATOR_HEADERS, _parseRelevantRegulators


class TestParseRelevantRegulators(unittest.TestCase):
    def parse(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        try:
            handle.write(text)
            handle.close()
            return _parseRelevantRegulators(handle.name)
        finally:
            os.unlink(handle.name)

    def test_a_plain_one_per_line_list_is_read_whole(self):
        self.assertEqual(self.parse("TF1\nTF2\nTF3\n"), {"tf1", "tf2", "tf3"})

    def test_ids_are_lowercased_because_the_match_downstream_is(self):
        # The values file is compared with .lower(), so anything else here
        # would make correctly-spelled IDs miss.
        self.assertEqual(self.parse("TF1\nmiRNA-21\n"), {"tf1", "mirna-21"})

    def test_only_the_first_field_is_taken(self):
        # A p-value column is the usual second field of a stats-table export.
        self.assertEqual(self.parse("TF1\t0.001\nTF2\t0.04\n"), {"tf1", "tf2"})

    def test_commas_and_semicolons_separate_as_well_as_tabs(self):
        self.assertEqual(self.parse("TF1,0.001\nTF2;0.04\nTF3\t0.02\n"),
                         {"tf1", "tf2", "tf3"})

    def test_excel_style_quoting_is_stripped(self):
        self.assertEqual(self.parse('"TF1"\n\'TF2\'\n"TF3",0.01\n'),
                         {"tf1", "tf2", "tf3"})

    def test_a_leading_header_row_is_skipped(self):
        self.assertEqual(self.parse("regulator\tpvalue\nTF1\t0.01\n"), {"tf1"})

    def test_every_recognised_header_word_is_skipped_on_the_first_line(self):
        for header in _REGULATOR_HEADERS:
            self.assertEqual(self.parse(f"{header}\nTF1\n"), {"tf1"},
                             f"header {header!r} was not skipped")

    def test_a_header_word_is_case_insensitive(self):
        self.assertEqual(self.parse("Regulator\nTF1\n"), {"tf1"})

    def test_a_regulator_genuinely_named_like_a_header_survives_below_line_one(self):
        # The skip is deliberately anchored to index 0 so this stays true.
        self.assertEqual(self.parse("TF1\ngene\n"), {"tf1", "gene"})

    def test_a_first_line_that_is_not_a_header_is_kept(self):
        self.assertEqual(self.parse("TF1\nTF2\n"), {"tf1", "tf2"})

    def test_blank_lines_are_ignored(self):
        self.assertEqual(self.parse("TF1\n\n   \nTF2\n"), {"tf1", "tf2"})

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(self.parse("  TF1  \t0.01\n\tTF2\n"), {"tf1", "tf2"})

    def test_duplicates_collapse(self):
        self.assertEqual(self.parse("TF1\nTF1\ntf1\n"), {"tf1"})

    def test_an_empty_file_yields_an_empty_set_rather_than_raising(self):
        # The caller guards on `relevant_tfs` being truthy, so an empty set
        # means "no red stars" rather than a crashed job.
        self.assertEqual(self.parse(""), set())

    def test_a_file_of_only_a_header_yields_an_empty_set(self):
        self.assertEqual(self.parse("regulator\n"), set())

    def test_a_missing_file_raises_rather_than_silently_returning_nothing(self):
        # Distinguishing "path wrong" from "nothing significant" matters; the
        # caller only reaches here when it has already checked the upload.
        with self.assertRaises(IOError):
            _parseRelevantRegulators(os.path.join(tempfile.gettempdir(), "no_such_more_file.txt"))

    def test_crlf_line_endings_do_not_leave_a_stray_carriage_return(self):
        # A Windows-exported list would otherwise yield "tf1\r", matching nothing.
        self.assertEqual(self.parse("TF1\r\nTF2\r\n"), {"tf1", "tf2"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
