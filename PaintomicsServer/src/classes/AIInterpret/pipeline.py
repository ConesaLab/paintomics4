import json
import logging
import threading
from src.classes.AIInterpret.llm_client import LLMClient
from src.classes.AIInterpret.pubmed_client import PubMedClient
from src.classes.AIInterpret.context_builder import (
    build_pathway_context, get_organism_name, build_gene_symbol_whitelist)
from src.classes.AIInterpret.verification import (
    verify_report, redact_unverified,
    verify_report_v2, redact_unverified_v2, parse_references_section,
    renumber_citations,
)
from src.classes.AIInterpret.prompts import (
    SYSTEM_PROMPT_INTERPRET, SYSTEM_PROMPT_SYNTHESIZE,
    SYSTEM_PROMPT_INTERPRET_V2, SYSTEM_PROMPT_SYNTHESIZE_V2,
    SYSTEM_PROMPT_VERIFICATION,
    build_batch_interpretation_prompt, build_synthesis_prompt,
    build_two_pass_interpretation_prompt, build_synthesis_prompt_v2,
    build_verification_prompt, build_correction_prompt,
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
)

logger = logging.getLogger(__name__)

# Concurrency control
_pipeline_semaphore = threading.Semaphore(AI_MAX_CONCURRENT_PIPELINES)
_cancel_flags = {}


def run_ai_pipeline(job_id, experiment_design, RESPONSE):
    """PySiQ-compatible entry point. MUST return a Response object."""
    dao = None
    try:
        _pipeline_semaphore.acquire()
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
        # Phase 1: Extract pathway context (0% - 10%)
        # =====================================================================
        dao.save_progress(job_id, {"status": "extracting", "percent": 5, "detail": "Extracting pathway data..."})
        pathways = build_pathway_context(job_instance, max_pathways=AI_MAX_PATHWAYS)
        gene_whitelist = build_gene_symbol_whitelist(job_instance)

        if _cancel_flags.get(job_id):
            raise InterruptedError("Cancelled")

        # =====================================================================
        # Phase 2: Enhanced Paper Fetching (10% - 40%)
        # =====================================================================
        all_papers = []
        total = len(pathways)
        for i, pw in enumerate(pathways):
            dao.save_progress(job_id, {
                "status": "searching_pubmed", "percent": 10 + int(30 * i / max(total, 1)),
                "detail": f"Searching PubMed for \"{pw['name']}\" ({i+1}/{total})"
            })
            gene_symbols = [g["symbol"] for g in pw["top_genes"][:5]]
            q1 = f'"{pw["name"]}"[Title/Abstract] AND "{organism_name}"[Title/Abstract]'
            q2 = (f'({" OR ".join(gene_symbols[:3])}) AND "{pw["name"]}"[Title/Abstract]'
                  if gene_symbols else None)

            pmids = pubmed.search(q1, max_results=AI_PAPERS_PER_PATHWAY)
            if q2:
                pmids += pubmed.search(q2, max_results=3)
            pmids = list(set(pmids))[:AI_PAPERS_PER_PATHWAY]

            # Multi-tier fetching: PMC full text -> Europe PMC -> abstract only
            papers = pubmed.fetch_papers(pmids) if pmids else []
            for p in papers:
                p["pathway"] = pw["name"]
                if "pathways" not in p:
                    p["pathways"] = []
                p["pathways"].append(pw["name"])
            all_papers.extend(papers)

            if _cancel_flags.get(job_id):
                raise InterruptedError("Cancelled")

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
                # Merge pathway info into existing entry
                existing = seen[p["pmid"]]
                if p.get("pathway") and p["pathway"] not in existing.get("pathways", []):
                    existing.setdefault("pathways", []).append(p["pathway"])

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
        dao.save_progress(job_id, {"status": "interpreting", "percent": 45,
                                   "detail": "Generating interpretation with evidence extraction..."})

        interpretation_executor = build_interpretation_executor(paper_index, llm)
        batch_reports = []

        for batch_start in range(0, len(pathways), AI_PATHWAYS_PER_BATCH):
            batch = pathways[batch_start:batch_start + AI_PATHWAYS_PER_BATCH]
            batch_pathway_names = {pw["name"] for pw in batch}

            # Get papers relevant to this batch (by pathway overlap)
            batch_papers = [
                p for p in unique_papers
                if batch_pathway_names & set(p.get("pathways", [p.get("pathway", "")]))
            ]

            prompt = build_two_pass_interpretation_prompt(
                batch, batch_papers, experiment_design, organism_name)

            # Main agent uses extract_evidence tool to spawn sub-agents
            result = llm.complete_with_tools(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_INTERPRET_V2},
                    {"role": "user", "content": prompt},
                ],
                tools=INTERPRETATION_TOOLS,
                tool_executor=interpretation_executor,
                max_tokens=4000,
                temperature=AI_TEMPERATURE,
                max_iterations=15,
            )
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
        dao.save_progress(job_id, {"status": "verifying", "percent": 85, "detail": "Verifying citations..."})

        verification_executor = build_verification_executor(paper_index)

        for iteration in range(AI_MAX_VERIFICATION_ITERATIONS):
            citations = parse_references_section(report)
            if not citations:
                break

            failed_citations = []
            for citation in citations:
                if not citation.get("cited_text"):
                    continue

                verdict = _run_verification_subagent(
                    llm, verification_executor,
                    citation["claim_sentence"],
                    citation["cited_text"],
                    citation["ref_index"],
                )

                if not verdict.get("text_match") or not verdict.get("supports_claim"):
                    failed_citations.append({
                        "ref_index": citation["ref_index"],
                        "reason": verdict.get("reasoning", "Verification failed"),
                        "cited_text": citation["cited_text"],
                        "claim_sentence": citation["claim_sentence"],
                        "actual_text": verdict.get("actual_text", ""),
                        "suggested_fix": verdict.get("suggested_fix", ""),
                    })

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
    import re
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
