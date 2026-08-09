# Simulated example datasets — design

Date: 2026-08-09
Status: approved for implementation

## 1. Goal and biological constraints

Ship a set of **simulated, well-organised multi-omic datasets** that exercise every
analysis module PaintOmics offers, and let the user choose which one to load
instead of getting the single hardcoded bundle that exists today.

Biological constraints that shape the data:

* **Identifiers must be real.** Enrichment only means anything if the features
  map to real KEGG pathways. Every simulated gene is a real *Mus musculus*
  Ensembl gene ID that resolves through the installed mapping chain
  `ENSMUSG → NCBI GeneID → mmu:<id> → path:mmuNNNNN`. Measured against the
  locally installed KEGG snapshot: 28,270 Ensembl→NCBI pairs, 10,406 Ensembl
  genes carrying at least one pathway, 344 pathways with ≥15 genes.
* **Signal must be planted, not random.** Uniform noise produces no enriched
  pathway, so a green end-to-end run on random data cannot distinguish "the
  pipeline works" from "the pipeline silently returned nothing". A chosen set of
  target pathways gets a coherent shift; everything else stays near zero; the
  chosen pathways are written to disk so a test can assert recovery.
* **Values are log-scale ratios** for the pathway-acquisition pipeline (positive
  = over-expression vs. the reference), matching the documented input contract.
  MORE is the exception: it models **per-sample** matrices with replicates plus a
  design matrix, so its scenario simulates samples, not ratios.
* **Region coordinates need a genome.** `examplefiles/GTF/` holds only a
  zero-byte `.dummy`, so the region scenario ships its own small synthetic GTF
  whose gene IDs are real Ensembl IDs at synthetic coordinates. Regions are then
  placed relative to those genes' TSS so RGmatch has something to find.

## 2. What is wrong with the current state

* `examplefiles/` is 20 files flat in one directory. Meaning is encoded in
  filenames by convention only (`dnase_values.tab` = gene-mapped,
  `dnase_unmapped_values.tab` = region-based). Nothing declares which file
  belongs to which analysis.
* `examplefiles/original/` holds `.dat` copies of the same STATegra time course
  that **no code reads**. It is a dead archive that reads like the source of truth.
* There is exactly **one** example, and it is hardcoded in six places:
  `PathwayAcquisitionServlet.py:159` and the two sibling servlets each rebuild
  filenames by string-mangling omic names
  (`"DNase-seq"` → `dnase_values.tab`), and `PA_Step1Views.js` mirrors literal
  paths in three separate `setExampleMode()` functions (lines 990, 1237, 2029).
  Adding a second example today means editing all six.
* The client's displayed example filenames are fabricated:
  `"example/" + this.type + "_example.tab"` names a file that does not exist.
  It is cosmetic, but it teaches users the wrong filename convention.
* **MORE has no example at all.** Its panel has no `setExampleMode()`, and no
  conditions/design file ships anywhere in the repo.
* **Multi-condition relevance is never exercised.** Every bundled relevant file
  is single-column, yet `Job.py:820-880` carries a heuristic-heavy parser for
  multi-column per-condition relevance (header detection, legacy two-column
  disambiguation, per-condition flags). None of it is reachable from a bundled
  example.

## 3. Architecture

One generator, one manifest, one loader. The manifest is the single source of
truth; servlets and client read it instead of hardcoding filenames.

```
PaintomicsServer/src/examplefiles/
├── datasets/
│   ├── manifest.json                  <- generated catalogue, the contract
│   ├── 01-gene-single-condition/
│   ├── 02-gene-multi-condition/
│   ├── 03-gene-multi-condition-relevance/
│   ├── 04-multiomics-integration/
│   ├── 05-regulatory-mirna/
│   ├── 06-regulatory-more/
│   ├── 07-region-based/
│   └── 08-stategra-mmu-timecourse/    <- the real published data, moved here
├── GTF/                               <- unchanged, other code appends "GTF/"
└── words                              <- unchanged, UserManagementServlet reads it
```

Each scenario directory:

```
<id>/
├── README.md          human-readable: what it tests, how to run it
├── data/              the input files a user would upload
└── expected/          expected_pathways.txt, signal feature lists
```

`examplefiles/original/` moves to `archive/original-dat/` rather than being
deleted: it is unreferenced by any code, but it is the source material the
shipped `.tab` files were derived from, and moving it out of the top level is
enough to stop it reading like the source of truth.

### 3.1 Manifest schema

```json
{
  "version": 1,
  "generator": "generateExampleDatasets.py",
  "seed": 20260809,
  "defaultScenario": "stategra-mmu-timecourse",
  "scenarios": [
    {
      "id": "gene-single-condition",
      "title": "Gene expression — single condition",
      "summary": "One condition, one relevant-features list. The simplest path.",
      "tests": ["pathway enrichment", "single-condition heatmap"],
      "pipeline": "pathway-acquisition",
      "organism": "mmu",
      "databases": ["KEGG"],
      "conditions": ["Treated_vs_Control"],
      "simulated": true,
      "omics": [
        {
          "omicName": "Gene expression",
          "omicType": "gene",
          "enrichment": "genes",
          "dataFile": "datasets/01-gene-single-condition/data/gene_expression_values.tab",
          "relevantFile": "datasets/01-gene-single-condition/data/gene_expression_relevant.tab"
        }
      ],
      "references": [],
      "expected": {
        "pathwaysFile": "datasets/01-gene-single-condition/expected/expected_pathways.txt",
        "signalFeatures": 1234
      }
    }
  ]
}
```

Paths are **relative to `EXAMPLE_FILES_DIR`**, so the manifest survives the
directory being mounted anywhere. `pipeline` is one of
`pathway-acquisition`, `regions2genes`, `mirna2genes`, `more` — it decides which
entry point the scenario is offered under.

### 3.2 Loader — `src/common/ExampleDatasets.py`

Small, one purpose, no Flask imports so it is unit-testable:

* `loadManifest(exampleFilesDir)` — read + validate + cache by (path, mtime).
* `getScenario(exampleFilesDir, scenarioId)` — returns the scenario dict, or
  raises `UserWarning` naming the valid ids. An unknown id must not reach the
  user as a traceback.
* `listScenarios(exampleFilesDir, pipeline=None)` — the picker's data source,
  filtered to scenarios whose files are actually present on disk.
* `resolveOmics(exampleFilesDir, scenario)` — turns the scenario's `omics` into
  the exact dicts `addGeneBasedInputOmic` / `addCompoundBasedInputOmic` /
  `addReferenceInput` expect, with absolute paths and `isExample: True`.

A missing or malformed manifest degrades to the legacy hardcoded bundle rather
than breaking example mode outright.

### 3.3 Servlet changes

`exampleMode` today is the literal string `"example"` arriving through
`@route('/pa_step1/<path:exampleMode>')`. Because the converter is `<path:>` it
already accepts slashes, so the extension is free:

* `"example"` → the manifest's `defaultScenario` (existing behaviour preserved).
* `"example/<scenarioId>"` → that scenario.
* anything else → the existing `NotImplementedError` with its explanatory text,
  now also listing the valid ids.

The three example branches collapse into one call to
`ExampleDatasets.applyScenario(jobInstance, exampleFilesDir, scenarioId)`. The
string-mangling of omic names into filenames is deleted.

New read-only endpoint `GET /example_datasets` returns the manifest for the
client picker. It exposes no user data and needs no session.

MORE gets its example branch built for the first time: `/dm_fromMOREtoGenes`
grows the same `<path:exampleMode>` optional segment its siblings already have.

### 3.4 Client changes

`#exampleButton` currently calls `setExampleModeHandler()` directly. It becomes:
fetch `/example_datasets`, render a chooser listing the scenarios for this
pipeline (title, summary, what it tests), then apply the chosen one. The three
`setExampleMode()` functions take the scenario's omic list as an argument, so
the filenames they display are the real ones instead of fabricated strings.

### 3.5 Generator — `src/AdminTools/scripts/exampledata/`

A package, not one long script, so each piece stays reviewable:

| module | responsibility |
|---|---|
| `keggsource.py` | load Ensembl↔pathway and pathway↔compound maps from `KEGG_DATA` |
| `simulate.py` | value simulation: planted signal vs. background, ratios and per-sample replicates |
| `writers.py` | one writer per file format (gene values, relevant single/multi, BED, GTF, MORE design/associations) |
| `scenarios.py` | the declarative catalogue — the only file that changes to add a scenario |
| `__main__.py` | CLI: `--outdir`, `--scenario`, `--seed`, `--kegg-data` |

Deterministic: fixed seed, no wall-clock, sorted iteration everywhere. Rerunning
produces byte-identical files, so a regeneration shows an empty diff unless the
data genuinely changed.

**The generated files are committed.** The deployed server then needs no KEGG
data to serve examples, and CI can assert against them.

## 4. Scenario catalogue

| # | id | pipeline | what it exercises |
|---|---|---|---|
| 01 | `gene-single-condition` | pathway-acquisition | one condition, single-column relevance — the minimal path |
| 02 | `gene-multi-condition` | pathway-acquisition | 6 conditions, one shared relevance list |
| 03 | `gene-multi-condition-relevance` | pathway-acquisition | 6 conditions, **per-condition** relevance columns → per-condition p-values, currently unreachable from any example |
| 04 | `multiomics-integration` | pathway-acquisition | 5 omics × 6 conditions: genes, proteins, metabolites (KEGG C-IDs **and** a name-keyed variant to exercise the compound name matcher), TF, miRNA |
| 05 | `regulatory-mirna` | mirna2genes | miRNA values + miRNA→gene association table + target expression |
| 06 | `regulatory-more` | more | per-sample matrices with replicates, design matrix, 2 regulatory omics, association files, relevant-regulator list |
| 07 | `region-based` | regions2genes | BED-like regions + synthetic GTF, 3-column relevant regions |
| 08 | `stategra-multiomics` | pathway-acquisition | the existing real STATegra data, relocated and registered — the default |
| 09 | `stategra-regions` | regions2genes | the real DNase regions; needs the full mouse GTF, so absent from a fresh checkout and simply not offered there |
| 10 | `stategra-mirna` | mirna2genes | the real miRNA table plus the 31 MB miRBase→Ensembl map |

## 5. File formats produced

Taken from the validators and `runMORE.R`, not from prose docs:

* gene/protein/miRNA/compound values — `#ID<TAB>Cond1…CondN`, then `id<TAB>values`
* relevant features, single — one ID per line
* relevant features, per-condition — header of condition names, then one ID per column
* region values — `#CHR<TAB>start<TAB>end<TAB>values…`
* relevant regions — exactly three columns: chr, start, end
* miRNA→gene associations — `miRNA<TAB>EnsemblGeneID<TAB>PLR`
* MORE target/regulator matrices — `ID<TAB>Sample1…SampleN`, numeric, per-sample
* MORE design — `Sample<TAB>Group1<TAB>Group2`, 0/1 indicators, one row per sample
* MORE associations — `Target<TAB>Regulator` (orientation is auto-detected downstream)

## 6. Error handling

* Unknown scenario id → `UserWarning` listing valid ids; never a traceback.
* Manifest missing/malformed → log a warning, fall back to the legacy bundle, so
  a bad deploy degrades instead of removing example mode.
* A scenario whose files are absent is omitted from `listScenarios`, so the
  picker cannot offer something that will fail.
* Generator refuses to run when the species is not installed, naming the
  directory it looked in and the command that installs it.

## 7. Testing

| test | asserts |
|---|---|
| `test_example_manifest.py` | every referenced file exists, is non-empty, is valid UTF-8, has the declared column count; ids unique; omic names unique within a scenario |
| `test_example_scenarios_validate.py` | every scenario runs through the **real** `validateInput`/`validateFile` of its job class and is accepted — the bundled data is proven acceptable before any user clicks |
| `test_example_datasets_loader.py` | unknown id raises with the id list; a corrupt manifest falls back; caching invalidates on mtime |
| `test_example_servlet_scenarios.py` | `"example"` still resolves to the default; `"example/<id>"` resolves; a junk id yields a readable message |
| `test_generator_determinism.py` | two runs at the same seed produce identical bytes |

Existing suite convention applies: standalone `__main__` scripts, run with
`PYTHONPATH=PaintomicsServer`, no pytest.

## 7a. What implementation changed about this design

Recorded because each of these was a wrong assumption in the design above, found
by building the thing and measuring it.

**Missing values are not a supported input.** The design said scenario 02 would
ship ~2% `NA` cells to exercise "NaN handling before FDR correction". It cannot:
`PathwayAcquisitionJob.validateFile` runs `list(map(float, line[1:]))` over every
data row and rejects the file for anything that will not parse. An example with
gaps would be an example that cannot be uploaded. The missing-value generator was
removed and a test (`test_no_values_file_carries_a_missing_value_token`) now
holds the line. Malformed input stays covered by `tests/fake_omics.py`, which
exists to build files that *should* be refused.

**Region promoters are strand-dependent.** The first generator placed every
signal region at `TSS - 500` regardless of strand, which puts a third of them
*inside* the gene body on the minus strand. RGmatch still assigns those to the
gene, under a different area rule, so the scenario would have silently stopped
testing promoter assignment. Fixed and pinned by
`test_signal_regions_sit_upstream_of_their_gene`.

**A per-row missing rate rounds to nothing.** `round(6 * 0.02) == 0`, so the
first implementation of the gap generator produced not a single gap while
looking correct. Found only because a test asserted on the output rather than
the code.

**The MORE scenario needed three measured attempts.** Recovery of the planted
regulator-target pairs, measured by running the real `runMORE.R`:

| attempt | design | recall |
| --- | --- | --- |
| shared ramp per responder, 3 groups × 3 reps, both omics drive each target | 63% |
| independent group profiles, weak group effect, strong per-sample noise | 48% |
| as above, 4 replicates | 66% |
| independent profiles, **strong** group effect *and* strong per-sample noise, 4 groups × 3 reps, one driving omic per target | **80%** |

The 48% dip is the instructive one: decorrelating the candidates by shrinking the
group effect also pushed the true drivers under MORE's `minVariation` filter,
which drops regulators with low variability *across conditions*. Both terms have
to be large — the group effect to survive the filter, the per-sample noise to
make one candidate distinguishable from its decoys. Chance recovery for the
number of pairs MORE reports is ~58%, so 80% is a real signal; the manifest
records `recallFloor: 0.70` for a test to assert against, not the exact figure,
because MORE's model selection is not bit-stable across versions.

**Two pre-existing bugs surfaced and were fixed**, both of which had never been
reachable before because the features that reach them had no example:

* `MOREServlet` derived the path to `runMORE.R` from `CLIENT_TMP_DIR`
  (`os.path.dirname(CLIENT_TMP_DIR.rstrip('/'))`), which assumes the data
  directory is a sibling of `src/`. In the documented development layout it is
  not, so the path resolved to a file that does not exist — and
  `Rscript <missing file>` exits 2 printing nothing, surfacing as "R Script
  failed with exit code 2. Output:" with no hint that the script was never
  found. Now derived from `__file__`, with an explicit existence check.
* `dark.css` set the window header's text colour but never its background, and
  targeted `.x-window-header-title` (ExtJS 6) in an ExtJS 4.2.1 app. Every modal
  title in dark mode was white on near-white. Fixed and verified by measuring
  the computed contrast ratio on a rendered window: 12.02:1.

## 8. Edge cases addressed

* Duplicate feature IDs — the STATegra data contains them (`ENSMUSG00000091455`
  appears five times in `dnase_values.dat`); the generator emits unique IDs, and
  scenario 04 deliberately includes one duplicated compound to keep the
  duplicate-handling path covered.
* Missing values — NOT shipped: the validator rejects any non-numeric cell, so
  a values file with gaps is one no user could upload. See section 7a.
* Line endings — `original/dnase_values.dat` uses classic-Mac `CR` endings,
  which is why `wc -l` reports 0 for it. All generated files use `\n`.
* Encoding — all files ASCII, so `ensure_utf8` normalisation is a no-op and
  cannot mask a bug.
* Compound name ambiguity — the name-keyed metabolomics variant in scenario 04
  includes a name that maps to more than one KEGG compound, exercising the
  matched-metabolites selection step.
* 5+ conditions with Ensembl IDs — scenario 03's per-condition relevance file has
  lines over 80 characters, the case `test_multicondition_validation.py` was
  written for.

## 9. Out of scope

* Species other than *Mus musculus*. The scenario catalogue is declarative, so
  adding `hsa` later is a data change, not a code change.
* Replacing `generateSimulatedData.py` or `tests/fake_omics.py`. The first is a
  developer tool for ad-hoc KEGG-backed data; the second builds deliberately
  malformed files for unit tests. Neither overlaps with a shipped, selectable
  catalogue.
