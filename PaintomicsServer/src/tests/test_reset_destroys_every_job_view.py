"""Leaving a job must destroy every view the job created, not only the one on screen.

Clicking the PaintOmics wordmark (or Reset) runs JobController.resetButtonClickHandler
-> cleanStoredApplicationData -> MainView.clearSubViews. That method dropped its
references to the step views and called removeAll() on the centre panel, which
destroys whatever is *inside* the panel -- and only that. changeMainView() moves
the outgoing view out of the panel with remove(cmp, false) so a step can be
returned to, so by the time a user reaches the pathway view (Step 4) the Step 1,
2 and 3 components are all detached: alive, rendered, and no longer anyone's.

Measured in Chrome (2026-08-23): from Step 4, wordmark -> "Yes" rendered the
landing page with the AI launcher still in the bottom-right corner, Step 3's
status poll still running against the abandoned job, and Ext.ComponentManager
holding 278 components where a fresh Step 1 holds 132. The launcher survives
because Step 3's `beforedestroy` is the one place that tears it down -- the
widget lives on document.body, outside the panel removeAll() sweeps -- and a
detached component never fires `beforedestroy`. From Step 3 itself the same
click worked, which is why it looked intermittent.

A reset is a promise that nothing of the old job is left. Every subview's
component, detached or not, has to be destroyed.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_reset_destroys_every_job_view
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
MAIN_VIEW = os.path.join(CLIENT_ROOT, "app", "view", "MainView.js")

HEADER = "this.clearSubViews = function()"


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def extract_block(source, header):
    """`header` plus the brace-matched block that follows it."""
    start = source.find(header)
    if start == -1:
        raise AssertionError("%s is missing from MainView.js" % header)
    opening = source.index("{", start + len(header) - 1)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("unbalanced braces after %s" % header)


# The real clearSubViews, driven by stand-ins for the only things it touches:
# the subview map, each view's model/observers, each view's ExtJS component and
# the centre panel. The panel is the ExtJS contract in miniature -- removeAll()
# destroys its own items and nothing else, which is the whole bug.
HARNESS = """
const log = [];
let nObservers = 0;

function makeComponent(name, panel) {
    const cmp = {
        name: name,
        isDestroyed: false,
        ownerCt: null,
        destroy: function () {
            if (cmp.isDestroyed) { log.push("double-destroy:" + name); return; }
            cmp.isDestroyed = true;
            log.push("beforedestroy:" + name);
            // ExtJS Component.destroy detaches from the owner first.
            if (cmp.ownerCt) { cmp.ownerCt.items.splice(cmp.ownerCt.items.indexOf(cmp), 1); cmp.ownerCt = null; }
        }
    };
    return cmp;
}

function makeView(name, cmp, observed) {
    const observers = [];
    const model = {
        getObservers: function () { return observers; },
        deleteObserver: function (o) {
            const i = observers.indexOf(o);
            if (i >= 0) { observers.splice(i, 1); }
        },
        addObserver: function (o) { observers.push(o); }
    };
    const view = {
        name: name,
        component: cmp,
        getName: function () { return name; },
        getModel: function () { return model; },
        // The real getComponent() *creates* the component when it is null:
        // a teardown that went through it would instantiate a view in order
        // to destroy it.
        getComponent: function () {
            if (view.component === null) { log.push("created:" + name); view.component = makeComponent(name); }
            return view.component;
        }
    };
    if (observed) { model.addObserver(view); }
    return view;
}

// The centre panel. removeAll() is ExtJS's: it destroys what it holds.
const panel = {
    items: [],
    add: function (cmp) { panel.items.push(cmp); cmp.ownerCt = panel; },
    removeAll: function () {
        const held = panel.items.slice();
        held.forEach(function (cmp) { cmp.destroy(); });
        panel.items = [];
        log.push("removeAll");
    }
};

function MainView() {
    this.subviews = {};
    this.currentView = null;
    this.getComponent = function () {
        return {queryById: function (id) { if (id !== "mainViewCenterPanel") { throw new Error(id); } return panel; }};
    };
    %(clearSubViews)s
}

// Step 1 and Step 3 were shown and then moved out of the panel for Step 4
// (changeMainView's remove(cmp, false)); Step 4 is the one on screen.
const mv = new MainView();
const step1 = makeView("PA_Step1JobView", makeComponent("PA_Step1JobView"), true);
const step3 = makeView("PA_Step3JobView", makeComponent("PA_Step3JobView"), true);
const step4 = makeView("PA_Step4JobView", makeComponent("PA_Step4JobView"), true);
// A view that was registered but never rendered: its component is still null.
const lazy = makeView("DM_MyDataListView", null, false);
[step1, step3, step4, lazy].forEach(function (v) { mv.subviews[v.getName()] = v; });
panel.add(step4.component);
mv.currentView = step4;

let threw = null;
try { mv.clearSubViews(); } catch (e) { threw = String(e && e.stack || e); }

console.log(JSON.stringify({
    log: log,
    threw: threw,
    destroyed: {
        step1: step1.component.isDestroyed,
        step3: step3.component.isDestroyed,
        step4: step4.component.isDestroyed
    },
    lazyCreated: lazy.component !== null,
    observersLeft: {
        step1: step1.getModel().getObservers().length,
        step3: step3.getModel().getObservers().length,
        step4: step4.getModel().getObservers().length
    },
    subviewsLeft: Object.keys(mv.subviews).length,
    currentView: mv.currentView,
    panelItems: panel.items.length
}));
"""


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-reset-")
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
class ResetDestroysEveryJobViewTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        block = extract_block(read(MAIN_VIEW), HEADER)
        cls.results = run_node(HARNESS % {"clearSubViews": block})

    def test_it_runs(self):
        self.assertIsNone(self.results["threw"], self.results["threw"])

    def test_the_view_on_screen_is_destroyed(self):
        """removeAll() already did this; the fix must not undo it."""
        self.assertTrue(self.results["destroyed"]["step4"])

    def test_a_detached_step_is_destroyed_too(self):
        """The measured bug. Step 3 lived on, and with it the AI launcher,
        its poll timer and ~150 ExtJS components per reset."""
        self.assertTrue(
            self.results["destroyed"]["step3"],
            "a view changeMainView() moved out of the centre panel was "
            "dropped from the map but never destroyed, so its beforedestroy "
            "never ran: the AI widget it owns stays on the page")
        self.assertTrue(self.results["destroyed"]["step1"])

    def test_beforedestroy_runs_once_per_view(self):
        """Destroying the on-screen view both directly and through removeAll()
        would run Step 3-style teardown twice."""
        log = self.results["log"]
        self.assertEqual(
            [entry for entry in log if entry.startswith("double-destroy:")], [])
        self.assertEqual(log.count("beforedestroy:PA_Step4JobView"), 1)

    def test_an_unrendered_view_is_not_built_in_order_to_be_destroyed(self):
        self.assertFalse(
            self.results["lazyCreated"],
            "teardown went through getComponent(), which instantiates a view "
            "whose component is still null")
        self.assertEqual(
            [entry for entry in self.results["log"] if entry.startswith("created:")], [])

    def test_observers_and_bookkeeping_are_cleared(self):
        for step, left in self.results["observersLeft"].items():
            with self.subTest(step=step):
                self.assertEqual(left, 0)
        self.assertEqual(self.results["subviewsLeft"], 0)
        self.assertIsNone(self.results["currentView"])
        self.assertEqual(self.results["panelItems"], 0)


if __name__ == "__main__":
    unittest.main()
