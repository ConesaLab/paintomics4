#!/usr/bin/env python3
"""How a relevance file is shaped, and where condition names come from.

Three defects measured over the ten bundled example datasets, all in
`src/classes/Job.py`:

1. HIGH -- a miRNA's *name* decided whether the relevance file parsed at all.
   MiRNA2GeneJob writes `regulator2Gene_relevant_*.tab` as `GENE<TAB>miRNA`
   rows under a `# Gene name<TAB>miRNA ID` header. The parser decided between
   "legacy [TARGET, REGULATOR] pairs" and "two-condition relevance matrix" by
   asking whether BOTH cells of the first data row contained 4+ consecutive
   digits or a colon. Measured before the fix:

       _row_looks_like_data(['MMU-MIR-100-3P'])  -> False   # file mis-parsed
       _row_looks_like_data(['MMU-MIR-1983'])    -> True    # same shape, fine

   Mis-parsed, the file yields bare `gene` / `mirna` keys which can never match
   the values file's `gene:::mirna` feature IDs, so the regulator omic carried
   ZERO relevant features and every pathway came out at Fisher p = 1.0
   (scenario 05: 0 of 357; scenario 10: 0 of 362).

   Fixed by deciding the shape from the HEADER: a `#`-prefixed first row is a
   schema descriptor, and with exactly two columns it declares a pair file.

2. LOW -- the BED branch never skipped comment rows, and it runs BEFORE the
   `#` handling used by the other formats. Scenario 09 ships a stray
   `#CHR<TAB>start<TAB>end` at line 886 (a concatenation artifact) and the
   parser turned it into the phantom relevant feature `#chr_start_end`.

3. MEDIUM -- `conditionNames` had exactly one source, the relevance file, and
   a single-column relevance file cannot name conditions. Scenarios 01/02/04/05
   resolved to `['Condition 1']` (client then renders "Cond 2".."Cond 6")
   although their values files are headed T00h..T24h; the chained miRNA job
   shipped the literal schema header `[' Gene name', 'miRNA ID']` to the
   browser AS condition labels.

Usage:
    cd PaintomicsServer
    PYTHONPATH=. python -m src.tests.test_relevance_file_shape_and_conditions
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Job import Job

EXAMPLE_DATASETS = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examplefiles", "datasets"))


def dataset(scenarioDir, fileName):
    return os.path.join(EXAMPLE_DATASETS, scenarioDir, "data", fileName)


def firstDataRow(path):
    """The first non-comment, non-blank row of a bundled file, as a list of cells.

    Tests below assert that a shipped file still parses losslessly. Naming a
    literal identifier for that is a trap: the simulated datasets are rebuilt by
    `python -m src.AdminTools.scripts.exampledata`, and a regeneration that
    legitimately changes which features are relevant then fails a test about the
    *parser*. Both of these assertions did exactly that within half an hour of
    being written. Reading the row back from the file keeps the test aimed at
    what it is really checking -- that row one survives the parse -- and lets the
    data move freely underneath it.
    """
    with open(path, "r") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                return line.split("\t")
    raise AssertionError("%s has no data rows" % path)


class TempFilesTestCase(unittest.TestCase):
    """Writes relevance files to a scratch dir; nothing lands in the repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="paintomics_relevance_")
        self.job = Job("SHAPETEST01", None, "/tmp/")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def writeFile(self, name, *lines):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        return path


# ----------------------------------------------------------------------------
# DEFECT 1 -- the shape comes from the header, not from an identifier's spelling
# ----------------------------------------------------------------------------

class PairFileShapeTest(TempFilesTestCase):

    HEADER = "# Gene name\tmiRNA ID"

    def parsePairFile(self, *rows):
        return self.job.parseSignificativeFeaturesFile(
            self.writeFile("regulator2Gene_relevant.tab", self.HEADER, *rows))

    def test_the_predicate_that_used_to_decide_this_is_still_name_dependent(self):
        """Premise of the defect. If this ever stops being true the fix is
        still correct, but the reason it was needed has changed."""
        self.assertFalse(Job._row_looks_like_data(['MMU-MIR-100-3P']))
        self.assertFalse(Job._row_looks_like_data(['hsa-let-7a-5p']))
        self.assertTrue(Job._row_looks_like_data(['MMU-MIR-1983']))
        self.assertTrue(Job._row_looks_like_data(['ENSMUSG00000021748']))

    def test_a_regulator_whose_name_has_no_long_digit_run_still_pairs(self):
        """The exact row that broke scenarios 05 and 10."""
        parsed = self.parsePairFile(
            "ENSMUSG00000021748\tmmu-miR-100-3p",
            "ENSMUSG00000021748\tmmu-miR-100-5p",
            "ENSMUSG00000004455\tmmu-let-7a-5p")

        self.assertEqual(sorted(parsed), [
            "ensmusg00000004455:::mmu-let-7a-5p",
            "ensmusg00000021748:::mmu-mir-100-3p",
            "ensmusg00000021748:::mmu-mir-100-5p"])
        for value in parsed.values():
            self.assertEqual(value, [True])

    def test_the_same_file_parses_the_same_whatever_the_first_regulator_is(self):
        """This is the whole point: no identifier may change the file's shape.

        Before the fix these two returned different key *formats* -- the
        digit-bearing one produced `gene:::mirna`, the other produced bare
        `gene` and `mirna` keys.
        """
        digitRun = self.parsePairFile("ENSMUSG00000021748\tmmu-miR-1983")
        noDigitRun = Job("SHAPETEST02", None, "/tmp/").parseSignificativeFeaturesFile(
            self.writeFile("other.tab", self.HEADER,
                           "ENSMUSG00000021748\tmmu-miR-100-3p"))

        self.assertEqual(list(digitRun), ["ensmusg00000021748:::mmu-mir-1983"])
        self.assertEqual(list(noDigitRun), ["ensmusg00000021748:::mmu-mir-100-3p"])

    def test_a_schema_header_is_never_shipped_as_condition_names(self):
        """Measured before: conditionNames == [' Gene name', 'miRNA ID']."""
        self.parsePairFile("ENSMUSG00000021748\tmmu-miR-100-3p")
        self.assertEqual(self.job.conditionNames, [])

    def test_every_row_is_paired_not_only_the_first(self):
        parsed = self.parsePairFile(
            "ENSMUSG00000000001\tmmu-miR-let-a",
            "ENSMUSG00000000002\tmmu-miR-let-b",
            "ENSMUSG00000000003\tmmu-miR-let-c")
        self.assertEqual(len(parsed), 3)
        self.assertTrue(all(":::" in key for key in parsed))

    def test_blank_and_short_rows_do_not_abort_the_parse(self):
        parsed = self.parsePairFile(
            "ENSMUSG00000000001\tmmu-miR-let-a",
            "",
            "\t",
            "ENSMUSG00000000002")
        self.assertEqual(sorted(parsed),
                         ["ensmusg00000000001:::mmu-mir-let-a",
                          "ensmusg00000000002"])


class ShapesThatMustNotChangeTest(TempFilesTestCase):
    """Everything the header rule is NOT allowed to reinterpret."""

    def test_a_headerless_two_column_pair_file_is_still_legacy(self):
        """datasets/08's mirna_relevant.tab shape -- no header at all, so the
        first-data-row heuristic is still the only thing that can decide."""
        parsed = self.job.parseSignificativeFeaturesFile(
            dataset("08-stategra-multiomics", "mirna_relevant.tab"))
        self.assertTrue(parsed)
        self.assertTrue(all(":::" in key for key in parsed),
                        "headerless pair file stopped being read as pairs")

    def test_a_plain_two_condition_header_is_still_a_condition_matrix(self):
        parsed = self.job.parseSignificativeFeaturesFile(
            self.writeFile("two_conditions.tab",
                           "WT\tKO",
                           "ENSMUSG00000000001\tENSMUSG00000000002",
                           "ENSMUSG00000000003\tENSMUSG00000000001"))

        self.assertEqual(self.job.conditionNames, ["WT", "KO"])
        self.assertEqual(parsed["ensmusg00000000001"], [True, True])
        self.assertEqual(parsed["ensmusg00000000002"], [False, True])
        self.assertEqual(parsed["ensmusg00000000003"], [True, False])

    def test_the_six_condition_example_keeps_its_six_real_names(self):
        """datasets/03 is the one scenario whose relevance file really does
        supply condition names. It must not be reinterpreted."""
        parsed = self.job.parseSignificativeFeaturesFile(
            dataset("03-gene-multi-condition-relevance",
                    "gene_expression_relevant.tab"))

        self.assertEqual(self.job.conditionNames,
                         ["T00h", "T02h", "T06h", "T12h", "T18h", "T24h"])
        self.assertTrue(parsed)
        for value in parsed.values():
            self.assertEqual(len(value), 6)

    def test_a_hash_prefixed_header_of_more_than_two_columns_still_names_conditions(self):
        """Only the two-column case has a pair interpretation to switch to."""
        parsed = self.job.parseSignificativeFeaturesFile(
            self.writeFile("three_conditions.tab",
                           "#T00h\tT02h\tT06h",
                           "ENSMUSG00000000001\tENSMUSG00000000002\tENSMUSG00000000003"))

        self.assertEqual(self.job.conditionNames, ["T00h", "T02h", "T06h"])
        self.assertEqual(parsed["ensmusg00000000001"], [True, False, False])

    def test_a_single_column_relevance_file_is_unchanged(self):
        path = dataset("05-regulatory-mirna", "mirna_relevant.tab")
        firstFeature = firstDataRow(path)[0].lower()

        parsed = self.job.parseSignificativeFeaturesFile(path)

        self.assertIn(firstFeature, parsed)
        self.assertEqual(parsed[firstFeature], [True])

    def test_a_single_column_hash_header_is_not_a_relevant_feature(self):
        """datasets/08's dnase_relevant.tab starts with `#Gene name`, which the
        single-column branch never skipped -- it became a feature key."""
        parsed = self.job.parseSignificativeFeaturesFile(
            dataset("08-stategra-multiomics", "dnase_relevant.tab"))
        self.assertTrue(parsed)
        self.assertEqual([key for key in parsed if key.startswith("#")], [])

    def test_a_proteomics_style_symbol_first_row_is_still_a_feature(self):
        """datasets/08's proteomics_relevant.tab starts with `Nup50`, which
        fails the ID heuristic. It has no `#`, so it is data, not a header."""
        parsed = self.job.parseSignificativeFeaturesFile(
            dataset("08-stategra-multiomics", "proteomics_relevant.tab"))
        self.assertIn("nup50", parsed)


# ----------------------------------------------------------------------------
# DEFECT 2 -- comment rows in a BED relevance file
# ----------------------------------------------------------------------------

class BedCommentRowsTest(TempFilesTestCase):

    def test_the_shipped_stray_header_is_not_a_relevant_region(self):
        """datasets/09 carries `#CHR<TAB>start<TAB>end` at line 886."""
        parsed = self.job.parseSignificativeFeaturesFile(
            dataset("09-stategra-regions", "dnase_unmapped_relevant.tab"),
            isBedFormat=True)

        self.assertEqual([key for key in parsed if key.startswith("#")], [],
                         "phantom relevant region built from a comment row")
        self.assertIn("17_13654752_13655272", parsed)

    def test_a_leading_bed_header_is_skipped_too(self):
        parsed = self.job.parseSignificativeFeaturesFile(
            self.writeFile("regions.tab",
                           "#CHR\tstart\tend",
                           "1\t40098\t40498",
                           "#CHR\tstart\tend",
                           "1\t129499\t129899"),
            isBedFormat=True)

        self.assertEqual(sorted(parsed),
                         ["1_129499_129899", "1_40098_40498"])

    def test_a_headerless_bed_file_is_unchanged(self):
        path = dataset("07-region-based", "dnase_regions_relevant.tab")
        chromosome, start, end = firstDataRow(path)[:3]

        parsed = self.job.parseSignificativeFeaturesFile(path, isBedFormat=True)

        self.assertIn("%s_%s_%s" % (chromosome, start, end), parsed)
        self.assertEqual(self.job.conditionNames, ["Condition 1"])


# ----------------------------------------------------------------------------
# DEFECT 3 -- condition names fall back to the values file's own header
# ----------------------------------------------------------------------------

class ConditionNameFallbackTest(unittest.TestCase):

    def setUp(self):
        self.job = Job("CONDTEST01", None, "/tmp/")

    def test_a_placeholder_is_replaced_by_the_values_header(self):
        """Scenarios 01/02/04/05: `['Condition 1']` against a T00h..T24h file."""
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(
            ["#geneID", "T00h", "T02h", "T06h", "T12h", "T18h", "T24h"], 6)
        self.assertEqual(self.job.conditionNames,
                         ["T00h", "T02h", "T06h", "T12h", "T18h", "T24h"])

    def test_a_generated_placeholder_set_is_replaced(self):
        self.job.conditionNames = ["Condition 1", "Condition 2"]
        self.job._applyValuesFileConditionNames(["#ID", "WT", "KO"], 2)
        self.assertEqual(self.job.conditionNames, ["WT", "KO"])

    def test_real_names_from_the_relevance_file_are_kept(self):
        """datasets/03 supplies six real names and must keep them even when the
        values file disagrees."""
        self.job.conditionNames = ["A", "B", "C", "D", "E", "F"]
        self.job._applyValuesFileConditionNames(
            ["#geneID", "T00h", "T02h", "T06h", "T12h", "T18h", "T24h"], 6)
        self.assertEqual(self.job.conditionNames,
                         ["A", "B", "C", "D", "E", "F"])

    def test_an_unlabelled_id_column_is_handled(self):
        """datasets/10's values file heads six data columns with six names and
        no label for the ID column at all."""
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(
            ["I/C_0h", "I/C_2h", "I/C_6h", "I/C_12h", "I/C_18h", "I/C_24h"], 6)
        self.assertEqual(self.job.conditionNames,
                         ["I/C_0h", "I/C_2h", "I/C_6h", "I/C_12h",
                          "I/C_18h", "I/C_24h"])

    def test_a_header_that_cannot_be_aligned_is_ignored(self):
        """Guessing here would mislabel the chart axes."""
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(["#geneID", "T00h", "T02h"], 6)
        self.assertEqual(self.job.conditionNames, ["Condition 1"])

    def test_a_schema_header_left_over_from_a_pair_file_is_overwritten(self):
        """The chained miRNA job used to ship these to the browser as labels."""
        self.job.conditionNames = [" Gene name", "miRNA ID"]
        self.job._applyValuesFileConditionNames(
            ["#geneID", "T00h", "T02h", "T06h", "T12h", "T18h", "T24h"], 6)
        self.assertEqual(self.job.conditionNames,
                         ["T00h", "T02h", "T06h", "T12h", "T18h", "T24h"])

    def test_a_values_file_without_a_header_changes_nothing(self):
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(None, 6)
        self.assertEqual(self.job.conditionNames, ["Condition 1"])

    def test_a_header_with_an_empty_cell_is_ignored(self):
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(["#ID", "T00h", "  "], 2)
        self.assertEqual(self.job.conditionNames, ["Condition 1"])

    def test_a_single_condition_file_gets_its_real_column_name(self):
        self.job.conditionNames = ["Condition 1"]
        self.job._applyValuesFileConditionNames(["#geneID", "logFC"], 1)
        self.assertEqual(self.job.conditionNames, ["logFC"])

    def test_the_shipped_values_headers_of_05_and_10_still_name_conditions(self):
        """Guarding against the BED reserved vocabulary (see
        src/tests/test_region_condition_names.py) must not cost these two the
        names the fallback won for them: scenario 05's chained miRNA job takes
        T00h..T24h from `#miRNA<TAB>T00h..`, and scenario 10 takes I/C_0h..
        from a header with no label on the ID column at all.

        Read from the shipped files rather than written out here, so the
        assertion follows the data if it is legitimately renamed."""
        for scenarioDir, valuesFile in (
                ("05-regulatory-mirna", "mirna_values.tab"),
                ("10-stategra-mirna", "mirna_unmapped_values.tab")):
            path = dataset(scenarioDir, valuesFile)
            with open(path, "r") as handle:
                header = handle.readline().rstrip("\n").split("\t")
            nValueColumns = len(firstDataRow(path)) - 1

            job = Job("CONDTEST_" + scenarioDir[:2], None, "/tmp/")
            job.conditionNames = ["Condition 1"]
            job._applyValuesFileConditionNames(header, nValueColumns)

            expected = (header[1:] if len(header) == nValueColumns + 1
                        else header)
            self.assertEqual(job.conditionNames, expected,
                             "%s lost its condition names" % scenarioDir)
            self.assertEqual(len(job.conditionNames), nValueColumns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
