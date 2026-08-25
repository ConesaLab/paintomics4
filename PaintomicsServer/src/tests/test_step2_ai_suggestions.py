#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""The browser half of the closed-set guarantee, and Undo.

The server refuses to answer with a KEGG id that was not on a card. This file
pins the other half: the code that moves the checkboxes refuses to act on one
either, and it only ever touches candidates inside the set it was given.

Both halves are needed. The server's validation protects against the model; this
protects against the payload -- a decision for an input name this browser has no
card for, or an id that belongs to a different set. Neither is hypothetical:
the server deliberately ranks compound sets this view draws no card for, because
`selected` does not exist server-side and its needsDisambiguation is therefore
more permissive than the view's.

Runs the real PA_Step2Views.js inside node with stubs for Ext, jQuery and View,
exactly as test_step2_compound_panel.py does. Skipped where node is missing.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", "..", ".."))
STEP2_VIEW = os.path.join(
    REPO_ROOT, "PaintomicsClient", "public_html", "app", "view",
    "PathwayAcquisitionViews", "PA_Step2Views.js")

NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[2], 'utf8');

function htmlEncode(value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// jQuery is only used here for the toolbar buttons; every call is a no-op that
// returns a chainable stub, so setAIButtonState and the click wiring can run.
function jqStub() {
    const self = {
        length: 0,
        on: () => self, click: () => self, html: () => self, show: () => self,
        hide: () => self, addClass: () => self, removeClass: () => self,
        hasClass: () => false, attr: () => undefined, is: () => false,
        closest: () => self, val: () => "", toggle: () => self, find: () => self,
        prev: () => self, remove: () => self
    };
    return self;
}

const sandbox = {
    console: {log(){}, info(){}, warn(){}, error(){}},
    View: function View() {
        this.model = null; this.component = null;
        this.getModel = function () { return this.model; };
        this.getComponent = function () { return this.component; };
        this.loadModel = function (model) { this.model = model; return this; };
    },
    Ext: {
        String: {htmlEncode: htmlEncode},
        widget: function () { return {}; },
        create: function () { return {}; }
    },
    $: jqStub,
    initializeTooltips: function () {},
    showWarningMessage: function () {},
    withAIProviderInfo: function () {}
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source + "\n;globalThis.__api = {" +
    "PA_Step2CompoundSetView: PA_Step2CompoundSetView," +
    "PA_Step2JobView: PA_Step2JobView};", sandbox, {filename: 'PA_Step2Views.js'});
const api = sandbox.__api;

function compound(id, name, selected) {
    return {
        ID: id, name: name, selected: selected,
        getID: function () { return this.ID; },
        getName: function () { return this.name; },
        isSelected: function () { return this.selected; }
    };
}
function compoundSet(title, main, other) {
    return {
        title: title, mainCompounds: main, otherCompounds: other || [],
        getTitle: function () { return this.title; },
        getMainCompounds: function () { return this.mainCompounds; },
        getOtherCompounds: function () { return this.otherCompounds; },
        addObserver: function () {}
    };
}
function jobView(sets) {
    const view = new api.PA_Step2JobView();
    view.loadModel({
        getFoundCompounds: function () { return sets; },
        deleteObserver: function () {},
        getJobID: function () { return "job1"; },
        aiConsent: true
    });
    view.items = sets.map(function (set) {
        const cardView = new api.PA_Step2CompoundSetView();
        cardView.loadModel(set);
        return cardView;
    });
    // The panel component only exists once the widget is built; refresh must
    // survive its absence, which is also what happens in a background tab.
    view.component = null;
    return view;
}

function ticks(set) {
    return set.mainCompounds.concat(set.otherCompounds)
        .map(function (c) { return c.selected === true; });
}

const out = {};

// --- a legal decision moves exactly one tick, and clears its rivals ---------
{
    const alanine = compoundSet("Alanine", [
        compound("C01401", "Alanine", true),
        compound("C00041", "L-Alanine", true),
        compound("C00133", "D-Alanine", true)]);
    const view = jobView([alanine]);
    const counts = view.applyAISuggestions({
        decisions: [{title: "Alanine", keggID: "C00041", tier: "ai",
                     confidence: "high", reason: "mouse"}],
        unresolved: [], model: "m"});
    out.legal = {ticks: ticks(alanine), counts: counts,
                 badge: view.items[0].aiState};
}

// --- an id this set does not contain must change nothing -------------------
{
    const serine = compoundSet("Serine", [
        compound("C00065", "L-Serine", true),
        compound("C00740", "D-Serine", true)]);
    const view = jobView([serine]);
    const counts = view.applyAISuggestions({
        decisions: [{title: "Serine", keggID: "C00041", tier: "ai",
                     confidence: "high", reason: "wrong set"}],
        unresolved: [], model: "m"});
    out.foreignID = {ticks: ticks(serine), counts: counts};
}

// --- a decision for a card this view does not have is dropped --------------
{
    const serine = compoundSet("Serine", [
        compound("C00065", "L-Serine", true),
        compound("C00740", "D-Serine", true)]);
    const view = jobView([serine]);
    const counts = view.applyAISuggestions({
        decisions: [{title: "Pyruvic acid", keggID: "C00022", tier: "deterministic",
                     confidence: "", reason: "not drawn here"}],
        unresolved: [], model: "m"});
    out.unknownCard = {ticks: ticks(serine), counts: counts};
}

// --- undo restores every tick exactly ---------------------------------------
{
    const glucose = compoundSet("Glucose",
        [compound("C00031", "Glucose", true), compound("C00221", "beta-D-Glucose", true)],
        [compound("C00092", "D-Glucose 6-phosphate", false)]);
    const view = jobView([glucose]);
    const before = ticks(glucose);
    view.applyAISuggestions({
        decisions: [{title: "Glucose", keggID: "C00031", tier: "ai",
                     confidence: "high", reason: "no anomer named"}],
        unresolved: [], model: "m"});
    const during = ticks(glucose);
    view.undoAISuggestions();
    out.undo = {before: before, during: during, after: ticks(glucose),
                summaryCleared: view.aiSummary === null,
                badgeCleared: view.items[0].aiState === null};
}

// --- an abstention badges the card and leaves it alone ----------------------
{
    const lysine = compoundSet("Lysine", [
        compound("C00047", "L-Lysine", true),
        compound("C00739", "D-Lysine", true)]);
    const view = jobView([lysine]);
    const counts = view.applyAISuggestions({
        decisions: [],
        unresolved: [{title: "Lysine", reason: "both forms are plausible", detail: ""}],
        model: "m"});
    out.abstain = {ticks: ticks(lysine), counts: counts,
                   badge: view.items[0].aiState,
                   card: view.items[0].renderCard(0)};
}

// --- the summary counts cards changed, not decisions received ---------------
{
    const already = compoundSet("Urea", [compound("C00086", "Urea", true)]);
    const view = jobView([already]);
    const counts = view.applyAISuggestions({
        decisions: [{title: "Urea", keggID: "C00086", tier: "deterministic",
                     confidence: "", reason: "only match"}],
        unresolved: [], model: "m"});
    out.noop = {counts: counts, summary: view.aiSummary,
                badge: view.items[0].aiState || null,
                banner: view.renderAISummary()};
}

process.stdout.write(JSON.stringify(out));
"""


@unittest.skipIf(NODE is None, "node is not installed")
class Step2AISuggestionsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        handle, path = tempfile.mkstemp(suffix=".js")
        with os.fdopen(handle, "w") as harness:
            harness.write(HARNESS)
        try:
            result = subprocess.run([NODE, path, STEP2_VIEW],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode != 0:
                raise AssertionError("harness failed:\n" + result.stderr.decode("utf-8"))
            cls.out = json.loads(result.stdout.decode("utf-8"))
        finally:
            os.unlink(path)

    def test_a_legal_decision_ticks_one_candidate_and_clears_the_rest(self):
        case = self.out["legal"]
        self.assertEqual([False, True, False], case["ticks"])
        self.assertEqual(1, case["counts"]["byAI"])
        self.assertEqual(0, case["counts"]["byRule"])
        self.assertEqual("picked", case["badge"]["status"])
        self.assertEqual("C00041", case["badge"]["keggID"])

    def test_an_id_from_another_set_changes_nothing(self):
        """selectOnly must not clear a set just because it cannot find the id.

        Unticking everything would be the worst outcome available: the user
        loses a selection they made, to an answer that was never valid.
        """
        case = self.out["foreignID"]
        self.assertEqual([True, True], case["ticks"])
        self.assertEqual(0, case["counts"]["byAI"])

    def test_a_decision_for_a_card_this_view_lacks_is_dropped(self):
        case = self.out["unknownCard"]
        self.assertEqual([True, True], case["ticks"])
        self.assertEqual(0, case["counts"]["byAI"] + case["counts"]["byRule"])

    def test_undo_restores_every_tick_including_collapsed_alternatives(self):
        case = self.out["undo"]
        self.assertEqual([True, True, False], case["before"])
        self.assertEqual([True, False, False], case["during"])
        self.assertEqual(case["before"], case["after"])
        self.assertTrue(case["summaryCleared"])
        self.assertTrue(case["badgeCleared"])

    def test_an_abstention_badges_the_card_without_touching_it(self):
        case = self.out["abstain"]
        self.assertEqual([True, True], case["ticks"])
        self.assertEqual(1, case["counts"]["unsure"])
        self.assertEqual("unsure", case["badge"]["status"])
        self.assertIn("AI unsure", case["card"])
        self.assertIn("aiBox-unsure", case["card"])
        self.assertIn("aiBadge-unsure", case["card"])

    def test_a_decision_that_changes_nothing_leaves_no_badge(self):
        """A chip on every card is a chip on none.

        The server decides every compound set it holds, and on a typical job
        most of those agree with what was already ticked. Marking those too put
        a badge on 52 of 47 cards and made the changes impossible to find.
        """
        case = self.out["noop"]
        self.assertIsNone(case["badge"])

    def test_a_decision_that_changes_nothing_is_not_counted_as_work(self):
        """The banner must not credit the feature with ticks it did not move."""
        case = self.out["noop"]
        self.assertEqual(0, case["counts"]["byRule"])
        self.assertEqual(0, case["counts"]["byAI"])
        self.assertIn("already matched", case["banner"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
