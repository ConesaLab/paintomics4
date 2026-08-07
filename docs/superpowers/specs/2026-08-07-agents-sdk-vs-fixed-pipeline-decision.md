# Agents SDK vs the fixed pipeline

> ## FINAL ANSWER (2026-08-07, after 24 iterations / 68 measured runs)
>
> **The framework is the least important variable in this system. Choose either;
> spend the effort elsewhere.**
>
> Both arms were built, repaired to parity, and run repeatedly on the same job.
> The SDK arm's best runs edge ahead, but the gap is far inside the run-to-run
> variance of a single configuration (score 11-17, citations 11-48, 150-514s on
> *fixed* settings). No comparison in this document — or in
> `runs/ai_loop/index.md` — separates the arms by more than the noise.
>
> **What actually moved quality, in order of effect:**
>
> | change | effect |
> |---|---|
> | references rendered from data, not written by the model | citations checked 0 -> 20+; verification went from never running to converging |
> | `search`/`fetch_abstracts` routed through their own retry wrapper | 429s 5-9/run -> 0; searches lost -> 0 |
> | supplying `experimentDesign` | quotes 1 -> 10; score 8.25 -> 11.50 |
> | multi-claim quote lookup (rank claims by digit density) | quote yield 32% -> 84% |
> | batched PubMed fetch (N+1 round trips, not 2N) | 29 papers/40s -> 440 abstracts/35s |
> | straggler hedging on short calls | phases ~halved; one call in 16 stalls 60s |
> | asking the report to cover what was found and state its caveats | score 8.50 -> 17.00 |
>
> Not one of those is a framework property. Six were bugs or contract failures
> in code shared by both arms.
>
> **The SDK-specific findings that do stand**, and matter to anyone who adopts
> it here: `output_type` silently disables tool calling on vLLM (a citation
> verifier so configured made 0 tool calls and still returned
> `supports_claim: true`); model IDs containing `/` die in `MultiProvider`; and
> `asyncio.gather` inherits the gateway's minute-long tail latency unless you
> hedge it yourself.
>
> **Practical recommendation:** stay on `pipeline.py`, because it is the arm in
> production and the SDK offers no measured quality gain to justify a migration
> — not because the SDK is worse. If you adopt the SDK for other reasons, the
> three findings above are the traps.
>
> Full record: `runs/ai_loop/index.md`.

> ## ⚠️ THE ORIGINAL VERDICT BELOW WAS RETRACTED (2026-08-07, same day)
>
> This document concluded "keep the fixed pipeline". That conclusion was
> **measured on a broken substrate and is not reliable.** Two defects invalidate
> it:
>
> 1. **Verification almost never ran.** The synthesis emitted a parseable
>    `### References` section in roughly 1 run in 6, so most citations were
>    never checked in *either* arm. The quality numbers were measuring broken
>    plumbing, not architecture.
> 2. **The SDK arm was missing a piece the incumbent has.** It handed each batch
>    global paper indices instead of local ones, so the model renumbered or
>    stopped citing. That, not the SDK, produced the "9 failed citations" cited
>    below as evidence against it.
>
> Both are fixed. On the repaired substrate the SDK arm is **competitive or
> ahead** (see `runs/ai_loop/index.md`, iter04 onward). The framework question
> is **open**.
>
> **What still stands from this document:** everything in "Why the SDK loses"
> points 1-3 (the `output_type`/tool-calling trap, the model-ID prefix failure,
> the async/threading friction) — those were measured directly and reproduce.
> Point 4 was explicitly flagged as an implementation gap and has since been
> closed. Point 5 ("no quality win") is withdrawn.
>
> Live status: `runs/ai_loop/index.md`.

**Date:** 2026-08-07
**Question:** should `AIInterpret` move to the OpenAI Agents SDK, or stay on the
hand-rolled `pipeline.py` + `llm_client.py`?
**Answer at the time:** stay. **Now: unresolved** — see the retraction above.
The schema-enforced JSON work it recommended was adopted and does stand.

## How it was measured

Both arms ran on job `vyfKO754n4` (STATegra, mouse B3, 6 omics, 44 significant
pathways) against the CSIC gateway (`deepseek-ai/DeepSeek-V4-Flash-0731`,
vLLM 0.26.0), with identical budgets (15 pathways, 8 search tasks).

The SDK arm (`sdk_pipeline.py`) shares everything that is not orchestration --
same prompts, same tool bodies, same PubMed client, same context builders, same
programmatic verification. Only `Runner` vs `complete_with_tools`, and pydantic
`output_type` vs text parsing, differ. Anything else would have measured a
prompt rewrite rather than an architecture.

Scoring uses tellme's own selector criteria (`runs/loop/select_best_draft.py`),
including its decision rule:

> HARD GATE first: a draft that fails faithfulness is DISQUALIFIED outright, no
> matter how complete -- correctness beats completeness.

## Results

| arm | tellme score | coverage | honesty | ANTI | failed citations | time |
|---|---|---|---|---|---|---|
| fixed (baseline) | 9.00 | 6/20 | 2 | 0 | **1** | 238s |
| SDK (+ verify loop) | 9.00 | 5/20 | 1 | 0 | **9** | 103s |
| SDK (no verify loop) | 12.25 | 8/20 | 3 | 0 | **9** | 129s |

The SDK is ~2x faster, and its highest-scoring variant is the one that skipped
verification -- the "more complete, less faithful" case the hard gate exists to
reject. On content the two are level (9.00 vs 9.00); on grounding the incumbent
wins decisively (1 failed citation vs 9).

## Why the SDK loses

**1. `output_type` silently disables tool calling. This is the disqualifying
finding.** `output_type` compiles to `response_format`, and vLLM's grammar
constrains the first token to `{`, so the model cannot emit a tool call. An
identical verifier agent, run twice:

| | tool calls | quoted the paper | verdict |
|---|---|---|---|
| with `output_type` | **0** | no | `supports_claim: true` |
| without | 3 | yes (fold-change + assay) | correct |

The schema-typed verifier returned `supports_claim: true` having read nothing,
its `reasoning` field narrating the check it had not performed. A citation
verifier that rubber-stamps is worse than none: it converts "unchecked" into
"checked and passed". Reproduce with
`scratchpad/test_sdk_tools_vs_schema.py`.

**2. Model IDs with slashes are rejected.** A model *string* routes through the
SDK's `MultiProvider`, which reads the left of `/` as a provider prefix, so
`deepseek-ai/DeepSeek-V4-Flash-0731` dies with `UserError: Unknown prefix:
deepseek-ai`. Every CSIC model ID has a slash. Workaround: pass a concrete
`OpenAIChatCompletionsModel`.

**3. Async-first collides with PySiQ's threads.** The entry point must own an
`asyncio.run` inside a PySiQ worker. And `asyncio.gather` is unbounded: the
first SDK run earned a wall of PubMed 429s, where the threaded arm gets a cap
free from `ThreadPoolExecutor(max_workers=N)`. Fixable with a semaphore -- but
the idiom invites the bug rather than preventing it.

**4. Rewriting orchestration silently broke a downstream contract.** The SDK
arm's synthesis emitted `Cited Text` blocks without `[N]` markers, so
`parse_references_section` found nothing, the verification loop ran zero
iterations, and all 9 citations were bulk-redacted. The report still *looked*
excellent -- 3,400 words, nine honest caveats -- while its entire literature
layer had been stripped. This one is an implementation gap in the SDK arm, not
an SDK defect; it is listed because it is exactly the migration risk: the
citation index remapping is domain glue that must be re-derived and
re-verified, and getting it subtly wrong fails silently.

**5. There is no quality win to pay for any of that.** Level on content,
behind on grounding.

## What was adopted instead

`response_format` schema enforcement now lives in `llm_client.py`:

- `complete(..., response_format=)` and `complete_json(...)` -- schema first,
  hand-rolled parser as fallback.
- `complete_with_tools_json(...)` -- runs the tool loop **unconstrained**, then
  coerces the finished answer. This is the deliberate opposite of trap #1.
- Endpoint capability is probed once and remembered; a 400 demotes the endpoint
  and every caller degrades to today's behaviour. Verified working on CSIC.
- Wired into 3 of the 4 parsers: `_parse_search_plan`, `_parse_pmid_list`,
  `_parse_json_verdict`. **`parse_references_section` is NOT addressable this
  way** -- it parses prose/markdown in the report, not a JSON reply.

Two silent-failure modes motivated this and are now guarded:
`_parse_json_verdict` falls back to `supports_claim=False`, so an unparseable
verdict *redacts a correctly-cited claim*; and `_parse_pmid_list` falls back to
`\b\d{7,8}\b`, so any 7-8 digit number in prose becomes a "PMID".

Covered by `src/tests/test_llm_schema_json.py` (12 tests).

## Bugs found along the way

**Fixed -- 429 was treated as fatal.** `complete()` grouped 429 with the
auth/bad-request 4xx and raised on sight, so a moment of rate limiting on the
shared CSIC gateway destroyed a 244-second job at its last phase. Observed
live. Now retried with backoff, honouring `Retry-After`; 401 still fails fast.

**Open -- the verification safety net silently no-ops.** It requires the
synthesis LLM to emit a `### References` section with `[N]` markers and
`**Cited Text:**` blocks, and the model often does not. Across four completed
report generations, only **one** was parseable:

| run | `### References` | `[N]` refs | Cited Text | citations checked |
|---|---|---|---|---|
| fixed baseline | yes | 5 | 5 | 5 |
| fixed rerun | **no** | 0 | 0 | **0** |
| SDK | **no** | 0 | 9 | **0** |
| SDK (no verify loop) | **no** | 0 | 9 | **0** |

When it no-ops, `verification` reports `citations_checked: 0` and
`ref_accuracy: 0.0` and the run still finishes as `done`. Nothing surfaces to
the user that the citation check did not happen. This affects the incumbent and
is independent of the SDK question. Recommended fix: have synthesis emit
references as schema-enforced JSON (the machinery now exists) and render the
markdown from that, rather than parsing prose back out. Failing that, the run
should at minimum report "citations not checked" rather than a silent pass.

## Also worth knowing

The retrieved literature is weak on this job: papers about *Saussurea lappa*
nanoparticles in oral carcinoma and curcumin in diabetic nephropathy, cited for
a B-cell differentiation time course. That is a PubMed retrieval-quality
problem shared by both arms (same `pubmed_client.py`), and it caps how much any
orchestration change can help. Setting `AI_PUBMED_API_KEY` (3 -> 10 req/s) is
the cheapest available improvement.

## Status of the SDK code

`sdk_pipeline.py` is left in the tree, untracked, as the reproducible
experiment behind this decision. It imports `agents`, which is **not** in
`requirements.txt` -- tracking it would make the import smoke test depend on an
undeclared package. Delete it, or declare the dependency, but do not leave it
tracked and undeclared.
