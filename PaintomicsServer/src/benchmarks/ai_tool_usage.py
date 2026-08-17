#!/usr/bin/env python3
"""Which of the agent's tools are worth their place — from the traces.

Every tool in `agent_loop.TOOLBELT` costs its schema in EVERY Decide turn of
every run, so an unused tool is not free: it is a tax on the prompt that carries
the whole investigation. Deciding which to keep has to come from what the agent
actually did, and this reads that off the per-run trace archive written by
`agent_loop._archive_trace` (CLIENT_TMP/ai_traces/<jobID>-<loopStart>.jsonl).

Three questions it answers:

  adoption   in what share of runs was the tool called at all? A tool used in one
             run of ten is a removal candidate; one used in every run is load
             bearing.
  cost       median and worst wall-clock per call. delegate_interpretation ran a
             median 23.6 s against 0-4 ms for the data tools, and the agent was
             told none of it until the descriptions said so.
  payoff     for read_paper specifically: did the paper it opened end up CITED in
             the shipped report? That is the only tool whose usefulness can be
             checked end to end, because the trace records the PMID and PMIDs
             survive the gate's renumbering (ref_index does not).

Usage:
    cd PaintomicsServer
    python -m src.benchmarks.ai_tool_usage                    # all archived runs
    python -m src.benchmarks.ai_tool_usage --since 1787000000 # by loop-start stamp
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def _runs(directory, since):
    """[(jobID, stamp, [event...])] for each archived run, oldest first."""
    out = []
    for path in sorted(glob.glob(os.path.join(directory, "*.jsonl"))):
        name = os.path.basename(path)[: -len(".jsonl")]
        job, _, stamp = name.rpartition("-")
        try:
            stamp = int(stamp)
        except ValueError:
            continue
        if since and stamp < since:
            continue
        events = []
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue          # a run killed mid-write leaves a partial line
        if events:
            out.append((job, stamp, events))
    return out


def _cited_pmids(job_id):
    """PMIDs cited in the report stored for this job, or None if unavailable.

    The stored papers list is post-renumbering and post-redaction: exactly the
    references the reader ends up with.
    """
    try:
        from src.common.DAO.AIInterpretDAO import AIInterpretDAO
        dao = AIInterpretDAO()
        try:
            record = dao.find_by_job_id(job_id) or {}
        finally:
            dao.closeConnection()
    except Exception:
        return None
    papers = record.get("papers")
    if papers is None:
        return None
    report = record.get("report") or ""
    body = report.split("### References")[0]
    kept = {int(n) for n in re.findall(r"\[(\d+)\]", body)}
    return {str(p.get("pmid")) for p in papers if p.get("ref_index") in kept}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", default=None,
                        help="trace directory (default: CLIENT_TMP/ai_traces)")
    parser.add_argument("--since", type=int, default=0,
                        help="only runs whose loop-start stamp is >= this")
    args = parser.parse_args()

    directory = args.traces
    if directory is None:
        from src.conf.serverconf import CLIENT_TMP_DIR
        directory = os.path.join(CLIENT_TMP_DIR, "ai_traces")
    runs = _runs(directory, args.since)
    if not runs:
        print("no archived traces in %s" % directory)
        return

    calls = Counter()
    per_run = defaultdict(int)          # tool -> runs that used it
    latency = defaultdict(list)
    for _job, _stamp, events in runs:
        seen = set()
        for e in events:
            tool = e.get("tool")
            calls[tool] += 1
            latency[tool].append(e.get("ms") or 0)
            seen.add(tool)
        for tool in seen:
            per_run[tool] += 1

    n = len(runs)
    print("%d archived run(s), %d tool calls\n" % (n, sum(calls.values())))
    print("%-26s %6s %8s %9s %9s" % ("tool", "calls", "runs", "median ms", "max ms"))
    for tool, count in calls.most_common():
        values = sorted(latency[tool])
        print("%-26s %6d %5d/%d %9d %9d"
              % (tool, count, per_run[tool], n,
                 values[len(values) // 2], values[-1]))

    # Declared but never called anywhere in the archive: each still costs its
    # schema in every Decide turn.
    try:
        from src.classes.AIInterpret.agent_loop import TOOLBELT
        unused = [t.name for t in TOOLBELT if t.name not in calls]
        if unused:
            print("\nnever called in any archived run (schema cost, no payoff):")
            for name in unused:
                print("  %s" % name)
    except Exception:
        pass

    # read_paper payoff: opened -> cited, matched on PMID.
    opened, cited_after, checked = 0, 0, 0
    for job, _stamp, events in runs:
        pmids = {m.group(1) for e in events if e.get("tool") == "read_paper"
                 for m in [re.search(r"pmid=(\S+)", str(e.get("args")))] if m}
        if not pmids:
            continue
        cited = _cited_pmids(job)
        if cited is None:
            continue
        checked += 1
        opened += len(pmids)
        cited_after += len(pmids & cited)
    if opened:
        print("\nread_paper payoff over %d run(s) whose report is still stored:"
              % checked)
        print("  papers opened: %d · of those cited in the shipped report: %d (%.0f%%)"
              % (opened, cited_after, 100.0 * cited_after / opened))
        print("  (a low rate means reading is not what decides a citation, and the"
              "\n   tool is costing 3 s a call for something the abstract already"
              "\n   settled; a high rate argues for reading MORE before citing)")
    else:
        print("\nread_paper payoff: no run yet carries pmid= in its trace"
              "\n  (added after the first six rounds; re-run to populate)")


if __name__ == "__main__":
    main()
