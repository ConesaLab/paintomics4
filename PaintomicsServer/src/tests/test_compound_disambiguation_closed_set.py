#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The closed-set guarantee: a model answer is applied only if it was offered.

Step 2's "Choose for me" asks an LLM which KEGG compound an ambiguous metabolite
name meant. The whole safety property of that feature is one sentence:

    an answer is applied only if it names a KEGG id that was in THAT input
    name's own candidate list.

Everything else -- an invented id, an id lifted from a different input name in
the same batch, a name nobody asked about, an answer given twice, a
low-confidence guess -- must leave the user's ticks alone. That matters more
here than in most places because a wrong compound has no symptom: the run
succeeds, the pathways are drawn, and the analysis is simply about a different
metabolite than the one that was measured.

These tests never reach a gateway. validateChoice and applyChoices are pure
functions over one reply and the question it claims to answer, which is exactly
why the guarantee can be pinned without a network, a job or a key.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.classes.CompoundDisambiguation import resolver


def decision(title, *keggIDs):
    return {"title": title, "status": "residual", "tier": "residual",
            "candidates": [{"keggID": keggID, "names": [keggID + " name"],
                            "similarity": 0.9, "isMain": True}
                           for keggID in keggIDs]}


ALANINE = decision("Alanine", "C00041", "C00133", "C00099", "C01401")
SERINE = decision("Serine", "C00065", "C00740")


class ValidateChoiceTest(unittest.TestCase):

    def test_a_candidate_from_the_list_is_accepted(self):
        verdict = resolver.validateChoice(
            {"kegg_id": "C00041", "confidence": "high", "reason": "mouse"}, ALANINE)
        self.assertEqual("accepted", verdict["outcome"])
        self.assertEqual("C00041", verdict["keggID"])

    def test_an_invented_id_is_rejected(self):
        """The failure this whole design exists to make impossible."""
        verdict = resolver.validateChoice(
            {"kegg_id": "C99999", "confidence": "high", "reason": "looks right"}, ALANINE)
        self.assertEqual("rejected", verdict["outcome"])
        self.assertIsNone(verdict["keggID"])

    def test_an_id_from_another_input_name_is_rejected(self):
        """C00065 is a real KEGG compound and a real candidate -- for Serine.

        Answering it for "Alanine" is the batching-specific failure: every set
        in a batch is in the same prompt, so a model CAN reach across. Being a
        valid id somewhere in the batch must not make it a valid answer here.
        """
        verdict = resolver.validateChoice(
            {"kegg_id": "C00065", "confidence": "high", "reason": "serine"}, ALANINE)
        self.assertEqual("rejected", verdict["outcome"])

    def test_the_abstain_token_abstains(self):
        verdict = resolver.validateChoice(
            {"kegg_id": "ABSTAIN", "confidence": "high", "reason": "ambiguous"}, ALANINE)
        self.assertEqual("abstained", verdict["outcome"])
        self.assertIsNone(verdict["keggID"])

    def test_an_empty_id_abstains(self):
        verdict = resolver.validateChoice(
            {"kegg_id": "", "confidence": "high", "reason": ""}, ALANINE)
        self.assertEqual("abstained", verdict["outcome"])

    def test_low_confidence_abstains_even_on_a_legal_id(self):
        """Low confidence is the model saying it does not know.

        Applying it anyway would turn "I am guessing" into a tick the user has
        no reason to re-examine.
        """
        verdict = resolver.validateChoice(
            {"kegg_id": "C00041", "confidence": "low", "reason": "not sure"}, ALANINE)
        self.assertEqual("abstained", verdict["outcome"])
        self.assertIsNone(verdict["keggID"])

    def test_a_missing_confidence_is_not_treated_as_low(self):
        """A gateway that dropped response_format still returns usable answers."""
        verdict = resolver.validateChoice({"kegg_id": "C00041", "reason": "mouse"}, ALANINE)
        self.assertEqual("accepted", verdict["outcome"])
        self.assertEqual("medium", verdict["confidence"])


class ApplyChoicesTest(unittest.TestCase):

    def test_answers_are_matched_by_name_not_by_position(self):
        """A reordered reply must not shift answers onto the wrong metabolite.

        This is the one failure mode in the feature that produces confident,
        plausible, uniformly wrong output: every tick lands on a real compound,
        and every one belongs to a different input name.
        """
        accepted, abstained, rejected = resolver.applyChoices(
            [ALANINE, SERINE],
            [{"input_name": "Serine", "kegg_id": "C00065", "confidence": "high", "reason": "L"},
             {"input_name": "Alanine", "kegg_id": "C00041", "confidence": "high", "reason": "L"}])

        self.assertEqual([], rejected)
        picks = dict((entry["title"], entry["keggID"]) for entry in accepted)
        self.assertEqual({"Alanine": "C00041", "Serine": "C00065"}, picks)

    def test_a_set_the_model_ignored_becomes_an_abstention(self):
        accepted, abstained, rejected = resolver.applyChoices(
            [ALANINE, SERINE],
            [{"input_name": "Alanine", "kegg_id": "C00041", "confidence": "high", "reason": ""}])

        self.assertEqual(["Alanine"], [entry["title"] for entry in accepted])
        self.assertEqual(["Serine"], [entry["title"] for entry in abstained])

    def test_an_unknown_input_name_is_rejected(self):
        accepted, abstained, rejected = resolver.applyChoices(
            [ALANINE],
            [{"input_name": "Tryptophan", "kegg_id": "C00078", "confidence": "high", "reason": ""}])

        self.assertEqual([], accepted)
        self.assertEqual(["Tryptophan"], [entry["title"] for entry in rejected])
        # ...and Alanine is still reported as undecided rather than dropped.
        self.assertEqual(["Alanine"], [entry["title"] for entry in abstained])

    def test_the_same_name_answered_twice_keeps_only_the_first(self):
        accepted, abstained, rejected = resolver.applyChoices(
            [ALANINE],
            [{"input_name": "Alanine", "kegg_id": "C00041", "confidence": "high", "reason": ""},
             {"input_name": "Alanine", "kegg_id": "C00133", "confidence": "high", "reason": ""}])

        self.assertEqual(["C00041"], [entry["keggID"] for entry in accepted])
        self.assertEqual(1, len(rejected))

    def test_matching_tolerates_case_and_surrounding_space(self):
        accepted, _, rejected = resolver.applyChoices(
            [ALANINE],
            [{"input_name": "  alanine ", "kegg_id": "C00041", "confidence": "high", "reason": ""}])
        self.assertEqual([], rejected)
        self.assertEqual(["C00041"], [entry["keggID"] for entry in accepted])


class ParseChoicesTest(unittest.TestCase):

    def test_a_plain_schema_reply_parses(self):
        text = '{"choices": [{"input_name": "Alanine", "kegg_id": "C00041", ' \
               '"confidence": "high", "reason": "mouse"}]}'
        self.assertEqual(1, len(resolver.parseChoices(text)))

    def test_a_fenced_reply_parses(self):
        """Gateways that ignore response_format wrap JSON in markdown."""
        text = '```json\n{"choices": [{"input_name": "A", "kegg_id": "C1", ' \
               '"confidence": "high", "reason": ""}]}\n```'
        self.assertEqual(1, len(resolver.parseChoices(text)))

    def test_json_buried_in_prose_parses(self):
        text = 'Here you go:\n{"choices": [{"input_name": "A", "kegg_id": "C1", ' \
               '"confidence": "high", "reason": ""}]}\nHope that helps.'
        self.assertEqual(1, len(resolver.parseChoices(text)))

    def test_unparseable_text_yields_nothing_rather_than_raising(self):
        """An empty list becomes a batch of abstentions, which is safe.

        Raising here would lose the whole batch to an error the user cannot act
        on; returning junk would be worse still.
        """
        for text in ("", None, "I could not do that", "{not json"):
            self.assertEqual([], resolver.parseChoices(text))

    def test_non_object_entries_are_dropped(self):
        text = '{"choices": ["C00041", {"input_name": "A", "kegg_id": "C1", ' \
               '"confidence": "high", "reason": ""}]}'
        self.assertEqual(1, len(resolver.parseChoices(text)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
