#!/usr/bin/env python3
"""Structural integrity of the shipped example catalogue.

`test_example_scenarios_validate.py` asks whether the *data* is acceptable.
This asks whether the *catalogue* is coherent: that every path resolves, that
ids are unique, that nothing declares a file it does not ship.

Worth separating because the failure modes differ. A malformed values file is
caught the moment someone runs the scenario; a manifest that names a file which
was renamed is caught only when a user picks that scenario, and reaches them as
"the example dataset is incomplete on this server" -- accurate but late.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_example_manifest
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

KNOWN_PIPELINES = {"pathway-acquisition", "regions2genes", "mirna2genes", "more"}


class ManifestShapeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MANIFEST_PATH, encoding="utf-8") as handle:
            cls.manifest = json.load(handle)
        cls.scenarios = cls.manifest["scenarios"]

    def test_the_manifest_is_actually_committed(self):
        """Without it every entry point silently falls back to the legacy bundle.

        The fallback is deliberate and logs a warning, but a warning in a server
        log is not a test failure, so nothing else here would notice.
        """
        self.assertTrue(os.path.isfile(MANIFEST_PATH),
                        "no manifest at %s -- run "
                        "`python -m src.AdminTools.scripts.exampledata`"
                        % MANIFEST_PATH)
        self.assertEqual(self.manifest["version"], ExampleDatasets.SUPPORTED_VERSION)

    def test_scenario_ids_are_unique(self):
        ids = [scenario["id"] for scenario in self.scenarios]
        duplicates = {name for name in ids if ids.count(name) > 1}
        self.assertEqual(duplicates, set(),
                         "duplicate scenario ids: %s. getScenario returns the "
                         "first match, so one of them is unreachable" % duplicates)

    def test_every_scenario_declares_the_fields_the_loader_reads(self):
        for scenario in self.scenarios:
            for field in ("id", "title", "summary", "pipeline", "organism", "omics"):
                self.assertIn(field, scenario,
                              "scenario %r has no %r" % (scenario.get("id"), field))
            self.assertIn(scenario["pipeline"], KNOWN_PIPELINES,
                          "scenario %r declares unknown pipeline %r; no entry "
                          "point would ever offer it"
                          % (scenario["id"], scenario["pipeline"]))
            self.assertTrue(scenario["omics"],
                            "scenario %r has no omics" % scenario["id"])

    def test_omic_names_are_unique_within_a_scenario(self):
        """Two omics with the same name collide downstream.

        `findInputOmicByName` returns the first match, and MORE refuses the case
        outright because both would write MORE_output_<name>_<date>.tab and one
        would overwrite the other.
        """
        for scenario in self.scenarios:
            names = [omic["omicName"] for omic in scenario["omics"]]
            self.assertEqual(len(names), len(set(names)),
                             "scenario %r repeats an omic name: %s"
                             % (scenario["id"], names))

    def test_every_declared_file_exists_and_is_not_empty(self):
        missingAnywhere = []
        for scenario in self.scenarios:
            for relativePath in ExampleDatasets.declaredFiles(scenario):
                absolute = ExampleDatasets.absolutePath(EXAMPLE_DIR, relativePath)
                if not os.path.isfile(absolute):
                    missingAnywhere.append((scenario["id"], relativePath))
                    continue
                self.assertGreater(
                    os.path.getsize(absolute), 0,
                    "%s declares %s, which is empty" % (scenario["id"], relativePath))

        # The mouse GTF is fetched by a manual deploy step and is legitimately
        # absent from a checkout, so its scenario is allowed to be incomplete --
        # listScenarios drops it. Nothing else may be.
        allowed = {"stategra-regions"}
        unexpected = [item for item in missingAnywhere if item[0] not in allowed]
        self.assertEqual(unexpected, [],
                         "scenarios declare files that do not exist: %s" % unexpected)

    def test_paths_stay_inside_the_example_directory(self):
        for scenario in self.scenarios:
            for relativePath in ExampleDatasets.declaredFiles(scenario):
                self.assertFalse(os.path.isabs(relativePath),
                                 "%s declares the absolute path %s; the manifest "
                                 "must be relocatable" % (scenario["id"], relativePath))
                ExampleDatasets.absolutePath(EXAMPLE_DIR, relativePath)   # raises if it escapes

    def test_the_default_scenario_exists_and_is_offerable(self):
        default = self.manifest["defaultScenario"]
        offered = {scenario["id"]
                   for scenario in ExampleDatasets.listScenarios(EXAMPLE_DIR)}
        self.assertIn(default, offered,
                      "the default scenario %r is not among the offerable ones "
                      "(%s), so a bare /pa_step1/example would fail"
                      % (default, sorted(offered)))

    def test_every_pipeline_has_at_least_one_offerable_scenario(self):
        """The point of the exercise: no entry point left without an example.

        MORE shipped without one for its whole existence, which is how its input
        format -- per-sample matrices and a numeric design matrix, unlike every
        other omic -- ended up undocumented by example.
        """
        for pipeline in sorted(KNOWN_PIPELINES):
            available = ExampleDatasets.listScenarios(EXAMPLE_DIR, pipeline=pipeline)
            self.assertGreater(len(available), 0,
                               "no example is offerable for the %r pipeline" % pipeline)

    def test_every_scenario_has_a_readme(self):
        for scenario in self.scenarios:
            paths = ExampleDatasets.declaredFiles(scenario)
            self.assertTrue(paths)
            folder = os.path.dirname(os.path.dirname(
                ExampleDatasets.absolutePath(EXAMPLE_DIR, paths[0])))
            readme = os.path.join(folder, "README.md")
            self.assertTrue(os.path.isfile(readme),
                            "%s has no README.md at %s" % (scenario["id"], readme))

    def test_simulated_scenarios_record_what_should_be_recovered(self):
        """Ground truth is what separates a smoke test from an assertion.

        A simulated scenario without an expected-pathways list can only answer
        "did it crash", never "did it find the signal that was planted".
        """
        for scenario in self.scenarios:
            if not scenario.get("simulated"):
                continue
            expected = scenario.get("expected", {})
            self.assertIn("pathwaysFile", expected,
                          "%s plants a signal but records no expected pathways"
                          % scenario["id"])
            path = ExampleDatasets.absolutePath(EXAMPLE_DIR, expected["pathwaysFile"])
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as handle:
                entries = [line for line in handle
                           if line.strip() and not line.startswith("#")]
            self.assertGreater(len(entries), 0,
                               "%s has an empty expected-pathways file" % scenario["id"])


class EncodingTest(unittest.TestCase):
    """Every shipped file must already be UTF-8.

    `ensure_utf8` rewrites a non-UTF-8 file **in place**. Run against a bundled
    example that is read from where it lies rather than copied per job, that
    would mutate the shipped data on first use -- and the rewrite is a guess
    from chardet, so it could corrupt it. Keeping everything ASCII makes the
    call a no-op by construction.
    """

    def test_all_example_files_decode_as_utf8(self):
        for scenario in ExampleDatasets.loadManifest(EXAMPLE_DIR)["scenarios"]:
            for relativePath in ExampleDatasets.declaredFiles(scenario):
                absolute = ExampleDatasets.absolutePath(EXAMPLE_DIR, relativePath)
                if not os.path.isfile(absolute):
                    continue
                with open(absolute, "rb") as handle:
                    head = handle.read(200000)
                try:
                    head.decode("utf-8")
                except UnicodeDecodeError as error:
                    # A multi-byte character split by the read boundary is not a
                    # failure; anything earlier is.
                    if error.start < len(head) - 4:
                        self.fail("%s is not UTF-8 at byte %d"
                                  % (relativePath, error.start))

    def test_generated_files_use_unix_line_endings(self):
        """`archive/original-dat/dnase_values.dat` uses classic-Mac CR endings,
        which is why `wc -l` reports 0 lines for a 1.9 MB file. Nothing this
        generator writes may repeat that."""
        for scenario in ExampleDatasets.loadManifest(EXAMPLE_DIR)["scenarios"]:
            if not scenario.get("simulated"):
                continue          # the real STATegra files are shipped as they came
            for relativePath in ExampleDatasets.declaredFiles(scenario):
                absolute = ExampleDatasets.absolutePath(EXAMPLE_DIR, relativePath)
                with open(absolute, "rb") as handle:
                    head = handle.read(100000)
                self.assertNotIn(b"\r", head,
                                 "%s contains a carriage return" % relativePath)
                self.assertIn(b"\n", head,
                              "%s has no newline in its first 100 kB" % relativePath)


if __name__ == "__main__":
    unittest.main(verbosity=2)
