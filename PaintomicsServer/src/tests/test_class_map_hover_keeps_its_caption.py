#!/usr/bin/env python3
"""Hovering a mark on the metabolite class map must not move the map.

Why this exists
---------------
Pointing at a mark on the class map (Step 3, "Metabolite class activity
analysis") made it flash on and off for as long as the cursor stayed there.
Reproduced in Chrome on job PU14YF2L61 with the cursor held still on the
"Amino acids" mark, counting the mark's own events for two seconds:

    mouseenter 54   mouseleave 54

and the layout at every one of them, caption height / SVG top, in px:

    enter 21/158  leave 56/193  enter 21/158  leave 56/193  ...

The chart's caption (#classActivityMapSummary) sits directly above the SVG and
doubles as the hover readout: focusClass() swapped the resting three-line
sentence for a one-line readout by assigning summary.innerHTML. The paragraph
lost two lines, the SVG rose 35px, and the mark slid out from under a cursor
that had not moved. Chrome then dispatched mouseleave, focusClass() put the
three lines back, the mark slid back under the cursor, mouseenter -- 27 times
a second. The "shine" was the focus stroke toggling at that rate.

The fix keeps the resting caption in the flow, where it sizes the paragraph,
and lays the readout over it (position: absolute, the caption's text hidden
but still occupying its lines). Nothing above the SVG changes height on
hover, so nothing under the cursor moves.

These tests run the shipped focusClass() -- the real function extracted from
PA_Step3Views.js, not a re-implementation -- in node against a stub DOM whose
innerHTML setter discards the children, as a browser's does. Before the fix
the resting caption is gone after one hover; after it, it is intact.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_class_map_hover_keeps_its_caption
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
    os.path.dirname(__file__), "..", "..", "..",
    "PaintomicsClient", "public_html"))

STEP3_VIEWS = os.path.join(CLIENT, "app", "view", "PathwayAcquisitionViews",
                           "PA_Step3Views.js")
MAIN_CSS = os.path.join(CLIENT, "resources", "css", "main.css")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def method(source, name):
    """The text of `this.<name> = function (...) {...}`, brace-matched."""
    match = re.search(r"this\.%s\s*=\s*function" % re.escape(name), source)
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


# A DOM with exactly the behaviour the bug depends on: assigning innerHTML
# replaces every child, so a caption that is swapped rather than overlaid
# disappears. querySelector understands one class selector, which is all
# focusClass() asks of it.
STUB_DOM = r"""
function el(cls, html) {
    var node = {
        cls: cls, children: [], attrs: {}, _html: html || "",
        classList: {
            _set: {},
            add: function (c) { this._set[c] = true; },
            remove: function (c) { delete this._set[c]; },
            contains: function (c) { return !!this._set[c]; },
            toggle: function (c, force) {
                var on = (force === undefined) ? !this._set[c] : !!force;
                if (on) { this._set[c] = true; } else { delete this._set[c]; }
                return on;
            }
        },
        getAttribute: function (n) { return this.attrs.hasOwnProperty(n) ? this.attrs[n] : null; },
        setAttribute: function (n, v) { this.attrs[n] = String(v); },
        querySelector: function (sel) {
            var c = sel.replace(/^\./, "");
            for (var i = 0; i < this.children.length; i++) {
                if (this.children[i].cls === c) { return this.children[i]; }
            }
            return null;
        },
        querySelectorAll: function () { return []; }
    };
    Object.defineProperty(node, "innerHTML", {
        get: function () { return this._html; },
        set: function (v) { this._html = v; this.children = []; }
    });
    return node;
}

var RESTING = "<b>0</b> of 9 classes at FDR &lt; 0.05 &middot; tested against the rest of this job";
var base = el("paClassMapBase", RESTING);
var readout = el("paClassMapReadout", "");
var summary = el("paClassMapSummary", "");
summary.children = [base, readout];
summary.attrs["data-base"] = RESTING;
var map = el("paClassMap", "");

var document = {
    getElementById: function (id) {
        if (id === "classActivityMapSummary") { return summary; }
        if (id === "classActivityMap") { return map; }
        return null;
    }
};

var classMapRowsCache = [{
    name: "Amino acids", parent: "Peptides", k: 0, n: 7, proportion: 0,
    p: 1, fdr: 1, up: 0, down: 0, significant: false
}];
var classMapHasDirection = false;
function classMapEscape(v) { return String(v); }
function classMapFormatP(v) { return Number(v).toFixed(4); }

var me = {};
"""


def run_in_node(body):
    """Evaluate `body` with the shipped focusClass() bound to `me`."""
    source = read(STEP3_VIEWS)
    script = "\n".join([
        STUB_DOM,
        "(function () {\n" + method(source, "focusClass") + "\n}).call(me);",
        body,
    ])
    directory = tempfile.mkdtemp(prefix="paintomics-classmap-")
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


def snapshot():
    return """
    console.log(JSON.stringify({
        base: summary.querySelector(".paClassMapBase") && summary.querySelector(".paClassMapBase").innerHTML,
        readout: summary.querySelector(".paClassMapReadout") && summary.querySelector(".paClassMapReadout").innerHTML,
        focused: summary.classList.contains("paIsFocused")
    }));
    """


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class FocusClassTest(unittest.TestCase):

    def test_hover_leaves_the_resting_caption_in_place(self):
        """The caption sizes the paragraph; the readout must not replace it."""
        result = run_in_node('me.focusClass("Amino acids");' + snapshot())

        self.assertIsNotNone(
            result["base"],
            "focusClass() replaced the caption with the readout. The caption "
            "is what gives the paragraph its height, and the SVG sits directly "
            "under it: a shorter readout lifts the map out from under the "
            "cursor, Chrome fires mouseleave, the caption comes back, the map "
            "drops, mouseenter -- 27 times a second, which is the flashing.")
        self.assertIn("0</b> of 9 classes", result["base"])
        self.assertTrue(result["focused"], "the summary was not marked focused")
        self.assertIn("Amino acids", result["readout"] or "",
                      "the readout was not written for the hovered class")

    def test_unhover_clears_the_readout_and_keeps_the_caption(self):
        result = run_in_node(
            'me.focusClass("Amino acids"); me.focusClass(null);' + snapshot())

        self.assertFalse(result["focused"])
        self.assertEqual(result["readout"], "")
        self.assertIn("0</b> of 9 classes", result["base"] or "")

    def test_an_unknown_class_changes_nothing(self):
        result = run_in_node('me.focusClass("No such class");' + snapshot())

        self.assertFalse(result["focused"])
        self.assertEqual(result["readout"], "")
        self.assertIn("0</b> of 9 classes", result["base"] or "")


class SourceStructureTest(unittest.TestCase):
    """Holds with or without a JavaScript runtime available."""

    def test_the_readout_is_laid_over_the_caption_not_in_its_flow(self):
        """position: absolute is what keeps the paragraph's height fixed."""
        css = read(MAIN_CSS)
        rule = re.search(
            r"\.paClassMapSummary\s+\.paClassMapReadout\s*\{([^}]*)\}", css)
        self.assertIsNotNone(rule, "main.css has no .paClassMapSummary "
                                   ".paClassMapReadout rule")
        self.assertIn("position: absolute", rule.group(1))

        hidden = re.search(
            r"\.paClassMapSummary\.paIsFocused\s+\.paClassMapBase\s*\{([^}]*)\}", css)
        self.assertIsNotNone(hidden, "the focused caption is never hidden")
        # visibility keeps the lines in the layout; display: none would collapse
        # them and bring the bug straight back.
        self.assertIn("visibility: hidden", hidden.group(1))
        self.assertNotIn("display", hidden.group(1))

    def test_draw_class_map_builds_both_halves_of_the_caption(self):
        source = read(STEP3_VIEWS)
        draw = method(source, "drawClassMap")
        for cls in ("paClassMapBase", "paClassMapReadout"):
            self.assertTrue(cls in draw,
                            "drawClassMap() no longer writes a .%s span" % cls)

    def test_the_view_still_parses(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed")
        completed = subprocess.run(
            ["node", "--check", STEP3_VIEWS], capture_output=True, text=True,
            timeout=60)
        self.assertEqual(completed.returncode, 0,
                         "%s does not parse:\n%s" % (STEP3_VIEWS, completed.stderr))


if __name__ == "__main__":
    unittest.main(verbosity=2)
