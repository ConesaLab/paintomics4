"""Stored gene-set collections (GO, Hallmark, user GMT) for one organism.

The installer (`scripts/installGeneSets.py`) writes one document per set into
`<organism>-paintomics.geneSets`:

    {"source": "GO_BP", "id": "GO:0006915", "name": "apoptotic process",
     "genes": ["CASP3", ...],          # upper-cased symbols, true-path
     "parents": ["GO:0012501"]}        # is_a/part_of within the namespace

This module reads them back as `GeneSetCollection`s (cached per process —
GO_BP for mouse is ~12k documents and a Paper run asks for it more than
once), lists what is installed, and parses an inline GMT so a user-supplied
collection needs no install at all.
"""
from __future__ import annotations

import logging

from .enrichment import GeneSetCollection

logger = logging.getLogger(__name__)

_CACHE = {}
_CACHE_LIMIT = 12

GO_SOURCES = ("GO_BP", "GO_MF", "GO_CC")


def _database(organism):
    from pymongo import MongoClient
    from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
    client = MongoClient(MONGODB_HOST, MONGODB_PORT)
    return client, client[str(organism) + "-paintomics"]


def available_collections(organism):
    """[{source, n_sets}] for what the installer has put there."""
    try:
        client, db = _database(organism)
    except Exception as exc:
        logger.warning("gene sets unavailable: %s", exc)
        return []
    try:
        out = []
        for source in db["geneSets"].distinct("source"):
            out.append({"source": source,
                        "n_sets": db["geneSets"].count_documents(
                            {"source": source})})
        return sorted(out, key=lambda e: e["source"])
    except Exception as exc:
        logger.warning("gene sets unavailable for %s: %s", organism, exc)
        return []
    finally:
        client.close()


def load_collection(organism, source):
    """GeneSetCollection or None. Cached per (organism, source)."""
    key = (str(organism), str(source))
    if key in _CACHE:
        return _CACHE[key]
    try:
        client, db = _database(organism)
    except Exception as exc:
        logger.warning("gene sets unavailable: %s", exc)
        return None
    try:
        sets, parents = {}, {}
        for doc in db["geneSets"].find({"source": str(source)},
                                       {"_id": 0}):
            sets[doc["id"]] = {"name": doc.get("name") or doc["id"],
                               "genes": doc.get("genes") or []}
            if doc.get("parents"):
                parents[doc["id"]] = list(doc["parents"])
        if not sets:
            return None
        collection = GeneSetCollection(source, sets, parents or None)
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = collection
        return collection
    except Exception as exc:
        logger.warning("gene sets unreadable for %s/%s: %s",
                       organism, source, exc)
        return None
    finally:
        client.close()


def from_gmt(text, source="custom"):
    """A GeneSetCollection parsed from GMT text (name<TAB>desc<TAB>genes...)."""
    sets = {}
    for line in str(text or "").splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3 or not parts[0]:
            continue
        sets[parts[0]] = {"name": parts[1] or parts[0],
                          "genes": [g for g in parts[2:] if g]}
    if not sets:
        return None
    return GeneSetCollection(source, sets)


def reset_cache_for_tests():
    _CACHE.clear()
