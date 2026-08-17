"""The AI interpretation agent workflow, built on the OpenAI Agents SDK.

This is the production entry point for AI interpretation: the SDK's ``Runner``
drives the agent loop and tool round-trips, and structured phases declare a
pydantic ``output_type`` instead of parsing free text. Everything that is not
orchestration lives in sibling modules and is shared by import:

  * prompts (``prompts.py``), tool bodies (``tools.py``)
  * literature retrieval (``pubmed_client.py``)
  * context builders (``context_builder.py``)
  * cross-pipeline helpers (``shared.py``)
  * budgets from ``serverconf.py``

The SDK is async-first while PaintOmics runs on PySiQ's threads, so the public
entry points stay synchronous and own their own event loop:

  * ``run_ai_agent(job_id, experiment_design, RESPONSE)`` -- servlet-facing
    adapter (DAO progress, persistence, cancellation, concurrency semaphore).
  * ``run_agent_workflow(job_instance, job_id, experiment_design)`` -- the bare
    workflow, also used by the AgentEvolve replay harness (``--arm sdk``).
"""
import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from agents import (
    Agent, ModelSettings, OpenAIChatCompletionsModel, RunContextWrapper, Runner,
    function_tool, set_default_openai_api, set_default_openai_client,
    set_tracing_disabled,
)
import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, Field

from src.conf.serverconf import (
    AI_LLM_PROVIDER, AI_PROVIDERS, AI_MAX_PATHWAYS, AI_PATHWAYS_PER_BATCH,
    AI_TEMPERATURE, AI_MAX_SEARCH_TASKS, AI_PAPERS_PER_SEARCH_TASK,
    AI_PAPERS_KEPT_PER_TASK, AI_SEARCH_SUBAGENT_WORKERS,
    AI_VERIFICATION_WORKERS, AI_MAX_VERIFICATION_ITERATIONS,
)
from src.classes.AIInterpret import tools as tools_mod
from src.classes.AIInterpret import prompts as prompts_mod
from src.classes.AIInterpret.context_builder import (
    build_pathway_context, build_gene_symbol_whitelist, get_organism_name,
    triage_pathways, build_cross_omic_matrix, build_key_regulators_block,
    render_pathway_table,
)
from src.classes.AIInterpret.pubmed_client import PubMedClient
from src.classes.AIInterpret.verification import (
    verify_report_v2, redact_unverified_v2, renumber_citations,
    sort_references_section,
    parse_references_section, render_references_section,
    normalize_citation_markers, resolve_pmid_mentions, count_body_citations,
)
# The shared verdict parser: the verifier agent keeps its tools (see the
# DANGER note in _build_agents), so its verdict arrives as free text.
from src.classes.AIInterpret.shared import (
    _parse_json_verdict, _collect_cited_quotes,
    _build_local_paper_index, _remap_citation_indices, _shared_gene_core,
)
from src.classes.AIInterpret.llm_client import LLMClient
# Cluster-first interpretation (AI_CLUSTER_MODE=1): the shared-feature
# pathway network is partitioned and every significant pathway is interpreted
# inside its cluster. Off by default so the base arm stays reproducible.
from src.classes.AIInterpret import clusters as clusters_mod

logger = logging.getLogger(__name__)

# How many pathways one cluster-mode interpretation batch may hold (units are
# never split; a bigger cluster travels alone) and how many batches run at
# once. Cluster mode has ~5x the batches of the top-15 path, so it needs a
# bound the three-batch path never did.
CLUSTER_BATCH_MAX = int(os.getenv("AI_CLUSTER_BATCH_MAX", "8"))
CLUSTER_CONCURRENCY = int(os.getenv("AI_CLUSTER_CONCURRENCY", "6"))
# Two tiers of interpretation in cluster mode. A unit that carries a top-N
# (by p-value) pathway gets the full tool-loop interpreter, capped at
# CLUSTER_INTERPRET_TURNS; every other unit gets one single-shot
# call from the same instructions without tools. Measured: a full-protocol
# cluster run at 8 turns x 14 batches blew a 600 s cap on the gateway, where
# parallel tool loops serialise; single-shot calls parallelise.
CLUSTER_INTERPRET_TURNS = int(os.getenv("AI_CLUSTER_INTERPRET_TURNS", "5"))
# AI_CLUSTER_TOOLS=0 makes every cluster batch single-shot (no data tools) --
# the cheap mode for gateways whose tool loops crawl, and the mode a
# qualitative smoke can run on a backend that never finishes a tool loop.
CLUSTER_TOOLS = os.getenv("AI_CLUSTER_TOOLS", "1") == "1"

# Tuning knobs for the SDK arm. Separate from the shared AI_* settings so
# sweeping this workflow keeps its behaviour stable mid-comparison.
SDK_VERIFY_CONCURRENCY = int(os.getenv("AI_SDK_VERIFY_CONCURRENCY", "8"))
SDK_SEARCH_CONCURRENCY = int(os.getenv("AI_SDK_SEARCH_CONCURRENCY",
                                        str(AI_SEARCH_SUBAGENT_WORKERS)))
# Search every triaged pathway rather than only the planner's task list: PubMed
# retrieval is 6-10s of a 300s budget, so breadth here is nearly free, and
# citations are the metric we are short on.
SDK_SEARCH_ALL_PATHWAYS = os.getenv("AI_SDK_SEARCH_ALL_PATHWAYS", "1") == "1"
# Ceiling on the total search-task list once per-pathway backfill is added
# (planner tasks + up to three angles per uncovered pathway). Unbounded, a
# 40-pathway triage would issue 120+ PubMed queries and their screening calls.
SDK_BACKFILL_MAX_TASKS = int(os.getenv("AI_SDK_BACKFILL_MAX_TASKS", "45"))
# Papers shown to one interpretation batch. More retrieved literature is good;
# more literature *per prompt* is not -- see the cap in _one_batch.
SDK_PAPERS_PER_BATCH = int(os.getenv("AI_SDK_PAPERS_PER_BATCH", "10"))
# Tool-loop depth for an interpretation batch. Batches run in parallel, so this
# sets the slowest-batch floor on the interpretation phase -- 109s of a 318s
# run. Worth bounding: measured batch reports carry no citations at all, so
# extra turns buy analysis depth rather than references.
SDK_INTERPRET_TURNS = int(os.getenv("AI_SDK_INTERPRET_TURNS", "8"))
# Straggler cutoff. Median call is ~3.5s and a stalled one runs ~63s, so
# anything past this is stuck rather than slow -- see run_hedged.
SDK_CALL_TIMEOUT = float(os.getenv("AI_SDK_CALL_TIMEOUT", "45"))
# Below this many cited papers, synthesis is asked once more to use what it was
# given. Not a quota: the quote and verification guards still decide what stays.
SDK_MIN_CITATIONS = int(os.getenv("AI_SDK_MIN_CITATIONS", "22"))
# Parallel synthesis drafts, best kept. Defaults to 1 -- best-of-N was tried and
# does not pay here, for two measured reasons:
#
#   * It is not free in wall-clock. Short calls parallelise on this gateway (32
#     concurrent in 5.6s), but three full-length syntheses took 216s against ~80s
#     for one, pushing a 280s run to 417s. Long generations queue.
#   * The drafts barely differ on anything selectable from the data: scores came
#     out 162 / 164 / 164, so the selector was choosing between near-identical
#     candidates and the variance that motivated this lives elsewhere.
#
# Raise it only where wall-clock is not a constraint.
SDK_SYNTH_DRAFTS = int(os.getenv("AI_SDK_SYNTH_DRAFTS", "1"))
# Deterministic completeness pass. Off by default -- see the note at its call
# site: it works, and it costs ~190s for a quality change that measured negative.
SDK_GAP_FILL = os.getenv("AI_SDK_GAP_FILL", "0") == "1"
# Every chat completion is issued as a stream and folded back into a
# ChatCompletion for the SDK (see _stream_to_completion). Measured on the CSIC
# gateway 2026-08-17: a non-streamed generation has ~120 s per attempt before
# the gateway abandons it (14k tokens: HTTP 200 after 477 s = four attempts;
# the citation top-up of a 105-pathway report: HTTP 408 after 489 s, three
# times over), while a streamed 25k-token generation completed in 203 s --
# the budget is per read, not per response. Set AI_SDK_STREAM=0 only for a
# provider that cannot stream chat completions.
SDK_STREAM = os.getenv("AI_SDK_STREAM", "1") != "0"
# httpx read timeout, per read: with streaming that is "no token for this
# long", not "the whole answer in this long". Generous, because a large prompt
# queues behind other work before its first token; a stalled stream still
# surfaces as APITimeoutError and gets the shim's retry.
SDK_HTTP_READ_TIMEOUT = float(os.getenv("AI_SDK_HTTP_READ_TIMEOUT", "180"))
# Wall-clock cap on one long-form call (synthesis draft, gap-fill, top-up,
# correction rewrite). These echo or write a whole report, so they cannot use
# run_hedged's 45 s straggler cutoff -- but nor may they run unbounded: two
# live runs sat 90+ minutes inside one top-up before this existed.
SDK_LONG_CALL_TIMEOUT = float(os.getenv("AI_SDK_LONG_CALL_TIMEOUT", "600"))
# The whole interpretation, end to end. A run that is still going after this
# has stalled somewhere the phase caps did not reach; better an error the user
# can retry than a job that reads as running for the rest of the day.
AI_MAX_RUN_SECONDS = float(os.getenv("AI_MAX_RUN_SECONDS", "2700"))

_SYSTEM_STOPWORDS = frozenset("""
a an the and or of in on at to for from with without by as is are was were be
been being this that these those it its their there here into over under
between across per via using used use data dataset datasets sample samples
study analysis experiment experimental design condition conditions time course
timecourse series omics omic multi multiomics layer layers level levels five
four three two one several multiple various different profile profiles
""".split())


def _system_terms(experiment_design, limit=3):
    """Up to `limit` content words from the user's experiment description, for
    a PubMed angle tied to the experimental system.

    Free text such as "murine B-cell precursor differentiation time course,
    five omics layers" yields ["murine", "B-cell", "precursor"]; generic words
    (time, course, omics, layers ...) and short tokens are dropped, and an
    empty or all-generic design yields [] so the caller adds no such angle.
    """
    if not experiment_design:
        return []
    terms = []
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", experiment_design):
        low = tok.lower()
        if low in _SYSTEM_STOPWORDS or low.isdigit() or low in terms:
            continue
        terms.append(low)
        if len(terms) >= limit:
            break
    return terms


# Servlet-facing state: the servlet flips
# _cancel_flags[job_id] to cancel, and the semaphore bounds concurrent runs.
import threading
from src.conf.serverconf import AI_MAX_CONCURRENT_PIPELINES
_cancel_flags = {}
_agent_semaphore = threading.Semaphore(AI_MAX_CONCURRENT_PIPELINES)

_sdk_configured = False
_MODEL_OBJ = None


class _AsyncPacer:
    """Space gateway calls to AI_LLM_MAX_RPM requests/min (0 disables).

    The SDK drives its own AsyncOpenAI client, so LLMClient's token bucket --
    the thing that took the live arm from 6 lost sub-agents to 0 -- never sees
    these calls. Without this shim an SDK run is unpaced against a gateway
    with a measured ceiling of 60/min, and its scores are not comparable to a
    paced live run (round 1p: same agent, pacing alone moved the gap +0.27).

    The pace is one process-wide schedule: run_agent_workflow owns a fresh
    event loop per job and up to AI_MAX_CONCURRENT_PIPELINES jobs run on
    separate threads, all against the same gateway. The reservation below has
    no await inside it, so a plain threading.Lock guards it correctly across
    loops and threads alike -- an asyncio.Lock would bind to one loop and
    either leak per job or trip over a reused loop id.
    """

    def __init__(self, rpm):
        self._interval = 60.0 / rpm if rpm > 0 else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    async def wait(self):
        if not self._interval:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            await asyncio.sleep(delay)


class _EmptyStream(Exception):
    """The gateway closed a completion stream without a single choice."""


async def _stream_to_completion(stream):
    """Fold a chat-completion chunk stream into one ChatCompletion.

    The SDK's non-streaming path calls ``create(stream=False)`` and reads a
    ``ChatCompletion``. We issue the request as a stream instead (see
    SDK_STREAM for why) and rebuild the object it expects: content deltas
    concatenate, tool-call deltas join by ``index`` (name and id arrive in the
    first fragment, arguments trickle in over the rest), the last non-null
    ``finish_reason`` wins, and ``usage`` is whatever the final chunk carried
    (vLLM sends it only when ``stream_options.include_usage`` is set).

    Provider-specific delta fields the SDK does not read (DeepSeek's
    ``reasoning_content``, for one) are dropped here on purpose.
    """
    content = []
    role = None
    refusal = []
    tool_calls = {}          # index -> {"id", "type", "name", "arguments"}
    finish_reason = None
    usage = None
    meta = {}
    saw_choice = False
    try:
        async for chunk in stream:
            if not meta:
                meta = {"id": chunk.id, "created": chunk.created,
                        "model": chunk.model,
                        "system_fingerprint": getattr(chunk, "system_fingerprint", None)}
            if getattr(chunk, "usage", None) is not None:
                usage = chunk.usage
            for choice in (chunk.choices or []):
                saw_choice = True
                delta = choice.delta
                if delta is None:
                    continue
                if delta.role:
                    role = delta.role
                if delta.content:
                    content.append(delta.content)
                if getattr(delta, "refusal", None):
                    refusal.append(delta.refusal)
                for tc in (delta.tool_calls or []):
                    slot = tool_calls.setdefault(tc.index, {
                        "id": None, "type": "function", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.type:
                        slot["type"] = tc.type
                    fn = tc.function
                    if fn is not None:
                        if fn.name:
                            slot["name"] += fn.name
                        if fn.arguments:
                            slot["arguments"] += fn.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass
    if not saw_choice:
        raise _EmptyStream("completion stream ended without any choice")

    message = {"role": role or "assistant",
               "content": "".join(content) if content else None,
               "refusal": "".join(refusal) if refusal else None}
    if tool_calls:
        message["tool_calls"] = [
            {"id": slot["id"] or "call_%d" % idx, "type": slot["type"] or "function",
             "function": {"name": slot["name"], "arguments": slot["arguments"]}}
            for idx, slot in sorted(tool_calls.items())]
    if finish_reason is None:
        # vLLM always closes with one; a provider that does not has still
        # answered, so record the answer rather than discard it.
        finish_reason = "tool_calls" if tool_calls else "stop"
        logger.warning("completion stream ended without finish_reason; assuming %s",
                       finish_reason)
    payload = {
        "id": meta.get("id") or "chatcmpl-stream",
        "object": "chat.completion",
        "created": meta.get("created") or int(time.time()),
        "model": meta.get("model") or "",
        "system_fingerprint": meta.get("system_fingerprint"),
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": message, "logprobs": None}],
        "usage": usage.model_dump() if usage is not None else None,
    }
    return ChatCompletion.model_validate(payload)


async def bounded(awaitable, timeout, label=""):
    """``asyncio.wait_for`` with the reason on the record.

    Every long-form model call goes through here so a stall has a ceiling: the
    task is cancelled at ``timeout`` and asyncio.TimeoutError propagates to a
    caller that decides whether the phase was optional (skip it) or not (fail
    the run). Logged at WARNING because a timeout here is always news.
    """
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("[bounded] %s exceeded %ss and was cancelled",
                       label or "call", timeout)
        raise


def configure_sdk():
    """Point the SDK at our OpenAI-compatible gateway. Idempotent."""
    global _sdk_configured, _MODEL_OBJ
    if _sdk_configured:
        return
    provider = AI_PROVIDERS[AI_LLM_PROVIDER]
    # max_retries=0: the shim below is the ONE retry policy. The client's own
    # default (2) stacked under the shim's 4 attempts turned a single 408 --
    # eight minutes each on this gateway -- into twelve of them, and that is
    # how two live runs spent 90+ minutes inside one citation top-up.
    # The read timeout is per read: with streaming (SDK_STREAM) it bounds the
    # silence between tokens, and a stalled request surfaces as
    # APITimeoutError instead of holding the phase open.
    client = AsyncOpenAI(
        base_url=provider["api_base"], api_key=provider["api_key"],
        max_retries=0,
        timeout=httpx.Timeout(connect=30.0, read=SDK_HTTP_READ_TIMEOUT,
                              write=60.0, pool=30.0))

    # Honour the same pacing knob as LLMClient. Applied at the transport
    # method the SDK actually calls, so every agent turn and tool round-trip
    # is spaced -- not just the calls this module makes directly.
    rpm = int(os.getenv("AI_LLM_MAX_RPM", "0") or 0)
    pacer = _AsyncPacer(rpm)
    completions = client.chat.completions
    completions._pa_orig_create = completions.create

    # One shim for pacing AND resilience: the CSIC gateway answers with bare
    # 500s ("connection reset by peer" from the vLLM behind litellm) during
    # load spikes, and a transient 500 must cost a retry, not the whole run --
    # LLMClient already behaves this way; the SDK transport has to match.
    import openai as _oai

    # 408 Request Timeout arrives as a bare APIStatusError (no dedicated
    # subclass); the gateway answers with it when a long tool-loop turn
    # outlives its upstream budget, and it is exactly as transient as a 5xx.
    _RETRY_STATUSES = {408, 409}

    def _transient(e):
        if isinstance(e, (_oai.InternalServerError, _oai.APIConnectionError,
                          _oai.APITimeoutError, _oai.RateLimitError)):
            return True
        if isinstance(e, (httpx.HTTPError, _EmptyStream)):
            # Raised while *iterating* a stream (openai wraps only the initial
            # request): a dropped connection, a read timeout between tokens,
            # or a stream that closed empty. All as transient as a 5xx.
            return True
        return (isinstance(e, _oai.APIStatusError)
                and getattr(e, "status_code", None) in _RETRY_STATUSES)

    _ATTEMPTS = 4  # one call plus three retries
    # 429 has a policy of its own. A throttled request answers instantly and
    # costs nothing to retry, where a 408 already cost minutes on the wire; and
    # with the client's own retries off (max_retries=0) this shim is all that
    # stands between a 60 rpm key and a verification phase that fans out 28
    # citations at once. Four quick tries there redacted citations the gateway
    # had merely throttled (live run 11n0VMC305). Retry-After is honoured when
    # the gateway sends it; otherwise the wait grows to a 30 s cap.
    _RATE_ATTEMPTS = 8

    def _retry_after(e):
        response = getattr(e, "response", None)
        headers = getattr(response, "headers", None)
        value = headers.get("retry-after") if headers else None
        try:
            return float(value) if value else None
        except (TypeError, ValueError):
            return None

    async def _issue(*args, **kwargs):
        # A caller that streams for itself (Runner.run_streamed) gets the raw
        # stream; every other call is issued as a stream and folded, because
        # on this gateway a non-streamed answer has ~120 s per attempt and a
        # streamed one has that per token.
        orig = completions._pa_orig_create
        if kwargs.get("stream") is True or not SDK_STREAM:
            return await orig(*args, **kwargs)
        kwargs = dict(kwargs, stream=True,
                      stream_options={"include_usage": True})
        stream = await orig(*args, **kwargs)
        return await _stream_to_completion(stream)

    async def _paced_create(*args, **kwargs):
        attempt = 0
        while True:
            await pacer.wait()
            try:
                return await _issue(*args, **kwargs)
            except (_oai.APIError, httpx.HTTPError, _EmptyStream) as e:
                if not _transient(e):
                    raise
                attempt += 1
                throttled = isinstance(e, _oai.RateLimitError)
                limit = _RATE_ATTEMPTS if throttled else _ATTEMPTS
                status = getattr(e, "status_code", None)
                if attempt >= limit:
                    logger.warning("SDK transport giving up after %d attempts (%s%s)",
                                   attempt, type(e).__name__,
                                   " %s" % status if status else "")
                    raise
                if throttled:
                    delay = _retry_after(e) or min(3.0 * 2 ** (attempt - 1), 30.0)
                else:
                    delay = min(2 ** (attempt - 1) * 2, 15)
                logger.warning("SDK transport retry %d/%d after %s%s (waiting %.0fs)",
                               attempt, limit - 1, type(e).__name__,
                               " %s" % status if status else "", delay)
                await asyncio.sleep(delay)

    # The original stays reachable as _pa_orig_create: tests substitute it,
    # and a provider that cannot stream is pointed back at it by AI_SDK_STREAM=0.
    completions.create = _paced_create
    logger.info("Agents SDK transport armed: pacing %s rpm, streaming %s, "
                "retry x%d on 5xx/timeouts and x%d on 429, read timeout %ss",
                rpm or "off", "on" if SDK_STREAM else "off",
                _ATTEMPTS - 1, _RATE_ATTEMPTS - 1, SDK_HTTP_READ_TIMEOUT)
    # chat_completions, not the Responses API: the CSIC gateway is vLLM, which
    # speaks /chat/completions only.
    set_default_openai_api("chat_completions")
    set_default_openai_client(client)
    set_tracing_disabled(True)  # never ship job data to OpenAI's trace backend

    # Passing the model as a *string* routes through the SDK's MultiProvider,
    # which splits on "/" and reads the left side as a provider prefix. Every
    # CSIC model id contains a slash ("deepseek-ai/DeepSeek-V4-Flash-0731"), so
    # that path dies with UserError: Unknown prefix: deepseek-ai. Handing the
    # SDK a concrete model object bypasses provider resolution entirely.
    _MODEL_OBJ = OpenAIChatCompletionsModel(model=provider["model"],
                                            openai_client=client)
    _sdk_configured = True
    logger.info("Agents SDK configured: provider=%s model=%s",
                AI_LLM_PROVIDER, provider["model"])


def _model():
    if _MODEL_OBJ is None:
        configure_sdk()
    return _MODEL_OBJ


_CAVEAT_CUES = (
    r"did not reach|short of significance|non-?significant|marginal|\btrend\b",
    r"discordan|does not follow|without corresponding|inconsist",
    r"annotation artefact|annotation artifact|named after|label reflects",
    r"driven (?:almost )?(?:entirely|solely) by|single (?:omic )?layer|only .{0,20}assay",
    r"remains? to be|requires? (?:further )?(?:testing|validation)|hypothes",
    r"control point|rate-?limiting|bottleneck",
    r"both up.{0,15}and down|mixed direction|in opposite direction",
)


def _completeness_gaps(report, pathways):
    """What the report omits that this job's data actually contains.

    Coverage and candour were both being left to chance: the same settings
    produce a report naming ten enriched pathways and one naming four, and the
    caveats that fire vary run to run. Hoping both land together is a lottery,
    and resampling until they do is not engineering. So: compute what is
    missing and ask for exactly that.

    Every gap is derived from the job. A caveat is only requested when the data
    warrants it -- marginal p-values are only flagged if some layer really is
    marginal, single-layer pathways only if some pathway really is carried by
    one assay. Asking for a caveat the data does not support would be inviting
    the model to invent one, which is the failure mode this whole workflow is
    built to avoid.

    Returns (missing_pathway_names, missing_caveat_instructions).
    """
    low = report.lower()
    missing_pw = [p["name"] for p in pathways
                  if p.get("name") and p["name"].lower() not in low]

    gaps = []

    def _pvals(pw):
        out = []
        for match in re.finditer(r"p=([0-9.eE+-]+)", str(pw.get("per_omic") or "")):
            try:
                out.append(float(match.group(1)))
            except ValueError:
                pass
        return out

    marginal = [p["name"] for p in pathways
                if any(0.05 < v <= 0.15 for v in _pvals(p))]
    if marginal and not re.search(r"did not reach|short of significance|"
                                  r"non-?significant|marginal|\btrend\b", report, re.I):
        gaps.append("Several pathways have layers with p-values between 0.05 "
                    "and 0.15 (e.g. %s). Report these as trends WITH the number "
                    "rather than as findings or silence."
                    % ", ".join(marginal[:3]))

    single = [p["name"] for p in pathways
              if len([v for v in _pvals(p) if v <= 0.05]) == 1]
    if single and not re.search(r"driven (?:almost )?(?:entirely|solely) by|"
                                r"single (?:omic )?layer|only .{0,20}assay",
                                report, re.I):
        gaps.append("These pathways are significant in exactly ONE omic layer "
                    "(%s). Name the lone assay carrying each -- it is a weaker "
                    "result than multi-layer support and should read that way."
                    % ", ".join(single[:3]))

    DISEASE = ("virus", "infection", "cancer", "carcinoma", "leukemia",
               "ataxia", "diabetic", "hepatitis", "melanoma", "papillomavirus")
    named = [p["name"] for p in pathways
             if any(d in p["name"].lower() for d in DISEASE)]
    if named and not re.search(r"annotation artefact|annotation artifact|"
                               r"named after|label reflects|despite (?:its|the) name",
                               report, re.I):
        gaps.append("These pathways are NAMED after diseases unrelated to this "
                    "experiment (%s). The enrichment is real; the label is an "
                    "artefact of database naming. Say so explicitly."
                    % ", ".join(named[:3]))

    # These two ask for the phrasing that makes the practice unambiguous, not
    # merely for the topic. "hypothesis" appearing anywhere satisfied the loose
    # check while the report never actually said what would test the idea --
    # the detector reported no gap and the practice was still missing.
    if not re.search(r"remains? to be (?:tested|confirmed|verified)|"
                     r"would (?:be )?(?:required to )?test|to be tested",
                     report, re.I):
        gaps.append("Mark every mechanistic proposal explicitly as 'remains to "
                    "be tested', and name the experiment that would test it.")

    if not re.search(r"control point|rate-?limiting|bottleneck", report, re.I):
        gaps.append("Where the data suggests one step gates a process, identify "
                    "it as a control point -- and say where changes look like "
                    "consequences rather than causes.")

    if not re.search(r"discordan|mRNA .{0,30}(?:without|not).{0,30}protein|"
                     r"protein .{0,30}(?:without|not).{0,30}mRNA", report, re.I):
        gaps.append("Name at least one cross-layer discordance explicitly using "
                    "the word 'discordant' -- mRNA moving without protein, "
                    "chromatin opening without transcription, or a regulator "
                    "whose targets do not follow.")

    if not re.search(r"both up.{0,15}and down|mixed direction|"
                     r"in opposite direction|move[sd]? in both", report, re.I):
        gaps.append("Where a group of pathways moves in both directions, say so "
                    "in those terms rather than describing them as uniformly up "
                    "or down.")

    return missing_pw, gaps


def _reattach_blocks(report, blocks):
    """Put deterministic blocks (the pathway and cluster tables) back if a
    correction rewrite dropped them, keeping them ahead of the References
    section. Blocks already present are left where they are."""
    from src.classes.AIInterpret.verification import _REFERENCES_HEADING_RE
    m = _REFERENCES_HEADING_RE.search(report)
    body = report[:m.start()].rstrip() if m else report.rstrip()
    refs = report[m.start():] if m else ""
    for heading, text in blocks:
        if text and heading not in body:
            body += "\n\n" + text.rstrip()
    return body + ("\n\n" + refs if refs else "\n")


def _pick_best_draft(drafts, pathways, papers):
    """Choose among synthesis drafts on evidence the DATA provides.

    The synthesis is stochastic to a degree that dominates every other variable
    measured here -- the same settings produce reports scoring 8.50 and 17.00 --
    so a single draw is not the best this workflow can do. Generating several
    and keeping the best is how the tellme loop handles the same narrator.

    Selection deliberately never consults the evaluation rubric. It counts
    things the job itself defines: how many of the enriched pathways the draft
    actually discusses, how many retrieved papers it cites, and how many
    distinct caveats it raises. Score the drafts against the rubric and the
    workflow starts optimising for the marker list rather than for the reader,
    which is the failure the rubric's ANTI markers exist to catch.

    Returns (best_draft, [per-draft score breakdowns]).
    """
    valid_refs = {p["ref_index"] for p in papers}
    names = [p.get("name", "") for p in pathways if p.get("name")]

    ranked = []
    for i, text in enumerate(drafts):
        low = text.lower()
        covered = sum(1 for n in names if n.lower() in low)
        cited = len({int(n) for n in re.findall(r'\[(\d+)\]', text)} & valid_refs)
        caveats = sum(1 for cue in _CAVEAT_CUES if re.search(cue, text, re.I))
        # A draft that lost its structure is not a candidate however well it
        # scores on the counts above.
        truncated = len(text) < 4000 or not re.search(r'^#', text, re.M)
        score = 0.0 if truncated else covered + 2.0 * cited + 3.0 * caveats
        ranked.append({"draft": i, "covered": covered, "cited": cited,
                       "caveats": caveats, "truncated": truncated,
                       "score": round(score, 1)})

    best = max(range(len(drafts)), key=lambda i: ranked[i]["score"])
    logger.info("best-of-%d synthesis: picked draft %d (%s)",
                len(drafts), best, ranked[best])
    return drafts[best], ranked


async def run_hedged(agent, prompt, ctx, max_turns=6, timeout=None, label=""):
    """Runner.run, with a straggler retried instead of waited on.

    Measured on the CSIC gateway: fire 16 identical requests and the median
    returns in 3.5s while ONE takes 63s -- reproducibly, roughly one trial in
    three. Because ``asyncio.gather`` waits for the slowest, that single
    straggler sets the whole phase's wall-clock: it is why the interpretation
    phase sat at ~107s regardless of batch count or tool-turn budget.

    A stalled request is not making progress, so waiting on it buys nothing.
    Cancel it, issue a fresh one, and keep whichever answers. Cost is one extra
    request on a small fraction of calls; the saving is tens of seconds of
    wall-clock per phase.
    """
    if timeout is None:
        timeout = SDK_CALL_TIMEOUT
    for attempt in (1, 2):
        try:
            return await asyncio.wait_for(
                Runner.run(agent, prompt, context=ctx, max_turns=max_turns),
                timeout=timeout)
        except asyncio.TimeoutError:
            if attempt == 1:
                logger.warning("[hedge] %s exceeded %ss; cancelling and retrying",
                               label or agent.name, timeout)
                continue
            logger.warning("[hedge] %s timed out twice; giving up",
                           label or agent.name)
            raise


# ---------------------------------------------------------------------------
# Shared context + structured output types
# ---------------------------------------------------------------------------

@dataclass
class AgentContext:
    """Threaded through every agent and tool via RunContextWrapper."""
    job_instance: Any
    job_id: str
    organism_name: str
    experiment_design: str
    paper_index: dict = field(default_factory=dict)   # ref_index -> paper
    llm: Any = None                                    # for extract_evidence
    tool_calls: int = 0                                # instrumentation


class TriagePick(BaseModel):
    pathway_name: str
    priority: int = Field(ge=1, le=5, description="1 = highest")
    reason: str


class TriageResult(BaseModel):
    picks: list[TriagePick]


class SearchTask(BaseModel):
    query: str = Field(description="A PubMed query string")
    pathway: str = Field(description="Pathway this query supports")
    rationale: str


class SearchPlan(BaseModel):
    tasks: list[SearchTask]


class RelevantPMIDs(BaseModel):
    """Replaces _parse_pmid_list."""
    pmids: list[str]


class Verdict(BaseModel):
    """Replaces _parse_json_verdict."""
    supported: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


# ---------------------------------------------------------------------------
# Tools -- thin SDK wrappers over the shared tool bodies in tools.py.
# No behaviour is redefined here; only the calling convention changes.
# ---------------------------------------------------------------------------

@function_tool
def get_gene_timecourse(ctx: RunContextWrapper[AgentContext], gene_symbol: str) -> str:
    """Return all timepoint values for a gene across every omic layer."""
    ctx.context.tool_calls += 1
    return tools_mod.execute_tool("get_gene_timecourse", ctx.context.job_instance,
                                  {"gene_symbol": gene_symbol})


@function_tool
def get_pathway_genes(ctx: RunContextWrapper[AgentContext], pathway_name: str) -> str:
    """Return all matched genes in a pathway with their measured values."""
    ctx.context.tool_calls += 1
    return tools_mod.execute_tool("get_pathway_genes", ctx.context.job_instance,
                                  {"pathway_name": pathway_name})


@function_tool
def compare_genes(ctx: RunContextWrapper[AgentContext], gene_symbols: list[str]) -> str:
    """Side-by-side comparison of several genes across all omic layers."""
    ctx.context.tool_calls += 1
    return tools_mod.execute_tool("compare_genes", ctx.context.job_instance,
                                  {"gene_symbols": gene_symbols})


@function_tool
def search_paper_text(ctx: RunContextWrapper[AgentContext], ref_index: int, query: str) -> str:
    """Search the full text of a cited paper for a phrase. ref_index is the [n] citation number."""
    ctx.context.tool_calls += 1
    executor = tools_mod.build_verification_executor(ctx.context.paper_index)
    return executor("search_paper_text", {"ref_index": ref_index, "query": query})


@function_tool
def fetch_paper_section(ctx: RunContextWrapper[AgentContext], ref_index: int, section: str) -> str:
    """Fetch a named section (abstract, results, discussion) of a cited paper."""
    ctx.context.tool_calls += 1
    executor = tools_mod.build_verification_executor(ctx.context.paper_index)
    return executor("fetch_paper_section", {"ref_index": ref_index, "section": section})


DATA_TOOLS = [get_gene_timecourse, get_pathway_genes, compare_genes]
VERIFY_TOOLS = [search_paper_text, fetch_paper_section]


# ---------------------------------------------------------------------------
# Agents. Instructions come verbatim from prompts.py -- see fairness contract.
# ---------------------------------------------------------------------------

def _build_agents():
    ms = ModelSettings(temperature=AI_TEMPERATURE)
    strict = ModelSettings(temperature=0.1)

    triage_agent = Agent[AgentContext](
        name="Triage Agent",
        model=_model(),
        instructions=(
            "You are an expert bioinformatics pathway triage agent. Given enriched "
            "pathways from a multi-omics experiment, select the most biologically "
            "informative ones to investigate deeply. Prefer pathways with support "
            "from multiple omic layers and strong statistical significance."
        ),
        model_settings=strict,
        output_type=TriageResult,   # <-- SDK structured output, replaces hand parsing
        tools=[],
    )

    search_planner = Agent[AgentContext](
        name="Search Planner",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_SEARCH_PLANNER,
        model_settings=ms,
        output_type=SearchPlan,     # <-- replaces _parse_search_plan
        tools=[],
    )

    paper_filter = Agent[AgentContext](
        name="Paper Filter",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_SEARCH_SUBAGENT,
        model_settings=strict,
        output_type=RelevantPMIDs,  # <-- replaces _parse_pmid_list
        tools=[],
    )

    interpreter = Agent[AgentContext](
        name="Pathway Interpreter",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_INTERPRET,
        model_settings=ms,
        tools=DATA_TOOLS,           # SDK drives the tool loop
    )

    # Cluster mode's second tier: the same brief, no tools, one call. Used for
    # units without a top-N or multi-omic pathway, where the data block in the
    # prompt already carries what the tools would fetch.
    interpreter_light = Agent[AgentContext](
        name="Pathway Interpreter (single-shot)",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_INTERPRET,
        model_settings=ms,
        tools=[],
    )

    synthesizer = Agent[AgentContext](
        name="Report Writer",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_SYNTHESIZE,
        model_settings=ms,
        tools=[],
    )

    # DANGER, measured 2026-08-07 against the CSIC gateway: declaring BOTH
    # tools= and output_type= on one Agent produces a verifier that never
    # verifies. output_type compiles to response_format, and vLLM's grammar
    # constrains the first token to "{", so the model cannot emit a tool call.
    # In the A/B (scratchpad/test_sdk_tools_vs_schema.py) the schema-typed
    # verifier made 0 tool calls and still returned supports_claim=true, its
    # reasoning field narrating the check it had not performed. The identical
    # agent without output_type made 3 tool calls and quoted the paper.
    #
    # A citation verifier that rubber-stamps is worse than none: it converts
    # "unchecked" into "checked and passed". So tools win and the verdict is
    # parsed from text -- the same trade llm_client.complete_with_tools_json
    # makes by coercing only after the tool loop has finished.
    verifier = Agent[AgentContext](
        name="Claim Verifier",
        model=_model(),
        instructions=prompts_mod.SYSTEM_PROMPT_VERIFICATION,
        model_settings=strict,
        tools=VERIFY_TOOLS,
    )
    return dict(triage=triage_agent, planner=search_planner, filter=paper_filter,
                interpret=interpreter, interpret_light=interpreter_light,
                synth=synthesizer, verify=verifier)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def _run_async(job_instance, job_id, experiment_design, budgets, stats,
                     hooks=None):
    def _hb(status, percent, detail):
        """Report progress to the servlet layer and honour cancellation."""
        if hooks and hooks.get("progress"):
            try:
                hooks["progress"](status, percent, detail)
            except Exception:
                logger.debug("progress hook failed", exc_info=True)
        if hooks and hooks.get("cancelled") and hooks["cancelled"]():
            raise InterruptedError("Cancelled")

    configure_sdk()
    agents = _build_agents()

    organism = job_instance.getOrganism()
    organism_name = get_organism_name(organism)
    pathways = build_pathway_context(job_instance, max_pathways=budgets["max_pathways"])
    # Cluster mode widens the pathway set from the top-N by p-value to every
    # significant pathway the network draws, grouped by shared matched
    # features. The list stays in global rank order -- clustering decides what
    # is discussed together, never the order of emphasis (evolve round 1 vs 2).
    partition = None
    if clusters_mod.CLUSTER_MODE:
        try:
            # The top-N by p-value the plain path would have shown are pinned
            # into the universe: a change that widens the context must never
            # drop a pathway the narrower one presented.
            candidate = clusters_mod.build_partition(
                job_instance, always_include=[p["id"] for p in pathways])
            member_ids = clusters_mod.partition_member_ids(candidate)
            if candidate.get("clusters") and member_ids:
                partition = candidate
                pathways = build_pathway_context(job_instance, pathway_ids=member_ids)
                logger.info("[%s][sdk] cluster mode: %s", job_id,
                            clusters_mod.partition_summary(partition))
            else:
                logger.info("[%s][sdk] cluster mode found no clusters (%s); using the "
                            "rank-ordered top-%d", job_id,
                            clusters_mod.partition_summary(candidate), len(pathways))
        except Exception as e:
            logger.warning("[%s][sdk] cluster mode failed (%s); using the rank-ordered "
                           "top-%d", job_id, e, len(pathways))
            partition = None
    ctx_by_id = {p["id"]: p for p in pathways}
    if hooks and hooks.get("pathways"):
        try:
            hooks["pathways"](pathways)
        except Exception:
            logger.debug("pathway-index hook failed", exc_info=True)
    if partition is not None and hooks and hooks.get("partition"):
        try:
            hooks["partition"](partition)
        except Exception:
            logger.debug("partition hook failed", exc_info=True)
    if partition is not None:
        stats["clusters"] = len(partition["clusters"])
        stats["cluster_pathways"] = len(pathways)
        stats["cluster_standalone"] = len(partition["standalone"])
        stats["cluster_further"] = len(partition["further"])
    gene_whitelist = build_gene_symbol_whitelist(job_instance)
    # The planner and the cross-omic matrix keep the top-N view even in
    # cluster mode: the wider set reaches literature through per-cluster
    # queries below, and a 100-pathway planner prompt is not a better planner.
    plan_pathways = pathways[:budgets["max_pathways"]] if partition is not None else pathways
    major, minor = triage_pathways(plan_pathways)
    matrix = build_cross_omic_matrix(major)

    ctx = AgentContext(job_instance=job_instance, job_id=job_id,
                          organism_name=organism_name,
                          experiment_design=experiment_design or "")
    # The quote collector is shared domain code and is synchronous; it gets a
    # plain LLMClient rather than an Agent so both arms gather quotes the same
    # way and the comparison stays about orchestration.
    llm_for_quotes = LLMClient(AI_PROVIDERS[AI_LLM_PROVIDER])
    try:
        # 30, after testing 80. Widening it does not surface the genes the
        # benchmark rewards (Ikzf1, Myc, Cdkn1b, Trp53): hundreds of features
        # outrank them on layer count and effect size, so they sit far below any
        # sane cut. Reaching them would mean ranking genes because a rubric
        # names them, which is fitting the metric rather than reading the data --
        # so the cut stays where the evidence puts it, and those tokens stay
        # unreachable.
        regulators_block = build_key_regulators_block(
            job_instance, limit=int(os.getenv("AI_SDK_REGULATORS", "30")))
    except Exception as e:
        logger.warning("[%s][sdk] regulator block failed: %s", job_id, e)
        regulators_block = ""

    # -- Phase 1: triage -----------------------------------------------------
    _hb("extracting", 10, "Reading the enrichment results...")
    t0 = time.time()
    # Keys must match build_pathway_context's current record shape: the old
    # p.get("pvalue")/p.get("omics") read fields that no longer exist, so
    # every triage line said "p=None, omics=0" and the agent picked on names.
    if partition is None:
        pathway_lines = "\n".join(
            "- %s (combined p=%.3g, significant omics=%s)"
            % (p.get("name"), p.get("combined_pvalue") or 1.0,
               p.get("significant_omic_count", "?"))
            for p in pathways)
        triage_res = await Runner.run(
            agents["triage"],
            "Experiment: %s\nOrganism: %s\n\nEnriched pathways:\n%s\n\n"
            "Select up to %d to investigate." % (experiment_design, organism_name,
                                                 pathway_lines, budgets["max_pathways"]),
            context=ctx, max_turns=3)
        picks = triage_res.final_output.picks
        logger.info("[%s][sdk] triage picked %d pathways", job_id, len(picks))
    else:
        # The partition already decided what is investigated (every
        # significant pathway, in its cluster); the triage pick is not
        # consumed downstream, so cluster mode skips the call.
        picks = []
    stats["triage_s"] = time.time() - t0

    # -- Phase 2: search planning -------------------------------------------
    _hb("searching_pubmed", 15, "Planning literature searches...")
    t0 = time.time()
    plan_prompt = prompts_mod.build_search_planner_prompt(
        major, matrix, gene_whitelist, experiment_design, organism_name,
        budgets["max_search_tasks"])
    plan_res = await Runner.run(agents["planner"], plan_prompt, context=ctx, max_turns=3)
    tasks = plan_res.final_output.tasks[:budgets["max_search_tasks"]]
    stats["plan_s"] = time.time() - t0
    logger.info("[%s][sdk] planner produced %d search tasks", job_id, len(tasks))

    # -- Phase 3: literature retrieval (shared domain code, concurrent) ------
    _hb("searching_pubmed", 25, "Retrieving literature...")
    t0 = time.time()
    pubmed = PubMedClient()

    # Retrieval is split into search-all-then-fetch-once because PubMed, not the
    # LLM, is the budget here. Per-task search+fetch costs 2N round trips at the
    # unkeyed 3 req/s ceiling; EFetch accepts hundreds of PMIDs in one call, so
    # batching the fetches costs N+1. That is what makes a wider search budget
    # affordable inside 300s: 88 tasks previously blew past 600s.
    _fetched = {}   # pmid -> paper, filled by the batched fetch below
    # task.pathway is the attribution key. The planner and the per-pathway
    # backfill use a pathway name; cluster-mode queries use the cluster id so
    # one search feeds every member's drill-down. This maps a key back to the
    # pathway names a paper should be attributed to.
    attribution = {}

    def _attributed(task):
        return list(attribution.get(task.pathway) or [task.pathway])

    def _task_display(task):
        names = attribution.get(task.pathway)
        return ", ".join(names[:4]) + (" ..." if names and len(names) > 4 else "") \
            if names else task.pathway

    async def _search_only(task):
        try:
            pmids = await asyncio.to_thread(
                pubmed.search, task.query, AI_PAPERS_PER_SEARCH_TASK)
        except Exception as e:
            logger.warning("[%s][sdk] PubMed search failed for '%s': %s",
                           job_id, task.query[:80], e)
            return task, []
        return task, list(dict.fromkeys(pmids or []))

    async def _filter_task(task, pmids):
        papers = [_fetched[p] for p in pmids if p in _fetched]
        if not papers:
            return []
        listing = "\n".join(
            "PMID %s: %s\n%s" % (p.get("pmid"), p.get("title", ""),
                                 (p.get("abstract", "") or "")[:600])
            for p in papers)
        res = await Runner.run(
            agents["filter"],
            "Experiment: %s\nOrganism: %s\nPathway: %s\nQuery: %s\n\n"
            "Candidate papers:\n%s\n\n"
            "Return ONLY the PMIDs that could support a claim in a report about "
            "this experiment. Be strict -- keep at most a handful.\n\n"
            "The test is whether the paper contains a specific, quotable finding "
            "about the MECHANISM these genes participate in: regulation, "
            "interaction, direction of effect. Such findings do transfer across "
            "systems -- a paper showing Myc drives polyamine-synthesis genes "
            "supports that mechanistic claim here even if shown in another cell "
            "type -- so judge the finding, not the model organism.\n\n"
            "REJECT anything that merely shares a keyword, above all a paper "
            "matched because a pathway is NAMED after a disease: a carcinoma or "
            "hepatitis paper retrieved because the pathway is called 'Hepatitis "
            "B' says nothing about this experiment, and once cited it usually "
            "contradicts the claim it was attached to. Reject reviews with no "
            "specific finding to quote, and papers whose result runs opposite to "
            "what is described.\n\n"
            "Precision beats volume: a kept paper with no quotable finding costs "
            "a citation, since the claim it was attached to is then removed. An "
            "empty list is correct when nothing fits."
            % (experiment_design, organism_name, _task_display(task), task.query, listing),
            context=ctx, max_turns=3)
        answered = {str(x).strip() for x in (res.final_output.pmids or [])}
        candidates = {str(p.get("pmid")) for p in papers}
        keep = answered & candidates
        # Three outcomes, only one of them a judgement. An explicit empty list
        # is the screener saying nothing fits, and the prompt asks for exactly
        # that when it is true -- honour it. A non-empty list that names no
        # candidate is a malformed answer (invented or garbled PMIDs), not a
        # verdict, and dropping the whole task on it silently starves the report
        # of literature; keep the top hits instead, as PubMed ranked them.
        if answered and not keep:
            logger.warning("[%s][sdk] screener for '%s' returned %d PMID(s), none "
                           "among the %d candidates; keeping the top %d hits",
                           job_id, task.query[:60], len(answered), len(candidates),
                           AI_PAPERS_KEPT_PER_TASK)
            keep = {str(p.get("pmid")) for p in papers[:AI_PAPERS_KEPT_PER_TASK]}
        out = []
        for p in papers:
            if str(p.get("pmid")) in keep:
                # Copy: the fetch cache is shared between tasks, and assigning
                # pathways in place would let the last task to keep a paper
                # erase every other pathway it was found for. The dedup below
                # merges these lists back together.
                paper = dict(p)
                paper["pathways"] = _attributed(task)
                out.append(paper)
        # Which stage is actually starving the citation count: PubMed returning
        # little, or the filter rejecting most of what it returns? Without this
        # the funnel is invisible and tuning is guesswork.
        stats.setdefault("search_hits", 0)
        stats.setdefault("search_kept", 0)
        stats["search_hits"] += len(papers)
        stats["search_kept"] += len(out)
        logger.info("[%s][sdk] search '%s' -> %d hits, %d kept",
                    job_id, task.query[:60], len(papers), len(out))
        return out

    if SDK_SEARCH_ALL_PATHWAYS:
        # One extra search per pathway the planner did not cover. The planner
        # optimises for cross-cutting themes and leaves whole pathways with no
        # literature at all, which caps how many citations the report can carry.
        # Several query angles per pathway, not one. References scale with the
        # number of searches (26 tasks produced 22 references), but only ~30% of
        # references yield a usable supporting quote -- so reaching ~20
        # citations needs roughly 60+ references, which one query per pathway
        # cannot supply. The planner's own task count is capped upstream by
        # _adaptive_budgets at (pathways+1)//2, so raising AI_MAX_SEARCH_TASKS
        # alone does nothing; the breadth has to be added here.
        #
        # Gene-anchored, never pathway-name-anchored: database entries are often
        # named after a disease, and searching that label returns the disease's
        # literature instead of this experiment's biology.
        covered = {t.pathway for t in tasks}
        # The system angle comes from the user's own experiment description,
        # never from a fixed phrase: a hard-coded "B cell OR lymphocyte" here
        # (a leftover from tuning on one dataset) would pull immunology papers
        # into a plant or yeast report. Empty design -> no system angle at all.
        system_terms = _system_terms(experiment_design)
        system_angle = ("(%s)" % " OR ".join('"%s"' % t if " " in t else t
                                             for t in system_terms)
                        if system_terms else "")
        budget = SDK_BACKFILL_MAX_TASKS
        if partition is not None:
            # One or two gene-anchored queries per cluster from its shared
            # core (one per standalone / further pathway), in cluster rank
            # order so the budget goes to the strongest clusters first.
            # Attributed to every member, so a paper found for a cluster is
            # available to each member's interpretation and drill-down.
            seen_queries = {t.query for t in tasks}
            n_before = len(tasks)
            for query, key, names, why in clusters_mod.cluster_search_queries(
                    partition, ctx_by_id, organism_name, system_angle):
                if len(tasks) >= budget:
                    logger.info("[%s][sdk] backfill budget of %d tasks reached; "
                                "remaining clusters get no extra search", job_id, budget)
                    break
                if query in seen_queries:
                    continue
                seen_queries.add(query)
                attribution[key] = names
                tasks.append(SearchTask(query=query, pathway=key, rationale=why))
            logger.info("[%s][sdk] %d cluster search tasks added (%d total, system "
                        "angle: %s)", job_id, len(tasks) - n_before, len(tasks),
                        system_angle or "none")
        for pw in (pathways if partition is None else []):
            if pw["name"] in covered:
                continue
            if len(tasks) >= budget:
                logger.info("[%s][sdk] backfill budget of %d tasks reached; "
                            "remaining uncovered pathways get no extra search",
                            job_id, budget)
                break
            genes = [g["symbol"] for g in pw.get("top_genes", [])[:6]
                     if g.get("relevant")]
            variants = []
            if genes:
                variants.append("(%s) AND (%s)" % (" OR ".join(genes[:3]), organism_name))
                if len(genes) > 3:
                    variants.append("(%s) AND (%s)" % (" OR ".join(genes[3:6]), organism_name))
                # One angle tied to the experimental system rather than the
                # organism, which "Mus musculus" alone does not narrow.
                if system_angle:
                    variants.append("(%s) AND %s" % (" OR ".join(genes[:3]), system_angle))
            else:
                variants.append('"%s"[Title/Abstract]' % pw["name"])
            for v in variants[:max(0, budget - len(tasks))]:
                tasks.append(SearchTask(query=v, pathway=pw["name"],
                                        rationale="per-pathway coverage backfill"))
        logger.info("[%s][sdk] %d search tasks after per-pathway backfill "
                    "(system angle: %s)", job_id, len(tasks), system_angle or "none")

    # Bound the fan-out. A bare asyncio.gather over every task issues all the
    # PubMed requests at once and earns a wall of HTTP 429s -- the threaded arm
    # gets this for free from ThreadPoolExecutor(max_workers=N), whereas the
    # async idiom is unbounded unless you remember to say otherwise.
    sem = asyncio.Semaphore(SDK_SEARCH_CONCURRENCY)

    async def _bounded_search(task):
        async with sem:
            return await _search_only(task)

    # Step 1: every search, bounded.
    search_results = await asyncio.gather(
        *[_bounded_search(t) for t in tasks], return_exceptions=True)
    task_pmids = []
    for r in search_results:
        if isinstance(r, Exception):
            logger.warning("[%s][sdk] search task failed: %s", job_id, r)
            continue
        task_pmids.append(r)

    # Step 2: ONE fetch for every PMID any search found, in EFetch-sized chunks.
    # This is the whole point of the split -- N searches now cost N+ceil(M/200)
    # round trips instead of 2N.
    all_pmids = list(dict.fromkeys(p for _t, pmids in task_pmids for p in pmids))
    stats["pmids_found"] = len(all_pmids)
    CHUNK = 200
    for start in range(0, len(all_pmids), CHUNK):
        chunk = all_pmids[start:start + CHUNK]
        try:
            for paper in (await asyncio.to_thread(pubmed.fetch_abstracts, chunk)) or []:
                _fetched[str(paper.get("pmid"))] = paper
        except Exception as e:
            logger.warning("[%s][sdk] batched abstract fetch failed: %s", job_id, e)
    logger.info("[%s][sdk] %d searches -> %d PMIDs -> %d abstracts fetched",
                job_id, len(tasks), len(all_pmids), len(_fetched))

    # Step 3: relevance filtering. No PubMed in this loop any more, so it is
    # bounded by the gateway rather than by NCBI's 3 req/s and gets its own,
    # much wider semaphore.
    fsem = asyncio.Semaphore(SDK_VERIFY_CONCURRENCY)

    async def _bounded_filter(task, pmids):
        async with fsem:
            return await _filter_task(task, pmids)

    filter_results = await asyncio.gather(
        *[_bounded_filter(t, pmids) for t, pmids in task_pmids],
        return_exceptions=True)
    all_papers = []
    for (task, pmids), r in zip(task_pmids, filter_results):
        if isinstance(r, Exception):
            # A dead screener is not a verdict either: fall back to the top
            # hits so a gateway hiccup on one sub-agent costs precision on one
            # task, not that task's entire literature.
            fallback = [_fetched[p] for p in pmids if p in _fetched][:AI_PAPERS_KEPT_PER_TASK]
            logger.warning("[%s][sdk] filter task failed for '%s' (%s); keeping "
                           "the top %d hits", job_id, task.query[:60], r, len(fallback))
            for p in fallback:
                paper = dict(p)
                paper["pathways"] = _attributed(task)
                all_papers.append(paper)
            continue
        all_papers.extend(r)

    seen, unique_papers, n = {}, [], 1
    for p in all_papers:
        pmid = p.get("pmid")
        if pmid not in seen:
            p["ref_index"] = n
            n += 1
            seen[pmid] = p
            unique_papers.append(p)
        else:
            for pw in p.get("pathways", []):
                if pw not in seen[pmid].setdefault("pathways", []):
                    seen[pmid]["pathways"].append(pw)
    # Upgrade to full text (PMC -> Europe PMC -> abstract), as the incumbent
    # does. This arm was fetching abstracts only, which capped citations
    # directly: a supporting sentence for a mechanistic claim usually sits in
    # Results, while an abstract states conclusions. Quotes could only ever be
    # drawn from the abstract, so most citations had no quote and were redacted.
    if unique_papers:
        pathways_by_pmid = {p["pmid"]: p.get("pathways", []) for p in unique_papers}
        index_by_pmid = {p["pmid"]: p["ref_index"] for p in unique_papers}
        try:
            full = await asyncio.to_thread(pubmed.fetch_papers,
                                           list(index_by_pmid.keys()))
        except Exception as e:
            logger.warning("[%s][sdk] full-text fetch failed (%s); keeping abstracts",
                           job_id, e)
            full = []
        if full:
            for p in full:
                # Carry over what retrieval established; fetch_papers does not
                # know about our numbering or pathway attribution.
                p["ref_index"] = index_by_pmid.get(p["pmid"])
                p["pathways"] = pathways_by_pmid.get(p["pmid"], [])
            unique_papers = [p for p in full if p.get("ref_index") is not None]

    ctx.paper_index = {p["ref_index"]: p for p in unique_papers}
    stats["retrieval_s"] = time.time() - t0
    stats["papers"] = len(unique_papers)
    stats["full_text_papers"] = sum(1 for p in unique_papers
                                    if p.get("full_text_available"))
    logger.info("[%s][sdk] %d unique papers (%d with full text)",
                job_id, len(unique_papers), stats["full_text_papers"])

    # -- Phase 4: batched interpretation (SDK drives the tool loop) ----------
    _hb("interpreting", 45, "Generating interpretation with evidence extraction...")
    t0 = time.time()

    async def _one_batch(batch, unit_batch=None):
        names = {p["name"] for p in batch}
        batch_papers = [p for p in unique_papers
                        if names & set(p.get("pathways", []))]
        # Cap what one batch is shown. Loosening the relevance filter raised the
        # kept pool from ~30 to 106 papers and citations COLLAPSED 15 -> 3: a
        # batch handed 20+ abstracts cites fewer of them, not more. The wider
        # pool still exists for other batches and for quote lookup; this only
        # bounds what any single prompt must reason over.
        if len(batch_papers) > SDK_PAPERS_PER_BATCH:
            # Prefer papers with full text, then the earliest-found (which are
            # the planner's targeted queries rather than the backfill sweep).
            batch_papers = sorted(
                batch_papers,
                key=lambda p: (not p.get("full_text_available"), p["ref_index"])
            )[:SDK_PAPERS_PER_BATCH]
        # Number this batch's papers [1..n] and remap afterwards, exactly as
        # pipeline.py does. Handing a batch its GLOBAL indices -- [7], [12],
        # [15] -- fights the model's habit of renumbering from 1: it either
        # renumbers anyway (so the markers match no paper and get dropped) or
        # stops citing altogether. That was this arm's 1-in-2 zero-citation
        # rate, and its 9 "failed citations" back in the first comparison.
        local_papers, local_to_global = _build_local_paper_index(batch_papers)
        prompt = prompts_mod.build_batch_interpretation_prompt(
            batch, local_papers, experiment_design, organism_name)
        prompt += _shared_gene_core(batch, ctx.job_instance)
        if unit_batch:
            # Cluster context: what the members share, their global ranks,
            # and the instruction to interpret each cluster as one unit.
            prompt += "\n\n" + clusters_mod.render_units_block(unit_batch, partition)
        # Features corroborated across independent assays. The pathway context
        # reaches genes only through the top enriched pathways, so a gene with
        # signal in two or three layers that sits outside those pathways is
        # invisible to the writer no matter how strong its evidence.
        if regulators_block:
            prompt += "\n\n" + regulators_block
        # Deliberately NOT hedged. Hedging suits calls whose median is seconds,
        # where a minute-long response is unambiguously stuck. An interpretation
        # batch legitimately runs ~60s, so a timeout tight enough to catch a
        # straggler also cancels healthy work: at a 30s cutoff this fired 66
        # times, and the rushed retries pulled off-lineage claims into the report
        # (GATA3 presented as a B-cell regulator) and dropped the score to 5.00.
        # Speed bought that way is not speed.
        agent_key, turns = "interpret", SDK_INTERPRET_TURNS
        if unit_batch:
            # Heavy = the unit holds one of the top-N pathways by p-value, the
            # set the top-N path interpreted with tools. "Or any multi-omic
            # pathway" was tried first: on the STATegra fold that made every
            # one of the 14 batches heavy (36 of 101 nodes are multi-omic), so
            # it saved nothing.
            core_ids = {p["id"] for p in pathways[:budgets["max_pathways"]]}
            heavy = CLUSTER_TOOLS and any(p["id"] in core_ids for p in batch)
            agent_key = "interpret" if heavy else "interpret_light"
            turns = CLUSTER_INTERPRET_TURNS if heavy else 2
            logger.info("[%s][sdk] cluster batch %s: %d pathways, %s",
                        job_id, "/".join(u["id"] for u in unit_batch), len(batch),
                        "full tool loop" if heavy else "single-shot")
        try:
            res = await Runner.run(agents[agent_key], prompt, context=ctx, max_turns=turns)
        except Exception as e:
            if not (unit_batch and agent_key == "interpret"):
                raise
            # A tool loop that runs out of turns (an 11-pathway cluster can
            # ask for a timecourse per member) or dies on the gateway must not
            # take its whole cluster out of the report: answer it in one call
            # from the same brief instead. Measured: 4 of 14 batches were lost
            # this way in one servlet run before this fallback existed.
            logger.warning("[%s][sdk] cluster batch %s: tool loop failed (%s: %s); "
                           "retrying single-shot", job_id,
                           "/".join(u["id"] for u in unit_batch), type(e).__name__,
                           str(e)[:120])
            res = await Runner.run(agents["interpret_light"], prompt, context=ctx,
                                   max_turns=2)
        return _remap_citation_indices(str(res.final_output), local_to_global)

    if partition is not None:
        # One unit per cluster (never split), small units packed together,
        # standalone pathways alone, the 'further' pool in chunks; the
        # fan-out is bounded because there are ~5x more batches than the
        # top-15 path ever ran.
        units = clusters_mod.build_units(partition, ctx_by_id)
        unit_batches = clusters_mod.pack_units(units, CLUSTER_BATCH_MAX)
        bsem = asyncio.Semaphore(CLUSTER_CONCURRENCY)

        async def _bounded_batch(ub):
            async with bsem:
                return await _one_batch(clusters_mod.batch_pathways(ub), ub)

        stats["cluster_units"] = len(units)
        batches = unit_batches
        batch_reports = await asyncio.gather(*[_bounded_batch(ub) for ub in unit_batches],
                                             return_exceptions=True)
    else:
        batches = [pathways[i:i + AI_PATHWAYS_PER_BATCH]
                   for i in range(0, len(pathways), AI_PATHWAYS_PER_BATCH)]
        batch_reports = await asyncio.gather(*[_one_batch(b) for b in batches],
                                             return_exceptions=True)
    failed_batches = 0
    for i, b in enumerate(batch_reports):
        if isinstance(b, Exception):
            failed_batches += 1
            label = ("/".join(u["id"] for u in batches[i]) if partition is not None
                     else "batch %d" % (i + 1))
            logger.warning("[%s][sdk] interpretation batch %s failed: %s: %s", job_id,
                           label, type(b).__name__, str(b)[:160])
    if failed_batches:
        logger.warning("[%s][sdk] %d of %d interpretation batches failed", job_id,
                       failed_batches, len(batch_reports))
    stats["batches_failed"] = failed_batches
    batch_reports = [b for b in batch_reports if not isinstance(b, Exception)]
    stats["interpret_s"] = time.time() - t0
    # Some runs finish with zero citations while others on identical settings
    # reach 29. Counting markers at each stage says whether the batches never
    # cited, or the synthesis dropped citations the batches had supplied --
    # two different bugs that look the same from the outside.
    import re as _re
    stats["batch_citations"] = sum(
        len(set(_re.findall(r'\[(\d+)\]', b or ""))) for b in batch_reports)
    stats["batches_with_citations"] = sum(
        1 for b in batch_reports if _re.search(r'\[\d+\]', b or ""))
    stats["batches"] = len(batch_reports)
    logger.info("[%s][sdk] %d batches, %d citing, %d distinct markers",
                job_id, len(batch_reports), stats["batches_with_citations"],
                stats["batch_citations"])

    # -- Phase 5: synthesis --------------------------------------------------
    _hb("synthesizing", 78, "Synthesizing report...")
    t0 = time.time()
    synth_prompt = prompts_mod.build_synthesis_prompt_v2(
        batch_reports, experiment_design, organism_name, unique_papers)
    # Round-3 KEEP (evolve loop): the synthesis must SEE the numbers, not
    # merely know a table will be appended -- prompt-visibility measured
    # claim +0.029 / rank +0.027 on the live arm.
    try:
        synth_prompt += ("\n\n## Pathway significance table (from the data)\n"
                         + render_pathway_table(pathways))
    except Exception:
        pass
    if partition is not None:
        # The cluster map: which pathways belong together and why, with
        # every member's global rank, plus the rules that keep the report's
        # emphasis on rank while its themes follow the clusters.
        try:
            synth_prompt += "\n\n" + clusters_mod.render_synthesis_block(partition, ctx_by_id)
        except Exception as e:
            logger.warning("[%s][sdk] cluster synthesis block failed: %s", job_id, e)
    # Pin the citable range. Measured: the synthesis emitted 82 distinct markers
    # against 47 real papers -- it numbers citations past the end of the list it
    # was given. render_references_section drops the invalid ones, so nothing
    # fabricated ships, but each invented marker still costs a quote lookup and
    # a verification slot, and the dropped claims lose their support for no
    # reason.
    # Breadth and candour, both of which the reports were short on. The
    # analysis enriches ~25 pathways and the write-up was developing three or
    # four themes, so most of what the run found never reached the reader; and
    # the discordances the data plainly shows (mRNA against protein, chromatin
    # against transcription) were being smoothed into a tidy narrative instead
    # of reported. Neither instruction names a gene, pathway or finding -- the
    # data decides what fills them.
    synth_prompt += (
        "\n\n## Cover what the analysis actually found\n"
        "A complete pathway table is appended automatically, so do not rewrite "
        "one -- but the table is a reference, not the analysis. **Every enriched "
        "pathway above must be named somewhere in your prose**, grouped into "
        "themes, with the genes driving it and what its direction means for this "
        "experiment. A pathway that appears only as a table row has been listed, "
        "not interpreted, and interpretation is the part only you can do.\n\n"
        "Give the strongest findings full paragraphs; group the rest into "
        "thematic sections (metabolic, immune/inflammatory, chromatin, cell "
        "cycle, signalling, whatever the data suggests) and cover each theme's "
        "pathways together by name. A run that enriches twenty-five pathways and "
        "discusses four has hidden most of its own result from the reader.\n\n"
        "## State the awkward parts\n"
        "A caveat is a finding about the data's limits, not a weakness in the "
        "writing. Specifically:\n"
        "- **Disagreeing layers:** say so rather than resolving it in prose -- "
        "mRNA moving without protein, chromatin opening without transcription, "
        "a regulator whose targets do not follow.\n"
        "- **Marginal results:** report them as trends WITH the number "
        "(\"p=0.06, short of significance\"). A real trend stated honestly is "
        "worth more than one promoted to a finding or dropped in silence. When "
        "you discuss a pathway, state which of its omic layers reached "
        "significance and which did not -- a metabolic pathway carried by gene "
        "expression while proteomics sits at p=1.0 is a materially different "
        "finding from one supported by both, and the reader cannot tell them "
        "apart unless you say.\n"
        "- **Annotation artefacts:** where a pathway's database name refers to "
        "a disease unrelated to this experiment, say the enrichment is real but "
        "the label is an artefact of how the database is named.\n"
        "- **Single-layer pathways:** name which lone assay carries them.\n"
        "- **Control points:** where the data suggests one step gates a "
        "process, say which and why -- and equally, where several changes look "
        "like consequences rather than causes.\n"
        "- **Hypotheses:** mark every mechanistic proposal as remaining to be "
        "tested, and say what experiment would test it.\n"
        "- **Mixed directions:** if a group of pathways moves both ways, say so "
        "rather than describing them as uniformly up or down.")

    if unique_papers:
        valid = sorted(p["ref_index"] for p in unique_papers)
        synth_prompt += (
            "\n\n## Citation index range (strict)\n"
            "The ONLY valid citation numbers are [%d] through [%d]. Every one of "
            "them refers to a specific paper listed above. Do not write a "
            "citation number outside this range and do not invent new ones -- a "
            "marker with no matching paper is deleted along with the claim it "
            "supports, so inventing one loses you a finding."
            % (valid[0], valid[-1]))
    # Narrative and pathway table in parallel. Requiring one call to produce
    # both put a per-pathway table on the critical path: synthesis ran 81s at 24
    # pathways and 206s at 30, which is what pushed the highest-scoring
    # configuration past the time budget. The two outputs share no state, so the
    # cost of the table becomes max() instead of sum().
    # Generated in ONE call, deliberately. Splitting the narrative from the
    # pathway table did cut synthesis from 206s to 89s, but the score fell 17.00
    # -> 10.00: written separately the table lost the biology, because the model
    # was no longer interpreting each pathway in the context of the analysis it
    # had just written. The coupling was doing real work, and buying 100s by
    # discarding it was a bad trade.
    # Each draft is bounded (SDK_LONG_CALL_TIMEOUT); a draft that never comes
    # back is an exception here like any other, and only a run with no draft
    # at all fails.
    drafts = await asyncio.gather(
        *[bounded(Runner.run(agents["synth"], synth_prompt, context=ctx, max_turns=3),
                  SDK_LONG_CALL_TIMEOUT, label="synthesis draft %d" % i)
          for i in range(SDK_SYNTH_DRAFTS)],
        return_exceptions=True)
    failures = [d for d in drafts if isinstance(d, BaseException)]
    for f in failures:
        logger.warning("[%s][sdk] synthesis draft failed: %s: %s",
                       job_id, type(f).__name__, f)
    drafts = [str(d.final_output) for d in drafts if not isinstance(d, BaseException)]
    if not drafts:
        raise RuntimeError("all synthesis drafts failed (%s)" % (
            "; ".join("%s: %s" % (type(f).__name__, f) for f in failures) or "no drafts"))
    report, draft_scores = _pick_best_draft(drafts, pathways, unique_papers)
    stats["synth_drafts"] = len(drafts)
    stats["draft_scores"] = draft_scores
    # The model sometimes cites by identifier -- "(PMID 42565800)", 90 times
    # in one live draft -- and keeps "[N]" for a bibliography of its own.
    # Every downstream reader matches "[N]" in the body, so those citations
    # are converted here, deterministically, from the exact PMID -> index
    # map; done before the top-up gate so a draft that cited well by PMID is
    # not sent for a rewrite it does not need.
    report = resolve_pmid_mentions(report, {p["ref_index"]: p for p in unique_papers})
    # Close the gaps the draft left, before anything else touches the report.
    # One targeted revision naming exactly what is missing, rather than another
    # sample of the same distribution.
    #
    # Off by default. Measured cost/benefit: it filled 15 unmentioned pathways
    # and 1 caveat, and the run went 325s -> 514s (99s of gap-fill plus a
    # synthesis inflated to 308s by the longer prompt) while honesty markers
    # FELL from 5 to 3. The gaps it names are real and the detection is sound,
    # but asking for them mid-pipeline costs more than it returns. Worth
    # enabling where wall-clock is not a constraint, or worth moving to a
    # post-hoc report on what a run omitted rather than a revision pass.
    missing_pw, gaps = ((), ())
    if SDK_GAP_FILL:
        missing_pw, gaps = _completeness_gaps(report, pathways)
    stats["gaps_pathways"] = len(missing_pw)
    stats["gaps_caveats"] = len(gaps)
    if missing_pw or gaps:
        t_gap = time.time()
        request = ["Your report is below. Revise it to close these specific "
                   "gaps, changing nothing else -- keep every existing finding, "
                   "number and citation exactly as written.\n"]
        if missing_pw:
            request.append(
                "NOT YET DISCUSSED -- these pathways were enriched by this "
                "analysis but appear nowhere in your prose. Add each to the "
                "relevant thematic section with the genes driving it and what "
                "its direction means here:\n%s\n"
                % "\n".join("  - %s" % n for n in missing_pw[:20]))
        if gaps:
            request.append("MISSING CAVEATS -- each is warranted by this "
                           "dataset:\n%s\n" % "\n".join("  - %s" % g for g in gaps))
        try:
            revised = await bounded(Runner.run(
                agents["synth"], "\n".join(request) + "\n\n## Report\n\n" + report,
                context=ctx, max_turns=3), SDK_LONG_CALL_TIMEOUT, label="gap-fill")
            candidate = str(revised.final_output)
            # Only accept a revision that grew the report; a "revision" that
            # summarises it away would trade real content for checklist items.
            if len(candidate) >= 0.85 * len(report):
                report = candidate
                stats["gap_fill_applied"] = True
            else:
                logger.warning("[%s][sdk] gap-fill discarded (%d -> %d chars)",
                               job_id, len(report), len(candidate))
        except (Exception, asyncio.TimeoutError) as e:
            logger.warning("[%s][sdk] gap-fill failed: %s: %s",
                           job_id, type(e).__name__, e)
        stats["gap_fill_s"] = time.time() - t_gap
        logger.info("[%s][sdk] gap-fill: %d pathways, %d caveats requested",
                    job_id, len(missing_pw), len(gaps))

    # Append the enrichment table from the data. Placed after synthesis and
    # before the references rebuild, so citation extraction sees the prose the
    # model wrote rather than table rows -- a quote lookup pointed at a table
    # cell has nothing to find.
    # In cluster mode the report carries NO enrichment table: the full table
    # stays in the synthesis prompt, where its grounding effect was measured,
    # but at the end of a report a 100-row table is noise for a reader and
    # nothing a paper would include -- the Pathway Clusters table below is the
    # one deterministic block that earns its place there (it defines the
    # cluster ids the prose uses). The plain path keeps its table as before.
    table = "" if partition is not None else render_pathway_table(pathways)
    if table:
        report = report.rstrip() + "\n\n" + table + "\n"
    cluster_table = ""
    if partition is not None:
        try:
            cluster_table = clusters_mod.render_partition_table(partition, ctx_by_id)
            report = report.rstrip() + "\n\n" + cluster_table + "\n"
            # The reading note goes under the report's title (or at the very
            # top): the ids must be explained before the reader meets them.
            note = clusters_mod.render_reading_note(partition)
            if note and note not in report:
                lines = report.split("\n", 1)
                if lines[0].lstrip().startswith("# ") and len(lines) > 1:
                    report = lines[0] + "\n\n" + note + "\n" + lines[1]
                else:
                    report = note + "\n\n" + report
        except Exception as e:
            logger.warning("[%s][sdk] cluster table failed: %s", job_id, e)
    stats["synth_s"] = time.time() - t0
    stats["synth_citations"] = len(set(re.findall(r'\[(\d+)\]', str(report))))

    # Whether synthesis cites 7 papers or 25 from the same pool is close to a
    # coin flip -- that swing, not any ceiling, is what stops citations and
    # runtime landing inside budget together. When it under-cites, ask once
    # more, naming the papers it passed over.
    #
    # Safe to ask for more because nothing here decides what survives: each
    # added citation still needs a verbatim supporting sentence from its own
    # paper (_collect_cited_quotes) and still faces the verifier. A paper that
    # does not support anything yields no quote and is redacted. So this raises
    # the number of *attempts*, never the number of unsupported claims.
    # Count only markers that resolve to a retrieved paper. Counting raw markers
    # made this gate meaningless: the synthesis invents indices (79 markers
    # against 11 real papers), so the threshold was always satisfied and the
    # top-up never once fired on runs that badly needed it.
    valid_indices = {p["ref_index"] for p in unique_papers}
    # Count markers in the BODY only. A synthesis that lists its papers in a
    # References section of its own but never cites them in the text (seen
    # live: 25 entries, 0 in-text markers, 0 rendered) must trigger the
    # top-up, and counting the bibliography's [N] hid exactly that case.
    # The acceptance test below uses the same helper, so the two cannot
    # disagree -- they did once, and a rewrite whose whole contribution was
    # a bibliography was accepted as "56 citations added".
    cited_now = count_body_citations(str(report), valid_indices)
    uncited = [p for p in unique_papers if p["ref_index"] not in cited_now]
    if uncited and len(cited_now) < SDK_MIN_CITATIONS:
        listing = "\n".join(
            "[%d] %s — %s" % (p["ref_index"], p.get("title", "")[:110],
                              (p.get("abstract") or "")[:220])
            for p in uncited[:30])
        t_top = time.time()
        # Optional pass, bounded: the report is already complete without it,
        # so a top-up that outlives SDK_LONG_CALL_TIMEOUT is skipped, not
        # waited on. (Two live runs sat 90+ min here before this bound existed:
        # this call echoes the whole report, and on the CSIC gateway that
        # answer outran the per-attempt budget until streaming was added.)
        try:
            topped = await bounded(Runner.run(
                agents["synth"],
                "Here is your report:\n\n%s\n\n"
                "These retrieved papers are not cited anywhere in it:\n\n%s\n\n"
                "Return the SAME report with citations added wherever one of "
                "these papers genuinely supports a statement you already make. "
                "Change nothing else: no new findings, no rewritten analysis, no "
                "altered numbers. Add [N] only where that paper really does "
                "support that sentence -- a citation that does not fit is "
                "removed later along with the claim it sits on, so forcing one "
                "in costs you the finding. Leaving a paper uncited is a fine "
                "outcome." % (report, listing),
                context=ctx, max_turns=3), SDK_LONG_CALL_TIMEOUT, label="citation top-up")
            candidate = resolve_pmid_mentions(
                str(topped.final_output), {p["ref_index"]: p for p in unique_papers})
            # Guard against the "rewrite" degenerating into a summary: keep the
            # top-up only if it preserved the report and added BODY citations.
            added = len(count_body_citations(candidate, valid_indices))
            if len(candidate) > 0.6 * len(str(report)) and added > len(cited_now):
                report = candidate
                stats["topup_added"] = added - len(cited_now)
            else:
                stats["topup_rejected"] = True
                logger.warning("[%s][sdk] citation top-up discarded (len %d->%d, "
                               "citations %d->%d)", job_id, len(str(report)),
                               len(candidate), len(cited_now), added)
        except (Exception, asyncio.TimeoutError) as e:
            stats["topup_failed"] = "%s: %s" % (type(e).__name__, e)
            logger.warning("[%s][sdk] citation top-up failed: %s: %s",
                           job_id, type(e).__name__, e)
        stats["topup_s"] = time.time() - t_top
    if stats.get("batch_citations") and not stats["synth_citations"]:
        logger.warning("[%s][sdk] synthesis dropped ALL citations: batches "
                       "supplied %d markers, report kept none",
                       job_id, stats["batch_citations"])

    # "[17, 18]" -> "[17], [18]" before anything reads a marker: quote
    # collection, rendering, verification and renumbering all match single
    # "[N]" markers, and an unsplit multi-citation is invisible to every one of
    # them -- the shipped report then cites entries its References section does
    # not carry.
    report = normalize_citation_markers(report)
    # Deterministic references rebuild from the paper index -- asking the model
    # to hit the parser's format by instruction fails most of the time.
    quotes = _collect_cited_quotes(llm_for_quotes, report, ctx.paper_index, job_id)
    report, rendered = render_references_section(report, ctx.paper_index, quotes)
    stats["refs_rendered"] = len(rendered)
    stats["quotes_supplied"] = len(quotes)
    logger.info("[%s][sdk] references rebuilt: %d rendered, %d quotes",
                job_id, len(rendered), len(quotes))

    # -- Phase 5b: iterative verify -> correct, the SDK's turn at pipeline.py's
    _hb("verifying", 85, "Verifying citations...")
    # Phase 4. Same budget (AI_MAX_VERIFICATION_ITERATIONS), same per-citation
    # sub-agent shape, same correction prompt; Runner and asyncio replace
    # complete_with_tools and ThreadPoolExecutor. Without this the SDK arm would
    # be scored on an uncorrected report against a corrected one.
    t0 = time.time()
    verify_iters = 0
    previous_failures = None
    for _iteration in range(AI_MAX_VERIFICATION_ITERATIONS):
        citations = parse_references_section(report)
        to_verify = [c for c in citations if c.get("cited_text")]
        if not to_verify:
            break
        verify_iters += 1
        # Verification is ~60% of wall-clock (138-216s of a 236-376s run), and
        # it is embarrassingly parallel: each citation is checked independently.
        # The gateway takes the fan-out and tokens are not a constraint here, so
        # the cap exists only to avoid hammering a shared service.
        vsem = asyncio.Semaphore(SDK_VERIFY_CONCURRENCY)

        async def _verify_one(cit):
            async with vsem:
                try:
                    r = await run_hedged(
                        agents["verify"],
                        prompts_mod.build_verification_prompt(
                            cit["claim_sentence"], cit["cited_text"], cit["ref_index"]),
                        ctx, max_turns=6,
                        label="verify[%s]" % cit["ref_index"])
                    return cit, str(r.final_output)
                except Exception as e:  # a dead sub-agent must not pass as verified
                    logger.warning("[%s][sdk] verifier raised for [%s]: %s",
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
        logger.info("[%s][sdk] VERIFY iter %d: %d checked, %d failed",
                    job_id, _iteration + 1, len(to_verify), len(failed))
        if not failed:
            break
        # Stop when a round fixes nothing. Where the citation is simply wrong --
        # the paper does not say it -- rewriting cannot rescue it, so further
        # rounds re-verify the same failures and the loop spends its whole
        # budget standing still: 10 failed, 10 failed, 10 failed cost ~200s of a
        # 384s run. The programmatic net still redacts whatever remains.
        if previous_failures is not None and len(failed) >= previous_failures:
            logger.info("[%s][sdk] verification made no progress (%d -> %d "
                        "failures); stopping early", job_id, previous_failures,
                        len(failed))
            break
        previous_failures = len(failed)
        # On the final permitted iteration a correction is a rewrite nothing
        # will re-verify, and the programmatic net redacts whatever still fails
        # either way -- so it buys no accuracy and costs a full synthesis pass
        # (~70s of a 347s run).
        if _iteration == AI_MAX_VERIFICATION_ITERATIONS - 1:
            logger.info("[%s][sdk] final iteration: skipping correction rewrite "
                        "(%d citations will be redacted instead)", job_id, len(failed))
            break

        # The rewrite is a full-report echo like the top-up, and it is
        # optional in the same way: the programmatic net (phase 6) redacts
        # whatever still fails. So a rewrite that times out or raises ends the
        # loop with the report as it stands, rather than ending the run.
        try:
            corr = await bounded(Runner.run(
                agents["synth"],
                "Here is your report:\n\n%s\n\n%s"
                % (report, prompts_mod.build_correction_prompt(report, failed)),
                context=ctx, max_turns=3), SDK_LONG_CALL_TIMEOUT,
                label="correction rewrite %d" % (_iteration + 1))
        except (Exception, asyncio.TimeoutError) as e:
            logger.warning("[%s][sdk] correction rewrite failed: %s: %s; keeping "
                           "the report and leaving %d citation(s) to the "
                           "programmatic net", job_id, type(e).__name__, e,
                           len(failed))
            stats["correction_failed"] = "%s: %s" % (type(e).__name__, e)
            break
        report = resolve_pmid_mentions(str(corr.final_output), ctx.paper_index)
        # The rewrite re-authors the references, so re-render them from the
        # paper index; without this the loop verifies on iteration 1 and then
        # finishes with an unparseable section again. A rewrite also
        # reintroduces "[17, 18]" markers, so they are re-split first.
        report = normalize_citation_markers(report)
        quotes.update(_collect_cited_quotes(llm_for_quotes, report, ctx.paper_index,
                                            job_id, known=quotes))
        report, _ = render_references_section(report, ctx.paper_index, quotes)
    stats["verify_loop_s"] = time.time() - t0
    if partition is not None:
        # A correction rewrite re-authors the whole report and can drop the
        # appended data tables; they are data, not prose, so put them back.
        report = _reattach_blocks(report, [
            ("## Enriched Pathway Summary", table),
            ("## Pathway Clusters", cluster_table),
        ])
        note = clusters_mod.render_reading_note(partition)
        if note and note not in report:
            report = note + "\n\n" + report
    stats["verify_iterations"] = verify_iters

    # -- Phase 6: the programmatic safety net ---------------------------------
    # verification.py is domain code, not orchestration: whatever the agents
    # concluded, unverifiable citations are redacted here, deterministically.
    t0 = time.time()
    final = verify_report_v2(report, gene_whitelist, unique_papers, job_instance)
    if final.get("failed_citations"):
        report, removed = redact_unverified_v2(report, final["failed_citations"])
        final["redacted_count"] = removed
    report, citation_mapping = renumber_citations(report)
    # ...and then put the entries back in the order of the labels they now
    # carry. Renumbering rewrites the markers where they stand, so a section
    # rendered in ascending old index order ends up printed as [1], [5], [3],
    # [2], [4] -- every entry pointing at the right paper, the list itself
    # unreadable. Nothing downstream can catch it, because the citations are
    # all still valid; only the reader sees it. This call existed in
    # pipeline.py (0616e2df) and was dropped when the SDK workflow replaced
    # that module, so every report shipped since has been scrambled.
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
    return report, unique_papers, ctx


def run_agent_workflow(job_instance, job_id, experiment_design, budgets=None,
                     hooks=None):
    """Synchronous entry point.

    PySiQ hands us a worker thread, so we own an event loop here rather than
    assuming one. ``asyncio.run`` refuses to nest, which is exactly the
    threaded/async friction this experiment is meant to measure.
    """
    budgets = budgets or {"max_pathways": AI_MAX_PATHWAYS,
                          "max_search_tasks": AI_MAX_SEARCH_TASKS}
    stats = {}
    t0 = time.time()

    async def _with_deadline():
        # The last line of defence against "still running" as a permanent
        # state. Every phase has its own cap; this one catches whatever they
        # miss, and turns it into an error the UI can show and the user can
        # retry, instead of a heartbeat that keeps a dead run looking alive.
        try:
            return await asyncio.wait_for(
                _run_async(job_instance, job_id, experiment_design, budgets,
                           stats, hooks=hooks),
                timeout=AI_MAX_RUN_SECONDS)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "The interpretation exceeded its %d-minute limit and was "
                "stopped. The literature gateway was slow to answer; please "
                "try again later." % int(AI_MAX_RUN_SECONDS // 60))

    report, papers, ctx = asyncio.run(_with_deadline())
    stats["total_s"] = time.time() - t0
    return {"report": report, "papers": papers, "stats": stats}


class _Heartbeat:
    """Background thread that touches the job's updatedAt every interval.

    The servlet's stale-job check declares a run dead when its record has not
    changed for AI_STALE_JOB_TIMEOUT (10 min). The workflow only reports
    progress at phase boundaries, and the interpretation phase alone can run
    longer than that -- batches with tool loops serialise on the gateway --
    so without this a healthy run was flipped to "error" mid-interpretation
    (measured: 'interpreting 45' at 120 s, watchdog at 721 s, batches still
    running). Runs from before the semaphore is acquired, so a job waiting for
    a permit is also seen as alive rather than dead.
    """

    def __init__(self, job_id, interval=30):
        self._job_id = job_id
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="ai-heartbeat-%s" % job_id)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        from src.common.DAO.AIInterpretDAO import AIInterpretDAO
        while not self._stop.wait(self._interval):
            # Best-effort, but never silent, and the connection is closed in a
            # finally: DBManager builds a new MongoClient per DAO, and this
            # beats every 30 s for the whole life of a job.
            dao = None
            try:
                dao = AIInterpretDAO()
                dao.touch(self._job_id)
            except Exception:
                logger.debug("[%s] heartbeat touch failed", self._job_id,
                             exc_info=True)
            finally:
                if dao is not None:
                    dao.closeConnection()


def run_ai_agent(job_id, experiment_design, RESPONSE):
    """Servlet entry point — drop-in replacement for pipeline.run_ai_agent.

    Same contract the servlet and PySiQ rely on: DAO progress milestones the
    UI polls, pathway-index and papers persistence, cancellation via
    _cancel_flags, the concurrency semaphore, and the same RESPONSE payloads.
    The agent workflow (Runner-driven phases) happens inside run_agent_workflow.
    """
    from src.common.JobInformationManager import JobInformationManager
    from src.common.DAO.AIInterpretDAO import AIInterpretDAO

    dao = None
    acquired = False
    heartbeat = _Heartbeat(job_id)
    try:
        dao = AIInterpretDAO()
        dao.save_progress(job_id, {"status": "extracting", "percent": 5,
                                   "detail": "Loading analysis results..."})
        dao.save_progress(job_id, {"experimentDesign": experiment_design or ""})
        heartbeat.start()

        job_instance = JobInformationManager().loadJobInstance(job_id)
        if job_instance is None:
            raise UserWarning("Job %s was not found." % job_id)

        _agent_semaphore.acquire()
        acquired = True

        hooks = {
            "progress": lambda s, p, d: dao.save_progress(
                job_id, {"status": s, "percent": p, "detail": d}),
            "cancelled": lambda: bool(_cancel_flags.get(job_id)),
            "pathways": lambda pw: dao.save_pathway_index(job_id, pw),
            "partition": lambda part: dao.save_clusters(job_id, part),
        }
        # AI_FULL_AGENT=1 swaps the fixed six-phase workflow for the Lead
        # Interpreter loop (agent_loop.py; design in docs/diagrams/
        # paintomics-ai-agent-proposal.drawio). Same contract either way:
        # {report, papers, stats}, the same DAO milestones, the same gate.
        if os.getenv("AI_FULL_AGENT", "0") == "1":
            from src.classes.AIInterpret.agent_loop import run_agent_loop_workflow
            # A retry appends to the previous run's journal otherwise: the first
            # live re-run left 27 dead events sitting above 34 live ones in one
            # array, with nothing marking the boundary. The journal describes
            # THIS run.
            dao.save_progress(job_id, {"toolTrace": [], "notebook": []})
            hooks["tool_event"] = lambda e: dao.append_tool_event(job_id, e)
            hooks["notebook"] = lambda nb: dao.save_progress(
                job_id, {"notebook": nb})
            out = run_agent_loop_workflow(job_instance, job_id,
                                          experiment_design, hooks=hooks)
        else:
            out = run_agent_workflow(job_instance, job_id, experiment_design,
                                     hooks=hooks)
        report = out.get("report") or ""
        papers = out.get("papers") or []
        if papers:
            dao.save_papers(job_id, papers)
        # A finished run with an empty report is a failure wearing success's
        # clothes (two such runs scored as data in evolve round 5); refuse it.
        if not report.strip():
            raise RuntimeError("The agent workflow produced an empty report.")

        known = {p.get("ref_index") for p in papers}
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", report)} & known
        with_full = sum(1 for p in papers if p.get("ref_index") in cited
                        and p.get("full_text_available"))
        detail = (f"Ready — {len(cited)} of {len(papers)} retrieved papers "
                  f"cited ({with_full} with full text)")
        stats = out.get("stats") or {}
        dao.save_progress(job_id, {
            "status": "done", "percent": 100, "detail": detail,
            "report": report,
            # The stored contract: "verification" is verify_report_v2's dict
            # (references_section_found, citations_checked, failed_citations);
            # timings and counters live beside it, not inside it.
            "verification": stats.get("verification") or {},
            "stats": {k: v for k, v in stats.items() if k != "verification"},
        })
        RESPONSE.setContent({"success": True, "jobID": job_id, "status": "done"})

    except InterruptedError:
        if dao:
            dao.save_progress(job_id, {"status": "cancelled", "percent": 0,
                                       "detail": "Cancelled by user"})
        RESPONSE.setContent({"success": True, "jobID": job_id,
                             "status": "cancelled"})
    except Exception as ex:
        logger.exception("agent workflow failed for job %s", job_id)
        if dao:
            try:
                dao.save_progress(job_id, {"status": "error", "percent": 0,
                                           "detail": str(ex)})
            except Exception:
                pass
        from src.common.ServerErrorManager import handleException
        handleException(RESPONSE, ex, __file__, "run_ai_agent")
    finally:
        if acquired:
            _agent_semaphore.release()
        heartbeat.stop()
        _cancel_flags.pop(job_id, None)
        if dao:
            try:
                dao.closeConnection()
            except Exception:
                pass
