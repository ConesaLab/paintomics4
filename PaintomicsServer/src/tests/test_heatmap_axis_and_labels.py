#***************************************************************
#  Guards for the step 3 / step 4 heatmap and line-chart labelling.
#
#  There is no JS test runner in this repo, so these tests do two things:
#
#   1. Static guards over PA_Step3Views.js / PA_Step4Views.js, pinning the
#      properties that were regressions the last time round: the hardcoded
#      "Timepoint n" x axis with its labels switched off, head-first
#      truncation that discards the discriminating tail of an identifier, and
#      a row label that pairs a gene symbol with another gene's identifier.
#
#   2. Behavioural tests of the shared helpers themselves, by extracting the
#      helper block out of PA_Step3Views.js and running it under node. The
#      helpers are pure functions of their arguments, so they can be exercised
#      without a browser, a chart library or a job.
#
#  Run with:
#    cd <repo root> && PYTHONPATH=PaintomicsServer \
#      python3 PaintomicsServer/src/tests/test_heatmap_axis_and_labels.py
#***************************************************************

import json
import os
import re
import shutil
import subprocess
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
VIEWS_DIR = os.path.join(REPO_ROOT, "PaintomicsClient", "public_html", "app",
                         "view", "PathwayAcquisitionViews")
STEP3 = os.path.join(VIEWS_DIR, "PA_Step3Views.js")
STEP4 = os.path.join(VIEWS_DIR, "PA_Step4Views.js")

HELPER_START = "/* ====================================================================="
HELPER_END = "var renderFunctionLimit = function"

NODE = shutil.which("node")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def strip_comments(source):
    """
    Drops /* */ and // comments so a grep for a defect pattern cannot be
    satisfied (or defeated) by a comment that merely *describes* the defect -
    every one of these guards has a comment next to it explaining the old
    behaviour, and those comments quote it verbatim.
    """
    # Line comments FIRST. These files are full of "//*****" banner rules, and
    # a block-comment pass run before them sees the "/*" one character in and
    # swallows everything up to the next "*/" - 16k characters of real code in
    # PA_Step4Views.js, which would make these guards pass on a file that still
    # contains the defect.
    source = re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return source


class HeatmapAxisStaticGuards(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.step3 = read(STEP3)
        cls.step4 = read(STEP4)
        cls.step3_code = strip_comments(cls.step3)
        cls.step4_code = strip_comments(cls.step4)

    def test_no_hardcoded_timepoint_placeholder(self):
        """The seven charts must label their columns from the omic header."""
        for name, code in (("PA_Step3Views.js", self.step3_code),
                           ("PA_Step4Views.js", self.step4_code)):
            self.assertNotIn('"Timepoint " + (i + 1)', code,
                             name + " still pushes the positional x-axis placeholder")

    def test_no_categorised_axis_with_labels_disabled(self):
        """
        A `categories` list on an axis whose labels are off is the exact shape
        of the defect: the names are computed and then not drawn.
        """
        pattern = re.compile(r"categories:\s*xAxisCat[^}]*labels:\s*\{\s*enabled:\s*false")
        for name, code in (("PA_Step3Views.js", self.step3_code),
                           ("PA_Step4Views.js", self.step4_code)):
            self.assertIsNone(pattern.search(code),
                              name + " still builds x-axis categories and hides them")

    def test_every_condition_axis_goes_through_the_shared_helper(self):
        """DRY: one helper, not seven copies (project mandate)."""
        self.assertEqual(1, self.step3_code.count("var paConditionAxis = function"),
                         "paConditionAxis must be defined exactly once, in PA_Step3Views.js")
        self.assertNotIn("paConditionAxis = function", self.step4_code,
                         "PA_Step4Views.js must reuse the helper, not redefine it")

        # The definition reads "paConditionAxis = function (" and so is not
        # counted here; only call sites are.
        calls = self.step3_code.count("paConditionAxis(") + self.step4_code.count("paConditionAxis(")
        self.assertEqual(7, calls,
                         "expected the seven placeholder sites to call paConditionAxis, found %d" % calls)

    def test_shared_helpers_are_defined_once(self):
        for helper in ("paTruncateTail", "paRowLabel", "paColorLegend",
                       "paOmicHeaders", "paSharedOmicHeader", "paJobModel",
                       "paEscapeAttribute", "paFeatureRowName"):
            self.assertEqual(1, self.step3_code.count("var %s = function" % helper),
                             helper + " must be defined exactly once, in PA_Step3Views.js")
            self.assertNotIn("%s = function" % helper, self.step4_code,
                             helper + " must not be redefined in PA_Step4Views.js")

    def test_no_head_first_truncation_left_in_row_labels(self):
        """
        T4d: "5 head + 4 tail" and "first 14" both keep the shared prefix of an
        accession and throw away the digits that tell rows apart.
        """
        forbidden = [
            "substring(0, 5) + \"...\"",
            "substring(0, 10) + \"...\"",
            "substring(0, 14) + \"...\"",
            "substring(0, 12) + '...'",
            "substring(0, 20) + '...'",
        ]
        for name, code in (("PA_Step3Views.js", self.step3_code),
                           ("PA_Step4Views.js", self.step4_code)):
            for pattern in forbidden:
                self.assertNotIn(pattern, code,
                                 name + " still truncates from the head: " + pattern)

    def test_row_labels_carry_the_untruncated_value(self):
        """A truncated label must stay recoverable without hovering a cell."""
        self.assertIn('title="\' + paEscapeAttribute(fullText)', self.step3_code,
                      "paRowLabel must put the full name in a title attribute")

    def test_global_heatmap_row_carries_the_kegg_gene_id(self):
        """
        V3-2: the symbol alone does not identify the row - one uploaded
        identifier can map to several KEGG genes.
        """
        self.assertIn("var featureName = paFeatureRowName(omicsValues[matchedFeatures[i]]);",
                      self.step4_code)
        # ...and the row label must be that disambiguated name, not the bare symbol.
        self.assertIn("keggName: featureName,", self.step4_code)
        self.assertNotIn("keggName: targetName,", self.step4_code)

    def test_regulator_branch_is_not_corrupted(self):
        """
        The regulator row still swaps the sides: the regulator is the primary
        identifier and the target the secondary one.
        """
        self.assertIn("keggName: omicValue.originalName,", self.step4_code)
        self.assertIn("inputName: targetName,", self.step4_code)
        # Its linkKey must agree with what the other rows' labels now yield,
        # or cross-heatmap hover highlighting silently stops matching.
        self.assertIn("linkKey: featureName,", self.step4_code)
        self.assertNotIn("linkKey: targetName,", self.step4_code)

    def test_data_matrix_key_round_trips_through_the_axis_label(self):
        """
        generateContent() recovers the data-matrix key by parsing the reference
        heatmap's y-axis labels. Relevance markers are written "* ", so without
        the trim() the key keeps a leading space and never matches.
        """
        self.assertIn('orderedGenes[i].split("#")[0].replace(/[\\*\\^]/g, "").trim()', self.step4_code)

    def test_colour_legend_is_rendered(self):
        self.assertIn("var paColorLegend = function", self.step3_code)
        self.assertGreaterEqual(self.step4_code.count("paColorLegend("), 2,
                                "expected a colour legend on the global heatmap and the details view")

    @unittest.skipIf(NODE is None, "node is not available")
    def test_both_view_files_parse(self):
        """A syntax error in either file takes the whole client down."""
        for path in (STEP3, STEP4):
            result = subprocess.run([NODE, "--check", path],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(0, result.returncode,
                             path + " does not parse:\n" + result.stdout.decode("utf-8", "replace"))


@unittest.skipIf(NODE is None, "node is not available")
class HeatmapLabelHelperBehaviour(unittest.TestCase):
    """
    Runs the extracted helper block under node and checks what it actually
    produces. The helpers are pure, so no DOM, chart library or job is needed;
    only getColor() (which paColorLegend samples) has to be supplied, and it is
    taken verbatim from the same file.
    """

    @classmethod
    def setUpClass(cls):
        source = read(STEP3)

        start = source.index(HELPER_START)
        end = source.index(HELPER_END)
        cls.helpers = source[start:end]

        color_start = source.index("var getColor = function")
        color_end = source.index("var renderFunctionLimit = function")
        cls.get_color = source[color_start:source.index("};", color_start) + 2]

        cls.prelude = (
            "var Date_logFormat = function () { return ''; };\n"
            "Date.logFormat = Date_logFormat;\n"
            "var console_error = console.error; console.error = function () {};\n"
            + cls.get_color + "\n" + cls.helpers + "\n"
        )

    def evaluate(self, expression):
        script = self.prelude + "process.stdout.write(JSON.stringify(" + expression + "));"
        result = subprocess.run([NODE, "-e", script],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(0, result.returncode,
                         "node failed: " + result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout.decode("utf-8"))

    # --- paConditionAxis -------------------------------------------------

    def test_axis_uses_the_real_condition_names(self):
        header = ["#geneID", "T00h", "T02h", "T06h", "T12h", "T18h", "T24h"]
        axis = self.evaluate("paConditionAxis(6, %s, {})" % json.dumps(header))
        self.assertEqual(["T00h", "T02h", "T06h", "T12h", "T18h", "T24h"], axis["categories"])

    def test_axis_labels_are_enabled_and_rotated(self):
        axis = self.evaluate("paConditionAxis(3, ['#id','a','b','c'], {})")
        self.assertTrue(axis["labels"]["enabled"],
                        "enabling the labels is half the fix; leaving them off is the defect")
        self.assertNotEqual(0, axis["labels"]["rotation"],
                            "at ~21px per column horizontal labels overlap - rotation must land "
                            "together with enabling them")
        self.assertEqual(1, axis["labels"]["step"],
                         "Highcharts must not thin the labels out; a dropped label looks like no label")

    def test_axis_falls_back_to_positional_labels_without_a_header(self):
        """An older cached job model carries no headers; it must not go blank."""
        axis = self.evaluate("paConditionAxis(2, null, {})")
        self.assertEqual(["Condition 1", "Condition 2"], axis["categories"])

        axis = self.evaluate("paConditionAxis(2, ['#id'], {})")
        self.assertEqual(["Condition 1", "Condition 2"], axis["categories"])

    def test_axis_labels_are_length_capped(self):
        long_name = "Wild_type_untreated_replicate_1"
        rendered = self.evaluate(
            "paConditionAxis(1, ['#id', %s], {maxChars: 10}).labels.formatter.call({value: %s})"
            % (json.dumps(long_name), json.dumps(long_name)))
        self.assertLessEqual(len(rendered), 10)
        self.assertTrue(rendered.endswith("replicate_1"[-(len(rendered) - 1):]),
                        "the cap must keep the end of the name, got " + rendered)

    # --- paTruncateTail --------------------------------------------------

    def test_truncation_keeps_the_discriminating_tail(self):
        first = self.evaluate("paTruncateTail('ENSMUSG00000036438', 12)")
        second = self.evaluate("paTruncateTail('ENSMUSG00000019370', 12)")
        self.assertNotEqual(first, second,
                            "two distinct Ensembl ids must not render identically")
        self.assertTrue(first.endswith("036438"))

    def test_truncation_keeps_the_relevance_marker(self):
        rendered = self.evaluate("paTruncateTail('* ENSMUSG00000036438', 12)")
        self.assertTrue(rendered.startswith("* "),
                        "front-ellipsising must not eat the significance marker, got " + rendered)

    def test_short_values_are_untouched(self):
        self.assertEqual("Calm1", self.evaluate("paTruncateTail('Calm1', 14)"))

    # --- paRowLabel ------------------------------------------------------

    def test_row_label_shows_symbol_with_kegg_id_and_full_title(self):
        label = self.evaluate("paRowLabel('Calm1 (12313)', 'ENSMUSG00000036438', {width: 90, maxChars: 14})")
        self.assertIn("Calm1 (12313)", label)
        self.assertIn('title="Calm1 (12313)  |  ENSMUSG00000036438"', label)

    def test_row_label_leaves_regulator_markup_intact(self):
        primary = 'WRKY40<br><span class="x">AT2G25000</span>'
        label = self.evaluate("paRowLabel(%s, 'NAC001', {})" % json.dumps(primary))
        self.assertIn(primary, label,
                      "character slicing would cut a tag in half on regulator rows")

    def test_row_label_escapes_the_title_attribute(self):
        label = self.evaluate("paRowLabel('a\"b', 'c', {})")
        self.assertNotIn('title="a"b"', label)
        self.assertIn("&quot;", label)

    # --- paFeatureRowName ------------------------------------------------

    def test_feature_row_name_disambiguates_two_genes_sharing_an_identifier(self):
        """
        V3-2, measured: ENSMUSG00000036438 maps to Calm2/12314 AND Calm1/12313,
        so two rows carried the same identifier under different symbols and a
        reader could not tell which KEGG gene either row was.
        """
        calm2 = "{getName: function(){return 'Calm2';}, getID: function(){return '12314';}}"
        calm1 = "{getName: function(){return 'Calm1';}, getID: function(){return '12313';}}"
        self.assertEqual("Calm2 (12314)", self.evaluate("paFeatureRowName(%s)" % calm2))
        self.assertEqual("Calm1 (12313)", self.evaluate("paFeatureRowName(%s)" % calm1))

    def test_feature_row_name_does_not_repeat_itself(self):
        """Metagenes and unmapped features use the id as their name."""
        same = "{getName: function(){return 'Metagene_1';}, getID: function(){return 'Metagene_1';}}"
        self.assertEqual("Metagene_1", self.evaluate("paFeatureRowName(%s)" % same))

        noid = "{getName: function(){return 'Calm1';}, getID: function(){return '';}}"
        self.assertEqual("Calm1", self.evaluate("paFeatureRowName(%s)" % noid))
        self.assertEqual("", self.evaluate("paFeatureRowName(null)"))

    # --- paColorLegend ---------------------------------------------------

    def test_colour_legend_samples_the_painting_scale(self):
        legend = self.evaluate(
            "paColorLegend({min: -2, max: 2, absMin: -4, absMax: 4}, 'bwr', {})")
        self.assertIn("linear-gradient", legend)
        self.assertIn("-2.00", legend)
        self.assertIn("2.00", legend)
        self.assertNotIn("NaN", legend)

    def test_colour_legend_refuses_a_degenerate_range(self):
        """One invalid stop voids the whole CSS gradient - draw nothing instead."""
        self.assertEqual("", self.evaluate(
            "paColorLegend({min: 0, max: 0, absMin: 0, absMax: 0}, 'bwr', {})"))
        self.assertEqual("", self.evaluate("paColorLegend(null, 'bwr', {})"))

    # --- paSharedOmicHeader ----------------------------------------------

    def test_shared_header_requires_agreement_between_omics(self):
        model = ("{getOmicHeaders: function () { return {"
                 "'Gene expression': ['#id','T0','T1'],"
                 "'Proteomics': ['#id','T0','T1'],"
                 "'Metabolomics': ['#id','A','B']}; }}")
        agreeing = self.evaluate(
            "paSharedOmicHeader(%s, ['Gene expression','Proteomics'], 2)" % model)
        self.assertEqual(["#id", "T0", "T1"], agreeing)

        disagreeing = self.evaluate(
            "paSharedOmicHeader(%s, ['Gene expression','Metabolomics'], 2)" % model)
        self.assertEqual([], disagreeing,
                         "labelling one omic's columns with another's names is worse than not labelling")

    def test_shared_header_rejects_a_header_that_is_too_short(self):
        model = "{getOmicHeaders: function () { return {'Gene expression': ['#id','T0']}; }}"
        self.assertEqual([], self.evaluate(
            "paSharedOmicHeader(%s, ['Gene expression'], 3)" % model))

    def test_omic_headers_tolerate_a_model_without_them(self):
        self.assertEqual([], self.evaluate("paOmicHeaders(null, 'Gene expression')"))
        self.assertEqual([], self.evaluate("paOmicHeaders({}, 'Gene expression')"))

    # --- the two lines truncate from opposite ends -------------------------
    #
    # Measured on the running app after the row label gained its KEGG gene id:
    # ellipsising both lines from the front turned every symbol into noise --
    # Slc22a3 rendered as "…2a3", Gnai3 as "…ai3", Adcy9 as "…cy9". The
    # identifier still has to lose its front, because every mouse gene shares
    # the "ENSMUSG0000" prefix and only the tail tells two of them apart.

    def test_a_display_name_keeps_its_front(self):
        self.assertEqual("Slc22a3 (20…",
                         self.evaluate("paTruncateHead('Slc22a3 (20497)', 12)"))

    def test_a_display_name_short_enough_is_untouched(self):
        self.assertEqual("Lrp6 (16974)",
                         self.evaluate("paTruncateHead('Lrp6 (16974)', 14)"))

    def test_relevance_markers_survive_head_truncation(self):
        rendered = self.evaluate("paTruncateHead('* Slc22a3 (20497)', 14)")
        self.assertTrue(rendered.startswith("* "), rendered)
        self.assertTrue(rendered.endswith("…"), rendered)

    def test_the_row_label_truncates_its_two_lines_from_opposite_ends(self):
        """The whole point: the name reads forwards, the id reads backwards."""
        rendered = self.evaluate(
            "paRowLabel('Slc22a3 (20497)', 'ENSMUSG00000031766',"
            " {width: 90, maxChars: 12})")
        self.assertIn("Slc22a3 (20…", rendered,
                      "the display name lost its front and now names nothing")
        # maxChars 12 leaves 11 characters after the ellipsis.
        self.assertIn("…00000031766", rendered,
                      "the identifier lost its discriminating tail")

    def test_two_genes_differing_only_late_stay_distinguishable(self):
        """The pair that exposed the original defect."""
        first = self.evaluate(
            "paRowLabel('Calm2 (12314)', 'ENSMUSG00000036438', {maxChars: 12})")
        second = self.evaluate(
            "paRowLabel('Calm1 (12313)', 'ENSMUSG00000019370', {maxChars: 12})")
        self.assertNotEqual(first, second)
        self.assertIn("Calm2 (12314)", first)
        self.assertIn("Calm1 (12313)", second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
