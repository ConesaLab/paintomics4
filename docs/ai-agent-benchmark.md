# Full-agent arm vs the six-phase workflow, on STATegra, under 600 s

Both arms interpret the same jobs, built from
`PaintomicsServer/src/examplefiles/datasets/08-stategra-multiomics` through
`/pa_step1/example/stategra-multiomics` + step 2 (887 pathways matched, 5 omic
layers, 6 time points), against the live CSIC gateway, with a 600 s ceiling.

## Protocol, pre-registered before the first run

Replicates are paired on identical jobs and the arm order is reversed between
pairs, because one fold cannot measure a change on this gateway: two runs of the
*same* agent have decomposed to gaps of +0.037 and +0.302 on the AgentEvolve
fold score. The agent arm was declared better only if **all** of:

1. every agent replicate finishes `status=done` within 600 s;
2. mean body citations (resolving to retrieved papers, post-redaction) ≥ base;
3. mean redactions ≤ base + 2;
4. mean pathway coverage in prose ≥ base;
5. report length within [0.6×, 2.0×] of the base mean.

Any agent replicate erroring or overrunning while the base arm completes is a
loss regardless of the other numbers. Ties break on full-text citations, then
default to the incumbent.

## Round 1 — as built

Two replicates per arm, paired on the same two jobs, arm order reversed between
pairs. Every run finished `done` inside the ceiling.

| | base r1 | base r2 | agent r1 | agent r2 |
|---|---|---|---|---|
| wall clock | 184 s | 478 s | 172 s | 176 s |
| report | 35 006 | 47 580 | 20 330 | 19 321 chars |
| **prose** (excl. appended tables + references) | — | **39 237** | **6 825** | — chars |
| cited papers in body | 22 | 20 | 9 | 4 |
| redactions | 4 | 5 | 0 | 0 |
| pathways named in prose | — | 15 | 6 | — |
| tool calls | 347 | — | 34 | 38 |
| literature searches | 150 hits / 35 kept | — | 16 of 18 budget | 16 |
| pathways in scope | top 15 by combined p | top 15 | **102** | **102** |

The agent chose to widen its own scope — it called `cluster_pathways`
unprompted, which partitioned 102 significant pathways into 20 clusters, a
thing the workflow arm can only do when an operator sets `AI_CLUSTER_MODE=1`.

**Round 1 verdict: the agent arm loses.** Rule 2 fails (mean 6.5 cited papers
vs 21), rule 4 fails (6 pathways named in prose vs 15), rule 5 fails
(20 330 chars against a 24 776-char floor). Rules 1 and 3 pass, and the agent is
*faster* — 174 s mean against 331 s, with base r2 spending 478 s of its 600 s
ceiling and 293 s of that inside its verify loop.

Three diagnoses, all from the run journal rather than guesswork:

1. **No grounding pass.** The agent retrieved ~25 papers and cited 9. The
   workflow arm runs a citation top-up towards `SDK_MIN_CITATIONS = 22` —
   exactly the number it lands on — and the agent arm, as first built, had no
   equivalent.
2. **Budget left on the table.** The agent finished in 172 s of 600 s and wrote
   a fifth of the prose. Its whole gate cost ~74 s while 240 s were reserved
   for it.
3. **Coverage was an investigation rule, not a writing rule.** The agent
   analysed 6 of 15 top pathways and said nothing about the other 9 — silence a
   reader cannot distinguish from "nothing there".

Two smaller findings: 7 of 14 `search_literature` calls returned zero hits
(queries stacking too many AND clauses, budget spent either way), and
`toolTrace`/`notebook` accumulated across runs of the same job instead of
describing one run.

## Round 2 — parity fixes, same rule

Three changes, all inside the same 600 s ceiling: the workflow arm's **citation
top-up** at the gate (`AI_AGENT_MIN_CITATIONS`, defaulting to the incumbent's
`SDK_MIN_CITATIONS = 22`); the **budget rebalanced** from the gate to the loop
(its whole gate cost ~74 s against the 240 s reserved, so the reserve became
150 s, the loop 450 s, the turn cap 40); and coverage promoted from an
investigation rule to a **writing requirement** — name every cluster and
top-ranked pathway, or say why you set it aside. The measurement rule did not
change.

| mean of 2 replicates each | base | agent r1 | agent r2 |
|---|---|---|---|
| wall clock | 331 s | 174 s | 221 s |
| report | 41 293 | 19 826 | 21 010 chars |
| prose (excl. tables/references) | 39 237 | 7 426 | 7 335 chars |
| cited papers in body | 21.0 | 6.5 | 10.0 |
| of those, full text read | 13.5 | 3.5 | 1.5 |
| **redactions** | 4.5 | **0** | **0** |
| pathways named in prose | 15 | 6.5 | 8.5 |

Scored against the pre-registered rule:

| | rule 1 done ≤600 s | 2 citations | 3 redactions | 4 coverage | 5 length | verdict |
|---|---|---|---|---|---|---|
| agent r1 | pass | **fail** 6.5 vs 21 | pass 0 vs 4.5 | **fail** 6.5 vs 15 | **fail** 19 826 vs 24 776 floor | **not better** |
| agent r2 | pass | **fail** 10 vs 21 | pass 0 vs 4.5 | **fail** 8.5 vs 15 | **fail** 21 010 vs floor | **not better** |

**Decision: not merged.** The parity fixes moved every number the right way —
citations 6.5 → 10, coverage 6.5 → 8.5 — and still lost by a wide margin on
three of five criteria. The top-up fired in both round-2 runs and was *rejected*
both times by the same acceptance guard the workflow arm uses: the rewrite did
not add body citations, so it was discarded rather than shipped.

## Round 3 — retrieval parity and delegation for breadth

The three diagnoses above, acted on: search budget 18 → **40** (the workflow's
effective 35–45); the `search_literature` description now teaches the query
shape that works (`(GeneA OR GeneB) AND one term` — round 1 lost half its
searches to stacked AND clauses); the system prompt makes **delegation the route
to breadth** ("call `delegate_interpretation` a few times, covering all the
top-ranked pathways… skipping it is why a report ends up covering six"); and the
Detailed Pathway Analysis section is declared non-optional.

The instructions were followed and the retrieval problem was solved — replicate 1
issued 14 searches with **zero empty results** (against 7 of 14 empty in round 1)
and delegated twice, early. It did not change the outcome:

| mean of 2 replicates | base | round 1 | round 2 | round 3 |
|---|---|---|---|---|
| wall clock | 331 s | 174 s | 221 s | 236 s |
| prose | 39 237 | 7 426 | 7 335 | 8 870 chars |
| pathways named | 15 | 6.5 | 8.5 | 9.0 |
| cited papers | 21.0 | 6.5 | 10.0 | 7.5 |
| redactions | 4.5 | 0 | 0 | **7.0** |

More literature reached the report and more of it failed verification, so round 3
loses a fourth criterion (redactions) while gaining nothing on the other three.
**Final verdict: not better, in three rounds — rules 2, 3, 4 and 5 all fail.**

Across six agent runs and three configurations the prose stays at 7–9 k
characters whatever the budget, instruction or retrieval breadth: the agent
synthesises delegated material into a compact summary instead of carrying its
detail through. That is the shape of this arm, not a tuning miss, and it is
where any future attempt has to start.

## Round 4 — carry the delegated detail into the report

Round 3's diagnosis named report *construction* as the last untested lever: the
agent had the same material as the workflow arm (its delegated interpretations)
and summarised it away. So the gate now merges the sub-agents' reports with the
Lead's draft in one Report Writer pass — the workflow arm's own phase-5 shape —
kept only if the result is at least 1.2× longer and cites no less
(`AI_AGENT_MERGE_DELEGATED=0` restores round 3).

That fixed the two size criteria outright:

| mean of 2 | base | round 3 | round 4 |
|---|---|---|---|
| prose | 39 237 | 8 870 | **38 480** chars |
| pathways named | 15 | 9.0 | **18.5** |
| cited papers | 21.0 | 7.5 | 4.5 |
| redactions | 4.5 | 7.0 | **3.5** |
| wall clock | 331 s | 236 s | 360 s |

Four of five rules pass — coverage now *exceeds* the workflow arm — and only
citations fail, worse than before: an interpretation written about pathways whose
literature the sub-agent was never shown has nothing to cite, and
`delegate_interpretation` was handing every sub-agent the same arbitrary first
twelve papers.

## Round 5 — attribute the literature to the pathways being delegated

Mirrors `agent.py::_one_batch`: each delegation is shown the papers *attributed*
to its own pathways (the `topic_tag` the Lead passes to `search_literature`,
matched loosely), capped at ten, full text first — plus a prompt rule to search
before delegating. Replicate 1: citations **5 → 10**, prose 32 169, 16 pathways,
5 redactions, 398 s.

Both replicates: citations 11.0, coverage 16.5, prose 28 468, redactions 5.5,
384 s — **the arm's best measured state, 4 of 5 rules, still short only on
citations (11 vs 21).**

The remaining ceiling looked mechanical: the citation top-up never fired, because
*every* retrieved paper was already cited. The agent's index held ~13 papers
where the workflow arm's held 27 — ten queries at five hits each, overlapping
heavily because they are gene-anchored on the same pathways.

## Round 6 — widening the pool, which made it worse

Search hits per query 5 → 10. The pool filled exactly as predicted ("10 hits, 10
new" on every query, ~49 papers against round 5's ~13) and citations **fell to
7.0** with redactions **doubling to 10.5** and replicate variance blowing out
(3 and 11 citations from identical code).

This is the incumbent's own measurement reappearing one level up. `agent.py`
records it for its batches:

> Loosening the relevance filter raised the kept pool from ~30 to 106 papers and
> citations COLLAPSED 15 → 3: a batch handed 20+ abstracts cites fewer of them,
> not more.

The per-delegation cap (10 papers) held, but the merge step hands the Report
Writer the *full* master reference list, and a writer given ninety references
cites three. **Reverted** — the branch keeps round 5, and `AI_AGENT_SEARCH_HITS`
carries the note so nobody widens it again.

## All six rounds

| mean of 2 replicates | base | r1 | r2 | r3 | r4 | r5 | r6 |
|---|---|---|---|---|---|---|---|
| wall clock (s) | 331 | 174 | 221 | 236 | 360 | 384 | 379 |
| prose chars | 39 237 | 7 426 | 7 335 | 8 870 | 38 480 | 28 468 | 31 974 |
| pathways named | 15 | 6.5 | 8.5 | 9.0 | **18.5** | **16.5** | 16.5 |
| cited papers | **21.0** | 6.5 | 10.0 | 7.5 | 4.5 | 11.0 | 7.0 |
| redactions | 4.5 | 0 | 0 | 7.0 | **3.5** | 5.5 | 10.5 |
| rules passed | — | 2/5 | 2/5 | 1/5 | **4/5** | **4/5** | 3/5 |

Rounds 4 and 5 pass everything except citations, and coverage *exceeds* the
workflow arm. Rule 2 never comes close: six configurations put the agent between
4.5 and 11 cited papers against a stable 21, and the two levers that should have
fixed it — more searching, a bigger pool — moved it the wrong way. **The verdict
stands at not better, and the citation gap is a property of writing one report
from a shared reference list rather than three batch reports each grounded in its
own attributed slice.**

## Rounds 7-15 — a loop, and what it moved

Run every ten minutes against the same two jobs and the same rule. The changes
that survived their measurement, in the order the evidence arrived:

| change | what it was measured to do |
|---|---|
| **stitch** instead of re-authoring the delegated reports | merge citations 9 -> 15, 10 -> 19; prose 8 870 -> 38 480 |
| **prefetched, tool-less verifier** | redactions 12 -> 2, verify loop 291 s -> 117 s, run 485 s -> 338 s |
| **grounded-citation merge guard** | refuses a stitch that adds markers without quotes (one rejection: 7 -> 3 citations, correctly declined) |
| **PMID-aware full-text upgrade** | cited papers with full text 4 -> 9 (64 %, matching the workflow arm) |
| **stitch cap 42 k -> 56 k** | pathways named 12 -> 15 |
| **clock-bounded post-loop work** | two runs had died at 602 s of a 600 s ceiling |
| **toolbelt 13 -> 10** | schema cost removed for tools with no adoption |

And the changes that were measured WORSE and reverted, which cost less to record
than to rediscover:

| change | why it was reverted |
|---|---|
| search hits 5 -> 10 (tried twice) | round 6: citations 11 -> 7. round 12: 14 -> 11.5, redactions 5 -> 8.5. A bigger pool spreads each delegation's ten attributed papers thinner |
| delegated sub-agents get their own [N] prompt | merge citations 5 -> 18 became 7 -> 3; a caution about quotability produced caution, not accuracy |
| `read_paper` urged in the prompt on a 45 % payoff | the figure was 8 runs old; at 28 runs it is 20 %, and read-backed citations verify *no better* (78 % vs 84 %) |

### Round 17 — tie searching to coverage, and the frontier moves

One change: search once per cluster you mean to write about, rather than a few
times overall. It is the opposite of the wider-query change that failed twice --
more queries add papers with their OWN attribution tags, wider queries dilute the
slices that already exist.

| | r1 | r2 | mean |
|---|---|---|---|
| searches | 28 | 16 | 22 |
| citations | **18** | 12 | **15.0** |
| redactions | 5 | 5 | **5.0** |
| cited papers with full text | 13 (68 %) | 8 | 10.5 |
| pathways named | 16 | 17 | 16.5 |

**4 of 5 rules**, citations at their highest mean and redactions steady -- the
first time in seventeen rounds that grounding rose without quality falling. r1
alone reached 18 citations with 68 % full text, beating the workflow arm's 65 %.

And the number that tells the next move: **citations track searches at about 0.64
each** (28 -> 18, 16 -> 12). The instruction sets a floor on searching, not a
target, so the spread in citations IS the spread in searching. Another
instruction will not fix that -- the replicate that searched 16 times had already
read the one that exists.

### Rounds 19-20 — showing the agent its own coverage made grounding reliable

The ledger line that reported what the agent MAY still spend now also reports
what it has covered: *literature searched for 7 of 20 clusters*. Budget is a
constraint; coverage is a gap. Nothing instructs the agent to close it.

| citations, four runs each | spread |
|---|---|
| without the coverage line | 18, 12, 15, 25 — **13** |
| with it | **18, 18, 19, 18 — 1** |

| mean (n=4) | base | candidate | with coverage line |
|---|---|---|---|
| citations | 21.0 | 17.5 | **18.2** |
| redactions | 4.5 | 4.5 | 6.2 |
| pathways named | 15.0 | 16.2 | 15.5 |
| cited papers with full text | 13.5 | 9.8 | **12.2** |
| wall clock | 331 s | 410 s | 460 s |

Four of five rules, and -- the point -- grounding stopped depending on which day
the run had. Every earlier configuration's mean was an average over runs that
differed by a factor of two; this one's four runs differ by one citation.

Two things to watch. Redactions carry a single outlier (0, 4, 6, **15**), so 6.2
sits just under the 6.5 threshold on the strength of three good runs. And the
mean report is 81 155 chars against an 82 586 ceiling -- a larger run would fail
the size rule, so the stitch cap has less headroom than it looks.

### The result is a frontier, not a hill

| mean of 2 | wall | prose | paths | cites | redactions |
|---|---|---|---|---|---|
| base (workflow arm) | 331 s | 39 237 | 15.0 | **21.0** | 4.5 |
| r10 | 414 s | 61 580 | 16.0 | 17.0 | 16.0 |
| r11 | 421 s | 60 826 | **16.5** | 14.0 | 5.0 |
| r15 | **270 s** | 10 252 | 12.5 | 11.5 | **0.0** |

r15 ships nothing unsupported and covers least; r10 covers most and strips most;
r11 is the balance and passes 4 of 5 rules. The workflow arm sits outside all of
them: more grounded citations *and* more of them stripped. "Citation grounded" is
therefore two numbers, not one -- markers that arrive, and markers that survive --
and every round that optimised the first moved the second the wrong way until the
guard started counting the second directly.

## A production defect this uncovered (affects the shipped workflow arm too)

Round 3's high redaction count exposed a real fault in `redact_unverified_v2`,
which **both** arms use:

```python
report = ("## Key Findings\nIkaros represses Ccr2 [3].\n\n"
          "## Cross-Pathway Themes\nA shared GPCR module underlies four enrichments.\n\n"
          "## Limitations\nSingle time course.\n")
redact_unverified_v2(report, [{"ref_index": 3, ...}])
# -> "## Cross-Pathway Themes\nA shared GPCR module underlies four enrichments. ## Limitations\nSingle time course."
```

The body is split on sentence boundaries and rejoined with a single space, so
(1) the heading *preceding* a redacted sentence is inside the same chunk and is
deleted with it, and (2) the *following* heading lands mid-line and stops
rendering as a heading. The two workflow runs measured here redacted 4 and 5
citations each, so shipped reports have been losing structure this way already —
it only became obvious at 14. Fixing it changes the incumbent's output and so
belongs in its own PR with its own before/after.

## Why the workflow arm wins here

The gap is retrieval breadth, and it is structural rather than a tuning miss:

* the workflow arm issues 35–45 machine-generated queries (planner + per-pathway
  backfill), lands 150 hits, keeps 35, and reaches 27 papers;
* the agent issues 12–16 self-authored queries under its spend meter, and 7 of
  14 in the first run came back empty because it stacked AND clauses;
* the workflow arm then interprets **all** 15 pathways in three batches and
  synthesises across those batch reports, which is why its prose is five times
  longer; the agent writes one dense report directly.

So for a fixed, well-understood task under a tight ceiling, the fixed pipeline's
breadth is worth more than the agent's adaptivity. That is a real result, and
the opposite of what the proposal assumed.

## What the agent arm is nonetheless better at

Recorded because it is measured, not to soften the verdict:

* **Precision of grounding.** 0 redactions across four runs against 4.5 per
  workflow run: every citation the agent made survived verification, while the
  workflow arm loses four or five sentences per report to unverifiable ones.
* **Speed.** 174–221 s against 331 s, with the workflow arm's worst run
  spending 478 s of the 600 s ceiling — 293 s of it inside the verify loop.
* **Self-widened scope.** Both agent runs called `cluster_pathways` unprompted
  and interpreted inside a 102-pathway partition; the workflow arm needs an
  operator to set `AI_CLUSTER_MODE=1`.
* **Self-reported gaps.** "Several gene-anchored literature searches … returned
  no direct hits" appears in the agent's own Limitations — the spend meter and
  notebook surfacing as honesty in the output.

## If this is picked up again

1. **Give retrieval parity first.** Raise the search budget to the workflow's
   effective 35–45 and fix query construction (fewer AND clauses, gene-OR
   groups); the round-1 trace says that alone is most of the gap.
2. **Make delegation the default path to breadth.** The agent has
   `delegate_interpretation` and used it once per run; requiring one delegation
   per cluster then synthesising across the returned reports is what produces
   the workflow arm's coverage.
3. **Score with the AgentEvolve rubric, not proxies.** Citation count and prose
   length are stand-ins for quality. The harness in `../agentevolve` scores
   claim coverage and rank order against a frozen fold, and a KEEP there means
   something these five rules cannot say. Two replicates per arm is also thin:
   that harness's own measurement showed same-agent gaps swinging 0.27.


## Qualitative read

The agent's prose is not a weaker version of the workflow's — it is a different
document. Round 1's agent report:

* chose its own scope: it clustered first (20 clusters over 102 significant
  pathways) and then went deep on the ones sharing feature cores, which the
  workflow arm can only do when an operator sets `AI_CLUSTER_MODE=1`;
* built a temporal narrative across pathways (early chromatin/protein surges →
  mid apoptosis-clearance window → late IL-2 signalling) rather than a
  pathway-by-pathway walk;
* caught an enrichment artefact on its own: "the Cholinergic synapse and
  Morphine addiction enrichments most likely reflect shared GPCR/G-protein
  machinery rather than neurotransmitter-specific biology";
* reported its own retrieval failures in Limitations ("several gene-anchored
  literature searches … returned no direct hits"), which is the notebook and
  the spend meter showing up as honesty in the output.

Against that: fewer grounded citations, a shorter report, and an investigation
path that differs run to run — which makes evaluation noisier, not cleaner.

## Round 25, queued: the outage bundle (pre-registered 9e291e18a2)

The CSIC gateway has been returning 504s on a bare 8-token probe since ~04:00 on
2026-08-18. Nothing has been scored since round 19/20, and work continued on
things that do not need a gateway. That leaves a bundle of unscored changes, so
the design is written down BEFORE the numbers exist.

Every run from here stamps `code` -- a hash of the module source, the Lead
prompt and every tool description -- so runs of different agents can no longer be
averaged together. The bundle below is fingerprint `9e291e18a2`.

**Unscored changes, in the order they were made**

| # | change | expected direction |
|---|---|---|
| 1 | symmetric grounding sieve in the merge guard | more stitches accepted |
| 2 | quote probes bounded by the clock | no run past 600 s |
| 3 | model-free fallback when synthesis dies | a report instead of an error |
| 4 | structure-preserving redaction | no effect on counts; report readable |
| 5 | delegation cache | ~40 s back in the 7-in-60 runs that repeat one |
| 6 | tool failures traced | measurement only |
| 7 | one nudge when flagged citations survive to submit | fewer redactions |

**Protocol** -- unchanged: jobs 73I734364H and 1354co025T, two replicates each,
the same 5 rules. The bundle is measured as a bundle first; 14 runs to attribute
seven changes individually is not affordable at ~8 minutes a run.

**Pre-registered bisect order, if the bundle fails a rule.** Written now so it
cannot be chosen after seeing which way the numbers went:

1. **the citation nudge (7)** -- the only change that can *lose* citations. The
   agent may delete a flagged claim rather than ground it, which would show as
   citations down and redactions down together.
2. **the delegation cache (5)** -- a cache hit returns an identical analysis
   where a re-run would have produced a fresh one; if the repeat was doing
   useful work, coverage drops.
3. **the merge sieve (1)** -- it changes which draft ships.

4-6 are not bisect candidates: they cannot alter a report that does not error.

**The honest statement of where this stands.** Seven changes, one measured
baseline, zero runs. Each is argued from the archive -- 60 runs, 1892 tool calls
-- and none is argued from a scored comparison. Reasoning from traces is how the
hypotheses were found; it is not evidence that the bundle is better.

## The harness is in the repository now (2026-08-18)

This document described a protocol that nothing in the repository could execute.
The runner, the scorer, the gateway probe and twenty-five drive scripts lived in
a session scratchpad -- a temporary directory. Round 25 was pre-registered
against a runner that would have disappeared with it.

    python -m src.benchmarks.ai_arm_bench ready
    python -m src.benchmarks.ai_arm_bench run <jobID> <base|agent> <dir> --label agent-v25-r1
    python -m src.benchmarks.ai_arm_bench score <dir>

The per-run metrics for rounds 1-24 are kept in
`src/benchmarks/history/ai_arm/` (49 runs, 200 KB). Scoring that directory
reproduces every verdict in this document, including the ones that went against
the agent arm. The reports themselves, 2.4 MB of prose, are not kept.

Two things the port fixed or fixed in place:

**The prose cut is now permanent.** Coverage counts a pathway only if it is
named before the first appended table. The original metric counted the whole
report, and both arms append a table of pathway names, which is how the agent
arm once scored 102/102 for pathways it had never analysed.

**Grouping is part of the protocol, because it changes the answer.**
`agent-v20` alone fails rule 3 -- redactions 7.5 against base 4.5 + 2. Pooled
with `agent-v19` it passes at 6.25, which is the "4 of 5 rules" figure quoted
earlier in this document. Both readings are honest and they disagree. Round 25
therefore fixes its grouping in advance: every replicate stamped with code
fingerprint `9e291e18a2` is one arm, and no other pooling will be reported.

Ten tests pin the five rules and the prose cut, so the rule cannot drift once
the numbers exist.

### Round 25 is now one command

The harness was missing the piece that starts a round: creating the jobs. That
lived only in the scratchpad, and pointed at the wrong checkout.

    python -m src.benchmarks.ai_arm_bench jobs 2          # fresh STATegra jobs
    python -m src.benchmarks.ai_arm_bench round <j1>,<j2> <dir> --label agent-v25

`round` probes the gateway first and **refuses to start** if it is not
answering -- two replicates once spent ten minutes each against a gateway
returning 504 and produced two outage reports dressed as results. It then runs
base/agent/base/agent, interleaved on purpose: gateway throughput drifts over
tens of minutes, and running one arm's replicates back to back lets that
weather land entirely on one side of the comparison. It scores at the end.

Twelve tests cover the five rules, the prose cut, the refusal (exit 2, nothing
written) and the interleaving.

### What the outage of 2026-08-18 actually was

Reported for two and a half hours as "gateway unreachable", which pointed at the
wrong layer. Diagnosed properly:

    DNS            llm.iiia.es -> 161.111.18.39
    TCP connect    OK in 0.02 s
    TLS handshake  OK, TLSv1.3
    GET /v1/models HTTP 504 Gateway Time-out, from nginx, after 60 s

The proxy was healthy throughout and answering. What was down was the model
service behind it, and even a trivial `/models` listing 504ed -- so it was not
load, not the model, not the key, and nothing on this side.

`ready` now separates the three cases, because they call for different
responses: a name that will not resolve or a refused connection is the network
or the host; a 5xx from the proxy means the gateway is up and its upstream is
down; no answer at all means the upstream is hanging rather than refusing. Five
tests cover the classification.

### Round 25 launched 2026-08-18 08:42, and the bundle is bigger than pre-registered

The gateway answered at 08:42 after four hours and forty minutes of 504s. The
round started immediately: `73I734364H,1354co025T`, base/agent interleaved,
label `agent-v25`.

**The fingerprint has moved: `9e291e18a2` at pre-registration, `e92a9a5737` at
launch.** Work continued during the outage, so the arm being measured is not
byte-identical to the one the bisect order was written for. What changed after
pre-registration:

| change | can it move the numbers? |
|---|---|
| read_paper description corrected (claimed reading helps survival; it does not) | possibly -- it is prompt text the Lead reads every turn |
| "Optionally run check_my_citations" removed from the Lead prompt | possibly -- it should raise re-checks, which measured well |
| orphaned `SYSTEM_PROMPT_DELEGATED_INTERPRET` deleted | no -- nothing sent it |
| uncited references pruned before renumbering | slightly -- fewer reference entries, same citations |
| truncation detection, ungrounded-report note | no -- observability, and the note only fires when nothing grounded |

Two of those are prompt text, so the pre-registered bisect order gains a step at
the front: **if the bundle fails a rule, suspect the two prompt edits before the
citation nudge**, because they are the newest and the least measured.

Saying this before the numbers exist is the whole point of writing it down. The
alternative -- quietly reporting the result against the old fingerprint -- would
have been a measurement of something other than what the document claims.

## Round 25 result: NOT better, 2 of 5 rules

Fingerprint `e92a9a5737`, jobs 73I734364H and 1354co025T, interleaved, 2026-08-18.

| | base | agent-v25 |
|---|---|---|
| wall_s | 362.4 | 333.6 |
| citations_in_body | 17.0 | **5.5** |
| redacted | 11.0 | **22.0** |
| prose_pathways_covered | 13.0 | 12.0 |
| report_chars | 33530 | 43978 |

    1 every replicate done within 600s   PASS
    2 citations >= base                  FAIL  (5.5 vs 17.0)
    3 redactions <= base + 2             FAIL  (22.0 vs 11.0)
    4 prose coverage >= base             FAIL  (12.0 vs 13.0)
    5 length within [0.6x, 2.0x]         PASS
    => NOT better - the incumbent stands. PR #38 stays a draft.

**The mean hides the finding.** The two agent replicates could hardly differ more:

| | agent-r1 | agent-r2 |
|---|---|---|
| papers retrieved | 11 | 102 |
| citations surviving | 11 | **0** |
| redactions | **0** | 44 |

r1 is the best-behaved agent run yet measured: it called `check_my_citations`
three times, drove unquotable citations 7 -> 2 -> 0, and shipped with **zero**
redactions against base's ten. The tool work of this session did exactly what
the traces predicted.

r2 did the same thing and shipped nothing. It submitted a 7 726-character draft
carrying 7 citations, every one of them checked and grounded. The gate then
merged in 52 000 characters of delegated sub-agent text, which carried **44
citations the agent had never checked**, and could not ground them in the
remaining budget. All 44 were redacted; none of the agent's own 7 survived
renumbering either.

### The structural defect this exposes

**`check_my_citations` validates the draft; the gate ships draft + merge.** The
one tool measured to improve grounding is applied to a document that is not the
one being verified. The agent spends its budget grounding seven citations and
the gate then imports forty-four unchecked ones.

That is not a tuning problem and no prompt wording fixes it. Candidate
directions, none of them measured yet:

1. ground delegated citations at delegation time, inside the sub-agent's own
   budget, so the merge imports only citations that carry a quote;
2. have the merge drop an unquotable citation marker rather than the sentence,
   so delegated prose survives without a false citation;
3. have `check_my_citations` check the merged document, which means the merge
   has to happen before the agent's final check rather than after it.

(1) is closest to the design's spirit -- the sub-agent that wrote the claim is
the one that can find its quote -- and it is where the next round should go.

The pre-registered bisect is not needed: the failure is not one of the nine
changes, it is a seam between the loop and the gate that every version of this
arm has had. The changes did what they were supposed to: r1's zero redactions
are the evidence.

## Round 26, pre-registered: does grounding at delegation time fix the seam?

Fingerprint `90fd3e74c7`. One change from round 25: `delegate_interpretation`
grounds its own citations as the sub-agents return, caches the quotes on the
context, seeds the gate from them, and names the ungrounded indices to the Lead.

**Prediction, written before the run.** Round 25's replicates split on exactly
one thing -- whether the merged text's citations could be grounded in the time
left (r1: 11 citations, 0 redactions; r2: 0 citations, 44 redactions). If the
diagnosis is right:

| | expectation |
|---|---|
| redactions | **down**, and the r1/r2 spread should collapse |
| citations | **up or level** -- the merge stops shedding them |
| wall clock | +5 to +15 s per delegation, still under 600 s |
| `quotes_from_delegation` | non-zero in the stored stats |

**What would falsify it:** citations fall again while redactions also fall. That
is the signature of the agent dropping claims rather than grounding them, and it
would mean the seam was not the binding constraint.

The five rules and the two jobs are unchanged.

## Round 26 measured a fix that never ran

The grounding step added before round 26 was guarded on `"[" in out` -- but the
delegated sub-agents are told to write `(PMID: 12345)`, not `[N]`. That prompt
was reverted to the workflow arm's on evidence months of rounds ago, and the
markers are only converted later, inside the merge. The guard was therefore
never true. No quotes were collected at delegation, the gate found none either,
references rendered with no Cited Text, and `agent-v26-r1` shipped **0 citations
with 54 redactions** -- the round-25 r2 failure, now in r1 as well.

The trace is what caught it: no `delegate_grounding` event existed at all. Had
the event been there with a poor result, the honest reading would have been "the
fix does not help". Its absence says something different and more useful.

`resolve_pmid_mentions` now runs on the delegated text before grounding, so the
Lead reads the same citation form it has to check. A regression test drives the
tool with PMID-form output and asserts the trace event exists; it fails against
the code as round 26 ran it.

**Round 26 is therefore not a test of the fix.** It is a second replication of
round 25's configuration, and worth keeping as exactly that -- it says the
0-citation collapse is not rare, since it has now happened in three of four
agent replicates across two rounds.

## Round 28, pre-registered: write from quotes, and check what ships

Two changes, both aimed at the same seam.

**1. The sub-agent gets its evidence before it writes.** For each delegated
chunk, `search_paper_text` (a 1 ms substring search, no model) pulls the
passages matching that chunk's pathways and genes, and they go into the prompt
as "Evidence you may cite -- cite [N] only where you are using that paper's
passage, and write the claim so the passage supports it." This is what the
shipped arm does implicitly by writing with abstracts in context, and it is why
its citations survive.

**2. `check_my_citations` checks draft + delegated text.** It was validating
about 9 KB of the ~60 KB that ships. Round 27 is the cost of that: the agent
submitted 11 citations it had checked and grounded, and 6 survived.

**Prediction.** Citations up substantially -- the mechanism now matches the arm
that scores 21. Redactions down. Wall clock roughly flat: the shelf is free and
the extra checking reuses quotes already collected at delegation.

**Falsifier.** Citations stay near 5 while the shelf is demonstrably in the
prompt and the check demonstrably covers the delegated text. That would mean
writing-from-quotes is not the mechanism behind base's advantage, and the honest
next step is the hybrid -- agent decides what to investigate, base-style batched
writing produces the prose.

**Verify first, score second.** The trace must show a non-empty shelf and a
check whose citation count matches the shipping text, before any rule is read.
Round 26 scored a fix that never ran.

## Round 28: 4 of 5 rules, the best this arm has done

| | base | agent-v28 | r1 | r2 |
|---|---|---|---|---|
| citations | 20.0 | 9.0 **FAIL** | 10 | 8 |
| redactions | 13.5 | 5.0 **PASS** | 10 | 0 |
| prose coverage | 14.5 | 16.5 **PASS** | 17 | 16 |
| length | | **PASS** | | |
| wall_s | | | 557 | 475 |

Rule 3 passes for the first time in 28 rounds, and by a wide margin -- the arm
now redacts less than a third as often as the shipped one. The replicate spread,
which has been the loudest thing in this data (11 vs 0 in round 25), collapsed
to 10 vs 8.

The trajectory says the diagnosis was right:

    r25   5.5 citations / 22 redactions   2 of 5
    r26   0.0           / 45              2 of 5
    r27   4.5           / 26              3 of 5
    r28   9.0           /  5              4 of 5

### The remaining gap is conversion, not retrieval

`papers_retrieved` misled me twice. Fixed properly, the runs read:

| | papers retrieved | citations shipped | conversion |
|---|---|---|---|
| base | 34.5 | 20 | **58%** |
| agent | 63, 60 | 10, 8 | **16%** |

The agent retrieves nearly twice what the shipped arm does and converts a
quarter as well. Retrieval was never the problem, and the "stop rewarding
retrieval volume" note withdrawn earlier was doubly wrong.

The likely cause is where citations can be born. Base writes fourteen batches,
each citing its own papers. This arm wrote a draft plus two delegate calls of
one or two chunks -- and `DELEGATE_WORKERS` is 4, so two slots never ran at all.

Round 29 raises the delegation cap from 10 pathways to 20, which is four chunks
and fills the pool exactly. Four sub-agents run in the wall clock two used, so
the extra breadth is free.

**Prediction:** citations up towards base, redactions staying low, wall clock
flat. **Falsifier:** citations flat at ~9 with four chunks demonstrably running
-- which would mean the ceiling is what the agent is willing to claim, not how
many places it has to claim it, and the honest next step is the hybrid.

### Correcting round 29's prediction, before the numbers

The cap was not the binding constraint. Round 28's Lead asked for **6 and 9**
pathways in two calls -- it never reached the old cap of 10. So raising the cap
to 20 does not create more places a citation can be born; it lets the same ~15
pathways be covered in one call of three or four parallel chunks instead of two
sequential calls of two.

**Revised prediction: wall clock down by roughly the length of one delegation
(~30 s), citations roughly flat.** The earlier prediction of "citations up
towards base" was reasoning from a constraint that was not binding, and it is
withdrawn rather than quietly left to be judged against the result.

What the numbers still cannot be:
* if citations rise anyway, the extra parallel breadth mattered after all;
* if wall clock does not fall, the Lead ignored the "make ONE call" wording and
  the change is inert -- the same shape as round 26's guard that never fired.

**The next lever this points at.** Base writes fourteen batches, each citing its
own papers; this arm writes four chunks plus a draft, about five writing units.
That ratio, not pathway count, tracks the citation gap of 9 against 20. The
experiment that follows is smaller chunks -- three pathways per sub-agent rather
than five, giving five to seven writing units for the same breadth, still inside
one or two parallel waves.

## The merge guard has been blind since the outage

Round 29's stats carried the answer to why grounded citations kept disappearing:

    merge_citations      7->11
    merge_grounded       0->0
    quotes_unverifiable  11
    quotes_reused        11

Eleven quotes collected, eleven reused, **eleven judged unverifiable**, and the
merge guard comparing zero grounded against zero grounded.

`_verified_quotes` called `_fuzzy_contains(quote, text)`. The signature is
`_fuzzy_contains(haystack, needle)` -- so it was asking whether an entire paper
fits inside a one-sentence quote. That is never true. Every quote failed, always,
and the guard that decides whether the stitched report is better grounded than
the draft has been comparing 0 with 0 since the sieve was added during the
gateway outage. Rounds 25 to 29 all ran with it.

Replayed on round 29's own report: **6 of 6 quotes survive the corrected sieve**,
where the run recorded 0 of 11.

It stayed hidden because "0 grounded" reads like a finding about the report
rather than a broken predicate -- I had even written it up as evidence that
delegated citations were poorly grounded. A test now pins the argument order
with a quote that is in its paper and one that is not.

This is the fifth defect in this arm found by reading stats rather than scores,
and the second where my own instrumentation reported a plausible number that
meant something else entirely.

## Round 29 result, and round 30 pre-registered

Round 29: **4 of 5 rules**, two rounds in a row. Citations 8.0 against base 14.5
(the only failure), redactions 8.5 against 8.5, coverage 17.5 against 14.0, wall
399 s and 470 s. The corrected prediction held -- one delegate call of three
parallel chunks instead of two sequential calls cut ~160 s, and citations stayed
flat, exactly as the withdrawal of the original prediction said they would.

**Round 30 isolates the sieve repair.** One change: `_verified_quotes` now asks
whether the quote is in the paper rather than whether the paper is in the quote.
The merge guard has been comparing zero grounded against zero grounded since the
outage, so it has been choosing between draft and stitch on a tie-break rather
than on evidence.

**Verify before scoring:** `merge_grounded` must no longer read `0->0`. If it
does, the repair did not reach the code path and the round measures nothing --
the round-26 lesson, now a standing check.

**Prediction:** the guard makes an informed choice for the first time, so it
should keep the stitch when the stitch is better grounded. Citations up modestly
or flat; redactions flat or down. **Falsifier:** `merge_grounded` shows real
numbers and citations still sit at 8 -- which would mean the merge was never
choosing badly, and the conversion gap is entirely upstream, in the 45 of 75
papers no writer ever sees.

## Round 30 r1: the agent breached the ceiling, and the harness lied about it

    status  error      wall  914.4 s
    detail  "The agent interpretation exceeded its 10-minute limit"

The run was stopped at the limit the whole exercise is built around. But the
metrics file recorded **17 citations, 19 redactions, 32 393 characters** -- and
those are base-r1's numbers, identical field for field. MongoDB keeps one
interpretation per JOB, the errored run never wrote its own, and `_measure`
happily read whatever was there.

For a few minutes that looked like the best citation count this arm had ever
produced, and it would have been reported as evidence that the sieve repair
worked. It is evidence of nothing.

`_measure` now returns status, wall clock and a `stale_record` flag for any run
that did not finish, and nothing report-derived. The score table prints "of
which measurable" beside the replicate count, so a mean over one surviving run
of two cannot be read as a mean over two. Two tests.

**What round 30 does say.** The agent arm hit the wall clock, which no previous
round did -- 914 s against 600. Whether the sieve repair raises citations is
still unmeasured, because the only replicate that could have shown it never
finished.

## Round 30: the sieve repair works, and exposes the next problem

One replicate errored at the ceiling (914 s) and its metrics were the stale
record described above. The other completed and is the best run this arm has
produced.

    merge_grounded       9->12     (0->0 for the five rounds before)
    quotes_unverifiable  0         (11 of 11 before)
    quotes_reused        15

| | base-r2 | agent-v30-r2 | v29-r2 |
|---|---|---|---|
| citations | 24 | **16** | 10 |
| redactions | 4 | **0** | 9 |
| prose coverage | 15 | 15 | 18 |
| wall_s | 352 | 455 | 402 |
| report chars | 36 930 | 78 776 | 72 153 |

**Sixteen citations with zero redactions**: every citation it shipped was
grounded. Citations up 60% on round 29, redactions to nothing.

Scored against the five rules this replicate is 3 of 5, and the second failure
is new:

    5 length within [0.6x, 2.0x]   FAIL   2.13x

Prose 62 161 characters against base's 26 599. The rule exists to catch
degenerate output and it is pre-registered, so it is not being relaxed after the
fact -- but it names something real. The arm now grounds well and says too much:
the merge concatenates every sub-agent's text, and more writing units make a
longer report, not a denser one.

**Two problems remain, and they pull against each other.** Citations are 16
against 24, which argues for more writing units; length is 2.13x, which argues
for fewer or shorter ones. The measurement that separates them is citations per
thousand characters of prose: base 0.90, this arm 0.26. The arm does not need
more text, it needs the text it has to carry more evidence.

## Round 32, pre-registered: make the prose carry its evidence

Round 30 left two failures pulling against each other -- citations 16 against
24, length 2.13x. The number that separates them is citations per thousand
characters of prose: **base 0.90, this arm 0.26**. The arm does not need more
text; it needs its text to carry more evidence.

The change is one prompt block. The delegated writer is told to keep two kinds
of sentence apart: what the DATA shows, which needs no citation and must not be
given one, and what the LITERATURE says, which needs a passage from the shelf
standing behind it. A sentence that is neither -- mechanism written as
established fact with nothing to point at -- is the one thing to leave out.

**Prediction:** prose down (that third category is where the excess length
lives), citations flat or up, density up towards base. **Falsifier:** prose down
AND citations down together, meaning the writer answered by saying less rather
than by grounding more -- in which case the ceiling is the model's willingness
to commit, not the prompt.

Round 31 runs first with the clock guards alone, because an arm that cannot hold
600 s cannot be judged on anything else.

## Round 31 r1: rule 2 passes for the first time

With the clock guards in and nothing else changed:

| | base-r1 | agent-v31-r1 |
|---|---|---|
| citations | 14 | **14  PASS** |
| redactions | 19 | **8  PASS** |
| wall_s | 342 | **351  PASS** |
| length | 27 913 | 25 196 (0.90x) **PASS** |
| prose coverage | 15 | 10  **FAIL** |
| citations / 1000 chars prose | 0.64 | **1.41** |

4 of 5, and the first replicate in thirty-one rounds to match the shipped arm on
citations. The clock guards held it at 351 s where round 30 needed 914. Evidence
density is now more than double base's.

**Coverage failed for a reason worth reading.** The stats:

    merge_rejected  len 11209->55618, cites 15->12, GROUNDED 8->10

The guard threw away a stitch that had **two more grounded citations** and 44 000
characters of pathway coverage, because three raw markers went with it. Those
three had no quote: the block immediately after acceptance strips exactly such
markers, and the gate deletes them after that. The guard was refusing candidates
for losing citations that were never going to survive.

It now judges on grounded citations alone. Raw marker count is not a quantity
anyone ships.

That single condition explains the shape of round 31: a dense, well-grounded,
narrow report -- the Lead's own draft, with the delegated breadth discarded at
the last step.
