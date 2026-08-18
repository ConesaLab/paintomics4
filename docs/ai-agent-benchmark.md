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
