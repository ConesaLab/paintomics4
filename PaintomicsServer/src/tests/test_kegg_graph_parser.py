#!/usr/bin/env python3
"""The KGML parser must attribute subtypes and reaction headers correctly.

The R parser this replaces did two things that a real XML parse makes
impossible, both measured over all 364 mmu KGML files:

  * `GalaxyNetworkFunctionsv2.R:96` collected EVERY <subtype> in the pathway into
    one list and `:121` indexed it by RELATION number. Correct only when every
    relation has exactly one subtype. 2,885 mmu relations have two and 285 have
    none, so once drift starts every later relation in that pathway is
    mis-zipped: 5,963 of 21,120 subtypes wrong (28.2%), 194 of 364 pathways.
  * `:192/:234/:262` read reaction id/name/type as tokens 3/5/7 of the
    stringified node. A reaction whose name holds two ids shifts the type one
    token right, yielding the literal attribute NAME "type": 3,083 of 22,038
    reaction rows corrupted (14.0%).

FIXTURE is built so the old behaviour and the correct behaviour differ. Its
relations carry 2, 1, 0 and 1 subtypes. Index-zipping gives relation 2 the
SECOND subtype ("phosphorylation") where its own child says "expression", so
`test_subtype_is_read_from_its_own_relation` fails against the old algorithm and
passes against a correct one.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph.parser import parse_pathway, parse_directory

FIXTURE = """<?xml version="1.0"?>
<pathway name="path:tst00001" org="tst" number="00001">
  <entry id="1" name="tst:100 tst:101" type="gene"/>
  <entry id="2" name="tst:200" type="gene"/>
  <entry id="3" name="cpd:C00001" type="compound"/>
  <entry id="4" name="cpd:C00002" type="compound"/>
  <entry id="5" name="undefined" type="group">
    <component id="1"/>
    <component id="2"/>
  </entry>
  <entry id="6" name="tst:300" type="gene"/>
  <entry id="7" name="path:tst00002" type="map"/>
  <entry id="8" name="tst:400" type="gene"/>
  <relation entry1="1" entry2="2" type="PPrel">
    <subtype name="activation" value="--&gt;"/>
    <subtype name="phosphorylation" value="+p"/>
  </relation>
  <relation entry1="2" entry2="6" type="GErel">
    <subtype name="expression" value="--&gt;"/>
  </relation>
  <relation entry1="6" entry2="7" type="maplink"/>
  <relation entry1="5" entry2="8" type="PPrel">
    <subtype name="inhibition" value="--|"/>
  </relation>
  <reaction id="6" name="rn:R00001 rn:R00002" type="irreversible">
    <substrate id="3" name="cpd:C00001"/>
    <product id="4" name="cpd:C00002"/>
  </reaction>
</pathway>
"""


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="paintomics-kgml-")
        self.path = os.path.join(self.dir, "tst00001.kgml")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(FIXTURE)
        self.edges, self.types = parse_pathway(self.path)
        self.by_pair = {(e.a, e.b): e for e in self.edges}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_subtype_is_read_from_its_own_relation(self):
        """D-1. Index-zipping would give relation 2 'phosphorylation'."""
        self.assertEqual(self.by_pair[("200", "300")].subtype, "expression")

    def test_all_subtypes_of_one_relation_are_kept(self):
        self.assertEqual(self.by_pair[("100", "200")].subtype,
                         "activation,phosphorylation")

    def test_relation_with_no_subtype_is_still_an_edge(self):
        edge = self.by_pair[("300", "tst00002")]
        self.assertEqual(edge.subtype, "")
        self.assertEqual(edge.kind, "maplink")

    def test_reaction_type_is_read_as_an_attribute(self):
        """D-2. Token-position parsing yields the literal string 'type' here."""
        edge = self.by_pair[("300", "C00001")]
        self.assertEqual(edge.kind, "reaction")
        self.assertFalse(edge.reversible)

    def test_multi_id_reaction_name_keeps_both_ids(self):
        self.assertEqual(self.by_pair[("300", "C00001")].subtype,
                         "rn:R00001,rn:R00002")

    def test_reaction_links_enzyme_to_substrate_and_product(self):
        self.assertIn(("300", "C00001"), self.by_pair)
        self.assertIn(("300", "C00002"), self.by_pair)

    def test_group_expands_to_its_components(self):
        for member in ("100", "101", "200"):
            self.assertIn((member, "400"), self.by_pair)
            self.assertEqual(self.by_pair[(member, "400")].subtype, "inhibition")

    def test_group_itself_is_never_a_node(self):
        names = {e.a for e in self.edges} | {e.b for e in self.edges}
        self.assertNotIn("undefined", names)
        self.assertNotIn("", names)

    def test_entry_types_are_recorded(self):
        self.assertEqual(self.types["100"], "gene")
        self.assertEqual(self.types["C00001"], "compound")
        self.assertEqual(self.types["tst00002"], "map")

    def test_every_edge_carries_its_pathway(self):
        self.assertTrue(all(e.pathway == "tst00001" for e in self.edges))

    def test_parse_directory_reports_the_file_count(self):
        edges, types, files = parse_directory(self.dir)
        self.assertEqual(files, 1)
        self.assertEqual(len(edges), len(self.edges))

    def test_unreadable_file_is_skipped_not_raised(self):
        bad = os.path.join(self.dir, "broken.kgml")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("<pathway><unclosed>")
        edges, types, files = parse_directory(self.dir)
        self.assertEqual(files, 1)
        self.assertTrue(edges)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
