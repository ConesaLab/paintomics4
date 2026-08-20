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

    function check(input, file, fieldName) {
        var strip = stripFor(input, fieldName);
        if (!strip) return;
        strip.__input = input;
        strip.__omic = omicNameFor(fieldName);
        strip.className = "pa-format-strip pa-format-busy";
        strip.textContent = "Checking " + file.name + "…";

        if (SPREADSHEET.test(file.name)) {
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
            if (result.ok) { renderOk(strip, result.summary, partial, input); return; }

            var repairs = API.proposeRepairs(read.rows, read.delimiter, result.problems);
            var repaired = repairs.length ? API.applyRepairs(read.rows, repairs) : null;
            var fixable = repaired && API.validateValues(repaired.rows).ok && !partial;

            if (fixable) {
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
