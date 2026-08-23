#!/usr/bin/env python3
"""A figure with no rows must never be drawn.

Why this exists
---------------
A live run asked for a scatter over ten purine-metabolism genes. Not one of
them was measured in BOTH layers, so the slice came out with a header and no
rows -- and the bundle rendered anyway: 23 kB of empty axes, a legend that
said "10 feature(s) carried by only one layer are not shown", and a QA line
reporting the emptiness after the figure slot was already spent.

That mattered more than it looks, because the store-time guarantee shows
every figure to the reader. An empty panel used to be a wasted slot; it is
now certain to reach the page.

So the refusal moves to where the agent can still choose differently: no
bundle is written, the slot is handed back, and the message says WHICH way
the slice came out empty.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_an_empty_figure_is_never_drawn
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import figures  # noqa: E402

CONDITIONS = ["GM", "M"]
FEATURE = {"id": "Fos|Gene expression", "label": "Fos", "omic": "Gene expression",
           "values": [1.0, 2.0]}


def _slice(features):
    return {"conditions": list(CONDITIONS), "features": list(features),
            "colours": {}, "pathways": []}


def _spec(archetype):
    return {"archetype": archetype, "conclusion": "Purine metabolism shifts",
            "title": "", "width": "single", "has_negative": False,
            "centre_zero": None, "n": 0, "test": None}


class RefusalTest(unittest.TestCase):

    def _build(self, archetype, features):
        return figures.build_bundle(None, "fig1-x", archetype,
                                    _slice(features), _spec(archetype))

    def test_a_scatter_with_nothing_in_both_layers_is_refused(self):
        # One layer only -- exactly the live failure.
        with self.assertRaises(figures.EmptyFigure) as caught:
            self._build("scatter", [FEATURE])
        self.assertIn("BOTH layers", str(caught.exception))

    def test_no_features_at_all_is_refused(self):
        for archetype in ("timecourse", "heatmap", "scatter"):
            with self.assertRaises(figures.EmptyFigure):
                self._build(archetype, [])

    def test_the_reason_names_what_to_do_instead(self):
        reason = figures._empty_reason("scatter", _slice([FEATURE]))
        self.assertIn("timecourse", reason, "it must offer a way forward")
        reason = figures._empty_reason("timecourse", _slice([]))
        self.assertIn("nothing to draw", reason)

    def test_an_enrichment_with_no_pathways_is_refused(self):
        with self.assertRaises(figures.EmptyFigure):
            figures.build_bundle(None, "fig1-x", "enrichment",
                                 {"conditions": CONDITIONS, "features": [],
                                  "colours": {}, "pathways": []},
                                 _spec("enrichment"))

    def test_a_slice_with_rows_still_builds(self):
        # Guard against a refusal that fires on real data: two layers, so the
        # scatter has one point. It must get past the emptiness check -- what
        # happens after (render, QA) is covered elsewhere, so only the
        # EmptyFigure path is asserted here.
        both = [FEATURE, {"id": "Fos|Proteomics", "label": "Fos",
                          "omic": "Proteomics", "values": [3.0, 4.0]}]
        try:
            figures.build_bundle(None, "fig1-x", "scatter", _slice(both),
                                 _spec("scatter"))
        except figures.EmptyFigure:
            self.fail("a scatter with a feature in both layers was refused")
        except Exception:
            pass          # writing/rendering needs a job; not this test's job


if __name__ == "__main__":
    unittest.main(verbosity=2)
