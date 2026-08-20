#!/usr/bin/env python3
"""A metagene box on the diagram is coloured against the trends, not the omic.

Why this exists
---------------
There are three places that colour metagene values, and the first two fixes
each caught one of them:

  1. `PA_Step3PathwayDetailsView.generateHeatmap` -- the trend rows in the
     Pathway information panel.
  2. the other, top-level `generateHeatmap` in PA_Step3Views.js.
  3. `PA_Step4KeggDiagramFeatureSetSVGBox.generateBox` -- **the boxes painted
     on the pathway diagram itself**, which is this one.

The third was found by looking at production after the second shipped. The
Alzheimer map still showed flat yellow "Metagene" boxes, and instrumenting
getColor in the browser named the caller:

    PA_Step4Views.js:2641  value -0.0200  limits {min: 0.986, max: 1.042}

A metagene is a trend -- a component describing how a whole cluster of features
moves -- centred on zero, so it goes negative whatever the omic did. Measured on
paintomics.uv.es, the Proteomics omic runs 0.79..1.41 while its metagenes sit at
-0.02, -0.046 and -0.0037. Every one of those is off the bottom of the omic's
p10/p90 window, so every one was painted the same `rgb(255, 255,127)`: a flat
yellow, on values that are very close to no change at all.

That colour is *valid* -- the clamp in getColor sees to that -- and still means
nothing. Clamping stopped the output being broken; it could not make the
question being asked the right one.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_metagene_boxes_use_the_trend_scale
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

CLIENT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "PaintomicsClient", "public_html"))
STEP3 = os.path.join(CLIENT, "app", "view", "PathwayAcquisitionViews", "PA_Step3Views.js")
STEP4 = os.path.join(CLIENT, "app", "view", "PathwayAcquisitionViews", "PA_Step4Views.js")
MODELS = os.path.join(CLIENT, "app", "model", "FeatureModels.js")


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def strip_comments(text):
    """A rule described in a comment is not a rule."""
    try:
        return re.sub(r"/\*.*?\*/", "", re.sub(r"(?m)^\s*//.*$", "", text), flags=re.S)
    except Exception:
        return text


def extract(source, name):
    match = re.search(r"var\s+%s\s*=\s*function" % re.escape(name), source)
    if match is None:
        raise AssertionError("%s is not defined" % name)
    opening = source.index("{", match.end())
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1] + ";"
    raise AssertionError("unbalanced braces in %s" % name)


def generate_box(source):
    start = source.index("this.generateBox = function")
    depth = 0
    opening = source.index("{", start)
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("unbalanced braces in generateBox")


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TrendScaleBehaviourTest(unittest.TestCase):
    """What the colours actually come out as, with production's numbers."""

    def run_js(self, body):
        step3 = read(STEP3)
        helpers = "\n".join(extract(step3, name) for name in
                            ("paColourRange", "getMinMax", "paMetageneLimits",
                             "paOutlierFraction", "paChannel", "paRampPosition",
                             "getColor"))
        directory = tempfile.mkdtemp(prefix="paintomics-metabox-")
        try:
            path = os.path.join(directory, "check.js")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(helpers + "\n" + body)
            done = subprocess.run(["node", path], capture_output=True,
                                  text=True, timeout=60)
            if done.returncode != 0:
                raise AssertionError("node failed:\n%s" % done.stderr)
            return json.loads(done.stdout)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_the_production_metagenes_are_no_longer_flat_yellow(self):
        """The three values the live server was painting identically."""
        result = self.run_js("""
            // the Proteomics omic on job bF624h75w1, and its metagenes
            const omic = getMinMax([0,0,0.789984901,0.9859346925,null,null,null,
                                    1.0419202442,1.414217124], "p10p90");
            const trends = [{values: [-0.0200317, -0.0459393, -0.0037434, 0.031, 0.048]}];
            const trend = paMetageneLimits(trends);
            const probe = [-0.0459393, -0.0200317, -0.0037434];
            process.stdout.write(JSON.stringify({
              onTheOmicScale: probe.map(v => getColor(omic, v, "bwr")),
              onTheTrendScale: probe.map(v => getColor(trend, v, "bwr"))
            }));
        """)

        # Every value was the same yellow before: indistinguishable.
        self.assertEqual(set(result["onTheOmicScale"]), {"rgb(255, 255,127)"},
                         "the premise has changed; re-derive this test")

        distinct = set(result["onTheTrendScale"])
        self.assertGreater(len(distinct), 1,
                           "the trend scale still paints every metagene the "
                           "same colour: %s" % distinct)
        for colour in result["onTheTrendScale"]:
            self.assertNotIn("255,127", colour,
                             "still the meaningless yellow: %s" % colour)

    def test_a_trend_near_zero_is_near_white(self):
        """The reading that matters: small change looks like small change."""
        result = self.run_js("""
            const trend = paMetageneLimits([{values: [-4, 4]}]);
            process.stdout.write(JSON.stringify({
              atZero: getColor(trend, 0, "bwr"),
              slightlyDown: getColor(trend, -0.04, "bwr"),
              stronglyDown: getColor(trend, -4, "bwr"),
              stronglyUp: getColor(trend, 4, "bwr")
            }));
        """)
        self.assertEqual(result["atZero"], "rgb(255, 255,255)")
        self.assertEqual(result["stronglyDown"], "rgb(0, 0,255)")
        self.assertEqual(result["stronglyUp"], "rgb(255, 0,0)")

        # "almost no change" must be almost white, not a saturated anything.
        channels = [int(n) for n in re.findall(r"-?\d+", result["slightlyDown"])]
        self.assertTrue(all(c > 230 for c in channels),
                        "a metagene of -0.04 on a -4..4 scale is drawn as %s, "
                        "which is not 'nearly unchanged'" % result["slightlyDown"])

    def test_sibling_boxes_share_one_scale(self):
        """Boxes of the same set must be comparable with each other.

        The range is taken across the set's metagenes, not across the values in
        one box, or two boxes showing the same number would use different
        scales and disagree about its colour.
        """
        result = self.run_js("""
            // The ranges must genuinely differ, or this proves nothing:
            // paColourRange symmetrises, so [-4,1] and [-1,4] both become
            // +/-4 and the two scales are identical. A narrow box beside a
            // wide one is the case that separates them.
            const set = [{values: [-1, 1]}, {values: [-4, 4]}];
            const shared = paMetageneLimits(set);
            const perBoxA = paMetageneLimits([set[0]]);
            process.stdout.write(JSON.stringify({
              shared: {min: shared.min, max: shared.max},
              perBox: {min: perBoxA.min, max: perBoxA.max},
              sameValueShared: getColor(shared, 1, "bwr"),
              sameValuePerBox: getColor(perBoxA, 1, "bwr")
            }));
        """)
        self.assertNotEqual(result["sameValueShared"], result["sameValuePerBox"],
                            "this test cannot tell the two apart, so it proves "
                            "nothing about which one is used")
        self.assertEqual(result["shared"], {"min": -4, "max": 4})


class GenerateBoxWiringTest(unittest.TestCase):
    """The diagram painter asks the right question."""

    def setUp(self):
        self.block = strip_comments(generate_box(read(STEP4)))

    def test_a_metagene_box_uses_the_trend_scale(self):
        self.assertIn("paMetageneLimits", self.block,
                      "the diagram still colours metagene boxes with the "
                      "omic's distribution")

    def test_an_ordinary_box_still_uses_the_omic_scale(self):
        """The other half: this must not change how real features are drawn."""
        self.assertIn("getMinMax(dataDistributionSummaries[omicName]", self.block,
                      "ordinary feature boxes have lost the omic scale, which "
                      "is the correct scale for them")

    def test_the_choice_is_made_on_feature_type(self):
        self.assertRegex(self.block, r"isMetageneFeature\s*=\s*/\^meta/i\.test")

    def test_the_scale_comes_from_the_whole_set(self):
        self.assertIn("getMetagenes()", self.block,
                      "the range is taken from this box alone, so sibling "
                      "metagene boxes would not be comparable")


class TheIsMetageneLandmineTest(unittest.TestCase):
    """SimpleOmicValue.isMetagene cannot be used, and this says why.

    In FeatureModels.js the name is a boolean initialised to false, then
    overwritten by a METHOD of the same name, which setMetagene() then
    overwrites again with a boolean. So it is:

      * a function on an ordinary omic value -- and calling it returns
        `this.isMetagene`, which is that same function, i.e. truthy;
      * a boolean on the metagenes it exists to identify, where calling it
        throws "is not a function".

    Wrong in both directions. Nothing calls it today, and the diagram fix
    deliberately reads featureType instead. This test exists so that a later
    reader who finds the accessor and reaches for it discovers the trap here
    rather than in production.
    """

    def test_the_accessor_is_still_shadowed(self):
        source = read(MODELS)
        self.assertRegex(
            source, r"this\.isMetagene\s*=\s*false",
            "the boolean is gone; if isMetagene was properly separated from "
            "its accessor this test should be replaced by one that uses it")
        self.assertRegex(source, r"this\.isMetagene\s*=\s*function")
        self.assertRegex(source, r"this\.isMetagene\s*=\s*isMetagene")

    def test_nothing_calls_it(self):
        for name in ("PA_Step3Views.js", "PA_Step4Views.js"):
            path = os.path.join(CLIENT, "app", "view",
                                "PathwayAcquisitionViews", name)
            # Comments stripped first: the fix's own comment quotes the
            # accessor to explain why it is not used, and reading the raw file
            # made this test fail on that prose.
            self.assertNotIn("isMetagene()", strip_comments(read(path)),
                             "%s calls isMetagene(), which throws for metagenes "
                             "and is truthy for everything else" % name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
