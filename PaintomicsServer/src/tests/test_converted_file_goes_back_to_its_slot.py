#!/usr/bin/env python3
"""A converted file must be usable in the slot it was converted for.

The behaviour this guards
-------------------------
The convert drawer ends on a review, and the review's whole point is the
button that puts the result back in the form. That button was appended on one
condition:

    if (out.values.length) actions.appendChild(accept);

`out.values` is the produced files whose role is "values". A conversion that
produces no values table has none -- so the review ended with "Cancel" and
"Download all", and the only way to use the result was to save it to disk and
pick it again through Browse.

Reported on the conversion that makes it plainest: a MORE Conditions file. The
agent read 24 rows of sample metadata, wrote exactly the 0/1 experimental
design PaintOmics wants, named it design.tab -- and then offered no way to put
it in the field the user had clicked Convert on. Four of the five roles this
form accepts (relevant, associations, relevant-associations, design) had the
same dead end.

Same shape as the rest of this family: code that enumerates omic files knows
the plain values case and forgets the others. The slot the drawer was opened
from already says which role is wanted, so the fix is to carry it -- format
panel passes roleForInput(input), the drawer matches a produced file against
it, and that file is what "Use this file" applies.

Verified in Chrome on the reporting user's own samplemetadata_miRNA.csv:
"Use this file" appears, and clicking it puts design.tab (373 bytes) in the
Conditions field, closes the drawer, and the strip re-checks it green --
"24 rows - 4 conditions (C, DSS, DSS_SDExc, DSS_SDmEVs)".

What this file asserts
----------------------
The decision rule, lifted verbatim from the shipped drawer and run in node
against every role the form has; plus the two ends of the wiring that carries
the role there.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_converted_file_goes_back_to_its_slot
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
FORMAT_DIR = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                          "PathwayAcquisitionViews", "InputFormat")
DRAWER = os.path.join(FORMAT_DIR, "convert-drawer.js")
PANEL = os.path.join(FORMAT_DIR, "format-panel.js")

ROLES = ("values", "relevant", "associations", "relevant-associations", "design")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def statement(source, header, what):
    """`header` up to the semicolon that ends it, ignoring nested ones."""
    start = source.find(header)
    if start == -1:
        raise AssertionError("%r is missing from %s" % (header, what))
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == ";" and depth == 0:
            return source[start:index + 1]
    raise AssertionError("ran off the end of %s" % what)


HARNESS = """
'use strict';
// The rule, lifted from the shipped drawer. Only the two names it reads are
// stubbed: `out` (what the conversion produced) and `context` (what the drawer
// was opened with).
function decide(context, files) {
    const out = {
        files: files,
        values: files.filter(f => f.role === 'values'),
        lists:  files.filter(f => f.role === 'relevant')
    };
    let chosen = out.values.filter(f => f.recommended)[0] || out.values[0];
    %(slot_role)s
    %(for_slot)s
    const offered = !!(out.values.length || forSlot);
    return {
        offered: offered,
        applies: chosen ? chosen.name : (forSlot ? forSlot.name : null),
        viaSlot: !chosen && !!forSlot
    };
}

const out = {};
const ROLES = %(roles)s;

// One produced file, of each role, converted from that role's own slot.
for (const role of ROLES) {
    out['only_' + role] = decide({slotRole: role},
        [{name: role + '.tab', role: role}]);
}

// The reported case: a design file produced for the Conditions slot.
out.design_for_conditions = decide({slotRole: 'design'},
    [{name: 'design.tab', role: 'design'}]);

// A values table still wins when there is one, and the recommended one at that.
out.values_still_win = decide({slotRole: 'values'},
    [{name: 'a.tab', role: 'values'}, {name: 'b.tab', role: 'values', recommended: true}]);

// A values slot that also received a relevant list: the values table is applied.
out.values_with_list = decide({slotRole: 'values'},
    [{name: 'v.tab', role: 'values'}, {name: 'r.tab', role: 'relevant'}]);

// Nothing matching the slot and no values table: no button, rather than one
// that would put the wrong file in the field.
out.nothing_for_this_slot = decide({slotRole: 'design'},
    [{name: 'assoc.tab', role: 'associations'}]);

// No context at all falls back to values, as the drawer's default does.
out.no_context = decide(null, [{name: 'v.tab', role: 'values'}]);

console.log(JSON.stringify(out));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ConvertedFileGoesBackToItsSlotTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.drawer = read(DRAWER)
        cls.panel = read(PANEL)
        script = HARNESS % {
            "slot_role": statement(cls.drawer, "var slotRole = (context",
                                   "convert-drawer.js"),
            "for_slot": statement(cls.drawer, "var forSlot = chosen ? null",
                                  "convert-drawer.js"),
            "roles": json.dumps(list(ROLES)),
        }
        directory = tempfile.mkdtemp(prefix="paintomics-convert-slot-")
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

    # -- the decision -----------------------------------------------------

    def test_every_role_can_be_used_from_its_own_slot(self):
        """The regression: four of the five had no way back into the form."""
        for role in ROLES:
            case = self.result["only_" + role]
            self.assertTrue(case["offered"],
                            "a %s conversion offers no way to use the result"
                            % role)
            self.assertEqual(case["applies"], role + ".tab")

    def test_the_reported_case(self):
        """A design file produced for a MORE Conditions slot."""
        case = self.result["design_for_conditions"]
        self.assertTrue(case["offered"])
        self.assertEqual(case["applies"], "design.tab")
        self.assertTrue(case["viaSlot"], "it should be applied by role match")

    def test_a_values_table_still_wins_when_there_is_one(self):
        """The path that already worked must keep working, unchanged."""
        case = self.result["values_still_win"]
        self.assertEqual(case["applies"], "b.tab", "the recommended table")
        self.assertFalse(case["viaSlot"], "values go through the old path")
        self.assertEqual(self.result["values_with_list"]["applies"], "v.tab")
        self.assertEqual(self.result["no_context"]["applies"], "v.tab")

    def test_a_file_of_the_wrong_role_is_not_offered(self):
        """Better no button than one that puts the wrong file in the field."""
        case = self.result["nothing_for_this_slot"]
        self.assertFalse(case["offered"])
        self.assertIsNone(case["applies"])

    # -- the wiring that carries the role ---------------------------------

    def test_the_panel_tells_the_drawer_which_slot_it_opened(self):
        code = re.sub(r"/\*.*?\*/", "", self.panel, flags=re.S)
        self.assertIn("openConvertDrawer(\n                input, file, fieldName, roleForInput(input))",
                      code.replace("\r", ""))

    def test_the_drawer_takes_the_role_and_keeps_it(self):
        code = re.sub(r"/\*.*?\*/", "", self.drawer, flags=re.S)
        self.assertIn("function openConvertDrawer(input, file, fieldName, slotRole)", code)
        self.assertIn("slotRole: slotRole || \"values\"", code)
        self.assertIn("var slotRole = (context && context.slotRole) || \"values\";", code)

    def test_the_button_is_no_longer_gated_on_values_alone(self):
        """The one line that caused this."""
        code = re.sub(r"/\*.*?\*/", "", self.drawer, flags=re.S)
        self.assertNotIn("if (out.values.length) actions.appendChild(accept)", code)
        self.assertIn("if (out.values.length || forSlot) actions.appendChild(accept)", code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
