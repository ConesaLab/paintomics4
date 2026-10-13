#***************************************************************
#  Guards for the global heatmap's Download button (PNG / SVG figure).
#
#  A user asked for it: they download the painted diagram for their reports
#  and had to screenshot the heatmap, which only takes what fits on the
#  screen. The button had been in the markup for years, commented out, over
#  a download() that threw "Not implemented".
#
#  Two kinds of test, as in test_heatmap_axis_and_labels.py:
#
#   1. Static guards over PA_Step4Views.js: the button is live, it offers
#      both formats, and download() no longer throws.
#
#   2. Behaviour of the pure half of the export, paHeatmapFigureSVG() and
#      its helpers, extracted from PA_Step3Views.js and run under node. The
#      DOM-reading half (paCollectHeatmapFigure) needs a browser and a drawn
#      chart; it was verified in Chrome on a five-omic job. What is checked
#      here is that whatever it collects becomes a well-formed, standalone
#      SVG -- the property that decides whether the file opens at all.
#
#  Run with:
#    cd <repo root> && PYTHONPATH=PaintomicsServer \
#      python3 PaintomicsServer/src/tests/test_heatmap_figure_export.py
#***************************************************************

import json
import os
import re
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ElementTree

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
VIEWS_DIR = os.path.join(REPO_ROOT, "PaintomicsClient", "public_html", "app",
                         "view", "PathwayAcquisitionViews")
STEP3 = os.path.join(VIEWS_DIR, "PA_Step3Views.js")
STEP4 = os.path.join(VIEWS_DIR, "PA_Step4Views.js")

EXPORT_START = "/* =====================================================================\n * Heatmap figure export"
EXPORT_END = "var renderFunctionLimit = function"

SVG_NS = "{http://www.w3.org/2000/svg}"

NODE = shutil.which("node")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def strip_comments(source):
    # Line comments first: a "//*****" banner seen by the block pass would
    # swallow real code up to the next "*/" (see test_heatmap_axis_and_labels).
    source = re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return source


def global_heatmap_view(code):
    """The PA_Step4GlobalHeatmapView constructor's body, comments removed."""
    start = code.index("function PA_Step4GlobalHeatmapView()")
    end = code.index("\nfunction ", start + 1)
    return code[start:end]


class DownloadButtonIsWired(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.view = global_heatmap_view(strip_comments(read(STEP4)))

    def test_the_button_is_in_the_panel_header(self):
        self.assertIn('id="downloadHeatmapButton"', self.view,
                      "the Download button is missing (or commented out again)")

    def test_the_button_is_labelled_not_icon_only(self):
        """It sits next to the diagram's labelled Download; an icon alone is how it went unfound."""
        button = re.search(r'<a [^>]*id="downloadHeatmapButton"[^>]*>(.*?)</a>', self.view)
        self.assertIsNotNone(button)
        self.assertIn("Download", button.group(1))
        self.assertIn("downloadTool", button.group(0))

    def test_download_no_longer_throws(self):
        self.assertNotIn("Not implemented", self.view)

    def test_both_formats_are_offered(self):
        self.assertIn('me.download("png")', self.view)
        self.assertIn('me.download("svg")', self.view)

    def test_the_button_opens_the_menu(self):
        handler = re.search(r'\$\("#downloadHeatmapButton"\)\.click\(function\(\) \{(.*?)\}\);', self.view, re.DOTALL)
        self.assertIsNotNone(handler)
        self.assertIn("showDownloadMenu", handler.group(1))

    def test_the_tooltip_is_closed_before_the_menu_opens(self):
        """Left open, the interactive tooltip covers the PNG item and takes its click."""
        menu = self.view[self.view.index("this.showDownloadMenu"):]
        self.assertLess(menu.index('tooltipster("close")'), menu.index(".showBy("))

    def test_the_menu_is_destroyed_with_the_panel(self):
        destroy = self.view[self.view.index("beforedestroy"):]
        self.assertIn("me.downloadMenu.destroy()", destroy[:400])

    def test_a_png_too_large_for_1x_is_refused_before_drawing(self):
        """paFigureScale answers 0 below screen size; the view must check it
        before the spinner goes up, not hand 0 to the rasteriser."""
        download = self.view[self.view.index("this.download = function"):self.view.index("this.showDownloadMenu")]
        self.assertIn("scale === 0", download)
        self.assertLess(download.index("scale === 0"), download.index("showInfoMessage"))


class CollectorGuards(unittest.TestCase):
    """The DOM-reading half needs a browser; these pin the review fixes in it."""

    @classmethod
    def setUpClass(cls):
        code = strip_comments(read(STEP3))
        start = code.index("var paCollectHeatmapFigure = function")
        cls.collector = code[start:code.index("var paRasteriseSVG = function", start)]
        start = code.index("var paRasteriseSVG = function")
        cls.rasterise = code[start:code.index("var paSaveBlob = function", start)]

    def test_the_hover_outline_is_dropped_from_the_clone(self):
        """Nothing hides the row outline when the pointer leaves, so it is
        tagged on the live chart and removed from the copy."""
        self.assertIn("chart.heatmapSelector.element", self.collector)
        self.assertIn("[data-pa-drop]", self.collector)
        self.assertIn('removeAttribute("data-pa-drop")', self.collector)

    def test_full_condition_names_only_where_nothing_is_stacked_below(self):
        self.assertIn("nextElementSibling", self.collector)
        self.assertIn("!stacked", self.collector)

    def test_the_serialised_charts_are_stripped_of_illegal_xml_characters(self):
        self.assertIn(".replace(PA_XML_ILLEGAL", self.collector)

    def test_a_failure_while_drawing_still_reaches_the_caller(self):
        """The caller's spinner is cleared only by the callback."""
        self.assertRegex(self.rasterise, r"catch \(error\) \{[^}]*callback\(null\)")


@unittest.skipIf(NODE is None, "node is not available")
class FigureSerialisation(unittest.TestCase):
    """paHeatmapFigureSVG and its helpers, run under node."""

    @classmethod
    def setUpClass(cls):
        source = read(STEP3)
        start = source.index(EXPORT_START)
        end = source.index(EXPORT_END, start)
        escape_start = source.index("var paEscapeAttribute = function")
        escape = source[escape_start:source.index("\n};", escape_start) + 3]
        cls.prelude = escape + "\n" + source[start:end] + "\n"

    def evaluate(self, expression):
        script = self.prelude + "process.stdout.write(JSON.stringify(" + expression + "));"
        result = subprocess.run([NODE, "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(0, result.returncode, "node failed: " + result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout.decode("utf-8"))

    def figure(self, figure):
        built = self.evaluate("paHeatmapFigureSVG(" + json.dumps(figure) + ")")
        # The first thing any consumer does with the file: parse it. A raw
        # "&" or "<" from a pathway or gene name fails right here.
        root = ElementTree.fromstring(built["svg"].encode("utf-8"))
        return built, root

    CHART = ('<svg xmlns="http://www.w3.org/2000/svg" class="highcharts-root" width="370" height="200">'
             '<rect class="highcharts-background" width="370" height="200" fill="#ffffff"/>'
             '<rect class="highcharts-point" x="10" y="10" width="20" height="20" fill="rgb(200,30,30)"/></svg>')

    BASE = {
        "bounds": {"left": 10, "top": 50, "right": 410, "bottom": 350},
        "title": "Glycolysis / Gluconeogenesis",
        "subtitle": "Global heatmap",
        "footer": "Created with PaintOmics AI",
        "items": [
            {"type": "svg", "x": 40, "y": 140, "markup": CHART},
            {"type": "text", "x": 120, "y": 160, "text": "Cacna1b (12287)", "size": 9, "anchor": "end"},
            {"type": "text", "x": 120, "y": 171, "text": "ENSMUSG00000004113", "size": 9, "italic": True,
             "anchor": "end", "fill": "rgb(102,102,102)"},
            {"type": "star", "cx": 50, "cy": 157, "r": 4.5, "fill": "rgb(255, 0, 0)"},
            {"type": "gradient", "x": 10, "y": 60, "width": 160, "height": 12,
             "stops": [{"offset": 0, "color": "rgb(15, 89, 169)"}, {"offset": 100, "color": "rgb(170, 20, 20)"}]},
            {"type": "rect", "x": 90, "y": 58, "width": 1, "height": 16, "fill": "#000000", "opacity": 0.42},
            {"type": "line", "x1": 400, "y1": 50, "x2": 400, "y2": 350, "stroke": "#BABABA", "width": 2, "dash": "4,3"},
        ],
    }

    def test_document_is_well_formed_and_sized(self):
        built, root = self.figure(self.BASE)
        self.assertEqual(SVG_NS + "svg", root.tag)
        self.assertEqual(str(built["width"]), root.get("width"))
        self.assertEqual(str(built["height"]), root.get("height"))
        self.assertEqual("0 0 %d %d" % (built["width"], built["height"]), root.get("viewBox"))
        # 400 x 300 of content, a 16 px margin each side, 46 px of title,
        # 18 px of footer.
        self.assertEqual(400 + 32, built["width"])
        self.assertEqual(300 + 32 + 46 + 18, built["height"])

    def test_the_page_is_white(self):
        _, root = self.figure(self.BASE)
        background = root.find(SVG_NS + "rect")
        self.assertEqual("#FFFFFF", background.get("fill"))
        self.assertEqual(root.get("width"), background.get("width"))

    def test_names_with_markup_characters_survive(self):
        figure = dict(self.BASE, title='A <b> & "C" pathway')
        _, root = self.figure(figure)
        texts = [element.text for element in root.iter(SVG_NS + "text")]
        self.assertIn('A <b> & "C" pathway', texts)

    def test_items_are_moved_into_the_margin(self):
        """Page coordinates in, figure coordinates out: the content group's
        translate puts bounds.left/top at the 16 px margin under the title."""
        _, root = self.figure(self.BASE)
        groups = [g for g in root.findall(SVG_NS + "g") if g.get("transform")]
        self.assertEqual("translate(6,12)", groups[0].get("transform"))  # 16-10, 16+46-50

    def test_the_chart_svg_is_embedded_verbatim(self):
        built, root = self.figure(self.BASE)
        nested = [element for element in root.iter(SVG_NS + "svg") if element is not root]
        self.assertEqual(1, len(nested))
        self.assertEqual("highcharts-root", nested[0].get("class"))
        self.assertIn('<g transform="translate(40,140)"><svg xmlns="http://www.w3.org/2000/svg" class="highcharts-root"',
                      built["svg"])

    def test_right_aligned_labels_keep_their_anchor(self):
        _, root = self.figure(self.BASE)
        label = [t for t in root.iter(SVG_NS + "text") if t.text == "Cacna1b (12287)"][0]
        self.assertEqual("end", label.get("text-anchor"))
        identifier = [t for t in root.iter(SVG_NS + "text") if t.text == "ENSMUSG00000004113"][0]
        self.assertEqual("italic", identifier.get("font-style"))

    def test_no_text_depends_on_a_web_font(self):
        """SourceSansPro is a web font; an SVG drawn as an image cannot load it."""
        _, root = self.figure(self.BASE)
        for text in root.iter(SVG_NS + "text"):
            self.assertIn("Helvetica", text.get("font-family"))
            self.assertNotIn("SourceSansPro", text.get("font-family"))

    def test_the_colour_ramp_is_a_real_gradient(self):
        _, root = self.figure(self.BASE)
        gradient = root.find(".//" + SVG_NS + "linearGradient")
        self.assertIsNotNone(gradient)
        stops = gradient.findall(SVG_NS + "stop")
        self.assertEqual(["0%", "100%"], [stop.get("offset") for stop in stops])
        self.assertEqual("rgb(15, 89, 169)", stops[0].get("stop-color"))
        users = [r for r in root.iter(SVG_NS + "rect") if r.get("fill") == "url(#%s)" % gradient.get("id")]
        self.assertEqual(1, len(users))

    def test_a_long_title_widens_the_page(self):
        figure = dict(self.BASE, title="x" * 200)
        built, _ = self.figure(figure)
        self.assertGreater(built["width"], 200 * 16 * 0.6)

    def test_the_key_names_each_star(self):
        figure = dict(self.BASE, key=[{"fill": "rgb(255, 0, 0)", "text": "Relevant feature"},
                                      {"fill": "#3F3F46", "text": "On a cell: significant in that condition"}])
        built, root = self.figure(figure)
        texts = [t.text for t in root.iter(SVG_NS + "text")]
        self.assertIn("Relevant feature", texts)
        self.assertIn("On a cell: significant in that condition", texts)
        # One star in the items, two in the key.
        self.assertEqual(3, len(list(root.iter(SVG_NS + "polygon"))))
        without_key, _ = self.figure(self.BASE)
        self.assertEqual(without_key["height"] + 18, built["height"])

    def test_an_empty_figure_still_opens(self):
        built, root = self.figure({"bounds": {"left": 0, "top": 0, "right": 0, "bottom": 0}, "items": []})
        self.assertEqual(SVG_NS + "svg", root.tag)
        self.assertEqual(32, built["width"])

    def test_a_star_has_ten_corners_alternating_in_radius(self):
        points = self.evaluate("paStarPoints(10, 10, 4)").split(" ")
        self.assertEqual(10, len(points))
        radii = [round(((float(x) - 10) ** 2 + (float(y) - 10) ** 2) ** 0.5, 2)
                 for x, y in (point.split(",") for point in points)]
        self.assertEqual([4.0, 2.0] * 5, radii)
        self.assertEqual("10.00,6.00", points[0])  # the first point is straight up

    def test_file_names_are_safe(self):
        self.assertEqual("paintomics_heatmap_Glycolysis_Gluconeogenesis_jR0LbyJig2.png",
                         self.evaluate('paFigureFileName("heatmap", "Glycolysis / Gluconeogenesis", "jR0LbyJig2", "png")'))
        self.assertEqual("paintomics_heatmap_Ras_signaling_pathway_ab12.svg",
                         self.evaluate('paFigureFileName("heatmap", "  Ras signaling pathway ", "ab12", "svg")'))
        # A missing pathway name or job id is left out, not written as "undefined".
        self.assertEqual("paintomics_heatmap_ab12.png",
                         self.evaluate('paFigureFileName("heatmap", undefined, "ab12", "png")'))

    def test_png_scale_is_three_unless_the_canvas_cannot_hold_it(self):
        self.assertEqual(3, self.evaluate("paFigureScale(1700, 1400)"))
        # About 600 rows: the area cap decides, and it stays above 1x.
        tall = self.evaluate("paFigureScale(1500, 18000)")
        self.assertLessEqual(1500 * tall * 18000 * tall, 6e7)
        self.assertGreater(tall, 1.4)
        # Chrome's side limit is 32,767 px.
        self.assertLessEqual(self.evaluate("paFigureScale(400, 20000)") * 20000, 32767)
        wide = self.evaluate("paFigureScale(6000, 6000)")
        self.assertLessEqual((6000 * wide) ** 2, 6e7)

    def test_png_scale_never_goes_below_screen_size(self):
        """A scale under 1 shrank 9px labels to 2-5px and still downloaded as
        a success; 0 tells the caller to refuse and offer the SVG."""
        self.assertEqual(0, self.evaluate("paFigureScale(700, 60000)"))
        self.assertEqual(0, self.evaluate("paFigureScale(1500, 45000)"))
        self.assertGreaterEqual(self.evaluate("paFigureScale(1500, 30000)"), 1)

    def test_control_characters_do_not_break_the_document(self):
        """A vertical tab or a DOS end-of-file in a name is legal in a TSV
        and illegal in XML 1.0: one of them made the whole file unparseable."""
        figure = dict(self.BASE, title="Path\u000bway\u001a name")
        figure["items"] = [{"type": "text", "x": 10, "y": 60, "text": "Gene\u0001A", "size": 9}]
        _, root = self.figure(figure)
        texts = [t.text for t in root.iter(SVG_NS + "text")]
        self.assertIn("Pathway name", texts)
        self.assertIn("GeneA", texts)


if __name__ == "__main__":
    unittest.main()
