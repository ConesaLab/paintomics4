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
    parser.add_argument("--include-stubs", action="store_true",
                        help="also count scripted end-to-end test runs")
    args = parser.parse_args()

    directory = args.traces
    if directory is None:
        from src.conf.serverconf import CLIENT_TMP_DIR
        directory = os.path.join(CLIENT_TMP_DIR, "ai_traces")
    runs = _runs(directory, args.since)
    if not args.include_stubs:
        kept = []
        for entry in runs:
            cfg = next((e.get("result") for e in entry[2]
                        if e.get("tool") == "__config__"), "")
            if '"label": "stub' in (cfg or ""):
                continue
            kept.append(entry)
        dropped = len(runs) - len(kept)
        runs = kept
        if dropped:
            print("(excluded %d scripted end-to-end run(s); --include-stubs to keep)"
                  % dropped)
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
            if tool == "__config__":
                continue
            calls[tool] += 1
            latency[tool].append(e.get("ms") or 0)
            seen.add(tool)
        for tool in seen:
            per_run[tool] += 1

    n = len(runs)
    print("%d archived run(s), %d tool calls\n" % (n, sum(calls.values())))

    # Tools that RAISED. Before failure handlers existed these were invisible:
    # the SDK swallows a tool exception into a string and _trace runs at the end
    # of the tool, so a tool failing on every call looked exactly like a tool
    # nobody called. Runs archived before that fix show nothing here.
    failures = Counter()
    for _job, _stamp, events in runs:
        for e in events:
            if str(e.get("result", "")).startswith("ERROR"):
                failures[e.get("tool")] += 1
    if failures:
        print("tools that RAISED (these are defects, not usage signals):")
        for tool, count in failures.most_common():
            print("  %-26s %d failure(s) of %d call(s)" % (tool, count, calls[tool]))
        print()

    # Distinct configurations present, so a table of averages cannot silently mix
    # two different agents. Runs before the fingerprint existed show as unknown.
    configs = Counter()
    for _job, _stamp, events in runs:
        cfg = next((e.get("result") for e in events
                    if e.get("tool") == "__config__"), None)
        configs[cfg or "(not stamped)"] += 1
    if len(configs) > 1:
        print("configurations in this sample:")
        for cfg, count in configs.most_common():
            print("  %2d run(s)  %s" % (count, cfg[:150]))
        print()
    # Ranked by SECONDS, not calls. The binding constraint is a 10-minute
    # ceiling, and the two orders disagree sharply: notebook_write is the
    # second most-called tool in the archive and costs 4 ms, while
    # delegate_interpretation is called a twentieth as often at a 31 s median.
    # A table sorted by call count says the opposite of what the budget says.
    spend = {t: sum(latency[t]) / 1000.0 for t in calls}
    total_spend = sum(spend.values()) or 1.0
    print("%-26s %6s %8s %9s %9s %9s %7s"
          % ("tool", "calls", "runs", "median ms", "max ms", "total s", "share"))
    for tool, seconds in sorted(spend.items(), key=lambda kv: -kv[1]):
        values = sorted(latency[tool])
        print("%-26s %6d %5d/%d %9d %9d %9.0f %6.1f%%"
              % (tool, calls[tool], per_run[tool], n,
                 values[len(values) // 2], values[-1],
                 seconds, 100.0 * seconds / total_spend))
    print("  %.0f s of tool time over %d run(s) -- %.0f s per run, against a "
          "600 s ceiling." % (total_spend, n, total_spend / max(1, n)))
    print("  Sub-agents and verifiers run concurrently, so this is work done, "
          "not wall-clock: it is the bill the gateway sees.")
    free = [t for t, sec in spend.items() if sec < 1.0 and calls[t] >= 10]
    if free:
        print("  effectively free (<1 s total, local reads): %s"
              % ", ".join(sorted(free)))

    # What verification actually buys. The two failure modes it can catch are
    # very different problems, and until they were counted separately the
    # 30%-of-the-bill spent here had no stated purpose.
    verdicts = Counter()
    per_run_drift = []
    for _job, _stamp, events in runs:
        ok = drift = dead = 0
        for e in events:
            if e.get("tool") != "verify_citation_prefetched":
                continue
            result = e.get("result") or ""
            if result.startswith("match=True supports=True"):
                ok += 1
            elif result.startswith("match=True supports=False"):
                drift += 1
            else:
                dead += 1
        verdicts["supported"] += ok
        verdicts["drifted"] += drift
        verdicts["unquotable"] += dead
        if ok + drift + dead >= 5:
            per_run_drift.append(100.0 * drift / (ok + drift + dead))
    checked = sum(verdicts.values())
    if checked:
        print("\nwhat verification catches, over %d checked citation(s):" % checked)
        for name, label in (("supported", "quote real, supports the claim"),
                            ("drifted", "quote real, does NOT support it"),
                            ("unquotable", "quote not found in the paper")):
            print("  %-32s %5d  %5.1f%%"
                  % (label, verdicts[name], 100.0 * verdicts[name] / checked))
        if per_run_drift:
            per_run_drift.sort()
            print("  drift rate per run: median %.1f%%, mean %.1f%% over %d run(s)"
                  % (per_run_drift[len(per_run_drift) // 2],
                     sum(per_run_drift) / len(per_run_drift), len(per_run_drift)))
        print("  Fabrication is not the failure mode -- claim drift is, and it")
        print("  sits near 1 in 5 whether the text was written from a quote")
        print("  (quote-shelf runs, median 18.3%) or cited afterwards (17.4%).")
        print("  Reordering search and writing does not move it; only a")
        print("  constraint on how far a sentence may go beyond its quote can.")

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

    # Delegation adoption, called out because it predicts the report: runs that
    # skip delegate_interpretation stitch nothing, and two replicates of identical
    # code came out 47 094 vs 10 043 chars of prose on exactly that difference.
    delegated_runs = per_run.get("delegate_interpretation", 0)
    print("\ndelegation: %d of %d runs called delegate_interpretation (%.0f%%)"
          % (delegated_runs, n, 100.0 * delegated_runs / n))
    if delegated_runs < n:
        print("  the rest stitched nothing, which costs most of the report's"
              "\n  per-pathway detail -- submit_report now nudges once when a thin"
              "\n  draft arrives undelegated")

    # read_paper payoff: opened -> cited, matched on PMID.
    opened, cited_after, checked, cited_total = 0, 0, 0, 0
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
        cited_total += len(cited)
    if opened:
        print("\nread_paper, over %d run(s) whose report is still stored:" % checked)
        print("  opened -> cited:  %d of %d (%.0f%%)"
              % (cited_after, opened, 100.0 * cited_after / opened))
        if cited_total:
            print("  cited <- opened:  %d of %d (%.0f%%)"
                  % (cited_after, cited_total, 100.0 * cited_after / cited_total))
        print("  The second number is the one that matters. opened->cited alone"
              "\n  cannot tell 'reading is useless' from 'reading correctly"
              "\n  rejected the paper', and rejecting a source before it becomes an"
              "\n  unquotable citation is the tool working. cited<-opened says"
              "\n  whether reading is on the critical path to a citation at all.")
    _outcomes(runs)

    if not opened:
        print("\nread_paper payoff: no run yet carries pmid= in its trace"
              "\n  (added after the first six rounds; re-run to populate)")

    # Does reading a paper make its citation survive verification? This is the
    # question that decides whether read_paper is worth its 2.2 s, and it can be
    # answered inside a single run: read_paper records the ref_index it opened,
    # the gate records a verdict per ref_index, and both are pre-renumbering, so
    # they join directly. (Across runs they cannot -- renumber_citations rewrites
    # every index at the gate.)
    read_ok = read_bad = unread_ok = unread_bad = 0
    for _job, _stamp, events in runs:
        opened_refs = set()
        for e in events:
            if e.get("tool") == "read_paper":
                m = re.search(r"\[(\d+)\]", str(e.get("args")))
                if m:
                    opened_refs.add(int(m.group(1)))
        for e in events:
            if not e.get("gate") or "verify_citation" not in str(e.get("tool")):
                continue
            m = re.search(r"\[(\d+)\]", str(e.get("args")))
            if not m:
                continue
            ref = int(m.group(1))
            good = "supports=True" in str(e.get("result"))
            if ref in opened_refs:
                read_ok += good
                read_bad += not good
            else:
                unread_ok += good
                unread_bad += not good
    if read_ok + read_bad + unread_ok + unread_bad:
        def rate(ok, bad):
            total = ok + bad
            return "%d/%d (%.0f%%)" % (ok, total, 100.0 * ok / total) if total else "n/a"
        print("\ncitations that PASSED verification, split by whether the agent"
              "\nhad opened the paper with read_paper first:")
        print("  read first:     %s" % rate(read_ok, read_bad))
        print("  never read:     %s" % rate(unread_ok, unread_bad))
        print("  If reading does not raise the pass rate, read_paper is costing"
              "\n  2.2 s a call to confirm what the abstract already said, and the"
              "\n  prompt should stop urging it. If it does, reading is the cheapest"
              "\n  grounding available and the agent should do more of it.")


def _outcomes(runs):
    """Associate each tool with the outcome of the runs that used it.

    Reads the run's own __outcome__ stamp rather than MongoDB: the database keeps
    one interpretation per JOB, so with two jobs reused across forty runs it
    could answer this for two of them. The archive carries configuration,
    tool calls and outcome per run, which is what an association needs.

    Correlation, not cause -- an agent that delegates may differ in other ways.
    It is still the only per-tool outcome signal there is, and it was decisive
    once: runs that never delegated shipped a fifth of the prose.
    """
    from collections import defaultdict as _dd
    with_tool, without_tool = _dd(list), _dd(list)
    watched = ("delegate_interpretation", "read_paper", "cluster_pathways",
               "check_my_citations", "compare_gene_profiles", "notebook_write")
    scored = 0
    for _job, _stamp, events in runs:
        outcome = next((e.get("result") for e in events
                        if e.get("tool") == "__outcome__"), None)
        if not outcome:
            continue
        try:
            outcome = json.loads(outcome)
        except ValueError:
            continue
        scored += 1
        used = {e.get("tool") for e in events if not e.get("gate")}
        for tool in watched:
            (with_tool if tool in used else without_tool)[tool].append(outcome)
    if not scored:
        print("\noutcome by tool: no run carries an __outcome__ stamp yet"
              "\n  (added late in the loop; it fills in from the next run on)")
        return
    print("\noutcome by tool over %d scored run(s) -- correlation, not cause:" % scored)
    print("  %-26s %20s %20s" % ("tool", "used: prose/cites", "not used"))
    for tool in watched:
        a, b = with_tool[tool], without_tool[tool]
        if not a and not b:
            continue
        def avg(rs, k):
            return sum(r.get(k, 0) for r in rs) / len(rs) if rs else 0
        print("  %-26s %11.0f /%5.1f %11.0f /%5.1f  (n=%d/%d)"
              % (tool, avg(a, "prose_chars"), avg(a, "citations"),
                 avg(b, "prose_chars"), avg(b, "citations"), len(a), len(b)))


if __name__ == "__main__":
    main()
