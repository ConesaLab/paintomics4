#!/usr/bin/env python3
"""Run and score the AI interpretation arms against the pre-registered rule.

`docs/ai-agent-benchmark.md` describes a protocol; this is the thing that
executes it. Until now it did not live in the repository at all -- it was a
scatter of scripts in a session scratchpad, which meant the documented protocol
could not be re-run by anyone, including a later session of mine. Round 25 was
pre-registered against a runner that would have vanished with the tmpdir.

Three subcommands:

    python -m src.benchmarks.ai_arm_bench ready
        One 8-token call to the configured gateway. Exit 0 if it answers.
        Two replicates once burned ten minutes each against a gateway that was
        504-ing every request and produced two "results" that were outage
        reports. A round should not start unless the instrument works.

    python -m src.benchmarks.ai_arm_bench run <jobID> <base|agent> <outdir>
        Runs one arm in-process on a stored job, writes <label>.json (metrics)
        and <label>.report.md (the prose -- the next run on that job overwrites
        the stored record, and metrics cannot answer "is this any good").

    python -m src.benchmarks.ai_arm_bench score <outdir>
        Groups the runs by arm, prints the table, and applies the five rules.

THE COVERAGE METRIC IS PROSE-ONLY, and that is not a detail. The first version
counted a pathway as covered if its name appeared anywhere in the report -- and
both arms APPEND a table of pathway names (the workflow arm's "Enriched Pathway
Summary", the agent arm's "Pathway Clusters"). The agent arm scored 102/102 by
printing a table it had not analysed. Everything from the first table marker or
the References heading onward is excluded here, permanently.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Everything after one of these is appended data, not analysis.
TABLE_MARKERS = ("## Enriched Pathway Summary", "## Pathway Clusters",
                 "### References", "## References")

CEILING_SECONDS = 600

STATEGRA_DESIGN = (
    "Mouse B-cell precursor differentiation time course (Ikaros induction vs "
    "control) over six time points: 0h, 2h, 6h, 12h, 18h, 24h. Five omic "
    "layers: gene expression (RNA-seq), proteomics, miRNA-seq, DNase-seq "
    "chromatin accessibility, metabolomics.")


def prose_of(report):
    """The part of a report a model actually wrote about the biology."""
    end = len(report)
    for marker in TABLE_MARKERS:
        i = report.find(marker)
        if i != -1:
            end = min(end, i)
    return report[:end]


# -- ready -----------------------------------------------------------------

def cmd_ready(_args):
    import requests
    from src.conf.serverconf import AI_PROVIDERS, AI_LLM_PROVIDER
    cfg = AI_PROVIDERS[AI_LLM_PROVIDER]
    try:
        response = requests.post(
            cfg["api_base"].rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer %s" % cfg["api_key"],
                     "Content-Type": "application/json"},
            json={"model": cfg["model"], "max_tokens": 4, "temperature": 0.0,
                  "messages": [{"role": "user", "content": "say ready"}]},
            timeout=(10, 45))
        if response.status_code == 200:
            print("gateway ready")
            return 0
        print("gateway unhealthy: HTTP %d" % response.status_code)
    except Exception as exc:
        print("gateway unreachable: %s" % str(exc)[:110])
    return 1


# -- run -------------------------------------------------------------------

def cmd_run(args):
    os.environ["AI_MAX_RUN_SECONDS"] = str(CEILING_SECONDS)
    os.environ["AI_AGENT_MAX_RUN_SECONDS"] = str(CEILING_SECONDS)
    if args.arm == "agent":
        os.environ["AI_FULL_AGENT"] = "1"
    else:
        os.environ.pop("AI_FULL_AGENT", None)

    from src.classes.AIInterpret.agent import run_ai_agent
    from src.common.DAO.AIInterpretDAO import AIInterpretDAO
    from src.paintomicsserver import Response

    label = args.label or "%s-%s" % (args.arm, args.jobID)
    os.makedirs(args.outdir, exist_ok=True)

    started = time.time()
    response = Response()
    run_ai_agent(args.jobID, args.design, response)
    wall = time.time() - started

    dao = AIInterpretDAO()
    try:
        record = dao.find_by_job_id(args.jobID) or {}
    finally:
        dao.closeConnection()

    metrics = _measure(record, args.arm, args.jobID, wall, response)
    path = os.path.join(args.outdir, label + ".json")
    with open(path, "w") as handle:
        json.dump(metrics, handle, indent=1)
    with open(os.path.join(args.outdir, label + ".report.md"), "w") as handle:
        handle.write(record.get("report") or "")
    print(json.dumps(metrics, indent=1))
    return 0 if metrics["status"] == "done" else 1


def _measure(record, arm, job_id, wall, response=None):
    report = record.get("report") or ""
    papers = record.get("papers") or []
    stats = record.get("stats") or {}
    verification = record.get("verification") or {}

    body = report.split("### References")[0]
    prose = prose_of(report)
    known = {p.get("ref_index") for p in papers}
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", body)} & known

    pathway_index = record.get("pathwayIndex") or []
    covered = [pw.get("name") for pw in pathway_index
               if pw.get("name") and pw["name"].lower() in prose.lower()]

    return {
        "arm": arm,
        "jobID": job_id,
        "status": record.get("status"),
        "wall_s": round(wall, 1),
        "report_chars": len(report),
        "prose_chars": len(prose),
        "papers_retrieved": len(papers),
        "citations_in_body": len(cited),
        "prose_citations": len({int(n) for n in re.findall(r"\[(\d+)\]", prose)}),
        "full_text_cited": sum(1 for p in papers
                               if p.get("ref_index") in cited
                               and p.get("full_text_available")),
        "redacted": verification.get("redacted_count", 0),
        "pathways_indexed": len(pathway_index),
        "prose_pathways_covered": len(covered),
        "prose_pathway_names": sorted(covered)[:40],
        "tool_calls": stats.get("tool_calls"),
        "forced_synthesis": stats.get("forced_synthesis", False),
        "detail": record.get("detail"),
    }


# -- score -----------------------------------------------------------------

METRICS = ("wall_s", "prose_chars", "report_chars", "citations_in_body",
           "full_text_cited", "redacted", "prose_pathways_covered",
           "papers_retrieved")


def _mean(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    return statistics.mean(values) if values else None


def judge(agent_rows, base_rows):
    """The five pre-registered rules. Every one must hold.

    Written before any arm ran, and deliberately not touched since: a rule
    edited after seeing the numbers is not a rule.
    """
    citations_a = _mean(agent_rows, "citations_in_body") or 0
    citations_b = _mean(base_rows, "citations_in_body") or 0
    redacted_a = _mean(agent_rows, "redacted") or 0
    redacted_b = _mean(base_rows, "redacted") or 0
    coverage_a = _mean(agent_rows, "prose_pathways_covered") or 0
    coverage_b = _mean(base_rows, "prose_pathways_covered") or 0
    chars_a = _mean(agent_rows, "report_chars") or 0
    chars_b = _mean(base_rows, "report_chars") or 0

    rules = [
        ("1 every replicate done within %ds" % CEILING_SECONDS,
         bool(agent_rows) and all(r.get("status") == "done"
                                  and (r.get("wall_s") or 0) <= CEILING_SECONDS
                                  for r in agent_rows),
         "%d replicate(s)" % len(agent_rows)),
        ("2 citations >= base",
         citations_a >= citations_b, "%.1f vs %.1f" % (citations_a, citations_b)),
        ("3 redactions <= base + 2",
         redacted_a <= redacted_b + 2, "%.1f vs %.1f" % (redacted_a, redacted_b)),
        ("4 prose coverage >= base",
         coverage_a >= coverage_b, "%.1f vs %.1f" % (coverage_a, coverage_b)),
        ("5 length within [0.6x, 2.0x] of base",
         bool(chars_b) and 0.6 * chars_b <= chars_a <= 2.0 * chars_b,
         "%.0f vs base %.0f" % (chars_a, chars_b)),
    ]
    return rules, all(passed for _, passed, _ in rules)


def cmd_score(args):
    runs = []
    for path in sorted(glob.glob(os.path.join(args.outdir, "*.json"))):
        try:
            runs.append((os.path.basename(path)[:-5], json.load(open(path))))
        except ValueError:
            print("skipped unreadable %s" % path)
    if not runs:
        print("no run metrics in %s" % args.outdir)
        return 1

    groups = {}
    for name, row in runs:
        # The arm is recorded in the row; the label prefix separates variants
        # of the same arm (agent-v20-r1 -> agent-v20).
        # "mode" is what the pre-repo scripts wrote; rounds 1-24 are readable.
        key = row.get("arm") or row.get("mode") or "unknown"
        if key != "base":
            key = name.rsplit("-r", 1)[0] if "-r" in name else name
        groups.setdefault(key, []).append(row)

    order = ["base"] + sorted(k for k in groups if k != "base")
    print("%-26s %s" % ("", "".join("%12s" % k[:12] for k in order)))
    for metric in METRICS:
        cells = "".join("%12s" % ("  n/a" if _mean(groups[k], metric) is None
                                  else "%.1f" % _mean(groups[k], metric))
                        for k in order)
        print("%-26s %s" % (metric, cells))
    print("%-26s %s" % ("replicates",
                        "".join("%12d" % len(groups[k]) for k in order)))

    base = groups.get("base") or []
    if not base:
        print("\nno base replicates: nothing to judge against")
        return 1
    for key in order:
        if key == "base":
            continue
        rules, verdict = judge(groups[key], base)
        print("\n%s:" % key)
        for label, passed, detail in rules:
            print("  %-38s %-5s (%s)" % (label, "PASS" if passed else "FAIL", detail))
        print("  => %s" % ("BETTER than base"
                           if verdict else "NOT better - the incumbent stands"))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ready", help="probe the gateway; exit 0 if it answers")

    run = sub.add_parser("run", help="run one arm on one job")
    run.add_argument("jobID")
    run.add_argument("arm", choices=["base", "agent"])
    run.add_argument("outdir")
    run.add_argument("--label", default=None,
                     help="file stem, e.g. agent-v25-r1 (groups by prefix)")
    run.add_argument("--design", default=STATEGRA_DESIGN)

    score = sub.add_parser("score", help="apply the pre-registered rules")
    score.add_argument("outdir")

    args = parser.parse_args(argv)
    return {"ready": cmd_ready, "run": cmd_run, "score": cmd_score}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
