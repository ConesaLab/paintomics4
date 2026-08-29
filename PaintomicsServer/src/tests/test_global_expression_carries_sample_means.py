"""globalExpressionData must carry the per-condition means.

The store holds `sampleValues` / `sampleRelevant` on every omic value once a
design (or the replicate detector) has collapsed replicate columns, and every
Step 3 chart prefers them in "samples" mode. getGlobalExpressionData() built
its payload by hand with `values` only, so the class activity members' heatmap
drew one cell per replicate: 36 "Condition n" columns on a job whose design
names 12 conditions.
"""
import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", ".."))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from src.classes.Feature import Compound, Gene, OmicValue  # noqa: E402
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob  # noqa: E402


def _omicValue(name, values, sampleValues=None, sampleRelevant=None):
    omicValue = OmicValue(name)
    omicValue.setOriginalName(name)
    omicValue.setOmicName("Metabolomics")
    omicValue.setValues(list(values))
    omicValue.setRelevant([True])
    if sampleValues is not None:
        omicValue.setSampleValues(list(sampleValues))
    if sampleRelevant is not None:
        omicValue.setSampleRelevant(list(sampleRelevant))
    return omicValue


def _job():
    job = PathwayAcquisitionJob.__new__(PathwayAcquisitionJob)
    job.jobID = "TESTGLOBALEXPR"
    job.inputCompoundsData = {}
    job.inputGenesData = {}
    grouped = Compound("C00041")
    grouped.addOmicValue(_omicValue("alanine", range(36), sampleValues=range(12),
                                    sampleRelevant=[True] * 12))
    job.inputCompoundsData["C00041"] = grouped
    plain = Compound("C00187")
    plain.addOmicValue(_omicValue("cholesterol", range(6)))
    job.inputCompoundsData["C00187"] = plain
    gene = Gene("11606")
    gene.addOmicValue(_omicValue("agt", range(36), sampleValues=range(12)))
    job.inputGenesData["11606"] = gene
    return job


class GlobalExpressionCarriesSampleMeansTest(unittest.TestCase):
    def setUp(self):
        self.data = _job().getGlobalExpressionData()

    def test_a_grouped_compound_carries_its_condition_means(self):
        entry = self.data["inputCompound"]["C00041"]
        self.assertEqual(36, len(entry["values"]))
        self.assertEqual(12, len(entry["sampleValues"]))
        self.assertEqual(12, len(entry["sampleRelevant"]))

    def test_a_grouped_gene_carries_them_too(self):
        entry = self.data["inputGene"]["11606"]
        self.assertEqual(12, len(entry["sampleValues"]))

    def test_an_ungrouped_feature_keeps_the_payload_it_always_had(self):
        # tests/baseline compares this payload byte for byte for the example
        # jobs, none of which carry a mapping: no new keys for them.
        entry = self.data["inputCompound"]["C00187"]
        self.assertEqual(6, len(entry["values"]))
        self.assertNotIn("sampleValues", entry)
        self.assertNotIn("sampleRelevant", entry)


if __name__ == "__main__":
    unittest.main()
