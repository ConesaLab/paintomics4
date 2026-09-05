#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interaction sources and printed obstacles for the pathway evidence overlay.

Two defects are pinned here, both found by looking at a real drawn map:

  1. The overlay placed regulator boxes on top of KEGG artwork it could not
     see. The installed pathway document stores `genes`, `compounds` and
     `relatedPathways` only, so the 31 `ortholog` entries of mmu05167 -- the
     VIRAL proteins, LANA among them -- were invisible obstacles and a
     satellite landed on 44.7% of one. The geometry was on disk in the KGML
     all along.

  2. Corroboration was decided against OmniPath alone, which threw away
     curated biology: a regulator and its target are routinely joined by KEGG
     in a DIFFERENT map from the one on screen. Measured on the STATegra mouse
     job, 132 of 492 drawable relationships (26.8%) are recorded in KEGG while
     being labelled "novel" or -- worse -- "unsupported", which asserts there
     is no external evidence either way about an interaction KEGG curates.

Hermetic on purpose: every fixture is written into a temporary KEGG_DATA_DIR,
so this runs in the deploy image and on a machine with no species installed.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.classes import PathwayEvidence


#: One gene entry, one ortholog entry (the LANA case), one group, and three
#: relations of which one is a maplink that must NOT become an interaction.
KGML = """<?xml version="1.0"?>
<pathway name="path:mmu99999" org="mmu" number="99999" title="Fixture">
  <entry id="1" name="mmu:100 mmu:101" type="gene">
    <graphics name="Aaa" x="100" y="200" width="46" height="17" type="rectangle"/>
  </entry>
  <entry id="2" name="mmu:200" type="gene">
    <graphics name="Bbb" x="300" y="200" width="46" height="17" type="rectangle"/>
  </entry>
  <entry id="3" name="ko:K21664" type="ortholog">
    <graphics name="K21664" x="500" y="400" width="46" height="17" type="rectangle"/>
  </entry>
  <entry id="4" name="mmu:300" type="gene">
    <graphics name="Ccc" x="700" y="200" width="46" height="17" type="rectangle"/>
  </entry>
  <entry id="5" name="undefined" type="group">
    <graphics x="900" y="200" width="60" height="30" type="rectangle"/>
    <component id="2"/>
    <component id="4"/>
  </entry>
  <entry id="6" name="path:mmu04010" type="map">
    <graphics name="MAPK signaling" x="1100" y="600" width="109" height="25" type="roundrectangle"/>
  </entry>
  <relation entry1="1" entry2="2" type="GErel"/>
  <relation entry1="1" entry2="5" type="PPrel"/>
  <relation entry1="2" entry2="6" type="maplink"/>
</pathway>
"""

#: Reaction with a catalyst, an inhibitor and an input. Only the first two may
#: produce interactions; input -> output is the same molecule modified.
REACTOME_GRAPH = {
    "stId": "R-MMU-99999",
    "nodes": [
        {"dbId": 1, "identifier": "P00001", "referenceType": "ReferenceGeneProduct",
         "geneNames": ["Cat1"], "children": []},
        {"dbId": 2, "identifier": "P00002", "referenceType": "ReferenceGeneProduct",
         "geneNames": ["Out1"], "children": []},
        {"dbId": 3, "identifier": "P00003", "referenceType": "ReferenceGeneProduct",
         "geneNames": ["Inh1"], "children": []},
        {"dbId": 4, "identifier": "P00004", "referenceType": "ReferenceGeneProduct",
         "geneNames": ["In1"], "children": []},
        # A complex: carries no accession itself, only members.
        {"dbId": 5, "identifier": None, "referenceType": "Complex", "children": [1, 3]},
    ],
    "edges": [
        {"dbId": 10, "schemaClass": "Reaction",
         "inputs": [4], "outputs": [2], "catalysts": [1], "inhibitors": [3]},
    ],
}


class PrintedObstacles(unittest.TestCase):
    """Everything the map prints has to reach the placer."""

    def setUp(self):
        self.dataDir = tempfile.mkdtemp(prefix="evidence-fixture-")
        kgmlDir = os.path.join(self.dataDir, "current", "mmu", "kgml")
        os.makedirs(kgmlDir)
        with open(os.path.join(kgmlDir, "mmu99999.kgml"), "w") as handle:
            handle.write(KGML)
        self._patchDataDir()

    def tearDown(self):
        shutil.rmtree(self.dataDir, ignore_errors=True)
        PathwayEvidence._KGML_BOX_CACHE.clear()
        PathwayEvidence._RAW_GRAPH_CACHE.clear()

    def _patchDataDir(self):
        from src.conf import serverconf
        self._original = serverconf.KEGG_DATA_DIR
        serverconf.KEGG_DATA_DIR = self.dataDir
        self.addCleanup(setattr, serverconf, "KEGG_DATA_DIR", self._original)

    def test_ortholog_and_group_boxes_come_from_the_kgml(self):
        """The KGML holds boxes Mongo never stored. LANA is one of them."""
        PathwayEvidence._KGML_BOX_CACHE.clear()
        boxes = PathwayEvidence._kgmlOnlyBoxes("mmu", "mmu99999")

        centres = sorted((box["x"], box["y"]) for box in boxes)
        self.assertIn((500.0, 400.0), centres,
                      "the ortholog box (LANA's class) must be an obstacle")
        self.assertIn((900.0, 200.0), centres, "a group box is printed too")
        self.assertEqual(len(boxes), 2,
                         "gene/compound/map geometry is already in Mongo; taking "
                         "it from the KGML as well would duplicate rectangles")

    def test_document_boxes_are_merged_deduplicated_and_sized(self):
        document = {
            "source": "KEGG",
            "genes": [
                {"id": "100", "x": "100", "y": "200", "width": "46", "height": "17"},
                # Co-located gene: same printed rectangle, must collapse.
                {"id": "101", "x": "100", "y": "200", "width": "46", "height": "17"},
                # MapMan stores every feature at width = height = 0.
                {"id": "999", "x": "5", "y": "5", "width": "0", "height": "0"},
                # A coordinate-less entry is a link, not a drawn box.
                {"id": "998", "x": None, "y": None, "width": "46", "height": "17"},
            ],
            "compounds": [{"id": "C1", "x": "50", "y": "60", "width": "8", "height": "8"}],
            "relatedPathways": [
                {"id": "04010", "x": "1100", "y": "600", "width": "109", "height": "25"}],
        }
        boxes = PathwayEvidence._printedObstacles(document, "mmu", "mmu99999")
        centres = sorted((box["x"], box["y"]) for box in boxes)

        self.assertEqual(centres, [(50.0, 60.0), (100.0, 200.0),
                                   (500.0, 400.0), (900.0, 200.0), (1100.0, 600.0)])

    def test_a_missing_kgml_costs_the_extra_boxes_not_the_overlay(self):
        PathwayEvidence._KGML_BOX_CACHE.clear()
        self.assertEqual(PathwayEvidence._kgmlOnlyBoxes("mmu", "no-such-pathway"), [])

    def test_non_kegg_sources_do_not_look_for_a_kgml(self):
        """Reactome and MapMan diagrams have no KGML; OmniPath has no diagram."""
        document = {"source": "Reactome",
                    "genes": [{"id": "1", "x": "10", "y": "10", "width": "4", "height": "4"}]}
        boxes = PathwayEvidence._printedObstacles(document, "mmu", "mmu99999")
        self.assertEqual([(box["x"], box["y"]) for box in boxes], [(10.0, 10.0)])


class KeggRelationGraph(unittest.TestCase):
    """KEGG's own relations, read across EVERY pathway of the organism."""

    def setUp(self):
        self.dataDir = tempfile.mkdtemp(prefix="evidence-kegg-")
        kgmlDir = os.path.join(self.dataDir, "current", "mmu", "kgml")
        os.makedirs(kgmlDir)
        with open(os.path.join(kgmlDir, "mmu99999.kgml"), "w") as handle:
            handle.write(KGML)
        from src.conf import serverconf
        original = serverconf.KEGG_DATA_DIR
        serverconf.KEGG_DATA_DIR = self.dataDir
        self.addCleanup(setattr, serverconf, "KEGG_DATA_DIR", original)
        self.addCleanup(shutil.rmtree, self.dataDir, True)
        self.addCleanup(PathwayEvidence._RAW_GRAPH_CACHE.clear)
        PathwayEvidence._RAW_GRAPH_CACHE.clear()
        self.graph = PathwayEvidence._keggRelationGraph("mmu")

    def test_a_relation_names_the_pathway_it_was_recorded_on(self):
        """The whole point: the interaction is curated, just not drawn here.

        Gene 200 is BOTH the direct GErel partner of 100 and a member of the
        group 100 has a PPrel with, so this pair genuinely carries two records
        and the summariser is expected to report both.
        """
        self.assertIn(("GErel", "mmu99999"), self.graph[("100", "200")])
        for _relationType, pathwayID in self.graph[("100", "200")]:
            self.assertEqual(pathwayID, "mmu99999")

    def test_a_multi_gene_entry_yields_every_pair(self):
        """`mmu:100 mmu:101` is one box holding two genes."""
        self.assertIn(("101", "200"), self.graph)

    def test_a_group_is_expanded_to_its_members(self):
        """A complex relates through the genes it is made of."""
        self.assertIn(("100", "300"), self.graph)
        self.assertEqual(self.graph[("100", "300")], [("PPrel", "mmu99999")])

    def test_maplink_is_not_an_interaction(self):
        """It points at a PATHWAY, not at a gene; keeping it invents edges."""
        for (source, target) in self.graph:
            self.assertNotEqual(target, "mmu04010")
        self.assertNotIn(("200", "04010"), self.graph)

    def test_no_self_edges(self):
        for source, target in self.graph:
            self.assertNotEqual(source, target)


class ReactomeRelationGraph(unittest.TestCase):
    """Only the roles that assert one gene product acting on another."""

    def setUp(self):
        self.dataDir = tempfile.mkdtemp(prefix="evidence-reactome-")
        reactomeDir = os.path.join(self.dataDir, "current", "mmu", "reactome")
        os.makedirs(reactomeDir)
        with open(os.path.join(reactomeDir, "R-MMU-99999.graph.json"), "w") as handle:
            json.dump(REACTOME_GRAPH, handle)
        from src.conf import serverconf
        original = serverconf.KEGG_DATA_DIR
        serverconf.KEGG_DATA_DIR = self.dataDir
        self.addCleanup(setattr, serverconf, "KEGG_DATA_DIR", original)
        self.addCleanup(shutil.rmtree, self.dataDir, True)
        self.addCleanup(PathwayEvidence._RAW_GRAPH_CACHE.clear)
        PathwayEvidence._RAW_GRAPH_CACHE.clear()
        self.graph = PathwayEvidence._reactomeRelationGraph("mmu")

    def test_catalyst_and_inhibitor_reach_the_output(self):
        self.assertEqual(self.graph[("P00001", "P00002")], [("catalysts", "R-MMU-99999")])
        self.assertEqual(self.graph[("P00003", "P00002")], [("inhibitors", "R-MMU-99999")])

    def test_an_input_is_not_a_regulator(self):
        """input -> output is usually the same molecule modified."""
        self.assertNotIn(("P00004", "P00002"), self.graph)

    def test_pairs_are_uniprot_accessions(self):
        for source, target in self.graph:
            self.assertTrue(source.startswith("P0") and target.startswith("P0"))


class EvidenceClassification(unittest.TestCase):
    """Every source is consulted, and each says what it recorded and where."""

    def setUp(self):
        self.kegg = PathwayEvidence.InteractionSource(
            "KEGG",
            {("A", "B"): [("GErel", "mmu04010"), ("PPrel", "mmu05167")]},
            {"A", "B", "C"})
        self.omniPath = PathwayEvidence.InteractionSource(
            "OmniPath",
            {("A", "B"): ("stimulation", "SIGNOR:12345", 7),
             ("C", "D"): ("inhibition", "", 1)},
            {"A", "B", "C", "D"})
        self.knowledge = PathwayEvidence.EvidenceKnowledge([self.omniPath, self.kegg])

    def test_a_pair_recorded_by_several_sources_returns_all_of_them(self):
        hits = self.knowledge.interactions("A", "B")
        self.assertEqual([name for name, _ in hits], ["OmniPath", "KEGG"])

    def test_lookup_is_direction_agnostic(self):
        """MORE asserts a direction a curated database need not have recorded."""
        self.assertTrue(self.knowledge.interactions("B", "A"))

    def test_a_gene_known_to_any_source_is_known(self):
        self.assertTrue(self.knowledge.knows("D"))
        self.assertFalse(self.knowledge.knows("Z"))

    def test_a_pair_only_kegg_records_is_still_corroborated(self):
        """The regression this whole change exists to prevent."""
        keggOnly = PathwayEvidence.EvidenceKnowledge([
            PathwayEvidence.InteractionSource("OmniPath", {}, {"X", "Y"}),
            PathwayEvidence.InteractionSource("KEGG", {("X", "Y"): [("GErel", "mmu04010")]},
                                              {"X", "Y"}),
        ])
        self.assertTrue(keggOnly.interactions("X", "Y"),
                        "a KEGG-only interaction used to be labelled unsupported")

    def test_summary_names_the_other_pathway_and_flags_this_one(self):
        hits = self.knowledge.interactions("A", "B")
        names = {"mmu04010": "MAPK signaling pathway",
                 "mmu05167": "Kaposi sarcoma-associated herpesvirus infection"}
        summary = PathwayEvidence._summariseEvidence(hits, "mmu05167", names)

        byName = {entry["source"]: entry for entry in summary}
        self.assertEqual(byName["KEGG"]["detail"], "GErel, PPrel")
        self.assertTrue(byName["KEGG"]["onThisPathway"],
                        "one of the two records IS the open map")
        self.assertEqual([p["name"] for p in byName["KEGG"]["pathways"]],
                         ["MAPK signaling pathway"],
                         "the open map is not repeated back at the reader")

        self.assertEqual(byName["OmniPath"]["detail"], "stimulation")
        self.assertEqual(byName["OmniPath"]["curationEffort"], 7)
        self.assertEqual([r["pmid"] for r in byName["OmniPath"]["references"]], ["12345"])

    def test_named_pathways_are_capped_and_the_rest_counted(self):
        many = PathwayEvidence.InteractionSource(
            "KEGG",
            {("A", "B"): [("GErel", "mmu0%d" % index) for index in range(4010, 4020)]},
            {"A", "B"})
        knowledge = PathwayEvidence.EvidenceKnowledge([many])
        summary = PathwayEvidence._summariseEvidence(
            knowledge.interactions("A", "B"), "mmu05167", {})

        self.assertEqual(len(summary[0]["pathways"]), PathwayEvidence._MAX_NAMED_PATHWAYS)
        self.assertEqual(summary[0]["morePathways"],
                         10 - PathwayEvidence._MAX_NAMED_PATHWAYS)

    def test_an_unreadable_source_costs_only_itself(self):
        empty = PathwayEvidence.EvidenceKnowledge([None, self.kegg])
        self.assertEqual(len(empty.sources), 1)
        self.assertTrue(empty.interactions("A", "B"))


class TranslatedSource(unittest.TestCase):
    """A raw graph is rewritten into the pathway's own ID space."""

    def test_translation_maps_pairs_and_drops_isoform_collapses(self):
        raw = {("P1", "P2"): [("GErel", "mmu04010")],
               ("P1", "P3"): [("PPrel", "mmu04010")]}
        # P1 and P3 collapse onto the same gene: that is not an edge.
        translation = {"P1": ["10"], "P2": ["20"], "P3": ["10"]}

        original = PathwayEvidence._translateIdentifiers
        PathwayEvidence._translateIdentifiers = \
            lambda identifiers, jobID, db, targetDbnameId: translation
        try:
            source = PathwayEvidence._buildTranslatedSource("KEGG", raw, 1, "job", None)
        finally:
            PathwayEvidence._translateIdentifiers = original

        self.assertEqual(source.interaction("10", "20"), [("GErel", "mmu04010")])
        self.assertIsNone(source.interaction("10", "10"))
        self.assertTrue(source.knows("20"))

    def test_an_empty_raw_graph_yields_an_empty_source(self):
        source = PathwayEvidence._buildTranslatedSource("Reactome", {}, 1, "job", None)
        self.assertEqual(len(source), 0)
        self.assertFalse(source.knows("anything"))


class RegulationTableToleratesLoadedNone(unittest.TestCase):
    """The stored MORE table survives DAO.adaptBSON's None -> "None".

    A job with no MORE analysis stores ``regulationPerConditionData`` as null.
    DAO.adaptBSON turns every None leaf into the string ``"None"`` on load, so
    the evidence overlay receives the string, not None -- and ``("None" or {})``
    is truthy, so the old ``(regulationData or {}).get(...)`` called ``.get`` on
    a str. On paintomics.uv.es that surfaced as a 400 with
    ``'str' object has no attribute 'get'`` on /pa_pathway_evidence for every
    Step 4 diagram of a job that never ran MORE (the common case), which is 43%
    of all evidence requests in the production log.
    """

    def test_string_none_is_not_usable_and_does_not_raise(self):
        table = PathwayEvidence._RegulationTable("None")
        self.assertFalse(table.usable)
        self.assertEqual(table.rows, [])
        self.assertEqual(table.columns, [])
        self.assertEqual(table.conditionNames, [])

    def test_python_none_is_not_usable(self):
        self.assertFalse(PathwayEvidence._RegulationTable(None).usable)

    def test_any_other_non_dict_is_treated_as_empty(self):
        for value in ("", "[]", [], 0, 3.5):
            self.assertFalse(PathwayEvidence._RegulationTable(value).usable)

    def test_a_real_dict_still_reads(self):
        table = PathwayEvidence._RegulationTable(
            {"columns": ["targetF", "regulator", "Group_C1"],
             "rows": [["t1", "r1", "0.5"]]})
        self.assertTrue(table.usable)
        self.assertEqual(table.conditionNames, ["C1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
