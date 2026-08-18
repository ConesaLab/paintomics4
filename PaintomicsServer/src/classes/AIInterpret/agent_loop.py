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
import re
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
    SDK_CALL_TIMEOUT,
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
    _fuzzy_contains,
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
DELEGATE_MAX_PATHWAYS = int(os.getenv("AI_AGENT_DELEGATE_MAX_PATHWAYS", "20"))
"""Pathways one delegate call may cover, chunked five to a sub-agent.

Was 10, which is two chunks -- so two of the four worker slots never ran and
the arm had half the places a citation can be born. Base writes fourteen
batches, each citing its own papers, and converts 58% of retrieved papers
into shipped citations against this arm's 16%. Twenty pathways is four
chunks, which fills DELEGATE_WORKERS exactly, so the extra breadth is free
in wall clock: four sub-agents run in the time two did.
"""

DELEGATE_QUOTE_SECONDS = float(os.getenv("AI_AGENT_DELEGATE_QUOTE_SECONDS", "45"))
"""Ceiling on grounding a delegation's citations, so it cannot eat the run.

Collection is a thread pool of 8 and costs about 5 s for 20 citations; 45 s
is room for a wide delegation plus a slow gateway, and no more.
"""
# Below this many cited papers the gate asks the Report Writer once more to
# use the literature the agent retrieved but never cited. Same floor as the
# workflow arm (SDK_MIN_CITATIONS): the two arms are only comparable if the
# incumbent's own grounding pass exists on both sides.
MIN_CITATIONS = int(os.getenv("AI_AGENT_MIN_CITATIONS", str(SDK_MIN_CITATIONS)))
# Merge the sub-agents' interpretations into the final report rather than
# shipping the Lead's compression of them. AI_AGENT_MERGE_DELEGATED=0 restores
# the round-3 behaviour for comparison.
MERGE_DELEGATED = os.getenv("AI_AGENT_MERGE_DELEGATED", "1") == "1"
# "stitch" keeps each delegated report's own grounded text and spends the writer
# call only on framing prose; "rewrite" is round 4-5's single pass over
# everything, which measured 4.5-11 citations because the writer saw the whole
# reference list at once.
MERGE_MODE = os.getenv("AI_AGENT_MERGE_MODE", "stitch")
# The gate's own floor. Post-loop work (the merge) is bounded by the clock that
# is actually left after reserving this, and skipped when there is not enough --
# measured the hard way: a 50 s merge on top of a 450 s loop and a 150 s reserve
# put a run at 602 s and it died on the 600 s ceiling with nothing to show. A
# step that can push a run past its deadline is not optional work, it is a bug.
GATE_MIN_SECONDS = float(os.getenv("AI_AGENT_GATE_MIN", "130"))
# Ceiling on the stitched per-pathway detail. Measured: stitching every delegated
# report verbatim produced a 90 621-char report, 2.2x the workflow arm's, which
# is not "thorough" but unreadable.
# 42 000 was a first guess and it bound too tightly: with it, a run shipped
# 61 090 chars against a 82 586-char sanity ceiling and lost coverage (12 pathways
# named against the workflow arm's 15) because the truncated tail took its
# citations with it. 56 000 leaves the report around 75 000 -- still inside the
# ceiling, with the paragraphs that carry the grounding.
STITCH_MAX_CHARS = int(os.getenv("AI_AGENT_STITCH_MAX_CHARS", "56000"))
# The LLM verify->correct loop's share of the clock. It is the single most
# expensive thing in a run once grounding works -- 291 s to check 19 citations,
# the same price the workflow arm pays for 20 -- and it is also the most
# interruptible: whatever it does not reach, verify_report_v2 and
# redact_unverified_v2 still handle deterministically. So it gets a slice, not
# a promise.
VERIFY_MAX_SECONDS = float(os.getenv("AI_AGENT_VERIFY_MAX_SECONDS", "300"))
# Hand the verifier its evidence instead of making it hunt for it.
# Measured: 9 of the 14 redactions in the best-grounded run so far were the
# Claim Verifier reporting "Max turns (6) exceeded" -- it spent its whole tool
# budget on search_paper_text round-trips and never returned a verdict, and a
# verifier that raises counts as a failure, so real citations were redacted for a
# tooling reason. The same warning appears in the workflow arm's logs.
#
# Finding the quote in the paper is mechanical: tools.py does it in pure Python.
# So the passage is extracted in code and pasted into the prompt, and the model
# is left with the one judgement only it can make -- does this text support this
# claim. No tools, one call, no turns to exhaust. The deterministic quote check
# in verify_report_v2 still runs afterwards either way.
# Default ON as of the measurement above: 29 of 29 calls returned a verdict at a
# median 2 464 ms, redactions fell 12 -> 2 (the survivors being the only two
# genuine refutations), the verify loop 291 s -> 117 s and the run 485 s -> 338 s.
# AI_AGENT_VERIFY_PREFETCH=0 restores the tool-loop verifier for comparison.
VERIFY_PREFETCH = os.getenv("AI_AGENT_VERIFY_PREFETCH", "1") == "1"
# How many abstract-only papers may be upgraded to full text before quoting.
# Measured: the workflow arm cites 13-14 full-text papers of ~21 (~65 %) because
# it batch-fetches full text for everything it retrieves; this arm cited 2-4 of
# 11-19 (~20 %) because it upgraded lazily, one paper per read_paper call. A
# quote has to be found VERBATIM in the paper, and a 250-word abstract rarely
# contains the sentence a specific claim needs -- so the citation arrives
# unquotable and the net strips it. That is most of the grounding gap.
FULLTEXT_MAX_PAPERS = int(os.getenv("AI_AGENT_FULLTEXT_MAX", "24"))
# Verify->correct rounds at the gate. 2 = one verification pass, one
# correction, one re-verification -- the 600 s budget does not fit the
# workflow arm's 3 (its own no-progress rule usually stops at 2 anyway).
VERIFY_ITERATIONS = min(int(os.getenv("AI_AGENT_VERIFY_ITERATIONS", "2")),
                        AI_MAX_VERIFICATION_ITERATIONS)

NUDGE_MIN_SECONDS = float(os.getenv("AI_AGENT_NUDGE_MIN", "90"))
"""Don't ask the agent to redo work there is no time to redo.

Measured over the archived runs, the gap after a submit_report -- the agent
rewriting a ten-thousand-character report -- runs a median 58 s and a mean 69 s.
A nudge with less than that left costs a minute of rewriting and delivers
nothing.

Measured against `hard_deadline`, which ALREADY has GATE_RESERVE_SECONDS taken
off it, so the exit gate is not part of this sum. The first version added the
gate reserve on top and set the bar at 210 s, which silently disabled the nudge
in the end-to-end test's 300 s budget -- both submits sailed through and the
suite caught it.
"""


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
    searched_tags: set = field(default_factory=set)     # topic_tags with a search
    tool_chars: int = 0
    pmid_to_ref: dict = field(default_factory=dict)
    next_ref: int = 1
    submitted_report: str = ""
    submit_attempts: int = 0                            # nudges are one-shot
    started_at: float = 0.0                             # loop start (wall clock)
    archived: list = field(default_factory=list)         # events already on disk
    hard_deadline: float = 0.0                          # loop must be done by
    delegation_cache: dict = field(default_factory=dict)  # resolved key -> report
    quotes: dict = field(default_factory=dict)          # ref_index -> verbatim quote
    flagged_citations: set = field(default_factory=set)   # unquotable at last check


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


def _trace_gate(ctx, tool, args_summary, result, started):
    """Archive a GATE-side LLM call (verification, quotes) as its own event.

    The toolbelt trace answers "which tools does the Lead use". It says nothing
    about the per-citation verifier, which is the most expensive LLM consumer in
    a run -- 291 s of a 597 s run, hedged calls timing out at 45 s and retrying,
    9 of 14 redactions caused by it exhausting its turns rather than refuting
    anything. Instrumentation that cannot see the biggest cost is not
    instrumentation.

    Marked `gate: True` and deliberately NOT counted in ctx.tool_calls, so the
    toolbelt numbers stay comparable across every round measured so far.
    """
    ctx.trace.append({
        "seq": len(ctx.trace) + 1,
        "t": round(time.time() - ctx.started_at, 1),
        "gate": True,
        "tool": tool,
        "args": str(args_summary)[:120],
        # The config stamp is the one event whose whole value IS its text; the
        # 160-char cap cut its JSON mid-string and made every run unparseable by
        # the analyzer that the stamp exists to feed.
        "result": (str(result) if tool == "__config__" else str(result)[:160]),
        "ms": int((time.time() - started) * 1000),
    })
    _archive_trace(ctx)


def _code_fingerprint():
    """A short hash of everything that decides how this agent behaves.

    The config stamp records tunable constants, which is what the early rounds
    varied. It cannot see a behaviour change: a delegation cache, a nudge, a
    reworded tool description all leave the constants identical, so two runs of
    genuinely different agents stamp the same line and get averaged together.

    Hashing the module source, the Lead's prompt and every tool description
    catches all of them without a hand-kept list that would drift out of date.
    It says "these runs are the same code", never what changed -- git does that.
    """
    try:
        import hashlib
        import inspect
        import sys as _sys
        parts = [inspect.getsource(_sys.modules[__name__]),
                 prompts_mod.SYSTEM_PROMPT_LEAD_AGENT]
        parts.extend(sorted(str(t.description or "") for t in TOOLBELT))
        return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()[:10]
    except Exception:
        logger.debug("code fingerprint failed", exc_info=True)
        return "unknown"


def _ledger_note(ctx):
    remaining = max(0, int(ctx.hard_deadline - time.time()))
    note = ("\n[budget: %d searches left · %d s left · %d/%d tool-output chars"
            % (max(0, SEARCH_BUDGET - ctx.searches_used), remaining,
               ctx.tool_chars, TOOL_CHAR_BUDGET))
    # Coverage, not just constraint. Measured: citations track searches at about
    # 0.64 each, and two replicates of the same agent searched 28 and 16 times --
    # so what limits grounding is how much of its own map the agent has looked
    # for literature on. Budget tells it what it MAY spend; this tells it what is
    # still unlit. It remains free to decide the answer is "nothing".
    if ctx.partition is not None:
        units = len(ctx.partition.get("clusters") or []) + len(
            ctx.partition.get("standalone") or [])
        if units:
            note += (" · literature searched for %d of %d clusters"
                     % (len(ctx.searched_tags), units))
    return note + "]"


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

def _assemble_without_synthesis(ctx):
    """The report a run can still produce when no model is reachable.

    Measured: a 504 from the gateway killed the loop, then killed the forced
    synthesis that exists to rescue it, and a run holding two delegated analyses,
    a notebook and retrieved papers shipped nothing. This assembles what was
    gathered -- no model, no network -- and says what it is at the top so no
    reader mistakes it for a finished interpretation.

    Returns "" when nothing was gathered, so the caller can fail honestly
    instead of shipping a stub.
    """
    pieces = ["# Interpretation (assembled without synthesis)",
              "",
              "*The language model became unavailable before this report could "
              "be written. What follows is the material the run had already "
              "gathered: the analyses its sub-agents completed, the findings it "
              "recorded, and the enrichment data itself. It has not been "
              "synthesised, and its citations have not been through the usual "
              "verification.*"]
    if ctx.notebook:
        pieces += ["", "## Findings recorded during the investigation", ""]
        pieces += ["- %s" % n for n in ctx.notebook]
    if ctx.delegated:
        pieces += ["", "## Pathway analyses", "", "\n\n".join(ctx.delegated)]
    report = "\n".join(pieces)
    return report if (ctx.notebook or ctx.delegated) else ""


def _verified_quotes(ctx, quotes):
    """Keep only quotes the gate's own matcher can find in their paper.

    Used on BOTH sides of the merge comparison. Filtering only the candidate
    compared a strict count against a lenient one, so the guard could not accept
    anything: one run reported 15 unverifiable quotes, rejected a stitch that was
    genuinely better, and shipped the thin draft instead. An asymmetric test is
    not a strict test, it is a broken one.
    """
    out = {}
    for ref, quote in (quotes or {}).items():
        paper = ctx.paper_index.get(ref) or {}
        text = " ".join((paper.get("sections") or {}).values()) or (
            paper.get("abstract") or "")
        # _fuzzy_contains(haystack, needle): is the QUOTE inside the PAPER.
        # These were reversed, asking whether a whole paper fits inside a
        # one-sentence quote, which is never true -- so every quote was judged
        # unverifiable, the merge saw 0 grounded on both sides, and the guard
        # lost the only signal it had. Round 29 reported quotes_unverifiable 11
        # of 11 with merge_grounded 0->0.
        if quote and text and _fuzzy_contains(text, quote):
            out[ref] = quote
    return out


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


def _tool_failure(name):
    """Make a raising tool visible instead of silently generic.

    The SDK catches any exception a tool raises and hands the model
    "An error occurred while running the tool", then carries on. Because _trace
    runs at the END of each tool, a raise also means no trace event at all -- so
    a tool that fails on every call looks, in the archive, exactly like a tool
    the agent chose not to use. Every adoption and cost figure measured so far
    counts successful calls only.

    This was not theoretical: the first version of the delegation-cache tests
    passed against a fixture that raised KeyError on every call, because the
    swallowed error came back as an ordinary string.

    The handler records the failure in the run journal (so it reaches the
    frontend activity feed and the trace archive) and tells the model what broke
    and not to repeat it unchanged.
    """
    def handler(ctx, error):
        c = getattr(ctx, "context", None)
        detail = "%s: %s" % (type(error).__name__, error)
        if c is not None:
            try:
                _trace(c, name, "(raised)", "ERROR " + detail, time.time())
            except Exception:
                logger.debug("failed to trace a tool failure", exc_info=True)
        logger.warning("[AGENT] tool %s raised: %s", name, detail, exc_info=True)
        return ("%s failed -- %s. This is a fault in the tool, not in what you "
                "asked for. Do not call it again with the same arguments; use "
                "another tool or carry on with what you have." % (name, detail))
    handler.tool_name = name
    return handler


@function_tool(failure_error_function=_tool_failure("get_experiment_overview"))
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


@function_tool(failure_error_function=_tool_failure("get_pathway_details"))
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


@function_tool(failure_error_function=_tool_failure("compare_gene_profiles"))
def compare_gene_profiles(ctx: RunContextWrapper[LoopContext],
                          gene_symbols: list[str]) -> str:
    """Measured values for one or several genes (max 10) across every omic layer, side by side. Instant and free -- pass every gene you are comparing in ONE call."""
    c = ctx.context
    t0 = time.time()
    out = _spend(c, tools_mod.execute_tool(
        "compare_genes", c.job_instance, {"gene_symbols": gene_symbols}))
    _trace(c, "compare_gene_profiles", gene_symbols, out[:60], t0)
    return out


@function_tool(failure_error_function=_tool_failure("cluster_pathways"))
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


@function_tool(failure_error_function=_tool_failure("search_literature"))
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
    if topic_tag:
        c.searched_tags.add(str(topic_tag).strip().lower())
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


@function_tool(failure_error_function=_tool_failure("read_paper"))
async def read_paper(ctx: RunContextWrapper[LoopContext], ref_index: int,
                     section: str) -> str:
    """Read one section (abstract, introduction, results, discussion, other) of a retrieved paper [N]. Fetches full text on first use, about 3 s. Use it to check a paper really says what you want to cite it for. Reading is for deciding, not for unlocking text: a paper you cite has its full text fetched anyway, and reading first does not by itself make a citation survive."""
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
    _trace(c, "read_paper",
           "[%s] %s pmid=%s" % (ref_index, section, paper.get("pmid")),
           "%d chars" % len(out), t0)
    return out


@function_tool(failure_error_function=_tool_failure("notebook_write"))
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


@function_tool(failure_error_function=_tool_failure("check_my_citations"))
def check_my_citations(ctx: RunContextWrapper[LoopContext], draft: str) -> str:
    """Check a draft's [N] citations BEFORE submitting: which resolve to real papers, and which have no supporting quote and will therefore be dropped. Costs a few seconds. Run it on your draft, fix what it names, then run it AGAIN -- the second run is what turns a flagged citation into a grounded one."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    valid = set(c.paper_index)
    # Check what will SHIP, not just what was typed here. The gate merges the
    # delegated analyses into the report, and measured over rounds 25-27 those
    # carried most of the citations: an agent submitted 11 citations it had
    # checked and grounded and the report went out with 6, because the merge
    # brought in citations this tool had never seen. Checking the draft alone is
    # checking the wrong artifact.
    delegated = "\n\n".join(c.delegated)
    text = normalize_citation_markers(draft)
    shipping = normalize_citation_markers(draft + "\n\n" + delegated) if delegated else text
    cited_draft = count_body_citations(text, valid)
    cited = count_body_citations(shipping, valid)
    text = shipping
    invalid = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)} - valid)

    # The real question. verify_report_v2 cannot answer it on a draft -- it reads
    # quotes out of a References section the draft does not have yet, so it
    # reported "0 failed" for every draft ever passed to it, in eight runs. What
    # decides whether a citation survives is whether a verbatim supporting
    # sentence exists in the paper, and _collect_cited_quotes answers exactly
    # that for ~3 s.
    quotes = {}
    try:
        quotes = dict(c.quotes)
        quotes.update(_collect_cited_quotes(
            LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER]), text, c.paper_index,
            c.job_id, known=quotes))
        c.quotes.update(quotes)
    except Exception as e:
        logger.warning("[%s][loop] pre-submit quote check failed: %s", c.job_id, e)
    unquotable = sorted(cited - set(quotes))

    lines = ["%d citation(s) will ship (%d in this draft, the rest in the "
             "delegated analyses the gate merges in); %d have a supporting quote."
             % (len(cited), len(cited_draft), len(quotes))]
    if invalid:
        lines.append("INVALID, no such paper -- remove these: %s"
                     % ", ".join("[%d]" % i for i in invalid[:15]))
    if unquotable:
        lines.append("NO SUPPORTING QUOTE FOUND, these will be removed from the "
                     "report along with the sentence carrying them: %s"
                     % ", ".join("[%d]" % i for i in unquotable[:15]))
        lines.append("Either cite a different paper for that claim, soften the "
                     "claim to what the paper does say, or read_paper first and "
                     "cite the sentence you find.")
    if not invalid and not unquotable:
        lines.append("Every citation resolves and is quotable.")
    # Remembered so submit_report can tell whether the agent acted on its own
    # check. Measured over 28 runs that called this tool: the 10 that re-checked
    # after a bad result improved every time (11/6 -> 7/0, 14/7 -> 8/0,
    # 10/4 -> 10/0), and none got worse. The 18 that checked once sometimes
    # submitted with citations this tool had already flagged.
    c.flagged_citations = set(unquotable)
    out = _spend(c, "\n".join(lines))
    _trace(c, "check_my_citations", "%d chars" % len(draft),
           "%d cited, %d unquotable" % (len(cited), len(unquotable)), t0)
    return out


async def _single_shot(agent, prompt, ctx, timeout, label):
    try:
        r = await bounded(Runner.run(agent, prompt, context=ctx, max_turns=2),
                          timeout, label=label)
        return str(r.final_output)
    except (Exception, asyncio.TimeoutError) as e:
        logger.warning("[%s][loop] %s failed: %s", ctx.job_id, label, e)
        return ""


def _clean_passage(raw):
    """Strip the search tool's framing so the writer sees only paper text.

    search_paper_text answers a human: "Found 3 passage(s) in paper [1]:
    --- Passage 1 --- ...". Handing that to a model as evidence invites it to
    quote the framing, and the gate then looks for that sentence in the paper
    and does not find it.
    """
    body = re.sub(r'^\s*Found\s+\d+\s+passage\(s\)[^:]*:', '', raw).strip()
    parts = [p.strip() for p in re.split(r'-{2,}\s*Passage\s*\d+\s*-{2,}', body)]
    parts = [p for p in parts if len(p) > 40]
    if not parts:
        return ""
    # Two passages is enough context to write from without burying the prompt.
    return "  ".join(parts[:2])[:600]


def _quote_shelf(c, chunk, papers):
    """Candidate supporting sentences, pulled BEFORE the sub-agent writes.

    The arm loses citations because it writes claims and then hunts for support.
    The shipped workflow arm does not have that problem: it writes each citation
    in the same call that holds the paper, so the quote is findable afterwards
    because the sentence was written from it.

    This inverts the sub-agent the same way. For each paper assigned to a chunk,
    pull the passages that match that chunk's pathways and genes and hand them to
    the writer as the evidence it may cite. search_paper_text is a 1 ms substring
    and keyword search -- no model, no gateway -- so a shelf for ten papers costs
    nothing measurable.
    """
    executor = tools_mod.build_verification_executor(c.paper_index)
    terms = [str(p.get("name") or "") for p in chunk if p.get("name")]
    for pathway in chunk:
        for gene in (pathway.get("top_genes") or [])[:4]:
            symbol = gene.get("symbol")
            if symbol:
                terms.append(str(symbol))
    shelf = {}
    for paper in papers:
        ref = paper.get("ref_index")
        if ref is None:
            continue
        for term in terms[:8]:
            try:
                passage = executor("search_paper_text",
                                   {"ref_index": ref, "query": term})
            except Exception:
                continue
            if passage and not passage.lower().startswith(("error", "no text",
                                                           "no match")):
                cleaned = _clean_passage(passage)
                if cleaned:
                    shelf[ref] = cleaned
                    break
    return shelf


@function_tool(failure_error_function=_tool_failure("delegate_interpretation"))
async def delegate_interpretation(ctx: RunContextWrapper[LoopContext],
                                  pathway_names: list[str], focus: str) -> str:
    """Delegate deep interpretation of up to ~20 named pathways to Cluster Interpreter sub-agents (parallel, single-shot). Returns their reports; their [N] citations use your reference numbers. EXPENSIVE: about 30 seconds per CALL regardless of how many pathways it covers -- the sub-agents run in parallel, four at a time -- so covering twenty pathways in one call costs what three would. It is where breadth comes from, and every pathway you delegate is somewhere a citation can be earned: make ONE call that covers everything, never one per pathway."""
    c = ctx.context
    t0 = time.time()
    guard = _time_guard(c)
    if guard:
        return guard
    wanted = {w.strip().lower() for w in pathway_names if w and w.strip()}
    chosen = [p for p in c.pathways
              if {str(p.get("name", "")).lower(), str(p.get("id", "")).lower()} & wanted
              or any(w in str(p.get("name", "")).lower() for w in wanted)
              ][:DELEGATE_MAX_PATHWAYS]
    if not chosen:
        out = "No enriched pathway matches %s." % pathway_names
        _trace(c, "delegate_interpretation", pathway_names, "no match", t0)
        return out
    # A delegation already run is not run again. Measured over 60 archived runs:
    # 7 of them re-issued an identical delegation, costing 25-62 s each (mean 40)
    # out of a 600 s budget, for an answer the run was already holding. That is
    # 99% of all wall clock this agent spends repeating itself -- every other
    # tool is cheap enough for a repeat not to matter.
    #
    # The key is the RESOLVED pathway set, not the argument spelling, so asking
    # for the same pathways by a different name still hits. A different focus is
    # a different question and runs.
    cache_key = (tuple(sorted(str(p.get("id")) for p in chosen)),
                 (focus or "").strip().lower())
    if cache_key in c.delegation_cache:
        cached = c.delegation_cache[cache_key]
        out = _spend(c, ("You have already delegated exactly these pathways with "
                         "this focus, and the analysis below is that same result "
                         "-- it was not run again, which just saved you about 30 "
                         "seconds. Do not request it a third time; spend the "
                         "budget on what is still uncovered.\n\n"
                         + cached + _ledger_note(c)))
        _trace(c, "delegate_interpretation",
               "%d pathways (cached)" % len(chosen), "cache hit", t0)
        return out

    papers = [c.paper_index[k] for k in sorted(c.paper_index)]
    # The loop's own interpreter: same model and settings as the workflow arm's
    # single-shot one, different instructions -- [N] markers on quotable claims
    # rather than "(PMID: X)" prose. Built here rather than in _build_agents so
    # the workflow arm keeps exactly the agents it was measured with.
    # REVERTED to the workflow arm's interpreter prompt, on evidence. Giving the
    # sub-agents their own instructions -- [N] markers, and "cite only where you
    # could point to a specific sentence" -- suppressed the citations the report
    # is built from: the merge went 5 -> 18 markers under the old prompt (round
    # 11) and 7 -> 10, then 7 -> 3, under the new one (rounds 13-15), until the
    # grounded-citation guard started rejecting the stitch outright for costing
    # grounding. Careful phrasing produced caution, not accuracy.
    #
    # The PMID format it asks for is fine now: resolve_pmid_mentions converts the
    # markers inside the merge, and the full-text upgrade was taught to count
    # PMID-form citations, which was the real defect behind that format.
    interpreter = Agent[LoopContext](
        name="Delegated Interpreter",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_INTERPRET,
        model_settings=ModelSettings(temperature=AI_TEMPERATURE),
        tools=[],
    )
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
            chunk_papers = _papers_for(chunk)
            t_shelf = time.time()
            shelf = _quote_shelf(c, chunk, chunk_papers)
            # Traced because an untraced step cannot be told apart from a step
            # that never ran, and round 26 was scored on exactly that mistake.
            _trace(c, "quote_shelf", "%d papers" % len(chunk_papers),
                   "%d passage(s)" % len(shelf), t_shelf)
            prompt = prompts_mod.build_batch_interpretation_prompt(
                chunk, chunk_papers, c.experiment_design, c.organism_name)
            if shelf:
                prompt += prompts_mod.build_evidence_shelf_block(shelf)
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
    # The sub-agents are told to write "(PMID: 12345)", not "[N]" -- that prompt
    # was reverted to the workflow arm's on evidence, and the markers are only
    # converted later, inside the merge. Convert here instead: the Lead then
    # reads the same citation form it must check, and the grounding step below
    # can see citations at all. Without this its guard is simply never true, and
    # round 26 measured a fix that had not run.
    out = resolve_pmid_mentions(out, c.paper_index)

    # Ground the sub-agents' citations NOW, while their papers are the ones in
    # hand -- and tell the Lead which ones cannot be grounded.
    #
    # Round 25 r2 is why. The agent submitted a 7 726-character draft carrying 7
    # citations, every one checked with check_my_citations and grounded. The gate
    # then merged in 52 000 characters of this delegated text, carrying citations
    # the agent had never checked, could not find quotes for them in the time it
    # had left, and redacted all of them: a 64 830-character report shipped with
    # ZERO citations. check_my_citations was validating the draft while the gate
    # shipped draft + merge.
    #
    # Collection is a thread pool of 8, so ~20 citations cost about 5 s. The
    # quotes are cached on the context and reused by the gate, which is the part
    # that stops the collapse; the message back is what lets the Lead act.
    ungrounded = []
    if out and "[" in out:
        t_q = time.time()
        try:
            fresh = await bounded(
                asyncio.to_thread(_collect_cited_quotes,
                                  LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER]), out,
                                  c.paper_index, c.job_id, c.quotes),
                DELEGATE_QUOTE_SECONDS, label="delegate quote grounding")
            c.quotes.update(fresh or {})
        except (Exception, asyncio.TimeoutError) as exc:
            logger.warning("[%s][loop] delegated-citation grounding failed: %s",
                           c.job_id, exc)
        cited_here = {int(n) for n in re.findall(r"\[(\d+)\]", out)} & set(c.paper_index)
        ungrounded = sorted(cited_here - set(c.quotes))
        _trace(c, "delegate_grounding",
               "%d cited" % len(cited_here),
               "%d grounded, %d not (%.1fs)"
               % (len(cited_here) - len(ungrounded), len(ungrounded), time.time() - t_q),
               t_q)
    if ungrounded:
        out += ("\n\n[grounding] %d citation(s) in this analysis have no verifiable "
                "quote yet: %s. The gate deletes each one along with its sentence, "
                "so read_paper on them, or drop them from what you keep."
                % (len(ungrounded), ", ".join("[%d]" % i for i in ungrounded[:12])))
    # Cached for the run, and deliberately NOT re-appended to c.delegated on a
    # hit: the gate stitches from that list, and a duplicated interpretation
    # would both pad the merge toward STITCH_MAX_CHARS and let the same claim be
    # counted twice when the stitch is compared with the draft.
    c.delegation_cache[cache_key] = out
    out = _spend(c, out + _ledger_note(c))
    _trace(c, "delegate_interpretation",
           "%d pathways / %d chunks" % (len(chosen), len(chunks)),
           "%d chars" % len(out), t0)
    return out


@function_tool(failure_error_function=_tool_failure("submit_report"))
def submit_report(ctx: RunContextWrapper[LoopContext], report_markdown: str) -> str:
    """Submit your final report (markdown, [N] citations). The only way to finish. It goes to the mandatory verification gate, never straight to the user."""
    c = ctx.context
    t0 = time.time()
    c.submit_attempts += 1
    # One nudge, never a veto. Measured: two replicates of the same code differed
    # by a factor of five in prose and 15 vs 9 pathways named, and the difference
    # was that one of them never called delegate_interpretation -- so nothing was
    # stitched and the report covered a fraction of the experiment. Delegation is
    # the behaviour the whole report rests on and it is entirely optional, which
    # is fine as a choice and expensive as an oversight. So the first submit that
    # arrives thin and undelegated says so; the second goes through regardless,
    # because a tool that can refuse twice is a workflow step wearing a tool's
    # clothes.
    time_to_act = c.hard_deadline - time.time()
    if (c.submit_attempts == 1 and not c.delegated
            and len(report_markdown.strip()) < 9000
            and time_to_act > NUDGE_MIN_SECONDS):
        out = ("NOT SUBMITTED YET (this is the only time you will be asked). You "
               "have not delegated any pathway analysis, and %d characters cannot "
               "cover %d enriched pathways -- the per-pathway detail is what makes "
               "a report usable. Call delegate_interpretation over the top "
               "clusters (two calls cover everything, ~30 s each), then submit "
               "again. If you have a considered reason to submit as it stands, "
               "call submit_report again now and it will be accepted."
               % (len(report_markdown.strip()), len(c.pathways)))
        _trace(c, "submit_report", "%d chars, no delegation"
               % len(report_markdown.strip()), "nudged once", t0)
        return out
    if len(report_markdown.strip()) < 500:
        out = ("REJECTED: that is not a report (%d chars). Write the full "
               "analysis: Key Findings, Cross-Pathway Themes, Detailed Pathway "
               "Analysis, Suggested Follow-up Experiments, Limitations."
               % len(report_markdown.strip()))
        _trace(c, "submit_report", "%d chars" % len(report_markdown), "rejected", t0)
        return out
    # The same one-shot nudge, for the other thing the agent already knows is
    # wrong. check_my_citations names the citations with no supporting quote and
    # says what to do about them; when the agent re-checks it fixes them every
    # time (10 of 10 runs improved, none got worse). When it submits anyway,
    # those citations become redactions and take their sentences with them.
    #
    # Only ever one nudge per run, shared with the delegation nudge above: the
    # first submit may be answered once, the second is always accepted. A tool
    # that can refuse twice is a workflow step wearing a tool's clothes.
    still_flagged = sorted(i for i in c.flagged_citations
                           if ("[%d]" % i) in report_markdown)
    if (c.submit_attempts == 1 and still_flagged
            and time_to_act > NUDGE_MIN_SECONDS):
        out = ("NOT SUBMITTED YET (this is the only time you will be asked). "
               "Your own check_my_citations run found no supporting quote for "
               "%s, and they are still in this draft -- the gate will delete "
               "each one along with the sentence carrying it. Fix them the way "
               "that tool suggested (cite another paper, soften the claim, or "
               "read_paper and quote what you find), then submit. If you have a "
               "considered reason to submit as it stands, call submit_report "
               "again now and it will be accepted."
               % ", ".join("[%d]" % i for i in still_flagged[:10]))
        _trace(c, "submit_report", "%d chars, %d flagged citations"
               % (len(report_markdown.strip()), len(still_flagged)),
               "nudged once", t0)
        return out
    c.submitted_report = report_markdown
    _trace(c, "submit_report", "%d chars" % len(report_markdown), "accepted", t0)
    return "SUBMITTED. Reply with the single word DONE and stop."


# Eleven, not thirteen: get_gene_profile was compare_gene_profiles with one
# argument, and notebook_read re-read what the SDK already keeps in context.
# Every tool here costs its schema in EVERY Decide turn, so an unused tool is a
# tax on the prompt that carries the whole investigation.
# Ten. delegate_literature went uncalled in all 17 archived runs -- the Lead
# writes its own queries and search_literature covers the same ground -- and a
# declared tool is not free: its schema rides in every Decide turn of every run.
TOOLBELT = [get_experiment_overview, get_pathway_details, compare_gene_profiles,
            cluster_pathways, search_literature, read_paper, notebook_write,
            check_my_citations, delegate_interpretation, submit_report]


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

    # Stamp the configuration into the run's own trace. Every analysis so far has
    # depended on me remembering which round carried which knobs -- and one of
    # them (the delegated-interpreter prompt) took three rounds to convict
    # because its effect was mixed with two other changes. A run that cannot say
    # what it was is a measurement waiting to be misattributed.
    _trace_gate(ctx, "__config__", "run start", json.dumps({
        # First, so it survives any truncation downstream: two runs share a
        # fingerprint exactly when they are the same agent.
        "code": _code_fingerprint(),
        "merge_mode": MERGE_MODE,
        "verify_prefetch": VERIFY_PREFETCH,
        "stitch_max": STITCH_MAX_CHARS,
        "search_budget": SEARCH_BUDGET,
        "search_hits": SEARCH_HITS,
        "delegate_papers": DELEGATE_PAPERS,
        "max_turns": AGENT_MAX_TURNS,
        "gate_reserve": GATE_RESERVE_SECONDS,
        "lead_prompt_chars": len(prompts_mod.SYSTEM_PROMPT_LEAD_AGENT),
        "tools": len(TOOLBELT),
        # Synthetic runs must be separable from real ones. The end-to-end test
        # drives a scripted agent against a stand-in gateway with a 2-search
        # budget, and two of those had already landed in the tool-adoption
        # tables as if a model had chosen those calls.
        "label": os.getenv("AI_AGENT_RUN_LABEL", "live"),
    }), time.time())

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
            # Last resort, and it calls no model at all. The forced synthesis
            # above needs the same gateway that just failed -- measured: a 504
            # from the gateway killed the loop, then killed the synthesis, and a
            # run that had already delegated two interpretations, kept a
            # notebook and retrieved papers shipped NOTHING. Material that has
            # been gathered should not be lost to the thing that stopped the
            # gathering.
            stats["deterministic_fallback"] = "%s: %s" % (type(e).__name__, e)
            logger.warning("[%s][loop] synthesis unavailable (%s); assembling "
                           "the report from gathered material without a model",
                           job_id, e)
            report = _assemble_without_synthesis(ctx)
            if not report.strip():
                raise RuntimeError(
                    "The agent produced no report and had nothing gathered to "
                    "fall back on (loop: %s; synthesis: %s)"
                    % (stats.get("loop_backstop", "ended"), e))

    # ---- carry the delegated detail into the report ------------------------
    # Round 4 merged by RE-AUTHORING: one Report Writer pass over the draft plus
    # every delegated report, with the full master reference list attached. It
    # fixed length (8 870 -> 38 480 chars) and coverage (9 -> 18.5 pathways) and
    # wrecked grounding -- citations fell to 4.5, and round 6 showed why: a writer
    # handed ninety references cites three of them. agent.py records the same
    # effect for its batches ("a batch handed 20+ abstracts cites fewer of them").
    #
    # The delegated reports are ALREADY grounded: each was written against the <=10
    # papers attributed to its own pathways. So do not re-author them. Stitch them
    # in as the per-pathway analysis and spend the single writer call only on the
    # framing prose, where reference dilution costs nothing. That is the workflow
    # arm's grounding property -- per-batch attributed slices, preserved through
    # synthesis -- without its fixed control flow: the agent still chose what to
    # investigate, what to delegate and what to submit.
    # ---- give the citations something to be quoted FROM --------------------
    # Deterministic, batched, and placed before the merge guard so both its quote
    # probe and the gate's collection see the fuller text. Bounded by the clock
    # like every other post-loop step, and skipped without ceremony when tight.
    # Count BOTH citation forms. The delegated reports cite by PMID -- their
    # instructions (SYSTEM_PROMPT_INTERPRET) say "(PMID: XXXXXXXX)" -- and those
    # only become [N] markers when resolve_pmid_mentions runs inside the merge,
    # which is after this step. Counting markers alone saw 5 citations where the
    # run actually had 18, so this step found "0 thin" every time and quietly did
    # nothing: the diagnostic said "5 cited, 0 thin" and that number was the bug.
    cited_anywhere = set()
    for text in ctx.delegated + [report]:
        text = text or ""
        cited_anywhere |= {int(n) for n in re.findall(r"\[(\d+)\]", text)}
        for pmid in re.findall(r"PMID:?\s*(\d{6,9})", text):
            ref = ctx.pmid_to_ref.get(str(pmid))
            if ref:
                cited_anywhere.add(ref)
    thin = [ctx.paper_index[r] for r in sorted(cited_anywhere)
            if r in ctx.paper_index
            and ctx.paper_index[r].get("fetch_tier") == "abstract_only"]
    fulltext_budget = ((ctx.started_at + AGENT_RUN_SECONDS) - time.time()
                       - GATE_MIN_SECONDS - 60)
    # Always recorded, including the zero case. The first run with this step
    # showed no upgrade stat at all and left me inferring why from stored
    # documents -- a branch that says nothing when it does nothing is a branch
    # you cannot debug.
    stats["fulltext_candidates"] = "%d cited, %d thin, %ds budget" % (
        len(cited_anywhere), len(thin), max(0, int(fulltext_budget)))
    if thin and fulltext_budget > 20:
        t_f = time.time()
        try:
            upgraded = await bounded(
                asyncio.to_thread(ctx.pubmed.fetch_papers,
                                  [p["pmid"] for p in thin[:FULLTEXT_MAX_PAPERS]]),
                min(fulltext_budget, 90), label="full-text upgrade")
            by_pmid = {str(p.get("pmid")): p for p in (upgraded or [])}
            gained = 0
            for paper in thin[:FULLTEXT_MAX_PAPERS]:
                fresh = by_pmid.get(str(paper.get("pmid")))
                if fresh and fresh.get("fetch_tier") != "abstract_only":
                    fresh["ref_index"] = paper["ref_index"]
                    fresh["pathways"] = paper.get("pathways", [])
                    ctx.paper_index[paper["ref_index"]] = fresh
                    gained += 1
            stats["fulltext_upgraded"] = "%d of %d cited abstracts" % (gained,
                                                                      len(thin))
        except (Exception, asyncio.TimeoutError) as e:
            stats["fulltext_failed"] = "%s: %s" % (type(e).__name__, e)
        stats["fulltext_s"] = time.time() - t_f
    elif thin:
        stats["fulltext_skipped"] = "%d thin papers, %ds left" % (
            len(thin), max(0, int(fulltext_budget)))

    premade_quotes = None
    merge_budget = ((ctx.started_at + AGENT_RUN_SECONDS) - time.time()
                    - GATE_MIN_SECONDS)
    if ctx.delegated and MERGE_DELEGATED and merge_budget < 30:
        stats["merge_skipped"] = ("%ds left, the gate needs %ds"
                                  % (max(0, int(merge_budget + GATE_MIN_SECONDS)),
                                     int(GATE_MIN_SECONDS)))
        logger.info("[%s][loop] skipping the merge: %s", job_id,
                    stats["merge_skipped"])
    elif ctx.delegated and MERGE_DELEGATED:
        t_m = time.time()
        merge_timeout = min(SDK_LONG_CALL_TIMEOUT, merge_budget)
        papers_now = [ctx.paper_index[k] for k in sorted(ctx.paper_index)]
        valid = {p["ref_index"] for p in papers_now}
        before = len(count_body_citations(str(report), valid))
        detail = "\n\n".join(ctx.delegated)
        if len(detail) > STITCH_MAX_CHARS:
            # Delegations arrive in rank order, so truncating the tail drops the
            # lowest-ranked pathways' paragraphs -- the ones the report can most
            # afford to lose -- and says so rather than trailing off mid-sentence.
            detail = (detail[:STITCH_MAX_CHARS].rsplit("\n\n", 1)[0]
                      + "\n\n*(Lower-ranked pathways are listed in the tables "
                        "below; their per-pathway analysis was trimmed to keep "
                        "this report readable.)*")
            stats["stitch_truncated"] = True
        if MERGE_MODE == "stitch":
            framing_prompt = (
                "You are finishing a multi-omics interpretation report.\n\n"
                "## The lead interpreter's draft\n%s\n\n"
                "## The per-pathway analyses that will follow it verbatim\n%s\n\n"
                "## Task\nWrite ONLY these sections, in this order, as markdown:\n"
                "## Key Findings (3-5 bullets, the most important results across "
                "everything above)\n"
                "## Cross-Pathway Themes (shared mechanisms and crosstalk; name "
                "the pathways)\n\n"
                "Then stop -- do NOT write a pathway-by-pathway section, it is "
                "already written and will be appended after yours. Afterwards add:\n"
                "## Suggested Follow-up Experiments (3-5, prioritised, each with "
                "technique, rationale, expected outcome)\n"
                "## Limitations and Caveats\n\n"
                "Reuse [N] citation markers ONLY where they already appear above "
                "for that claim. Do not invent markers and do not renumber."
                % (report, detail[:60000]))
            try:
                framed = await bounded(
                    Runner.run(agents["synth"], framing_prompt, context=ctx,
                               max_turns=3),
                    merge_timeout, label="framing")
                framing = str(framed.final_output)
            except (Exception, asyncio.TimeoutError) as e:
                stats["framing_failed"] = "%s: %s" % (type(e).__name__, e)
                framing = report
            # Splice: framing's forward-looking sections stay last, the stitched
            # per-pathway detail goes between themes and follow-ups.
            marker = "## Suggested Follow-up Experiments"
            if marker in framing:
                head, tail = framing.split(marker, 1)
                candidate = "%s\n## Detailed Pathway Analysis\n\n%s\n\n%s%s" % (
                    head.rstrip(), detail, marker, tail)
            else:
                candidate = "%s\n\n## Detailed Pathway Analysis\n\n%s" % (
                    framing.rstrip(), detail)
            candidate = resolve_pmid_mentions(candidate, ctx.paper_index)
        else:
            prompt = prompts_mod.build_synthesis_prompt_v2(
                ctx.delegated + ["## The lead interpreter's own draft\n" + report],
                experiment_design, organism_name, papers_now)
            prompt += ("\n\nThe last block is the lead interpreter's draft: keep "
                       "its structure, its Key Findings and its judgements, and "
                       "restore the per-pathway detail from the batch reports that "
                       "the draft compressed away. Every pathway named in any block "
                       "gets its own paragraph. Do not invent citations.")
            try:
                merged = await bounded(
                    Runner.run(agents["synth"], prompt, context=ctx, max_turns=3),
                    merge_timeout, label="delegated merge")
                candidate = resolve_pmid_mentions(str(merged.final_output),
                                                  ctx.paper_index)
            except (Exception, asyncio.TimeoutError) as e:
                stats["merge_failed"] = "%s: %s" % (type(e).__name__, e)
                candidate = report
        after = len(count_body_citations(candidate, valid))
        # Count GROUNDED citations, not markers. The first version of this guard
        # compared raw [N] counts, and a stitch that added thirty markers passed
        # it -- then the deterministic net removed them all for having no quote:
        # one run reported 22 verifier calls, 5 refutations, and 32 redactions,
        # which is arithmetic that only works if two thirds of the citations were
        # never quote-backed at all. A citation without a quote is not grounding,
        # it is a number in brackets.
        #
        # Quote collection costs ~3 s (measured), so the guard can afford to ask
        # the real question, and the quotes it collects are reused by the gate
        # rather than recomputed.
        quote_probe = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER])
        # Both sides through the same sieve: a model reporting support is not the
        # same fact as the support being there, and the gate checks the second.
        #
        # Bounded, because these were the last unbounded work left in the run.
        # _collect_cited_quotes makes one LLM call per cited paper and the guard
        # runs it twice; with twenty papers on a slow gateway that is minutes,
        # and it sat OUTSIDE merge_timeout, which bounds only the writer call.
        # A run died at 601 s of a 600 s ceiling here. Every step after the loop
        # now answers to the clock, without exception.
        probe_budget = max(20.0, min(merge_timeout,
                                     (ctx.started_at + AGENT_RUN_SECONDS)
                                     - time.time() - GATE_MIN_SECONDS))
        try:
            before_quotes = _verified_quotes(ctx, await bounded(
                asyncio.to_thread(_collect_cited_quotes, quote_probe,
                                  str(report), ctx.paper_index, job_id),
                probe_budget / 2, label="quote probe (draft)"))
            raw_after = await bounded(
                asyncio.to_thread(_collect_cited_quotes, quote_probe,
                                  candidate, ctx.paper_index, job_id),
                probe_budget / 2, label="quote probe (candidate)")
        except (Exception, asyncio.TimeoutError) as e:
            # No probe, no informed judgement: keep the draft rather than accept
            # a stitch whose grounding could not be checked.
            stats["merge_probe_failed"] = "%s: %s" % (type(e).__name__, e)
            stats["merge_s"] = time.time() - t_m
            before_quotes, raw_after, candidate = {}, {}, str(report)
        grounded_after_quotes = _verified_quotes(ctx, raw_after)
        stats["quotes_unverifiable"] = len(raw_after) - len(grounded_after_quotes)
        grounded_before = len(before_quotes)
        grounded_after = len(grounded_after_quotes)
        if (len(candidate) > 1.2 * len(str(report))
                and after >= before and grounded_after >= grounded_before):
            stats["merge_gain_chars"] = len(candidate) - len(str(report))
            stats["merge_citations"] = "%d->%d" % (before, after)
            stats["merge_grounded"] = "%d->%d" % (grounded_before, grounded_after)
            # Strip the citations we already know have no quote. The guard
            # accepts a stitch when grounded citations RISE, so it can pass a
            # batch that adds ten grounded markers and eleven unquotable ones --
            # measured: one run had 33 verifier calls, 4 refutations and 15
            # redactions, the other 11 coming from the net removing citations
            # with no quote at all, and redaction takes the whole SENTENCE with
            # them. The claim usually came from the data, not the paper; the
            # citation was the decoration. So drop the decoration here and let
            # the sentence stand, rather than let the gate delete both.
            keep = set(grounded_after_quotes)
            def _strip(match):
                return "" if int(match.group(1)) not in keep else match.group(0)
            trimmed = re.sub(r"\s*\[(\d+)\]", _strip, candidate)
            dropped = (len(count_body_citations(candidate, valid))
                       - len(count_body_citations(trimmed, valid)))
            if dropped:
                stats["unquotable_markers_dropped"] = dropped
            report = trimmed
            premade_quotes = grounded_after_quotes
        else:
            stats["merge_rejected"] = (
                "len %d->%d, cites %d->%d, GROUNDED %d->%d"
                % (len(str(report)), len(candidate), before, after,
                   grounded_before, grounded_after))
        stats["merge_mode"] = MERGE_MODE
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
    t_q = time.time()
    if premade_quotes is not None:
        # The merge guard already collected these for the text it accepted.
        quotes = dict(ctx.quotes)
        quotes.update(premade_quotes)
        stats["quotes_reused"] = len(quotes)
    else:
        # Seeded with whatever delegation already grounded: those citations were
        # quoted while the sub-agent's own papers were in hand, and re-deriving
        # them here, against a merged report and a shrinking clock, is what left
        # round 25's second replicate with no citations at all.
        quotes = dict(ctx.quotes)
        stats["quotes_from_delegation"] = len(quotes)
        quotes.update(_collect_cited_quotes(llm_for_quotes, report,
                                            ctx.paper_index, job_id, known=quotes))
    stats["quotes_s"] = time.time() - t_q
    report, rendered = render_references_section(report, ctx.paper_index, quotes)
    stats["refs_rendered"] = len(rendered)
    stats["quotes_supplied"] = len(quotes)

    _hb(ctx, "verifying", 85, "Verifying citations...")
    # Same instructions as agents["verify"], no tools: with the passage in the
    # prompt there is nothing to look up, and nothing to run out of turns on.
    verifier_solo = Agent[LoopContext](
        name="Claim Verifier (prefetched)",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_VERIFICATION,
        model_settings=ModelSettings(temperature=0.1),
        tools=[],
    )
    t0 = time.time()
    verify_deadline = min(t0 + VERIFY_MAX_SECONDS,
                          ctx.started_at + AGENT_RUN_SECONDS - 45)
    previous_failures = None
    for _iteration in range(VERIFY_ITERATIONS):
        if time.time() > verify_deadline:
            stats["verify_cut_short"] = _iteration
            logger.info("[%s][loop] verification out of clock after %d round(s); "
                        "the programmatic net takes the rest", job_id, _iteration)
            break
        citations = parse_references_section(report)
        to_verify = [c for c in citations if c.get("cited_text")]
        if not to_verify:
            break
        vsem = asyncio.Semaphore(SDK_VERIFY_CONCURRENCY)

        async def _verify_one_prefetched(cit):
            """One short call, with the paper's own words already in the prompt."""
            async with vsem:
                executor = tools_mod.build_verification_executor(ctx.paper_index)
                passage = ""
                try:
                    passage = executor("search_paper_text",
                                       {"ref_index": cit["ref_index"],
                                        "query": (cit["cited_text"] or "")[:180]})
                    if not passage or passage.lower().startswith("error"):
                        passage = executor("fetch_paper_section",
                                           {"ref_index": cit["ref_index"],
                                            "section": "abstract"})
                except Exception as e:
                    passage = "(the paper's text could not be searched: %s)" % e
                prompt = (prompts_mod.build_verification_prompt(
                              cit["claim_sentence"], cit["cited_text"],
                              cit["ref_index"])
                          + "\n\n## What paper [%s] actually says, retrieved for "
                            "you\n%s\n\nJudge from the text above. Do not ask for "
                            "more; if the quote is not in it, say so."
                          % (cit["ref_index"], passage[:6000]))
                try:
                    r = await bounded(
                        Runner.run(verifier_solo, prompt, context=ctx, max_turns=2),
                        SDK_CALL_TIMEOUT, label="verify[%s]" % cit["ref_index"])
                    return cit, str(r.final_output)
                except Exception as e:
                    logger.warning("[%s][loop] prefetched verifier failed for "
                                   "[%s]: %s", job_id, cit["ref_index"], e)
                    return cit, ""

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

        checker = _verify_one_prefetched if VERIFY_PREFETCH else _verify_one

        async def _timed(cit):
            started = time.time()
            cit, text = await checker(cit)
            verdict = _parse_json_verdict(text) if text else None
            _trace_gate(ctx, "verify_citation" + ("_prefetched" if VERIFY_PREFETCH
                                                  else "_toolloop"),
                        "[%s]" % cit["ref_index"],
                        "no verdict (raised or empty)" if verdict is None else
                        "match=%s supports=%s" % (verdict.get("text_match"),
                                                  verdict.get("supports_claim")),
                        started)
            return cit, text

        # Hard-bound the fan-out itself, not just the decision to start another
        # round. A deadline checked at the top of the loop bounds nothing: one
        # round over nineteen citations, each hedged at 45 s x2 across eight
        # workers, ran a run to 602 s and it died on the ceiling with a finished
        # report it never got to ship.
        #
        # Whatever does not finish in time counts as unverified, which is exactly
        # what verify_report_v2 and redact_unverified_v2 handle deterministically
        # a few lines below. Stopping early costs a redaction; overrunning costs
        # the entire interpretation.
        budget = max(20.0, verify_deadline - time.time())
        tasks = [asyncio.ensure_future(_timed(c)) for c in to_verify]
        done, pending = await asyncio.wait(tasks, timeout=budget)
        for task in pending:
            task.cancel()
        if pending:
            stats["verify_unchecked"] = (stats.get("verify_unchecked", 0)
                                         + len(pending))
            logger.info("[%s][loop] %d of %d citations unchecked when the clock "
                        "ran out; the programmatic net takes them", job_id,
                        len(pending), len(to_verify))
        verdicts = []
        for task in done:
            try:
                verdicts.append(task.result())
            except Exception:
                continue
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
    # The TRUE retrieval count, into stats so it reaches the stored record and
    # the scorer. It was stamped only into the outcome trace before, so the
    # scorer kept falling back to len(papers) -- the reference list the gate had
    # already filtered -- and reported 9 for a run that retrieved 68.
    stats["papers_retrieved"] = len(ctx.paper_index)
    stats["verification"] = final
    # Stamp the outcome next to the tool calls that produced it. Mongo keeps one
    # interpretation per JOB, so it can answer "how did this job's last run go"
    # and nothing else -- an association between a tool and the report it helped
    # produce came out at n=1 because two jobs were reused for forty runs. The
    # archive now closes that loop: configuration at the start, tool calls in the
    # middle, outcome at the end, one self-contained file per run.
    try:
        body = str(report).split("### References")[0]
        _trace_gate(ctx, "__outcome__", "run end", json.dumps({
            "prose_chars": len(body),
            "citations": len(count_body_citations(
                body, {p["ref_index"] for p in unique_papers})),
            "redacted": final.get("redacted_count", 0),
            "papers": len(unique_papers),
            # unique_papers is filtered to the SURVIVING references above -- but
            # only when citation_mapping is non-empty. A run that keeps its
            # citations therefore reports a small number and a run that loses
            # every one reports the full retrieval, so the metric reads
            # backwards exactly when it matters. The index is the truth.
            "papers_retrieved": len(ctx.paper_index),
            "full_text_papers": sum(1 for p in unique_papers
                                    if p.get("full_text_available")),
            "seconds": round(time.time() - ctx.started_at, 1),
        }), time.time())
    except Exception as exc:                      # never lose a finished report
        # This is measurement, and it sits on the return path of a run that has
        # already spent its ten minutes. Nothing it can hit -- a paper without a
        # ref_index, a report that is not a string -- is worth discarding the
        # interpretation for. Log and hand back the report.
        logging.warning("[AGENT] outcome stamp failed: %s", exc)
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
