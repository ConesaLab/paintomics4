# Conversion corpus

Broken files the AI converter is measured against, and the harness that runs them.

Every case is built by CORRUPTING a file that already ships as a working
example, so the original is the ground truth. That matters because a converter
which merely produces something the format validator accepts has done half the
job: it also has to produce the same INFORMATION. Comparing against the original
catches a conversion that drops rows, swaps two conditions, transposes a matrix
the wrong way or coerces values to NaN -- none of which a format check can see.

    python  src/tests/build_conversion_corpus.py      # regenerate the inputs
    node    src/tests/run_conversion_corpus.js        # run them through the agent
    node    src/tests/run_conversion_corpus.js --case ge-transposed --attempts 2

The harness boots the same Pyodide sandbox the browser uses and calls the same
`agent_turn.next_action` the HTTP route calls, so it measures production rather
than a parallel implementation.

## Measured 2026-08-20

16/16 pass, format and information both verified.

| module            | cases | pass |
|-------------------|-------|------|
| gene expression   | 8     | 8    |
| regulatory (MORE) | 5     | 5    |
| region-based      | 3     | 3    |

Getting there fixed six real defects, listed here because the numbers alone
would hide them:

1. The profiler crashed on any file with a title row -- duplicate column names
   made `df[name]` return a DataFrame rather than a Series.
2. `build_user_message` silently dropped the caller's `goal`, so "rebuild the
   missing experimental design" arrived as an ordinary conversion request.
3. `/work/input` was read as a directory by generated code. The input is now
   written under its real name and the exact path is stated.
4. The sandbox cleared `/out` but not `/work`, so a previous case's file
   survived and the profiler described the wrong file.
5. The values contract cannot see a region matrix that has lost every
   measurement -- chromosome/start/end alone passes, because start and end are
   numeric. `REGION_HAS_NO_MEASUREMENTS` closes that; the server shares the gap.
6. Duplicate identifiers at the END of a file were invisible to a 4,000-row
   sample. Row and duplicate counts are now taken over the whole file by reading
   the identifier column alone.

Duplicated identifiers are surfaced as a QUESTION rather than decided: leaving
them double-counts features in the enrichment, collapsing them discards a
measurement the user may have meant to keep, and only the user knows which.
