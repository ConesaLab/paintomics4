#!/usr/bin/env python3
"""Repairing a file must also lift the block that file put on the submit.

The behaviour this guards
-------------------------
InputFormat/format-panel.js keeps a registry of files it knows the server will
reject, and a capture-phase listener on #submitButton refuses the submit while
any entry is live. Entries go stale, so liveBlocked() re-checks each one
against the form before letting it stop anything -- by comparing the picked
file's NAME:

    if (!current || current.name !== blocked[fieldName].fileName) {
        clearBlocked(fieldName);

A repair rewrites the file IN PLACE, under the same name: DEGs2.txt with
decimal commas becomes DEGs2.txt with dots. The name check therefore cannot
notice, and the entry has to be cleared explicitly.

Three code paths applied a repair -- the auto-apply branch, the banner's own
`apply`, and the "Fix automatically" button -- and the button, the one a user
actually clicks, was the only one that did not call clearBlocked. So the card
went green and the block stayed live. Measured on the reporting user's DEGs2.txt,
whose only fault was decimal commas that this very button had just fixed:

    the card's strip     OK Gene expression: 112 rows - 1 value column
    the submit banner    X  Gene expression: the server will reject this file

Two verdicts on one file, from one module, at one moment. The banner renders at
the END of the form, so from the top of a long Step 1 the Run button simply
looks dead -- no dialog, no console error, nothing.

There is one implementation now, used by all three, so the paths cannot drift
apart again.

What this file asserts
----------------------
1. the lifted applyRepair clears the block, replaces the file and re-renders;
2. there is exactly ONE place that applies a repair;
3. the button is wired to that one place;
4. liveBlocked still keys on the file name -- which is WHY 1 is required.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_repair_clears_the_submit_block
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
PANEL = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                     "PathwayAcquisitionViews", "InputFormat", "format-panel.js")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def statement(source, header):
    start = source.find(header)
    if start == -1:
        raise AssertionError("%r is missing from format-panel.js" % header)
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == ";" and depth == 0:
            return source[start:index + 1]
    raise AssertionError("ran off the end of format-panel.js")


HARNESS = """
'use strict';
const calls = [];
const blocked = { 'omic0_file': { fileName: 'DEGs2.txt' } };

function replaceFile(input, rows, name) { calls.push('replaceFile:' + name); }
function clearBlocked(fieldName) { calls.push('clearBlocked:' + fieldName);
                                   delete blocked[fieldName]; }
function renderOk() { calls.push('renderOk'); }
function hostFor() { return {}; }
function validate() { return { ok: true, summary: { nRows: 112 } }; }

const input = {};
const fieldName = 'omic0_file';
const file = { name: 'DEGs2.txt' };
const repaired = { rows: [['#gene', 'v'], ['Cp', '-1.86']] };

%(apply_repair)s

applyRepair();

console.log(JSON.stringify({
    calls: calls,
    stillBlocked: Object.keys(blocked)
}));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class RepairClearsTheSubmitBlockTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = read(PANEL)
        script = HARNESS % {
            "apply_repair": statement(cls.source, "var applyRepair = function ()"),
        }
        directory = tempfile.mkdtemp(prefix="paintomics-repair-block-")
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

    def test_applying_a_repair_lifts_the_block(self):
        """The regression: the card went green and the submit stayed refused."""
        self.assertEqual(self.result["stillBlocked"], [])
        self.assertIn("clearBlocked:omic0_file", self.result["calls"])

    def test_it_also_replaces_the_file_and_re_renders(self):
        self.assertIn("replaceFile:DEGs2.txt", self.result["calls"])
        self.assertIn("renderOk", self.result["calls"])
        self.assertLess(self.result["calls"].index("replaceFile:DEGs2.txt"),
                        self.result["calls"].index("renderOk"),
                        "the file must be replaced before it is re-rendered")

    def test_there_is_exactly_one_way_to_apply_a_repair(self):
        """Three copies drifted apart once; one cannot."""
        code = re.sub(r"/\\*.*?\\*/", "", self.source, flags=re.S)
        self.assertEqual(code.count("replaceFile(input, repaired.rows, file.name)"), 1,
                         "a second copy of the repair has appeared")
        self.assertEqual(code.count("var applyRepair = function ()"), 1)

    def test_every_path_goes_through_it(self):
        code = re.sub(r"/\\*.*?\\*/", "", self.source, flags=re.S)
        self.assertIn("if (autoApply) { applyRepair(); return; }", code)
        self.assertIn("fixable: true, apply: applyRepair", code)
        self.assertIn('onClick: applyRepair', code)

    def test_the_block_is_still_kept_alive_by_file_name(self):
        """Which is exactly why a repair has to clear it explicitly.

        If this ever changes to compare content, size or an identity token, the
        explicit clear may stop being necessary -- but until then it is.
        """
        code = re.sub(r"/\\*.*?\\*/", "", self.source, flags=re.S)
        self.assertIn("current.name !== blocked[fieldName].fileName", code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
