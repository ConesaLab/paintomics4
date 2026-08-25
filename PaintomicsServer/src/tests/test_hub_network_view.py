#!/usr/bin/env python3
"""The hub row shape on the client, and the network view's contract.

hub_result.csv was a headerless 8-column TSV read POSITIONALLY at
PA_Step3Views.js:5786-5794 -- the column order stated in exactly one place on
each side and versioned nowhere, so reordering the R frame would have silently
relabelled the whole grid with no error anywhere.

Rows are named dicts with a schema now. Jobs stored before that are RE-SCORED on
the server rather than translated on the client: they expire in at most 14 days,
and a re-score returns the corrected numbers instead of preserving the wrong
ones. So the client must have exactly one code path, and that is asserted here.

The helper is run in node, the same way test_neighbouring_features_button.py
runs paNeighbourRequest: extract the real function text, evaluate it, assert on
its JSON output.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

CLIENT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))),
    "PaintomicsClient", "public_html")
STEP3_VIEWS = os.path.join(CLIENT, "app", "view", "PathwayAcquisitionViews",
                           "PA_Step3Views.js")
HUB_NETWORK_VIEW = os.path.join(CLIENT, "app", "view",
                                "PathwayAcquisitionViews",
                                "PA_Step3HubNetworkView.js")


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
    with open(STEP3_VIEWS, "r", encoding="utf-8") as handle:
        source = handle.read()
    script = extract(source, "paHubRow") + "\n" + body
    directory = tempfile.mkdtemp(prefix="paintomics-hub-")
    try:
        path = os.path.join(directory, "check.js")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        done = subprocess.run(["node", path], capture_output=True, text=True,
                              timeout=60)
        if done.returncode != 0:
            raise AssertionError("node failed:\n%s" % done.stderr)
        return json.loads(done.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class RecomputesStaleRowsTest(unittest.TestCase):
    """Legacy rows are re-scored on the server, never translated on the client."""

    def test_recovery_rescores_when_the_schema_is_stale(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "servlets",
            "PathwayAcquisitionServlet.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("safe_hubAnalysisResult = ")
        window = source[max(0, start - 1600):start + 200]
        self.assertIn("HUB_SCHEMA_VERSION", window)
        self.assertIn("hubAnalysis()", window)

    def test_client_has_no_legacy_branch(self):
        with open(STEP3_VIEWS, "r", encoding="utf-8") as handle:
            body = handle.read()
        start = body.index("var paHubRow")
        window = body[start:start + 1200]
        self.assertNotIn("Array.isArray", window)
        self.assertNotIn("[0]", window)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class HubRowTest(unittest.TestCase):
    def test_schema_2_dict_row_is_normalised(self):
        out = run_in_node(
            'console.log(JSON.stringify(paHubRow({schema:2,name:"C00042",'
            'step:1,density:0.25,percentile:0.5425,pvalue:0.9393,'
            'pvalue_adjust:1,DEN:1,noDEN:3,ball_size:4,ball_fraction:0.01})));')
        self.assertEqual(out["ID"], "C00042")
        self.assertEqual(out["Step"], 1)
        self.assertEqual(out["DEN"], 1)
        self.assertEqual(out["noDEN"], 3)
        self.assertEqual(out["Percentage"], 0.25)
        self.assertEqual(out["ballFraction"], 0.01)

    def test_ball_fraction_reaches_the_grid(self):
        """It is how a reader sees that radius 4 covers half the network."""
        out = run_in_node(
            'console.log(JSON.stringify(paHubRow({schema:2,name:"C00024",'
            'step:4,density:0.1,percentile:0.5,pvalue:0.5,pvalue_adjust:0.9,'
            'DEN:2,noDEN:18,ball_size:4494,ball_fraction:0.469})));')
        self.assertAlmostEqual(out["ballFraction"], 0.469)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class SyntaxTest(unittest.TestCase):
    def test_step3_views_parses(self):
        done = subprocess.run(["node", "--check", STEP3_VIEWS],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_new_view_parses(self):
        if not os.path.exists(HUB_NETWORK_VIEW):
            self.skipTest("view not written yet (Task 8)")
        done = subprocess.run(["node", "--check", HUB_NETWORK_VIEW],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)



@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class HubNetworkViewContractTest(unittest.TestCase):
    """The design decisions that are easy to undo by accident."""

    def source(self):
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            return handle.read()

    def code(self):
        """Source with comments stripped.

        The "must not appear" assertions below are about CODE. This file's
        comments deliberately NAME the APIs it avoids -- requestAnimationFrame
        and svg.js's .path() -- to record why, and matching those explanations
        would fail the very tests that document them.
        """
        body = re.sub(r"/\*.*?\*/", "", self.source(), flags=re.S)
        return re.sub(r"(?m)^\s*//.*$", "", body)

    def test_uses_defer_frame_not_raf(self):
        """rAF never fires in a background tab; the panel came up blank."""
        self.assertIn("paDeferFrame", self.source())
        self.assertNotIn("requestAnimationFrame", self.code())

    def test_destroys_cytoscape_on_teardown(self):
        body = self.source()
        self.assertIn("beforedestroy", body)
        self.assertIn("cy.destroy()", body)

    def test_announces_what_was_not_drawn(self):
        """A cap must never read as "this is all there is".

        The first version hardcoded "Showing the 400 edges closest to X" while
        rings 3 and 4 were missing entirely -- true, and useless. The server
        budgets per ring now and reports shown/total, so the panel says
        "step 3 showing 40 of 461".
        """
        body = self.source()
        self.assertIn("payload.rings", body)
        self.assertIn("r.shown < r.total", body)
        # comment-stripped: the docblock names the old string to record it
        self.assertNotIn("400 edges closest", self.code())

    def test_ring_labels_carry_the_sample_size(self):
        self.assertIn('info.shown < info.total', self.source())

    def test_state_is_read_through_the_omicvalue_accessors(self):
        """entry.relevant is an ARRAY after OmicValue.loadFromJSON, and [] is
        truthy -- testing the property directly made "measured but not DE"
        unreachable and painted every measured feature up or down."""
        body = self.code()
        self.assertIn("entry.isRelevant()", body)
        self.assertIn("entry.isRelevantAssociation()", body)
        self.assertNotIn("entry.relevant ||", body)

    def test_a_node_click_opens_a_heatmap(self):
        body = self.source()
        self.assertIn('cy.on("tap", "node"', body)
        self.assertIn("generateHeatmap(", body)
        self.assertIn("generatePlot(", body)

    def test_heatmap_and_plot_divs_are_adjacent_siblings(self):
        """The heatmap's point handlers reach the plot with
        .parent().next().highcharts(); anything between them makes that
        undefined and hovering a cell throws."""
        body = self.source()
        heat = body.index("PA_step5_heatmapContainer")
        plot = body.index("PA_step5_plotContainer")
        self.assertLess(heat, plot)
        between = body[heat:plot]
        self.assertNotIn("<h3", between)
        self.assertNotIn("paColorLegend", between)

    def test_charts_are_destroyed_before_redraw(self):
        """Highcharts appends and neither primitive clears its container;
        emptying the div alone orphans every resize and tooltip listener."""
        body = self.source()
        self.assertIn("chart.destroy()", body)
        self.assertIn("this.charts = []", body)

    def test_omic_name_is_derived_not_hardcoded(self):
        """The old handler hardcoded "Gene expression" / "Metabolomics", so
        every other omic silently drew nothing."""
        body = self.code()
        self.assertIn("getGeneBasedInputOmics()", body)
        self.assertIn("getCompoundBasedInputOmics()", body)
        self.assertNotIn('"Metabolomics"', body)

    def test_unmeasured_node_explains_itself(self):
        body = self.source()
        self.assertIn("paEmptyNote", body)
        self.assertIn("connectedEdges()", body)

    def test_click_highlight_does_not_fight_the_dim_class(self):
        """setLevel owns .dim; a click highlight needs its own class."""
        self.assertIn('"picked"', self.source())

    def test_the_heading_is_an_h2_in_the_body(self):
        """paTocSections() queries h2 only, so an Ext panel header never
        reaches the contents rail."""
        body = self.source()
        self.assertIn("<h2 id=", body)
        self.assertNotIn('title: "Metabolite neighbourhood"', body)

    def test_the_panel_is_a_contentbox_with_a_margin(self):
        body = self.source()
        self.assertIn('cls: "contentbox pa-hub-net"', body)
        self.assertIn('margin: "10 10 10 10"', body)

    def test_the_list_replaces_the_grid(self):
        body = self.source()
        self.assertIn("pa-hub-item", body)
        self.assertIn("buildList", body)
        self.assertIn("SORTS", body)

    def test_refuses_arrows_from_the_legacy_source(self):
        """The legacy fallback carries no subtypes; direction would be invented."""
        self.assertIn("legacy-json", self.source())

    def test_hop_distance_is_not_encoded_as_colour(self):
        """Rings already carry distance; spending hue on it too would leave
        nothing for DE direction, which is what the panel exists to show."""
        body = self.source()
        self.assertIn("node[state = 'up']", body)
        self.assertIn("node[state = 'down']", body)
        self.assertNotIn('"background-color": "data(step)"', body)

    def test_uses_the_validated_palette(self):
        """CVD dE 21.6 / normal-vision 32.3, checked with the palette validator.
        A casual colour edit should have to come past this test."""
        body = self.source()
        self.assertIn("#e34948", body)
        self.assertIn("#2a78d6", body)

    def test_labels_are_selective(self):
        """Radius 4 can reach thousands of nodes; a label on each is unreadable."""
        self.assertIn("showLabel", self.source())

    def test_has_a_legend_and_a_hover_layer(self):
        body = self.source()
        self.assertIn("pa-hub-legend", body)
        self.assertIn("mouseover", body)

    def test_ring_guides_use_createElementNS(self):
        """svg.js 2.0.5's .path() reads pathSegList, removed in Chrome 48 --
        which is why no diagram here had ever carried a vector primitive."""
        self.assertIn("createElementNS", self.source())
        self.assertNotIn(".path(", self.code())


class RegistrationTest(unittest.TestCase):
    def test_view_is_registered_in_index_html(self):
        path = os.path.join(CLIENT, "index.html")
        with open(path, "r", encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("PA_Step3HubNetworkView.js", body)

    def test_toolbar_joins_the_shared_stylesheet(self):
        path = os.path.join(CLIENT, "resources", "css", "network-views.css")
        with open(path, "r", encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn(".pa-hub-net-toolbar", body)
        self.assertIn(".pa-net-notice", body)
        self.assertIn(".pa-hub-ring", body)

    def test_step3_mounts_and_feeds_the_view(self):
        with open(STEP3_VIEWS, "r", encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("new PA_Step3HubNetworkView()", body)
        self.assertIn("hubNetworkView.getComponent()", body)

    def test_the_old_grid_is_no_longer_mounted(self):
        """The nine-column table is replaced, not merely supplemented."""
        with open(STEP3_VIEWS, "r", encoding="utf-8") as handle:
            body = handle.read()
        self.assertNotIn("me.hubAnalysisView.getComponent()", body)

    def test_url_constant_exists(self):
        path = os.path.join(CLIENT, "resources", "ServerConfiguration.js")
        with open(path, "r", encoding="utf-8") as handle:
            self.assertIn("SERVER_URL_PA_HUB_SUBGRAPH", handle.read())


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
