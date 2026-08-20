# Input Format Converter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user upload omics data in almost any tabular shape and get it into PaintOmics, by validating every upload instantly, repairing mechanical faults deterministically, and falling back to an AI agent that writes conversion code and runs it in a browser sandbox.

**Architecture:** Three escalating layers. Layer 0 and 1 are pure client-side JavaScript with no LLM and no network. Layer 2 runs Pyodide in an opaque-origin iframe (no network, no cookies) driven by a state machine in the parent page; the server is only a stateless, queued LLM proxy that never sees raw data values.

**Tech Stack:** Vanilla JS (no ExtJS — follow `PA_AIInterpretView.js`, which uses plain DOM), Node 26 built-in test runner for JS, Pyodide + pandas for the sandbox, Flask + PySiQ + `llm_client.py` on the server, Python `unittest` for server tests.

**Spec:** `docs/superpowers/specs/2026-08-20-input-format-converter-design.md`

## Global Constraints

- Values-file contract is defined by `PathwayAcquisitionJob.py:660-745`, not by the example files. Match it exactly, including the quirk that line 0 is a header **only if `float(line[1])` raises**.
- `Job.detect_delimiter` (`Job.py:47`) already accepts comma files. **Do not build a delimiter repair.**
- `MAX_NUMBER_FEATURES = 1000000` (`src/conf/serverconf.py:16`).
- Converter upload cap: **20 MB**, far below the global `SERVER_MAX_CONTENT_LENGTH = 100 MB`.
- Never translate identifiers. `findIDsByFeaturesName` resolves `display_id` at Step 2.
- No server route may wait on the LLM inline. `processes=1, threads=4` — enqueue via `QUEUE_INSTANCE` and poll, like `aiInterpretInitiate` (`AIInterpretServlet.py:136`).
- Max 2 in-flight conversions server-wide.
- Ship behind `AI_INPUT_CONVERTER`, inert when unset.
- Pyodide and all Layer 2 JS must lazy-load at drawer-open only.
- Every JS file must run in the browser as a plain script **and** be `require()`-able by tests. Use the UMD tail shown in Task 1.
- Bump `?v=` in `index.html` for every edited JS/CSS file, restart the server, and verify in Chrome before claiming a task done (CLAUDE.md §5).

## File Structure

| File | Responsibility |
|---|---|
| `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/format-reader.js` | Bytes → `{encoding, delimiter, rows}`. Mirrors `ensure_utf8` + `detect_delimiter` + `csv_reader`. |
| `.../InputFormat/format-validator.js` | Parsed rows → problems + summary. Mirrors `PathwayAcquisitionJob.py:660-745`. No DOM. |
| `.../InputFormat/format-repair.js` | Deterministic repairs; returns repaired rows + a change list for the diff. |
| `.../InputFormat/format-panel.js` | Layer 0/1 status strip under the file row. Plain DOM. |
| `.../InputFormat/sandbox-host.js` | Parent side of the iframe: load, run code, return results. |
| `PaintomicsClient/public_html/inputformat-sandbox.html` | Sandbox document: Pyodide, no network, opaque origin. |
| `.../InputFormat/convert-agent.js` | The agent loop state machine. |
| `.../InputFormat/convert-drawer.js` | Layer 2 UI: transcript, questions, review diff, accept. |
| `PaintomicsServer/src/servlets/InputConvertServlet.py` | Queued, stateless LLM proxy for conversion turns. |
| `PaintomicsServer/src/classes/InputConvert/prompts.py` | Prompt + action JSON schema. |
| `PaintomicsClient/tests/inputformat/*.test.js` | Node tests for every pure-JS module. |
| `PaintomicsServer/src/tests/test_input_convert_*.py` | Python `unittest` scripts. |

**Phase 1 = Tasks 1-4** (Layers 0 and 1). Independently shippable, no AI, no Pyodide.
**Phase 2 = Tasks 5-9** (Layer 2).

---

### Task 1: Format reader

**Files:**
- Create: `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/format-reader.js`
- Test: `PaintomicsClient/tests/inputformat/format-reader.test.js`

**Interfaces:**
- Consumes: nothing.
- Produces: `readDelimited(bytes) -> {encoding, delimiter, rows, decodeError}` where `bytes` is a `Uint8Array`, `encoding` is `"utf-8"|"utf-8-sig"|null`, `delimiter` is `"\t"|","`, `rows` is `string[][]`, `decodeError` is `string|null`.

- [ ] **Step 1: Write the failing test**

```js
// PaintomicsClient/tests/inputformat/format-reader.test.js
const test = require("node:test");
const assert = require("node:assert");
const { readDelimited } = require("../../public_html/app/view/PathwayAcquisitionViews/InputFormat/format-reader.js");

const bytes = (s) => new Uint8Array(Buffer.from(s, "utf8"));

test("prefers tab when the first non-empty line has one", () => {
  const r = readDelimited(bytes("a\tb,c\n1\t2,3\n"));
  assert.strictEqual(r.delimiter, "\t");
  assert.deepStrictEqual(r.rows[0], ["a", "b,c"]);
});

test("falls back to comma when the first non-empty line has no tab", () => {
  const r = readDelimited(bytes("a,b\n1,2\n"));
  assert.strictEqual(r.delimiter, ",");
});

test("skips leading blank lines when sniffing, like detect_delimiter", () => {
  const r = readDelimited(bytes("\n\n a,b \n1,2\n"));
  assert.strictEqual(r.delimiter, ",");
});

test("strips a UTF-8 BOM and reports utf-8-sig", () => {
  const r = readDelimited(new Uint8Array([0xef, 0xbb, 0xbf, ...Buffer.from("a,b\n1,2\n")]));
  assert.strictEqual(r.encoding, "utf-8-sig");
  assert.strictEqual(r.rows[0][0], "a");
});

test("reports a decode error for non-UTF-8 bytes", () => {
  const r = readDelimited(new Uint8Array([0x67, 0x65, 0x6e, 0xe9, 0x0a]));
  assert.ok(r.decodeError);
});

test("unquotes CSV fields the way csv_reader does", () => {
  const r = readDelimited(bytes('a,"b,c",d\n1,"2,5",3\n'));
  assert.deepStrictEqual(r.rows[1], ["1", "2,5", "3"]);
});

test("drops a trailing newline without emitting an empty final row", () => {
  const r = readDelimited(bytes("a,b\n1,2\n"));
  assert.strictEqual(r.rows.length, 2);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test PaintomicsClient/tests/inputformat/format-reader.test.js`
Expected: FAIL — `Cannot find module '.../format-reader.js'`

- [ ] **Step 3: Write minimal implementation**

```js
// format-reader.js
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Mirrors Job.detect_delimiter: the FIRST non-empty line decides, tab wins
  // over comma, and a line with neither still yields tab.
  function detectDelimiter(text) {
    for (const raw of text.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      if (line.includes("\t")) return "\t";
      if (line.includes(",")) return ",";
      return "\t";
    }
    return "\t";
  }

  // Minimal RFC4180 split matching Python's csv.reader for the shapes we see:
  // quotes group, "" is a literal quote, delimiters inside quotes are data.
  function splitLine(line, delimiter) {
    const out = [];
    let field = "";
    let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (quoted) {
        if (c === '"') {
          if (line[i + 1] === '"') { field += '"'; i++; }
          else quoted = false;
        } else field += c;
      } else if (c === '"') quoted = true;
      else if (c === delimiter) { out.push(field); field = ""; }
      else field += c;
    }
    out.push(field);
    return out;
  }

  function readDelimited(bytes) {
    let encoding = "utf-8";
    let body = bytes;
    if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
      encoding = "utf-8-sig";
      body = bytes.subarray(3);
    }
    let text;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(body);
    } catch (e) {
      return { encoding: null, delimiter: "\t", rows: [], decodeError:
        "The file is not valid UTF-8. Re-save it as UTF-8 and upload again." };
    }
    const delimiter = detectDelimiter(text);
    const rows = text
      .replace(/\r\n/g, "\n")
      .split("\n")
      .filter((line, i, arr) => !(line === "" && i === arr.length - 1))
      .map((line) => splitLine(line, delimiter));
    return { encoding, delimiter, rows, decodeError: null };
  }

  return { readDelimited, detectDelimiter, splitLine };
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test PaintomicsClient/tests/inputformat/format-reader.test.js`
Expected: PASS, 7/7

- [ ] **Step 5: Commit**

```bash
git add PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/format-reader.js \
        PaintomicsClient/tests/inputformat/format-reader.test.js
git commit -m "feat(inputformat): add delimited file reader matching the server contract"
```

---

### Task 2: Values-file validator

**Files:**
- Create: `.../InputFormat/format-validator.js`
- Test: `PaintomicsClient/tests/inputformat/format-validator.test.js`

**Interfaces:**
- Consumes: `rows` from `readDelimited`.
- Produces: `validateValues(rows) -> {ok, problems, summary}`.
  `problems` is `[{code, line, detail}]` with `code` in
  `EMPTY | TOO_FEW_COLUMNS | RAGGED | NON_NUMERIC | DECIMAL_COMMA | TOO_MANY_FEATURES | NO_FEATURE_LINES`.
  `summary` is `{nRows, nCols, hasHeader, columnNames, idSample, numericColumns, textColumns}`
  where `numericColumns`/`textColumns` are arrays of 0-based column indices.
- Also produces `isPythonFloat(s) -> boolean`.

- [ ] **Step 1: Write the failing test**

```js
// PaintomicsClient/tests/inputformat/format-validator.test.js
const test = require("node:test");
const assert = require("node:assert");
const { validateValues, isPythonFloat } =
  require("../../public_html/app/view/PathwayAcquisitionViews/InputFormat/format-validator.js");

test("isPythonFloat matches Python float() and never treats '' as 0", () => {
  for (const s of ["1", "-1.5", "+2", ".5", "1e5", "1E-5", " 3 ", "inf", "NaN"])
    assert.ok(isPythonFloat(s), `${JSON.stringify(s)} should parse`);
  for (const s of ["", "  ", "abc", "1,5", "1.2.3", "category_default", "-"])
    assert.ok(!isPythonFloat(s), `${JSON.stringify(s)} should not parse`);
});

test("accepts a well-formed values matrix with a header", () => {
  const rows = [["#geneID", "T00h", "T02h"], ["G1", "0.77", "-0.49"], ["G2", "1", "2"]];
  const r = validateValues(rows);
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.summary.hasHeader, true);
  assert.strictEqual(r.summary.nRows, 2);
  assert.strictEqual(r.summary.nCols, 3);
});

test("treats line 0 as data when column two is numeric, matching the server", () => {
  const rows = [["G1", "1", "2"], ["G2", "3", "4"]];
  assert.strictEqual(validateValues(rows).summary.hasHeader, false);
});

test("flags a text column on every row (the interleaved-annotation case)", () => {
  const rows = [
    ["Gene", "Gene_Valence", "Valence_Source", "SCI_vs_H_10d"],
    ["Aste1", "1", "category_default", "0.531"],
    ["Ackr1", "1", "category_default", "0.022"],
  ];
  const r = validateValues(rows);
  assert.strictEqual(r.ok, false);
  assert.ok(r.problems.some((p) => p.code === "NON_NUMERIC"));
  assert.deepStrictEqual(r.summary.textColumns, [2]);
  assert.deepStrictEqual(r.summary.numericColumns, [1, 3]);
});

test("flags a banner row whose trailing cells are blank", () => {
  const rows = [
    ["Gene", "Gene_Valence", "SCI_vs_H_10d"],
    ["✓ GENI VALIDATI (138)", "", ""],
    ["Aste1", "1", "0.531"],
  ];
  const r = validateValues(rows);
  assert.ok(r.problems.some((p) => p.code === "NON_NUMERIC" && p.line === 1));
});

test("reports the decimal-comma hint the server would report", () => {
  const rows = [["Gene", "A", "B"], ["G1", "0,77", "1,20"]];
  const r = validateValues(rows);
  assert.ok(r.problems.some((p) => p.code === "DECIMAL_COMMA"));
});

test("flags ragged rows against the first data line", () => {
  const rows = [["Gene", "A", "B"], ["G1", "1", "2"], ["G2", "3"]];
  const r = validateValues(rows);
  assert.ok(r.problems.some((p) => p.code === "RAGGED" && p.line === 2));
});

test("rejects a single-column file", () => {
  const r = validateValues([["Gene"], ["G1"]]);
  assert.ok(r.problems.some((p) => p.code === "TOO_FEW_COLUMNS"));
});

test("rejects a header with no feature lines", () => {
  const r = validateValues([["#geneID", "T00h"]]);
  assert.ok(r.problems.some((p) => p.code === "NO_FEATURE_LINES"));
});

test("stops collecting after ten bad lines, like the server", () => {
  const rows = [["Gene", "A"]];
  for (let i = 0; i < 50; i++) rows.push(["G" + i, "bad"]);
  assert.ok(validateValues(rows).problems.length <= 11);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test PaintomicsClient/tests/inputformat/format-validator.test.js`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal implementation**

```js
// format-validator.js
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MAX_NUMBER_FEATURES = 1000000;
  var NUM = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;
  var SPECIAL = /^[+-]?(inf(inity)?|nan)$/i;

  // Python's float(): strips surrounding whitespace, accepts inf/nan, and
  // rejects "". JS Number("") is 0, so Number() must never be used here.
  function isPythonFloat(s) {
    if (typeof s !== "string") return false;
    var t = s.trim();
    if (!t) return false;
    return NUM.test(t) || SPECIAL.test(t);
  }

  function validateValues(rows) {
    var problems = [];
    var summary = { nRows: 0, nCols: 0, hasHeader: false, columnNames: [],
                    idSample: [], numericColumns: [], textColumns: [] };
    if (!rows || !rows.length) {
      problems.push({ code: "EMPTY", line: 0, detail: "The file is empty." });
      return { ok: false, problems: problems, summary: summary };
    }

    var nConditions = -1, nLine = -1, dataLines = 0;
    var erroneous = new Map();

    for (var i = 0; i < rows.length; i++) {
      var line = rows[i];
      nLine++;

      // Server: line 0 is a header ONLY if float(line[1]) raises. A one-column
      // line raises IndexError, which the bare except also swallows.
      if (nLine === 0 && (line.length < 2 || !isPythonFloat(line[1]))) {
        summary.hasHeader = true;
        summary.columnNames = line.slice();
        continue;
      }

      if (nConditions === -1) {
        if (line.length < 2) {
          erroneous.set(nLine, "Expected at least 2 columns, but found one.");
          problems.push({ code: "TOO_FEW_COLUMNS", line: nLine,
                          detail: "Expected at least 2 columns, but found one." });
          break;
        }
        nConditions = line.length;
      }

      if (nLine > MAX_NUMBER_FEATURES) {
        problems.push({ code: "TOO_MANY_FEATURES", line: nLine,
                        detail: "The file exceeds " + MAX_NUMBER_FEATURES + " features." });
        break;
      }

      if (nConditions !== line.length && line.length > 0) {
        erroneous.set(nLine, "Expected " + nConditions + " columns but found " + line.length + ";");
        problems.push({ code: "RAGGED", line: nLine, detail: erroneous.get(nLine) });
      }

      dataLines++;
      if (summary.idSample.length < 5) summary.idSample.push(line[0]);

      var rest = line.slice(1);
      if (!rest.every(isPythonFloat)) {
        var joined = rest.join(" ");
        var comma = joined.indexOf(",") > -1;
        problems.push({
          code: comma ? "DECIMAL_COMMA" : "NON_NUMERIC",
          line: nLine,
          detail: comma
            ? "Perhaps you are using commas instead of dots as decimal mark?"
            : "Line contains invalid values or symbols.",
        });
        erroneous.set(nLine, problems[problems.length - 1].detail);
      }
      if (erroneous.size > 9) break;
    }

    // Per-column classification drives Layer 2's "which columns are values?"
    // question, so it is computed over data lines only.
    var width = nConditions > 0 ? nConditions : (rows[0] ? rows[0].length : 0);
    var start = summary.hasHeader ? 1 : 0;
    for (var c = 1; c < width; c++) {
      var allNumeric = true, seen = 0;
      for (var r = start; r < rows.length && seen < 200; r++) {
        if (!rows[r] || rows[r].length <= c) continue;
        seen++;
        if (!isPythonFloat(rows[r][c])) { allNumeric = false; break; }
      }
      (allNumeric && seen > 0 ? summary.numericColumns : summary.textColumns).push(c);
    }

    if (dataLines === 0 && !problems.some(function (p) { return p.code === "TOO_FEW_COLUMNS"; })) {
      problems.push({ code: "NO_FEATURE_LINES", line: 0,
                      detail: "The file does not seem to have any feature lines." });
    }

    summary.nRows = dataLines;
    summary.nCols = width;
    return { ok: problems.length === 0, problems: problems, summary: summary };
  }

  return { validateValues: validateValues, isPythonFloat: isPythonFloat,
           MAX_NUMBER_FEATURES: MAX_NUMBER_FEATURES };
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test PaintomicsClient/tests/inputformat/format-validator.test.js`
Expected: PASS, 10/10

- [ ] **Step 5: Cross-check the validator against the server on real files**

Write `PaintomicsServer/src/tests/test_validator_agrees_with_server.py`: for each
file in `src/examplefiles/datasets/*/data/*.tab`, run the server's own validation
path and the JS validator (via `node -e`), and assert both agree on ok/not-ok.
This is the test that keeps the two implementations from drifting.

```python
import glob, json, os, subprocess, unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
JS = os.path.join(REPO, "PaintomicsClient/public_html/app/view/"
                        "PathwayAcquisitionViews/InputFormat")

def js_ok(path):
    script = (
        "const {readDelimited}=require(%r);"
        "const {validateValues}=require(%r);"
        "const fs=require('fs');"
        "const r=readDelimited(new Uint8Array(fs.readFileSync(process.argv[1])));"
        "process.stdout.write(JSON.stringify("
        "  r.decodeError?false:validateValues(r.rows).ok));"
        % (os.path.join(JS, "format-reader.js"), os.path.join(JS, "format-validator.js"))
    )
    out = subprocess.run(["node", "-e", script, path], capture_output=True, text=True)
    return json.loads(out.stdout)

class ValidatorAgreesWithServer(unittest.TestCase):
    def test_every_example_values_file_validates(self):
        files = glob.glob(os.path.join(
            REPO, "PaintomicsServer/src/examplefiles/datasets/*/data/*values*.tab"))
        self.assertTrue(files, "no example values files found")
        for path in files:
            with self.subTest(path=os.path.basename(path)):
                self.assertTrue(js_ok(path), "%s should validate" % path)

if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Run: `/Users/tianyuan/miniforge3/envs/paintomics4/bin/python PaintomicsServer/src/tests/test_validator_agrees_with_server.py`
Expected: PASS — every shipped example validates clean.

- [ ] **Step 6: Commit**

```bash
git add PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/format-validator.js \
        PaintomicsClient/tests/inputformat/format-validator.test.js \
        PaintomicsServer/src/tests/test_validator_agrees_with_server.py
git commit -m "feat(inputformat): validate values files against the server contract"
```

---

### Task 3: Deterministic repairs

**Files:**
- Create: `.../InputFormat/format-repair.js`
- Test: `PaintomicsClient/tests/inputformat/format-repair.test.js`

**Interfaces:**
- Consumes: `rows`, `delimiter` from `readDelimited`; `problems` from `validateValues`.
- Produces: `proposeRepairs(rows, delimiter, problems) -> [{id, label, apply(rows) -> rows, describe() -> string}]`
  and `applyRepairs(rows, repairs) -> {rows, changes}` where `changes` is
  `[{line, before, after}]` capped at 20 entries for the diff.
- Repair ids: `DECIMAL_COMMA` (tab-delimited only), `TRIM_TRAILING_EMPTY`,
  `DROP_BLANK_LINES`, `DROP_BANNER_ROW`.

- [ ] **Step 1: Write the failing test**

```js
const test = require("node:test");
const assert = require("node:assert");
const { proposeRepairs, applyRepairs } =
  require("../../public_html/app/view/PathwayAcquisitionViews/InputFormat/format-repair.js");
const { validateValues } =
  require("../../public_html/app/view/PathwayAcquisitionViews/InputFormat/format-validator.js");

function repair(rows, delimiter) {
  const problems = validateValues(rows).problems;
  return applyRepairs(rows, proposeRepairs(rows, delimiter, problems));
}

test("converts decimal commas to dots in tab-delimited files", () => {
  const rows = [["Gene", "A", "B"], ["G1", "0,77", "1,20"]];
  const out = repair(rows, "\t");
  assert.deepStrictEqual(out.rows[1], ["G1", "0.77", "1.20"]);
  assert.strictEqual(validateValues(out.rows).ok, true);
});

test("never offers a decimal-comma repair for comma-delimited files", () => {
  const rows = [["Gene", "A"], ["G1", "0,77"]];
  const ids = proposeRepairs(rows, ",", validateValues(rows).problems).map((r) => r.id);
  assert.ok(!ids.includes("DECIMAL_COMMA"));
});

test("trims trailing empty columns from an Excel CSV export", () => {
  const rows = [["Gene", "A", "", ""], ["G1", "1", "", ""]];
  const out = repair(rows, ",");
  assert.deepStrictEqual(out.rows[1], ["G1", "1"]);
});

test("drops fully blank lines in the middle of a file", () => {
  const rows = [["Gene", "A"], ["G1", "1"], [""], ["G2", "2"]];
  const out = repair(rows, "\t");
  assert.strictEqual(out.rows.length, 3);
});

test("drops a banner row whose cells after the first are all blank", () => {
  const rows = [["Gene", "A"], ["✓ GENI VALIDATI (138)", ""], ["G1", "1"]];
  const out = repair(rows, "\t");
  assert.deepStrictEqual(out.rows[1], ["G1", "1"]);
  assert.strictEqual(validateValues(out.rows).ok, true);
});

test("records a bounded change list for the diff", () => {
  const rows = [["Gene", "A"]];
  for (let i = 0; i < 100; i++) rows.push(["G" + i, "0,5"]);
  const out = repair(rows, "\t");
  assert.ok(out.changes.length <= 20);
});

test("leaves an already-valid file untouched", () => {
  const rows = [["#geneID", "T00h"], ["G1", "0.77"]];
  const out = repair(rows, "\t");
  assert.deepStrictEqual(out.rows, rows);
  assert.strictEqual(out.changes.length, 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test PaintomicsClient/tests/inputformat/format-repair.test.js`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal implementation**

```js
// format-repair.js
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var V = (typeof module === "object" && module.exports)
    ? require("./format-validator.js")
    : (typeof self !== "undefined" ? self.PaintomicsInputFormat : this.PaintomicsInputFormat);

  var DECIMAL_COMMA = /^[+-]?\d+,\d+$/;

  function isBlankRow(row) {
    return row.every(function (c) { return String(c).trim() === ""; });
  }

  // A banner row carries content in column 0 and nothing anywhere else --
  // Excel's merged title cell. Distinct from a blank row, and distinct from a
  // real feature, which must have a numeric column 1.
  function isBannerRow(row) {
    return row.length > 1 && String(row[0]).trim() !== "" &&
           row.slice(1).every(function (c) { return String(c).trim() === ""; });
  }

  function proposeRepairs(rows, delimiter, problems) {
    var repairs = [];
    var codes = new Set((problems || []).map(function (p) { return p.code; }));

    // Only safe when the delimiter is a tab: in a comma-delimited file the
    // decimal comma has already been consumed as a field separator, so the
    // original values are unrecoverable and a "repair" would invent data.
    if (delimiter === "\t" && codes.has("DECIMAL_COMMA")) {
      repairs.push({
        id: "DECIMAL_COMMA",
        label: "Use dots as the decimal mark",
        describe: function () { return "Replaces 0,77 with 0.77 in numeric cells."; },
        apply: function (rs) {
          return rs.map(function (row, i) {
            if (i === 0) return row;
            return row.map(function (cell, c) {
              return c > 0 && DECIMAL_COMMA.test(String(cell).trim())
                ? String(cell).trim().replace(",", ".") : cell;
            });
          });
        },
      });
    }

    var width = rows.length ? Math.max.apply(null, rows.map(function (r) { return r.length; })) : 0;
    var trailingEmpty = width > 1 && rows.every(function (r) {
      return r.length < width || String(r[width - 1]).trim() === "";
    });
    if (trailingEmpty) {
      repairs.push({
        id: "TRIM_TRAILING_EMPTY",
        label: "Remove empty trailing columns",
        describe: function () { return "Drops columns that are blank on every row."; },
        apply: function (rs) {
          var keep = rs[0].length;
          while (keep > 1 && rs.every(function (r) {
            return r.length < keep || String(r[keep - 1]).trim() === "";
          })) keep--;
          return rs.map(function (r) { return r.slice(0, keep); });
        },
      });
    }

    if (rows.some(isBlankRow)) {
      repairs.push({
        id: "DROP_BLANK_LINES",
        label: "Remove blank lines",
        describe: function () { return "Drops rows that are empty in every column."; },
        apply: function (rs) { return rs.filter(function (r) { return !isBlankRow(r); }); },
      });
    }

    if (rows.some(function (r, i) { return i > 0 && isBannerRow(r); })) {
      repairs.push({
        id: "DROP_BANNER_ROW",
        label: "Remove title rows",
        describe: function () {
          return "Drops rows with a title in the first column and nothing else.";
        },
        apply: function (rs) {
          return rs.filter(function (r, i) { return i === 0 || !isBannerRow(r); });
        },
      });
    }
    return repairs;
  }

  function applyRepairs(rows, repairs) {
    var before = rows.map(function (r) { return r.join("\t"); });
    var out = rows;
    for (var i = 0; i < repairs.length; i++) out = repairs[i].apply(out);
    var changes = [];
    for (var j = 0; j < before.length && changes.length < 20; j++) {
      var after = out[j] ? out[j].join("\t") : null;
      if (after !== before[j]) changes.push({ line: j, before: before[j], after: after });
    }
    return { rows: out, changes: changes };
  }

  return { proposeRepairs: proposeRepairs, applyRepairs: applyRepairs,
           isBannerRow: isBannerRow, isBlankRow: isBlankRow };
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test PaintomicsClient/tests/inputformat/format-repair.test.js`
Expected: PASS, 7/7

- [ ] **Step 5: Commit**

```bash
git add PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/format-repair.js \
        PaintomicsClient/tests/inputformat/format-repair.test.js
git commit -m "feat(inputformat): add deterministic repairs for mechanical format faults"
```

---

### Task 4: Layer 0/1 status strip in Step 1

**Files:**
- Create: `.../InputFormat/format-panel.js`
- Create: `PaintomicsClient/public_html/resources/css/inputformat.css`
- Modify: `PaintomicsClient/public_html/index.html` (script + css tags, `?v=` bump)
- Modify: `PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step1Views.js` (one hook)

**Interfaces:**
- Consumes: `readDelimited`, `validateValues`, `proposeRepairs`, `applyRepairs`.
- Produces: `PaintomicsInputFormat.attachPanel(fileInputEl, {onRepaired(blob, name), onNeedsAgent(profile)})`.

- [ ] **Step 1: Find the file-selection hook in Step 1**

Run: `grep -n "filefield\|change.*file\|inputDataFile" PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step1Views.js | head -30`
Record the exact handler and element id. The Step 1 edit must be **one call** to
`attachPanel` from that handler and nothing else — this file is 224 KB and on
every job's path.

- [ ] **Step 2: Write `format-panel.js`**

Plain DOM (no `Ext.create`, no `xtype:` — follow `PA_AIInterpretView.js`).
Renders one status strip below the file row with three states:

```js
// states, in order of escalation
// ok       -> "✓ 14,203 rows · 6 numeric columns · IDs look like: Plaa, Cldn10"
// repair   -> problem text + [Fix automatically] [show what changes] buttons
// agent    -> problem text + [Convert with AI] [I'll do it myself]
```

`Fix automatically` calls `applyRepairs`, re-runs `validateValues`, and on `ok`
serialises rows back to a tab-delimited `Blob` and calls `onRepaired(blob, name)`.
`show what changes` toggles a `<table>` of the `changes` list.
`Convert with AI` calls `onNeedsAgent(profile)` — a no-op stub until Task 8.
A binary file (any decode error, or an `xlsx` extension) goes straight to `agent`
state with the message "Excel workbooks need conversion — PaintOmics reads text
tables." Excel is not supported today, so this is new capability, not a regression.

- [ ] **Step 3: Verify in Chrome (mandatory, CLAUDE.md §5)**

Restart the server, bump `?v=` in `index.html`, then with the browser tools:
1. Open Step 1, select `src/examplefiles/datasets/02-gene-multi-condition/data/gene_expression_values.tab`.
   Expect the **ok** strip and no other change to the form.
2. Build a broken copy in the scratchpad: `sed 's/\./,/g'` over the same file.
   Expect the **repair** strip; click Fix; expect it to flip to **ok**.
3. Select `Caudal SCI_bPAC_FINAL.xlsx`. Expect the **agent** strip.
4. Screenshot all three. Confirm via `read_console_messages` that no error fired.

- [ ] **Step 4: Run the alignment guides (CLAUDE.md §6)**

Open Step 1 with `?guides=1`, screenshot, fix every off-rail element the HUD
lists, repeat until it shows 0 off-rail.

- [ ] **Step 5: Commit**

```bash
git add PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/format-panel.js \
        PaintomicsClient/public_html/resources/css/inputformat.css \
        PaintomicsClient/public_html/index.html \
        PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step1Views.js
git commit -m "feat(inputformat): check every upload and offer one-click repairs"
```

**Phase 1 ends here and is shippable on its own.**

---

### Task 5: Pyodide sandbox

**Files:**
- Create: `PaintomicsClient/public_html/inputformat-sandbox.html`
- Create: `.../InputFormat/sandbox-host.js`
- Test: `PaintomicsClient/tests/inputformat/sandbox-host.test.js` (message protocol only — Pyodide itself is verified in Chrome)

**Interfaces:**
- Produces: `createSandbox() -> {ready: Promise, run(code, files) -> Promise<{ok, stdout, traceback, outputs}>, destroy()}`.
  `files` is `{name: Uint8Array}` written into the sandbox FS; `outputs` is
  `{name: Uint8Array}` read back from `/out`.

- [ ] **Step 1: Write the sandbox document**

```html
<!-- inputformat-sandbox.html -->
<!doctype html><meta charset="utf-8"><title>sandbox</title>
<script src="resources/pyodide/pyodide.js"></script>
<script>
// This document is loaded into an iframe with sandbox="allow-scripts" and
// WITHOUT allow-same-origin, so it has an opaque origin: no cookies, no
// localStorage, no parent DOM. It must never be given a network capability.
let pyodide = null;
addEventListener("message", async (e) => {
  const { id, type, code, files } = e.data || {};
  try {
    if (type === "init") {
      pyodide = await loadPyodide({ indexURL: "resources/pyodide/" });
      await pyodide.loadPackage(["pandas", "openpyxl"]);
      parent.postMessage({ id, ok: true }, "*");
      return;
    }
    if (type === "run") {
      pyodide.FS.mkdir("/work"); pyodide.FS.mkdir("/out");
      for (const [name, bytes] of Object.entries(files || {}))
        pyodide.FS.writeFile("/work/" + name, bytes);
      let stdout = "";
      pyodide.setStdout({ batched: (s) => { stdout += s + "\n"; } });
      await pyodide.runPythonAsync(code);
      const outputs = {};
      for (const name of pyodide.FS.readdir("/out"))
        if (name !== "." && name !== "..")
          outputs[name] = pyodide.FS.readFile("/out/" + name);
      parent.postMessage({ id, ok: true, stdout, outputs }, "*");
    }
  } catch (err) {
    parent.postMessage({ id, ok: false, traceback: String(err && err.message || err) }, "*");
  }
});
parent.postMessage({ type: "loaded" }, "*");
</script>
```

- [ ] **Step 2: Vendor Pyodide**

Download the Pyodide release into `PaintomicsClient/public_html/resources/pyodide/`
(pyodide.js, pyodide.asm.wasm, python stdlib, and the pandas/openpyxl wheels only —
not the full distribution). Add the directory to `.gitignore` **only if** the repo
already excludes vendored bundles; otherwise commit it. Verify the total is under
30 MB and that the page never requests it until the drawer opens.

- [ ] **Step 3: Write `sandbox-host.js`** — creates the iframe with
`sandbox="allow-scripts"` (never `allow-same-origin`), correlates request ids to
promises, enforces a 60 s per-run timeout, and `destroy()` removes the iframe so
every conversion starts from a clean interpreter.

- [ ] **Step 4: Verify isolation in Chrome (mandatory)**

Open the drawer, and from the sandbox run each of these, asserting all four fail:
```python
import js; js.document.cookie          # opaque origin -> no cookie access
import js; js.parent.location.href     # cross-origin -> SecurityError
from pyodide.http import pyfetch; await pyfetch("/")   # no network
open("/etc/passwd")                    # no host FS
```
Capture the failures with `read_console_messages`. **Do not use `alert`.**

- [ ] **Step 5: Commit**

```bash
git add PaintomicsClient/public_html/inputformat-sandbox.html \
        PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/sandbox-host.js \
        PaintomicsClient/tests/inputformat/sandbox-host.test.js
git commit -m "feat(inputformat): add an opaque-origin Pyodide sandbox"
```

---

### Task 6: Server route — queued, stateless LLM proxy

**Files:**
- Create: `PaintomicsServer/src/servlets/InputConvertServlet.py`
- Create: `PaintomicsServer/src/classes/InputConvert/prompts.py`
- Modify: `PaintomicsServer/src/paintomicsserver.py` (two routes)
- Test: `PaintomicsServer/src/tests/test_input_convert_route.py`

**Interfaces:**
- Produces: `POST /input_convert/turn` → `{ticket}`; `GET /input_convert/turn/<ticket>` →
  `{state: "running"|"done"|"error", action?}` where `action` is
  `{"type": "code", "python": str}` or
  `{"type": "question", "text": str, "options": [str], "field": str}` or
  `{"type": "done", "note": str}`.

- [ ] **Step 1: Write the failing test**

```python
import unittest
class InputConvertRoute(unittest.TestCase):
    def test_rejects_without_a_valid_session(self): ...
    def test_rejects_when_the_flag_is_unset(self): ...
    def test_enqueues_and_returns_a_ticket_without_calling_the_llm(self): ...
    def test_refuses_a_third_concurrent_conversion(self): ...
    def test_rejects_a_payload_containing_raw_value_rows(self): ...
if __name__ == "__main__":
    unittest.main(verbosity=2)
```

The last test is the privacy guard: the request body schema permits column
names, dtypes, counts, summary statistics, ID samples, tracebacks and validator
output — and nothing else. Reject anything carrying a `rows` key.

- [ ] **Step 2: Run to verify it fails**

Run: `/Users/tianyuan/miniforge3/envs/paintomics4/bin/python PaintomicsServer/src/tests/test_input_convert_route.py`
Expected: FAIL — servlet does not exist

- [ ] **Step 3: Implement the servlet**

Model it on `aiInterpretInitiate` (`AIInterpretServlet.py:136`): validate the
session, check `AI_INPUT_CONVERTER`, check the ownership of the referenced job,
enforce a module-level semaphore of 2, `QUEUE_INSTANCE.enqueue(...)` the LLM
call, and return the ticket. The LLM call itself goes through
`AIInterpret/llm_client.py` so the token bucket and retry logic are shared.
**No inline LLM call in the request path** — `threads = 4`.

- [ ] **Step 4: Run to verify it passes**

Run: `/Users/tianyuan/miniforge3/envs/paintomics4/bin/python PaintomicsServer/src/tests/test_input_convert_route.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add PaintomicsServer/src/servlets/InputConvertServlet.py \
        PaintomicsServer/src/classes/InputConvert/prompts.py \
        PaintomicsServer/src/paintomicsserver.py \
        PaintomicsServer/src/tests/test_input_convert_route.py
git commit -m "feat(inputformat): add a queued, stateless conversion proxy"
```

---

### Task 7: Agent loop

**Files:**
- Create: `.../InputFormat/convert-agent.js`
- Test: `PaintomicsClient/tests/inputformat/convert-agent.test.js`

**Interfaces:**
- Produces: `runAgent({profile, transport, sandbox, validate, ask, onEvent, maxAttempts=5}) -> Promise<{ok, outputs, history}>`.
  `transport(state) -> Promise<action>` is injected so tests can drive the loop
  with a scripted server and no network.

- [ ] **Step 1: Write the failing test**

```js
test("stops as soon as the validator passes", async () => { /* scripted transport returns one good code action */ });
test("feeds the traceback back and retries", async () => { /* first run throws, second succeeds; assert transport saw the traceback */ });
test("gives up after maxAttempts and returns the best partial result", async () => {});
test("pauses for a question and resumes with the answer in state", async () => {});
test("never sends raw rows to the transport", async () => { /* assert every payload lacks a `rows` key */ });
test("grades with the injected validator, not the model's claim", async () => { /* model says done, validator says no -> keeps going */ });
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test PaintomicsClient/tests/inputformat/convert-agent.test.js`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the loop** — the state machine from the spec, with the
validator's verdict as the only exit condition and a hard `maxAttempts`.

- [ ] **Step 4: Run to verify it passes**

Run: `node --test PaintomicsClient/tests/inputformat/convert-agent.test.js`
Expected: PASS, 6/6

- [ ] **Step 5: Commit**

```bash
git add PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/convert-agent.js \
        PaintomicsClient/tests/inputformat/convert-agent.test.js
git commit -m "feat(inputformat): add the conversion agent loop"
```

---

### Task 8: Converter drawer

**Files:**
- Create: `.../InputFormat/convert-drawer.js`
- Modify: `.../InputFormat/format-panel.js` (replace the `onNeedsAgent` stub)
- Modify: `PaintomicsClient/public_html/index.html` (`?v=` bump)

**Interfaces:**
- Consumes: `createSandbox`, `runAgent`, `validateValues`.
- Produces: `openDrawer(file, {species, omicType, jobId}) -> Promise<{accepted, files}>`.

- [ ] **Step 1: Build the drawer** — overlays Step 1 without unmounting it;
lazy-loads Pyodide on open with its own progress readout; renders the live
transcript, elapsed seconds and a Cancel that actually aborts the poll; the
generated code behind a `▸ show code` toggle; question cards; and the review
screen (source vs converted preview plus the validator checklist).

- [ ] **Step 2: Wire Accept** — POST the converted files to the existing upload
endpoint so they land in `CLIENT_TMP_DIR` through `registerFile`, then select
them in the omic panel. Downloads then work through `dataManagementDownloadFile`
with no new code.

- [ ] **Step 3: Verify in Chrome (mandatory)** — restart, bump `?v=`, run a full
conversion of `Caudal SCI_bPAC_FINAL.xlsx`, screenshot the transcript, a question
card, and the review screen. Confirm with `read_network_requests` that no request
carries expression values, and that Pyodide is fetched only after the drawer opens.

- [ ] **Step 4: Commit**

```bash
git add PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/convert-drawer.js \
        PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat/format-panel.js \
        PaintomicsClient/public_html/index.html
git commit -m "feat(inputformat): add the AI conversion drawer"
```

---

### Task 9: Acceptance on the SCI bPAC workbooks

**Files:**
- Create: `PaintomicsServer/src/tests/test_sci_bpac_workbook_conversion.py`

- [ ] **Step 1: Pin the expected conversion**

For `Caudal SCI_bPAC_FINAL.xlsx` sheet `Dorsal GM`, the correct values matrix is:
column 0 = `Gene`; columns = the six comparisons `SCI_vs_H_10d`, `SCI_vs_H_30d`,
`bPAC_vs_SCI_10d`, `bPAC_vs_SCI_30d`, `bPAC_vs_H_10d`, `bPAC_vs_H_30d`. Every
other column is annotation and must be dropped. The `✓ GENI VALIDATI (138)`
banner row must be gone. Expected: 138 feature rows, 7 columns, validator `ok`.

- [ ] **Step 2: Write the test** — run the conversion headlessly by driving
`convert-agent.js` under `node --test` with a recorded transport (capture one
real LLM session and replay it), then assert the output passes `validateValues`
and has the shape above. Recording keeps the test deterministic and free.

- [ ] **Step 3: Verify the two science guards fire**

Assert the agent raises a question for each, and that neither is silently
resolved:
1. `Geni_Flaggati` holds genes marked `FALSO POSITIVO`; concatenating all sheets
   imports known false positives.
2. The workbook is already filtered to ~400 genes, so pathway enrichment against
   a whole-genome background yields optimistic p-values. Compare
   `simulated-example-significance-calibration`.

- [ ] **Step 4: End-to-end in Chrome (mandatory)** — convert `Dorsal GM`, accept,
submit the Step 1 job for mouse, and confirm it reaches Step 3 with a non-zero
matched-feature count. Screenshot the result. Repeat for the Rostral workbook,
which has the drifted schema (`PriorityScore_v12`, no `S_*` columns).

- [ ] **Step 5: Commit**

```bash
git add PaintomicsServer/src/tests/test_sci_bpac_workbook_conversion.py
git commit -m "test(inputformat): pin conversion of the SCI bPAC workbooks"
```
