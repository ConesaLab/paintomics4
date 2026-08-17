import os
import threading

from pymongo import MongoClient

from src.conf.serverconf import MONGODB_DATABASE, MONGODB_HOST, MONGODB_PORT

# One MongoClient per (host, port, pid) for the whole process.
#
# Every DAO used to build its own MongoClient -- there are ~40 bare DAO()
# sites -- and each one costs a topology-monitor thread pair plus a
# server-selection round trip on its first operation, then is thrown away.
# A MongoClient is already thread-safe and already pools its sockets, so one
# per process serves every DAO with the same queries, the same filters and
# the same results; only the lifecycle changes.
#
# The pid is part of the key and that is not optional. The identifier mapper
# and the enrichment workers are fork()ed children (see
# FeatureNamesToKeggIDsMapper._refreshStandardStreamsInForkChild, which exists
# precisely because those children are real), and a MongoClient must never be
# used across a fork: the child inherits sockets whose state belongs to the
# parent's threads, none of which exist in the child. Keying on os.getpid()
# means a child asking for a connection builds its own instead of inheriting
# one, which is exactly what pymongo's "MongoClient opened before fork" warning
# asks for.
_sharedClients = {}
_sharedClientsLock = threading.Lock()

# Clients a forked child inherited from its parent, kept alive on purpose so
# nothing in the child can finalise them. Never read; never emptied. See
# getSharedClient.
_inheritedClients = []


def getSharedClient(host=None, port=None):
    """
    The process-wide MongoClient for (host, port), created on first use.

    Never reused across a fork: the cache is keyed by pid, so a forked child
    misses and builds its own client.
    """
    if host is None:
        host = MONGODB_HOST
    if port is None:
        port = MONGODB_PORT

    key = (host, port, os.getpid())
    client = _sharedClients.get(key)
    if client is not None:
        return client

    with _sharedClientsLock:
        client = _sharedClients.get(key)
        if client is None:
            # A client inherited from a parent process is taken out of the
            # cache and PARKED -- never closed, never released. Belt and
            # braces: never let pymongo finalise an object whose state belongs
            # to another process. Closing it would run pymongo's teardown here
            # over a topology the parent owns, and letting the collector have
            # it hands the same object to pymongo's finalisers (`Pool.__del__`
            # is real on the installed version) at a moment nobody chose.
            # Neither is known to damage the parent -- `close()` on an
            # inherited descriptor releases only the child's copy -- but the
            # cost of holding one dead object for the life of a short-lived
            # worker is nil, and this is the same rule the fork hook in
            # FeatureNamesToKeggIDsMapper applies to inherited stdout/stderr.
            for staleKey in [k for k in _sharedClients if k[2] != key[2]]:
                _inheritedClients.append(_sharedClients.pop(staleKey))
            client = MongoClient(host, port)
            _sharedClients[key] = client
    return client


def _resetSharedClientStateInForkChild():
    """
    Give a forked child an empty cache and a lock of its own.

    The pid key alone already makes the child miss and build its own client.
    What it does not cover is the LOCK: a child forked while another of the
    parent's threads held `_sharedClientsLock` inherits it locked, held by a
    thread that does not exist here, and the child's first getSharedClient()
    blocks forever. That is not theoretical in this codebase --
    `_matchPathways` (PathwayAcquisitionJob.py) runs in a forked worker and
    reaches getSharedClient through
    KeggInformationManager.getPathwaySourceByID -> loadOrganismData ->
    getConnectionByOrganismCode -- and it is the same class of bug that wedged
    a mapper worker for 32 minutes in production, which is why
    FeatureNamesToKeggIDsMapper registers a hook of its own.

    Rebinding the lock is safe because a fork child starts single-threaded:
    there is nobody to race with, and any parent thread mid-critical-section
    simply did not come across.
    """
    global _sharedClientsLock
    _sharedClientsLock = threading.Lock()
    for staleKey in list(_sharedClients):
        _inheritedClients.append(_sharedClients.pop(staleKey))


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_resetSharedClientStateInForkChild)


class SharedClientHandle(object):
    """
    A borrowed view of the process client for code that owns and closes what
    it is handed.

    Everything is forwarded to the real client except close(), which drops the
    reference instead of tearing down a topology other threads are using. It
    exists for KeggInformationManager.getConnectionByOrganismCode, whose one
    caller closes the client it receives in a finally.
    """

    __slots__ = ("_client",)

    def __init__(self, client):
        object.__setattr__(self, "_client", client)

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_client"), name)

    def __getitem__(self, name):
        return object.__getattribute__(self, "_client")[name]

    def __enter__(self):
        return self

    def __exit__(self, excType, excValue, traceback):
        return False

    def __repr__(self):
        return "SharedClientHandle(%r)" % (object.__getattribute__(self, "_client"),)


class DBmanager:
    def __init__(self):
        self.connection = None

    def openConnection(self):
        self.connection = getSharedClient(MONGODB_HOST, MONGODB_PORT)

    def closeConnection(self):
        # A reference drop, not a teardown -- and now an inert one: the client
        # belongs to the process, not to this manager, other DAOs (possibly on
        # other threads) are using it right now, and getCollection looks it up
        # again on every call. Callers keep calling closeConnection() in their
        # finally blocks; it just costs nothing.
        self.connection = None

    def getConnection(self):
        return self.connection

    def getCollection(self, collectionName):
        # Looked up on EVERY call rather than cached on the manager. The
        # lookup is one dict get on a (host, port, pid) key plus an
        # os.getpid(), which is nothing beside a round trip, and it closes the
        # one hole the pid key would otherwise leave: a DAO that is alive when
        # the process forks used to keep serving the child out of
        # self.connection -- the parent's client -- without the pid ever being
        # consulted again.
        self.openConnection()
        db = self.getConnection()[MONGODB_DATABASE]
        return db[collectionName]
