"""A section is furniture only if dropping it loses nothing.

Four consecutive production runs on paintomics.uv.es had their Results rewrite
rejected -- `lost_15,droppedpathways_12`, `lost_28,invented_1,droppedpathways_7`,
`lost_2`, `lost_1` -- so every user saw the old dossier and none of them saw
the paper prose the stage exists to produce. Every one of those rejections came
from the same place: a hard-coded list of heading names deciding which sections
were framing.

The list was a guess about SHAPE made from a TITLE, and reports come in more
than one shape:

  * flat      -- the whole body is one `## Detailed Pathway Analysis` whose
                 pathways are `**Name (p=...)** -- prose` lead-ins. The name
                 was on the list, so all 15 (and all 35) citations went at once.
  * sectioned -- one `## ` per pathway, plus a `## Key Findings` summary that
                 happened to carry one or two markers appearing nowhere else.
  * stitched  -- several `# ` reports concatenated, each with its own framing.

These tests fix the rule that replaces the guess: a named-furniture section is
dropped only when every citation marker in it survives elsewhere and it names
no pathway that would otherwise go unmentioned. They use the three real shapes
because a single fixture is what let this ship -- the one report I tested by
hand was the one shape the bug does not touch.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SERVER, "src"))
sys.path.insert(0, SERVER)

SRC = os.path.join(SERVER, "src", "classes", "AIInterpret", "agent_loop.py")

try:
    from src.classes.AIInterpret import agent_loop as al
    IMPORTED = True
except Exception as _e:                                   # pragma: no cover
    IMPORTED = False
    IMPORT_ERROR = _e


REFS = "\n### References\n" + "".join("[%d] Paper %d.\n" % (i, i)
                                      for i in range(1, 8))

FLAT = """# Synthesis Report: Cross-Pathway Analysis

## Key Findings
- Ikaros induction drives differentiation.
- Chromatin opens before transcription responds.

## Cross-Pathway Themes
The pathways share a chromatin-first ordering.

## Detailed Pathway Analysis

**Kaposi sarcoma-associated herpesvirus infection (p=1.47e-06, 38/61 genes)** -- the
top-ranked pathway. Myc shows a biphasic pattern [1], and IMiD-mediated IKZF1
degradation downregulates MYC [2].

**Cadherin signaling (p=5.03e-06, 20/26)** -- converges on beta-catenin. Wnt4 rises
to 17.92 at 24 h [3].

**Thyroid cancer (p=1.58e-05, 15/18)** -- shared RET/RAS/RAF drivers [4].

## Suggested Follow-up Experiments
ATAC-seq at 6 h would separate the two orderings.

## Limitations and Caveats
Time points are sparse.

## Enriched Pathway Summary
| Pathway | p | Genes |
| --- | --- | --- |
| Alcoholism | 1e-03 | 12/40 |
| Adherens junction | 4e-03 | 8/22 |
""" + REFS

SECTIONED = """# Integrated Synthesis Report

## Key Findings
Ribosome biogenesis leads the response [5]; lysosome genes follow [1].

## Ribosome Biogenesis in Eukaryotes (mmu03008)
Ribosome biogenesis rises early [1].

## Lysosome Biogenesis (mmu04142)
Lysosome genes follow at 18 h [2].

## Basal Transcription Factors (mmu03022)
Basal factors are unchanged [3].

## Limitations and Caveats
Replicates are limited.
""" + REFS

FURNITURE_ONLY = """# Report

## Key Findings
Ribosome biogenesis leads the response [1].

## Ribosome Biogenesis in Eukaryotes (mmu03008)
Ribosome biogenesis rises early [1].

## Lysosome Biogenesis (mmu04142)
Lysosome genes follow [2].
""" + REFS

NAMES = ["Kaposi sarcoma-associated herpesvirus infection", "Cadherin signaling",
         "Thyroid cancer", "Ribosome Biogenesis in Eukaryotes",
         "Lysosome Biogenesis", "Basal Transcription Factors"]


def _marks(text):
    return set(re.findall(r"\[(\d+)\]", str(text).split("### References")[0]))


@unittest.skipUnless(IMPORTED, "agent_loop did not import")
class FurnitureIsDecidedByEvidence(unittest.TestCase):
    """The classification, replayed over the three real report shapes."""

    def _partition(self, report):
        stats = {}
        pre, secs, closing, tail = al._partition_sections(report, NAMES, stats)
        kept = pre + "".join(h + b for h, b in secs) + "".join(closing)
        return pre, secs, closing, tail, kept, stats

    # ---- the flat shape: the whole report was being thrown away ----------
    def test_a_container_holding_every_citation_is_not_dropped(self):
        """`lost_15` and `lost_28`, the two worst production rejections.

        `## Detailed Pathway Analysis` is on the furniture list, and in this
        shape it is the entire report.
        """
        _, _, _, _, kept, _ = self._partition(FLAT)
        self.assertEqual(_marks(FLAT) - _marks(kept), set(),
                         "the container carried every marker in the report")

    def test_a_container_is_split_into_one_section_per_pathway(self):
        """Kept but unsplit is only half a fix.

        One chunk covering everything is the single-call rewrite that chunking
        exists to replace -- measured at 28 of 35 citations dropped.
        """
        _, secs, _, _, _, _ = self._partition(FLAT)
        heads = " | ".join(h for h, _ in secs).lower()
        self.assertIn("kaposi", heads)
        self.assertIn("cadherin", heads)
        self.assertIn("thyroid", heads)
        self.assertGreaterEqual(len(secs), 3)

    def test_a_split_container_keeps_each_pathway_with_its_own_citations(self):
        """A split that separates a claim from its marker would trade one
        failure for a subtler one."""
        _, secs, _, _, _, _ = self._partition(FLAT)
        by_head = {h.lower(): b for h, b in secs}
        kaposi = [b for h, b in by_head.items() if "kaposi" in h][0]
        self.assertEqual(_marks(kaposi), {"1", "2"})
        cadherin = [b for h, b in by_head.items() if "cadherin" in h][0]
        self.assertEqual(_marks(cadherin), {"3"})

    # ---- the sectioned shape: one or two orphan markers ------------------
    def test_a_summary_holding_an_orphan_marker_is_kept(self):
        """`lost_2` and `lost_1`. [5] appears only in Key Findings."""
        _, _, _, _, kept, stats = self._partition(SECTIONED)
        self.assertIn("5", _marks(kept),
                      "a marker that lives only in the summary is still a "
                      "verified claim")
        self.assertEqual(stats.get("results_furniture_kept"), 1)

    def test_a_summary_that_repeats_what_survives_is_still_dropped(self):
        """The guard must not become 'keep everything' -- the bullets and the
        duplicate tables are what the stage was built to remove."""
        _, secs, _, _, kept, stats = self._partition(FURNITURE_ONLY)
        self.assertNotIn("key findings", " ".join(h for h, _ in secs).lower())
        self.assertNotIn("results_furniture_kept", stats)
        self.assertEqual(_marks(FURNITURE_ONLY) - _marks(kept), set())

    def test_furniture_naming_an_otherwise_unmentioned_pathway_is_kept(self):
        """A finding can be lost without a citation going with it: the rubric
        scores pathway NAMES, and coverage and citation count are independent
        (r = 0.05 measured)."""
        report = FURNITURE_ONLY.replace(
            "Ribosome biogenesis leads the response [1].",
            "Basal Transcription Factors are unchanged [1].")
        _, secs, _, _, kept, _ = self._partition(report)
        self.assertIn("basal transcription factors", kept.lower())

    # ---- placement -------------------------------------------------------
    def test_follow_up_experiments_close_the_section_rather_than_open_one(self):
        """Rewritten as a finding it acquires a heading for work nobody did."""
        _, secs, closing, _, _, _ = self._partition(FLAT)
        self.assertNotIn("follow-up", " ".join(h for h, _ in secs).lower())
        self.assertIn("follow-up", " ".join(closing).lower())

    def test_caveats_stay_in_the_closing_block(self):
        _, secs, closing, _, _, _ = self._partition(FLAT)
        self.assertIn("limitations", " ".join(closing).lower())
        self.assertNotIn("limitations", " ".join(h for h, _ in secs).lower())

    # ---- a table restates; it does not find -----------------------------
    def test_a_data_table_is_furniture_however_many_pathways_it_names(self):
        """The over-correction the first fix shipped.

        The enriched-pathway summary lists EVERY enriched pathway -- 46 rows on
        job 4j00f2377Y -- while the prose discusses a handful. Judged on raw
        text, all 46 read as pathways mentioned nowhere else, the table is
        readmitted as evidence, and the rewrite ships with exactly the table it
        was asked to remove.
        """
        _, secs, closing, _, kept, _ = self._partition(FLAT)
        self.assertNotIn("| Alcoholism |", kept,
                         "a row of data the job already holds is not a finding")
        self.assertNotIn("enriched pathway summary",
                         " ".join(h for h, _ in secs).lower())

    def test_a_citation_inside_a_table_still_counts_as_evidence(self):
        """Names are findings only in prose; a marker is evidence wherever it
        is. Stripping tables from BOTH tests would let a cited row vanish."""
        report = FLAT.replace("| Alcoholism | 1e-03 | 12/40 |",
                              "| Alcoholism | 1e-03 | see [7] |")
        _, _, _, _, kept, _ = self._partition(report)
        self.assertIn("7", _marks(kept))

    def test_the_reference_list_is_carried_across_verbatim(self):
        for report in (FLAT, SECTIONED, FURNITURE_ONLY):
            _, _, _, tail, _, _ = self._partition(report)
            self.assertIn("### References", tail)

    # ---- the property that all four rejections violated ------------------
    def test_no_shape_loses_a_marker_in_classification(self):
        """The one assertion that would have caught every production failure
        before it shipped."""
        for name, report in (("flat", FLAT), ("sectioned", SECTIONED),
                             ("furniture-only", FURNITURE_ONLY)):
            _, _, _, _, kept, _ = self._partition(report)
            self.assertEqual(_marks(report) - _marks(kept), set(),
                             "%s shape dropped a marker before the model ever "
                             "ran" % name)

    def test_no_shape_loses_a_pathway_the_prose_discusses(self):
        """The other half of the guard, on the same basis the guard uses.

        Citation count and rubric coverage are independent (r = 0.05), so
        conserving markers says nothing about conserving findings.
        """
        for name, report in (("flat", FLAT), ("sectioned", SECTIONED),
                             ("furniture-only", FURNITURE_ONLY)):
            _, _, _, _, kept, _ = self._partition(report)
            prose_before = al._without_table_rows(
                report.split("### References")[0]).lower()
            prose_kept = al._without_table_rows(kept).lower()
            lost = [n for n in NAMES
                    if n.lower() in prose_before and n.lower() not in prose_kept]
            self.assertEqual(lost, [], "%s shape dropped %s" % (name, lost))


@unittest.skipUnless(IMPORTED, "agent_loop did not import")
class ALeadInIsOnlySplitWhenItIsAContainer(unittest.TestCase):

    def test_a_single_lead_in_is_left_alone(self):
        """One bold paragraph is emphasis, not a list of pathways."""
        out = al._explode_container("## Notes", "\n**Only one** -- prose [1].\n")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], "## Notes")

    def test_framing_above_the_first_lead_in_is_carried(self):
        body = ("\nThese pathways share a theme [9].\n\n"
                "**One (p=1)** -- a [1].\n\n**Two (p=2)** -- b [2].\n")
        out = al._explode_container("## Detailed Pathway Analysis", body)
        self.assertEqual(len(out), 2)
        self.assertIn("9", _marks(out[0][1]),
                      "the container's own framing can carry a citation")


class TheChunkKeepsItsSourceWhenItCannotConserveIt(unittest.TestCase):
    """Source-level: the second half of the production failure.

    Citations were counted once, over the finished report, and any loss threw
    the whole rewrite away -- so two runs that had reorganised the dossier
    correctly were discarded for one and two markers.
    """

    def setUp(self):
        with open(SRC) as fh:
            self.src = fh.read()
        self.block = self.src.split("    async def one(group, taken):")[1]
        self.block = self.block.split("\n    # Sequential")[0]

    def test_a_chunk_checks_its_own_markers(self):
        self.assertIn("own_marks", self.block)
        self.assertIn("lost = own_marks - got", self.block)

    def test_a_failing_chunk_reverts_to_its_source_text(self):
        """One section reading like the old dossier is a far smaller loss than
        no rewrite at all."""
        self.assertIn("results_chunk_reverted", self.block)
        self.assertEqual(self.block.count("return chunk, owned"), 2,
                         "both the exception path and the unconserved path "
                         "must keep the ORIGINAL sections")

    def test_invented_markers_are_judged_against_the_whole_report(self):
        """A chunk may legitimately reuse a marker another chunk introduced;
        reverting for that would punish good prose."""
        self.assertIn("made_up = got - all_marks", self.block)

    def test_the_retry_names_what_went_missing(self):
        low = self.block.lower()
        self.assertIn("dropped these citation markers", low)
        self.assertIn("stopped discussing these pathways", low)


if __name__ == "__main__":
    if not IMPORTED:
        print("NOTE: agent_loop did not import (%s); behavioural cases skip."
              % IMPORT_ERROR)
    r = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    sys.exit(0 if r.wasSuccessful() else 1)
