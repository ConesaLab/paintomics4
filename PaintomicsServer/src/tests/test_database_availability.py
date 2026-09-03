#!/usr/bin/env python3
"""The database checkboxes must describe what the server can actually run.

What was wrong
--------------
Step 1 offered KEGG, MapMan and Reactome to every visitor for every organism,
and `PathwayAcquisitionServlet` then intersected the submission with the
organism's own databases before queuing the job:

    organismDB = set(dicDatabases.get(specie, [{}])[0].keys())
    jobInstance.setDatabases(list(set([u'KEGG']) | set(databases).intersection(organismDB)))

So ticking MapMan for mouse, or Reactome for tomato, changed nothing and
reported nothing. The form asked a question whose answer was discarded.

Reactome had the mirror-image problem. It was pre-ticked when
`window.location.hostname` was localhost and unticked everywhere else, which
means the box tracked who was looking rather than what was installed: a
deployment with Reactome fully installed offered it unticked, and a laptop
without it offered it ticked.

What this checks
----------------
`DatabaseAvailability` answers "what can this organism actually be analysed
against" from two facts that are both properties of the deployment -- the
pathway sources present in the organism's own MongoDB, and the identifier
mappings in organismDB.py -- and both the form and the servlet now read that
one answer.

The MongoDB read is injected, so the logic is exercised without a server. One
test at the end talks to a real MongoDB when there is one and skips when there
is not.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_database_availability
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common import DatabaseAvailability


class FakeCollection(object):
    def __init__(self, sources, indexLog=None, name=None):
        self._sources = sources
        self._indexLog = indexLog
        self._name = name

    def distinct(self, field):
        assert field == "source"
        if self._sources is None:
            raise RuntimeError("connection refused")
        return list(self._sources)

    def create_index(self, keys):
        if self._sources is None:
            raise RuntimeError("connection refused")
        if self._indexLog is not None:
            self._indexLog.append((self._name, keys))
        return "source_1"


class FakeDatabase(object):
    def __init__(self, sources, indexLog=None, name=None):
        self.kegg = FakeCollection(sources, indexLog=indexLog, name=name)

    def __getitem__(self, collection):
        """pymongo reaches a collection both ways; so does the code under test."""
        return getattr(self, collection)


class FakeClient(object):
    """Just enough MongoClient for DatabaseAvailability.

    `sourcesByDatabase` is keyed by the full database name, e.g.
    "mmu-paintomics", because that mapping is part of what is under test.
    """

    def __init__(self, sourcesByDatabase):
        self._sources = sourcesByDatabase
        self.closed = False
        #: Every create_index call, as (database name, keys). What
        #: ensurePathwaySourceIndexes is judged on.
        self.indexes = []

    def __getitem__(self, name):
        return FakeDatabase(self._sources.get(name, []),
                            indexLog=self.indexes, name=name)

    def list_database_names(self):
        return list(self._sources)

    def close(self):
        self.closed = True


def clientFor(**sourcesByOrganism):
    return FakeClient({organism + "-paintomics": sources
                       for organism, sources in sourcesByOrganism.items()})


class InstalledDatabasesTest(unittest.TestCase):
    def setUp(self):
        DatabaseAvailability.clearCache()

    def test_an_organism_reports_the_sources_its_mongodb_holds(self):
        """mmu-paintomics tags its 888 pathway documents KEGG or Reactome."""
        client = clientFor(mmu=["KEGG", "Reactome"])
        self.assertEqual(["KEGG", "Reactome"],
                         DatabaseAvailability.getInstalledDatabases("mmu", client=client))

    def test_a_mapman_organism_reports_mapman_and_not_reactome(self):
        client = clientFor(ath=["KEGG", "MapMan"])
        self.assertEqual(["KEGG", "MapMan"],
                         DatabaseAvailability.getInstalledDatabases("ath", client=client))

    def test_a_database_with_no_identifier_mapping_is_not_offered(self):
        """Pathways without an xref mapping would be present and always empty.

        `dosa` is in organismDB.py with KEGG alone. Loading Reactome pathways
        for it would not make Reactome usable: FeatureNamesToKeggIDsMapper has
        no database to turn a feature name into a Reactome identifier, so every
        one of those pathways would match nothing.
        """
        client = clientFor(dosa=["KEGG", "Reactome"])
        self.assertEqual(["KEGG"],
                         DatabaseAvailability.getInstalledDatabases("dosa", client=client))

    def test_pathways_that_are_not_installed_are_not_offered(self):
        """sly has MapMan in organismDB.py; conf alone is not installation.

        This is the half that organismDB.py cannot answer. An entry there says
        an identifier mapping exists, not that anyone ran DBManager for that
        species on this host.
        """
        client = clientFor(sly=[])
        self.assertEqual(["KEGG"],
                         DatabaseAvailability.getInstalledDatabases("sly", client=client))

    def test_kegg_is_always_present(self):
        """The servlet unions KEGG into every job whatever was submitted."""
        client = clientFor(zzz=[])
        self.assertEqual(["KEGG"],
                         DatabaseAvailability.getInstalledDatabases("zzz", client=client))

    def test_a_document_with_no_source_counts_as_kegg(self):
        """`source` was added when Reactome was; its absence dates a document."""
        client = clientFor(mmu=[None, "Reactome"])
        self.assertEqual(["KEGG", "Reactome"],
                         DatabaseAvailability.getInstalledDatabases("mmu", client=client))

    def test_the_order_is_stable_and_independent_of_mongodb(self):
        client = clientFor(mmu=["Reactome", "KEGG"])
        self.assertEqual(["KEGG", "Reactome"],
                         DatabaseAvailability.getInstalledDatabases("mmu", client=client))

    def test_an_unreachable_mongodb_falls_back_to_the_conf(self):
        """Step 1 has to stay submittable when the pathway read fails.

        The fallback is never more permissive than the servlet's own filter, so
        the worst case is the behaviour this change replaced: a box that can be
        ticked and is then dropped.
        """
        client = clientFor(mmu=None)

        # Derived from the conf rather than written out. Spelling the answer as
        # ["KEGG", "Reactome"] made this test assert mmu's 2026 conf rather than
        # the property it is named for, and it duly broke the day OmniPath was
        # added for mmu -- a conf change, with the fallback behaving exactly as
        # intended. What must hold is that the fallback IS the mappable set,
        # ordered by KNOWN_DATABASES, whatever that set happens to contain.
        from src.conf.organismDB import dicDatabases
        mappable = set(dicDatabases["mmu"][0]) | {DatabaseAvailability.MANDATORY_DATABASE}
        expected = [database for database in DatabaseAvailability.KNOWN_DATABASES
                    if database in mappable]

        self.assertEqual(expected,
                         DatabaseAvailability.getInstalledDatabases("mmu", client=client))

    def test_no_organism_yields_kegg(self):
        self.assertEqual(["KEGG"], DatabaseAvailability.getInstalledDatabases(""))
        self.assertEqual(["KEGG"], DatabaseAvailability.getInstalledDatabases(None))


class CacheTest(unittest.TestCase):
    def setUp(self):
        DatabaseAvailability.clearCache()

    def test_the_answer_is_memoised_per_organism(self):
        client = clientFor(mmu=["KEGG", "Reactome"])
        self.assertEqual(["KEGG", "Reactome"],
                         DatabaseAvailability.getInstalledDatabases("mmu", client=client))

        # A second client that would answer differently is not consulted.
        stale = clientFor(mmu=["KEGG"])
        self.assertEqual(["KEGG", "Reactome"],
                         DatabaseAvailability.getInstalledDatabases("mmu", client=stale))

    def test_refresh_bypasses_the_cache(self):
        DatabaseAvailability.getInstalledDatabases(
            "mmu", client=clientFor(mmu=["KEGG", "Reactome"]))
        self.assertEqual(["KEGG"], DatabaseAvailability.getInstalledDatabases(
            "mmu", client=clientFor(mmu=["KEGG"]), refresh=True))

    def test_the_entry_expires(self):
        """Installing a species mid-run must not be invisible until a restart."""
        DatabaseAvailability.getInstalledDatabases(
            "mmu", client=clientFor(mmu=["KEGG"]))

        realNow = DatabaseAvailability._now
        DatabaseAvailability._now = lambda: realNow() + DatabaseAvailability.CACHE_TTL_SECONDS + 1
        try:
            self.assertEqual(["KEGG", "Reactome"],
                             DatabaseAvailability.getInstalledDatabases(
                                 "mmu", client=clientFor(mmu=["KEGG", "Reactome"])))
        finally:
            DatabaseAvailability._now = realNow

    def test_a_returned_list_cannot_corrupt_the_cache(self):
        client = clientFor(mmu=["KEGG", "Reactome"])
        DatabaseAvailability.getInstalledDatabases("mmu", client=client).append("MapMan")
        self.assertEqual(["KEGG", "Reactome"],
                         DatabaseAvailability.getInstalledDatabases("mmu", client=client))


class ResolveDatabasesTest(unittest.TestCase):
    """The rule the servlet applies, and the rule the form must agree with."""

    def setUp(self):
        DatabaseAvailability.clearCache()

    def test_a_selection_is_filtered_to_what_is_installed(self):
        client = clientFor(mmu=["KEGG", "Reactome"])
        self.assertEqual(["KEGG", "Reactome"], DatabaseAvailability.resolveDatabases(
            "mmu", ["Reactome", "MapMan"], client=client))

    def test_kegg_survives_an_empty_selection(self):
        client = clientFor(mmu=["KEGG", "Reactome"])
        self.assertEqual(["KEGG"],
                         DatabaseAvailability.resolveDatabases("mmu", [], client=client))

    def test_none_means_everything_installed(self):
        """What an example dataset asks for: it has no form to submit."""
        client = clientFor(mmu=["KEGG", "Reactome"])
        self.assertEqual(["KEGG", "Reactome"],
                         DatabaseAvailability.resolveDatabases("mmu", None, client=client))

    def test_a_selection_can_never_exceed_the_offer(self):
        """Whatever the form lets you tick is what the job runs, and no more.

        This is the property the whole change rests on: the checkboxes are drawn
        from getInstalledDatabases and the job is filtered by resolveDatabases,
        so a tick that survives the form survives the servlet.
        """
        client = clientFor(mmu=["KEGG", "Reactome"], ath=["KEGG", "MapMan"])
        for organism in ("mmu", "ath"):
            offered = DatabaseAvailability.getInstalledDatabases(organism, client=client)
            resolved = DatabaseAvailability.resolveDatabases(
                organism, offered, client=client)
            self.assertEqual(offered, resolved,
                             "every offered database must reach the job for " + organism)


class OrganismMapTest(unittest.TestCase):
    def setUp(self):
        DatabaseAvailability.clearCache()

    def test_the_shared_database_is_not_an_organism(self):
        client = FakeClient({
            "mmu-paintomics": ["KEGG", "Reactome"],
            "ath-paintomics": ["KEGG", "MapMan"],
            "global-paintomics": ["KEGG"],
            "admin": [],
        })
        # The endpoint opens its own connection, so drive the per-organism call
        # the way it does and assert on the filtering rule directly.
        names = [name for name in client.list_database_names()
                 if name.endswith("-paintomics")
                 and name not in DatabaseAvailability._NON_ORGANISM_DATABASES]
        self.assertEqual(["mmu-paintomics", "ath-paintomics"], names)

    def test_the_live_server_agrees_with_its_mongodb(self):
        """Against a real MongoDB when one is running; skipped when not.

        The fakes above prove the rule; this proves the rule is being applied to
        the real collection -- that `kegg`, `source` and `<code>-paintomics` are
        still the names the data uses.
        """
        try:
            from pymongo import MongoClient
            from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
            client = MongoClient(MONGODB_HOST, MONGODB_PORT,
                                 serverSelectionTimeoutMS=1500)
            names = client.list_database_names()
        except Exception as ex:
            raise unittest.SkipTest("no MongoDB to check against (%s)" % (ex,))

        organisms = [name[:-len("-paintomics")] for name in names
                     if name.endswith("-paintomics")
                     and name not in DatabaseAvailability._NON_ORGANISM_DATABASES]
        if not organisms:
            client.close()
            raise unittest.SkipTest("no organism is installed on this MongoDB")

        try:
            availability = DatabaseAvailability.getInstalledDatabasesByOrganism(
                refresh=True)
            self.assertEqual(sorted(organisms), sorted(availability))
            for organism, databases in availability.items():
                self.assertIn("KEGG", databases,
                              "KEGG is forced onto every job, so it is always offered")
                sources = set(client[organism + "-paintomics"].kegg.distinct("source"))
                for database in databases:
                    if database == "KEGG":
                        continue
                    self.assertIn(database, sources,
                                  "%s is offered for %s but has no pathways loaded"
                                  % (database, organism))
        finally:
            client.close()


class PathwaySourceIndexTest(unittest.TestCase):
    """distinct("source") must not read every pathway document.

    Without an index on `source` the read is a collection scan of documents
    that average 17 KB -- 28 MB for hsa -- repeated for every installed
    organism on every cache miss. /organism_databases, which sweeps all 133
    organisms on paintomics.uv.es, measured 4.9 s idle and 90 to 957 s under
    I/O pressure (2026-09-02/03), nginx cut those off at 60 s, and visitors
    reported the resulting 504 as "Unable to parse the error message". With
    the index the same distinct is an index-only DISTINCT_SCAN.
    """

    def setUp(self):
        DatabaseAvailability.clearCache()

    def test_every_organism_collection_gets_the_source_index(self):
        client = FakeClient({
            "mmu-paintomics": ["KEGG", "Reactome"],
            "ath-paintomics": ["KEGG", "MapMan"],
            "global-paintomics": [],
            "admin": [],
            "PaintomicsDB": [],
        })
        indexed = DatabaseAvailability.ensurePathwaySourceIndexes(client)

        self.assertEqual(["ath", "mmu"], indexed)
        self.assertEqual(
            sorted([("ath-paintomics", DatabaseAvailability.PATHWAY_SOURCE_INDEX),
                    ("mmu-paintomics", DatabaseAvailability.PATHWAY_SOURCE_INDEX)]),
            sorted(client.indexes),
            "the shared database and the job database are not organisms")
        self.assertFalse(client.closed, "a caller's connection is not closed for it")

    def test_one_failing_organism_does_not_cost_the_others_their_index(self):
        client = FakeClient({
            "mmu-paintomics": ["KEGG"],
            "bad-paintomics": None,          # create_index raises
            "ath-paintomics": ["KEGG"],
        })
        self.assertEqual(["ath", "mmu"],
                         DatabaseAvailability.ensurePathwaySourceIndexes(client))

    def test_an_unreachable_mongodb_indexes_nothing_and_does_not_raise(self):
        class Unreachable(FakeClient):
            def list_database_names(self):
                raise RuntimeError("connection refused")

        self.assertEqual([], DatabaseAvailability.ensurePathwaySourceIndexes(
            Unreachable({})))

    def test_the_live_distinct_is_an_index_scan(self):
        """Against a real MongoDB when one is running; skipped when not.

        The fakes prove which collections are indexed; this proves the index
        is the one the query planner picks for the read `_loadedSources`
        actually issues, on the real collection name and field.
        """
        import json
        try:
            from pymongo import MongoClient
            from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
            client = MongoClient(MONGODB_HOST, MONGODB_PORT,
                                 serverSelectionTimeoutMS=1500)
            client.list_database_names()
        except Exception as ex:
            raise unittest.SkipTest("no MongoDB to check against (%s)" % (ex,))

        try:
            indexed = DatabaseAvailability.ensurePathwaySourceIndexes(client)
            populated = [organism for organism in indexed
                         if client[organism + "-paintomics"].kegg.estimated_document_count()]
            if not populated:
                raise unittest.SkipTest("no organism with pathways is installed here")
            for organism in populated:
                database = client[organism + "-paintomics"]
                plan = database.command(
                    "explain", {"distinct": "kegg",
                                "key": DatabaseAvailability.PATHWAY_SOURCE_INDEX},
                    verbosity="queryPlanner")
                self.assertIn("DISTINCT_SCAN", json.dumps(plan, default=str),
                              "%s: distinct(\"source\") still scans the collection"
                              % organism)
        finally:
            client.close()

if __name__ == "__main__":
    unittest.main(verbosity=2)
