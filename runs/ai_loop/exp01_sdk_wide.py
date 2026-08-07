"""iter01 -- does WIDE parallelism make the SDK smarter?

iter00 ran the SDK at the incumbent's own budget (5 pathways per batch, one
verifier per citation) and found no quality win. That never tested the SDK's
actual argument: that an agent runtime lets you throw many independent agents at
the problem. Token cost is explicitly not a constraint here.

So this arm goes as wide as the design allows:

  * one Pathway Expert agent PER PATHWAY (15 concurrent) instead of 3 batched
    calls covering 5 pathways each -- each expert gets the full tool set and
    many turns to interrogate its own pathway;
  * N independent verifiers PER CITATION, each prompted to REFUTE, with a
    majority vote -- instead of a single verifier whose lone verdict decides;
  * a synthesis pass over 15 deep reports rather than 3 shallow ones.

Everything else is held identical to the incumbent (same prompts, same tools,
same PubMed client, same programmatic safety net), so what is measured is
depth-of-parallelism, not a prompt rewrite.

NOTE on a hard-won constraint: no tool-using agent here declares output_type.
On this vLLM gateway that combination yields zero tool calls and a confident
unevidenced verdict (see the DANGER note in sdk_pipeline._build_agents).

Usage: python runs/ai_loop/exp01_sdk_wide.py <job_id> [n_verifiers]
"""
import asyncio, json, os, sys, time, warnings
warnings.filterwarnings("ignore")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER = os.path.join(REPO, "PaintomicsServer")
sys.path.insert(0, os.path.join(SERVER, "src"))
sys.path.insert(0, SERVER)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("exp01")

from agents import Agent, ModelSettings, Runner
from src.classes.AIInterpret.sdk_pipeline import (
    configure_sdk, _model, PipelineContext, DATA_TOOLS, VERIFY_TOOLS,
)
from src.classes.AIInterpret import prompts as P
from src.classes.AIInterpret.context_builder import (
    build_pathway_context, build_gene_symbol_whitelist, get_organism_name,
    triage_pathways, build_cross_omic_matrix,
)
from src.classes.AIInterpret.pubmed_client import PubMedClient
from src.classes.AIInterpret.verification import (
    verify_report_v2, redact_unverified_v2, renumber_citations,
    parse_references_section,
)
from src.common.JobInformationManager import JobInformationManager
from src.conf.serverconf import (
    AI_MAX_PATHWAYS, AI_SEARCH_SUBAGENT_WORKERS, AI_PAPERS_PER_SEARCH_TASK,
    AI_TEMPERATURE,
)

JOB = sys.argv[1] if len(sys.argv) > 1 else "vyfKO754n4"
N_VERIFIERS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
OUT = os.path.dirname(os.path.abspath(__file__))

# PubMed without an API key allows ~3 req/s; going wider just earns 429s and
# fewer papers. The LLM fan-out is unbounded, the PubMed fan-out is not.
PUBMED_CONCURRENCY = AI_SEARCH_SUBAGENT_WORKERS


async def main():
    configure_sdk()
    stats = {"arm": "sdk_wide", "job": JOB, "n_verifiers": N_VERIFIERS}
    t_all = time.time()

    ji = JobInformationManager().loadJobInstance(JOB)
    if ji is None:
        raise SystemExit("job %s not loadable" % JOB)
    organism_name = get_organism_name(ji.getOrganism())
    import pymongo
    design = (pymongo.MongoClient("localhost", 27017)["PaintomicsDB"]
              ["jobInstanceCollection"].find_one({"jobID": JOB}) or {}).get("experimentDesign", "")

    pathways = build_pathway_context(ji, max_pathways=AI_MAX_PATHWAYS)
    whitelist = build_gene_symbol_whitelist(ji)
    major, minor = triage_pathways(pathways)
    matrix = build_cross_omic_matrix(major)
    ctx = PipelineContext(job_instance=ji, job_id=JOB, organism_name=organism_name,
                          experiment_design=design)

    # ---- literature, per pathway (same client, bounded fan-out) ------------
    t0 = time.time()
    pubmed = PubMedClient()
    sem = asyncio.Semaphore(PUBMED_CONCURRENCY)

    async def _lit(pw):
        query = '"%s"[Title/Abstract] AND "%s"[Title/Abstract]' % (pw["name"], organism_name)
        async with sem:
            try:
                pmids = await asyncio.to_thread(pubmed.search, query, AI_PAPERS_PER_SEARCH_TASK)
                if not pmids:
                    return []
                papers = await asyncio.to_thread(pubmed.fetch_abstracts, list(dict.fromkeys(pmids)))
            except Exception as e:
                logger.warning("pubmed failed for %s: %s", pw["name"], e)
                return []
        for p in papers or []:
            p["pathways"] = [pw["name"]]
        return papers or []

    per_pathway = await asyncio.gather(*[_lit(pw) for pw in pathways])
    seen, unique, n = {}, [], 1
    for group in per_pathway:
        for p in group:
            if p["pmid"] not in seen:
                p["ref_index"] = n; n += 1
                seen[p["pmid"]] = p; unique.append(p)
            else:
                for pw in p.get("pathways", []):
                    if pw not in seen[p["pmid"]].setdefault("pathways", []):
                        seen[p["pmid"]]["pathways"].append(pw)
    ctx.paper_index = {p["ref_index"]: p for p in unique}
    stats["retrieval_s"] = round(time.time() - t0, 1)
    stats["papers"] = len(unique)
    logger.info("retrieved %d unique papers", len(unique))

    # ---- WIDE: one deep expert agent per pathway --------------------------
    t0 = time.time()
    expert = Agent[PipelineContext](
        name="Pathway Expert", model=_model(),
        instructions=P.SYSTEM_PROMPT_PATHWAY_FOCUS,
        model_settings=ModelSettings(temperature=AI_TEMPERATURE),
        tools=DATA_TOOLS)   # tools, deliberately no output_type

    async def _one_pathway(pw):
        papers = [p for p in unique if pw["name"] in p.get("pathways", [])]
        try:
            r = await Runner.run(
                expert,
                P.build_pathway_focus_prompt(pw, papers, design, organism_name),
                context=ctx, max_turns=12)   # generous: depth is the point
            return str(r.final_output)
        except Exception as e:
            logger.warning("expert failed for %s: %s", pw["name"], e)
            return ""

    reports = await asyncio.gather(*[_one_pathway(pw) for pw in pathways])
    reports = [r for r in reports if r.strip()]
    stats["expert_s"] = round(time.time() - t0, 1)
    stats["experts_run"] = len(reports)
    stats["tool_calls_experts"] = ctx.tool_calls
    logger.info("%d expert reports, %d tool calls", len(reports), ctx.tool_calls)

    # ---- synthesis ---------------------------------------------------------
    t0 = time.time()
    synth = Agent[PipelineContext](
        name="Report Writer", model=_model(),
        instructions=P.SYSTEM_PROMPT_SYNTHESIZE,
        model_settings=ModelSettings(temperature=AI_TEMPERATURE), tools=[])
    r = await Runner.run(synth, P.build_synthesis_prompt_v2(
        reports, design, organism_name, unique), context=ctx, max_turns=3)
    report = str(r.final_output)
    stats["synth_s"] = round(time.time() - t0, 1)

    # ---- ADVERSARIAL verification: N refuters per citation, majority vote --
    t0 = time.time()
    verifier = Agent[PipelineContext](
        name="Skeptic", model=_model(),
        instructions=P.SYSTEM_PROMPT_VERIFICATION + (
            "\n\nYou are a SKEPTIC. Your job is to REFUTE this citation. Read the "
            "paper with the tools before ruling. If the cited text is not "
            "present, or does not support the claim, say so plainly. Default to "
            "REFUTED when uncertain."),
        model_settings=ModelSettings(temperature=0.2), tools=VERIFY_TOOLS)

    citations = parse_references_section(report)
    to_verify = [c for c in citations if c.get("cited_text")]
    stats["citations_parsed"] = len(citations)
    stats["citations_verifiable"] = len(to_verify)

    failed = []
    if to_verify:
        vsem = asyncio.Semaphore(8)

        async def _one_vote(cit, k):
            async with vsem:
                try:
                    rr = await Runner.run(
                        verifier,
                        P.build_verification_prompt(cit["claim_sentence"],
                                                    cit["cited_text"], cit["ref_index"])
                        + "\n\n(Independent reviewer %d.)" % (k + 1),
                        context=ctx, max_turns=6)
                    from src.classes.AIInterpret.pipeline import _parse_json_verdict
                    return _parse_json_verdict(str(rr.final_output))
                except Exception as e:
                    logger.warning("verifier %d failed for [%s]: %s", k, cit["ref_index"], e)
                    return {"text_match": False, "supports_claim": False,
                            "reasoning": "verifier error"}

        async def _judge(cit):
            votes = await asyncio.gather(*[_one_vote(cit, k) for k in range(N_VERIFIERS)])
            good = sum(1 for v in votes
                       if v.get("text_match") and v.get("supports_claim"))
            return cit, good, votes

        results = await asyncio.gather(*[_judge(c) for c in to_verify])
        for cit, good, votes in results:
            if good * 2 <= N_VERIFIERS:   # needs a strict majority to survive
                failed.append({"ref_index": cit["ref_index"],
                               "reason": "%d/%d reviewers refuted" % (N_VERIFIERS - good, N_VERIFIERS),
                               "cited_text": cit["cited_text"],
                               "claim_sentence": cit["claim_sentence"],
                               "actual_text": "", "suggested_fix": ""})
        if failed:
            corr = await Runner.run(synth, "Here is your report:\n\n%s\n\n%s" % (
                report, P.build_correction_prompt(report, failed)), context=ctx, max_turns=3)
            report = str(corr.final_output)
    stats["verify_s"] = round(time.time() - t0, 1)
    stats["adversarially_failed"] = len(failed)

    # ---- same programmatic safety net as every other arm -------------------
    final = verify_report_v2(report, whitelist, unique, ji)
    if final.get("failed_citations"):
        report, removed = redact_unverified_v2(report, final["failed_citations"])
        final["redacted_count"] = removed
    report, mapping = renumber_citations(report)
    stats["verification"] = final
    stats["total_s"] = round(time.time() - t_all, 1)
    stats["report_chars"] = len(report)

    with open(os.path.join(OUT, "sdk_wide_%s_report.md" % JOB), "w") as fh:
        fh.write(report)
    with open(os.path.join(OUT, "sdk_wide_%s_stats.json" % JOB), "w") as fh:
        json.dump(stats, fh, indent=2, default=str)
    print(json.dumps({k: v for k, v in stats.items() if k != "verification"},
                     indent=2, default=str))
    print("report chars:", len(report))


asyncio.run(main())
