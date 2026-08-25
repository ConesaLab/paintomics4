"""Derive-or-cache. The only module in this package that touches disk.

The graph is a pure function of the KGML the organism install already ships, and
deriving it costs 1.03 s for the largest species measured (mmu, 364 files,
96,618 edges, 32 MB peak). Persisting it would save ~0.9 s once per process and
cost an install step, a schema, a migration across 87 species, and the
download/ -> current/ -> old/ staging bug class. So nothing is persisted.

If a future measurement says otherwise, this module is the only one that
changes: `get_graph` is the seam.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict

from src.common.KeggGraph.graph import KeggGraph
from src.common.KeggGraph.parser import Edge, parse_directory

try:
    from src.conf.serverconf import KEGG_DATA_DIR
except Exception:                                     # pragma: no cover
    KEGG_DATA_DIR = ""

logger = logging.getLogger(__name__)

CACHE_SIZE = 4
_CACHE = OrderedDict()          # key -> KeggGraph
_LOCK = threading.Lock()


def clear_cache():
    with _LOCK:
        _CACHE.clear()


def _kgml_signature(kgml_dir):
    """(file count, max mtime) -- changes whenever the species is reinstalled."""
    count, newest = 0, 0.0
    try:
        entries = os.listdir(kgml_dir)
    except OSError:
        return None
    for name in entries:
        if not name.endswith(".kgml"):
            continue
        count += 1
        try:
            newest = max(newest, os.path.getmtime(os.path.join(kgml_dir, name)))
        except OSError:
            continue
    return (count, newest) if count else None


def _legacy_edges(path):
    """Rebuild edges from hubData/kegg_interaction.json.

    That file holds each compound's cumulative 1..4-step BALLS, not pairs, so the
    only honest reconstruction is compound -> radius-1 members. It is a safety
    net for species whose KGML was not retained, and it inherits the old parse:
    no subtypes, no reaction direction. `graph.source` says so, and the network
    view refuses to draw arrowheads when it sees it.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("[keggraph] unreadable %s: %s", path, exc)
        return [], {}
    for _ in range(4):                       # tolerate the old double encoding
        if isinstance(payload, list) and len(payload) == 1:
            payload = payload[0]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                break
    if not isinstance(payload, dict):
        return [], {}

    edges, types = [], {}
    for compound, radii in payload.items():
        types[compound] = "compound"
        first = radii[0] if isinstance(radii, list) and radii else []
        if isinstance(first, str):
            first = [first]
        for neighbour in first or []:
            neighbour = str(neighbour)
            types.setdefault(neighbour,
                             "compound" if neighbour[:1] in "CGD" else "gene")
            edges.append(Edge(compound, neighbour, "legacy", "", "", False))
    return edges, types


def get_graph(organism):
    """The organism's KeggGraph, or None if neither source is available."""
    if not organism or not KEGG_DATA_DIR:
        return None
    organism = str(organism)
    base = os.path.join(KEGG_DATA_DIR, "current", organism)
    kgml_dir = os.path.join(base, "kgml")
    signature = _kgml_signature(kgml_dir)
    key = (organism, signature)

    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached

    if signature is not None:
        edges, types, files = parse_directory(kgml_dir)
        source = "kgml"
        logger.info("[keggraph] %s derived from %d KGML files: %d edges",
                    organism, files, len(edges))
    else:
        legacy = os.path.join(base, "hubData", "kegg_interaction.json")
        if not os.path.exists(legacy):
            logger.warning("[keggraph] %s has neither kgml/ nor hubData/"
                           "kegg_interaction.json; hub features unavailable",
                           organism)
            return None
        edges, types = _legacy_edges(legacy)
        source = "legacy-json"
        logger.warning("[keggraph] %s has no KGML; falling back to %s "
                       "(no subtypes, no direction)", organism, legacy)

    if not edges:
        return None
    graph = KeggGraph(edges, types, source)

    with _LOCK:
        _CACHE[key] = graph
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    return graph
