#!/usr/bin/env python3
"""An error report must not carry a stray `""` where nothing was ever meant.

The behaviour this guards
-------------------------
A user reported this on 2026-08-26, quoting it exactly:

    Invalid Form. Please check the form errors. ""

The two quote characters are not part of any message. showMessage() in
Util.js keeps an optional `extra` -- a server stack trace on the dialogs that
have one -- and stashed it in a hidden div for the Report-error button to
append:

    var extra = (data.extra || "");
    extra = JSON.stringify(extra);              // JSON.stringify("") === '""'
    ...
    $("#hiddenMessageDialogBody").text(extra);

A Step 1 form refusal has no stack trace, so `extra` was "" -- and
JSON.stringify turned "nothing" into the two-character string `""`, which went
into the hidden body and from there into the report the user emails and reads.
It is the last thing on the line, so a reader's first guess is that PaintOmics
failed to name the field it was refusing over. Nothing was ever meant to be
there.

So: nothing is stringified when there is nothing, and the report is joined on
the parts that have content.

What this file asserts
----------------------
Both shipped statements are lifted verbatim and run in node:

1. an absent or empty `extra` produces an empty string, not `""`;
2. a real `extra` is still JSON, unchanged -- the reason the field exists;
3. the report of a dialog with no stack trace ends at the message, with no
   trailing blank line and no stray quotes;
4. the report of a dialog WITH one still carries it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_error_report_carries_no_empty_extra
"""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
UTIL = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                    "common", "Util.js")

EXTRA_HEADER = "extra = (extra === \"\")"
REPORT_HEADER = "sendReportMessage(\"error\", ["


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def statement(source, header):
    """`header` up to the semicolon that ends it, ignoring nested ones."""
    start = source.find(header)
    if start == -1:
        raise AssertionError("%r is missing from Util.js" % header)
    depth, index = 0, start
    while index < len(source):
        char = source[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == ";" and depth == 0:
            return source[start:index + 1]
        index += 1
    raise AssertionError("ran off the end of Util.js")


HARNESS = """
'use strict';
// The two shipped statements, lifted verbatim, each given only the names it
// actually reads.
function extraFor(data) {
    var extra = (data.extra || "");
    %(extra_statement)s
    return extra;
}

let reported = null;
function sendReportMessage(kind, body) { reported = {kind: kind, body: body}; }

function reportFor(parts) {
    // jQuery, stubbed down to the three lookups the handler makes.
    const $ = (selector) => ({ text: () => parts[selector] });
    reported = null;
    %(report_statement)s
    return reported;
}

const noStack = { title: "Invalid form.", body: "Please choose a species.", extra: undefined };
const withStack = { title: "Oops..Internal error!", body: "The job failed.",
                    extra: { trace: "KeyError: 'omic'" } };

const bodyOf = (d) => reportFor({
    "#messageDialogTitle": d.title,
    "#messageDialogBody": d.body,
    "#hiddenMessageDialogBody": extraFor({ extra: d.extra })
}).body;

console.log(JSON.stringify({
    extraAbsent: extraFor({}),
    extraEmpty: extraFor({ extra: "" }),
    extraReal: extraFor({ extra: { trace: "KeyError: 'omic'" } }),
    reportNoStack: bodyOf(noStack),
    reportWithStack: bodyOf(withStack),
    reportKind: reportFor({
        "#messageDialogTitle": "t", "#messageDialogBody": "b",
        "#hiddenMessageDialogBody": ""
    }).kind
}));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ErrorReportCarriesNoEmptyExtraTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = read(UTIL)
        script = HARNESS % {
            "extra_statement": statement(source, EXTRA_HEADER),
            "report_statement": statement(source, REPORT_HEADER),
        }
        directory = tempfile.mkdtemp(prefix="paintomics-error-report-")
        try:
            path = os.path.join(directory, "check.js")
            with io.open(path, "w", encoding="utf-8") as handle:
                handle.write(script)
            done = subprocess.run(["node", path], capture_output=True,
                                  text=True, timeout=60)
            if done.returncode != 0:
                raise AssertionError("node failed:\n%s" % done.stderr)
            cls.result = json.loads(done.stdout)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_nothing_is_stringified_when_there_is_nothing(self):
        """The bug: JSON.stringify("") is the two-character string `\"\"`."""
        self.assertEqual(self.result["extraAbsent"], "")
        self.assertEqual(self.result["extraEmpty"], "")

    def test_a_real_extra_is_still_json(self):
        """The reason the field exists at all -- this must not regress."""
        self.assertEqual(json.loads(self.result["extraReal"]),
                         {"trace": "KeyError: 'omic'"})

    def test_a_report_with_no_stack_trace_ends_at_the_message(self):
        """Exactly the line the user quoted, minus the quotes."""
        report = self.result["reportNoStack"]
        self.assertEqual(report, "Invalid form.\nPlease choose a species.")
        self.assertNotIn('""', report)
        self.assertFalse(report.endswith("\n"), "no trailing blank line")

    def test_a_report_with_a_stack_trace_still_carries_it(self):
        report = self.result["reportWithStack"]
        self.assertIn("KeyError", report)
        self.assertEqual(report.count("\n"), 2)

    def test_the_report_is_still_sent_as_an_error(self):
        self.assertEqual(self.result["reportKind"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
