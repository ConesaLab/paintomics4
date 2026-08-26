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
HELPERS = ("paColourRange", "getMinMax", "paMetageneLimits", "paOutlierFraction",
           "paChannel", "paRampPosition", "PA_RAMP", "paOklabChannels",
           "paDivergingChannels", "getColor", "paValuesForHeader",
           "paTruncateTail", "paConditionAxis")


def read_source():
    with open(STEP3_VIEWS, "r", encoding="utf-8") as handle:
        return handle.read()


def extract(source, name):
    """The text of `var <name> = <brace-delimited value>;`, brace-matched.

    Matches up to the `=` rather than to `function`, so a plain object literal
    lifts out the same way a function does. PA_RAMP is one: the ramp's
    endpoints are data, not code, and getColor cannot run without them.
    """
    # Lookahead, not a consuming group: the brace scan below starts from
    # match.end(), so consuming the `{` of an object literal would make it
    # find the first NESTED brace and stop at the wrong place.
    match = re.search(r"var\s+%s\s*=\s*(?=function|\{)" % re.escape(name), source)
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
                re.search(r"var\s+%s\s*=\s*(?:function|\{)" % re.escape(name), source),
                "%s has been renamed or removed" % name)

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
        self.assertEqual(result["atMin"], "rgb(232, 232,232)")
        self.assertEqual(result["atMax"], "rgb(165, 31,30)")

    def test_a_diverging_range_keeps_its_zero_anchor(self):
        result = run_in_node("""
            const limits = {min: -3, max: 3, absMin: -4, absMax: 4};
            process.stdout.write(JSON.stringify({
              atMin: getColor(limits, -3, "bwr"),
              atZero: getColor(limits, 0, "bwr"),
              atMax: getColor(limits, 3, "bwr")
            }));
        """)
        self.assertEqual(result["atMin"], "rgb(15, 89,169)")
        self.assertEqual(result["atZero"], "rgb(232, 232,232)")
        self.assertEqual(result["atMax"], "rgb(165, 31,30)")


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

        self.assertEqual(result["atMin"], "rgb(232, 232,232)")
        self.assertEqual(result["atMax"], "rgb(165, 31,30)")

    def test_the_interquartile_range_is_no_longer_compressed(self):
        """The complaint, quantified.

        Anchored at zero the middle half of this omic spanned 33 of the 255
        available steps. Spanning the data instead has to widen that materially
        -- not merely change it -- or the diagram still reads as flat.
        """
        row = summary(1.93, 8.50, 10.99, 12.75, 13.73, 14.71, 20.93)
        result = run_in_node("""
            const limits = getMinMax(%s, "absoluteMinMax");
            const step = v => Math.round(paRampPosition(limits, v) * 255);
            process.stdout.write(JSON.stringify({q1: step(10.99), q3: step(13.73)}));
        """ % json.dumps(row))

        # Measured on paRampPosition rather than on a colour channel. The green
        # channel used to BE the ramp position -- the old scale walked it 255
        # to 0 in a straight line -- so reading it was a shortcut, not a
        # measurement, and the shortcut stopped being true when the ramp moved
        # into OKLab. The claim was always about how much of the ramp the
        # middle half occupies, and that is what is asked now.
        spread = result["q3"] - result["q1"]
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

        self.assertEqual(result["nearestZero"], "rgb(232, 232,232)")
        self.assertEqual(result["furthest"], "rgb(15, 89,169)")

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

        self.assertEqual(result["belowClip"], "rgb(232, 232,232)")
        self.assertEqual(result["atClip"], "rgb(232, 232,232)")

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

        self.assertEqual(result["atClip"], "rgb(165, 31,30)")
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


class MetageneTrendsGetTheirOwnScaleTest(unittest.TestCase):
    """A trend is not the omic it summarises, and must not borrow its scale.

    `generateHeatmap` coloured `metagenes[i].values` with
    `getMinMax(dataDistributionSummaries[omicName], "p10p90")` -- the raw
    omic's distribution. A metagene is a component describing how a cluster
    moves, centred on zero, on its own scale entirely. Measured on a real
    production job the omic ran 0.79..1.41 while its metagenes reached +/-9.4:
    eight times outside the scale in both directions.

    getColor's outlier term then runs far past 1 and pushes channels out of
    range. Captured from the live server:

        rgb(0, 0,-2744)      rgb(255, 255,-410)

    Chrome clamps the second to yellow and rejects the first outright, painting
    it black, so the trend rows showed two arbitrary colours that meant nothing
    about the data.
    """

    def _colours(self, metagenes, values):
        return run_in_node("""
            const limits = paMetageneLimits(%s);
            process.stdout.write(JSON.stringify({
              limits: limits,
              colours: %s.map(v => getColor(limits, v, "bwr"))
            }));
        """ % (json.dumps(metagenes), json.dumps(values)))

    def test_a_metagene_never_produces_an_impossible_colour(self):
        """The regression, with the real numbers that produced it."""
        metagenes = [{"values": [-6.655823, -7.692578, 7.549343, 9.402448, 0.1]}]
        result = self._colours(metagenes, [-7.692578, -1.0, 0.0, 9.402448])
        for colour in result["colours"]:
            self.assertNotIn("-", colour, "channel out of range: %s" % colour)
            self.assertNotIn("Infinity", colour)
            self.assertNotIn("NaN", colour)

    def test_the_scale_comes_from_the_trends_not_the_omic(self):
        metagenes = [{"values": [-9.4, 9.4]}]
        result = self._colours(metagenes, [0])
        self.assertAlmostEqual(result["limits"]["max"], 9.4)
        self.assertAlmostEqual(result["limits"]["min"], -9.4)

    def test_a_trend_reads_as_a_diverging_scale(self):
        """Blue for down, red for up, white for no change."""
        metagenes = [{"values": [-4.0, 4.0]}]
        result = self._colours(metagenes, [-4.0, 0.0, 4.0])
        self.assertEqual(result["colours"][0], "rgb(15, 89,169)")
        self.assertEqual(result["colours"][1], "rgb(232, 232,232)")
        self.assertEqual(result["colours"][2], "rgb(165, 31,30)")

    def test_the_range_is_symmetric_so_equal_moves_read_equally(self):
        """An asymmetric trend range would say -2 and +2 differ. They do not.

        Asked of the ramp POSITION, not of a raw channel. Comparing the blue
        channel of the down colour with the red channel of the up one worked
        only while the two poles were pure primaries and each owned exactly one
        channel. The diverging ramp gives its two sides deliberately different
        chroma -- blue needs less of it to carry the same weight -- so equal
        channel numbers would now mean unequal colours, and the test would have
        been enforcing the opposite of what it says.
        """
        metagenes = [{"values": [-1.0, 8.0]}]
        result = run_in_node("""
            const limits = paMetageneLimits(%s);
            process.stdout.write(JSON.stringify({
              down: paRampPosition(limits, -2.0),
              up: paRampPosition(limits, 2.0),
              colours: [-2.0, 2.0].map(v => getColor(limits, v, "bwr"))
            }));
        """ % json.dumps(metagenes))

        self.assertAlmostEqual(result["down"], result["up"],
                               msg="equal magnitudes either side of zero are "
                                   "drawn at different intensities")
        # ...and they are still two different colours, not one.
        self.assertNotEqual(result["colours"][0], result["colours"][1])

    def test_several_trends_share_one_scale(self):
        """Rows of the same chart must be comparable with each other."""
        metagenes = [{"values": [-1.0, 1.0]}, {"values": [-5.0, 5.0]}]
        result = self._colours(metagenes, [5.0])
        self.assertAlmostEqual(result["limits"]["max"], 5.0)
        self.assertEqual(result["colours"][0], "rgb(165, 31,30)")

    def test_unusable_values_do_not_poison_the_chart(self):
        """One NaN must not take every colour on the chart with it.

        Metagene values arrive as strings and a cluster with a gap yields NaN,
        which would otherwise propagate through both ends of the range.
        """
        metagenes = [{"values": ["-2.0", "nonsense", "2.0", None]}]
        result = self._colours(metagenes, [-2.0, 2.0])
        self.assertAlmostEqual(result["limits"]["max"], 2.0)
        for colour in result["colours"]:
            self.assertNotIn("NaN", colour)

    def test_no_values_at_all_is_a_valid_colour(self):
        result = self._colours([], [0])
        self.assertNotIn("NaN", result["colours"][0])
        self.assertNotIn("-", result["colours"][0])


class GenerateHeatmapUsesTheTrendScaleTest(unittest.TestCase):
    """Wiring: the helper exists and generateHeatmap is what calls it."""

    def test_generate_heatmap_no_longer_borrows_the_omic_distribution(self):
        source = read_source()
        start = source.index("this.generateHeatmap = function")
        block = source[start:start + 2500]
        self.assertIn("paMetageneLimits(metagenes)", block)
        self.assertNotIn('getMinMax(dataDistributionSummaries[omicName], "p10p90")', block,
                         "the trend heatmap is still coloured with the raw "
                         "omic's distribution")


# Three integers, each 0..255. `\d{1,3}` is not that: it accepts rgb(510, 0,0),
# which is how the out-of-range-ABOVE case hid -- Chrome clamps it to 255 and
# renders, so it never looked broken the way a negative channel did.
VALID_RGB = re.compile(
    r"^rgb\((25[0-5]|2[0-4]\d|1?\d?\d), (25[0-5]|2[0-4]\d|1?\d?\d),"
    r"(25[0-5]|2[0-4]\d|1?\d?\d)\)$")

# The same test, for the node side.
JS_VALID = """
function isColour(s) {
  const m = /^rgb\\((-?\\d+), (-?\\d+),(-?\\d+)\\)$/.exec(s);
  if (!m) return false;
  for (let i = 1; i <= 3; i++) {
    const n = Number(m[i]);
    if (!Number.isInteger(n) || n < 0 || n > 255) return false;
  }
  return true;
}
"""


class GetColorAlwaysReturnsAColourTest(unittest.TestCase):
    """Whatever it is handed, what leaves getColor is a colour.

    Channels were free to run out of range and did. Captured off
    paintomics.uv.es: `rgb(255, 255,-402)` and `rgb(0, 0,-2744)`; and before
    the ramp was clamped, `rgb(247, 247,-Infinity)`. Chrome clamps the first to
    yellow and rejects the last outright, painting it black, so cells that
    should have been pale showed as two loud, arbitrary colours.

    The cause is upstream and there is more than one of it: any caller that
    colours one quantity against another quantity's distribution can push a
    value outside [absMin, absMax], which makes the outlier term exceed 1. Two
    such sites were found -- the metagene trend heatmap, and this file's other
    generateHeatmap, which takes omicsValues and was missed by the first fix.
    Hence the invariant lives in getColor, the one place every colour comes
    from, rather than being restated at each caller.
    """

    def test_no_combination_produces_an_invalid_colour(self):
        """A sweep, because the failures came from inputs nobody predicted."""
        result = run_in_node(JS_VALID + """
            const summaries = [
              [0,0, 0.79, 0.98, null,null,null, 1.04, 1.41],     // all positive
              [0,0, -1.27, -1.03, null,null,null, 0.45, 0.56],   // crosses zero
              [0,0, -12, -10, null,null,null, -6, -5],           // all negative
              [0,0, 5, 5, null,null,null, 5, 5],                 // degenerate
              [0,0, 0, 0, null,null,null, 0, 0]                  // all zero
            ];
            const values = [-2744, -9.4, -1, -0.02, 0, 0.02, 1, 9.4, 2744, NaN, Infinity, -Infinity];
            const options = ["absoluteMinMax", "p10p90", "riMinMax"];
            const scales = ["bwr", "bwr2", "rbg"];
            const bad = [];
            let n = 0;
            for (const s of summaries) for (const o of options) {
              const lim = getMinMax(s, o);
              for (const v of values) for (const sc of scales) {
                n++;
                const out = getColor(lim, v, sc);
                if (!isColour(out)) {
                  if (bad.length < 8) bad.push({limits: lim, value: String(v), scale: sc, out: out});
                }
              }
            }
            process.stdout.write(JSON.stringify({checked: n, bad: bad}));
        """)
        self.assertEqual(result["bad"], [],
                         "getColor produced something that is not a colour")
        self.assertGreater(result["checked"], 400, "the sweep did not run")

    def test_the_production_failures_are_colours_now(self):
        """The exact numbers the live server was caught emitting."""
        result = run_in_node("""
            const a = getMinMax([0,0,0.789984901,0.9859346925,null,null,null,1.0419202442,1.414217124], "p10p90");
            const b = getMinMax([0,0,-1.267366,-1.0271118,null,null,null,0.45,0.5599585], "p10p90");
            process.stdout.write(JSON.stringify({
              wasMinus402: getColor(a, -0.0200317, "bwr"),
              wasMinus2744: getColor(b, -6.6558233, "bwr")
            }));
        """)
        for key, colour in result.items():
            self.assertRegex(colour, VALID_RGB,
                             "%s is still not a colour: %s" % (key, colour))

    def test_the_outlier_term_is_a_fraction(self):
        """It is a proportion of the clip-to-extreme distance. It cannot exceed 1."""
        result = run_in_node("""
            const lim = getMinMax([0,0,-1.267366,-1.0271118,null,null,null,0.45,0.5599585], "p10p90");
            process.stdout.write(JSON.stringify({
              farBelow: paOutlierFraction(lim, -6.66),
              farAbove: paOutlierFraction(lim, 9.40),
              justOutside: paOutlierFraction(lim, -1.1),
              inside: paOutlierFraction(lim, 0.0)
            }));
        """)
        self.assertEqual(result["farBelow"], 1)
        self.assertEqual(result["farAbove"], 1)
        self.assertLessEqual(result["justOutside"], 1)
        self.assertGreaterEqual(result["inside"], 0)

    def test_an_unclipped_reference_has_no_outlier_distance(self):
        """absoluteMinMax does not clip, so there is no "past the clip".

        The denominator is zero there, and it used to divide by it.
        """
        result = run_in_node("""
            const lim = getMinMax([0,0,1.93,8.5,null,null,null,14.7,20.93], "absoluteMinMax");
            process.stdout.write(JSON.stringify({fraction: paOutlierFraction(lim, 20.93)}));
        """)
        self.assertEqual(result["fraction"], 0)


# What the code produced BEFORE the clamp, for every case where its answer was
# already a colour. Recorded rather than recomputed from git: the first version
# of this compared against `git show HEAD:...`, which is the pre-change file
# only until the change is committed -- after that it compares the new code
# with itself, the lifted helpers no longer resolve, and it fails for a reason
# that has nothing to do with colour. A recorded table is what the
# versioned-asset guard already does in this repo, and it cannot rot that way.
#
# (summary index, colour reference, value, scale, colour)
#
# The `bwr` column was RE-BASELINED when that scale moved off the pure primaries
# and onto the OKLab diverging ramp (PA_RAMP). That was a deliberate,
# whole-application repaint, so "unchanged" could not be asserted of it and
# pretending otherwise would have meant deleting the rows -- which would have
# left the one scale the application actually defaults to as the only one this
# table does not cover. The `rbg` and `bwr2` rows were NOT touched: they still
# pin the clamp fix against the exact colours it shipped with, so an accidental
# change to the shared arithmetic still shows up here.
COLOURS_BEFORE_THE_CLAMP = [
    (0, 'absoluteMinMax', 0.79, 'bwr', 'rgb(232, 232,232)'),
    (0, 'absoluteMinMax', 0.79, 'bwr2', 'rgb(255, 255,255)'),
    (0, 'absoluteMinMax', 0.79, 'rbg', 'rgb(0, 0,0)'),
    (0, 'absoluteMinMax', 1.1, 'bwr', 'rgb(217, 132,123)'),
    (0, 'absoluteMinMax', 1.1, 'bwr2', 'rgb(255, 127,127)'),
    (0, 'absoluteMinMax', 1.1, 'rbg', 'rgb(128, 0,0)'),
    (0, 'absoluteMinMax', 1.41, 'bwr', 'rgb(165, 31,30)'),
    (0, 'absoluteMinMax', 1.41, 'bwr2', 'rgb(255, 0,0)'),
    (0, 'absoluteMinMax', 1.41, 'rbg', 'rgb(255, 0,0)'),
    (0, 'p10p90', 0.79, 'bwr', 'rgb(232, 232,232)'),
    (0, 'p10p90', 0.79, 'bwr2', 'rgb(255, 86,255)'),
    (0, 'p10p90', 0.79, 'rbg', 'rgb(0, 0,0)'),
    (0, 'p10p90', 1.1, 'bwr', 'rgb(156, 25,25)'),
    (0, 'p10p90', 1.1, 'bwr2', 'rgb(255, 21,0)'),
    (0, 'p10p90', 1.41, 'bwr', 'rgb(109, 0,0)'),
    (0, 'p10p90', 1.41, 'bwr2', 'rgb(255, 128,0)'),
    (1, 'absoluteMinMax', -1.27, 'bwr', 'rgb(15, 89,169)'),
    (1, 'absoluteMinMax', -1.27, 'bwr2', 'rgb(0, 0,255)'),
    (1, 'absoluteMinMax', -1.27, 'rbg', 'rgb(0, 255,0)'),
    (1, 'absoluteMinMax', -0.355, 'bwr', 'rgb(164, 193,230)'),
    (1, 'absoluteMinMax', -0.355, 'bwr2', 'rgb(184, 184,255)'),
    (1, 'absoluteMinMax', -0.355, 'rbg', 'rgb(0, 71,0)'),
    (1, 'absoluteMinMax', 0.56, 'bwr', 'rgb(222, 143,134)'),
    (1, 'absoluteMinMax', 0.56, 'bwr2', 'rgb(255, 143,143)'),
    (1, 'absoluteMinMax', 0.56, 'rbg', 'rgb(112, 0,0)'),
    (1, 'p10p90', -1.27, 'bwr', 'rgb(0, 51,114)'),
    (1, 'p10p90', -1.27, 'bwr2', 'rgb(0, 128,255)'),
    (1, 'p10p90', -0.355, 'bwr', 'rgb(151, 184,226)'),
    (1, 'p10p90', -0.355, 'bwr2', 'rgb(167, 167,255)'),
    (1, 'p10p90', -0.355, 'rbg', 'rgb(0, 88,0)'),
    (1, 'p10p90', 0.56, 'bwr', 'rgb(213, 124,114)'),
    (1, 'p10p90', 0.56, 'bwr2', 'rgb(255, 116,116)'),
    (1, 'p10p90', 0.56, 'rbg', 'rgb(139, 0,0)'),
    (2, 'absoluteMinMax', 1.93, 'bwr', 'rgb(232, 232,232)'),
    (2, 'absoluteMinMax', 1.93, 'bwr2', 'rgb(255, 255,255)'),
    (2, 'absoluteMinMax', 1.93, 'rbg', 'rgb(0, 0,0)'),
    (2, 'absoluteMinMax', 11.43, 'bwr', 'rgb(217, 132,123)'),
    (2, 'absoluteMinMax', 11.43, 'bwr2', 'rgb(255, 128,128)'),
    (2, 'absoluteMinMax', 11.43, 'rbg', 'rgb(128, 0,0)'),
    (2, 'absoluteMinMax', 20.93, 'bwr', 'rgb(165, 31,30)'),
    (2, 'absoluteMinMax', 20.93, 'bwr2', 'rgb(255, 0,0)'),
    (2, 'absoluteMinMax', 20.93, 'rbg', 'rgb(255, 0,0)'),
    (2, 'p10p90', 1.93, 'bwr', 'rgb(232, 232,232)'),
    (2, 'p10p90', 1.93, 'rbg', 'rgb(0, 0,0)'),
    (2, 'p10p90', 11.43, 'bwr', 'rgb(219, 137,128)'),
    (2, 'p10p90', 11.43, 'bwr2', 'rgb(255, 134,134)'),
    (2, 'p10p90', 11.43, 'rbg', 'rgb(121, 0,0)'),
    (2, 'p10p90', 20.93, 'bwr', 'rgb(109, 0,0)'),
    (2, 'p10p90', 20.93, 'bwr2', 'rgb(255, 128,0)'),
    (3, 'absoluteMinMax', -8, 'bwr', 'rgb(15, 89,169)'),
    (3, 'absoluteMinMax', -8, 'bwr2', 'rgb(0, 0,255)'),
    (3, 'absoluteMinMax', -8, 'rbg', 'rgb(0, 255,0)'),
    (3, 'absoluteMinMax', 0, 'bwr', 'rgb(232, 232,232)'),
    (3, 'absoluteMinMax', 0, 'bwr2', 'rgb(255, 255,255)'),
    (3, 'absoluteMinMax', 0, 'rbg', 'rgb(0, 0,0)'),
    (3, 'absoluteMinMax', 8, 'bwr', 'rgb(165, 31,30)'),
    (3, 'absoluteMinMax', 8, 'bwr2', 'rgb(255, 0,0)'),
    (3, 'absoluteMinMax', 8, 'rbg', 'rgb(255, 0,0)'),
    (3, 'p10p90', -8, 'bwr', 'rgb(0, 51,114)'),
    (3, 'p10p90', -8, 'bwr2', 'rgb(0, 128,255)'),
    (3, 'p10p90', 0, 'bwr', 'rgb(232, 232,232)'),
    (3, 'p10p90', 0, 'bwr2', 'rgb(255, 255,255)'),
    (3, 'p10p90', 0, 'rbg', 'rgb(0, 0,0)'),
    (3, 'p10p90', 8, 'bwr', 'rgb(109, 0,0)'),
    (3, 'p10p90', 8, 'bwr2', 'rgb(255, 128,0)'),
]

SUMMARIES_BEFORE_THE_CLAMP = [
    [0, 0, 0.79, 0.98, None, None, None, 1.04, 1.41],
    [0, 0, -1.27, -1.03, None, None, None, 0.45, 0.56],
    [0, 0, 1.93, 8.5, None, None, None, 14.7, 20.93],
    [0, 0, -8, -5, None, None, None, 5, 8],
]


class LegitimateColoursAreUnchangedTest(unittest.TestCase):
    """The half that must NOT move.

    A clamp that quietly altered ordinary colours would repaint every diagram
    in the application -- a far worse outcome than the defect it fixes. So
    every colour the previous implementation produced, for the cases where it
    produced a colour at all, is recorded above and required to still hold.

    Cases where the old answer was NOT a colour are deliberately absent: those
    are exactly what changed, on purpose. So is the `bwr` column, once -- see
    the note on the table.
    """

    def test_every_previously_valid_colour_is_unchanged(self):
        script = (
            "const summaries = " + json.dumps(SUMMARIES_BEFORE_THE_CLAMP) + ";\n"
            "const want = " + json.dumps(COLOURS_BEFORE_THE_CLAMP) + ";\n"
            "const diffs = [];\n"
            "for (const row of want) {\n"
            "  const lim = getMinMax(summaries[row[0]], row[1]);\n"
            "  const got = getColor(lim, row[2], row[3]);\n"
            "  if (got !== row[4]) diffs.push({summary: row[0], option: row[1],\n"
            "      value: row[2], scale: row[3], expected: row[4], got: got});\n"
            "}\n"
            "process.stdout.write(JSON.stringify("
            "{checked: want.length, diffs: diffs.slice(0, 8)}));"
        )
        result = run_in_node(script)

        self.assertEqual(result["diffs"], [],
                         "a colour that was already valid has changed")
        self.assertEqual(result["checked"], len(COLOURS_BEFORE_THE_CLAMP))
        self.assertGreater(result["checked"], 40, "the table is suspiciously small")


class TheDivergingRampTest(unittest.TestCase):
    """What the ramp has to be, stated as behaviour rather than as hex codes.

    Both of these are regressions with a face: the first is why every heatmap
    in the application carried a black grid, and the second is the solid black
    colour legend beside the metabolite hub heatmaps.
    """

    LIMITS = {"min": -8, "max": 8, "absMin": -8, "absMax": 8}

    def _colour(self, value, scale="bwr"):
        return run_in_node("""
            process.stdout.write(JSON.stringify(getColor(%s, %s, %s)));
        """ % (json.dumps(self.LIMITS), json.dumps(value),
               "undefined" if scale is None else json.dumps(scale)))

    @staticmethod
    def _channels(colour):
        return [int(part) for part in re.findall(r"\d+", colour)]

    def test_the_midpoint_is_a_cell_and_not_a_hole(self):
        """Zero must be distinguishable from the white panel behind it.

        `rgb(255,255,255)` on a white card is not a pale cell, it is the
        absence of one, and it is the entire reason the heatmaps drew a 0.5px
        black border around every cell: the outline was doing the work the fill
        could not. With a toned neutral the grid is not load-bearing any more
        and generateHeatmap can separate cells with a transparent gap instead.
        """
        channels = self._channels(self._colour(0))
        self.assertTrue(all(c < 250 for c in channels),
                        "the midpoint is white again, so a value of zero is "
                        "invisible on a white panel: %s" % channels)
        # ...but still clearly the PALE end, not a grey that competes with data.
        self.assertTrue(all(c > 200 for c in channels),
                        "the midpoint has drifted dark enough to out-weigh "
                        "small real changes: %s" % channels)

    def test_the_midpoint_is_neutral_and_takes_no_side(self):
        """A tinted midpoint would nudge every zero toward one of the poles."""
        channels = self._channels(self._colour(0))
        self.assertEqual(max(channels) - min(channels), 0,
                         "the midpoint leans toward one pole: %s" % channels)

    def test_an_unknown_scale_paints_the_default_ramp_not_black(self):
        """The black colour-scale bar, pinned.

        getColor's unknown-scale branch left red, green and blue undefined and
        fell through to the shared return, where paChannel turned every NaN
        into 0. Callers that pass a scale they were never given -- which is
        what the hub panel did, because it read a network options object that
        has no colorScale on it -- got rgb(0,0,0) for every single value, and
        the legend rendered as a solid black strip beside correctly coloured
        cells.
        """
        self.assertEqual(self._colour(8, scale=None), self._colour(8, "bwr"))
        self.assertEqual(self._colour(-8, scale=None), self._colour(-8, "bwr"))
        self.assertNotEqual(self._colour(8, scale=None), "rgb(0, 0,0)")

    def test_a_shipped_file_contains_no_debugger_statement(self):
        """Neither fall-through may stop the application for a reader.

        getColor and getMinMax both ended their unknown-input branch with
        `debugger;`. With devtools open that is a breakpoint, and both branches
        run once per cell -- a legend alone hit one of them 25 times.
        """
        source = read_source()
        self.assertNotIn("\n\t\t\t\tdebugger;", source)
        self.assertIsNone(re.search(r"^\s*debugger\s*;", source, re.MULTILINE),
                          "a debugger statement is back in PA_Step3Views.js")

    def test_lightness_rises_without_a_single_step_backwards(self):
        """Monotone lightness is what a colour-blind reader is left with.

        If the ramp ever gets lighter as a value moves further from zero, the
        one channel of information that survives total colour blindness is
        reporting the opposite of the data.
        """
        result = run_in_node("""
            const limits = %s;
            const luma = v => {
              const c = getColor(limits, v, "bwr").match(/\\d+/g).map(Number);
              return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
            };
            const up = [], down = [];
            for (let i = 0; i <= 32; i++) { up.push(luma(i / 4)); down.push(luma(-i / 4)); }
            process.stdout.write(JSON.stringify({up: up, down: down}));
        """ % json.dumps(self.LIMITS))

        for side in ("up", "down"):
            series = result[side]
            for index in range(1, len(series)):
                self.assertLessEqual(
                    round(series[index], 6), round(series[index - 1], 6),
                    "%s side gets lighter between step %d and %d"
                    % (side, index - 1, index))


if __name__ == "__main__":
    unittest.main(verbosity=2)
