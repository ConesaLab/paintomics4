/*
 * The conversion drawer: what the user watches while the agent works.
 *
 * It is a transcript, not a spinner. A gateway call takes on the order of a
 * minute, and a progress bar with nothing behind it is a lie told for that
 * whole minute -- so every step the agent takes is named as it happens, the
 * generated code is available at each one, and the bar advances against the
 * attempt budget, which is a real quantity rather than a guess at completion.
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

    var PHASE_ICON = {
        profiling: "◴", thinking: "✦", running: "▶", validating: "✓",
        asking: "?", finalising: "◴", done: "✓", failed: "✕"
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
                return send({ type: "run", code: code, files: files }, 240000).then(function (r) {
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
                throw new Error((body && body.errorMessage) || "The conversion service refused the request.");
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
        panel.appendChild(progressWrap);

        // ---- transcript ---------------------------------------------------
        var body = el("div", "pa-convert-body");
        var steps = el("ol", "pa-convert-steps");
        body.appendChild(steps);
        panel.appendChild(body);

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
        var elapsed = el("span", "pa-convert-elapsed", "0s");
        progressWrap.appendChild(elapsed);

        var currentStep = null;

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

        function askUser(question) {
            return new Promise(function (resolve) {
                var card = el("div", "pa-convert-question");
                card.appendChild(el("p", "pa-convert-question-text", question.text));
                var opts = el("div", "pa-convert-options");
                (question.options && question.options.length
                    ? question.options : ["Use your best judgement"]).forEach(function (opt) {
                    var b = el("button", "pa-convert-option", opt);
                    b.type = "button";
                    b.addEventListener("click", function () {
                        card.querySelectorAll("button").forEach(function (x) { x.disabled = true; });
                        b.classList.add("pa-convert-option-chosen");
                        resolve(opt);
                    });
                    opts.appendChild(b);
                });
                card.appendChild(opts);
                currentStep.querySelector(".pa-convert-step-body").appendChild(card);
                body.scrollTop = body.scrollHeight;
            });
        }

        var cancelled = false;
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

        return (async function () {
            try {
                await sandbox.boot();
                setProgress(0.05, "Reading your file");

                var bytes = new Uint8Array(await file.arrayBuffer());
                var result = await api().runAgent({
                    api: api(),
                    sandbox: sandbox,
                    transport: serverTransport(),
                    files: safeName(file.name) ? { [safeName(file.name)]: bytes } : { input: bytes },
                    inputPath: "/work/" + (safeName(file.name) || "input"),
                    fileName: file.name,
                    omicType: (context && context.omicType) || "unknown",
                    species: (context && context.species) || "unknown",
                    goal: "Convert this file into the format PaintOmics accepts.",
                    ask: askUser,
                    onEvent: function (event) {
                        if (cancelled) return;
                        if (event.type === "step") {
                            addStep(event);
                            setProgress(event.progress, event.title);
                        } else if (event.type === "code") {
                            attachCode(event.code);
                        }
                    }
                });

                if (cancelled) return { accepted: false };
                renderReview(result);
                return result;
            } catch (err) {
                if (!cancelled) {
                    addStep({ phase: "failed", title: "The conversion could not finish",
                              detail: String(err && err.message || err) });
                    setProgress(1, "Stopped");
                }
                return { ok: false };
            }
        })();

        /* ---- review ---------------------------------------------------- */
        function renderReview(result) {
            clearInterval(timer);
            setProgress(1, result.ok ? "Ready to use" : "Could not finish");

            var review = el("div", "pa-convert-review");
            if (result.ok) {
                review.appendChild(el("h3", null, "Converted"));
                var list = el("ul", "pa-convert-files");
                Object.keys(result.outputs).forEach(function (name) {
                    if (name === "manifest.json") return;
                    var report = result.reports[name] || {};
                    var li = el("li");
                    li.appendChild(el("span", "pa-convert-file", name));
                    var s = report.summary || {};
                    li.appendChild(el("span", "pa-convert-filestat",
                        [s.nRows != null ? s.nRows.toLocaleString() + " rows" : null,
                         s.nCols != null ? s.nCols + " columns" : null,
                         report.role].filter(Boolean).join(" · ")));
                    list.appendChild(li);
                });
                review.appendChild(list);

                var accept = el("button", "pa-convert-accept", "Use these files");
                accept.type = "button";
                accept.addEventListener("click", function () {
                    applyOutputs(input, result.outputs);
                    shutdown();
                });
                footer.appendChild(accept);
            } else {
                review.appendChild(el("h3", null, "Could not finish this one"));
                review.appendChild(el("p", "pa-convert-step-detail",
                    "The script is above — a colleague who knows pandas can take it from there, " +
                    "or you can tell us what the file contains and we will try again."));
            }
            var dismiss = el("button", "pa-convert-dismiss", result.ok ? "Cancel" : "Close");
            dismiss.type = "button";
            dismiss.addEventListener("click", function () { cancelled = true; shutdown(); });
            footer.appendChild(dismiss);
            body.appendChild(review);
            body.scrollTop = body.scrollHeight;
        }

        /* Put the converted values file back into the omic's file input. */
        function applyOutputs(fileInput, outputs) {
            var names = Object.keys(outputs).filter(function (n) { return n !== "manifest.json"; });
            var primary = names.filter(function (n) { return /value|expression|region/i.test(n); })[0]
                       || names[0];
            if (!primary) return;
            var transfer = new DataTransfer();
            transfer.items.add(new File([outputs[primary]], primary, { type: "text/plain" }));
            fileInput.files = transfer.files;
            fileInput.dispatchEvent(new Event("change", { bubbles: true }));
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
             createSandbox: createSandbox };
});
