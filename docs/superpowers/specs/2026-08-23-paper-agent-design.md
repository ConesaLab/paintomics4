# PaintOmics Paper Agent — design

**Date:** 2026-08-23 · **Status:** proposal, nothing built · **Supersedes** the round-2 plan's M1/M3 (upstream DE stage — dropped: statistics are the user's job upstream) and M8 #7 (standalone correlation tool — dropped: the regulatory network already exists, the agent must *read* it).

## 1. The idea in one paragraph

A job that has finished Step 3 already holds everything a Results section is made of: pathway enrichment per omic and combined, the pathway-similarity network, MORE regulator→target relationships with per-condition coefficients, KGML/OmniPath evidence for those relationships, metabolite classes and hub neighbourhoods, and per-feature values. Today one agent with sixteen tools reads a slice of that and writes an interpretation. The Paper Agent is a second, larger entry point — **"Write the paper"** — that runs a small team of *specialist analysts*, each with a narrow toolbelt and a mandatory output contract, in parallel over the job; a *Lead author* then assembles their notes into a manuscript with publication-grade figures, a deterministic Methods section, and a verification gate that refuses any number not traceable to a tool result. Every analysis is a tool module; every figure is a typed archetype; every number has a provenance id.

## 2. Why a team and not a bigger single agent

Measured on this codebase: the single Lead was offered `compare_sets` in 19 tool schemas on one run and never chose it; nudges at the 600 s budget are inert; a tool "needs an occasion, not a signature". Adding fifteen more tools to one agent makes choice worse, not better. A specialist with five tools and a contract that says *"return PCA variance, PERMANOVA and an outlier statement"* cannot skip the analysis — the occasion is the job description. The Lead author then has no tools to *compute* with, only to *read* — which is the division of labour a real paper has.

Alternatives considered: (B) one agent, all tools, longer budget — rejected for the reason above; (C) fully deterministic pipeline with the LLM only narrating — most reliable numbers but no adaptive depth (cannot decide which pathway deserves a drill-down), which is the one thing the current interpreter does well. The design is A with a deterministic *mandatory pass* inside each specialist, i.e. a hybrid of A and C.

## 3. Architecture

```
Step 3 done ──► [Write the paper] ──► PySiQ worker: run_paper_agent(jobID)
                                          │
        Phase 0  Prelude (code, 0 LLM)    │  PaperContext = LoopContext
                                          │    + JobGraph (networkx)
                                          │    + condition axis, data limits
                                          │    + top movers, comparison inventory
                                          │    + FactsLedger (empty)
                                          ▼
        Phase 1  Specialists (parallel, ≤3 at a time, ≤300 s each)
           ┌────────────┬────────────┬────────────┬────────────┬────────────┬────────────┐
           │ Design&QC  │ Pathway    │ Enrichment │ Network    │ Metabolite │ Literature │
           │ analyst    │ analyst    │ analyst    │ analyst    │ analyst*   │ analyst    │
           └─────┬──────┴─────┬──────┴─────┬──────┴─────┬──────┴─────┬──────┴─────┬──────┘
                 └────────────┴────────────┴─────┬──────┴────────────┴────────────┘
                                                 ▼   AnalysisNote per specialist
        Phase 2  Lead author (tools: read_note, get_fact, cite, check_my_citations, submit_paper)
                                                 ▼
        Phase 3  Gate (code): facts substitution → numbers check → citations → italic genes
                 → figure ids → Methods (generated) → Supplementary tables → store
                                                 ▼
                 paperCollection {markdown, sections, figures, tables, methods,
                                  verification, notes, graph_summary}
        * only when the job has a compound layer
```

Runs inside the existing `_agent_semaphore` (AI_MAX_CONCURRENT_PIPELINES) on a PySiQ worker — no Flask request thread ever blocks. Target wall clock ≤ 20 min (specialists 2 waves × 300 s + Lead 400 s + gate), progress streamed to the client as today via `AIInterpretDAO.save_progress`-style heartbeats.

### 3.1 The specialists and their toolbelts

| Specialist | Tools (all existing or in this plan) | Mandatory contract (the occasion) | Results subsection it owns |
|---|---|---|---|
| **Design & QC** | `get_experiment_overview`, `sample_ordination` (v2: loadings, PERMANOVA, correlation, outlier/batch), `top_movers`, `data_limits`, `make_figure(pca, samplecorr)` | axis kind; per omic: n samples/conditions, replicates yes/no, PCA variance, PERMANOVA p + min attainable, outlier statement, top-5 movers per layer | "Data overview and quality" |
| **Pathway** (today's Lead, narrowed) | `get_pathway_details`, `cluster_pathways`, `list_pathway_genes`, `get_gene_measurements`, `delegate_interpretation`, `make_figure(timecourse, heatmap, enrichment)` | enrichment figure; one paragraph per significant cluster; named genes with values | "Pathway-level changes" (per cluster) |
| **Enrichment** | `enrich_collection(GO_BP/MF/CC, Hallmark, custom; direction up/down/both)`, `run_gsea`, `compare_sets` (descriptor grammar), `concordance_test`, `make_figure(nes_dotplot, gsea_running, venn, upset, concordance)` | GO/GSEA tables per omic and contrast; every available cross-layer/cross-contrast comparison from the inventory tested | "Functional enrichment beyond pathways"; "Agreement across layers and contrasts" |
| **Network** | `graph_schema`, `graph_neighbors`, `graph_hubs`, `graph_path`, `graph_subgraph`, `graph_evidence`, `make_figure(network)` | top regulators by out-degree × evidence; per significant pathway the regulatory subgraph; supported/novel/unsupported split | "Regulatory relationships" |
| **Metabolite** | class activity, hub neighbourhoods, compound movers, `make_figure(heatmap)` | class-level table; hub compounds with neighbour agreement | "Metabolite-level findings" |
| **Literature** | `search_literature`, `read_paper`, `notebook_write` | quote shelf tagged by pathway/gene — no prose | (feeds Discussion) |

Each specialist returns an `AnalysisNote` (structured, not prose): `findings[] {sentence, fact_ids[], figure_ids[], confidence}`, `figures[]`, `tables[]`, `caveats[]`, `unused_occasions[]` (what the contract asked for that could not be computed, with the reason — this is what reaches the paper's Limitations and the harness's GAPS).

### 3.2 The FactsLedger — numbers by construction

Every tool result registers the numbers it prints: `ledger.add(kind='pvalue'|'q'|'log2fc'|'percent'|'count'|'coef'|'r2'|'n', value, scope={omic, condition, feature|pathway|edge}, tool, call_seq)` → a short id (`f17`). Tool text shows the id beside the number (`p = 3.2e-4 [f17]`). The Lead writes `{{f17}}` in prose; the gate substitutes the formatted value, and **any bare number in a Results sentence that is not a fact id, a year, a citation index or a condition label is rejected** (one re-emission while >120 s remain, else the sentence is redacted). This replaces the regex attribution heuristic of the round-2 plan with a mechanism that cannot misattribute.

### 3.3 JobGraph and the network tools (the neo4j lesson, without neo4j)

What works when an LLM reads a graph store (Neo4j's own agent tooling, LangChain's graph chains) is **schema first, then a few typed traversals** — free-form query generation is where agents fail. The graph here is small (hundreds to a few thousand edges), so it is built in-process with `networkx` at Phase 0; no daemon, nothing new in the deploy image.

Nodes: `gene` (job feature: symbol, ids, values per condition, relevant flags), `regulator` (MORE regulatory omic feature: miRNA/TF/region/…), `compound`, `pathway` (id, source, combined p, per-omic p). Edges:

| type | from → to | properties | source |
|---|---|---|---|
| `REGULATES` | regulator → gene | `coef{condition}`, `strongest_condition`, `target_r2`, `omic`, `area`, `method (PLS1/MLR)`, `evidence ∈ {supported, novel, unsupported}`, `support[]` | MORE table (`_RegulationTable`) + `PathwayEvidence` classification |
| `MEMBER_OF` | gene/compound → pathway | `matched_by` | job pathways |
| `KGML` | gene → gene | `relation_type (activation, inhibition, PPrel, GErel…)`, `pathway_id` | KGML relations (`PathwayEvidence.kgmlGraph`) |
| `OMNIPATH` | gene → gene | `sign`, `sources[]` | OmniPath source, where installed |
| `SIMILAR_TO` | pathway ↔ pathway | `shared_features`, `jaccard` | the Step-3 pathways network |
| `NEIGHBOUR_OF` | compound ↔ gene/compound | `distance` | metabolite hub analysis |

Tools (read-only, every output bounded and ranked, every number ledgered):

- `graph_schema()` — node/edge counts by type, property keys, three example edges per type. Called first by contract.
- `graph_neighbors(node, edge_types=[], direction='any', depth=1, condition='', top_k=20)` — ranked by |coef| then evidence; depth ≤ 2.
- `graph_hubs(node_type='regulator', edge_type='REGULATES', within_pathway='', top_k=15)` — degree, mean |coef|, evidence split.
- `graph_path(a, b, max_len=3, edge_types=[])` — shortest paths with the evidence of each hop.
- `graph_subgraph(pathway_id, edge_types=['REGULATES','KGML'], max_edges=40)` — compact edge list + summary (regulators, targets, sign split, evidence split, strongest condition).
- `graph_evidence(regulator, target)` — coefficients per condition, target R², KGML/OmniPath support, the sentence the overlay would draw.
- `graph_filter(expr)` — a deliberately tiny DSL (`type == REGULATES and abs(coef) > 1 and evidence == supported`), parsed, never `eval`; this is the "read-cypher" equivalent, bounded to 200 rows.

Guard-rails baked into the tool text (from the MORE memories): coefficients are unbounded slopes, not correlations, and are not comparable across omics or targets; R² belongs to the target's model, not the edge; MLR carries no p-values; the readable budget on a diagram is 5–8 edges. The `network` figure archetype draws one pathway's regulatory subgraph (≤ 30 edges, spring layout seeded, Okabe–Ito by evidence class, legend states method/alpha/condition).

### 3.4 What "correlation network" means here

PaintOmics computes no feature–feature correlation today. Two things are already networks and go into `JobGraph`: the Step-3 *pathways network* (pathway similarity by shared features) and the *metabolite hub neighbourhoods*. If a feature–feature correlation across replicates is wanted as well, it is one bounded tool (`correlate_features`, K most-variable features, BH, ≥6 columns) writing `CORRELATED_WITH` edges — deferred until asked for explicitly (see §7 Q1).

### 3.5 Methods and Supplementary — generated, never written

`methods.py` renders from the job: organism, databases and their versions, id mapping, enrichment test (Fisher per omic, Stouffer/Fisher combination, weights), MORE method/engine/alpha/VIP/R² filter/regulatory omics, GO/Hallmark release, GSEA parameters and seed, PCA/PERMANOVA parameters, figure pipeline (archetype, matplotlib version), AI model name and run date. Supplementary tables are the tool outputs as TSV (enrichment, GO, GSEA, MORE edges used, facts ledger). The LLM never touches either.

### 3.6 Paper skeleton

Title · Abstract (≤ 200 words, every number a fact id) · Results (subsections in §3.1 order; figure callouts `![Fig. N](figure:id)`) · Discussion (literature analyst's shelf; citation-verified) · Limitations (from `unused_occasions` + `data_limits`, deterministic bullets first, then the Lead's prose) · Methods (generated) · References · Figures with legends · Supplementary tables. Introduction is **not** generated in v1 (it is framing, not evidence; highest hallucination risk).

## 4. Front-end

### 4.1 Step 3 results page → tabs

`PA_Step3JobView` becomes an `Ext.tab.Panel` (ExtJS 4.2.1, `deferredRender: true`) with:

1. **Pathways** — Pathways summary · Pathway enrichment (folded, §4.2) · Pathway explorer per database (classification + network).
2. **Regulation** — MORE regulation analysis (present only when a MORE job exists).
3. **Metabolites** — Metabolite class activity · Metabolite hub analysis (present only with a compound layer).
4. **Data & mapping** — Mapping and data statistics.
5. **Paper** — the Paper Agent (§4.3); "AI interpretation" stays where it is.

Traps already known in this codebase: sigma canvases and Highcharts do not size in a hidden tab — render on `activate`, once; ExtJS vbox repositions only on `setHeight`; bump `?v=` on `PA_Step3Views.js`/`app.js`; run `?guides=1` to 0 off-rail on every tab; detached views must be destroyed via `view.component` (the logo-reset lesson).

### 4.2 Enrichment table folded to top 20 with row expansion

- Sort by the selected combined method; show rank ≤ 20 via a store filter; footer button "Show all 888 pathways" toggles the filter; the live search *ignores the fold* (searching un-folds to the matches, then re-folds on clear).
- `Ext.grid.plugin.RowExpander` (4.2.1 ships it): the expanded row renders what `PA_Step3PathwayDetailsView` shows today for that pathway — per-omic significance per condition, matched features with values, external links — so the details card can disappear from the page.
- Download still exports all rows.

### 4.3 Paper view

A new `PA_PaperView` under the Paper tab: a run button with consent (same as AI interpretation), a progress board with one lane per specialist (status, tool activity labels, elapsed), then the manuscript: outline sidebar, sections, figures (PNG inline, SVG/PDF/py/tsv downloads), tables, Methods, References, a Verification panel (facts substituted n, sentences redacted n, citations verified k/m, figures QA p/q), and export: Markdown now, DOCX via `python-docx` in a follow-up.

## 5. Build order and effort

| Step | What | Days | Depends on |
|---|---|---|---|
| 0 | Shared kernel subset: `LayerMatrix`, stats kernels, `FactsLedger` + gate substitution, `make_figure` registry, `PythonExecutable` fix (uWSGI) + matplotlib pin, TOOL_LABELS/`?v` | 4 | — |
| 1 | `JobGraph` + six graph tools + `graph_filter` DSL + `network` archetype | 6 | 0 |
| 2 | GO/Hallmark resource (`genesetInstaller`, `feature_table` fixing clone-inflated universes) + `enrich_collection` (up/down/both, topGO elim) + `run_gsea` + two archetypes; inline custom sets only | 8 | 0 |
| 3 | QC v2: `sample_ordination` (loadings, PERMANOVA, correlation, outlier/batch), `pca` + `samplecorr` archetypes, `top_movers`, `data_limits`, condition axis | 5 | 0 |
| 4 | Sets/concordance: descriptor grammar, multiset exact test, Venn/UpSet, concordance + archetype, comparison inventory | 6 | 0 |
| 5 | Paper orchestration: `PaperContext`, specialist agents + contracts, `AnalysisNote`, Lead author, `methods.py`, gate, `paperCollection`, `PaperServlet` + routes | 10 | 1–4 |
| 6 | Step 3 tabs + folded/expandable enrichment table | 3 | — |
| 7 | `PA_PaperView` + progress lanes + Markdown export | 6 | 5 |
| **Total** | | **≈ 48** | |

Steps 1–4 and 6 are independent and can run in parallel; each is shippable on its own (the existing interpreter gains the tools immediately). Step 5 is the integration.

## 6. Verification policy

Five layers, each leaving evidence. (1) Unit: standalone `__main__` tests per module with reference values — scipy/statsmodels parity, hand-computed GSEA ES, a 6-node graph fixture with known paths/hubs; every tool has a "refuses with a reason" test. (2) Contract: each specialist run alone on a frozen job fixture, its mandatory outputs asserted in the `AnalysisNote` (tool results, never schema echoes). (3) Smoke: one full Paper run on the STATegra example (`11-stategra-more`, the only local job with MORE), scored against the `stategra-v4` rubric. (4) **Corpus — the real test:** blind Paper runs through `phase_c.py` on every runnable dev study of the harvested corpus on Garnatxa (≥12 after wrapping; prerequisites: `keep_replicates` on ≥3 balanced studies so the QC analyst has replicates, MORE runnable on the stack + the miRNA study 2022-35534493 wrapped so ≥1 study has REGULATES edges), then — dev only, after the run — `COMPARISON.md` against each paper's Results: reached/partial/missed/not-derivable per main-claim analysis, contradictions, figures, recomputable numbers; the aggregate reported beside the interpreter's 67 % prior. (5) UI: Chrome on every front-end step (restart, `?v=`, screenshot, `read_page`, `?guides=1` → 0 off-rail); figure rendering verified once under uWSGI. The firewall is unchanged throughout; scoring on a sealed TEST split is a later, separate exercise.

The runnable goal statement for this plan lives at `agentevolve/prompts/GOAL-paper-agent.md`.

## 8. What was built, and what the first corpus round measured (2026-08-24)

Items 1-7 of the goal shipped on `feat/paper-agent` (PaintOmics PR #83);
evidence in `docs/verification/paper-agent/`. Two deviations from §3 are
worth recording:

* **The specialists' mandatory pass is executed as code, and the model
  narrates it** (spec §2's hybrid, taken further than §3.1's tool-loop
  sketch). One narrate call per specialist over evidence it did not compute;
  the Lead assembles. This is why `facts_unknown = 0` on every corpus run.
* **The gate grew two checks the design did not foresee**: a token whose
  KIND cannot fill its slot ("a combined p-value of {{count}}") is redacted,
  and a `(Figure: x)` pointer at a non-figure is stripped. Both came from
  reading real manuscripts.
* **`pathway_diagram`** was added after the first human read: when the text
  explains a pathway, the figure is that pathway's own KEGG map, painted
  with the job's values and cropped to the region under discussion.

**Round 1 on nine blind dev studies** (`agentevolve/proposals/
2026-08-24-paper-agent-scored.md`): 16 of 37 derivable main-claim analyses
reached (43 %) against the interpreter's 26/37 (70 %) on the same maps,
**zero contradictions**, 45-91 s per manuscript. The agent is broader per
run (QC with PERMANOVA's floor stated, GO+elim, painted diagrams, generated
Methods, every number ledgered) and narrower per claim: everything
conditions on the pooled relevant list, so a claim inside one contrast is
invisible. The contrast pass (spec §3.1's Design&QC contract, extended)
addresses exactly that and is the subject of round 2.

## 7. Decisions needed

1. **"Correlation network"** — do you mean the Step-3 pathways network + metabolite hub neighbourhoods (both go into `JobGraph` as designed), or a feature–feature correlation across replicates (one extra tool, +2 d)?
2. **Paper sections** — Results + Discussion + Limitations + generated Methods (recommended); add an Abstract? an Introduction (not recommended in v1)?
3. **Export** — Markdown in-app first, DOCX in a follow-up (recommended), or DOCX from day one (+2 d, `python-docx`)?
4. **Runtime** — is ≤ 20 min per paper acceptable (the interpreter is capped at 10)? It shares the 4-worker PySiQ queue.
5. **Relationship to "AI interpretation"** — keep both entry points (recommended: the interpreter becomes the Pathway specialist, so one code path), or replace it?
6. **Order** — start with step 1 (graph tools; the interpreter benefits immediately and it is the part you asked to "form the idea" of), or step 6 (the visible front-end change)?
