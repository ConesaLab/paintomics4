#!/usr/bin/env python3
"""runMORE.R's two helpers, exercised directly instead of only through a run.

read_matrix and parse_min_variation were covered only incidentally, by the
end-to-end tests feeding them well-formed files. That left three silent
data-loss paths, all found by probing the helpers in isolation:

  * A comma-separated matrix loaded as a 2x0 matrix. The old code fell back to
    sep="," only when the tab parse *threw*, and read.table(sep="\\t") does not
    throw on a comma file -- every line is one field, row.names=1 consumes it,
    and the result is a valid data frame with zero columns. is.null() was
    FALSE so the caller's guard passed and MORE ran on nothing.

  * Duplicate feature IDs took the same path. The tab parse fails with
    "duplicate 'row.names' are not allowed", the comma retry returns the empty
    frame, and the job proceeded with no data. Duplicate gene and metabolite
    IDs are explicitly the kind of input this codebase assumes it will get.

  * One non-numeric cell anywhere coerced the entire matrix to character via
    as.matrix, and the failure surfaced later inside MORE's model fit with no
    mention of the file that caused it.

read_matrix now picks the separator by which parse yields more data columns,
rejects a parse with none, and rejects a non-numeric matrix while naming the
offending columns. It still signals failure by returning NULL, because every
call site already converts NULL into its own specific stop().

The helpers are extracted from the script rather than sourced: sourcing
runMORE.R would execute the whole pipeline, including parse_args.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_runmore_read_matrix
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

R_SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "common", "bioscripts", "runMORE.R"))

HELPERS = ("read_matrix", "parse_min_variation")


def extractFunctions(path, names):
    """Source text of the named top-level functions, by brace balancing.

    Text extraction on purpose. Sourcing the script would run parse_args and
    the whole pipeline; these are unit tests of two helpers.
    """
    with open(path, encoding="utf-8") as handle:
        src = handle.read()
    chunks = []
    for name in names:
        start = src.index("%s <- function" % name)
        depth, i, seen = 0, start, False
        while i < len(src):
            if src[i] == "{":
                depth += 1
                seen = True
            elif src[i] == "}":
                depth -= 1
                if seen and depth == 0:
                    i += 1
                    break
            i += 1
        chunks.append(src[start:i])
    return "\n\n".join(chunks) + "\n"


# Reports mode/dims for a matrix, "NULL", or "ERROR: ...". One line per case so
# the Python side can assert without parsing R objects.
DRIVER = r'''
args <- commandArgs(trailingOnly=TRUE)
source(args[1])
tmp <- args[2]
w <- function(name, lines) { p <- file.path(tmp, name); writeLines(lines, p); p }
emit <- function(label, value) {
  if (is.null(value)) { cat(sprintf("%s|NULL\n", label)); return(invisible()) }
  cat(sprintf("%s|%s|%d|%d|%s|%s\n", label, mode(value), nrow(value), ncol(value),
              paste(rownames(value), collapse=","),
              paste(colnames(value), collapse=",")))
}
run <- function(label, expr)
  emit(label, tryCatch(expr, error=function(e) NULL))

run("nullpath",   read_matrix(NULL))
run("literalnull",read_matrix("NULL"))
run("missing",    read_matrix(file.path(tmp, "nope.tab")))
run("tab",        read_matrix(w("a.tab", c("ID\tS1\tS2","G1\t1\t2","G2\t3\t4"))))
run("comma",      read_matrix(w("b.csv", c("ID,S1,S2","G1,1,2","G2,3,4"))))
run("hdrspaces",  read_matrix(w("c.tab", c("ID\tCtrl 1\tCtrl 2","G1\t1\t2"))))
run("quoted",     read_matrix(w("d.tab", c("ID\tS1","\"G1\"\t\"1\""))))
run("textcell",   read_matrix(w("e.tab", c("ID\tS1\tS2","G1\t1\tNA","G2\tabc\t4"))))
run("dupids",     read_matrix(w("f.tab", c("ID\tS1","G1\t1","G1\t2"))))
run("onecol",     read_matrix(w("g.tab", c("ID\tS1","G1\t1","G2\t2"))))
run("blankline",  read_matrix(w("h.tab", c("ID\tS1","G1\t1",""))))
run("emptycell",  read_matrix(w("i.tab", c("ID\tS1\tS2","G1\t1\t","G2\t3\t4"))))
run("headeronly", read_matrix(w("j.tab", c("ID\tS1\tS2"))))
run("commadup",   read_matrix(w("k.csv", c("ID,S1","G1,1","G1,2"))))

pv <- function(label, raw, omics) {
  out <- tryCatch(suppressWarnings(parse_min_variation(raw, omics)),
                  error=function(e) "ERROR")
  cat(sprintf("MV:%s|%s|%s\n", label, paste(out, collapse=","),
              paste(names(out), collapse=",")))
}
pv("single",   "0.1", c("TF","miRNA"))
pv("peromic",  "0.1,0.2", c("TF","miRNA"))
pv("auto",     "NA", c("TF","miRNA"))
pv("mixed",    "0.1,NA", c("TF","miRNA"))
pv("empty",    "", c("TF","miRNA"))
pv("padded",   " 0.1 , 0.2 ", c("TF","miRNA"))
pv("toomany",  "0.1,0.2,0.3", c("TF","miRNA"))
pv("nonnum",   "abc", c("TF","miRNA"))
pv("zero",     "0", c("TF"))
'''


def runDriver():
    """{label: fields} for every case, or None when R is unavailable."""
    if not shutil.which("Rscript"):
        return None
    workdir = tempfile.mkdtemp(prefix="runmore_helpers_")
    try:
        helpers = os.path.join(workdir, "helpers.R")
        driver = os.path.join(workdir, "driver.R")
        data = os.path.join(workdir, "data")
        os.makedirs(data)
        with open(helpers, "w") as handle:
            handle.write(extractFunctions(R_SCRIPT, HELPERS))
        with open(driver, "w") as handle:
            handle.write(DRIVER)
        proc = subprocess.run(["Rscript", driver, helpers, data],
                              capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            raise AssertionError("driver failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        results = {}
        for line in proc.stdout.splitlines():
            if "|" not in line:
                continue                      # MORE ERROR: diagnostics
            label, _, rest = line.partition("|")
            results[label] = rest.split("|")
        return results
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


RESULTS = runDriver()


@unittest.skipIf(RESULTS is None, "Rscript not available")
class ReadMatrixTest(unittest.TestCase):

    def result(self, label):
        self.assertIn(label, RESULTS, "driver produced no line for %s" % label)
        return RESULTS[label]

    def assertMatrix(self, label, mode, nrow, ncol):
        fields = self.result(label)
        self.assertNotEqual(fields[0], "NULL", "%s returned NULL" % label)
        self.assertEqual((fields[0], int(fields[1]), int(fields[2])),
                         (mode, nrow, ncol))

    def assertNull(self, label):
        self.assertEqual(self.result(label)[0], "NULL",
                         "%s should have been rejected" % label)

    # -- absent input ----------------------------------------------------
    def test_a_null_path_yields_null(self):
        self.assertNull("nullpath")

    def test_the_literal_string_NULL_yields_null(self):
        """optparse hands through 'NULL' for an omitted association file."""
        self.assertNull("literalnull")

    def test_a_missing_file_yields_null(self):
        self.assertNull("missing")

    # -- the shapes that must load ---------------------------------------
    def test_a_tab_matrix_loads_numeric(self):
        self.assertMatrix("tab", "numeric", 2, 2)

    def test_a_comma_matrix_loads_numeric(self):
        """The regression. This used to come back 2x0 and logical, and the
        caller's is.null() guard let it through."""
        self.assertMatrix("comma", "numeric", 2, 2)

    def test_the_comma_matrix_keeps_its_ids_and_headers(self):
        fields = self.result("comma")
        self.assertEqual(fields[3], "G1,G2")
        self.assertEqual(fields[4], "S1,S2")

    def test_headers_with_spaces_survive(self):
        """check.names=FALSE: sample names must match the design file exactly."""
        self.assertEqual(self.result("hdrspaces")[4], "Ctrl 1,Ctrl 2")

    def test_quoted_fields_are_unquoted(self):
        self.assertMatrix("quoted", "numeric", 1, 1)

    def test_a_single_sample_column_loads(self):
        self.assertMatrix("onecol", "numeric", 2, 1)

    def test_a_trailing_blank_line_is_ignored(self):
        self.assertMatrix("blankline", "numeric", 1, 1)

    def test_an_empty_cell_stays_numeric_as_na(self):
        """Missing values are ordinary in omics matrices and must not flip the
        matrix to character."""
        self.assertMatrix("emptycell", "numeric", 2, 2)

    # -- the shapes that must be rejected, loudly ------------------------
    def test_duplicate_feature_ids_are_rejected(self):
        """Was a silent 2x0 matrix. Duplicate gene/metabolite IDs are exactly
        the input this codebase expects to receive."""
        self.assertNull("dupids")

    def test_duplicate_ids_in_a_comma_file_are_rejected_too(self):
        self.assertNull("commadup")

    def test_a_non_numeric_cell_is_rejected(self):
        """as.matrix would otherwise coerce every cell to character and the
        failure would surface inside MORE's model fit."""
        self.assertNull("textcell")

    def test_a_header_with_no_data_rows_is_rejected(self):
        self.assertNull("headeronly")


@unittest.skipIf(RESULTS is None, "Rscript not available")
class ParseMinVariationTest(unittest.TestCase):
    """--min_variation is one value per omic in --omic_names order, or a single
    value for all, or the 'NA' sentinel meaning MORE's automatic threshold."""

    def values(self, label):
        self.assertIn("MV:" + label, RESULTS)
        return RESULTS["MV:" + label]

    def test_one_value_is_broadcast_to_every_omic(self):
        self.assertEqual(self.values("single")[0], "0.1,0.1")

    def test_the_result_is_named_by_omic(self):
        """MORE indexes minVariation by omic name; unnamed would misassign."""
        self.assertEqual(self.values("single")[1], "TF,miRNA")

    def test_one_value_per_omic_is_kept_in_order(self):
        self.assertEqual(self.values("peromic")[0], "0.1,0.2")

    def test_the_NA_sentinel_becomes_a_real_na(self):
        self.assertEqual(self.values("auto")[0], "NA,NA")

    def test_NA_can_be_mixed_with_numbers(self):
        self.assertEqual(self.values("mixed")[0], "0.1,NA")

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(self.values("padded")[0], "0.1,0.2")

    def test_an_empty_string_falls_back_to_zero_for_all(self):
        self.assertEqual(self.values("empty")[0], "0,0")

    def test_a_wrong_length_list_falls_back_to_zero_for_all(self):
        """Better a stated default for every omic than a silent misalignment
        that applies omic 2's threshold to omic 1."""
        self.assertEqual(self.values("toomany")[0], "0,0")

    def test_a_non_numeric_value_becomes_na(self):
        self.assertEqual(self.values("nonnum")[0], "NA,NA")

    def test_zero_is_preserved_and_not_treated_as_missing(self):
        self.assertEqual(self.values("zero")[0], "0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
