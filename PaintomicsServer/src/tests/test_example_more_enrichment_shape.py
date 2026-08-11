#!/usr/bin/env python3
"""Does the MORE example produce an enrichment, or a flat list?

`test_example_scenarios_validate.py` asks whether MORE's inputs are well
formed. `test_example_enrichment_calibration.py` asks whether the ratio
scenarios' shipped relevance behaves like data. Neither covers the MORE
scenario's relevance, and it is the one scenario that does not ship any: red
stars for a MORE job are computed by MOREServlet at run time, by expanding the
user's "significant regulators" file to every GENE:::REGULATOR pair the
ASSOCIATION file puts that regulator in (MOREServlet.py, "regardless of MORE
significance"). So the shape of the enrichment is decided by two shipped files
per omic -- the flagged regulators and the associations -- and by nothing else.

That is exactly what went wrong. With every responding regulator flagged and
each target given three candidates drawn uniformly, a gene had a
1 - (1/2)**3 = 87.5% chance of being associated with a flagged regulator, and a
full run measured 225 of 249 modelled genes (90.4%) relevant on the TF omic and
219 (88.0%) on miRNA. Against a modelled set that was itself entirely inside
the eight declared target pathways, the hypergeometric had nothing to contrast:
of 96 matched pathways exactly one came back significant -- mmu01100, which is
not a declared target -- and the declared eight ran from p 0.109 to 0.976, two
of them at ranks 38 and 39 of 96.

This reproduces the servlet's rule offline and asserts the resulting shape.
Offline because a real run costs ~80 s of R plus ~25 s of pathway analysis; it
was checked against the real thing, which on the same files reports 283 matched
and 15 significant where this reports 281 and 15, with the eight declared
targets in the same order (the two-pathway difference is genes that map to more
than one KEGG id, which only the real mapping step knows about).

Usage:
    cd PaintomicsServer
    python -m src.tests.test_example_more_enrichment_shape
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from scipy.stats import combine_pvalues                                 # noqa: E402

from src.common import ExampleDatasets                                  # noqa: E402
from src.common.Statistics import calculateFisher                       # noqa: E402
from src.servlets.MOREServlet import _parseRelevantRegulators           # noqa: E402

EXAMPLE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examplefiles")) + os.sep

# The band the real STATegra job occupies, per
# test_example_enrichment_calibration: 0.8% to 11% of matched pathways
# significant, widened at the top by a point.
MIN_SIGNIFICANT_FRACTION = 0.005
MAX_SIGNIFICANT_FRACTION = 0.12

# Every declared target has to be inside this many places, ranked by p-value.
# The same ceiling the ratio scenarios are held to.
TARGET_RANK_CEILING = 30

# A relevance rate above this is the failure this module exists for: once most
# of the submission is relevant, no pathway can be enriched relative to it.
# The real STATegra omics run 13% to 83% globally, but they are measured over
# 10406 genes, not over a set built to be enriched.
MAX_RELEVANT_RATE = 0.45


def keggSource():
    try:
        from src.AdminTools.scripts.exampledata.keggsource import (
            KeggSource, SpeciesNotInstalled)
        from src.conf.serverconf import KEGG_DATA_DIR
    except ImportError:
        return None
    try:
        return KeggSource(KEGG_DATA_DIR, "mmu")
    except (SpeciesNotInstalled, OSError):
        return None


def redStarredGenes(scenario, omic):
    """The genes MOREServlet would mark relevant for one regulatory omic.

    Mirrors fromMOREtoGenes_STEP2: parse the user's regulator list with the
    servlet's own parser, then take every association whose regulator is in it.
    The servlet reads the pairs back out of MORE's output file rather than the
    association file, which can only ever be a subset of it, so this is the
    upper bound of what a run can star -- and the bound is what the flood
    exceeded.
    """
    flagged = _parseRelevantRegulators(
        ExampleDatasets.absolutePath(EXAMPLE_DIR, omic["relevantFile"]))
    starred = set()
    path = ExampleDatasets.absolutePath(EXAMPLE_DIR, omic["associationsFile"])
    with open(path, encoding="utf-8") as handle:
        handle.readline()                                # Target<TAB>Regulator
        for line in handle:
            if not line.strip():
                continue
            target, regulator = line.rstrip("\n").split("\t")[:2]
            if regulator.lower() in flagged:
                starred.add(target)
    return starred


def modelledGenes(scenario):
    path = ExampleDatasets.absolutePath(EXAMPLE_DIR, scenario["target"]["dataFile"])
    with open(path, encoding="utf-8") as handle:
        handle.readline()
        return {line.split("\t")[0].strip() for line in handle if line.strip()}


def declaredTargets(scenario):
    path = ExampleDatasets.absolutePath(
        EXAMPLE_DIR, scenario["expected"]["pathwaysFile"])
    with open(path, encoding="utf-8") as handle:
        return [line.split("\t")[0].strip() for line in handle
                if line.strip() and not line.startswith("#")]


def enrichmentRows(kegg, background, relevantByOmic):
    """(pathway, combined p) per matched pathway, the way the job does it.

    calculateFisher is PathwayAcquisitionJob's own hypergeometric, and the
    omics are combined with Fisher's method exactly as
    Pathway.getTotalGlobalPvalues does. With a single omic the combination is
    the identity -- chi2(-2 ln p, 2 df) survives back to p -- so one code path
    covers both MORE scenarios.
    """
    total = len(background)
    rows = []
    for pathway, members in kegg.pathwayToGenes.items():
        inPathway = [gene for gene in members if gene in background]
        if not inPathway:
            continue
        pvalues = []
        for relevant in relevantByOmic.values():
            hits = sum(1 for gene in inPathway if gene in relevant)
            pvalues.append(calculateFisher(total, len(inPathway),
                                           len(relevant), hits))
        rows.append((pathway, float(combine_pvalues(pvalues,
                                                    method="fisher")[1])))
    rows.sort(key=lambda row: row[1])
    return rows


class MoreEnrichmentShapeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.kegg = keggSource()
        if cls.kegg is None:
            raise unittest.SkipTest(
                "no installed KEGG snapshot; this checks the shipped MORE "
                "files against pathway membership and cannot run without it")
        cls.scenario = ExampleDatasets.getScenario(EXAMPLE_DIR, "regulatory-more")
        cls.background = {gene for gene in modelledGenes(cls.scenario)
                          if gene in cls.kegg.geneToPathways}
        cls.relevant = {omic["omicName"]: redStarredGenes(cls.scenario, omic)
                        & cls.background
                        for omic in cls.scenario["omics"]}
        cls.targets = declaredTargets(cls.scenario)
        cls.rows = enrichmentRows(cls.kegg, cls.background, cls.relevant)

    def test_relevance_is_not_a_flood(self):
        for omicName, relevant in self.relevant.items():
            rate = len(relevant) / float(len(self.background))
            self.assertLessEqual(
                rate, MAX_RELEVANT_RATE,
                "%s stars %d of %d modelled genes (%.1f%%). Expanding the "
                "flagged regulators over the associations marks so much of "
                "the submission that nothing can be enriched against it."
                % (omicName, len(relevant), len(self.background), 100 * rate))
            self.assertGreater(rate, 0.0, "%s stars nothing at all" % omicName)

    def test_every_declared_target_is_significant(self):
        pvalue = dict(self.rows)
        for pathway in self.targets:
            self.assertIn(pathway, pvalue,
                          "%s is declared a target but no modelled gene is in "
                          "it" % pathway)
            self.assertLessEqual(
                pvalue[pathway], 0.05,
                "declared target %s comes back at p=%.3g. The scenario's "
                "expected_pathways.txt says enrichment should rank it highly."
                % (pathway, pvalue[pathway]))

    def test_every_declared_target_ranks_near_the_top(self):
        rank = {row[0]: index + 1 for index, row in enumerate(self.rows)}
        worst = max(rank[pathway] for pathway in self.targets)
        self.assertLessEqual(
            worst, TARGET_RANK_CEILING,
            "the weakest declared target ranks %d of %d matched pathways"
            % (worst, len(self.rows)))

    def test_the_significant_fraction_looks_like_the_real_job(self):
        significant = sum(1 for _pathway, p in self.rows if p <= 0.05)
        fraction = significant / float(len(self.rows))
        self.assertGreaterEqual(fraction, MIN_SIGNIFICANT_FRACTION,
                                "%d of %d pathways significant"
                                % (significant, len(self.rows)))
        self.assertLessEqual(fraction, MAX_SIGNIFICANT_FRACTION,
                             "%d of %d pathways significant"
                             % (significant, len(self.rows)))

    def test_the_example_exercises_a_realistic_share_of_the_pathway_space(self):
        """96 matched pathways was the symptom that the modelled set had
        collapsed onto the eight declared targets."""
        self.assertGreaterEqual(
            len(self.rows), 200,
            "only %d pathways hold a modelled gene; the example would exercise "
            "a quarter of the pathway space it used to" % len(self.rows))


class RealMoreEnrichmentShapeTest(unittest.TestCase):
    """The same question asked of `stategra-more`, which has no ground truth.

    `regulatory-more` can be checked against the pathways it planted. This one
    plants nothing, so the assertions are about shape only -- but the shape is
    exactly what was wrong with it. Built against TFLink "All", every one of
    its 600 targets carried a red star, which pins each pathway's
    hypergeometric at exactly 1.0 and left the scenario with zero significant
    pathways out of 309 and no threshold able to change that. Rebuilt against
    TFLink's small-scale subset it stars 31.5%.

    The counts below are deliberately banded rather than pinned: matched and
    significant totals move with the installed KEGG snapshot (888/44 on the
    deploy VM against 877/41 locally for the same job), and this file would
    otherwise fail on a perfectly good machine. The star rate is pinned harder,
    because it is computed from the shipped files alone.
    """

    # The failure this scenario was rebuilt to fix, and the opposite one. A
    # star rate at either end makes the pathway step uninformative: at 100%
    # nothing can be enriched against the background, at 0% nothing is
    # relevant at all.
    MAX_STAR_RATE = 0.45
    MIN_STAR_RATE = 0.05

    # Wide on purpose -- see the class docstring. Measured 23.5% locally; the
    # band exists to catch 0% and 100%, not to pin the snapshot.
    MIN_SIGNIFICANT_FRACTION = 0.02
    MAX_SIGNIFICANT_FRACTION = 0.40

    @classmethod
    def setUpClass(cls):
        cls.kegg = keggSource()
        if cls.kegg is None:
            raise unittest.SkipTest(
                "no installed KEGG snapshot; this checks the shipped MORE "
                "files against pathway membership and cannot run without it")
        cls.scenario = ExampleDatasets.getScenario(EXAMPLE_DIR, "stategra-more")
        cls.modelled = modelledGenes(cls.scenario)
        cls.background = {gene for gene in cls.modelled
                          if gene in cls.kegg.geneToPathways}
        cls.relevant = {omic["omicName"]: redStarredGenes(cls.scenario, omic)
                        & cls.background
                        for omic in cls.scenario["omics"]}
        cls.rows = enrichmentRows(cls.kegg, cls.background, cls.relevant)

    def test_the_star_rate_matches_what_the_manifest_declares(self):
        """The manifest's number and the shipped files must not drift apart.

        Computed over every modelled gene rather than only the ones KEGG
        knows, because that is what the manifest records and what MOREServlet
        actually produces.
        """
        starred = redStarredGenes(self.scenario, self.scenario["omics"][0])
        starred &= self.modelled
        expected = self.scenario["expected"]
        self.assertEqual(
            len(starred), expected["starredTargets"],
            "the shipped association and relevant-regulator files star %d of "
            "%d modelled genes; the manifest says %d. Regenerate the manifest "
            "or the dataset -- they disagree."
            % (len(starred), len(self.modelled), expected["starredTargets"]))
        self.assertAlmostEqual(
            len(starred) / float(len(self.modelled)),
            expected["starredTargetRate"], places=3)

    def test_relevance_is_neither_a_flood_nor_empty(self):
        for omicName, relevant in self.relevant.items():
            rate = len(relevant) / float(len(self.background))
            self.assertLessEqual(
                rate, self.MAX_STAR_RATE,
                "%s stars %d of %d genes (%.1f%%). Expanding the flagged "
                "regulators over the associations marks so much of the "
                "submission that nothing can be enriched against it -- which "
                "is what TFLink 'All' did to this scenario at 100%%."
                % (omicName, len(relevant), len(self.background), 100 * rate))
            self.assertGreaterEqual(
                rate, self.MIN_STAR_RATE,
                "%s stars only %.1f%% of the background" % (omicName, 100 * rate))

    def test_the_enrichment_separates(self):
        """Something has to come back significant, and convincingly.

        The old files failed this at its weakest possible reading: the *best*
        pathway of 309 came back at exactly p = 1.0.
        """
        best = self.rows[0][1]
        self.assertLess(
            best, 1e-4,
            "the most enriched of %d matched pathways is only p=%.3g; the "
            "regulatory hand-off is not separating anything"
            % (len(self.rows), best))

    def test_the_significant_fraction_is_believable(self):
        significant = sum(1 for _pathway, p in self.rows if p <= 0.05)
        fraction = significant / float(len(self.rows))
        self.assertGreaterEqual(fraction, self.MIN_SIGNIFICANT_FRACTION,
                                "%d of %d pathways significant"
                                % (significant, len(self.rows)))
        self.assertLessEqual(fraction, self.MAX_SIGNIFICANT_FRACTION,
                             "%d of %d pathways significant"
                             % (significant, len(self.rows)))

    def test_the_example_exercises_a_realistic_share_of_the_pathway_space(self):
        self.assertGreaterEqual(
            len(self.rows), 200,
            "only %d pathways hold a modelled gene" % len(self.rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
