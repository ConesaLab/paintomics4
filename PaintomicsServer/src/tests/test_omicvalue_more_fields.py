#!/usr/bin/env python3
"""Cover for the OmicValue fields MORE-v2 added, and their BSON round-trip.

MORE-v2 put four new pieces of state on OmicValue:

  sampleValues / sampleRelevant  -- the replicate-aggregated view, written by
                                    PathwayAcquisitionJob._walkAndAggregateOmicValues
  isRegulator / regulatorID      -- set when a values row is keyed
                                    GENE:::REGULATOR, so Step 4 can flip which
                                    of the pair is the row's identifier

All four have to survive Mongo. This is not a given in this codebase: MOREJob
.results is a dict and is silently dropped by Job.toBSON(recursive=False),
which is why it is worth checking rather than assuming. OmicValue inherits
Model.toBSON, which returns self.__dict__, so everything is written -- these
tests hold that open, because a future toBSON that filters attributes would
lose the aggregation with no error anywhere.

sampleRelevant additionally gets bool-coercion on the way back in, mirroring
`relevant`, because a JSON round-trip can stringify booleans and a truthy
"False" would invert a significance flag.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_omicvalue_more_fields
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Feature import Gene, OmicValue


def roundTrip(omicValue):
    return OmicValue("").parseBSON(dict(omicValue.toBSON()))


class DefaultsTest(unittest.TestCase):

    def test_the_aggregated_view_starts_absent(self):
        """None, not [] -- the renderer distinguishes 'not aggregated' from
        'aggregated to nothing'."""
        ov = OmicValue("G1")
        self.assertIsNone(ov.sampleValues)
        self.assertIsNone(ov.sampleRelevant)

    def test_regulator_flags_start_off(self):
        ov = OmicValue("G1")
        self.assertFalse(ov.isRegulator)
        self.assertEqual(ov.regulatorID, "")

    def test_original_name_defaults_to_the_input_name(self):
        self.assertEqual(OmicValue("G1").getOriginalName(), "G1")


class RoundTripTest(unittest.TestCase):

    def test_sample_values_survive(self):
        ov = OmicValue("G1")
        ov.setSampleValues([2.0, 15.0])
        self.assertEqual(roundTrip(ov).sampleValues, [2.0, 15.0])

    def test_sample_relevant_survives(self):
        ov = OmicValue("G1")
        ov.setSampleRelevant([True, False])
        self.assertEqual(roundTrip(ov).sampleRelevant, [True, False])

    def test_a_nan_sample_value_survives_as_nan(self):
        """An all-NaN replicate group aggregates to NaN; it must not come back
        as 0.0, which would plot as a real measurement."""
        ov = OmicValue("G1")
        ov.setSampleValues([2.0, float("nan")])
        restored = roundTrip(ov).sampleValues
        self.assertEqual(restored[0], 2.0)
        self.assertTrue(math.isnan(restored[1]))

    def test_an_unaggregated_value_stays_none(self):
        self.assertIsNone(roundTrip(OmicValue("G1")).sampleValues)

    def test_cleared_aggregation_stays_cleared(self):
        """applyReplicateMappingForOmic(mode="off") sets these back to None."""
        ov = OmicValue("G1")
        ov.setSampleValues([1.0])
        ov.setSampleValues(None)
        ov.setSampleRelevant(None)
        restored = roundTrip(ov)
        self.assertIsNone(restored.sampleValues)
        self.assertIsNone(restored.sampleRelevant)

    def test_regulator_metadata_survives(self):
        ov = OmicValue("G1")
        ov.isRegulator = True
        ov.regulatorID = "AT1G01010"
        ov.setOriginalName("STAT3")
        restored = roundTrip(ov)
        self.assertTrue(restored.isRegulator)
        self.assertEqual(restored.regulatorID, "AT1G01010")
        self.assertEqual(restored.getOriginalName(), "STAT3")

    def test_raw_values_and_omic_name_survive_alongside(self):
        ov = OmicValue("G1")
        ov.setOmicName("Gene expression")
        ov.setValues([1.0, 3.0])
        ov.setSampleValues([2.0])
        restored = roundTrip(ov)
        self.assertEqual(restored.getOmicName(), "Gene expression")
        self.assertEqual(restored.getValues(), [1.0, 3.0])


class StringifiedBooleanTest(unittest.TestCase):
    """A JSON round-trip can turn booleans into strings, and a bare truthiness
    test on "False" is True -- which would invert a significance flag."""

    def test_stringified_sample_relevant_is_coerced(self):
        restored = OmicValue("").parseBSON({"sampleRelevant": ["True", "False"]})
        self.assertEqual(restored.sampleRelevant, [True, False])

    def test_a_scalar_stringified_sample_relevant_is_coerced(self):
        restored = OmicValue("").parseBSON({"sampleRelevant": "True"})
        self.assertIs(restored.sampleRelevant, True)
        restored = OmicValue("").parseBSON({"sampleRelevant": "False"})
        self.assertIs(restored.sampleRelevant, False)

    def test_none_sample_relevant_stays_none(self):
        restored = OmicValue("").parseBSON({"sampleRelevant": None})
        self.assertIsNone(restored.sampleRelevant)

    def test_relevant_gets_the_same_treatment(self):
        restored = OmicValue("").parseBSON({"relevant": ["True", "False"]})
        self.assertEqual(restored.relevant, [True, False])


class IsRelevantTest(unittest.TestCase):
    """The accessor the renderers key on, including the length<=1 convention
    that ReplicateDetection deliberately produces for feature-level relevance."""

    def test_per_condition_lookup(self):
        ov = OmicValue("G1")
        ov.setRelevant([False, True, False])
        self.assertFalse(ov.isRelevant(0))
        self.assertTrue(ov.isRelevant(1))

    def test_out_of_range_condition_falls_back_to_any(self):
        ov = OmicValue("G1")
        ov.setRelevant([False, True])
        self.assertTrue(ov.isRelevant(9))

    def test_no_index_collapses_with_any(self):
        ov = OmicValue("G1")
        ov.setRelevant([False, False, True])
        self.assertTrue(ov.isRelevant())
        ov.setRelevant([False, False])
        self.assertFalse(ov.isRelevant())

    def test_a_scalar_relevant_is_returned_as_is(self):
        ov = OmicValue("G1")
        ov.setRelevant(True)
        self.assertTrue(ov.isRelevant())
        self.assertTrue(ov.isRelevant(0))

    def test_the_empty_default_is_not_relevant(self):
        self.assertFalse(OmicValue("G1").isRelevant())


class AccessorTest(unittest.TestCase):
    """The getters, exercised through the getters.

    Every other test in this file reads ``ov.sampleValues`` directly, which is
    what the aggregation code does. The renderers and the serializer go through
    the accessors instead, so a getter returning the wrong attribute would be
    invisible to the rest of this file while breaking the views.
    """

    def test_get_sample_values_returns_what_was_set(self):
        ov = OmicValue("G1")
        ov.setSampleValues([2.0, 15.0])
        self.assertEqual(ov.getSampleValues(), [2.0, 15.0])

    def test_get_sample_relevant_returns_what_was_set(self):
        ov = OmicValue("G1")
        ov.setSampleRelevant([True, False])
        self.assertEqual(ov.getSampleRelevant(), [True, False])

    def test_the_getters_start_none(self):
        ov = OmicValue("G1")
        self.assertIsNone(ov.getSampleValues())
        self.assertIsNone(ov.getSampleRelevant())

    def test_the_getters_survive_the_round_trip(self):
        ov = OmicValue("G1")
        ov.setSampleValues([2.0])
        ov.setSampleRelevant([True])
        restored = roundTrip(ov)
        self.assertEqual(restored.getSampleValues(), [2.0])
        self.assertEqual(restored.getSampleRelevant(), [True])

    def test_has_sample_aggregation_tracks_sample_values(self):
        """The flag the renderer branches on to choose replicate columns over
        raw ones. It keys on sampleValues alone, so an aggregation that
        produced values but no relevance still counts as aggregated."""
        ov = OmicValue("G1")
        self.assertFalse(ov.hasSampleAggregation())
        ov.setSampleValues([2.0])
        self.assertTrue(ov.hasSampleAggregation())
        ov.setSampleValues(None)
        self.assertFalse(ov.hasSampleAggregation())

    def test_an_empty_aggregation_still_counts_as_aggregated(self):
        """[] is not None: an omic aggregated to zero samples has been
        processed, and must not fall back to rendering raw replicates."""
        ov = OmicValue("G1")
        ov.setSampleValues([])
        self.assertTrue(ov.hasSampleAggregation())


class FeatureNestingTest(unittest.TestCase):
    """Features serialise their OmicValues; the aggregation must survive that
    nesting too, since that is how it actually reaches Mongo."""

    def test_aggregation_survives_a_feature_round_trip(self):
        gene = Gene("G1")
        ov = OmicValue("G1")
        ov.setOmicName("Gene expression")
        ov.setSampleValues([2.0, 15.0])
        ov.setSampleRelevant([True, False])
        gene.addOmicValue(ov)

        restored = Gene("")
        restored.parseBSON(dict(gene.toBSON()))

        values = restored.getOmicsValues()
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].sampleValues, [2.0, 15.0])
        self.assertEqual(values[0].sampleRelevant, [True, False])

    def test_several_omics_keep_their_own_aggregation(self):
        gene = Gene("G1")
        for name, values in (("Gene expression", [1.0]), ("Proteomics", [9.0])):
            ov = OmicValue("G1")
            ov.setOmicName(name)
            ov.setSampleValues(values)
            gene.addOmicValue(ov)

        restored = Gene("")
        restored.parseBSON(dict(gene.toBSON()))
        byName = {v.getOmicName(): v.sampleValues for v in restored.getOmicsValues()}
        self.assertEqual(byName, {"Gene expression": [1.0], "Proteomics": [9.0]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
