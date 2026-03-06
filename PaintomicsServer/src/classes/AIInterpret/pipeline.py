"""AI interpretation pipeline — agent-based with evaluation loops.

Entry point: run_ai_pipeline() (PySiQ-compatible sync function).
Internally runs an async pipeline with the OpenAI Agents SDK.
"""
import asyncio
import json
import logging
import re
import threading

from agents import Runner
from agents.exceptions import MaxTurnsExceeded

from src.classes.AIInterpret.agents import (
    configure_sdk, triage_agent, build_pathway_expert,
    pathway_evaluator, report_writer, report_evaluator,
)
from src.classes.AIInterpret.context_builder import (
    build_enrichment_table, build_feature_name_whitelist,
    get_organism_name, detect_design_type,
)
from src.classes.AIInterpret.models import PipelineContext, TriageResult, EvaluationResult
from src.classes.AIInterpret.prompts import format_enrichment_table
from src.classes.AIInterpret.pubmed_client import PubMedClient
from src.classes.AIInterpret.verification import (
    verify_report_v2, redact_unverified_v2, renumber_citations,
    convert_pmid_citations,
)
from src.common.DAO.AIInterpretDAO import AIInterpretDAO
from src.common.JobInformationManager import JobInformationManager
from src.conf.serverconf import (
    AI_MAX_CONCURRENT_PIPELINES, AI_TRIAGE_MAX_PATHWAYS,
    AI_MAX_SELECTED_PATHWAYS, AI_MAX_EVAL_ITERATIONS,
)

logger = logging.getLogger(__name__)

# Concurrency control
_pipeline_semaphore = threading.Semaphore(AI_MAX_CONCURRENT_PIPELINES)
_cancel_flags = {}


class _Heartbeat:
    """Background thread that touches updatedAt every interval so stale-job
    detection can distinguish 'alive but slow' from 'dead'."""

    def __init__(self, job_id, interval=30):
        self._job_id = job_id
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self._interval):
            try:
                dao = AIInterpretDAO()
                dao.touch(self._job_id)
                dao.closeConnection()
            except Exception:
                pass


def run_ai_pipeline(job_id, experiment_design, RESPONSE):
    """PySiQ-compatible entry point. MUST return a Response object."""
    dao = None
    heartbeat = _Heartbeat(job_id)
    try:
        _pipeline_semaphore.acquire()
        heartbeat.start()

        configure_sdk()

        dao = AIInterpretDAO()
        job_instance = JobInformationManager().loadJobInstance(job_id)
        if job_instance is None:
            raise ValueError(f"Job {job_id} not found")

        # Run async pipeline in a new event loop
        asyncio.run(_async_pipeline(job_id, experiment_design, job_instance, dao))

        RESPONSE.setContent({"success": True, "jobID": job_id, "status": "done"})

    except InterruptedError:
        if dao:
            dao.save_progress(job_id, {"status": "cancelled", "percent": 0,
                                       "detail": "Cancelled by user"})
        RESPONSE.setContent({"success": True, "jobID": job_id, "status": "cancelled"})
    except Exception as ex:
        logging.exception(f"AI pipeline failed for job {job_id}")
        if dao:
            dao.save_progress(job_id, {"status": "error", "percent": 0, "detail": str(ex)})
        from src.common.ServerErrorManager import handleException
        handleException(RESPONSE, ex, __file__, "run_ai_pipeline")
    finally:
        heartbeat.stop()
        _pipeline_semaphore.release()
        _cancel_flags.pop(job_id, None)
        if dao:
            dao.closeConnection()
        return RESPONSE


async def _async_pipeline(job_id, experiment_design, job_instance, dao):
    """Core async pipeline: triage -> expert+eval -> report+eval -> post-process."""
    organism = job_instance.getOrganism()
    organism_name = get_organism_name(organism)

    # =====================================================================
    # Phase 0: Data Prep
    # =====================================================================
    dao.save_progress(job_id, {"status": "extracting", "percent": 5,
                               "detail": "Preparing context..."})

    design_type = detect_design_type(job_instance, experiment_design)
    enrichment_table = build_enrichment_table(job_instance, max_pathways=AI_TRIAGE_MAX_PATHWAYS)
    whitelist = build_feature_name_whitelist(job_instance)

    ctx = PipelineContext(
        job_instance=job_instance,
        job_id=job_id,
        organism_name=organism_name,
        design_type=design_type,
        experiment_design=experiment_design,
        enrichment_table=enrichment_table,
        gene_whitelist=whitelist,
        compound_whitelist=whitelist,  # combined whitelist
        pubmed_client=PubMedClient(),
    )

    _check_cancel(job_id)
    logger.info(f"[{job_id}] Phase 0: design={design_type}, "
                f"{len(enrichment_table)} pathways, {len(whitelist)} features")

    # =====================================================================
    # Phase 1: Triage (1 LLM call)
    # =====================================================================
    dao.save_progress(job_id, {"status": "triaging", "percent": 8,
                               "detail": "Selecting pathways..."})

    triage_prompt = format_enrichment_table(enrichment_table, experiment_design, organism_name)
    triage_result = await _run_triage(ctx, triage_prompt)

    selected = [d for d in triage_result.decisions if d.investigate]
    selected.sort(key=lambda d: d.priority)
    selected = selected[:AI_MAX_SELECTED_PATHWAYS]

    logger.info(f"[{job_id}] Phase 1: selected {len(selected)} pathways")
    dao.save_progress(job_id, {"status": "triaging", "percent": 10,
                               "detail": f"Selected {len(selected)} pathways"})
    _check_cancel(job_id)

    # =====================================================================
    # Phase 2: Per-Pathway Expert + Evaluator — PARALLEL (agentic swarm)
    # =====================================================================
    completed = [0]  # mutable container for monotonic counter

    async def _analyze_one_pathway(pw_decision):
        """Analyze a single pathway with error isolation."""
        pw_name = pw_decision.pathway_name
        pw_data = next((e for e in enrichment_table if e["name"] == pw_name), None)
        pval_str = ""
        if pw_data:
            pval_parts = [f"{k}: {v:.4f}" for k, v in pw_data.get("per_omic_pvalues", {}).items()]
            pval_str = "; ".join(pval_parts)

        try:
            report = await _expert_with_evaluation(
                ctx, pw_name, pval_str, experiment_design, design_type,
                max_iterations=AI_MAX_EVAL_ITERATIONS,
            )
        except Exception as e:
            logger.error(f"[{job_id}] Pathway '{pw_name}' failed: {e}", exc_info=True)
            report = f"[Analysis of {pw_name} could not be completed: {type(e).__name__}]"

        completed[0] += 1
        dao.save_progress(job_id, {
            "status": "interpreting",
            "percent": 10 + int(60 * completed[0] / len(selected)),
            "detail": f"Analyzed {completed[0]}/{len(selected)}: {pw_name}"
        })
        return report

    tasks = [_analyze_one_pathway(pw) for pw in selected]
    pathway_reports = list(await asyncio.gather(*tasks))

    # =====================================================================
    # Phase 3: Report Writer + Evaluator Loop
    # =====================================================================
    _check_cancel(job_id)
    dao.save_progress(job_id, {"status": "synthesizing", "percent": 75,
                               "detail": "Writing report..."})

    valid_reports = [r for r in pathway_reports if not r.startswith("[Analysis of")]
    if not valid_reports:
        raise RuntimeError("All pathway analyses failed. No report generated.")

    report = await _report_with_evaluation(
        ctx, valid_reports, experiment_design, organism_name,
        max_iterations=AI_MAX_EVAL_ITERATIONS,
    )

    dao.save_progress(job_id, {"status": "verifying", "percent": 90,
                               "detail": "Post-processing..."})

    # =====================================================================
    # Phase 4: Post-Processing
    # =====================================================================
    papers = list(ctx.papers_used.values())

    # Assign ref_index to papers for verification
    for idx, p in enumerate(papers, 1):
        p["ref_index"] = idx

    # Convert [PMID:xxx] citations to [N] format before verification
    report = convert_pmid_citations(report, papers)

    final = verify_report_v2(report, ctx.gene_whitelist, papers, job_instance)
    if final.get("failed_citations"):
        report, removed = redact_unverified_v2(report, final["failed_citations"])
        final["redacted_count"] = removed

    report, citation_mapping = renumber_citations(report)
    if citation_mapping:
        final["citation_mapping"] = {str(k): v for k, v in citation_mapping.items()}
        updated_papers = []
        for p in papers:
            old_idx = p["ref_index"]
            if old_idx in citation_mapping:
                p["ref_index"] = citation_mapping[old_idx]
                updated_papers.append(p)
        updated_papers.sort(key=lambda p: p["ref_index"])
        papers = updated_papers

    # Save final result
    dao.save_papers(job_id, papers)
    dao.save_progress(job_id, {
        "status": "done", "percent": 100,
        "detail": f"Ready — {len(papers)} papers cited",
        "report": report,
        "verification": final,
    })


async def _run_triage(ctx, triage_prompt):
    """Run triage agent. Falls back to JSON parsing if structured output fails."""
    try:
        result = await Runner.run(triage_agent, triage_prompt, context=ctx, max_turns=1)
        if isinstance(result.final_output, TriageResult):
            return result.final_output
        # If output_type not supported, try parsing as JSON
        return _parse_triage_fallback(result.final_output, ctx.enrichment_table)
    except Exception as e:
        logger.warning(f"Triage agent failed: {e}, using fallback")
        return _build_triage_fallback(ctx.enrichment_table)


def _parse_triage_fallback(text, enrichment_table):
    """Parse triage output as JSON string. Handles various wrapper formats."""
    text = str(text).strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try to extract JSON from text that may contain prose around it
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        text = json_match.group(0)

    try:
        data = json.loads(text)

        # Direct TriageResult format: {"decisions": [...]}
        if isinstance(data, dict) and "decisions" in data:
            return TriageResult.model_validate(data)

        # Nested wrapper: {"triage_result": {"decisions": [...]}} or similar
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, dict) and "decisions" in val:
                    return TriageResult.model_validate(val)
                if isinstance(val, dict) and "pathways" in val:
                    # {"triage_result": {"pathways": [...]}}
                    return TriageResult(decisions=[
                        _validate_triage_decision(d) for d in val["pathways"] if isinstance(d, dict)
                    ])
                if isinstance(val, list):
                    return TriageResult(decisions=[
                        _validate_triage_decision(d) for d in val if isinstance(d, dict)
                    ])

        # Direct list: [{"pathway_id": ...}, ...]
        if isinstance(data, list):
            return TriageResult(decisions=[
                _validate_triage_decision(d) for d in data if isinstance(d, dict)
            ])
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Triage JSON parsing failed: {e}")

    return _build_triage_fallback(enrichment_table)


def _validate_triage_decision(d):
    """Validate a single triage decision dict."""
    from src.classes.AIInterpret.models import TriageDecision
    return TriageDecision(
        pathway_id=str(d.get("pathway_id", "")),
        pathway_name=str(d.get("pathway_name", "")),
        investigate=bool(d.get("investigate", False)),
        priority=max(1, min(5, int(d.get("priority", 3)))),
        reasoning=str(d.get("reasoning", "")),
    )


def _build_triage_fallback(enrichment_table):
    """Fallback: select top 8 pathways by combined p-value."""
    from src.classes.AIInterpret.models import TriageDecision
    decisions = []
    for i, pw in enumerate(enrichment_table):
        decisions.append(TriageDecision(
            pathway_id=pw["id"],
            pathway_name=pw["name"],
            investigate=i < AI_MAX_SELECTED_PATHWAYS,
            priority=min(i + 1, 5),
            reasoning="Fallback: selected by combined p-value rank",
        ))
    return TriageResult(decisions=decisions)


async def _expert_with_evaluation(ctx, pathway_name, pval_str, experiment_design,
                                   design_type, max_iterations=1):
    """Expert → Critic → Correction. Single pass by default."""
    expert = build_pathway_expert(pathway_name, design_type)
    prompt = (
        f"Investigate: {pathway_name}\n"
        f"Per-omic p-values: {pval_str}\n"
        f"Experiment design: {experiment_design}\n"
        f"Design type: {design_type}"
    )

    # Step 1: Expert analysis
    try:
        expert_result = await Runner.run(expert, prompt, context=ctx, max_turns=20)
        expert_output = str(expert_result.final_output)
    except MaxTurnsExceeded:
        logger.warning(f"Pathway '{pathway_name}' expert exceeded max turns")
        return f"[Analysis of {pathway_name} was incomplete due to complexity limits.]"

    if max_iterations < 1:
        return expert_output

    # Step 2: Critic
    eval_prompt = (
        f"Review this pathway analysis for accuracy and completeness:\n\n"
        f"{expert_output}\n\nPathway: {pathway_name}\nDesign type: {design_type}"
    )
    eval_output = await _run_evaluator(ctx, eval_prompt, pathway_evaluator)

    if eval_output.approved:
        logger.info(f"Pathway '{pathway_name}' approved on first pass")
        return expert_output

    # Step 3: Single correction
    logger.info(f"Pathway '{pathway_name}': {len(eval_output.issues)} issues, revising once")
    prev_summary = expert_output[:2000] + "\n... [truncated]" if len(expert_output) > 2000 else expert_output
    revision_prompt = (
        f"Your previous analysis of {pathway_name}:\n\n{prev_summary}\n\n"
        f"Reviewer feedback:\n\n{eval_output.feedback}\n\n"
        f"Please revise your analysis to address the issues above."
    )
    try:
        expert = build_pathway_expert(pathway_name, design_type)
        revised = await Runner.run(expert, revision_prompt, context=ctx, max_turns=20)
        return str(revised.final_output)
    except MaxTurnsExceeded:
        logger.warning(f"Pathway '{pathway_name}' revision exceeded max turns, using original")
        return expert_output


async def _report_with_evaluation(ctx, pathway_reports, experiment_design,
                                   organism_name, max_iterations=3):
    """Run Report Writer with evaluation loop. Returns final report text."""
    synth_input = (
        f"## Experiment Context\nOrganism: {organism_name}\n"
        f"Design: {experiment_design}\n\n"
        f"## Individual Pathway Analyses\n\n"
        + "\n\n---\n\n".join(pathway_reports)
    )

    report_output = None
    eval_output = None

    for iteration in range(max_iterations):
        if iteration == 0:
            prompt = synth_input
        else:
            report_summary = report_output
            if len(report_summary) > 3000:
                report_summary = report_summary[:3000] + "\n... [truncated for context]"
            prompt = (
                f"Your previous report:\n\n{report_summary}\n\n"
                f"Reviewer feedback:\n\n{eval_output.feedback}\n\n"
                f"Please revise the report to address the issues above."
            )

        result = await Runner.run(report_writer, prompt, context=ctx, max_turns=1)
        report_output = str(result.final_output)

        # Evaluate
        eval_prompt = f"Review this synthesis report:\n\n{report_output}"
        eval_output = await _run_evaluator(ctx, eval_prompt, report_evaluator)

        if eval_output.approved:
            logger.info(f"Report approved at iteration {iteration + 1}")
            break
        else:
            logger.info(f"Report iteration {iteration + 1}: {len(eval_output.issues)} issues")

    return report_output


async def _run_evaluator(ctx, prompt, evaluator_agent):
    """Run an evaluator agent with fallback for structured output failures."""
    try:
        result = await Runner.run(evaluator_agent, prompt, context=ctx, max_turns=8)
        if isinstance(result.final_output, EvaluationResult):
            return result.final_output
        return _parse_evaluation_fallback(result.final_output)
    except Exception as e:
        logger.warning(f"Evaluator failed: {e}, auto-approving")
        return EvaluationResult(
            approved=True,
            issues=[f"Evaluator error: {e}"],
            suggestions=[],
            feedback="Auto-approved due to evaluator failure.",
        )


def _parse_evaluation_fallback(text):
    """Parse evaluation output as JSON when structured output isn't supported."""
    text = str(text).strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try to extract JSON object from text
    json_match = re.search(r'\{[\s\S]*\}', text)
    json_str = json_match.group(0) if json_match else text

    try:
        data = json.loads(json_str)
        if isinstance(data, dict):
            # Handle nested wrappers like {"evaluation_result": {...}}
            if "approved" in data:
                return EvaluationResult.model_validate(data)
            for key, val in data.items():
                if isinstance(val, dict) and "approved" in val:
                    return EvaluationResult.model_validate(val)
    except (json.JSONDecodeError, ValueError):
        pass

    # Heuristic: if text contains "approved" or "APPROVED", approve
    lower = text.lower()
    approved = "approved" in lower and "not approved" not in lower
    return EvaluationResult(
        approved=approved,
        issues=[],
        suggestions=[],
        feedback=text[:500],
    )


def _check_cancel(job_id):
    """Check if the job has been cancelled."""
    if _cancel_flags.get(job_id):
        raise InterruptedError("Cancelled")
