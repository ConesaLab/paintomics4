#!/usr/bin/env python3
"""Regression tests for Job.parseSignificativeFeaturesFile.

The BED branch of this parser feeds Regions2Genes (RGMatch). It regressed when
multi-condition support was added: the branch computed the right region ID and
then fell through to a tail branch that recomputed `featureID = line[0].lower()`,
collapsing a 3-column BED to a set of bare chromosome names. Every region ID
lookup missed, so the tool silently reported zero relevant genes.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_relevant_features_parsing
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Job import Job


def _write(contents, suffix=".tab"):
    handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
    handle.write(contents)
    handle.close()
    return handle.name


class RelevantFeaturesBedFormatTest(unittest.TestCase):
    """isBedFormat=True must key on chrom_start_end, matching RGMatch region IDs."""

    def setUp(self):
        self.job = Job("testjob", "nologin", tempfile.gettempdir())
        self._paths = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _parse(self, contents, isBedFormat):
        path = _write(contents)
        self._paths.append(path)
        return self.job.parseSignificativeFeaturesFile(path, isBedFormat=isBedFormat)

    def test_bed_rows_key_on_full_region_id(self):
        # Three real rows from examplefiles/dnase_unmapped_relevant.tab.
        result = self._parse(
            "17\t13654752\t13655272\n"
            "10\t128821396\t128822090\n"
            "6\t52045696\t52045826\n",
            isBedFormat=True,
        )
        self.assertEqual(
            sorted(result),
            ["10_128821396_128822090", "17_13654752_13655272", "6_52045696_52045826"],
        )

    def test_bed_rows_do_not_collapse_to_chromosomes(self):
        # The regression signature: every row on chr 1 folding into a single "1" key.
        result = self._parse(
            "1\t4780215\t4780345\n"
            "1\t4785494\t4786020\n"
            "1\t4857386\t4857985\n",
            isBedFormat=True,
        )
        self.assertNotIn("1", result)
        self.assertEqual(len(result), 3)

    def test_bed_ids_match_rgmatch_region_ids(self):
        # Bed2GeneJob tests `regionID in relevantRegions` where regionID comes
        # from RGMatch column 0. That join must be reproduced exactly.
        result = self._parse("1\t4780215\t4780345\n", isBedFormat=True)
        rgmatch_region_id = "1_4780215_4780345"
        self.assertIn(rgmatch_region_id, result)

    def test_bed_values_are_truthy_for_isRelevant(self):
        # Feature.isRelevant() does any(self.relevant) for list values.
        result = self._parse("1\t4780215\t4780345\n", isBedFormat=True)
        self.assertTrue(any(result["1_4780215_4780345"]))


class RelevantFeaturesNonBedRegressionTest(unittest.TestCase):
    """The BED fix must not disturb the gene-list formats sharing this parser."""

    def setUp(self):
        self.job = Job("testjob", "nologin", tempfile.gettempdir())
        self._paths = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _parse(self, contents):
        path = _write(contents)
        self._paths.append(path)
        return self.job.parseSignificativeFeaturesFile(path, isBedFormat=False)

    def test_single_column_gene_list(self):
        result = self._parse("ENSMUSG00000028180\nENSMUSG00000002010\n")
        self.assertEqual(
            sorted(result), ["ensmusg00000002010", "ensmusg00000028180"]
        )

    def test_legacy_two_column_joins_with_triple_colon(self):
        # Real rows from examplefiles/mirna_relevant.tab. Legacy detection needs
        # BOTH cells of row 1 to look like biological IDs, and "looks like an ID"
        # means 4+ consecutive digits or a colon -- so the miRNA name in row 1
        # must carry a 4-digit number for the file to be read as legacy.
        result = self._parse(
            "ENSMUSG00000038127\tmmu-miR-3091-3p\n"
            "ENSMUSG00000038127\tmmu-miR-466k\n"
        )
        self.assertIn("ensmusg00000038127:::mmu-mir-3091-3p", result)
        self.assertIn("ensmusg00000038127:::mmu-mir-466k", result)

    def test_legacy_detection_is_fragile_for_short_mirna_names(self):
        # Documents a real limitation rather than asserting desired behaviour:
        # mmu-miR-155-5p and mmu-miR-21a-5p are genuine miRNA names whose longest
        # digit run is 3, so row 1 fails the ID heuristic and the same legacy
        # file is read as a 2-condition file instead. Whether to widen the
        # heuristic is a product decision, not something this test presumes.
        result = self._parse(
            "ENSMUSG00000028180\tmmu-miR-155-5p\n"
            "ENSMUSG00000002010\tmmu-miR-21a-5p\n"
        )
        self.assertNotIn("ensmusg00000028180:::mmu-mir-155-5p", result)
        self.assertIn("mmu-mir-155-5p", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
