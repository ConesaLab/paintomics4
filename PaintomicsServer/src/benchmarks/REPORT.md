# PaintOmics 4 pipeline speed-up — benchmark report

Branch `perf/pipeline-speed` (base: master `b0641ce4`, 2026-08-17). Every
scenario in `src/examplefiles/datasets/` (11 datasets, all four pipelines:
pathway acquisition, regions→genes, miRNA→genes, MORE) was run through the
harness in this directory on the same machine, MongoDB and KEGG snapshot,
before and after the changes.

**Acceptance rule applied to every commit:** results identical to master
(or the difference proven to be a pre-existing master defect) **and**
faster. Nothing that failed either half was kept.

## 1. Headline (local, interleaved A/B, 6 mapper/enrichment workers, medians)

Machine: Apple M4 Pro, 12 cores, MongoDB 8.2 local, KEGG snapshot 20260813.
Both sides run back to back per scenario and repeat (`bench_ab`), so drift
hits both alike. "Strict" = the same job run with one worker on both sides,
where master itself is deterministic.

| Scenario | Baseline median (s) | Candidate median (s) | Speed-up | Runs (A/B) | Equivalence (timing runs) | Equivalence (strict, 1 worker) |
|---|---:|---:|---:|:-:|:-:|:-:|
| gene-multi-condition | 7.79 | 4.46 | 1.75x | 2/2 | WITHIN-NOISE | IDENTICAL |
| gene-multi-condition-relevance | 8.29 | 4.54 | 1.83x | 2/2 | WITHIN-NOISE | IDENTICAL |
| gene-single-condition | 6.99 | 3.47 | 2.01x | 2/2 | WITHIN-NOISE | IDENTICAL |
| multiomics-integration | 73.36 | 12.10 | 6.06x | 2/2 | WITHIN-NOISE | IDENTICAL |
| region-based | 1.47 | 1.39 | 1.05x | 2/2 | IDENTICAL | IDENTICAL |
| regulatory-mirna | 0.29 | 0.10 | 2.99x | 2/2 | IDENTICAL | IDENTICAL |
| regulatory-more | 68.37 | 66.51 | 1.03x | 2/2 | IDENTICAL | IDENTICAL |
| stategra-mirna | 14.97 | 4.09 | 3.66x | 2/2 | IDENTICAL | IDENTICAL |
| stategra-more | 236.5 | 246.9 | 0.96x | 3/3 | IDENTICAL | IDENTICAL |
| stategra-multiomics | 51.07 | 15.57 | 3.28x | 2/2 | WITHIN-NOISE | IDENTICAL |
| stategra-regions | 8.10 | 6.32 | 1.28x | 2/2 | IDENTICAL | IDENTICAL |


Verdict columns:

* **Equivalence (strict, 1 worker)** — bit-for-bit comparison of every
  client-visible result (step-1 mapping summary and matched metabolites, the
  whole step-2 payload: pathways with all p-values, adjusted p-values,
  combined p-values, matched members, metagenes; hub and metabolite-class
  results; step-3 graphical data and feature values; every converter output
  file; every MORE output file) — **IDENTICAL for all 11 scenarios**
  (`bench_compare`, floats compared exactly, NaN==NaN).
* **Equivalence (timing runs)** — same comparison against master's 6-worker
  output. `WITHIN-NOISE` means the only differences fall in the classes where
  master's *own* output already depends on how many workers it uses (see
  §3): which of two aliases fills a symbol-keyed display slot, the order of a
  feature's omics values, and how many values a merged duplicate compound
  carries. **No p-value, matched-pathway set, significance or converter
  byte differs in any comparison.**

The MORE scenarios are unchanged code paths (R/Rust MORE engine); their
±4 % is machine noise (one candidate run of `stategra-more` stalled to
706 s wall / 288 s in-process for reasons outside the pipeline — a third
run on each side was added: 242 s vs 247 s).

`step2.compoundsClassification` reads slower in `multiomics-integration`
(0.16 → 0.54 s): the harness starts a fresh process per run, so it always
pays the one-time build of the per-process compound-neighbour cache; on the
server every job after the first costs milliseconds there and no longer
allocates ~1 GB of transient objects to look up 50–100 compounds.

## 2. Per-phase medians


### gene-multi-condition

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| step1.processFilesContent | 3.57 | 1.02 | 3.49x |
| step1.store | 0.24 | 0.24 | 1.01x |
| step2.generatePathwaysList | 0.47 | 0.38 | 1.23x |
| step2.metagenes | 3.03 | 2.44 | 1.24x |
| step2.store | 0.14 | 0.05 | 2.55x |
| step3.generateSelectedPathwaysInformation | 0.18 | 0.18 | 1.02x |

### gene-multi-condition-relevance

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| step1.processFilesContent | 3.67 | 1.05 | 3.49x |
| step1.store | 0.25 | 0.26 | 0.96x |
| step2.generatePathwaysList | 0.72 | 0.39 | 1.86x |
| step2.metagenes | 3.03 | 2.45 | 1.24x |
| step2.store | 0.16 | 0.07 | 2.36x |
| step3.generateSelectedPathwaysInformation | 0.31 | 0.19 | 1.61x |

### gene-single-condition

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| step1.processFilesContent | 3.55 | 0.96 | 3.71x |
| step1.store | 0.22 | 0.22 | 1.02x |
| step2.generatePathwaysList | 0.45 | 0.31 | 1.46x |
| step2.metagenes | 2.22 | 1.61 | 1.38x |
| step2.store | 0.13 | 0.06 | 2.22x |
| step3.generateSelectedPathwaysInformation | 0.26 | 0.18 | 1.46x |

### multiomics-integration

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| step1.processFilesContent | 43.43 | 2.49 | 17.45x |
| step1.store | 0.46 | 0.50 | 0.92x |
| step2.compoundsClassification | 0.16 | 0.54 | 0.30x |
| step2.generatePathwaysList | 1.08 | 0.42 | 2.58x |
| step2.hubAnalysis | 14.73 | 3.05 | 4.83x |
| step2.metagenes | 11.99 | 4.38 | 2.74x |
| step2.store | 0.72 | 0.20 | 3.52x |
| step2.updateCompounds | 0.07 | 0.06 | 1.03x |
| step3.generateSelectedPathwaysInformation | 0.50 | 0.26 | 1.95x |

### region-based

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| bed.fromBED2Genes | 1.46 | 1.38 | 1.05x |

### regulatory-mirna

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| mirna.fromMiRNA2Genes | 0.28 | 0.09 | 3.21x |

### regulatory-more

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| more.step2 | 68.37 | 66.51 | 1.03x |

### stategra-mirna

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| mirna.fromMiRNA2Genes | 14.84 | 3.96 | 3.74x |

### stategra-more

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| more.step2 | 236.5 | 246.9 | 0.96x |

### stategra-multiomics

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| step1.processFilesContent | 22.54 | 5.32 | 4.24x |
| step1.store | 0.88 | 0.69 | 1.27x |
| step2.compoundsClassification | 0.37 | 0.30 | 1.25x |
| step2.generatePathwaysList | 1.17 | 0.61 | 1.91x |
| step2.globalExpressionData | 0.03 | 0.22 | 0.11x |
| step2.hubAnalysis | 13.10 | 2.66 | 4.92x |
| step2.metagenes | 12.22 | 5.14 | 2.38x |
| step2.store | 0.18 | 0.10 | 1.84x |
| step3.generateSelectedPathwaysInformation | 0.29 | 0.26 | 1.11x |

### stategra-regions

| Phase | Baseline (s) | Candidate (s) | Speed-up |
|---|---:|---:|---:|
| bed.fromBED2Genes | 8.06 | 6.27 | 1.28x |

## 3. What changed, and how each change was proven equivalent

| Area | Change | Proof of equivalence | Local effect |
|---|---|---|---|
| Identifier mapping | Translation cache carried across omics (workers hand tables back; misses cached too) | function-level dump of 12,762 genes / 2,385 proteins / 4,700 compounds identical to master | repeat mapping of the same names 5.1 s → 0.38 s |
| Identifier mapping | `$lookup` filtered on `dbname_id` inside the join instead of unwinding every mate | identical per-name id lists **including order** on gene, protein and symbol lookups | 12,762-gene cold mapping 5.7 s → 1.1 s |
| Identifier mapping | `kegg_compounds` (93k names) held in memory as a lower-cased haystack; same escaped-literal / anchored / 500-cap semantics as PR #32 | table vs live Mongo identical for every name in the example files + probes; 11 PR #32 contract tests | 4,667 compound names 40.5 s → 0.9 s |
| Identifier mapping | one hand-over per worker instead of one Manager round trip per clone; results concatenated in worker (= input) order | 6-worker output now equals the sequential output bit for bit | removes ~92 µs × up to 40k IPC calls per omic; deterministic results |
| Step 2 | metagene R scripts run per omic in parallel (databases of one omic sequential; `PAINTOMICS_METAGENES_PARALLEL`, default 3) | independent processes with their own seeds and output names; consumed in original order | metagenes 12–14 s → 4–5 s |
| Step 2 | Stouffer / Fisher combination via the special functions scipy reduces to | bit-identical to `combine_pvalues` / `chi2.sf` over 80,000 random cases each (test) | enrichment single-worker pass 0.9 → 0.6 s |
| Step 2 | enrichment workers hand back one dict; feature lookups computed once; shared join deadline; Manager shut down | dict equality of matched pathways | ~900 IPC round trips removed |
| Step 2 | `kegg_interaction.json` parsed once per process into compact per-compound strings | same filtered dict (JSON round trip) | 34–79 MB parse and ~370 MB–1 GB transient per job removed |
| R: metagenes | `PCA2GO.2.R` pre-splits the annotation (levels pinned, positional lookup) and accumulates instead of growing | `identical()` on every returned element, 26 scenarios; 24 end-to-end runs, 74 `.tab`/PNG files byte-identical | Reactome PCA call 0.94 → 0.40 s |
| R: hub analysis | `hubAnalysis.R` lists the directory once, integer-codes membership per block, hoists loop invariants | `hub_result.csv` byte-identical on real mmu hubData (3 input shapes) + synthetic edge cases | 13.7 s → 2.0 s per metabolomics job |
| DAO | one shared, pid-keyed MongoClient; `insert_many` for pathways; `adaptBSON` fast path (its `None→"None"` and ObjectId→str behaviour kept); one features query on load; jobID index on the AI collection; daily `reindex()` retired; indexes ensured off the boot path | 332,869 real documents `adaptBSON` bit-identical; 500-pathway old/new dump identical; 5 real jobs deep-compared old vs new load; 100 loads: +0 threads (was +300) | store phase 2–3×; every DAO op loses a client construction |
| Regions→genes | parsed GTF cached (pickle, keyed on path/mtime/size/tags/format); regex attribute extraction replaced by an equivalent scanner; `__slots__` records | RGMatch/B2G outputs byte-identical on the synthetic and the real 566 MB GTF, cold and warm; 42 tests | real-GTF job 8.4 → 5.4 s warm |
| miRNA→genes | exact Kendall τ-b kernel (scipy's own arithmetic on the same counts) instead of the full test with its unused p-value | bit-identical to `kendalltau` over 120,000 random rows; both miRNA scenarios byte-identical | 97,983 pairs 14.9 → 4.1 s |

### Pre-existing master behaviour surfaced by the harness (not changed here)

* Master's mapping results depend on worker scheduling: which alias fills a
  symbol-keyed slot (`globalExpressionData.inputGene[SYMBOL]`, a feature's
  displayed `name`), the order of a feature's `omicsValues`, and how many
  values a merged duplicate compound carries all vary between a 1-worker
  and a 6-worker run of the same job (and run to run under `spawn`). The
  branch makes this deterministic (input order); p-values and pathway
  membership were never affected.
* `paintomics.uv.es` (original code) killed one of two `multiomics-
  integration` runs at step 1 after a mapper worker hung for the full 900 s
  budget on a 1,200-feature omic (see §4).
* The gzipped-BED reader drops the last character of every output row
  (`reportOutput`'s `[:-1]`); the gz paths were deliberately left untouched
  because fixing them changes bytes. Filed for a separate fix.
* `PathwayAcquisitionJob.toBSON(recursive=True)` raises on any DB-loaded
  job (`FoundFeatureDAO` returns `Feature`, the recursive branch expects
  `FoundFeature`); nothing on the hot path calls it.

### Rejected experiments (measured, not kept)

* Rust rewrite of the identifier mapper — ~98 % of its time is MongoDB round
  trips; the wins were query count and cache hits.
* Larger aggregation batches — 250 vs 2000 within ~2 % (measured on Drago).
* NumPy port of the metagene k-means — R's Hartigan–Wong + Mersenne-Twister
  stream cannot be reproduced bit for bit; cluster labels are user-visible.
* Hoisting the per-pair float conversion in the miRNA scorer alone (E33a) —
  correct but worth ~1 %; the Kendall kernel above is what moved that phase.

## 4. paintomics.uv.es (production, 6 cores, 7 GB): original code

Driven over HTTPS the way the browser does (`bench_http`), before any
deploy; wall time per step includes queueing and payload transfer.

| Scenario | run | total (s) | step 1 | step 2 | step 3 |
|---|---|---:|---:|---:|---:|
| gene-single-condition | 1 | 44.9 | 20.8 | 10.9 | 13.2 |
| gene-single-condition | 2 | 37.0 | 17.7 | 11.4 | 7.9 |
| gene-multi-condition | 1 | 41.9 | 18.9 | 14.1 | 9.0 |
| gene-multi-condition | 2 | 36.0 | 18.6 | 12.9 | 4.4 |
| gene-multi-condition-relevance | 1 | 40.9 | 18.6 | 12.7 | 9.6 |
| gene-multi-condition-relevance | 2 | 40.2 | 17.6 | 13.4 | 9.1 |
| multiomics-integration | 1 | FAILED (job l5ABJ0uHZT failed at step1: Exception: AT PathwayAcquisitionServlet.py: pathwayAcquisi) | | | |
| multiomics-integration | 2 | 188.8 | 69.9 | 99.0 | 19.7 |
| stategra-multiomics | 1 | 213.0 | 98.5 | 81.7 | 32.7 |
| stategra-multiomics | 2 | 183.2 | 95.3 | 75.2 | 12.7 |

The failed run is the original code: a mapper worker on the third omic
(1,200 features) hung for the whole shared 900 s budget and the job was
killed ("Your data took too long to process"); the second run of the same
dataset completed in 189 s.

## 5. paintomics.uv.es after the deploy

Master `0976b4c4` (PR #33) was deployed at 14:29 UTC and immediately hung
every mapping: the `$lookup` sub-pipeline of PR #33 is fast on MongoDB 8.2
but MongoDB 4.4 (production) cannot index it, so every batch became a
collection scan of the 1.1 M-document `xref`. It was hot-fixed live at
14:48 UTC (classic pipeline restored), and PR #34 replaced the lookup with
two plain indexed `find`s -- 9x faster than the classic aggregation on
MongoDB 4.4 itself and still 0.8 s for 12,762 genes on 8.2 -- deployed at
15:15 UTC. The measurements below are that final code, same driver, same
scenarios, nothing else running:

| Scenario | run | total (s) | step 1 | step 2 | step 3 |
|---|---|---:|---:|---:|---:|
| gene-single-condition | 1 | 14.7 | 3.4 | 6.0 | 5.4 |
| gene-single-condition | 2 | 14.6 | 3.2 | 6.0 | 5.3 |
| gene-multi-condition | 1 | 20.2 | 4.1 | 9.5 | 6.5 |
| gene-multi-condition | 2 | 17.9 | 3.4 | 9.2 | 5.2 |
| gene-multi-condition-relevance | 1 | 17.6 | 3.6 | 8.3 | 5.8 |
| gene-multi-condition-relevance | 2 | 18.2 | 3.6 | 9.0 | 5.5 |
| multiomics-integration | 1 | 52.6 | 9.3 | 37.0 | 6.1 |
| multiomics-integration | 2 | 53.6 | 10.7 | 35.0 | 7.8 |
| stategra-multiomics | 1 | 54.6 | 18.1 | 27.9 | 8.5 |
| stategra-multiomics | 2 | 58.6 | 22.5 | 25.9 | 10.1 |

| Scenario | before (median total) | after | speed-up | before step 1 → after | before step 2 → after |
|---|---:|---:|---:|---|---|
| gene-single-condition | 40.9 s | 14.7 s | 2.8x | 19.2 → 3.3 s | 11.2 → 6.0 s |
| gene-multi-condition | 39.0 s | 19.1 s | 2.0x | 18.8 → 3.8 s | 13.5 → 9.4 s |
| gene-multi-condition-relevance | 40.6 s | 17.9 s | 2.3x | 18.1 → 3.6 s | 13.1 → 8.7 s |
| multiomics-integration | 188.8 s (+1 run killed at 900 s) | 53.1 s | 3.6x | 69.9 → 10.0 s | 99.0 → 36.0 s |
| stategra-multiomics | 198.1 s | 56.6 s | 3.5x | 96.9 → 20.3 s | 78.5 → 26.9 s |

Equivalence on production (before vs after, different server processes):
every pathway p-value, adjusted and combined p-value, matched member set,
significance count, hub and metabolite-class result and step-3 graphical
payload is IDENTICAL for the three gene scenarios and EQUIVALENT for the two
5-omic scenarios (largest relative difference 8.6e-14, in combined p-values
only). That last-digit movement is master's own: the omic p-values are
combined in the order a set of gene IDs iterates, which follows the process
hash seed (unpinned on the server) -- master alone, run under two seeds,
moves the same fields by up to 2.3e-15 (259 values on STATegra). The
remaining before/after differences are the display-slot classes of §3
(which alias fills a symbol-keyed slot, list orders), for which the original
code's own two runs on production disagree with each other as well
(`bench_compare --noise-runs`: WITHIN-NOISE for all five scenarios).

The full 5-omic STATegra example was also run through the UI on the live
site with the AI interpretation enabled (job `w15JXC232h`): 898 pathways /
105 significant, hub and class panels populated, and the AI report ("105
significant pathways grouped into 23 clusters", cited key findings) rendered.

## 6. Method

* `bench_runner.py` — one scenario per fresh process, calls the same job
  methods the servlets call in the same order, records per-phase timings and
  every client-visible result. Fork start method is forced (production
  forks; macOS `spawn` distorts both timing and cache inheritance).
* `bench_all.py` / `bench_ab.py` — sweeps; `bench_compare.py` — verdicts
  (`IDENTICAL` / `EQUIVALENT` (floats within 1e-12) / `WITHIN-NOISE` /
  `DIFFERENT`), with the client contract encoded (ordered lists where the
  client renders order, keyed dicts elsewhere, `omicsValuesID` tokens and a
  feature's `omicsValues` list compared as sets because their order follows
  the process hash seed / worker scheduling on master).
* `bench_http.py` — the same measurement against a live server;
  `bench_report.py` — this document's tables.
