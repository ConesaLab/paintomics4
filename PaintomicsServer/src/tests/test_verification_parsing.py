#!/usr/bin/env python3
"""Tests for parse_references_section, the gate on all citation checking.

This function decides whether any citation is verified at all. pipeline.py's
verification loop breaks immediately when it returns nothing, and
verify_report_v2's fuzzy grounding pass iterates over its output -- so an empty
result silently disables both, while still reporting failed_citations = 0, which
reads as "everything verified".

It used to require the literal heading "### References". Real reports are
written with "## References", so on the deployed server it returned [] for every
report and no quoted passage was ever checked against its paper. Verified
against the stored report for job fcs152VG4Z: 0 citations before, 13 after.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_verification_parsing
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.verification import parse_references_section

BODY = (
    "## Key Findings\n\n"
    "Hypoxia activates protective autophagy in this dataset [8].\n"
    "BCL2 and BAX act as regulators of apoptosis [2].\n\n"
)

ENTRIES = (
    '[8] Wang, X. et al. "Hypoxia-induced inflammation and protective autophagy." '
    'Archives of oral biology, 2026. PMID: 42314241\n'
    '    **Cited Text:** "Meanwhile, hypoxia activated autophagic flux."\n\n'
    '[2] Smith, J. et al. "Apoptosis in cancer progression." Cell, 2024. PMID: 111\n'
    '    **Cited Text:** "Apoptosis is a critical regulatory mechanism."\n'
)


def report_with(heading):
    return BODY + heading + "\n\n" + ENTRIES


class HeadingToleranceTest(unittest.TestCase):
    """Heading level, bold, colon and case all vary between generations."""

    def test_h2_the_format_real_reports_use(self):
        self.assertEqual(len(parse_references_section(report_with("## References"))), 2)

    def test_h3_the_format_originally_required(self):
        self.assertEqual(len(parse_references_section(report_with("### References"))), 2)

    def test_h1(self):
        self.assertEqual(len(parse_references_section(report_with("# References"))), 2)

    def test_h4(self):
        self.assertEqual(len(parse_references_section(report_with("#### References"))), 2)

    def test_bold_without_a_hash(self):
        self.assertEqual(len(parse_references_section(report_with("**References**"))), 2)

    def test_trailing_colon(self):
        self.assertEqual(len(parse_references_section(report_with("## References:"))), 2)

    def test_lowercase(self):
        self.assertEqual(len(parse_references_section(report_with("## references"))), 2)

    def test_plain_line_without_markup(self):
        self.assertEqual(len(parse_references_section(report_with("References"))), 2)


class ExtractionTest(unittest.TestCase):

    def setUp(self):
        self.entries = parse_references_section(report_with("## References"))
        self.byIndex = {e["ref_index"]: e for e in self.entries}

    def test_reference_indices(self):
        self.assertEqual(sorted(self.byIndex), [2, 8])

    def test_cited_text_is_extracted(self):
        self.assertEqual(self.byIndex[8]["cited_text"],
                         "Meanwhile, hypoxia activated autophagic flux.")

    def test_claim_sentence_comes_from_the_body(self):
        self.assertIn("Hypoxia activates protective autophagy",
                      self.byIndex[8]["claim_sentence"])

    def test_title_is_extracted(self):
        self.assertIn("Hypoxia-induced inflammation", self.byIndex[8]["title"])

    def test_references_inside_the_body_are_not_treated_as_entries(self):
        # Only the section after the heading supplies entries; [8] and [2]
        # appearing in prose above must not create their own.
        self.assertEqual(len(self.entries), 2)


class NoSectionTest(unittest.TestCase):

    def test_report_without_references_yields_nothing(self):
        self.assertEqual(parse_references_section("## Findings\n\nSome text.\n"), [])

    def test_empty_report(self):
        self.assertEqual(parse_references_section(""), [])

    def test_word_references_in_prose_is_not_a_heading(self):
        # A sentence mentioning references mid-paragraph must not open a
        # section -- the pattern is anchored to a whole line.
        text = "## Findings\n\nWe compared this against references from prior work.\n"
        self.assertEqual(parse_references_section(text), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
