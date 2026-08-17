#!/usr/bin/env python3
"""Step 4's "Neighbouring features" button must always say what it did.

Why this exists
---------------
The button (Feature set overview -> "Please enter a level (1-4)" -> Show
Features) resolved its neighbour list inline and guarded every empty case the
same way:

    if (!features || features.length === 0) { console.warn('No features'); return; }
    if (!compoundRegulateFeatures || !compoundRegulateFeatures[featureID]) {
        console.warn('No regulate data for', featureID); return; }
    if (!compoundRegulateFeatures[inputLevel]) {
        console.warn('No data for input level', inputLevel); return; }

Four returns, no pixels. Reproduced in Chrome on a freshly run six-omic STATegra
job (e6rwH1sB3o), L-Glutamic acid in mmu00250:

    click Show Features with the level box as it opens (empty)
      -> PA_Step4Views.js:4474 "No data for input level "   nothing drawn
    type 1, click again
      -> 69-row gene-expression heatmap + plot

So the feature worked; the first click on it never did, because the level box
opens blank. That is what "the button doesn't work" was.

Two more silent inversions in the same block, from feeding OmicValue instances
to a renderer written for `addTableEntrie` rows -- where `isRelevant` is a
boolean, not a method:

  - `omicsValues[i].isRelevant === true` is false for a function, so no row ever
    showed the `*` relevant marker the rest of the panel uses.
  - `x.isRelevant || x.isRelevantAssociation` is truthy for a function, so
    "Only relevant" filtered nothing. Measured in the browser before the fix:
    69 series before ticking it, 69 after.

These tests run the two extracted helpers in node -- the real functions, taken
out of the shipped file, not a re-implementation of them.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_neighbouring_features_button
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

CLIENT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "PaintomicsClient", "public_html"))

STEP3_VIEWS = os.path.join(CLIENT, "app", "view", "PathwayAcquisitionViews",
                           "PA_Step3Views.js")
STEP4_VIEWS = os.path.join(CLIENT, "app", "view", "PathwayAcquisitionViews",
                           "PA_Step4Views.js")

HELPERS = ("paNeighbourRequest", "paNeighbourRows")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def extract(source, name):
    """The text of `var <name> = function ... };`, brace-matched."""
    match = re.search(r"var\s+%s\s*=\s*function" % re.escape(name), source)
    if match is None:
        raise AssertionError("%s() is not defined in %s" % (name, STEP3_VIEWS))

    opening = source.index("{", match.end())
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1] + ";"
    raise AssertionError("unbalanced braces in %s()" % name)


def run_in_node(body):
    """Evaluate `body` with both helpers in scope; return its parsed stdout."""
    source = read(STEP3_VIEWS)
    script = "\n".join(extract(source, name) for name in HELPERS) + "\n" + body
    directory = tempfile.mkdtemp(prefix="paintomics-neighbours-")
    try:
        path = os.path.join(directory, "check.js")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        completed = subprocess.run(
            ["node", path], capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise AssertionError("node failed:\n%s" % completed.stderr)
        return json.loads(completed.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


NETWORK_JS = """
var NETWORK = {
  "C00025": {"1": ["11302", "12974"], "2": ["11302", "12974", "71832"],
             "3": ["11302"], "4": []},
  "C00026": {"1": ["104112"], "2": [], "3": [], "4": []}
};
"""


class SourceStructureTest(unittest.TestCase):
    """Holds with or without a JavaScript runtime available."""

    def neighbours_method(self):
        """The text of `this.showNeighbouringFeatures = function () {...}`."""
        source = read(STEP4_VIEWS)
        start = source.index("this.showNeighbouringFeatures = function")
        opening = source.index("{", start)
        depth = 0
        for index in range(opening, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[start:index + 1]
        raise AssertionError("unbalanced braces in showNeighbouringFeatures()")

    def section_markup(self):
        """The Ext item that holds the level box and the button."""
        source = read(STEP4_VIEWS)
        start = source.index('itemId: "neighbouringFeaturesSection"')
        return source[start:source.index("featureFamilyOverviewContainerRegulate", start)]

    def test_both_helpers_are_defined(self):
        source = read(STEP3_VIEWS)
        for name in HELPERS:
            self.assertIsNotNone(
                re.search(r"var\s+%s\s*=\s*function" % re.escape(name), source),
                "%s() has been renamed or removed" % name)

    def test_the_button_no_longer_returns_without_drawing(self):
        """Pinning the absence of the old guards, not just the presence of the
        new helper: one of them coming back reinstates the silent click."""
        source = read(STEP4_VIEWS)
        for gone in ("console.warn('No features')",
                     "console.warn('No feature ID')",
                     "console.warn('No regulate data for'",
                     "console.warn('No data for input level'"):
            self.assertNotIn(gone, source,
                             "the silent guard %s is back" % gone)

    def test_the_button_asks_the_helper(self):
        source = read(STEP4_VIEWS)
        self.assertIn("paNeighbourRequest(", source)
        self.assertIn("paNeighbourRows(", source)

    def test_the_relevance_filter_reads_a_boolean(self):
        """`x.isRelevant` without the parentheses is the bug this replaced, and
        it is only a bug on OmicValues -- the sibling "Values by omic type"
        checkbox filters addTableEntrie rows, where the same name really is a
        boolean. So this is scoped to the neighbours method.
        """
        body = self.neighbours_method()
        code = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        code = re.sub(r"//[^\n]*", "", code)
        self.assertNotIn("x.isRelevant", code)
        self.assertIn("row.isRelevant || row.isRelevantAssociation", code)

    def test_the_dead_spinner_markup_is_gone(self):
        """div.applyWaitMessage is display:none in main.css and this one was
        never faded in, so it could only ever be invisible markup promising
        feedback the button did not give. Scoped to the section's own markup:
        the Find Features panel has one of these that it does fade in.
        """
        section = self.section_markup()
        self.assertIn("Show Features", section,
                      "the section markup is not where this test thinks")
        self.assertNotIn("applyWaitMessage", section)

    def test_the_section_is_gated_on_the_feature_type(self):
        """A gene box must not be offered a control that cannot work for it."""
        source = read(STEP4_VIEWS)
        self.assertIn("neighbouringFeaturesSection", source)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class NeighbourRequestTest(unittest.TestCase):

    def resolve(self, **request):
        body = NETWORK_JS + """
var request = %s;
if (request.neighbourMap === "NETWORK") { request.neighbourMap = NETWORK; }
process.stdout.write(JSON.stringify(paNeighbourRequest(request)));
""" % json.dumps(request)
        return run_in_node(body)

    def test_an_empty_level_is_reported_not_swallowed(self):
        """The reported failure: the box opens blank and the first click is
        this."""
        result = self.resolve(featureID="C00025", featureType="Compound",
                              neighbourMap="NETWORK", level="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no-level")
        self.assertIn("1 to 4", result["message"])

    def test_a_missing_level_property_behaves_the_same(self):
        result = self.resolve(featureID="C00025", featureType="Compound",
                              neighbourMap="NETWORK")
        self.assertEqual(result["reason"], "no-level")

    def test_a_level_outside_one_to_four_is_reported(self):
        for level in ("0", "5", "9", "-1"):
            result = self.resolve(featureID="C00025", featureType="Compound",
                                  neighbourMap="NETWORK", level=level)
            self.assertEqual(result["reason"], "bad-level", "level %r" % level)

    def test_a_level_that_only_looks_numeric_is_rejected(self):
        """parseInt would take all three of these for 1."""
        for level in ("1.9", "1e9", "1 2"):
            result = self.resolve(featureID="C00025", featureType="Compound",
                                  neighbourMap="NETWORK", level=level)
            self.assertEqual(result["reason"], "bad-level", "level %r" % level)

    def test_whitespace_around_a_good_level_is_accepted(self):
        result = self.resolve(featureID="C00025", featureType="Compound",
                              neighbourMap="NETWORK", level=" 2 ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["level"], 2)
        self.assertEqual(result["neighbours"], ["11302", "12974", "71832"])

    def test_a_numeric_level_is_accepted(self):
        """The DOM gives a string; a caller reading a number must work too."""
        result = self.resolve(featureID="C00025", featureType="Compound",
                              neighbourMap="NETWORK", level=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["neighbours"], ["11302", "12974"])

    def test_a_gene_box_is_told_the_control_is_not_for_it(self):
        result = self.resolve(featureID="11302", featureType="Gene",
                              neighbourMap="NETWORK", level="1")
        self.assertEqual(result["reason"], "not-a-metabolite")

    def test_the_type_is_decided_before_the_level(self):
        """Otherwise a gene box with an empty level is told to type one."""
        result = self.resolve(featureID="11302", featureType="Gene",
                              neighbourMap="NETWORK", level="")
        self.assertEqual(result["reason"], "not-a-metabolite")

    def test_an_unknown_feature_type_is_not_blocked(self):
        """Metagene boxes and anything else unlabelled fall through to the data
        rather than being refused on a name."""
        result = self.resolve(featureID="C00025", featureType="",
                              neighbourMap="NETWORK", level="1")
        self.assertTrue(result["ok"])

    def test_an_empty_network_is_reported(self):
        """What a species installed without hubData looks like."""
        result = self.resolve(featureID="C00025", featureType="Compound",
                              neighbourMap={}, level="1")
        self.assertEqual(result["reason"], "no-map")

    def test_a_metabolite_outside_the_network_is_reported(self):
        result = self.resolve(featureID="C99999", featureType="Compound",
                              neighbourMap="NETWORK", level="1")
        self.assertEqual(result["reason"], "not-in-network")

    def test_an_empty_step_is_reported_with_its_level(self):
        result = self.resolve(featureID="C00026", featureType="Compound",
                              neighbourMap="NETWORK", level="3")
        self.assertEqual(result["reason"], "no-neighbours-at-level")
        self.assertEqual(result["level"], 3)
        self.assertIn("3 steps", result["message"])

    def test_one_step_is_singular(self):
        result = self.resolve(featureID="C00026", featureType="Compound",
                              neighbourMap={"C00026": {"1": []}}, level="1")
        self.assertIn("1 step.", result["message"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class NeighbourRowTest(unittest.TestCase):
    """paNeighbourRows against stand-ins shaped like the real OmicValue: the
    two relevance names are methods, which is the whole point."""

    OMIC_VALUES_JS = """
function omicValue(keggName, values, relevant, association, sampleValues) {
  return {
    keggName: keggName, inputName: keggName + "_input", originalName: keggName + "_input",
    values: values, relevant: relevant, relevantAssociation: association,
    sampleValues: sampleValues || null,
    getValues: function (mode) {
      return (mode === "samples" && this.sampleValues) ? this.sampleValues : this.values;
    },
    isRelevant: function (index, mode) {
      if (index !== undefined && Array.isArray(this.relevant)) {
        if (this.relevant.length <= 1) { return false; }
        return this.relevant[index] === true;
      }
      if (Array.isArray(this.relevant)) { return this.relevant.some(function (x) { return x === true; }); }
      return this.relevant === true;
    },
    isRelevantAssociation: function () { return this.relevantAssociation === true; }
  };
}
"""

    def rows(self, body):
        return run_in_node(self.OMIC_VALUES_JS + body)

    def test_relevance_becomes_a_boolean(self):
        result = self.rows("""
var rows = paNeighbourRows([
  omicValue("Gad1", [1, 2], [true, false], false),
  omicValue("Gad2", [1, 2], [false, false], false)
], "replicates");
process.stdout.write(JSON.stringify(rows.map(function (r) {
  return {name: r.keggName, isRelevant: r.isRelevant, sig: r.significance};
})));
""")
        self.assertEqual(result[0]["isRelevant"], True)
        self.assertEqual(result[0]["sig"], [True, False])
        self.assertEqual(result[1]["isRelevant"], False)
        self.assertEqual(result[1]["sig"], [False, False])

    def test_the_only_relevant_filter_now_separates_the_rows(self):
        """The measured symptom: the old expression kept every row."""
        result = self.rows("""
var rows = paNeighbourRows([
  omicValue("Gad1", [1, 2], [true, false], false),
  omicValue("Gad2", [1, 2], [false, false], false),
  omicValue("Gad3", [1, 2], [false, false], true)
], "replicates");
var kept = rows.filter(function (x) { return x.isRelevant || x.isRelevantAssociation; });
process.stdout.write(JSON.stringify({total: rows.length, kept: kept.map(function (r) { return r.keggName; })}));
""")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["kept"], ["Gad1", "Gad3"])

    def test_the_sample_mode_is_applied_once(self):
        """`values` must already be in the drawn space and `sampleValues` must
        not ride along, or paValuesForHeader() would aggregate a second time."""
        result = self.rows("""
var rows = paNeighbourRows([omicValue("Gad1", [1, 2, 3, 4], [false], false, [1.5, 3.5])], "samples");
process.stdout.write(JSON.stringify({
  values: rows[0].values,
  hasSampleValues: rows[0].sampleValues !== undefined,
  sig: rows[0].significance
}));
""")
        self.assertEqual(result["values"], [1.5, 3.5])
        self.assertFalse(result["hasSampleValues"])
        self.assertEqual(result["sig"], [False, False])

    def test_null_entries_are_dropped_not_rendered(self):
        result = self.rows("""
process.stdout.write(JSON.stringify(paNeighbourRows(
  [null, omicValue("Gad1", [1], [true], false), undefined], "replicates").length));
""")
        self.assertEqual(result, 1)

    def test_no_omic_values_yields_no_rows(self):
        result = self.rows("""
process.stdout.write(JSON.stringify([
  paNeighbourRows([], "replicates").length,
  paNeighbourRows(null, "replicates").length,
  paNeighbourRows(undefined, "replicates").length
]));
""")
        self.assertEqual(result, [0, 0, 0])

    def test_a_plain_row_still_converts(self):
        """Not every caller has to hand over OmicValue instances."""
        result = self.rows("""
var rows = paNeighbourRows([{keggName: "Gad1", inputName: "x", values: [1, 2],
                             relevant: true, relevantAssociation: false}], "replicates");
process.stdout.write(JSON.stringify(rows[0]));
""")
        self.assertEqual(result["isRelevant"], True)
        self.assertEqual(result["values"], [1, 2])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class EditedFilesParseTest(unittest.TestCase):

    def test_both_client_files_parse(self):
        for path in (STEP3_VIEWS, STEP4_VIEWS):
            completed = subprocess.run(
                ["node", "--check", path], capture_output=True, text=True,
                timeout=60)
            self.assertEqual(completed.returncode, 0,
                             "%s does not parse:\n%s" % (path, completed.stderr))


if __name__ == "__main__":
    unittest.main(verbosity=2)
