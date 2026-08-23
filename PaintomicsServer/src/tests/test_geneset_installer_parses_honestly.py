#!/usr/bin/env python3
"""The gene-set installer refuses garbage and propagates the true path.

Why this exists
---------------
The installer audit's systemic finding: `curl` without `-f` plus
`mongoimport --drop` turns a 4xx HTML body into the database, and a 200
serving an SPA page defeats `-f` too. This installer verifies CONTENT. The
parsing rules that carry biology are pinned here: NOT-qualified annotations
are skipped, obsolete terms are skipped, alt_ids resolve, and an annotation
to a child term reaches every ancestor (the true-path rule) BEFORE storage.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_geneset_installer_parses_honestly
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

import installGeneSets as I                     # noqa: E402
from src.classes.AIInterpret.gene_set_store import from_gmt  # noqa: E402

OBO = """format-version: 1.2

[Term]
id: GO:0000001
name: root process
namespace: biological_process

[Term]
id: GO:0000002
name: middle process
namespace: biological_process
is_a: GO:0000001 ! root process

[Term]
id: GO:0000003
name: leaf process
namespace: biological_process
alt_id: GO:0999999
relationship: part_of GO:0000002 ! middle process

[Term]
id: GO:0000009
name: dead process
namespace: biological_process
is_obsolete: true

[Typedef]
id: part_of
name: part of
"""

GAF = "\n".join([
    "!gaf-version: 2.2",
    "\t".join(["MGI", "MGI:1", "Casp3", "enables", "GO:0000003", "PMID:1",
               "IDA", "", "P", "caspase 3", "", "protein", "taxon:10090",
               "20240101", "MGI"]),
    "\t".join(["MGI", "MGI:2", "Trp53", "NOT|enables", "GO:0000003",
               "PMID:2", "IDA", "", "P", "p53", "", "protein",
               "taxon:10090", "20240101", "MGI"]),
    "\t".join(["MGI", "MGI:3", "Bax", "enables", "GO:0999999", "PMID:3",
               "IDA", "", "P", "bax", "", "protein", "taxon:10090",
               "20240101", "MGI"]),
])


class OboTest(unittest.TestCase):

    def test_terms_parents_and_alt_ids(self):
        terms, alt = I.parse_obo(OBO)
        self.assertIn("GO:0000003", terms)
        self.assertEqual(terms["GO:0000003"]["parents"], ["GO:0000002"])
        self.assertEqual(alt["GO:0999999"], "GO:0000003")

    def test_an_obsolete_term_is_not_a_term(self):
        terms, _ = I.parse_obo(OBO)
        self.assertNotIn("GO:0000009", terms)


class GafTest(unittest.TestCase):

    def test_not_qualified_rows_are_skipped(self):
        rows = I.parse_gaf(GAF)
        symbols = {s for s, _g, _a in rows}
        self.assertIn("CASP3", symbols)
        self.assertNotIn("TRP53", symbols)


class PropagationTest(unittest.TestCase):

    def test_true_path_reaches_every_ancestor(self):
        terms, alt = I.parse_obo(OBO)
        sets, dropped = I.propagate(terms, alt, I.parse_gaf(GAF))
        self.assertIn("CASP3", sets["GO:0000003"])
        self.assertIn("CASP3", sets["GO:0000002"])     # part_of edge
        self.assertIn("CASP3", sets["GO:0000001"])     # is_a edge above it
        self.assertEqual(dropped, 0)

    def test_an_alt_id_annotation_lands_on_the_canonical_term(self):
        terms, alt = I.parse_obo(OBO)
        sets, _ = I.propagate(terms, alt, I.parse_gaf(GAF))
        self.assertIn("BAX", sets["GO:0000003"])


class ContentGuardTest(unittest.TestCase):

    def test_html_is_recognised_as_not_data(self):
        self.assertTrue(I.looks_like_html(b"<!DOCTYPE html><html>..."))
        self.assertTrue(I.looks_like_html(b"  <html lang='en'>"))
        self.assertFalse(I.looks_like_html(b"format-version: 1.2"))


class GmtTest(unittest.TestCase):

    def test_gmt_round_trips_into_a_collection(self):
        text = "HALLMARK_X\tdesc\tFos\tJun\nSHORT\td\tA\nH2\t\tMYC\tTP53\tEGFR\n"
        col = from_gmt(text, "Hallmark")
        self.assertEqual(sorted(col.sets), ["H2", "HALLMARK_X", "SHORT"])
        self.assertEqual(col.sets["HALLMARK_X"]["genes"], {"FOS", "JUN"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
