#!/usr/bin/env python3
"""Cover for PathwayAcquisitionJob._findInputOmicByName.

This is the resolver both replicate-mapping callers share: the auto-apply path
inside processFilesContent and the /pa_apply_replicate_mapping endpoint. It
returns a three-tuple ``(inputOmic, featureDict, featureType)``, and every
element of it is load-bearing at a different point in the servlet:

    inputOmic    -- mutated in place with replicateSource / sampleHeader /
                    replicateMapping, then persisted with the job document
    featureDict  -- the features re-inserted after featDAO.removeAll(...)
    featureType  -- the "Gene"/"Compound" discriminator that removeAll and
                    insertAll are keyed on

The endpoint previously dropped the middle element on the floor, which deleted
the job's whole feature collection and put nothing back (see
test_apply_replicate_mapping_servlet). Those tests drive the servlet; nothing
tested this function directly, so the identity and precedence guarantees it
makes to its callers were unpinned. They are pinned here.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_find_input_omic_by_name
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Feature import Compound, Gene
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob


def buildJob():
    job = PathwayAcquisitionJob("J1", "u1", "/tmp/")
    job.geneBasedInputOmics = [
        {"omicName": "Gene expression"},
        {"omicName": "Proteomics"},
    ]
    job.compoundBasedInputOmics = [{"omicName": "Metabolomics"}]
    job.inputGenesData = {"G1": Gene("G1")}
    job.inputCompoundsData = {"C1": Compound("C1")}
    return job


class ResolutionTest(unittest.TestCase):

    def setUp(self):
        self.job = buildJob()

    def test_a_gene_omic_resolves_to_the_gene_collection(self):
        omic, features, featureType = self.job._findInputOmicByName("Gene expression")
        self.assertEqual(omic["omicName"], "Gene expression")
        self.assertEqual(featureType, "Gene")
        self.assertIn("G1", features)

    def test_a_second_gene_omic_resolves_to_its_own_dict(self):
        omic, _, _ = self.job._findInputOmicByName("Proteomics")
        self.assertEqual(omic["omicName"], "Proteomics")

    def test_a_compound_omic_resolves_to_the_compound_collection(self):
        omic, features, featureType = self.job._findInputOmicByName("Metabolomics")
        self.assertEqual(omic["omicName"], "Metabolomics")
        self.assertEqual(featureType, "Compound")
        self.assertIn("C1", features)

    def test_an_unknown_omic_yields_a_none_triple(self):
        """All three, not just the first -- the servlet only checks
        ``inputOmic is None`` and would carry a stale featureDict otherwise."""
        self.assertEqual(self.job._findInputOmicByName("Nope"), (None, None, None))


class IdentityTest(unittest.TestCase):
    """The caller mutates what it gets back. Copies would be silent no-ops."""

    def setUp(self):
        self.job = buildJob()

    def test_the_returned_omic_is_the_live_dict(self):
        omic, _, _ = self.job._findInputOmicByName("Gene expression")
        omic["replicateSource"] = "manual"
        self.assertEqual(self.job.geneBasedInputOmics[0].get("replicateSource"), "manual")

    def test_the_returned_feature_dict_is_the_live_dict(self):
        """applyReplicateMappingForOmic writes sampleValues onto these
        OmicValues and the servlet then re-inserts featureDict.values(); a
        copy here would persist features without the aggregation."""
        _, features, _ = self.job._findInputOmicByName("Gene expression")
        self.assertIs(features, self.job.inputGenesData)

    def test_the_compound_feature_dict_is_the_live_dict(self):
        _, features, _ = self.job._findInputOmicByName("Metabolomics")
        self.assertIs(features, self.job.inputCompoundsData)


class MatchingSemanticsTest(unittest.TestCase):
    """Matching is exact ``==`` on the raw string. Worth pinning, because the
    sibling lookup in MOREJob.getTargetExpressionFile normalises with
    ``.strip().lower()`` and the two are easy to assume identical."""

    def setUp(self):
        self.job = buildJob()

    def test_matching_is_case_sensitive(self):
        self.assertEqual(self.job._findInputOmicByName("gene expression"),
                         (None, None, None))

    def test_surrounding_whitespace_is_not_stripped(self):
        self.assertEqual(self.job._findInputOmicByName(" Gene expression"),
                         (None, None, None))

    def test_an_empty_name_matches_nothing(self):
        self.assertEqual(self.job._findInputOmicByName(""), (None, None, None))


class DegenerateInputTest(unittest.TestCase):

    def setUp(self):
        self.job = buildJob()

    def test_an_omic_dict_without_a_name_key_does_not_raise(self):
        """.get, not [] -- a partially-built omic must not take down the
        lookup for the omics either side of it."""
        self.job.geneBasedInputOmics.insert(0, {})
        omic, _, featureType = self.job._findInputOmicByName("Gene expression")
        self.assertEqual(omic["omicName"], "Gene expression")
        self.assertEqual(featureType, "Gene")

    def test_a_none_name_matches_a_nameless_omic(self):
        """Documented edge, not an endorsement: ``.get`` returns None for a
        nameless omic and ``None == None``, so a None query resolves to it.
        The servlet guards this upstream by rejecting a missing omicName
        before it calls, and this test exists so that guard is not removed
        without someone seeing what it protects."""
        nameless = {}
        self.job.geneBasedInputOmics = [nameless]
        omic, _, featureType = self.job._findInputOmicByName(None)
        self.assertIs(omic, nameless)
        self.assertEqual(featureType, "Gene")

    def test_no_omics_at_all_yields_a_none_triple(self):
        self.job.geneBasedInputOmics = []
        self.job.compoundBasedInputOmics = []
        self.assertEqual(self.job._findInputOmicByName("Gene expression"),
                         (None, None, None))

    def test_gene_omics_win_over_a_compound_omic_of_the_same_name(self):
        """Gene-based omics are scanned first. Pinned because the two
        collections are removed and re-inserted under different featureType
        keys, so a precedence flip would delete the wrong collection."""
        self.job.compoundBasedInputOmics = [{"omicName": "Gene expression"}]
        _, features, featureType = self.job._findInputOmicByName("Gene expression")
        self.assertEqual(featureType, "Gene")
        self.assertIs(features, self.job.inputGenesData)


if __name__ == "__main__":
    unittest.main(verbosity=2)
