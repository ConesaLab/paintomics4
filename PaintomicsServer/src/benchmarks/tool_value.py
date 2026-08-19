#!/usr/bin/env python3
"""Which tools earn their place, computed over every archived run.

The standing question for this agent is "which tool is really useful and which
is not". It has been answered, round after round, from a SINGLE run's trace --
because that was the trace still on disk. Meanwhile `_archive_trace` has been
keeping every run since it was added, and each of those files ends with an
`__outcome__` stamp carrying citations, redactions and wall clock. Trace and
outcome sit in the same file, so no join is needed and none of the timing
guesswork that produced a wrong per-call table applies.

    python -m src.benchmarks.tool_value              # last 40 runs
    python -m src.benchmarks.tool_value --runs 80
    python -m src.benchmarks.tool_value --all

Reads only. It never touches a running round.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# The architecture marker. Traces from before delegation describe a different
# agent, and averaging them in is how a retired design goes on voting.
ERA_MARKER = "delegate_interpretation"


def _trace_dir():
    from src.conf.serverconf import CLIENT_TMP_DIR
    return os.path.join(CLIENT_TMP_DIR, "ai_traces")


def load_runs(limit=40, era_marker=ERA_MARKER):
    """(events, outcome) per archived run, oldest first, current era only."""
    files = sorted(glob.glob(os.path.join(_trace_dir(), "*.jsonl")),
                   key=lambda f: int(os.path.basename(f).rsplit("-", 1)[1].split(".")[0])
                   if "-" in os.path.basename(f) else 0)
    runs = []
    for path in files:
        try:
            events = [json.loads(line) for line in open(path) if line.strip()]
        except Exception:
            continue                                  # a truncated tail is not fatal
        if not events:
            continue
        tools = {e.get("tool") for e in events if not e.get("gate")}
        if era_marker and era_marker not in tools:
            continue
        stamp = next((e for e in events if e.get("tool") == "__outcome__"), None)
        try:
            outcome = json.loads(stamp["result"]) if stamp else {}
        except Exception:
            outcome = {}
        runs.append((os.path.basename(path), events, outcome))
    return runs[-limit:] if limit else runs


def adoption(runs):
    """Per tool: how many runs called it, median calls, failures, median seconds.

    A tool nobody calls is not free -- its schema and description ride in every
    Decide turn of every run -- so "used in 0 runs" is a removal candidate, and
    that is the number this table exists to surface.
    """
    used, calls, fails, secs = (collections.Counter(), collections.defaultdict(list),
                                collections.Counter(), collections.defaultdict(list))
    for _name, events, _o in runs:
        counted = collections.Counter(e["tool"] for e in events if not e.get("gate"))
        for tool, n in counted.items():
            used[tool] += 1
            calls[tool].append(n)
        for e in events:
            if e.get("gate"):
                continue
            if str(e.get("result", "")).startswith("ERROR"):
                fails[e["tool"]] += 1
            secs[e["tool"]].append(e.get("ms", 0) / 1000.0)
    rows = []
    for tool in sorted(used, key=lambda t: -used[t]):
        rows.append({"tool": tool, "runs": used[tool],
                     "median_calls": st.median(calls[tool]),
                     "failures": fails[tool],
                     "median_s": st.median(secs[tool]) if secs[tool] else 0.0})
    return rows


def _tertiles(rows, key, outcome_key):
    """Median outcome for the bottom and top third by `key`.

    Preferred to a correlation because these are small samples with long tails,
    where one 125-paper run moves r and moves no median.
    """
    usable = [r for r in rows if r.get(key) is not None
              and r.get(outcome_key) is not None]
    if len(usable) < 6:
        return None
    usable.sort(key=lambda r: r[key])
    cut = max(1, len(usable) // 3)
    low, high = usable[:cut], usable[-cut:]
    return (st.median([r[key] for r in low]), st.median([r[outcome_key] for r in low]),
            st.median([r[key] for r in high]), st.median([r[outcome_key] for r in high]))


def retrieval_value(runs):
    """Does retrieving more actually produce more citations?"""
    rows = []
    for _name, events, outcome in runs:
        if outcome.get("citations") is None:
            continue
        counted = collections.Counter(e["tool"] for e in events if not e.get("gate"))
        rows.append({"searches": counted.get("search_literature", 0),
                     "reads": counted.get("read_paper", 0),
                     "retrieved": outcome.get("papers_retrieved") or 0,
                     "cited_papers": outcome.get("papers") or 0,
                     "citations": outcome["citations"],
                     "redacted": outcome.get("redacted") or 0,
                     "seconds": outcome.get("seconds") or 0})
    return rows


def report(runs):
    out = []
    out.append("%d archived runs, current architecture (%s)\n" % (len(runs), ERA_MARKER))
    out.append("%-26s %9s %11s %8s %8s" % ("tool", "used in", "med calls",
                                           "failures", "med s"))
    for row in adoption(runs):
        out.append("%-26s %6d/%-2d %11.0f %8d %8.1f"
                   % (row["tool"], row["runs"], len(runs), row["median_calls"],
                      row["failures"], row["median_s"]))

    rows = retrieval_value(runs)
    if not rows:
        out.append("\nNo run carried an outcome stamp; nothing to value.")
        return "\n".join(out)

    ret = [r["retrieved"] for r in rows if r["retrieved"]]
    share = [100.0 * r["cited_papers"] / r["retrieved"] for r in rows if r["retrieved"]]
    secs = [r["seconds"] for r in rows if r["seconds"]]
    out.append("\nRetrieval")
    out.append("  papers retrieved per run : median %5.0f  (min %d, max %d)"
               % (st.median(ret), min(ret), max(ret)))
    out.append("  papers in the references : median %5.0f" % st.median(
        [r["cited_papers"] for r in rows]))
    out.append("  share ever cited         : median %4.0f%%" % st.median(share))

    for key, label in (("searches", "search_literature calls"),
                       ("retrieved", "papers retrieved"),
                       ("reads", "read_paper calls")):
        t = _tertiles(rows, key, "citations")
        if t:
            out.append("  %-24s %3.0f -> %2.0f citations | %3.0f -> %2.0f citations"
                       % (label, t[0], t[1], t[2], t[3]))

    if secs:
        over = sum(1 for s in secs if s > 600)
        out.append("\nThe ten-minute brief")
        out.append("  wall clock: median %.0f s; %d of %d runs over 600 s"
                   % (st.median(secs), over, len(secs)))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=40)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    runs = load_runs(limit=0 if args.all else args.runs)
    if not runs:
        print("No archived traces for the current era in %s" % _trace_dir())
        return
    print(report(runs))


if __name__ == "__main__":
    main()
