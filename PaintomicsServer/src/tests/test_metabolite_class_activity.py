#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Guards for compundsClassification() -- the metabolite class activity analysis.

Four properties of that method are load bearing and none of them had a test.
All four were found while building a chart on top of the payload it produces;
each is invisible in the current grid because the grid draws neither the
proportion the test measured nor the null it was measured against.

  1. The background counts DISTINCT compounds. br08001 files 33 of its 621
     compounds under more than one level-2 class -- C00246 is both a
     Carboxylic acid and a Fatty acid, C00002 is both a Nucleotide and a
     Cofactor. Summing the per-class lists counted those twice, and under
     "generate automatically" that inflated denominator IS the null
     proportion p0 handed to binomtest, so it moved every class's p-value.

  2. Adjusted p-values are NOT rounded in transport. round(p, 4) mapped every
     adjusted p below 1e-4 to exactly 0.0, so -log10(FDR) is +Inf for exactly
     the classes with the strongest evidence.

  3. Every tested class reports its BRITE level-1 parent. The walk always had
     it and dropped it, which is why nine steroid classes reach the client
     named "18-Carbon atoms" .. "30-Carbon atoms" with nothing marking them as
     steroids.

  4. The null proportion each condition was judged against is reported, along
     with whether it came from the user or was derived. It differs per
     condition in the derived case, so a client cannot reconstruct it.

The method needs only inputCompoundsData and the neighbour map off `self`, so
the tests drive it on a bare instance with the neighbour lookup stubbed -- that
lookup reads a per-organism KEGG file and is a separate concern.
"""

import os
import sys
import unittest
from unittest import mock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", ".."))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob


class _OmicValue(object):
    """The two fields compundsClassification reads off omicsValues[0]."""

    def __init__(self, relevant, values, inputName):
        self.relevant = relevant
        self.values = values
        self.inputName = inputName


class _Compound(object):
    def __init__(self, relevant, values, inputName):
        self.omicsValues = [_OmicValue(relevant, values, inputName)]


def _job(compounds):
    """A PathwayAcquisitionJob carrying nothing but the compounds under test."""
    job = PathwayAcquisitionJob.__new__(PathwayAcquisitionJob)
    job.inputCompoundsData = compounds
    job.compoundRegulateFeatures = None
    job.organism = "hsa"
    return job


def _run(job, threshold=None):
    payload = {} if threshold is None else {"thresholdMetaboliteClass": threshold}
    with mock.patch.object(PathwayAcquisitionJob,
                           "getCompoundRegulateFeatures", return_value={}):
        return job.compundsClassification(payload)


# C00246 and C01585 are each filed under BOTH "Carboxylic acids" and
# "Fatty acids"; C00158 (citrate) is filed under Carboxylic acids alone.
DOUBLE_FILED = ["C00246", "C01585"]
SINGLE_FILED = ["C00158"]


class BackgroundCountsDistinctCompoundsTest(unittest.TestCase):

    def test_a_compound_in_two_classes_is_counted_once(self):
        ids = DOUBLE_FILED + SINGLE_FILED
        job = _job({cid: _Compound(True, [1.0], cid) for cid in ids})
        _, _, classificationDict, _, _, _, featureSummary, _ = _run(job)

        # Both classes are populated, and the two double-filed compounds appear
        # in each -- so the per-class lists sum to more than the compound count.
        summed = sum(len(v) for v in classificationDict.values())
        self.assertGreater(summed, len(ids),
                           "expected the fixture to actually exercise double filing")

        self.assertEqual(featureSummary[0], len(ids),
                         "totalFeatures must be distinct compounds, not the sum "
                         "of the per-class lists")

    def test_the_derived_null_cannot_exceed_one(self):
        # Every compound relevant => the derived null is relevant/total. With a
        # double-counted denominator the numerator was also double counted, so
        # the ratio stayed near 1; the guard here is that it is exactly 1 and
        # that both halves now count the same compounds.
        ids = DOUBLE_FILED + SINGLE_FILED
        job = _job({cid: _Compound(True, [1.0], cid) for cid in ids})
        _run(job)
        self.assertEqual(job.classificationMeta["nullProportion"], [1.0])


class AdjustedPValuesKeepTheirPrecisionTest(unittest.TestCase):

    def test_a_strong_class_does_not_round_to_zero(self):
        # 25 relevant compounds against a null of 0.05 gives an adjusted p far
        # below 1e-4. Rounded to 4 decimals that is 0.0, and -log10(0) is inf.
        import json as _json
        with open(os.path.join(SERVER_ROOT, "src", "common", "br08001.json")) as handle:
            tree = _json.load(handle)
        aminoAcids = []
        for level1 in tree["children"]:
            for level2 in level1["children"]:
                if level2["name"] != "Amino acids":
                    continue
                for level3 in level2["children"]:
                    for leaf in level3["children"]:
                        aminoAcids.append(leaf["name"].split()[0])
        ids = sorted(set(aminoAcids))[:25]

        job = _job({cid: _Compound(True, [1.0], cid) for cid in ids})
        _, _, _, _, adjustPvalue, _, _, _ = _run(job, threshold="0.05")

        adjusted = adjustPvalue[0]["FDR BH"]["Amino acids"]
        self.assertGreater(adjusted, 0.0,
                           "an adjusted p rounded to 0.0 makes -log10(FDR) infinite")
        self.assertLess(adjusted, 1e-4,
                        "expected the fixture to land below the old rounding floor")


class ClassesReportTheirParentAndNullTest(unittest.TestCase):

    def test_every_tested_class_names_its_brite_parent(self):
        # C00037 is filed under both "Amino acids" (Peptides) and
        # "Neurotransmitters" (Hormones and transmitters) -- two different
        # level-1 groups, so a single lookup table cannot be keyed on the leaf.
        job = _job({"C00037": _Compound(True, [1.0], "C00037")})
        _, _, classificationDict, _, _, _, _, _ = _run(job)

        parents = job.classificationMeta["parents"]
        self.assertEqual(set(parents), set(classificationDict),
                         "every tested class must report a parent")
        self.assertEqual(parents["Amino acids"], "Peptides")
        self.assertEqual(parents["Neurotransmitters"], "Hormones and transmitters")

    def test_a_user_threshold_is_reported_verbatim_and_labelled(self):
        job = _job({"C00158": _Compound(True, [1.0], "C00158")})
        _run(job, threshold="0.30")
        self.assertEqual(job.classificationMeta["nullProportion"], [0.30])
        self.assertEqual(job.classificationMeta["thresholdSource"], "user")

    def test_a_derived_threshold_is_labelled_auto_and_is_per_condition(self):
        # Two conditions, different relevance in each: the derived null is a
        # per-condition quantity, so one number would be wrong for one of them.
        job = _job({
            "C00158": _Compound([True, False], [1.0, 1.0], "C00158"),
            "C00042": _Compound([True, False], [1.0, 1.0], "C00042"),
        })
        _run(job)
        meta = job.classificationMeta
        self.assertEqual(meta["thresholdSource"], "auto")
        self.assertEqual(len(meta["nullProportion"]), 2)
        self.assertEqual(meta["nullProportion"][0], 1.0)
        self.assertEqual(meta["nullProportion"][1], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
