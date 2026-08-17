#!/usr/bin/env python3
"""Inline PMID mentions become [N] markers; a bibliography alone is not citing.

Why this exists
---------------
The first STATegra 5-omics run after the streaming transport landed (local
job n6e03200f1, 2026-08-17) finished in 8 minutes and reported
"0 of 56 retrieved papers cited". The synthesis draft had in fact cited 90
times -- as ``(PMID 42565800)``, ``PMIDs 42505068 and 42371798``,
``PMID 39112517 links CCL2 to ...`` -- and put its ``[N]`` markers only in a
References list it wrote itself. Every reader of citations in the pipeline
(quote collection, rendering, verification, renumbering) matches ``[N]`` in
the body, so all of that support was dropped and the final report carried no
references at all. Two things let it happen:

  * nothing turned a PMID the model *did* name into the marker the pipeline
    reads, although the mapping PMID -> ref_index is known exactly;
  * the citation top-up accepted its own rewrite because the count of "added"
    markers included the model's bibliography -- the gate before it had been
    fixed to count body markers only (PR #28), the acceptance after it had not.

The tests pin both: ``resolve_pmid_mentions`` rewrites the mention forms seen
live into markers (only for PMIDs that were retrieved), and
``count_body_citations`` ignores anything under a References heading.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_pmid_mentions_resolve_to_markers
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

PAPERS = {
    3: {"ref_index": 3, "pmid": "42565800"},
    7: {"ref_index": 7, "pmid": "42505068"},
    9: {"ref_index": 9, "pmid": "42371798"},
    12: {"ref_index": 12, "pmid": "39112517"},
}


class ResolvePmidMentionsTest(unittest.TestCase):

    def setUp(self):
        from src.classes.AIInterpret.verification import resolve_pmid_mentions
        self.resolve = resolve_pmid_mentions

    def test_parenthesised_pmid_becomes_a_marker(self):
        out = self.resolve("The STAT5A axis (PMID 42565800) provides a link.", PAPERS)
        self.assertEqual(out, "The STAT5A axis [3] provides a link.")

    def test_colon_form_and_pmid_list_forms(self):
        out = self.resolve("As shown (PMID: 42565800; PMID: 42505068).", PAPERS)
        self.assertEqual(out, "As shown [3], [7].")
        out = self.resolve("connecting to PMIDs 42505068 and 42371798.", PAPERS)
        self.assertEqual(out, "connecting to [7], [9].")

    def test_a_bracket_that_is_not_the_mentions_own_survives(self):
        out = self.resolve("Reported before (see PMID 42565800).", PAPERS)
        self.assertEqual(out, "Reported before (see [3]).")

    def test_sentence_initial_mention_keeps_the_sentence(self):
        out = self.resolve("PMID 39112517 links CCL2 to IKZF1 expression.", PAPERS)
        self.assertEqual(out, "[12] links CCL2 to IKZF1 expression.")

    def test_unretrieved_pmids_are_left_alone(self):
        text = "Elsewhere (PMID 11111111) this was disputed."
        self.assertEqual(self.resolve(text, PAPERS), text)
        # A mixed group keeps the unknown one as text and converts the known.
        out = self.resolve("(PMIDs 42565800 and 11111111)", PAPERS)
        self.assertIn("[3]", out)
        self.assertIn("11111111", out)

    def test_existing_markers_and_prose_are_untouched(self):
        text = "Ccl2 falls to -5.24 [3]; see Table 2 and p=1.7e-08 in 2024."
        self.assertEqual(self.resolve(text, PAPERS), text)

    def test_the_models_own_references_section_is_not_rewritten(self):
        # It is discarded by render_references_section anyway; rewriting it
        # would only manufacture body-looking markers below the heading.
        text = ("Body cites (PMID 42565800).\n\n### References\n\n"
                "[3] Some title. PMID 42565800\n")
        out = self.resolve(text, PAPERS)
        self.assertTrue(out.startswith("Body cites [3]."))
        self.assertIn("[3] Some title. PMID 42565800", out)

    def test_idempotent(self):
        once = self.resolve("(PMID 42565800) and (PMID 42505068)", PAPERS)
        self.assertEqual(self.resolve(once, PAPERS), once)


class BodyCitationCountTest(unittest.TestCase):

    def test_bibliography_only_counts_as_zero(self):
        from src.classes.AIInterpret.verification import count_body_citations
        report = ("## Findings\n\nNo markers here.\n\n### References\n\n"
                  "[3] A. [7] B. [9] C.\n")
        self.assertEqual(count_body_citations(report, set(PAPERS)), set())

    def test_body_markers_are_counted_and_unknown_ones_are_not(self):
        from src.classes.AIInterpret.verification import count_body_citations
        report = "Claim [3], claim [7], invented [99].\n\n### References\n\n[9] C."
        self.assertEqual(count_body_citations(report, set(PAPERS)), {3, 7})


if __name__ == "__main__":
    unittest.main(verbosity=2)
