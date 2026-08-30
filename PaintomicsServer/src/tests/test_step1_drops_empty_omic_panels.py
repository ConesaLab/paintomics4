#!/usr/bin/env python3
"""An omic panel the user left empty must be dropped, never reported.

The behaviour this guards
-------------------------
Step 1 opens with a Gene expression panel and a Metabolomics panel already on
the form, and adding a Region-based, miRNA or MORE panel is one click in
"Available omics". A panel with no file in it therefore means "I did not want
this one" -- which is why `PA_Step1JobView.checkForm()` deletes empty panels
instead of complaining about them, and only refuses the form when *every*
panel is empty.

It used to validate first and delete afterwards, and the two halves disagreed:

    valid = combo.isValid();
    for (i in items) { valid = valid && items[i].isValid(); }   // empty ones too
    for (i in items) { if (items[i].isEmpty()) { ...click delete... } }

An empty panel was counted as invalid and then deleted by the very next loop.
The plain omic panel hides this -- its isValid() returns early when the panel
is empty -- but the Region-based, miRNA and MORE panels have no such guard:
empty, they mark their own file fields invalid and return false. Those three
are also exactly the panels that route the submit through
`step1ComplexFormSubmitHandler`, whose failure branch is the only place that
shows

    "Invalid Form. </br> Please check the form errors."   (with Report error)

So: add a Region-based omic, fill in Gene expression, press Run PaintOmics ->
the form is refused because of the region panel, the region panel is deleted a
moment later, and the user is left looking at one clean Gene expression box
with nothing marked anywhere, being told to check errors that no longer exist.
That is the report received from a user on 2026-08-26; reproduced in Chrome
against the deployed client, which left 0 panels marked invalid and 0 elements
carrying x-form-invalid.

Order is the fix: drop the empty panels first, then validate what is left.

Why node runs a browser file
----------------------------
The client has no test harness of its own (see test_reset_destroys_every_job_view
and test_organism_search for the same pattern). `checkForm` is lifted out of
PA_Step1Views.js as shipped and driven against stand-ins for the only things it
touches -- the omic panels, the organism combo and jQuery's delete click -- so
what is tested is the source the browser loads, not a copy of it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_step1_drops_empty_omic_panels
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

CLIENT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "PaintomicsClient", "public_html"))
JOB_CONTROLLER = os.path.join(CLIENT_ROOT, "app", "controller", "JobController.js")
STEP1_VIEWS = os.path.join(
    CLIENT_ROOT, "app", "view", "PathwayAcquisitionViews", "PA_Step1Views.js")

HEADERS = {
    "dropEmptyOmicPanels": "this.dropEmptyOmicPanels = function() {",
    "checkForm": "this.checkForm = function() {",
    "submitFormHandler": "this.submitFormHandler = function() {",
}


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def extract_block(source, header):
    """`header` plus the brace-matched block that follows it.

    Braces inside strings and comments are skipped, so a selector or an
    explanation cannot unbalance the count.
    """
    start = source.find(header)
    if start == -1:
        raise AssertionError("%s is missing from PA_Step1Views.js" % header)
    index = source.index("{", start + len(header) - 1)
    depth = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char in "\"'":
            quote = char
            index += 1
            while index < length and source[index] != quote:
                index += 2 if source[index] == "\\" else 1
        elif source.startswith("//", index):
            index = source.find("\n", index)
            if index == -1:
                break
        elif source.startswith("/*", index):
            index = source.index("*/", index) + 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise AssertionError("unbalanced braces after %s" % header)


# The real dropEmptyOmicPanels/checkForm/submitFormHandler, driven by stand-ins
# for the only things they touch: the panels the view's ComponentQuery returns,
# each panel's isEmpty/isValid, the organism combo, the jQuery click that
# removes a panel, and the controller the submit is routed to.
HARNESS = """
function makePanel(name, cls, empty, valid) {
    const panel = {
        name: name,
        cls: cls,
        deleted: false,
        askedIfValid: false,
        isEmpty: function () { return empty; },
        isValid: function () { panel.askedIfValid = true; return valid; },
        getEl: function () { return {dom: panel}; },
        // ExtJS returns null for anything inside a component it has destroyed,
        // which is what a deleted panel throws on once it reaches the
        // pre-processing list.
        queryById: function (itemId) {
            if (itemId !== "itemsContainer") { throw new Error(itemId); }
            if (panel.deleted) { return null; }
            return {isDisabled: function () { return false; }};
        }
    };
    return panel;
}

// jQuery, as the view uses it: $(panelDom).find("a.deleteOmicBox").click().
const $ = function (dom) {
    return {find: function () { return {click: function () { dom.drop(); }}; }};
};

function isSpecial(panel) { return panel.cls !== "omicbox"; }

function makeView(panels, organismValid) {
    const live = panels.slice();
    panels.forEach(function (panel) {
        panel.drop = function () {
            panel.deleted = true;
            const at = live.indexOf(panel);
            if (at >= 0) { live.splice(at, 1); }
        };
    });

    // One query for both callers: checkForm asks for every omic panel,
    // submitFormHandler asks submittingPanelsContainer for the region, miRNA
    // and MORE ones only.
    const query = function (selector) {
        const wantsAll = selector.indexOf("container[cls=omicbox],") === 0;
        return live.filter(function (panel) { return wantsAll || isSpecial(panel); });
    };

    const routed = [];
    const view = {
        routed: routed,
        controller: {
            step1ComplexFormSubmitHandler: function (jobView, omicBoxes) {
                routed.push({path: "complex", boxes: omicBoxes.map(function (b) { return b.name; })});
                // What the real handler does with each panel it is given, and
                // what threw when it was given one checkForm had removed.
                omicBoxes.forEach(function (b) { b.queryById("itemsContainer").isDisabled(); });
            },
            step1OnFormSubmitHandler: function () { routed.push({path: "plain", boxes: []}); }
        },
        getComponent: function () {
            return {
                query: query,
                queryById: function (itemId) {
                    if (itemId === "speciesCombobox") {
                        return {isValid: function () { return organismValid; }};
                    }
                    if (itemId === "submittingPanelsContainer") { return {query: query}; }
                    throw new Error(itemId);
                }
            };
        }
    };
    // The blocks below are lifted verbatim out of PA_Step1Views.js, so they are
    // installed the way the view installs them.
    (function () { %(dropEmptyOmicPanels)s }).call(view);
    (function () { %(checkForm)s }).call(view);
    (function () { %(submitFormHandler)s }).call(view);
    return view;
}

function report(label, view, panels, threw, accepted) {
    return {
        label: label,
        threw: threw,
        accepted: accepted,
        routed: view.routed,
        panels: panels.map(function (p) {
            return {name: p.name, deleted: p.deleted, askedIfValid: p.askedIfValid};
        })
    };
}

function run(label, panels, organismValid) {
    const view = makeView(panels, organismValid);
    let threw = null, accepted = null;
    try { accepted = view.checkForm(); } catch (e) { threw = String(e && e.stack || e); }
    return report(label, view, panels, threw, accepted);
}

// Pressing "Run PaintOmics": the whole route, from the button to the handler
// the submission is given to.
function runSubmit(label, panels, organismValid) {
    const view = makeView(panels, organismValid);
    let threw = null;
    try { view.submitFormHandler(); } catch (e) { threw = String(e && e.stack || e); }
    return report(label, view, panels, threw, null);
}

const results = {};

// The report: Gene expression filled in, an empty Region-based panel added
// alongside it. The region panel is not part of the submission -- it is about
// to be deleted -- so it must not make the form invalid.
results.emptyRegionAlongsideFilledGene = run("emptyRegionAlongsideFilledGene", [
    makePanel("geneexpression", "omicbox", false, true),
    makePanel("metabolomics", "omicbox", true, true),
    makePanel("region", "omicbox regionBasedOmic", true, false)
], true);

// Same shape for the other two panels that reach the complex submit path.
results.emptyMirnaAlongsideFilledGene = run("emptyMirnaAlongsideFilledGene", [
    makePanel("geneexpression", "omicbox", false, true),
    makePanel("mirna", "omicbox miRNABasedOmic", true, false)
], true);

results.emptyMoreAlongsideFilledGene = run("emptyMoreAlongsideFilledGene", [
    makePanel("geneexpression", "omicbox", false, true),
    makePanel("more", "omicbox moreBasedOmic", true, false)
], true);

// A panel the user DID fill in and got wrong is a real error: it stays on the
// form, it is marked, and the form is refused. This is the case the dialog's
// "please check the form errors" is actually about.
results.filledRegionThatIsInvalid = run("filledRegionThatIsInvalid", [
    makePanel("geneexpression", "omicbox", false, true),
    makePanel("region", "omicbox regionBasedOmic", false, false)
], true);

// Nothing filled in anywhere: there is no submission to make.
results.everyPanelEmpty = run("everyPanelEmpty", [
    makePanel("geneexpression", "omicbox", true, true),
    makePanel("metabolomics", "omicbox", true, true),
    makePanel("region", "omicbox regionBasedOmic", true, false)
], true);

// No organism chosen. The combo is marked by isValid() itself, so the dialog
// has something to point at.
results.noOrganism = run("noOrganism", [
    makePanel("geneexpression", "omicbox", false, true),
    makePanel("region", "omicbox regionBasedOmic", false, true)
], false);

// The happy path the region pipeline runs on.
results.filledGeneAndRegion = run("filledGeneAndRegion", [
    makePanel("geneexpression", "omicbox", false, true),
    makePanel("metabolomics", "omicbox", true, true),
    makePanel("region", "omicbox regionBasedOmic", false, true)
], true);

// Pressing Run with the reported form: the empty region panel must not reach
// the region/miRNA/MORE pre-processing handler. It is deleted on the way
// there, and a deleted panel is a destroyed ExtJS component.
results.submitWithEmptyRegion = runSubmit("submitWithEmptyRegion", [
    makePanel("geneexpression", "omicbox", false, true),
    makePanel("metabolomics", "omicbox", true, true),
    makePanel("region", "omicbox regionBasedOmic", true, false)
], true);

// A region panel the user did fill in is the reason the complex path exists.
results.submitWithFilledRegion = runSubmit("submitWithFilledRegion", [
    makePanel("geneexpression", "omicbox", false, true),
    makePanel("metabolomics", "omicbox", true, true),
    makePanel("region", "omicbox regionBasedOmic", false, true)
], true);

console.log(JSON.stringify(results));
"""


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-step1-checkform-")
    try:
        path = os.path.join(directory, "check.js")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        completed = subprocess.run(["node", path], capture_output=True,
                                   text=True, timeout=60)
        if completed.returncode != 0:
            raise AssertionError("node failed:\n%s" % completed.stderr)
        return json.loads(completed.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def panelNamed(result, name):
    for panel in result["panels"]:
        if panel["name"] == name:
            return panel
    raise AssertionError("no panel %r in %s" % (name, result["label"]))


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class Step1DropsEmptyOmicPanelsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = read(STEP1_VIEWS)
        cls.results = run_node(HARNESS % dict(
            (name, extract_block(source, header))
            for name, header in HEADERS.items()))

    def test_it_runs(self):
        for name, result in self.results.items():
            self.assertIsNone(result["threw"], "%s: %s" % (name, result["threw"]))

    def test_an_empty_region_panel_does_not_refuse_the_form(self):
        """The reported bug, in one assertion.

        The user filled in Gene expression and added a Region-based panel they
        left empty. The panel is dropped, so the form goes.
        """
        result = self.results["emptyRegionAlongsideFilledGene"]
        self.assertTrue(result["accepted"],
                        "an empty region panel must not make the form invalid")
        self.assertTrue(panelNamed(result, "region")["deleted"],
                        "the empty region panel must be removed from the form")

    def test_an_empty_mirna_panel_does_not_refuse_the_form(self):
        result = self.results["emptyMirnaAlongsideFilledGene"]
        self.assertTrue(result["accepted"])
        self.assertTrue(panelNamed(result, "mirna")["deleted"])

    def test_an_empty_more_panel_does_not_refuse_the_form(self):
        result = self.results["emptyMoreAlongsideFilledGene"]
        self.assertTrue(result["accepted"])
        self.assertTrue(panelNamed(result, "more")["deleted"])

    def test_a_panel_that_is_about_to_be_deleted_is_never_validated(self):
        """Validity is only asked of panels that will be submitted.

        Asking an empty panel is what marked fields on a panel the user was
        about to lose, and is the shape the bug can come back in.
        """
        for name in ("emptyRegionAlongsideFilledGene",
                     "emptyMirnaAlongsideFilledGene",
                     "emptyMoreAlongsideFilledGene",
                     "everyPanelEmpty"):
            result = self.results[name]
            for panel in result["panels"]:
                if panel["deleted"]:
                    self.assertFalse(
                        panel["askedIfValid"],
                        "%s: %s was validated and then deleted"
                        % (name, panel["name"]))

    def test_empty_panels_are_still_cleared_away(self):
        """The drop-the-ones-you-did-not-use behaviour must not regress."""
        result = self.results["filledGeneAndRegion"]
        self.assertTrue(result["accepted"])
        self.assertTrue(panelNamed(result, "metabolomics")["deleted"])
        self.assertFalse(panelNamed(result, "geneexpression")["deleted"])
        self.assertFalse(panelNamed(result, "region")["deleted"])

    def test_a_filled_panel_with_an_error_still_refuses_the_form(self):
        """The message the dialog shows is only honest if this stays true."""
        result = self.results["filledRegionThatIsInvalid"]
        self.assertFalse(result["accepted"])
        self.assertFalse(panelNamed(result, "region")["deleted"],
                         "a panel carrying the error must stay on the form")

    def test_every_filled_panel_is_validated_even_when_the_organism_is_wrong(self):
        """`valid = valid && panel.isValid()` short-circuited: with the organism
        missing no panel was validated or marked, and the user learnt about
        the panel only on the NEXT round. The panel call must come first."""
        source = read(STEP1_VIEWS)
        self.assertIn("valid = filled[i].isValid() && valid;", source)
        self.assertNotIn("valid = valid && filled[i].isValid();", source)

    def test_the_plain_panel_actually_validates_itself(self):
        """`if (this.isEmpty)` tested the METHOD -- always truthy -- so a plain
        panel with a file and no omic name was posted with an empty name."""
        source = read(STEP1_VIEWS)
        self.assertNotIn("if (this.isEmpty) {", source)
        self.assertIn("if (this.isEmpty()) {", source)

    def test_the_plain_submit_path_shows_the_same_refusal(self):
        """The plain path said "provide at least Gene expression..." whatever
        was wrong; both paths now go through showInvalidStep1FormMessage."""
        source = read(JOB_CONTROLLER)
        # Twice for checkForm()'s refusal on each submit path, once more for
        # the complex path's refusal raised by ExtJS inside submit() (its
        # temporary form is gone by then, so the main form names the field).
        self.assertEqual(source.count("showInvalidStep1FormMessage(jobView);"), 3,
                         "both submit paths must call it, and the complex path "
                         "again for a client-side abort")

    def test_a_form_with_nothing_in_it_is_refused(self):
        self.assertFalse(self.results["everyPanelEmpty"]["accepted"])

    def test_no_organism_refuses_the_form(self):
        self.assertFalse(self.results["noOrganism"]["accepted"])

    def test_a_dropped_panel_never_reaches_the_pre_processing_handler(self):
        """The other half of the same mistake.

        submitFormHandler used to pick the region/miRNA/MORE panels to
        pre-process before the empty ones were dropped, so the list it handed
        over could name a panel that was destroyed moments later --
        `Cannot read properties of null (reading 'query')` on the first thing
        step1ComplexFormSubmitHandler asks it for.
        """
        result = self.results["submitWithEmptyRegion"]
        self.assertIsNone(result["threw"], result["threw"])
        self.assertEqual([r["path"] for r in result["routed"]], ["plain"],
                         "an empty region panel is not something to pre-process")
        self.assertTrue(panelNamed(result, "region")["deleted"])

    def test_a_filled_region_panel_still_takes_the_pre_processing_path(self):
        result = self.results["submitWithFilledRegion"]
        self.assertIsNone(result["threw"], result["threw"])
        self.assertEqual(result["routed"], [{"path": "complex", "boxes": ["region"]}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
