/*
 * The conversion agent loop.
 *
 * It is a state machine, not a framework. The model returns one of exactly
 * three typed actions -- write code, ask the user, or declare done -- so there
 * is no tool surface for it to reach past, and anything else is a parse failure
 * and a retry.
 *
 * The exit condition is the VALIDATOR, never the model's own opinion. That is
 * the same module Layer 0 uses, which a test pins to the server's validation
 * loop over every shipped example file, so the agent cannot declare success on
 * a file the server would go on to reject.
 *
 * Scripts are developed against a SAMPLE of a delimited file and the accepted
 * script is then re-run on the whole file. The earlier version of this loop
 * told the model it was working on a sample and then ran every attempt on the
 * full input, which made a 54 MB file cost a full parse per attempt and made
 * the prompt a lie. Workbooks are read whole: a sample of a zip is not a
 * workbook, and the largest one measured parses in about 20 s.
 *
 * Everything the loop touches is injected -- transport, sandbox, validator, the
 * question hook -- so the identical code runs in the browser against the real
 * gateway and headlessly in the corpus harness against a recorded one.
 */
(function (root, factory) {
    if (typeof module === "object" && module.exports) module.exports = factory();
    else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var DEFAULT_MAX_ATTEMPTS = 5;

    // The agent develops against this many data rows, not the whole file. A
    // 100 MB input is ~1M rows and pandas holds several times the file size, so
    // iterating on all of it would make every round slow and would peak memory
    // once per attempt instead of once per conversion.
    var SAMPLE_ROWS = 5000;

    function emit(onEvent, event) {
        if (typeof onEvent === "function") {
            try { onEvent(event); } catch (e) { /* a UI fault must not kill the run */ }
        }
    }

    /*
     * Progress is reported as a fraction of the attempt budget rather than as a
     * guess at completion. It is honest -- attempt 2 of 5 really is 40% of the
     * effort this run is allowed -- and it never goes backwards, which a
     * confidence-based estimate does the moment a round fails.
     */
    function progressFor(phase, attempt, maxAttempts) {
        var base = { profiling: 0.05, thinking: 0.15, running: 0.45,
                     validating: 0.7, asking: 0.55, finalising: 0.85, done: 1 }[phase] || 0;
        var span = 0.75 / Math.max(1, maxAttempts);
        return Math.min(1, base + (attempt - 1) * span * 0.35);
    }

    function step(onEvent, phase, title, detail, attempt, maxAttempts) {
        emit(onEvent, {
            type: "step", phase: phase, title: title, detail: detail || "",
            attempt: attempt, maxAttempts: maxAttempts,
            progress: progressFor(phase, attempt, maxAttempts)
        });
    }

    function decodeText(bytes) {
        if (typeof TextDecoder !== "undefined") {
            return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
        }
        return Buffer.from(bytes).toString("utf8");
    }

    function encodeText(text) {
        if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(text);
        return new Uint8Array(Buffer.from(text, "utf8"));
    }

    function isWorkbook(bytes) {
        return bytes && bytes.length > 1 && bytes[0] === 0x50 && bytes[1] === 0x4B; // "PK"
    }

    /*
     * The first SAMPLE_ROWS lines of a delimited file, cut at a line boundary.
     * Returns null when the file is a workbook or already small enough, so the
     * caller can tell "ran on a sample" from "ran on everything".
     */
    function sampleOf(bytes, rows) {
        if (isWorkbook(bytes)) return null;
        var limit = rows || SAMPLE_ROWS;
        var seen = 0;
        for (var i = 0; i < bytes.length; i++) {
            if (bytes[i] === 0x0A) {
                seen++;
                if (seen >= limit + 1) return bytes.subarray(0, i + 1);
            }
        }
        return null;                                   // fewer lines than the sample
    }

    function sampleFiles(files) {
        var out = {}, sampled = false;
        Object.keys(files || {}).forEach(function (name) {
            var s = sampleOf(files[name]);
            if (s) sampled = true;
            out[name] = s || files[name];
        });
        return sampled ? out : null;
    }

    function parseManifest(outputs) {
        if (!outputs || !outputs["manifest.json"]) return null;
        try {
            var m = JSON.parse(decodeText(outputs["manifest.json"]));
            return (m && typeof m === "object") ? m : null;
        } catch (e) {
            return null;
        }
    }

    /*
     * Grade every produced file. A conversion that writes a beautiful values
     * matrix and a malformed relevant list has not succeeded, so the whole
     * output set has to pass, not the first file.
     */
    /*
     * A values matrix with a repeated identifier double-counts that feature in
     * the enrichment. That is sometimes intended -- a phosphosite table has one
     * row per site and many sites per protein -- so it is not always wrong, but
     * it must never be SILENT: the agent has to have either asked the user how
     * to handle the duplicates or said in the manifest why they are kept. This
     * is what makes a small model ask instead of quietly emitting a
     * double-counted matrix.
     */
    function isInteger(s) {
        return /^-?\d+$/.test(String(s).trim());
    }

    /*
     * How many leading columns form the identifier. Normally one, but a
     * region-based matrix identifies a feature by chromosome + start + end
     * together: keying on the chromosome alone would call every region on chr1
     * a duplicate, which is exactly what rejected a correct locus split five
     * times. Detected by the COORDINATE PAIR -- two integer columns where end
     * >= start -- because the chromosome is a bare number ("1", "2", "X"), so a
     * "non-numeric first column" test does not distinguish it from a gene id.
     * A gene count matrix has integer columns too, but they are independent
     * per-sample counts with no start<=end ordering, and its identifier column
     * is unique so there are no duplicates to key in the first place.
     */
    function idColumnCount(body) {
        if (!body.length || body[0].length < 4) return 1;
        var sample = body.slice(0, 200);
        var pairs = 0, checked = 0;
        for (var i = 0; i < sample.length; i++) {
            var a = sample[i][1], b = sample[i][2];
            if (!isInteger(a) || !isInteger(b)) return 1;
            checked++;
            if (parseInt(b, 10) >= parseInt(a, 10)) pairs++;
        }
        return (checked && pairs / checked >= 0.9) ? 3 : 1;
    }

    function duplicateIds(rows, api) {
        var header = rows.length && rows[0].slice(1).every(function (c) { return api.isPythonFloat(String(c)); })
            ? null : rows[0];
        var body = header ? rows.slice(1) : rows;
        var idCols = idColumnCount(body);
        var seen = Object.create(null), dupes = 0, example = null;
        for (var i = 0; i < body.length; i++) {
            var key = body[i].slice(0, idCols).map(function (c) { return String(c).trim(); }).join("\t");
            if (key.replace(/\t/g, "") === "") continue;
            if (seen[key]) { dupes++; if (!example) example = key.replace(/\t/g, ":"); }
            else seen[key] = true;
        }
        return { count: dupes, example: example };
    }

    function duplicatesAcknowledged(name, manifest, context) {
        var re = /duplicat|repeat|site|isoform|kept as|keep them|as they are|collaps|averag|one row per/i;
        if (context && Array.isArray(context.instructions) && context.instructions.some(function (t) { return re.test(t); })) return true;
        if (context && context.answers && Object.keys(context.answers).some(function (k) {
            return re.test(k) || re.test(String(context.answers[k])); })) return true;
        if (!manifest) return false;
        if (re.test(String(manifest.summary || ""))) return true;
        return (manifest.files || []).some(function (f) {
            return f && f.name === name && re.test(String(f.note || "") + " " + String(f.label || ""));
        });
    }

    function gradeOutputs(outputs, api, context) {
        var reports = {};
        var declared = api.rolesFromManifest ? api.rolesFromManifest(outputs, decodeText) : {};
        // The manifest describes the output; it is not part of it.
        var names = Object.keys(outputs || {}).filter(function (n) { return n !== "manifest.json"; });
        if (!names.length) {
            return { ok: false, reports: reports,
                     summary: "The script produced no files in /out." };
        }
        var failures = [];
        var manifest = parseManifest(outputs);
        if (outputs && outputs["manifest.json"] && !manifest) {
            failures.push("manifest.json is not valid JSON.");
        }
        if (manifest && Array.isArray(manifest.files)) {
            manifest.files.forEach(function (f) {
                if (f && f.name && !outputs[f.name]) {
                    failures.push("manifest.json lists " + f.name + " but the script did not write it.");
                }
            });
        }
        names.forEach(function (name) {
            var text = decodeText(outputs[name]);
            var read = api.readDelimited(encodeText(text));
            var role = declared[name] ||
                       (api.roleForFileName ? api.roleForFileName(name) : "values");
            var report = api.validateForRole
                ? api.validateForRole(role, read.rows)
                : api.validateValues(read.rows);
            report.role = role;
            reports[name] = report;
            if (!report.ok) {
                failures.push(name + " (" + role + "): " +
                    report.problems.slice(0, 3).map(function (p) {
                        return "line " + p.line + " " + p.code + " — " + p.detail;
                    }).join("; "));
            } else if (role === "values" && read.rows.length) {
                var dup = duplicateIds(read.rows, api);
                if (dup.count > 0 && !duplicatesAcknowledged(name, manifest, context)) {
                    failures.push(name + " (values): " + dup.count + " duplicate identifiers (e.g. " +
                        dup.example + "). Ask the user how to handle them — a \"question\" action offering " +
                        "\"average the duplicates\", \"keep the first occurrence\" and \"keep them as they are\" — " +
                        "or, if they are intentional (one row per site/isoform), say so in the manifest note.");
                }
            }
        });
        var values = names.filter(function (n) { return (reports[n] || {}).role === "values"; });
        if (!values.length && !(manifest && /no (expression|measurement)/i.test(manifest.summary || ""))) {
            // A run that produced only lists must say why in its summary; the
            // user is converting a file they believe holds measurements.
            if (!names.some(function (n) { return /relevant|design|association/.test((reports[n] || {}).role || ""); })) {
                failures.push("No values matrix was produced and the manifest does not explain why.");
            }
        }
        return {
            ok: failures.length === 0,
            reports: reports,
            manifest: manifest,
            summary: failures.length ? failures.join("\n") : "All output files pass validation."
        };
    }

    /*
     * Whether the loop should ask about duplicate identifiers before it starts.
     * True only when a SINGLE-table file has duplicates in its first identifier
     * candidate that nothing explains: no other text column to group by, and
     * not the (chromosome, start, end) triple of a region matrix. A workbook of
     * several sheets, or a table with a category column, is left to the model.
     */
    function needsDuplicateDecision(profile, state) {
        if (state.answers && state.answers.duplicate_identifiers) return false;
        var re = /duplicat|repeat|average|first occurrence|as they are/i;
        if ((state.instructions || []).some(function (t) { return re.test(t); })) return false;
        var tables = (profile && profile.tables) || [];
        if (tables.length !== 1) return false;              // a workbook: the model decides per sheet
        var t = tables[0];
        var exact = t.exact || {};
        var cands = exact.id_candidates || [];
        if (!cands.length || !(cands[0].duplicates > 0)) return false;
        // A second text column could explain the repeats (tidy long format).
        var cols = t.columns || [];
        var idIndex = cands[0].index;
        var otherText = cols.some(function (c) {
            return c.index !== idIndex && c.kind === "text";
        });
        if (otherText) return false;
        // A region matrix identifies a feature by chromosome + start + end, so
        // the chromosome column repeating is expected. Detect it from the
        // sample rows by the coordinate-pair shape (works whether the
        // chromosome reads as "1" or "chr1").
        var rows = t.first_rows || [];
        var body = (t.header_row === null || t.header_row === undefined)
            ? rows : rows.slice(t.header_row + 1);
        if (idColumnCount(body) >= 3) return false;
        return true;
    }

    /*
     * options:
     *   api, sandbox, transport, files {name: Uint8Array}, inputPath, fileName,
     *   omicType, species, goal, onEvent, ask(question) -> Promise<string>,
     *   maxAttempts, instructions [string], accepted {code, manifest} (revision),
     *   answers {field: answer}
     */
    async function runAgent(options) {
        var api = options.api;
        var sandbox = options.sandbox;
        var transport = options.transport;
        var onEvent = options.onEvent;
        var maxAttempts = options.maxAttempts || DEFAULT_MAX_ATTEMPTS;
        var files = options.files;                 // {name: Uint8Array}
        var history = [];

        var profile = options.profile || null;
        if (!profile) {
            step(onEvent, "profiling", "Reading your file",
                 "Working out its structure. Measurements stay on this computer; only " +
                 "column names, counts and a few example rows describe the file.",
                 1, maxAttempts);

            var profileRun = await sandbox.run(api.PROFILE_CODE, files);
            if (!profileRun.ok) {
                emit(onEvent, { type: "failed", reason: "profile", traceback: profileRun.traceback });
                return { ok: false, stage: "profile", traceback: profileRun.traceback, history: history };
            }
            try {
                profile = JSON.parse(profileRun.stdout.trim().split("\n").pop());
            } catch (e) {
                emit(onEvent, { type: "failed", reason: "profile", traceback: "The profiler returned no description." });
                return { ok: false, stage: "profile", traceback: profileRun.stdout, history: history };
            }

            // The description as the model will receive it, for the UI to show:
            // "what the AI sees" is only checkable if the user can see it too.
            emit(onEvent, { type: "profile", profile: profile });

            var tableNote = (profile.tables || []).map(function (t) {
                if (t.empty) return t.name + ": empty";
                var rows = t.exact ? t.exact.data_rows : t.sampled_rows;
                return t.name + ": " + rows + " rows × " + t.n_columns + " columns";
            }).join(" · ");
            if (profile.parse_error) tableNote = "Could not parse it as a table yet: " + profile.parse_error;
            step(onEvent, "profiling", "Structure found", tableNote, 1, maxAttempts);
        }

        var sample = sampleFiles(files);
        var state = {
            goal: options.goal,
            omicType: options.omicType,
            species: options.species,
            fileName: options.fileName,
            inputPath: options.inputPath || ("/work/" + (options.fileName || "input")),
            sampleRows: sample ? SAMPLE_ROWS : null,
            profile: profile,
            history: history,
            answers: options.answers || {},
            instructions: options.instructions || [],
            accepted: options.accepted || null
        };

        /*
         * Duplicate identifiers are a decision only the user can make, and a
         * small model does not reliably raise it. When the profile shows the
         * identifier column repeats AND nothing in the file explains the
         * repeats -- no second text column to group by, and not the coordinate
         * triple of a region matrix -- ask here, deterministically, before the
         * model writes anything. A tidy table whose repeats ARE explained by a
         * category column is left to the model, which pivots it.
         */
        if (!state.accepted && needsDuplicateDecision(profile, state)) {
            step(onEvent, "asking", "Repeated identifiers",
                 "The identifier column has repeated values that nothing else in the file explains.",
                 1, maxAttempts);
            var dupAnswer = await options.ask({
                text: "Some feature identifiers appear more than once, and no other column explains it. " +
                      "How should the duplicates be handled?",
                field: "duplicate_identifiers",
                options: ["Average the duplicates", "Keep the first occurrence", "Keep them as they are"]
            });
            state.answers.duplicate_identifiers = dupAnswer;
            state.instructions = state.instructions.concat(
                ["The identifier column has duplicates. The user chose: \"" + dupAnswer +
                 "\". Apply exactly that when building the matrix."]);
            history.push({ attempt: 0, question: "duplicate identifiers", answer: dupAnswer });
        }

        var best = null;

        for (var attempt = 1; attempt <= maxAttempts; attempt++) {
            step(onEvent, "thinking",
                 attempt === 1 ? (state.accepted ? "Revising the conversion" : "Planning the conversion")
                               : "Adjusting the conversion",
                 attempt === 1 ? "" : "Using the previous error to correct the script.",
                 attempt, maxAttempts);

            var action = await transport(state);

            if (!action || !action.type) {
                history.push({ attempt: attempt, error: "unparseable action" });
                continue;
            }

            if (action.type === "question") {
                step(onEvent, "asking", "Needs your input", action.text, attempt, maxAttempts);
                var answer = await options.ask(action);
                state.answers[action.field || ("q" + attempt)] = answer;
                history.push({ attempt: attempt, question: action.text, answer: answer });
                attempt--;                          // a question is not an attempt
                continue;
            }

            if (action.type === "done") {
                break;
            }

            if (action.type !== "code") {
                history.push({ attempt: attempt, error: "unknown action " + action.type });
                continue;
            }

            emit(onEvent, { type: "code", code: action.python, attempt: attempt });
            step(onEvent, "running", "Running the conversion",
                 (action.summary || "Executing the script") +
                 (sample ? " — on the first " + SAMPLE_ROWS.toLocaleString() + " rows." : "."),
                 attempt, maxAttempts);

            var run = await sandbox.run(action.python, sample || files);

            if (!run.ok) {
                step(onEvent, "running", "The script failed",
                     String(run.traceback || "").trim().split("\n").pop(), attempt, maxAttempts);
                history.push({ attempt: attempt, code: action.python,
                               traceback: run.traceback });
                state.history = history;
                continue;
            }

            // Whatever the script printed, beside the script that printed it.
            if (run.stdout && String(run.stdout).trim()) {
                emit(onEvent, { type: "output", stdout: run.stdout, attempt: attempt });
            }

            step(onEvent, "validating", "Checking the result",
                 "Against the exact format PaintOmics accepts.", attempt, maxAttempts);

            var grade = gradeOutputs(run.outputs, api, { answers: state.answers, instructions: state.instructions });
            history.push({ attempt: attempt, code: action.python, stdout: run.stdout,
                           valid: grade.ok, validation: grade.summary });
            state.history = history;

            if (!grade.ok) {
                if (!best) best = { outputs: run.outputs, reports: grade.reports,
                                    manifest: grade.manifest, code: action.python,
                                    stdout: run.stdout, valid: false };
                step(onEvent, "validating", "Not accepted yet", grade.summary,
                     attempt, maxAttempts);
                continue;
            }

            // Accepted on the sample: now the whole file, once.
            if (sample) {
                step(onEvent, "finalising", "Applying it to the whole file",
                     "The script passed on the sample; running it on every row now.",
                     attempt, maxAttempts);
                var full = await sandbox.run(action.python, files);
                if (!full.ok) {
                    step(onEvent, "running", "The script failed on the whole file",
                         String(full.traceback || "").trim().split("\n").pop(), attempt, maxAttempts);
                    history.push({ attempt: attempt, code: action.python, full: true,
                                   traceback: full.traceback });
                    state.history = history;
                    continue;
                }
                var fullGrade = gradeOutputs(full.outputs, api, { answers: state.answers, instructions: state.instructions });
                history.push({ attempt: attempt, code: action.python, full: true,
                               stdout: full.stdout, valid: fullGrade.ok,
                               validation: fullGrade.summary });
                state.history = history;
                if (!fullGrade.ok) {
                    step(onEvent, "validating", "Not accepted on the whole file",
                         fullGrade.summary, attempt, maxAttempts);
                    continue;
                }
                run = full;
                grade = fullGrade;
            }

            best = { outputs: run.outputs, reports: grade.reports, manifest: grade.manifest,
                     code: action.python, stdout: run.stdout, valid: true };
            emit(onEvent, { type: "step", phase: "done", title: "Converted",
                            detail: Object.keys(run.outputs).filter(function (n) {
                                return n !== "manifest.json";
                            }).join(", "),
                            attempt: attempt, maxAttempts: maxAttempts, progress: 1 });
            return { ok: true, attempts: attempt, outputs: run.outputs,
                     reports: grade.reports, manifest: grade.manifest,
                     code: action.python, stdout: run.stdout, history: history,
                     profile: profile, answers: state.answers,
                     instructions: state.instructions };
        }

        emit(onEvent, { type: "exhausted", attempts: maxAttempts, best: !!best });
        return {
            ok: false, stage: "attempts", attempts: maxAttempts,
            outputs: best ? best.outputs : null,
            reports: best ? best.reports : null,
            manifest: best ? best.manifest : null,
            code: best ? best.code : null,
            history: history, profile: profile, answers: state.answers,
            instructions: state.instructions
        };
    }

    return { runAgent: runAgent, gradeOutputs: gradeOutputs, parseManifest: parseManifest,
             sampleOf: sampleOf, SAMPLE_ROWS: SAMPLE_ROWS };
});
