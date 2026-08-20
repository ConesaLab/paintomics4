#!/usr/bin/env python3
"""Two invariants of the pathway heatmaps, checked against the real JavaScript.

Both were broken at once by the MORE regulator omic, and neither is visible to
a Python test suite, so the helpers are lifted out of PA_Step3Views.js and run
under node.

1. A colour stop is never NaN
---------------------------------
`getColor` divided by `limits.min` on its non-positive branch. For an omic
whose values never cross zero -- the bundled MORE regulators run 0.00 to 14.71
-- that is 0/0 at the bottom of the range, and the result is the string
"rgb(NaN, NaN,NaN)". A single invalid stop makes CSS discard an entire
`linear-gradient`, which is why the legend beside those heatmaps rendered as an
empty white box rather than a ramp. It is a whole-element failure caused by one
sample, so a test that only checks the midpoint would have passed.

The same guard also stretches a non-diverging range across the full min..max.
bwr and rbg are built around a zero midpoint; on all-positive data half the
scale is unreachable and anchoring at zero wastes the pale end too. Diverging
data must keep the zero anchor, and that is pinned here as well -- it is the
half of the change that could silently alter every existing result.

2. Cells are plotted in the space their axis is labelled in
-----------------------------------------------------------
An OmicValue carries `values` (one per uploaded column) and, once a replicate
or design grouping is applied, `sampleValues` (one per condition).
`paOmicHeaders` returns whichever header matches the job's mode, so a renderer
that labels from that header and then plots `values` unconditionally is
captioning one space with the other's names.

Measured on the bundled example the day the design grouping landed: the heatmap
drew 36 replicate columns and labelled the first twelve "Ctr_0H … Ik_24H", so
column 2 read Ctr_2H while holding Batch_2_Ctr_0H. Wrong labels beat missing
ones only in being harder to notice. `paValuesForHeader` picks the series whose
length matches the header, and `paConditionAxis` discards a header that does
not describe the columns instead of pasting a partial one -- the same rule
`paSharedOmicHeader` already applied to disagreeing omics.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_heatmap_colour_and_column_space
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

STEP3_VIEWS = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "../../../PaintomicsClient/public_html/app/view/PathwayAcquisitionViews/PA_Step3Views.js"))

# The helpers under test, plus the ones they delegate to. getMinMax and
# paColourRange are here because the tests below that hand-build a `limits`
# object prove less than they appear to: nothing in the application ever builds
# one by hand, and for two years getMinMax could not produce the very shape
# those tests assert on. See SequentialRangeReachableTest.
HELPERS = ("paColourRange", "getMinMax", "paRampPosition", "getColor",
           "paValuesForHeader", "paTruncateTail", "paConditionAxis")


def read_source():
    with open(STEP3_VIEWS, "r", encoding="utf-8") as handle:
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
    """Evaluate `body` with every helper in scope; return its parsed stdout."""
    source = read_source()
    script = "\n".join(extract(source, name) for name in HELPERS) + "\n" + body
    directory = tempfile.mkdtemp(prefix="paintomics-js-")
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


class SourceStructureTest(unittest.TestCase):
    """Holds with or without a JavaScript runtime available."""

    def test_every_helper_is_defined(self):
        source = read_source()
        for name in HELPERS:
            self.assertIsNotNone(
                re.search(r"var\s+%s\s*=\s*function" % re.escape(name), source),
                "%s() has been renamed or removed" % name)

    def test_no_scale_divides_by_a_limit_directly(self):
        """The division that produced NaN must stay behind paRampPosition().

        Pinning the absence of the old expression, not just the presence of the
        new helper: re-introducing `value / limits.min` in one branch would
        bring the empty legend back for that scale alone.
        """
        source = read_source()
        colour = extract(source, "getColor")
        self.assertNotIn("value / limits.min", colour)
        self.assertNotIn("value / limits.max", colour)


RANGES = [
    {"name": "all-positive from zero", "min": 0, "max": 14.71},
    {"name": "positive, min above zero", "min": 5, "max": 14.71},
    {"name": "all-negative", "min": -8, "max": 0},
    {"name": "diverging", "min": -3, "max": 3},
    {"name": "degenerate", "min": 7, "max": 7},
]


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ColourStopTest(unittest.TestCase):

    def test_no_range_and_no_scale_ever_yields_a_nan_stop(self):
        results = run_in_node("""
            const ranges = %s;
            const bad = [];
            ranges.forEach(function (r) {
              const limits = {min: r.min, max: r.max, absMin: r.min - 1, absMax: r.max + 1};
              ["bwr", "bwr2", "rbg"].forEach(function (scale) {
                for (var i = 0; i <= 40; i++) {
                  var v = (r.max === r.min) ? r.min : r.min + (i / 40) * (r.max - r.min);
                  var c = getColor(limits, v, scale);
                  if (/NaN|undefined/.test(c)) bad.push(r.name + " " + scale + " @" + v + " -> " + c);
                }
              });
            });
            process.stdout.write(JSON.stringify(bad));
        """ % json.dumps(RANGES))
        self.assertEqual(results, [], "invalid colour stops: %s" % results[:5])

    def test_a_sequential_range_uses_the_whole_ramp(self):
        result = run_in_node("""
            const limits = {min: 5, max: 14.71, absMin: 5, absMax: 14.71};
            process.stdout.write(JSON.stringify({
              atMin: getColor(limits, 5, "bwr"),
              atMax: getColor(limits, 14.71, "bwr")
            }));
        """)
        # Pale end at the observed minimum, saturated at the maximum.
        self.assertEqual(result["atMin"], "rgb(255, 255,255)")
        self.assertEqual(result["atMax"], "rgb(255, 0,0)")

    def test_a_diverging_range_keeps_its_zero_anchor(self):
        result = run_in_node("""
            const limits = {min: -3, max: 3, absMin: -4, absMax: 4};
            process.stdout.write(JSON.stringify({
              atMin: getColor(limits, -3, "bwr"),
              atZero: getColor(limits, 0, "bwr"),
              atMax: getColor(limits, 3, "bwr")
            }));
        """)
        self.assertEqual(result["atMin"], "rgb(0, 0,255)")
        self.assertEqual(result["atZero"], "rgb(255, 255,255)")
        self.assertEqual(result["atMax"], "rgb(255, 0,0)")


# [MAPPED, UNMAPPED, MIN, P10, Q1, MEDIAN, Q3, P90, MAX, MIN_IR, MAX_IR,
#  MIN_CUSTOM, MAX_CUSTOM] -- the layout getMinMax documents and indexes.
def summary(minimum, p10, q1, median, q3, p90, maximum,
            minIR=None, maxIR=None, customMin=None, customMax=None):
    row = [0, 0, minimum, p10, q1, median, q3, p90, maximum,
           p10 if minIR is None else minIR,
           p90 if maxIR is None else maxIR]
    if customMin is not None:
        row.extend([customMin, customMax])
    return row


class SequentialRangeReachableTest(unittest.TestCase):
    """The ramp that stretches to the data has to be REACHABLE from real data.

    test_a_sequential_range_uses_the_whole_ramp above passes, and passed before
    any of this was fixed, because it writes its own limits:

        const limits = {min: 5, max: 14.71, ...}

    Nothing in the application does. Every `limits` comes from getMinMax, and
    getMinMax ended each branch with

        min = ((low > 0) ? 0 : -max);

    so for data that never went below zero it returned min: 0, always. The
    stretch existed, was covered by a test, and could not be entered. The
    measured consequence, on the bundled MORE regulator omic (1.93..20.93):
    every value satisfied `value > 0`, red was pinned at 255, and the
    interquartile range -- half the points -- was drawn across 33 of 255, so
    whole pathway diagrams came out one flat red.

    These tests therefore start where the application starts: at a distribution
    summary.
    """

    def _limits(self, row, option="absoluteMinMax"):
        return run_in_node(
            "process.stdout.write(JSON.stringify(getMinMax(%s, %s)));"
            % (json.dumps(row), json.dumps(option)))

    def test_all_positive_data_keeps_its_own_minimum(self):
        """The regression, at the only place that can produce it."""
        limits = self._limits(summary(1.93, 8.50, 10.99, 12.75, 13.73, 14.71, 20.93))

        self.assertAlmostEqual(limits["min"], 1.93,
                               msg="the observed minimum was replaced by 0, so "
                                   "the pale end of the ramp carries no data "
                                   "and every box is red")
        self.assertAlmostEqual(limits["max"], 20.93)

    def test_all_positive_data_reaches_white_at_its_minimum(self):
        """End to end: summary -> getMinMax -> getColor."""
        row = summary(1.93, 8.50, 10.99, 12.75, 13.73, 14.71, 20.93)
        result = run_in_node("""
            const limits = getMinMax(%s, "absoluteMinMax");
            process.stdout.write(JSON.stringify({
              atMin: getColor(limits, 1.93, "bwr"),
              atMax: getColor(limits, 20.93, "bwr")
            }));
        """ % json.dumps(row))

        self.assertEqual(result["atMin"], "rgb(255, 255,255)")
        self.assertEqual(result["atMax"], "rgb(255, 0,0)")

    def test_the_interquartile_range_is_no_longer_compressed(self):
        """The complaint, quantified.

        Anchored at zero the middle half of this omic spanned 33 of the 255
        available steps. Spanning the data instead has to widen that materially
        -- not merely change it -- or the diagram still reads as flat.
        """
        row = summary(1.93, 8.50, 10.99, 12.75, 13.73, 14.71, 20.93)
        result = run_in_node("""
            const limits = getMinMax(%s, "absoluteMinMax");
            const channel = v => parseInt(getColor(limits, v, "bwr").split(",")[1], 10);
            process.stdout.write(JSON.stringify({q1: channel(10.99), q3: channel(13.73)}));
        """ % json.dumps(row))

        spread = result["q1"] - result["q3"]
        self.assertGreater(spread, 33,
                           "the interquartile range still occupies no more of "
                           "the ramp than it did when anchored at zero")

    def test_diverging_data_still_gets_a_symmetric_range(self):
        """The half that must NOT change.

        A range of -2..+8 drawn asymmetrically would paint -2 and +2 at
        different intensities and assert a difference the data does not hold.
        Zero-crossing data keeps the symmetry it always had.
        """
        limits = self._limits(summary(-2, -1.5, -0.5, 0.5, 3, 6, 8))

        self.assertEqual(limits["min"], -8)
        self.assertEqual(limits["max"], 8)

    def test_all_negative_data_no_longer_paints_an_invalid_colour(self):
        """`rgb(255, 255,-Infinity)` was the literal output, for every value.

        With `max = ((high < 0) ? 0 : ...)` and `min = -max`, an all-negative
        omic collapsed to {min: 0, max: 0}; getColor then divided by
        (absMin - min) = 0 and emitted -Infinity into the blue channel. CSS
        discards the declaration, so the cell fell back to whatever was under
        it -- a heatmap that silently showed no data at all.
        """
        row = summary(-12, -10, -9, -8, -7, -6, -5)
        result = run_in_node("""
            const limits = getMinMax(%s, "absoluteMinMax");
            const values = [-12, -10, -8, -6, -5];
            process.stdout.write(JSON.stringify({
              limits: limits,
              colours: values.map(v => getColor(limits, v, "bwr"))
            }));
        """ % json.dumps(row))

        for colour in result["colours"]:
            self.assertNotIn("Infinity", colour)
            self.assertNotIn("NaN", colour)

        self.assertEqual(result["limits"]["min"], -12)
        self.assertEqual(result["limits"]["max"], -5)

    def test_all_negative_data_saturates_at_the_most_negative_value(self):
        """Direction, not just validity.

        Anchoring an all-negative ramp at its minimum would paint -12 palest
        and -5 the deepest blue -- announcing the least negative point as the
        strongest downward effect. Saturation has to track distance from zero.
        """
        row = summary(-12, -10, -9, -8, -7, -6, -5)
        result = run_in_node("""
            const limits = getMinMax(%s, "absoluteMinMax");
            process.stdout.write(JSON.stringify({
              nearestZero: getColor(limits, -5, "bwr"),
              furthest: getColor(limits, -12, "bwr")
            }));
        """ % json.dumps(row))

        self.assertEqual(result["nearestZero"], "rgb(255, 255,255)")
        self.assertEqual(result["furthest"], "rgb(0, 0,255)")

    def test_the_custom_slider_can_actually_move_the_low_end(self):
        """The setting that looked like a workaround and was not one.

        Visual settings offers a two-handled range slider, initialised from
        getMinMax(..., "absoluteMinMax"). Dragging its low end to 5 stores 5 in
        MIN_CUSTOM -- and the custom branch ran the same `(low > 0) ? 0` clamp,
        so the value was discarded and the range stayed 0..12. Anyone trying to
        fix the flat-red diagram by hand found the control did nothing.
        """
        row = summary(1, 2, 3, 5, 8, 10, 12, customMin=5, customMax=12)
        limits = self._limits(row, "custom")

        self.assertEqual(limits["min"], 5,
                         "the custom range's low end is still being clamped "
                         "to zero, so the slider does nothing on positive data")
        self.assertEqual(limits["max"], 12)

    def test_a_value_below_a_clipped_range_lands_at_the_pale_end(self):
        """paRampPosition used Math.abs, which folds under-range points back up.

        Safe only while `lo` was pinned at 0 and the ramp could not be entered
        from underneath. Once p10 is a real 8.5 on data reaching to 1.93, the
        absolute value turns a position of -1.06 into +1.06 and paints the
        SMALLEST value the most intense one on the map.
        """
        row = summary(1.93, 8.50, 10.99, 12.75, 13.73, 14.71, 20.93)
        result = run_in_node("""
            const limits = getMinMax(%s, "p10p90");
            process.stdout.write(JSON.stringify({
              belowClip: getColor(limits, 1.93, "bwr"),
              atClip: getColor(limits, 8.50, "bwr")
            }));
        """ % json.dumps(row))

        self.assertEqual(result["belowClip"], "rgb(255, 255,255)")
        self.assertEqual(result["atClip"], "rgb(255, 255,255)")

    def test_an_outlier_above_a_clipped_range_is_still_darkened(self):
        """The clamp must not cost the outlier shading above the clip.

        Positions above 1 stay as they are; only the negative side is clamped.
        """
        row = summary(1.93, 8.50, 10.99, 12.75, 13.73, 14.71, 20.93)
        result = run_in_node("""
            const limits = getMinMax(%s, "p10p90");
            process.stdout.write(JSON.stringify({
              atClip: getColor(limits, 14.71, "bwr"),
              beyond: getColor(limits, 20.93, "bwr")
            }));
        """ % json.dumps(row))

        self.assertEqual(result["atClip"], "rgb(255, 0,0)")
        self.assertNotEqual(result["beyond"], result["atClip"],
                            "a value past the p90 clip is drawn identically to "
                            "the clip itself, so the outlier shading is gone")


# 12 conditions plus the leading feature-id column.
HEADER_12 = ["#id", "Ctr_0H", "Ctr_2H", "Ctr_6H", "Ctr_12H", "Ctr_18H", "Ctr_24H",
             "Ik_0H", "Ik_2H", "Ik_6H", "Ik_12H", "Ik_18H", "Ik_24H"]


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ColumnSpaceTest(unittest.TestCase):

    def test_an_aggregated_omic_is_plotted_in_condition_space(self):
        result = run_in_node("""
            const header = %s;
            const ov = {values: new Array(36).fill(1), sampleValues: new Array(12).fill(2)};
            process.stdout.write(JSON.stringify(paValuesForHeader(ov, header).length));
        """ % json.dumps(HEADER_12))
        self.assertEqual(result, 12)

    def test_an_un_aggregated_omic_keeps_its_own_columns(self):
        result = run_in_node("""
            const header = %s;
            const ov = {values: new Array(36).fill(1)};
            process.stdout.write(JSON.stringify(paValuesForHeader(ov, header).length));
        """ % json.dumps(HEADER_12))
        self.assertEqual(result, 36)

    def test_a_stale_aggregation_is_not_plotted(self):
        """sampleValues of the wrong length is a mismatch, not a preference."""
        result = run_in_node("""
            const header = %s;
            const ov = {values: new Array(36).fill(1), sampleValues: new Array(7).fill(2)};
            process.stdout.write(JSON.stringify(paValuesForHeader(ov, header).length));
        """ % json.dumps(HEADER_12))
        self.assertEqual(result, 36)

    def test_a_matching_header_labels_the_axis_with_real_names(self):
        result = run_in_node("""
            const header = %s;
            process.stdout.write(JSON.stringify(paConditionAxis(12, header, {}).categories));
        """ % json.dumps(HEADER_12))
        self.assertEqual(result[:3], ["Ctr_0H", "Ctr_2H", "Ctr_6H"])
        self.assertEqual(len(result), 12)

    def test_a_mismatched_header_is_discarded_rather_than_pasted(self):
        """The regression: 36 columns must never wear the 12 condition names."""
        result = run_in_node("""
            const header = %s;
            process.stdout.write(JSON.stringify(paConditionAxis(36, header, {}).categories));
        """ % json.dumps(HEADER_12))
        self.assertEqual(len(result), 36)
        self.assertEqual(result[:2], ["Condition 1", "Condition 2"])
        for name in ("Ctr_0H", "Ik_24H"):
            self.assertNotIn(name, result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
