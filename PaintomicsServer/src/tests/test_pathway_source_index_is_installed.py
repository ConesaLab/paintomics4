#!/usr/bin/env python3
"""Every path that writes pathway documents must leave a `source` index behind.

Why
---
`DatabaseAvailability._loadedSources` answers "which pathway databases does
this organism have" with distinct("source") on the organism's `kegg`
collection. Without an index that is a scan of every pathway document -- 17 KB
each on average, 28 MB for hsa -- once per organism per cache miss, and
/organism_databases sweeps every organism. On paintomics.uv.es (133 organisms,
8 GB, swapping) the sweep took 4.9 s idle and 90 to 957 s under I/O pressure;
nginx gave up at 60 s and the visitor saw "Unable to parse the error message".

The index is cheap and turns the read into an index-only DISTINCT_SCAN, but
it only helps if it exists on every organism, including the ones installed
next year. So it is created in four places and this file pins all four:

  * the two installers that build an organism from KEGG
    (common_build_database.createDatabase, customSpeciesInstaller)
  * the installer that adds a source to an existing organism (omnipathInstaller)
  * the running server's startup pass and the nightly cron, for organisms
    installed before the index existed (paintomicsserver.ensureIndexes,
    clean_databases.rebuildIndexes) -- both through
    DatabaseAvailability.ensurePathwaySourceIndexes, so there is one sweep
    and one definition of the key.

Why source assertions
---------------------
The installers download from KEGG and shell out to mongoimport; the server's
startup pass is a daemon thread. None of them can run in a unit test. The
behaviour was verified against a live MongoDB (test_database_availability
checks the query plan); these keep the wiring that produced it from being
unpicked file by file.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_pathway_source_index_is_installed
"""
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with io.open(os.path.join(SRC, *parts), encoding="utf-8") as handle:
        return handle.read()


def _function(source, name):
    """The body of `def name(` up to the next top-level def/class."""
    match = re.search(r"^def %s\(.*?(?=^def |^class |\Z)" % re.escape(name),
                      source, re.S | re.M)
    assert match, "no function %s" % name
    return match.group(0)


# `create_index("source")` or `create_index([("source", ASCENDING)])`: both
# build the same index, source_1, and both are what the planner needs.
SOURCE_INDEX = re.compile(
    r'create_index\(\s*(?:"source"|\[\s*\(\s*"source"\s*,\s*ASCENDING\s*\)\s*\])\s*\)')


class InstallersCreateTheIndexTest(unittest.TestCase):
    def test_the_kegg_build_indexes_source_beside_the_xref_indexes(self):
        body = _function(_read("AdminTools", "scripts", "common_build_database.py"),
                         "createDatabase")
        self.assertRegex(body, r"db\.kegg\." + SOURCE_INDEX.pattern)

    def test_the_custom_species_installer_indexes_source(self):
        source = _read("AdminTools", "customSpeciesInstaller.py")
        self.assertRegex(source, r"db\.kegg\." + SOURCE_INDEX.pattern)

    def test_the_omnipath_installer_indexes_source_after_writing(self):
        body = _function(_read("AdminTools", "omnipathInstaller.py"), "_write")
        self.assertRegex(body, r"\[PATHWAY_COLLECTION\]\." + SOURCE_INDEX.pattern)


class TheServerBackfillsTheIndexTest(unittest.TestCase):
    """Organisms installed before the index existed get it without a rebuild."""

    def test_startup_ensures_the_index_on_every_organism(self):
        source = _read("paintomicsserver.py")
        match = re.search(r"def ensureIndexes\(self\):.*?(?=\n    def )", source, re.S)
        self.assertTrue(match, "paintomicsserver.ensureIndexes is gone")
        self.assertIn("ensurePathwaySourceIndexes", match.group(0))

    def test_the_nightly_cron_ensures_it_too(self):
        body = _function(_read("AdminTools", "scripts", "clean_databases.py"),
                         "rebuildIndexes")
        self.assertIn("ensurePathwaySourceIndexes", body)

    def test_the_key_is_defined_once(self):
        """Installers and the sweep must agree on the field, or the planner
        has an index it cannot use."""
        from src.common import DatabaseAvailability
        self.assertEqual("source", DatabaseAvailability.PATHWAY_SOURCE_INDEX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
