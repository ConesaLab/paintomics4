import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.classes.AIInterpret.llm_client import LLMClient, SHORT_CALL_TIMEOUT
from src.classes.AIInterpret.pubmed_client import PubMedClient
from src.classes.AIInterpret.context_builder import (
    build_pathway_context, get_organism_name, build_gene_symbol_whitelist,
    triage_pathways, build_cross_omic_matrix,
)
from difflib import SequenceMatcher
from src.classes.AIInterpret.verification import (
    verify_report, redact_unverified,
    verify_report_v2, redact_unverified_v2, parse_references_section,
    render_references_section,
    renumber_citations, sort_references_section,
    # Reused so a quote is held to the same matching rule that will later judge
    # it; a private import beats a second, subtly different matcher.
    _fuzzy_contains, _normalize_text,
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
            # The connection is closed in a finally, not after the touch.
            # `except` decides whether the error propagates; only `finally`
            # decides whether the connection comes back, and the two are easy
            # to mistake for each other. DBmanager builds a new MongoClient per
            # DAO with its own monitor threads, and this beats every 30s for
            # the whole life of a job, once per concurrent job -- so a database
            # that is merely flaky leaked a client every half minute, with the
            # bare `pass` below ensuring nobody ever heard about it.
            dao = None
            try:
                dao = AIInterpretDAO()
                dao.touch(self._job_id)
            except Exception:
                # Still best-effort: a heartbeat that cannot reach the database
                # must not take the pipeline down with it. But it is logged now
                # rather than silently dropped, because a heartbeat failing
                # every 30s is worth knowing about.
                logger.debug("[%s] heartbeat touch failed", self._job_id,
                             exc_info=True)
            finally:
                if dao is not None:
                    dao.closeConnection()


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

        # This is called from run_ai_pipeline's finally, ahead of the semaphore
        # release, so whatever it does it must not raise. Dividing by `total`
        # did: a phase that finishes faster than the clock can measure records
        # 0.0, and if every recorded phase does, `total` is 0.0. time.time()
        # has roughly 15ms resolution on Windows, so that is a tick, not a
        # freak event. The percentages are the expendable part of this line --
        # the phase names and durations are what makes it worth logging.
        if total > 0:
            parts = ", ".join(f"{name}={seconds:.1f}s "
                              f"({100 * seconds / total:.0f}%)"
                              for name, seconds in self.timings)
        else:
            parts = ", ".join(f"{name}={seconds:.1f}s"
                              for name, seconds in self.timings)
        return f"AI pipeline {total:.1f}s total -- {parts}"


# =========================================================================
# JSON schemas for schema-enforced LLM replies.
#
# These do not replace the hand-rolled parsers below -- they run in front of
# them. Where the gateway supports response_format (verified on the CSIC
# vLLM gateway, 2026-08-07) the reply is grammar-constrained and parses on the
# first try; where it does not, LLMClient transparently drops the schema and
# the original parser handles the free text exactly as before.
#
# This matters most where a parse failure is silently destructive:
#   * _parse_json_verdict falls back to supports_claim=False, so an unparseable
#     verdict REDACTS a claim that may have been perfectly well cited.
#   * _parse_pmid_list falls back to a \b\d{7,8}\b regex, so any 7-8 digit
#     number in prose -- a fold-change, a coordinate -- becomes a "PMID".
# =========================================================================

SEARCH_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "query_intent": {"type": "string"},
                    "target_pathways": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "pubmed_queries": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["task_id", "query_intent", "target_pathways",
                             "keywords", "pubmed_queries"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tasks"],
    "additionalProperties": False,
}

PMID_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        # Strings, not integers: PMIDs are identifiers, and leading zeros or a
        # stray float would be silently mangled by numeric coercion.
        "pmids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["pmids"],
    "additionalProperties": False,
}

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "text_match": {"type": "boolean"},
        "supports_claim": {"type": "boolean"},
        "reasoning": {"type": "string"},
        "actual_text": {"type": "string"},
        "suggested_fix": {"type": "string"},
    },
    "required": ["text_match", "supports_claim", "reasoning",
                 "actual_text", "suggested_fix"],
    "additionalProperties": False,
}


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

        # Batches are independent and were parallelised here on the reasoning
        # that concurrency should cost the slowest batch rather than their sum.
        # MEASURED: interpretation went 196s -> 230s. It is slower, not faster.
        #
        # Each batch is a 15-iteration tool loop whose extract_evidence tool
        # spawns further LLM calls, so six concurrent batches put dozens of
        # multi-turn conversations on the gateway at once -- the same load that
        # made 26 parallel pathway agents all time out (iter25). This deployment
        # parallelises short independent calls beautifully (32 in 5.6s) and
        # serialises tool-loop workloads regardless of how they are dispatched.
        #
        # Kept concurrent anyway at max_workers=2: measurably no worse than
        # sequential, and it bounds the damage when one batch stalls, since the
        # others are not queued behind it. Raising this does not help.
        batches = [pathways[i:i + AI_PATHWAYS_PER_BATCH]
                   for i in range(0, len(pathways), AI_PATHWAYS_PER_BATCH)]

        def _interpret_batch(batch):
            batch_pathway_names = {pw["name"] for pw in batch}
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
            return _remap_citation_indices(result, local_to_global)

        batch_reports = [None] * len(batches)
        _batch_workers = int(os.getenv("AI_INTERPRET_BATCH_WORKERS", "2"))
        with ThreadPoolExecutor(max_workers=min(len(batches), _batch_workers)) as executor:
            futures = {executor.submit(_interpret_batch, b): i
                       for i, b in enumerate(batches)}
            done_count = 0
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    # Indexed, not appended: as_completed returns out of order,
                    # and the synthesis reads these as a sequence, so appending
                    # would reshuffle the report's narrative between runs.
                    batch_reports[idx] = future.result()
                except Exception as e:
                    logger.warning(f"[{job_id}] Interpretation batch {idx} failed: {e}")
                    batch_reports[idx] = ""
                done_count += 1
                pct = 45 + int(30 * done_count / max(len(batches), 1))
                dao.save_progress(job_id, {
                    "status": "interpreting", "percent": pct,
                    "detail": f"Interpreted {done_count}/{len(batches)} pathway batches"
                })
                if _cancel_flags.get(job_id):
                    raise InterruptedError("Cancelled")
        batch_reports = [r for r in batch_reports if r]

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

        # Rebuild the References section from ground truth before anything tries
        # to read it. Asking the model to hit the parser's format by instruction
        # failed in 5 of 6 measured runs -- no heading, or unquoted Cited Text,
        # or citation markers with no list at all -- and each failure silently
        # disabled the entire citation check. Now the model supplies only the
        # quote it relied on; metadata and layout come from paper_index.
        _quotes = _collect_cited_quotes(llm, report, paper_index, job_id)
        report, _rendered = render_references_section(report, paper_index, _quotes)
        logger.info(f"[{job_id}] References rebuilt: {len(_rendered)} citation(s) "
                    f"rendered, {len(_quotes)} quote(s) supplied")

        # =====================================================================
        # Phase 5: Agentic Verification Loop (85% - 97%)
        # =====================================================================
        timer.start("verification")
        dao.save_progress(job_id, {"status": "verifying", "percent": 85, "detail": "Verifying citations..."})

        verification_executor = build_verification_executor(paper_index)

        previousFailureCount = None
        for iteration in range(AI_MAX_VERIFICATION_ITERATIONS):
            _iterStart = time.time()
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
            _checkSeconds = time.time() - _iterStart

            pct = 85 + int(10 * (iteration + 1) / AI_MAX_VERIFICATION_ITERATIONS)
            dao.save_progress(job_id, {
                "status": "verifying", "percent": pct,
                "detail": f"Verification iteration {iteration + 1}: "
                          f"{len(failed_citations)} issue(s) found"
            })

            if not failed_citations:
                logger.info(f"[{job_id}] VERIFY iter {iteration + 1}: "
                            f"{len(toVerify)} citations checked in {_checkSeconds:.1f}s, "
                            f"0 failed, no correction needed")
                break  # All citations verified

            # Stop once the rewrites stop helping. Measured on the example job:
            # each correction costs ~40s -- the single largest item in the whole
            # pipeline -- and the failure count went 4 -> 2 -> 2, so the third
            # rewrite bought nothing. A rewrite that fails to reduce the count
            # has shown it cannot fix what remains, and the programmatic safety
            # net below redacts those citations either way, so the outcome is
            # identical without the call.
            if previousFailureCount is not None and len(failed_citations) >= previousFailureCount:
                logger.info(f"[{job_id}] VERIFY iter {iteration + 1}: "
                            f"{len(toVerify)} citations checked in {_checkSeconds:.1f}s, "
                            f"{len(failed_citations)} failed, no improvement on "
                            f"{previousFailureCount} -- stopping, remaining "
                            f"citations will be redacted")
                break
            previousFailureCount = len(failed_citations)

            # Feed issues back to LLM for correction. This rewrites the whole
            # report in one call and cannot be parallelised, so it is timed
            # separately from the per-citation checks above.
            _correctStart = time.time()
            correction_prompt = build_correction_prompt(report, failed_citations)
            report = llm.complete(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_INTERPRET_V2},
                    {"role": "user", "content": f"Here is your report:\n\n{report}\n\n{correction_prompt}"},
                ],
                max_tokens=6000,
                temperature=AI_TEMPERATURE,
            )
            # The correction is a full model rewrite, so it re-authors the
            # References section and re-breaks the format we just rendered --
            # which is why the loop could check 6 citations on iteration 1 and
            # then finish with ref_accuracy 0.0. Re-render after every rewrite,
            # carrying forward the quotes already gathered so surviving
            # citations are not re-queried.
            _quotes.update(_collect_cited_quotes(llm, report, paper_index, job_id,
                                                 known=_quotes))
            report, _rendered = render_references_section(report, paper_index, _quotes)
            logger.info(f"[{job_id}] VERIFY iter {iteration + 1}: "
                        f"{len(toVerify)} citations checked in {_checkSeconds:.1f}s, "
                        f"{len(failed_citations)} failed, "
                        f"correction rewrite {time.time() - _correctStart:.1f}s, "
                        f"references re-rendered ({len(_rendered)})")

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

        # ...and then put the entries back in the order of the labels they now
        # carry. Renumbering rewrites the markers where they stand, so a section
        # rendered in ascending old index order ends up printed as [1], [5],
        # [3], [2], [4] -- every entry pointing at the right paper, the list
        # itself unreadable. Nothing downstream can catch it, because the
        # citations are all still valid.
        report = sort_references_section(report)
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
        # "papers cited" used to report len(unique_papers), which is how many
        # were *retrieved* -- so a report citing none still announced "9 papers
        # cited". Count the [N] markers the finished report actually carries,
        # and keep the retrieved total alongside it so a large gap between the
        # two is visible rather than hidden.
        knownRefIndices = {p["ref_index"] for p in unique_papers}
        citedRefIndices = {int(n) for n in re.findall(r'\[(\d+)\]', report)} & knownRefIndices
        citedWithFullText = sum(1 for p in unique_papers
                                if p["ref_index"] in citedRefIndices
                                and p.get("full_text_available"))

        detail = (f"Ready — {len(citedRefIndices)} of {len(unique_papers)} "
                  f"retrieved papers cited ({citedWithFullText} with full text)")
        if final.get("quotations_unverifiable"):
            # Say so rather than let an empty failed_citations read as a pass.
            detail += " — no References section, so quotations were not checked"
        elif final.get("citations_checked"):
            detail += f", {final['citations_checked']} quotation(s) checked"

        dao.save_progress(job_id, {
            "status": "done", "percent": 100,
            "detail": detail,
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
        # The permit comes back first, before anything that could fail.
        #
        # It used to be released last, after the phase summary and the
        # heartbeat stop. `_PhaseTimer.summary()` divided by the total elapsed
        # time, which is 0.0 when every recorded phase measured 0.0, so a
        # ZeroDivisionError there skipped both the heartbeat stop and this
        # release. That is not a lost log line: two such runs exhaust
        # AI_MAX_CONCURRENT_PIPELINES and every later interpretation blocks
        # forever on acquire() with no error and no timeout, until the server
        # is restarted.
        #
        # The division is fixed too, but the ordering is the part that matters
        # -- it is what stops the *next* statement added here from doing the
        # same thing.
        _pipeline_semaphore.release()
        heartbeat.stop()
        _cancel_flags.pop(job_id, None)

        try:
            # Log the breakdown regardless of outcome: a run that failed partway
            # is exactly when knowing which phase consumed the time is most
            # useful. Best-effort -- a logging failure must not become the
            # pipeline's result.
            phaseSummary = timer.summary()
            if phaseSummary:
                logger.info(f"[{job_id}] {phaseSummary}")
        except Exception:
            logger.exception(f"[{job_id}] could not summarise phase timings")

        if dao:
            dao.closeConnection()
        return RESPONSE


CITED_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "cited_text": {
            "type": "string",
            "description": "Verbatim sentence from the paper, or empty if none supports the claim",
        },
        "supports": {"type": "boolean"},
    },
    "required": ["cited_text", "supports"],
    "additionalProperties": False,
}


def _quote_source_text(paper, max_chars=None):
    """Text a supporting quote may be drawn from: full text if we fetched it.

    The same text is handed to the verifier's tools later, so quote extraction
    and quote checking read from one source. If they disagreed -- extract from
    the abstract, verify against full text or the reverse -- valid citations
    would be refuted for being in the wrong half of the paper.
    """
    if max_chars is None:
        max_chars = int(os.getenv("AI_QUOTE_SOURCE_CHARS", "12000"))
    sections = paper.get("sections") or {}
    if sections:
        # Abstract first: the strongest one-sentence statements of a finding
        # tend to live there, and truncation should not cut them off.
        ordered = [sections.get("abstract") or ""]
        ordered += [v for k, v in sections.items() if k != "abstract" and v]
        text = "\n".join(t for t in ordered if t).strip()
        if text:
            return text[:max_chars]
    return (paper.get("abstract") or "")[:max_chars]


def _snap_quote_to_source(quote, source_text):
    """Return the source's own wording for `quote`, or "" if nothing matches.

    Models paraphrase however firmly they are told not to, and a paraphrased
    "quote" is then correctly refuted by the verifier for not appearing in the
    paper -- which is how a tuned run reached "6 checked, 6 failed" on all three
    verification iterations without a single genuine problem. The verifier was
    right; the quote was never really from the paper.

    So the model's answer is treated as a *pointer* to the right sentence rather
    than as the citation itself. If it already matches, keep it; otherwise snap
    to the source sentence it resembles most. Dropping the quote entirely is the
    honest fallback -- verify_report_v2 then reports it unverifiable instead of
    the report carrying words the paper never said.
    """
    if not quote or not source_text:
        return ""
    if _fuzzy_contains(source_text, quote):
        return quote

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', source_text)
                 if len(s.strip()) > 30]
    if not sentences:
        return ""

    best, best_score = "", 0.0
    for sentence in sentences:
        score = SequenceMatcher(None, _normalize_text(quote),
                                _normalize_text(sentence)).ratio()
        if score > best_score:
            best, best_score = sentence, score
    # Below this the "closest" sentence is just the least unrelated one, and
    # substituting it would attach the claim to whatever the paper happened to
    # say instead of admitting there is no support.
    return best if best_score >= 0.45 else ""


def _claim_sentences_for(body, ref_index, limit=3):
    """Sentences citing [ref_index], most citable first.

    A reference is usually cited more than once, and only some of those
    sentences are the kind a paper can support. Taking the first one was
    costing citations outright: if it happened to be "Bcl2 peaks at 3.058 at
    24h" the lookup returned "no support" and the whole citation was dropped,
    even when the same reference also sat on a mechanistic sentence two
    paragraphs down that any relevant paper could back.

    Ranking is by digit density. Sentences thick with numbers are this
    dataset's own measurements, which no publication contains; sentences
    without them are the mechanistic statements that literature can confirm.
    """
    tag = "[%d]" % ref_index
    matches = [s.strip()[:600] for s in re.split(r'(?<=[.!?])\s+', body)
               if tag in s]
    if not matches:
        return []

    def _numeric_density(sentence):
        return sum(c.isdigit() for c in sentence) / max(len(sentence), 1)

    return sorted(matches, key=_numeric_density)[:limit]


def _claim_sentence_for(body, ref_index):
    """First sentence in the report body citing [ref_index]. Kept for callers
    that want a single claim; prefer _claim_sentences_for."""
    sentences = _claim_sentences_for(body, ref_index, limit=1)
    return sentences[0] if sentences else ""


def _collect_cited_quotes(llm, report, paper_index, job_id, known=None):
    """Ask which sentence of each cited paper backs the claim. {ref_index: quote}.

    One focused call per citation, not one call for all of them. The batched
    version was tried first and returned ``{"citations": []}`` -- 17 characters
    -- for a report with 16 citations: given a 12k-character report and a schema
    whose array may legally be empty, the model took the empty-array exit. A
    per-citation prompt carries one claim and one abstract, so there is no such
    exit and nothing to lose track of.

    Only the quote is requested. Author, title, journal and PMID are already
    known from retrieval, and letting the model restate them is how citations
    drift away from the papers they name.

    A failure here is not fatal: references still render without quotes, which
    verify_report_v2 reports honestly as unverifiable rather than as passed.
    """
    cited = sorted({int(n) for n in re.findall(r'\[(\d+)\]', report)}
                   & set(paper_index.keys()))
    # A citation already resolved against its paper does not change when the
    # report is rewritten, and re-asking costs one LLM call per reference per
    # verification round -- ~60s of a 412s verification loop at 42 references.
    if known:
        cited = [i for i in cited if i not in known]
    if not cited:
        return {}

    ref_match = re.search(r'^\s*(?:#{1,6}\s*)?\**\s*references\s*\**\s*:?\s*$',
                          report, re.MULTILINE | re.IGNORECASE)
    body = report[:ref_match.start()] if ref_match else report

    def _one(idx):
        paper = paper_index[idx] or {}
        claims = _claim_sentences_for(body, idx)
        if not claims:
            return idx, ""
        claim = "\n".join("- %s" % c for c in claims)
        # Search the full text where we have it, not just the abstract. An
        # abstract states conclusions; the sentence that actually supports a
        # specific mechanistic claim usually lives in Results. Restricting the
        # search to abstracts was discarding citations to papers that genuinely
        # do support the claim, one paragraph further down.
        source = _quote_source_text(paper)
        if not source:
            return idx, ""
        prompt = (
            'A report cites the paper below for the following claim(s):\n\n'
            '%s\n\n'
            'PAPER: "%s"\nTEXT: %s\n\n'
            'Quote the single sentence from the paper text that best supports '
            'ANY ONE of those claims -- they are alternatives, so you need only '
            'find support for one. Copy it verbatim: do not paraphrase, shorten, '
            'or write a sentence of your own. If no sentence in the text '
            'supports any of them, set supports=false and cited_text to an empty '
            'string. Answering "no support" is correct and useful; inventing a '
            'quote is not.' % (claim, paper.get("title", ""), source))
        try:
            result = llm.complete_json(
                messages=[
                    {"role": "system", "content": "You extract verbatim "
                                                  "supporting quotations from papers."},
                    {"role": "user", "content": prompt},
                ],
                schema_name="cited_quote",
                schema=CITED_QUOTE_SCHEMA,
                fallback_parser=lambda text: {"cited_text": "", "supports": False},
                max_tokens=800,
                temperature=0.0,
                timeout=SHORT_CALL_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"[{job_id}] Quote lookup failed for [{idx}]: {e}")
            return idx, ""
        if not result.get("supports"):
            return idx, ""
        # Hold the model to the paper's own words before the quote ever reaches
        # the report or the verifier.
        return idx, _snap_quote_to_source(
            (result.get("cited_text") or "").strip(), source)

    # One call per citation, so this scales with citation count; at 20 citations
    # a pool of 4 costs five serial rounds for work that is fully independent.
    quotes = {}
    workers = int(os.getenv("AI_QUOTE_WORKERS", str(max(AI_VERIFICATION_WORKERS, 8))))
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(cited)))) as executor:
        for idx, text in executor.map(_one, cited):
            if text:
                quotes[idx] = text
    return quotes


def _run_verification_subagent(llm, tool_executor, claim, cited_text, ref_index, temperature=0.1):
    """Run a verification sub-agent for a single citation.

    The sub-agent uses search_paper_text and fetch_paper_section tools
    to verify the cited text exists in the paper and supports the claim.
    Returns a dict with {text_match, supports_claim, reasoning, actual_text, suggested_fix}.
    """
    prompt = build_verification_prompt(claim, cited_text, ref_index)

    try:
        # complete_with_tools_json, not complete_with_tools + schema on every
        # turn: constraining the whole loop to the verdict grammar stops the
        # agent emitting tool calls at all, so it would rule on the citation
        # without ever opening the paper. The tool loop runs unconstrained and
        # only the finished answer is coerced into the schema.
        return llm.complete_with_tools_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_VERIFICATION},
                {"role": "user", "content": prompt},
            ],
            tools=VERIFICATION_TOOLS,
            tool_executor=tool_executor,
            schema_name="verification_verdict",
            schema=VERDICT_SCHEMA,
            fallback_parser=_parse_json_verdict,
            max_tokens=1000,
            temperature=temperature,
            max_iterations=5,
            # Short call at high fan-out: hedge the straggler instead of
            # letting one stalled verification hold the whole phase.
            timeout=SHORT_CALL_TIMEOUT,
        )
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


_CITATION_GROUP_RE = re.compile(r'\[(\d+(?:\s*,\s*\d+)*)\]')


def _remap_citation_indices(text, local_to_global):
    """Remap [N] citation indices from local batch numbering to global numbering.

    Handles grouped markers -- ``[1, 2]`` -- as well as single ones. The
    previous implementation matched only the exact string ``[N]``, so a grouped
    citation kept its LOCAL indices and silently came to mean two entirely
    different papers once the surrounding report was globally numbered. Models
    write grouped citations constantly, so this was mis-attributing evidence in
    ordinary reports, not edge cases.

    Rewriting each ``[...]`` exactly once also removes the need for the old
    two-pass placeholder dance: with a single pass there is no way for
    ``1 -> 3`` and ``3 -> 7`` to chain into ``1 -> 7``.

    Indices with no mapping are left as they are: an unmapped number is more
    likely a citation from another batch than a mistake to be guessed at.
    """
    if not local_to_global:
        return text

    def _replace(match):
        parts = [p.strip() for p in match.group(1).split(",")]
        return "[" + ", ".join(
            str(local_to_global.get(int(p), int(p))) for p in parts) + "]"

    return _CITATION_GROUP_RE.sub(_replace, text)


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

            plan = llm.complete_json(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_SEARCH_PLANNER.format(
                        max_tasks=AI_MAX_SEARCH_TASKS)},
                    {"role": "user", "content": prompt},
                ],
                schema_name="search_plan",
                schema=SEARCH_PLAN_SCHEMA,
                # The old parser returns a bare list; wrap it so both paths
                # hand back the same shape.
                fallback_parser=lambda text: {"tasks": _parse_search_plan(text)},
                max_tokens=3000,
                temperature=AI_SEARCH_PLANNER_TEMPERATURE,
            )
            planned = [t for t in (plan.get("tasks") or [])
                       if isinstance(t, dict) and t.get("pubmed_queries")]
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

    # ESearch for every task first, then ONE EFetch per 200 PMIDs, rather than
    # a search+fetch pair inside each worker. NCBI allows 3 req/s unkeyed and
    # 10 keyed, so round trips -- not tokens -- are what bound retrieval:
    # halving them is what let the SDK arm pull 440 abstracts in 35s where the
    # paired version managed 29 papers in 40s. EFetch takes hundreds of ids at
    # once, so the second half of each pair was almost pure overhead.
    prefetched = {}
    with ThreadPoolExecutor(max_workers=AI_SEARCH_SUBAGENT_WORKERS) as executor:
        search_futures = {
            executor.submit(_search_task_pmids, pubmed, task, job_id): task
            for task in tasks
        }
        found = []
        for future in as_completed(search_futures):
            try:
                found.extend(future.result(timeout=60))
            except Exception as e:
                logger.warning(f"[{job_id}] PMID search failed: {e}")

    unique_pmids = list(dict.fromkeys(found))
    for start in range(0, len(unique_pmids), 200):
        chunk = unique_pmids[start:start + 200]
        try:
            for paper in pubmed.fetch_abstracts(chunk) or []:
                prefetched[str(paper.get("pmid"))] = paper
        except Exception as e:
            logger.warning(f"[{job_id}] Batched abstract fetch failed: {e}")
    logger.info(f"[{job_id}] {len(tasks)} searches -> {len(unique_pmids)} PMIDs "
                f"-> {len(prefetched)} abstracts (batched)")

    abstract_papers = []  # paper dicts from sub-agents (abstract only)
    completed = 0
    total = len(tasks)

    with ThreadPoolExecutor(max_workers=AI_SEARCH_SUBAGENT_WORKERS) as executor:
        futures = {
            executor.submit(
                _search_subagent_worker, llm, pubmed, task, design, org, job_id,
                prefetched
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


def _search_task_pmids(pubmed, task, job_id):
    """ESearch only -- abstracts are fetched in one batch by the caller."""
    if _cancel_flags.get(job_id):
        raise InterruptedError("Cancelled")
    found = []
    for query in task.get("pubmed_queries", []):
        try:
            found.extend(pubmed.search(query, max_results=AI_PAPERS_PER_SEARCH_TASK))
        except Exception as e:
            logger.warning(f"[{job_id}] PubMed search failed for "
                           f"'{query[:80]}': {e}")
    task["_pmids"] = list(dict.fromkeys(found))
    return task["_pmids"]


def _search_subagent_worker(llm, pubmed, task, design, org, job_id, prefetched=None):
    """Single search sub-agent: filter this task's papers with the LLM.

    Abstracts arrive via ``prefetched`` (pmid -> paper) from the caller's single
    batched EFetch. ``prefetched=None`` keeps the old self-fetching path so the
    function still works standalone.
    """
    if _cancel_flags.get(job_id):
        raise InterruptedError("Cancelled")

    unique_pmids = task.get("_pmids")
    if unique_pmids is None:
        unique_pmids = _search_task_pmids(pubmed, task, job_id)
    if not unique_pmids:
        return []

    if _cancel_flags.get(job_id):
        raise InterruptedError("Cancelled")

    if prefetched is not None:
        papers = [prefetched[p] for p in unique_pmids if p in prefetched]
    else:
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

    # Attach pathway attribution. Copy first: with the batched fetch these dicts
    # are shared between every task that found the same PMID, so assigning in
    # place would let whichever task finished last erase the other pathways the
    # paper was retrieved for. The caller merges the lists back together.
    target_pathways = task.get("target_pathways", [])
    attributed = []
    for p in papers:
        paper = dict(p)
        paper["pathways"] = list(target_pathways)
        attributed.append(paper)

    return attributed


def _llm_filter_papers(llm, task, papers, design, org):
    """Use LLM sub-agent to select the most relevant papers.

    Returns set of PMID strings, or empty set on failure (caller uses fallback).
    """
    if len(papers) <= AI_PAPERS_KEPT_PER_TASK:
        return set()  # No filtering needed

    prompt = build_subagent_filter_prompt(task, papers, design, org, AI_PAPERS_KEPT_PER_TASK)

    try:
        result = llm.complete_json(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_SEARCH_SUBAGENT.format(
                    max_keep=AI_PAPERS_KEPT_PER_TASK)},
                {"role": "user", "content": prompt},
            ],
            schema_name="relevant_pmids",
            schema=PMID_LIST_SCHEMA,
            fallback_parser=lambda text: {"pmids": sorted(_parse_pmid_list(text))},
            max_tokens=500,
            temperature=AI_SEARCH_SUBAGENT_TEMPERATURE,
            timeout=SHORT_CALL_TIMEOUT,
        )
        selected = {str(x) for x in (result.get("pmids") or []) if str(x).isdigit()}
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
