/*
 * Checks every omic data file the moment it is picked, and says what is wrong
 * in terms the user can act on.
 *
 * Today a malformed file is accepted here and dies at Step 2 with up to ten
 * lines of "Line contains invalid values or symbols", or -- worse -- succeeds
 * and yields zero matched features. This module moves that verdict to the one
 * moment the user still has the file open and can do something about it.
 *
 * It installs itself with a delegated listener rather than by editing
 * PA_Step1Views.js. That file is 224 KB and sits on the path of every job in
 * the application; a feature that is meant to help people who upload odd files
 * has no business being able to break submission for everybody else.
 */
(function () {
    "use strict";

    var API = window.PaintomicsInputFormat;
    if (!API || !API.readDelimited) { return; }   // scripts out of order; stay silent

    // Files above this are checked partially. Reading a 100 MB file into a
    // string to count columns would freeze the tab for seconds, and the first
    // few megabytes answer the question for every fault this module reports.
    var FULL_CHECK_LIMIT = 25 * 1024 * 1024;
    var PARTIAL_CHECK_BYTES = 5 * 1024 * 1024;

    var VALUES_FIELD = /^omic\d+_file$/;

    /*
     * Files we KNOW the server will reject, keyed by field name.
     *
     * This exists because a warning is not enough. Observed on the very first
     * run-through: the strip said the numbers used decimal commas, the form was
     * submitted anyway, and the server answered with ten identical lines of
     * "Perhaps you are using commas instead of dots as decimal mark?" -- the
     * exact wall of noise this module was written to replace. Since the client
     * validator is pinned to the server's own loop by a test over every example
     * file, an invalid file here is a GUARANTEED server error, so submitting is
     * blocked rather than merely annotated.
     */
    var blocked = {};
    var SPREADSHEET = /\.(xlsx|xlsm|xls|ods)$/i;

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function plural(n, word) {
        return n.toLocaleString() + " " + word + (n === 1 ? "" : "s");
    }

    /* ------------------------------------------------------------------ *
     * Locating the strip
     * ------------------------------------------------------------------ */

    /*
     * Where the strip lives, and why it is not next to the field.
     *
     * The obvious home is the omic card. It does not work. The omic cards sit
     * in an ExtJS vbox with align:stretch, and that layout positions its
     * children from measurements it took once. Growing a card -- by raw DOM
     * insertion OR by adding a real Ext.Component and calling updateLayout on
     * the card, its container and the form -- leaves every sibling exactly
     * where it was, so the card silently overlaps the omic beneath it.
     * Measured three ways; the sibling moved 0px each time.
     *
     * So the strips are collected in one region appended to the Step 1 form
     * panel's body, which flows normally. Each message names its omic, which
     * the field alone would not have made clear anyway once several omics are
     * in play, and the first problem scrolls itself into view.
     */
    function omicNameFor(fieldName) {
        var prefix = fieldName.replace(/_file$/, "");
        if (!window.Ext || !Ext.ComponentQuery) return prefix;
        var field = Ext.ComponentQuery.query("[name=" + prefix + "_omic_name]")[0];
        var value = field && field.getValue && field.getValue();
        return value || prefix;
    }

    function regionFor(input) {
        var panel = input.closest(".x-panel.paStep1Form") || input.closest(".x-panel");
        var body = panel && panel.querySelector(".x-panel-body");
        if (!body) return null;
        var region = body.querySelector(":scope > .pa-format-region");
        if (!region) {
            region = el("div", "pa-format-region");
            body.appendChild(region);
        }
        return region;
    }

    function stripFor(input, fieldName) {
        var region = regionFor(input);
        if (!region) return null;
        var key = "pa-strip-" + fieldName;
        var existing = region.querySelector("#" + key);
        if (existing) return existing;
        var strip = el("div", "pa-format-strip");
        strip.id = key;
        region.appendChild(strip);
        return strip;
    }

    /*
     * An ExtJS 4 panel body is measured once and then carries overflow:hidden,
     * so content added afterwards is CLIPPED rather than scrolled to. Every
     * DOM-level insert into one has to be followed by a relayout.
     */
    function relayout(input) {
        if (!window.Ext || !Ext.getCmp) return;
        var panel = input.closest(".x-panel.paStep1Form") || input.closest(".x-panel");
        if (!panel || !panel.id) return;
        var component = Ext.getCmp(panel.id);
        if (!component) return;
        if (typeof window.poRelayout === "function") { window.poRelayout(component); return; }
        if (component.updateLayout) component.updateLayout();
    }

    // Only the first problem for a given file pulls the page; re-checking the
    // same field after a repair must not yank the user around.
    function revealOnce(strip) {
        if (strip.dataset.revealed) return;
        strip.dataset.revealed = "1";
        if (strip.scrollIntoView) strip.scrollIntoView({ block: "center", behavior: "smooth" });
    }

    /* ------------------------------------------------------------------ *
     * Rendering
     * ------------------------------------------------------------------ */

    function renderOk(strip, summary, partial, input) {
        strip.className = "pa-format-strip pa-format-ok";
        strip.innerHTML = "";
        var bits = [plural(summary.nRows, "row"),
                    plural(summary.numericColumns.length, "value column")];
        if (summary.idSample.length) {
            bits.push("IDs like " + summary.idSample.slice(0, 3).join(", "));
        }
        strip.appendChild(el("span", "pa-format-icon", "✓"));
        strip.appendChild(el("span", "pa-format-text",
            (strip.__omic ? strip.__omic + ": " : "") + bits.join(" · ")));
        if (partial) {
            strip.appendChild(el("span", "pa-format-note",
                " (checked the first " + Math.round(PARTIAL_CHECK_BYTES / 1048576) + " MB)"));
        }
        if (input) relayout(input);
    }

    function markBlocked(fieldName, entry) { blocked[fieldName] = entry; }

    function clearBlocked(fieldName) { delete blocked[fieldName]; }

    /*
     * Entries go stale when an omic card is deleted or a different file is
     * picked, and a stale entry would block submission forever with a message
     * about a file that is no longer there. So every entry is re-checked
     * against the live form before it is allowed to stop anything.
     */
    function liveBlocked() {
        var live = [];
        if (!window.Ext || !Ext.ComponentQuery) return live;
        var fields = Ext.ComponentQuery.query("filefield");
        Object.keys(blocked).forEach(function (fieldName) {
            var field = null;
            for (var i = 0; i < fields.length; i++) {
                if (fields[i].name === fieldName) { field = fields[i]; break; }
            }
            var dom = field && field.fileInputEl && field.fileInputEl.dom;
            var current = dom && dom.files && dom.files[0];
            if (!current || current.name !== blocked[fieldName].fileName) {
                clearBlocked(fieldName);
                return;
            }
            live.push(blocked[fieldName]);
        });
        return live;
    }

    function renderProblem(strip, kind, headline, detail, actions) {
        strip.className = "pa-format-strip pa-format-" + kind;
        strip.innerHTML = "";
        strip.appendChild(el("span", "pa-format-icon", kind === "warn" ? "⚠" : "✗"));
        var body = el("div", "pa-format-body");
        var title = el("div", "pa-format-headline");
        if (strip.__omic) {
            title.appendChild(el("span", "pa-format-omic", strip.__omic + ": "));
        }
        title.appendChild(document.createTextNode(headline));
        body.appendChild(title);
        revealOnce(strip);
        if (detail) body.appendChild(el("div", "pa-format-detail", detail));
        var bar = el("div", "pa-format-actions");
        actions.forEach(function (action) {
            var button = el("button", "pa-format-button" + (action.primary ? " pa-format-primary" : ""), action.label);
            button.type = "button";                     // never submit the Step 1 form
            button.addEventListener("click", action.onClick);
            bar.appendChild(button);
        });
        body.appendChild(bar);
        strip.appendChild(body);
        if (strip.__input) relayout(strip.__input);
        return body;
    }

    function renderDiff(container, changes) {
        var existing = container.querySelector(".pa-format-diff");
        if (existing) { existing.remove(); return; }
        var table = el("table", "pa-format-diff");
        changes.forEach(function (change) {
            var row = el("tr");
            row.appendChild(el("td", "pa-format-line", "line " + (change.line + 1)));
            row.appendChild(el("td", "pa-format-before", change.before));
            row.appendChild(el("td", "pa-format-arrow", "→"));
            row.appendChild(el("td", "pa-format-after",
                change.after === null ? "(removed)" : change.after));
            table.appendChild(row);
        });
        container.appendChild(table);
    }

    /* ------------------------------------------------------------------ *
     * Replacing the picked file with a repaired one
     * ------------------------------------------------------------------ */

    function replaceFile(input, rows, name) {
        var text = rows.map(function (row) { return row.join("\t"); }).join("\n") + "\n";
        var transfer = new DataTransfer();
        transfer.items.add(new File([text], name, { type: "text/plain" }));
        input.files = transfer.files;
    }

    /* ------------------------------------------------------------------ *
     * The check itself
     * ------------------------------------------------------------------ */

    function describeProblems(result) {
        var counts = {};
        result.problems.forEach(function (p) { counts[p.code] = (counts[p.code] || 0) + 1; });
        var summary = result.summary;

        if (counts.DECIMAL_COMMA) {
            return "Numbers use commas as the decimal mark; PaintOmics needs dots.";
        }
        if (counts.NON_NUMERIC && summary.textColumns.length) {
            var names = summary.textColumns.map(function (i) {
                return summary.columnNames[i] || ("column " + (i + 1));
            });
            return "Every column after the identifier must be numeric, but " +
                   names.slice(0, 4).join(", ") +
                   (names.length > 4 ? " and " + (names.length - 4) + " more" : "") +
                   " contain text.";
        }
        if (counts.RAGGED) return "Some rows have more or fewer columns than the rest.";
        if (counts.TOO_FEW_COLUMNS) return "The file has only one column; a values file needs an identifier plus at least one measurement.";
        if (counts.NO_FEATURE_LINES) return "The file has a header but no data rows.";
        if (counts.EMPTY) return "The file is empty.";
        return "The file does not match the format PaintOmics expects.";
    }

    /*
     * autoApply: apply a deterministic repair the moment it is found, instead
     * of offering a button. Used by the error-dialog hook, where the user has
     * already asked for the file to be fixed -- making them find the strip and
     * press a second button would be two clicks for one intention.
     */
    function check(input, file, fieldName, autoApply) {
        var strip = stripFor(input, fieldName);
        if (!strip) return;
        strip.__input = input;
        strip.__omic = omicNameFor(fieldName);
        strip.className = "pa-format-strip pa-format-busy";
        strip.textContent = "Checking " + file.name + "…";

        if (SPREADSHEET.test(file.name)) {
            markBlocked(fieldName, { fieldName: fieldName, fileName: file.name,
                                     input: input, omic: strip.__omic, fixable: false });
            renderProblem(strip, "err",
                "Spreadsheets need converting first.",
                "PaintOmics reads plain text tables. " + file.name +
                " is a workbook, which may hold several sheets and columns that are not measurements.",
                [{ label: "Convert it for me", primary: true, onClick: function () { requestAgent(input, file); } },
                 { label: "I'll export it myself", onClick: function () { strip.remove(); } }]);
            return;
        }

        var partial = file.size > FULL_CHECK_LIMIT;
        var slice = partial ? file.slice(0, PARTIAL_CHECK_BYTES) : file;
        var reader = new FileReader();

        reader.onerror = function () {
            renderProblem(strip, "err", "The file could not be read.", "", []);
        };
        reader.onload = function () {
            var read = API.readDelimited(new Uint8Array(reader.result));

            if (read.decodeError) {
                markBlocked(fieldName, { fieldName: fieldName, fileName: file.name,
                                         input: input, omic: strip.__omic, fixable: false });
                renderProblem(strip, "err", "The file is not saved as UTF-8.",
                    "Re-save it as UTF-8 (in Excel: Save As → CSV UTF-8) and pick it again.",
                    [{ label: "Convert it for me", primary: true,
                       onClick: function () { requestAgent(input, file); } }]);
                return;
            }

            // A partial read almost always ends mid-line; that truncated row
            // would otherwise be reported as a ragged-column error the file
            // does not actually have.
            if (partial && read.rows.length > 1) read.rows.pop();

            var result = API.validateValues(read.rows);
            if (result.ok) {
                clearBlocked(fieldName);
                renderOk(strip, result.summary, partial, input);
                return;
            }

            var repairs = API.proposeRepairs(read.rows, read.delimiter, result.problems);
            var repaired = repairs.length ? API.applyRepairs(read.rows, repairs) : null;
            var fixable = repaired && API.validateValues(repaired.rows).ok && !partial;

            if (fixable) {
                if (autoApply) {
                    replaceFile(input, repaired.rows, file.name);
                    clearBlocked(fieldName);
                    renderOk(stripFor(input, fieldName),
                             API.validateValues(repaired.rows).summary, false, input);
                    return;
                }
                markBlocked(fieldName, {
                    fieldName: fieldName, fileName: file.name, input: input,
                    omic: strip.__omic, fixable: true,
                    apply: function () {
                        replaceFile(input, repaired.rows, file.name);
                        clearBlocked(fieldName);
                        renderOk(stripFor(input, fieldName),
                                 API.validateValues(repaired.rows).summary, false, input);
                    }
                });
                var body = renderProblem(strip, "warn", describeProblems(result),
                    repairs.map(function (r) { return r.describe(); }).join(" "),
                    [{ label: "Fix automatically", primary: true, onClick: function () {
                          replaceFile(input, repaired.rows, file.name);
                          renderOk(stripFor(input, fieldName), API.validateValues(repaired.rows).summary, false, input);
                      } },
                     { label: "Show what changes", onClick: function () {
                          renderDiff(body, repaired.changes);
                          relayout(input);
                      } }]);
                return;
            }

            // A partial check saw only the first few megabytes, so it is not
            // grounds for blocking -- only a full check is conclusive.
            if (!partial) {
                markBlocked(fieldName, {
                    fieldName: fieldName, fileName: file.name, input: input,
                    omic: strip.__omic, fixable: false
                });
            }
            renderProblem(strip, "err", describeProblems(result),
                partial ? "Checked the first few megabytes of a large file." : "",
                [{ label: "Convert it for me", primary: true,
                   onClick: function () { requestAgent(input, file); } },
                 { label: "I'll fix it myself", onClick: function () { strip.remove(); } }]);
        };
        reader.readAsArrayBuffer(slice);
    }

    /* Layer 2 hand-off. Replaced by convert-drawer.js when that ships; until
       then it says so plainly rather than doing nothing, because a button that
       silently does nothing reads as a broken page. */
    function requestAgent(input, file, fieldName) {
        if (window.PaintomicsInputFormat.openConvertDrawer) {
            window.PaintomicsInputFormat.openConvertDrawer(input, file, fieldName);
            return;
        }
        var strip = stripFor(input, fieldName);
        if (!strip) return;
        renderProblem(strip, "err", "AI conversion is not enabled on this server.",
            "Ask an administrator to enable it, or export the file as a tab-separated " +
            "table whose first column is the identifier and whose remaining columns are numbers.",
            []);
    }

    /* ------------------------------------------------------------------ *
     * Installation
     * ------------------------------------------------------------------ */

    function extFieldNameFor(input) {
        if (!window.Ext || !Ext.ComponentQuery) return null;
        var fields = Ext.ComponentQuery.query("filefield");
        for (var i = 0; i < fields.length; i++) {
            var dom = fields[i].fileInputEl && fields[i].fileInputEl.dom;
            if (dom === input) return fields[i].name || null;
        }
        return null;
    }

    /* ------------------------------------------------------------------ *
     * Stopping a submit that is certain to fail
     * ------------------------------------------------------------------ */

    function renderBlockBanner(entries) {
        var input = entries[0].input;
        var region = regionFor(input);
        if (!region) return;

        var existing = region.querySelector(".pa-format-block");
        if (existing) existing.remove();

        var banner = el("div", "pa-format-strip pa-format-err pa-format-block");
        banner.appendChild(el("span", "pa-format-icon", "✗"));
        var body = el("div", "pa-format-body");

        var names = entries.map(function (e) { return e.omic || e.fieldName; });
        body.appendChild(el("div", "pa-format-headline",
            names.join(" and ") + ": the server will reject " +
            (entries.length === 1 ? "this file" : "these files") + "."));
        body.appendChild(el("div", "pa-format-detail",
            "The same check that runs on the server has already read " +
            (entries.length === 1 ? "it" : "them") +
            ", so submitting now only produces the same error more slowly."));

        var bar = el("div", "pa-format-actions");
        var fixable = entries.filter(function (e) { return e.fixable; });

        if (fixable.length === entries.length) {
            var fix = el("button", "pa-format-button pa-format-primary",
                         "Fix " + (entries.length === 1 ? "it" : "them") + " and run");
            fix.type = "button";
            fix.addEventListener("click", function () {
                fixable.forEach(function (e) { e.apply(); });
                banner.remove();
                submitNow();
            });
            bar.appendChild(fix);
        }

        var convert = el("button", "pa-format-button", "Convert with AI");
        convert.type = "button";
        convert.addEventListener("click", function () {
            var first = entries[0];
            var picked = first.input.files && first.input.files[0];
            if (picked) requestAgent(first.input, picked, first.fieldName);
        });
        bar.appendChild(convert);

        /*
         * An escape hatch, deliberately. The validator is pinned to the
         * server's loop by a test over every example file, but "pinned by a
         * test" is not "cannot be wrong", and a user must never be locked out
         * of their own analysis by a bug in a convenience feature.
         */
        var anyway = el("button", "pa-format-button", "Submit anyway");
        anyway.type = "button";
        anyway.addEventListener("click", function () {
            banner.remove();
            submitNow();
        });
        bar.appendChild(anyway);

        body.appendChild(bar);
        banner.appendChild(body);
        region.appendChild(banner);
        relayout(input);
        banner.scrollIntoView({ block: "center", behavior: "smooth" });
    }

    var bypassGuard = false;

    function submitNow() {
        var button = document.getElementById("submitButton");
        if (!button) return;
        bypassGuard = true;
        button.click();
        bypassGuard = false;
    }

    document.addEventListener("click", function (event) {
        if (bypassGuard) return;
        var target = event.target;
        if (!target || !target.closest) return;
        if (!target.closest("#submitButton")) return;

        var entries = liveBlocked();
        if (!entries.length) return;

        // stopImmediatePropagation, not just preventDefault: the submit is
        // wired as a jQuery/ExtJS click handler on the same element, and
        // preventDefault alone would let it run.
        event.preventDefault();
        event.stopImmediatePropagation();
        renderBlockBanner(entries);
    }, true);

    /* ------------------------------------------------------------------ *
     * The same offer, on the error the server sends back
     * ------------------------------------------------------------------ */

    /*
     * Not every bad file passes through the checker. A file picked from server
     * storage never reaches the browser at all, a large file is only checked in
     * part, and the server knows about faults this module does not model. In
     * all of those the user still lands on the error dialog, and that dialog is
     * where the offer to fix belongs.
     */
    function pickedFileMatching(reportedName) {
        if (!window.Ext || !Ext.ComponentQuery) return null;
        var fields = Ext.ComponentQuery.query("filefield");
        for (var i = 0; i < fields.length; i++) {
            if (!VALUES_FIELD.test(fields[i].name || "")) continue;
            var dom = fields[i].fileInputEl && fields[i].fileInputEl.dom;
            var file = dom && dom.files && dom.files[0];
            if (!file) continue;
            // The server prefixes the stored copy with the job id, so the name
            // it reports ENDS WITH the name the user picked.
            if (reportedName === file.name ||
                reportedName.slice(-file.name.length) === file.name) {
                return { input: dom, file: file, fieldName: fields[i].name };
            }
        }
        return null;
    }

    function attachDialogFix() {
        var body = document.getElementById("messageDialogBody");
        var closeButton = document.getElementById("messageDialogButton");
        if (!body || !closeButton || !closeButton.parentNode) return;
        if (document.getElementById("pa-format-dialog-fix")) return;

        var text = body.textContent || "";
        if (text.indexOf("Errors detected while processing") === -1) return;

        var match = /Errors detected while processing ([^\s:]+)/.exec(text);
        if (!match) return;
        var picked = pickedFileMatching(match[1]);
        if (!picked) return;

        var button = el("a", "button btn-secondary btn-right", "Fix this file");
        button.title = "Repairs the file in place, then you can run again.";
        button.id = "pa-format-dialog-fix";
        button.href = "#";
        button.style.display = "inline-block";
        button.addEventListener("click", function (event) {
            event.preventDefault();
            if (typeof closeButton.click === "function") closeButton.click();
            check(picked.input, picked.file, picked.fieldName, true);
        });
        closeButton.parentNode.insertBefore(button, closeButton);
    }

    // The dialog is rendered by Util.js's showMessage, which several call sites
    // reach through showErrorMessage. Wrapping that one function catches them
    // all without editing Util.js, which every surface in the app depends on.
    if (typeof window.showErrorMessage === "function") {
        var originalShowErrorMessage = window.showErrorMessage;
        window.showErrorMessage = function () {
            var result = originalShowErrorMessage.apply(this, arguments);
            // The window is laid out asynchronously; attach once it exists.
            setTimeout(function () {
                try { attachDialogFix(); }
                catch (e) { if (window.console) console.warn("[inputformat] dialog hook", e); }
            }, 60);
            return result;
        };
    }

    // Capture phase: ExtJS re-dispatches and sometimes stops change events on
    // its own wrappers, and capture runs before any of that.
    document.addEventListener("change", function (event) {
        var input = event.target;
        if (!input || input.type !== "file" || !input.files || !input.files.length) return;
        var name = extFieldNameFor(input);
        if (!name || !VALUES_FIELD.test(name)) return;
        try {
            check(input, input.files[0], name);
        } catch (e) {
            // Never let a check failure take the upload with it: the user can
            // always still submit, exactly as before this module existed.
            if (window.console && console.warn) console.warn("[inputformat] check failed", e);
        }
    }, true);
})();
