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

    /*
     * The contract a picked file is held to, keyed by the SLOT it was picked
     * into.
     *
     * This replaces a test on the field's NAME (/^omic\d+_file$/). That is the
     * plain, region-based and miRNA panels' naming convention and it is not the
     * MORE panel's -- MORE calls its five selectors conditions, rnaseqaux,
     * file_0, relevant_file_0 and assoc_file_0 -- so every file picked into a
     * Regulatory Omic (MORE) panel went unchecked: no strip, no warning, no
     * offer to fix, and no block. Reported 2026-08-26 by a user whose files
     * used decimal commas, the single fault this module exists to catch and
     * blocks a submit over. She was told nothing, and the run failed on the
     * server an hour later.
     *
     * itemId is the key because it is the one thing every panel type agrees
     * on; the field names differ per panel and the file names are not evidence
     * of anything (see roleForFileName's note in format-roles.js).
     *
     * Two slots are deliberately absent, because this module does not model
     * what they hold and judging them by a validator that does not fit would
     * block work that is correct:
     *
     *   tertiaryFileSelector    the region panel's GTF -- not a delimited
     *                           table in any of these contracts;
     *   third/fourthFileSelector  the miRNA panel's RESULTS container, filled
     *                           by setContent with server paths rather than
     *                           picked, so there is no browser file to read.
     *                           An empty regulator_relevant_associations file
     *                           is a legitimate conversion output and the
     *                           relevant-associations contract rejects it, so
     *                           judging them could only ever block correct work;
     *   mirnaTargetsFileSelector  the miRNA2Genes prediction table, which is
     *                           miRNA / gene / PLR. The shipped
     *                           mirna_to_gene_associations.tab has THREE
     *                           columns for that reason, so the two-column
     *                           associations contract rejects it -- the very
     *                           trap format-roles.js records under
     *                           roleForFileName.
     */
    var ROLE_BY_SLOT = {
        mainFileSelector: "values",
        rnaseqauxFileSelector: "values",
        secondaryFileSelector: "relevant",
        moreRelevantFileSelector: "relevant",
        mainAssociationFileSelector: "associations",
        moreAssociationsFileSelector: "associations",
        secondaryAssociationFileSelector: "relevant-associations",
        conditionsFileSelector: "design"
    };

    /* The Ext filefield that owns this DOM input, or null. */
    function extFieldFor(input) {
        if (!window.Ext || !Ext.ComponentQuery) return null;
        var fields = Ext.ComponentQuery.query("filefield");
        for (var i = 0; i < fields.length; i++) {
            var dom = fields[i].fileInputEl && fields[i].fileInputEl.dom;
            if (dom === input) return fields[i];
        }
        return null;
    }

    /* The role of the slot a filefield sits in, or null when it is not one of
       the omic panels' data slots. */
    function roleForField(field) {
        if (!field || !field.up) return null;
        var selector = field.up("myFilesSelectorButton");
        if (!selector || !selector.itemId) return null;
        return ROLE_BY_SLOT[selector.itemId] || null;
    }

    function roleForInput(input) {
        return roleForField(extFieldFor(input));
    }

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

    /* What the AI actually does, in the user's terms. People are right to
       be wary of "AI will fix your data"; saying that it writes a script,
       runs it locally, and shows both is what makes it trustworthy. */
    var AI_EXPLAINER = "The PaintOmics AI agent can convert it here in your browser: it reads the file's structure, writes a short script, runs it locally and checks the result. You see the script, the tables and what it left out before anything is used.";

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
     * Where the message lives, and why the omic card carries the state.
     *
     * The message cannot go INSIDE the omic card. The cards are `flex: 1` items
     * in a vbox whose height is fixed at 314px by an hbox pinned at 400px, so
     * the layout ASSIGNS each card its height out of a fixed budget rather than
     * measuring its content. Nothing added to a card can make it taller; it can
     * only overflow, and the row is overflow:hidden. Measured three ways -- raw
     * DOM insertion, a real Ext.Component, and updateLayout on the card, its
     * container and the form -- and the sibling omic moved 0px every time.
     *
     * So the message sits just below the omics row, but pinned to the same left
     * edge and width as the cards and pulled up into the row's unused space, and
     * the CARD is tinted to carry the state. The tint is what makes a problem
     * impossible to miss; the message below it is what says how to fix it.
     * Neither costs a single pixel of layout.
     */
    // The omic's display name, used by the submit-time banner, which can be
    // about several omics at once.
    //
    // Taken off the card the input sits in, not from the field name. The name
    // lookup this replaces asked for "<prefix>_omic_name", which the MORE panel
    // does not have -- its combo is `omic_name_0` -- so a MORE file would have
    // been announced to the user as "file_0".
    function omicNameFor(input, fieldName) {
        var card = cardComponentFor(input);
        if (card) {
            var combo = card.down && card.down("#omicNameField");
            var typed = combo && combo.getValue && combo.getValue();
            if (typed) return typed;
            var heading = card.el && card.el.dom &&
                          card.el.dom.querySelector(".omicboxTitle h4");
            if (heading) {
                var text = String(heading.textContent || "").replace(/\s+/g, " ").trim();
                if (text) return text;
            }
        }
        return String(fieldName || "").replace(/_file$/, "") || "this omic";
    }

    function cardFor(input) {
        return input.closest(".omicbox");
    }

    function cardComponentFor(input) {
        var card = cardFor(input);
        if (!card || !card.id || !window.Ext || !Ext.getCmp) return null;
        return Ext.getCmp(card.id) || null;
    }

    // The visible filename box, a sibling of the hidden file input inside the
    // custom selector widget.
    function filenameBoxFor(input) {
        var selector = input.closest("[id*=myFilesSelector]") || input.closest(".omicbox");
        if (!selector) return null;
        var boxes = selector.querySelectorAll("input[type=text]");
        for (var i = 0; i < boxes.length; i++) {
            if (boxes[i].getBoundingClientRect().width > 100) return boxes[i];
        }
        return null;
    }

    var CARD_STATES = ["pa-state-ok", "pa-state-warn", "pa-state-err"];

    /*
     * Set the card's state class through ExtJS, not through classList.
     *
     * A raw classList.add is silently undone: updateLayout() rewrites the
     * component's class attribute from its own list, so the class survives
     * exactly until the next layout pass -- which this module triggers itself,
     * one line later. addCls/removeCls put the class in the list Ext rebuilds
     * from, so it survives.
     */
    function setCardState(input, state) {
        var component = cardComponentFor(input);
        var card = cardFor(input);
        if (component && component.addCls) {
            CARD_STATES.forEach(function (cls) { component.removeCls(cls); });
            if (state) component.addCls("pa-state-" + state);
        } else if (card) {
            CARD_STATES.forEach(function (cls) { card.classList.remove(cls); });
            if (state) card.classList.add("pa-state-" + state);
        }

        var box = filenameBoxFor(input);
        if (!box) return;
        box.classList.remove("pa-field-warn", "pa-field-err");
        if (state === "warn" || state === "err") box.classList.add("pa-field-" + state);
    }

    /* ------------------------------------------------------------------ *
     * Putting the message inside its own omic card
     * ------------------------------------------------------------------ */

    /*
     * The omic cards are items in an ExtJS vbox, and the vbox lays them out as
     * position:absolute elements carrying an inline `top`. That is the whole
     * difficulty: growing a card's DOM does not move the card below it,
     * because nothing rewrites that `top`.
     *
     * What this module used to do about that was compute the height the card
     * ought to have and setHeight() it. A computed height is a MEASUREMENT,
     * and a measurement has a moment. The MORE card is tall enough that its
     * sections had not settled when the card was primed -- 662px recorded
     * where itemsContainer alone settles at 684 -- so the card was pinned 66px
     * short of its own contents. The omic title is itself a `flex: 1` item, so
     * the vbox took the entire shortfall out of the title: it was allocated
     * 0px, CSS min-height painted it at 44px regardless, and it landed on top
     * of the first section heading. Reported twice from a screenshot.
     *
     * There is no number to get wrong in what replaces it. A vbox child with
     * neither `flex` nor an explicit height shrink-wraps its own items, so the
     * card is whatever its contents are, whenever they change; updateLayout()
     * is what rewrites the siblings' `top`.
     *
     * Dropping `flex` is what makes that hold, and it is also the reading
     * behind the older note here that "updateLayout() on the card does not
     * work": while the card shares a height budget with its siblings, its
     * height is the layout's to decide and updateLayout() can only hand back
     * the same number. Out of the budget, it works. Measured on the MORE card:
     * idle strip -> card 771px, title 44px, overlap 0; growing the strip by
     * 34px -> card 805px and the card below moved from 1028 to 1062. Plain
     * cards go 178 -> 175, which is exactly the 3px the title's own flex had
     * been stretching them by.
     */
    function hostFor(input) {
        return hostForComponent(cardComponentFor(input));
    }

    function hostForComponent(component) {
        if (!component) return null;

        var existing = component.down && component.down("[itemId=paFormatHost]");
        if (existing) return existing.getEl().dom.firstChild;

        var host = null;
        Ext.suspendLayouts();
        freeCardHeight(component);
        host = component.add(Ext.create("Ext.Component", {
            itemId: "paFormatHost",
            cls: "pa-format-strip-host",
            html: '<div class="pa-format-strip"></div>'
        }));
        Ext.resumeLayouts(true);
        component.updateLayout();
        return host.getEl().dom.firstChild;
    }

    /*
     * Take the card out of the vbox's height budget, once, so that it sizes
     * itself from its items from here on. Both halves are needed: `flex` keeps
     * the layout deciding the height, and the inline height the layout has
     * already written keeps the DOM at that decision.
     */
    function freeCardHeight(component) {
        if (!component || component.__paFreed) return;
        component.__paFreed = true;
        component.flex = null;
        component.height = null;
        if (component.el && component.el.dom) component.el.dom.style.height = "";
    }

    /*
     * Re-lay the card out to fit whatever the message currently is.
     *
     * Called after every render because the message changes height -- opening
     * the change preview roughly doubles it -- and the vbox does not notice a
     * child's DOM growing underneath it. Measured with the strip grown by 34px
     * and no relayout: the strip hangs 33px below the card's own bottom edge.
     */
    function syncCardHeight(input) {
        syncCardHeightFor(cardComponentFor(input));
    }

    function syncCardHeightFor(component) {
        if (!component || component.isDestroyed || !component.__paFreed) return;
        component.updateLayout();
    }

    /*
     * The submit-time banner is the one message that is NOT about a single
     * file -- it can name several omics at once -- so it keeps a region at the
     * end of the form rather than living in any one card.
     */
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

    /*
     * The resting state of a card that has no file yet. It is the first thing
     * the AI says on this form, so it says the one thing that matters -- any
     * file will do -- and nothing else. No tint, no border: a promise is not a
     * verdict.
     */
    function renderIdle(strip) {
        strip.className = "pa-format-strip pa-format-idle";
        strip.innerHTML = "";
        var icon = el("span", "pa-format-icon pa-format-icon-ai");
        icon.innerHTML = typeof window.getAIMark === "function" ? window.getAIMark() : "✦";
        strip.appendChild(icon);
        var text = el("span", "pa-format-text");
        text.appendChild(document.createTextNode("Any format works — the "));
        text.appendChild(el("b", null, "PaintOmics AI agent"));
        text.appendChild(document.createTextNode(" converts it here if needed."));
        strip.appendChild(text);
    }

    /* The one AI action a problem strip offers. Pressing it is the consent:
       nothing leaves this computer until the user does, so there is no box to
       tick beforehand. */
    function aiActions(input, file, fieldName) {
        return [{ label: "Convert it for me", primary: true, ai: true,
                  onClick: function () { requestAgent(input, file, fieldName); } }];
    }

    function aiExplainer() { return AI_EXPLAINER; }

    /* What an accepted file is worth saying about it, per contract.
     *
     * Only the values summary carries numericColumns and idSample; a design
     * matrix reports its conditions and the two association contracts report
     * nothing but their shape. Reading the values fields unconditionally threw
     * ("Cannot read properties of undefined") the moment this module started
     * checking the other slots, leaving a blank green strip. */
    function summaryBits(summary) {
        var bits = [plural(summary.nRows, "row")];
        if (summary.numericColumns) {
            bits.push(plural(summary.numericColumns.length, "value column"));
        } else if (summary.conditions) {
            bits.push(plural(summary.conditions.length, "condition") +
                      " (" + summary.conditions.slice(0, 4).join(", ") + ")");
        } else if (summary.nCols) {
            bits.push(plural(summary.nCols, "column"));
        }
        if (summary.idSample && summary.idSample.length) {
            bits.push("IDs like " + summary.idSample.slice(0, 3).join(", "));
        }
        return bits;
    }

    function renderOk(strip, summary, partial, input) {
        strip.className = "pa-format-strip pa-format-ok";
        strip.innerHTML = "";
        var bits = summaryBits(summary || {});
        strip.appendChild(el("span", "pa-format-icon", "✓"));
        var body = el("div", "pa-format-body");
        var line = el("div", "pa-format-text",
            (strip.__omic ? strip.__omic + ": " : "") + bits.join(" · "));
        if (partial) {
            line.appendChild(el("span", "pa-format-note",
                " (checked the first " + Math.round(PARTIAL_CHECK_BYTES / 1048576) + " MB)"));
        }
        body.appendChild(line);

        /*
         * Provenance. A file the AI produced looks exactly like one the user
         * made, and the card would otherwise forget that within a second of
         * the sheet closing. Saying which table came from which upload is what
         * lets the user -- and a reviewer reading their methods -- know.
         */
        var converted = strip.__converted;
        if (converted) {
            strip.classList.add("pa-format-converted");
            var prov = el("div", "pa-format-provenance");
            var mark = el("span", "pa-format-provenance-mark");
            mark.innerHTML = typeof window.getAIMark === "function" ? window.getAIMark() : "✦";
            prov.appendChild(mark);
            var what = el("span", "pa-format-provenance-text");
            what.appendChild(document.createTextNode("Converted by the PaintOmics AI agent from "));
            what.appendChild(el("b", null, converted.from));
            var extras = [];
            if (converted.label) extras.push("table “" + converted.label + "”");
            if (converted.relevant) extras.push("relevant-features list attached");
            if (extras.length) what.appendChild(document.createTextNode(" (" + extras.join(", ") + ")"));
            what.appendChild(document.createTextNode("."));
            if (converted.original) {
                // Inline, at the end of the sentence: a control on its own line
                // under a one-line note reads as a second message.
                var again = el("button", "pa-format-linkbtn", "Convert again");
                again.type = "button";
                again.title = "Reopen the AI conversion for " + converted.from;
                again.addEventListener("click", function () {
                    requestAgent(input, converted.original, converted.fieldName || strip.__field);
                });
                what.appendChild(again);
            }
            prov.appendChild(what);
            body.appendChild(prov);
        }
        strip.appendChild(body);
        if (input) { setCardState(input, "ok"); syncCardHeight(input); }
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
            var button = el("button", "pa-format-button" + (action.primary ? " pa-format-primary" : ""));
            button.type = "button";                     // never submit the Step 1 form
            /*
             * The mark goes on the AI action and nowhere else. The
             * deterministic repair is a find-and-replace on numeric cells, and
             * badging it as AI would claim credit for something no model did --
             * which also devalues the badge where it is true.
             */
            if (action.ai && typeof window.getAIMark === "function") {
                button.innerHTML = window.getAIMark();
                button.appendChild(document.createTextNode(" " + action.label));
            } else {
                button.textContent = action.label;
            }
            button.addEventListener("click", action.onClick);
            bar.appendChild(button);
        });
        body.appendChild(bar);
        strip.appendChild(body);
        if (strip.__input) {
            setCardState(strip.__input, kind === "warn" ? "warn" : "err");
            syncCardHeight(strip.__input);
        }
        return body;
    }

    /*
     * The change preview was removed along with its button: one message, one
     * action. If it comes back, it belongs behind a disclosure on the review
     * screen rather than as a second button competing with the fix.
     */

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
        if (counts.NON_NUMERIC && summary.textColumns && summary.textColumns.length) {
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

        /* The other contracts. Without these every fault in a conditions,
           associations or relevant-features file fell through to the generic
           sentence below, which tells the reader nothing they can act on --
           and telling them is the whole purpose of this module. */
        if (counts.DUPLICATE_IDENTIFIER) {
            /* First, because it is fatal and because every other complaint
               about this file is downstream of it. The numbers are in the
               message on purpose: "you have duplicates" sends someone hunting,
               "65 rows share ENSMUSG00000104758" tells them where to look and
               how bad it is. */
            var dup = result.problems.filter(function (p) {
                return p.code === "DUPLICATE_IDENTIFIER";
            })[0].detail;
            return dup.ids + " identifier" + (dup.ids === 1 ? "" : "s") +
                   " name more than one row — " + dup.rows + " rows in all, and " +
                   "\u201C" + dup.worst + "\u201D appears " + dup.worstCount +
                   " times. Every row has to name a different feature: the " +
                   "analysis reads this file into a table keyed on that column, " +
                   "and cannot hold two values under one name.";
        }
        if (counts.NOT_INDICATOR) {
            return "A conditions file marks each sample with 1 or 0 in every " +
                   "group column; this one holds other values.";
        }
        if (counts.NOT_ONE_CONDITION) {
            return "Every sample must belong to exactly one condition — one 1 per row.";
        }
        if (counts.CONDITION_MISMATCH) {
            return "This file does not have one column per condition.";
        }
        if (counts.NOT_TWO_COLUMNS) {
            return "An associations file needs exactly two columns: the target and its regulator.";
        }
        if (counts.BAD_COLUMN_COUNT) {
            return "The file does not have the number of columns this slot expects.";
        }
        if (counts.FIELD_TOO_LONG) {
            return "A field is far too long to be an identifier — this looks like the wrong file for the slot.";
        }
        return "The file does not match the format PaintOmics expects.";
    }

    /*
     * autoApply: apply a deterministic repair the moment it is found, instead
     * of offering a button. Used by the error-dialog hook, where the user has
     * already asked for the file to be fixed -- making them find the strip and
     * press a second button would be two clicks for one intention.
     */
    function check(input, file, fieldName, autoApply, role) {
        /* Every slot is held to its OWN contract. Running the values-matrix
           validator over an associations file or a 0/1 design matrix would
           report faults they cannot have; format-roles.js already models
           each one. */
        role = role || roleForInput(input) || "values";
        var validate = function (rows) { return API.validateForRole(role, rows); };
        var strip = hostFor(input);
        if (!strip) return;
        strip.__input = input;
        strip.__field = fieldName;
        strip.__omic = omicNameFor(input, fieldName);
        // Set by the conversion sheet just before it hands the table over;
        // consumed here so a file the user picks by hand afterwards carries no
        // stale provenance.
        strip.__converted = input.__paConverted || null;
        input.__paConverted = null;
        strip.className = "pa-format-strip pa-format-busy";
        strip.textContent = "Checking " + file.name + "…";

        if (SPREADSHEET.test(file.name)) {
            markBlocked(fieldName, { fieldName: fieldName, fileName: file.name,
                                     input: input, omic: strip.__omic, fixable: false });
            renderProblem(strip, "err",
                "This spreadsheet needs converting.",
                file.name + " is a workbook — it may hold several sheets and " +
                "columns that are not measurements. " + aiExplainer(),
                aiActions(input, file, fieldName));
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
                    "Re-save it as UTF-8 (in Excel: Save As → CSV UTF-8), or let the PaintOmics AI agent convert it. " + AI_EXPLAINER,
                    aiActions(input, file, fieldName));
                return;
            }

            // A partial read almost always ends mid-line; that truncated row
            // would otherwise be reported as a ragged-column error the file
            // does not actually have.
            if (partial && read.rows.length > 1) read.rows.pop();

            var result = validate(read.rows);
            if (result.ok) {
                clearBlocked(fieldName);
                renderOk(strip, result.summary, partial, input);
                return;
            }

            var repairs = API.proposeRepairs(read.rows, read.delimiter, result.problems);
            var repaired = repairs.length ? API.applyRepairs(read.rows, repairs) : null;
            var fixable = repaired && validate(repaired.rows).ok && !partial;

            /*
             * ONE implementation, used by all three ways of applying a repair.
             *
             * There used to be three copies, and the one the user actually
             * clicks -- the "Fix automatically" button -- was the only one that
             * forgot `clearBlocked`. The block is keyed by field name and kept
             * alive by comparing the picked file's NAME, and a repair rewrites
             * the file in place under the same name. So the card went green and
             * the entry stayed live: the strip said
             *
             *     OK Gene expression: 112 rows - 1 value column
             *
             * while the submit interceptor still refused, with
             *
             *     X Gene expression: the server will reject this file
             *
             * -- two verdicts on the same file, from this module, at the same
             * moment. The banner renders at the END of the form, so from the
             * top of a long Step 1 the Run button simply looks dead. Hit on the
             * reporting user's own DEGs2.txt, whose only fault was decimal
             * commas that this very button had just fixed.
             */
            var applyRepair = function () {
                replaceFile(input, repaired.rows, file.name);
                clearBlocked(fieldName);
                renderOk(hostFor(input), validate(repaired.rows).summary, false, input);
            };

            if (fixable) {
                if (autoApply) { applyRepair(); return; }
                markBlocked(fieldName, {
                    fieldName: fieldName, fileName: file.name, input: input,
                    omic: strip.__omic, fixable: true, apply: applyRepair
                });
                renderProblem(strip, "warn", describeProblems(result),
                    repairs.map(function (r) { return r.describe(); }).join(" ") +
                    " This is a direct find-and-replace, not an AI conversion.",
                    [{ label: "Fix automatically", primary: true, onClick: applyRepair }]);
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
                (partial ? "Checked the first few megabytes of a large file. " : "") + aiExplainer(),
                aiActions(input, file, fieldName));
        };
        reader.readAsArrayBuffer(slice);
    }

    /* Layer 2 hand-off. Replaced by convert-drawer.js when that ships; until
       then it says so plainly rather than doing nothing, because a button that
       silently does nothing reads as a broken page. */
    function requestAgent(input, file, fieldName, serverSaid, siblings) {
        if (window.PaintomicsInputFormat.openConvertDrawer) {
            // What the server said, when it is the server that refused, and
            // what the job's other files look like. The agent is otherwise
            // reading ONE file blind against a fault that is not in it: these
            // files disagree with EACH OTHER, and no single one of them is
            // wrong on its own -- the format check passed all of them.
            if (serverSaid) { input.__paServerSaid = serverSaid; }
            if (siblings) { input.__paSiblings = siblings; }
            // The slot's role goes with it. The drawer decides from this which
            // produced file belongs back in the field the user started from --
            // without it, it can only recognise a `values` table, and a
            // conversion that produces a design or an associations file has no
            // way home.
            window.PaintomicsInputFormat.openConvertDrawer(
                input, file, fieldName, roleForInput(input));
            return;
        }
        var strip = hostFor(input);
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
        var field = extFieldFor(input);
        return (field && field.name) || null;
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

        if (fixable.length !== entries.length) {
            var convert = el("button", "pa-format-button pa-format-primary");
            convert.type = "button";
            if (typeof window.getAIMark === "function") {
                convert.innerHTML = window.getAIMark();
                convert.appendChild(document.createTextNode(" Convert with the PaintOmics AI agent"));
            } else {
                convert.textContent = "Convert with the PaintOmics AI agent";
            }
            convert.addEventListener("click", function () {
                var first = entries[0];
                var picked = first.input.files && first.input.files[0];
                if (picked) requestAgent(first.input, picked, first.fieldName);
            });
            bar.appendChild(convert);
        }

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
    /* What every OTHER file in this job looks like, one line each.
     *
     * The converter is per-file, and the failures that actually reach a user
     * with real data are not. Each file here is individually valid -- the
     * client check passes all of them -- and they are wrong TOGETHER:
     *
     *   MORE ERROR: No common sample names across input files.
     *   Target samples: DSSmEVs_vs_DSS
     *   Condition rows: 1-C1, 2-C2, 3-C3, ...
     *   miRNA-Seq_data samples: DSS_SDmEV_vs_DSS
     *
     * Nothing about the regulator file on its own says that. The agent needs
     * to see the design file's sample column and the target file's headers
     * next to it, or it re-reads a valid file and finds nothing wrong.
     *
     * Only the HEADER of each -- the first 64 KB is read, never the
     * measurements -- because column names are what disagree. Same rule as the
     * rest of this module: the numbers stay in the browser.
     */
    function siblingSummaries(exceptInput) {
        if (!window.Ext || !Ext.ComponentQuery) return Promise.resolve([]);
        var jobs = [];
        Ext.ComponentQuery.query("filefield").forEach(function (field) {
            var role = roleForField(field);
            if (!role) return;
            var dom = field.fileInputEl && field.fileInputEl.dom;
            var file = dom && dom.files && dom.files[0];
            if (!file || dom === exceptInput) return;
            var card = field.up && field.up("[cls~=omicbox]");
            var nameField = card && card.queryById && card.queryById("omicNameField");
            jobs.push(new Promise(function (resolve) {
                var reader = new FileReader();
                reader.onload = function () {
                    var first = String(reader.result || "").split(/\r?\n/)[0] || "";
                    var cells = first.split(first.indexOf("\t") !== -1 ? "\t" : ",");
                    resolve({
                        name: file.name, role: role,
                        omic: (nameField && nameField.getValue && nameField.getValue()) || "",
                        columns: cells.length,
                        header: cells.slice(0, 12).join(" | ")
                    });
                };
                reader.onerror = function () { resolve(null); };
                reader.readAsText(file.slice(0, 65536));
            }));
        });
        return Promise.all(jobs).then(function (all) {
            return all.filter(Boolean);
        });
    }

    /* The sibling summaries as one instruction the agent can read. */
    function siblingBrief(summaries) {
        if (!summaries.length) return "";
        return "The other files in this job, so you can judge whether they " +
               "agree with each other (only their first line was read):\n" +
               summaries.map(function (f) {
                   return "- " + f.name + " (" + f.role +
                          (f.omic ? ", omic \u201C" + f.omic + "\u201D" : "") +
                          ", " + f.columns + " columns): " + f.header;
               }).join("\n");
    }

    /* The values file of whichever omic card the error names.
     *
     * Second chance for the errors that identify the omic rather than the
     * file, which is most of what the analysis stage produces: it knows which
     * omic it was modelling, not which upload the bytes came from. */
    function pickedFileForOmicNamedIn(text) {
        if (!window.Ext || !Ext.ComponentQuery) return null;
        var haystack = String(text).replace(/[\s_]+/g, " ").toLowerCase();
        var fields = Ext.ComponentQuery.query("filefield");
        for (var i = 0; i < fields.length; i++) {
            if (roleForField(fields[i]) !== "values") continue;
            var dom = fields[i].fileInputEl && fields[i].fileInputEl.dom;
            var file = dom && dom.files && dom.files[0];
            if (!file) continue;
            /* `[cls~=omicbox]`, not `.omicbox`: ComponentQuery has no CSS
               class selector, and `.omicbox` silently matches nothing. Same
               family as the `[cls=omicbox]` exact-match trap that has caught
               this file's neighbours -- one entry of the whitespace list, not
               the whole string and not a CSS class. */
            var card = fields[i].up && fields[i].up("[cls~=omicbox]");
            var nameField = card && card.queryById && card.queryById("omicNameField");
            var omic = nameField && nameField.getValue && nameField.getValue();
            if (!omic || String(omic).trim().length < 3) continue;
            var needle = String(omic).replace(/[\s_]+/g, " ").trim().toLowerCase();
            if (haystack.indexOf(needle) !== -1) {
                return { input: dom, file: file, fieldName: fields[i].name };
            }
        }
        return null;
    }

    function pickedFileMatching(reportedName) {
        if (!window.Ext || !Ext.ComponentQuery) return null;
        var fields = Ext.ComponentQuery.query("filefield");
        for (var i = 0; i < fields.length; i++) {
            if (!roleForField(fields[i])) continue;
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

        /* Which file the server is complaining about, from ANY error that
           names one.
         *
         * This used to require the literal phrase "Errors detected while
         * processing", which is one servlet's wording. Every other failure --
         * and the ones that actually reach a user with real data are the MORE
         * ones -- says something else entirely, so the offer never appeared:
         *
         *   The MORE analysis failed (more-rs backend). Details:
         *   MORE ERROR: no data columns could be read from
         *     /.../inputData/mirna_values.tab
         *
         * That names the file perfectly well. So the dialog is read for
         * anything shaped like one of OUR file names and matched against what
         * the user actually picked, which is the question that was being asked
         * all along. Reported by a user watching a MORE run fail with the agent
         * sitting one click away and never offered. */
        var text = body.textContent || "";
        var picked = null;
        var names = text.match(/[\w./\\-]+\.(?:tab|txt|csv|tsv|xls|xlsx|xlsm|ods|gtf|bed)\b/gi) || [];
        for (var n = 0; n < names.length && !picked; n++) {
            picked = pickedFileMatching(names[n].replace(/^.*[\\/]/, ""));
        }
        /* Some failures name no file at all. The one that sent a user looking
           for this button is the clearest example -- it names sample names and
           an omic, and nothing else:

             MORE ERROR: No common sample names across input files.
             Target samples: DSSmEVs_vs_DSS
             Condition rows: 1-C1, 2-C2, 3-C3, ...
             miRNA-Seq_data samples: DSS_SDmEV_vs_DSS

           `miRNA-Seq_data` is the name the user typed into Omic Name, so the
           card is identifiable even though the file is not. Underscores because
           the backend substitutes them for spaces. */
        if (!picked) picked = pickedFileForOmicNamedIn(text);
        if (!picked) return;

        /* Two different offers, because they do different things and the
           difference matters. Re-checking applies a MECHANICAL repair and is
           only useful when the fault is one this module models. The agent can
           be told what the server said, which is the only route open when the
           server knows something the client checker does not -- a sample name
           that does not line up, an identifier space that does not match. */
        var wrap = el("span", null, null);
        wrap.id = "pa-format-dialog-fix";

        var ask = el("a", "button btn-secondary btn-right", "Ask the PaintOmics AI agent");
        ask.title = "Opens the agent on this file, with what the server said.";
        ask.href = "#";
        ask.style.display = "inline-block";
        ask.addEventListener("click", function (event) {
            event.preventDefault();
            var serverSaid = text.replace(/\s+/g, " ").trim();
            // Gathered BEFORE the dialog closes, while every field still holds
            // its file, so the agent starts with the whole job in front of it
            // rather than one file out of context.
            siblingSummaries(picked.input).then(function (others) {
                if (typeof closeButton.click === "function") closeButton.click();
                requestAgent(picked.input, picked.file, picked.fieldName,
                             serverSaid, siblingBrief(others));
            });
        });

        var again = el("a", "button btn-secondary btn-right", "Check this file again");
        again.title = "Re-reads the file and repairs what can be repaired mechanically.";
        again.href = "#";
        again.style.display = "inline-block";
        again.addEventListener("click", function (event) {
            event.preventDefault();
            if (typeof closeButton.click === "function") closeButton.click();
            check(picked.input, picked.file, picked.fieldName, true);
        });

        wrap.appendChild(again);
        wrap.appendChild(ask);
        closeButton.parentNode.insertBefore(wrap, closeButton);
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

    /*
     * The column moves when an omic is added or removed and when the window is
     * resized, and a region left at its old offset would sit under nothing.
     * Reposition on both, throttled to an animation frame.
     */
    // Capture phase: ExtJS re-dispatches and sometimes stops change events on
    // its own wrappers, and capture runs before any of that.
    /*
     * Every omic card starts with the AI's standing offer in its strip, so the
     * upload step reads as "bring any file" before a file is picked rather
     * than only after one fails. Cards are created by ExtJS on drag or on the
     * plus button, so they are found by watching the DOM; the strip is added
     * once the card is rendered, which is all `component.add()` needs. It used
     * to wait for a card taller than 100px as well, because the card's height
     * was recorded here as the base to grow from -- nothing is recorded now,
     * and that wait was in any case no guarantee the height had settled: on
     * the MORE card it fired at 662px against a settled 771px.
     */
    function primeCard(cardEl) {
        if (!cardEl || cardEl.__paPrimed || !window.Ext || !Ext.getCmp) return;
        var component = Ext.getCmp(cardEl.id);
        if (!component || !component.query) return;
        var hasValuesField = component.query("filefield").some(function (f) {
            return !!roleForField(f);
        });
        if (!hasValuesField) return;
        cardEl.__paPrimed = true;
        var prime = function () {
            if (component.isDestroyed || component.down("[itemId=paFormatHost]")) return;
            var strip = hostForComponent(component);
            if (!strip) return;
            renderIdle(strip);
            syncCardHeightFor(component);
        };
        if (component.rendered) prime();
        else component.on("afterlayout", prime, null, { single: true, delay: 30 });
    }

    function primeCardsIn(root) {
        if (!root || root.nodeType !== 1) return;
        if (root.matches && root.matches(".omicbox")) primeCard(root);
        if (root.querySelectorAll) {
            root.querySelectorAll(".omicbox").forEach(primeCard);
        }
    }

    if (typeof MutationObserver === "function") {
        var observer = new MutationObserver(function (records) {
            var found = [];
            records.forEach(function (r) {
                r.addedNodes.forEach(function (n) {
                    if (n.nodeType !== 1) return;
                    if (n.matches && n.matches(".omicbox")) found.push(n);
                    if (n.querySelectorAll) n.querySelectorAll(".omicbox").forEach(function (c) { found.push(c); });
                });
            });
            if (!found.length) return;
            /* paDeferFrame, not a bare requestAnimationFrame: Chrome throttles
               rAF to zero in a hidden tab, and a card primed in a bare frame
               would then have no strip and no input check at all until the tab
               came forward. Util.js keeps the house version of this -- rAF when
               visible, setTimeout(0) when hidden -- and four pieces of this app
               have already been caught scheduling layout work on the bare one.
               Guarded, because this module is loaded on its own in the tests. */
            var defer = window.paDeferFrame || requestAnimationFrame;
            defer(function () {
                found.forEach(function (c) {
                    try { primeCard(c); }
                    catch (e) { if (window.console && console.warn) console.warn("[inputformat] prime failed", e); }
                });
            });
        });
        observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
        primeCardsIn(document.body);
    }

    document.addEventListener("change", function (event) {
        var input = event.target;
        if (!input || input.type !== "file" || !input.files || !input.files.length) return;
        var name = extFieldNameFor(input);
        var role = roleForInput(input);
        if (!name || !role) return;
        try {
            check(input, input.files[0], name, false, role);
        } catch (e) {
            // Never let a check failure take the upload with it: the user can
            // always still submit, exactly as before this module existed.
            if (window.console && console.warn) console.warn("[inputformat] check failed", e);
        }
    }, true);
})();
