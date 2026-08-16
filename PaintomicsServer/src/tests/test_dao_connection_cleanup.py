#!/usr/bin/env python3
"""A DAO connection must be closed even when the operation using it raises.

Why this exists
---------------
`DBmanager.openConnection` builds a **new `MongoClient` per DAO**, and PyMongo
runs topology-monitor threads for each one. Measured on this machine: ten
managers left unclosed take the process from 1 thread to 26, and closing them
returns it to 1. A leaked DAO is therefore ~2.5 leaked threads plus its sockets,
not merely an idle object waiting for the collector.

Several handlers closed theirs on the success path only:

    daoInstance = MessageDAO()
    matchedMessages = daoInstance.findAll(...)   # <- raises
    daoInstance.closeConnection()                # <- skipped

The `except` below catches the error and the request returns a tidy failure, so
nothing looks wrong from outside. What makes this worth fixing is *when* it
fires: `findAll` raises when MongoDB is unreachable or slow, which is exactly
when every request starts failing at once. Each one then leaks a client whose
monitor threads keep retrying the database that is already struggling, so the
failure mode compounds instead of settling.

`adminServletGetMessage` is the sharpest case -- it backs the public welcome
banner (`message_type == "starting_message"` skips the session check), so it is
hit on every page load by every visitor.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_dao_connection_cleanup
"""
import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Functions that take a DAO connection while serving a request. Named
# individually so adding one is deliberate rather than pattern-matched.
MUST_CLOSE_IN_FINALLY = [
    ("servlets/AdminServlet.py", "adminServletGetMessage"),
    ("servlets/AdminServlet.py", "adminServletSaveMessage"),
    ("servlets/AdminServlet.py", "adminServletDeleteMessage"),
    ("servlets/DataManagementServlet.py", "registerFile"),
    ("common/JobInformationManager.py", "getVisualOptions"),
    ("common/JobInformationManager.py", "storeVisualOptions"),
    # _Heartbeat._run is the worst of the set and the easiest to overlook: it
    # already had a try/except, which reads like cleanup and is not. `except`
    # decides whether the error propagates; only `finally` decides whether the
    # connection comes back. This one beats every 30s for the whole life of a
    # job, swallows the error with a bare `pass`, and runs once per concurrent
    # job -- so a flaky database leaks a client every half minute, silently.
    ("classes/AIInterpret/agent.py", "_run"),
]


def _closesInFinally(relativePath, functionName):
    """(found, closesInFinally) for one function."""
    path = os.path.join(_SRC, relativePath)
    source = open(path).read()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != functionName:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Try):
                for statement in sub.finalbody:
                    text = ast.get_source_segment(source, statement) or ""
                    if "closeConnection" in text:
                        return True, True
        body = ast.get_source_segment(source, node) or ""
        return True, "closeConnection" not in body   # no close at all is fine
    return False, False


class ConnectionCleanupTest(unittest.TestCase):

    def test_every_request_scoped_dao_closes_in_a_finally(self):
        offending = []
        for relativePath, functionName in MUST_CLOSE_IN_FINALLY:
            found, ok = _closesInFinally(relativePath, functionName)
            if not found:
                offending.append("%s: %s no longer exists" % (relativePath, functionName))
            elif not ok:
                offending.append("%s: %s closes its DAO only on the success path"
                                 % (relativePath, functionName))

        self.assertEqual(
            offending, [],
            "a DAO connection is left open when the operation raises. Each one "
            "is a MongoClient with its own monitor threads, and the raising "
            "case is a database that is already unreachable:\n  "
            + "\n  ".join(offending))


class LeakCostTest(unittest.TestCase):
    """The measurement behind the rule, so it is not taken on faith."""

    def test_an_unclosed_manager_costs_threads(self):
        import threading
        from src.common.DBmanager import DBmanager

        try:
            baseline = threading.active_count()
            managers = []
            for _ in range(5):
                manager = DBmanager()
                manager.getCollection("userCollection")
                managers.append(manager)
            leaked = threading.active_count()
        except Exception as exc:
            raise unittest.SkipTest("no reachable mongod: %s" % exc)

        try:
            self.assertGreater(
                leaked, baseline,
                "leaking DAO connections no longer costs threads; if PyMongo "
                "changed, the finally rule above may be over-strict")
        finally:
            for manager in managers:
                manager.closeConnection()

    def test_closing_returns_the_threads(self):
        import threading
        import time
        from src.common.DBmanager import DBmanager

        try:
            baseline = threading.active_count()
            managers = [DBmanager() for _ in range(5)]
            for manager in managers:
                manager.getCollection("userCollection")
        except Exception as exc:
            raise unittest.SkipTest("no reachable mongod: %s" % exc)

        for manager in managers:
            manager.closeConnection()
        time.sleep(1)

        self.assertLessEqual(threading.active_count(), baseline + 2,
                             "closing did not return the monitor threads")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
