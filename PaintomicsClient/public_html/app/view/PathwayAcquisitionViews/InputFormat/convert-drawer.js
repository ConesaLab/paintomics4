/*
 * The conversion drawer: what the user watches while the agent works, and
 * where they review what it made and steer it.
 *
 * It is a transcript, not a spinner. Every step the agent takes is named as it
 * happens, the generated code is available at each one, and the bar advances
 * against the attempt budget, which is a real quantity rather than a guess at
 * completion.
 *
 * When the agent finishes, the drawer does not simply hand back "a file". A
 * real upload often holds several tables -- one per sheet, one per measurement
 * family -- and a significance column that should become the relevant-features
 * list. So the review shows every table the agent produced with a preview, the
 * columns it kept and dropped, and lets the user choose which one goes into
 * this omic box, attach the relevant list, add the others as separate omics,
 * or download any of them. Nothing the file held is silently lost.
 *
 * And the user can talk back. A composer at the bottom sends an instruction
 * ("keep the flagged genes", "the first column is a KEGG ID", "use the reads
 * sheet, not TPM") and the agent revises the accepted script rather than
 * starting over. The same composer answers a question in the user's own words
 * when none of the offered options fit.
 *
 * Nothing here is decorative. Showing the code is what lets a bioinformatician
 * check the transformation; showing the validator's report is what stops the
 * model grading its own work.
 */
(function (root, factory) {
    if (typeof module === "object" && module.exports) module.exports = factory();
    else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var API = null;
    function api() { return API || (API = window.PaintomicsInputFormat); }

    /* Pyodide's filesystem takes a plain name; a user's file name may not be
       one. Keep the extension, because the reader dispatches on it. */
    function safeName(name) {
        var cleaned = String(name).replace(/[^A-Za-z0-9._-]/g, "_").replace(/^\.+/, "");
        return cleaned.length ? cleaned.slice(-80) : "input";
    }

    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text !== undefined && text !== null) n.textContent = text;
        return n;
    }

    function decode(bytes) {
        return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    }

    var PHASE_ICON = {
        profiling: "◴", thinking: "✦", running: "▶", validating: "✓", finalising: "⇶",
        asking: "?", done: "✓", failed: "✕", user: "✎"
    };

    /* ------------------------------------------------------------------ *
     * Sandbox host
     * ------------------------------------------------------------------ */

    function createSandbox(onProgress) {
        var frame = document.createElement("iframe");
        // allow-scripts WITHOUT allow-same-origin: opaque origin, so the code
        // the model writes cannot read cookies, localStorage, this page, or the
        // network. Verified by an isolation probe in inputformat-sandbox.html.
        frame.setAttribute("sandbox", "allow-scripts");
        frame.className = "pa-convert-sandbox";
        frame.src = "inputformat-sandbox.html";
        document.body.appendChild(frame);

        var next = 1;
        var waiters = {};
        var loaded = false;
        var loadedWaiters = [];

        function onMessage(event) {
            if (event.source !== frame.contentWindow) return;
            var msg = event.data || {};
            if (msg.type === "loaded") {
                loaded = true;
                loadedWaiters.splice(0).forEach(function (fn) { fn(); });
                return;
            }
            if (msg.id && waiters[msg.id]) { waiters[msg.id](msg); delete waiters[msg.id]; }
        }
        window.addEventListener("message", onMessage);

        function ready() {
            return loaded ? Promise.resolve()
                          : new Promise(function (res) { loadedWaiters.push(res); });
        }

        function send(payload, timeoutMs) {
            return new Promise(function (resolve, reject) {
                var id = next++;
                waiters[id] = resolve;
                setTimeout(function () {
                    if (waiters[id]) { delete waiters[id]; reject(new Error("The sandbox stopped responding.")); }
                }, timeoutMs || 180000);
                payload.id = id;
                frame.contentWindow.postMessage(payload, "*");
            });
        }

        return {
            async boot() {
                await ready();
                if (onProgress) onProgress("Starting the Python sandbox…");
                return send({ type: "boot" }, 240000);
            },
            run: function (code, files) {
                return send({ type: "run", code: code, files: files }, 300000).then(function (r) {
                    return r.ok ? { ok: true, stdout: r.stdout, outputs: r.outputs }
                                : { ok: false, traceback: r.traceback, stdout: r.stdout || "" };
                });
            },
            destroy: function () {
                window.removeEventListener("message", onMessage);
                // A fresh interpreter per conversion: nothing a previous run
                // defined, imported or left in /out can affect the next one.
                if (frame.parentNode) frame.parentNode.removeChild(frame);
            }
        };
    }

    /* ------------------------------------------------------------------ *
     * Transport
     * ------------------------------------------------------------------ */

    function serverTransport() {
        return async function (state) {
            var res = await fetch("input_convert/turn", {
                method: "POST", credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(state)
            });
            var body = await res.json();
            if (!body || !body.ticket) {
                // ServerErrorManager answers with `message`, prefixed by the
                // file and function it was raised in; the readable half is
                // after "ERROR MESSAGE:". Same split PA_Step1Views already does,
                // so a disabled server says so plainly instead of "refused".
                var raw = (body && (body.errorMessage || body.message)) || "";
                var half = raw.split("ERROR MESSAGE:");
                var reason = (half.length > 1 ? half[1] : raw).trim();
                throw new Error(reason || "The conversion service refused the request.");
            }
            // Poll rather than hold a request open: the site has four request
            // threads and the gateway takes about a minute.
            for (var i = 0; i < 240; i++) {
                await new Promise(function (r) { setTimeout(r, 1000); });
                var poll = await fetch("input_convert/turn/" + encodeURIComponent(body.ticket),
                                       { credentials: "same-origin" });
                var p = await poll.json();
                if (p.state === "done") return p.action;
                if (p.state === "error") throw new Error("The conversion service failed on that step.");
            }
            throw new Error("The conversion timed out.");
        };
    }

    /* ------------------------------------------------------------------ *
     * Talking to the Step 1 form
     * ------------------------------------------------------------------ */

    function setFile(inputEl, bytes, name) {
        var transfer = new DataTransfer();
        transfer.items.add(new File([bytes], name, { type: "text/plain" }));
        inputEl.files = transfer.files;
        inputEl.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function download(bytes, name) {
        var url = URL.createObjectURL(new Blob([bytes], { type: "text/tab-separated-values" }));
        var a = document.createElement("a");
        a.href = url; a.download = name;
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 0);
    }

    function omicComponentOf(inputEl) {
        var box = inputEl && inputEl.closest ? inputEl.closest(".omicbox") : null;
        return (box && window.Ext && Ext.getCmp) ? Ext.getCmp(box.id) : null;
    }

    function fileInputIn(component, itemId) {
        var selector = component && component.queryById ? component.queryById(itemId) : null;
        var field = selector && selector.queryById ? selector.queryById("fileField") : null;
        return field && field.fileInputEl ? field.fileInputEl.dom : null;
    }

    var PANEL_TYPE = {
        "gene expression": "geneexpression", "proteomics": "proteomics",
        "metabolomics": "metabolomics", "mirna-seq": "mirnaseq", "dnase-seq": "dnaseseq",
        "transcription factor": "transcriptionfactor"
    };

    /*
     * Adds a sibling omic box of the same type and puts a converted table in
     * it. Returns false when the Step 1 view is not reachable, so the caller
     * can fall back to a download rather than lose the table.
     */
    function addAsNewOmic(omicType, omicName, values, relevant) {
        try {
            var view = window.application && application.getMainView
                ? application.getMainView().getSubView("PA_Step1JobView") : null;
            if (!view || !view.addNewOmicSubmittingPanel) return false;
            var panel = view.addNewOmicSubmittingPanel(
                PANEL_TYPE[String(omicType).toLowerCase()] || "otheromic");
            if (!panel || !panel.getComponent) return false;
            var component = panel.getComponent();
            var fill = function () {
                var nameField = component.queryById("omicNameField");
                if (nameField && nameField.setValue) nameField.setValue(omicName);
                var main = fileInputIn(component, "mainFileSelector");
                if (main) setFile(main, values.bytes, values.name);
                var secondary = fileInputIn(component, "secondaryFileSelector");
                if (relevant && secondary) setFile(secondary, relevant.bytes, relevant.name);
            };
            if (component.rendered) fill(); else component.on("afterrender", fill, null, { single: true });
            return true;
        } catch (e) {
            if (window.console && console.warn) console.warn("[inputformat] add omic failed", e);
            return false;
        }
    }

    /* ------------------------------------------------------------------ *
     * Reading the manifest
     * ------------------------------------------------------------------ */

    function describeOutputs(result) {
        var manifest = result.manifest || api().parseManifest(result.outputs) || {};
        var declared = {};
        (manifest.files || []).forEach(function (f) { if (f && f.name) declared[f.name] = f; });
        var files = Object.keys(result.outputs || {})
            .filter(function (n) { return n !== "manifest.json"; })
            .map(function (name) {
                var info = declared[name] || {};
                var report = (result.reports || {})[name] || {};
                var bytes = result.outputs[name];
                var text = decode(bytes);
                var lines = text.split(/\r?\n/).filter(function (l) { return l.trim() !== ""; });
                var rows = lines.slice(0, 7).map(function (l) { return l.split("\t"); });
                var header = rows.length && !api().isPythonFloat(String(rows[0][1] || "")) ? rows[0] : null;
                return {
                    name: name, bytes: bytes, role: info.role || report.role || "values",
                    label: info.label || name, source: info.source || "", note: info.note || "",
                    kept: info.columns_kept || [], dropped: info.columns_dropped || [],
                    rowsIn: info.rows_in, rowsOut: info.rows_out,
                    recommended: !!info.recommended, relevantFor: info.relevant_for || null,
                    nRows: (report.summary && report.summary.nRows) || (lines.length - (header ? 1 : 0)),
                    nCols: (report.summary && report.summary.nCols) || (rows[0] ? rows[0].length : 0),
                    preview: { header: header, rows: header ? rows.slice(1, 6) : rows.slice(0, 5) }
                };
            });
        return { manifest: manifest, files: files,
                 values: files.filter(function (f) { return f.role === "values"; }),
                 lists: files.filter(function (f) { return f.role === "relevant"; }),
                 others: files.filter(function (f) { return f.role !== "values" && f.role !== "relevant"; }) };
    }

    /* ------------------------------------------------------------------ *
     * The drawer
     * ------------------------------------------------------------------ */

    function openDrawer(input, file, fieldName, context) {
        var overlay = el("div", "pa-convert-overlay");
        var panel = el("section", "pa-convert-panel");
        panel.setAttribute("role", "dialog");
        panel.setAttribute("aria-label", "Convert " + file.name);

        // ---- header -------------------------------------------------------
        var header = el("header", "pa-convert-header");
        var title = el("div", "pa-convert-title");
        if (typeof window.getAIMark === "function") {
            var mark = el("span", "pa-convert-mark");
            mark.innerHTML = window.getAIMark();
            title.appendChild(mark);
        }
        var titles = el("div", "pa-convert-titles");
        titles.appendChild(el("h2", null, "Converting your file"));
        titles.appendChild(el("p", "pa-convert-filename", file.name));
        title.appendChild(titles);
        header.appendChild(title);

        var close = el("button", "pa-convert-close", "✕");
        close.type = "button";
        close.setAttribute("aria-label", "Cancel conversion");
        header.appendChild(close);
        panel.appendChild(header);

        // ---- progress -----------------------------------------------------
        var progressWrap = el("div", "pa-convert-progress");
        var bar = el("div", "pa-convert-bar");
        var fill = el("div", "pa-convert-fill");
        bar.appendChild(fill);
        progressWrap.appendChild(bar);
        var progressText = el("div", "pa-convert-progress-text", "Starting…");
        progressWrap.appendChild(progressText);
        var elapsed = el("span", "pa-convert-elapsed", "0s");
        progressWrap.appendChild(elapsed);
        panel.appendChild(progressWrap);

        // ---- transcript + review ------------------------------------------
        var body = el("div", "pa-convert-body");
        var steps = el("ol", "pa-convert-steps");
        body.appendChild(steps);
        var reviewHost = el("div", "pa-convert-reviewhost");
        body.appendChild(reviewHost);
        panel.appendChild(body);

        // ---- composer -----------------------------------------------------
        var composer = el("form", "pa-convert-composer");
        var composerInput = el("textarea", "pa-convert-composer-input");
        composerInput.rows = 1;
        composerInput.placeholder = "Tell the AI what to change — e.g. “keep the flagged genes”, “use the reads sheet”, “column A is a KEGG ID”";
        composerInput.setAttribute("aria-label", "Instruction for the AI");
        var composerSend = el("button", "pa-convert-composer-send", "Revise");
        composerSend.type = "submit";
        composer.appendChild(composerInput);
        composer.appendChild(composerSend);
        var composerHint = el("div", "pa-convert-composer-hint",
            "Your words go to the AI as an instruction; the script is revised and re-checked. Your data stays on this computer.");
        panel.appendChild(composer);
        panel.appendChild(composerHint);

        var footer = el("footer", "pa-convert-footer");
        panel.appendChild(footer);

        overlay.appendChild(panel);
        document.body.appendChild(overlay);
        requestAnimationFrame(function () { overlay.classList.add("pa-convert-open"); });

        var startedAt = Date.now();
        var timer = setInterval(function () {
            var s = Math.round((Date.now() - startedAt) / 1000);
            elapsed.textContent = s < 60 ? s + "s" : Math.floor(s / 60) + "m " + (s % 60) + "s";
        }, 1000);

        var currentStep = null;
        var running = false;
        var cancelled = false;
        var last = null;                     // the latest agent result
        var pendingAnswer = null;            // resolver while a question is open

        function addStep(event) {
            var li = el("li", "pa-convert-step pa-phase-" + event.phase);
            var icon = el("span", "pa-convert-icon", PHASE_ICON[event.phase] || "•");
            li.appendChild(icon);
            var content = el("div", "pa-convert-step-body");
            content.appendChild(el("div", "pa-convert-step-title", event.title));
            if (event.detail) content.appendChild(el("div", "pa-convert-step-detail", event.detail));
            li.appendChild(content);
            if (event.attempt > 1) {
                li.appendChild(el("span", "pa-convert-attempt",
                                  "try " + event.attempt + "/" + event.maxAttempts));
            }
            if (currentStep) currentStep.classList.remove("pa-convert-current");
            li.classList.add("pa-convert-current");
            currentStep = li;
            steps.appendChild(li);
            body.scrollTop = body.scrollHeight;
            return li;
        }

        function setProgress(fraction, label) {
            fill.style.width = Math.round(Math.max(0.02, Math.min(1, fraction)) * 100) + "%";
            if (label) progressText.textContent = label;
        }

        function attachCode(code) {
            if (!currentStep) return;
            var toggle = el("button", "pa-convert-codetoggle", "▸ show the code");
            toggle.type = "button";
            var pre = el("pre", "pa-convert-code");
            pre.appendChild(el("code", null, code));
            pre.hidden = true;
            toggle.addEventListener("click", function () {
                pre.hidden = !pre.hidden;
                toggle.textContent = (pre.hidden ? "▸ show" : "▾ hide") + " the code";
            });
            currentStep.querySelector(".pa-convert-step-body").appendChild(toggle);
            currentStep.querySelector(".pa-convert-step-body").appendChild(pre);
        }

        function setComposerState(state) {
            // "idle": revise the result; "asking": answer in your own words; "busy": wait.
            composerInput.disabled = state === "busy";
            composerSend.disabled = state === "busy";
            composerSend.textContent = state === "asking" ? "Answer" : "Revise";
            composerInput.placeholder = state === "asking"
                ? "…or answer in your own words"
                : "Tell the AI what to change — e.g. “keep the flagged genes”, “use the reads sheet”, “column A is a KEGG ID”";
            composer.classList.toggle("pa-convert-composer-busy", state === "busy");
        }

        function askUser(question) {
            return new Promise(function (resolve) {
                var card = el("div", "pa-convert-question");
                card.appendChild(el("p", "pa-convert-question-text", question.text));
                var opts = el("div", "pa-convert-options");
                var settle = function (answer) {
                    card.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
                    card.appendChild(el("div", "pa-convert-answer", "You chose: " + answer));
                    pendingAnswer = null;
                    setComposerState("busy");
                    resolve(answer);
                };
                (question.options && question.options.length
                    ? question.options : ["Use your best judgement"]).forEach(function (opt) {
                    var b = el("button", "pa-convert-option", opt);
                    b.type = "button";
                    b.addEventListener("click", function () {
                        b.classList.add("pa-convert-option-chosen");
                        settle(opt);
                    });
                    opts.appendChild(b);
                });
                card.appendChild(opts);
                currentStep.querySelector(".pa-convert-step-body").appendChild(card);
                body.scrollTop = body.scrollHeight;
                pendingAnswer = settle;
                setComposerState("asking");
                composerInput.focus();
            });
        }

        var sandbox = createSandbox(function (msg) { setProgress(0.03, msg); });

        function shutdown() {
            clearInterval(timer);
            try { sandbox.destroy(); } catch (e) { /* already gone */ }
            overlay.classList.remove("pa-convert-open");
            setTimeout(function () {
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
            }, 200);
        }

        close.addEventListener("click", function () { cancelled = true; shutdown(); });

        var bytes = null;
        var fileKey = safeName(file.name) || "input";

        function onEvent(event) {
            if (cancelled) return;
            if (event.type === "step") {
                addStep(event);
                setProgress(event.progress, event.title);
            } else if (event.type === "code") {
                attachCode(event.code);
            }
        }

        async function runOnce(extra) {
            running = true;
            setComposerState("busy");
            footer.innerHTML = "";
            reviewHost.innerHTML = "";
            var result = await api().runAgent(Object.assign({
                api: api(),
                sandbox: sandbox,
                transport: serverTransport(),
                files: (function () { var f = {}; f[fileKey] = bytes; return f; })(),
                inputPath: "/work/" + fileKey,
                fileName: file.name,
                omicType: (context && context.omicType) || "unknown",
                species: (context && context.species) || "unknown",
                goal: "Convert this file into the format PaintOmics accepts, keeping every measurement it holds.",
                ask: askUser,
                onEvent: onEvent
            }, extra || {}));
            running = false;
            if (cancelled) return result;
            last = result;
            renderReview(result);
            setComposerState("idle");
            return result;
        }

        async function revise(instruction) {
            if (!last) return;
            addStep({ phase: "user", title: "Your instruction", detail: instruction });
            setProgress(0.1, "Revising");
            var instructions = (last.instructions || []).concat([instruction]);
            await runOnce({
                profile: last.profile,
                instructions: instructions,
                answers: last.answers || {},
                accepted: last.code ? { code: last.code, manifest: last.manifest } : null
            });
        }

        composer.addEventListener("submit", function (event) {
            event.preventDefault();
            var text = composerInput.value.trim();
            if (!text) return;
            composerInput.value = "";
            if (pendingAnswer) { pendingAnswer(text); return; }
            if (running) return;
            revise(text);
        });
        composerInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                composer.requestSubmit ? composer.requestSubmit() : composer.dispatchEvent(new Event("submit"));
            }
        });

        return (async function () {
            try {
                setComposerState("busy");
                await sandbox.boot();
                setProgress(0.05, "Reading your file");
                bytes = new Uint8Array(await file.arrayBuffer());
                return await runOnce();
            } catch (err) {
                if (!cancelled) {
                    addStep({ phase: "failed", title: "The conversion could not finish",
                              detail: String(err && err.message || err) });
                    setProgress(1, "Stopped");
                    renderFailure(null);
                    setComposerState(last ? "idle" : "busy");
                }
                return { ok: false };
            }
        })();

        /* ---- review ---------------------------------------------------- */

        function previewTable(preview) {
            var wrap = el("div", "pa-convert-preview");
            var table = el("table");
            var maxCols = 7;
            var cols = preview.header ? preview.header.length : (preview.rows[0] || []).length;
            var shown = Math.min(cols, maxCols);
            if (preview.header) {
                var tr = el("tr");
                preview.header.slice(0, shown).forEach(function (h) { tr.appendChild(el("th", null, h)); });
                if (cols > shown) tr.appendChild(el("th", "pa-convert-more", "+" + (cols - shown)));
                table.appendChild(tr);
            }
            preview.rows.forEach(function (r) {
                var tr = el("tr");
                r.slice(0, shown).forEach(function (c, i) { tr.appendChild(el("td", i === 0 ? "pa-convert-id" : null, c)); });
                if (cols > shown) tr.appendChild(el("td", "pa-convert-more", "…"));
                table.appendChild(tr);
            });
            wrap.appendChild(table);
            return wrap;
        }

        function chips(label, names, cls) {
            if (!names || !names.length) return null;
            var box = el("div", "pa-convert-chips " + (cls || ""));
            box.appendChild(el("span", "pa-convert-chips-label", label));
            names.slice(0, 12).forEach(function (n) { box.appendChild(el("span", "pa-convert-chip", n)); });
            if (names.length > 12) box.appendChild(el("span", "pa-convert-chip pa-convert-chip-more", "+" + (names.length - 12) + " more"));
            return box;
        }

        function renderReview(result) {
            clearInterval(timer);
            if (!result.ok) { renderFailure(result); return; }
            setProgress(1, "Ready to review");

            var out = describeOutputs(result);
            var review = el("section", "pa-convert-review");
            review.appendChild(el("h3", null, out.values.length > 1
                ? out.values.length + " tables ready" : "Converted"));
            if (out.manifest.summary) review.appendChild(el("p", "pa-convert-summary", out.manifest.summary));

            var chosen = out.values.filter(function (f) { return f.recommended; })[0] || out.values[0];
            var addOthers = false;

            out.values.forEach(function (f) {
                var card = el("article", "pa-convert-card" + (f === chosen ? " pa-convert-card-chosen" : ""));
                var head = el("header", "pa-convert-card-head");
                var pick = el("label", "pa-convert-pick");
                var radio = document.createElement("input");
                radio.type = "radio"; radio.name = "pa-convert-choice"; radio.checked = f === chosen;
                radio.addEventListener("change", function () {
                    chosen = f;
                    review.querySelectorAll(".pa-convert-card").forEach(function (c) { c.classList.remove("pa-convert-card-chosen"); });
                    card.classList.add("pa-convert-card-chosen");
                    syncFooter();
                });
                pick.appendChild(radio);
                var labels = el("div", "pa-convert-card-titles");
                labels.appendChild(el("div", "pa-convert-card-title", f.label));
                var meta = [f.source, f.nRows != null ? f.nRows.toLocaleString() + " rows" : null,
                            f.nCols ? (f.nCols - 1) + " conditions" : null].filter(Boolean).join(" · ");
                labels.appendChild(el("div", "pa-convert-card-meta", meta));
                pick.appendChild(labels);
                head.appendChild(pick);
                if (f.recommended) head.appendChild(el("span", "pa-convert-badge", "Recommended"));
                var dl = el("button", "pa-convert-iconbtn", "⤓");
                dl.type = "button"; dl.title = "Download " + f.name;
                dl.addEventListener("click", function () { download(f.bytes, f.name); });
                head.appendChild(dl);
                card.appendChild(head);

                card.appendChild(previewTable(f.preview));
                var kept = chips("Kept", f.kept, "pa-convert-kept");
                var dropped = chips("Left out", f.dropped, "pa-convert-dropped");
                if (kept) card.appendChild(kept);
                if (dropped) card.appendChild(dropped);
                if (f.note) card.appendChild(el("p", "pa-convert-card-note", f.note));
                var linked = out.lists.filter(function (l) { return l.relevantFor === f.name; });
                linked.forEach(function (l) {
                    var row = el("div", "pa-convert-linked");
                    row.appendChild(el("span", "pa-convert-linked-icon", "≡"));
                    row.appendChild(el("span", null, l.label + " — " + (l.nRows != null ? l.nRows.toLocaleString() : "?") +
                                                      " identifiers, attached as the relevant-features list" +
                                                      (l.note ? " (" + l.note + ")" : "")));
                    var ldl = el("button", "pa-convert-iconbtn", "⤓");
                    ldl.type = "button"; ldl.title = "Download " + l.name;
                    ldl.addEventListener("click", function () { download(l.bytes, l.name); });
                    row.appendChild(ldl);
                    card.appendChild(row);
                });
                review.appendChild(card);
            });

            var unlinked = out.lists.filter(function (l) {
                return !out.values.some(function (v) { return v.name === l.relevantFor; });
            });
            if (unlinked.length || out.others.length) {
                var extras = el("div", "pa-convert-extras");
                extras.appendChild(el("h4", null, out.values.length ? "Also produced" : "Produced"));
                unlinked.concat(out.others).forEach(function (f) {
                    var row = el("div", "pa-convert-linked");
                    row.appendChild(el("span", "pa-convert-linked-icon", f.role === "relevant" ? "≡" : "▤"));
                    row.appendChild(el("span", null, f.label + " — " + (f.nRows != null ? f.nRows.toLocaleString() + " rows" : "") +
                                                      (f.note ? " (" + f.note + ")" : "")));
                    var fdl = el("button", "pa-convert-iconbtn", "⤓");
                    fdl.type = "button"; fdl.title = "Download " + f.name;
                    fdl.addEventListener("click", function () { download(f.bytes, f.name); });
                    row.appendChild(fdl);
                    extras.appendChild(row);
                });
                review.appendChild(extras);
            }

            if (out.manifest.skipped && out.manifest.skipped.length) {
                var skipped = el("details", "pa-convert-skipped");
                skipped.appendChild(el("summary", null, "Not converted (" + out.manifest.skipped.length + ")"));
                out.manifest.skipped.forEach(function (s) {
                    skipped.appendChild(el("div", "pa-convert-skipped-row",
                        (s.source || "?") + " — " + (s.reason || "")));
                });
                review.appendChild(skipped);
            }

            if (out.values.length > 1) {
                var addLabel = el("label", "pa-convert-addothers");
                var addBox = document.createElement("input");
                addBox.type = "checkbox";
                addBox.addEventListener("change", function () { addOthers = addBox.checked; syncFooter(); });
                addLabel.appendChild(addBox);
                addLabel.appendChild(el("span", null, "Also add the other " + (out.values.length - 1) +
                    " table" + (out.values.length > 2 ? "s" : "") + " as separate omics, named after their source"));
                review.appendChild(addLabel);
            }

            reviewHost.innerHTML = "";
            reviewHost.appendChild(review);

            // ---- footer -------------------------------------------------
            var accept = el("button", "pa-convert-accept", "Use this table");
            accept.type = "button";
            var downloadAll = el("button", "pa-convert-dismiss", "Download all");
            downloadAll.type = "button";
            downloadAll.addEventListener("click", function () {
                out.files.forEach(function (f, i) { setTimeout(function () { download(f.bytes, f.name); }, i * 150); });
            });
            var dismiss = el("button", "pa-convert-dismiss", "Cancel");
            dismiss.type = "button";
            dismiss.addEventListener("click", function () { cancelled = true; shutdown(); });
            footer.innerHTML = "";
            if (out.values.length) footer.appendChild(accept);
            footer.appendChild(downloadAll);
            footer.appendChild(dismiss);

            function syncFooter() {
                accept.textContent = addOthers
                    ? "Use this table + add " + (out.values.length - 1) + " more"
                    : (out.values.length > 1 ? "Use this table" : "Use this file");
            }
            syncFooter();

            accept.addEventListener("click", function () {
                if (!chosen) return;
                var omicType = (context && context.omicType) || "Gene expression";
                var linkedList = out.lists.filter(function (l) { return l.relevantFor === chosen.name; })[0];
                var component = omicComponentOf(input);

                if (addOthers) {
                    // Keep names unique across the job: the server keys omics by name.
                    var nameField = component && component.queryById("omicNameField");
                    if (nameField && nameField.setValue) nameField.setValue(omicType + " (" + chosen.label + ")");
                    out.values.filter(function (v) { return v !== chosen; }).forEach(function (v) {
                        var vList = out.lists.filter(function (l) { return l.relevantFor === v.name; })[0];
                        var added = addAsNewOmic(omicType, omicType + " (" + v.label + ")", v, vList);
                        if (!added) { download(v.bytes, v.name); if (vList) download(vList.bytes, vList.name); }
                    });
                }
                setFile(input, chosen.bytes, chosen.name);
                var secondary = fileInputIn(component, "secondaryFileSelector");
                if (linkedList && secondary) setFile(secondary, linkedList.bytes, linkedList.name);
                shutdown();
            });
            body.scrollTop = reviewHost.offsetTop - 8;
        }

        function renderFailure(result) {
            setProgress(1, "Could not finish");
            var review = el("section", "pa-convert-review pa-convert-review-failed");
            review.appendChild(el("h3", null, "Could not finish this one"));
            review.appendChild(el("p", "pa-convert-summary",
                "Tell the AI what the file contains in the box below and it will try again — " +
                "which sheet matters, what the columns are, what the identifiers are. " +
                "The script it wrote is above; a colleague who knows pandas can take it from there."));
            if (result && result.outputs) {
                var out = describeOutputs(result);
                if (out.files.length) {
                    var p = el("p", "pa-convert-summary", "Its best attempt produced " + out.files.length + " file(s) that did not pass the check: ");
                    out.files.forEach(function (f) {
                        var b = el("button", "pa-convert-codetoggle", "⤓ " + f.name);
                        b.type = "button";
                        b.addEventListener("click", function () { download(f.bytes, f.name); });
                        p.appendChild(b);
                    });
                    review.appendChild(p);
                }
            }
            reviewHost.innerHTML = "";
            reviewHost.appendChild(review);
            footer.innerHTML = "";
            var dismiss = el("button", "pa-convert-dismiss", "Close");
            dismiss.type = "button";
            dismiss.addEventListener("click", function () { cancelled = true; shutdown(); });
            footer.appendChild(dismiss);
            body.scrollTop = body.scrollHeight;
        }
    }

    /*
     * The name format-panel.js looks for. It reads the omic's own type and the
     * chosen species off the form, because the model converts a metabolomics
     * file differently from a gene-expression one and would otherwise be
     * guessing from the file alone.
     */
    function openConvertDrawer(input, file, fieldName) {
        var prefix = String(fieldName || "").replace(/_file$/, "");
        function fieldValue(name) {
            if (!window.Ext || !Ext.ComponentQuery) return null;
            var f = Ext.ComponentQuery.query("[name=" + name + "]")[0];
            return f && f.getValue ? f.getValue() : null;
        }
        return openDrawer(input, file, fieldName, {
            omicType: fieldValue(prefix + "_omic_name") || "unknown",
            species: fieldValue("specie") || "unknown"
        });
    }

    return { openDrawer: openDrawer, openConvertDrawer: openConvertDrawer,
             createSandbox: createSandbox, describeOutputs: describeOutputs };
});
