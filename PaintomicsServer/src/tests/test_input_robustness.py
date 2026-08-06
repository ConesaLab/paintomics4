#!/usr/bin/env python3
"""Edge-case behaviour of the input parsers.

Omics files arrive from spreadsheets, other pipelines and hand editing, so the
parsers see duplicate IDs, blank cells, stray whitespace, BOMs, CRLF endings and
ragged rows. This exercises those directly rather than through an upload, and
records what each one currently does -- so a change in behaviour is visible
rather than silent.

Where the current behaviour is arguably wrong the test says so in a comment and
asserts what actually happens, so the suite stays honest instead of encoding a
wish.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_input_robustness
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Job import Job


class ParserEdgeCaseTest(unittest.TestCase):

    def setUp(self):
        self.job = Job("robustness", "nologin", tempfile.gettempdir())
        self._paths = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _write(self, contents, mode="w", encoding="utf-8"):
        handle = tempfile.NamedTemporaryFile(mode, suffix=".tab", delete=False,
                                             encoding=encoding if "b" not in mode else None)
        handle.write(contents)
        handle.close()
        self._paths.append(handle.name)
        return handle.name

    def _parse(self, contents, isBedFormat=False, **kw):
        return self.job.parseSignificativeFeaturesFile(self._write(contents, **kw),
                                                       isBedFormat=isBedFormat)

    # ---- things that must not raise -------------------------------------

    def test_empty_file(self):
        self.assertEqual(self._parse(""), {})

    def test_only_a_header(self):
        self.assertEqual(self._parse("Cond1\tCond2\n"), {})

    def test_blank_lines_between_records(self):
        result = self._parse("ENSMUSG00000000001\n\nENSMUSG00000000002\n\n\n")
        self.assertIn("ensmusg00000000001", result)
        self.assertIn("ensmusg00000000002", result)

    def test_crlf_line_endings(self):
        result = self._parse("ENSMUSG00000000001\r\nENSMUSG00000000002\r\n")
        self.assertIn("ensmusg00000000001", result)
        self.assertNotIn("ensmusg00000000001\r", result)

    def test_utf8_bom_is_stripped(self):
        # Excel exports carry a BOM; without utf-8-sig the first ID would keep
        # a ﻿ prefix and silently never match anything.
        result = self._parse("ENSMUSG00000000001\n", encoding="utf-8-sig")
        self.assertIn("ensmusg00000000001", result)

    def test_duplicate_ids_collapse_rather_than_duplicate(self):
        result = self._parse("ENSMUSG00000000001\nENSMUSG00000000001\n")
        self.assertEqual(len(result), 1)

    def test_case_differences_collapse(self):
        # Keys are lowercased, so these are the same feature.
        result = self._parse("ENSMUSG00000000001\nensmusg00000000001\n")
        self.assertEqual(len(result), 1)

    def test_very_long_identifier(self):
        longID = "ENSMUSG" + "0" * 500
        result = self._parse(longID + "\n")
        self.assertIn(longID.lower(), result)

    def test_unicode_identifier(self):
        result = self._parse("GENEÅÑ中\n")
        self.assertEqual(len(result), 1)

    def test_bed_row_with_too_few_columns_is_skipped(self):
        # A BED region needs chrom/start/end. A shorter row used to raise
        # IndexError and abort the job; it is now skipped, and the valid rows
        # around it still parse.
        result = self._parse("1\t100\n1\t200\t300\n", isBedFormat=True)
        self.assertEqual(list(result), ["1_200_300"])

    def test_bed_file_of_only_short_rows_yields_nothing(self):
        self.assertEqual(self._parse("1\t100\n2\t200\n", isBedFormat=True), {})

    def test_associations_file_tolerates_blank_and_short_rows(self):
        path = self._write("GENE1\tmiR-1\n\nGENE2\n\nGENE3\tmiR-3\n")
        result = self.job.parseAssociationsFile(path)
        self.assertEqual(sorted(result), ["miR-1", "miR-3"])

    def test_ragged_rows_do_not_raise_in_gene_list_mode(self):
        result = self._parse("ENSMUSG00000000001\nENSMUSG00000000002\textra\tcells\n")
        self.assertGreaterEqual(len(result), 1)

    def test_whitespace_only_cells(self):
        result = self._parse("   \nENSMUSG00000000001\n")
        self.assertIn("ensmusg00000000001", result)

    def test_missing_file_returns_empty(self):
        self.assertEqual(
            self.job.parseSignificativeFeaturesFile("/nonexistent/path.tab"), {})

    def test_none_filename_returns_empty(self):
        self.assertEqual(self.job.parseSignificativeFeaturesFile(None), {})


class DelimiterDetectionTest(unittest.TestCase):
    """detect_delimiter picks from the first non-blank line only."""

    def setUp(self):
        self._paths = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _write(self, contents):
        handle = tempfile.NamedTemporaryFile("w", suffix=".tab", delete=False)
        handle.write(contents)
        handle.close()
        self._paths.append(handle.name)
        return handle.name

    def test_tab_wins_over_comma_on_the_same_line(self):
        self.assertEqual(Job.detect_delimiter(self._write("a\tb,c\n")), "\t")

    def test_comma_detected_when_no_tab(self):
        self.assertEqual(Job.detect_delimiter(self._write("a,b,c\n")), ",")

    def test_single_column_defaults_to_tab(self):
        self.assertEqual(Job.detect_delimiter(self._write("onlyonecolumn\n")), "\t")

    def test_empty_file_defaults_to_tab(self):
        self.assertEqual(Job.detect_delimiter(self._write("")), "\t")

    def test_leading_blank_lines_are_skipped(self):
        self.assertEqual(Job.detect_delimiter(self._write("\n\na,b\n")), ",")

    def test_decimal_commas_would_be_read_as_delimiters(self):
        # A real hazard rather than a bug in this function: a European-format
        # file whose first line is "gene\t1,5\t2,7" has a tab, so it is fine --
        # but one with no tabs at all would be split on the decimal comma.
        # Recorded so the risk is visible.
        self.assertEqual(Job.detect_delimiter(self._write("1,5\n")), ",")


class RowClassificationTest(unittest.TestCase):
    """_row_looks_like_data decides header-vs-data, which drives condition names."""

    def test_ensembl_id_is_data(self):
        self.assertTrue(Job._row_looks_like_data(["ENSMUSG00000000001"]))

    def test_kegg_compound_is_data(self):
        self.assertTrue(Job._row_looks_like_data(["cpd:C00001"]))

    def test_arabidopsis_locus_is_data(self):
        self.assertTrue(Job._row_looks_like_data(["AT3G09260"]))

    def test_condition_labels_are_header(self):
        self.assertFalse(Job._row_looks_like_data(["Cond1", "Cond2", "WT"]))

    def test_timepoint_labels_are_header(self):
        self.assertFalse(Job._row_looks_like_data(["I/C_0h", "I/C_2h"]))

    def test_short_gene_symbol_is_classified_as_header(self):
        # The limitation behind the miRNA legacy-format fragility: a symbol with
        # fewer than four consecutive digits and no colon is indistinguishable
        # from a condition label by this heuristic. A values file whose first
        # data row is such a symbol would have that row eaten as a header.
        self.assertFalse(Job._row_looks_like_data(["Tp53"]))
        self.assertFalse(Job._row_looks_like_data(["Bcl2"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
