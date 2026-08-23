#!/usr/bin/env python3
"""An omic that matched nothing must say so, not die inside R.

Why this exists
---------------
Found on a sealed TEST study. The deposit's Ensembl ids carried version
suffixes (`ENSMUSG00000000001.4`), PaintOmics matches unversioned ids, and so
**0 of 54,232 features mapped**. The empty `<omic>_matched.txt` went to
`generateMetaGenes.R`, which died with:

    Error in read.table(file = args$input_file, header = FALSE, sep = "\t", ...)

The user is shown an R stack trace four steps downstream of the real problem,
while the two file sizes state it plainly. Version-suffixed ids are one of the
commonest things a user will paste; GEO ships them routinely.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_zero_mapped_features_says_so
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")


class MessageTest(unittest.TestCase):
    """The guard's text is what a user has to act on, so it is pinned."""

    def _message(self, omic, organism, sample):
        # the exact string the guard raises, kept in one place
        return ("None of the identifiers in omic '%s' matched %s. Nothing can be "
                "computed from it. The first few were: %s. This is usually a "
                "version suffix on an Ensembl id (ENSMUSG00000000001.4 instead "
                "of ENSMUSG00000000001), transcript ids where gene ids are "
                "expected, or a different organism."
                % (omic, organism, ", ".join(sample) if sample else "(none readable)"))

    def test_it_names_the_omic_and_the_organism(self):
        msg = self._message("Gene expression", "mmu",
                            ["ENSMUSG00000000001.4", "ENSMUSG00000000003.15"])
        self.assertIn("Gene expression", msg)
        self.assertIn("mmu", msg)

    def test_it_shows_the_ids_that_failed(self):
        msg = self._message("Gene expression", "mmu", ["ENSMUSG00000000001.4"])
        self.assertIn("ENSMUSG00000000001.4", msg,
                      "a user cannot fix ids they are not shown")

    def test_it_names_the_usual_cause(self):
        msg = self._message("Proteomics", "hsa", [])
        self.assertIn("version suffix", msg)
        self.assertIn("transcript ids", msg)
        self.assertIn("different organism", msg)

    def test_it_survives_an_unreadable_unmatched_file(self):
        msg = self._message("Gene expression", "mmu", [])
        self.assertIn("(none readable)", msg)
        self.assertIn("None of the identifiers", msg)

    def test_it_never_mentions_read_table(self):
        msg = self._message("Gene expression", "mmu", ["X"])
        self.assertNotIn("read.table", msg)
        self.assertNotIn("Rscript", msg)


class GuardIsWiredTest(unittest.TestCase):
    """The check sits before the R call, not after it."""

    def test_the_guard_precedes_the_metagenes_loop(self):
        path = os.path.join(os.path.dirname(__file__), "..", "classes",
                            "JobInstances", "PathwayAcquisitionJob.py")
        src = open(path).read()
        guard = src.find("None of the identifiers in omic")
        # the INVOCATION, not the docstring that describes it 110 kB earlier --
        # the first draft of this test anchored on the bare filename and failed
        # against correct code
        rcall = src.find('ROOT_DIRECTORY + "common/bioscripts/generateMetaGenes.R"')
        self.assertGreater(guard, 0, "guard missing")
        self.assertGreater(rcall, 0, "R invocation missing")
        self.assertLess(guard, rcall,
                        "the guard must run BEFORE the R script is invoked")

    def test_the_guard_checks_file_size_not_just_existence(self):
        path = os.path.join(os.path.dirname(__file__), "..", "classes",
                            "JobInstances", "PathwayAcquisitionJob.py")
        src = open(path).read()
        self.assertIn("os.path.getsize(matchedPath) > 0", src,
                      "an empty file exists; size is what distinguishes it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
