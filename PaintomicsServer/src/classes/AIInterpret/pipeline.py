import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.classes.AIInterpret.llm_client import LLMClient
from src.classes.AIInterpret.pubmed_client import PubMedClient
from src.classes.AIInterpret.context_builder import (
    build_pathway_context, get_organism_name, build_gene_symbol_whitelist,
    triage_pathways, build_cross_omic_matrix,
)
from src.classes.AIInterpret.verification import (
    verify_report, redact_unverified,
    verify_report_v2, redact_unverified_v2, parse_references_section,
    renumber_citations,
)
from src.classes.AIInterpret.prompts import (
    SYSTEM_PROMPT_INTERPRET, SYSTEM_PROMPT_SYNTHESIZE,
    SYSTEM_PROMPT_INTERPRET_V2, SYSTEM_PROMPT_SYNTHESIZE_V2,
    SYSTEM_PROMPT_VERIFICATION,
    SYSTEM_PROMPT_SEARCH_PLANNER, SYSTEM_PROMPT_SEARCH_SUBAGENT,
    build_batch_interpretation_prompt, build_synthesis_prompt,
    build_two_pass_interpretation_prompt, build_synthesis_prompt_v2,
    build_verification_prompt, build_correction_prompt,
    build_search_planner_prompt, build_subagent_filter_prompt,
)
from src.classes.AIInterpret.tools import (
    INTERPRETATION_TOOLS, VERIFICATION_TOOLS,
    build_interpretation_executor, build_verification_executor,
)
from src.common.DAO.AIInterpretDAO import AIInterpretDAO
from src.common.JobInformationManager import JobInformationManager
from src.conf.serverconf import (
    AI_PROVIDERS, AI_LLM_PROVIDER, AI_MAX_PATHWAYS,
    AI_PATHWAYS_PER_BATCH, AI_PAPERS_PER_PATHWAY, AI_TEMPERATURE,
    AI_MAX_CONCURRENT_PIPELINES, AI_MAX_VERIFICATION_ITERATIONS,
    AI_MAX_SEARCH_TASKS, AI_SEARCH_SUBAGENT_WORKERS, AI_VERIFICATION_WORKERS,
    AI_PAPERS_PER_SEARCH_TASK, AI_PAPERS_KEPT_PER_TASK,
    AI_SEARCH_PLANNER_TEMPERATURE, AI_SEARCH_SUBAGENT_TEMPERATURE,
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
                pass  # best-effort; don't crash the heartbeat


class _PhaseTimer:
    """Records wall-clock time per pipeline phase.

    Added because the pipeline's cost was being estimated from the code rather
    than measured. Each phase is logged as it ends, and a summary line at the
    end gives the whole breakdown in one place -- so deciding what to simplify
    can be based on where the time actually goes.
    """

    def __init__(self, job_id):
        self.job_id = job_id
        self.timings = []
        self._current = None
        self._started = None

    def start(self, phase):
        self.stop()
        self._current = phase
        self._started = time.time()

    def stop(self):
        if self._current is None:
            return
        elapsed = time.time() - self._started
        self.timings.append((self._current, elapsed))
        logger.info(f"[{self.job_id}] PHASE {self._current}: {elapsed:.1f}s")
        self._current = None

    def summary(self):
        self.stop()
        if not self.timings:
            return ""
        total = sum(t for _, t in self.timings)
        parts = ", ".join(f"{name}={seconds:.1f}s "
                          f"({100 * seconds / total:.0f}%)"
                          for name, seconds in self.timings)
        return f"AI pipeline {total:.1f}s total -- {parts}"


def _count_significant_pathways(job_instance, threshold=0.05):
    """How many pathways actually cleared the significance threshold.

    Multi-condition analyses store one p-value per condition, so a pathway
    counts as significant if it is significant in any condition. Falls back to
    the configured ceiling if the job exposes nothing usable, so an unexpected
    shape degrades to the previous fixed behaviour rather than to zero work.
    """
    try:
        matched = job_instance.getMatchedPathways()
    except Exception:
        return AI_MAX_PATHWAYS
    if not matched:
        return AI_MAX_PATHWAYS

    significant = 0
    for pathway in matched.values():
        pvalues = getattr(pathway, "combinedSignificancePvalues", None) or {}
        for value in pvalues.values():
            candidates = value if isinstance(value, (list, tuple)) else [value]
            if any(isinstance(v, (int, float)) and v < threshold for v in candidates):
                significant += 1
                break
    return significant or AI_MAX_PATHWAYS


def _adaptive_budgets(significantCount):
    """Scale the work to how much signal there actually is.

    The fixed ceilings (15 pathways, 12 search tasks) cost the same whether an
    analysis produced 3 significant pathways or 300. Scaling to the real count
    avoids paying for searches on pathways that were never interesting, and
    avoids capping an unusually rich result at an arbitrary 15.
    """
    pathways = max(5, min(AI_MAX_PATHWAYS, significantCount))
    # Roughly one search task per two pathways, within the configured ceiling.
    searchTasks = max(3, min(AI_MAX_SEARCH_TASKS, (pathways + 1) // 2))
    return pathways, searchTasks


def run_ai_pipeline(job_id, experiment_design, RESPONSE):
    """PySiQ-compatible entry point. MUST return a Response object."""
    dao = None
    heartbeat = _Heartbeat(job_id)
    timer = _PhaseTimer(job_id)
    try:
        _pipeline_semaphore.acquire()
        heartbeat.start()
        dao = AIInterpretDAO()

        # Load job
        job_instance = JobInformationManager().loadJobInstance(job_id)
        if job_instance is None:
            raise ValueError(f"Job {job_id} not found")

        organism = job_instance.getOrganism()
        organism_name = get_organism_name(organism)
        llm = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER])
        pubmed = PubMedClient()

        # =====================================================================
        # Phase 1: Context Triage + Cross-Omic Matrix (0% - 10%)
        # =====================================================================
        timer.start("triage")
        dao.save_progress(job_id, {"status": "extracting", "percent": 5,
                                   "detail": "Extracting pathway data..."})
        # Budgets scale to the analysis: an experiment with 3 significant
        # pathways should not pay for the same search volume as one with 300.
        significantCount = _count_significant_pathways(job_instance)
        maxPathways, maxSearchTasks = _adaptive_budgets(significantCount)
        logger.info(f"[{job_id}] {significantCount} significant pathways -> "
                    f"budget {maxPathways} pathways, {maxSearchTasks} search tasks")
        pathways = build_pathway_context(job_instance, max_pathways=maxPathways)
        gene_whitelist = build_gene_symbol_whitelist(job_instance)

        # The report refers to pathways by name. Persist the name -> id/source
        # mapping so the client can turn those mentions into links that open the
        # pathway, and so a per-pathway interpretation can be generated later
        # without rebuilding the whole job context.
        dao.save_pathway_index(job_id, pathways)
        # Kept alongside so a later per-pathway request interprets against the
        # same stated design as the main report, instead of no design at all.
        dao.save_progress(job_id, {"experimentDesign": experiment_design or ""})

        if _cancel_flags.get(job_id):
            raise InterruptedError("Cancelled")

        major_pathways, minor_pathways = triage_pathways(pathways)
        cross_omic_matrix = build_cross_omic_matrix(major_pathways)

        logger.info(f"[{job_id}] Triage: {len(major_pathways)} major + "
                    f"{len(minor_pathways)} minor pathways")
        dao.save_progress(job_id, {"status": "extracting", "percent": 10,
                                   "detail": f"{len(major_pathways)} major + "
                                             f"{len(minor_pathways)} minor pathways"})

        if _cancel_flags.get(job_id):
            raise InterruptedError("Cancelled")

        # =====================================================================
        # Phase 2: Agentic Literature Discovery (10% - 40%)
        # =====================================================================
        timer.start("search_planning")
        search_tasks = _run_search_planner(
            llm, major_pathways, minor_pathways, cross_omic_matrix,
            gene_whitelist, experiment_design, organism_name, job_id,
            maxSearchTasks=maxSearchTasks)

        logger.info(f"[{job_id}] Search planner produced {len(search_tasks)} tasks")
        timer.start("literature_retrieval")
        dao.save_progress(job_id, {"status": "searching_pubmed", "percent": 15,
                                   "detail": f"Executing {len(search_tasks)} search tasks..."})

        if _cancel_flags.get(job_id):
            raise InterruptedError("Cancelled")

        all_papers = _execute_search_subagents(
            llm, pubmed, search_tasks, experiment_design, organism_name,
            job_id, dao)

        # Deduplicate and assign global ref_index
        seen = {}
        unique_papers = []
        ref_counter = 1
        for p in all_papers:
            if p["pmid"] not in seen:
                p["ref_index"] = ref_counter
                ref_counter += 1
                seen[p["pmid"]] = p
                unique_papers.append(p)
            else:
                existing = seen[p["pmid"]]
                for pw_name in p.get("pathways", []):
                    if pw_name not in existing.get("pathways", []):
                        existing.setdefault("pathways", []).append(pw_name)

        paper_index = {p["ref_index"]: p for p in unique_papers}

        dao.save_progress(job_id, {
            "status": "searching_pubmed", "percent": 40,
            "detail": f"Found {len(unique_papers)} unique papers "
                      f"({sum(1 for p in unique_papers if p.get('full_text_available'))} with full text)"
        })
        dao.save_papers(job_id, unique_papers)

        if _cancel_flags.get(job_id):
            raise InterruptedError("Cancelled")

        # =====================================================================
        # Phase 3: Sub-Agent Interpretation (45% - 75%)
        # =====================================================================
        timer.start("interpretation")
        dao.save_progress(job_id, {"status": "interpreting", "percent": 45,
                                   "detail": "Generating interpretation with evidence extraction..."})

        batch_reports = []

        for batch_start in range(0, len(pathways), AI_PATHWAYS_PER_BATCH):
            batch = pathways[batch_start:batch_start + AI_PATHWAYS_PER_BATCH]
            batch_pathway_names = {pw["name"] for pw in batch}

            # Get papers relevant to this batch (by pathway overlap)
            batch_papers = [
                p for p in unique_papers
                if batch_pathway_names & set(p.get("pathways", [p.get("pathway", "")]))
            ]

            # Use local indices [1, 2, ...] per batch to prevent the LLM from
            # renumbering citations (it tends to reset to [1] regardless of the
            # global ref_index).  After the batch report, remap back to global.
            local_papers, local_to_global = _build_local_paper_index(batch_papers)
            local_paper_index = {lp["ref_index"]: lp for lp in local_papers}
            local_executor = build_interpretation_executor(local_paper_index, llm)

            prompt = build_two_pass_interpretation_prompt(
                batch, local_papers, experiment_design, organism_name)

            # Main agent uses extract_evidence tool to spawn sub-agents
            result = llm.complete_with_tools(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_INTERPRET_V2},
                    {"role": "user", "content": prompt},
                ],
                tools=INTERPRETATION_TOOLS,
                tool_executor=local_executor,
                max_tokens=4000,
                temperature=AI_TEMPERATURE,
                max_iterations=15,
            )

            # Remap local [1], [2] back to global [10], [14] etc.
            result = _remap_citation_indices(result, local_to_global)
            batch_reports.append(result)

            pct = 45 + int(30 * (batch_start + len(batch)) / max(len(pathways), 1))
            dao.save_progress(job_id, {
                "status": "interpreting", "percent": pct,
                "detail": f"Interpreted {min(batch_start + len(batch), len(pathways))}/{len(pathways)} pathways"
            })

            if _cancel_flags.get(job_id):
                raise InterruptedError("Cancelled")

        # =====================================================================
        # Phase 4: Synthesis (78% - 83%)
        # =====================================================================
        timer.start("synthesis")
        dao.save_progress(job_id, {"status": "synthesizing", "percent": 78, "detail": "Synthesizing report..."})

        synthesis_prompt = build_synthesis_prompt_v2(
            batch_reports, experiment_design, organism_name, unique_papers)
        report = llm.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_SYNTHESIZE_V2},
                {"role": "user", "content": synthesis_prompt},
            ],
            max_tokens=6000,
            temperature=AI_TEMPERATURE,
        )

        if _cancel_flags.get(job_id):
            raise InterruptedError("Cancelled")

        # =====================================================================
        # Phase 5: Agentic Verification Loop (85% - 97%)
        # =====================================================================
        timer.start("verification")
        dao.save_progress(job_id, {"status": "verifying", "percent": 85, "detail": "Verifying citations..."})

        verification_executor = build_verification_executor(paper_index)

        for iteration in range(AI_MAX_VERIFICATION_ITERATIONS):
            citations = parse_references_section(report)
            if not citations:
                break

            failed_citations = []
            # Each citation is an independent sub-agent call, so they run
            # concurrently -- the same pattern and worker count already used for
            # the search sub-agents. This phase went from a no-op to the largest
            # in the run once citation parsing was fixed, and it was walking the
            # citations one at a time.
            toVerify = [c for c in citations if c.get("cited_text")]
            with ThreadPoolExecutor(max_workers=AI_VERIFICATION_WORKERS) as executor:
                futures = {
                    executor.submit(
                        _run_verification_subagent,
                        llm, verification_executor,
                        citation["claim_sentence"],
                        citation["cited_text"],
                        citation["ref_index"],
                    ): citation
                    for citation in toVerify
                }
                for future in as_completed(futures):
                    citation = futures[future]
                    try:
                        verdict = future.result()
                    except Exception as ex:
                        # A sub-agent that dies must not pass its citation off as
                        # verified; record it as failed so it is corrected or
                        # redacted like any other unsupported claim.
                        logger.warning(f"[{job_id}] Verification sub-agent raised for "
                                       f"[{citation['ref_index']}]: {ex}")
                        verdict = {"text_match": False, "supports_claim": False,
                                   "reasoning": f"Verification error: {ex}"}

                    if not verdict.get("text_match") or not verdict.get("supports_claim"):
                        failed_citations.append({
                            "ref_index": citation["ref_index"],
                            "reason": verdict.get("reasoning", "Verification failed"),
                            "cited_text": citation["cited_text"],
                            "claim_sentence": citation["claim_sentence"],
                            "actual_text": verdict.get("actual_text", ""),
                            "suggested_fix": verdict.get("suggested_fix", ""),
                        })
            # as_completed returns out of order; keep reports stable between runs.
            failed_citations.sort(key=lambda c: c["ref_index"])

            pct = 85 + int(10 * (iteration + 1) / AI_MAX_VERIFICATION_ITERATIONS)
            dao.save_progress(job_id, {
                "status": "verifying", "percent": pct,
                "detail": f"Verification iteration {iteration + 1}: "
                          f"{len(failed_citations)} issue(s) found"
            })

            if not failed_citations:
                break  # All citations verified

            # Feed issues back to LLM for correction
            correction_prompt = build_correction_prompt(report, failed_citations)
            report = llm.complete(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_INTERPRET_V2},
                    {"role": "user", "content": f"Here is your report:\n\n{report}\n\n{correction_prompt}"},
                ],
                max_tokens=6000,
                temperature=AI_TEMPERATURE,
            )

            if _cancel_flags.get(job_id):
                raise InterruptedError("Cancelled")

        # Final programmatic safety net
        final = verify_report_v2(report, gene_whitelist, unique_papers, job_instance)
        if final["failed_citations"]:
            report, removed = redact_unverified_v2(report, final["failed_citations"])
            final["redacted_count"] = removed

        # Renumber citations to be sequential [1], [2], [3]...
        # This fixes gaps left by redaction or LLM dropping citations during synthesis
        report, citation_mapping = renumber_citations(report)
        if citation_mapping:
            final["citation_mapping"] = {str(k): v for k, v in citation_mapping.items()}

            # Update papers' ref_index to match renumbered report
            updated_papers = []
            for p in unique_papers:
                old_idx = p["ref_index"]
                if old_idx in citation_mapping:
                    p["ref_index"] = citation_mapping[old_idx]
                    updated_papers.append(p)
            updated_papers.sort(key=lambda p: p["ref_index"])
            unique_papers = updated_papers
            dao.save_papers(job_id, unique_papers)

        # =====================================================================
        # Done
        # =====================================================================
        dao.save_progress(job_id, {
            "status": "done", "percent": 100,
            "detail": f"Ready — {len(unique_papers)} papers cited "
                      f"({sum(1 for p in unique_papers if p.get('full_text_available'))} with full text)",
            "report": report,
            "verification": final,
        })

        RESPONSE.setContent({"success": True, "jobID": job_id, "status": "done"})

    except InterruptedError:
        if dao:
            dao.save_progress(job_id, {"status": "cancelled", "percent": 0, "detail": "Cancelled by user"})
        RESPONSE.setContent({"success": True, "jobID": job_id, "status": "cancelled"})
    except Exception as ex:
        logging.exception(f"AI pipeline failed for job {job_id}")
        if dao:
            dao.save_progress(job_id, {"status": "error", "percent": 0, "detail": str(ex)})
        from src.common.ServerErrorManager import handleException
        handleException(RESPONSE, ex, __file__, "run_ai_pipeline")
    finally:
        # Log the breakdown regardless of outcome: a run that failed partway is
        # exactly when knowing which phase consumed the time is most useful.
        phaseSummary = timer.summary()
        if phaseSummary:
            logger.info(f"[{job_id}] {phaseSummary}")
        heartbeat.stop()
        _pipeline_semaphore.release()
        _cancel_flags.pop(job_id, None)
        if dao:
            dao.closeConnection()
        return RESPONSE


def _run_verification_subagent(llm, tool_executor, claim, cited_text, ref_index, temperature=0.1):
    """Run a verification sub-agent for a single citation.

    The sub-agent uses search_paper_text and fetch_paper_section tools
    to verify the cited text exists in the paper and supports the claim.
    Returns a dict with {text_match, supports_claim, reasoning, actual_text, suggested_fix}.
    """
    prompt = build_verification_prompt(claim, cited_text, ref_index)

    try:
        result = llm.complete_with_tools(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_VERIFICATION},
                {"role": "user", "content": prompt},
            ],
            tools=VERIFICATION_TOOLS,
            tool_executor=tool_executor,
            max_tokens=1000,
            temperature=temperature,
            max_iterations=5,
        )
        return _parse_json_verdict(result)
    except Exception as e:
        logger.warning(f"Verification sub-agent failed for [{ref_index}]: {e}")
        return {
            "text_match": False,
            "supports_claim": False,
            "reasoning": f"Verification sub-agent error: {e}",
            "actual_text": "",
            "suggested_fix": "",
        }


def _parse_json_verdict(text):
    """Parse JSON verdict from verification sub-agent, with fallback for malformed output."""
    # Try direct JSON parse
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        result = json.loads(text)
        return {
            "text_match": bool(result.get("text_match", False)),
            "supports_claim": bool(result.get("supports_claim", False)),
            "reasoning": str(result.get("reasoning", "")),
            "actual_text": str(result.get("actual_text", "")),
            "suggested_fix": str(result.get("suggested_fix", "")),
        }
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: try to find JSON within the text
    json_pattern = re.search(r'\{[^{}]*"text_match"[^{}]*\}', text, re.DOTALL)
    if json_pattern:
        try:
            result = json.loads(json_pattern.group())
            return {
                "text_match": bool(result.get("text_match", False)),
                "supports_claim": bool(result.get("supports_claim", False)),
                "reasoning": str(result.get("reasoning", "")),
                "actual_text": str(result.get("actual_text", "")),
                "suggested_fix": str(result.get("suggested_fix", "")),
            }
        except (json.JSONDecodeError, ValueError):
            pass

    # Final fallback: assume verification failed
    logger.warning(f"Could not parse verification verdict: {text[:200]}")
    return {
        "text_match": False,
        "supports_claim": False,
        "reasoning": "Could not parse verification result",
        "actual_text": "",
        "suggested_fix": "",
    }


# =========================================================================
# Phase 3 helpers: local batch indexing
# =========================================================================

def _build_local_paper_index(batch_papers):
    """Create locally-numbered copies of batch papers (1, 2, 3, ...).

    LLMs tend to renumber citations starting from 1 regardless of the
    provided ref_index.  By giving each batch local indices, we work
    *with* that tendency and remap back to global indices afterward.

    Returns:
        (local_papers, local_to_global): list of paper copies with local
        ref_index, and a dict mapping local_idx -> global_idx.
    """
    local_papers = []
    local_to_global = {}
    for local_idx, p in enumerate(batch_papers, 1):
        local_paper = dict(p)  # shallow copy — sections dict is shared (read-only)
        local_paper["ref_index"] = local_idx
        local_papers.append(local_paper)
        local_to_global[local_idx] = p["ref_index"]
    return local_papers, local_to_global


def _remap_citation_indices(text, local_to_global):
    """Remap [N] citation indices from local batch numbering to global numbering.

    Uses a two-pass placeholder approach to avoid collision when e.g.
    local [1] -> global [3] and local [3] -> global [7].
    """
    if not local_to_global:
        return text

    result = text

    # Pass 1: replace [local] with unique placeholders (process largest first
    # so [12] is replaced before [1])
    for local_idx in sorted(local_to_global.keys(), reverse=True):
        global_idx = local_to_global[local_idx]
        placeholder = f"__CITE_REMAP_{global_idx}__"
        result = result.replace(f"[{local_idx}]", placeholder)

    # Pass 2: replace placeholders with final [global] indices
    for global_idx in set(local_to_global.values()):
        result = result.replace(f"__CITE_REMAP_{global_idx}__", f"[{global_idx}]")

    return result


# =========================================================================
# Phase 2 helpers: Agentic Literature Discovery
# =========================================================================

def _run_search_planner(llm, major, minor, matrix, whitelist, design, org, job_id,
                        maxSearchTasks=AI_MAX_SEARCH_TASKS):
    """Use LLM to plan strategic PubMed search tasks for major pathways,
    then auto-generate simple tasks for minor pathways.

    Returns combined list of search task dicts.
    """
    all_tasks = []

    # --- Major pathways: LLM-planned searches ---
    if major:
        prompt = build_search_planner_prompt(
            major, matrix, whitelist, design, org, maxSearchTasks)
        try:
            if _cancel_flags.get(job_id):
                raise InterruptedError("Cancelled")

            raw = llm.complete(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_SEARCH_PLANNER.format(
                        max_tasks=AI_MAX_SEARCH_TASKS)},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3000,
                temperature=AI_SEARCH_PLANNER_TEMPERATURE,
            )
            planned = _parse_search_plan(raw)
            if planned:
                all_tasks.extend(planned)
                logger.info(f"[{job_id}] Search planner returned {len(planned)} tasks")
            else:
                logger.warning(f"[{job_id}] Search planner returned empty plan, using fallback")
                all_tasks.extend(_build_fallback_search_tasks(major, org))
        except InterruptedError:
            raise
        except Exception as e:
            logger.warning(f"[{job_id}] Search planner failed: {e}, using fallback")
            all_tasks.extend(_build_fallback_search_tasks(major, org))

    # --- Minor pathways: auto-generated simple tasks (no LLM) ---
    for pw in minor:
        gene_symbols = [g["symbol"] for g in pw.get("top_genes", [])[:5]]
        queries = [f'"{pw["name"]}"[Title/Abstract] AND "{org}"[Title/Abstract]']
        if gene_symbols:
            queries.append(
                f'({" OR ".join(gene_symbols[:3])}) AND "{pw["name"]}"[Title/Abstract]')
        all_tasks.append({
            "task_id": f"minor_{pw['id']}",
            "query_intent": f"General literature for {pw['name']}",
            "target_pathways": [pw["name"]],
            "keywords": gene_symbols[:3],
            "pubmed_queries": queries,
        })

    return all_tasks[:AI_MAX_SEARCH_TASKS]


def _parse_search_plan(raw_text):
    """Parse JSON array from search planner LLM output.

    Tries: direct parse → strip markdown fences → regex extract.
    Returns list of task dicts, or empty list on failure.
    """
    text = raw_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct JSON parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [t for t in result if isinstance(t, dict) and t.get("pubmed_queries")]
    except (json.JSONDecodeError, ValueError):
        pass

    # Regex fallback: extract JSON array
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [t for t in result if isinstance(t, dict) and t.get("pubmed_queries")]
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning(f"Could not parse search plan: {text[:300]}")
    return []


def _build_fallback_search_tasks(pathways, organism_name):
    """Generate simple keyword-based search tasks (no LLM required).

    Replicates the original rigid Phase 2 query logic as a fallback.
    """
    tasks = []
    for pw in pathways:
        gene_symbols = [g["symbol"] for g in pw.get("top_genes", [])[:5]]
        q1 = f'"{pw["name"]}"[Title/Abstract] AND "{organism_name}"[Title/Abstract]'
        queries = [q1]
        if gene_symbols:
            q2 = f'({" OR ".join(gene_symbols[:3])}) AND "{pw["name"]}"[Title/Abstract]'
            queries.append(q2)
        tasks.append({
            "task_id": f"fallback_{pw.get('id', pw['name'])}",
            "query_intent": f"Literature for {pw['name']}",
            "target_pathways": [pw["name"]],
            "keywords": gene_symbols[:3],
            "pubmed_queries": queries,
        })
    return tasks


def _execute_search_subagents(llm, pubmed, tasks, design, org, job_id, dao):
    """Run search sub-agents in parallel via ThreadPoolExecutor.

    Each sub-agent searches PubMed, filters with LLM, and returns abstract-only
    paper dicts. After all sub-agents finish, a single batch fetch retrieves
    full text for all unique PMIDs.

    Returns list of paper dicts with full text where available.
    """
    if not tasks:
        return []

    abstract_papers = []  # paper dicts from sub-agents (abstract only)
    completed = 0
    total = len(tasks)

    with ThreadPoolExecutor(max_workers=AI_SEARCH_SUBAGENT_WORKERS) as executor:
        futures = {
            executor.submit(
                _search_subagent_worker, llm, pubmed, task, design, org, job_id
            ): task
            for task in tasks
        }

        for future in as_completed(futures):
            task = futures[future]
            try:
                if _cancel_flags.get(job_id):
                    raise InterruptedError("Cancelled")
                papers = future.result(timeout=120)
                abstract_papers.extend(papers)
            except InterruptedError:
                raise
            except Exception as e:
                logger.warning(f"[{job_id}] Sub-agent failed for task "
                               f"'{task.get('task_id', '?')}': {e}")

            completed += 1
            pct = 15 + int(20 * completed / max(total, 1))
            dao.save_progress(job_id, {
                "status": "searching_pubmed", "percent": pct,
                "detail": f"Search tasks: {completed}/{total} complete"
            })

    if _cancel_flags.get(job_id):
        raise InterruptedError("Cancelled")

    # Batch full-text fetch for all unique PMIDs (35% → 40%)
    dao.save_progress(job_id, {"status": "searching_pubmed", "percent": 35,
                               "detail": "Fetching full text for discovered papers..."})

    # Dedup PMIDs and collect pathway attributions
    pmid_pathways = {}  # pmid -> set of pathway names
    for p in abstract_papers:
        pmid = p["pmid"]
        pmid_pathways.setdefault(pmid, set()).update(p.get("pathways", []))

    deduped_pmids = list(pmid_pathways.keys())
    if not deduped_pmids:
        return []

    # Batch fetch with full text (multi-tier: PMC → Europe PMC → abstract)
    try:
        full_papers = pubmed.fetch_papers(deduped_pmids)
    except Exception as e:
        logger.warning(f"[{job_id}] Batch full-text fetch failed: {e}, "
                       f"falling back to abstracts only")
        full_papers = pubmed.fetch_abstracts(deduped_pmids)
        for p in full_papers:
            p["full_text_available"] = False
            p["fetch_tier"] = "abstract_only"
            p["sections"] = {"abstract": p.get("abstract", "")}
            p["full_text_char_count"] = len(p.get("abstract", ""))
            p["authors_short"] = _format_authors_short_inline(p.get("first_author", ""))
            p["pathways"] = []

    # Attach pathway attributions to fetched papers
    for p in full_papers:
        pw_names = pmid_pathways.get(p["pmid"], set())
        existing = set(p.get("pathways", []))
        p["pathways"] = sorted(existing | pw_names)

    return full_papers


def _search_subagent_worker(llm, pubmed, task, design, org, job_id):
    """Single search sub-agent: search PubMed, optionally filter with LLM.

    Returns list of abstract-only paper dicts with pathway attribution.
    """
    if _cancel_flags.get(job_id):
        raise InterruptedError("Cancelled")

    all_pmids = []
    for query in task.get("pubmed_queries", []):
        try:
            pmids = pubmed.search(query, max_results=AI_PAPERS_PER_SEARCH_TASK)
            all_pmids.extend(pmids)
        except Exception as e:
            logger.warning(f"[{job_id}] PubMed search failed for "
                           f"'{query[:80]}': {e}")

    # Dedup
    unique_pmids = list(dict.fromkeys(all_pmids))
    if not unique_pmids:
        return []

    if _cancel_flags.get(job_id):
        raise InterruptedError("Cancelled")

    # Fetch abstracts for LLM filtering
    try:
        papers = pubmed.fetch_abstracts(unique_pmids)
    except Exception as e:
        logger.warning(f"[{job_id}] Abstract fetch failed for task "
                       f"'{task.get('task_id', '?')}': {e}")
        return []

    if not papers:
        return []

    # LLM filter: select top papers by relevance
    kept_pmids = _llm_filter_papers(llm, task, papers, design, org)

    # Apply filter (or fallback to first N)
    if kept_pmids:
        papers = [p for p in papers if p["pmid"] in kept_pmids]
    else:
        papers = papers[:AI_PAPERS_KEPT_PER_TASK]

    # Attach pathway attribution
    target_pathways = task.get("target_pathways", [])
    for p in papers:
        p["pathways"] = list(target_pathways)

    return papers


def _llm_filter_papers(llm, task, papers, design, org):
    """Use LLM sub-agent to select the most relevant papers.

    Returns set of PMID strings, or empty set on failure (caller uses fallback).
    """
    if len(papers) <= AI_PAPERS_KEPT_PER_TASK:
        return set()  # No filtering needed

    prompt = build_subagent_filter_prompt(task, papers, design, org, AI_PAPERS_KEPT_PER_TASK)

    try:
        raw = llm.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_SEARCH_SUBAGENT.format(
                    max_keep=AI_PAPERS_KEPT_PER_TASK)},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=AI_SEARCH_SUBAGENT_TEMPERATURE,
        )
        selected = _parse_pmid_list(raw)
        # Validate: only keep PMIDs that are actually in the candidate set
        candidate_pmids = {p["pmid"] for p in papers}
        valid = selected & candidate_pmids
        if valid:
            return valid
        logger.warning(f"LLM filter returned no valid PMIDs from candidates")
        return set()
    except Exception as e:
        logger.warning(f"LLM filter failed: {e}")
        return set()


def _parse_pmid_list(raw_text):
    """Parse a set of PMID strings from LLM output.

    Tries JSON array first, then regex fallback for 7-8 digit numbers.
    """
    text = raw_text.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try JSON parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return {str(x) for x in result if str(x).isdigit()}
    except (json.JSONDecodeError, ValueError):
        pass

    # Regex fallback: 7-8 digit numbers (PMID format)
    matches = re.findall(r'\b(\d{7,8})\b', text)
    return set(matches)


def _format_authors_short_inline(first_author):
    """'John Smith' -> 'Smith, J. et al.' formatting."""
    if not first_author:
        return "Unknown"
    parts = first_author.strip().split()
    if len(parts) >= 2:
        last = parts[-1]
        initials = ".".join(p[0].upper() for p in parts[:-1] if p) + "."
        return f"{last}, {initials} et al."
    return f"{first_author} et al."
