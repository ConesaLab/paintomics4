#!/usr/bin/env python3
"""Every new archetype renders a fixture through the REAL pipeline, QA 8/8.

Why this exists
---------------
An archetype that only ever ran in its author's head fails on its first live
slice -- the network archetype failed twice on its first real subgraph
(label collisions) before this kind of test existed for it. Each fixture
here goes through build_bundle: template writer, subprocess sandbox render,
and the full QA battery. The assertion is `passed` -- all checks, not most.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_new_archetypes_pass_figure_qa
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import figures  # noqa: E402


def _spec(archetype, conclusion, **kw):
    base = {"archetype": archetype, "conclusion": conclusion, "title": "",
            "width": "single", "has_negative": True, "centre_zero": None,
            "n": 0, "test": None}
    base.update(kw)
    return base


SLICES = {
    "network": (
        {"pathway": {"id": "mmu04110", "name": "Cell cycle"},
         "edges": [
             {"from": "miR-9", "to": "Fos", "coefficient": -1.2,
              "evidence": "supported", "condition": "T1"},
             {"from": "miR-9", "to": "Jun", "coefficient": 0.8,
              "evidence": "novel", "condition": "T2"},
             {"from": "Ikzf1", "to": "Ccnd2", "coefficient": 2.4,
              "evidence": "unsupported", "condition": "T1"}],
         "features": [1], "conditions": [], "colours": {}, "pathways": []},
        _spec("network", "Regulators converge on the cell cycle.")),
    "pca": (
        {"samples": [
            {"name": "A_rep1", "condition": "A", "pc1": -5.0, "pc2": 0.1},
            {"name": "A_rep2", "condition": "A", "pc1": -4.8, "pc2": -0.2},
            {"name": "A_rep3", "condition": "A", "pc1": -5.2, "pc2": 0.0},
            {"name": "B_rep1", "condition": "B", "pc1": 5.1, "pc2": 0.2},
            {"name": "B_rep2", "condition": "B", "pc1": 4.9, "pc2": -0.1},
            {"name": "B_rep3", "condition": "B", "pc1": 5.0, "pc2": 0.1}],
         "pc1_percent": 92.3, "pc2_percent": 3.1, "n_features": 500,
         "features": [1], "conditions": [], "colours": {}, "pathways": []},
        _spec("pca", "The conditions separate on PC1.")),
    "samplecorr": (
        {"samples": ["A_rep1", "A_rep2", "B_rep1", "B_rep2"],
         "matrix": [[1.0, 0.95, 0.60, 0.62],
                    [0.95, 1.0, 0.61, 0.63],
                    [0.60, 0.61, 1.0, 0.96],
                    [0.62, 0.63, 0.96, 1.0]],
         "features": [1], "conditions": [], "colours": {}, "pathways": []},
        _spec("samplecorr", "Replicates agree within conditions.")),
    "venn": (
        {"sets": [{"name": "RNA", "members": ["FOS", "JUN", "MYC", "EGFR"]},
                  {"name": "Protein", "members": ["FOS", "JUN", "AKT1"]}],
         "features": [1], "conditions": [], "colours": {}, "pathways": []},
        _spec("venn", "Two layers share most of their changed features.")),
    "upset": (
        {"sets": [{"name": "RNA", "members": ["FOS", "JUN", "MYC"]},
                  {"name": "Protein", "members": ["FOS", "JUN", "AKT1"]},
                  {"name": "Metab", "members": ["FOS", "CIT", "AKT1"]}],
         "features": [1], "conditions": [], "colours": {}, "pathways": []},
        _spec("upset", "Three layers overlap unevenly.")),
    "concordance": (
        {"omic_a": "RNA", "omic_b": "Protein",
         "quadrants": {"++": 2, "--": 1, "+-": 1, "-+": 0},
         "agreement": 0.75,
         "features": [{"feature": "FOS", "x": 2.0, "y": 1.0},
                      {"feature": "JUN", "x": 1.5, "y": 0.4},
                      {"feature": "MYC", "x": -1.0, "y": -0.5},
                      {"feature": "EGFR", "x": 0.7, "y": -0.3}],
         "conditions": [], "colours": {}, "pathways": []},
        _spec("concordance", "Directions mostly agree across layers.")),
}


class _Job(object):
    def __init__(self, outdir):
        self._outdir = outdir

    def getOutputDir(self):
        return self._outdir


class RenderAllTest(unittest.TestCase):

    def _render(self, archetype):
        data_slice, spec = SLICES[archetype]
        outdir = tempfile.mkdtemp(prefix="qa8-%s-" % archetype)
        try:
            bundle, (passed, lines), result = figures.build_bundle(
                _Job(outdir), "fig-%s" % archetype, archetype,
                data_slice, spec)
            self.assertTrue(result.ok,
                            "%s render failed: %s"
                            % (archetype, getattr(result, "stderr_tail", "")))
            failures = [l for l in lines if "FAIL" in l.upper()]
            self.assertTrue(passed,
                            "%s QA not clean:\n%s"
                            % (archetype, "\n".join(failures)))
        finally:
            shutil.rmtree(outdir, ignore_errors=True)


def _add(archetype):
    def test(self):
        self._render(archetype)
    test.__name__ = "test_%s_renders_qa_clean" % archetype
    setattr(RenderAllTest, test.__name__, test)


for _name in SLICES:
    _add(_name)


class RefusalTest(unittest.TestCase):

    def test_a_four_set_venn_is_refused_toward_upset(self):
        data_slice, spec = SLICES["venn"]
        four = dict(data_slice,
                    sets=[{"name": n, "members": ["X"]} for n in "ABCD"])
        with self.assertRaises(ValueError) as ctx:
            figures.build_bundle(_Job(tempfile.mkdtemp()), "fig-v4", "venn",
                                 four, spec)
        self.assertIn("upset", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
