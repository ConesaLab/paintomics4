# Input format checking and AI conversion

Status: Layers 0 and 1 built and verified. Layer 2 redesigned 2026-08-20 after
the requirement was restated; not yet implemented.

## The requirement

**If a file contains information PaintOmics can analyse, PaintOmics must be able
to analyse it.** The user should not have to know what shape the tool expects.

That is a much stronger claim than "handle the common cases", and it is what
rules out the design this document previously described. A converter built on a
fixed vocabulary of operations — pick a sheet, drop these columns, skip that row
— can only ever handle the transformations someone thought of in advance. The
first user with a transposed matrix, a long-format table, per-sheet replicates
that need averaging, or counts that need a log is stuck, and no amount of
prompting fixes it because the operation cannot be expressed.

So the agent writes real code. That decision drives everything below.

## Three layers

- **Layer 0 — validate** (BUILT). Every upload is checked client-side against
  the format contract. Instant, offline, no LLM.
- **Layer 1 — repair** (BUILT). Deterministic one-click fixes for mechanical
  faults, with a visible diff.
- **Layer 2 — convert** (THIS DOCUMENT). An agent writes pandas, runs it in a
  browser sandbox, checks the result against Layer 0's validator, and iterates.

Layer 2 is the last resort, not the first. A decimal comma is repaired by a
regex in Layer 1 — routing it through the gateway would cost ~120 s and be less
reliable than the regex it replaces.

## Why the sandbox is in the browser

The generated code has to run somewhere. It does not run on the server.

`paintomics4.ini` is `processes = 1, threads = 4`: four threads serve every API
request on paintomics.uv.es. A 100 MB conversion executing server-side would
occupy a quarter of the site's capacity for as long as it ran, and an
arbitrary-code executor on that host is a security surface nobody needs.

The sandbox is an iframe with `sandbox="allow-scripts"` and **without**
`allow-same-origin`, so it has an opaque origin: no cookies, no localStorage, no
parent DOM, no network. It holds Pyodide, pandas/numpy/openpyxl, the user's file
and the generated script — no PaintOmics code and no credentials. The worst a
malicious or mistaken script can do is spoil the tab it runs in.

The LLM call happens on the server, outside the sandbox, so the sandbox never
needs a network capability at all.

## What crosses the wire

- **Browser → server**: column names, dtypes, row counts, summary statistics,
  example identifier strings, tracebacks, validator output.
- **Server → browser**: Python source, or a question for the user.
- **Browser → server, only on accept**: the converted files, through the
  existing upload endpoint.

Raw measurement values never leave the user's machine until they accept the
result. For unpublished omics data that is the difference between people using
this and not, and it should be stated in the UI.

## Develop on a sample, apply to the whole file

The upload cap is **100 MB**, matching `SERVER_MAX_CONTENT_LENGTH`, which is
already 100 MB — so no server or nginx change is needed.

Two consequences follow, and neither is optional.

**Quota.** `MAX_CLIENT_SPACE` is 200 MB per user. Only the CONVERTED file is
stored server-side (the source stays in the browser unless the user uploads it
separately), so one 100 MB conversion takes half a user's space. The drawer
states the output size before the user accepts.

**Memory.** 100 MB of CSV is roughly a million rows, and pandas holds several
times the file size in RAM. Running every agent attempt over the whole thing
would make each round slow and would put the largest inputs at risk of taking
the tab down.

So the loop iterates on the **first 5,000 data rows** and the accepted script
runs once over the full file at the end. Iteration is fast regardless of input
size, memory peaks once rather than five times, and the full pass is checked by
the same validator before anything is offered.

The full pass on a 100 MB input is the one genuinely risky operation in this
design, so it is measured rather than assumed: peak heap is recorded for a
100 MB fixture, and if a single `read_csv` will not hold, the executor reads in
chunks and the agent is told to write a script that accepts a chunk iterator.
The measured ceiling goes in the README, and a file above it gets an honest
warning instead of a crashed tab.

## The loop

```
profile → agent writes python → run on sample → VALIDATE
             ↑                                     │
             └──── traceback + validator report ───┘   (max 5 rounds)
                          │
              ask the user when ambiguous
                          │
                  run on the full file → review → accept
```

The exit condition is the **validator**, not the model's opinion. It is the same
module Layer 0 uses, which a test pins to the server's own loop over every
example file. An agent cannot declare success on a file the server would reject.

The model returns one of exactly three typed actions — `code`, `question`,
`done` — so there is no tool surface to reach past. Anything else is a parse
failure and a retry.

## What "any data issue" actually requires

The transformations a real corpus demands, all of which pandas expresses and a
fixed vocabulary does not:

transpose (samples as rows) · long → wide pivot · merge or concatenate sheets ·
log/ratio computation · aggregate duplicate identifiers · split a combined
identifier column · multi-row and merged-cell headers · per-condition replicate
averaging · derive a relevant-features list from a p-value column · infer a
design matrix from sample names.

## Honest success criteria

"Always works" cannot be promised, and claiming it would be dishonest. What can
be done is to measure it.

A corpus of deliberately awful inputs is built and the pass rate reported: the
two SCI bPAC workbooks, a transposed matrix, a long-format table, a multi-row
header, merged cells, raw counts needing a log, duplicated identifiers, a
latin-1 export, a GEO series matrix, and a DESeq2 results table. The measured
number goes in the README rather than a claim.

When the agent cannot finish, it says so and hands back the best partial result
**plus the code**, so a user who knows pandas can take it from there. That is
better than a dead end, and it is the honest failure mode.

## Acceptance

`Caudal SCI_bPAC_FINAL.xlsx` and `Rostral SCI_bPAC_FINAL.xlsx` — mouse spatial
transcriptomics of spinal cord injury with bPAC. Between them they carry:

1. **Multi-sheet**: 7 and 6 sheets; only 4-5 hold data.
2. **A banner row under the header**: `✓ GENI VALIDATI (n)`, rest of the row blank.
3. **Annotation interleaved with measurements**: 6 of 14-19 columns are values
   (`SCI_vs_H_10d`, `SCI_vs_H_30d`, `bPAC_vs_SCI_10d`, `bPAC_vs_SCI_30d`,
   `bPAC_vs_H_10d`, `bPAC_vs_H_30d`); `Valence_Source`, `Functional_Category`,
   `Temporal_Logic`, `Flag_Detail` are free text.
4. **Schema drift between the two files**: Caudal has `PriorityScore` plus
   `S_SCI`/`S_bSCI`/`S_bH`/`Bonus_Partial`; Rostral has `PriorityScore_v12` and
   no `S_*`. Same agent, different result — this is what proves nothing is
   hardcoded to one file.
5. **Long vs wide**: `Ranked_Global_Filtered` carries a `Region` column; the
   per-region sheets encode region in the sheet name.
6. **Mixed language**: `Geni_Flaggati`, `FALSO POSITIVO`.
7. **A prose sheet**: `Methodology`, two columns of text.
8. **Cross-sheet duplicate identifiers**: `Mrpl43` is in `MN spots` and in
   `Geni_Flaggati`.
9. **Gene symbols, not Ensembl** — correct as-is. `findIDsByFeaturesName`
   resolves `display_id` at Step 2, so the converter must NOT translate them.

Two traps no validator can catch, which the agent must raise as **questions**
rather than decide silently:

- `Geni_Flaggati` lists genes marked `FALSO POSITIVO`. Concatenating every sheet
  imports known false positives into the analysis.
- Both workbooks are already filtered to ~400 genes. PaintOmics scores relevant
  features against a background of all measured features, so a pre-filtered
  upload with no full matrix yields optimistic p-values. Compare
  `simulated-example-significance-calibration`.

Passing means: both workbooks convert to files the validator accepts, both
questions are surfaced, and a job run on the output reaches Step 3 with a
non-zero matched-feature count.

## Out of scope

- Identifier translation. `findIDsByFeaturesName` already does it; an LLM
  guessing `ENSMUSG` numbers is pure hallucination surface.
- `.h5ad` / Seurat. `anndata` is not in the Pyodide distribution.
- Server-side execution, for the thread-budget and security reasons above.
