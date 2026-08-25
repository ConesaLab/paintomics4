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
        every other omic silently drew nothing.

        The name is no longer guessed from the model at all: /pa_hub_feature
        returns the omic each value actually belongs to, so the panel labels
        and scales a row with its own omic rather than with whichever omic
        happened to be first in the job.
        """
        body = self.code()
        self.assertIn("o.omicName", body)
        self.assertNotIn('"Metabolomics"', body)
        self.assertNotIn('"Gene expression"', body)

    def test_every_omic_is_drawn_not_just_the_first(self):
        """globalExpressionData carries omicsValues[0] only, so a job with four
        gene-based omics showed one of them -- and said nothing about the other
        three, while the pathway views on the same page showed all four."""
        body = self.code()
        self.assertIn("SERVER_URL_PA_HUB_FEATURE", body)
        self.assertIn("payload.omics", body)
        self.assertIn("drawable.forEach", body)

    def test_the_feature_fetch_is_cached(self):
        """Re-clicking a node must not re-hit the server."""
        body = self.code()
        self.assertIn("featureCache", body)

    def test_a_late_response_does_not_write_into_a_replaced_card(self):
        """Clicking a second node before the first request lands must not paint
        the first node's heatmap into the second node's card."""
        self.assertIn("document.body.contains(slot)", self.code())

    def test_unmeasured_node_explains_itself(self):
        body = self.code()
        self.assertIn("connectedEdges()", body)
        self.assertIn("How it connects", body)
        self.assertIn("nothing to plot", body)

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


class DetailIsVisibleTest(unittest.TestCase):
    """The card a click opens must be ON SCREEN.

    Measured on job fh304774Lw: the detail rendered its heatmap correctly at
    y=1254 in an 806px viewport -- 448px below the fold, under a 720px canvas.
    It drew, and from the user's seat clicking a node did nothing. Both halves
    of the fix are asserted here because both were needed: the card is a child
    of the stage (so it cannot open below the canvas), and the canvas resizes
    and re-fits when it opens (so the graph is not clipped instead).
    """

    def _view(self):
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            return handle.read()

    def _css(self):
        path = os.path.join(CLIENT, "resources", "css", "network-views.css")
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_the_card_is_inside_the_stage(self):
        """Declared after the stage opens and before the body's flex row ends,
        so it is a flex child of the stage rather than a block after it."""
        body = self._view()
        stage = body.index('class="pa-hub-stage')
        rail = body.index('class="more-net-body"')
        detail = body.index('class="pa-hub-detail"')
        self.assertLess(rail, stage)
        self.assertGreater(detail, stage,
                           "the detail card must be declared inside the stage")

    def test_the_fit_does_not_magnify_a_small_ring(self):
        """fit() scales to fill: a five-node ring came up at 3x with 60px
        labels. Zoom carries no information here -- the rings do."""
        body = self._view()
        start = body.index("this.fitToVisible = function")
        window = body[start:start + 700]
        self.assertIn("MAX_FIT_ZOOM", window)
        self.assertIn("cy.center(", window)

    def test_opening_the_card_resizes_and_refits_the_graph(self):
        body = self._view()
        start = body.index("this.resizeGraph = function")
        window = body[start:start + 700]
        self.assertIn("cy.resize()", window)
        self.assertIn("fitToVisible()", window)

    def test_the_card_has_no_height_transition(self):
        """Measured: with `transition: height`, the flex item resolved to 1px
        and stayed there while Cytoscape resized against the same box. Sized
        with flex-basis instead, it settled immediately."""
        css = self._css()
        start = css.index(".pa-hub-detail {")
        window = css[start:css.index(".pa-hub-detail-body")]
        self.assertNotIn("transition: height", window)
        self.assertIn("flex-basis", css[start:start + 900])

    def test_a_click_scrolls_the_card_into_view_but_the_load_does_not(self):
        """block:"nearest" is a no-op when the card is already visible; the
        panel opening its first metabolite by itself must not scroll the page
        to Step 3's seventh section."""
        body = self._view()
        self.assertIn('scrollIntoView({ block: "nearest" })', body)
        start = body.index("this.selectFirst = function")
        window = body[start:start + 400]
        self.assertNotIn("true", window)


class NoFigureBandTest(unittest.TestCase):
    """The three-tile figure band is gone.

    It spent a quarter of the panel's height on three circled icons and 48px
    numerals, above the list they described. The counts survive as one line of
    text in the rail head.
    """

    def _view(self):
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            body = handle.read()
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        return re.sub(r"(?m)^\s*//.*$", "", body)

    def test_the_stat_tiles_are_gone(self):
        body = self._view()
        self.assertNotIn("po-pathway-stat", body)
        self.assertNotIn("po-band-figure", body)
        self.assertNotIn("renderSummary", body)

    def test_the_counts_survive_as_text(self):
        body = self._view()
        self.assertIn("renderCount", body)
        self.assertIn("with FDR", body)


class StepControlTest(unittest.TestCase):
    """The step control sits with the graph and says which steps are empty.

    It was four toggle buttons in the panel's bottom toolbar -- as far from the
    graph as the layout allows, and silent about which of them had anything to
    show. Most compounds run out well before radius 4, so a pressable button
    that changed nothing was the common case.
    """

    def _view(self):
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_the_bottom_toolbar_is_gone(self):
        self.assertNotIn("bbar:", self._view())

    def test_an_empty_ring_disables_its_chip(self):
        body = self._view()
        start = body.index("this.renderSteps = function")
        window = body[start:start + 1800]
        self.assertIn("total === 0", window)
        self.assertIn("disabled", window)

    def test_the_chip_badge_is_the_ring_and_says_so(self):
        """The chip counts one ring; the step table counts the whole ball.
        Both are on screen at once, so the chip's tooltip has to name which."""
        body = self._view()
        start = body.index("this.renderSteps = function")
        window = body[start:start + 1800]
        self.assertIn("exactly", window)


class SeedSummaryTest(unittest.TestCase):
    """Selecting a metabolite prints its four step scores.

    These four rows per compound are what the removed grid held. Dropping the
    grid without printing them anywhere would have lost information rather than
    clarified it.
    """

    def _view(self):
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_the_step_table_exists(self):
        body = self._view()
        self.assertIn("pa-hub-steptable", body)
        start = body.index("this.showSeedDetail = function")
        window = body[start:start + 2600]
        self.assertIn("[1, 2, 3, 4]", window)
        self.assertIn("row.DEN", window)
        self.assertIn("row.noDEN", window)
        self.assertIn("row.padjust", window)

    def test_a_step_that_was_not_scored_says_so(self):
        body = self._view()
        start = body.index("this.showSeedDetail = function")
        window = body[start:start + 2600]
        self.assertIn("not scored", window)

    def test_the_cumulative_column_is_labelled_as_such(self):
        self.assertIn("Cumulative, and counting only", self._view())


class NamesNotIdsTest(unittest.TestCase):
    """The panel shows names. It showed "C12145" and "225256" everywhere.

    Two different sources, because the data has two: compound names come from
    the server (global-paintomics.kegg_compounds), gene names are already in
    the browser as globalExpressionData's `keggName` -- the SYMBOL the mapper
    resolved (Aanat, Abca1, Krt5).
    """

    def _view(self):
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            body = handle.read()
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        return re.sub(r"(?m)^\s*//.*$", "", body)

    def test_the_name_map_is_fetched_once(self):
        body = self._view()
        self.assertIn("SERVER_URL_PA_HUB_NAMES", body)
        self.assertIn("loadNames", body)

    def test_genes_are_named_from_keggname(self):
        body = self._view()
        start = body.index("this.nameOf = function")
        window = body[start:start + 700]
        self.assertIn("keggName", window)
        self.assertIn("compoundNames", window)

    def test_a_symbol_equal_to_the_id_is_not_a_name(self):
        """keggName is not always resolved; when it is the id, it adds nothing
        and the id should be printed once, not twice."""
        body = self._view()
        start = body.index("this.nameOf = function")
        window = body[start:start + 700]
        self.assertIn("symbol !== id", window)

    def test_the_id_survives_beside_the_name(self):
        """A KEGG id is what a reader carries to another tool, and several
        compounds share a common name."""
        body = self._view()
        self.assertIn("nameWithID", body)
        self.assertIn("pa-hub-id", body)

    def test_the_list_row_carries_the_id(self):
        body = self._view()
        start = body.index("this.renderList = function")
        window = body[start:start + 2200]
        self.assertIn("pa-hub-item-meta", window)
        self.assertIn("m.name === m.ID", window)

    def test_canvas_labels_are_truncated_but_tooltips_are_not(self):
        """Compound names run long ("Ultra-long-chain omega-hydroxy fatty
        acid"); a label wider than its ring is worse than an id."""
        body = self._view()
        start = body.index("this.elements = function")
        window = body[start:start + 1600]
        self.assertIn("fullName", window)
        self.assertIn("name.length > 24", window)
        self.assertIn('n.data("fullName")', body)

    def test_ring_compound_names_arrive_with_the_subgraph(self):
        body = self._view()
        self.assertIn("mergeNames(payload.names", body)

    def test_mappingcomp_is_only_a_fallback(self):
        """It holds what the USER uploaded, which for a file keyed by KEGG id
        is the id again -- so it can be a last resort and nothing more."""
        body = self._view()
        self.assertEqual(body.count("mappingComp"), 1)
        start = body.index("this.nameOf = function")
        self.assertGreater(body.index("mappingComp"), start)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
