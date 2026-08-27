#!/usr/bin/env python3
"""When several omics are converted together, the grader holds them to the
rule the server will apply, not to the model's opinion.

The behaviour this guards
-------------------------
The conversion loop's exit condition is the validator. That was enough while
one file was converted at a time: the validator is pinned to the server's own
per-file loop. It is not enough for the job-level conversion that makes two
omics agree, because the fault the run was refused for is not in any one file
-- `PathwayAcquisitionJob.validateInput` requires every values file to have the
same number of columns, and the per-file grader cannot see two files at once.

Without this a model could write one beautiful file, leave the other as it
was, declare itself done, and the loop would accept it -- and the run would
fail again in the same place. Measured before this existed: "the AI said it
fixed the problem and it fails again" is the report this whole feature answers.

So `gradeOutputs(outputs, api, {harmonise: {inputs: [...]}})` adds two
deterministic checks, run in node against the shipped source:

  * every input is answered by ONE values output, declared in the manifest
    with "for": <input path>;
  * every values output has the same number of columns.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_harmonise_grader
"""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

JS_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "PaintomicsClient", "public_html",
    "app", "view", "PathwayAcquisitionViews", "InputFormat"))

SCRIPT = r"""
const path = require("path");
const DIR = %(dir)s;
const API = Object.assign({},
    require(path.join(DIR, "format-reader.js")),
    require(path.join(DIR, "format-validator.js")),
    require(path.join(DIR, "format-roles.js")));
const AGENT = require(path.join(DIR, "convert-agent.js"));

const enc = (s) => new TextEncoder().encode(s);
const table = (header, rows) => enc([header].concat(rows).map(r => r.join("\t")).join("\n") + "\n");

const narrow = table(["proteinID", "FC"], [["P1", "1.5"], ["P2", "0.7"], ["P3", "2.0"]]);
const wideIn = table(["Label", "C_1", "C_2", "T_1", "T_2"],
                     [["LPE 18:0", "1", "2", "3", "4"], ["LPI 18:0", "2", "2", "5", "5"]]);
const wideOut = table(["Label", "T_vs_C"], [["LPE 18:0", "2.33"], ["LPI 18:0", "2.5"]]);

const INPUTS = [{path: "/work/vp_fc_values.tab", omic: "Proteomics"},
                {path: "/work/lipidomica_samples.tab", omic: "Metabolomics"}];
const manifest = (files) => enc(JSON.stringify({summary: "s", files: files}));

const grade = (outputs) => {
    const g = AGENT.gradeOutputs(outputs, API, {harmonise: {inputs: INPUTS}});
    return {ok: g.ok, summary: g.summary};
};
const out = {};

// Both inputs answered, both one condition wide: accepted.
out.agree = grade({
    "manifest.json": manifest([
        {name: "vp_fc_values.tab", role: "values", "for": "/work/vp_fc_values.tab", unchanged: true},
        {name: "lipids_t_vs_c.tab", role: "values", "for": "/work/lipidomica_samples.tab"}]),
    "vp_fc_values.tab": narrow, "lipids_t_vs_c.tab": wideOut});

// The wide one written back as it was: still 5 columns against 2.
out.still_disagree = grade({
    "manifest.json": manifest([
        {name: "vp_fc_values.tab", role: "values", "for": "/work/vp_fc_values.tab", unchanged: true},
        {name: "lipidomica_samples.tab", role: "values", "for": "/work/lipidomica_samples.tab", unchanged: true}]),
    "vp_fc_values.tab": narrow, "lipidomica_samples.tab": wideIn});

// One input answered, the other forgotten.
out.one_missing = grade({
    "manifest.json": manifest([
        {name: "lipids_t_vs_c.tab", role: "values", "for": "/work/lipidomica_samples.tab"}]),
    "lipids_t_vs_c.tab": wideOut});

// Answered by basename rather than the full path: accepted.
out.by_basename = grade({
    "manifest.json": manifest([
        {name: "a.tab", role: "values", "for": "vp_fc_values.tab", unchanged: true},
        {name: "b.tab", role: "values", "for": "lipidomica_samples.tab"}]),
    "a.tab": narrow, "b.tab": wideOut});

// No harmonise context: the single-file grader is unchanged and accepts a
// lone valid file.
const single = AGENT.gradeOutputs({
    "manifest.json": manifest([{name: "a.tab", role: "values"}]), "a.tab": narrow}, API, {});
out.single = {ok: single.ok, summary: single.summary};

console.log(JSON.stringify(out));
"""


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-harmonise-")
    try:
        path = os.path.join(directory, "check.js")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        done = subprocess.run(["node", path], capture_output=True, text=True, timeout=120)
        if done.returncode != 0:
            raise AssertionError("node failed:\n%s" % done.stderr)
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class HarmoniseGraderTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = run_node(SCRIPT % {"dir": json.dumps(JS_DIR)})

    def test_agreeing_outputs_are_accepted(self):
        self.assertTrue(self.r["agree"]["ok"], self.r["agree"]["summary"])

    def test_outputs_that_still_disagree_are_refused_by_width(self):
        case = self.r["still_disagree"]
        self.assertFalse(case["ok"])
        self.assertIn("still disagree on their number of columns", case["summary"])
        self.assertIn("lipidomica_samples.tab (5 columns, 4 conditions)", case["summary"])
        self.assertIn("vp_fc_values.tab (2 columns, 1 condition)", case["summary"])

    def test_an_unanswered_input_is_refused_by_name(self):
        case = self.r["one_missing"]
        self.assertFalse(case["ok"])
        self.assertIn("No values file is declared for the input /work/vp_fc_values.tab (Proteomics)",
                      case["summary"])

    def test_a_basename_answers_an_input(self):
        self.assertTrue(self.r["by_basename"]["ok"], self.r["by_basename"]["summary"])

    def test_the_single_file_grader_is_unchanged(self):
        self.assertTrue(self.r["single"]["ok"], self.r["single"]["summary"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
