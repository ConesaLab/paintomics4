#!/usr/bin/env python3
"""A file that could not be prepared must say why, and must not fail silently.

The behaviour this guards
-------------------------
When a Step 1 pre-processing job fails (bed2genes, miRNA2genes, MORE), the user
saw only:

    Ops!... Something went wrong during the request files processing.
    One or more files were not succesfully processed.
    Please check the form for more information.

There was more information, and the handler had already parsed it -- but it put
it in a box inside the omic's own card, below the fold of a long Step 1. From
where the user stands the run failed for no stated reason. Reported as exactly
that, on a MORE run whose real cause the server had named precisely:

    MORE ERROR: no data columns could be read from mirna_values.tab.
    (tab: duplicate 'row.names' are not allowed)

Worse, the parse that produced it was unguarded:

    if (response.responseText) {
        var response = JSON.parse(response.responseText);   // throws

Anything that is not JSON -- a Flask HTML error page, a proxy's 504, a
truncated body -- threw from inside the error handler, so `pendingRequests === 0`
was never reached: endStep1Submission() never ran, the submit lock was never
released, and NO dialog appeared at all. The one path whose whole job is to
report a failure was the one that could fail silently.

What this file asserts
----------------------
step1FailureReason is lifted verbatim and run in node over every body shape the
server and the stack in front of it can produce, and the two call sites are
checked to go through the shared dialog.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_preparation_failure_says_why
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CONTROLLER = os.path.join(REPO, "PaintomicsClient", "public_html", "app",
                          "controller", "JobController.js")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def function_body(source, header):
    start = source.find(header)
    if start == -1:
        raise AssertionError("%r is missing from JobController.js" % header)
    opening = source.index("{", start)
    depth, index = 0, opening
    while index < len(source):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise AssertionError("ran off the end of JobController.js")


HARNESS = """
'use strict';
%(fn)s

const MORE_ERROR = "MORE ERROR: no data columns could be read from mirna_values.tab. "
                 + "(tab: duplicate 'row.names' are not allowed)";

const cases = {
    // What the server actually sends.
    json:        { responseText: JSON.stringify({ message: MORE_ERROR }) },
    // The markup the server's own message vocabulary uses.
    markup:      { responseText: JSON.stringify({ message: "[b]Bad file[/b][br]row 7 - column 3" }) },
    // Everything that is NOT JSON, which used to throw from inside the handler.
    html:        { responseText: "<html><head><title>504 Gateway Timeout</title></head>"
                                 + "<body><h1>504 Gateway Timeout</h1></body></html>" },
    truncated:   { responseText: '{"message": "half a mess' },
    plain:       { responseText: "Internal Server Error" },
    // Nothing to say.
    emptyBody:   { responseText: "" },
    noMessage:   { responseText: JSON.stringify({ jobID: "abc" }) },
    nullMessage: { responseText: JSON.stringify({ message: null }) },
    missing:     {},
    nothing:     null
};

const out = {};
for (const [name, response] of Object.entries(cases)) {
    let threw = null, value = null;
    try { value = step1FailureReason(response); }
    catch (e) { threw = String(e); }
    out[name] = { threw, value };
}
console.log(JSON.stringify(out));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class PreparationFailureSaysWhyTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = read(CONTROLLER)
        script = HARNESS % {
            "fn": function_body(cls.source, "function step1FailureReason(response)"),
        }
        directory = tempfile.mkdtemp(prefix="paintomics-prep-failure-")
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

    def test_nothing_throws_for_any_body_shape(self):
        """The regression: a throw here left the form locked and silent."""
        for name, case in self.result.items():
            self.assertIsNone(case["threw"], "%s threw: %s" % (name, case["threw"]))

    def test_the_server_s_own_reason_survives(self):
        reason = self.result["json"]["value"]
        self.assertIn("duplicate 'row.names'", reason)
        self.assertIn("mirna_values.tab", reason)

    def test_the_message_markup_is_rendered(self):
        reason = self.result["markup"]["value"]
        self.assertIn("<b>Bad file</b>", reason)
        self.assertIn("</br>", reason)
        self.assertNotIn("[b]", reason)

    def test_a_non_json_body_still_says_something(self):
        """A proxy's 504 is a better answer than "check the form"."""
        self.assertIn("504 Gateway Timeout", self.result["html"]["value"])
        self.assertNotIn("<h1>", self.result["html"]["value"], "markup is stripped")
        self.assertIn("half a mess", self.result["truncated"]["value"])
        self.assertEqual(self.result["plain"]["value"], "Internal Server Error")

    def test_nothing_to_say_says_nothing(self):
        """So the dialog can fall back rather than print "null"."""
        for name in ("emptyBody", "noMessage", "nullMessage", "missing", "nothing"):
            self.assertEqual(self.result[name]["value"], "", name)

    # -- the wiring --------------------------------------------------------

    def test_both_failure_paths_go_through_the_one_dialog(self):
        code = re.sub(r"/\*.*?\*/", "", self.source, flags=re.S)
        self.assertEqual(code.count("showStep1PreparationFailure(jobView);"), 2,
                         "a failure path bypasses the shared dialog")
        self.assertNotIn("Please check the form for more info", code,
                         "the message that carried no information is back")

    def test_the_unguarded_parse_is_gone(self):
        code = re.sub(r"/\*.*?\*/", "", self.source, flags=re.S)
        self.assertNotIn("JSON.parse(response.responseText)", code)

    def test_the_dialog_shows_the_collected_reasons(self):
        body = function_body(self.source, "function showStep1PreparationFailure(jobView)")
        self.assertIn("step1FailureReasons", body)
        self.assertIn("could not be prepared", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
