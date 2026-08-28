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
        self.assertIn("order.forEach", body)

    def test_rows_of_one_omic_share_a_heatmap(self):
        """One KEGG gene can map to several input features, and the payload
        carries one OmicValue per (omic, input row). Gene 100040843 has seven
        "Gene expression" rows; a box each produced seven single-row heatmaps
        under seven identical headings."""
        body = self.code()
        start = body.index("this.drawOmics = function")
        window = body[start:start + 3000]
        self.assertIn("grouped[o.omicName]", window)
        self.assertIn("grouped[omicName].length", window)

    def test_the_feature_fetch_is_cached(self):
        """Re-clicking a node must not re-hit the server."""
        body = self.code()
        self.assertIn("featureCache", body)

    def test_a_late_response_does_not_write_into_a_replaced_card(self):
        """Clicking a second node before the first request lands must not paint
        the first node's heatmap into the second node's card."""
        self.assertIn("document.body.contains(slot)", self.code())

    def test_unmeasured_node_explains_itself(self):
        """Most nodes in a radius-4 ring were never measured, so the card has
        to say something other than an empty figure.

        The heading used to read "How it connects" above a list capped at eight
        rows. It is a Connections TAB now, carrying the true count -- the
        wording moved, the obligation did not.
        """
        body = self.code()
        self.assertIn("connectedEdges()", body)
        self.assertIn("Connections", body)
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

    def test_a_step_that_adds_nothing_is_marked_and_explained(self):
        """Four rows of identical numbers read as a broken step control.

        A compound in a small component of the KEGG graph runs out of new
        neighbours and every step past that point scores the SAME genes:
        C22353's rings are 32, 1, 0, 0, so steps 3 and 4 print step 2's
        numbers. Correct, and indistinguishable from a bug unless it is said.
        """
        body = self._view()
        start = body.index("this.showSeedDetail = function")
        window = body[start:start + 3600]
        self.assertIn("is-saturated", window)
        self.assertIn("has no ", window)
        self.assertIn("grew", window)

    def test_the_cumulative_column_is_labelled_as_such(self):
        self.assertIn("Counts are cumulative and count only genes measured", self._view())


class TheOldGridIsGoneTest(unittest.TestCase):
    """The nine-column hub table is deleted, not merely unmounted.

    It was left in the file after the network panel replaced it, which meant
    534 lines of it were still constructed and loadModel'd on every job -- an
    852-row Ext store plus its heatmap machinery -- for a component nobody
    rendered.
    """

    def _step3(self):
        with open(STEP3_VIEWS, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_the_view_is_deleted(self):
        body = self._step3()
        self.assertNotIn("function PA_Step3HubAnalysis", body)
        self.assertNotIn("PA_Step3HubAnalysis.prototype", body)

    def test_nothing_constructs_it_any_more(self):
        body = self._step3()
        self.assertNotIn("hubAnalysisView", body)

    def test_the_row_normaliser_survives(self):
        """paHubRow lives outside the deleted view and the network panel and
        its tests read it."""
        self.assertIn("var paHubRow = function", self._step3())

    def test_every_column_it_carried_is_in_the_card(self):
        """Removing the table must not remove what the table said. Percentile
        is the one that is not derivable from the rest -- it is the scorer's
        size-stratified ECDF rank."""
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            view = handle.read()
        start = view.index("this.showSeedDetail = function")
        window = view[start:start + 3200]
        for column in ("row.DEN", "row.noDEN", "row.Percentage",
                       "row.Percentile", "row.pvalue", "row.padjust"):
            self.assertIn(column, window, column + " is not in the step table")


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


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ConnectionsModelTest(unittest.TestCase):
    """paHubConnections(): every connection, grouped, DE first, counted true.

    The panel used to print `connectedEdges().slice(0, 8)`. On the STATegra
    job, gene Ggt1 has 72 connections and 44 distinct partners, so eight rows
    were 11% of the answer with nothing on screen saying so -- and 48 of that
    graph's 161 nodes were truncated the same way. The cap is gone; these
    tests exist so it cannot come back by accident.
    """

    def run_model(self, body):
        """Evaluate paHubConnections() in node and return its JSON."""
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            source = handle.read()
        match = re.search(r"var\s+paHubConnections\s*=\s*function", source)
        if match is None:
            raise AssertionError("paHubConnections() is not defined in the view")
        opening = source.index("{", match.end())
        depth = 0
        for index in range(opening, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    fn = source[match.start():index + 1] + ";"
                    break
        else:
            raise AssertionError("unbalanced braces in paHubConnections()")
        directory = tempfile.mkdtemp(prefix="paintomics-conn-")
        try:
            path = os.path.join(directory, "check.js")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(fn + "\n" + body)
            done = subprocess.run(["node", path], capture_output=True,
                                  text=True, timeout=60)
            if done.returncode != 0:
                raise AssertionError("node failed:\n%s" % done.stderr)
            return json.loads(done.stdout)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    HARNESS = """
    var STATE = %s;
    var NAME = %s;
    function describe(id) {
      return { name: NAME[id] || id, state: STATE[id] || "absent" };
    }
    """

    def test_no_connection_is_ever_dropped(self):
        """72 in, 72 out -- and 500 in, 500 out. There is no cap at any size."""
        out = self.run_model("""
        var edges = [], STATE = {}, NAME = {};
        for (var i = 0; i < 500; i++) {
          edges.push({ source: "hub", target: "p" + i, kind: "ECrel",
                       subtype: "compound", pathway: "mmu0048" + (i % 3) });
          STATE["p" + i] = "quiet"; NAME["p" + i] = "G" + i;
        }
        function describe(id) {
          return { name: NAME[id] || id, state: STATE[id] || "absent" };
        }
        var m = paHubConnections(edges, "hub", describe);
        var rows = m.groups.reduce(function (a, g) { return a + g.rows.length; }, 0);
        console.log(JSON.stringify({ total: m.total, rows: rows,
                                     partners: m.partners }));
        """)
        self.assertEqual(out["total"], 500)
        self.assertEqual(out["rows"], 500, "a cap has come back")
        self.assertEqual(out["partners"], 500)

    def test_the_total_counts_edges_and_partners_separately(self):
        """Ggt1's real shape: 72 edges over 44 partners. Reporting either
        number for the other one would misstate the graph."""
        out = self.run_model("""
        var edges = [
          { source: "hub", target: "a", kind: "ECrel", subtype: "compound", pathway: "p1" },
          { source: "hub", target: "a", kind: "PPrel", subtype: "activation", pathway: "p2" },
          { source: "b", target: "hub", kind: "ECrel", subtype: "compound", pathway: "p1" }
        ];
        function describe(id) { return { name: id.toUpperCase(), state: "quiet" }; }
        var m = paHubConnections(edges, "hub", describe);
        console.log(JSON.stringify({ total: m.total, partners: m.partners }));
        """)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["partners"], 2)

    def test_differentially_expressed_partners_come_first(self):
        """DE concentration is the claim the whole panel exists to show, so a
        DE neighbour must never sort below a gene nobody measured."""
        out = self.run_model("""
        var edges = ["quietOne", "absentOne", "downOne", "upOne"].map(function (t) {
          return { source: "hub", target: t, kind: "ECrel", subtype: "", pathway: "p1" };
        });
        var STATE = { quietOne: "quiet", absentOne: "absent",
                      downOne: "down", upOne: "up" };
        function describe(id) { return { name: id, state: STATE[id] || "absent" }; }
        var m = paHubConnections(edges, "hub", describe);
        console.log(JSON.stringify(m.groups[0].rows.map(function (r) { return r.state; })));
        """)
        self.assertEqual(out, ["up", "down", "quiet", "absent"])

    def test_pathways_are_ranked_by_how_much_de_they_carry(self):
        """A pathway holding the DE neighbours outranks a bigger one that
        holds none -- size alone would bury the finding."""
        out = self.run_model("""
        var edges = [
          { source: "hub", target: "u1", kind: "ECrel", subtype: "", pathway: "small" },
          { source: "hub", target: "q1", kind: "ECrel", subtype: "", pathway: "big" },
          { source: "hub", target: "q2", kind: "ECrel", subtype: "", pathway: "big" },
          { source: "hub", target: "q3", kind: "ECrel", subtype: "", pathway: "big" }
        ];
        var STATE = { u1: "up", q1: "quiet", q2: "quiet", q3: "quiet" };
        function describe(id) { return { name: id, state: STATE[id] || "absent" }; }
        var m = paHubConnections(edges, "hub", describe);
        console.log(JSON.stringify(m.groups.map(function (g) { return g.pathway; })));
        """)
        self.assertEqual(out, ["small", "big"])

    def test_a_shared_symbol_is_disambiguated_by_its_id(self):
        """KEGG ids 100042314, 14857 and 14858 all resolve to the symbol
        Gsta5, so three rows printed the identical line and the panel looked
        like it was repeating itself. Rows that collide carry their id."""
        out = self.run_model("""
        var edges = ["100042314", "14857", "66988"].map(function (t) {
          return { source: "hub", target: t, kind: "ECrel", subtype: "", pathway: "p1" };
        });
        var NAME = { "100042314": "Gsta5", "14857": "Gsta5", "66988": "Lap3" };
        function describe(id) { return { name: NAME[id], state: "quiet" }; }
        var m = paHubConnections(edges, "hub", describe);
        console.log(JSON.stringify(m.groups[0].rows.map(function (r) {
          return { name: r.name, ambiguous: !!r.ambiguous };
        })));
        """)
        collided = [r for r in out if r["name"] == "Gsta5"]
        self.assertEqual(len(collided), 2)
        self.assertTrue(all(r["ambiguous"] for r in collided),
                        "a repeated symbol must be marked so the row can show its id")
        alone = [r for r in out if r["name"] == "Lap3"][0]
        self.assertFalse(alone["ambiguous"], "a unique symbol needs no id")

    def test_states_are_counted_per_partner_not_per_edge(self):
        """Two edges to one gene is one partner. Counting edges would claim
        more differentially expressed neighbours than the job has."""
        out = self.run_model("""
        var edges = [
          { source: "hub", target: "a", kind: "ECrel", subtype: "", pathway: "p1" },
          { source: "hub", target: "a", kind: "PPrel", subtype: "", pathway: "p2" }
        ];
        function describe(id) { return { name: id, state: "up" }; }
        var m = paHubConnections(edges, "hub", describe);
        console.log(JSON.stringify(m.states));
        """)
        self.assertEqual(out["up"], 1)

    def test_direction_survives_so_reciprocal_edges_stay_distinct(self):
        """KEGG records Ggt1->Chac1 AND Chac1->Ggt1 as two ECrel edges in
        mmu00480. Dropping which way each one points prints the same line
        twice, which is the "it repeats itself" complaint all over again --
        this time manufactured by the fix rather than by a name collision."""
        out = self.run_model("""
        var edges = [
          { source: "hub", target: "chac", kind: "ECrel", subtype: "compound", pathway: "p1" },
          { source: "chac", target: "hub", kind: "ECrel", subtype: "compound", pathway: "p1" }
        ];
        function describe(id) { return { name: "Chac1", state: "quiet" }; }
        var m = paHubConnections(edges, "hub", describe);
        console.log(JSON.stringify(m.groups[0].rows.map(function (r) {
          return r.direction;
        })));
        """)
        self.assertEqual(sorted(out), ["in", "out"],
                         "a reciprocal pair must not render as one line twice")

    def test_an_isolated_node_reports_nothing_rather_than_breaking(self):
        out = self.run_model("""
        function describe(id) { return { name: id, state: "absent" }; }
        var m = paHubConnections([], "hub", describe);
        console.log(JSON.stringify({ total: m.total, partners: m.partners,
                                     groups: m.groups.length }));
        """)
        self.assertEqual(out, {"total": 0, "partners": 0, "groups": 0})


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class NodeInspectorTest(unittest.TestCase):
    """The click has to answer "how does this connect?" in the GRAPH.

    Before this, selecting a node drew a 4px ring on that node and did nothing
    else: its 72 edges stayed indistinguishable inside a 600-edge wash, which
    is why a text list had to carry the whole answer in a 269px drawer holding
    1273px of content.
    """

    def source(self):
        with open(HUB_NETWORK_VIEW, "r", encoding="utf-8") as handle:
            return handle.read()

    def code(self):
        body = re.sub(r"/\*.*?\*/", "", self.source(), flags=re.S)
        return re.sub(r"(?m)^\s*//.*$", "", body)

    def test_the_eight_row_cap_is_gone(self):
        """The specific regression: `.slice(0, 8)` over connectedEdges()."""
        body = self.code()
        self.assertNotIn(".slice(0, 8)", body)
        self.assertIn("paHubConnections", body)
        self.assertIn("pa-hub-dir", body)   # direction is still on the row

    def test_selecting_a_node_lights_its_own_edges(self):
        body = self.code()
        self.assertIn("this.focusEgo", body)
        self.assertIn("pa-ego-edge", body)

    def test_the_focus_leaves_the_step_filter_alone(self):
        """setLevel owns .dim. The ego focus must compose with it, not fight
        it -- an edge outside the chosen ring stays dimmed either way."""
        body = self.code()
        start = body.index("this.focusEgo = function")
        window = body[start:start + 2200]
        self.assertIn('hasClass("dim")', window)
        self.assertNotIn('removeClass("dim")', window)

    def test_the_seed_card_clears_the_focus(self):
        """Opening the panel shows the metabolite, and focusing its ego on
        load would dim most of the graph before anyone clicked anything."""
        body = self.code()
        start = body.index("this.showSeedDetail = function")
        end = body.index("this.showNodeDetail = function", start)
        self.assertIn("focusEgo(null)", body[start:end])

    def test_the_drawer_separates_expression_from_connections(self):
        body = self.code()
        self.assertIn("pa-hub-tab", body)
        self.assertIn("detailTab", body)

    def test_the_connection_count_is_on_the_tab(self):
        """8 of 72 was silent. The number is now furniture."""
        body = self.code()
        self.assertIn("model.total", body)

    def test_the_drawer_can_be_resized(self):
        """The expression figures alone measure 1046px in a 269px window."""
        body = self.code()
        self.assertIn("pa-hub-grip", body)
        self.assertIn("flexBasis", body)

    def test_a_dragged_height_survives_a_tab_switch(self):
        """Switching tab or facet re-renders through clearDetail(), which drops
        the inline flex-basis -- so the card snapped back to 300px every time
        the reader touched a chip, discarding the height they just dragged."""
        body = self.code()
        self.assertIn("detailHeight", body)
        start = body.index("this.openDetail = function")
        window = body[start:start + 1400]
        self.assertIn("me.detailHeight", window)
        self.assertIn("flexBasis", window)

    def test_the_resize_does_not_animate_height(self):
        """A height transition on this flex item resolved to 1px and stayed
        there; flex-basis is what the column algorithm reads."""
        body = self.code()
        start = body.index("this.bindResize")
        window = body[start:start + 1800]
        self.assertNotIn(".style.height", window)


class ConnectionStylesTest(unittest.TestCase):
    """The stylesheet half of the same change."""

    def css(self):
        path = os.path.join(CLIENT, "resources", "css", "network-views.css")
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_the_card_advertises_that_it_scrolls(self):
        """macOS overlay scrollbars are invisible until dragged, so a row cut
        mid-glyph read as a broken render rather than as more content."""
        body = self.css()
        self.assertIn(".pa-hub-detail-body::after", body)   # the fade
        self.assertIn(".pa-hub-detail-body.at-end::after", body)
        self.assertIn(".pa-hub-pane::-webkit-scrollbar", body)

    def test_the_ego_edges_carry_the_de_colours(self):
        body = self.css()
        self.assertIn("pa-hub-tab", body)
        self.assertIn("pa-hub-facet", body)

    def test_the_card_title_sits_on_the_same_rail_as_its_rows(self):
        """main.css's `div.contentbox h3` is (0,1,2) and beat the bare
        `.pa-hub-detail-title` class (0,1,0), so the title rendered at
        margin-left 0 while the tabs, counts and rows sit on the 12px rail."""
        body = self.css()
        self.assertIn(".pa-hub-detail .pa-hub-detail-title", body)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
