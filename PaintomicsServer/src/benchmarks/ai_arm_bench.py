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
    """Is the gateway answering? Exit 0 if yes, 1 if not -- and say WHICH failure.

    "Unreachable" was the wrong word for two and a half hours of outage. The
    host resolved, TCP connected in 0.02 s and TLS handshook; what failed was the
    model service behind the proxy, which nginx eventually reported as HTTP 504.
    A probe that calls all of that "unreachable" sends you looking at your own
    network. The three cases need different responses:

        cannot resolve / connect  -> your side, or the host is gone
        proxy answers 5xx         -> the gateway is up, its upstream is down
        no answer at all in time  -> upstream is hanging rather than refusing
    """
    import socket
    import requests
    from src.conf.serverconf import AI_PROVIDERS, AI_LLM_PROVIDER
    cfg = AI_PROVIDERS[AI_LLM_PROVIDER]
    base = cfg["api_base"].rstrip("/")
    host = base.split("//")[-1].split("/")[0]

    if not cfg.get("api_key"):
        print("no API key configured for provider %r" % AI_LLM_PROVIDER)
        return 1
    try:
        socket.create_connection((host, 443), timeout=10).close()
    except Exception as exc:
        print("cannot reach %s: %s: %s -- this is the network or the host, "
              "not the model service" % (host, type(exc).__name__, str(exc)[:70]))
        return 1

    try:
        response = requests.post(
            base + "/chat/completions",
            headers={"Authorization": "Bearer %s" % cfg["api_key"],
                     "Content-Type": "application/json"},
            json={"model": cfg["model"], "max_tokens": 4, "temperature": 0.0,
                  "messages": [{"role": "user", "content": "say ready"}]},
            timeout=(10, 45))
    except requests.Timeout:
        print("%s accepts connections but did not answer an 8-token call in 45 s: "
              "the proxy is up and its upstream is hanging" % host)
        return 1
    except Exception as exc:
        print("gateway probe failed: %s: %s" % (type(exc).__name__, str(exc)[:80]))
        return 1

    if response.status_code == 200:
        print("gateway ready")
        return 0
    if response.status_code in (502, 503, 504):
        print("%s answered HTTP %d: the proxy is healthy, the model service "
              "behind it is down. Nothing to fix on this side."
              % (host, response.status_code))
    else:
        print("gateway unhealthy: HTTP %d %s"
              % (response.status_code, response.text[:80].replace("\n", " ")))
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


SALVAGE_MARK = "**Incomplete interpretation.**"
_SALVAGE_STAGE = re.compile(r"last completed stage:\s*([^)]+)\)")


def _salvage_stage(report_text):
    """The stage named in the salvage header, or None for a complete report."""
    head = (report_text or "")[:600]
    if SALVAGE_MARK not in head:
        return None
    found = _SALVAGE_STAGE.search(head)
    return found.group(1).strip() if found else "unknown"


def _measure(record, arm, job_id, wall, response=None):
    """Metrics for one run -- or an honest blank when the run did not finish.

    MongoDB keeps one interpretation per JOB. A run that errors never writes its
    own record, so everything report-derived read here belongs to whatever ran
    on this job LAST -- usually the other arm, minutes earlier. Round 30's
    errored agent replicate reported 17 citations, 19 redactions and 32 393
    characters: base-r1's numbers exactly, and briefly the best citation count
    this arm had ever "produced".

    Report-derived fields are therefore left None unless the record says done.
    wall_s and status are real either way, and rule 1 fails on both.
    """
    if record.get("status") != "done":
        return {
            "arm": arm, "jobID": job_id, "status": record.get("status"),
            "wall_s": round(wall, 1), "detail": record.get("detail"),
            "stale_record": True,
        }
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

    # A salvaged partial report is not comparable to a finished one. It ships
    # BEFORE verification and redaction, so its citation count is inflated by
    # exactly the citations a complete run would have removed: round 33's
    # base-r2 timed out at "references rendered" and reported 30 citations with
    # 0 redactions, its best-looking numbers of the round, precisely because the
    # gate never ran. Counted as a run, flagged, and kept out of the means.
    stage = (record.get("stats") or {}).get("timed_out_at_stage")
    if not stage:
        # The salvage stamps its own header into the report. Read that too: the
        # stats dict is per-run and can be absent (an older metrics file, a
        # record re-read after the next run overwrote stats), while the header
        # travels with the text the user actually sees.
        stage = _salvage_stage(report)
    partial = bool(stage)
    return {
        "arm": arm,
        "jobID": job_id,
        "status": record.get("status"),
        "partial_report": partial or None,
        "timed_out_at_stage": stage,
        "wall_s": round(wall, 1),
        "report_chars": len(report),
        "prose_chars": len(prose),
        # `papers` is the reference list that survived, not what was retrieved:
        # it is filtered to cited papers only when citations survive, so a
        # collapsed run reports MORE papers than a healthy one. Prefer the
        # run's own retrieval count and keep the reference count separately.
        "papers_retrieved": (stats.get("papers_retrieved")
                             or stats.get("papers") or len(papers)),
        "papers_in_references": len(papers),
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
           "papers_retrieved", "papers_in_references")


REPORT_DERIVED = {"citations_in_body", "redacted", "prose_pathways_covered",
                  "full_text_cited", "report_chars", "prose_chars",
                  "prose_citations", "papers_in_references"}


def _mean(rows, key):
    """Mean over the runs that HAVE the value; failed runs carry none.

    Report-derived quantities skip salvaged partial runs: they ship before
    verification, so their citation counts are inflated by whatever the gate
    would have removed. wall_s and status still count -- a partial run is a run,
    and it still fails rule 1.

    Reported alongside the replicate count so a mean over one surviving run of
    two cannot be read as a mean over two.
    """
    usable = [r for r in rows
              if not (r.get("partial_report") and key in REPORT_DERIVED)]
    values = [r[key] for r in usable if r.get(key) is not None]
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
    print("%-26s %s" % ("of which partial",
                        "".join("%12d" % sum(1 for r in groups[k]
                                             if r.get("partial_report"))
                                for k in order)))
    print("%-26s %s" % ("of which measurable",
                        "".join("%12d" % sum(1 for r in groups[k]
                                             if not r.get("stale_record"))
                                for k in order)))

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


# -- jobs ------------------------------------------------------------------

def cmd_jobs(args):
    """Create fresh STATegra jobs (step 1 + step 2) to measure against.

    The protocol needs jobs that exist before an arm runs, and this was the one
    piece that never made it into the repository -- so the documented round
    could not actually be started from a clean checkout. Requires the server to
    be running locally.
    """
    from src.benchmarks.bench_http import Client, _selectedCompounds
    client = Client(args.server, verify=False)
    ids = []
    for i in range(args.count):
        started = time.time()
        step1 = client.post("/pa_step1/example/stategra-multiomics")
        job_id = step1["jobID"]
        first = client.waitForJob(job_id, "step1")
        selected = _selectedCompounds(first.get("matchedMetabolites", []))
        form = [("jobID", job_id)] + [("selectedCompounds[]", c) for c in selected]
        client.post("/pa_step2", data=form)
        second = client.waitForJob(job_id, "step2")
        print("job %d/%d: %s  (%d pathways, %.0f s)"
              % (i + 1, args.count, job_id, len(second.get("pathwaysInfo") or {}),
                 time.time() - started), flush=True)
        ids.append(job_id)
    print(json.dumps(ids))
    return 0


# -- round -----------------------------------------------------------------

def cmd_round(args):
    """One complete round: gateway check, interleaved replicates, verdict.

    Interleaved base/agent/base/agent on purpose. The gateway's throughput
    varies over tens of minutes, and running one arm's replicates back to back
    lets that weather land entirely on one side of the comparison.
    """
    if cmd_ready(args) != 0:
        print("round not started: the gateway is not answering. "
              "A ten-minute replicate against a 504 is an outage report, "
              "not a measurement.")
        return 2

    jobs = args.jobs.split(",")
    plan = []
    for replicate, job in enumerate(jobs, start=1):
        plan.append((job, "base", "base-r%d" % replicate))
        plan.append((job, "agent", "%s-r%d" % (args.label, replicate)))

    for job, arm, label in plan:
        print("\n=== %s  job=%s  %s" % (label, job, time.strftime("%H:%M:%S")),
              flush=True)
        run_args = argparse.Namespace(jobID=job, arm=arm, outdir=args.outdir,
                                      label=label, design=args.design)
        try:
            cmd_run(run_args)
        except Exception as exc:                  # one bad replicate is data
            print("%s FAILED: %s: %s" % (label, type(exc).__name__, exc))
    print("\n=== verdict ===")
    return cmd_score(argparse.Namespace(outdir=args.outdir))


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

    jobs = sub.add_parser("jobs", help="create fresh STATegra jobs to measure on")
    jobs.add_argument("count", type=int, nargs="?", default=2)
    jobs.add_argument("--server", default="http://localhost:8000")

    rnd = sub.add_parser("round", help="gateway check, interleaved replicates, verdict")
    rnd.add_argument("jobs", help="comma-separated jobIDs, one per replicate pair")
    rnd.add_argument("outdir")
    rnd.add_argument("--label", default="agent",
                     help="agent-arm label, e.g. agent-v25")
    rnd.add_argument("--design", default=STATEGRA_DESIGN)

    args = parser.parse_args(argv)
    return {"ready": cmd_ready, "run": cmd_run, "score": cmd_score,
            "jobs": cmd_jobs, "round": cmd_round}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
