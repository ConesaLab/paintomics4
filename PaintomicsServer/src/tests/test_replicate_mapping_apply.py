#!/usr/bin/env python3
"""Cover for the replicate-aggregation bridge on PathwayAcquisitionJob.

applyReplicateMappingForOmic and _walkAndAggregateOmicValues are what turn a
replicate grouping into per-sample numbers on every Feature. They sit between
two pieces that are already tested in isolation -- detect_replicates /
aggregate_replicates on one side, the Step 2/4 renderers on the other -- and
were themselves untested, which is a bad place for a gap: this is where a
mis-indexed group stops being a unit-test abstraction and becomes a wrong mean
written onto a real gene.

It is the single source of truth for the aggregation step, reached from two
callers: the auto-apply inside processFilesContent, and the
/pa_apply_replicate_mapping endpoint (auto / manual / off).

Contracts pinned here
---------------------
* "off" clears sampleValues/sampleRelevant rather than leaving stale numbers
  behind. A user who turns aggregation off after turning it on must not keep
  seeing the aggregated view.
* "auto" refuses anything other than detection status "complete". Aggregating
  a "partial" detection would silently merge columns the detector could not
  account for.
* Aggregation touches only the named omic. A job with several omics must not
  have the others rewritten underneath it.
* A ragged feature -- fewer values than the header has columns -- must not
  raise. That is the ReplicateDetection IndexError, reached the way a real job
  reaches it: through a Feature whose row was short.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_replicate_mapping_apply
"""
import math
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Feature import Gene, OmicValue
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob


def makeGene(geneID, omicName, values, relevant=None):
    gene = Gene(geneID)
    ov = OmicValue(geneID)
    ov.setOmicName(omicName)
    ov.setValues(values)
    if relevant is not None:
        ov.setRelevant(relevant)
    gene.addOmicValue(ov)
    return gene


class ApplyReplicateMappingTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="repmap_")
        self.job = PathwayAcquisitionJob("JOB1", "u1", self.tmp + os.sep)
        self.omicName = "Gene expression"
        # Two samples of two replicates each: S1_R1 S1_R2 S2_R1 S2_R2
        self.detection = {
            "status": "complete",
            "sampleHeader": ["S1", "S2"],
            "mapping": [0, 0, 1, 1],
            "groups": [[0, 1], [2, 3]],
            "unmatched": [],
        }
        self.job.geneBasedInputOmics = [{
            "omicName": self.omicName,
            "omicHeader": ["ID", "S1_R1", "S1_R2", "S2_R1", "S2_R2"],
            "replicateDetection": dict(self.detection),
        }]
        self.job.inputGenesData = {
            "G1": makeGene("G1", self.omicName, [1.0, 3.0, 10.0, 20.0]),
            "G2": makeGene("G2", self.omicName, [2.0, 2.0, 4.0, 8.0]),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def firstOmicValue(self, geneID="G1"):
        return self.job.inputGenesData[geneID].getOmicsValues()[0]


class AutoModeTest(ApplyReplicateMappingTestCase):

    def test_reports_what_it_did(self):
        result = self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["mode"], "auto")
        self.assertEqual(result["sampleHeader"], ["S1", "S2"])
        self.assertEqual(result["featureType"], "Gene")
        self.assertEqual(result["featuresUpdated"], 2)

    def test_writes_per_sample_means_onto_every_feature(self):
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        self.assertEqual(self.firstOmicValue("G1").sampleValues, [2.0, 15.0])
        self.assertEqual(self.firstOmicValue("G2").sampleValues, [2.0, 6.0])

    def test_records_the_grouping_on_the_input_omic(self):
        """Step 2/4 read these back off the omic to label columns."""
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        omic = self.job.geneBasedInputOmics[0]
        self.assertEqual(omic["replicateSource"], "auto")
        self.assertEqual(omic["sampleHeader"], ["S1", "S2"])
        self.assertEqual(omic["replicateMapping"], [0, 0, 1, 1])

    def test_refuses_a_partial_detection(self):
        """Aggregating a partial detection would merge columns the detector
        could not account for, silently."""
        self.job.geneBasedInputOmics[0]["replicateDetection"]["status"] = "partial"
        with self.assertRaises(ValueError):
            self.job.applyReplicateMappingForOmic(self.omicName, "auto")

    def test_refuses_when_no_replicates_were_detected(self):
        self.job.geneBasedInputOmics[0]["replicateDetection"]["status"] = "none"
        with self.assertRaises(ValueError):
            self.job.applyReplicateMappingForOmic(self.omicName, "auto")

    def test_refuses_when_detection_is_absent(self):
        del self.job.geneBasedInputOmics[0]["replicateDetection"]
        with self.assertRaises(ValueError):
            self.job.applyReplicateMappingForOmic(self.omicName, "auto")


class ManualModeTest(ApplyReplicateMappingTestCase):

    def test_uses_the_supplied_grouping_over_the_detected_one(self):
        """The manual route exists precisely to override detection."""
        result = self.job.applyReplicateMappingForOmic(
            self.omicName, "manual",
            sampleHeader=["All"], mapping=[0, 0, 0, 0], groups=[[0, 1, 2, 3]])
        self.assertEqual(result["sampleHeader"], ["All"])
        self.assertEqual(self.firstOmicValue("G1").sampleValues, [8.5])

    def test_requires_the_full_grouping(self):
        for kwargs in ({"sampleHeader": ["A"]},
                       {"mapping": [0, 0, 0, 0]},
                       {"sampleHeader": ["A"], "mapping": [0, 0, 0, 0]},
                       {}):
            with self.subTest(kwargs=sorted(kwargs)):
                with self.assertRaises(ValueError):
                    self.job.applyReplicateMappingForOmic(
                        self.omicName, "manual", **kwargs)


class OffModeTest(ApplyReplicateMappingTestCase):

    def test_clears_previously_written_values(self):
        """Otherwise the user turns aggregation off and still sees it."""
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        self.assertIsNotNone(self.firstOmicValue("G1").sampleValues)

        result = self.job.applyReplicateMappingForOmic(self.omicName, "off")
        self.assertEqual(result["status"], "cleared")
        self.assertIsNone(self.firstOmicValue("G1").sampleValues)
        self.assertIsNone(self.firstOmicValue("G1").sampleRelevant)

    def test_resets_the_grouping_on_the_input_omic(self):
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        self.job.applyReplicateMappingForOmic(self.omicName, "off")
        omic = self.job.geneBasedInputOmics[0]
        self.assertEqual(omic["replicateSource"], "off")
        self.assertEqual(omic["sampleHeader"], [])
        self.assertEqual(omic["replicateMapping"], [])

    def test_leaves_the_raw_values_untouched(self):
        """Clearing the aggregate must not destroy the underlying data."""
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        self.job.applyReplicateMappingForOmic(self.omicName, "off")
        self.assertEqual(self.firstOmicValue("G1").getValues(), [1.0, 3.0, 10.0, 20.0])


class OmicIsolationTest(ApplyReplicateMappingTestCase):

    def test_only_the_named_omic_is_touched(self):
        other = "Proteomics"
        self.job.geneBasedInputOmics.append({
            "omicName": other,
            "omicHeader": ["ID", "S1_R1", "S1_R2", "S2_R1", "S2_R2"],
            "replicateDetection": dict(self.detection),
        })
        gene = self.job.inputGenesData["G1"]
        otherValue = OmicValue("G1")
        otherValue.setOmicName(other)
        otherValue.setValues([5.0, 5.0, 5.0, 5.0])
        gene.addOmicValue(otherValue)

        result = self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        self.assertEqual(result["featuresUpdated"], 2, "counted another omic's values")
        self.assertIsNone(otherValue.sampleValues)

    def test_an_unknown_omic_is_rejected(self):
        with self.assertRaises(ValueError):
            self.job.applyReplicateMappingForOmic("Nope", "auto")

    def test_an_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.job.applyReplicateMappingForOmic(self.omicName, "sideways")


class RaggedFeatureTest(ApplyReplicateMappingTestCase):
    """The route by which a real job reaches the aggregate_replicates guard."""

    def test_a_feature_with_fewer_values_than_columns_does_not_raise(self):
        """Job.py builds values per row and pads nothing, so a row narrower
        than the header arrives here intact."""
        self.job.inputGenesData["G3"] = makeGene("G3", self.omicName, [1.0, 3.0])
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        values = self.firstOmicValue("G3").sampleValues
        self.assertEqual(values[0], 2.0)
        self.assertTrue(math.isnan(values[1]), "absent data must be NaN, not 0.0")

    def test_a_feature_with_no_values_does_not_raise(self):
        self.job.inputGenesData["G4"] = makeGene("G4", self.omicName, [])
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        for value in self.firstOmicValue("G4").sampleValues:
            self.assertTrue(math.isnan(value))


class RelevanceTest(ApplyReplicateMappingTestCase):

    def test_per_condition_relevance_collapses_per_sample(self):
        self.job.inputGenesData["G5"] = makeGene(
            "G5", self.omicName, [1.0, 2.0, 3.0, 4.0],
            relevant=[True, False, False, False])
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        self.assertEqual(self.firstOmicValue("G5").sampleRelevant, [True, False])

    def test_feature_level_relevance_stays_length_one(self):
        """Length <= 1 is the renderer's signal to draw a row-label star
        instead of per-cell stars."""
        self.job.inputGenesData["G6"] = makeGene(
            "G6", self.omicName, [1.0, 2.0, 3.0, 4.0], relevant=True)
        self.job.applyReplicateMappingForOmic(self.omicName, "auto")
        self.assertEqual(self.firstOmicValue("G6").sampleRelevant, [True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
