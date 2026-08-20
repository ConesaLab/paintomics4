# Input format checking and AI-assisted conversion

Status: approved in conversation 2026-08-20, not yet implemented.

## Goal

A user who has omics data in *some* tabular shape should be able to get it into
PaintOmics without knowing what PaintOmics expects. Today a malformed file is
accepted at upload and fails later with a wall of per-line errors, or — worse —
succeeds and yields zero matched features.

Three layers, escalating only as far as each file needs:

- **Layer 0 — validate.** Every upload is checked client-side against the format
  contract. Instant, offline, no LLM. Most users see a green tick and nothing else.
- **Layer 1 — repair.** When the fault is mechanical and unambiguous, offer a
  deterministic one-click fix with a visible diff. Still no LLM.
- **Layer 2 — convert.** Only when 0 and 1 cannot resolve it: an agent writes
  conversion code, runs it in a browser sandbox, and iterates against the
  validator until it passes or it asks the user a question.

Layer 0 is independently valuable and ships first.

## The format contract

Authoritative source is `PathwayAcquisitionJob.py:660-745` (values files) and
`:606-660` (relevant files), not the example datasets. A **values file** must:

1. Be valid UTF-8 (`ensure_utf8`; a BOM is tolerated via `utf-8-sig`).
2. Use tab or comma. `Job.detect_delimiter` (`Job.py:47`) returns `\t` if the
   first non-empty line contains a tab, else `,`. **Comma files already work** —
   do not build a delimiter repair. The one real trap is a comma-delimited file
   whose header happens to contain a tab, which mis-detects as TSV.
3. Have at least 2 columns.
4. Have the *same* column count on every line — set from the first data line.
5. Have every column from index 1 onward parse as `float`.
6. Not exceed `MAX_NUMBER_FEATURES` (1,000,000 — not a practical limit).

Header detection is subtle and worth restating because it drives Layer 0's
messages: line 0 is treated as a header **only if `float(line[1])` raises**.
Detection keys on column *two*, not column one. A header whose second cell is
numeric is silently parsed as data.

Errors stop being collected after 10 lines, so today a structurally wrong file
produces ten cryptic messages and no diagnosis. Layer 0 exists to replace that.

**Relevant files** are one ID per line, no header. **Associations** are
`Target<TAB>Regulator`. **Design** files are `Sample` plus 0/1 indicator columns
(see `more-condition-columns-are-indicator-patterns`).

## Architecture

The LLM and the sandbox sit on opposite sides of the wire.

```
PARENT PAGE (your origin)      — agent loop (state machine), validator
   |  profile / traceback              |  postMessage
   v  code or question                 v  file bytes, result
SERVER: stateless proxy          IFRAME (opaque origin)
  auth, quota, key -> CSIC         Pyodide + pandas, the generated script
                                   no network, no LLM, no credentials
```

- The **sandbox** is an iframe with `sandbox="allow-scripts"` and *without*
  `allow-same-origin`, so it has an opaque origin: no cookies, no localStorage,
  no parent DOM, no network. Contents are Pyodide, pandas/numpy/openpyxl, the
  user's file, and the generated script. Blast radius is the user's own tab.
- The **validator runs in the parent, never in the sandbox.** If it ran inside,
  generated code could stub it out and grade itself green.
- The **agent loop** is ~200 lines of JS in the parent. The model returns one of
  exactly two typed actions — write code, or ask the user. Not tool-calling:
  there is no registry to reach past. Max 5 iterations.
- The **server route is a stateless proxy**: one LLM call per request, holding
  the CSIC key, enforcing auth, per-user quota and a concurrency cap.

Raw expression values never leave the user's machine. Only column names, dtypes,
row counts, summary statistics, example ID strings, tracebacks and validator
output are sent. This is a privacy property worth stating in the UI.

### The route must not block

`paintomics4.ini` is `processes = 1`, `threads = 4` — four threads serve every
API request (see `four-uwsgi-threads-serve-the-whole-site`). The CSIC gateway
takes ~120 s per attempt. An inline route would hold a quarter of the site's
capacity per conversion and take the site down at four concurrent users.

Follow `aiInterpretInitiate` (`AIInterpretServlet.py:136`): enqueue into
`QUEUE_INSTANCE`, return a ticket, let the browser poll. Cap in-flight
conversions at 2 server-wide; beyond that, refuse with "busy, try again".

## Impact on users who never touch it

- Parsing, pandas and all conversion memory are on the user's machine. Zero
  server CPU or RAM.
- Outputs land in `CLIENT_TMP_DIR` via the existing `registerFile`, so they
  appear in the normal picker and download through `dataManagementDownloadFile`.
  No new storage or download machinery. They count against that user's own
  200 MB `MAX_CLIENT_SPACE`.
- Conversions share the CSIC token bucket with AI report generation. The
  concurrency cap of 2 is what keeps a conversion burst from degrading reports.
- Pyodide (~20 MB) and the converter JS **must** lazy-load at drawer-open, or
  every visitor pays for a feature they did not use.
- The Step 1 entry point touches `PA_Step1Views.js` (224 KB, every job's path).
  Keep the drawer in its own file; the Step 1 change is one button plus a
  callback setting an existing field; ship behind a flag, inert by default, the
  way `AI_FULL_AGENT` does.

## Front end

`PA_AIInterpretView.js` contains zero `Ext.create` and zero `xtype:` — the AI
surfaces already render plain DOM inside an Ext container. Follow that; do not
fight ExtJS 4.2.1.

Progressive disclosure under the file row: valid files show a one-line summary
and nothing more. Layer 1 offers a fix with a diff. Layer 2 opens a drawer that
overlays Step 1 without unmounting it, showing a live transcript (not a spinner
— ~120 s per call is too long to fake), elapsed time, a working Cancel, the
generated code behind a toggle, and a review diff with the validator checklist
as the thing the user approves.

## Acceptance test

`Caudal SCI_bPAC_FINAL.xlsx` and `Rostral SCI_bPAC_FINAL.xlsx` — mouse spatial
transcriptomics of spinal cord injury with bPAC. They exercise, in one artifact:

1. **Multi-sheet**: 7 and 6 sheets; only 4-5 hold data.
2. **A banner row below the header**: row 1 of every per-region sheet is
   `✓ GENI VALIDATI (n)` with the rest blank. Naive `read_excel` yields a
   garbage first data row.
3. **Annotation columns interleaved with measurements**: only 6 of 14-19 columns
   are values (`SCI_vs_H_10d`, `SCI_vs_H_30d`, `bPAC_vs_SCI_10d`,
   `bPAC_vs_SCI_30d`, `bPAC_vs_H_10d`, `bPAC_vs_H_30d`). `Valence_Source`,
   `Functional_Category`, `Temporal_Logic`, `Flag_Detail` are free text — every
   row fails rule 5 above.
4. **Schema drift between the two files**: Caudal has `PriorityScore` plus
   `S_SCI`/`S_bSCI`/`S_bH`/`Bonus_Partial`; Rostral has `PriorityScore_v12` and
   lacks the `S_*` columns.
5. **Long vs wide**: `Ranked_Global_Filtered` carries a `Region` column; the
   per-region sheets encode region as the sheet name.
6. **Mixed language**: `Geni_Flaggati`, `FALSO POSITIVO`, `bPAC opposto a healthy`.
7. **A prose sheet**: `Methodology` is 2 columns of text.
8. **Cross-sheet duplicate IDs**: `Mrpl43` appears in Caudal `MN spots` and in
   `Geni_Flaggati`; concatenating sheets breaks per-row ID uniqueness.
9. **Gene symbols, not Ensembl** (`Plaa`, `Cldn10`, `Etv4`). Correct as-is —
   `findIDsByFeaturesName` resolves `display_id` at Step 2. The converter must
   NOT translate IDs.

Two traps the validator cannot catch, which the agent must raise as questions:

- **`Geni_Flaggati` is a rejection list** — genes marked `FALSO POSITIVO`.
  Concatenating every sheet silently imports known false positives.
- **The data is already filtered** (~400 genes of a genome). PaintOmics
  enrichment scores relevant features against a background of all measured
  features; a pre-filtered upload with no full matrix produces optimistic
  p-values. Compare `simulated-example-significance-calibration`. The agent must
  say so rather than produce a confident wrong answer.

Acceptance: both workbooks convert to a values matrix PaintOmics parses without
error, the flagged-gene and background questions are surfaced to the user, and a
job run on the output reaches Step 3 with a non-zero matched-feature count.

## Out of scope

- ID translation. `findIDsByFeaturesName` already does it; an LLM guessing
  `ENSMUSG` numbers is pure hallucination surface.
- `.h5ad` / Seurat objects. `anndata` is not in the Pyodide distribution.
- Server-side code execution. Rejected: it needs a container runtime on a box
  whose whole web tier is one process with four threads.
