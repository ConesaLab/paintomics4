/*
 * Deterministic repairs for the format faults that have one obvious fix.
 *
 * The bar for belonging here is high: a repair must be unambiguous, reversible
 * in the user's head, and describable in one sentence. Anything requiring a
 * judgement call -- which column is the identifier, which of fifteen columns
 * are measurements -- is the agent's job, not this module's. Guessing here
 * would silently change someone's data with no record of why.
 *
 * Note what is deliberately ABSENT: a delimiter repair. Job.detect_delimiter
 * (Job.py:47) already accepts comma-separated files, so "converting" one to
 * tabs would be work with no effect.
 */
(function (root, factory) {
    if (typeof module === "object" && module.exports) module.exports = factory();
    else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var DECIMAL_COMMA = /^[+-]?\d+,\d+$/;
    var MAX_CHANGES_SHOWN = 20;

    function isBlankRow(row) {
        for (var i = 0; i < row.length; i++) {
            if (String(row[i]).trim() !== "") return false;
        }
        return true;
    }

    /*
     * A banner row carries content in column 0 and nothing anywhere else --
     * Excel's merged title cell, flattened by any export. It is distinct from a
     * blank row, and distinct from a real feature, whose second column must
     * hold a number.
     */
    function isBannerRow(row) {
        if (row.length < 2) return false;
        if (String(row[0]).trim() === "") return false;
        for (var i = 1; i < row.length; i++) {
            if (String(row[i]).trim() !== "") return false;
        }
        return true;
    }

    function lastMeaningfulColumn(rows) {
        var width = 0;
        for (var i = 0; i < rows.length; i++) width = Math.max(width, rows[i].length);
        while (width > 1) {
            var allBlank = true;
            for (var r = 0; r < rows.length; r++) {
                var row = rows[r];
                if (row.length >= width && String(row[width - 1]).trim() !== "") {
                    allBlank = false;
                    break;
                }
            }
            if (!allBlank) break;
            width--;
        }
        return width;
    }

    function proposeRepairs(rows, delimiter, problems) {
        var repairs = [];
        if (!rows || !rows.length) return repairs;

        var codes = {};
        for (var i = 0; i < (problems || []).length; i++) codes[problems[i].code] = true;

        /*
         * Only safe when the delimiter is a tab. In a comma-delimited file the
         * decimal comma was already consumed as a field separator before this
         * code ever saw the row, so the original values cannot be recovered and
         * any "fix" would be fabrication.
         */
        if (delimiter === "\t" && codes.DECIMAL_COMMA) {
            repairs.push({
                id: "DECIMAL_COMMA",
                label: "Use dots as the decimal mark",
                describe: function () {
                    return "Rewrites values like 0,77 as 0.77. Identifiers are left alone.";
                },
                apply: function (input) {
                    return input.map(function (row, index) {
                        if (index === 0) return row;           // never touch the header
                        return row.map(function (cell, column) {
                            var text = String(cell).trim();
                            return column > 0 && DECIMAL_COMMA.test(text)
                                ? text.replace(",", ".")
                                : cell;
                        });
                    });
                }
            });
        }

        var width = 0;
        for (var w = 0; w < rows.length; w++) width = Math.max(width, rows[w].length);
        if (width > 1 && lastMeaningfulColumn(rows) < width) {
            repairs.push({
                id: "TRIM_TRAILING_EMPTY",
                label: "Remove empty trailing columns",
                describe: function () {
                    return "Drops columns that are blank on every row, which spreadsheets often add.";
                },
                apply: function (input) {
                    var keep = lastMeaningfulColumn(input);
                    return input.map(function (row) { return row.slice(0, keep); });
                }
            });
        }

        var hasBlank = false;
        for (var b = 0; b < rows.length; b++) {
            if (isBlankRow(rows[b])) { hasBlank = true; break; }
        }
        if (hasBlank) {
            repairs.push({
                id: "DROP_BLANK_LINES",
                label: "Remove blank lines",
                describe: function () { return "Drops rows that are empty in every column."; },
                apply: function (input) {
                    return input.filter(function (row) { return !isBlankRow(row); });
                }
            });
        }

        var hasBanner = false;
        for (var n = 1; n < rows.length; n++) {
            if (isBannerRow(rows[n])) { hasBanner = true; break; }
        }
        if (hasBanner) {
            repairs.push({
                id: "DROP_BANNER_ROW",
                label: "Remove title rows",
                describe: function () {
                    return "Drops rows holding a title in the first column and nothing else.";
                },
                // Index 0 is exempt: the header legitimately has no numbers, and
                // a one-column header would otherwise look exactly like a banner.
                apply: function (input) {
                    return input.filter(function (row, index) {
                        return index === 0 || !isBannerRow(row);
                    });
                }
            });
        }

        return repairs;
    }

    /*
     * Applies repairs in order and returns a bounded change list.
     *
     * The change list is what the user is shown before accepting, so it is
     * built by comparing rendered rows rather than by each repair reporting its
     * own edits -- that way the diff describes the end state, which is what the
     * user actually gets, rather than an intermediate one.
     */
    function applyRepairs(rows, repairs) {
        var before = rows.map(function (row) { return row.join("\t"); });
        var out = rows;
        for (var i = 0; i < repairs.length; i++) out = repairs[i].apply(out);

        var after = out.map(function (row) { return row.join("\t"); });
        var changes = [];

        // Row indices shift when rows are dropped, so compare as sequences:
        // walk both and record where they diverge, rather than pairing by index.
        var a = 0;
        for (var b = 0; b < before.length && changes.length < MAX_CHANGES_SHOWN; b++) {
            if (a < after.length && after[a] === before[b]) { a++; continue; }
            if (a < after.length && after.indexOf(before[b], a) === -1) {
                changes.push({ line: b, before: before[b], after: after[a] === undefined ? null : after[a] });
                a++;
            } else {
                changes.push({ line: b, before: before[b], after: null });
            }
        }

        return { rows: out, changes: changes };
    }

    return {
        proposeRepairs: proposeRepairs,
        applyRepairs: applyRepairs,
        isBannerRow: isBannerRow,
        isBlankRow: isBlankRow
    };
});
