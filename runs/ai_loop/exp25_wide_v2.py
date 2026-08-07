"""iter25 — wide parallelism, re-tested on the repaired substrate.

iter01 ran one expert agent per pathway and produced the worst score of the loop
(4.75). Two reasons to distrust that result now:

  * It ran on the broken substrate -- before references rendered deterministically,
    before quote yield went 32% -> 84%, before retrieval was batched. Every
    comparison from that era measured plumbing, and the iter00 framework verdict
    made on the same substrate had to be retracted.
  * The experts made **zero tool calls**, because `build_pathway_focus_prompt`
    already contained the pathway's data. Nothing was left to investigate, so
    "deep agent" collapsed into "one shallow call, fifteen times".

This fixes both. Each expert gets the pathway NAME and its enrichment statistics
only -- no gene tables -- and is told the data is reachable solely through its
tools. That is the configuration where per-pathway agents could actually pay:
each one interrogates its own pathway rather than paraphrasing a prompt.

Usage: python runs/ai_loop/exp25_wide_v2.py <job_id>
"""
import asyncio, json, os, sys, time, warnings
warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SERVER = os.path.join(REPO, "PaintomicsServer")
sys.path.insert(0, os.path.join(SERVER, "src"))
sys.path.insert(0, SERVER)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("exp25")

from agents import Agent, ModelSettings, Runner
from src.classes.AIInterpret.sdk_pipeline import (
    configure_sdk, _model, PipelineContext, DATA_TOOLS, run_hedged,
)
from src.classes.AIInterpret import prompts as P
from src.classes.AIInterpret.context_builder import (
    build_pathway_context, build_gene_symbol_whitelist, get_organism_name,
    render_pathway_table,
)
from src.classes.AIInterpret.verification import (
    verify_report_v2, redact_unverified_v2, renumber_citations,
    render_references_section,
)
from src.common.JobInformationManager import JobInformationManager

JOB = sys.argv[1] if len(sys.argv) > 1 else "vyfKO754n4"
N_PATHWAYS = int(os.getenv("AI_MAX_PATHWAYS", "26"))
CONCURRENCY = int(os.getenv("EXP25_CONCURRENCY", "26"))

EXPERT_INSTRUCTIONS = """You are a molecular biologist investigating ONE pathway \
from a multi-omics experiment.

You have NOT been given the data. It is available only through your tools:
  - get_pathway_genes(pathway_name): every measured gene in the pathway, with values
  - get_gene_timecourse(gene_symbol): one gene across every omic layer
  - compare_genes(gene_symbols): several genes side by side

Investigate before you write. Call get_pathway_genes first, then follow up on the \
genes that look most informative -- the largest changes, the ones moving in \
several layers, the ones whose layers disagree. A claim you did not look up is a \
guess.

Then write 2-3 paragraphs: what this pathway is doing in this experiment, which \
genes drive it, which omic layers support it, and what is uncertain. Name real \
values you retrieved. If the data does not support a clear story, say that."""


async def main():
    configure_sdk()
    stats = {"arm": "wide_v2", "job": JOB}
    t_all = time.time()

    ji = JobInformationManager().loadJobInstance(JOB)
    if ji is None:
        raise SystemExit("job not loadable")
    organism = get_organism_name(ji.getOrganism())
    import pymongo
    design = os.getenv("AI_EXPERIMENT_DESIGN") or (
        pymongo.MongoClient("localhost", 27017)["PaintomicsDB"]
        ["jobInstanceCollection"].find_one({"jobID": JOB}) or {}).get("experimentDesign", "")

    pathways = build_pathway_context(ji, max_pathways=N_PATHWAYS)
    whitelist = build_gene_symbol_whitelist(ji)
    ctx = PipelineContext(job_instance=ji, job_id=JOB, organism_name=organism,
                          experiment_design=design)

    expert = Agent[PipelineContext](
        name="Pathway Expert", model=_model(),
        instructions=EXPERT_INSTRUCTIONS,
        model_settings=ModelSettings(temperature=0.3),
        tools=DATA_TOOLS)

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _one(pw):
        async with sem:
            before = ctx.tool_calls
            try:
                r = await run_hedged(
                    expert,
                    "Experiment: %s\nOrganism: %s\n\n"
                    "Pathway to investigate: **%s** (%s)\n"
                    "Enrichment: combined p=%s; per-omic: %s\n\n"
                    "Investigate it with your tools and report."
                    % (design, organism, pw["name"], pw.get("id"),
                       pw.get("combined_pvalue"), pw.get("per_omic")),
                    ctx, max_turns=10, timeout=120,
                    label="expert:%s" % pw["name"][:24])
                return pw["name"], str(r.final_output), ctx.tool_calls - before
            except Exception as e:
                logger.warning("expert failed for %s: %s", pw["name"], e)
                return pw["name"], "", 0

    t0 = time.time()
    results = await asyncio.gather(*[_one(p) for p in pathways])
    reports = [(n, t, c) for n, t, c in results if t.strip()]
    stats["expert_s"] = round(time.time() - t0, 1)
    stats["experts"] = len(reports)
    stats["tool_calls"] = ctx.tool_calls
    stats["tool_calls_per_expert"] = round(ctx.tool_calls / max(len(reports), 1), 1)
    logger.info("%d experts, %d tool calls (%.1f each) in %.0fs",
                len(reports), ctx.tool_calls, stats["tool_calls_per_expert"],
                stats["expert_s"])

    # Synthesis over the per-pathway investigations.
    t0 = time.time()
    synth = Agent[PipelineContext](
        name="Report Writer", model=_model(),
        instructions=P.SYSTEM_PROMPT_SYNTHESIZE,
        model_settings=ModelSettings(temperature=0.3), tools=[])
    body = "\n\n".join("### %s\n%s" % (n, t) for n, t, _ in reports)
    r = await Runner.run(
        synth,
        "Experiment: %s\nOrganism: %s\n\n"
        "Below are independent per-pathway investigations, each performed by an "
        "agent that queried the data directly. Synthesise them into one report: "
        "group them into themes, name every pathway, keep the specific values "
        "they retrieved, and state where the evidence is thin or the layers "
        "disagree.\n\n%s" % (design, organism, body),
        context=ctx, max_turns=3)
    report = str(r.final_output)
    stats["synth_s"] = round(time.time() - t0, 1)

    table = render_pathway_table(pathways)
    if table:
        report = report.rstrip() + "\n\n" + table + "\n"

    # Same programmatic net as every other arm (no literature in this arm, so
    # there is nothing to cite -- this measures analysis depth, not citations).
    final = verify_report_v2(report, whitelist, [], ji)
    report, _ = renumber_citations(report)
    stats["total_s"] = round(time.time() - t_all, 1)
    stats["report_chars"] = len(report)
    stats["gene_accuracy"] = final.get("gene_accuracy")

    out = os.path.join(HERE, "wide_v2_%s_report.md" % JOB)
    open(out, "w").write(report)
    open(out.replace("_report.md", "_stats.json"), "w").write(
        json.dumps(stats, indent=2, default=str))
    print(json.dumps(stats, indent=2, default=str))

asyncio.run(main())
