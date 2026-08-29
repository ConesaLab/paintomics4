#!/usr/bin/env python3
"""The metabolomics replicate design is its own contract, not a looser `design`.

`design` is MORE's conditions file, held to runMORE.R's rules: numeric cells
only, because as.numeric turns a text label into NA and the run dies
(test_conditions_file_is_held_to_r_rules). The metabolomics panel's design is
what src/common/DesignFile.py parse_design reads: the long form
`column<TAB>condition` with an optional `#` header, or that same indicator
matrix. The first cut widened `design` to take the long form, and CI caught
what that meant -- `s1 control / s2 treated`, the exact file MORE must refuse,
started passing for the Conditions slot. So the long form lives under
`replicates`, bound to designFileSelector alone, and this file keeps the two
apart.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_replicate_design_takes_both_shapes
"""
import json
import os
import shutil
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", ".."))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from src.tests.test_conditions_file_is_held_to_r_rules import JS_DIR, run_node  # noqa: E402
from src.tests.test_input_check_covers_every_omic_slot import role_by_slot  # noqa: E402

SCRIPT = """
const path = require("path");
const DIR = %(dir)s;
const API = Object.assign({},
    require(path.join(DIR, "format-reader.js")),
    require(path.join(DIR, "format-validator.js")),
    require(path.join(DIR, "format-roles.js")));
const out = {};
const check = (name, role, rows) => {
    const r = API.validateForRole(role, rows);
    out[name] = { ok: !!r.ok, codes: (r.problems || []).map(p => p.code), summary: r.summary };
};
const longForm = [["Ctr_0H_B10","Ctr_0H"], ["Ctr_0H_B11","Ctr_0H"], ["Ik_0H_B10","Ik_0H"]];
check("long_form",         "replicates", longForm);
check("long_form_header",  "replicates", [["#sample","condition"]].concat(longForm));
check("indicator",         "replicates", [["Sample","C","DSS"], ["s1","1","0"], ["s2","0","1"]]);
check("wide_text",         "replicates", [["Sample","Group","Batch"], ["s1","control","a"], ["s2","treated","b"]]);
check("blank_label",       "replicates", [["s1","control"], ["s2",""]]);
check("dup_column",        "replicates", [["s1","control"], ["s1","treated"]]);
check("header_only",       "replicates", [["#sample","condition"]]);
check("long_form_as_design", "design",   longForm);
out.roles = API.ROLES;
console.log(JSON.stringify(out));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ReplicateDesignTakesBothShapesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = run_node(SCRIPT % {"dir": json.dumps(JS_DIR)})
        cls.slots = role_by_slot()

    def test_the_long_form_passes_and_names_its_conditions(self):
        r = self.r["long_form"]
        self.assertTrue(r["ok"], r["codes"])
        self.assertEqual(r["summary"]["conditions"], ["Ctr_0H", "Ik_0H"])
        self.assertTrue(r["summary"]["longForm"])

    def test_a_hash_header_is_not_a_sample(self):
        """parse_design skips `#` lines; so does the check."""
        r = self.r["long_form_header"]
        self.assertTrue(r["ok"], r["codes"])
        self.assertEqual(r["summary"]["nRows"], 3)

    def test_the_indicator_matrix_still_passes(self):
        self.assertTrue(self.r["indicator"]["ok"], self.r["indicator"]["codes"])

    def test_text_in_a_wide_file_is_refused_under_its_own_name(self):
        """Refused as the matrix would be, but the code is this slot's, so the
        sentence can say the two-column form exists."""
        r = self.r["wide_text"]
        self.assertFalse(r["ok"])
        self.assertIn("TEXT_IN_DESIGN_MATRIX", r["codes"])
        self.assertNotIn("NOT_INDICATOR", r["codes"])

    def test_a_column_without_a_condition_is_refused(self):
        r = self.r["blank_label"]
        self.assertFalse(r["ok"])
        self.assertIn("NO_CONDITION", r["codes"])

    def test_a_column_listed_twice_is_refused(self):
        r = self.r["dup_column"]
        self.assertFalse(r["ok"])
        self.assertIn("DUPLICATE_IDENTIFIER", r["codes"])

    def test_a_header_alone_is_refused(self):
        r = self.r["header_only"]
        self.assertFalse(r["ok"])
        self.assertIn("EMPTY", r["codes"])

    def test_the_long_form_is_still_refused_for_more(self):
        """The regression CI caught: `design` must keep R's rules."""
        r = self.r["long_form_as_design"]
        self.assertFalse(r["ok"])
        self.assertIn("NOT_INDICATOR", r["codes"])

    def test_the_role_is_declared_and_bound_to_the_right_slot(self):
        self.assertIn("replicates", self.r["roles"])
        self.assertEqual(self.slots.get("designFileSelector"), "replicates")
        self.assertEqual(self.slots.get("conditionsFileSelector"), "design")


if __name__ == "__main__":
    unittest.main(verbosity=2)
