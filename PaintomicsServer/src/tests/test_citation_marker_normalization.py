#!/usr/bin/env python3
"""Multi-citation markers must be visible to every citation reader.

The model writes "[17, 18]" however firmly the prompt asks for single
markers, and every reader in verification.py matches "[N]" alone. An unsplit
multi-marker was therefore invisible to all of them at once:
render_references_section dropped refs 17 and 18 from the References section
("not cited"), redaction could not remove the sentence, renumbering skipped
the marker -- and the shipped report ended with a body citation pointing at
entries that were not there. Seen on a real report: "...coupling [17, 18]."
with no [17] or [18] in its References.

normalize_citation_markers splits those markers, and is applied inside every
reader so no call site can forget it. These tests pin the splitting rules and
the end-to-end behaviour through render/verify/redact/renumber.

Also pinned here: each rendered reference names what its quote was found in
("abstract" or a full-text section), which is the reader-facing half of the
full-text pipeline.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_citation_marker_normalization
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.verification import (
    normalize_citation_markers, render_references_section,
    parse_references_section, redact_unverified_v2, renumber_citations,
)


class SplitRulesTest(unittest.TestCase):

    def test_comma_list_is_split(self):
        self.assertEqual(normalize_citation_markers("coupling [17, 18]."),
                         "coupling [17], [18].")

    def test_semicolon_and_tight_lists_split_too(self):
        self.assertEqual(normalize_citation_markers("x [3;4] y [5,6,7]"),
                         "x [3], [4] y [5], [6], [7]")

    def test_a_range_is_expanded(self):
        self.assertEqual(normalize_citation_markers("shown [17-19]."),
                         "shown [17], [18], [19].")

    def test_a_span_of_years_is_not_a_citation(self):
        text = "between [2010-2015] the cohort grew"
        self.assertEqual(normalize_citation_markers(text), text)

    def test_inverted_and_implausibly_wide_ranges_are_left_alone(self):
        for text in ("[9-2]", "[1-40]"):
            self.assertEqual(normalize_citation_markers(text), text)

    def test_single_markers_and_idempotency(self):
        text = "as reported [17], later [18]."
        once = normalize_citation_markers(text)
        self.assertEqual(once, text)
        self.assertEqual(normalize_citation_markers(once), once)

    def test_a_markdown_link_is_not_split(self):
        text = "see [3, 4](https://example.org/figure)"
        self.assertEqual(normalize_citation_markers(text), text)


def _paper(idx, abstract="", results=""):
    sections = {}
    if abstract:
        sections["abstract"] = abstract
    if results:
        sections["results"] = results
    return {
        "ref_index": idx,
        "pmid": str(30000000 + idx),
        "title": "Paper %d" % idx,
        "first_author": "Author%d" % idx,
        "journal": "J Test",
        "year": "2024",
        "abstract": abstract,
        "sections": sections,
        "full_text_available": bool(results),
    }


class RenderKeepsMultiCitedEntriesTest(unittest.TestCase):
    """The exact shipped symptom: [17, 18] in the body, nothing in References."""

    def test_both_references_of_a_multi_marker_are_rendered(self):
        body = "PPP flux rises with G6pd coupling [17, 18].\n"
        papers = {17: _paper(17, abstract="G6pd drives PPP flux."),
                  18: _paper(18, abstract="Coupling of PPP enzymes rises.")}
        quotes = {17: "G6pd drives PPP flux.",
                  18: "Coupling of PPP enzymes rises."}
        report, rendered = render_references_section(body, papers, quotes)
        self.assertEqual(rendered, [17, 18])
        self.assertIn("[17] Author17", report)
        self.assertIn("[18] Author18", report)
        # And the body marker is now two markers the client can linkify.
        self.assertIn("coupling [17], [18].", report)

    def test_redaction_removes_a_multi_cited_sentence(self):
        body = ("A first claim [1]. A second claim [2, 3].\n\n"
                "### References\n\n"
                "[1] A \"P1.\" J, 2024. PMID: 1\n"
                "[2] B \"P2.\" J, 2024. PMID: 2\n"
                "[3] C \"P3.\" J, 2024. PMID: 3\n")
        cleaned, removed = redact_unverified_v2(
            body, [{"ref_index": 3, "reason": "no support",
                    "cited_text": "", "claim_sentence": ""}])
        self.assertNotIn("[3]", cleaned.split("### References")[0])
        self.assertIn("A first claim [1].", cleaned)
        self.assertGreater(removed, 0)

    def test_renumbering_sees_split_markers(self):
        text = "One [7]. Two [9, 11]."
        renumbered, mapping = renumber_citations(text)
        self.assertEqual(renumbered, "One [1]. Two [2], [3].")
        self.assertEqual(mapping, {7: 1, 9: 2, 11: 3})


class QuoteProvenanceTest(unittest.TestCase):

    def _entry_for(self, report, idx):
        block = [line for line in report.split("\n")
                 if line.strip().startswith("*Cited from:")]
        return "\n".join(block)

    def test_a_quote_found_in_the_abstract_is_labelled_abstract(self):
        body = "A claim [1]."
        papers = {1: _paper(1, abstract="The abstract states the finding.")}
        report, _ = render_references_section(
            body, papers, {1: "The abstract states the finding."})
        self.assertIn("*Cited from: abstract*", report)

    def test_a_quote_found_in_results_is_labelled_full_text(self):
        body = "A claim [1]."
        papers = {1: _paper(1, abstract="Short summary.",
                            results="The results section carries the exact supporting sentence.")}
        report, _ = render_references_section(
            body, papers,
            {1: "The results section carries the exact supporting sentence."})
        self.assertIn("*Cited from: full text (results)*", report)

    def test_the_label_does_not_break_reference_parsing(self):
        body = "A claim [1]."
        papers = {1: _paper(1, abstract="The abstract states the finding.")}
        report, _ = render_references_section(
            body, papers, {1: "The abstract states the finding."})
        parsed = parse_references_section(report)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["cited_text"],
                         "The abstract states the finding.")

    def test_redaction_also_removes_the_label_line(self):
        body = "A claim [1]. Another [2]."
        papers = {1: _paper(1, abstract="Alpha finding."),
                  2: _paper(2, abstract="Beta finding.")}
        report, _ = render_references_section(
            body, papers, {1: "Alpha finding.", 2: "Beta finding."})
        cleaned, _ = redact_unverified_v2(
            report, [{"ref_index": 2, "reason": "x",
                      "cited_text": "", "claim_sentence": ""}])
        refs = cleaned.split("### References")[1]
        self.assertNotIn("Beta finding", refs)
        self.assertEqual(refs.count("*Cited from:"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
