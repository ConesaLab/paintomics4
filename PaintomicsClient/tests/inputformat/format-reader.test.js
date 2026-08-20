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

test("handles CRLF line endings", () => {
  const r = readDelimited(bytes("a\tb\r\n1\t2\r\n"));
  assert.deepStrictEqual(r.rows[1], ["1", "2"]);
});
