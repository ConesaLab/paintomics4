#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tier 1 over the shipped STATegra metabolomics example, against real KEGG.

The unit tests build compound sets by hand. This one builds them the way step 1
does -- the same substring query against `global-paintomics.kegg_compounds`, the
same similarity split into main/other -- and runs the ranker over the result, so
the rules are exercised against the actual shape of the data rather than against
a fixture that agrees with them by construction.

It asserts named outcomes rather than a total, because a KEGG reinstall moves
totals and none of these compounds. The one count it does check is a floor: if
the deterministic tier ever settles nothing, the feature has become a pure LLM
call and the whole design has quietly inverted.

Needs MongoDB with `global-paintomics` and `mmu-paintomics` installed, and
reaches no gateway at all. Skipped when either database is missing.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.classes.Feature import Compound
from src.classes.FoundFeature import FoundFeature
from src.classes.CompoundDisambiguation import ranker
from src.common.CompoundNameSimilarity import MAIN_SIMILARITY_THRESHOLD

VALUES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "examplefiles", "datasets",
    "08-stategra-multiomics", "data", "metabolomics_values.tab")

ORGANISM = "mmu"
MAX_COMPOUND_MATCHES = 500


def _mongo():
    """The client, or None when this machine has no usable database."""
    try:
        import pymongo
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        client = pymongo.MongoClient(MONGODB_HOST, MONGODB_PORT,
                                     serverSelectionTimeoutMS=2000)
        names = client.list_database_names()
        if "global-paintomics" not in names or (ORGANISM + "-paintomics") not in names:
            return None
        if client[ORGANISM + "-paintomics"]["kegg"].estimated_document_count() == 0:
            return None
        return client
    except Exception:
        return None


CLIENT = _mongo()


@unittest.skipIf(CLIENT is None,
                 "needs MongoDB with global-paintomics and %s-paintomics" % ORGANISM)
class RankerOnExampleDataTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        compounds = CLIENT["global-paintomics"]["kegg_compounds"]

        cls.onMapIDs = frozenset(
            compound["id"]
            for pathway in CLIENT[ORGANISM + "-paintomics"]["kegg"].find({}, {"compounds.id": 1})
            for compound in (pathway.get("compounds") or [])
            if compound.get("id"))

        with open(os.path.abspath(VALUES_FILE), encoding="utf-8") as handle:
            cls.inputNames = [line.split("\t")[0].strip() for line in handle
                              if line.strip() and not line.startswith("#")]

        cls.sets = []
        for name in cls.inputNames:
            compoundSet = cls._buildCompoundSet(compounds, name)
            if compoundSet is not None:
                cls.sets.append(compoundSet)

        synonyms = ranker.loadCompoundSynonyms(ranker.collectKeggIDs(cls.sets))
        cls.resolved, cls.residual, cls.skipped = ranker.partitionCompoundSets(
            cls.sets, cls.onMapIDs, ORGANISM, synonyms)

        cls.resolvedByTitle = dict((d["title"], d) for d in cls.resolved)
        cls.residualByTitle = dict((d["title"], d) for d in cls.residual)

    @staticmethod
    def _buildCompoundSet(compounds, name):
        """Reproduce mapCompoundsIdentifiers for one input name."""
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        hits = list(compounds.find({"name": {"$regex": pattern}})
                    .limit(MAX_COMPOUND_MATCHES + 1))
        if len(hits) > MAX_COMPOUND_MATCHES:
            exact = re.compile("^" + re.escape(name) + "$", re.IGNORECASE)
            hits = list(compounds.find({"name": {"$regex": exact}}).limit(MAX_COMPOUND_MATCHES))
        if not hits:
            return None

        found = FoundFeature("")
        found.setTitle(name)
        for hit in hits:
            candidate = Compound(hit["id"])
            candidate.setName(hit["name"])
            if candidate.calculateSimilarity(name) >= MAIN_SIMILARITY_THRESHOLD:
                found.addMainCompound(candidate)
            else:
                found.addOtherCompound(candidate)
        return found

    # ------------------------------------------------------------------
    # The deterministic tier still carries real weight
    # ------------------------------------------------------------------
    def test_the_rules_settle_a_substantial_share_without_a_model(self):
        """A floor, not a total: KEGG reinstalls move totals, not this property.

        Measured when written: 31 settled, 18 escalated, 2 with no card, of 51
        sets built from 58 input names.
        """
        self.assertGreater(len(self.resolved), len(self.sets) // 2,
                           "the deterministic tier settled %d of %d sets; if this "
                           "has collapsed, the feature has become a pure LLM call"
                           % (len(self.resolved), len(self.sets)))
        self.assertGreater(len(self.residual), 0,
                           "nothing was escalated, so either the data changed or a "
                           "rule started deciding things it should not")

    # ------------------------------------------------------------------
    # Named outcomes
    # ------------------------------------------------------------------
    def test_a_clean_single_match_is_settled(self):
        self.assertIn("Pyruvic acid", self.resolvedByTitle)
        self.assertEqual("C00022", self.resolvedByTitle["Pyruvic acid"]["keggID"])

    def test_the_comma_in_a_kegg_name_does_not_break_l_arginine(self):
        """C04137 is stored as "Arginine, N2-(1-carboxyethyl)-, L-".

        Splitting synonyms on commas invented "Arginine", scored it as a direct
        hit for "L-arginine", and turned a set the rules can settle into one
        they cannot. Real data is the only place this shows up.
        """
        self.assertIn("L-arginine", self.resolvedByTitle)
        self.assertEqual("C00062", self.resolvedByTitle["L-arginine"]["keggID"])

    def test_alanine_is_escalated_and_not_resolved_to_the_unspecified_form(self):
        """The trap: C01401 is literally named "Alanine" AND is on mouse maps.

        Neither an exact-name rule nor the species filter can save this one, so
        it must reach the model with the real alternatives still in the pool.
        """
        self.assertNotIn("Alanine", self.resolvedByTitle)
        self.assertIn("Alanine", self.residualByTitle)

        offered = set(candidate["keggID"]
                      for candidate in self.residualByTitle["Alanine"]["candidates"])
        self.assertIn("C00041", offered, "L-Alanine must remain choosable")
        self.assertIn("C01401", offered, "the unspecified form must not be hidden")

    def test_glucose_reaches_the_model_with_only_the_on_map_forms(self):
        """113 candidates in, three out: the parent and its two anomers."""
        self.assertIn("Glucose", self.residualByTitle)
        offered = set(candidate["keggID"]
                      for candidate in self.residualByTitle["Glucose"]["candidates"])
        self.assertEqual({"C00031", "C00221", "C00267"}, offered)

    def test_the_species_filter_drops_the_off_map_generic_lactic_acid(self):
        """C01432 is literally named "Lactic acid" and is on no mouse pathway.

        The name still has to be escalated -- L- and D-lactate are both drawn
        and both real -- but the generic form must not be among the choices,
        because selecting it would contribute nothing to any mouse pathway.
        """
        decision = self.residualByTitle.get("Lactic acid")
        self.assertIsNotNone(decision, "Lactic acid should still need a decision")

        offered = set(candidate["keggID"] for candidate in decision["candidates"])
        self.assertNotIn("C01432", offered,
                         "an off-map generic form was offered as a real choice")
        self.assertIn("C00186", offered, "L-lactate must remain choosable")

    # ------------------------------------------------------------------
    # Candidate hygiene
    # ------------------------------------------------------------------
    def test_no_candidate_is_offered_under_an_accession_or_chebi_name(self):
        for decision in self.residual:
            for candidate in decision["candidates"]:
                for name in candidate["names"]:
                    self.assertFalse(name.lower().startswith("chebi:"),
                                     "%s offered as %r" % (candidate["keggID"], name))
                    self.assertFalse(name.isdigit(),
                                     "%s offered as %r" % (candidate["keggID"], name))

    def test_every_escalated_set_offers_at_least_two_real_choices(self):
        """A one-candidate 'choice' is a rule that failed to fire."""
        for decision in self.residual:
            self.assertGreaterEqual(
                len(decision["candidates"]), 2,
                "%r was escalated with %d candidate(s)"
                % (decision["title"], len(decision["candidates"])))

    def test_the_prompt_pool_never_exceeds_its_cap(self):
        for decision in self.residual:
            self.assertLessEqual(len(decision["candidates"]),
                                 ranker.MAX_CANDIDATES_IN_PROMPT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
