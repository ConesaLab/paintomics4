#!/usr/bin/env python3
"""Behaviour of src/common/ExampleDatasets.py, against synthetic manifests.

The other two example tests run against the real catalogue and therefore only
see the happy path. This one builds manifests on purpose -- corrupt, empty,
wrong-version, pointing outside the tree -- because those are what a bad deploy
or a half-finished regeneration actually produce, and the module's whole failure
policy is that they must degrade rather than take example mode down.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_example_datasets_loader
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common import ExampleDatasets


def manifestWith(scenarios, version=ExampleDatasets.SUPPORTED_VERSION,
                 default="alpha"):
    return {"version": version, "defaultScenario": default, "scenarios": scenarios}


def scenario(scenarioId, pipeline="pathway-acquisition", dataFile=None,
             simulated=True):
    return {
        "id": scenarioId,
        "title": scenarioId,
        "summary": "",
        "pipeline": pipeline,
        "organism": "mmu",
        "databases": ["KEGG"],
        "simulated": simulated,
        "omics": [{"omicName": "Gene expression", "omicType": "gene",
                   "enrichment": "genes",
                   "dataFile": dataFile or ("datasets/%s/data/values.tab" % scenarioId)}],
        "references": [],
    }


class LoaderTestCase(unittest.TestCase):
    """A throwaway example tree per test."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="example_loader_") + os.sep
        os.makedirs(os.path.join(self.root, "datasets"))
        ExampleDatasets.clearCache()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        ExampleDatasets.clearCache()

    def writeManifest(self, manifest):
        path = os.path.join(self.root, ExampleDatasets.MANIFEST_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        ExampleDatasets.clearCache()
        return path

    def writeDataFor(self, scenarioId):
        path = os.path.join(self.root, "datasets", scenarioId, "data", "values.tab")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write("#geneID\tCondA\nENSMUSG00000000001\t1.0\n")
        return path


class ResolutionTest(LoaderTestCase):

    def test_a_known_id_resolves(self):
        self.writeManifest(manifestWith([scenario("alpha")]))
        self.assertEqual(ExampleDatasets.getScenario(self.root, "alpha")["id"], "alpha")

    def test_no_id_means_the_default(self):
        self.writeManifest(manifestWith([scenario("alpha"), scenario("beta")],
                                        default="beta"))
        self.assertEqual(ExampleDatasets.getScenario(self.root, None)["id"], "beta")
        self.assertEqual(ExampleDatasets.getScenario(self.root, "")["id"], "beta")

    def test_an_unknown_id_names_the_valid_ones(self):
        """The message is the whole feature: a bare "not found" leaves the user
        with no way to discover what they should have typed."""
        self.writeManifest(manifestWith([scenario("alpha"), scenario("beta")]))
        with self.assertRaises(ExampleDatasets.UnknownScenario) as caught:
            ExampleDatasets.getScenario(self.root, "gamma")
        message = str(caught.exception)
        self.assertIn("gamma", message)
        self.assertIn("alpha", message)
        self.assertIn("beta", message)

    def test_unknown_scenario_is_a_userwarning(self):
        """ServerErrorManager renders UserWarning as the user-facing message;
        anything else becomes an internal error with a traceback."""
        self.assertTrue(issubclass(ExampleDatasets.UnknownScenario, UserWarning))


class FallbackTest(LoaderTestCase):
    """Every one of these used to be "example mode is gone"."""

    def _assertFellBack(self, manifest):
        self.assertTrue(manifest.get("isFallback"))
        self.assertIn(ExampleDatasets.LEGACY_DEFAULT,
                      [entry["id"] for entry in manifest["scenarios"]])

    def test_no_manifest_at_all(self):
        self._assertFellBack(ExampleDatasets.loadManifest(self.root))

    def test_manifest_is_not_json(self):
        path = os.path.join(self.root, ExampleDatasets.MANIFEST_NAME)
        with open(path, "w") as handle:
            handle.write("{ this is not json")
        ExampleDatasets.clearCache()
        self._assertFellBack(ExampleDatasets.loadManifest(self.root))

    def test_manifest_declares_a_future_version(self):
        """An older server reading a newer manifest must not misread it."""
        self.writeManifest(manifestWith([scenario("alpha")], version=999))
        self._assertFellBack(ExampleDatasets.loadManifest(self.root))

    def test_manifest_lists_no_scenarios(self):
        self.writeManifest(manifestWith([]))
        self._assertFellBack(ExampleDatasets.loadManifest(self.root))

    def test_the_fallback_still_resolves_the_default(self):
        resolved = ExampleDatasets.getScenario(self.root, None)
        self.assertEqual(resolved["id"], ExampleDatasets.LEGACY_DEFAULT)


class AvailabilityTest(LoaderTestCase):

    def test_a_scenario_with_missing_files_is_not_offered(self):
        self.writeManifest(manifestWith([scenario("alpha"), scenario("beta")]))
        self.writeDataFor("alpha")
        offered = [entry["id"] for entry in ExampleDatasets.listScenarios(self.root)]
        self.assertEqual(offered, ["alpha"])

    def test_but_it_can_still_be_asked_for_by_name(self):
        """getScenario resolves it; applyScenario is what refuses, with a
        message naming how many files are missing. Splitting it that way keeps
        "you asked for something that does not exist" distinct from "it exists
        but this server does not have the files"."""
        self.writeManifest(manifestWith([scenario("beta")]))
        self.assertEqual(ExampleDatasets.getScenario(self.root, "beta")["id"], "beta")
        self.assertEqual(ExampleDatasets.missingFiles(
            self.root, ExampleDatasets.getScenario(self.root, "beta")),
            ["datasets/beta/data/values.tab"])

    def test_pipeline_filter(self):
        self.writeManifest(manifestWith([
            scenario("alpha", pipeline="pathway-acquisition"),
            scenario("regions", pipeline="regions2genes")]))
        self.writeDataFor("alpha")
        self.writeDataFor("regions")
        self.assertEqual(
            [entry["id"] for entry in
             ExampleDatasets.listScenarios(self.root, "regions2genes")],
            ["regions"])

    def test_each_pipeline_gets_its_own_default(self):
        """The global default belongs to pathway-acquisition, so a region entry
        point cannot use it -- it would hand a gene-based job to the region
        converter."""
        self.writeManifest(manifestWith([
            scenario("alpha", pipeline="pathway-acquisition"),
            scenario("regions", pipeline="regions2genes")], default="alpha"))
        self.writeDataFor("alpha")
        self.writeDataFor("regions")
        self.assertEqual(
            ExampleDatasets.defaultScenarioFor(self.root, "pathway-acquisition"),
            "alpha")
        self.assertEqual(
            ExampleDatasets.defaultScenarioFor(self.root, "regions2genes"),
            "regions")

    def test_a_pipeline_default_prefers_real_data_over_simulated(self):
        """Matches the behaviour that exists today: the bundled example has
        always been the real STATegra dataset."""
        self.writeManifest(manifestWith([
            scenario("sim", pipeline="mirna2genes", simulated=True),
            scenario("real", pipeline="mirna2genes", simulated=False)],
            default="unrelated"))
        self.writeDataFor("sim")
        self.writeDataFor("real")
        self.assertEqual(
            ExampleDatasets.defaultScenarioFor(self.root, "mirna2genes"), "real")

    def test_a_pipeline_with_nothing_available_returns_none(self):
        self.writeManifest(manifestWith([scenario("alpha")]))
        self.writeDataFor("alpha")
        self.assertIsNone(ExampleDatasets.defaultScenarioFor(self.root, "more"))


class PathSafetyTest(LoaderTestCase):
    """The scenario id arrives in a URL, so a manifest path is reachable input."""

    def test_a_path_escaping_the_tree_is_refused(self):
        for attempt in ("../../../../etc/passwd",
                        "datasets/../../outside.tab",
                        "/etc/passwd"):
            with self.assertRaises(ExampleDatasets.UnknownScenario, msg=attempt):
                ExampleDatasets.absolutePath(self.root, attempt)

    def test_an_ordinary_path_resolves(self):
        self.writeDataFor("alpha")
        resolved = ExampleDatasets.absolutePath(
            self.root, "datasets/alpha/data/values.tab")
        self.assertTrue(os.path.isfile(resolved))
        self.assertTrue(resolved.startswith(os.path.realpath(self.root)))


class ModeParsingTest(unittest.TestCase):
    """`exampleMode` is a URL segment; three states, not two."""

    def test_upload(self):
        for value in (False, None, ""):
            self.assertEqual(ExampleDatasets.scenarioIdFromMode(value), (False, None))

    def test_default_example(self):
        self.assertEqual(ExampleDatasets.scenarioIdFromMode("example"), (True, None))

    def test_named_example(self):
        self.assertEqual(ExampleDatasets.scenarioIdFromMode("example/region-based"),
                         (True, "region-based"))

    def test_a_trailing_slash_means_the_default(self):
        """URLs grow trailing slashes when they are copied around."""
        self.assertEqual(ExampleDatasets.scenarioIdFromMode("example/"), (True, None))

    def test_garbage_is_neither(self):
        """None, not False: the servlets must be able to tell "this is an
        upload" from "this is nonsense", because the second raises."""
        self.assertEqual(ExampleDatasets.scenarioIdFromMode("junk"), (None, None))
        self.assertEqual(ExampleDatasets.scenarioIdFromMode("exampleish/x"),
                         (None, None))


class CacheTest(LoaderTestCase):

    def test_a_regenerated_manifest_is_picked_up(self):
        """A developer who reruns the generator should not have to restart the
        server. The cache key includes size as well as mtime, because mtime
        alone has one-second granularity and two writes can land inside it."""
        self.writeManifest(manifestWith([scenario("alpha")]))
        self.assertEqual([s["id"] for s in
                          ExampleDatasets.loadManifest(self.root)["scenarios"]],
                         ["alpha"])

        self.writeManifest(manifestWith([scenario("alpha"), scenario("beta")]))
        self.assertEqual([s["id"] for s in
                          ExampleDatasets.loadManifest(self.root)["scenarios"]],
                         ["alpha", "beta"])


class ClientCatalogueTest(LoaderTestCase):

    def test_no_filesystem_paths_reach_the_browser(self):
        """The client posts an id back; it never opens these files. Publishing
        server paths would be a leak for no functional gain."""
        self.writeManifest(manifestWith([scenario("alpha")]))
        self.writeDataFor("alpha")
        payload = ExampleDatasets.catalogueForClient(self.root)
        text = json.dumps(payload)
        self.assertNotIn("datasets/", text)
        self.assertNotIn(self.root, text)
        self.assertEqual(payload["scenarios"][0]["omicNames"], ["Gene expression"])

    def test_only_offerable_scenarios_are_published(self):
        self.writeManifest(manifestWith([scenario("alpha"), scenario("beta")]))
        self.writeDataFor("alpha")
        payload = ExampleDatasets.catalogueForClient(self.root)
        self.assertEqual([entry["id"] for entry in payload["scenarios"]], ["alpha"])

    def test_the_card_names_what_the_job_will_run_not_what_the_manifest_says(self):
        """The picker card is a promise about the job that is about to start.

        A manifest entry declares the databases the dataset was authored
        against; it cannot know what the host running it installed. Every
        bundled scenario is mmu and five of the seven declare KEGG alone, while
        an mmu install that has Reactome runs both -- so the unresolved card
        understated its own job by half the pathway universe.
        """
        self.writeManifest(manifestWith([scenario("alpha")]))
        self.writeDataFor("alpha")
        payload = ExampleDatasets.catalogueForClient(
            self.root, resolveDatabases=lambda organism: ["KEGG", "Reactome"])
        self.assertEqual(["KEGG", "Reactome"], payload["scenarios"][0]["databases"])

    def test_the_resolver_is_given_the_scenario_organism(self):
        seen = []
        self.writeManifest(manifestWith([scenario("alpha")]))
        self.writeDataFor("alpha")
        ExampleDatasets.catalogueForClient(
            self.root,
            resolveDatabases=lambda organism: seen.append(organism) or ["KEGG"])
        self.assertEqual(["mmu"], seen)

    def test_a_failing_resolver_leaves_the_picker_working(self):
        """A stale database list is a smaller failure than a picker that won't open."""
        def explode(organism):
            raise RuntimeError("MongoDB is down")

        self.writeManifest(manifestWith([scenario("alpha")]))
        self.writeDataFor("alpha")
        payload = ExampleDatasets.catalogueForClient(self.root, resolveDatabases=explode)
        self.assertEqual(["alpha"], [entry["id"] for entry in payload["scenarios"]])
        self.assertEqual(["KEGG"], payload["scenarios"][0]["databases"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
