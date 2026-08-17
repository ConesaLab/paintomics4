#!/usr/bin/env python3
"""Reactome/MapMan matched genes must display gene symbols, not input IDs.

For every organism whose Reactome (or MapMan) entry in
src/conf/organismDB.py maps both the ID database and the "symbol" database
to the same xref table (e.g. mmu Reactome: reactome_gene_id twice), the
symbol pass in mapFeatureIdentifiers was a no-op: the symbols cache ended
up keyed by input name, the featureID lookup missed, and the matched clone
kept the raw input identifier as its display name. A full STATegra job
stored 8,396 of 25,870 gene features named "ENSMUSG..." — every one of
them a Reactome match — and the Reactome pathway views painted Ensembl IDs
on every gene box while the KEGG views showed symbols.

The fix resolves symbols for such databases against a real symbol database
of the organism (mmu: refseq_gene_symbol); the xref mates graph links the
Reactome gene IDs to it (GNAI3 -> Gnai3).

Needs the local MongoDB with the mmu species database installed.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_reactome_matches_get_symbol_names
"""
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Feature import Gene
from src.common.FeatureNamesToKeggIDsMapper import (
    mapFeatureIdentifiers, resolveDatabaseIds)


ORGANISM = "mmu"
DATABASES = ["KEGG", "Reactome"]
# Ensembl gene IDs with a known refseq_gene_symbol translation. The first
# three have the symbol in their Reactome gene ID's xref group; the last
# three only carry it in the INPUT name's group (GNA12/SDHD/DLAT have no
# refseq_gene_symbol mate), which exercises the per-name fallback.
INPUTS = {
    "ENSMUSG00000000001": "Gnai3",
    "ENSMUSG00000000028": "Cdc45",
    "ENSMUSG00000000184": "Ccnd2",
    "ENSMUSG00000000149": "Gna12",
    "ENSMUSG00000000171": "Sdhd",
    "ENSMUSG00000000168": "Dlat",
}


def mongoAvailable():
    try:
        from pymongo import MongoClient
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        client = MongoClient(MONGODB_HOST, MONGODB_PORT,
                             serverSelectionTimeoutMS=2000)
        names = client.list_database_names()
        client.close()
        return (ORGANISM + "-paintomics") in names
    except Exception:
        return False


@unittest.skipUnless(mongoAvailable(), "local MongoDB with mmu not available")
class ReactomeMatchesGetSymbolNames(unittest.TestCase):

    def mapInputs(self):
        featureList = []
        for name in INPUTS:
            gene = Gene("")
            gene.setName(name)
            featureList.append(gene)
        matched, notMatched, found = [], [], []
        mapFeatureIdentifiers("TEST" + uuid.uuid4().hex[:8], ORGANISM,
                              DATABASES, featureList, matched, notMatched,
                              found, "genes")
        return matched

    def test_symbol_database_ids_differ_from_id_database_ids(self):
        """resolveDatabaseIds must never hand a worker the identity mapping."""
        idDBs, symbolDBs = resolveDatabaseIds(ORGANISM, DATABASES)
        self.assertNotEqual(
            idDBs["Reactome"], symbolDBs["Reactome"],
            "Reactome symbol lookups run against the ID database itself; "
            "the symbol pass is a no-op and matched genes keep their raw "
            "input identifier as display name.")
        self.assertEqual(
            symbolDBs["Reactome"], symbolDBs["KEGG"],
            "Reactome must borrow KEGG's gene-symbol table, not whichever "
            "symbol database the organism config happens to list first.")

    def test_reactome_clones_are_named_with_the_gene_symbol(self):
        matched = self.mapInputs()
        self.assertTrue(matched, "no features matched; mmu data missing?")
        reactomeClones = [f for f in matched
                          if "Reactome" in str(f.getMatchingDB())]
        self.assertTrue(reactomeClones,
                        "no Reactome matches; mmu Reactome data missing?")
        badlyNamed = sorted({f.getName() for f in reactomeClones
                             if f.getName().startswith("ENSMUSG")})
        self.assertEqual(
            badlyNamed, [],
            "Reactome-matched clones still display raw input IDs: %s"
            % badlyNamed)

    def test_clone_names_are_the_expected_symbols(self):
        """Every clone of the three inputs must carry one of their symbols."""
        matched = self.mapInputs()
        expected = {symbol.lower() for symbol in INPUTS.values()}
        actual = {feature.getName().lower() for feature in matched}
        self.assertTrue(
            actual and actual.issubset(expected),
            "matched clones are named %s, expected only symbols from %s"
            % (sorted(actual), sorted(expected)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
