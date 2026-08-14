#!/usr/bin/env python3
"""PMID -> PMCID conversion must survive the API answering with integers.

Measured across every stored AI job on this machine: 0 papers with full text
out of hundreds retrieved, on a pipeline that carries a three-tier full-text
fetch. The tiers were fine; nothing ever reached them. The NCBI ID Converter
returns each record's "pmid" as a JSON *number*, and convert_pmids_to_pmcids
seeded its result dict with the caller's *string* PMIDs -- so the assignment
added a new integer key beside the string key it was meant to update:

    {'32015508': None, 32015508: 'PMC7094943'}

fetch_papers then looked the string up, found None, and logged
"Tier 3 (abstract only) -- no PMCID" for every paper ever fetched. The AI
therefore only ever read abstracts, exactly as reported.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_pubmed_pmcid_conversion
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.pubmed_client import PubMedClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class PmcidConversionTest(unittest.TestCase):

    def _client_answering(self, records):
        client = PubMedClient()
        client._request_with_retry = (
            lambda *args, **kwargs: _FakeResponse({"records": records}))
        return client

    def test_integer_pmids_in_the_response_update_the_string_keys(self):
        client = self._client_answering(
            [{"pmid": 32015508, "pmcid": "PMC7094943"}])
        result = client.convert_pmids_to_pmcids(["32015508"])
        self.assertEqual(result, {"32015508": "PMC7094943"})

    def test_string_pmids_in_the_response_still_work(self):
        client = self._client_answering(
            [{"pmid": "26509449", "pmcid": "PMC4624794"}])
        result = client.convert_pmids_to_pmcids(["26509449"])
        self.assertEqual(result, {"26509449": "PMC4624794"})

    def test_a_paper_without_a_pmc_deposit_stays_none(self):
        client = self._client_answering(
            [{"pmid": 11111111}, {"pmid": 22222222, "pmcid": "PMC2"}])
        result = client.convert_pmids_to_pmcids(["11111111", "22222222"])
        self.assertEqual(result, {"11111111": None, "22222222": "PMC2"})

    def test_no_stray_integer_keys_are_left_behind(self):
        client = self._client_answering(
            [{"pmid": 32015508, "pmcid": "PMC7094943"}])
        result = client.convert_pmids_to_pmcids(["32015508"])
        self.assertTrue(all(isinstance(k, str) for k in result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
