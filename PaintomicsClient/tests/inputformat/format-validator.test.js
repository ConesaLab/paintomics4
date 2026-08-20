const test = require("node:test");
const assert = require("node:assert");
const { validateValues, isPythonFloat } =
  require("../../public_html/app/view/PathwayAcquisitionViews/InputFormat/format-validator.js");

test("isPythonFloat matches Python float() and never treats '' as 0", () => {
  for (const s of ["1", "-1.5", "+2", ".5", "1e5", "1E-5", " 3 ", "inf", "NaN", "5."])
    assert.ok(isPythonFloat(s), `${JSON.stringify(s)} should parse`);
  for (const s of ["", "  ", "abc", "1,5", "1.2.3", "category_default", "-", "additive"])
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

test("reports an empty file rather than throwing", () => {
  assert.strictEqual(validateValues([]).ok, false);
  assert.ok(validateValues([]).problems.some((p) => p.code === "EMPTY"));
});

test("collects an ID sample for the summary line", () => {
  const rows = [["Gene", "A"], ["Plaa", "1"], ["Cldn10", "2"]];
  assert.deepStrictEqual(validateValues(rows).summary.idSample, ["Plaa", "Cldn10"]);
});

test("one banner row does not mark every column as text", () => {
  // Regression: the first real workbook tested had a merged title row under
  // the header. Its blank cells made all-cells-must-be-numeric classify every
  // measurement column as annotation, which is the opposite of useful.
  const rows = [["Gene", "Gene_Valence", "Valence_Source", "SCI_vs_H_10d"],
                ["✓ GENI VALIDATI (138)", "", "", ""]];
  for (let i = 0; i < 40; i++) rows.push(["G" + i, "1", "category_default", "0.5"]);
  const summary = validateValues(rows).summary;
  assert.deepStrictEqual(summary.numericColumns, [1, 3]);
  assert.deepStrictEqual(summary.textColumns, [2]);
});

test("a column of mostly text is still text even with a few numbers", () => {
  const rows = [["Gene", "A"]];
  for (let i = 0; i < 40; i++) rows.push(["G" + i, i < 4 ? "1.5" : "additive"]);
  assert.deepStrictEqual(validateValues(rows).summary.textColumns, [1]);
});
