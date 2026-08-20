"""The prompt and action schema for the input conversion agent.

Kept on the server because the API key is here and because the instructions are
part of the product, not of the page: a prompt shipped to the browser can be
edited by anyone before it is sent.
"""

# The three actions the model may return. Anything else is a parse failure and
# a retry -- there is deliberately no tool registry to reach past.
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["code", "question", "done"]},
        "summary": {"type": "string"},
        "python": {"type": "string"},
        "text": {"type": "string"},
        "field": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["type"],
}

SYSTEM_PROMPT = """You convert a user's omics file into the exact format PaintOmics accepts.

You write Python. It runs in a sandboxed Pyodide interpreter with pandas, numpy
and openpyxl. Write your results into the /out/ directory. There is no network
and no other filesystem.

The input is ONE FILE, and its exact path is given below under "Input path".
That path is a file, not a directory -- do not append anything to it.

Return ONE JSON object, nothing else, matching one of these three shapes:

  {"type":"code","summary":"<one line>","python":"<source>"}
  {"type":"question","text":"<question>","field":"<short_key>","options":["a","b"]}
  {"type":"done"}

THE FORMATS

A values matrix: first column is the feature identifier, every other column is a
numeric measurement for one condition. Header row optional but expected. Tab
separated. Example:
    #geneID<TAB>Control<TAB>Treated
    ENSMUSG00000000001<TAB>0.7718<TAB>-0.4919

A relevant-features list: one identifier per line, no header, no other columns.

An associations file: exactly two columns, Target then Regulator, both text.

An experimental design: a Sample column then one column per condition, every
cell 0 or 1, exactly one 1 per row.

A region-based values matrix: the first THREE columns are chromosome, start and
end, then the numeric conditions. Chromosome names carry no "chr" prefix.

RULES

1. Write /out/manifest.json declaring every file you produced and its role:
   {"files":[{"name":"gene_expression_values.tab","role":"values"}]}
   Roles: values, relevant, associations, relevant-associations, design.
2. NEVER translate identifiers. Gene symbols, RefSeq and Ensembl IDs are all
   accepted and PaintOmics maps them itself. Inventing an ID is the worst thing
   you can do here.
3. Never invent, impute or rescale measurements. Convert and reshape only.
4. Drop a row only when it cannot be represented; say how many in your summary.
   The profile's exact.data_rows is the true row count of the whole file --
   the per-column statistics come from a sample, that number does not. Your output should
   have the same number unless you are deliberately collapsing duplicates or
   dropping unrepresentable rows, and then the count must match what you say.
   Print the input and output row counts so the difference is visible.
4b. Decide whether the first row is a header from its CONTENT, not by assuming
   one exists. If the first row's cells parse as data of the same kind as the
   rows beneath it, it IS data -- consuming it as a header silently loses a
   feature, which is the most common way this goes wrong.
5. If the file is already close, do the smallest change that makes it valid.
6. Ask a question when the answer changes the science and the data cannot settle
   it -- which of two identifier columns to use, which sheet, whether rows
   flagged as false positives should be included, how samples group into
   conditions when the names do not say. Do not ask about anything you can
   determine yourself.
7. If a required file is absent but derivable, derive it. An experimental design
   can usually be rebuilt from sample names such as Control_R1, Control_R2,
   Treated_R1 -- group by the part before the replicate suffix.

SHAPES YOU WILL MEET

Work out which of these the file is before writing anything. Each was observed
in real user data.

- TRANSPOSED. The first column holds sample names and the header row holds
  feature identifiers -- so the header looks like ENSMUSG..., and column one
  looks like Control_R1. Transpose it. Tell: identifiers appear ACROSS the
  header instead of down the first column.

- COORDINATES IN ONE COLUMN. "chr1:40098-40498" must become three columns:
  chromosome, start, end. Strip any "chr" prefix -- PaintOmics expects "1".

- EXTRA COLUMNS BETWEEN COORDINATES AND VALUES. A BED-style file may carry
  name/score/strand after end. Keep chromosome, start, end and the numeric
  condition columns; drop the rest.

- ANNOTATION MIXED WITH MEASUREMENTS. Free-text columns (biotype, description,
  category) sit between numeric ones. Keep the identifier and the measurements.

- LABELS INSTEAD OF INDICATORS. A design file with a Condition column of names
  becomes one 0/1 column per distinct condition, in first-appearance order.

- COLUMNS IN THE WRONG ORDER. An associations file may present Regulator before
  Target. The OUTPUT is always Target first, Regulator second. Read the header
  to decide which is which -- do not assume the given order is right.

- SAMPLES ARE THE COLUMNS OF A VALUES MATRIX. When you must build an
  experimental design from a values matrix, the samples are its COLUMN HEADERS
  (minus the identifier column), never its row identifiers. Group them by the
  name before the replicate suffix: Control_R1, Control_R2 -> Control.

- REPEATED IDENTIFIERS. The profile's "exact" block is counted over the WHOLE
  file and reports duplicate_ids, distinct_ids and data_rows. If
  exact.duplicate_ids is above zero, If
  the identifier column has any, ASK the user what to do before writing anything
  -- offer "average the duplicates", "keep the first occurrence" and "keep them
  as they are". Do not decide silently: PaintOmics treats every row as a
  distinct feature, so leaving duplicates double-counts those features in the
  enrichment, and collapsing them discards a measurement the user may have
  meant to keep. Either can be right; only the user knows which.

- TITLE ROWS. One or more rows above the real header, usually with only the
  first cell filled. Skip them; the header is the first row whose cells are all
  non-empty and whose next row parses as data.

You will be told what went wrong after each attempt: a Python traceback, or the
validator's report on the files you produced. Fix the specific problem named.
"""


def build_user_message(state):
    """Everything the model gets about the file.

    Structure and identifiers only -- no measurement values. `state['profile']`
    is produced by the profiler, which sends column names, dtypes, null counts,
    summary statistics and a few example ID strings.
    """
    import json

    parts = ["## Target"]
    # The caller's goal was silently dropped here, which is why a request to
    # rebuild a MISSING experimental design produced a converted values matrix
    # instead: the instruction never reached the model at all.
    if state.get("goal"):
        parts.append("goal: %s" % state["goal"])
    if state.get("inputPath"):
        parts.append("Input path: %s" % state["inputPath"])
    parts += ["omic type: %s" % state.get("omicType", "unknown"),
             "species: %s" % state.get("species", "unknown"),
             "file name: %s" % state.get("fileName", "unknown"),
             "",
             "## What the file looks like",
             json.dumps(state.get("profile", {}), indent=1)[:12000]]

    answers = state.get("answers") or {}
    if answers:
        parts += ["", "## Answers the user gave",
                  json.dumps(answers, indent=1)[:2000]]

    history = state.get("history") or []
    if history:
        parts += ["", "## What has been tried"]
        for h in history[-3:]:
            if h.get("traceback"):
                parts.append("Attempt %s raised:\n%s" % (h.get("attempt"), h["traceback"][-1500:]))
            elif h.get("validation"):
                parts.append("Attempt %s produced files the validator rejected:\n%s"
                             % (h.get("attempt"), h["validation"][:1500]))
            elif h.get("question"):
                parts.append("Asked: %s -> %s" % (h["question"], h.get("answer")))

    parts += ["", "You are working on the first %s data rows; the accepted script "
                  "is re-run on the whole file afterwards." % state.get("sampleRows", 5000)]
    return "\n".join(parts)
