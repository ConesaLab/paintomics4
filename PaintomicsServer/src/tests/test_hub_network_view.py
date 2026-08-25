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


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
