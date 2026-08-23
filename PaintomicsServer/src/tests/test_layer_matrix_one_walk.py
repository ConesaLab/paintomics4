#!/usr/bin/env python3
"""One walk over the job, one table every tool reads.

Why this exists
---------------
ordination, differential statistics and figure slicing each re-derived their
own matrix from the job, three ways, with three sets of silent drops. The
LayerMatrix walks once and counts what it lost. These tests pin: layers come
from the job's own declarations (gene AND compound), condition labels come
from each omic's own header, holes stay NaN instead of becoming zeros, ragged
rows are dropped AND counted, undeclared omics do not invent layers, and
clone deduplication merges identical (label, values) rows while keeping the
user's relevance if ANY clone carried it.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_layer_matrix_one_walk
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret.layer_matrix import LayerMatrix  # noqa: E402

RNA = "Gene expression"
MET = "Metabolomics"


class _OV(object):
    def __init__(self, values, omic, relevant=False):
        self._v, self._o, self._r = values, omic, relevant

    def getOmicName(self):
        return self._o

    def getValues(self):
        return self._v

    def isRelevant(self):
        return self._r


class _Feature(object):
    def __init__(self, name, ovs):
        self._name, self._ovs = name, ovs

    def getName(self):
        return self._name

    def getOmicsValues(self):
        return self._ovs


class _Job(object):
    def __init__(self, genes=None, compounds=None,
                 gene_omics=None, compound_omics=None):
        self._genes = genes or {}
        self._compounds = compounds or {}
        self._gene_omics = gene_omics or []
        self._compound_omics = compound_omics or []

    def getGeneBasedInputOmics(self):
        return self._gene_omics

    def getCompoundBasedInputOmics(self):
        return self._compound_omics

    def getInputGenesData(self):
        return self._genes

    def getInputCompoundsData(self):
        return self._compounds


def _rna_omic(labels=("Day0", "Day7")):
    return {"omicName": RNA, "omicHeader": ["gene"] + list(labels)}


class BuildTest(unittest.TestCase):

    def test_layers_follow_the_jobs_own_declarations(self):
        job = _Job(
            genes={"g1": _Feature("Fos", [_OV([1.0, 2.0], RNA, True)])},
            compounds={"c1": _Feature("Citrate", [_OV([0.5, 0.7], MET)])},
            gene_omics=[_rna_omic()],
            compound_omics=[{"omicName": MET,
                             "omicHeader": ["compound", "Day0", "Day7"]}])
        matrix = LayerMatrix.from_job(job)
        self.assertEqual(sorted(matrix.omics()), sorted([RNA, MET]))
        self.assertEqual(matrix.get(RNA).kind, "gene")
        self.assertEqual(matrix.get(MET).kind, "compound")
        self.assertEqual([l.omic for l in matrix.compound_layers()], [MET])

    def test_columns_come_from_the_omics_own_header(self):
        job = _Job(genes={"g1": _Feature("Fos", [_OV([1.0, 2.0], RNA)])},
                   gene_omics=[_rna_omic(("Control", "Treated"))])
        layer = LayerMatrix.from_job(job).get(RNA)
        self.assertEqual(layer.columns, ["Control", "Treated"])
        self.assertEqual(layer.labels, ["Fos"])
        self.assertEqual(layer.relevant, [False])

    def test_a_hole_stays_nan_never_zero(self):
        job = _Job(genes={"g1": _Feature("Fos", [_OV([1.0, None], RNA)])},
                   gene_omics=[_rna_omic()])
        layer = LayerMatrix.from_job(job).get(RNA)
        self.assertEqual(layer.n_features, 1)
        self.assertTrue(math.isnan(layer.values[0][1]))
        self.assertEqual(layer.n_dropped_nonnumeric, 1)

    def test_numeric_strings_are_numbers(self):
        job = _Job(genes={"g1": _Feature("Fos", [_OV(["1.5", "2"], RNA)])},
                   gene_omics=[_rna_omic()])
        layer = LayerMatrix.from_job(job).get(RNA)
        self.assertEqual(layer.values[0], [1.5, 2.0])
        self.assertEqual(layer.n_dropped_nonnumeric, 0)

    def test_a_ragged_row_is_dropped_and_counted(self):
        job = _Job(genes={"g1": _Feature("Fos", [_OV([1.0, 2.0, 3.0], RNA)]),
                          "g2": _Feature("Jun", [_OV([1.0, 2.0], RNA)])},
                   gene_omics=[_rna_omic()])
        layer = LayerMatrix.from_job(job).get(RNA)
        self.assertEqual(layer.labels, ["Jun"])
        self.assertEqual(layer.n_dropped_ragged, 1)

    def test_an_undeclared_omic_invents_no_layer(self):
        job = _Job(genes={"g1": _Feature("Fos", [_OV([1.0], "Phantomics")])},
                   gene_omics=[_rna_omic()])
        matrix = LayerMatrix.from_job(job)
        self.assertEqual(matrix.omics(), [RNA])

    def test_row_lookup_by_feature_id(self):
        job = _Job(genes={"g1": _Feature("Fos", [_OV([1.0, 2.0], RNA)])},
                   gene_omics=[_rna_omic()])
        layer = LayerMatrix.from_job(job).get(RNA)
        self.assertEqual(layer.row("g1"), [1.0, 2.0])
        self.assertIsNone(layer.row("g9"))


class CloneTest(unittest.TestCase):

    def _layer(self):
        # The same uploaded row mapped to three feature ids; one clone is
        # flagged relevant. A fourth feature shares the label but not the
        # values -- a genuinely different measurement, never merged.
        job = _Job(genes={
            "g1": _Feature("Fos", [_OV([1.0, 2.0], RNA, False)]),
            "g2": _Feature("Fos", [_OV([1.0, 2.0], RNA, True)]),
            "g3": _Feature("Fos", [_OV([1.0, 2.0], RNA, False)]),
            "g4": _Feature("Fos", [_OV([9.0, 9.0], RNA, False)]),
        }, gene_omics=[_rna_omic()])
        return LayerMatrix.from_job(job).get(RNA)

    def test_identical_clones_merge_to_one_row(self):
        dedup = self._layer().deduplicated()
        self.assertEqual(dedup.n_features, 2)
        self.assertEqual(dedup.n_clones_merged, 2)

    def test_relevance_survives_if_any_clone_carried_it(self):
        dedup = self._layer().deduplicated()
        merged = dedup.values.index([1.0, 2.0])
        self.assertTrue(dedup.relevant[merged])

    def test_the_full_view_keeps_its_clones(self):
        self.assertEqual(self._layer().n_features, 4)

    def test_describe_admits_what_was_lost(self):
        text = self._layer().deduplicated().describe()
        self.assertIn("2 clone rows merged", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
