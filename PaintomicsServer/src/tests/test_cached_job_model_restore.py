#!/usr/bin/env python3
"""Regression test for the cached job model that locked users out of the site.

After a job crashed in Step 2, every later load of the application -- the plain
home page included -- rendered "Oops..Internal error!" and nothing else. All the
assets returned 200 and reloading did not help; only
``sessionStorage.removeItem('jobModel')`` brought the site back. The cached model
was 397 KB, jobID 10E1g361L3, stepNumber 2, pathways [].

The cause was one branch of JobInstance.loadFromJSON(): it tested for the
*presence* of the "globalExpressionData" key and then dereferenced its value.
Every model cached before Step 3 stores ``globalExpressionData: null`` (see the
JobInstance constructor), so restoring threw

    TypeError: Cannot read properties of null (reading 'inputGene')

inside Application.launch(). The blanket catch in app.js turned that into the
error dialog, the poisoned copy was never removed from either cache, and the
next load died at exactly the same place -- for good.

Two things are asserted here, because fixing only one leaves the site broken:

  * the model normalises a null globalExpressionData through its own setter, so
    a restored model always carries the {inputGene:{}, inputCompound:{}} shape.
    Merely skipping the branch would leave the field null, and the Step 3/4
    views index it without a guard (PA_Step3Views.js:5343,
    PA_Step4Views.js:4389) -- that moves the crash, it does not fix it;
  * app.js contains the failure: a cache that cannot be read is a cache MISS.
    The restore is wrapped, the real exception is logged, BOTH cached copies
    (sessionStorage "jobModel" and the Dexie "jobs" row) are dropped, and the
    application boots clean.

The behavioural checks execute the shipped JavaScript in node rather than a
Python restatement of it, following test_matching_summary_shapes.py.

Usage:
    cd /Users/tianyuan/Desktop/github_dev/paintomics4
    PYTHONPATH=PaintomicsServer python3 PaintomicsServer/src/tests/test_cached_job_model_restore.py
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

CLIENT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../../PaintomicsClient/public_html"))

APP_JS = os.path.join(CLIENT, "app.js")
MODEL_DIR = os.path.join(CLIENT, "app/model")
MODEL_FILES = ["FeatureModels.js", "PathwayModels.js", "JobInstanceModels.js"]

# The model as it was cached by the crashed job: no pathways, still on Step 2,
# and every Step-3 field left at its constructor default.
POISONED_MODEL = {
    "jobID": "10E1g361L3",
    "stepNumber": 2,
    "timestamp": 1524491415,
    "pathways": [],
    "foundCompounds": [],
    "globalExpressionData": None,
    "hubAnalysisResult": None,
    "compoundRegulateFeatures": None,
}


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def extract_block(source, header, description):
    """Return `header` plus the brace-matched block that follows it.

    Brace matching runs on the raw text; that is adequate for the blocks pulled
    out here (no braces inside strings or regexes) and the extracted text is
    handed to node, which rejects it loudly if that ever stops being true.
    """
    start = source.find(header)
    if start == -1:
        raise AssertionError("%s is missing from app.js -- %s" % (header, description))

    opening = source.index("{", start + len(header) - 1)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("unbalanced braces after %s in app.js" % header)


def run_node(script):
    """Run a script in node and return its parsed stdout."""
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


# Loads the shipped model classes into a sandbox. Model/Observable live in
# Util.js, which cannot run outside a browser (jQuery, Ext), so only those two
# base declarations are stubbed -- everything under test is the real file.
HARNESS = """
const fs = require('fs'), vm = require('vm');
const ctx = {console: console};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext("function Observable(){}; function Model(){}; Model.prototype = new Observable();"
    + "function showWarningMessage(){}; function showErrorMessage(){};"
    + "Date.logFormat = function(){ return ''; };", ctx);
for (const file of %(files)s) {
    vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
}
"""


def harness():
    files = [os.path.join(MODEL_DIR, name) for name in MODEL_FILES]
    return HARNESS % {"files": json.dumps(files)}


class ModelSourceTest(unittest.TestCase):
    """Checks that hold with or without a JavaScript runtime available."""

    def setUp(self):
        self.source = read(os.path.join(MODEL_DIR, "JobInstanceModels.js"))

    def test_restore_does_not_dereference_the_raw_value(self):
        """The exact expression that threw on a null globalExpressionData."""
        self.assertIsNone(
            re.search(r"jsonObject\.globalExpressionData\.", self.source),
            "loadFromJSON dereferences jsonObject.globalExpressionData again; "
            "every model cached before Step 3 stores null there, so restoring "
            "throws inside Application.launch() and blanks the whole site")

    def test_restore_delegates_to_the_guarded_setter(self):
        self.assertIn(
            "this.setGlobalExpressionData(jsonObject.globalExpressionData)",
            self.source,
            "the null guard lives in setGlobalExpressionData(); restoring must "
            "go through it so the field ends up normalised rather than null -- "
            "PA_Step3Views.js:5343 and PA_Step4Views.js:4389 index it unguarded")


class AppSourceTest(unittest.TestCase):
    """The containment in app.js, read off the shipped file."""

    def setUp(self):
        self.source = read(APP_JS)

    def test_recovery_helpers_are_declared_at_module_scope(self):
        """The error dialog calls them from the $(document).ready block.

        Declared inside Application() they would be a ReferenceError, i.e. an
        error dialog whose recovery action is itself broken.
        """
        for helper in ("discardCachedJobModel", "resetPaintomicsSession",
                       "showBootFailureMessage", "openPaintomicsDB"):
            with self.subTest(helper=helper):
                self.assertIsNotNone(
                    re.search(r"^function %s\s*\(" % helper, self.source, re.MULTILINE),
                    "%s() must be a top-level declaration in app.js" % helper)

    def test_no_argument_less_catch_swallows_the_failure(self):
        """The IndexedDB twin used to hide the same exception."""
        self.assertIsNone(
            re.search(r"\.catch\(function\s*\(\s*\)", self.source),
            "an argument-less .catch() is back in app.js: it discards the real "
            "exception and keeps the poisoned row, which is how one bad model "
            "survived every reload")

    def test_discard_removes_both_copies(self):
        """Either copy left behind is re-read on the next load."""
        discard = extract_block(
            self.source, "function discardCachedJobModel(",
            "the cached model has to be dropped from both caches")
        self.assertIn('sessionStorage.removeItem("jobModel")', discard)
        self.assertIn('table("jobs")', discard)

    def test_the_dialog_no_longer_advises_clearing_the_web_cache(self):
        """Wrong advice: it clears neither sessionStorage nor IndexedDB."""
        self.assertNotIn("clear your web cache", self.source)
        self.assertIn("resetPaintomicsSession()", self.source,
                      "the boot error dialog must offer a recovery action that "
                      "actually clears the cached analysis")


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class RestoreBehaviourTest(unittest.TestCase):
    """Runs the shipped JobInstance.loadFromJSON()."""

    def restore(self, jsonObject):
        script = harness() + """
        ctx.payload = %s;
        vm.runInContext("var model = new JobInstance(null);"
            + "model.loadFromJSON(payload);"
            + "result = {"
            + "  normalised: model.getGlobalExpressionData(),"
            + "  fieldIsNull: model.globalExpressionData === null,"
            + "  stepNumber: model.getStepNumber(),"
            + "  jobID: model.getJobID()"
            + "};", ctx);
        process.stdout.write(JSON.stringify(ctx.result));
        """ % json.dumps(jsonObject)
        return run_node(script)

    def test_null_global_expression_data_restores_without_throwing(self):
        """The measured lockout, as a unit test."""
        result = self.restore(POISONED_MODEL)

        self.assertEqual(result["jobID"], "10E1g361L3")
        self.assertEqual(result["stepNumber"], 2)

    def test_null_yields_the_normalised_shape(self):
        result = self.restore(POISONED_MODEL)

        self.assertEqual(result["normalised"], {"inputGene": {}, "inputCompound": {}})
        self.assertFalse(
            result["fieldIsNull"],
            "the field is still null after restoring; the views index it "
            "unguarded, so Step 3 would throw instead of the boot")

    def test_empty_object_is_normalised_too(self):
        payload = dict(POISONED_MODEL, globalExpressionData={})
        result = self.restore(payload)

        self.assertEqual(result["normalised"], {"inputGene": {}, "inputCompound": {}})

    def test_missing_key_does_not_throw(self):
        payload = dict(POISONED_MODEL)
        del payload["globalExpressionData"]

        self.assertEqual(self.restore(payload)["stepNumber"], 2)

    def test_populated_data_is_still_rebuilt_into_omic_values(self):
        """The fix must not cost the Step 3/4 path its OmicValue instances."""
        payload = dict(POISONED_MODEL, globalExpressionData={
            "inputGene": {"mmu:11669": {"omicName": "Gene expression",
                                        "values": ["1.5", "-2.0"],
                                        "relevant": [True, False]}},
            "inputCompound": {"C00022": {"omicName": "Metabolomics",
                                         "values": ["0.25"],
                                         "relevant": [False]}},
        })
        script = harness() + """
        ctx.payload = %s;
        vm.runInContext("var model = new JobInstance(null);"
            + "model.loadFromJSON(payload);"
            + "var gene = model.getGlobalExpressionData().inputGene['mmu:11669'];"
            + "var comp = model.getGlobalExpressionData().inputCompound['C00022'];"
            + "result = {"
            + "  geneIsOmicValue: gene instanceof OmicValue,"
            + "  geneValues: gene.getValues(),"
            + "  compIsOmicValue: comp instanceof OmicValue,"
            + "  compValues: comp.getValues()"
            + "};", ctx);
        process.stdout.write(JSON.stringify(ctx.result));
        """ % json.dumps(payload)
        result = run_node(script)

        self.assertTrue(result["geneIsOmicValue"])
        self.assertTrue(result["compIsOmicValue"])
        # Strings in, floats out: OmicValue.loadFromJSON coerces them.
        self.assertEqual(result["geneValues"], [1.5, -2.0])
        self.assertEqual(result["compValues"], [0.25])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ContainmentBehaviourTest(unittest.TestCase):
    """Runs the shipped Application.restoreCachedModel()."""

    @classmethod
    def setUpClass(cls):
        cls.restore_source = extract_block(
            read(APP_JS), "this.restoreCachedModel = function",
            "restoring a cached model must not be able to take the boot down")

    def run_restore(self, model_js):
        script = harness() + """
        vm.runInContext(%s, ctx);
        vm.runInContext("var discarded = [];"
            + "function discardCachedJobModel(jobID) { discarded.push(jobID === undefined ? null : jobID); }"
            + "var app = {};"
            + "(function(){ " + %s + " }).call(app);"
            + "var restored = app.restoreCachedModel(model, payload);"
            + "result = {restored: restored, discarded: discarded};", ctx);
        process.stdout.write(JSON.stringify(ctx.result));
        """ % (json.dumps(model_js), json.dumps(self.restore_source))
        return run_node(script)

    def test_a_model_that_cannot_be_restored_becomes_a_cache_miss(self):
        """Whatever the reason, the cache is dropped and the boot survives."""
        broken = ("var payload = {jobID: '10E1g361L3'};"
                  "var model = {loadFromJSON: function() {"
                  "  throw new TypeError(\"Cannot read properties of null (reading 'inputGene')\");"
                  "}};")
        result = self.run_restore(broken)

        self.assertFalse(result["restored"])
        self.assertEqual(result["discarded"], ["10E1g361L3"],
                         "the poisoned model must be discarded by jobID, or the "
                         "next load reads it back and fails identically")

    def test_a_readable_model_is_kept(self):
        good = ("var payload = {jobID: '10E1g361L3'};"
                "var loaded = false;"
                "var model = {loadFromJSON: function() { loaded = true; }};")
        result = self.run_restore(good)

        self.assertTrue(result["restored"])
        self.assertEqual(result["discarded"], [],
                         "a cache that restored fine must never be discarded")

    def test_the_real_poisoned_model_now_restores(self):
        """End to end: the shipped model class through the shipped guard."""
        real = ("var payload = %s;"
                "var model = new JobInstance(null);" % json.dumps(POISONED_MODEL))
        result = self.run_restore(real)

        self.assertTrue(result["restored"])
        self.assertEqual(result["discarded"], [])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class SyntaxTest(unittest.TestCase):
    """A syntax error in app.js is the same blank page by another route."""

    def test_edited_files_parse(self):
        for path in [APP_JS, os.path.join(MODEL_DIR, "JobInstanceModels.js")]:
            with self.subTest(path=os.path.basename(path)):
                completed = subprocess.run(
                    ["node", "--check", path], capture_output=True, text=True, timeout=60)
                self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
