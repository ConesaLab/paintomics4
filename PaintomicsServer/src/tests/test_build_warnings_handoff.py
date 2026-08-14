"""The species build hands its skipped sources back through a private file.

`common_build_database` runs as a subprocess of `DBManager`, so the only things
that cross the boundary are an exit status and whatever the child writes down.
That channel used to be a fixed `/tmp/build_warnings.tmp`, which had three
problems worth keeping fixed:

  * Two installs running at once on the same machine wrote to one path and read
    each other's warnings, attributing one species' missing sources to another.
  * /tmp is world-writable, so a predictable name there can be pre-created as a
    symlink onto a file the build then truncates.
  * A fixed path has to be deleted before every build so the previous species'
    list is not inherited -- and that delete is one `finally` away from being
    skipped on a failure path.

A fresh mkstemp file per species answers all three: unique, 0600, and unable to
be stale. The parent names it in PAINTOMICS_BUILD_WARNINGS; the child writes
there or, when no parent is listening, writes nothing at all.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_build_warnings_handoff
"""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "../..")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "../AdminTools")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "../AdminTools/scripts")))

import DBManager
import common_build_database


def _writeAsChild(path, specie, rows):
    """Drive the real writer in common_build_database, not a replica of it."""
    saved = (common_build_database.SPECIE, common_build_database.SKIPPED_SOURCES,
             common_build_database.xref, common_build_database.dbname,
             common_build_database.ALL_PATHWAYS, common_build_database.FAILED_LINES,
             common_build_database.UNKNOWN_PATHWAY_PAIRS,
             common_build_database.PATHWAYS_WITHOUT_NODES)
    common_build_database.SPECIE = specie
    common_build_database.SKIPPED_SOURCES = list(rows)
    common_build_database.xref = {}
    common_build_database.dbname = {}
    common_build_database.ALL_PATHWAYS = {}
    common_build_database.FAILED_LINES = {}
    common_build_database.UNKNOWN_PATHWAY_PAIRS = []
    common_build_database.PATHWAYS_WITHOUT_NODES = []
    previous = os.environ.get("PAINTOMICS_BUILD_WARNINGS")
    if path is None:
        os.environ.pop("PAINTOMICS_BUILD_WARNINGS", None)
    else:
        os.environ["PAINTOMICS_BUILD_WARNINGS"] = path
    try:
        # summariseBuild also prints a human-readable block to stderr. That is the
        # point of it; only the hand-off file is under test here.
        stderr = common_build_database.stderr
        common_build_database.stderr = open(os.devnull, "w")
        try:
            common_build_database.summariseBuild()
        finally:
            common_build_database.stderr.close()
            common_build_database.stderr = stderr
    finally:
        if previous is None:
            os.environ.pop("PAINTOMICS_BUILD_WARNINGS", None)
        else:
            os.environ["PAINTOMICS_BUILD_WARNINGS"] = previous
        (common_build_database.SPECIE, common_build_database.SKIPPED_SOURCES,
         common_build_database.xref, common_build_database.dbname,
         common_build_database.ALL_PATHWAYS, common_build_database.FAILED_LINES,
         common_build_database.UNKNOWN_PATHWAY_PAIRS,
         common_build_database.PATHWAYS_WITHOUT_NODES) = saved


class BuildWarningsHandoffTest(unittest.TestCase):

    def setUp(self):
        self._warnings = list(DBManager.INSTALL_WARNINGS)
        DBManager.INSTALL_WARNINGS[:] = []

    def tearDown(self):
        DBManager.INSTALL_WARNINGS[:] = self._warnings

    def test_each_build_gets_its_own_file(self):
        """The whole point: two concurrent installs must not share a path."""
        first = DBManager.newBuildWarningsHandoff()
        second = DBManager.newBuildWarningsHandoff()
        try:
            self.assertNotEqual(first, second,
                                "two builds were handed the same file, which is the "
                                "collision this replaced a fixed /tmp path to avoid")
            self.assertNotIn("build_warnings.tmp", first)
        finally:
            for path in (first, second):
                if os.path.isfile(path):
                    os.remove(path)

    def test_the_file_is_private(self):
        """0600. A world-readable name in /tmp is a name anyone can pre-create."""
        path = DBManager.newBuildWarningsHandoff()
        try:
            self.assertEqual(oct(os.stat(path).st_mode)[-3:], "600")
        finally:
            os.remove(path)

    def test_a_warning_survives_the_round_trip(self):
        path = DBManager.newBuildWarningsHandoff()
        _writeAsChild(path, "ath",
                      [("VEGA", "input file not found: /data/vega.tsv",
                        "VEGA identifiers will be absent for this species")])
        DBManager.collectBuildWarnings("ath", path)

        self.assertEqual(len(DBManager.INSTALL_WARNINGS), 1)
        subject, detail = DBManager.INSTALL_WARNINGS[0]
        self.assertIn("VEGA", subject)
        self.assertIn("VEGA identifiers will be absent", detail)

    def test_a_reason_carrying_tabs_or_newlines_stays_one_record(self):
        """The fields are file paths and str(exception) -- not our text.

        The reader splits on tab and needs four fields, so an unescaped tab or
        newline in a path silently drops the warning it was trying to report.
        """
        path = DBManager.newBuildWarningsHandoff()
        _writeAsChild(path, "ath",
                      [("MAPMAN GENE 2 BIN", "not found in either\n/a/b\tc or /d/e",
                        "no MapMan bins can be assigned")])

        with open(path) as handle:
            lines = [line for line in handle.read().splitlines() if line]
        self.assertEqual(len(lines), 1, "the record was split across lines: %r" % lines)
        self.assertEqual(len(lines[0].split("\t")), 4,
                         "the record gained or lost fields: %r" % lines[0])

        DBManager.collectBuildWarnings("ath", path)
        self.assertEqual(len(DBManager.INSTALL_WARNINGS), 1)

    def test_another_species_rows_are_not_claimed(self):
        path = DBManager.newBuildWarningsHandoff()
        _writeAsChild(path, "mmu", [("UNIPROT", "input file is empty", "UniProt absent")])
        DBManager.collectBuildWarnings("ath", path)
        self.assertEqual(DBManager.INSTALL_WARNINGS, [],
                         "ath claimed mmu's warnings")

    def test_the_file_is_removed_even_when_the_read_fails(self):
        """Otherwise a long batch leaks one file per species into /tmp."""
        path = DBManager.newBuildWarningsHandoff()
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe not utf-8 at all \xff\n")

        DBManager.collectBuildWarnings("ath", path)
        self.assertFalse(os.path.exists(path),
                         "a read that raised left the hand-off file behind")

    def test_the_file_is_removed_after_a_good_read(self):
        path = DBManager.newBuildWarningsHandoff()
        _writeAsChild(path, "ath", [("VEGA", "absent", "VEGA ids absent")])
        DBManager.collectBuildWarnings("ath", path)
        self.assertFalse(os.path.exists(path))

    def test_a_missing_handoff_is_survivable(self):
        """installSpecieData calls this from a `finally`, on the failure path too."""
        DBManager.collectBuildWarnings("ath", None)
        DBManager.collectBuildWarnings("ath", os.path.join(tempfile.gettempdir(), "nope.tsv"))
        self.assertEqual(DBManager.INSTALL_WARNINGS, [])

    def test_no_parent_means_nothing_is_written(self):
        """A build run by hand has nobody listening, and no fixed path to fall back on."""
        legacy = os.path.join(tempfile.gettempdir(), "build_warnings.tmp")
        if os.path.exists(legacy):
            os.remove(legacy)

        _writeAsChild(None, "ath", [("VEGA", "absent", "VEGA ids absent")])

        self.assertFalse(os.path.exists(legacy),
                         "the build recreated the fixed path this change removed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
