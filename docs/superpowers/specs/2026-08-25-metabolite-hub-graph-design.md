# Metabolite Hub Analysis: derive the graph, drop R, draw the network

Date: 2026-08-25
Status: design, awaiting review
Branch: to be created from `master`

## 1. Goal

Three things, in one project, because they share one artifact:

1. **Correctness.** The KEGG graph hub analysis runs on is measurably wrong: 28.2% of
   relation subtypes are mis-attributed and 14.0% of reaction-derived rows are corrupted.
2. **Cost and maintainability.** Hub is the last feature whose *runtime* depends on R. The
   install builds a 60 MB derived tree in ~65 s that duplicates itself twice over; the
   scorer re-reads all of it on every job and peaks at 393 MB RSS.
3. **The missing view.** The graph exists on the server and has never reached the browser.
   Users get a table of numbers about a network they cannot see.

## 2. What hub analysis is (for reviewers)

Not topological hubness — no centrality is computed anywhere in the live path. For each
measured compound it takes the genes within k = 1..4 steps in the KEGG compound-gene graph
and asks whether that neighbourhood is enriched in differentially expressed genes:

    binom.test(DEN, DEN+noDEN, p = globalSigPer, alternative = "greater")

against the DE rate among all measured KEGG genes, plus a percentile against the background
compounds' densities.

## 3. Decisions taken

| # | Decision | Rationale |
|---|---|---|
| D-a | One project, staged | The network view needs an edge source the installer never produced; building it correctly is the same work that deletes R |
| D-b | Fix the science, stamp a version | Parser defects are bugs; the statistic changes are deliberate and must be traceable |
| D-c | Hop-ring network view | Rings = graph distance, all four drawn, step control lights/dims |
| D-d | No R anywhere in the hub path | Builder and scorer land together |
| D-e | `store.py` API and edge attributes shaped for the AI interpreter, migrated later | Costs a few arrays now, avoids a reshape later. There is no index artifact to shape — the contract is the API |
| D-f | **Derive the graph on demand; store nothing** | Measured 1.03 s cold start vs an install step, a schema, a migration and a class of staging bugs |

## 4. Architecture

New package `PaintomicsServer/src/common/KeggGraph/`:

- **`parser.py`** — KGML -> edges with attributes. The only KGML parser for hub. Replaces
  `GalaxyNetworkFunctionsv2.R` (2,171 lines) and `hubAnalysisInstall.R` (256 lines).
- **`graph.py`** — `KeggGraph`: the CSR index and traversal. Pure, no I/O.
- **`store.py`** — the seam. Derives, caches per organism, and serves:
  - `rings(seed, k) -> list[np.ndarray]` (exclusive rings, seed never included)
  - `subgraph(seed, k, budget) -> nodes, edges` (induced, ranked, capped)
  - `node_type(name)`, `compounds()`, `genes()`
  Backend-agnostic by construction: today it derives from KGML, and a future change to a
  stored or graph-database backend touches this module alone.
- **`scorer.py`** — the hub statistic. Replaces `hubAnalysis.R` (333 lines).

Nothing else in the subsystem needs R. R stays in the image for MORE and metagenes.

### 4.1 Derivation and cache

`store.py` builds the adjacency from `KEGG_DATA/current/<org>/kgml/*.kgml` on first use.
Measured on this machine, with full edge attributes, group expansion and reactions:

| organism | KGML files | edges | nodes | parse | CSR | total | peak RSS |
|---|---|---|---|---|---|---|---|
| mmu | 364 | 96,618 | 9,646 | 0.99 s | 0.03 s | **1.03 s** | 32.3 MB |
| ath | 162 | 54,679 | 5,269 | 0.58 s | 0.01 s | 0.61 s | 40.7 MB |
| hsa | 372 | 83,115 | 8,900 | 1.01 s | 0.02 s | 1.04 s | 27.0 MB |

**"Store nothing" means no persisted artifact, not no index.** An in-memory index is
essential and is built every cold start: CSR over integer-coded node names — `indptr`,
`indices`, plus parallel edge arrays for relation type, subtype, pathway and reversibility,
and an int8 node-type array. Without it each hop would linear-scan 96,618 edges and the
1,829-compound background would take minutes instead of 2.4 s.

It is also nearly free: of mmu's 1.03 s cold start, **0.99 s is XML parsing and 0.03 s is
building the index**. Persisting it would save 3% of a one-time cost in exchange for a
schema, an install step and a migration — which is the whole argument for deriving.

**Cache.** Keyed on `(organism, kgml file count, max mtime)` so it self-invalidates when the
species is reinstalled. LRU over 3-4 organisms (~130 MB) against today's single-slot 393 MB
spike. Traversal stays in process: 0.69-1.3 ms per compound seed, 2.34-4.07 ms per gene seed.

**Fallback.** Where `kgml/` is absent, `store.py` reads the legacy
`hubData/kegg_interaction.json`. Every species that has hub data today has that file, so no
species loses the feature, including any on production whose KGML was not retained. The
fallback inherits the old parse and is reported as such.

**Why nothing is stored.** Measured alternatives, all rejected:

| option | size/species | load | verdict |
|---|---|---|---|
| Mongo, one doc per pathway | 5.66 MB (492 MB x87) | 0.12 s | works, but buys 0.9 s for a schema + migration |
| Mongo, one binary doc | 0.49 MB | 0.00 s | opaque, same objection |
| Mongo `$graphLookup` | - | **53.9 ms/seed -> 98.6 s/job** | rejected: traversal must not cross the wire |
| NumPy `.npz` on disk | 1.0 MB | 0.00 s | inherits `download/`->`current/`->`old/` staging |
| Neo4j | - | not measured | Community Edition is one user database; 87 species do not fit. Right tool for a cross-database graph later, wrong tool for a 96k-edge one now |
| **derive on demand** | **0** | **1.03 s** | chosen |

## 5. Parser fixes

- **D-1 — subtype attribution.** Read each `<subtype>` as a child of its own `<relation>`,
  not from a document-global list zipped by relation index. Measured wrong for 5,963 of
  21,120 relations (28.2%) across 194 of 364 pathways.
- **D-2 — reaction headers.** Read `id`/`name`/`type` as XML attributes rather than tokens
  3/5/7 of the stringified node, and split multi-id `name="rn:R00431 rn:R00726"` into two
  reactions. Measured 3,083 of 22,038 reaction rows corrupted (14.0%), 2,388 of them holding
  the literal string `type`.
- **D-6 — seed exclusion.** BFS seeded with `seen = {seed}` so the seed never re-enters its
  own ball regardless of self-loops. Nine mmu compounds are affected today, including
  `C00024`, the compound every worked example used.
- **Group expansion** without the silent 50-component cap; any surviving cap is announced,
  following `AIInterpret/neighbours.py`'s convention rather than the R side's silent one.

## 6. Scorer

`scipy.stats.binomtest`, `statsmodels.stats.multitest.multipletests`, `numpy.searchsorted`.

- **D-4** — one BH family across all four radii, not four families over nested, near-perfectly
  positively dependent tests presented in a single sortable grid.
- **`schema_version`** stamped into every result so a reopened old job can never silently
  disagree with a re-run.
- Output becomes **named JSON**, retiring the headerless 8-column positional TSV that the
  client reads by index `0..7` with the column order recorded nowhere else (D-26). The client
  renders both shapes, switching on the version stamp, so stored jobs keep working.
- Background ECDF over all 1,829 compounds: 2.4 s, cached per organism.
- Written to the job output directory and persisted in `hubAnalysisResult` exactly as today,
  so nothing about job storage or recovery changes.

### 6.1 OPEN — the null model (D-5)

A modelling judgement, not a bug; listed for the reviewer to choose. The binomial null
assumes the N measured genes in a ball are i.i.d. Bernoulli draws. N is read off the same
graph that defines the neighbourhood, so power scales with neighbourhood size, which is
largest for the least specific metabolites — radius 4 covers 46.9% of the network for
`C00024`. Independence also fails through shared neighbours and co-regulated complexes.

Options, not mutually exclusive:

1. Keep the binomial, and report ball size prominently so a reader can see when a radius is
   non-discriminative.
2. Guard: flag or suppress radii whose ball exceeds a stated fraction of the network.
3. Stratify the percentile background by ball size, so a compound is compared with
   similarly-connected compounds rather than all compounds.
4. Degree-preserving permutation null. Most defensible, most expensive.
5. Two-sided, so depletion is reportable at all.

Recommendation to be settled at review: 1 + 3, with 2 as a UI affordance.

## 7. Network view

`PA_Step3HubNetworkView.js` — Cytoscape 3.34.0, already loaded on every page.

- `concentric` layout, rings = hop distance, all four radii drawn; the step control lights one
  ring and dims the rest rather than adding nodes.
- Structure copied from `PA_Step3RegTargetNetworkView.js`: hide-don't-remove filtering,
  strongest-N edge budget, `paDeferFrame` on `afterrender` (not `requestAnimationFrame`,
  which never fires in a background tab), `beforedestroy -> cy.destroy()`.
- Opened from the hub grid's row action. Edge cap announced in the UI.
- Directed edges with activation/inhibition semantics become honest only because D-1/D-2 land
  in the same project.

New route `{jobID, compoundID, level} -> induced subgraph`, with the ownership check that
`/check_job_status` lacks.

## 8. What gets deleted

- `GalaxyNetworkFunctionsv2.R` (2,171 lines), `hubAnalysisInstall.R` (256), `hubAnalysis.R` (333)
- The hub block in `DBManager.py` and `hub_data_is_complete()` (33 lines)
- The `hubData/` tree: 60 MB for mmu, 17 MB for ath
- Ten R packages from the deploy image; `data.table` (a hard `stop()` the image never installs)
  and `KEGGgraph` (installed, asserted, needed by nothing) both stop mattering
- Defects that become structurally impossible rather than fixed: D-3 (partial data reaching R),
  D-10 (non-atomic replace), D-11 (stranded `download/<sp>/`), D-16 (`dir()` by position with a
  `.RData` substring match), D-31 (60 MB byte-duplicate and an unnamed hard-linked twin)

## 9. Testing

The gap that let D-1 live for years: zero tests over 2,427 lines of installer R, and CI passes
`hub=0` so hub is never built.

- Golden fixture: a small KGML carrying a multi-subtype relation and a multi-id reaction,
  asserted against hand-checked truth. This is what catches D-1 and D-2.
- Properties: seed not in its own rings; rings disjoint and nested; every edge endpoint resolves.
- Cache invalidation: touching a KGML file changes the key.
- Fallback: a species with no `kgml/` still scores, and says it used the legacy source.
- Baselines `04-multiomics-integration` and `08-stategra-multiomics` **will change** and are
  re-baselined deliberately, with the version stamp recording why.
- CI builds hub for at least one species.
- Chrome verification of the view per CLAUDE.md section 5.

## 10. Risks

| risk | mitigation |
|---|---|
| A bad parse surfaces at runtime, not install | `hub doctor` command runs the same builder over every installed species on demand |
| KGML not retained on production for all species | Legacy `kegg_interaction.json` fallback; unverified on UV and to be checked before deploy |
| Cache thrash across organisms | LRU 3-4 organisms, ~130 MB, still a third of today's spike |
| 1 s parse holds a uWSGI thread | Runs inside the queued step-2 job, not a live request; warm by the time the view is opened |
| Changed numbers vs published results | `schema_version` in every result; stored jobs keep their stored table |

## 11. Out of scope

Mongo migration; MORE, Reactome, OmniPath, MapMan; `AIInterpret/neighbours.py` keeps its own
parser this round (the store API is shaped to accept it later); the unauthenticated
`/check_job_status` route is noted but fixed separately — only the new route is guarded here.
