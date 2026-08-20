/*
 * Reads a delimited text file the way the server will read it.
 *
 * The point of this module is fidelity, not convenience: every decision here
 * mirrors a decision in PaintomicsServer. If the two drift, the client tells
 * the user a file is fine and the server then rejects it, which is worse than
 * having no check at all. The mirrored code is Job.detect_delimiter
 * (Job.py:47), the ensure_utf8 call and the csv_reader loop in
 * PathwayAcquisitionJob.py:660-745.
 */
(function (root, factory) {
    if (typeof module === "object" && module.exports) module.exports = factory();
    else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    /*
     * Mirrors Job.detect_delimiter. Only the FIRST non-empty line votes, a tab
     * beats a comma on that line, and a line with neither still yields a tab.
     * The consequence worth knowing: a comma-separated file whose header
     * happens to contain a tab is read as TSV by the server too, so reproducing
     * the quirk is what keeps the two in agreement.
     */
    function detectDelimiter(text) {
        var lines = text.split("\n");
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (!line) continue;
            if (line.indexOf("\t") > -1) return "\t";
            if (line.indexOf(",") > -1) return ",";
            return "\t";
        }
        return "\t";
    }

    /*
     * Field splitter matching Python's csv.reader for the shapes omics files
     * take: quotes group a field, "" inside quotes is a literal quote, and a
     * delimiter inside quotes is data rather than a separator.
     */
    function splitLine(line, delimiter) {
        var out = [];
        var field = "";
        var quoted = false;
        for (var i = 0; i < line.length; i++) {
            var c = line.charAt(i);
            if (quoted) {
                if (c === '"') {
                    if (line.charAt(i + 1) === '"') { field += '"'; i++; }
                    else quoted = false;
                } else field += c;
            } else if (c === '"') {
                quoted = true;
            } else if (c === delimiter) {
                out.push(field);
                field = "";
            } else {
                field += c;
            }
        }
        out.push(field);
        return out;
    }

    /*
     * bytes: Uint8Array. Returns {encoding, delimiter, rows, decodeError}.
     *
     * A decode error is returned rather than thrown because it is a normal
     * outcome for a user file -- a latin-1 export is a thing people upload --
     * and the caller turns it into a repair suggestion, not a stack trace.
     */
    function readDelimited(bytes) {
        var encoding = "utf-8";
        var body = bytes;

        // utf-8-sig on the server strips the BOM; do the same, or the first
        // identifier silently carries a zero-width prefix and matches nothing.
        if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
            encoding = "utf-8-sig";
            body = bytes.subarray(3);
        }

        var text;
        try {
            text = new TextDecoder("utf-8", { fatal: true }).decode(body);
        } catch (e) {
            return {
                encoding: null,
                delimiter: "\t",
                rows: [],
                decodeError: "The file is not valid UTF-8. Re-save it as UTF-8 and upload again."
            };
        }

        var delimiter = detectDelimiter(text);
        var lines = text.replace(/\r\n/g, "\n").split("\n");

        // A file almost always ends with a newline; without this the last row
        // is a phantom [""] that fails the column-count check on every file.
        if (lines.length && lines[lines.length - 1] === "") lines.pop();

        var rows = [];
        for (var i = 0; i < lines.length; i++) rows.push(splitLine(lines[i], delimiter));

        return { encoding: encoding, delimiter: delimiter, rows: rows, decodeError: null };
    }

    return {
        readDelimited: readDelimited,
        detectDelimiter: detectDelimiter,
        splitLine: splitLine
    };
});
