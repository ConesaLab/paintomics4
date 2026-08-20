const test = require("node:test");
const assert = require("node:assert");
const D = "../../public_html/app/view/PathwayAcquisitionViews/InputFormat/";
const { proposeRepairs, applyRepairs } = require(D + "format-repair.js");
const { validateValues } = require(D + "format-validator.js");

function repair(rows, delimiter) {
  const problems = validateValues(rows).problems;
  return applyRepairs(rows, proposeRepairs(rows, delimiter, problems));
}

test("converts decimal commas to dots in tab-delimited files", () => {
  const rows = [["Gene", "A", "B"], ["G1", "0,77", "1,20"], ["G2", "1,5", "2,5"]];
  const out = repair(rows, "\t");
  assert.deepStrictEqual(out.rows[1], ["G1", "0.77", "1.20"]);
  assert.strictEqual(validateValues(out.rows).ok, true);
});

test("never offers a decimal-comma repair for comma-delimited files", () => {
  // The decimal comma has already been eaten as a field separator, so the
  // original numbers are unrecoverable; a "repair" here would invent data.
  const rows = [["Gene", "A"], ["G1", "0,77"]];
  const ids = proposeRepairs(rows, ",", validateValues(rows).problems).map((r) => r.id);
  assert.ok(!ids.includes("DECIMAL_COMMA"));
});

test("trims trailing empty columns from an Excel CSV export", () => {
  const rows = [["Gene", "A", "", ""], ["G1", "1", "", ""], ["G2", "2", "", ""]];
  const out = repair(rows, ",");
  assert.deepStrictEqual(out.rows[1], ["G1", "1"]);
  assert.strictEqual(validateValues(out.rows).ok, true);
});

test("drops fully blank lines in the middle of a file", () => {
  const rows = [["Gene", "A"], ["G1", "1"], [""], ["G2", "2"]];
  const out = repair(rows, "\t");
  assert.strictEqual(out.rows.length, 3);
  assert.strictEqual(validateValues(out.rows).ok, true);
});

test("drops a banner row whose cells after the first are all blank", () => {
  const rows = [["Gene", "A"], ["✓ GENI VALIDATI (138)", ""], ["G1", "1"], ["G2", "2"]];
  const out = repair(rows, "\t");
  assert.deepStrictEqual(out.rows[1], ["G1", "1"]);
  assert.strictEqual(validateValues(out.rows).ok, true);
});

test("never drops the header row even though it has no numbers", () => {
  const rows = [["Gene", "A"], ["G1", "1"]];
  const out = repair(rows, "\t");
  assert.deepStrictEqual(out.rows[0], ["Gene", "A"]);
});

test("records a bounded change list for the diff", () => {
  const rows = [["Gene", "A"]];
  for (let i = 0; i < 100; i++) rows.push(["G" + i, "0,5"]);
  const out = repair(rows, "\t");
  assert.ok(out.changes.length <= 20, "changes should be capped for the diff");
  assert.ok(out.changes.length > 0);
  assert.ok(out.changes[0].before.includes("0,5"));
  assert.ok(out.changes[0].after.includes("0.5"));
});

test("leaves an already-valid file untouched", () => {
  const rows = [["#geneID", "T00h"], ["G1", "0.77"], ["G2", "1.5"]];
  const out = repair(rows, "\t");
  assert.deepStrictEqual(out.rows, rows);
  assert.strictEqual(out.changes.length, 0);
});

test("proposes nothing for an already-valid file", () => {
  const rows = [["#geneID", "T00h"], ["G1", "0.77"]];
  assert.deepStrictEqual(proposeRepairs(rows, "\t", validateValues(rows).problems), []);
});

test("combines repairs when a file has several faults at once", () => {
  const rows = [["Gene", "A", ""], ["TITLE", "", ""], ["G1", "0,5", ""], [""], ["G2", "1,5", ""]];
  const out = repair(rows, "\t");
  assert.strictEqual(validateValues(out.rows).ok, true);
  assert.deepStrictEqual(out.rows[0], ["Gene", "A"]);
});
