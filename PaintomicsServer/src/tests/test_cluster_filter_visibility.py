#!/usr/bin/env python3
"""A requested filter that cannot run must not pass for no filter at all.

`build_partition` applies a minimum-features filter by reading pathway totals
from the installed network file. When that file is missing the loader returns
{} by design and the filter is skipped -- so pathways the caller asked to
exclude come back into the universe, the clustering is computed over a wider
set than was requested, and nothing anywhere says so.

Failing soft is right here; failing silently is not. This pins the warning.

    python -m src.tests.test_cluster_filter_visibility
"""
from __future__ import annotations

import io
import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import clusters  # noqa: E402

_PASSED, _FAILED = [], []


class _Pathway:
    matchedGenes = ["a", "b"]
    matchedCompounds = []

    def getSignificanceValues(self):
        return {"Gene expression": ([0.01], [0.01], [0.01])}


class _Job:
    def __init__(self, organism="nosuchorganism"):
        self._organism = organism

    def getMatchedPathways(self):
        return {"xyz00010": _Pathway()}

    def getOrganism(self):
        return self._organism


def _run_capturing(params):
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger = logging.getLogger("src.classes.AIInterpret.clusters")
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        result = clusters.build_partition(_Job(), params=params)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    return result, buffer.getvalue()


def test_an_unappliable_filter_says_so():
    _, logged = _run_capturing({"min_features": 5})
    assert "min_features=5 requested" in logged, (
        "the filter was skipped in silence; the caller cannot tell that the "
        "clustering ran over a wider set than asked for. Logged: %r" % logged)
    assert "NOT" in logged, "the message does not say the filter was skipped"


def test_no_warning_when_no_filter_was_asked_for():
    """min_features=0 means the caller wants everything; nothing was skipped."""
    _, logged = _run_capturing({"min_features": 0})
    assert "min_features" not in logged, (
        "warned about a filter nobody requested: %r" % logged)


def test_the_partition_is_still_produced():
    """Fail soft, not fail hard: a missing network file must not stop the run."""
    result, _ = _run_capturing({"min_features": 5})
    assert isinstance(result, dict), "build_partition stopped returning a partition"


def test_the_loader_returns_empty_for_an_unknown_organism():
    assert clusters._load_total_features("nosuchorganism") == {}


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_an_unappliable_filter_says_so,
              test_no_warning_when_no_filter_was_asked_for,
              test_the_partition_is_still_produced,
              test_the_loader_returns_empty_for_an_unknown_organism):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
