#!/usr/bin/env python3
"""MORE must read PaintOmics' own `#gene` header as a header, not a comment.

The behaviour this guards
-------------------------
PaintOmics writes its values files with the identifier column headed `#gene`,
and twelve of the shipped example datasets do it -- as does every file a user
exports from PaintOmics. R's read.table defaults to `comment.char="#"`, so that
line was stripped before it could be used as a header. The first DATA row then
became the header, and its VALUES became the sample names.

Measured on a three-feature file headed `#gene<TAB>s1<TAB>s2<TAB>s3<TAB>s4`:

    R as shipped     nrow=2  samples "1.0,2.0,3.0,4.0"  features G2,G3 (G1 LOST)
    R with the fix   nrow=3  samples "s1,s2,s3,s4"      features G1,G2,G3
    the Rust port    nrow=3  samples "s1,s2,s3,s4"      features G1,G2,G3

So the two engines disagreed on the project's own documented format, and R was
the one that was wrong. A whole feature disappeared and the sample names became
numbers; downstream that surfaces as

    MORE ERROR: No common sample names across input files.

which sends the user to inspect a sample naming that has nothing wrong with it.
It escaped CI because 06-regulatory-more -- the only MORE fixture -- writes
plain `Sample` / `GeneID` / `RegulatorID` headers and never exercises the
convention.

Found while reproducing a user's failed MORE run whose regulator file was
headed `#gene`.

What this file asserts
----------------------
1. every read.table in runMORE.R passes comment.char="" -- source-level, so it
   holds on a machine with no R;
2. with R available, that a `#`-headed matrix round-trips with every feature
   and every sample name intact, and that the shipped call is what does it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_reads_a_hash_header
"""
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RUNMORE = os.path.join(REPO, "PaintomicsServer", "src", "common", "bioscripts", "runMORE.R")
DATASETS = os.path.join(REPO, "PaintomicsServer", "src", "examplefiles", "datasets")

# The header PaintOmics itself writes.
MATRIX = "#gene\ts1\ts2\ts3\ts4\nG1\t1.0\t2.0\t3.0\t4.0\nG2\t2.0\t1.0\t4.0\t3.0\nG3\t5.0\t6.0\t7.0\t8.0\n"


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


class MoreReadsAHashHeaderTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Comment lines dropped first: this file's own prose quotes
        # `read.table(sep="\t")` while explaining the separator logic, and a
        # scan that counted it would be arguing with the documentation.
        cls.source = "\n".join(line for line in read(RUNMORE).splitlines()
                               if not line.lstrip().startswith("#"))

    # -- source level, runs anywhere ---------------------------------------

    def test_every_reader_disables_the_comment_character(self):
        """`#` opens a HEADER in this project's format, never a comment."""
        calls = re.findall(r"read\.(?:table|delim|csv)\s*\(", self.source)
        self.assertTrue(calls, "no reader found in runMORE.R -- has it moved?")
        # Each call's argument list, up to the closing paren of that call.
        for match in re.finditer(r"read\.(?:table|delim|csv)\s*\(", self.source):
            depth, index = 0, match.end() - 1
            while index < len(self.source):
                if self.source[index] == "(":
                    depth += 1
                elif self.source[index] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            call = self.source[match.start():index + 1]
            self.assertIn('comment.char=""', call.replace(" ", ""),
                          "a reader would treat a `#gene` header as a comment:\n%s"
                          % call.strip())

    def test_the_convention_is_actually_used_by_the_shipped_data(self):
        """If this ever stops being true the guard above is arguing with nobody."""
        hashed = []
        for base, _dirs, files in os.walk(DATASETS):
            for name in files:
                if not name.endswith(".tab"):
                    continue
                path = os.path.join(base, name)
                with io.open(path, encoding="utf-8", errors="replace") as handle:
                    if handle.read(1) == "#":
                        hashed.append(os.path.relpath(path, DATASETS))
        self.assertGreater(len(hashed), 5,
                           "expected the `#` header convention in the shipped "
                           "datasets; found %d" % len(hashed))

    # -- behavioural, needs R ----------------------------------------------

    @unittest.skipIf(shutil.which("Rscript") is None, "Rscript is not installed")
    def test_a_hash_headed_matrix_keeps_every_feature_and_sample(self):
        directory = tempfile.mkdtemp(prefix="paintomics-hash-header-")
        try:
            path = os.path.join(directory, "values.tab")
            with io.open(path, "w", encoding="utf-8") as handle:
                handle.write(MATRIX)
            script = (
                'd <- read.table("%s", header=TRUE, sep="\\t", check.names=FALSE, '
                'quote="\\"", row.names=1, comment.char="");'
                'cat(nrow(d), "|", paste(colnames(d), collapse=","), "|", '
                'paste(rownames(d), collapse=","), sep="")' % path
            )
            done = subprocess.run(["Rscript", "--vanilla", "-e", script],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr)
            rows, samples, features = done.stdout.strip().split("|")
            self.assertEqual(rows, "3", "a feature was lost to the comment char")
            self.assertEqual(samples, "s1,s2,s3,s4",
                             "the sample names came from a data row")
            self.assertEqual(features, "G1,G2,G3")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    @unittest.skipIf(shutil.which("Rscript") is None, "Rscript is not installed")
    def test_the_default_really_does_lose_a_feature(self):
        """The bug itself, so this suite fails if R ever changes under us."""
        directory = tempfile.mkdtemp(prefix="paintomics-hash-header-")
        try:
            path = os.path.join(directory, "values.tab")
            with io.open(path, "w", encoding="utf-8") as handle:
                handle.write(MATRIX)
            script = (
                'd <- read.table("%s", header=TRUE, sep="\\t", check.names=FALSE, '
                'quote="\\"", row.names=1);'
                'cat(nrow(d), "|", paste(colnames(d), collapse=","), sep="")' % path
            )
            done = subprocess.run(["Rscript", "--vanilla", "-e", script],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr)
            rows, samples = done.stdout.strip().split("|")
            self.assertEqual(rows, "2")
            self.assertEqual(samples, "1.0,2.0,3.0,4.0",
                             "R's default no longer mangles this; the fix may "
                             "still be right, but this suite's premise changed")
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
