#!/usr/bin/env python3
"""The red-star contract between MORE's output files and relevance lookup.

MORE's "relevant regulators" file and its values file have to agree on a key,
and they are produced by different code in different languages:

  * runMORE.R writes the values file with a first column of
    GENE:::REGULATOR.
  * MOREServlet.fromMOREtoGenes_STEP2 writes MORE_relevant_reg_<omic>_<date>.tab
    as a single column of those same GENE:::REGULATOR strings, selected by
    whether the user flagged that regulator.
  * Job.parseSignificativeFeaturesFile loads that file into a dict, and
    Job.parseGeneBasedFiles looks each values row up with
    relevantFeatures.get(line[0].lower()).

If the two ever disagree on shape or case, nothing raises. Relevance lookups
simply all miss, every red star silently disappears, and the omic's pathway
enrichment shifts because significance is what enrichment counts. That is the
failure this file is here to catch.

Also pins the deliberately-empty case. When the user supplies no
relevant-regulators file, STEP2 writes an EMPTY relevance file rather than
skipping it, matching miRNA2Genes: red stars are user-driven, and an omic with
no user file must contribute no significant features.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_relevance_contract
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Job import Job


class MoreRelevanceContractTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="morerel_")
        self.job = Job("J1", "u1", self.tmp + os.sep)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def writeFile(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path

    def parse(self, name, text, **kwargs):
        return self.job.parseSignificativeFeaturesFile(
            self.writeFile(name, text), **kwargs)

    # -- the shape STEP2 actually writes ---------------------------------
    def test_a_single_column_of_joined_pairs_keeps_the_join(self):
        """STEP2 writes already-joined GENE:::REGULATOR, one per line."""
        result = self.parse("rel.tab", "GENEA:::STAT3\nGENEB:::NFKB1\n")
        self.assertIn("genea:::stat3", result)
        self.assertIn("geneb:::nfkb1", result)

    def test_keys_are_lowercased_to_match_the_lookup(self):
        """parseGeneBasedFiles looks up with line[0].lower(); a case-sensitive
        key here would miss every row."""
        result = self.parse("rel.tab", "GeneA:::Stat3\n")
        self.assertIn("genea:::stat3", result)
        self.assertNotIn("GeneA:::Stat3", result)

    def test_the_values_first_column_finds_its_relevance_entry(self):
        """The whole contract, stated as one assertion: the key STEP2 writes is
        the key parseGeneBasedFiles will ask for."""
        valuesFirstColumn = "GENEA:::STAT3"          # runMORE.R writes this
        result = self.parse("rel.tab", valuesFirstColumn + "\n")
        self.assertTrue(result.get(valuesFirstColumn.lower()),
                        "relevance lookup would miss this row")

    def test_relevance_values_are_truthy_for_isRelevant(self):
        result = self.parse("rel.tab", "GENEA:::STAT3\n")
        self.assertTrue(result["genea:::stat3"])

    def test_an_unflagged_regulator_is_simply_absent(self):
        result = self.parse("rel.tab", "GENEA:::STAT3\n")
        self.assertNotIn("geneb:::nfkb1", result)

    # -- the deliberately empty file -------------------------------------
    def test_an_empty_relevance_file_yields_no_relevant_features(self):
        """Red stars are user-driven. STEP2 writes this file empty when the
        user supplied no relevant-regulators list; anything non-empty here
        would paint stars MORE never justified and shift enrichment."""
        self.assertEqual(self.parse("rel.tab", ""), {})

    def test_a_file_of_blank_lines_yields_nothing(self):
        """Trailing newlines are ordinary in hand-edited and Windows files."""
        self.assertEqual(self.parse("rel.tab", "\n\n\n"), {})

    def test_a_missing_file_yields_nothing_rather_than_raising(self):
        result = self.job.parseSignificativeFeaturesFile(
            os.path.join(self.tmp, "does_not_exist.tab"))
        self.assertEqual(result, {})

    # -- the relevant-associations slot ----------------------------------
    # Job.py:353 parses this one with forceLegacyTwoCol=True, and MORE fills it
    # with MORE_relevant_pairs_<omic>_<date>.tab. runMORE.R writes that file
    # single-column and already joined (col.names=FALSE, no header).
    def test_mores_relevant_pairs_file_survives_the_forced_two_column_path(self):
        """The exact bytes runMORE.R emits, through the exact call Job.py makes."""
        result = self.parse("pairs.tab", "CXCL8:::ATF4\nCXCL8:::CREB1\nCCL2:::CREB1\n",
                            forceLegacyTwoCol=True)
        self.assertEqual(sorted(result),
                         ["ccl2:::creb1", "cxcl8:::atf4", "cxcl8:::creb1"])

    def test_the_first_pair_is_not_mistaken_for_a_header(self):
        """Row 1 is only kept when _row_looks_like_data says so, which needs a
        colon or a 4+ digit run. The ':::' join supplies the colon -- that is
        the whole reason MORE's first pair survives."""
        result = self.parse("pairs.tab", "CXCL8:::ATF4\n", forceLegacyTwoCol=True)
        self.assertIn("cxcl8:::atf4", result)

    def test_two_column_ids_with_digits_are_joined(self):
        """The other shape this slot sees: [TARGET, REGULATOR] with real IDs."""
        result = self.parse("assoc.tab",
                            "ENSMUSG00000038127\tmmu-mir-3091-3p\n"
                            "ENSMUSG00000028180\tmmu-mir-466k\n",
                            forceLegacyTwoCol=True)
        self.assertIn("ensmusg00000038127:::mmu-mir-3091-3p", result)
        self.assertIn("ensmusg00000028180:::mmu-mir-466k", result)

    def test_a_descriptor_header_is_skipped(self):
        result = self.parse("assoc.tab",
                            "Target\tRegulator\nENSMUSG00000038127\tmmu-mir-3091-3p\n",
                            forceLegacyTwoCol=True)
        self.assertEqual(sorted(result), ["ensmusg00000038127:::mmu-mir-3091-3p"])

    def test_rows_with_no_target_are_skipped(self):
        result = self.parse("assoc.tab",
                            "ENSMUSG00000038127\tmmu-mir-3091-3p\n\tmmu-mir-466k\n",
                            forceLegacyTwoCol=True)
        self.assertEqual(sorted(result), ["ensmusg00000038127:::mmu-mir-3091-3p"])

    def test_comma_separated_association_file(self):
        """detect_delimiter picks the separator; users hand-edit these."""
        result = self.parse("assoc.csv",
                            "ENSMUSG00000038127,mmu-mir-3091-3p\n",
                            forceLegacyTwoCol=True)
        self.assertIn("ensmusg00000038127:::mmu-mir-3091-3p", result)

    def test_a_headerless_symbol_only_file_loses_its_first_row(self):
        """Documents a real limitation, so it is discovered here and not in a
        user's results.

        _row_looks_like_data calls a row data only if some cell holds a colon
        or 4+ consecutive digits. Bare gene symbols (TNF, STAT3, NFKB1) hold
        neither, so a headerless two-column symbol file has its first pair
        eaten as a header. MORE itself is unaffected -- its pairs file is
        ':::'-joined -- but a hand-written association file for a
        symbol-annotated organism would silently lose one association.

        If this ever starts passing, the heuristic was improved: delete the
        test rather than restoring it.
        """
        result = self.parse("symbols.tab", "TNF\tSTAT3\nIL6\tNFKB1\n",
                            forceLegacyTwoCol=True)
        self.assertNotIn("tnf:::stat3", result)
        self.assertIn("il6:::nfkb1", result)

    # -- shapes that must not be mangled ---------------------------------
    def test_a_regulator_id_containing_a_hyphen_survives(self):
        """miRNA-style ids are the common case for regulator names."""
        result = self.parse("rel.tab", "GENEA:::mmu-miR-155-5p\n")
        self.assertIn("genea:::mmu-mir-155-5p", result)

    def test_duplicate_pairs_collapse_rather_than_duplicating(self):
        result = self.parse("rel.tab", "GENEA:::STAT3\nGENEA:::STAT3\n")
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
