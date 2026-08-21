# AI input converter — how it handles real files

The converter turns any file that *contains* omics measurements into the exact
format PaintOmics accepts, keeping every measurement and dropping only what
PaintOmics cannot use. It is the drawer that opens from the **Convert it for
me** button on a file that fails the format check.

This note answers the three questions raised in review, each with the design
that ships and where it is exercised.

## 1. A workbook with several sheets, each an expression table

**Every measurement sheet becomes its own values file; nothing is merged and
nothing is dropped.**

The profiler describes every sheet — name, columns, row counts, a few example
rows — and the agent converts each measurement table separately, names it after
its sheet, and lists the sheets it did *not* convert (methodology, legends,
free text) under `skipped` with a reason. If one sheet is only the union of the
others (a "global"/"all" sheet carrying a Region column), the per-group sheets
are the information and the union is skipped.

The review panel then shows one card per table, each with a preview, the columns
it kept, and the columns it left out. The user picks which table fills this omic
box, and can tick **"also add the other N as separate omics"** to load the rest
into sibling omic boxes named after their source — so a four-region workbook
becomes four omics in one step. Any table can also be downloaded.

*Measured:* the four-region SCI workbook (`Caudal SCI_bPAC_FINAL.xlsx`) →
Dorsal / Medial / Ventral GM / MN spots, four values files, each with its own
significant-gene list; the Plasmodium TPM workbook → nine tables across IT4 and
3D7 var/rif genes, TPM and reads kept as separate families.

## 2. p-values and other non-expression columns

**Statistics never go into the values matrix; a significance column becomes the
relevant-features list instead.**

PaintOmics paints measurements — expression, abundance, fold change — on pathway
maps. It cannot use `pvalue`, `padj`, `FDR`, `t`, `baseMean`, peptide counts,
coverage, priority scores, or annotation (symbol, description, biotype,
coordinates). The prompt carries an explicit taxonomy of MEASUREMENTS vs
STATISTICS vs ANNOTATION, and the agent keeps only the measurements. The
dropped columns are shown to the user as struck-through **Left out** chips, so
the decision is visible, not hidden.

The statistics are not thrown away, though: a DESeq2/edgeR/limma table's
`padj`/`FDR` column becomes a **relevant-features list** (identifiers below the
significance threshold), linked to the values file and attached automatically to
the omic's "relevant features" slot. A file that carries *only* statistics and
no measurement at all (a list of significant genes per cell type) produces
relevant lists and says in its summary that it holds no expression values —
building a matrix out of q-values is treated as an error.

*Measured:* `GSE297370_edgeR_DEGs_all_Samples.csv` → counts / TPM / log2TPM
matrices **plus** an `FDR < 0.05` relevant list, with `logFC`, `logCPM`,
`PValue` dropped from the matrices.

## The conversion sheet — what the user watches

The sheet that opens from **Convert it for me** is laid out as a notebook of
the run rather than a spinner, so that every claim the feature makes is
checkable on screen:

- **Stage rail** — Read → Plan → Run → Check → Apply → Review, lit as the
  agent's own state machine reaches each stage. A retry visibly drops back to
  Plan; a failure marks the stage it failed in. The attempt count and the clock
  sit beside it.
- **What the agent sees** — the profile exactly as the model receives it: the
  container (workbook / delimited text), every sheet with rows × columns, each
  column as a chip kind-coded *identifier candidate / numeric / text*, repeated
  identifiers flagged on the chip, column families, the example rows behind a
  disclosure, the payload size in characters and the gateway it is sent to
  (from `/ai_provider`). This is what makes "only the structure leaves your
  computer" a statement the user can verify rather than trust.
- **Timeline** — every step with the seconds it cost (the model turns are the
  visible cost), attempt badges, the generated script and its printed output
  one click away at the step that ran them (with Copy), the validator's verdict
  quoted one failure per line, and the agent's questions as answer cards.
- **Result tickets** — one per table: preview, kept / left-out columns, the
  attached relevant list, a download; the chosen one wears the destination
  omic's hue bar.
- **Dock** — the composer (two lines tall, grows as you type; Enter sends) to
  steer or answer in your own words, then the decision row.

On **Use this table** the omic card's strip records the provenance —
*Converted by PaintOmics AI from `<file>` (table "…", relevant-features list
attached)* — with a **Convert again** link that reopens the sheet on the
original upload.

Section 3 of the upload form states the offer before any file is picked, as a
plain row on the same two columns as the Section 2 panel: a bold lead ("Bring
your files as they are.") and one sentence on the left, a "Works with" column
of format pills on the right. There is deliberately no checkbox: pressing
**Convert it for me** on a file is the consent, nothing leaves the browser
before that, and a second box under the interpretation's consent box read as
the same decision asked twice. The page keeps one right column — the
experiment-design field, the "Works with" pills and the Help panel all start
on the same x. A standing one-line note in every omic card and a sentence in
the Help panel complete it. The actor is named the same way on every surface:
*the PaintOmics AI agent*. The job's name is taken from the experiment
design's first line; there is no separate description field.

## 3. Letting the user steer with a prompt, and review the result

**Yes — the drawer is a conversation, not a one-shot.**

Every conversion ends in a review the user reads before anything is loaded: the
summary, one card per table with a data preview and kept/left-out columns, the
attached relevant lists, and the sheets that were skipped. Below it is a
composer. The user types an instruction in their own words —

> "keep the flagged genes", "use the reads sheet, not TPM", "column A is a KEGG
> ID", "these duplicates are separate isoforms, keep them"

— and the agent **revises the accepted script** rather than starting over,
re-runs it, and re-checks it. The same composer answers a question in the user's
own words when none of the offered options fit. The instruction is shown in the
transcript as a step, so the history of what was asked and changed is visible.

Some decisions the agent raises itself, because only the user can make them:
whether rows the authors flagged as false positives belong in the analysis;
whether a transcript table stays transcript-level or is summed to genes; and —
deterministically, before any code runs — how to handle duplicate identifiers
that nothing in the file explains (average, keep first, or keep as-is), since
leaving them double-counts features and collapsing them discards a measurement.

*Measured:* converting the SCI workbook, then typing "keep the flagged rows
too" in the composer, re-ran the conversion and lifted Dorsal GM from 139 to
147 rows with the note "All genes included, including those flagged as false
positives, per user request."

## Everything the file held, nothing it did not — how that is verified

Two test corpora pin both halves of "correct":

- **Synthetic** (`run_conversion_corpus.js`, 16 cases): each broken file is a
  *corrupted copy of a shipped example*, so the untouched original is ground
  truth for the information, not just the format. This is the deterministic CI
  gate.
- **Real-world** (`run_realworld_corpus.js`, 38 files): GEO supplements, PRIDE
  proteomics exports, MetaboLights MAFs, a collaborator's workbook, graded
  against an expert answer key that records which sheets, columns and rows a
  correct conversion must contain. See `README-realworld-corpus.md`.

The acceptance gate is always PaintOmics' own validator — the agent never grades
its own work — extended to reject a values matrix that silently repeats an
identifier or leaves an identifier cell empty.

## Privacy and isolation (unchanged)

The generated Python runs in an opaque-origin Pyodide sandbox
(`sandbox="allow-scripts"`, no `allow-same-origin`): no cookies, no
localStorage, no parent DOM, no network. Only the file's **structure** — column
names, dtypes, counts, a few example rows — is sent to the LLM gateway; the
measurements never leave the machine, and the server refuses any request that
carries raw data. The feature is gated behind `AI_INPUT_CONVERTER` and is inert
where the flag is unset.
