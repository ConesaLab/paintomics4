/*
 * The other file contracts PaintOmics accepts.
 *
 * A values matrix is not the only thing a job takes, and the rules genuinely
 * differ -- an associations file must have exactly two columns and both are
 * text, which is the precise opposite of what a values file requires. Grading
 * every produced file against the values contract would reject correct work.
 *
 * Transcribed from PathwayAcquisitionJob.py: associations at :545-568,
 * relevant-associations at :569-596, relevant features at :606-660; and the
 * MORE design matrix from MOREServlet.py:429-480.
 */
(function (root, factory) {
    if (typeof module === "object" && module.exports) module.exports = factory();
    else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var V = (typeof module === "object" && module.exports)
        ? require("./format-validator.js")
        : (typeof self !== "undefined" ? self.PaintomicsInputFormat : this.PaintomicsInputFormat);

    var MAX_NUMBER_FEATURES = 1000000;

    function problem(code, line, detail) {
        return { code: code, line: line, detail: detail };
    }

    function nonEmptyRows(rows) {
        return (rows || []).filter(function (r) {
            return r.length && r.some(function (c) { return String(c).trim() !== ""; });
        });
    }

    /* Exactly two columns on every line. */
    function validateAssociations(rows) {
        var problems = [];
        var body = nonEmptyRows(rows);
        if (!body.length) problems.push(problem("EMPTY", 0, "The file is empty."));
        body.forEach(function (r, i) {
            if (i > MAX_NUMBER_FEATURES) return;
            if (r.length !== 2) {
                problems.push(problem("NOT_TWO_COLUMNS", i,
                    "Expected 2 columns (Target, Regulator) but found " + r.length + "."));
            }
        });
        return { ok: problems.length === 0, problems: problems.slice(0, 10),
                 summary: { nRows: body.length, nCols: 2 } };
    }

    /* One or two columns. */
    function validateRelevantAssociations(rows) {
        var problems = [];
        var body = nonEmptyRows(rows);
        if (!body.length) problems.push(problem("EMPTY", 0, "The file is empty."));
        body.forEach(function (r, i) {
            if (r.length !== 1 && r.length !== 2) {
                problems.push(problem("BAD_COLUMN_COUNT", i,
                    "Expected 1 or 2 columns but found " + r.length + "."));
            }
        });
        return { ok: problems.length === 0, problems: problems.slice(0, 10),
                 summary: { nRows: body.length } };
    }

    /*
     * A list of identifiers, one per line -- or one column per condition when it
     * carries per-condition relevance. `conditions` is the number of value
     * columns in the matching values file; when it is unknown only the shape is
     * checked, because demanding a specific width without knowing it would
     * reject valid files.
     */
    function validateRelevant(rows, conditions) {
        var problems = [];
        var body = nonEmptyRows(rows);
        if (!body.length) {
            problems.push(problem("EMPTY", 0, "The file is empty."));
            return { ok: false, problems: problems, summary: { nRows: 0 } };
        }
        var width = body[0].length;
        body.forEach(function (r, i) {
            if (r.length !== width) {
                problems.push(problem("RAGGED", i,
                    "Expected " + width + " columns but found " + r.length + "."));
            }
            r.forEach(function (cell) {
                // The server rejects a field over 80 characters as "not a list
                // of identifiers at all".
                if (String(cell).trim().length > 80) {
                    problems.push(problem("FIELD_TOO_LONG", i,
                        "A field is longer than 80 characters; this does not look like an identifier."));
                }
            });
        });
        // Legacy two-column target/regulator pair lists are accepted whatever
        // the condition count -- MiRNA2GenesServlet emits them for the
        // regulatory workflow.
        if (typeof conditions === "number" && conditions > 0 && width > 1 && width !== 2 &&
            width !== conditions) {
            problems.push(problem("CONDITION_MISMATCH", 0,
                "The file has " + width + " columns but the values file declares " +
                conditions + " conditions."));
        }
        return { ok: problems.length === 0, problems: problems.slice(0, 10),
                 summary: { nRows: body.length, nCols: width } };
    }

    /*
     * MORE's experimental design: a Sample column followed by one indicator
     * column per condition, every cell 0 or 1, and exactly one 1 per row --
     * a sample belongs to one condition. See
     * `more-condition-columns-are-indicator-patterns`.
     */
    function validateDesign(rows) {
        var problems = [];
        var body = nonEmptyRows(rows);
        if (body.length < 2) {
            problems.push(problem("EMPTY", 0, "A design file needs a header and at least one sample."));
            return { ok: false, problems: problems, summary: { nRows: 0 } };
        }
        var header = body[0];
        if (header.length < 2) {
            problems.push(problem("TOO_FEW_COLUMNS", 0,
                "Expected a Sample column and at least one condition column."));
        }
        body.slice(1).forEach(function (r, i) {
            var line = i + 1;
            if (r.length !== header.length) {
                problems.push(problem("RAGGED", line,
                    "Expected " + header.length + " columns but found " + r.length + "."));
                return;
            }
            var ones = 0;
            r.slice(1).forEach(function (cell) {
                var t = String(cell).trim();
                if (t !== "0" && t !== "1") {
                    problems.push(problem("NOT_INDICATOR", line,
                        "Condition columns must be 0 or 1, found " + JSON.stringify(t) + "."));
                } else if (t === "1") ones++;
            });
            if (ones !== 1) {
                problems.push(problem("NOT_ONE_CONDITION", line,
                    "Each sample must belong to exactly one condition, found " + ones + "."));
            }
        });
        return { ok: problems.length === 0, problems: problems.slice(0, 10),
                 summary: { nRows: body.length - 1, nCols: header.length,
                            conditions: header.slice(1) } };
    }

    var ROLES = ["values", "relevant", "associations", "relevant-associations", "design"];

    /*
     * A LAST-RESORT guess at a file's contract from its name.
     *
     * Names are not reliable evidence of a file's shape and this codebase has
     * been bitten by trusting them before. Measured here: the shipped
     * `mirna_to_gene_associations.tab` has THREE columns -- miRNA, Ensembl gene,
     * PLR -- because it belongs to the MiRNA2Genes tool, not to the two-column
     * associations contract its name suggests. A name-based classifier calls it
     * an associations file and rejects a perfectly good input.
     *
     * So the agent DECLARES the role of every file it writes, in
     * /out/manifest.json, and that declaration is what grading uses. This
     * function only covers a script that forgot the manifest, and it defaults to
     * "values" -- the strictest contract -- so a wrong guess fails loudly rather
     * than passing something malformed.
     */
    function roleForFileName(name) {
        var n = String(name).toLowerCase();
        if (/(^|[_-])design/.test(n)) return "design";
        if (/relevant.*association|association.*relevant/.test(n)) return "relevant-associations";
        if (/(^|[_-])associations?\.(tab|tsv|txt|csv)$/.test(n)) return "associations";
        if (/relevant/.test(n)) return "relevant";
        return "values";
    }

    /* Roles declared by the conversion script, read from /out/manifest.json. */
    function rolesFromManifest(outputs, decode) {
        var declared = {};
        if (!outputs || !outputs["manifest.json"]) return declared;
        try {
            var parsed = JSON.parse(decode(outputs["manifest.json"]));
            (parsed.files || []).forEach(function (f) {
                if (f && f.name && ROLES.indexOf(f.role) !== -1) declared[f.name] = f.role;
            });
        } catch (e) { /* a broken manifest falls back to the name guess */ }
        return declared;
    }

    var COORD_START = /^(start|begin|from|chromstart)$/i;
    var COORD_END = /^(end|stop|to|chromend)$/i;
    var COORD_CHR = /^#?\s*(chr|chrom|chromosome|seqname)$/i;

    /*
     * A region-based matrix hides a failure the values contract cannot see.
     *
     * Its first THREE columns are chromosome, start and end -- and start and end
     * are numbers, so a file that has lost every measurement column still looks
     * like "an identifier plus two numeric conditions" and passes. Measured: a
     * conversion selected zero condition columns (its filter tested
     * "00h".isdigit()), produced chr/start/end only, and was graded valid.
     *
     * So when the header says these are coordinates, require at least one
     * column beyond them. The server shares this blind spot; catching it here
     * stops a silently empty file reaching a job.
     */
    function looksLikeRegionHeader(row) {
        return !!row && row.length >= 3 &&
               COORD_CHR.test(String(row[0]).trim()) &&
               COORD_START.test(String(row[1]).trim()) &&
               COORD_END.test(String(row[2]).trim());
    }

    function validateValuesWithRegionCheck(rows) {
        var report = V.validateValues(rows);
        if (!rows || !rows.length) return report;
        if (!looksLikeRegionHeader(rows[0])) return report;

        report.summary.regionBased = true;
        if (report.summary.nCols <= 3) {
            report.problems = (report.problems || []).concat([{
                code: "REGION_HAS_NO_MEASUREMENTS", line: 0,
                detail: "The first three columns are chromosome, start and end, and there " +
                        "are no columns after them. Every measurement has been lost."
            }]);
            report.ok = false;
        }
        return report;
    }

    function validateForRole(role, rows, conditions) {
        if (role === "associations") return validateAssociations(rows);
        if (role === "relevant-associations") return validateRelevantAssociations(rows);
        if (role === "relevant") return validateRelevant(rows, conditions);
        if (role === "design") return validateDesign(rows);
        return validateValuesWithRegionCheck(rows);
    }

    return {
        validateAssociations: validateAssociations,
        validateRelevantAssociations: validateRelevantAssociations,
        validateRelevant: validateRelevant,
        validateDesign: validateDesign,
        roleForFileName: roleForFileName,
        rolesFromManifest: rolesFromManifest,
        ROLES: ROLES,
        validateForRole: validateForRole,
        looksLikeRegionHeader: looksLikeRegionHeader,
        validateValuesWithRegionCheck: validateValuesWithRegionCheck
    };
});
