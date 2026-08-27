#!/usr/bin/env python3
"""The conditions (design) contract refuses what runMORE.R refuses, and nothing more.

The first cut of `validateDesign` demanded 0/1 cells with exactly one 1 per
row and a header as wide as the rows. Replicating runMORE.R's `read_matrix`
in R 4.6.0 showed it blocking three files R accepts:

    - an R `write.table` default, whose header is one cell short (the
      row-name column is unnamed);
    - a multi-factor row (`s2 0 1 1`), which MOREServlet._designPatternNames
      handles on purpose ("a hand-written design file may carry one");
    - numeric levels such as `Time 0/24/48` -- numeric is R's only demand.

Text labels and a repeated sample name ARE refused by R, and stay refused.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_conditions_file_is_held_to_r_rules
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
JS_DIR = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                      "PathwayAcquisitionViews", "InputFormat")

SCRIPT = """
const path = require("path");
const DIR = %(dir)s;
const API = Object.assign({},
    require(path.join(DIR, "format-reader.js")),
    require(path.join(DIR, "format-validator.js")),
    require(path.join(DIR, "format-roles.js")));
const out = {};
const check = (name, rows) => {
    const r = API.validateForRole("design", rows);
    out[name] = { ok: !!r.ok, codes: (r.problems || []).map(p => p.code), summary: r.summary };
};
check("indicator",     [["Sample","C","DSS"], ["s1","1","0"], ["s2","0","1"]]);
check("r_short_header", [["C","DSS"], ["s1","1","0"], ["s2","0","1"]]);
check("multi_factor",  [["Sample","A","B","T"], ["s1","1","0","0"], ["s2","0","1","1"]]);
check("numeric_levels", [["Sample","Time"], ["s1","0"], ["s2","24"], ["s3","48"]]);
check("text_labels",   [["Sample","Group"], ["s1","control"], ["s2","treated"]]);
check("dup_sample",    [["Sample","C","DSS"], ["s1","1","0"], ["s1","0","1"]]);
check("ragged",        [["Sample","C","DSS"], ["s1","1","0"], ["s2","0"]]);
check("header_only",   [["Sample","C","DSS"]]);
console.log(JSON.stringify(out));
"""


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-design-")
    try:
        path = os.path.join(directory, "check.js")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        done = subprocess.run(["node", path], capture_output=True, text=True, timeout=120)
        if done.returncode != 0:
            raise AssertionError("node failed:\n%s" % done.stderr)
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ConditionsFileIsHeldToRRulesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = run_node(SCRIPT % {"dir": json.dumps(JS_DIR)})

    def test_the_documented_shape_passes(self):
        self.assertTrue(self.r["indicator"]["ok"], self.r["indicator"]["codes"])
        self.assertEqual(self.r["indicator"]["summary"]["conditions"], ["C", "DSS"])

    def test_an_r_written_header_one_cell_short_passes(self):
        """write.table's default; read_matrix reads it as a 2x2 with row names."""
        r = self.r["r_short_header"]
        self.assertTrue(r["ok"], r["codes"])
        self.assertEqual(r["summary"]["conditions"], ["C", "DSS"])
        self.assertEqual(r["summary"]["nRows"], 2)

    def test_a_multi_factor_row_passes(self):
        self.assertTrue(self.r["multi_factor"]["ok"], self.r["multi_factor"]["codes"])

    def test_numeric_levels_pass(self):
        self.assertTrue(self.r["numeric_levels"]["ok"], self.r["numeric_levels"]["codes"])

    def test_text_labels_are_refused(self):
        """R's as.numeric turns them into NA; the run dies."""
        self.assertFalse(self.r["text_labels"]["ok"])
        self.assertIn("NOT_INDICATOR", self.r["text_labels"]["codes"])

    def test_a_repeated_sample_is_refused(self):
        self.assertFalse(self.r["dup_sample"]["ok"])
        self.assertIn("DUPLICATE_IDENTIFIER", self.r["dup_sample"]["codes"])

    def test_a_ragged_row_is_refused(self):
        self.assertIn("RAGGED", self.r["ragged"]["codes"])

    def test_a_header_alone_is_refused(self):
        self.assertIn("EMPTY", self.r["header_only"]["codes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
