#!/usr/bin/env python3
"""New figure kinds plug into the pipeline; nothing dispatches by hand.

Why this exists
---------------
build_bundle used to hold a literal dict of four builders, so every new
archetype (network, pca, venn, nes_dotplot...) would edit the pipeline's core.
The registry inverts it: an archetype registers (builder, values_for) and gets
the sandbox, QA, cap and store-time guarantee for free. These tests pin the
contract: the four built-ins are present at import, ARCHETYPES stays a module
attribute (the make_figure tool validates against it), a registered archetype
renders through the same path, an unknown one is named in the error, and a
name collision with a different builder is refused instead of resolved by
import order.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_archetype_registry_owns_dispatch
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret import figures  # noqa: E402


def _toy_builder(data_slice, spec):
    rows = data_slice.get("features") or []
    tsv = "id\tvalue\n" + "".join("%s\t%s\n" % (r["id"], r["values"][0])
                                  for r in rows)
    return tsv, "print('no-op')\n", "A toy legend.\n"


def _toy_values(data_slice):
    return {r["id"]: {"value": float(r["values"][0])}
            for r in (data_slice.get("features") or [])}


class RegistryTest(unittest.TestCase):

    def test_the_builtins_are_registered_at_import(self):
        for name in ("timecourse", "heatmap", "enrichment", "scatter"):
            self.assertIn(name, figures.ARCHETYPES)

    def test_archetypes_is_still_the_module_attribute_tools_validate_on(self):
        self.assertIsInstance(figures.ARCHETYPES, tuple)
        self.assertEqual(figures.ARCHETYPES, figures.archetype_names())

    def test_registration_extends_archetypes(self):
        figures.register_archetype("toy", _toy_builder, _toy_values)
        try:
            self.assertIn("toy", figures.ARCHETYPES)
        finally:
            figures._REGISTRY.pop("toy", None)
            figures.ARCHETYPES = tuple(figures._REGISTRY)

    def test_a_name_collision_is_refused(self):
        figures.register_archetype("toy", _toy_builder, _toy_values)
        try:
            with self.assertRaises(ValueError):
                figures.register_archetype("toy", lambda a, b: None,
                                           _toy_values)
            # Re-affirming the SAME pair is not a collision.
            figures.register_archetype("toy", _toy_builder, _toy_values)
        finally:
            figures._REGISTRY.pop("toy", None)
            figures.ARCHETYPES = tuple(figures._REGISTRY)

    def test_an_unknown_archetype_is_named_in_the_error(self):
        with self.assertRaises(KeyError) as ctx:
            figures._archetype("hexbin")
        self.assertIn("hexbin", str(ctx.exception))
        self.assertIn("timecourse", str(ctx.exception))

    def test_an_unregistered_callable_pair_is_refused(self):
        with self.assertRaises(ValueError):
            figures.register_archetype("bad", None, _toy_values)
        with self.assertRaises(ValueError):
            figures.register_archetype("", _toy_builder, _toy_values)


class DispatchTest(unittest.TestCase):

    def test_a_registered_archetype_renders_through_the_pipeline(self):
        import shutil
        import tempfile

        figures.register_archetype("toy", _toy_builder, _toy_values)
        outdir = tempfile.mkdtemp(prefix="toyjob-")

        class _Job(object):
            def getOutputDir(self):
                return outdir

        data_slice = {"conditions": ["A"], "colours": {}, "pathways": [],
                      "features": [{"id": "Fos|RNA", "label": "Fos",
                                    "omic": "RNA", "values": [1.5]}]}
        spec = {"archetype": "toy", "conclusion": "toys render", "title": "",
                "width": "single", "has_negative": False, "centre_zero": None,
                "n": 1, "test": None}
        try:
            bundle, (_passed, _lines), result = figures.build_bundle(
                _Job(), "fig1-toy", "toy", data_slice, spec)
            self.assertTrue(result.ok, getattr(result, "stderr_tail", ""))
            self.assertTrue(os.path.isfile(os.path.join(bundle, "data.tsv")))
            self.assertTrue(os.path.isfile(os.path.join(bundle, "qa.json")))
        finally:
            figures._REGISTRY.pop("toy", None)
            figures.ARCHETYPES = tuple(figures._REGISTRY)
            shutil.rmtree(outdir, ignore_errors=True)

    def test_an_empty_slice_is_still_refused_before_the_registry(self):
        figures.register_archetype("toy", _toy_builder, _toy_values)
        try:
            with self.assertRaises(figures.EmptyFigure):
                figures.build_bundle(None, "fig1-toy", "toy",
                                     {"conditions": [], "features": [],
                                      "colours": {}, "pathways": []},
                                     {"archetype": "toy", "conclusion": "x"})
        finally:
            figures._REGISTRY.pop("toy", None)
            figures.ARCHETYPES = tuple(figures._REGISTRY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
