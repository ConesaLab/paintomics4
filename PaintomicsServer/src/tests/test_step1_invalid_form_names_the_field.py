#!/usr/bin/env python3
"""A refused Step 1 submission must name the field it is refusing over.

The behaviour this guards
-------------------------
Step 1 is three sections tall: the organism combo is in section 1 and the omic
panels are in section 3. "Invalid Form. Please check the form errors." over a
page that long is only a direction if the reader can find the error, and the
field that refused the submission is routinely off screen behind the dialog.

That is what happened to the user who reported it on 2026-08-26. The nginx log
on paintomics.uv.es has her whole session in one page load:

    12:57:53  GET /                     page loaded (after um_signin)
    13:00:55  GET /more_backends        Regulatory Omic -> MORE panel added
       ...    no request of any kind    filling the MORE panel in the browser
    13:11:56  POST /dm_sendReport       "Invalid Form. Please check the form errors."
    13:12:27  GET /organism_databases   the organism combo, chosen at last
    14:07:04  POST /dm_fromMOREtoGenes  the submission finally goes through

`/organism_databases` is fetched once per page load, by the combo's own change
listener (`loadOrganismDatabases` guards on ORGANISM_DATABASES_REQUEST) -- so
it landing 31 seconds AFTER the report is the proof that **no organism had been
chosen** when she pressed Run PaintOmics. And nothing at all was POSTed between
13:00:55 and the report, which is the signature of a refusal that never left
the browser: checkForm() said no.

So the one thing wrong with her form was a single field, two sections above
where she had spent the last eleven minutes working, and the dialog neither
named it nor took her to it.

Now it does: the first *visible* marked field is scrolled into view and the
message reads "Organism: This field is required."

Why node runs a browser file
----------------------------
The client has no test harness of its own. `firstFormError` is lifted out of
PA_Step1Views.js and `showInvalidStep1FormMessage` out of JobController.js, as
shipped, and driven against stand-ins for the fields and the dialog -- the same
pattern as test_step1_drops_empty_omic_panels and test_organism_search.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_step1_invalid_form_names_the_field
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
STEP1_VIEWS = os.path.join(
    CLIENT_ROOT, "app", "view", "PathwayAcquisitionViews", "PA_Step1Views.js")
JOB_CONTROLLER = os.path.join(
    CLIENT_ROOT, "app", "controller", "JobController.js")
UTIL_JS = os.path.join(CLIENT_ROOT, "app", "view", "common", "Util.js")

VIEW_HEADERS = {"firstFormError": "this.firstFormError = function() {"}
CONTROLLER_HEADERS = {
    "showInvalidStep1FormMessage": "function showInvalidStep1FormMessage(jobView) {",
}
# The composition lives in Util.js, shared with the failure handler's
# client-abort branch.
UTIL_HEADERS = {
    "plainFieldText": "function plainFieldText(html) {",
    "fieldErrorText": "function fieldErrorText(field) {",
    "firstVisibleInvalidField": "function firstVisibleInvalidField(fields) {",
    "showInvalidFieldMessage": "function showInvalidFieldMessage(field) {",
    "extJSErrorHandler": "function extJSErrorHandler(form, responseObj) {",
}
NO_DATA_STATEMENT = "var STEP1_NO_DATA_MESSAGE ="


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _scan(source, start, stop_at_depth_zero):
    """Walk `source` from `start`, skipping strings and comments.

    Calls `stop_at_depth_zero(char, depth)` for every character that is real
    code; the first index for which it returns True is returned.
    """
    index, depth, length = start, 0, len(source)
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
            continue
        elif source.startswith("/*", index):
            index = source.index("*/", index) + 1
        else:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            if stop_at_depth_zero(char, depth):
                return index
        index += 1
    raise AssertionError("ran off the end from offset %d" % start)


def extract_block(source, header, what):
    """`header` plus the brace-matched block that follows it."""
    start = source.find(header)
    if start == -1:
        raise AssertionError("%s is missing from %s" % (header, what))
    opening = source.index("{", start + len(header) - 1)
    end = _scan(source, opening, lambda char, depth: char == "}" and depth == 0)
    return source[start:end + 1]


def extract_statement(source, header, what):
    """`header` up to the semicolon that ends it (semicolons inside the
    string literals do not count -- the message carries inline CSS)."""
    start = source.find(header)
    if start == -1:
        raise AssertionError("%s is missing from %s" % (header, what))
    end = _scan(source, start, lambda char, depth: char == ";" and depth == 0)
    return source[start:end + 1]


HARNESS = """
var Ext = {String: {htmlEncode: function (s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}}, form: {action: {Action: {CLIENT_INVALID: "client"}}}};
var debugging = false;
var shown = [];
function showErrorMessage(title, opts) { shown.push({title: title, opts: opts}); }

%(STEP1_NO_DATA_MESSAGE)s
%(plainFieldText)s
%(fieldErrorText)s
%(firstVisibleInvalidField)s
%(showInvalidFieldMessage)s
%(showInvalidStep1FormMessage)s
%(extJSErrorHandler)s

function makeField(spec) {
    var field = {
        name: spec.name,
        fieldLabel: spec.label,
        scrolled: false,
        hasActiveError: function () { return !!spec.error; },
        getActiveError: function () { return spec.error || ""; },
        isVisible: function () { return spec.visible !== false; },
        getEl: function () {
            if (spec.rendered === false) { return null; }
            return {dom: {scrollIntoView: function () { field.scrolled = true; }}};
        }
    };
    return field;
}

function makeView(fields, formIsEmpty) {
    var view = {
        formIsEmpty: formIsEmpty,
        getComponent: function () { return {query: function () { return fields; }}; }
    };
    (function () { %(firstFormError)s }).call(view);
    return view;
}

function run(label, fields, formIsEmpty) {
    shown = [];
    var view = makeView(fields, formIsEmpty);
    var threw = null;
    try { showInvalidStep1FormMessage(view); } catch (e) { threw = String(e && e.stack || e); }
    return {
        label: label,
        threw: threw,
        shown: shown,
        scrolled: fields.filter(function (f) { return f.scrolled; })
                        .map(function (f) { return f.name; })
    };
}

/* ExtJS's own submit-time refusal: failureType "client", no response. The
   form is a BasicForm whose monitor is gone once the complex path has
   destroyed it. */
function runHandler(label, fields, formAlive) {
    shown = [];
    var form = formAlive
        ? {monitor: {}, getFields: function () { return {getRange: function () { return fields; }}; }}
        : {monitor: null};
    var threw = null;
    try { extJSErrorHandler(form, {failureType: "client"}); } catch (e) { threw = String(e && e.stack || e); }
    return {label: label, threw: threw, shown: shown,
            scrolled: fields.filter(function (f) { return f.scrolled; }).map(function (f) { return f.name; })};
}
var results = {};
results.clientAbortNamesTheField = runHandler("clientAbortNamesTheField", [
    makeField({name: "speciesCombobox", label: "Organism"}),
    makeField({name: "omicNameField", label: "Omic Name",
               error: '<ul class="x-list-plain"><li role="alert">The maximum length for this field is 100</li></ul>'})
], true);
results.clientAbortDestroyedForm = runHandler("clientAbortDestroyedForm", [
    makeField({name: "omicNameField", label: "Omic Name", error: "This field is required"})
], false);
results.clientAbortHiddenOnly = runHandler("clientAbortHiddenOnly", [
    makeField({name: "fileTypeSelector", label: "File Type", visible: false,
               error: "This field is required"})
], true);

// The report: a MORE panel filled in at the bottom of the page, no organism
// chosen at the top. ExtJS renders allowBlank errors wrapped in a <ul>.
results.organismMissing = run("organismMissing", [
    makeField({name: "speciesCombobox", label: "Organism",
               error: '<ul class="x-list-plain"><li role="alert">This field is required</li></ul>'}),
    makeField({name: "conditionsFileSelector", label: "Experimental design:"}),
    makeField({name: "mainFileSelector", label: "Regulator values:"})
], false);

// A custom markInvalid() message: only ever on the active error.
results.customMessage = run("customMessage", [
    makeField({name: "speciesCombobox", label: "Organism"}),
    makeField({name: "tertiaryFileSelector", label: "Annotations file (GTF):",
               error: "Please, provide a GTF file."})
], false);

// A hidden field cannot be shown to anybody: name the first VISIBLE one.
results.hiddenFirst = run("hiddenFirst", [
    makeField({name: "configVars", label: "configVars", visible: false,
               error: "This field is required"}),
    makeField({name: "speciesCombobox", label: "Organism",
               error: "This field is required"})
], false);

// Nothing filled in anywhere: not a field error, and not a bug to report.
results.emptyForm = run("emptyForm", [
    makeField({name: "speciesCombobox", label: "Organism"})
], true);

// Refused with nothing marked: the old wording, kept, and still reportable.
results.nothingMarked = run("nothingMarked", [
    makeField({name: "speciesCombobox", label: "Organism"})
], false);

// A field marked before it was rendered must not take the dialog down.
results.unrenderedField = run("unrenderedField", [
    makeField({name: "ghost", label: "Ghost", error: "This field is required",
               rendered: false})
], false);

// Six shipped labels carry a <br>, and the file widget's inner textfield --
// the one markInvalid() lands on -- is built with that same label.
results.labelMarkup = run("labelMarkup", [
    makeField({name: "speciesCombobox", label: "Organism"}),
    makeField({name: "mainFileSelector", label: "Regions file <br>(BED + Quantification):",
               error: "Please, provide a Data file."})
], false);
// Several errors on one field arrive as several <li>; they must not be glued.
results.twoErrors = run("twoErrors", [
    makeField({name: "jobDescription", label: "Description",
               error: '<ul class="x-list-plain"><li>This field is required</li><li>Maximum length is 100</li></ul>'})
], false);
console.log(JSON.stringify(results));
"""


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-step1-message-")
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


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class InvalidFormNamesTheFieldTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        views, controller, util = read(STEP1_VIEWS), read(JOB_CONTROLLER), read(UTIL_JS)
        pieces = {name: extract_block(views, header, "PA_Step1Views.js")
                  for name, header in VIEW_HEADERS.items()}
        pieces.update({name: extract_block(controller, header, "JobController.js")
                       for name, header in CONTROLLER_HEADERS.items()})
        pieces.update({name: extract_block(util, header, "Util.js")
                       for name, header in UTIL_HEADERS.items()})
        pieces["STEP1_NO_DATA_MESSAGE"] = extract_statement(
            controller, NO_DATA_STATEMENT, "JobController.js")
        cls.results = run_node(HARNESS % pieces)

    def test_it_runs(self):
        for name, result in self.results.items():
            self.assertIsNone(result["threw"], "%s: %s" % (name, result["threw"]))

    def test_the_missing_organism_is_named_and_scrolled_to(self):
        """The reported session, in one assertion."""
        result = self.results["organismMissing"]
        title = result["shown"][0]["title"]
        self.assertIn("Organism", title)
        self.assertIn("This field is required", title)
        self.assertNotIn("<ul", title, "the markup around the error must be stripped")
        self.assertEqual(result["scrolled"], ["speciesCombobox"],
                         "the field the message names is the one brought into view")

    def test_a_custom_field_message_survives(self):
        title = self.results["customMessage"]["shown"][0]["title"]
        self.assertIn("Annotations file (GTF)", title)
        self.assertIn("Please, provide a GTF file.", title)

    def test_a_hidden_field_is_never_the_one_named(self):
        result = self.results["hiddenFirst"]
        title = result["shown"][0]["title"]
        self.assertIn("Organism", title)
        self.assertNotIn("configVars", title)
        self.assertEqual(result["scrolled"], ["speciesCombobox"])

    def test_an_empty_form_says_so_and_is_not_reportable(self):
        entry = self.results["emptyForm"]["shown"][0]
        self.assertIn("Please provide at least", entry["title"])
        self.assertFalse(entry["opts"]["showReportButton"],
                         "an empty form is the user's to fill in, not a bug to report")

    def test_a_refusal_with_nothing_marked_keeps_the_old_wording(self):
        entry = self.results["nothingMarked"]["shown"][0]
        self.assertIn("Please check the form errors", entry["title"])
        self.assertTrue(entry["opts"]["showReportButton"],
                        "nothing marked anywhere is the shape of a bug")

    def test_an_unrendered_field_still_produces_a_message(self):
        entry = self.results["unrenderedField"]["shown"][0]
        self.assertIn("Invalid Form", entry["title"])

    def test_a_label_carrying_markup_is_shown_as_text(self):
        """Regions file <br>(BED + Quantification): the <br> was printed."""
        title = self.results["labelMarkup"]["shown"][0]["title"]
        self.assertIn("Regions file (BED + Quantification)", title)
        self.assertNotIn("br", title.replace("</br>", ""))

    def test_several_errors_on_one_field_are_not_glued(self):
        title = self.results["twoErrors"]["shown"][0]["title"]
        self.assertIn("This field is required \u2014 Maximum length is 100", title)

    def test_a_client_side_abort_names_and_scrolls_to_the_field(self):
        """ExtJS refused inside submit(): the same dialog as checkForm()'s."""
        result = self.results["clientAbortNamesTheField"]
        self.assertIn("Omic Name", result["shown"][0]["title"])
        self.assertIn("The maximum length for this field is 100", result["shown"][0]["title"])
        self.assertEqual(result["scrolled"], ["omicNameField"])

    def test_a_client_side_abort_on_a_destroyed_form_does_not_throw(self):
        """The complex path destroys its temporary form before the handler
        runs; the generic wording, not a TypeError, is what follows."""
        entry = self.results["clientAbortDestroyedForm"]["shown"][0]
        self.assertIn("Please check the form errors", entry["title"])

    def test_a_client_side_abort_never_names_a_hidden_field(self):
        entry = self.results["clientAbortHiddenOnly"]["shown"][0]
        self.assertNotIn("File Type", entry["title"])
        self.assertIn("Please check the form errors", entry["title"])

    def test_every_case_shows_exactly_one_dialog(self):
        for name, result in self.results.items():
            self.assertEqual(len(result["shown"]), 1,
                             "%s showed %d dialogs" % (name, len(result["shown"])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
