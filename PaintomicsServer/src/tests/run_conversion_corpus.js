/*
 * Runs the whole broken-file corpus through the real conversion agent and
 * checks both halves of "correct": the FORMAT the server will accept, and the
 * INFORMATION the original file carried.
 *
 * Format alone is not enough. A script that drops half the rows, transposes a
 * matrix the wrong way round, swaps two conditions or coerces values to NaN
 * still emits a file the validator happily accepts. Every case here was built
 * by corrupting a file that already ships as a working example, so the original
 * is available as ground truth and the conversion is compared against it.
 *
 *   node PaintomicsServer/src/tests/run_conversion_corpus.js [--case ID] [--attempts N]
 */

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const IF = path.join(ROOT, "PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/InputFormat");
const PYODIDE = path.join(ROOT, "PaintomicsClient/public_html/resources/pyodide/");
const CORPUS = path.join(__dirname, "inputformat_corpus");
const DATASETS = path.join(ROOT, "PaintomicsServer/src/examplefiles/datasets");
const PYTHON = "/Users/tianyuan/miniforge3/envs/paintomics4/bin/python";

const api = Object.assign({},
  require(path.join(IF, "format-reader.js")),
  require(path.join(IF, "format-validator.js")),
  require(path.join(IF, "format-roles.js")),
  require(path.join(IF, "convert-profiler.js")));
const { runAgent } = require(path.join(IF, "convert-agent.js"));

// ---------------------------------------------------------------------------
// Sandbox: the same Pyodide the browser runs, headless.
// ---------------------------------------------------------------------------
async function makeSandbox() {
  const { loadPyodide } = require(PYODIDE + "pyodide.js");
  const py = await loadPyodide({ indexURL: PYODIDE, stdout: () => {}, stderr: () => {} });
  await py.loadPackage(["pandas", "numpy"]);
  await py.loadPackage(PYODIDE + "et_xmlfile-2.0.0-py3-none-any.whl");
  await py.loadPackage(PYODIDE + "openpyxl-3.1.5-py2.py3-none-any.whl");

  return {
    async run(code, files) {
      for (const d of ["/work", "/out"]) {
        try { py.FS.mkdir(d); } catch (e) { /* exists */ }
      }
      // Each attempt starts from an empty /work AND /out. Leaving /work dirty
      // let a previous case's file survive into the next one, and the profiler
      // -- which takes the first file it finds -- then described the wrong
      // file entirely.
      for (const dir of ["/out", "/work"]) {
        for (const f of py.FS.readdir(dir)) {
          if (f !== "." && f !== "..") py.FS.unlink(dir + "/" + f);
        }
      }
      for (const [name, bytes] of Object.entries(files || {})) {
        py.FS.writeFile("/work/" + name, bytes);
      }
      let stdout = "";
      py.setStdout({ batched: (s) => { stdout += s + "\n"; } });
      py.setStderr({ batched: (s) => { stdout += s + "\n"; } });
      try {
        await py.runPythonAsync(code);
      } catch (err) {
        return { ok: false, stdout, traceback: String(err.message || err) };
      }
      const outputs = {};
      for (const f of py.FS.readdir("/out")) {
        if (f !== "." && f !== "..") outputs[f] = py.FS.readFile("/out/" + f);
      }
      return { ok: true, stdout, outputs };
    }
  };
}

// ---------------------------------------------------------------------------
// Transport: the production turn function, called as a subprocess.
// ---------------------------------------------------------------------------
function makeTransport() {
  return async function (state) {
    const out = execFileSync(PYTHON,
      [path.join(ROOT, "PaintomicsServer/src/classes/InputConvert/agent_turn.py")],
      { input: JSON.stringify(state), cwd: path.join(ROOT, "PaintomicsServer"),
        maxBuffer: 16 * 1024 * 1024, encoding: "utf8",
        env: Object.assign({}, process.env, { PYTHONPATH: path.join(ROOT, "PaintomicsServer/src") }) });
    try { return JSON.parse(out); } catch (e) { return null; }
  };
}

// ---------------------------------------------------------------------------
// Ground truth
// ---------------------------------------------------------------------------
const TRUTH = {
  "ge-decimal-comma":        [DATASETS, "02-gene-multi-condition/data/gene_expression_values.tab"],
  "ge-semicolon":            [DATASETS, "02-gene-multi-condition/data/gene_expression_values.tab"],
  "ge-transposed":           [DATASETS, "02-gene-multi-condition/data/gene_expression_values.tab"],
  "ge-title-rows":           [DATASETS, "02-gene-multi-condition/data/gene_expression_values.tab"],
  "ge-annotation-columns":   [DATASETS, "02-gene-multi-condition/data/gene_expression_values.tab"],
  "ge-latin1":               [DATASETS, "02-gene-multi-condition/data/gene_expression_values.tab"],
  "ge-crlf-quoted":          [DATASETS, "02-gene-multi-condition/data/gene_expression_values.tab"],
  "ge-duplicate-ids":        [DATASETS, "02-gene-multi-condition/data/gene_expression_values.tab"],
  "more-design-labels":      [DATASETS, "06-regulatory-more/data/experimental_design.tab"],
  "more-associations-3col":  [DATASETS, "06-regulatory-more/data/mirna_associations.tab"],
  "more-associations-swapped": [DATASETS, "06-regulatory-more/data/mirna_associations.tab"],
  "more-regulators-transposed": [DATASETS, "06-regulatory-more/data/mirna_regulators.tab"],
  "more-missing-design":     [DATASETS, "06-regulatory-more/data/experimental_design.tab"],
  "region-locus-string":     [DATASETS, "07-region-based/data/dnase_regions_values.tab"],
  "region-chr-prefix":       [DATASETS, "07-region-based/data/dnase_regions_values.tab"],
  "region-extra-bed-columns":[DATASETS, "07-region-based/data/dnase_regions_values.tab"],
};

function parseTable(text) {
  const rows = api.readDelimited(new Uint8Array(Buffer.from(text, "utf8"))).rows;
  return rows.filter(r => r.some(c => String(c).trim() !== ""));
}

function isNum(s) { return api.isPythonFloat(String(s)); }

/*
 * Compare a converted table against the original.
 *
 * Identifiers are compared as a set and values as numbers keyed by identifier,
 * because column ORDER and header spelling are not information the user cares
 * about -- "T00h" arriving as "T00h" or "Control" is cosmetic, whereas a gene
 * losing its value is not. Numbers are compared with a tolerance, since a
 * round-trip through float text can move the last digit.
 */
function compareInformation(produced, truth, opts = {}) {
  // Some fixtures are deliberately truncated. Judging them against the whole
  // original counts rows the agent was never given as rows it lost, which is
  // the harness lying about the agent rather than measuring it.
  if (opts.limitTruthTo) {
    const rows = parseTable(truth);
    truth = rows.slice(0, opts.limitTruthTo + 1).map(r => r.join("\t")).join("\n");
  }
  const notes = [];
  const pRows = parseTable(produced);
  const tRows = parseTable(truth);
  if (!pRows.length) return { ok: false, notes: ["output is empty"] };

  const pHead = pRows[0].slice(1).every(isNum) ? null : pRows[0];
  const tHead = tRows[0].slice(1).every(isNum) ? null : tRows[0];
  const pBody = pHead ? pRows.slice(1) : pRows;
  const tBody = tHead ? tRows.slice(1) : tRows;

  const idCols = opts.idColumns || 1;
  const key = r => r.slice(0, idCols).join("|").replace(/^chr/i, "");
  const pMap = new Map(pBody.map(r => [key(r), r.slice(idCols)]));
  const tMap = new Map(tBody.map(r => [key(r), r.slice(idCols)]));

  const missing = [...tMap.keys()].filter(k => !pMap.has(k));
  const extra = [...pMap.keys()].filter(k => !tMap.has(k));
  if (missing.length) notes.push(`${missing.length} identifiers lost (e.g. ${missing.slice(0,3).join(", ")})`);
  if (extra.length) notes.push(`${extra.length} identifiers invented (e.g. ${extra.slice(0,3).join(", ")})`);

  let valueMismatch = 0, checked = 0, firstBad = null;
  for (const [k, tVals] of tMap) {
    const pVals = pMap.get(k);
    if (!pVals) continue;
    if (pVals.length !== tVals.length) {
      notes.push(`${k}: ${pVals.length} values, expected ${tVals.length}`);
      valueMismatch++;
      continue;
    }
    for (let i = 0; i < tVals.length; i++) {
      checked++;
      const a = parseFloat(pVals[i]), b = parseFloat(tVals[i]);
      if (Number.isNaN(a) !== Number.isNaN(b) || (!Number.isNaN(a) && Math.abs(a - b) > 1e-3)) {
        valueMismatch++;
        if (!firstBad) firstBad = `${k}[${i}] ${pVals[i]} != ${tVals[i]}`;
      }
    }
  }
  if (valueMismatch) notes.push(`${valueMismatch}/${checked} values differ (${firstBad})`);

  return {
    ok: missing.length === 0 && extra.length === 0 && valueMismatch === 0,
    notes,
    stats: { produced: pMap.size, expected: tMap.size, valuesChecked: checked }
  };
}

module.exports = { makeSandbox, makeTransport, compareInformation, parseTable, TRUTH, api, runAgent, CORPUS, ROOT };

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------
const OMIC_FOR = {
  "gene expression": "Gene expression",
  "regulatory": "Regulatory omic (MORE)",
  "region-based": "Region-based omic",
};

// Cases where the original cannot be recovered byte-for-byte and the check is
// stated explicitly instead.
function compareDesign(produced, truth) {
  // Two design files say the same thing if every sample lands in the same NAMED
  // condition. Column order is presentation, not information, so a positional
  // comparison marks a correct reordering as 12 wrong values -- which is what
  // it did before this was fixed.
  const mapOf = (text) => {
    const rows = parseTable(text);
    const header = rows[0], out = new Map();
    for (const r of rows.slice(1)) {
      const idx = r.slice(1).findIndex(v => String(v).trim() === "1");
      out.set(String(r[0]).trim(), idx === -1 ? null : String(header[idx + 1]).trim());
    }
    return out;
  };
  const p = mapOf(produced), t = mapOf(truth);
  const notes = [];
  const missing = [...t.keys()].filter(k => !p.has(k));
  if (missing.length) notes.push(`${missing.length} samples missing (e.g. ${missing.slice(0,3).join(", ")})`);
  let wrong = 0, firstBad = null;
  for (const [s, cond] of t) {
    if (!p.has(s)) continue;
    if (p.get(s) !== cond) { wrong++; if (!firstBad) firstBad = `${s}: ${p.get(s)} != ${cond}`; }
  }
  if (wrong) notes.push(`${wrong} samples in the wrong condition (${firstBad})`);
  return { ok: missing.length === 0 && wrong === 0, notes,
           stats: { produced: p.size, expected: t.size, valuesChecked: t.size } };
}

// What an unattended run should answer when the agent asks. Only cases whose
// correct handling genuinely depends on a user decision appear here.
const CASE_ANSWERS = {
  "ge-duplicate-ids": "average|mean",
};

const DERIVED_CHECKS = {
  "ge-duplicate-ids": (outputs, decode) => {
    const rows = parseTable(decode(Object.values(outputs)[0]));
    const body = rows[0].slice(1).every(isNum) ? rows : rows.slice(1);
    const ids = body.map(r => r[0]);
    const dupes = ids.length - new Set(ids).size;
    return { ok: dupes === 0,
             notes: dupes ? [`${dupes} duplicate identifiers remain`]
                          : [`collapsed to ${ids.length} unique identifiers`] };
  },
};

async function main() {
  const args = process.argv.slice(2);
  const only = args.includes("--case") ? args[args.indexOf("--case") + 1] : null;
  const attempts = args.includes("--attempts") ? +args[args.indexOf("--attempts") + 1] : 5;

  const manifest = JSON.parse(fs.readFileSync(path.join(CORPUS, "manifest.json"), "utf8"));
  const cases = only ? manifest.filter(c => c.id === only) : manifest;
  if (!cases.length) { console.error("no such case:", only); process.exit(2); }

  console.log(`booting sandbox…`);
  const sandbox = await makeSandbox();
  const transport = makeTransport();
  const decode = b => Buffer.from(b).toString("utf8");

  const results = [];
  for (const c of cases) {
    const dir = path.join(CORPUS, c.id);
    const inputs = fs.readdirSync(dir);
    // The agent converts one file per run; a case with several files uses the
    // one that is broken, or -- for a missing-file case -- the file the absent
    // one must be derived from.
    const primary = c.id === "more-missing-design"
      ? "gene_expression_targets.tab"
      : inputs[0];
    const bytes = new Uint8Array(fs.readFileSync(path.join(dir, primary)));

    const events = [];
    const t0 = Date.now();
    let res;
    try {
      res = await runAgent({
        api, sandbox, transport, maxAttempts: attempts,
        files: { [primary]: bytes },
        inputPath: "/work/" + primary,
        fileName: primary,
        omicType: OMIC_FOR[c.module] || c.module,
        species: "mmu",
        goal: c.id === "more-missing-design"
          ? "The experimental design file is missing. Rebuild it from the sample names in this matrix."
          : "Convert this file into the format PaintOmics accepts.",
        onEvent: e => events.push(e),
        ask: async (q) => {
          // Unattended, so the harness answers deterministically. It picks the
          // option matching what the case expects, because a run that asks the
          // right question and then gets an arbitrary answer would be scored on
          // the answer rather than on the question.
          const wanted = CASE_ANSWERS[c.id];
          if (wanted && q.options) {
            const hit = q.options.find(o => new RegExp(wanted, "i").test(o));
            if (hit) return hit;
          }
          return (q.options && q.options[0]) || "use your best judgement";
        },
      });
    } catch (err) {
      res = { ok: false, stage: "crash", traceback: String(err.message || err) };
    }
    const seconds = Math.round((Date.now() - t0) / 100) / 10;

    let info = { ok: null, notes: ["not checked"] };
    if (res.ok && res.outputs) {
      if (DERIVED_CHECKS[c.id]) {
        info = DERIVED_CHECKS[c.id](res.outputs, decode);
      } else if (TRUTH[c.id]) {
        const truth = fs.readFileSync(path.join(TRUTH[c.id][0], TRUTH[c.id][1]), "utf8");
        const names = Object.keys(res.outputs).filter(n => n !== "manifest.json");
        const idCols = c.module === "region-based" ? 3 : 1;
        // ge-transposed was built from the first 300 genes only.
        const limitTruthTo = c.id === "ge-transposed" ? 300 : null;
        // Judge against the produced file that best matches the truth's role.
        const isDesign = c.role === "design";
        let best = null;
        for (const n of names) {
          if (isDesign && !/design/i.test(n)) continue;
          const cmp = isDesign
            ? compareDesign(decode(res.outputs[n]), truth)
            : compareInformation(decode(res.outputs[n]), truth,
                                 { idColumns: idCols, limitTruthTo });
          if (!best || (cmp.stats.produced > best.stats.produced)) best = cmp;
        }
        info = best || { ok: false, notes: ["no output files"] };
      }
    }

    const questions = events.filter(e => e.phase === "asking").map(e => e.detail);
    results.push({ id: c.id, module: c.module, breakage: c.breakage,
                   format: !!res.ok, information: info.ok, notes: info.notes,
                   attempts: res.attempts || attempts, seconds, questions,
                   outputs: res.outputs ? Object.keys(res.outputs) : [],
                   failure: res.ok ? null : (res.traceback || res.stage),
                   history: (res.history || []).map(h => ({
                     attempt: h.attempt,
                     traceback: h.traceback ? String(h.traceback).slice(-600) : undefined,
                     validation: h.validation ? String(h.validation).slice(0, 400) : undefined,
                     code: h.code ? String(h.code).slice(0, 1200) : undefined })) });

    const mark = res.ok ? (info.ok === false ? "FORMAT-ONLY" : "PASS") : "FAIL";
    console.log(`${mark.padEnd(12)} ${c.id.padEnd(28)} ${seconds}s  ${info.notes.join("; ").slice(0, 90)}`);
  }

  const pass = results.filter(r => r.format && r.information !== false).length;
  const formatOnly = results.filter(r => r.format && r.information === false).length;
  const fail = results.filter(r => !r.format).length;

  console.log("\n" + "=".repeat(78));
  console.log(`PASS ${pass}/${results.length}   format-only ${formatOnly}   failed ${fail}`);
  for (const mod of [...new Set(results.map(r => r.module))]) {
    const rs = results.filter(r => r.module === mod);
    const p = rs.filter(r => r.format && r.information !== false).length;
    console.log(`  ${mod.padEnd(18)} ${p}/${rs.length}`);
  }
  fs.writeFileSync(path.join(CORPUS, "results.json"), JSON.stringify(results, null, 2));
  console.log(`\nwrote ${path.join(CORPUS, "results.json")}`);
  process.exit(fail || formatOnly ? 1 : 0);
}

if (require.main === module) main().catch(e => { console.error(e); process.exit(2); });
