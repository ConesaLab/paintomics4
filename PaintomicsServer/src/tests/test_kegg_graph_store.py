#!/usr/bin/env python3
"""The graph is derived on demand, cached per organism, and self-invalidating.

Today `_loadCompoundNeighbourMap` (PathwayAcquisitionJob.py:113-177) parses a
34 MB JSON and peaks at 360-420 MB RSS -- reproduced at 393 MB -- into a cache
with ONE slot, so a second organism evicts the first. Deriving from KGML instead
was measured at 1.03 s and 32 MB for the largest species.

The cache key is (organism, file count, max mtime) so reinstalling a species
invalidates it without anyone having to remember to.

The legacy fallback is not optional: KGML retention on production is unverified,
and every species that has hub data today has a kegg_interaction.json.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from src.common.KeggGraph import store

KGML = """<?xml version="1.0"?>
<pathway name="path:tst00001" org="tst" number="00001">
  <entry id="1" name="cpd:C00001" type="compound"/>
  <entry id="2" name="tst:100" type="gene"/>
  <relation entry1="1" entry2="2" type="PPrel">
    <subtype name="activation" value="--&gt;"/>
  </relation>
</pathway>
"""


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="paintomics-store-")
        self.kgml = os.path.join(self.root, "current", "tst", "kgml")
        self.hub = os.path.join(self.root, "current", "tst", "hubData")
        os.makedirs(self.kgml)
        os.makedirs(self.hub)
        with open(os.path.join(self.kgml, "tst00001.kgml"), "w") as handle:
            handle.write(KGML)
        self._old = store.KEGG_DATA_DIR
        store.KEGG_DATA_DIR = self.root + os.sep
        store.clear_cache()

    def tearDown(self):
        store.KEGG_DATA_DIR = self._old
        store.clear_cache()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_derives_from_kgml(self):
        graph = store.get_graph("tst")
        self.assertEqual(graph.source, "kgml")
        self.assertEqual(graph.rings("C00001", 1)[0], ["100"])

    def test_second_call_returns_the_same_object(self):
        self.assertIs(store.get_graph("tst"), store.get_graph("tst"))

    def test_touching_a_kgml_file_invalidates_the_cache(self):
        first = store.get_graph("tst")
        path = os.path.join(self.kgml, "tst00001.kgml")
        os.utime(path, (os.path.getatime(path), os.path.getmtime(path) + 60))
        self.assertIsNot(store.get_graph("tst"), first)

    def test_adding_a_kgml_file_invalidates_the_cache(self):
        first = store.get_graph("tst")
        with open(os.path.join(self.kgml, "tst00002.kgml"), "w") as handle:
            handle.write(KGML.replace("tst00001", "tst00002"))
        self.assertIsNot(store.get_graph("tst"), first)

    def test_falls_back_to_the_legacy_json_when_kgml_is_absent(self):
        shutil.rmtree(self.kgml)
        with open(os.path.join(self.hub, "kegg_interaction.json"), "w") as handle:
            json.dump({"C00001": [["100"], ["100", "200"], [], []]}, handle)
        graph = store.get_graph("tst")
        self.assertEqual(graph.source, "legacy-json")
        self.assertEqual(graph.rings("C00001", 1)[0], ["100"])

    def test_legacy_double_encoded_payload_is_unwrapped(self):
        """The installer used to write toJSON() through write_json(), producing
        a 1-element array wrapping escaped text."""
        shutil.rmtree(self.kgml)
        inner = json.dumps({"C00001": [["100"], [], [], []]})
        with open(os.path.join(self.hub, "kegg_interaction.json"), "w") as handle:
            json.dump([inner], handle)
        graph = store.get_graph("tst")
        self.assertEqual(graph.source, "legacy-json")
        self.assertEqual(graph.rings("C00001", 1)[0], ["100"])

    def test_returns_none_when_the_species_has_neither(self):
        shutil.rmtree(self.kgml)
        self.assertIsNone(store.get_graph("tst"))

    def test_unknown_organism_returns_none(self):
        self.assertIsNone(store.get_graph("nope"))

    def test_cache_is_bounded(self):
        for index in range(store.CACHE_SIZE + 2):
            code = "sp%d" % index
            directory = os.path.join(self.root, "current", code, "kgml")
            os.makedirs(directory)
            with open(os.path.join(directory, "a.kgml"), "w") as handle:
                handle.write(KGML)
            store.get_graph(code)
        self.assertLessEqual(len(store._CACHE), store.CACHE_SIZE)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
