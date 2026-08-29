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

    /* A regulator-to-target table: two identifier columns, and optionally a
     * third holding a prediction score.
     *
     * This is the miRNA panel's "targets" slot -- mirna_to_gene_associations.tab
     * and mmu_mirBase_to_ensembl.tab both ship as miRNA / Ensembl.Gene.ID / PLR
     * -- which is why it could not be held to the 2-column `associations`
     * contract and was left with no role at all. Left unchecked, it accepted
     * the file that broke a real run: 6,039 rows whose target column was empty.
     */
    function validateRegulatorTargets(rows) {
        var problems = [];
        var body = nonEmptyRows(rows);
        if (!body.length) problems.push(problem("EMPTY", 0, "The file is empty."));
        body.forEach(function (r, i) {
            if (i > MAX_NUMBER_FEATURES) return;
            /* Fewer than two is the only shape the server cannot use:
               miRNA2Target.py reads line[0] and line[1] and ignores the rest,
               and runMORE.R documents a third column and tolerates more. */
            if (r.length < 2) {
                problems.push(problem("BAD_COLUMN_COUNT", i,
                    "Expected at least 2 columns (Regulator, Target[, score]) but found " +
                    r.length + "."));
            }
        });
        return { ok: problems.length === 0, problems: problems.slice(0, 10),
                 summary: { nRows: body.length } };
    }

    /* One or two columns. Empty is fine: a run whose correlation filter kept
       no pair writes an empty relevant-associations file, and the server's
       loop over it (PathwayAcquisitionJob.py, the relevant-associations
       reader) raises nothing on zero lines -- the same reason third/fourth
       FileSelector are exempt from checking altogether. */
    function validateRelevantAssociations(rows) {
        var problems = [];
        var body = nonEmptyRows(rows);
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
        /* What runMORE.R's read_matrix actually requires, replicated in R
           4.6.0: a header of N or N-1 cells (R's own write.table default
           leaves the row-name column unnamed), numeric cells, unique sample
           names -- and nothing else. The first cut also demanded 0/1 cells
           with exactly one 1 per row, and blocked three files R accepts: an
           R-written header one cell short, a multi-factor row (which
           MOREServlet._designPatternNames handles on purpose), and numeric
           levels such as Time 0/24/48. The design-matrix advice stays as
           advice; only what R rejects is refused here. */
        var header = body[0];
        var samples = body.slice(1);
        var wide = samples.length && samples.every(function (r) { return r.length === header.length + 1; });
        var width = wide ? header.length + 1 : header.length;
        var conditions = wide ? header.slice(0) : header.slice(1);
        if (width < 2) {
            problems.push(problem("TOO_FEW_COLUMNS", 0,
                "Expected a Sample column and at least one condition column."));
        }
        samples.forEach(function (r, i) {
            var line = i + 1;
            if (r.length !== width) {
                problems.push(problem("RAGGED", line,
                    "Expected " + width + " columns but found " + r.length + "."));
                return;
            }
            r.slice(1).forEach(function (cell) {
                var t = String(cell).trim();
                if (!V.isPythonFloat(t)) {
                    problems.push(problem("NOT_INDICATOR", line,
                        "Condition columns must be numeric (1/0 indicators), found " + JSON.stringify(t) + "."));
                }
            });
        });
        return { ok: problems.length === 0, problems: problems.slice(0, 10),
                 summary: { nRows: samples.length, nCols: width, conditions: conditions } };
    }


    /*
     * The metabolomics panel's replicate design: which condition each value
     * column belongs to, so the class activity test can use the variance
     * between replicates. It is what src/common/DesignFile.py parse_design
     * reads, and that reader takes two shapes: the long form --
     * `column<TAB>condition`, one row per value column, an optional `#`
     * header -- or MORE's indicator matrix, judged by validateDesign.
     *
     * This is its own role and not a looser `design` on purpose. The first
     * cut widened `design` to take the long form, and CI caught what that
     * meant: `s1 control / s2 treated` -- the exact file runMORE.R must
     * REFUSE, because as.numeric turns a text label into NA -- started
     * passing for MORE's Conditions slot (test_conditions_file_is_held_to_r_rules).
     */
    function validateReplicates(rows) {
        var body = nonEmptyRows(rows).filter(function (r) {
            return String(r[0]).trim().charAt(0) !== "#";
        });
        var longForm = body.every(function (r) { return r.length === 2; });
        if (body.length < 2 || !longForm) {
            /* The matrix shape, under the matrix's rules -- but a text cell
               here is not "a conditions file holding text": the user of THIS
               slot has a second shape open to them, and the sentence should
               say so. Its own code, so describeProblems can. */
            var report = validateDesign(rows);
            (report.problems || []).forEach(function (p) {
                if (p.code === "NOT_INDICATOR") p.code = "TEXT_IN_DESIGN_MATRIX";
            });
            return report;
        }
        var problems = [];
        var seen = {}, labels = [], seenLabel = {};
        body.forEach(function (r, i) {
            var sample = String(r[0]).trim(), label = String(r[1]).trim();
            if (!sample) {
                problems.push(problem("BLANK_IDENTIFIER", i, "A design row needs the value column's name."));
                return;
            }
            if (!label) {
                problems.push(problem("NO_CONDITION", i, "Column " + JSON.stringify(sample) + " has no condition."));
            } else if (!seenLabel[label]) {
                seenLabel[label] = true;
                labels.push(label);
            }
            if (seen[sample]) {
                problems.push(problem("DUPLICATE_IDENTIFIER", i, "Column " + JSON.stringify(sample) + " appears twice."));
            }
            seen[sample] = true;
        });
        return { ok: problems.length === 0, problems: problems.slice(0, 10),
                 summary: { nRows: body.length, nCols: 2, longForm: true, conditions: labels } };
    }

    var ROLES = ["values", "relevant", "associations", "relevant-associations",
                 "regulator-targets", "design", "replicates"];

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

    /* How wide the identifier is.
     *
     * One column normally, three for a region file, where chr/start/end
     * together name the feature and column 0 alone repeats for every region on
     * a chromosome. Lifted from convert-agent.js, which has graded the AI's
     * own output this way since the converter shipped -- the rule was right,
     * it just never ran on a file the user picked themselves. */
    function idColumnCount(body) {
        if (!body.length || body[0].length < 4) return 1;
        var sample = body.slice(0, 200);
        var pairs = 0, checked = 0;
        for (var i = 0; i < sample.length; i++) {
            var a = sample[i][1], b = sample[i][2];
            if (!/^-?\d+$/.test(String(a).trim()) || !/^-?\d+$/.test(String(b).trim())) return 1;
            checked++;
            if (parseInt(b, 10) >= parseInt(a, 10)) pairs++;
        }
        return (checked && pairs / checked >= 0.9) ? 3 : 1;
    }

    /* Every identifier that names more than one row, worst first. */
    function duplicateIdentifiers(rows) {
        var all = nonEmptyRows(rows);
        if (!all.length) return { count: 0, rows: 0, worst: null, worstCount: 0 };
        var header = all[0].slice(1).every(function (c) { return V.isPythonFloat(String(c)); })
            ? null : all[0];
        var body = header ? all.slice(1) : all;
        var idCols = idColumnCount(body);
        var seen = Object.create(null), repeated = 0, rowsOver = 0;
        var worst = null, worstCount = 0;
        for (var i = 0; i < body.length; i++) {
            var key = body[i].slice(0, idCols).map(function (c) { return String(c).trim(); }).join(":");
            if (key.replace(/:/g, "") === "") continue;
            seen[key] = (seen[key] || 0) + 1;
            if (seen[key] === 2) repeated++;
            if (seen[key] > 1) rowsOver++;
            if (seen[key] > worstCount) { worstCount = seen[key]; worst = key; }
        }
        return { count: repeated, rows: rowsOver, worst: worst, worstCount: worstCount };
    }

    /* How many leading cells of a row are its identifier, per role.
     *
     * `values` and `design` defer to idColumnCount, which returns 3 for a
     * region-based table (id, start, end) and 1 otherwise. The pair roles hold
     * two ids side by side; a relevant-associations file may legitimately be a
     * single column. */
    function idColumnsForRole(role, body) {
        var width = body.length ? body[0].length : 0;
        if (role === "associations" || role === "regulator-targets") return Math.min(2, width);
        if (role === "relevant-associations") return Math.min(2, width);
        if (role === "relevant") return 1;
        return idColumnCount(body);
    }

    /* Rows whose identifier cell is blank.
     *
     * An identifier is what makes a row mean anything, and a blank one is worse
     * than a missing row: `""` is a valid key, so it JOINS -- to every other
     * blank cell in every other file. Measured on a user's real job
     * (2026-08-27): their targets file held 6,039 rows with an empty target id
     * and their expression file 13 rows with an empty gene id, so `""` matched
     * `""` and those 6,039 pairs were the only ones the server scored. Every
     * real target was an ENSMUSG id and the expression file was keyed by gene
     * symbol -- a true overlap of zero. The run was reported as a SUCCESS and
     * produced an associations file that was blank down its whole first column.
     *
     * The header is skipped the same way duplicateIdentifiers skips it, so a
     * labelled first row is not counted as a fault. */
    function blankIdentifiers(rows, role) {
        var all = nonEmptyRows(rows);
        if (!all.length) return { rows: 0, first: 0, column: 1 };
        /* A relevance list wider than one column is one column PER CONDITION
           (example 03-gene-multi-condition-relevance): a gene not relevant in
           condition 1 has an empty first cell, and that is the format, not a
           fault -- the server's parseSignificativeFeaturesFile skips blank
           cells by design. Only the one-column list keys on column 1, and
           nonEmptyRows already guarantees each row holds something. */
        if (role === "relevant" && all[0].length > 1) {
            return { rows: 0, first: 0, column: 1, total: all.length };
        }
        var header = all[0].slice(1).every(function (c) { return V.isPythonFloat(String(c)); })
            ? null : all[0];
        var body = header ? all.slice(1) : all;
        var idCols = idColumnsForRole(role, body);
        var offset = header ? 2 : 1;
        var count = 0, first = 0, column = 1;
        for (var i = 0; i < body.length; i++) {
            for (var c = 0; c < idCols; c++) {
                if (String(body[i][c] === undefined ? "" : body[i][c]).trim() === "") {
                    count++;
                    if (!first) { first = i + offset; column = c + 1; }
                    break;
                }
            }
        }
        return { rows: count, first: first, column: column, total: body.length };
    }

    /* The roles whose identifier has to be unique.
     *
     * `values` and `design` are read into a matrix keyed on the identifier --
     * runMORE.R:82 uses row.names=1, and the Rust port reproduces the same
     * rejection deliberately (MORE/rust/src/data.rs:141) -- so a repeat is
     * fatal on both engines, not a matter of taste.
     *
     * The association roles are deliberately absent: many regulators to one
     * target is the whole point of those files, and a repeated identifier
     * there is the file working as intended. */
    var UNIQUE_KEY_ROLES = { values: true, design: true, replicates: true };

    /* options.strictKeys: the file is bound for a MORE slot, whose R/Rust
       matrix readers refuse a repeated key. Anywhere else a repeated
       identifier in a values file is MERGED by the server
       (Job.addInputGeneData -> addOmicValues) and never rejected -- so a hard
       block there was a false "the server will reject this file", and it
       also took the decimal-comma repair away from files that carried both
       (the repair is only offered when the repaired file validates). Outside
       MORE the repeat is reported on the summary and the file stays OK. */
    function validateForRole(role, rows, conditions, options) {
        options = options || {};
        var report;
        if (role === "regulator-targets") report = validateRegulatorTargets(rows);
        else if (role === "associations") report = validateAssociations(rows);
        else if (role === "relevant-associations") report = validateRelevantAssociations(rows);
        else if (role === "relevant") report = validateRelevant(rows, conditions);
        else if (role === "design") report = validateDesign(rows);
        else if (role === "replicates") report = validateReplicates(rows);
        else report = validateValuesWithRegionCheck(rows);

        var blank = blankIdentifiers(rows, role);
        if (blank.rows) {
            report.problems = (report.problems || []).concat([
                problem("BLANK_IDENTIFIER", blank.first, {
                    rows: blank.rows, total: blank.total,
                    line: blank.first, column: blank.column
                })
            ]);
            report.ok = false;
        }

        if (UNIQUE_KEY_ROLES[role || "values"]) {
            var dup = duplicateIdentifiers(rows);
            if (dup.count) {
                var detail = { ids: dup.count, rows: dup.rows,
                               worst: dup.worst, worstCount: dup.worstCount };
                if (role === "design" || role === "replicates" || options.strictKeys) {
                    report.problems = (report.problems || []).concat([
                        problem("DUPLICATE_IDENTIFIER", 0, detail)
                    ]);
                    report.ok = false;
                } else {
                    report.summary = report.summary || {};
                    report.summary.duplicates = detail;
                }
            }
        }
        return report;
    }

    return {
        validateAssociations: validateAssociations,
        validateRegulatorTargets: validateRegulatorTargets,
        blankIdentifiers: blankIdentifiers,
        validateRelevantAssociations: validateRelevantAssociations,
        validateRelevant: validateRelevant,
        validateDesign: validateDesign,
        validateReplicates: validateReplicates,
        roleForFileName: roleForFileName,
        rolesFromManifest: rolesFromManifest,
        ROLES: ROLES,
        validateForRole: validateForRole,
        duplicateIdentifiers: duplicateIdentifiers,
        looksLikeRegionHeader: looksLikeRegionHeader,
        validateValuesWithRegionCheck: validateValuesWithRegionCheck
    };
});
