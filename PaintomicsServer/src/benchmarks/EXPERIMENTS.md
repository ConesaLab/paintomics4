# PaintOmics 4 pipeline speed experiments

Goal: make the pipeline faster with **provably unchanged results**. Every
experiment below is gated by the benchmark harness in this directory: a change
is kept only if (a) `bench_compare` reports IDENTICAL or EQUIVALENT
(float rel ≤ 1e-12) on **all 11 example scenarios**, or any difference is
proven to be a pre-existing bug — and (b) the phase it targets is measurably
faster.

Cost anchors (production-measured, from in-code instrumentation):
- Step 1 p50 **43.1 s**, 98.9% = `processFilesContent` (identifier mapping;
  ~98% of that is Mongo round trips inside the forked mapper workers).
- Step 2 p50 **76.5 s** with metabolites (classify 40.2%, metagenes 49.9%),
  ~**30 s** without (pathways 57%, metagenes 38%).
- Bed2Genes: full GTF re-parse per job (566 MB mouse GTF, est. 60–180 s).
- MiRNA2Genes: one scipy call per (miRNA, target) pair (~98k pairs shipped).

## Wave 1 — low risk, measured first

| ID  | Target | Change | Expected |
|-----|--------|--------|----------|
| E01 | mapper | Carry the per-job translation cache across omics (workers return their tables; parent merges before next omic forks) | 2–4× step 1 on multi-omic jobs |
| E04 | mapper | One Manager append per worker instead of per matched clone | 1–7 s per gene omic |
| E05 | mapper | In-memory kegg_compounds name scan replacing per-name Mongo regex COLLSCANs (reproduces PR #32 escape/cap/placeholder semantics exactly, natural order preserved) | compound mapping to ms |
| E06 | mapper | In-place translation-cache merge; hoist per-worker dbname find_ones | hygiene, frees O(cache²) |
| E07 | step 2 | Vectorize `hypergeom.sf` (and chi2.sf grouped by df) across the worker's pathway chunk; keep `combine_pvalues` per pathway | 2–6 s |
| E08 | step 2 | Per-worker SimpleQueue bulk result transfer replacing `Manager().dict()` per-pathway writes | 1–2 s |
| E09 | step 2 | mtime-keyed module cache for parsed `kegg_interaction.json`; delete `print(temp)` | 2–5 s on metabolite jobs |
| E10 | step 2 | `PathwayDAO.insertAll` → single `insert_many` (mirrors FeatureDAO) | 0.3–2 s per store |
| E11 | step 2 | Precompute lowercased pathway ID sets once per organism in the parent | 0.1–0.5 s |
| E12 | step 2 | Hoist per-worker preamble (max_conditions, input dicts) into the parent | 0.2–1 s |
| E15 | metagenes R | `PCA2GO.2.R`: pre-split annotation (`split()` once) instead of O(P·A) per-pathway scans; list-accumulate instead of `cbind` growth | 10–40 s per Reactome call |
| E19 | metagenes | Demote per-metagene-row logging; slider-path full-JSON logs → debug | s + log hygiene |
| E20 | metagenes | Extract only the needed zip members; os-level PNG moves | s |
| E21 | hub R | Hoist `dir()`; env/`fastmatch`-style membership sets instead of re-hashed `intersect`; hoist loop-invariant subsets | 10–25 s on metabolite jobs |
| E23 | classify | Module-level br08001 index + reverse compound→category map; delete `print(temp)` | sub-second + hygiene |
| E24 | DAO | Process-wide pid-keyed shared MongoClient; closeConnection no-op | ms per DAO op, removes leaks |
| E25 | DAO | `adaptBSON` str fast-path (verifier proves identity on real collections first) | 1–3 s per cold job load |
| E26 | DAO | Single features query on job load, partitioned client-side | round trip |
| E28 | step 3 | `getValueIdTable` via chain (no merged-dict copy) | 10–100 ms per response |
| E29 | step 3 | PNG-size cache; dedup member serialization in `generateSelectedPathwaysInformation` | ms–s per paint |
| E30 | ops | `create_index` on aiInterpretationCollection.jobID; retire daily `reindex()` | unblocks writes; latent pymongo-4 crash |
| E31 | bed2genes | Pickle-cache the parsed GTF keyed by (path, mtime, size, tags) | 60–180 s → s on repeat jobs |
| E33a | mirna | Hoist per-pair float conversions to load time (arrays once) | 20–40 % of scoring loop |
| E34 | step 1 misc | ensure_utf8/detect_delimiter memoize; closure hoist; numpy outlier mask for compounds; per-omic OmicValue index for replicate apply | 0.5–2 s |

## Wave 2 — medium risk, gated individually

| ID  | Target | Change | Risk to control |
|-----|--------|--------|-----------------|
| E02 | mapper | `$lookup` pipeline form filtering `dbname_id` inside (index-driven) | duplicate-mate multiset semantics; Mongo version |
| E03 | mapper | Fetch IDs+symbols in one aggregation per batch | symbol-path mates equivalence |
| E16 | metagenes R | One R process per job (manifest of omic×db datasets, re-seeded per dataset) | RNG stream position |
| E27 | responses | NaN-aware single-pass JSON encoding replacing `_sanitizeForJSON` deep copy | NaN token, tuples, key order |
| E32 | bed2genes | GTF parse: `str.find` prefix extraction + `__slots__` (pure python) | regex quirk reproduction |
| E33b | mirna | Vectorized kendall/spearman kernel (n≤6) matching scipy tie handling bit-for-bit | last-ulp float text |

## Wave 3 — evaluate only if Waves 1–2 leave the phase dominant

| ID  | Target | Change | Notes |
|-----|--------|--------|-------|
| E13 | step 2 | Rust (PyO3) enrichment counting kernel over interned feature/pathway arrays | only if counting still dominates after E07/E08; must reproduce OR-combine + padding rules exactly |
| E22 | hub | Full Python port of hub scoring with install-time artifact | supersedes E21 if landed |
| E32b | bed2genes | Rust GTF parser | deploy complexity vs E31 cache win |

## Explicitly rejected (recorded so effort is not re-spent)

- **Rust rewrite of the identifier mapper** — measured ~98% Mongo I/O; no CPU
  to accelerate. Wins are query count and cache hits (E01/E02/E05).
- **Larger aggregation batches** — 250 vs 2000 measured within ~2% on Drago.
- **NumPy port of metagene k-means** — R's Hartigan–Wong + Mersenne-Twister
  stream cannot be reproduced bit-for-bit; cluster labels are user-visible.

## Equivalence protocol

1. `bench_all` on master (baseline), 2 runs: run1 vs run2 establishes the
   noise floor (A/A must be IDENTICAL/EQUIVALENT; PYTHONHASHSEED pinned,
   mapper-worker line order pre-sorted at capture).
2. `bench_all` on the candidate branch, same Mongo + KEGG_DATA + machine.
3. `bench_compare --a baseline --b candidate` must pass all scenarios.
4. Timings compared per phase (median of ≥3 runs for the phases a change
   targets); a kept change must not regress any other phase beyond noise.
5. Pre-existing-bug differences require a standalone reproduction on
   unmodified master before the change is accepted.
