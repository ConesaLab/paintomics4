#!/usr/bin/env python3
"""The MongoDB access layer changes: one shared client, one insert_many, one
features query, one adaptBSON fast path.

Every one of them is a pure performance change, so every test here is an
*equivalence* test: the reference behaviour is spelled out in full (the HEAD
implementation of adaptBSON is inlined below, the two-query feature load is
replayed by hand) and the new code has to reproduce it exactly -- same
documents, same order, same python types.

Usage:
    cd PaintomicsServer
    PYTHONPATH=. python -m src.tests.test_dao_layer_speedups
"""
import ast
import datetime
import multiprocessing
import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from bson.objectid import ObjectId
from bson.int64 import Int64

from src.common import DBmanager as DBmanagerModule
from src.common.DBmanager import DBmanager, SharedClientHandle, getSharedClient
from src.common.DAO.DAO import DAO
from src.common.DAO.PathwayDAO import PathwayDAO
from src.common.DAO.PathwayAcquisitionJobDAO import PathwayAcquisitionJobDAO
from src.common.Util import adapt_string
from src.classes.Pathway import Pathway


# ---------------------------------------------------------------------------
# The reference implementation: DAO.adaptBSON exactly as it stood before the
# fast path. Every assertion below compares against this, not against a
# hand-written expectation, so "identical" means identical to what shipped.
# ---------------------------------------------------------------------------
def referenceAdaptBSON(object):
    if isinstance(object, dict):
        newDict = {}
        for (key, value) in object.items():
            newDict[str(key)] = referenceAdaptBSON(value)
        return newDict
    elif isinstance(object, list):
        newList = []
        for value in object:
            newList.append(referenceAdaptBSON(value))
        return newList
    elif isinstance(object, bool):
        return bool(object)
    elif isinstance(object, int):
        return int(object)
    elif isinstance(object, float):
        return float(object)
    else:
        return adapt_string(object)


def strictEqual(a, b, path="$"):
    """Deep compare that also fails on a changed python type or key order."""
    if a.__class__ is not b.__class__:
        return "%s: type %s != %s" % (path, a.__class__.__name__, b.__class__.__name__)
    if isinstance(a, dict):
        if list(a.keys()) != list(b.keys()):
            return "%s: keys %r != %r" % (path, list(a.keys()), list(b.keys()))
        for key in a:
            bad = strictEqual(a[key], b[key], "%s.%s" % (path, key))
            if bad:
                return bad
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return "%s: length %d != %d" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            bad = strictEqual(x, y, "%s[%d]" % (path, i))
            if bad:
                return bad
        return None
    if a != b:
        return "%s: %r != %r" % (path, a, b)
    return None


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeCollection(object):
    """Records what a DAO asked the database to do."""

    def __init__(self, documents=None):
        self.documents = list(documents or [])
        self.insertManyCalls = []
        self.insertOneCalls = []
        self.findCalls = []

    def insert_many(self, documents, ordered=True):
        self.insertManyCalls.append((list(documents), ordered))
        self.documents.extend(documents)
        return None

    def insert_one(self, document):
        self.insertOneCalls.append(document)
        self.documents.append(document)
        return None

    def find(self, query=None, *args, **kwargs):
        self.findCalls.append(dict(query or {}))
        matched = []
        for document in self.documents:
            if all(document.get(key) == value for key, value in (query or {}).items()):
                matched.append(dict(document))
        return iter(matched)

    def find_one(self, query=None, *args, **kwargs):
        for document in self.find(query):
            return document
        return None

    def delete_many(self, query=None):
        return None


class FakeDBmanager(object):
    def __init__(self, collections):
        self.collections = collections

    def getCollection(self, collectionName):
        return self.collections.setdefault(collectionName, FakeCollection())

    def closeConnection(self):
        return None


def _childTakesTheSharedClient(queue):
    """Run in a forked child: ask for a client and report back."""
    try:
        DBmanagerModule.getSharedClient("localhost", 27017)
        queue.put("ok")
    except BaseException as exc:                       # noqa: BLE001 - reported, not swallowed
        queue.put("error: %r" % (exc,))


# ---------------------------------------------------------------------------
# E24 -- one shared, fork-aware client
# ---------------------------------------------------------------------------
class SharedClientTest(unittest.TestCase):

    def setUp(self):
        self.savedClients = dict(DBmanagerModule._sharedClients)
        self.savedInherited = list(DBmanagerModule._inheritedClients)
        self.realPid = os.getpid()

    def tearDown(self):
        DBmanagerModule._sharedClients.clear()
        DBmanagerModule._sharedClients.update(self.savedClients)
        DBmanagerModule._inheritedClients[:] = self.savedInherited

    def _fakeClientFactory(self):
        built = []

        class FakeDatabase(object):
            def __init__(self, client, name):
                self.client = client
                self.name = name

            def __getitem__(self, collectionName):
                return ("collection", self.name, collectionName)

        class FakeClient(object):
            def __init__(self, host, port):
                self.host = host
                self.port = port
                self.closed = False
                built.append(self)

            def close(self):
                self.closed = True

            def __getitem__(self, name):
                return FakeDatabase(self, name)

        return FakeClient, built

    def test_one_client_per_process(self):
        FakeClient, built = self._fakeClientFactory()
        DBmanagerModule._sharedClients.clear()
        realMongoClient = DBmanagerModule.MongoClient
        DBmanagerModule.MongoClient = FakeClient
        try:
            first = getSharedClient("h", 1)
            for _ in range(50):
                self.assertIs(getSharedClient("h", 1), first)
            self.assertEqual(len(built), 1,
                             "a second MongoClient was built for the same (host, port, pid)")
        finally:
            DBmanagerModule.MongoClient = realMongoClient

    def test_a_different_pid_gets_a_different_client(self):
        """The fork rule, simulated: os.getpid moves, the client must not."""
        FakeClient, built = self._fakeClientFactory()
        DBmanagerModule._sharedClients.clear()
        realMongoClient = DBmanagerModule.MongoClient
        DBmanagerModule.MongoClient = FakeClient
        try:
            parent = getSharedClient("h", 1)
            with mock.patch("os.getpid", return_value=self.realPid + 1):  # "the child"
                child = getSharedClient("h", 1)

                self.assertIsNot(child, parent,
                                 "a forked child reused the parent's MongoClient")
                self.assertEqual(len(built), 2)
                self.assertEqual([key[2] for key in DBmanagerModule._sharedClients],
                                 [self.realPid + 1],
                                 "the parent's entry must be dropped in the child, "
                                 "and only the child's key may remain")
            self.assertFalse(parent.closed,
                             "the inherited client must never be closed in the child: "
                             "that runs pymongo's teardown over a topology the parent owns")
            self.assertIn(parent, DBmanagerModule._inheritedClients,
                          "the inherited client must be parked, not released: nothing "
                          "in the child should ever hand pymongo's finalisers an object "
                          "whose state belongs to another process")
        finally:
            DBmanagerModule.MongoClient = realMongoClient

    def test_get_collection_consults_the_pid_on_every_call(self):
        """A manager alive across a fork must not keep using the parent's client."""
        FakeClient, built = self._fakeClientFactory()
        DBmanagerModule._sharedClients.clear()
        realMongoClient = DBmanagerModule.MongoClient
        DBmanagerModule.MongoClient = FakeClient
        try:
            manager = DBmanager()
            manager.getCollection("userCollection")
            parent = manager.getConnection()

            with mock.patch("os.getpid", return_value=self.realPid + 1):
                manager.getCollection("userCollection")     # same manager, "new process"
                self.assertIsNot(
                    manager.getConnection(), parent,
                    "getCollection served the child out of a cached parent client; "
                    "the pid key is only a guard if it is consulted every time")
            self.assertEqual(len(built), 2)
        finally:
            DBmanagerModule.MongoClient = realMongoClient

    def test_the_fork_hook_resets_the_lock_and_the_cache(self):
        """The state a child must not inherit: a held lock and a stale cache."""
        FakeClient, _ = self._fakeClientFactory()
        DBmanagerModule._sharedClients.clear()
        DBmanagerModule._inheritedClients[:] = []
        realMongoClient = DBmanagerModule.MongoClient
        DBmanagerModule.MongoClient = FakeClient
        savedLock = DBmanagerModule._sharedClientsLock
        try:
            parent = getSharedClient("h", 1)
            DBmanagerModule._sharedClientsLock.acquire()    # as if forked mid-critical-section

            DBmanagerModule._resetSharedClientStateInForkChild()

            self.assertIsNot(DBmanagerModule._sharedClientsLock, savedLock,
                             "the child kept the parent's lock object")
            self.assertTrue(DBmanagerModule._sharedClientsLock.acquire(blocking=False),
                            "the child's lock is still held by a thread that does not exist")
            DBmanagerModule._sharedClientsLock.release()
            self.assertEqual(DBmanagerModule._sharedClients, {})
            self.assertIn(parent, DBmanagerModule._inheritedClients)
        finally:
            if savedLock.locked():
                savedLock.release()
            DBmanagerModule._sharedClientsLock = savedLock
            DBmanagerModule.MongoClient = realMongoClient

    def test_a_child_forked_while_the_lock_is_held_does_not_deadlock(self):
        """The real thing: fork with the lock held, child must still connect.

        _matchPathways runs in a forked worker and reaches getSharedClient
        through KeggInformationManager.loadOrganismData, so a lock inherited in
        the locked state would hang a real job. Needs no mongod: constructing a
        MongoClient does not connect.
        """
        if not hasattr(os, "register_at_fork"):
            raise unittest.SkipTest("no os.register_at_fork on this platform")

        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        process = None
        DBmanagerModule._sharedClientsLock.acquire()
        try:
            process = context.Process(target=_childTakesTheSharedClient, args=(queue,))
            process.start()
            try:
                result = queue.get(timeout=20)
            except Exception:
                result = "TIMED OUT -- the child inherited the lock held"
        finally:
            DBmanagerModule._sharedClientsLock.release()
            if process is not None:
                process.join(10)
                if process.is_alive():
                    process.terminate()
                    process.join(5)

        self.assertEqual(result, "ok", "forked child did not get a client: %s" % result)

    def test_close_connection_does_not_close_the_shared_client(self):
        FakeClient, built = self._fakeClientFactory()
        DBmanagerModule._sharedClients.clear()
        realMongoClient = DBmanagerModule.MongoClient
        DBmanagerModule.MongoClient = FakeClient
        try:
            manager = DBmanager()
            manager.openConnection()
            client = manager.getConnection()
            manager.closeConnection()

            self.assertFalse(client.closed,
                             "closeConnection tore down the process-wide client")
            self.assertIsNone(manager.getConnection(),
                              "closeConnection must still drop this manager's reference")
            manager.openConnection()
            self.assertIs(manager.getConnection(), client,
                          "reopening must hand back the same shared client")
            self.assertEqual(len(built), 1)
        finally:
            DBmanagerModule.MongoClient = realMongoClient

    def test_shared_client_handle_forwards_everything_but_close(self):
        class FakeClient(object):
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

            def __getitem__(self, name):
                return "database:" + name

            def someMethod(self):
                return "forwarded"

        client = FakeClient()
        handle = SharedClientHandle(client)
        handle.close()
        self.assertFalse(client.closed, "the handle closed the shared client")
        self.assertEqual(handle["mmu-paintomics"], "database:mmu-paintomics")
        self.assertEqual(handle.someMethod(), "forwarded")

    def test_a_real_shared_client_is_reused_and_flat_in_threads(self):
        try:
            manager = DBmanager()
            manager.getCollection("userCollection").find_one({})
        except Exception as exc:
            raise unittest.SkipTest("no reachable mongod: %s" % exc)

        before = threading.active_count()
        managers = []
        for _ in range(30):
            other = DBmanager()
            other.getCollection("userCollection").find_one({})
            managers.append(other)
        self.assertLessEqual(
            threading.active_count(), before + 1,
            "30 DAOs still cost threads; they are supposed to share one client")
        for other in managers:
            other.closeConnection()


# ---------------------------------------------------------------------------
# E25 -- adaptBSON fast path
# ---------------------------------------------------------------------------
class AdaptBSONTest(unittest.TestCase):

    def setUp(self):
        self.dao = DAO()

    def _assertMatchesReference(self, document):
        expected = referenceAdaptBSON(document)
        actual = self.dao.adaptBSON(document)
        bad = strictEqual(expected, actual)
        self.assertIsNone(bad, "fast path diverged from the shipped behaviour: %s" % bad)
        return actual

    def test_scalars(self):
        for value in ["", "text", "0", 0, 1, -7, 2 ** 70, 0.0, 1.5, float("inf"),
                      True, False]:
            self._assertMatchesReference(value)

    def test_none_still_becomes_the_string_none(self):
        """193k leaves in foundFeaturesCollection depend on this."""
        self.assertEqual(self.dao.adaptBSON(None), "None")
        self.assertEqual(self.dao.adaptBSON({"a": None, "b": [None]}),
                         {"a": "None", "b": ["None"]})
        self._assertMatchesReference({"a": None, "b": [None, {"c": None}]})

    def test_objectid_still_becomes_its_hex_string(self):
        oid = ObjectId("69a7073bc5345423de5026f6")
        self.assertEqual(self.dao.adaptBSON(oid), "69a7073bc5345423de5026f6")
        document = {"_id": oid, "jobID": "BMDAO"}
        self._assertMatchesReference(document)
        self.assertEqual(self.dao.adaptBSON(document)["_id"], str(oid))

    def test_bson_int64_and_other_int_subclasses_are_not_short_circuited(self):
        """Int64 is an int subclass; the old code turned it into a plain int."""
        document = {"big": Int64(9007199254740993), "small": 3}
        actual = self._assertMatchesReference(document)
        self.assertIs(type(actual["big"]), int)
        self.assertIsNot(type(actual["big"]), Int64)

    def test_exotic_leaves_keep_going_through_adapt_string(self):
        for value in [b"bytes", datetime.datetime(2026, 8, 17, 12, 0, 0),
                      (1, 2), {1, 2}, object]:
            self._assertMatchesReference({"leaf": value})

    def test_non_string_keys_are_still_stringified(self):
        self._assertMatchesReference({1: "one", None: "none", 2.5: "float"})

    def test_str_and_bool_subclasses_take_the_slow_path(self):
        class MyStr(str):
            pass

        class MyInt(int):
            pass

        self._assertMatchesReference({"a": MyStr("x"), "b": MyInt(4)})
        self.assertIs(type(self.dao.adaptBSON(MyStr("x"))), str)
        self.assertIs(type(self.dao.adaptBSON(MyInt(4))), int)

    def test_nested_documents_of_the_shape_this_database_stores(self):
        document = {
            "_id": ObjectId(),
            "jobID": "BMDAO1",
            "ID": "mmu:12345",
            "featureType": "Gene",
            "name": "Gene name",
            "omicsValues": [
                {"omicName": "Gene expression", "inputName": "probe1",
                 "originalName": None, "relevant": [True, False],
                 "values": [1.5, -2.0, 0.0], "isRelevant": True},
                {"omicName": "Proteomics", "inputName": "p1",
                 "originalName": "P1", "relevant": [False],
                 "values": [3], "isRelevant": False},
            ],
            "matchingDB": {"KEGG": ["mmu:12345"], "Reactome": []},
        }
        self._assertMatchesReference(document)

    def test_the_result_is_a_fresh_container(self):
        """Callers get a copy today; they must keep getting one."""
        document = {"a": {"b": [1, 2]}}
        adapted = self.dao.adaptBSON(document)
        self.assertIsNot(adapted, document)
        self.assertIsNot(adapted["a"], document["a"])
        self.assertIsNot(adapted["a"]["b"], document["a"]["b"])

    def test_deeply_nested(self):
        document = {"level0": {}}
        node = document["level0"]
        for depth in range(1, 12):
            node["level%d" % depth] = {"leaf": None, "list": [depth, str(depth)]}
            node = node["level%d" % depth]
        self._assertMatchesReference(document)


# ---------------------------------------------------------------------------
# E10 -- PathwayDAO.insertAll
# ---------------------------------------------------------------------------
def buildPathway(index):
    pathway = Pathway("bmd%03d" % index)
    pathway.setName("Pathway %d" % index)
    pathway.setClassification("Class %d" % (index % 3))
    pathway.setSource("KEGG" if index % 2 else "Reactome")
    pathway.matchedGenes = ["g%d" % index]
    pathway.significanceValues = {"omic": [[10, index, 0.5]]}
    return pathway


class PathwayInsertAllTest(unittest.TestCase):

    def test_one_insert_many_with_the_same_documents_in_the_same_order(self):
        pathways = [buildPathway(i) for i in range(25)]

        # what the old loop wrote: insert() per pathway
        expected = []
        for pathway in pathways:
            document = pathway.toBSON()
            document["jobID"] = "BMDAO_unit"
            expected.append(document)

        collections = {}
        dao = PathwayDAO(dbManager=FakeDBmanager(collections))
        self.assertTrue(dao.insertAll(pathways, {"jobID": "BMDAO_unit"}))

        collection = collections["pathwaysCollection"]
        self.assertEqual(len(collection.insertManyCalls), 1,
                         "insertAll must issue exactly one insert_many")
        self.assertEqual(collection.insertOneCalls, [],
                         "insertAll must not fall back to insert_one")

        documents, ordered = collection.insertManyCalls[0]
        self.assertTrue(ordered, "insert_many must stay ordered=True")
        self.assertIsNone(strictEqual(expected, documents))
        self.assertEqual([d["ID"] for d in documents], ["bmd%03d" % i for i in range(25)])

    def test_an_empty_list_writes_nothing(self):
        collections = {}
        dao = PathwayDAO(dbManager=FakeDBmanager(collections))
        self.assertTrue(dao.insertAll([], {"jobID": "BMDAO_unit"}))
        self.assertEqual(collections, {},
                         "an empty insertAll issued a database call")

    def test_an_empty_list_does_not_need_a_jobID(self):
        """The old loop never read otherParams for an empty list."""
        collections = {}
        dao = PathwayDAO(dbManager=FakeDBmanager(collections))
        self.assertTrue(dao.insertAll([], None))
        self.assertTrue(dao.insertAll([], {}))
        self.assertEqual(collections, {},
                         "an empty insertAll must not even reach for a collection")

    def test_a_generator_of_values_is_accepted(self):
        """The callers pass dict .values(), not a list."""
        pathways = {p.getID(): p for p in [buildPathway(i) for i in range(5)]}
        collections = {}
        dao = PathwayDAO(dbManager=FakeDBmanager(collections))
        dao.insertAll(pathways.values(), {"jobID": "BMDAO_unit"})
        documents, _ = collections["pathwaysCollection"].insertManyCalls[0]
        self.assertEqual([d["ID"] for d in documents], list(pathways.keys()))

    def test_the_graphical_data_branch_is_untouched(self):
        pathways = [buildPathway(i) for i in range(4)]
        for pathway in pathways:
            pathway.graphicalOptions = None

        collections = {}
        dao = PathwayDAO(dbManager=FakeDBmanager(collections))

        recorded = []

        class RecordingGraphicalDataDAO(object):
            def __init__(self, *args, **kwargs):
                pass

            def insert(self, instance, otherParams=None):
                recorded.append(otherParams.get("pathwayID"))

        import src.common.DAO.PathwayDAO as pathwayDAOModule
        realDAO = pathwayDAOModule.GraphicalDataDAO
        pathwayDAOModule.GraphicalDataDAO = RecordingGraphicalDataDAO
        try:
            dao.insertAll(pathways, {"jobID": "BMDAO_unit", "saveGraphicalData": True})
        finally:
            pathwayDAOModule.GraphicalDataDAO = realDAO

        collection = collections["pathwaysCollection"]
        self.assertEqual(len(collection.insertOneCalls), 4,
                         "the saveGraphicalData branch must stay per-pathway")
        self.assertEqual(collection.insertManyCalls, [])
        self.assertEqual(recorded, ["bmd%03d" % i for i in range(4)])


# ---------------------------------------------------------------------------
# E26 -- one features query on job load
# ---------------------------------------------------------------------------
class FindByIDPartitionTest(unittest.TestCase):

    def _featureDocument(self, index, featureType):
        return {
            "_id": ObjectId(),
            "jobID": "BMDAO_unit",
            "ID": "%s%03d" % (featureType[0].lower(), index),
            "name": "%s %d" % (featureType, index),
            "featureType": featureType,
            "omicsValues": [{"omicName": "o", "inputName": "in%d" % index,
                             "originalName": None, "values": [float(index)],
                             "relevant": [True]}],
        }

    def _collections(self, featureDocuments):
        return {
            "jobInstanceCollection": FakeCollection([{
                "_id": ObjectId(), "jobID": "BMDAO_unit", "userID": None,
                "organism": "mmu", "name": "unit job", "lastStep": 1,
            }]),
            "featuresCollection": FakeCollection(featureDocuments),
            "foundFeaturesCollection": FakeCollection([]),
            "pathwaysCollection": FakeCollection([]),
        }

    def test_one_query_and_the_same_order_as_two(self):
        # Interleaved on purpose: a single find() returns them mixed, so the
        # partition -- not the cursor -- is what has to restore the order.
        documents = []
        for index in range(20):
            documents.append(self._featureDocument(index, "Gene"))
            documents.append(self._featureDocument(index, "Compound"))

        collections = self._collections(documents)
        job = PathwayAcquisitionJobDAO(dbManager=FakeDBmanager(collections)).findByID("BMDAO_unit")
        self.assertIsNotNone(job)

        featureQueries = [q for q in collections["featuresCollection"].findCalls]
        self.assertEqual(len(featureQueries), 1,
                         "the job load must issue ONE features query, not one per type")
        self.assertEqual(featureQueries[0], {"jobID": "BMDAO_unit"})

        # what the two-query version produced
        expectedGenes = [d["ID"] for d in documents if d["featureType"] == "Gene"]
        expectedCompounds = [d["ID"] for d in documents if d["featureType"] == "Compound"]

        self.assertEqual(list(job.getInputGenesData().keys()), expectedGenes)
        self.assertEqual(list(job.getInputCompoundsData().keys()), expectedCompounds)

    def test_an_unknown_feature_type_is_still_dropped(self):
        """Neither old query matched it, so neither dict may gain it."""
        documents = [self._featureDocument(0, "Gene"),
                     self._featureDocument(1, "Region"),
                     self._featureDocument(2, "Compound")]
        documents[1]["ID"] = "unknown"
        del documents[2]["featureType"]              # and one with no type at all
        documents[2]["ID"] = "typeless"

        collections = self._collections(documents)
        job = PathwayAcquisitionJobDAO(dbManager=FakeDBmanager(collections)).findByID("BMDAO_unit")

        self.assertEqual(list(job.getInputGenesData().keys()), ["g000"])
        self.assertEqual(list(job.getInputCompoundsData().keys()), [])

    def test_duplicate_ids_merge_in_the_original_order(self):
        """addInputGeneData merges duplicates, so relative order is semantic."""
        first = self._featureDocument(0, "Gene")
        second = self._featureDocument(0, "Gene")
        second["omicsValues"][0]["inputName"] = "second"
        collections = self._collections([first, second])
        job = PathwayAcquisitionJobDAO(dbManager=FakeDBmanager(collections)).findByID("BMDAO_unit")

        self.assertEqual(list(job.getInputGenesData().keys()), ["g000"])
        self.assertEqual(
            [v.getInputName() for v in job.getInputGenesData()["g000"].getOmicsValues()],
            ["in0", "second"],
            "the merge order changed, so a duplicate feature's omic values moved")


# ---------------------------------------------------------------------------
# E30 -- indexes, and what the nightly cleanup is allowed to delete
# ---------------------------------------------------------------------------
class CleanDatabasesTest(unittest.TestCase):

    def _source(self, relativePath):
        return open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), relativePath)).read()

    def test_the_ai_collection_is_in_the_index_list(self):
        from src.AdminTools.scripts.clean_databases import JOBID_INDEXES
        self.assertIn(("aiInterpretationCollection", "jobID"), JOBID_INDEXES)

    def test_rebuild_indexes_no_longer_calls_reindex(self):
        """Removed in pymongo 4: `.reindex` resolves to a sub-collection there."""
        self.assertNotIn(".reindex(", self._source("AdminTools/scripts/clean_databases.py"))

    def test_the_gtf_cache_is_not_a_user_directory(self):
        """Every directory under CLIENT_TMP that no user claims gets rmtree'd.

        `<CLIENT_TMP>/gtfcache` is the shared GTF cache Bed2GeneJob writes, and
        no user will ever own it, so without this exclusion every cleanup run
        deleted the whole cache.
        """
        import re
        from src.AdminTools.scripts.clean_databases import NON_USER_CLIENT_TMP_DIRS

        self.assertIn("nologin", NON_USER_CLIENT_TMP_DIRS)

        source = self._source("classes/JobInstances/Bed2GeneJob.py")
        match = re.search(r'"cache_dir"\s*:\s*SERVER_CLIENT_TMP_DIR\s*\+\s*"([^"]+)"', source)
        self.assertIsNotNone(
            match, "Bed2GeneJob no longer builds its cache_dir from CLIENT_TMP; "
                   "check whether the cleanup exclusion below is still the right name")
        cacheDirName = match.group(1).strip("/")
        self.assertIn(
            cacheDirName, NON_USER_CLIENT_TMP_DIRS,
            "the GTF cache directory Bed2GeneJob creates (%r) is not excluded from "
            "the orphan-directory sweep in cleanDatabases, so the nightly cron will "
            "delete it" % cacheDirName)

    def test_the_directory_sweep_uses_the_exclusion_list(self):
        source = self._source("AdminTools/scripts/clean_databases.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "cleanDatabases":
                body = ast.get_source_segment(source, node) or ""
                self.assertIn("NON_USER_CLIENT_TMP_DIRS", body,
                              "cleanDatabases stopped using the exclusion list")
                self.assertNotIn('user_dirs.remove("nologin")', body,
                                 "the hardcoded single exclusion is back")
                return
        self.fail("cleanDatabases no longer exists")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
