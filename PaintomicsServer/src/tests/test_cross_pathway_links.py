#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Curated interactions a pathway map does not draw.

A pathway diagram is a drawing decision, not a claim that nothing else
connects. KEGG records Ctnnb1 -> Myc but draws it only on Human cytomegalovirus
infection, so opening the Kaposi sarcoma map with both genes lit up by the
user's data shows two boxes and says nothing about them. This layer finds those
and needs no MORE analysis at all.

Every rule pinned here is a measured response to the candidate pool being far
larger than the map can hold, and each one was arrived at by trying the obvious
thing first and watching it fail:

  * unrestricted, every pair of drawn genes some other map connects is a median
    of 233 per map and a maximum of 4,791;
  * restricted to genes the user has data for: median 11, max 574;
  * restricted again to pairs where BOTH endpoints are significant: median 1;
  * ranked by curation topology it fills with hubs -- "recorded in the most
    other maps" returns Raf1-Mapk1 (65 maps) and "the fewest" still returns
    Raf1 and Akt1, which are 139 of mmu05167's 259 candidates. Ranking on the
    WEAKER endpoint's effect size returns Ctnnb1-Myc and Ccnd1-Jun instead;
  * ranked without a distance rule it swept arcs across the whole diagram --
    chords ran to 924 px on a 1,894 px diagonal.

Hermetic: every input is a stub, so this runs with no database, no job on disk
and no species installed.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.classes import PathwayEvidence


class FakeOmicValue(object):
    def __init__(self, values, relevant):
        self._values, self._relevant = values, relevant

    def isRelevant(self):
        return self._relevant

    def getValues(self):
        return self._values


class FakeGene(object):
    def __init__(self, symbol, values, relevant):
        self._symbol = symbol
        self._omics = [FakeOmicValue(values, relevant)]

    def getName(self):
        return self._symbol

    def getOmicsValues(self):
        return self._omics


class FakePathway(object):
    def __init__(self, matched):
        self._matched = matched

    def getMatchedGenes(self):
        return self._matched


class FakeJob(object):
    """Only the three accessors the layer actually touches."""

    def __init__(self, genes, matched, pathwayID="mmuTEST"):
        self._genes = genes
        self._pathways = {pathwayID: FakePathway(matched)}

    def getMatchedPathways(self):
        return self._pathways

    def getInputGenesData(self):
        return self._genes


def knowledgeWith(edges, known=None):
    """An EvidenceKnowledge holding one KEGG source with `edges`."""
    source = PathwayEvidence.InteractionSource(
        "KEGG", edges, set(known if known is not None else
                           [gene for pair in edges for gene in pair]))
    return PathwayEvidence.EvidenceKnowledge([source])


#: Three genes 50 px apart plus one in the far corner. The corner one sets the
#: map's diagonal (1,131 px), so the readability limit is ~136 px: the three
#: neighbours are all inside it and anything involving "4" is outside. Spacing
#: them 100 px apart put 1<->3 outside the limit and made four ranking tests
#: fail for a reason that had nothing to do with ranking.
POSITIONS = {"1": [(100.0, 100.0)], "2": [(150.0, 100.0)],
             "3": [(200.0, 100.0)], "4": [(900.0, 900.0)]}


def genesFixture(**overrides):
    base = {
        "1": FakeGene("Aaa", [5.0], True),
        "2": FakeGene("Bbb", [4.0], True),
        "3": FakeGene("Ccc", [9.0], True),
        "4": FakeGene("Ddd", [9.0], True),
    }
    base.update(overrides)
    return base


class WhatCounts(unittest.TestCase):
    """Which pairs are eligible at all."""

    def test_a_pair_this_map_already_draws_is_not_a_missing_link(self):
        """That is the diagram working, not a gap in it."""
        job = FakeJob(genesFixture(), ["1", "2"])
        knowledge = knowledgeWith({("1", "2"): [("GErel", "mmuTEST")]})

        links, statistics = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "2"}, {}, 5, positions=POSITIONS)

        self.assertEqual(links, [])
        self.assertEqual(statistics["candidates"], 0)

    def test_a_pair_only_another_map_draws_is_the_whole_point(self):
        job = FakeJob(genesFixture(), ["1", "2"])
        knowledge = knowledgeWith({("1", "2"): [("GErel", "mmu04010")]})

        links, _statistics = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "2"}, {"mmu04010": "MAPK"}, 5,
            positions=POSITIONS)

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["sourceLabel"], "Aaa")
        self.assertEqual(links[0]["targetLabel"], "Bbb")
        self.assertTrue(links[0]["transcriptional"], "GErel is a directed claim")
        self.assertEqual(links[0]["evidenceSources"][0]["pathways"][0]["name"], "MAPK")

    def test_a_feature_with_no_box_on_this_map_cannot_be_an_endpoint(self):
        job = FakeJob(genesFixture(), ["1", "2"])
        knowledge = knowledgeWith({("1", "2"): [("GErel", "mmu04010")]})

        links, _ = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1"}, {}, 5, positions=POSITIONS)

        self.assertEqual(links, [])

    def test_an_unknown_pathway_yields_nothing_rather_than_raising(self):
        job = FakeJob(genesFixture(), ["1", "2"])
        links, _ = PathwayEvidence.crossPathwayLinks(
            job, "not-a-pathway", knowledgeWith({}), {"1", "2"}, {}, 5)
        self.assertEqual(links, [])


class SignificanceFilter(unittest.TestCase):
    """`relevantOnly` is the filter that takes the median from 11 to 1."""

    def setUp(self):
        self.genes = genesFixture(**{"2": FakeGene("Bbb", [4.0], False)})
        self.job = FakeJob(self.genes, ["1", "2"])
        self.knowledge = knowledgeWith({("1", "2"): [("PPrel", "mmu04010")]})

    def test_an_insignificant_endpoint_is_excluded_by_default(self):
        links, statistics = PathwayEvidence.crossPathwayLinks(
            self.job, "mmuTEST", self.knowledge, {"1", "2"}, {}, 5,
            positions=POSITIONS)
        self.assertEqual(links, [])
        self.assertEqual(statistics["relevantFeatures"], 1)
        self.assertTrue(statistics["relevantOnly"])

    def test_the_reader_can_widen_it(self):
        links, statistics = PathwayEvidence.crossPathwayLinks(
            self.job, "mmuTEST", self.knowledge, {"1", "2"}, {}, 5,
            relevantOnly=False, positions=POSITIONS)
        self.assertEqual(len(links), 1)
        self.assertEqual(statistics["relevantFeatures"], 2)
        self.assertFalse(statistics["relevantOnly"])

    def test_a_feature_the_user_has_no_data_for_is_never_an_endpoint(self):
        """Widening to "all matched" is not widening to the whole map."""
        job = FakeJob({"1": self.genes["1"]}, ["1", "2"])
        links, _ = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", self.knowledge, {"1", "2"}, {}, 5,
            relevantOnly=False, positions=POSITIONS)
        self.assertEqual(links, [])


class Distance(unittest.TestCase):
    """Both endpoints are fixed boxes, so a long link has nowhere to go."""

    def test_a_link_across_the_map_is_rejected_and_counted(self):
        job = FakeJob(genesFixture(), ["1", "4"])
        knowledge = knowledgeWith({("1", "4"): [("PPrel", "mmu04010")]})

        links, statistics = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "4"}, {}, 5, positions=POSITIONS)

        self.assertEqual(links, [])
        self.assertEqual(statistics["candidates"], 1,
                         "it IS a candidate; it is the drawing that refuses it")
        self.assertEqual(statistics["tooFarApart"], 1,
                         "counted, because it is a drawing decision and the "
                         "panel has to be able to say so")

    def test_a_neighbouring_pair_is_kept(self):
        job = FakeJob(genesFixture(), ["1", "2"])
        knowledge = knowledgeWith({("1", "2"): [("PPrel", "mmu04010")]})
        links, statistics = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "2"}, {}, 5, positions=POSITIONS)
        self.assertEqual(len(links), 1)
        self.assertEqual(statistics["tooFarApart"], 0)
        self.assertEqual(links[0]["chord"], 50.0)

    def test_the_shortest_of_several_drawn_copies_is_the_one_measured(self):
        positions = dict(POSITIONS)
        positions["4"] = [(900.0, 900.0), (220.0, 100.0)]
        job = FakeJob(genesFixture(), ["1", "4"])
        knowledge = knowledgeWith({("1", "4"): [("PPrel", "mmu04010")]})

        links, _ = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "4"}, {}, 5, positions=positions)

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["chord"], 120.0)

    def test_without_geometry_nothing_is_rejected_for_distance(self):
        job = FakeJob(genesFixture(), ["1", "4"])
        knowledge = knowledgeWith({("1", "4"): [("PPrel", "mmu04010")]})
        links, statistics = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "4"}, {}, 5, positions={})
        self.assertEqual(len(links), 1)
        self.assertEqual(statistics["tooFarApart"], 0)


class Ranking(unittest.TestCase):
    """The weaker endpoint decides, and short chords break ties."""

    def test_one_loud_gene_cannot_drag_a_quiet_partner_onto_the_map(self):
        genes = {
            "1": FakeGene("Loud", [100.0], True),
            "2": FakeGene("Quiet", [1.0], True),
            "3": FakeGene("Mid", [8.0], True),
        }
        job = FakeJob(genes, ["1", "2", "3"])
        knowledge = knowledgeWith({("1", "2"): [("PPrel", "mmu04010")],
                                   ("1", "3"): [("PPrel", "mmu04010")]})

        links, _ = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "2", "3"}, {}, 5, positions=POSITIONS)

        self.assertEqual([link["targetLabel"] for link in links], ["Mid", "Quiet"])
        self.assertEqual(links[0]["strength"], 8.0)

    def test_at_equal_strength_the_transcriptional_claim_comes_first(self):
        genes = {"1": FakeGene("Aaa", [5.0], True),
                 "2": FakeGene("Bbb", [5.0], True),
                 "3": FakeGene("Ccc", [5.0], True)}
        job = FakeJob(genes, ["1", "2", "3"])
        knowledge = knowledgeWith({("1", "2"): [("PPrel", "mmu04010")],
                                   ("1", "3"): [("GErel", "mmu04010")]})

        links, _ = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "2", "3"}, {}, 5, positions=POSITIONS)

        self.assertTrue(links[0]["transcriptional"])

    def test_the_cap_keeps_the_top_and_counts_the_rest(self):
        job = FakeJob(genesFixture(), ["1", "2", "3"])
        knowledge = knowledgeWith({("1", "2"): [("PPrel", "mmu04010")],
                                   ("1", "3"): [("PPrel", "mmu04010")],
                                   ("2", "3"): [("PPrel", "mmu04010")]})

        links, statistics = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "2", "3"}, {}, 1, positions=POSITIONS)

        self.assertEqual(len(links), 1)
        self.assertEqual(statistics["candidates"], 3)
        self.assertEqual(statistics["hidden"], 2)

    def test_a_zero_budget_does_no_work_at_all(self):
        job = FakeJob(genesFixture(), ["1", "2"])
        knowledge = knowledgeWith({("1", "2"): [("PPrel", "mmu04010")]})
        links, statistics = PathwayEvidence.crossPathwayLinks(
            job, "mmuTEST", knowledge, {"1", "2"}, {}, 0, positions=POSITIONS)
        self.assertEqual(links, [])
        self.assertEqual(statistics["candidates"], 0)


class Geometry(unittest.TestCase):
    def test_positions_are_read_off_the_pathway_document(self):
        document = {"genes": [
            {"id": "1", "x": "10", "y": "20"},
            {"id": "1", "x": "30", "y": "40"},          # drawn twice
            {"id": "2", "x": None, "y": None},          # no box
            {"id": "3", "x": "bad", "y": "5"},          # unparseable
        ]}
        positions = PathwayEvidence._featurePositions(document)
        self.assertEqual(positions["1"], [(10.0, 20.0), (30.0, 40.0)])
        self.assertNotIn("2", positions)
        self.assertNotIn("3", positions)

    def test_shortest_chord_handles_a_missing_feature(self):
        self.assertIsNone(PathwayEvidence._shortestChord({"1": [(0.0, 0.0)]}, "1", "2"))


class Profile(unittest.TestCase):
    def test_peak_is_the_largest_absolute_value_across_every_omic(self):
        gene = FakeGene("Aaa", [1.0, -7.5, 2.0], True)
        profile = PathwayEvidence._featureProfile({"1": gene}, "1")
        self.assertEqual(profile["peak"], 7.5)
        self.assertTrue(profile["relevant"])

    def test_a_feature_absent_from_the_data_has_no_profile(self):
        self.assertIsNone(PathwayEvidence._featureProfile({}, "1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
