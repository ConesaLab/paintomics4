#!/usr/bin/env python3
"""The example picker offers real data first, and no duplicated lessons.

Three rules, in precedence order:

1. **A superseded lesson hides behind its real counterpart.** Most simulated
   scenarios were written as stand-ins for a real STATegra scenario of the
   same shape, so offering both shows every pipeline twice. A scenario whose
   `supersededBy` names an offered scenario of the same pipeline is omitted --
   and comes back the moment the counterpart's files are missing, so a fresh
   checkout without the mouse GTF still gets a region example.
2. **Real before simulated.** The published STATegra scenarios are the reason
   to trust the tool, so they lead the picker instead of trailing the
   simulated lessons.
3. **Teaching order within each block.** The dataset directories are numbered
   01-..11- because they teach in that order: one condition, then six, then
   per-condition relevance, then multi-omic, and so on. The manifest was once
   written sorted by *id*, so the picker offered

       Gene expression — six conditions        (02-gene-multi-condition)
       Gene expression — per-condition relevance
       Gene expression — single condition      (01-gene-single-condition)

   which is lesson two before lesson one.

The number is derived in `listScenarios` from the directory rather than only
from an `order` field, because the manifest that is already committed has to
sort correctly without being regenerated -- regeneration needs a KEGG snapshot
and a mouse GTF a fresh checkout does not have.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_example_scenario_ordering
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common import ExampleDatasets

EXAMPLE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "examplefiles")) + os.sep
MANIFEST_PATH = os.path.join(EXAMPLE_DIR, ExampleDatasets.MANIFEST_NAME)

# The numbering on disk. Written out rather than globbed so that renumbering a
# directory has to be a deliberate edit here too.
EXPECTED_ORDER = [
    (1, "gene-single-condition"),
    (2, "gene-multi-condition"),
    (3, "gene-multi-condition-relevance"),
    (4, "multiomics-integration"),
    (5, "regulatory-mirna"),
    (6, "regulatory-more"),
    (7, "region-based"),
    (8, "stategra-multiomics"),
    (9, "stategra-regions"),
    (10, "stategra-mirna"),
    (11, "stategra-more"),
]

# What the picker offers: the real block (directories 08-11) ahead of the
# simulated lessons (01-07), teaching order inside each block. Entries hidden
# by SUPERSEDED below appear here so the order still holds wherever one IS
# offered (its counterpart's files missing on that deploy).
EXPECTED_OFFER = [
    "stategra-multiomics",
    "stategra-regions",
    "stategra-mirna",
    "stategra-more",
    "gene-single-condition",
    "gene-multi-condition",
    "gene-multi-condition-relevance",
    "multiomics-integration",
    "regulatory-mirna",
    "regulatory-more",
    "region-based",
]

# Simulated stand-ins and the real scenario each one duplicates. Offered only
# while the counterpart cannot be; otherwise the picker shows every pipeline
# twice, which is the duplication this was reported as.
SUPERSEDED = {
    "gene-multi-condition": "stategra-multiomics",
    "multiomics-integration": "stategra-multiomics",
    "regulatory-mirna": "stategra-mirna",
    "regulatory-more": "stategra-more",
    "region-based": "stategra-regions",
}


class ScenarioOrderTest(unittest.TestCase):
    """The derivation itself, on synthetic entries."""

    def test_the_directory_number_is_used(self):
        self.assertEqual(ExampleDatasets.scenarioOrder({
            "id": "x",
            "omics": [{"dataFile": "datasets/07-region-based/data/x.tab"}],
        }), 7)

    def test_an_explicit_order_wins_over_the_directory(self):
        self.assertEqual(ExampleDatasets.scenarioOrder({
            "id": "x", "order": 2,
            "omics": [{"dataFile": "datasets/07-region-based/data/x.tab"}],
        }), 2)

    def test_an_unnumbered_scenario_sorts_last_rather_than_first(self):
        self.assertEqual(ExampleDatasets.scenarioOrder({
            "id": "x",
            "omics": [{"dataFile": "datasets/legacy/data/x.tab"}],
        }), ExampleDatasets.UNORDERED_SCENARIO)

    def test_a_boolean_is_not_an_order(self):
        """`isinstance(True, int)` is True in Python; a stray flag must not
        become position 1."""
        self.assertEqual(ExampleDatasets.scenarioOrder({
            "id": "x", "order": True,
            "omics": [{"dataFile": "datasets/07-region-based/data/x.tab"}],
        }), 7)


class ShippedCatalogueTest(unittest.TestCase):

    def test_every_shipped_scenario_resolves_to_its_directory_number(self):
        with open(MANIFEST_PATH, encoding="utf-8") as handle:
            scenarios = json.load(handle)["scenarios"]
        byId = {entry["id"]: entry for entry in scenarios}
        for expected, scenarioId in EXPECTED_ORDER:
            self.assertIn(scenarioId, byId)
            self.assertEqual(ExampleDatasets.scenarioOrder(byId[scenarioId]),
                             expected, scenarioId)

    def test_listScenarios_offers_real_first_then_teaching_order(self):
        offered = [entry["id"] for entry in
                   ExampleDatasets.listScenarios(EXAMPLE_DIR)]
        # stategra-regions needs the full mouse GTF, which a fresh checkout
        # does not have, so it is legitimately absent from the offer.
        expected = [scenarioId for scenarioId in EXPECTED_OFFER
                    if scenarioId in offered]
        self.assertEqual(offered, expected)

    def test_every_real_scenario_precedes_every_simulated_one(self):
        """The symptom this was reported as: the real STATegra data sat below
        seven simulated lessons."""
        offered = ExampleDatasets.listScenarios(EXAMPLE_DIR)
        flags = [bool(entry.get("simulated")) for entry in offered]
        self.assertIn(False, flags, "no real scenario is offered at all")
        firstSimulated = flags.index(True)
        self.assertNotIn(False, flags[firstSimulated:],
                         "a real scenario sorted below a simulated one")

    def test_the_single_condition_lesson_comes_before_per_condition_relevance(self):
        """The ordering symptom this was first reported as -- lesson two before
        lesson one -- asserted on the two gene lessons that are still offered
        (gene-multi-condition now hides behind the real STATegra time course).
        """
        offered = [entry["id"] for entry in
                   ExampleDatasets.listScenarios(EXAMPLE_DIR)]
        self.assertLess(offered.index("gene-single-condition"),
                        offered.index("gene-multi-condition-relevance"))

    def test_superseded_lessons_are_not_offered_next_to_their_counterpart(self):
        """The duplication symptom: each pipeline group offered a real entry
        and its simulated clone side by side."""
        offered = {entry["id"] for entry in
                   ExampleDatasets.listScenarios(EXAMPLE_DIR)}
        for simulated, real in SUPERSEDED.items():
            if real in offered:
                self.assertNotIn(
                    simulated, offered,
                    "%s is offered although %s is" % (simulated, real))

    def test_the_shipped_manifest_declares_the_supersessions(self):
        """The committed manifest carries the mapping, so a regenerated one
        must too (the generator writes the same field)."""
        with open(MANIFEST_PATH, encoding="utf-8") as handle:
            scenarios = json.load(handle)["scenarios"]
        byId = {entry["id"]: entry for entry in scenarios}
        for simulated, real in SUPERSEDED.items():
            self.assertEqual(byId[simulated].get("supersededBy"), real,
                             simulated)
        for scenarioId, entry in byId.items():
            if scenarioId not in SUPERSEDED:
                self.assertNotIn("supersededBy", entry, scenarioId)

    def test_superseded_lessons_remain_loadable_by_id(self):
        """Hiding a lesson from the picker must not break a deep link to it."""
        for simulated in SUPERSEDED:
            self.assertEqual(
                ExampleDatasets.getScenario(EXAMPLE_DIR, simulated)["id"],
                simulated)

    def test_the_picker_sees_the_same_order(self):
        catalogue = ExampleDatasets.catalogueForClient(EXAMPLE_DIR)
        self.assertEqual([entry["id"] for entry in catalogue["scenarios"]],
                         [entry["id"] for entry in
                          ExampleDatasets.listScenarios(EXAMPLE_DIR)])


class SupersessionFallbackTest(unittest.TestCase):
    """The stand-in comes back the moment its counterpart cannot be offered.

    Exercised on a synthetic catalogue because the shipped one always has the
    STATegra files: the deploy where they are missing is exactly the deploy
    that cannot run this suite.
    """

    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp(prefix="example_supersession_") + os.sep
        self.addCleanup(self.cleanRoot)

    def cleanRoot(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)
        ExampleDatasets.clearCache()

    def writeCatalogue(self, scenarios, presentFiles):
        datasetsDir = os.path.join(self.root, "datasets")
        os.makedirs(datasetsDir, exist_ok=True)
        with open(os.path.join(datasetsDir, "manifest.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"version": ExampleDatasets.SUPPORTED_VERSION,
                       "defaultScenario": scenarios[0]["id"],
                       "scenarios": scenarios}, handle)
        for relative in presentFiles:
            path = os.path.join(self.root, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("x\n")
        ExampleDatasets.clearCache()

    @staticmethod
    def scenario(scenarioId, number, **extra):
        entry = {"id": scenarioId, "pipeline": "pathway-acquisition",
                 "omics": [{"omicName": "Gene expression", "omicType": "gene",
                            "dataFile": "datasets/%02d-%s/data/values.tab"
                                        % (number, scenarioId)}]}
        entry.update(extra)
        return entry

    def test_hidden_while_the_counterpart_is_offered(self):
        real = self.scenario("real-lesson", 2, simulated=False)
        standIn = self.scenario("sim-lesson", 1, simulated=True,
                                supersededBy="real-lesson")
        self.writeCatalogue([real, standIn],
                            ["datasets/02-real-lesson/data/values.tab",
                             "datasets/01-sim-lesson/data/values.tab"])
        self.assertEqual([entry["id"] for entry in
                          ExampleDatasets.listScenarios(self.root)],
                         ["real-lesson"])

    def test_offered_again_when_the_counterpart_files_are_missing(self):
        real = self.scenario("real-lesson", 2, simulated=False)
        standIn = self.scenario("sim-lesson", 1, simulated=True,
                                supersededBy="real-lesson")
        self.writeCatalogue([real, standIn],
                            ["datasets/01-sim-lesson/data/values.tab"])
        self.assertEqual([entry["id"] for entry in
                          ExampleDatasets.listScenarios(self.root)],
                         ["sim-lesson"])

    def test_a_cross_pipeline_supersession_does_not_fire(self):
        """Defensive: hiding a pipeline's only example behind a scenario the
        pipeline-filtered list cannot contain would empty that entry point."""
        real = self.scenario("real-lesson", 2, simulated=False)
        standIn = self.scenario("sim-lesson", 1, simulated=True,
                                pipeline="regions2genes",
                                supersededBy="real-lesson")
        self.writeCatalogue([real, standIn],
                            ["datasets/02-real-lesson/data/values.tab",
                             "datasets/01-sim-lesson/data/values.tab"])
        offered = [entry["id"] for entry in
                   ExampleDatasets.listScenarios(self.root)]
        self.assertIn("sim-lesson", offered)

    def test_a_self_supersession_does_not_hide_the_scenario(self):
        broken = self.scenario("sim-lesson", 1, simulated=True,
                               supersededBy="sim-lesson")
        self.writeCatalogue([broken],
                            ["datasets/01-sim-lesson/data/values.tab"])
        self.assertEqual([entry["id"] for entry in
                          ExampleDatasets.listScenarios(self.root)],
                         ["sim-lesson"])


class DefaultsAreUnchangedTest(unittest.TestCase):
    """Reordering the catalogue must not move any entry point's default.

    `defaultScenarioFor` falls back to "the first available scenario for this
    pipeline", so it reads whatever order listScenarios produces. The old order
    was the manifest's own, which was sorted by id -- so that is what the
    expected value is computed from here, rather than being hardcoded.
    """

    def oldDefaultFor(self, pipeline):
        manifest = ExampleDatasets.loadManifest(EXAMPLE_DIR)
        globalDefault = manifest.get("defaultScenario",
                                     ExampleDatasets.LEGACY_DEFAULT)
        available = sorted(
            (entry for entry in ExampleDatasets.listScenarios(EXAMPLE_DIR,
                                                              pipeline)),
            key=lambda entry: entry["id"])
        for entry in available:
            if entry["id"] == globalDefault:
                return globalDefault
        real = [entry for entry in available if not entry.get("simulated")]
        ordered = real or available
        return ordered[0]["id"] if ordered else None

    def test_no_pipeline_default_moved(self):
        for pipeline in ("pathway-acquisition", "regions2genes",
                         "mirna2genes", "more"):
            self.assertEqual(
                ExampleDatasets.defaultScenarioFor(EXAMPLE_DIR, pipeline),
                self.oldDefaultFor(pipeline),
                "the default for %s changed when the catalogue was reordered"
                % pipeline)

    def test_the_global_default_is_still_stategra(self):
        self.assertEqual(ExampleDatasets.defaultScenarioId(EXAMPLE_DIR),
                         "stategra-multiomics")


class GeneratorTest(unittest.TestCase):
    """Future builds write the position out instead of leaving it derived."""

    def test_writeManifest_emits_order_and_sorts_by_it(self):
        from src.AdminTools.scripts.exampledata import __main__ as builder

        entries = [
            {"id": "beta",
             "omics": [{"dataFile": "datasets/02-beta/data/x.tab"}]},
            {"id": "alpha",
             "omics": [{"dataFile": "datasets/01-alpha/data/x.tab"}]},
        ]

        import tempfile
        outputRoot = tempfile.mkdtemp(prefix="example_manifest_")
        try:
            class FakeKegg(object):
                speciesDir = outputRoot

            path = builder.writeManifest(outputRoot, entries, 1, FakeKegg())
            with open(path, encoding="utf-8") as handle:
                written = json.load(handle)
        finally:
            import shutil
            shutil.rmtree(outputRoot, ignore_errors=True)

        self.assertEqual([entry["id"] for entry in written["scenarios"]],
                         ["alpha", "beta"])
        self.assertEqual([entry["order"] for entry in written["scenarios"]],
                         [1, 2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
