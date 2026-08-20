# Real-world conversion corpus

`run_realworld_corpus.js` runs 38 **real** user files — GEO supplements, PRIDE
proteomics exports, MetaboLights MAF tables, a collaborator's multi-sheet
workbook — through the production conversion agent and grades each result on
both halves of "correct": the format PaintOmics accepts, **and** the
information the file carried.

It complements `run_conversion_corpus.js` (the synthetic corpus). The synthetic
corpus proves the agent can undo a *known* corruption, so the untouched
original is ground truth. This corpus asks the harder question: given a file
nobody broke on purpose, does the output keep every measurement the file held,
and nothing that is not a measurement?

```
node PaintomicsServer/src/tests/run_realworld_corpus.js \
     [--dir ~/Desktop/test-fails-check] [--only REGEX] [--attempts N] [--shard i/n]
```

The files live outside the repository (300 MB of other people's data); point
`--dir` at them. The default is `~/Desktop/test-fails-check`.

## How it grades

`realworld_answer_key.js` holds, for each file, what a correct conversion must
contain — written after reading the file: which sheets hold measurements, which
columns are per-sample values rather than statistics or annotation, which rows
the authors flag, where the header really is. `realworld_truth.py` extracts each
expected table with pandas, and the harness compares the agent's output against
it:

- **Identifiers as a set.** Losing a gene or inventing one fails. A trailing
  `.version` on an Ensembl ID, a `sp|ACC|NAME` UniProt group vs its bare
  accession, and an Excel-corrupted `Sept9`→date are normalised, because those
  are spellings, not information.
- **Values by identifier, columns matched by name *and* value.** Renaming or
  reordering columns is fine; a value that moved is not. A column name that
  matches but whose values disagree does **not** count as a match — otherwise a
  file that renamed its FPKM columns to bare sample names would be graded as the
  counts table.
- **Every measurement family must survive.** A file with counts *and* TPM *and*
  log2FC, or a workbook with one table per region, must produce all of them; a
  conversion that keeps one and drops the rest is a failure even though it
  passes the validator.
- **Statistics become the relevant-features list.** A DESeq2/edgeR table's
  `padj`/`FDR` column is expected as a relevant list, not as matrix columns.

`anyOf` on a table lists equivalent correct extractions (duplicates averaged or
kept; identifier by accession or by symbol). `tableSets` lists alternative
*complete* answers (transcript-level vs gene-level). `noValues` marks files that
carry no measurement at all — for those, building a matrix out of q-values is
the failure.

## What it caught

Every rule in `prompts.py` under "WHAT TO KEEP" and "SHAPES YOU WILL MEET" is
there because this corpus caught the agent getting it wrong on a real file:

1. **Multi-sheet workbooks reduced to one sheet.** The SCI workbook has four
   regional sheets; the agent converted only the first. Fix: convert every
   measurement sheet, skip the union/methodology sheets, and say which under
   `skipped`.
2. **q-values pivoted into an "expression matrix".** A DESeq2 result and a
   marker-gene table have no per-sample values; the agent built a matrix out of
   the statistics. Fix: the WHAT-TO-KEEP taxonomy, and the significance column
   becomes the relevant list.
3. **Tidy (long) tables collapsed.** A per-tissue table repeats each gene once
   per tissue; the agent emitted it as-is, so every gene appeared six times.
   The profiler now counts duplicates in **each** candidate identifier column
   (counting only column 0 — the tissue — reported zero), and the agent pivots.
4. **Two per-sample families merged into one.** A table with `END_D37` *and*
   `END_D37_fpkm` holds two families; the agent kept one. Fix: the
   MEASUREMENT-FAMILIES rule that suffixed/prefixed columns naming the same
   samples are different families.
5. **The header found one row off.** A DESeq2 sheet with `Control:`/`Treatment:`
   lines above the real header, and a MetaboLights MAF with sample names on the
   *second* header row, both misplaced the header. Fix: the header detector
   picks the most-filled text row above the first numeric row.
6. **Silent duplicate identifiers.** The agent emitted a double-counted matrix
   without asking. Fix: the acceptance gate (`gradeOutputs`) rejects a values
   file with repeated identifiers **unless** the agent asked the user or
   documented in the manifest why they are kept (a phosphosite table has one row
   per site, legitimately).
7. **Empty identifiers.** A mis-coalesced metabolomics identifier left 185 rows
   with a blank first cell; the validator now rejects `EMPTY_IDENTIFIER`.
8. **An empty output file sank the whole run.** When a significance column was
   entirely blank, the agent kept emitting an empty relevant list that failed
   validation and exhausted its attempts, losing the correct values matrix too.
   Fix: the prompt does not write a file that would be empty; it notes it and
   moves on.

## Non-determinism

The gateway model is small and runs at temperature 0.1, so a given file passes
on most runs but not every run — a hard pivot or a two-family split occasionally
comes out wrong. Treat a single red cell as "re-run to confirm"; a file that
fails every run is a real gap. The synthetic corpus is the deterministic gate
for CI; this corpus is the breadth measurement.
