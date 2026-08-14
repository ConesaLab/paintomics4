#!/usr/bin/env python3
"""The quote source must include Results and Discussion, not just the front.

Why this exists
---------------
`_collect_cited_quotes` extracts each citation's supporting quote from
`_quote_source_text(paper)`. That function used to cut the concatenated
sections at 12,000 characters from the top; sections arrive in document
order (introduction first), so abstract + introduction filled the window
and Results and Discussion were silently discarded. Measured across every
stored report: 13 "Cited from" labels, all of them "abstract" or
"full text (introduction)", zero "results", zero "discussion" -- on papers
whose Results had been fetched in full. The symptom users see ("the AI
never cites the results or discussion") is this truncation, not the
fetcher: the fetch fix of 2026-08-14 was live and working.

The contract pinned here: every non-empty section gets a share of the
budget, so a long introduction can no longer push Results and Discussion
past the cap.

Usage:
    cd PaintomicsServer
    PYTHONPATH=$PWD python src/tests/test_quote_source_covers_full_text.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.pipeline import _quote_source_text


def _paper(**sections):
    # kwargs order mirrors document order, which is how the PMC parser
    # builds the dict: abstract, introduction, results, discussion.
    return {"abstract": sections.get("abstract", ""), "sections": sections}


class QuoteSourceCoversFullText(unittest.TestCase):

    def test_results_and_discussion_survive_a_long_introduction(self):
        paper = _paper(
            abstract="ABSTRACT_SENTINEL " + "a" * 2000,
            introduction="INTRO_SENTINEL " + "i" * 12000,
            results="RESULTS_SENTINEL " + "r" * 12000,
            discussion="DISCUSSION_SENTINEL " + "d" * 8000,
        )
        src = _quote_source_text(paper)
        self.assertIn("ABSTRACT_SENTINEL", src)
        self.assertIn("RESULTS_SENTINEL", src)
        self.assertIn("DISCUSSION_SENTINEL", src)
        self.assertIn("INTRO_SENTINEL", src)

    def test_budget_is_respected(self):
        paper = _paper(
            abstract="a" * 3000,
            introduction="i" * 12000,
            results="r" * 12000,
            discussion="d" * 12000,
        )
        src = _quote_source_text(paper, max_chars=12000)
        # A few joining newlines over the budget is fine; a whole extra
        # section is not.
        self.assertLessEqual(len(src), 12000 + 10)

    def test_abstract_only_paper_falls_back_to_abstract(self):
        paper = {"abstract": "Only the abstract.", "sections": {}}
        self.assertEqual(_quote_source_text(paper), "Only the abstract.")

    def test_short_paper_is_taken_whole(self):
        paper = _paper(abstract="THE_ABSTRACT.", introduction="THE_INTRO.",
                       results="THE_RESULTS.", discussion="THE_DISCUSSION.")
        src = _quote_source_text(paper)
        for frag in ("THE_ABSTRACT.", "THE_INTRO.", "THE_RESULTS.",
                     "THE_DISCUSSION."):
            self.assertIn(frag, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
