#!/usr/bin/env python3
"""A figure bundle is reproducible, exact, and never colours a lie.

Why this exists
---------------
The bundle is the deliverable: `figure.py` + `data.tsv` must regenerate the
figure for whoever receives them, so the script has to be self-contained (no
import of this package) and the pair has to be deterministic — otherwise
"re-running the script regenerates the figure" is not a statement anyone can
check.

Three failure modes are checked directly because each has a history:

  * **Precision loss on the way to the file.** The values the agent reads are
    rendered to two decimals; a figure must carry the job's own numbers, so
    the TSV writes `repr(float)` and this test round-trips them.
  * **A diverging colour map on single-signed data.** All-positive values on a
    zero-centred map paint half the range in a colour that means "below the
    middle" — this product shipped that defect once already. The template asks
    `figure_style.colormap_for` and records the answer on the spec, so the
    request cannot override the data.
  * **Rainbow/jet.** Never, under any spec.

The generated scripts are compiled, not executed: matplotlib is not a
dependency of the test suite, and the render itself is covered by
`test_a_figure_render_cannot_run_away`.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_figure_templates_are_deterministic
"""
import csv
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import figure_style  # noqa: E402
from src.classes.AIInterpret import figure_templates as ft  # noqa: E402

CONDITIONS = ["WT_aCD40", "WT_aCD40_TLR9", "ROCK1cKO_aCD40",
              "ROCK1cKO_aCD40_TLR9"]
SIGNED = [{"id": "Fos|Gene expression", "label": "Fos", "omic": "Gene expression",
           "values": [1.234567, 2.5, -0.75, 3.14159]},
          {"id": "Fos|Proteomics", "label": "Fos", "omic": "Proteomics",
           "values": [0.5, 0.9, 0.2, 1.1]},
          {"id": "Egr1|Gene expression", "label": "Egr1", "omic": "Gene expression",
           "values": [2.0, 2.1, 2.2, 2.3]}]
POSITIVE = [{"id": "A|g", "label": "A", "omic": "g", "values": [1.0, 2.0, 3.0, 4.0]}]
PATHWAYS = [{"name": "Ribosome", "source": "KEGG", "p": 1e-12,
             "matched": 30, "total": 90},
            {"name": "Apoptosis", "source": "Reactome", "p": 0.004,
             "matched": 5, "total": 60}]

BUILDERS = {"timecourse": ft.build_timecourse, "heatmap": ft.build_heatmap,
            "enrichment": ft.build_enrichment, "scatter": ft.build_scatter}


def _slice(features=None):
    return {"conditions": list(CONDITIONS),
            "features": list(features if features is not None else SIGNED),
            "colours": {}, "pathways": list(PATHWAYS)}


def _spec(archetype, **kw):
    spec = {"archetype": archetype, "conclusion": "Immediate-early genes rise "
            "with TLR9 in both genotypes", "title": "", "width": "single",
            "has_negative": True, "centre_zero": None, "n": 3, "test": None}
    spec.update(kw)
    return spec


class EveryArchetypeTest(unittest.TestCase):

    def test_deterministic_and_compilable(self):
        for name, build in sorted(BUILDERS.items()):
            first = build(_slice(), _spec(name))
            second = build(_slice(), _spec(name))
            self.assertEqual(first, second, "%s is not deterministic" % name)
            data, script, legend = first
            compile(script, "figure.py", "exec")      # compiled, never run
            self.assertTrue(data.endswith("\n"), name)
            self.assertIn(_spec(name)["conclusion"], legend,
                          "%s legend must open with the conclusion" % name)

    def test_the_script_is_self_contained(self):
        """No import of this package: the bundle must run on its own."""
        for name, build in sorted(BUILDERS.items()):
            _data, script, _legend = build(_slice(), _spec(name))
            self.assertNotIn("figure_style", script, name)
            self.assertNotIn("AIInterpret", script, name)
            self.assertIn('matplotlib.use("Agg")', script, name)
            # the three vector/raster outputs are written by save(), which
            # builds the names -- assert the mechanism, not a literal
            self.assertIn('for ext in ("svg", "pdf", "png")', script, name)
            self.assertIn('"figure." + ext', script, name)

    def test_the_panel_label_is_there(self):
        for name, build in sorted(BUILDERS.items()):
            _d, script, _l = build(_slice(), _spec(name))
            self.assertIn("PANEL_LABEL", script, name)

    def test_no_forbidden_colormap_anywhere(self):
        for name, build in sorted(BUILDERS.items()):
            _d, script, _l = build(_slice(), _spec(name))
            for bad in figure_style.FORBIDDEN_CMAPS:
                self.assertNotIn('"%s"' % bad, script, "%s: %s" % (name, bad))


class ValuesSurviveTest(unittest.TestCase):

    def test_data_tsv_round_trips_exactly(self):
        data, _script, _legend = ft.build_timecourse(_slice(), _spec("timecourse"))
        rows = list(csv.reader(io.StringIO(data), delimiter="\t"))
        self.assertEqual(rows[0][1:], CONDITIONS)
        drawn = [float(v) for v in rows[1][1:]]
        self.assertEqual(drawn, SIGNED[0]["values"])
        self.assertEqual(drawn[0], 1.234567, "two-decimal rounding crept in")

    def test_every_condition_is_a_column(self):
        for build in (ft.build_timecourse, ft.build_heatmap):
            data, _s, _l = build(_slice(), _spec("heatmap"))
            rows = list(csv.reader(io.StringIO(data), delimiter="\t"))
            self.assertEqual(len(rows[0]) - 1, len(CONDITIONS))


class ColourMapTest(unittest.TestCase):

    def test_all_positive_data_refuses_a_diverging_map(self):
        spec = _spec("heatmap", centre_zero=True)      # the caller asks for it
        _data, script, legend = ft.build_heatmap(_slice(POSITIVE), spec)
        self.assertEqual(spec["cmap"], figure_style.SEQUENTIAL_CMAP)
        self.assertFalse(spec["centre_zero"], "the data has no negative values")
        self.assertIn(figure_style.SEQUENTIAL_CMAP, script)
        self.assertNotIn(figure_style.DIVERGING_CMAP, script)
        self.assertIn("sequential", legend)

    def test_signed_data_gets_a_symmetric_diverging_map(self):
        spec = _spec("heatmap")
        _data, script, legend = ft.build_heatmap(_slice(), spec)
        self.assertEqual(spec["cmap"], figure_style.DIVERGING_CMAP)
        self.assertTrue(spec["centre_zero"])
        self.assertIn("vmin", script)
        self.assertIn("centred on zero", legend)


class ScatterTest(unittest.TestCase):

    def test_a_feature_in_one_layer_only_is_counted_not_hidden(self):
        data, _script, legend = ft.build_scatter(_slice(), _spec("scatter"))
        rows = list(csv.reader(io.StringIO(data), delimiter="\t"))
        self.assertEqual([r[0] for r in rows[1:]], ["Fos"])   # Egr1 has one layer
        self.assertEqual(rows[0], ["feature", "x_mean", "y_mean"])
        self.assertIn("not shown", legend)


class ValuesContractTest(unittest.TestCase):
    """`values_for` is what QA compares data.tsv against -- they must agree."""

    def test_every_archetype_agrees_with_its_own_tsv(self):
        for name, build in sorted(BUILDERS.items()):
            sl = _slice()
            data, _s, _l = build(sl, _spec(name))
            expected = ft.values_for(name, sl)
            rows = list(csv.reader(io.StringIO(data), delimiter="\t"))
            header, body = rows[0], rows[1:]
            self.assertTrue(body, name)
            for row in body:
                key = row[0]
                self.assertIn(key, expected, "%s: %s missing from values_for" % (name, key))
                for column, cell in zip(header[1:], row[1:]):
                    self.assertIn(column, expected[key], "%s/%s" % (name, column))
                    self.assertAlmostEqual(float(cell), float(expected[key][column]),
                                           places=9, msg="%s %s/%s" % (name, key, column))

    def test_two_measurements_of_one_gene_in_one_layer_stay_distinct(self):
        """The defect a live run's QA check caught: `Rpl18|Gene expression`
        twice, at different values, so the dict kept one and the file had two."""
        dup = [{"id": "a", "label": "Rpl18", "omic": "Gene expression",
                "values": [10.1936, 10.1627, 1.0, 2.0]},
               {"id": "b", "label": "Rpl18", "omic": "Gene expression",
                "values": [10.2129, 10.2160, 1.0, 2.0]}]
        sl = _slice(dup)
        data, _s, _l = ft.build_timecourse(sl, _spec("timecourse"))
        ids = [r.split("\t")[0] for r in data.strip().splitlines()[1:]]
        self.assertEqual(ids, ["Rpl18|Gene expression", "Rpl18|Gene expression#2"])
        expected = ft.values_for("timecourse", sl)
        self.assertEqual(sorted(expected), sorted(ids))
        self.assertAlmostEqual(expected["Rpl18|Gene expression"]["WT_aCD40"], 10.1936)
        self.assertAlmostEqual(expected["Rpl18|Gene expression#2"]["WT_aCD40"], 10.2129)

    def test_a_gene_in_two_layers_is_two_distinct_rows(self):
        sl = _slice()
        data, _s, _l = ft.build_timecourse(sl, _spec("timecourse"))
        ids = [r.split("\t")[0] for r in data.strip().splitlines()[1:]]
        self.assertEqual(ids, ["Fos|Gene expression", "Fos|Proteomics",
                               "Egr1|Gene expression"])
        self.assertEqual(len(set(ids)), len(ids))


if __name__ == "__main__":
    unittest.main(verbosity=2)
