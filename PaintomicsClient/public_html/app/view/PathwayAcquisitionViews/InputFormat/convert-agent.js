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
                     validating: 0.75, asking: 0.55, finalising: 0.9, done: 1 }[phase] || 0;
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

    /*
     * Grade every produced file. A conversion that writes a beautiful values
     * matrix and a malformed relevant list has not succeeded, so the whole
     * output set has to pass, not the first file.
     */
    function gradeOutputs(outputs, api) {
        var reports = {};
        var declared = api.rolesFromManifest ? api.rolesFromManifest(outputs, decodeText) : {};
        // The manifest describes the output; it is not part of it.
        var names = Object.keys(outputs || {}).filter(function (n) { return n !== "manifest.json"; });
        if (!names.length) {
            return { ok: false, reports: reports,
                     summary: "The script produced no files in /out." };
        }
        var failures = [];
        names.forEach(function (name) {
            var text = decodeText(outputs[name]);
            var read = api.readDelimited(
                typeof TextEncoder !== "undefined"
                    ? new TextEncoder().encode(text)
                    : new Uint8Array(Buffer.from(text, "utf8")));
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
            }
        });
        return {
            ok: failures.length === 0,
            reports: reports,
            summary: failures.length ? failures.join("\n") : "All output files pass validation."
        };
    }

    async function runAgent(options) {
        var api = options.api;
        var sandbox = options.sandbox;
        var transport = options.transport;
        var onEvent = options.onEvent;
        var maxAttempts = options.maxAttempts || DEFAULT_MAX_ATTEMPTS;
        var files = options.files;                 // {name: Uint8Array}
        var history = [];

        step(onEvent, "profiling", "Reading your file",
             "Working out its structure without sending any measurements away.",
             1, maxAttempts);

        var profileRun = await sandbox.run(api.PROFILE_CODE, files);
        if (!profileRun.ok) {
            emit(onEvent, { type: "failed", reason: "profile", traceback: profileRun.traceback });
            return { ok: false, stage: "profile", traceback: profileRun.traceback, history: history };
        }
        var profile = JSON.parse(profileRun.stdout.trim().split("\n").pop());

        var tableNote = profile.tables.map(function (t) {
            return t.name + ": " + t.rows + " rows, " + t.columns.length + " columns";
        }).join(" · ");
        step(onEvent, "profiling", "Structure found", tableNote, 1, maxAttempts);

        var state = {
            goal: options.goal,
            omicType: options.omicType,
            species: options.species,
            fileName: options.fileName,
            inputPath: options.inputPath || ("/work/" + (options.fileName || "input")),
            sampleRows: SAMPLE_ROWS,
            profile: profile,
            history: history,
            answers: options.answers || {}
        };

        var best = null;

        for (var attempt = 1; attempt <= maxAttempts; attempt++) {
            step(onEvent, "thinking",
                 attempt === 1 ? "Planning the conversion" : "Adjusting the conversion",
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
                 action.summary || "Executing the script on a sample of your data.",
                 attempt, maxAttempts);

            var run = await sandbox.run(action.python, files);

            if (!run.ok) {
                step(onEvent, "running", "The script failed",
                     String(run.traceback || "").split("\n").pop(), attempt, maxAttempts);
                history.push({ attempt: attempt, code: action.python,
                               traceback: run.traceback });
                state.history = history;
                continue;
            }

            step(onEvent, "validating", "Checking the result",
                 "Against the exact format PaintOmics accepts.", attempt, maxAttempts);

            var grade = gradeOutputs(run.outputs, api);
            history.push({ attempt: attempt, code: action.python, stdout: run.stdout,
                           valid: grade.ok, validation: grade.summary });
            state.history = history;

            if (!best || grade.ok) {
                best = { outputs: run.outputs, reports: grade.reports,
                         code: action.python, stdout: run.stdout, valid: grade.ok };
            }

            if (grade.ok) {
                emit(onEvent, { type: "step", phase: "done", title: "Converted",
                                detail: Object.keys(run.outputs).join(", "),
                                attempt: attempt, maxAttempts: maxAttempts, progress: 1 });
                return { ok: true, attempts: attempt, outputs: run.outputs,
                         reports: grade.reports, code: action.python, history: history };
            }

            step(onEvent, "validating", "Not accepted yet", grade.summary,
                 attempt, maxAttempts);
        }

        emit(onEvent, { type: "exhausted", attempts: maxAttempts, best: !!best });
        return {
            ok: false, stage: "attempts", attempts: maxAttempts,
            outputs: best ? best.outputs : null,
            reports: best ? best.reports : null,
            code: best ? best.code : null,
            history: history
        };
    }

    return { runAgent: runAgent, gradeOutputs: gradeOutputs, SAMPLE_ROWS: SAMPLE_ROWS };
});
