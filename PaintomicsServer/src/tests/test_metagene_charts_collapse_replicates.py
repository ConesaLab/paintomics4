"""The pathway tooltip's metagene charts show one value per condition.

A job whose design (or the replicate detector) collapsed replicate columns is
shown per sample everywhere else on Step 3, but the tooltip drew the raw
metagene trends: 36 "Condition n" columns on a job whose design names 12.
paMetagenesForDisplay() collapses them with the same helper the feature rows
use, and only when the job is in "samples" mode and the omic has a mapping.
"""
import json
import os
import shutil
import subprocess
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", "..", ".."))
CLIENT = os.path.join(REPO_ROOT, "PaintomicsClient", "public_html", "app")
STEP3 = os.path.join(CLIENT, "view", "PathwayAcquisitionViews", "PA_Step3Views.js")
FEATURES = os.path.join(CLIENT, "model", "FeatureModels.js")
NODE = shutil.which("node")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def lift(source, start, end):
    begin = source.index(start)
    return source[begin:source.index(end, begin) + len(end)]


class TooltipUsesTheHelperTest(unittest.TestCase):
    def test_the_tooltip_collapses_its_metagenes(self):
        source = read(STEP3)
        self.assertIn("paMetagenesForDisplay(paJobModel(this), omicDataType[i], "
                      "this.getModel().metagenes[omicDataType[i]])", source)
        self.assertEqual(1, source.count("var paMetagenesForDisplay = function"))


@unittest.skipIf(NODE is None, "node is not available")
class CollapseBehaviourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prelude = (lift(read(FEATURES), "function collapseReplicatesByMapping", "\n}\n") + "\n"
                       + lift(read(STEP3), "var paMetagenesForDisplay = function", "\n};\n") + "\n")

    def run_case(self, mode, mapping, header, values):
        script = self.prelude + """
const model = {
  getReplicateMode: () => %s,
  getGeneBasedInputOmics: () => [],
  getCompoundBasedInputOmics: () => [{omicName: "Metabolomics", replicateMapping: %s, sampleHeader: %s}]
};
const raw = [{name: "Metagene 1", cluster: 2, values: %s}];
const out = paMetagenesForDisplay(model, "Metabolomics", raw);
process.stdout.write(JSON.stringify({out: out, rawUntouched: raw[0].values.length, same: out === raw}));
""" % (json.dumps(mode), json.dumps(mapping), json.dumps(header), json.dumps(values))
        result = subprocess.run([NODE, "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
        return json.loads(result.stdout.decode("utf-8"))

    def test_samples_mode_collapses_to_the_condition_means(self):
        case = self.run_case("samples", [0, 0, 0, 1, 1, 1], ["A", "B"], [1, 2, 3, 4, 5, 6])
        self.assertEqual([2, 5], case["out"][0]["values"])
        self.assertEqual("Metagene 1", case["out"][0]["name"])
        self.assertEqual(2, case["out"][0]["cluster"])
        # The pathway model keeps its raw trends.
        self.assertEqual(6, case["rawUntouched"])

    def test_replicates_mode_leaves_the_trends_alone(self):
        case = self.run_case("replicates", [0, 0, 0, 1, 1, 1], ["A", "B"], [1, 2, 3, 4, 5, 6])
        self.assertTrue(case["same"])

    def test_a_mapping_of_another_width_is_not_applied(self):
        case = self.run_case("samples", [0, 0, 1, 1], ["A", "B"], [1, 2, 3, 4, 5, 6])
        self.assertEqual([1, 2, 3, 4, 5, 6], case["out"][0]["values"])


if __name__ == "__main__":
    unittest.main()
