#!/usr/bin/env python3
"""Concurrent jobs must share one copy of an organism's KEGG data.

Why this exists
---------------
`KeggInformationManager.getKeggData` is the only method in its class that takes
no lock. Every other one -- the translation cache, the pathway lookups -- wraps
its access in `self.lock`. This one scans a shared deque, loads on a miss, and
inserts, with nothing held:

    for organismData in self.lastOrganisms:      # scan
        if organismData.get("name") == organism:
            return organismData
    organismData = self.loadOrganismData(organism)   # slow: reads Mongo
    if len(self.lastOrganisms) == KEGG_CACHE_MAX_SIZE:
        self.lastOrganisms.popleft()
    self.lastOrganisms.append(organismData)

Measured with six concurrent callers asking for the same organism on a cold
cache: `loadOrganismData` ran **six times** and the cache ended up holding six
copies of `mmu`. One load and one entry is the point of the cache.

That costs twice. The expensive read repeats exactly when the server is
busiest, and the duplicates consume a cache bounded at 25 entries -- so a few
concurrent jobs on one organism can evict every other organism's data and turn
subsequent lookups into more loads. The cache degrades under precisely the load
it exists to absorb.

The deque scan is also unsafe against concurrent mutation. That one is harder
to reach: with the production bound of 25 entries the scan takes microseconds,
and it took a deque of 20,000 to reproduce `RuntimeError: deque mutated during
iteration` reliably. It is recorded here as a reason the locking is not
optional, not as something users are hitting.

The fix uses a lock of its own rather than `self.lock`, because
`loadOrganismData` reads from MongoDB and holding the shared lock across it
would block every translation-cache operation for the duration -- trading a
duplicate load for a stall in unrelated work.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_kegg_cache_concurrency
"""
import collections
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.KeggInformationManager import KeggInformationManager


def _manager(preloaded=0):
    """A manager with its caches wired by hand and no database behind it."""
    manager = KeggInformationManager.__new__(KeggInformationManager)
    manager.lock = threading.RLock()
    manager.organismLock = threading.RLock()
    manager.lastOrganisms = collections.deque(
        [{"name": "org%d" % i} for i in range(preloaded)])
    manager.translationCache = {}
    manager.KEGG_DATA_DIR = ""
    return manager


class SharedOrganismLoadTest(unittest.TestCase):

    def test_concurrent_callers_load_an_organism_once(self):
        manager = _manager()
        loads = []

        def slowLoad(organism):
            loads.append(organism)
            time.sleep(0.1)          # loadOrganismData reads pathways from Mongo
            return {"name": organism}

        manager.loadOrganismData = slowLoad

        threads = [threading.Thread(target=lambda: manager.getKeggData("mmu"))
                   for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(loads), 1,
                         "the organism was loaded %d times for 6 concurrent "
                         "callers; the cache exists to make that once"
                         % len(loads))

    def test_the_cache_holds_one_entry_per_organism(self):
        manager = _manager()
        manager.loadOrganismData = lambda organism: (time.sleep(0.05)
                                                     or {"name": organism})

        threads = [threading.Thread(target=lambda: manager.getKeggData("mmu"))
                   for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        copies = [e for e in manager.lastOrganisms if e.get("name") == "mmu"]
        self.assertEqual(len(copies), 1,
                         "the cache holds %d copies of one organism, crowding "
                         "out the other 24 slots" % len(copies))

    def test_every_caller_gets_the_same_object(self):
        """Callers that share an entry must share it, not get private copies."""
        manager = _manager()
        manager.loadOrganismData = lambda organism: {"name": organism}
        seen = []

        def fetch():
            seen.append(id(manager.getKeggData("mmu")))

        threads = [threading.Thread(target=fetch) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(set(seen)), 1,
                         "callers received %d different objects for one "
                         "organism" % len(set(seen)))

    def test_different_organisms_are_all_cached(self):
        manager = _manager()
        manager.loadOrganismData = lambda organism: {"name": organism}

        threads = [threading.Thread(target=lambda o=o: manager.getKeggData(o))
                   for o in ("mmu", "hsa", "ath", "dme")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        names = sorted(e.get("name") for e in manager.lastOrganisms)
        self.assertEqual(names, ["ath", "dme", "hsa", "mmu"])

    def test_a_cached_organism_is_not_reloaded(self):
        manager = _manager()
        loads = []
        manager.loadOrganismData = lambda organism: (loads.append(organism)
                                                     or {"name": organism})

        manager.getKeggData("mmu")
        manager.getKeggData("mmu")
        manager.getKeggData("mmu")

        self.assertEqual(loads, ["mmu"])

    def test_the_scan_survives_concurrent_mutation(self):
        """Hard to reach at 25 entries; trivial to reach with a bigger deque."""
        manager = _manager(preloaded=5000)
        manager.loadOrganismData = lambda organism: {"name": organism}
        errors = []
        stop = threading.Event()

        def scan():
            try:
                while not stop.is_set():
                    manager.getKeggData("absent-organism")
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))
                stop.set()

        def churn():
            try:
                while not stop.is_set():
                    manager.getKeggData("churn-organism")
            except Exception as exc:
                errors.append("%s: %s" % (type(exc).__name__, exc))
                stop.set()

        threads = [threading.Thread(target=scan) for _ in range(2)] + \
                  [threading.Thread(target=churn) for _ in range(2)]
        for thread in threads:
            thread.start()
        time.sleep(1.5)
        stop.set()
        for thread in threads:
            thread.join(timeout=3)

        self.assertEqual(errors, [], "the shared deque broke under "
                                     "concurrent access: %s" % errors[:2])


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
