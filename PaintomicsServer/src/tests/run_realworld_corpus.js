/*
 * Runs real user files -- GEO supplements, PRIDE exports, MetaboLights MAFs,
 * a collaborator's workbook -- through the conversion agent and grades each
 * result against an expert answer key (realworld_answer_key.js).
 *
 * The synthetic corpus (run_conversion_corpus.js) proves the agent can undo a
 * known corruption. This one asks the harder question: given a file nobody
 * broke on purpose, does the output hold every measurement the file held, and
 * nothing that is not a measurement? A conversion that passes the validator
 * and drops three of four sheets, pivots q-values into a matrix, or loses the
 * tissue dimension of a tidy table is a failure here.
 *
 *   node PaintomicsServer/src/tests/run_realworld_corpus.js
 *        [--dir ~/Desktop/test-fails-check] [--only REGEX] [--attempts N]
 *        [--shard i/n] [--out DIR]
 */

const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const H = require("./run_conversion_corpus.js");
const { KEY, ANSWERS_DEFAULT } = require("./realworld_answer_key.js");

const PYTHON = process.env.PAINTOMICS_PYTHON || "/Users/tianyuan/miniforge3/envs/paintomics4/bin/python";
const TRUTH = path.join(__dirname, "realworld_truth.py");

// ---------------------------------------------------------------------------
// Truth extraction (cached per spec)
// ---------------------------------------------------------------------------
const truthCache = new Map();
function truth(spec) {
  const key = JSON.stringify(spec);
  if (truthCache.has(key)) return truthCache.get(key);
  let text;
  try {
    text = execFileSync(PYTHON, [TRUTH], { input: JSON.stringify(spec), encoding: "utf8",
                                            maxBuffer: 512 * 1024 * 1024 });
  } catch (err) {
    text = null;
    console.error("truth extraction failed for", spec.file, String(err.stderr || err.message).slice(-300));
  }
  truthCache.set(key, text);
  return text;
}

// ---------------------------------------------------------------------------
// Table comparison
// ---------------------------------------------------------------------------
function parseTsv(text) {
  const rows = text.split(/\r?\n/).filter(l => l.trim() !== "").map(l => l.split("\t"));
  return rows;
}

function toNum(s) {
  const t = String(s).trim().toLowerCase();
  if (t === "" || t === "na" || t === "nan" || t === "n/a" || t === "null" || t === "none" || t === "filtered") return NaN;
  const n = Number(t);
  return Number.isFinite(n) ? n : (t === "inf" ? Infinity : t === "-inf" ? -Infinity : NaN);
}

function sameValue(a, b) {
  if (Number.isNaN(a) || Number.isNaN(b)) return Number.isNaN(a) && Number.isNaN(b);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return a === b;
  return Math.abs(a - b) <= 1e-3 + 1e-6 * Math.abs(b);
}

/*
 * Rows keyed by identifier; a repeated identifier gets "#k" appended in file
 * order, so a phosphosite table (many sites per protein, deliberately kept)
 * compares row by row while a genuine duplicate still shows up as one.
 */
// Excel silently rewrites gene symbols like Sept9/March1/Dec1 into dates. Both
// the file and any faithful conversion carry that damage, but a datetime prints
// differently on each side ("2024-09-01" vs "2024-09-01 00:00:00"); normalise it
// so the corruption is not counted as a mismatch the agent could not have avoided.
function normId(s) {
  s = String(s).trim().replace(/^"|"$/g, "");
  const date = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T]00:00:00)?$/);
  if (date) return date[1] + "-" + date[2] + "-" + date[3];
  // A UniProt group "sp|P12345|NAME_MOUSE" / "tr|Q9..|.." reduces to its
  // accession -- the stable half PaintOmics maps; the agent may keep the
  // whole thing or just the accession and both are correct.
  const up = s.match(/^(?:sp|tr)\|([^|]+)\|/i);
  if (up) return up[1];
  return s;
}
// Compare identifiers ignoring a trailing .version (ENSMUSG...\.16 == ENSMUSG...).
function idKeyBase(base) { return base.replace(/\.\d+$/, ""); }
function keyed(rows, idCols) {
  const seen = new Map(), out = new Map();
  for (const r of rows) {
    const base = idKeyBase(r.slice(0, idCols).map(c => normId(c)).join("|").replace(/^chr/i, ""));
    const k = seen.get(base) || 0;
    seen.set(base, k + 1);
    out.set(k ? base + "#" + k : base, r.slice(idCols).map(toNum));
  }
  return out;
}

function compareTables(producedText, truthText, opts = {}) {
  const notes = [];
  const p = parseTsv(producedText), t = parseTsv(truthText);
  if (!p.length) return { ok: false, notes: ["output is empty"], score: 0 };
  const pHeader = p[0], tHeader = t[0];
  const pBody = p.slice(1), tBody = t.slice(1);
  const idCols = opts.idColumns || 1;
  const P = keyed(pBody, idCols), T = keyed(tBody, idCols);

  const missing = [...T.keys()].filter(k => !P.has(k));
  // A produced row that is not in the truth but carries no value at all is an
  // empty row the agent chose to keep, not an invented feature.
  const invented = [...P.keys()].filter(k => !T.has(k) && P.get(k).some(v => !Number.isNaN(v)));
  const tolerate = opts.tolerateMissing || 0;
  if (missing.length > tolerate * T.size) notes.push(`${missing.length}/${T.size} identifiers lost (e.g. ${missing.slice(0, 3).join(", ")})`);
  if (invented.length > tolerate * P.size) notes.push(`${invented.length} identifiers not in the source (e.g. ${invented.slice(0, 3).join(", ")})`);

  const common = [...T.keys()].filter(k => P.has(k));
  const nT = tHeader.length - idCols, nP = pHeader.length - idCols;
  const pNames = pHeader.slice(idCols).map(s => s.trim().toLowerCase());
  const tNames = tHeader.slice(idCols).map(s => s.trim().toLowerCase());
  const sample = common.length > 3000 ? common.filter((_, i) => i % Math.ceil(common.length / 3000) === 0) : common;

  // Match each truth column to a produced column. A matching NAME is taken
  // only when the values agree too: an FPKM file whose columns were renamed to
  // the bare sample names would otherwise be graded as the counts table.
  const used = new Set(), mapping = [];
  const rateOf = (i, j) => {
    let agree = 0, n = 0;
    for (const k of sample) {
      const a = P.get(k)[i], b = T.get(k)[j];
      if (a === undefined || b === undefined) continue;
      n++; if (sameValue(a, b)) agree++;
    }
    return n ? agree / n : 0;
  };
  for (let j = 0; j < nT; j++) {
    const named = pNames.indexOf(tNames[j]);
    if (named !== -1 && !used.has(named) && rateOf(named, j) >= 0.98) { used.add(named); mapping.push(named); continue; }
    let best = -1, bestRate = 0;
    for (let i = 0; i < nP; i++) {
      if (used.has(i)) continue;
      const rate = rateOf(i, j);
      if (rate > bestRate) { bestRate = rate; best = i; }
    }
    if (best !== -1 && bestRate >= 0.98) { used.add(best); mapping.push(best); }
    else mapping.push(-1);
  }
  const unmatched = mapping.map((m, j) => m === -1 ? tHeader[idCols + j] : null).filter(Boolean);
  if (unmatched.length) notes.push(`${unmatched.length}/${nT} measurement columns missing (e.g. ${unmatched.slice(0, 3).join(", ")})`);
  const extra = nP - used.size;
  if (extra > 0) notes.push(`${extra} extra column(s) that are not measurements of this family`);

  let mismatches = 0, checked = 0, first = null;
  for (const k of common) {
    const pv = P.get(k), tv = T.get(k);
    for (let j = 0; j < nT; j++) {
      const i = mapping[j];
      if (i === -1) continue;
      checked++;
      if (!sameValue(pv[i], tv[j])) { mismatches++; if (!first) first = `${k}[${tHeader[idCols + j]}] ${pv[i]} != ${tv[j]}`; }
    }
  }
  if (mismatches) notes.push(`${mismatches}/${checked} values differ (${first})`);

  const ok = missing.length <= tolerate * T.size && invented.length <= tolerate * P.size && unmatched.length === 0 &&
             extra <= 0 && mismatches === 0;
  const score = (common.length / Math.max(1, T.size)) * ((nT - unmatched.length) / Math.max(1, nT)) *
                (checked ? (checked - mismatches) / checked : 0) - (invented.length ? 0.2 : 0) - (extra > 0 ? 0.1 : 0);
  return { ok, notes, score, stats: { produced: P.size, expected: T.size, columns: nT, checked } };
}

function compareIds(producedText, truthText) {
  const norm = x => idKeyBase(normId(x));
  const p = new Set(producedText.split(/\r?\n/).map(norm).filter(Boolean));
  const t = new Set(truthText.split(/\r?\n/).map(norm).filter(Boolean));
  if (!p.size) return { ok: false, notes: ["empty list"], score: 0 };
  const invented = [...p].filter(x => !t.has(x)).length;
  const covered = [...t].filter(x => p.has(x)).length;
  const notes = [];
  if (invented / p.size > 0.02) notes.push(`${invented}/${p.size} listed identifiers are not significant in the source`);
  if (covered / t.size < 0.9) notes.push(`only ${covered}/${t.size} significant identifiers listed`);
  return { ok: notes.length === 0, notes, score: covered / t.size - invented / p.size };
}

// ---------------------------------------------------------------------------
// Grading one file against its key entry
// ---------------------------------------------------------------------------
function grade(entry, file, outputs, reports, decode) {
  const names = Object.keys(outputs || {}).filter(n => n !== "manifest.json");
  const values = names.filter(n => (reports[n] || {}).role === "values");
  const lists = names.filter(n => (reports[n] || {}).role === "relevant");
  const notes = [];
  let ok = true;
  const matched = {};

  if (entry.noValues) {
    if (values.length) { ok = false; notes.push(`${values.length} values file(s) built from a file that has no measurements: ${values.join(", ")}`); }
  }

  if (entry.tableSets) {
    let bestSet = null;
    for (const set of entry.tableSets) {
      const result = { found: [], lost: [], setNotes: [] };
      for (const table of set) {
        let best = null;
        for (const spec of table.anyOf) {
          const truthText = truth(Object.assign({ file }, spec));
          if (!truthText) continue;
          for (const n of values) {
            const cmp = compareTables(decode(outputs[n]), truthText, { tolerateMissing: spec.tolerateMissing || table.tolerateMissing || 0 });
            if (!best || cmp.score > best.cmp.score) best = { cmp, name: n, spec };
            if (cmp.ok) break;
          }
          if (best && best.cmp.ok) break;
        }
        if (best && best.cmp.ok) result.found.push({ table: table.name, file: best.name });
        else if (!table.optional) {
          result.lost.push(table.name);
          result.setNotes.push(`${table.name}: ${best ? best.cmp.notes.join("; ") || "no match" : "no values file"}`);
        }
      }
      if (!bestSet || result.lost.length < bestSet.lost.length) bestSet = result;
      if (!result.lost.length) break;
    }
    bestSet.found.forEach(f => { matched[f.file] = f.table; });
    if (bestSet.lost.length) { ok = false; notes.push(...bestSet.setNotes); }
    else notes.push(`tables: ${bestSet.found.map(f => f.table).join(", ")}`);
  }

  if (entry.relevant) {
    for (const rel of entry.relevant) {
      let best = null;
      for (const spec of rel.anyOf) {
        const truthText = truth(Object.assign({ file }, spec));
        if (!truthText) continue;
        for (const n of lists) {
          const cmp = compareIds(decode(outputs[n]), truthText);
          if (!best || cmp.score > best.cmp.score) best = { cmp, name: n };
        }
        // One list per group (cell type, experience) is a legitimate shape;
        // together they must cover the significant set.
        if (lists.length > 1) {
          const union = lists.map(n => decode(outputs[n])).join("\n");
          const cmp = compareIds(union, truthText);
          if (!best || cmp.score > best.cmp.score) best = { cmp, name: lists.join(" + ") };
        }
      }
      if (best && best.cmp.ok) { matched[best.name] = "relevant: " + rel.name; notes.push(`relevant list ok (${rel.name})`); }
      else if (!rel.optional) { ok = false; notes.push(`relevant list missing or wrong (${rel.name}): ${best ? best.cmp.notes.join("; ") : "no list produced"}`); }
    }
  }
  return { ok, notes, matched };
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------
function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i !== -1 ? process.argv[i + 1] : dflt;
}

async function main() {
  const dir = arg("--dir", path.join(os.homedir(), "Desktop/test-fails-check"));
  const only = arg("--only", null) ? new RegExp(arg("--only"), "i") : null;
  const attempts = +arg("--attempts", 5);
  const shard = arg("--shard", null);
  const outDir = arg("--out", path.join(__dirname, "realworld_results"));
  fs.mkdirSync(outDir, { recursive: true });

  let files = Object.keys(KEY).filter(f => fs.existsSync(path.join(dir, f)));
  const absent = Object.keys(KEY).filter(f => !fs.existsSync(path.join(dir, f)));
  if (absent.length) console.log(`(${absent.length} key entries have no file under ${dir})`);
  if (only) files = files.filter(f => only.test(f));
  if (shard) {
    const [i, n] = shard.split("/").map(Number);
    files = files.filter((_, k) => k % n === i - 1);
  }
  if (!files.length) { console.error("nothing to run"); process.exit(2); }

  console.log(`booting sandbox… (${files.length} files)`);
  const sandbox = await H.makeSandbox();
  const transport = H.makeTransport();
  const decode = b => Buffer.from(b).toString("utf8");
  const results = [];

  for (const rel of files) {
    const entry = KEY[rel];
    const file = path.join(dir, rel);
    const safe = path.basename(rel).replace(/[^A-Za-z0-9._-]/g, "_");
    const bytes = new Uint8Array(fs.readFileSync(file));
    const answers = (entry.answers || []).concat(ANSWERS_DEFAULT);
    const events = [], questions = [];
    const t0 = Date.now();
    let res;
    try {
      res = await H.runAgent({
        api: H.api, sandbox, transport, maxAttempts: attempts,
        files: { [safe]: bytes }, inputPath: "/work/" + safe, fileName: path.basename(rel),
        omicType: entry.omic, species: entry.species,
        goal: "Convert this file into the format PaintOmics accepts, keeping every measurement it holds.",
        instructions: entry.instructions || [],
        onEvent: e => events.push({ phase: e.phase, title: e.title, detail: String(e.detail || "").slice(0, 400), attempt: e.attempt }),
        ask: async q => {
          let answer = null;
          for (const [qRe, aRe] of answers) {
            if (!qRe.test(q.text)) continue;
            const hit = (q.options || []).find(o => aRe.test(o));
            answer = hit || aRe.source.split("|")[0].replace(/[\\^$()]/g, "");
            break;
          }
          if (!answer) answer = (q.options && q.options[0]) || "use your best judgement";
          questions.push({ q: q.text, options: q.options, answer });
          return answer;
        },
      });
    } catch (err) {
      res = { ok: false, stage: "crash", traceback: String(err.stack || err) };
    }
    const seconds = Math.round((Date.now() - t0) / 100) / 10;

    let info = { ok: null, notes: ["not graded: no valid output"], matched: {} };
    if (res.outputs) info = grade(entry, file, res.outputs, res.reports || {}, decode);

    const outputs = {};
    for (const [n, b] of Object.entries(res.outputs || {})) {
      const txt = decode(b);
      const lines = txt.split(/\r?\n/).filter(l => l.trim());
      outputs[n] = { rows: lines.length, head: lines.slice(0, 3).map(l => l.slice(0, 160)),
                     role: (res.reports && res.reports[n] || {}).role, matched: info.matched[n] || null };
    }
    const record = {
      file: rel, format: !!res.ok, information: info.ok, notes: info.notes, seconds,
      attempts: res.attempts || attempts, questions, outputs,
      manifest: res.manifest || null,
      failure: res.ok ? null : (res.traceback || res.stage),
      history: (res.history || []).map(h => ({
        attempt: h.attempt, full: h.full,
        traceback: h.traceback ? String(h.traceback).slice(-700) : undefined,
        validation: h.validation ? String(h.validation).slice(0, 500) : undefined,
        question: h.question, error: h.error })),
      code: res.code, events,
    };
    results.push(record);
    fs.writeFileSync(path.join(outDir, safe + ".json"), JSON.stringify(record, null, 2));

    const mark = res.ok ? (info.ok ? "PASS" : "FORMAT-ONLY") : "FAIL";
    console.log(`${mark.padEnd(12)} ${rel.padEnd(62)} ${String(seconds).padStart(6)}s  ` +
                `${Object.keys(outputs).filter(n => n !== "manifest.json").length} files  ` +
                `${info.notes.join(" | ").slice(0, 160)}${res.ok ? "" : "  " + String(record.failure || "").slice(-120).replace(/\n/g, " ")}`);
  }

  const pass = results.filter(r => r.format && r.information).length;
  const formatOnly = results.filter(r => r.format && !r.information).length;
  const fail = results.filter(r => !r.format).length;
  console.log("\n" + "=".repeat(100));
  console.log(`PASS ${pass}/${results.length}   format-only ${formatOnly}   failed ${fail}`);
  for (const group of ["gene-expression", "proteomics", "metabolomics", "workbook"]) {
    const rs = results.filter(r => group === "workbook" ? !r.file.includes("/") : r.file.startsWith(group));
    if (!rs.length) continue;
    console.log(`  ${group.padEnd(16)} ${rs.filter(r => r.format && r.information).length}/${rs.length}`);
  }
  fs.writeFileSync(path.join(outDir, "_summary" + (shard ? "_" + shard.replace("/", "of") : "") + ".json"),
                   JSON.stringify(results, null, 2));
  process.exit(pass === results.length ? 0 : 1);
}

if (require.main === module) main().catch(e => { console.error(e); process.exit(2); });
module.exports = { compareTables, compareIds, grade, truth };
