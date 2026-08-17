"""The full-agent workflow: one Lead Interpreter Agent running a tool loop.

Design document: ``docs/diagrams/paintomics-ai-agent-proposal.drawio`` (and the
exported ``.drawio.png``). This module is that page, translated:

  * **The loop** -- one SDK ``Agent`` ("Lead Interpreter") whose Observe ->
    Decide -> Act cycle is the Agents SDK tool loop: every turn the model sees
    the notebook and tool results so far (Observe), emits one tool call
    (Decide/Act), and continues until it calls ``submit_report`` -- the only
    door out of the loop.
  * **The toolbelt** -- the existing modules wrapped as tools. The agent
    chooses WHAT; the tool enforces HOW MUCH: the search spend meter, the
    PubMed rate limit and the retrieval guard all live inside
    ``search_literature``, never in the prompt.
  * **Sub-agents** -- reachable only through the ``delegate_*`` tools, and the
    fan-out inside them is parallel bounded calls, not unbounded sub-loops.
  * **The mandatory exit gate** -- outside the loop, where no decision can
    skip it: the same quote collection, canonical references rebuild,
    per-citation Claim Verifier pass and Phase-6 programmatic net
    (verify -> redact -> renumber -> sort) the workflow arm runs.
  * **Loop backstops** -- max turns, a tool-output character ledger, the
    wall-clock deadline and the cancel flag. Hitting one ends the run loudly
    (``stats`` records which), never silently.

Why the loop is budgeted the way it is -- measured on the CSIC gateway
(2026-08-17, see agent.py's transport notes): short single-shot calls
parallelise (32 concurrent in 5.6 s) while tool loops and long generations
serialise, so the design keeps Decide turns terse, makes every fan-out
single-shot, and allows exactly one long-form generation (the report) inside
the loop. The default budget is 10 minutes end to end: the loop gets what is
left after ``AI_AGENT_GATE_RESERVE`` seconds are set aside for the exit gate.

Off by default. ``AI_FULL_AGENT=1`` routes ``run_ai_agent`` here; everything
else (servlet, queue, DAO contract, progress statuses) is unchanged, so the
two arms stay comparable run for run.
"""
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from agents import Agent, ModelSettings, RunContextWrapper, Runner, function_tool

from src.conf.serverconf import (
    AI_LLM_PROVIDER, AI_PROVIDERS, AI_MAX_PATHWAYS, AI_TEMPERATURE,
    AI_PAPERS_PER_SEARCH_TASK, AI_MAX_VERIFICATION_ITERATIONS,
)
from src.classes.AIInterpret import tools as tools_mod
from src.classes.AIInterpret import prompts as prompts_mod
from src.classes.AIInterpret import clusters as clusters_mod
from src.classes.AIInterpret.agent import (
    AgentContext, _build_agents, bounded, configure_sdk, _model, run_hedged,
    SDK_LONG_CALL_TIMEOUT, SDK_VERIFY_CONCURRENCY, SDK_MIN_CITATIONS,
)
from src.classes.AIInterpret.context_builder import (
    build_pathway_context, build_gene_symbol_whitelist, get_organism_name,
    build_cross_omic_matrix, build_key_regulators_block, render_pathway_table,
    triage_pathways,
)
from src.classes.AIInterpret.llm_client import LLMClient
from src.classes.AIInterpret.pubmed_client import PubMedClient
from src.classes.AIInterpret.shared import _collect_cited_quotes, _parse_json_verdict
from src.classes.AIInterpret.verification import (
    count_body_citations, normalize_citation_markers, parse_references_section,
    redact_unverified_v2, render_references_section, renumber_citations,
    resolve_pmid_mentions, sort_references_section, verify_report_v2,
)

logger = logging.getLogger(__name__)

# The whole run, end to end. 600 s is the product constraint this arm is
# benchmarked under; the workflow arm's 2700 s ceiling still applies above it
# in run_agent_workflow-compatible deployments that raise it.
AGENT_RUN_SECONDS = float(os.getenv("AI_AGENT_MAX_RUN_SECONDS", "600"))
# Seconds set aside for the exit gate (quotes + verifier + programmatic net).
# The loop is given the remainder; a loop that spent everything would hand the
# gate a report it has no time to check, which converts "checked" to "shipped".
# Measured over the first live runs: the loop's whole gate (quotes,
# per-citation verification, the programmatic net) cost ~74 s, against the
# workflow arm's 293 s verify loop -- so a 240 s reserve was holding time
# that nothing spent while the loop stopped investigating at 172 s of 600.
GATE_RESERVE_SECONDS = float(os.getenv("AI_AGENT_GATE_RESERVE", "150"))
# Of the loop's own time, the last stretch belongs to writing the report: a
# long-form generation costs ~70-90 s on this gateway, so the tools start
# refusing further investigation this far from the loop deadline. Without it
# the agent is told "stop" only when there is no time left to write, and the
# run lands on the forced-synthesis backstop instead of its own report.
WRITE_RESERVE_SECONDS = float(os.getenv("AI_AGENT_WRITE_RESERVE", "110"))
# Decide turns. Each is one short streamed call at a measured ~3.5 s median.
# Round 1 used 34 tool calls in 172 s and stopped with 300 s of budget
# unspent, so the cap moves up; it is a backstop, not a target, and the
# clock guard still ends investigation in time to write.
AGENT_MAX_TURNS = int(os.getenv("AI_AGENT_MAX_TURNS", "40"))
# The literature spend meter: how many search_literature calls one run may
# make. Enforced in the tool -- the agent is TOLD the remaining budget in
# every result instead of being trusted to count.
# Parity with the workflow arm, which issues 35-45 queries (planner + per-pathway
# backfill) and reaches 27 papers. At 18 the agent retrieved a third of that and
# lost on citations for want of literature rather than judgement -- measured
# over four runs, see docs/ai-agent-benchmark.md.
SEARCH_BUDGET = int(os.getenv("AI_AGENT_SEARCH_BUDGET", "40"))
# Tool-output ledger: total characters of tool results the loop may consume,
# a proxy token backstop on the input side (the model's context is the real
# resource; characters are what this layer can measure without a tokenizer).
TOOL_CHAR_BUDGET = int(os.getenv("AI_AGENT_TOOL_CHAR_BUDGET", "400000"))
# Papers shown to one delegated interpretation. Same value and the same reason
# as the workflow arm's SDK_PAPERS_PER_BATCH.
DELEGATE_PAPERS = int(os.getenv("AI_AGENT_DELEGATE_PAPERS", "10"))
# Hits per search. Deliberately NOT widened: round 6 tried ten and the pool grew
# from ~13 papers to ~49 while citations collapsed 11 -> 3 and redactions rose
# 5.5 -> 11. It is the same effect agent.py records for its batches ("a batch
# handed 20+ abstracts cites fewer of them, not more") reappearing at the merge
# step, which hands the Report Writer the whole master reference list. More
# literature in one prompt buys fewer citations, not more.
SEARCH_HITS = int(os.getenv("AI_AGENT_SEARCH_HITS", str(AI_PAPERS_PER_SEARCH_TASK)))
# Parallel single-shot calls one delegate_* tool may run at once.
DELEGATE_WORKERS = int(os.getenv("AI_AGENT_DELEGATE_WORKERS", "4"))
# Below this many cited papers the gate asks the Report Writer once more to
# use the literature the agent retrieved but never cited. Same floor as the
# workflow arm (SDK_MIN_CITATIONS): the two arms are only comparable if the
# incumbent's own grounding pass exists on both sides.
MIN_CITATIONS = int(os.getenv("AI_AGENT_MIN_CITATIONS", str(SDK_MIN_CITATIONS)))
# Merge the sub-agents' interpretations into the final report rather than
# shipping the Lead's compression of them. AI_AGENT_MERGE_DELEGATED=0 restores
# the round-3 behaviour for comparison.
MERGE_DELEGATED = os.getenv("AI_AGENT_MERGE_DELEGATED", "1") == "1"
# Verify->correct rounds at the gate. 2 = one verification pass, one
# correction, one re-verification -- the 600 s budget does not fit the
# workflow arm's 3 (its own no-progress rule usually stops at 2 anyway).
VERIFY_ITERATIONS = min(int(os.getenv("AI_AGENT_VERIFY_ITERATIONS", "2")),
                        AI_MAX_VERIFICATION_ITERATIONS)


@dataclass
class LoopContext(AgentContext):
    """AgentContext plus the loop's ledger, notebook and trace.

    Subclassing keeps the Claim Verifier's tools working unchanged: they read
    ``ctx.paper_index`` and ``ctx.tool_calls`` through the same attributes.
    """
    agents: dict = field(default_factory=dict)          # the sub-agent registry
    pathways: list = field(default_factory=list)        # ranked context dicts
    gene_whitelist: set = field(default_factory=set)
    partition: Any = None                               # cluster partition or None
    pubmed: Any = None                                  # PubMedClient
    hooks: dict = field(default_factory=dict)
    notebook: list = field(default_factory=list)
    delegated: list = field(default_factory=list)      # sub-agent interpretations
    trace: list = field(default_factory=list)           # toolTrace events
    searches_used: int = 0
    tool_chars: int = 0
    pmid_to_ref: dict = field(default_factory=dict)
    next_ref: int = 1
    submitted_report: str = ""
    started_at: float = 0.0                             # loop start (wall clock)
    archived: list = field(default_factory=list)         # events already on disk
    hard_deadline: float = 0.0                          # loop must be done by


def _hb(ctx, status, percent, detail):
    hooks = ctx.hooks or {}
    if hooks.get("progress"):
        try:
            hooks["progress"](status, percent, detail)
        except Exception:
            logger.debug("progress hook failed", exc_info=True)
    if hooks.get("cancelled") and hooks["cancelled"]():
        raise InterruptedError("Cancelled")


def _archive_trace(ctx):
    """Append this run's trace to a per-run JSONL file.

    The DAO keeps the last 200 events of the current run because that is what a
    UI needs. Deciding which TOOLS are worth their place needs the opposite:
    every run, kept. Measured the hard way -- twelve benchmark runs produced two
    surviving traces, so "never called" could not be told apart from "not called
    in the run that happened to be last", and four tools sat unjudged.

    Best-effort by design: a failed write must never affect an interpretation.
    """
    try:
        from src.conf.serverconf import CLIENT_TMP_DIR
        directory = os.path.join(CLIENT_TMP_DIR, "ai_traces")
        os.makedirs(directory, exist_ok=True)
        stamp = int(ctx.started_at) if ctx.started_at else 0
        path = os.path.join(directory, "%s-%d.jsonl" % (ctx.job_id, stamp))
        with open(path, "a") as handle:
            for event in ctx.trace[len(ctx.archived):]:
                handle.write(json.dumps(event) + "\n")
        ctx.archived = list(ctx.trace)
    except Exception:
        logger.debug("trace archive failed", exc_info=True)


def _trace(ctx, tool, args_summary, result, started):
    """Record one tool call: the run journal, the DAO toolTrace, and progress.

    The trace is the design's run journal made real -- it is what the frontend
    activity feed reads, what a resumed session inspects, and the telemetry
    the benchmark harness scores search spend from.
    """
    event = {
        "seq": len(ctx.trace) + 1,
        "t": round(time.time() - ctx.started_at, 1),
        "tool": tool,
        "args": str(args_summary)[:200],
        "result": str(result)[:200],
        "ms": int((time.time() - started) * 1000),
    }
    ctx.trace.append(event)
    ctx.tool_calls += 1
    _archive_trace(ctx)
    hooks = ctx.hooks or {}
    if hooks.get("tool_event"):
        try:
            hooks["tool_event"](event)
        except Exception:
            logger.debug("tool_event hook failed", exc_info=True)
    # Turn-count progress: the loop has no phases, so the bar walks with work.
    percent = min(70, 15 + int(55 * len(ctx.trace) / max(AGENT_MAX_TURNS, 1)))
    _hb(ctx, "interpreting", percent, "Agent: %s" % tool)


def _ledger_note(ctx):
    remaining = max(0, int(ctx.hard_deadline - time.time()))
    return ("\n[budget: %d searches left · %d s left · %d/%d tool-output chars]"
            % (max(0, SEARCH_BUDGET - ctx.searches_used), remaining,
               ctx.tool_chars, TOOL_CHAR_BUDGET))


def _spend(ctx, text):
    """Count a tool result against the character ledger before returning it."""
    ctx.tool_chars += len(text)
    if ctx.tool_chars > TOOL_CHAR_BUDGET:
        return (text[: max(0, TOOL_CHAR_BUDGET - (ctx.tool_chars - len(text)))]
                + "\n[TOOL BUDGET EXHAUSTED — write your report from the "
                  "notebook and call submit_report now]")
    return text


def _time_guard(ctx):
    """Every tool names the wall it is about to hit; a backstop is never silent.

    The threshold is WRITE_RESERVE_SECONDS rather than a few seconds, because
    being told to stop with 30 s left is being told too late: the report is a
    long-form generation and one of those takes ~70-90 s on this gateway. A
    guard that fires only when there is no time left to write converts "the
    agent chose to stop" into "the loop was cut off mid-investigation with
    nothing submitted", which is the forced-synthesis path, not the design's.
    """
    if time.time() > ctx.hard_deadline - WRITE_RESERVE_SECONDS:
        return ("[TIME IS UP for investigating — %d s remain, and writing the "
                "report needs them. Do not call another data or literature "
                "tool. Write the report from your notebook and call "
                "submit_report now.]"
                % max(0, int(ctx.hard_deadline - time.time())))
    return None


# ---------------------------------------------------------------------------
# The toolbelt. Docstrings are the tool descriptions the model sees.
# ---------------------------------------------------------------------------

def _ctx_by_id(ctx):
    """id -> pathway context dict, for the cluster renderers."""
    return {p["id"]: p for p in ctx.pathways}


def _pathway_block(p):
    lines = ["### %s (%s, %s)" % (p.get("name"), p.get("id"), p.get("source"))]
    lines.append("Combined p=%.3g · global p=%s · significant omic layers: %s"
                 % (p.get("combined_pvalue") or 1.0, p.get("global_pvalue"),
                    p.get("significant_omic_count")))
    if p.get("per_omic"):
        lines.append("Per-omic: %s" % p["per_omic"])
    for g in (p.get("top_genes") or [])[:10]:
        profs = "; ".join(
            "%s: %s (%s)" % (op.get("omic"), op.get("values", op.get("value_pairs", "")),
                             op.get("pattern", ""))
            for op in (g.get("omic_profiles") or []))
        lines.append("- %s%s [effect %.2f] %s"
                     % (g.get("symbol"), "*" if g.get("relevant") else "",
                        g.get("effect_size") or 0, profs))
    return "\n".join(lines)


@function_tool
def get_experiment_overview(ctx: RunContextWrapper[LoopContext]) -> str:
    """The experiment at a glance: design, enriched pathway table, cross-omic matrix and key regulators. Start here."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    major, _minor = triage_pathways(c.pathways)
    parts = ["Organism: %s" % c.organism_name,
             "Design: %s" % (c.experiment_design or "(none given)"),
             render_pathway_table(c.pathways)]
    try:
        parts.append(build_cross_omic_matrix(major))
    except Exception as e:
        logger.warning("[%s][loop] cross-omic matrix failed: %s", c.job_id, e)
    try:
        parts.append(build_key_regulators_block(c.job_instance, limit=30))
    except Exception as e:
        logger.warning("[%s][loop] regulators block failed: %s", c.job_id, e)
    out = _spend(c, "\n\n".join(x for x in parts if x) + _ledger_note(c))
    _trace(c, "get_experiment_overview", "", "%d chars" % len(out), t0)
    return out


@function_tool
def get_pathway_details(ctx: RunContextWrapper[LoopContext],
                        pathway_names: list[str]) -> str:
    """Detailed data (p-values per layer, top genes with temporal profiles) for the named or ID'd pathways. Instant and free -- read the data before theorising about it, and ask for several pathways at once."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    wanted = {w.strip().lower() for w in pathway_names if w and w.strip()}
    blocks, matched_ids = [], []
    for p in c.pathways:
        keys = {str(p.get("name", "")).lower(), str(p.get("id", "")).lower()}
        if keys & wanted or any(w in k for k in keys for w in wanted):
            blocks.append(_pathway_block(p))
            matched_ids.append(p.get("id"))
        if len(blocks) >= 8:
            break
    if not blocks:
        out = ("No match among the enriched pathways for %s. Known: %s"
               % (pathway_names,
                  ", ".join(p.get("name", "?") for p in c.pathways[:30])))
    else:
        out = "\n\n".join(blocks) + _ledger_note(c)
    out = _spend(c, out)
    _trace(c, "get_pathway_details", pathway_names, matched_ids or "none", t0)
    return out


@function_tool
def get_gene_profile(ctx: RunContextWrapper[LoopContext], gene_symbol: str) -> str:
    """All measured timepoint values for one gene across every omic layer. Instant and free."""
    c = ctx.context
    t0 = time.time()
    out = _spend(c, tools_mod.execute_tool(
        "get_gene_timecourse", c.job_instance, {"gene_symbol": gene_symbol}))
    _trace(c, "get_gene_profile", gene_symbol, out[:60], t0)
    return out


@function_tool
def compare_gene_profiles(ctx: RunContextWrapper[LoopContext],
                          gene_symbols: list[str]) -> str:
    """Side-by-side measured values for several genes (max 10) across all omic layers. Instant and free -- prefer this over one get_gene_profile call per gene."""
    c = ctx.context
    t0 = time.time()
    out = _spend(c, tools_mod.execute_tool(
        "compare_genes", c.job_instance, {"gene_symbols": gene_symbols}))
    _trace(c, "compare_gene_profiles", gene_symbols, out[:60], t0)
    return out


@function_tool
def cluster_pathways(ctx: RunContextWrapper[LoopContext]) -> str:
    """Group the significant pathways by shared matched features (deterministic; no LLM). Returns clusters with their shared gene cores. Costs about half a second; worth calling once, early."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    if c.partition is None:
        try:
            candidate = clusters_mod.build_partition(
                c.job_instance, always_include=[p["id"] for p in c.pathways])
            member_ids = clusters_mod.partition_member_ids(candidate)
            if candidate.get("clusters") and member_ids:
                c.partition = candidate
                # Clustering widens what the agent can reach, exactly as it does
                # in the workflow arm: the partition covers every significant
                # pathway, so rebuild the context over its members (still in
                # global rank order) and let get_pathway_details see them all.
                # Without this the cluster table names pathways the agent then
                # cannot look up -- a map with no territory behind it.
                c.pathways = build_pathway_context(c.job_instance,
                                                   pathway_ids=member_ids)
                if (c.hooks or {}).get("partition"):
                    try:
                        c.hooks["partition"](candidate)
                    except Exception:
                        logger.debug("partition hook failed", exc_info=True)
                if (c.hooks or {}).get("pathways"):
                    try:
                        c.hooks["pathways"](c.pathways)
                    except Exception:
                        logger.debug("pathway-index hook failed", exc_info=True)
        except Exception as e:
            out = "Clustering failed: %s" % e
            _trace(c, "cluster_pathways", "", out, t0)
            return out
    if c.partition is None:
        out = "No clusters found: the significant pathways share too few features."
    else:
        out = clusters_mod.render_partition_table(c.partition, _ctx_by_id(c))
    out = _spend(c, out + _ledger_note(c))
    _trace(c, "cluster_pathways", "",
           clusters_mod.partition_summary(c.partition) if c.partition else "none", t0)
    return out


def _register_papers(c, papers, tag):
    """Give new papers a global ref_index and remember them; dedup by PMID."""
    listed = []
    for paper in papers:
        pmid = str(paper.get("pmid") or "")
        if not pmid:
            continue
        if pmid in c.pmid_to_ref:
            ref = c.pmid_to_ref[pmid]
            existing = c.paper_index[ref]
            if tag and tag not in existing.setdefault("pathways", []):
                existing["pathways"].append(tag)
        else:
            ref = c.next_ref
            c.next_ref += 1
            c.pmid_to_ref[pmid] = ref
            paper = dict(paper)
            paper.setdefault("sections", {"abstract": paper.get("abstract", "")})
            paper.setdefault("fetch_tier", "abstract_only")
            paper.setdefault("full_text_available", False)
            paper["ref_index"] = ref
            paper["pathways"] = [tag] if tag else []
            c.paper_index[ref] = paper
        p = c.paper_index[c.pmid_to_ref[pmid]]
        listed.append("[%d] %s (%s, %s) — %s"
                      % (p["ref_index"], p.get("title", "")[:110],
                         p.get("first_author", "?"), p.get("year", "?"),
                         (p.get("abstract") or "")[:240]))
    return listed


@function_tool
async def search_literature(ctx: RunContextWrapper[LoopContext], query: str,
                            topic_tag: str) -> str:
    """Search PubMed (about 2 s). Returns papers as [N] entries you may cite. Keep queries BROAD: two or three gene symbols joined by OR, AND at most one biological term, e.g. "(Ikzf1 OR Ccnd2) AND B cell differentiation". Extra AND clauses return nothing and still cost budget. topic_tag names the pathway/theme this search supports. Spend-metered."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    if c.searches_used >= SEARCH_BUDGET:
        out = ("SEARCH BUDGET EXHAUSTED (%d used). Cite what you have or "
               "read_paper for depth; do not ask again." % c.searches_used)
        _trace(c, "search_literature", query, "budget exhausted", t0)
        return out
    c.searches_used += 1
    try:
        pmids = await asyncio.to_thread(c.pubmed.search, query, SEARCH_HITS)
        new = [p for p in pmids if str(p) not in c.pmid_to_ref]
        papers = (await asyncio.to_thread(c.pubmed.fetch_abstracts, new)
                  if new else [])
    except Exception as e:
        out = "Search failed (%s). The budget was still spent." % e
        _trace(c, "search_literature", query, out, t0)
        return out + _ledger_note(c)
    listed = _register_papers(c, papers, topic_tag)
    for pmid in pmids:                       # already-known hits are re-listed
        ref = c.pmid_to_ref.get(str(pmid))
        if ref and not any(l.startswith("[%d]" % ref) for l in listed):
            p = c.paper_index[ref]
            listed.append("[%d] %s (%s) — already retrieved"
                          % (ref, p.get("title", "")[:110], p.get("year", "?")))
    if not listed:
        # Measured in the first live runs: 7 of 14 searches came back empty
        # because the query stacked too many AND terms. The budget was spent
        # either way, so the result says how to spend the next one better.
        body = ("no hits. PubMed matched nothing for that query -- it is "
                "probably too narrow. Drop an AND clause, use gene symbols "
                "with OR, or search the biology without the organism term.")
    else:
        body = "\n".join(listed)
    out = "Results for '%s': %s%s" % (query, body, _ledger_note(c))
    out = _spend(c, out)
    _trace(c, "search_literature", query, "%d hits, %d new" %
           (len(pmids), len(listed)), t0)
    return out


@function_tool
async def read_paper(ctx: RunContextWrapper[LoopContext], ref_index: int,
                     section: str) -> str:
    """Read one section (abstract, introduction, results, discussion, other) of a retrieved paper [N]. Fetches full text on first use, about 3 s. Do this before citing a paper for a specific claim -- an unread citation is the kind the verifier removes."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    paper = c.paper_index.get(int(ref_index))
    if paper is None:
        out = "No paper [%s]. Cite only indices search_literature returned." % ref_index
        _trace(c, "read_paper", ref_index, "unknown ref", t0)
        return out
    if paper.get("fetch_tier") == "abstract_only":
        try:
            upgraded = await asyncio.to_thread(c.pubmed.fetch_papers,
                                               [paper["pmid"]])
            if upgraded:
                fresh = upgraded[0]
                fresh["ref_index"] = paper["ref_index"]
                fresh["pathways"] = paper.get("pathways", [])
                c.paper_index[paper["ref_index"]] = fresh
                paper = fresh
        except Exception as e:
            logger.warning("[%s][loop] full-text upgrade failed for %s: %s",
                           c.job_id, paper.get("pmid"), e)
    executor = tools_mod.build_verification_executor(c.paper_index)
    out = executor("fetch_paper_section",
                   {"ref_index": int(ref_index), "section": section})
    out = _spend(c, out + _ledger_note(c))
    _trace(c, "read_paper", "[%s] %s" % (ref_index, section),
           "%d chars" % len(out), t0)
    return out


@function_tool
def notebook_write(ctx: RunContextWrapper[LoopContext], note: str) -> str:
    """Record a finding, hypothesis or open question in your run notebook. Free. Write one after every substantive discovery -- it is what the report is assembled from."""
    c = ctx.context
    t0 = time.time()
    c.notebook.append(note.strip())
    if (c.hooks or {}).get("notebook"):
        try:
            c.hooks["notebook"](list(c.notebook))
        except Exception:
            logger.debug("notebook hook failed", exc_info=True)
    out = "Noted (%d entries)." % len(c.notebook)
    _trace(c, "notebook_write", note[:80], out, t0)
    return out


@function_tool
def notebook_read(ctx: RunContextWrapper[LoopContext]) -> str:
    """Re-read your run notebook (numbered)."""
    c = ctx.context
    t0 = time.time()
    out = "\n".join("%d. %s" % (i, n) for i, n in enumerate(c.notebook, 1)) \
          or "(the notebook is empty)"
    out = _spend(c, out)
    _trace(c, "notebook_read", "", "%d entries" % len(c.notebook), t0)
    return out


@function_tool
def check_my_citations(ctx: RunContextWrapper[LoopContext], draft: str) -> str:
    """Advisory pre-check of a draft's [N] citations against the retrieved papers (deterministic). The mandatory exit gate still runs after you submit."""
    c = ctx.context
    t0 = time.time()
    papers = [c.paper_index[k] for k in sorted(c.paper_index)]
    try:
        result = verify_report_v2(normalize_citation_markers(draft),
                                  c.gene_whitelist, papers, c.job_instance)
    except Exception as e:
        out = "Check failed: %s" % e
        _trace(c, "check_my_citations", "%d chars" % len(draft), out, t0)
        return out
    failed = result.get("failed_citations") or []
    lines = ["citations checked: %s" % result.get("citations_checked"),
             "invalid or unsupported: %d" % len(failed)]
    for f in failed[:10]:
        lines.append("- [%s] %s" % (f.get("ref_index"), f.get("reason", "")[:140]))
    out = _spend(c, "\n".join(lines))
    _trace(c, "check_my_citations", "%d chars" % len(draft),
           "%d failed" % len(failed), t0)
    return out


async def _single_shot(agent, prompt, ctx, timeout, label):
    try:
        r = await bounded(Runner.run(agent, prompt, context=ctx, max_turns=2),
                          timeout, label=label)
        return str(r.final_output)
    except (Exception, asyncio.TimeoutError) as e:
        logger.warning("[%s][loop] %s failed: %s", ctx.job_id, label, e)
        return ""


@function_tool
async def delegate_interpretation(ctx: RunContextWrapper[LoopContext],
                                  pathway_names: list[str], focus: str) -> str:
    """Delegate deep interpretation of up to ~10 named pathways to Cluster Interpreter sub-agents (parallel, single-shot). Returns their reports; their [N] citations use your reference numbers. EXPENSIVE: about 25 seconds per call, the costliest thing you can do -- but it is also where breadth comes from, so plan two or three calls covering everything rather than one per pathway."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    wanted = {w.strip().lower() for w in pathway_names if w and w.strip()}
    chosen = [p for p in c.pathways
              if {str(p.get("name", "")).lower(), str(p.get("id", "")).lower()} & wanted
              or any(w in str(p.get("name", "")).lower() for w in wanted)][:10]
    if not chosen:
        out = "No enriched pathway matches %s." % pathway_names
        _trace(c, "delegate_interpretation", pathway_names, "no match", t0)
        return out
    papers = [c.paper_index[k] for k in sorted(c.paper_index)]
    interpreter = c.agents["interpret_light"]
    chunks = [chosen[i:i + 5] for i in range(0, len(chosen), 5)]
    sem = asyncio.Semaphore(DELEGATE_WORKERS)

    def _papers_for(chunk):
        """The papers ATTRIBUTED to this chunk's pathways, as the workflow arm
        selects them (agent.py::_one_batch).

        Handing every sub-agent the same arbitrary first-N papers is why round 4
        wrote 39 k characters and cited four of them: an interpretation of
        pathways whose literature it was never shown has nothing to cite. The
        topic_tag the Lead passes to search_literature is the attribution key,
        matched loosely because the Lead writes it in its own words.
        """
        names = {str(p.get("name", "")).lower() for p in chunk}
        ids = {str(p.get("id", "")).lower() for p in chunk}
        hits = []
        for paper in papers:
            tags = [str(t).lower() for t in (paper.get("pathways") or [])]
            if any(t in names or t in ids
                   or any(t in n or n in t for n in names if n and t)
                   for t in tags):
                hits.append(paper)
        # No attribution match (the Lead tagged by theme, not pathway): fall back
        # to the most recently retrieved, which are its latest lines of enquiry.
        if not hits:
            hits = papers[-DELEGATE_PAPERS:]
        # Cap what one prompt reasons over. The workflow arm measured citations
        # COLLAPSING 15 -> 3 when a batch was handed 20+ abstracts, so more
        # literature per prompt is not better; full text first, then earliest.
        if len(hits) > DELEGATE_PAPERS:
            hits = sorted(hits, key=lambda p: (not p.get("full_text_available"),
                                               p.get("ref_index", 0)))[:DELEGATE_PAPERS]
        return hits

    async def _one(chunk):
        async with sem:
            prompt = prompts_mod.build_batch_interpretation_prompt(
                chunk, _papers_for(chunk), c.experiment_design, c.organism_name)
            if focus:
                prompt += "\n\nFocus of this delegation: %s" % focus
            return await _single_shot(interpreter, prompt, c, 150,
                                      "delegate[%d pathways]" % len(chunk))

    reports = await asyncio.gather(*[_one(ch) for ch in chunks])
    # Keep the sub-agents' text: measured over three rounds, the Lead compresses
    # these interpretations into a summary a fifth the length of the workflow
    # arm's report, and the detail is lost with them. The gate re-synthesises
    # from what is kept here (see _merge_delegated).
    c.delegated.extend(r for r in reports if r)
    out = "\n\n---\n\n".join(r for r in reports if r) or "(delegation produced nothing)"
    out = _spend(c, out + _ledger_note(c))
    _trace(c, "delegate_interpretation",
           "%d pathways / %d chunks" % (len(chosen), len(chunks)),
           "%d chars" % len(out), t0)
    return out


@function_tool
async def delegate_literature(ctx: RunContextWrapper[LoopContext],
                              topic: str, gene_symbols: list[str]) -> str:
    """Delegate a literature sweep on one topic to the Literature Agent sub-agent: it issues up to 3 gene-anchored searches from your remaining budget and summarises what it found."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    genes = [g for g in (gene_symbols or []) if g][:4]
    queries = []
    if genes:
        queries.append("(%s) AND %s" % (" OR ".join(genes), topic))
        if len(genes) > 1:
            queries.append("(%s) AND %s" % (" OR ".join(genes[:2]), c.organism_name))
    queries.append(topic)
    found = []
    for q in queries[:3]:
        if c.searches_used >= SEARCH_BUDGET:
            found.append("(search budget exhausted)")
            break
        c.searches_used += 1
        try:
            pmids = await asyncio.to_thread(c.pubmed.search, q, SEARCH_HITS)
            new = [p for p in pmids if str(p) not in c.pmid_to_ref]
            papers = (await asyncio.to_thread(c.pubmed.fetch_abstracts, new)
                      if new else [])
            found.extend(_register_papers(c, papers, topic))
        except Exception as e:
            found.append("(search '%s' failed: %s)" % (q, e))
    out = ("Literature sweep on '%s':\n%s" % (topic, "\n".join(found) or "(nothing new)")
           + _ledger_note(c))
    out = _spend(c, out)
    _trace(c, "delegate_literature", topic, "%d lines" % len(found), t0)
    return out


@function_tool
def submit_report(ctx: RunContextWrapper[LoopContext], report_markdown: str) -> str:
    """Submit your final report (markdown, [N] citations). The only way to finish. It goes to the mandatory verification gate, never straight to the user."""
    c = ctx.context
    t0 = time.time()
    if len(report_markdown.strip()) < 500:
        out = ("REJECTED: that is not a report (%d chars). Write the full "
               "analysis: Key Findings, Cross-Pathway Themes, Detailed Pathway "
               "Analysis, Suggested Follow-up Experiments, Limitations."
               % len(report_markdown.strip()))
        _trace(c, "submit_report", "%d chars" % len(report_markdown), "rejected", t0)
        return out
    c.submitted_report = report_markdown
    _trace(c, "submit_report", "%d chars" % len(report_markdown), "accepted", t0)
    return "SUBMITTED. Reply with the single word DONE and stop."


TOOLBELT = [get_experiment_overview, get_pathway_details, get_gene_profile,
            compare_gene_profiles, cluster_pathways, search_literature,
            read_paper, notebook_write, notebook_read, check_my_citations,
            delegate_interpretation, delegate_literature, submit_report]


# ---------------------------------------------------------------------------
# Orchestration: the loop, then the mandatory exit gate.
# ---------------------------------------------------------------------------

async def _run_loop_async(job_instance, job_id, experiment_design, budgets,
                          stats, hooks=None):
    hooks = hooks or {}
    configure_sdk()
    agents = _build_agents()

    organism = job_instance.getOrganism()
    organism_name = get_organism_name(organism)
    pathways = build_pathway_context(job_instance,
                                     max_pathways=budgets["max_pathways"])
    gene_whitelist = build_gene_symbol_whitelist(job_instance)
    if hooks.get("pathways"):
        try:
            hooks["pathways"](pathways)
        except Exception:
            logger.debug("pathway-index hook failed", exc_info=True)

    ctx = LoopContext(job_instance=job_instance, job_id=job_id,
                      organism_name=organism_name,
                      experiment_design=experiment_design or "",
                      agents=agents,
                      pathways=pathways, gene_whitelist=gene_whitelist,
                      pubmed=PubMedClient(), hooks=hooks,
                      started_at=time.time(),
                      hard_deadline=time.time() + AGENT_RUN_SECONDS
                                    - GATE_RESERVE_SECONDS)

    lead = Agent[LoopContext](
        name="Lead Interpreter",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_LEAD_AGENT,
        model_settings=ModelSettings(temperature=AI_TEMPERATURE),
        # No output_type, ever: with tools it silences every tool call (the
        # rubber-stamp verifier, agent.py _build_agents). submit_report IS the
        # structured exit.
        tools=TOOLBELT,
    )

    _hb(ctx, "extracting", 10, "Agent reading the enrichment results...")
    kickoff = prompts_mod.build_lead_kickoff_prompt(
        organism_name, experiment_design, pathways, AGENT_MAX_TURNS,
        SEARCH_BUDGET, int(AGENT_RUN_SECONDS - GATE_RESERVE_SECONDS))

    loop_budget = max(60.0, ctx.hard_deadline - time.time())
    t0 = time.time()
    try:
        result = await bounded(
            Runner.run(lead, kickoff, context=ctx, max_turns=AGENT_MAX_TURNS),
            loop_budget, label="lead loop")
        stats["loop_final"] = str(result.final_output)[:200]
    except asyncio.TimeoutError:
        stats["loop_backstop"] = "wall-clock"
        logger.warning("[%s][loop] the loop hit its wall-clock backstop", job_id)
    except Exception as e:
        # MaxTurnsExceeded lands here too: the turn cap is a backstop, and a
        # submitted report survives it.
        stats["loop_backstop"] = "%s: %s" % (type(e).__name__, e)
        logger.warning("[%s][loop] loop ended by backstop: %s", job_id, e)
    stats["loop_s"] = time.time() - t0
    stats["agent_tool_calls"] = len(ctx.trace)
    stats["agent_searches"] = ctx.searches_used
    stats["agent_notebook"] = len(ctx.notebook)

    report = ctx.submitted_report
    if not report.strip():
        # The loop ended without walking through its one door. The backstop
        # answer is a single bounded synthesis from whatever the run learned:
        # loud in stats, and strictly better than shipping nothing.
        stats["forced_synthesis"] = True
        _hb(ctx, "synthesizing", 78, "Synthesizing report from the notebook...")
        papers = [ctx.paper_index[k] for k in sorted(ctx.paper_index)]
        notebook = "\n".join("- %s" % n for n in ctx.notebook) or "(empty)"
        prompt = prompts_mod.build_synthesis_prompt_v2(
            ["## Investigation notebook\n" + notebook],
            experiment_design, organism_name, papers)
        try:
            r = await bounded(Runner.run(agents["synth"], prompt, context=ctx,
                                         max_turns=3),
                              SDK_LONG_CALL_TIMEOUT, label="forced synthesis")
            report = str(r.final_output)
        except (Exception, asyncio.TimeoutError) as e:
            raise RuntimeError("The agent produced no report (loop: %s; "
                               "forced synthesis: %s)" %
                               (stats.get("loop_backstop", "ended"), e))

    # ---- carry the delegated detail into the report ------------------------
    # The workflow arm's 39 k of prose comes from synthesising ACROSS its three
    # batch reports; the agent had the same material (its delegations) and
    # summarised it away, which is the whole of the measured gap after retrieval
    # was fixed. So the submitted draft and the sub-agents' reports are merged
    # by one Report Writer pass -- and kept only if it is genuinely fuller and
    # cites at least as much, so a "merge" can never shrink the report.
    if ctx.delegated and MERGE_DELEGATED:
        t_m = time.time()
        papers_now = [ctx.paper_index[k] for k in sorted(ctx.paper_index)]
        valid = {p["ref_index"] for p in papers_now}
        before = len(count_body_citations(str(report), valid))
        prompt = prompts_mod.build_synthesis_prompt_v2(
            ctx.delegated + ["## The lead interpreter's own draft\n" + report],
            experiment_design, organism_name, papers_now)
        prompt += ("\n\nThe last block is the lead interpreter's draft: keep its "
                   "structure, its Key Findings and its judgements, and restore "
                   "the per-pathway detail from the batch reports that the draft "
                   "compressed away. Every pathway named in any block gets its "
                   "own paragraph. Do not invent citations.")
        try:
            merged = await bounded(
                Runner.run(agents["synth"], prompt, context=ctx, max_turns=3),
                SDK_LONG_CALL_TIMEOUT, label="delegated merge")
            candidate = resolve_pmid_mentions(str(merged.final_output),
                                              ctx.paper_index)
            after = len(count_body_citations(candidate, valid))
            if len(candidate) > 1.2 * len(str(report)) and after >= before:
                stats["merge_gain_chars"] = len(candidate) - len(str(report))
                report = candidate
            else:
                stats["merge_rejected"] = True
        except (Exception, asyncio.TimeoutError) as e:
            stats["merge_failed"] = "%s: %s" % (type(e).__name__, e)
            logger.warning("[%s][loop] delegated merge failed: %s", job_id, e)
        stats["merge_s"] = time.time() - t_m

    # The deterministic tables ride below the prose, exactly as the workflow
    # arm ships them (its phase 5d): data the job already holds is appended,
    # never asked of the model.
    if "## Enriched Pathway Summary" not in report:
        report = report.rstrip() + "\n\n" + render_pathway_table(pathways)
    if ctx.partition is not None:
        table = clusters_mod.render_partition_table(ctx.partition,
                                                   _ctx_by_id(ctx))
        if table and "## Pathway Clusters" not in report:
            report = report.rstrip() + "\n\n" + table
        note = clusters_mod.render_reading_note(ctx.partition)
        if note and note not in report:
            report = note + "\n\n" + report

    # ---- The mandatory exit gate ------------------------------------------
    # Identical sequence to agent.py's tail (phases 5a''''-6): marker hygiene,
    # quotes, canonical references, the Claim Verifier pass, then the
    # programmatic net. Kept in the same order on purpose -- and pinned by
    # test_reference_section_ordering against THIS module too.
    unique_papers = [ctx.paper_index[k] for k in sorted(ctx.paper_index)]
    report = resolve_pmid_mentions(report, ctx.paper_index)
    report = normalize_citation_markers(report)

    # ---- citation top-up (parity with the workflow arm's phase 5) ---------
    valid_indices = {p["ref_index"] for p in unique_papers}
    cited_now = count_body_citations(str(report), valid_indices)
    uncited = [p for p in unique_papers if p["ref_index"] not in cited_now]
    if uncited and len(cited_now) < MIN_CITATIONS:
        listing = "\n".join(
            "[%d] %s — %s" % (p["ref_index"], (p.get("title") or "")[:110],
                              (p.get("abstract") or "")[:220])
            for p in uncited[:30])
        t_top = time.time()
        try:
            topped = await bounded(Runner.run(
                agents["synth"],
                "Here is your report:\n\n%s\n\n"
                "These retrieved papers are not cited anywhere in it:\n\n%s\n\n"
                "Return the SAME report with citations added wherever one of "
                "these papers genuinely supports a statement you already make. "
                "Change nothing else: no new findings, no rewritten analysis, "
                "no altered numbers. Add [N] only where that paper really does "
                "support that sentence -- a citation that does not fit is "
                "removed later along with the claim it sits on, so forcing one "
                "in costs you the finding. Leaving a paper uncited is a fine "
                "outcome." % (report, listing),
                context=ctx, max_turns=3),
                SDK_LONG_CALL_TIMEOUT, label="loop citation top-up")
            candidate = resolve_pmid_mentions(str(topped.final_output),
                                             ctx.paper_index)
            added = len(count_body_citations(candidate, valid_indices))
            # Same acceptance test as the workflow arm: a "top-up" that
            # shortens the report into a summary is a regression wearing a
            # bigger citation count.
            if len(candidate) > 0.6 * len(str(report)) and added > len(cited_now):
                report = candidate
                stats["topup_added"] = added - len(cited_now)
            else:
                stats["topup_rejected"] = True
        except (Exception, asyncio.TimeoutError) as e:
            stats["topup_failed"] = "%s: %s" % (type(e).__name__, e)
            logger.warning("[%s][loop] citation top-up failed: %s: %s",
                           job_id, type(e).__name__, e)
        stats["topup_s"] = time.time() - t_top

    llm_for_quotes = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER])
    _hb(ctx, "verifying", 80, "Collecting supporting quotes...")
    quotes = _collect_cited_quotes(llm_for_quotes, report, ctx.paper_index, job_id)
    report, rendered = render_references_section(report, ctx.paper_index, quotes)
    stats["refs_rendered"] = len(rendered)
    stats["quotes_supplied"] = len(quotes)

    _hb(ctx, "verifying", 85, "Verifying citations...")
    t0 = time.time()
    previous_failures = None
    for _iteration in range(VERIFY_ITERATIONS):
        citations = parse_references_section(report)
        to_verify = [c for c in citations if c.get("cited_text")]
        if not to_verify:
            break
        vsem = asyncio.Semaphore(SDK_VERIFY_CONCURRENCY)

        async def _verify_one(cit):
            async with vsem:
                try:
                    r = await run_hedged(
                        agents["verify"],
                        prompts_mod.build_verification_prompt(
                            cit["claim_sentence"], cit["cited_text"],
                            cit["ref_index"]),
                        ctx, max_turns=6, label="verify[%s]" % cit["ref_index"])
                    return cit, str(r.final_output)
                except Exception as e:
                    logger.warning("[%s][loop] verifier raised for [%s]: %s",
                                   job_id, cit["ref_index"], e)
                    return cit, ""

        verdicts = await asyncio.gather(*[_verify_one(c) for c in to_verify])
        failed = []
        for cit, text in verdicts:
            v = _parse_json_verdict(text) if text else {
                "text_match": False, "supports_claim": False,
                "reasoning": "Verification error"}
            if not v.get("text_match") or not v.get("supports_claim"):
                failed.append({"ref_index": cit["ref_index"],
                               "reason": v.get("reasoning", "Verification failed"),
                               "cited_text": cit["cited_text"],
                               "claim_sentence": cit["claim_sentence"],
                               "actual_text": v.get("actual_text", ""),
                               "suggested_fix": v.get("suggested_fix", "")})
        failed.sort(key=lambda c: c["ref_index"])
        logger.info("[%s][loop] VERIFY iter %d: %d checked, %d failed",
                    job_id, _iteration + 1, len(to_verify), len(failed))
        if not failed:
            break
        if previous_failures is not None and len(failed) >= previous_failures:
            break
        previous_failures = len(failed)
        if _iteration == VERIFY_ITERATIONS - 1:
            break
        try:
            corr = await bounded(Runner.run(
                agents["synth"],
                "Here is your report:\n\n%s\n\n%s"
                % (report, prompts_mod.build_correction_prompt(report, failed)),
                context=ctx, max_turns=3), SDK_LONG_CALL_TIMEOUT,
                label="loop correction rewrite")
        except (Exception, asyncio.TimeoutError) as e:
            stats["correction_failed"] = "%s: %s" % (type(e).__name__, e)
            break
        report = resolve_pmid_mentions(str(corr.final_output), ctx.paper_index)
        report = normalize_citation_markers(report)
        quotes.update(_collect_cited_quotes(llm_for_quotes, report,
                                            ctx.paper_index, job_id, known=quotes))
        report, _ = render_references_section(report, ctx.paper_index, quotes)
    stats["verify_loop_s"] = time.time() - t0

    # ---- Phase 6, verbatim: the programmatic net --------------------------
    t0 = time.time()
    final = verify_report_v2(report, gene_whitelist, unique_papers, job_instance)
    if final.get("failed_citations"):
        report, removed = redact_unverified_v2(report, final["failed_citations"])
        final["redacted_count"] = removed
    report, citation_mapping = renumber_citations(report)
    report = sort_references_section(report)
    if citation_mapping:
        kept = []
        for p in unique_papers:
            if p["ref_index"] in citation_mapping:
                p["ref_index"] = citation_mapping[p["ref_index"]]
                kept.append(p)
        kept.sort(key=lambda p: p["ref_index"])
        unique_papers = kept
    stats["verify_s"] = time.time() - t0
    stats["tool_calls"] = ctx.tool_calls
    stats["verification"] = final
    if hooks.get("notebook") and ctx.notebook:
        try:
            hooks["notebook"](list(ctx.notebook))
        except Exception:
            pass
    return report, unique_papers, ctx


def run_agent_loop_workflow(job_instance, job_id, experiment_design,
                            budgets=None, hooks=None):
    """Synchronous entry point; same contract as run_agent_workflow."""
    budgets = budgets or {"max_pathways": AI_MAX_PATHWAYS}
    stats = {"mode": "full_agent"}
    t0 = time.time()

    async def _with_deadline():
        try:
            return await asyncio.wait_for(
                _run_loop_async(job_instance, job_id, experiment_design,
                                budgets, stats, hooks=hooks),
                timeout=AGENT_RUN_SECONDS)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "The agent interpretation exceeded its %d-minute limit and "
                "was stopped. Please try again later."
                % max(1, int(AGENT_RUN_SECONDS // 60)))

    report, papers, ctx = asyncio.run(_with_deadline())
    stats["total_s"] = time.time() - t0
    return {"report": report, "papers": papers, "stats": stats}
