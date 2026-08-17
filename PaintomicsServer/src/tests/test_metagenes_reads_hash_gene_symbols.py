#!/usr/bin/env python3
"""generateMetaGenes.R must read a gene symbol that contains '#'.

Real gene symbols do: potato `ptt#2-1`, human `mt-GrpE#1`, fly `CG#6450`,
arabidopsis `ATERF#011`. Column 2 of `<omic>_matched.txt` is a display name
copied straight out of the organism database, so those characters reach R
verbatim.

`read.table`'s default is `comment.char="#"`. Under it the rest of such a line
is discarded, the row comes up short, and read.table aborts the *whole* call --
it does not skip the row. That took the metagenes phase down, and metagenes
failing fails step 2, so every potato (`sot`) job died with

    Error in scan(...) : line 2131 did not have 7 elements

reproduced 2/2 on production before the fix and 1/1 after (218 pathways, 24
significant). The failure was total for that organism and latent for six
others: 7 species carry '#' in an xref display_id (ath 12, dme 11, rno 6,
hsa 4, mmu 4, sot 2, xtr 1), and whether it fires depends on which of them the
mapper resolves to -- `sot` triggers, `ath` and `hsa` with their '#' genes
force-injected do not.

`quote=""` was already present and is not sufficient: the two arguments defend
against different characters and R requires both to be named explicitly. Both
are pinned here.

The point of running the real statements under R rather than grepping for the
argument is that the second test would pass on a script that no longer parses.
The negative case is included so the fixture cannot quietly stop exercising the
bug -- without it, a fixture that R happened to accept either way would make
the positive tests vacuous.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_metagenes_reads_hash_gene_symbols
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

METAGENES_R = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../common/bioscripts/generateMetaGenes.R"))

RSCRIPT = shutil.which("Rscript")

# The two reads under test, keyed by the variable each one assigns.
INPUT_CALL = "input_data"          # <omic>_matched.txt, the file that crashed
REFERENCE_CALL = "genes2pathway"   # gene2pathway[_db].list

# One well formed row, then the row that used to end the run. Full width first
# on purpose: that is the order the real file has, and it is what makes R settle
# on 7 columns and then reject the short line the way production did.
MATCHED_TXT = (
    "Soltu.DM.01G000010\tStCDF1\t102591234\tKEGG\t0.4231\t0.3910\t1\n"
    "Soltu.DM.02G000020\tptt#2-1\t102577748\tKEGG\t0.0152\t0.0104\t0\n"
)

# `<sp>:<geneID>\tpath:<pathwayID>`. No installed species has a '#' in this
# file today (checked across the local set), so the argument is defensive here
# rather than load-bearing -- but the file is built from the same organism
# database, and a defence that is only added after it is needed is the bug.
GENE2PATHWAY_LIST = (
    "sot:102591234\tpath:sot00010\n"
    "sot:102577748\tpath:sot#00020\n"
)


def read_source():
    with open(METAGENES_R, "r", encoding="utf-8") as handle:
        return handle.read()


def extract_call(source, variable):
    """The text of `<variable> <- ...` up to its balanced closing paren.

    Comment lines are dropped first: the fix's own comment quotes
    `comment.char="#"` to explain the default, and that must not be mistaken
    for the argument being present in the call.
    """
    stripped = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#"))

    match = re.search(r"^%s\s*<-\s*" % re.escape(variable), stripped, re.MULTILINE)
    if match is None:
        raise AssertionError(
            "%s is no longer assigned in %s" % (variable, METAGENES_R))

    depth = 0
    for index in range(match.end(), len(stripped)):
        if stripped[index] == "(":
            depth += 1
        elif stripped[index] == ")":
            depth -= 1
            if depth == 0:
                return stripped[match.start():index + 1]
    raise AssertionError("unbalanced parentheses in the %s call" % variable)


def run_in_r(statement, path):
    """Run one extracted statement against `path`; return (rows, cols, col2row2).

    Both fixtures put the '#' in column 2 of their second row, so one accessor
    serves both. Returns None instead of a tuple when R exits non-zero, so a
    caller can assert on the failure as easily as on the success.
    """
    variable = statement.split("<-")[0].strip()
    script = "\n".join([
        'args <- list(input_file=%r, kegg_dir=%r)' % (path, path),
        statement,
        'frame <- as.data.frame(%s)' % variable,
        'cat(nrow(frame), ncol(frame), as.character(frame[[2]][2]), sep="\\n")',
        'cat("\\n")',
    ])

    directory = tempfile.mkdtemp(prefix="paintomics-r-")
    try:
        script_path = os.path.join(directory, "check.R")
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(script)
        completed = subprocess.run(
            [RSCRIPT, "--vanilla", script_path],
            capture_output=True, text=True, timeout=120)
        if completed.returncode != 0:
            return None, completed.stderr
        lines = completed.stdout.strip().splitlines()
        return (int(lines[0]), int(lines[1]), lines[2]), completed.stderr
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def write_fixture(contents, name):
    directory = tempfile.mkdtemp(prefix="paintomics-r-data-")
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(contents)
    return directory, path


class CallSiteTest(unittest.TestCase):
    """Holds with or without R installed."""

    def test_both_reads_disable_the_comment_character(self):
        source = read_source()
        for variable in (INPUT_CALL, REFERENCE_CALL):
            call = extract_call(source, variable)
            self.assertIn(
                'comment.char=""', call.replace(" ", ""),
                "%s reads a database-derived display name with R's default "
                "comment.char='#'" % variable)

    def test_both_reads_still_disable_quoting(self):
        """The other half of the pair, and the older of the two fixes.

        Apostrophes are at least as common in these files as '#'; dropping
        quote="" would swap one parse failure for another.
        """
        source = read_source()
        for variable in (INPUT_CALL, REFERENCE_CALL):
            call = extract_call(source, variable)
            self.assertIn('quote=""', call.replace(" ", ""),
                          "%s no longer disables quoting" % variable)

    def test_the_tab_separator_is_explicit(self):
        """Both files are tab separated; R's default splits on whitespace.

        A display name with a space in it ("B5 #1" is a real symbol) parses as
        two columns under the default, which is the same class of failure.
        """
        source = read_source()
        for variable in (INPUT_CALL, REFERENCE_CALL):
            self.assertIn('sep="\\t"', extract_call(source, variable))


@unittest.skipUnless(RSCRIPT, "Rscript is not installed")
class ParsesUnderRTest(unittest.TestCase):
    """The shipped statements, run by R against a '#'-bearing fixture."""

    def test_the_matched_file_read_keeps_the_hash_in_the_symbol(self):
        directory, path = write_fixture(MATCHED_TXT, "gene_matched.txt")
        try:
            result, stderr = run_in_r(
                extract_call(read_source(), INPUT_CALL), path)
            self.assertIsNotNone(result, "read.table failed:\n%s" % stderr)
            rows, columns, symbol = result
            self.assertEqual((rows, columns), (2, 7),
                             "the '#' row was dropped or truncated")
            self.assertEqual(symbol, "ptt#2-1",
                             "the symbol was altered on the way in")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_without_the_argument_the_same_read_aborts(self):
        """Proves the fixture exercises the bug, so the test above is not vacuous.

        Note what is asserted: not that the '#' row is skipped, but that the
        entire call fails. That is why one gene symbol could take down a whole
        job.
        """
        broken = extract_call(read_source(), INPUT_CALL).replace(
            ', comment.char=""', "")
        self.assertNotIn('comment.char=""', broken.replace(" ", ""))

        directory, path = write_fixture(MATCHED_TXT, "gene_matched.txt")
        try:
            result, stderr = run_in_r(broken, path)
            self.assertIsNone(
                result,
                "read.table accepted the '#' row without comment.char='' -- "
                "the fixture no longer reproduces the crash")
            self.assertIn("did not have", stderr,
                          "failed for some other reason:\n%s" % stderr)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_the_reference_file_read_also_tolerates_a_hash(self):
        directory, path = write_fixture(GENE2PATHWAY_LIST, "gene2pathway.list")
        try:
            result, stderr = run_in_r(
                extract_call(read_source(), REFERENCE_CALL), path)
            self.assertIsNotNone(result, "read.table failed:\n%s" % stderr)
            rows, columns, pathway = result
            self.assertEqual((rows, columns), (2, 2))
            self.assertEqual(pathway, "path:sot#00020")
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
