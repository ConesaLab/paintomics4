#!/usr/bin/env python3
"""A row with no identifier must be refused, and the omic must be named right.

The run this comes from
-----------------------
A user submitted a miRNA job four times on 2026-08-27 and got, each time:

    miRNA-Seq data: Exception: AT MiRNA2GenesServlet.py: fromMiRNAtoGenes_STEP2.
    Your mirna2gene association process did not return any result. Please,
    check the files (same identifiers, etc) and parameters.

Their own files, read: the targets file held 6,039 rows whose target column was
empty, and the gene expression file 13 rows whose gene column was empty. `""` is
a perfectly good dict key, so miRNA2Target joined blank to blank -- and because
every real target was an ENSMUSG id while the expression file was keyed by gene
SYMBOL, an overlap of exactly zero, those 6,039 blank pairs were the only ones
the server ever scored. PaintOmics called that run a success and handed back an
associations file blank down its entire first column. Feeding THAT file back in
is what produced the "no result" error above: nothing left to join on at all.

Two client-side gaps let it get that far:

1. `mirnaTargetsFileSelector` -- the slot the targets file goes into -- had no
   role in ROLE_BY_SLOT, so it was never checked. It was exempted because the
   table is miRNA/gene/PLR and does not fit the two-column `associations`
   contract; it now has `regulator-targets` of its own.

2. Nothing checked for a blank identifier in ANY role. Blank is worse than
   missing: a missing row is absent, a blank row JOINS.

And one that hid the way out:

3. A miRNA card holds TWO #omicNameField combos -- one per layout of the "map
   regions" toggle -- and the inactive one is disabled and empty. `queryById`
   returns the first, which is that one. Measured in Chrome on this user's form:

       combobox-1412  itemsContainerAlt  disabled:true   value ""
       combobox-1466  itemsContainer     disabled:false  value "miRNA-Seq data"

   So the failure dialog's "Ask the PaintOmics AI agent" button never appeared:
   it looks for the omic named in the message, and the name it read was "".

Usage:
    cd PaintomicsServer
    python -m src.tests.test_a_blank_identifier_is_refused
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
JS_DIR = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                      "PathwayAcquisitionViews", "InputFormat")
PANEL = os.path.join(JS_DIR, "format-panel.js")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def statement(source, header):
    """The one top-level statement that starts with `header`."""
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
            if depth == 0 and char == "}":
                return source[start:index + 1]
    raise AssertionError("ran off the end of format-panel.js")


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-blank-id-")
    try:
        path = os.path.join(directory, "check.js")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        done = subprocess.run(["node", path], capture_output=True,
                              text=True, timeout=120)
        if done.returncode != 0:
            raise AssertionError("node failed:\n%s" % done.stderr)
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


VALIDATE = """
const path = require("path");
const DIR = %(jsdir)s;
const API = Object.assign({},
    require(path.join(DIR, "format-reader.js")),
    require(path.join(DIR, "format-validator.js")),
    require(path.join(DIR, "format-roles.js")));

const cases = %(cases)s;
const out = [];
for (const c of cases) {
    const report = API.validateForRole(c.role, c.rows);
    const codes = (report.problems || []).map(p => p.code);
    const blank = (report.problems || []).filter(p => p.code === "BLANK_IDENTIFIER")[0];
    out.push({name: c.name, ok: !!report.ok, codes: codes,
              blank: blank ? blank.detail : null});
}
console.log(JSON.stringify(out));
"""

# The shapes of the reporting user's own files, cut down. Nothing here is
# invented: the blank cells sit exactly where they sat in result_test/.
USER_TARGETS_BLANK = [["mirnaid", "gene_ID"],
                      ["ENSMUSG00000065402", "ENSMUSG00000062006"],
                      ["ENSMUSG00000065402", ""],
                      ["ENSMUSG00000065402", ""]]
PAINTOMICS_OWN_OUTPUT = [["", "ENSMUSG00000065402"],
                         ["", "ENSMUSG00000065402"]]
USER_DEGS_BLANK = [["genesymbol", "DSSmEVs_vs_DSS"],
                   ["Fxyd4", "-10.88295478"],
                   ["", "-5.62969707"]]
SHIPPED_TARGETS = [["miRNA", "Ensembl.Gene.ID", "PLR"],
                   ["mmu-miR-100-3p", "ENSMUSG00000016498", "4.22"],
                   ["mmu-miR-101a-3p", "ENSMUSG00000026034", "3.55"]]


NAME_FIELD = """
'use strict';
%(fn)s

function combo(opts) {
    return {
        id: opts.id,
        disabled: !!opts.disabled,
        isDisabled: function () { return this.disabled; },
        getValue: function () { return opts.value; }
    };
}
function card(fields) {
    return { query: function (sel) {
        return sel === "#omicNameField" ? fields : [];
    } };
}

const out = {};
// The reporting user's own card, measured in Chrome.
out.miRNAcard = omicNameFieldIn(card([
    combo({id: "combobox-1412", disabled: true,  value: ""}),
    combo({id: "combobox-1466", disabled: false, value: "miRNA-Seq data"})
])).id;
// The order must not matter: the disabled twin can be built first or second.
out.reversed = omicNameFieldIn(card([
    combo({id: "combobox-1466", disabled: false, value: "miRNA-Seq data"}),
    combo({id: "combobox-1412", disabled: true,  value: ""})
])).id;
// A plain card has one, and it is returned whether or not it is filled in.
out.single = omicNameFieldIn(card([combo({id: "only", value: "Gene expression"})])).id;
out.singleEmpty = omicNameFieldIn(card([combo({id: "only", value: ""})])).id;
// An enabled but empty field still beats a disabled one that is filled in --
// only the enabled one is submitted, so only it names the omic on the server.
out.enabledEmptyWins = omicNameFieldIn(card([
    combo({id: "enabled", disabled: false, value: ""}),
    combo({id: "disabledFull", disabled: true, value: "Stale"})
])).id;
// Nothing to choose from is not a crash.
out.none = omicNameFieldIn(card([])) === null;
out.noCard = omicNameFieldIn(null) === null;
console.log(JSON.stringify(out));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class BlankIdentifierTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = read(PANEL)
        cls.reports = {r["name"]: r for r in run_node(VALIDATE % {
            "jsdir": json.dumps(JS_DIR),
            "cases": json.dumps([
                {"name": "user-targets", "role": "regulator-targets",
                 "rows": USER_TARGETS_BLANK},
                {"name": "paintomics-own-output", "role": "regulator-targets",
                 "rows": PAINTOMICS_OWN_OUTPUT},
                {"name": "user-degs", "role": "values", "rows": USER_DEGS_BLANK},
                {"name": "shipped-targets", "role": "regulator-targets",
                 "rows": SHIPPED_TARGETS},
                {"name": "two-column-targets", "role": "regulator-targets",
                 "rows": [["mmu-miR-1", "ENSMUSG1"], ["mmu-miR-2", "ENSMUSG2"]]},
                {"name": "four-column-targets", "role": "regulator-targets",
                 "rows": [["a", "b", "c", "d"], ["e", "f", "g", "h"]]},
                {"name": "blank-association", "role": "associations",
                 "rows": [["ENSMUSG1", "mmu-miR-1"], ["", "mmu-miR-2"]]},
            ]),
        })}
        cls.names = run_node(NAME_FIELD % {
            "fn": statement(cls.source, "function omicNameFieldIn(card)"),
        })

    # ---------------- the blank identifier ----------------

    def test_the_users_targets_file_is_refused(self):
        """6,039 rows with an empty target column, cut down to two."""
        report = self.reports["user-targets"]
        self.assertFalse(report["ok"])
        self.assertIn("BLANK_IDENTIFIER", report["codes"])
        self.assertEqual(report["blank"]["rows"], 2)

    def test_paintomics_own_broken_output_is_refused(self):
        """The file this bug produced, handed back in as an input.

        It has two columns and no ragged rows, so every shape check passes it.
        The first column is empty top to bottom.
        """
        report = self.reports["paintomics-own-output"]
        self.assertFalse(report["ok"])
        self.assertIn("BLANK_IDENTIFIER", report["codes"])
        self.assertEqual(report["blank"]["column"], 1)

    def test_a_values_file_with_a_blank_id_is_refused(self):
        """The 13 blank rows in their DEGs file -- the other half of the join."""
        report = self.reports["user-degs"]
        self.assertFalse(report["ok"])
        self.assertIn("BLANK_IDENTIFIER", report["codes"])

    def test_a_blank_in_an_associations_file_is_refused_too(self):
        self.assertIn("BLANK_IDENTIFIER", self.reports["blank-association"]["codes"])

    def test_the_header_is_not_counted_as_a_blank(self):
        """Both files above carry a labelled header; only data rows are faults."""
        self.assertEqual(self.reports["user-targets"]["blank"]["rows"], 2)
        self.assertEqual(self.reports["user-degs"]["blank"]["rows"], 1)

    def test_the_line_number_points_at_the_first_bad_row(self):
        """A count sends someone hunting; a line number does not."""
        self.assertEqual(self.reports["user-targets"]["blank"]["line"], 3)
        self.assertEqual(self.reports["user-degs"]["blank"]["line"], 3)

    # ---------------- the new contract ----------------

    def test_the_shipped_three_column_targets_table_is_accepted(self):
        """The reason this slot was left unchecked; it must not now be blocked."""
        self.assertTrue(self.reports["shipped-targets"]["ok"],
                        self.reports["shipped-targets"]["codes"])

    def test_two_columns_are_accepted_and_four_are_not(self):
        self.assertTrue(self.reports["two-column-targets"]["ok"])
        self.assertFalse(self.reports["four-column-targets"]["ok"])

    def test_the_slot_has_a_role(self):
        self.assertIn('mirnaTargetsFileSelector: "regulator-targets"', self.source)

    def test_the_message_says_what_a_blank_identifier_costs(self):
        """Not "invalid file": the reason a blank id is fatal is not obvious."""
        self.assertIn("counts.BLANK_IDENTIFIER", self.source)
        self.assertIn("have no identifier", self.source)

    # ---------------- the omic name ----------------

    def test_the_enabled_name_field_is_the_one_read(self):
        """The measured case: the disabled twin is built first and is empty."""
        self.assertEqual(self.names["miRNAcard"], "combobox-1466")

    def test_the_order_of_the_twins_does_not_matter(self):
        self.assertEqual(self.names["reversed"], "combobox-1466")

    def test_an_enabled_field_wins_even_when_empty(self):
        """Only the enabled one is submitted, so only it names the omic."""
        self.assertEqual(self.names["enabledEmptyWins"], "enabled")

    def test_a_plain_card_is_unaffected(self):
        self.assertEqual(self.names["single"], "only")
        self.assertEqual(self.names["singleEmpty"], "only")

    def test_no_card_and_no_field_are_not_crashes(self):
        self.assertTrue(self.names["none"])
        self.assertTrue(self.names["noCard"])

    def test_every_reader_goes_through_it(self):
        """Two call sites read the omic name; both were wrong the same way."""
        code = re.sub(r"/\*.*?\*/", "", self.source, flags=re.S)
        self.assertEqual(code.count('queryById("omicNameField")'), 0,
                         "a raw queryById would find the disabled twin again")
        self.assertEqual(code.count('down("#omicNameField")'), 0)
        self.assertGreaterEqual(code.count("omicNameFieldIn("), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
