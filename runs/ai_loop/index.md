# AI interpretation framework loop — experiment index

Goal: find the framework + configuration that makes the AI interpretation
**smartest**, judged on output quality. Token cost is explicitly NOT a
constraint (user directive, 2026-08-07).

Scored with tellme's own criteria (`tellme/runs/loop/select_best_draft.py`),
including its decision rule: **a draft that fails faithfulness is DISQUALIFIED
outright, no matter how complete — correctness beats completeness.**

Fixed job for comparability: `vyfKO754n4` (STATegra, mouse B3, 6 omics,
44 significant pathways). Gateway: CSIC `deepseek-ai/DeepSeek-V4-Flash-0731`.

| iter | arm | score | cov/20 | honesty | ANTI | failed cites | time | verdict |
|---|---|---|---|---|---|---|---|---|
| 00 | fixed (baseline) | 9.00 | 6 | 2 | 0 | 1 | 238s | reference point |
| 00 | sdk (same budget) | 9.00 | 5 | 1 | 0 | 9 | 103s | no quality win |
| 00 | sdk (no verify loop) | 12.25 | 8 | 3 | 0 | 9 | 129s | DISQUALIFIED (unfaithful) |
| 01 | sdk_wide (15 parallel experts, 3 adversarial verifiers) | **4.75** | 3 | 1 | 0 | 15 | 55s | **WORST — width lost to depth** |

## iter01 finding — width is not depth

Hypothesis: one deep expert agent per pathway + N refuters per citation beats
the batched incumbent. **Refuted, decisively.**

The 15 parallel experts made **0 tool calls** between them and finished in 10s.
The incumbent, on the same job, made **64** (35 `search_paper_text`, 16
`fetch_paper_section`, 13 `extract_evidence`) with tool loops running 5 turns
deep. Handing an agent tools does not make it investigate: the
`build_pathway_focus_prompt` already contains the pathway data, so there was
nothing left for the expert to look up. Parallelism multiplied shallow one-shot
calls instead of buying depth.

Two further costs of going per-pathway:
- **Cross-pathway context is destroyed.** The incumbent's 5-pathway batches let
  the model see relationships *between* pathways, which is where multi-omics
  insight actually lives. Isolated experts cannot. Coverage fell 6 -> 3.
- The adversarial verifier never ran (`citations_verifiable: 0`) because the
  synthesis again omitted `cited_text` — the same open bug as iter00.

**The incumbent is already the deep-agent architecture.** The lever that
matters is depth of evidence gathering, not count of agents.


| 02 | fixed, budget opened (14 search tasks, 8 papers/search) | 10.00 | 6 | 1 | 0 | **28 dangling** | 275s | best content, worst grounding |

## iter02 finding — budget helps content, and exposes the real bottleneck

Opening the budget raised papers retrieved 6 -> 28 and the content score
9.00 -> 10.00. But the report cites `[1]`..`[28]` with **no reference list at
all**: 28 unresolvable markers. Better content, no grounding.

Corrected the scorer while doing this: it only counted dangling citations when
a reference list existed, so a report with 28 markers and zero references
scored "dangling: none". The worst case was scoring as the best. Fixed — no
reference list now means every marker is dangling.

With the gate applied honestly, **no arm yet produces a well-grounded report**:

| arm | content | dangling | gate |
|---|---|---|---|
| fixed baseline | 9.00 | 1 | FAIL |
| fixed deeper | 10.00 | 28 | FAIL |
| sdk batched | 9.00 | 0 | pass *by emptiness* — all 9 citations redacted |
| sdk wide | 4.75 | 0 | pass *by emptiness* — 48 redactions |

The SDK arms only "pass" because redaction removed everything there was to be
wrong about. That is not grounding.

**Conclusion so far: the framework is not the bottleneck.** The references
contract is. Across six runs the synthesis emitted a parseable
`### References` / `[N]` / `**Cited Text:**` block exactly once. When it does
not, verification silently checks nothing and the run still reports `done`.
Every framework inherits this, so it is worth more than any framework choice.

| 03 | fixed + rendered references + PubMed retry wired | 7.50 | 4 | 1 | 0 | **0** | 245s | **first arm grounded, not empty — GATE PASS** |

## iter03 finding — the bottleneck was never the framework

Three defects, each hiding the next.

**1. The model cannot be instructed into the parser's format.** Replaced prose
instruction with deterministic rendering: `render_references_section()` builds
the section from `paper_index` (ground truth) and asks the model only for the
one thing it alone knows — the sentence it relied on. 9 round-trip tests.

**2. Asking for all quotes in one call returns none.** The batched request came
back `{"citations": []}` — 17 characters — for a report with 16 citations: a
12k-char report plus a schema whose array may legally be empty gives the model
an exit. One focused call per citation removed the exit. 0 quotes -> 5–6.

**3. `search()` and `fetch_abstracts()` bypassed their own retry wrapper.** The
two hottest methods in `pubmed_client` called `requests.get` directly, so
`_request_with_retry` existed but never ran on the paths that mattered. Every
429 silently dropped a search. Runs were losing 5–9 searches each — literature
the report then could not cite. Wired through the wrapper: **429s went 5–9 -> 0,
searches lost -> 0.**

**4. The correction rewrite re-broke the references.** It is a full model
rewrite, so it re-authored the section just rendered — the loop would check 6
citations on iteration 1 and still finish `ref_accuracy: 0.0`. Now re-rendered
after every rewrite, carrying quotes forward.

Result: `citations_checked` 0 -> 5, `ref_accuracy` 0.0 -> 0.56, verification
converging properly (iter1: 5 checked, 1 failed, corrected; iter2: 0 failed).

Content score fell 9.00 -> 7.50 and that is the **correct** direction:
redaction now removes unsupported claims instead of leaving them standing. The
earlier 10.00 was a report with 28 unresolvable citations.

| arm | content | dangling | gate |
|---|---|---|---|
| fixed baseline | 9.00 | 1 | FAIL |
| fixed deeper | 10.00 | 28 | FAIL |
| sdk wide | 4.75 | 0 | pass by emptiness |
| **fixed grounded** | **7.50** | **0** | **PASS — grounded** |

| 04 | fixed x3 + sdk x2, on the grounded substrate | 6.25 / 8.00 / 10.00 · 11.75 / vacuous | — | — | 0 | 0 | 108–587s | **iter00 verdict retracted** |

## iter04 finding — the iter00 verdict was measured on noise; SDK is back in play

**Retraction.** The iter00 conclusion ("keep the fixed pipeline") was reached on
a substrate where verification almost never ran and most citations were
unparseable. That was not a measurement of either architecture. Re-tested on the
iter03 substrate, with both arms receiving the same deterministic references
rebuild:

| arm | score | gate |
|---|---|---|
| fixed r1 | 6.25 | PASS (4 cited) |
| fixed r2 | 8.00 | PASS (8 cited) |
| fixed r3 | 10.00 | PASS (18 cited) |
| **sdk r1** | **11.75** | **PASS (9 cited)** |
| sdk r2 | 10.00 | VACUOUS (0 citations) |
| baseline (pre-iter03) | 9.00 | FAIL (1 unresolvable) |

**The SDK's best grounded run beats the incumbent's best.** But it produced a
citation-free report in 1 of 2 runs, where the incumbent was 3/3 grounded. So on
current evidence: SDK peaks higher, incumbent is more reliable. n is far too
small to choose — that is the honest state, not a verdict.

**Scorer hardened again.** A report citing nothing scored 0 dangling and
"PASSED". Two very different things were being conflated: every claim backed, vs
nothing to be wrong about. Vacuous runs are now labelled as such — which
retroactively reclassifies sdk-r2 and the iter01 SDK-WIDE run.

**Strongest signal in the data is not the framework.** Score tracks papers
retrieved almost linearly: 4 papers -> 6.25, 8 -> 8.00, 18 -> 10.00 (and sdk 9 ->
11.75). Retrieval volume may dominate the architecture choice entirely.

**Retry fix vindicated:** one run absorbed **45** HTTP 429s with **zero**
searches lost. Before iter03 that run would have lost most of its literature.

**Planner prompt rewritten** (relevance): pathway databases name entries after
diseases ("Human T-cell leukemia virus 1 infection", "Spinocerebellar ataxia"),
and searching those labels verbatim returned cirrhosis and lung-cancer papers
for a B-cell time course. The planner is now forbidden from searching a pathway
name that is a disease label, and must anchor every query in the experimental
system. Runs r2/r3 used it, r1 did not — suggestive (4 -> 8 -> 18 papers) but
confounded with retry luck, so **not yet established**.

| 05 | diagnosis + 2 real bugs fixed; n=5/arm running | — | — | — | — | — | — | in flight |

## iter05 finding — two bugs, one of them mis-attributing citations in production

**Why the SDK emitted zero citations (1 run in 2).** It handed each batch its
GLOBAL paper indices — [7], [12], [15]. `pipeline.py` has a comment explaining
exactly why that fails: *"LLMs tend to renumber citations starting from 1
regardless of the provided ref_index."* Handed non-contiguous large numbers the
model either renumbers anyway (markers then match no paper and are dropped) or
stops citing entirely — a 19,602-character report with zero markers. The
incumbent avoids this with `_build_local_paper_index` + `_remap_citation_indices`;
the SDK arm never had it. Now wired in. This also explains the "9 failed
citations" that drove the original iter00 verdict.

**A live correctness bug in the incumbent, found while testing that fix.**
`_remap_citation_indices` matched only the exact string `[N]`. Grouped markers —
`[1, 2]` — kept their LOCAL indices and silently came to mean two different
papers after global renumbering. Models write grouped citations constantly: the
first report examined this session contained `[4, 5]` and `[31, 88]`. So
ordinary reports have been mis-attributing evidence, not edge cases. Rewritten
to remap every index inside a group; the single-pass rewrite also retires the
old two-pass placeholder dance. 9 tests, `test_citation_remapping.py` — nothing
had covered this function at all.

n=5 per arm relaunched on identical code (the first attempt was killed after one
run because it straddled this fix — comparing across a code change is what made
the earlier verdicts unreliable). Arms interleaved so gateway drift loads on
both equally.

| 06 | SDK tuned — target: score 20, 20 citations, <300s | **15.25** | 11 | 2 | 0 | 0 | **242s** | PASS (5 cited) |

## iter06 — SDK tuning toward score 20 / 20 citations / 300s

Progress against the three targets: **time met** (242s, from 384s), **score 15.25**
(from 8.25), **citations 5** — still far from 20.

**The single biggest lever was not orchestration: `experimentDesign` is EMPTY on
this job.** The search planner is instructed to anchor every query in the
experimental system, but there was no system to anchor to, so it fell back to
pathway names — which in KEGG are disease labels — and retrieved cirrhosis and
oral-carcinoma papers for a B-cell time course. Supplying the STATegra
description:

| | quotes | checked | final failures | score | gate |
|---|---|---|---|---|---|
| empty design | 1 | 0 | 14 | 8.25 | VACUOUS |
| with design | 10 | 10 | 2 | 11.50 | PASS (10 cited) |

**This is a product-level finding, not a lab one.** Any user who leaves the
experiment description blank gets the same silently irrelevant citations. The
pipeline should either derive context from the data (organism, omic types,
condition labels) or say plainly that citation quality will be poor without it.

**Verification never converged, and never gave up.** "10 failed, 10 failed, 10
failed" burned ~200s of a 384s run. Where a citation is simply wrong, rewriting
cannot rescue it. Added the incumbent's no-progress break to the SDK loop:
384s -> 242s with no quality loss.

**Two honesty mechanisms added, both of which *reduce* citation count on
purpose:**
- `_snap_quote_to_source` holds the model to the paper's own wording. Models
  paraphrase however firmly instructed not to, and a paraphrased quote is then
  correctly refuted for not appearing in the paper.
- The paper filter may now return an empty list. It previously always kept the
  top N, so an irrelevant paper did not sit harmlessly in the bibliography — it
  got cited for a claim it contradicted and the citation was thrown away.

**Verification was never broken.** Three runs of "N checked, N failed" looked
like a bug; a controlled probe showed the verifier passes true citations (2 tool
calls) and fails false ones (3 tool calls). It was correctly rejecting citations
to papers that contradicted the claims — e.g. a paper reporting *upregulated*
Bax/Caspase-3 cited for Bcl2-mediated apoptosis *suppression*.

| 07 | SDK, widened retrieval + full-text quotes | 12.00–15.25 | 9–11 | 1–2 | 0 | 0 | 154–242s | best-so-far band |

## iter07 — the funnel, and two prompt edits that made things worse

Runs 6-10 against the targets (score 20 / ~20 citations / <300s):

| run | score | citations | time | note |
|---|---|---|---|---|
| tuned_5 | **15.25** | 5 | 242s | best score |
| tuned_6 | 12.00 | **8** | 227s | most citations |
| tuned_8 | 12.50 | 0 | 185s | prompt regression |
| tuned_9 | **0.50** | 0 | 154s | prompt regression, report mangled |
| tuned_10 | 12.25 | 5 | 205s | after revert |

**Time is met consistently** (154-242s). Score peaks at 15.25. Citations peak at 8.

**The funnel, now instrumented:** 268 PubMed hits -> 27 kept by the filter ->
22 references rendered -> **4-8 quotes** -> 5-8 surviving citations. The quote
step is the binding constraint, and the reason is structural: a report sentence
like "Bcl2 peak=3.058@24h" is a statement about *this dataset*, and no published
paper contains it. Only the mechanistic half of a claim is citable.

**Two prompt edits made it worse, and are recorded because the failure mode is
instructive.** Telling the model "do NOT cite your own measurements" collapsed
citations to zero — it read a placement rule as "cite less". Rewriting it as
"cite heavily, but put [N] on the mechanism" produced a *0.50* run: 5 citations,
0 quotes, all redacted, and the redaction tore the report apart into fragments
(`### 2. ### 3. ### 5.`, 5.7k chars against a normal 20k). Softened to a short
worked example, the score recovered to 12.25.

**Robustness bug found:** `redact_unverified_v2` mangles document structure when
it removes many citations at once, leaving orphaned heading fragments. A report
losing most of its citations should degrade to an uncited report, not a broken
one. Not yet fixed.

| 08 | SDK, full-text fetch + multi-angle retrieval | 7.75–13.00 | 5–9 | 1–2 | 0 | 0 | 150–286s | verification now converges clean |

## iter08 — where the citation ceiling actually is

**Target status: 1 of 3 met.** Time is met comfortably and repeatedly
(150-286s). Score peaks 15.25, typically 10-13. Citations peak 8.

Two fixes landed:
- **The SDK arm never fetched full text.** It called `fetch_abstracts`, while
  `fetch_papers` (PMC -> Europe PMC -> abstract) was used only by the incumbent.
  Wired in — but on this job it changes nothing: **all papers come back Tier 3,
  abstract-only.** No open-access full text exists for them.
- **Multi-angle per-pathway retrieval.** `_adaptive_budgets` caps planner tasks
  at `(pathways+1)//2`, so raising `AI_MAX_SEARCH_TASKS` alone does nothing;
  breadth had to be added in the backfill.

**Verification now converges clean** — 0 failed citations in three consecutive
runs, against 100% failure a few iterations ago.

### Why ~20 citations is not currently reachable, honestly

Measured funnel, per run:

| stage | count | limiter |
|---|---|---|
| PubMed hits | ~270-600 | search budget |
| kept by filter | 18-36 | relevance gate (~10%, deliberate) |
| unique papers | 13-29 | |
| **cited by synthesis** | **11-15** | writer uses ~half of what it is given |
| with a usable quote | 4-8 | **abstract-only: ~30-45% yield** |
| surviving citations | **4-8** | |

Two hard constraints, both external to the framework:

1. **PubMed unkeyed = 3 req/s.** 88 search tasks blew the 300s budget outright
   (killed at 600s, 8 rate-limit backoffs). 43 tasks fits in 286s. So retrieval
   volume is bounded by *time*, and the 20-citation and 300s targets are in
   direct conflict **without an NCBI API key**. With a key (10 req/s) the same
   130 requests cost ~14s instead of ~52s plus backoffs.
2. **Every paper is abstract-only.** Abstracts state conclusions; the sentence
   that supports a specific mechanistic claim usually sits in Results. That caps
   quote yield near 30-45% no matter how many papers are retrieved.

Reaching 20 citations from here would require relaxing quote-snapping or letting
the filter keep weak papers — which is precisely how the pipeline previously
cited a paper reporting *upregulated* Bax/Caspase-3 in support of Bcl2-mediated
apoptosis *suppression*. Not done.

**Next honest lever:** the synthesis cites only ~half the papers it is handed
(29 available -> 15 cited). Closing that gap is worth more than more retrieval,
and costs no time.

| 09 | SDK + batched PubMed fetch | 6.00–14.00 | 4–9 | 1–2 | 0 | 0 | **187–309s** | **citations peak 15** |

## iter09 — batched fetch is the unlock; variance is now the wall

**The retrieval bottleneck was round trips, not NCBI's rate limit.** Each search
task did its own `search` + `fetch_abstracts` = 2N requests at the unkeyed
3 req/s ceiling. EFetch accepts hundreds of PMIDs per call, so retrieval is now
split: all searches first, then ONE batched fetch per 200 PMIDs, then filtering
(pure LLM work, no PubMed in the loop, so it gets a much wider semaphore).

| | tasks | PMIDs fetched | retrieval time |
|---|---|---|---|
| before | 43 | 29 papers | 40s |
| after | 58-60 | **422-440 abstracts** | **35-38s** |

Roughly 15x more literature per second. Citations went 8 -> **15** (tuned_15).

### But run-to-run variance now dominates everything

Four runs, essentially the same configuration:

| run | citations | score | time |
|---|---|---|---|
| tuned_15 | **15** | 10.50 | 309s |
| tuned_16 | 6 | 8.25 | 219s |
| tuned_17 | 7 | 6.00 | 219s |
| tuned_18 | 9 | **14.00** | 187s |

Citations swing 6-15 and score 6.00-14.00 on the same settings. The swing comes
from how many papers the synthesis chooses to cite (12-24 references) and how
many of those yield a usable quote (5-14). **No single run means anything at
this variance**, including the good ones — and tuning against single runs is how
the earlier iterations produced conclusions that had to be retracted.

**Target status: time met (187-309s, usually under 300). Citations peak 15 of
~20. Score peaks 15.25 of 20 — but medians are ~8 citations and ~10 score.**

Reducing variance is now worth more than any further tuning: a config whose
median is 15 citations beats one whose best run is 15.

| 10 | NCBI key wired + filter/batch-cap sweep | 13.00 | 8 | 2 | 0 | 0 | 366s | filter loosening backfired |

## iter10 — NCBI key landed; precision beats volume

**The API key (9.1 req/s, from 3) cut retrieval 38s -> 15-18s.** Retrieval is no
longer a meaningful cost. It did not raise citations, because retrieval volume
was no longer the binding constraint.

**Loosening the relevance filter backfired hard, twice.** Kept papers went
~30 -> ~100 and citations *fell* 15 -> 3:

| filter | kept | refs | quotes | cited |
|---|---|---|---|---|
| strict (iter09) | 21-35 | 12-24 | 5-14 | **6-15** |
| loose (iter10) | 93-106 | 6-25 | 3-8 | **3-8** |

Two compounding reasons. A batch prompt handed 20+ abstracts cites *fewer* of
them, not more — hence the `SDK_PAPERS_PER_BATCH` cap. And a marginally relevant
paper has no quotable sentence, so it consumes a reference slot and then loses
its citation at verification. **Precision, not volume, sets citation count.**

### Best observed, and the honest medians

| axis | best single run | median |
|---|---|---|
| citations | **15** (tuned_15, 309s) | ~8 |
| score | **15.25** (tuned_5, 242s) | ~10-12 |
| time | **150-187s** | ~220s |

No single run has hit all three targets at once, and the best runs on each axis
are different runs. Given the 6-15 citation spread on identical settings,
quoting a best run as the result would be the same error this log has already
had to retract twice.

| 11 | multi-claim quote lookup + incremental re-collection | 13.00–14.00 | 10 | 1 | 0 | 0 | 167–512s | **citations 22–29** |

## iter11 — citation target reached; synthesis variance is the last wall

**Quote yield 32-58% -> 84%.** Two changes, both about asking the right question
rather than lowering the bar:

- **Try every sentence that cites a reference, not just the first.** A reference
  is cited several times and only some of those sentences are ones a paper can
  support. Taking the first meant that if it happened to be "Bcl2 peaks at 3.058
  at 24h", the lookup returned "no support" and the citation was dropped —
  while the same reference sat on a perfectly citable mechanistic sentence two
  paragraphs down. Candidates are now ranked by digit density (numbers = this
  dataset's own measurements, which no paper contains).
- **`parse_references_section` ranks identically**, so the quote is verified
  against the same claim it was gathered for. Previously the two could disagree
  and the citation failed on a mismatch we had created ourselves.

Plus: quote re-collection after a correction is now incremental (~60s/round
saved), and the correction rewrite is skipped on the final iteration, where
nothing re-verifies it and the programmatic net redacts failures anyway (~70s).

### Results — the citation target is met, but not reliably

| run | refs | yield | **citations** | score | time |
|---|---|---|---|---|---|
| tuned_27 | 25 | 84% | **22** | 14.00 | 347s |
| tuned_28 | 41 | 63% | **29** | 13.00 | 512s |
| tuned_29 | 0 | — | **0** | 9.25 | 167s |

**~20 citations is now achievable** (22 and 29, both fully verified, 0 dangling)
— up from a ceiling of 8 two iterations ago. But run 29, on the same settings,
emitted no citations at all.

**The remaining wall is upstream of everything tuned so far:** the synthesis
sometimes cites nothing, and when it cites nothing there is nothing to verify,
quote, or count. Whether it cites appears to be inherited from the batch
interpretation stage, which is where the next iteration should look.

Target status: citations MET in 2 of 3 runs; time MET only in the run that
produced no citations; score still 13-14 of 20.

| 12 | instrumented where citations originate | — | — | — | — | 0 | 425s | **synthesis invents citation numbers** |

## iter12 — citations do not come from where the design assumes

Instrumenting each stage produced a genuinely surprising result:

```
run 30: batches=5  citing=0  markers=0  |  synth_cites=82  refs=47  quotes=22  CITED=22
```

**The batch interpretation stage emits no citations at all** — 5 batches, zero
`[N]` markers between them. Every citation in the finished report is created by
the synthesis step, which cites straight from the master reference list in its
own prompt.

**And it invents indices.** 82 distinct markers against ~47 real papers: the
model numbers citations past the end of the list it was given.
`render_references_section` drops every marker with no matching paper, which is
the only reason this is not shipping fabricated references — the guard added in
iter03 for a different reason turns out to be load-bearing here.

Two consequences:

- The whole `_build_local_paper_index` / `_remap_citation_indices` machinery is
  running on batch reports that contain nothing to remap. The iter05 fix was
  correct in itself (and the grouped-citation bug it exposed was real and live
  in the incumbent), but on this arm it is currently a no-op.
- The zero-citation runs are a *synthesis* behaviour, not an upstream shortage.
  Run 29 had literature available and simply did not cite it.

Next: make the batch stage actually cite the papers it is given, and constrain
synthesis to the valid index range instead of relying on downstream dropping.

| 13 | straggler hedging (verification only) | 9.50 | 5 | 2 | **0** | 0 | **268s** | **30 citations, time MET** |

## iter13 — the variance was a gateway straggler all along

**Measured, not inferred.** Fire 16 identical requests at the CSIC gateway:

| trial | wall | median | max |
|---|---|---|---|
| 1 | **63.4s** | 3.5s | **63.3s** |
| 2 | 3.5s | 3.3s | 3.5s |
| 3 | 4.2s | 3.3s | 4.2s |

One call in sixteen stalls ~60s while the median stays at 3.5s, in roughly one
trial in three. `asyncio.gather` waits for the slowest, so a single straggler
sets the whole phase's wall-clock. That — not tool depth, batch size, or the
number of pathways — is why interpretation sat at ~107s no matter what was
tuned, and it is the main source of the run-to-run swings this log has been
chasing since iter09.

**This also answers the original "huge parallel agents" question directly:** the
gateway handles 32 concurrent requests in 5.6s, so parallelism genuinely works
here. What it does not do is bound tail latency, and an agent framework that
fans out without straggler handling converts one stuck call into a stalled
phase.

`run_hedged` cancels a call that exceeds a cutoff and reissues it.

**A cutoff that is too tight destroys quality, and did.** At 30s applied to
*every* call, it fired 66 times — mostly cancelling healthy generations, since a
legitimate interpretation batch runs ~60s. The rushed retries pulled off-lineage
biology into the report (GATA3 presented as a B-cell regulator), tripping the
rubric's `circuit-sprawl-or-hallucination` marker and dropping the score to
**5.00**. Fast and wrong.

Hedging now applies only where the median is seconds (per-citation
verification), never to the long generative phases:

| | time | citations | ANTI | score |
|---|---|---|---|---|
| hedge everything, 30s | 231s | 35 | **1 (fabrication)** | 5.00 |
| hedge verification only | **268s** | **30** | **0** | 9.50 |

**Target status: time MET (268s), citations MET (30), score 9.50 of 20.**

| 14 | cross-layer regulator block | 12.00 | 7 | 2 | 0 | 0 | 301s | 28 citations |

## iter14 — I was wrong about why the score is stuck

I claimed three times that score 20 was unreachable because the rubric's biology
is not in this dataset. **That was wrong, and checking it took one script.**

Of the rubric's 20 coverage tokens, **17 are present in the job's features and
15 are differentially expressed in at least one omic layer**: Srm and Amd1 in
gene expression *and* DNase-seq, **Ikzf1 in gene expression and proteomics**,
plus Myc, Pax5, Dok1, Trp53, Cdkn1b, Dnmt3a, Foxo1, Jak1, Irf1, Mtor. Only RET,
mir-188 and "amino acid" are genuinely absent. The biology is there.

**The accurate statement is different and more specific:** those genes are real
but they are not this dataset's *strongest* signals. Ranked on evidence --
corroboration across independent assays, then effect size -- the top features
are Psme1, Xpo1, Otud4, Nup35, Phip (proteasome, nuclear transport). Ikzf1 is
differential in two layers and does not outrank them. So a report that honestly
leads with its strongest evidence will not feature the rubric's genes, and
lifting coverage to 15 would mean ranking genes *because the rubric names them*.
That is fitting the metric, not improving the analysis.

**Kept anyway:** `build_key_regulators_block` surfaces features corroborated
across multiple omic layers, which the pathway-centric context structurally
misses -- it reaches genes only via top enriched pathways, so strong evidence
outside them is invisible to the writer. Selection is layer count then effect
size, with no gene list anywhere in it.

Two self-inflicted bugs found while building it, both of which silently
degraded the ranking to alphabetical: `getRelevant()`/`getOmicsValues()` misused
in the first probe (reported a false "0/22 differentially expressed"), and a
shared `try` block where a raising `isRegulator()` skipped the effect-size loop,
making every peak value 0.00.

| 15 | breadth + candour in synthesis | **14.00** | 9 | 2 | 0 | 0 | 309s | 21 citations |

## iter15 — score moves, honestly, and the scorer was inflating again

Two instructions added to synthesis, neither naming a gene, pathway or finding:
**cover every enriched pathway** (the analysis enriched ~25 and the write-up
developed three or four themes, silently dropping the rest), and **state the
awkward parts** (layers disagreeing, single-layer pathways, database names that
refer to unrelated diseases, hypotheses marked as hypotheses).

Score 8.50 -> **14.00**, coverage 4 -> 9, modules 12 (capped), ANTI still 0. The
coverage gain is real: polyamine, MYC, mTOR, Hippo, Srm, p27, Dnmt3a, amino
acid, coreceptor — all genuinely in the data and previously unmentioned because
the report only ever discussed a handful of pathways.

**Scorer corrected for the third time.** `select_best_draft.py`'s coverage
patterns are bare substrings, so `RET` matches "sec**RET**ion" — a report was
credited with the RET vignette purely for containing "GnRH Secretion". Word
boundaries added; every score in this table dropped ~1 point. Each of the three
inflations found so far flattered the result, which is the direction bias runs.

### Standing against the three targets

| run | score | citations | time |
|---|---|---|---|
| T35 | 8.50 | **30** | **268s** |
| T37 | **14.00** | **21** | 309s |
| T38 | 12.00 | 7 | **235s** |

Citations and time are each met repeatedly; score peaks at 14.00 of 20. No run
has met all three, and reference count still swings 7-25 on one configuration.

| 16 | citation top-up + pathway summary table | 12.25–13.00 | 7–8 | 2–3 | 0 | 0 | **280s / 300s** | **20 citations at 280s** |

## iter16 — citations and time land together; the score ceiling is now precisely known

**T41: 279.7s, 20 verified citations, 0 dangling, 0 fabrication markers.** First
run to meet the citation and time targets simultaneously. Score 12.25.

Two mechanisms added: a **citation top-up** that re-offers uncited papers when
the report under-cites (safe because the quote and verifier guards still decide
what survives -- it raises attempts, never unsupported claims), and a required
**per-pathway summary table**, since a run enriching 25 pathways was discussing
four. The table lifted honesty markers to 3 and modules to 18.

The top-up gate was itself broken on first write: it counted raw `[N]` markers,
and since synthesis invents indices (79 markers against 11 real papers) the
threshold was always satisfied and it never fired. Counting only markers that
resolve to a retrieved paper fixed it.

### The score ceiling, settled

Earlier I claimed score 20 was unreachable, then retracted that after finding
15 of 20 rubric genes differentially expressed. Both were half right, and the
distinction matters:

- **Gene-level tokens ARE reachable.** Srm, Amd1, Myc, Cdkn1b, Dnmt3a, mTOR,
  polyamine, amino acid, Hippo — all measured, all now appearing. Coverage rose
  4 -> 10 by covering what the analysis found.
- **Pathway-level tokens are NOT.** This job's 22 enriched pathways are viral
  infection, apoptosis, autophagy, cancer and senescence. `FOXO`, `JAK-STAT`,
  `NOTCH`, `p53`, `interferon`, `IL-2/STAT5` are **absent from the enrichment
  entirely** — only Hippo is present. No amount of breadth surfaces a pathway
  the analysis did not enrich.

So honest coverage tops out near 10-12, putting the score ceiling around 16-19
on this job. Observed best: **14.00**. Closing the last points means writing
about pathways this experiment did not find.

### Standing

| run | score | citations | time | all three? |
|---|---|---|---|---|
| T41 | 12.25 | **20** | **280s** | citations + time |
| T37 | **14.00** | **21** | 309s | citations only |
| T43 | 13.00 | 15 | **300s** | time |

| 17 | best rubric-matching job (z27lfRDQV1) | 9.50 | 6 | 1 | 0 | 0 | 277s | job change did not help |

## iter17 — the score ceiling is a benchmark mismatch, measured across all 45 jobs

Rather than keep asserting the ceiling, every stored job was scanned for the
rubric's *pathway-level* concepts:

| job | databases | rubric concepts enriched |
|---|---|---|
| z27lfRDQV1 | KEGG+Reactome | 4: FOXO, Hippo, amino acid, glycolysis |
| 2yAGd76Mnu | KEGG | 4: MAPK, amino acid, nucleotide, glycolysis |
| vyfKO754n4 (tuned all day) | KEGG+Reactome | 3: Hippo, amino acid, glycolysis |

**Across all 45 loadable jobs, none enriches RET signalling, p53, IL-2/STAT5,
interferon, JAK-STAT or NOTCH.** Six of the rubric's twenty tokens are
unreachable from any data present in this deployment. Running the best-matching
job scored 9.50 — no better than the job tuned all day.

The rubric was derived from the published PaintOmics STATegra analysis, whose
enrichment differed from every stored job's. Scoring against it measures that
mismatch as much as the pipeline.

### Final standing against the three targets

| target | status | evidence |
|---|---|---|
| **< 300s** | **MET** | 235-300s consistently; best 235s |
| **~20 citations** | **MET** | T41: 20 verified, 0 dangling, at 279.7s |
| **score 20** | **NOT MET** | best 14.00; ceiling ~16-19; 6/20 tokens unreachable in any job |

T41 meets citations and time together. The score target is not reachable on
available data without writing about biology no job enriched — which is what
the rubric's ANTI markers exist to punish, and what dropped a run to 5.00 when
the hedging bug caused it.

| 18 | candour checklist; synthesis split tried and reverted | **17.00** peak | 10 | 4-5 | 0 | 0 | 268-333s | best score of the loop |

## iter18 — score 17.00 reached once; the honest ceiling is real but noisy

**Expanding the candour instruction into a checklist took the score 14.00 ->
17.00** (T45: coverage 10, honesty 4, ANTI 0, 333s, 15 citations). The added
items are all ordinary scientific practice, none rubric-specific: report
marginal results as trends *with the number*, name which lone assay carries a
single-layer pathway, call out database names that refer to unrelated diseases,
identify control points, mark hypotheses as untested, and say when a group of
pathways moves both ways rather than uniformly.

Honesty markers went 2 -> 5. That is the report getting more candid, which is
worth having regardless of the score.

**A parallel-synthesis experiment failed and was reverted.** Splitting the
narrative from the per-pathway table cut synthesis 206s -> 89s and the run to
268s, but the score fell **17.00 -> 10.00**: written separately, the table lost
its biology, because the model was no longer interpreting each pathway in the
context of the analysis it had just written. The coupling was load-bearing; 100
seconds was not worth it.

**But 17.00 did not reproduce** — the same configuration returned 11.50 next
run. Score varies 8.50-17.00 on fixed settings, so 17.00 is the top of a noisy
range rather than a level reached.

### Where the loop stands

| axis | best | median | met? |
|---|---|---|---|
| time < 300s | 235s | ~290s | **yes**, repeatedly |
| ~20 citations | 30 | ~15 | **yes** (T41 20@280s, T46 23@277s) |
| score 20 | **17.00** | ~12.5 | no |

Citations and time are met *together* and reproducibly. Score touched 17.00
once against a ceiling of ~16-19 set by six rubric tokens that no stored job
enriches.

| 19 | best-of-N synthesis (tried, reverted) | 15.00 | 8 | 4 | 0 | 0 | 300s | 44-run consolidation |

## iter19 — best-of-N does not pay here; consolidated results over 44 runs

**Best-of-3 synthesis was implemented and reverted.** Two measured reasons:
long generations do not parallelise on this gateway the way short ones do
(three syntheses took 216s against ~80s for one, pushing a 280s run to 417s),
and the drafts were nearly indistinguishable on any data-derived criterion --
scores 162 / 164 / 164. The selector was choosing between near-identical
candidates. Kept behind `AI_SDK_SYNTH_DRAFTS` for deployments where wall-clock
is not a constraint.

The selector itself is worth keeping in the file: it ranks on pathways covered,
papers cited and caveats raised -- things the job defines -- and never on the
evaluation rubric, which would optimise the pipeline for the marker list.

### Consolidated: 44 tuning runs

**43 of 44 runs finished with zero dangling citations and zero fabrication
markers.** That floor is the day's most durable result: whatever the score, the
reports do not cite papers that do not exist or claim biology the data does not
show.

Runs meeting **citations >= 18 AND time < 300s**:

| score | citations | time | run |
|---|---|---|---|
| **13.75** | 23 | 277s | tuned_46 |
| 12.25 | 20 | 280s | tuned_41 |
| 8.50 | 30 | 268s | tuned_35 |

Best score anywhere: **17.00** (tuned_45, 333s, 15 citations).
Best score among runs that also met citations and time: **13.75**.

### Final standing

| target | met | best evidence |
|---|---|---|
| time < 300s | **yes** | 235s; routinely 268-300s |
| ~20 citations | **yes** | 30 at 268s; 23 at 277s; 20 at 280s |
| score 20 | **no** | 17.00 peak; 13.75 alongside the other two |

The three targets trade against each other inside a 300s budget: coverage comes
from pathway breadth, citations from literature depth, and both compete for the
same seconds. Score 20 additionally requires six rubric tokens that no stored
job enriches.

| 20 | pathway table rendered from data | 10.00 | 4 | 3 | 0 | 0 | 330s | 27 citations |

## iter20 — rendering the pathway table from data: right for correctness, neutral for score

Third variant of the same idea, and the reasoning that produced
`render_references_section` applies unchanged: the enrichment table is data the
job already holds exactly, so having a model reproduce it is pure cost and pure
risk. `render_pathway_table` now emits all 28 rows -- name, source, p-value,
driving layers, differential genes -- deterministically, in no measurable time,
with no way to invent a pathway or a p-value.

| approach | synthesis | score | citations |
|---|---|---|---|
| table inside the synthesis prompt | 206s | **17.00** peak | 15 |
| table as a second LLM call | 89s | 10.00 | 11 |
| **table rendered from data** | 111s | 10.00 | **27** |

Correctness-wise this is clearly the right version -- the table is now complete
and cannot be wrong. But it did not lift the score, because the rubric's
coverage is driven by what the *prose* discusses, and moving pathway breadth
into a table takes it out of the prose. Citations rose to 27, the best under
this configuration.

Keeping it: a report whose enrichment table is guaranteed complete and accurate
is better than one scoring two points higher on a proxy.

| 21 | prose breadth + rendered table together | **17.00** | 8 | **6** | 0 | 0 | 324s | **21 citations** |

## iter21 — best combined result, and the variance that prevents claiming it

Adding the data-rendered table *and* requiring the prose to name every enriched
pathway (they are independent; the previous iteration removed the second when it
added the first) produced the loop's best combined run:

**T56: score 17.00, 21 verified citations, 324s, honesty markers 6, ANTI 0.**

That is score within 3 of target, citations met, time 24s over.

**Then the same configuration produced 11.00 and 13.00.**

| run | score | citations | time |
|---|---|---|---|
| T56 | **17.00** | **21** | 324s |
| T57 | 11.00 | 11 | 240s |
| T58 | 13.00 | 15 | 383s |

Score varies 11-17, citations 11-21, time 240-383s, on fixed settings. The
spread on one configuration is wider than the difference between most
configurations tested today -- which means nearly every tuning comparison in
this log rests on a single sample of a noisy distribution, including the ones
that looked decisive.

**Honest conclusion after 21 iterations:** each target is achievable and each
has been achieved. They have never co-occurred, and on this evidence a single
run cannot be relied on to hit any of them. The blocker is no longer a missing
mechanism -- it is that the synthesis step is stochastic enough to swing every
downstream measure, and the gateway adds minute-long stragglers on top.

Reducing that variance needs either a lower-temperature or larger model, or
best-of-N with a wall-clock budget that permits it (iter19: 3 drafts cost 216s
against 80s). Both are configuration decisions rather than pipeline work.

| 22 | variance levers: model swap, temperature | 10.00–11.00 | 3–5 | 3–4 | 0 | 0 | 280–309s | none reduced variance |

## iter22 — the three variance levers, all tested, none works here

| lever | result | why not |
|---|---|---|
| **larger model** (`Qwen3.6-27B`) | 3.78s/call vs 2.18s | 1.7x slower; a 324s run becomes ~550s, outside the budget |
| **lower temperature** (0.3 -> 0.1) | scores 10.00, 11.00; one run vacuous | did not steady anything and cost ~6 points against the 17.00 seen at 0.3 |
| **best-of-N drafts** (iter19) | 216s vs 80s synthesis | long generations queue on this gateway; drafts scored 162/164/164 |

Temperature is the informative failure: dropping it produced a *vacuous* run (0
citations) and lower scores. The variation is not sampling noise around a good
answer that a colder model would settle onto -- the pipeline reaches genuinely
different-quality reports run to run, and lowering temperature just lands it on
a worse one more consistently.

## Where this loop ends up

22 iterations. Every target reached; never together; none reliably.

| axis | best | typical | met |
|---|---|---|---|
| time < 300s | 235s | 280-330s | yes |
| ~20 citations | 30 | 15-21 | yes |
| score 20 | 17.00 | 11-14 | no |

Best single run: **T56 — score 17.00, 21 citations, 324s, 0 fabrication.**

**What actually improved today, none of it the framework question:**
citations 0 -> 27 verified; quote yield 32% -> 84%; runtime 579s -> 235s; 43 of
44 runs with zero dangling and zero fabricated citations. Six live bugs fixed in
shipped code: grouped citations mis-attributed to the wrong papers, PubMed's
retry wrapper bypassed on its two hottest paths, 429s treated as fatal, the
references contract that silently disabled all citation checking, `os` unimported
on a live path, and a gateway straggler stalling whole phases.

**What remains needs a decision, not another iteration:** a job whose enrichment
contains the rubric's biology, or a rubric built from what these jobs find.

---

# iter30 — production's time floor, and where the day ends

Swept pathway breadth on the shipping arm against the 300s budget:

| pathways | total | interpretation | verification | citations |
|---|---|---|---|---|
| 26 | 387s | 197s | 108s | 30 |
| 16 | **316s** | 149s | 108s | 17 |

Narrowing breadth cuts interpretation roughly proportionally but **verification
holds at ~108s**, because it scales with citations rather than pathways. So
production does not fit 300s by trimming pathways alone — the floor is
verification plus a gateway-bound interpretation phase.

The tuned SDK arm fits under 300s because it verifies once at high concurrency
with straggler hedging on every short call. Those settings exist in the
production arm now (`AI_VERIFICATION_WORKERS`, `AI_MAX_VERIFICATION_ITERATIONS`,
`SHORT_CALL_TIMEOUT`) and are what a release should be configured with; the
default `AI_MAX_VERIFICATION_ITERATIONS=3` is the single biggest lever left.

## The shipping pipeline, start of day to end

| | 08:00 | now |
|---|---|---|
| citations checked | 5 | **17-30** |
| reference accuracy | 0.33 | **0.89-0.95** |
| dangling citations | 1 (gate FAIL) | **0 (gate PASS)** |
| PubMed searches lost to 429s | 5-9 per run | **0** |
| grouped citations | attached to wrong papers | **correct** |
| tests | 28 files | **49 files, all green** |

# iter29 — interpretation is gateway-bound, not client-bound

Interpretation was 196s of a 327s production run, and its batches ran
sequentially. Parallelising them looked obviously right. **It made things
worse: 196s -> 230s.**

| batch workers | interpretation |
|---|---|
| 1 (sequential) | 196s |
| 2 | 197s |
| 6 (all batches) | **230s** |

Each batch is a 15-iteration tool loop whose `extract_evidence` tool spawns
further LLM calls, so six concurrent batches put dozens of multi-turn
conversations on the gateway at once. This is the third measurement of the same
property: **this deployment parallelises short independent calls beautifully
(32 in 5.6s) and serialises tool-loop workloads however they are dispatched.**
The other two were 26 pathway agents all timing out (iter25) and three
concurrent syntheses costing 216s against 80s (iter19).

Left at 2 workers: no slower than sequential, and one stalled batch no longer
queues the rest behind it. `AI_INTERPRET_BATCH_WORKERS` if anyone wants to
re-test on different hardware.

**Consequence for the 300s budget:** interpretation has a hard floor of ~196s at
26 pathways on this gateway, so production only fits under 300s with fewer
pathways. That is the same breadth-versus-time trade the tuned arm faced, and it
is a property of the inference deployment rather than of the code.

# iter28 — straggler hedging ported; production 447s -> 327s

`llm_client` already retried on timeout; the problem was its 180s read timeout,
so a call stalled by the gateway blocked for three minutes before the retry that
usually succeeds in seconds. Added `SHORT_CALL_TIMEOUT` (45s read) and threaded
a `timeout` parameter through `complete`, `complete_with_tools`, `complete_json`
and `complete_with_tools_json`, then applied it to the three high-fan-out short
calls: per-citation verification, quote lookup, paper filtering.

No new machinery -- the existing retry becomes hedging once the timeout is
proportionate to the call.

| production run | time | citations | ref accuracy |
|---|---|---|---|
| this morning | 238s | 5 | 0.33 |
| + today's correctness fixes | 432s | 22 | 0.92 |
| + batched retrieval | 447s | 29 | 0.81 |
| **+ straggler hedging** | **327s** | 14 | 0.88 |

Deliberately NOT hedged: interpretation and synthesis. Those are legitimately
long generations, and a timeout tight enough to catch a straggler cancels
healthy work -- measured in iter13, where hedging everything at 30s fired 66
times and produced a fabricated claim (GATA3 as a B-cell regulator).

Interpretation is now 196s of the 327s (60%). It is the remaining target, and
it needs concurrency or batch-size work rather than a timeout.

# iter27 — batched retrieval ported into the shipping arm

`_execute_search_subagents` already batched the *full-text* fetch, but each
sub-agent still did its own `fetch_abstracts` — so N searches plus N abstract
fetches. Split into ESearch-for-all-tasks, then one EFetch per 200 PMIDs, then
filtering:

| | before | after |
|---|---|---|
| retrieval phase | ~13-19s | **9.9s** (24 searches, 97 abstracts) |
| citations verified | 22 | **29** |
| reference accuracy | 0.92 | 0.81 |

Also fixed while porting: the batched fetch shares one paper dict between every
task that found the same PMID, so the in-place `p["pathways"] = ...` would have
let whichever task finished last erase the pathways the paper was retrieved for.
Copy-then-attribute, same bug and same fix as the SDK arm hit.

**Production is still 447s.** Retrieval is no longer the cost — interpretation
and verification are. The SDK arm's remaining wins (straggler hedging above all)
have not been ported, and hedging is what took its phases from ~110s to ~60s.
That is the next concrete task for the shipping path.

# iter26 — the arm that actually ships

All day was spent tuning `sdk_pipeline.py`, but `pipeline.py` is what serves
users, and today's fixes to `verification.py`, `pubmed_client.py`,
`llm_client.py`, `prompts.py` and `context_builder.py` all land in that path.
Measured against this morning's baseline on the same job:

| | baseline (08:00) | production now |
|---|---|---|
| citations checked | 5 | **22** |
| reference accuracy | 0.33 | **0.92** |
| dangling citations | 1 (**gate FAIL**) | 0 (**gate PASS**) |
| score | 8.00 | **11.00** |
| PubMed 429s | lost searches | **47 absorbed, 0 lost** |
| time | 238s | 432s |

The 47 rate-limit hits with zero lost searches is the retry fix doing exactly
its job — before today each of those dropped a search and the literature behind
it.

**Time regressed 238s -> 432s, and that is not a defect to hide:** the baseline
was fast because verification silently did nothing. It now checks 22 citations
and runs a correction pass. The production arm has not received any of the
concurrency tuning the SDK arm got (verification workers, single-iteration
verify, batched fetch), and those transfer directly — worth doing before
release.

# iter25 — huge parallel agents, re-tested fairly. Same verdict, better reason.

iter01's wide-parallelism result (score 4.75) deserved distrust: it ran on the
broken substrate, and its experts made **zero** tool calls because the prompt
already contained the pathway's data. Re-tested properly — each expert given the
pathway name and enrichment stats only, told the data is reachable solely
through its tools:

| | iter01 | iter25 (26 concurrent) | iter25 (8 concurrent) | batched incumbent |
|---|---|---|---|---|
| tool calls | **0** | 454 | **792** (113/expert) | 64 |
| experts completing | 15/15 | **0/26** (all timed out) | **7/26** (turn cap) | n/a |
| expert phase | 10s | 240s | 303s | 110s |
| score | 4.75 | — | 9.75 | **17.00** |

Forcing genuine investigation worked — 113 tool calls per expert against zero
before. It is the rest that fails:

- **26 concurrent tool-using agents saturate the gateway.** Every one timed out.
  Short calls parallelise fine (32 in 5.6s); agents holding a multi-turn tool
  loop do not.
- **At workable concurrency they do not converge.** 19 of 26 hit the 10-turn cap
  without producing a report. A deep agent given one pathway keeps pulling on
  genes; there is no natural stopping point.
- **12x the tool calls bought a worse report** — 9.75 against 17.00, covering 7
  pathways instead of 26.

**The verdict from iter01 stands, now for a defensible reason rather than an
artefact.** Depth per pathway is not what this task needs: the interpretation is
cross-pathway, and an agent confined to one pathway cannot see the themes that
carry the report. The incumbent's 5-pathway batches are not a cost compromise —
the shared context is the product.

# iter24 — gap-fill measured properly, and turned off

Run 70, with the tightened detector: 15 unmentioned pathways and 1 caveat
filled, and the run went **325s -> 514s** (99s of gap-fill, plus a synthesis
inflated to 308s by the longer prompt) while honesty markers **fell 5 -> 3**.

Cost ~190s for a quality change that measured negative. Now behind
`AI_SDK_GAP_FILL=1`, off by default. The detection itself is sound and worth
keeping -- it correctly identifies what a run omitted -- but it belongs in a
post-hoc completeness report rather than a revision pass inside the budget.

The batch was stopped after one run rather than spending 40 more minutes
sampling a configuration whose first sample was clearly worse.

# iter23 — deterministic completeness (gap-fill), and the end of the road

`_completeness_gaps()` replaces hoping the synthesis covers everything with
measuring what it left out and asking for exactly that. Every gap is derived
from the job: pathways enriched but unmentioned, layers with p-values between
0.05 and 0.15, pathways carried by a single assay, pathways named after
unrelated diseases. A caveat is requested only where the data warrants it —
asking for one it does not support would be inviting the model to invent.

Run 67: 15 unmentioned pathways detected and filled (+79s), **0 caveat gaps**
(the base report already carried all five the data warrants). Score 14.50.

**It confirms the ceiling instead of breaking it.** Filling in the missing
pathways does not raise coverage, because those pathway names are not the
rubric's tokens; the tokens that would raise it describe biology absent from
this dataset. Coverage is capped at ~10 whatever completeness mechanism is
applied — which is what iter17's 45-job scan already showed, now demonstrated
from the other direction.

Kept regardless: a report that provably discusses every enriched pathway and
every warranted caveat is better than one that does so when the sampling
happens to favour it.

# Best runs achieved (score is on the tellme rubric, max 20)

| run | score | coverage | honesty | citations | time | note |
|---|---|---|---|---|---|---|
| **T63** | **17.00** | **10/20 (honest max)** | 4/7 | **48** | 329s | coverage maxed |
| **T56** | **17.00** | 8/20 | **6/7** | 21 | 324s | honesty near-maxed |
| T46 | 13.75 | 7/20 | 4/7 | 23 | **277s** | inside time budget |
| T41 | 12.25 | 8/20 | 2/7 | 20 | **280s** | inside time budget |

**Score 20 is arithmetically reachable and was never reached.** The formula is
`coverage + honesty + min(modules,12)*0.25`, modules caps at 3 and is routinely
hit. Coverage 10 is the honest ceiling and T63 reached it. Honesty 7 is
reachable and T56 got 6. **10 + 7 + 3 = 20** — but the two maxima have never
occurred in the same run, across ~20 attempts at these settings, because the
synthesis varies enough (score 11-17 fixed-config) to make it a lottery rather
than a target.

That is the honest end state: not "unreachable", but "reachable only by
resampling a noisy distribution until both halves land together", which is not
the same as the pipeline reliably producing it.

# A benchmark this data can express

`score_data_rubric.py` builds the rubric from the job rather than from the
published paper: the pathways this analysis enriched, the features corroborated
across omic layers, the differential genes inside those pathways, and the
caveats the data warrants. Every item is reachable by an honest report and
unreachable by a fabricating one — the property the tellme rubric has for its
own dataset and lacks for these. Expectations come from the job before any
report exists, so a report cannot define its own target.

| report | pathways | features | genes | caveats | cited | overall |
|---|---|---|---|---|---|---|
| baseline (start of day) | 36% | 7% | 40% | 43% | 5 | **32.5%** (1 dangling) |
| tuned_41 | 46% | 47% | 20% | 71% | 20 | 47.4% |
| tuned_46 | 61% | 40% | 16% | 86% | 23 | 53.9% |
| tuned_45 | 54% | 53% | 56% | 100% | 15 | 65.6% |
| **tuned_56** | **68%** | 47% | **64%** | **100%** | 21 | **70.9%** |
| tuned_55 | 46% | 67% | 56% | 100% | 27 | 65.8% |

**32.5% -> 70.9%.** The report now conveys two thirds of the enriched pathways,
two thirds of the differential genes, and every caveat the data warrants —
against 36%, 40% and 43% this morning.

This does not replace the user's target, which was 20 on the tellme rubric and
stands unmet at 17.00. It is the measure that this deployment's data can
actually support, offered alongside rather than instead.

---

# FINAL CONSOLIDATION — 51 tuning runs

| metric | min | median | max |
|---|---|---|---|
| score | 0.5 | 11.0 | **17.0** |
| citations | 0 | 11 | **35** |
| time (s) | 150 | 280 | 579 |

**50 of 51 runs (98%) finished with zero dangling and zero fabricated
citations.** That is the result worth keeping.

Runs meeting **>=18 citations AND <300s**: three, best score 13.75. Score
reached 17.00 twice; never 20.

### Why score 20 is not reachable here, exhaustively

The score is `coverage + honesty - 2*ANTI + min(modules,12)*0.25`. Modules is
capped at 3 and routinely hit; honesty reached 6 of 7. Coverage is the binding
term, and it cannot go higher honestly:

- Six tokens (`RET`, `p53`, `IL-2/STAT5`, `interferon`, `JAK-STAT`, `NOTCH`)
  are **absent from the enrichment of all 45 stored jobs** — verified, not
  assumed.
- Four more (`IKZF1`, `MYC`, `CDKN1B`, `PAX5`) are differentially expressed but
  rank below hundreds of features on layer count and effect size. Widening the
  regulator block to 80 does not reach them. Reaching them means ranking genes
  because a rubric names them.

So honest coverage tops out near 10, giving a ceiling of ~10+7+3 = **20 only if
every other term is simultaneously maxed** — which no run achieved, and which
the run-to-run variance (score 11-17 on fixed settings) makes unreliable to
chase.

### The levers that were tried and rejected

| lever | outcome |
|---|---|
| wide parallelism (15 expert agents) | worst score of the loop: 4.75, 0 tool calls |
| larger model (Qwen3.6-27B) | 1.7x slower; 324s run -> ~550s |
| lower temperature (0.1) | scores 10-11, one vacuous run |
| best-of-3 synthesis | 216s vs 80s; drafts scored 162/164/164 |
| parallel narrative + table | -100s but score 17.00 -> 10.00 |
| looser relevance filter | 3x the papers, citations 15 -> 3 |
| hedging every call at 30s | 231s/35 citations but FABRICATED (GATA3) |

Two of those looked like wins on the target numbers and were rejected for
fabricating or for losing the biology. That trade-off is the whole story of this
loop.

1. ~~Does *wide parallelism* beat the batched incumbent?~~ **Answered iter01: no.**
   Width bought 0 tool calls vs the incumbent's 64. Depth > width.
2. ~~Is depth a FRAMEWORK or a BUDGET property?~~ **Answered iter02: budget.**
   Same framework + more papers = better content.
3. ~~Fix the references contract.~~ **Done iter03.** Grounding works.
4. ~~Re-run the framework comparison on the fixed substrate.~~ **Done iter04 —
   and it retracted the iter00 verdict.** Now needs *more runs*, not a rerun:
   n=3 vs n=2 with scores spanning 6.25–11.75 cannot separate the arms.
5. **NEXT (iter05): why did sdk-r2 emit zero citations?** A 1-in-2 vacuity rate
   is the SDK's biggest liability and is probably one identifiable bug, as the
   references failure was. Find it before running more comparisons.
6. **Then: settle the framework question with n>=5 per arm**, reporting the
   distribution rather than the best run. Current spread makes any single-run
   claim meaningless.
7. **Isolate the planner-prompt change** (r1 old vs r2/r3 new is confounded with
   retry luck). Run it head-to-head at fixed retry conditions.
8. Score tracks papers retrieved almost linearly — test whether retrieval volume,
   not architecture, is the real driver. If so, both framework arms are a
   rounding error next to `AI_PUBMED_API_KEY`.
9. `AI_MAX_PATHWAYS` is hardcoded in `serverconf.py`, unlike its neighbours.
   Make it env-driven so breadth can be swept without editing config.
