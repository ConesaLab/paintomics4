# Replicate Aggregation — Implementation Plan

**Status:** Greenlit, pending implementation
**Branch:** TBD (suggest `replicate-aggregation`)
**Scope:** Visualisation-only feature — backend ingestion, p-values, enrichment, and MORE pipeline are unaffected.

---

## 1. Analysis & Biological Constraints

**Goal.** When a Regulatory-Omics or Gene-Expression dataset contains replicate columns (e.g., 16 samples = 8 biological samples × 2 replicates), detect the replicate structure at parse time, let the user confirm or override it in Step 2, and render group-mean cells in the Step-4 visualisation while preserving the raw per-replicate data for drill-down.

**Terminology (Option A — bench-scientist convention).**
- *Replicate* = a column in the values file (e.g., `brl3.2_22_R1`).
- *Sample* = the biological unit those replicates measure (e.g., `brl3.2_22`).
- *Mode flags*: `"replicates"` (today's behaviour) and `"samples"` (aggregated view).

**Invariants to preserve.**
- Existing per-replicate data path stays intact and remains the default until a sample mapping exists.
- MORE pipeline is untouched — its `conditionsFile` (biological factor for the regression) stays a separate input.
- Pathway enrichment and p-value math are not affected.
- Old saved jobs deserialize without migration.

**Biological constraints.**
- Replicate counts per sample may be unequal (1, 2, n).
- NaNs allowed inside a replicate set; aggregate with `nanmean`.
- Per-replicate `relevant` flags collapse deterministically: *any replicate relevant ⇒ sample relevant*.
- Different omics in the same job can have independent sample sets — each omic gets its own detection result.

**When the panel does NOT appear (deliberate non-goals).**

| Header pattern | Value columns | Detection | Panel shown? |
|---|---|---|---|
| `logFC` | 1 | `none` | No |
| `T0, T1, T2` (time series, no reps) | 3 | `none` | No |
| `Ctrl, Treat_2h, Treat_6h` (multi-condition, no reps) | 3 | `none` | No |
| `T0_R1, T0_R2, T1_R1, T1_R2` (time series + reps) | 4 | `complete` → 2 samples | Yes |
| `Ctrl_R1, Ctrl_R2, Treat_R1, Treat_R2` | 4 | `complete` → 2 samples | Yes |
| `Ctrl_a, Ctrl_b` (oddly named reps) | 2 | `none` | No (out of scope for v1) |

The panel surfaces only when the conservative regex matches *and* at least one sample has ≥2 replicates.

---

## 2. Architecture & Optimisation Plan

### 2.1 Data model

Extend `OmicValue` (`PaintomicsServer/src/classes/Feature.py:112`) with two parallel attributes:

```python
self.sampleValues   = None   # list[float], length = n_samples
self.sampleRelevant = None   # list[bool],  length = n_samples
```

Both are `None` when no detection/mapping exists → renderer falls back to `values`/`relevant`. No schema migration needed.

Extend `inputOmic` dict (`PathwayAcquisitionJob.processFilesContent`) with:

```python
inputOmic["sampleHeader"]      # list[str]   ordered sample names (replaces omicHeader[1:] in samples mode)
inputOmic["replicateMapping"]  # list[int]   length = len(omicHeader)-1; col i → sample idx
inputOmic["replicateSource"]   # "auto" | "manual" | "off"
```

### 2.2 Detection logic (server)

New module: `PaintomicsServer/src/common/ReplicateDetection.py`.

```python
REPLICATE_SUFFIX = re.compile(
    r'(?P<sample>.+?)(?P<sep>[._-])(?:R|r|rep|replicate)\s*(?P<num>\d+)$'
)
```

`detect_replicates(header)` returns one of:
- `{"status": "complete", "sampleHeader": [...], "mapping": [...]}` — every column matches and ≥1 sample has ≥2 replicates,
- `{"status": "partial", ...}` — some columns match but not all,
- `{"status": "none"}` — otherwise.

Conservative whitelist only. No silent collapse on `T0/T1/T2` or `Patient1/Patient2`-style names.

**Where it runs:** end of `Job.parseGeneBasedFiles` and `Job.parseCompoundBasedFile` (after `fileHeader` is captured). Result attaches to `inputOmic["replicateDetection"]` and is *not* applied yet — application happens after the user confirms in Step 2.

### 2.3 Aggregation (server, vectorised)

Once a mapping is committed (auto-accepted or via uploaded design file), aggregate per-row:

```python
arr = np.asarray(numericValues, dtype=float)
sampleVals = np.full(n_samples, np.nan, dtype=float)
for s_idx, cols in enumerate(sample_to_cols):
    sampleVals[s_idx] = np.nanmean(arr[cols])
omicValueAux.setSampleValues(sampleVals.tolist())
```

Or fully vectorised with `np.add.at` accumulators if profiling shows the row-wise loop is hot (typical N keeps row-wise simple).

Relevance: `sampleRelevant[s] = any(relevant[i] for i in cols_of_sample[s])`.

### 2.4 Persistence

Extend `OmicValue.parseBSON` / `toBSON` (`Feature.py:165-177`) to round-trip `sampleValues` and `sampleRelevant`. Old documents lacking these fields deserialize with `None`.

Extend the `inputOmic` BSON inside the job to include the four new keys above.

### 2.5 Wire format (server → client)

`OmicValue` JSON gains `sampleValues` and `sampleRelevant`. `inputOmic` JSON gains `sampleHeader`, `replicateMapping`, `replicateSource`. No breaking change for existing client builds — they ignore unknown fields.

### 2.6 Client model

`FeatureModels.js:484` (`OmicValue.getValues`) becomes mode-aware:

```js
this.getValues = function(mode) {
    return mode === "samples" && this.sampleValues != null
        ? this.sampleValues
        : this.values;
};
this.isRelevant = function(idx, mode) { /* parallel shape */ };
```

`JobInstanceModels.js:279` (`getOmicHeaders`) returns either the per-replicate header or the `sampleHeader` based on the same mode flag.

A new model field `JobInstanceModel.replicateMode` defaults to `"replicates"` and flips to `"samples"` when any omic has aggregation accepted.

### 2.7 Step-2 UI — replicate confirmation

New view: `PA_Step2Views.ReplicateDetectionPanel`. Rendered alongside the metabolite checkbox panel.

Per-omic card:

```
Replicate detection — Gene Expression
  8 samples, 2 replicates each (detected from column suffixes)
  └ brl3.2_22  ← brl3.2_22_R1, brl3.2_22_R2
  └ brl3.2_28  ← brl3.2_28_R1, brl3.2_28_R2
  …
  ( ) Show all replicates
  (•) Average replicates  (recommended)
  ( ) Upload design file  [Choose file…]
```

Behaviour:
- Default selection = `Average replicates` if detection status is `complete`, otherwise `Show all replicates`.
- "Upload design file" exposes a file picker that piggybacks on `DataManagementServlet.saveFile`; on success, the panel re-renders with the manual mapping.
- When the user proceeds to Step 3, the chosen mode + mapping is sent back to the server, which performs the aggregation and stores `sampleValues` on each `OmicValue`.

Endpoint: `POST /applyReplicateMapping` with `{jobID, omicName, mode, designFile?}`. Implemented in `PathwayAcquisitionServlet.py`.

### 2.8 Step-4 UI — view toggle

In the visual options panel (`PA_Step4Views.js` ~line 2680, alongside color-scale radios) add:

```
Replicate display
  (•) Show samples (averaged)     ← default when sample data exists
  ( ) Show all replicates
```

The toggle flips `JobInstanceModel.replicateMode`, which triggers redraw of the three render loci:

- `PA_Step4Views.js:2356-2400` — small in-pathway boxes (the user's "16 boxes" → "8 boxes").
- `PA_Step4Views.js:1897-2068` — Highcharts heatmap in the feature tooltip.
- `PA_Step4Views.js:2079+` — time-course plot.

Each loop's only change: replace `omicValues.getValues()` with `omicValues.getValues(mode)`, and replace `headers[omicName][index+1]` with the mode-aware header.

### 2.9 Design-file format (manual override)

```
	sample
brl3.2_22_R1	brl3.2_22
brl3.2_22_R2	brl3.2_22
brl3.2_28_R1	brl3.2_28
…
```

Parsed by reusing the loader pattern from `MOREServlet`. Header row optional (skip if present).

Validation:
- Every column in `omicHeader[1:]` must appear in column 1.
- Column 2 must be non-empty.
- Warn on singleton samples and unequal replicate counts (don't error).

---

## 3. Implementation Roadmap

| # | File | Change |
|---|---|---|
| 1 | `PaintomicsServer/src/common/ReplicateDetection.py` | **New.** Conservative regex matcher; `detect_replicates(header)` → status dict. Unit-tested standalone. |
| 2 | `PaintomicsServer/src/classes/Feature.py:112-177` | Add `sampleValues`, `sampleRelevant` to `OmicValue`; extend `parseBSON` / `toBSON`; getters. |
| 3 | `PaintomicsServer/src/classes/Job.py:386-499, 559+` | Call detection at end of header capture; store result on `inputOmic["replicateDetection"]`. No aggregation yet. |
| 4 | `PaintomicsServer/src/classes/JobInstances/PathwayAcquisitionJob.py:514-529` | Surface `replicateDetection` in the Step-2 response payload. |
| 5 | `PaintomicsServer/src/servlets/PathwayAcquisitionServlet.py` | New endpoint `applyReplicateMapping`. Validates input, writes `replicateMapping` + `sampleHeader` onto `inputOmic`, then walks `OmicValue` instances and computes `sampleValues` / `sampleRelevant` (vectorised, see §2.3). |
| 6 | `PaintomicsClient/public_html/app/model/FeatureModels.js:484` | Mode-aware `getValues` / `isRelevant`. |
| 7 | `PaintomicsClient/public_html/app/model/JobInstanceModels.js:279` | Mode-aware `getOmicHeaders`; new `replicateMode` field with default. |
| 8 | `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step2Views.js` (or wherever the metabolite panel lives) | Add `ReplicateDetectionPanel` — three radios + per-omic preview + design-file uploader. POSTs to `applyReplicateMapping` on confirm. |
| 9 | `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step4Views.js` (~2680, 2356, 1897, 2079) | Add toggle in visual options; pass `mode` through the three render loops. |
| 10 | `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step1Views.js` (optional, v2) | Lightweight in-browser FileReader hint under each upload row when local file selected. |

**Suggested branch order** — each independently mergeable, behind a feature flag if desired:

1. Steps 1–2 + unit tests for detection and aggregation math.
2. Steps 3–5 — detection runs but doesn't aggregate yet; payload exposes detection.
3. Steps 6–8 — client confirmation UI; aggregation now fully wired end-to-end.
4. Step 9 — Step-4 toggle, the visible payoff.
5. Step 10 — Step-1 hint polish (optional).

---

## 4. Validation & Edge Cases

| Case | Handling |
|---|---|
| All columns match regex, ≥1 sample has ≥2 reps | `complete` → default to *Average replicates*. |
| Some columns match, others don't | `partial` → default to *Show all replicates*; surface as a note ("12 of 16 columns look like replicates — upload a design file to confirm"). |
| No matches | `none` → panel hidden by default. |
| Singleton sample (1 replicate) | Allowed; mean = single value. Hint icon in tooltip ("no replication"). |
| NaN within replicate set | `nanmean`; sample becomes NaN only if all replicates are NaN → render gray cell. |
| Replicates disagree on relevance | Sample relevant if *any* replicate is relevant; document in tooltip. |
| Duplicate column names in header | Hard error during validation (already an issue today; tighten the message). |
| Design file references column not in header | Hard error with the offending list. |
| Header column missing from design file | Hard error. |
| Compound-omic file | Same logic via `parseCompoundBasedFile`. |
| Saved job pre-feature | `sampleValues == None` → renderer uses `values`; no migration. |
| MORE pipeline | Unchanged — its `conditionsFile` is read independently for the R script. The replicate-detection panel and the MORE conditions panel are separate UI elements; document the distinction in tooltip help. |
| Single-condition workflow | One value column → detection `none` → panel hidden. |
| Multi-condition workflow without reps | Distinct conditions like `T0/T1/T2` → detection `none` → panel hidden; existing N-box rendering unchanged. |
| Feature-flag rollback | Setting `replicateMode = "replicates"` and not exposing the toggle reverts behaviour with zero data risk. |

**Tests to add.**

- `test_replicate_detection.py` — regex coverage on a fixture set: `_R1/_R2`, `.rep1/.rep2`, mixed cases, `T0/T1/T2`, `Patient1/2`, `Sample_1/_2`. Each asserted as `complete`, `partial`, or `none`.
- `test_aggregation_math.py` — vectorised mean against `pandas.groupby` reference; NaN handling; relevance OR-collapse.
- Integration: a 16-column synthetic gene-expression file, expect 8-column `sampleValues` after `applyReplicateMapping`.
- Snapshot of `OmicValue.toBSON` / `parseBSON` round-trip with both fields populated.

---

## 5. Out-of-scope for v1 (revisit later)

- Step-1 client-side FileReader hint (item 10 in roadmap — polish).
- "Have replicates we didn't detect? Upload a design file" escape hatch when detection returns `none` with >1 value column.
- Median / mean ± SE aggregation modes (mean only for v1).
- Per-omic *and* job-wide design files (v1 is per-omic).
- Auto-promotion of MORE's `conditionsFile` for visualisation (out — the MORE file's second column has different semantics, see §1).

---

## 6. Next step

Branch off `MORE-v2`, start with roadmap items 1–2 (detection module + `OmicValue` extension). Both are pure-server, unit-testable in isolation, and add zero UI surface — safest first landing.
