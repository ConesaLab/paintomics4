#!/usr/bin/env python3
"""gene_accuracy must count gene claims, not shouty tokens.

Why this exists
---------------
Measured over 32 stored blind runs, `gene_accuracy` sat at 0.35 and never
moved, and it was treated as the product's worst number. It was not
measuring the product. In frequency order, the tokens it counted as failed
gene claims were:

    C01..C31   the report's OWN cluster labels, in all 32 runs
    NF, AP     the head of a hyphenated name (NF-kB, AP-1)
    MMU        the organism code
    II         a roman numeral
    GTPases    a plural family word

Read the convention the reports actually use -- gene symbols in italics --
and the same 32 runs give 909 of 934 present in the job's own data (0.973).

So the number was an artefact of the extractor. Two things follow, and this
file pins both: read the marked mentions when the report marks them, and
when it does not, say the number is not a measurement rather than letting a
fabricated 0.35 look like a real one -- the lesson `quotations_unverifiable`
already taught in this same module.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_gene_accuracy_measures_gene_claims
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.verification import (  # noqa: E402
    _italic_gene_mentions, gene_mentions, MIN_ITALIC_GENE_MENTIONS,
)

GENES = ["Fos", "Egr1", "Junb", "Ikzf1", "Rpl18", "Ahsg", "Krt4", "Krt13",
         "Loricrin", "Cyp2e1", "Gyg1", "Trp53"]
MARKED = " ".join("*%s* rose." % g for g in GENES)


class ItalicConventionTest(unittest.TestCase):

    def test_marked_symbols_are_read(self):
        self.assertEqual(_italic_gene_mentions(MARKED), GENES)

    def test_a_list_inside_one_span_is_split(self):
        self.assertEqual(_italic_gene_mentions("*Fos, Egr1 and Junb*"),
                         ["Fos", "Egr1", "Junb"])
        self.assertEqual(_italic_gene_mentions("*Krt4/Krt13*"),
                         ["Krt4", "Krt13"])

    def test_emphasis_is_not_a_gene(self):
        # A symbol is never all-lowercase in mouse or human nomenclature.
        for word in ("*entirely*", "*down*", "*increased*", "*not*", "*b*"):
            self.assertEqual(_italic_gene_mentions(word), [], word)

    def test_bold_is_not_italic(self):
        self.assertEqual(_italic_gene_mentions("**Results**"), [])

    def test_prose_inside_the_span_is_not_a_symbol(self):
        self.assertEqual(_italic_gene_mentions("*the whole programme shifts*"), [])


class WhichSourceTest(unittest.TestCase):

    def test_a_report_using_the_convention_is_measured(self):
        mentions, source = gene_mentions(MARKED)
        self.assertEqual(source, "italic")
        self.assertGreaterEqual(len(mentions), MIN_ITALIC_GENE_MENTIONS)

    def test_a_report_without_the_convention_falls_back_and_says_so(self):
        _m, source = gene_mentions("TLR9 signalling rose in the KO.")
        self.assertEqual(source, "heuristic")

    def test_a_couple_of_italics_do_not_count_as_the_convention(self):
        _m, source = gene_mentions("*Fos* rose while *Egr1* fell.")
        self.assertEqual(source, "heuristic", "two symbols is emphasis, not a convention")


class TheThingsItUsedToMiscountTest(unittest.TestCase):
    """Each of these appeared in the stored runs and is not a gene claim."""

    def _rough(self, text):
        mentions, source = gene_mentions(text)
        self.assertEqual(source, "heuristic")
        return mentions

    def test_cluster_labels_are_not_genes(self):
        got = self._rough("Clusters C01 to C08 and C31 were profiled.")
        for label in ("C01", "C08", "C31"):
            self.assertNotIn(label, got, label)

    def test_a_plural_family_word_is_not_a_gene(self):
        got = self._rough("The GTPases and TNFs respond.")
        self.assertNotIn("GTPases", got)
        self.assertNotIn("TNFs", got)

    def test_a_roman_numeral_is_not_a_gene(self):
        self.assertNotIn("II", self._rough("Complex II activity fell."))

    def test_a_real_symbol_still_survives_the_fallback(self):
        self.assertIn("TP53", self._rough("TP53 signalling rose."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
