#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""What tier 1 may and may not settle on its own.

Every rule here was measured against the real KEGG tables before it was
written, and two of the tests pin decisions the ranker deliberately REFUSES to
make. Those matter most: a rule that resolves an ambiguous name to the wrong
compound produces no error, no warning and a completed analysis about a
different metabolite than the user measured.

No MongoDB. The on-map compound set and the synonym table are both plain
arguments, which is the point of taking them as parameters rather than reading
them inside the ranker.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.classes.Feature import Compound
from src.classes.FoundFeature import FoundFeature
from src.classes.CompoundDisambiguation import ranker


def compoundSet(title, mains, others=()):
    """A step-2 compound set, bucketed the way the mapper buckets one."""
    found = FoundFeature("")
    found.setTitle(title)
    for keggID, name in mains:
        compound = Compound(keggID)
        compound.setName(name)
        compound.calculateSimilarity(title)
        found.addMainCompound(compound)
    for keggID, name in others:
        compound = Compound(keggID)
        compound.setName(name)
        compound.calculateSimilarity(title)
        found.addOtherCompound(compound)
    return found


class DeterministicRulesTest(unittest.TestCase):

    def test_one_main_candidate_resolves(self):
        """"Glyceric acid" matched one compound plus substring noise."""
        decision = ranker.rankCompoundSet(
            compoundSet("Glyceric acid",
                        [("C00258", "Glyceric acid")],
                        [("C00197", "3-Phospho-D-glycerate")]),
            onMapIDs=set())
        self.assertEqual("resolved", decision["status"])
        self.assertEqual("C00258", decision["keggID"])
        self.assertEqual("deterministic", decision["tier"])

    def test_the_species_filter_breaks_a_two_way_tie(self):
        """Only one of the two matching forms is drawn on this organism's maps."""
        decision = ranker.rankCompoundSet(
            compoundSet("Lactic acid",
                        [("C00186", "L-Lactic acid"), ("C01432", "Lactic acid")]),
            onMapIDs={"C00186"}, organismLabel="mmu")
        self.assertEqual("resolved", decision["status"])
        self.assertEqual("C00186", decision["keggID"])
        self.assertIn("mmu", decision["reason"])

    def test_a_single_candidate_resolves(self):
        decision = ranker.rankCompoundSet(
            compoundSet("Mannitol", [("C00392", "Mannitol")], [("C00392", "D-Mannitol")]),
            onMapIDs=set())
        self.assertEqual("resolved", decision["status"])
        self.assertEqual("C00392", decision["keggID"])


class RulesTheRankerRefusesTest(unittest.TestCase):
    """The two measured traps, pinned so no future 'obvious' rule reopens them."""

    def test_an_exact_name_match_does_not_win(self):
        """Measured: KEGG's compound literally named "Alanine" is C01401.

        C01401 is the unspecified form AND it is drawn on mouse pathways, so
        neither an exact-name rule nor the species filter rescues this one. A
        mouse experiment means C00041 L-Alanine, and only judgement gets there
        -- so the ranker must escalate rather than take the literal match.
        """
        decision = ranker.rankCompoundSet(
            compoundSet("Alanine",
                        [("C01401", "Alanine"), ("C00041", "L-Alanine"),
                         ("C00133", "D-Alanine"), ("C00099", "beta-Alanine")]),
            onMapIDs={"C01401", "C00041", "C00133", "C00099"}, organismLabel="mmu")

        self.assertEqual("residual", decision["status"])
        self.assertNotEqual("C01401", decision.get("keggID"))
        offered = set(c["keggID"] for c in decision["candidates"])
        self.assertIn("C00041", offered)
        self.assertIn("C01401", offered)

    def test_stereoisomers_both_on_the_map_are_escalated(self):
        """L- and D-Serine are both real and both drawn. Not a rule's call."""
        decision = ranker.rankCompoundSet(
            compoundSet("Serine", [("C00065", "L-Serine"), ("C00740", "D-Serine")]),
            onMapIDs={"C00065", "C00740"}, organismLabel="mmu")
        self.assertEqual("residual", decision["status"])


class SpeciesFilterSafetyTest(unittest.TestCase):

    def test_an_empty_on_map_set_skips_the_filter_rather_than_emptying_everything(self):
        """A missing organism database must weaken ranking, never narrow it.

        Treating "I could not read the pathways" as "no compound is on any
        pathway" would make every filtered set collapse to zero candidates.
        """
        decision = ranker.rankCompoundSet(
            compoundSet("Serine", [("C00065", "L-Serine"), ("C00740", "D-Serine")]),
            onMapIDs=frozenset())
        self.assertEqual("residual", decision["status"])
        self.assertEqual(2, len(decision["candidates"]))

    def test_the_filter_narrows_the_prompt_when_it_cannot_decide(self):
        """Three matches, two on the map: the model is asked about those two."""
        decision = ranker.rankCompoundSet(
            compoundSet("Glucose",
                        [("C00031", "Glucose"), ("C00221", "beta-D-Glucose"),
                         ("C00267", "alpha-D-Glucose"), ("C00936", "Off-map glucose")]),
            onMapIDs={"C00031", "C00221", "C00267"})
        self.assertEqual("residual", decision["status"])
        offered = set(c["keggID"] for c in decision["candidates"])
        self.assertEqual({"C00031", "C00221", "C00267"}, offered)


class CandidateCollapsingTest(unittest.TestCase):

    def test_names_are_not_split_on_commas(self):
        """6,581 KEGG names contain a comma; C04137 is "Arginine, N2-..., L-".

        Splitting it produced a synonym "Arginine", which scored as a direct hit
        for an input of "L-arginine" and pulled an unrelated compound into the
        choice -- turning a set the ranker could settle into one it could not.
        """
        found = compoundSet("L-arginine", [("C00062", "L-Arginine")],
                            [("C04137", "Arginine, N2-(1-carboxyethyl)-, L-")])
        byID = ranker.candidatesByKeggID(found)

        self.assertIn("Arginine, N2-(1-carboxyethyl)-, L-", byID["C04137"]["names"])
        self.assertFalse(byID["C04137"]["isMain"])

        decision = ranker.rankCompoundSet(found, onMapIDs=set())
        self.assertEqual("resolved", decision["status"])
        self.assertEqual("C00062", decision["keggID"])

    def test_main_comes_from_the_mapper_bucket_not_from_a_rescore(self):
        """The cards are drawn from the buckets, so the ranker must use them.

        Here the stored name scores poorly against the title, but the mapper put
        it in mainCompounds. Rescoring would call it "other", disagree with the
        card the user is looking at, and resolve a set they can still edit.
        """
        found = FoundFeature("")
        found.setTitle("Glucose")
        odd = Compound("C00031")
        odd.setName("Grape sugar")          # a real C00031 synonym, distant name
        found.addMainCompound(odd)
        other = Compound("C00092")
        other.setName("D-Glucose 6-phosphate")
        found.addOtherCompound(other)

        byID = ranker.candidatesByKeggID(found)
        self.assertTrue(byID["C00031"]["isMain"])
        self.assertFalse(byID["C00092"]["isMain"])

    def test_synonyms_are_ordered_by_closeness_to_the_input(self):
        """C00065 introduced itself as "L-2-Amino-3-hydroxypropionic acid"."""
        found = compoundSet("Serine", [("C00065", "L-Serine")])
        byID = ranker.candidatesByKeggID(found, synonymsByID={
            "C00065": ["L-2-Amino-3-hydroxypropionic acid", "L-Serine", "L-3-Hydroxy-alanine"]})
        self.assertEqual("L-Serine", byID["C00065"]["names"][0])

    def test_accession_and_chebi_pseudonyms_are_dropped(self):
        found = compoundSet("Glucose", [("C00031", "Glucose")])
        byID = ranker.candidatesByKeggID(found, synonymsByID={
            "C00031": ["C00031", "chebi:4167", "4167", "D-Glucose"]})
        self.assertEqual(["Glucose", "D-Glucose"], byID["C00031"]["names"])

    def test_a_candidate_is_never_left_without_a_name(self):
        """Dropping pseudonyms must not empty a candidate that has only those."""
        found = compoundSet("C00031", [("C00031", "C00031")])
        byID = ranker.candidatesByKeggID(found)
        self.assertEqual(["C00031"], byID["C00031"]["names"])

    def test_the_prompt_pool_is_capped(self):
        mains = [("C%05d" % n, "Glucose variant %d" % n) for n in range(40)]
        decision = ranker.rankCompoundSet(compoundSet("Glucose", mains), onMapIDs=set())
        self.assertEqual("residual", decision["status"])
        self.assertEqual(ranker.MAX_CANDIDATES_IN_PROMPT, len(decision["candidates"]))


class ReopenedJobShapeTest(unittest.TestCase):
    """A job reopened from MongoDB carries a different shape entirely.

    ``FoundFeatureDAO.findAll`` is ``FeatureDAO.findAll``, which constructs a
    plain ``Feature("")`` whatever the subclass; parseBSON then setattrs the
    stored document onto it. The result HAS ``title`` and ``mainCompounds``, but
    the candidates are raw dicts and ``getMainCompounds()`` does not exist.

    Measured against a running server: pressing "Choose for me" on a job opened
    by its ?jobID= URL failed with "'Feature' object has no attribute
    'getMainCompounds'". The in-memory step-1 path had hidden it completely.
    """

    def _storedRecord(self):
        return {
            "ID": "", "title": "Alanine",
            "mainCompounds": [
                {"ID": "C01401", "name": "Alanine", "similarity": 1.0},
                {"ID": "C00041", "name": "L-Alanine", "similarity": 0.9},
                {"ID": "C00133", "name": "D-Alanine", "similarity": 0.9}],
            "otherCompounds": [
                {"ID": "C00099", "name": "beta-Alanine", "similarity": 0.5}],
        }

    def test_a_stored_record_is_ranked_like_a_live_one(self):
        [coerced] = ranker.coerceCompoundSets([self._storedRecord()])
        decision = ranker.rankCompoundSet(
            coerced, onMapIDs={"C01401", "C00041", "C00133"}, organismLabel="mmu")

        self.assertEqual("residual", decision["status"])
        offered = set(c["keggID"] for c in decision["candidates"])
        self.assertEqual({"C01401", "C00041", "C00133"}, offered)

    def test_the_bucket_split_survives_the_round_trip(self):
        """beta-Alanine was an "other"; it must not become a main candidate."""
        [coerced] = ranker.coerceCompoundSets([self._storedRecord()])
        byID = ranker.candidatesByKeggID(coerced)
        self.assertFalse(byID["C00099"]["isMain"])
        self.assertTrue(byID["C00041"]["isMain"])

    def test_a_live_foundfeature_is_passed_through_untouched(self):
        live = compoundSet("Serine", [("C00065", "L-Serine")])
        [coerced] = ranker.coerceCompoundSets([live])
        self.assertIs(live, coerced)

    def test_an_object_with_attributes_rather_than_a_dict_also_works(self):
        """Feature.parseBSON setattrs, so the record arrives as an object."""
        class StoredFeature(object):
            pass

        record = StoredFeature()
        record.ID = ""
        record.title = "Serine"
        record.mainCompounds = [{"ID": "C00065", "name": "L-Serine"}]
        record.otherCompounds = []

        [coerced] = ranker.coerceCompoundSets([record])
        self.assertEqual("Serine", coerced.getTitle())
        self.assertEqual(["C00065"], [c.getID() for c in coerced.getMainCompounds()])

    def test_an_empty_list_is_not_an_error(self):
        self.assertEqual([], ranker.coerceCompoundSets(None))
        self.assertEqual([], ranker.coerceCompoundSets([]))


class NeedsDisambiguationTest(unittest.TestCase):
    """Mirrors PA_Step2CompoundSetView.needsDisambiguation."""

    def test_a_set_with_no_candidates_draws_no_card(self):
        decision = ranker.rankCompoundSet(compoundSet("Nothing", []), onMapIDs=set())
        self.assertEqual("skip", decision["status"])

    def test_a_lone_selected_candidate_draws_no_card(self):
        found = compoundSet("Urea", [("C00086", "Urea")])
        found.getMainCompounds()[0].selected = True
        decision = ranker.rankCompoundSet(found, onMapIDs=set())
        self.assertEqual("skip", decision["status"])

    def test_a_lone_unselected_candidate_still_draws_a_card(self):
        """The cross-box de-duplicator can leave a lone candidate unticked."""
        found = compoundSet("Alanine", [("C00041", "L-Alanine")])
        found.getMainCompounds()[0].selected = False
        decision = ranker.rankCompoundSet(found, onMapIDs=set())
        self.assertEqual("resolved", decision["status"])


class PartitionTest(unittest.TestCase):

    def test_sets_land_in_the_right_three_buckets(self):
        resolved, residual, skipped = ranker.partitionCompoundSets(
            [compoundSet("Glyceric acid", [("C00258", "Glyceric acid")],
                         [("C00197", "3-Phospho-D-glycerate")]),
             compoundSet("Serine", [("C00065", "L-Serine"), ("C00740", "D-Serine")]),
             compoundSet("Nothing", [])],
            onMapIDs={"C00065", "C00740"})

        self.assertEqual(["Glyceric acid"], [d["title"] for d in resolved])
        self.assertEqual(["Serine"], [d["title"] for d in residual])
        self.assertEqual(["Nothing"], [d["title"] for d in skipped])


if __name__ == "__main__":
    unittest.main(verbosity=2)
