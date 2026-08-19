#!/usr/bin/env python3
"""A test must not put fabricated tool calls into the measurement corpus.

`_trace` archives every tool call to CLIENT_TMP_DIR/ai_traces. That directory is
not scratch: it is the corpus every tool-usefulness figure in this project comes
from, and it now holds servlet runs as well as benchmark ones -- the live job
driven through the UI is in there beside the 206 archived replicates.

Five suites were writing into it under job ids "T", "JOB", "FTPROBE" and
"COSTPROBE", so eight fabricated runs were sitting in the dataset. They were
found by listing the directory while looking for something else, which is not a
way to find them again.

Any suite that builds a LoopContext and calls a traced tool must redirect
CLIENT_TMP_DIR to a tempdir before the traced call. `_archive_trace` re-reads
the attribute on every call, so module scope or inside the test both work.

    python -m src.tests.test_tests_do_not_write_to_the_trace_archive
"""
from __future__ import annotations

import glob
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_PASSED, _FAILED = [], []
_HERE = os.path.dirname(os.path.abspath(__file__))

# Probe job ids these suites have used. A trace file named for one of them in the
# live archive is a test's output masquerading as a run.
_PROBE_PREFIXES = ("T-", "JOB-", "FTPROBE-", "COSTPROBE-", "TRACEPROBE")


def _suites_that_trace():
    """Suites that construct a LoopContext and call a traced helper."""
    out = []
    for path in sorted(glob.glob(os.path.join(_HERE, "test_*.py"))):
        # This file talks ABOUT tracing, so it matches its own detector.
        if os.path.basename(path) == os.path.basename(__file__):
            continue
        src = open(path).read()
        if "LoopContext(" not in src:
            continue
        if not re.search(r"L\._trace|_trace\(|_pathway_block|_upgrade_chunk_papers"
                         r"|_screen_papers|read_paper|search_literature", src):
            continue
        out.append((os.path.basename(path), src))
    return out


def test_every_tracing_suite_redirects_the_archive():
    missing = [name for name, src in _suites_that_trace()
               if "CLIENT_TMP_DIR" not in src]
    assert not missing, (
        "these suites build a LoopContext and never redirect CLIENT_TMP_DIR, so "
        "their tool calls land in the live trace corpus: %s" % ", ".join(missing))


def test_the_redirect_reaches_the_writer():
    """It is enough that the redirect happens before the traced CALL.

    An earlier version of this test asserted the redirect must precede the
    `agent_loop` import, on the reasoning that serverconf is read at import time.
    It is not: `_archive_trace` does `from src.conf.serverconf import
    CLIENT_TMP_DIR` INSIDE the function, so it re-reads the module attribute on
    every call and a later redirect still takes effect. The assertion flagged two
    suites that were correct -- one of which redirects inside each test with
    save/restore, which is tighter than doing it at module scope.

    What actually matters is that the module attribute is what gets rebound, not
    a local copy, so the lazy import sees it.
    """
    wrong = []
    for name, src in _suites_that_trace():
        if "CLIENT_TMP_DIR" not in src:
            continue
        if not re.search(r"(serverconf|conf)\.CLIENT_TMP_DIR\s*=", src):
            wrong.append(name)
    assert not wrong, ("these rebind something other than the serverconf module "
                       "attribute, so the lazy import in _archive_trace will not "
                       "see it: %s" % ", ".join(wrong))


def test_the_live_archive_holds_no_probe_runs():
    """The corpus itself, checked. Skips when it is not present."""
    try:
        from src.conf.serverconf import CLIENT_TMP_DIR
    except Exception as exc:
        print("      (serverconf unavailable: %s; skipped)" % exc)
        return
    archive = os.path.join(CLIENT_TMP_DIR, "ai_traces")
    if not os.path.isdir(archive):
        print("      (no archive yet; skipped)")
        return
    probes = [f for f in os.listdir(archive)
              if f.startswith(_PROBE_PREFIXES)]
    assert not probes, ("test runs in the measurement corpus: %s"
                        % ", ".join(sorted(probes)[:6]))


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_every_tracing_suite_redirects_the_archive,
              test_the_redirect_reaches_the_writer,
              test_the_live_archive_holds_no_probe_runs):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
