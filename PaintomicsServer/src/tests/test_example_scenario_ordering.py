#!/usr/bin/env python3
"""The example picker offers the datasets in the order they were numbered.

The dataset directories are 01-..10- because they teach in that order: one
condition, then six, then per-condition relevance, then multi-omic, and so on.
The manifest was written sorted by *id*, so the picker offered

    Gene expression — six conditions        (02-gene-multi-condition)
    Gene expression — per-condition relevance
    Gene expression — single condition      (01-gene-single-condition)

which is lesson two before lesson one.

The order is derived in `listScenarios` from the directory number rather than
only from an `order` field, because the manifest that is already committed has
to sort correctly without being regenerated -- regeneration needs a KEGG
snapshot and a mouse GTF a fresh checkout does not have.

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
]


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

    def test_listScenarios_returns_them_in_teaching_order(self):
        offered = [entry["id"] for entry in
                   ExampleDatasets.listScenarios(EXAMPLE_DIR)]
        # stategra-regions needs the full mouse GTF, which a fresh checkout
        # does not have, so it is legitimately absent from the offer.
        expected = [scenarioId for _, scenarioId in EXPECTED_ORDER
                    if scenarioId in offered]
        self.assertEqual(offered, expected)

    def test_the_single_condition_lesson_comes_before_the_six_condition_one(self):
        """The symptom this was reported as."""
        offered = [entry["id"] for entry in
                   ExampleDatasets.listScenarios(EXAMPLE_DIR)]
        self.assertLess(offered.index("gene-single-condition"),
                        offered.index("gene-multi-condition"))

    def test_the_picker_sees_the_same_order(self):
        catalogue = ExampleDatasets.catalogueForClient(EXAMPLE_DIR)
        self.assertEqual([entry["id"] for entry in catalogue["scenarios"]],
                         [entry["id"] for entry in
                          ExampleDatasets.listScenarios(EXAMPLE_DIR)])


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
