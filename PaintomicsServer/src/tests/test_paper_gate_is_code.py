#!/usr/bin/env python3
"""The paper's gate is code: what the Lead may not do, it cannot do.

Why this exists
---------------
A stage that grades itself passes by changing nothing -- measured. So the
gate is deterministic and these tests drive it with a Lead stub that commits
every sin at once: writes a bare number, cites a paper that is not on the
shelf, uses a ledger token that does not exist, and forgets a figure. Each
sin has exactly one deterministic consequence, asserted here.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_paper_gate_is_code
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import paper_agent as P          # noqa: E402
from src.classes.AIInterpret.layer_matrix import Layer, LayerMatrix  # noqa: E402


class _Job(object):
    regulationPerConditionData = None

    def getOrganism(self):
        return "mmu"


def _ctx():
    ctx = P.PaperContext.__new__(P.PaperContext)
    from src.classes.AIInterpret.facts import FactsLedger
    ctx.job_instance = _Job()
    ctx.job_id = "TEST0001"
    ctx.experiment_design = "two conditions"
    ctx.ledger = FactsLedger()
    layer = Layer("RNA", "gene", ["Day0", "Day7"])
    layer.feature_ids.append("g1"); layer.labels.append("FOS")
    layer.values.append([1.0, 2.0]); layer.relevant.append(True)
    ctx.matrix = LayerMatrix({"RNA": layer})
    ctx.graph = None
    ctx.pathways = [{"id": "mmu04110", "name": "Cell cycle",
                     "source": "KEGG", "combined_pvalue": 1e-4}]
    ctx.inventory = {"sets": [], "pairs": [], "dropped_pairs": 0}
    ctx.notes = {}
    ctx.figures = [{"id": "paperfig1-pca", "conclusion": "Groups separate.",
                    "archetype": "pca", "qa_passed": True, "render_ok": True},
                   {"id": "paperfig2-net", "conclusion": "Hubs converge.",
                    "archetype": "network", "qa_passed": True,
                    "render_ok": True}]
    ctx.papers = [{"ref_index": 1, "pmid": "100", "title": "A real paper",
                   "abstract": "Cell cycle biology.", "year": "2020",
                   "journal": "J", "authors": "A B", "tag": "Cell cycle"}]
    ctx._figure_seq = 2
    note = P.AnalysisNote("design_qc")
    fid = ctx.ledger.add("pvalue", 0.05, {"omic": "RNA"}, "permanova")
    note.findings = ["The groups separate on PC1 (p = {{%s}})." % fid]
    note.evidence = ["PERMANOVA p = 0.05 [%s]" % fid]
    note.unused_occasions = [{"occasion": "PCA on Proteomics",
                              "reason": "no replicates"}]
    ctx.notes["design_qc"] = note
    ctx.fid = fid
    return ctx


class KindMismatchTest(unittest.TestCase):

    def test_a_pvalue_token_in_a_count_slot_kills_the_sentence(self):
        ctx = _ctx()
        p_fid = ctx.ledger.add("pvalue", 1.5e-6, {"pathway": "x"}, "enrich")
        n_fid = ctx.ledger.add("count", 95, {"pathway": "x"}, "enrich")

        class _Swapper(object):
            def complete(self, messages, **kw):
                return "\n\n".join([
                    "# T", "## Results", "### Data overview and quality",
                    "The pathway had a combined p-value of {{%s}} with "
                    "{{%s}} matched genes. "
                    "The groups separate on PC1 (p = {{%s}})."
                    % (n_fid, p_fid, ctx.fid)])
        markdown, verification = P.assemble_paper(ctx, _Swapper())
        self.assertTrue(verification["sentences_redacted_kinds"])
        self.assertNotIn("matched genes", markdown.split("## Limitations")[0])
        self.assertIn("p = 0.05", markdown)     # the honest sentence survives

    def test_matched_kinds_pass(self):
        ctx = _ctx()
        p_fid = ctx.ledger.add("pvalue", 1.5e-6, {"pathway": "x"}, "enrich")
        n_fid = ctx.ledger.add("count", 95, {"pathway": "x"}, "enrich")

        class _Honest(object):
            def complete(self, messages, **kw):
                return "\n\n".join([
                    "# T", "## Results", "### Data overview and quality",
                    "The pathway had a combined p-value of {{%s}} with "
                    "{{%s}} matched genes." % (p_fid, n_fid)])
        markdown, verification = P.assemble_paper(ctx, _Honest())
        self.assertEqual(verification["sentences_redacted_kinds"], [])
        self.assertIn("95 matched genes", markdown)


class _SinningLead(object):
    """Commits every sin the gate exists to catch."""

    def __init__(self, fid):
        self.fid = fid

    def complete(self, messages, **kw):
        return "\n\n".join([
            "# Ikaros arrests the cycle",
            "## Results",
            "### Data overview and quality",
            "The groups separate on PC1 (p = {{%s}}). "
            "We found 412 genes changed. "
            "The effect size was {{f99}} across layers. "
            "This is supported by prior work [1] and by nothing [9]."
            % self.fid,
            "![Fig](figure:paperfig1-pca)",
            "## Discussion",
            "The cell cycle arrest is consistent with the literature [1].",
        ])


class GateTest(unittest.TestCase):

    def setUp(self):
        self.ctx = _ctx()
        self.markdown, self.verification = P.assemble_paper(
            self.ctx, _SinningLead(self.ctx.fid))

    def test_the_ledger_token_became_the_number(self):
        self.assertIn("p = 0.05", self.markdown)
        self.assertNotIn("{{%s}}" % self.ctx.fid, self.markdown)
        self.assertGreaterEqual(self.verification["facts_substituted"], 1)

    def test_the_bare_number_sentence_died(self):
        self.assertNotIn("412", self.markdown)
        self.assertTrue(any("412" in s for s in
                            self.verification["sentences_redacted_numbers"]))

    def test_the_unknown_token_sentence_died(self):
        self.assertNotIn("f99", self.markdown)
        self.assertTrue(self.verification["sentences_redacted_tokens"])

    def test_the_shelfless_citation_was_dropped_and_the_real_one_kept(self):
        self.assertNotIn("[9]", self.markdown)
        self.assertIn("[1]", self.markdown)
        self.assertEqual(self.verification["citations_dropped"], 1)
        self.assertGreaterEqual(self.verification["citations_kept"], 1)

    def test_the_forgotten_figure_still_reaches_the_reader(self):
        self.assertIn("figure:paperfig2-net", self.markdown)

    def test_limitations_carry_the_unused_occasion(self):
        self.assertIn("PCA on Proteomics", self.markdown)
        self.assertIn("no replicates", self.markdown)

    def test_methods_are_generated_not_written(self):
        self.assertIn("## Methods", self.markdown)
        self.assertIn("PERMANOVA", self.markdown)
        self.assertIn("ledger token", self.markdown)

    def test_references_list_only_what_survived(self):
        self.assertIn("## References", self.markdown)
        self.assertIn("PMID: 100", self.markdown)

    def test_an_empty_lead_is_a_hard_failure(self):
        class _Silent(object):
            def complete(self, messages, **kw):
                return ""
        with self.assertRaises(RuntimeError):
            P.assemble_paper(self.ctx, _Silent())


if __name__ == "__main__":
    unittest.main(verbosity=2)
