"""The Results rewrite may reshape the prose. It may not cost a citation.

The rewrite runs on a report whose citations have been EARNED: each [N] was
checked against the paper it points at. A rewrite that drops one loses a
verified fact, and a rewrite that adds one points at a paper this text was
never verified against.

This document's two most expensive lessons are both this failure: sentence
repair was killed for -33% citations and the top-up deadline for -21%, each
having looked reasonable in every other respect. So the rule is a GUARD that
rejects the candidate, not a line in a prompt.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(SERVER, "src", "classes", "AIInterpret", "agent_loop.py")


def _markers(text):
    """Body markers only -- the reference list repeats every one of them.

    Counting the whole document lets a rewrite drop an inline citation while
    its reference entry survives, and the guard would see no change. That is
    marker-stripping, the exact behaviour that makes "failed citations" read
    0.0 on a report whose prose lost its support.
    """
    return set(re.findall(r"\[(\d+)\]", str(text).split("### References")[0]))


def _verdict(before_text, after_text, has_refs=True):
    """The guard's logic, mirrored exactly from _write_results_section."""
    before, after = _markers(before_text), _markers(after_text)
    reasons = []
    if before - after:
        reasons.append("lost_%d" % len(before - after))
    if after - before:
        reasons.append("invented_%d" % len(after - before))
    if has_refs and "### References" not in after_text:
        reasons.append("no_references")
    if len(after_text) < 0.2 * len(before_text):
        reasons.append("truncated")
    return reasons


REPORT = ("Ikaros drives differentiation [1]. Accessibility rises [2]. "
          "DYNLL1 is sustained [3].\n\n### References\n[1] a\n[2] b\n[3] c\n") * 6


class ResultsSectionKeepsItsCitations(unittest.TestCase):

    def setUp(self):
        with open(SRC) as fh:
            self.src = fh.read()

    # ---- the guard itself -------------------------------------------------

    def test_a_rewrite_that_keeps_every_marker_is_accepted(self):
        good = REPORT.replace("Ikaros drives differentiation [1].",
                              "Ikaros induction drove differentiation [1].")
        self.assertEqual(_verdict(REPORT, good), [])

    def test_a_rewrite_that_drops_a_marker_is_rejected(self):
        bad = REPORT.replace(" [2]", "")
        self.assertIn("lost_1", _verdict(REPORT, bad),
                      "a dropped marker loses a verified fact")

    def test_a_rewrite_that_invents_a_marker_is_rejected(self):
        bad = REPORT.replace("DYNLL1 is sustained [3].",
                             "DYNLL1 is sustained [3][9].")
        self.assertIn("invented_1", _verdict(REPORT, bad),
                      "a new marker points at a paper never verified here")

    def test_a_rewrite_that_drops_the_references_is_rejected(self):
        bad = REPORT.replace("### References", "## Bibliography")
        self.assertIn("no_references", _verdict(REPORT, bad))

    def test_a_rewrite_that_truncates_is_rejected(self):
        self.assertIn("truncated",
                      _verdict(REPORT, "Ikaros drives differentiation [1]."))

    def test_shortening_is_allowed_when_the_citations_survive(self):
        """The whole point is a shorter document -- 8184 words is the problem."""
        short = ("Ikaros drove differentiation [1], with accessibility rising "
                 "ahead of transcription [2] and DYNLL1 sustained throughout "
                 "[3].\n\n### References\n[1] a\n[2] b\n[3] c\n") * 3
        self.assertLess(len(short), len(REPORT))
        self.assertEqual(_verdict(REPORT, short), [],
                         "a shorter rewrite that keeps every marker must pass")

    # ---- the wiring -------------------------------------------------------

    def test_the_guard_is_in_the_source_not_only_in_the_prompt(self):
        # Not a fixed window: the function grew when the retry was added and a
        # 4000-char slice stopped short of the guard it is checking. Take the
        # whole function instead, bounded by the next top-level def.
        block = self.src.split("async def _write_results_section")[1]
        block = block.split("\nasync def ")[0].split("\ndef ")[0]
        self.assertIn('re.findall(', block,
                      "the marker set must be computed, not asked for")
        self.assertIn('split("### References")', block,
                      "the guard must compare BODY markers; the reference list "
                      "repeats every marker and would mask a dropped citation")
        self.assertIn('stats["results_rejected"]', block)
        self.assertIn("return report, False", block,
                      "a rejected rewrite must return the ORIGINAL report")

    def test_it_runs_before_the_exit_gate(self):
        """Order is the safety property.

        After the gate, a rewrite could move a verified marker onto a claim
        nobody checked -- reintroducing exactly the overshoot the gate removes.
        """
        call = self.src.index("_write_results_section(\n")
        gate = self.src.index("# ---- The mandatory exit gate")
        self.assertLess(call, gate,
                        "the Results rewrite must precede the exit gate")

    def test_the_cluster_table_is_suppressed_when_a_section_was_written(self):
        """It was asked for as prose; a table restating it undoes that."""
        block = self.src.split("The deterministic tables ride below")[1][:1200]
        self.assertIn("if not results_written:", block)

    def test_the_pathway_table_survives(self):
        """It is data the job already holds, not a model assertion."""
        block = self.src.split("The deterministic tables ride below")[1][:1200]
        self.assertIn("render_pathway_table(pathways)", block)

    def test_the_rewrite_is_renumbered_afterwards(self):
        """Reorganising prose scrambles first-appearance order.

        The dossier arrives numbered [1,2,3...] because it was written in that
        order. A Results section reorders the material by finding, so the same
        markers now appear as [9,5,6,14,13,...] -- measured exactly that on the
        first live rewrite. No journal accepts that; citations must be numbered
        in order of first appearance.

        The writer must NOT renumber itself: its markers still have to map to
        the papers they were verified against. `renumber_citations` does the
        remap across body AND references and returns the mapping the paper list
        is then filtered by. So the ordering property depends entirely on the
        writer running BEFORE it -- which is incidental unless pinned here.
        """
        writer = self.src.index("_write_results_section(\n")
        renumber = self.src.index("report, citation_mapping = renumber_citations(report)")
        self.assertLess(writer, renumber,
                        "the Results rewrite must run BEFORE renumber_citations, "
                        "or its citations ship out of first-appearance order")
        sort_refs = self.src.index("report = sort_references_section(report)")
        self.assertLess(renumber, sort_refs,
                        "references are sorted after the remap, not before")

    def test_the_writer_is_told_not_to_renumber(self):
        """The downstream remap owns numbering, and needs the ORIGINAL indices.

        renumber_citations returns a mapping the paper list is filtered by. If
        the model renumbered first, its markers would no longer identify the
        papers they were verified against.
        """
        # Whitespace-normalised: the instruction wraps as "do not\n  renumber",
        # so a literal search finds nothing and the test fails on correct text.
        prompt = " ".join(self.src.split("RESULTS_PROMPT")[1][:3000].lower().split())
        self.assertIn("do not renumber", prompt,
                      "the model must be told not to renumber; the pipeline "
                      "does it afterwards and owns the mapping")

    def test_it_is_off_by_default(self):
        self.assertIn('os.getenv("AI_AGENT_RESULTS_SECTION", "0")', self.src,
                      "a new writing stage ships off until it is measured")


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(ResultsSectionKeepsItsCitations))
    sys.exit(0 if r.wasSuccessful() else 1)
