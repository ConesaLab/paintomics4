#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
compundsClassification() end to end on the shipped replicate-level example.

The statistics are pinned in test_class_activity_stats; this file pins the
JOB: that a compound omic carrying a design makes the permutation test run,
that without one the binomial with p0 = alpha runs, that a design with a
single replicate falls back with a warning rather than a crash, and that the
level-2 fields every older client reads are still produced either way.

Data: 12-stategra-metabolomics-replicates, read straight from the example
directory, with a hand-written KEGG mapping for a subset of its metabolites
(checked against br08001 in setUp so a wrong id fails here, not silently).

Usage:
    cd PaintomicsServer
    python -m src.tests.test_class_activity_job
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", ".."))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from src.classes.Feature import Compound, OmicValue  # noqa: E402
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob  # noqa: E402
from src.common import ClassActivity as CA  # noqa: E402
from src.common.DesignFile import parse_design  # noqa: E402

DATA = os.path.join(SERVER_ROOT, "src", "examplefiles", "datasets",
                    "12-stategra-metabolomics-replicates", "data")
VALUES = os.path.join(DATA, "metabolomics_replicates.tab")
DESIGN = os.path.join(DATA, "experimental_design.tab")
RELEVANT = os.path.join(DATA, "metabolomics_relevant.tab")

# name in the values file -> KEGG id(s). Alanine is deliberately ticked under
# two ids (L- and D-alanine, both "Amino acids"), as step 2 does for a name
# that matches twice.
KEGG = {
    "Alanine": ["C00041", "C00133"], "Glutamic acid": ["C00025"], "Glycine": ["C00037"],
    "L-aspartic acid": ["C00049"], "Proline": ["C00148"], "Serine": ["C00065"],
    "Threonine": ["C00188"], "Valine": ["C00183"], "Leucine": ["C00123"],
    "putrescine": ["C00134"], "gamma-aminobutyric acid": ["C00334"],
    "ethanolamine": ["C00189"], "beta-alanine": ["C00099"],
    "Glucose": ["C00031"], "Fructose": ["C00095"], "Mannitol": ["C00392"], "Myo-inositol": ["C00137"],
    "Thymine": ["C00178"], "Cytosine": ["C00380"], "Guanine": ["C00242"], "Adenosine": ["C00212"],
    "Pyruvic acid": ["C00022"], "Succinic acid": ["C00042"], "Malic acid": ["C00149"],
    "Citric acid": ["C00158"], "Lactic acid": ["C00186"], "Alpha-ketoglutaric acid": ["C00026"],
    "Cholesterol": ["C00187"],
}


def _readValues():
    with open(VALUES, "r") as handle:
        lines = [l.rstrip("\n").split("\t") for l in handle if l.strip()]
    header = lines[0]
    rows = {line[0]: [float(x) for x in line[1:]] for line in lines[1:]}
    return header, rows


def _relevantNames():
    with open(RELEVANT, "r") as handle:
        return {l.strip().lower() for l in handle if l.strip()}


def _job(withDesign=True, thinDesign=False, oneCondition=False, secondOmic=False):
    """A bare PathwayAcquisitionJob carrying the example's compounds."""
    header, rows = _readValues()
    relevant = _relevantNames()
    job = PathwayAcquisitionJob.__new__(PathwayAcquisitionJob)
    job.jobID = "TESTCLASSACT"
    job.organism = "mmu"
    job.compoundRegulateFeatures = None
    job.inputCompoundsData = {}
    for name, ids in KEGG.items():
        for cid in ids:
            compound = Compound(cid)
            omicValue = OmicValue(name.lower())
            omicValue.setOriginalName(name)
            omicValue.setOmicName("Metabolomics")
            omicValue.setValues(list(rows[name]))
            omicValue.setRelevant([name.lower() in relevant])
            compound.addOmicValue(omicValue)
            job.inputCompoundsData[cid] = compound
    omic = {"omicName": "Metabolomics", "inputDataFile": VALUES, "isExample": True,
            "omicHeader": list(header)}
    if secondOmic:
        # A lipidomics panel of its own width: cholesterol under Steroids,
        # six ratio columns, no design.
        compound = Compound("C00187")
        omicValue = OmicValue("cholesterol")
        omicValue.setOriginalName("Cholesterol")
        omicValue.setOmicName("Lipidomics")
        omicValue.setValues([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        omicValue.setRelevant([True])
        compound.addOmicValue(omicValue)
        job.inputCompoundsData["C00187"] = compound
    if withDesign:
        with open(DESIGN, "r") as handle:
            body = handle.read()
        if thinDesign:
            # Every column its own condition: 36 conditions, one replicate each.
            body = "\n".join("%s\t%s" % (c, c) for c in header[1:])
        if oneCondition:
            # Every column the same condition: 36 replicates of nothing to compare.
            body = "\n".join("%s\tCtr" % c for c in header[1:])
        sampleHeader, mapping, groups = parse_design(body, header[1:])
        omic["sampleHeader"] = sampleHeader
        omic["replicateMapping"] = mapping
        omic["replicateSource"] = "manual"
    job.compoundBasedInputOmics = [omic]
    if secondOmic:
        job.compoundBasedInputOmics.append({"omicName": "Lipidomics", "inputDataFile": VALUES,
                                            "isExample": True, "omicHeader": ["ID"] + ["c%d" % i for i in range(6)]})
    job.geneBasedInputOmics = []
    return job


def _run(job, payload=None):
    with mock.patch.object(PathwayAcquisitionJob, "getCompoundRegulateFeatures", return_value={}), \
            mock.patch("src.classes.JobInstances.PathwayAcquisitionJob.CLASS_ACTIVITY_PERMUTATIONS", 300):
        job.compundsClassification(payload or {})
    return job


class KeggMappingIsRealTest(unittest.TestCase):

    def test_every_hand_written_id_is_in_brite(self):
        brite = CA.loadBrite()
        missing = [cid for ids in KEGG.values() for cid in ids if cid not in brite]
        self.assertEqual(missing, [])


class PermutationRouteTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.job = _run(_job(withDesign=True), {"thresholdMetaboliteClass": "0.05"})
        cls.activity = cls.job.classActivity

    def test_the_permutation_test_ran(self):
        a = self.activity
        self.assertIsNotNone(a)
        self.assertEqual(a["test"], "permutation")
        self.assertEqual(a["factor"], "factor0")
        self.assertEqual([f["id"] for f in a["factors"]], ["factor0", "factor1"])
        self.assertEqual(a["design"]["levels"], ["Ctr", "Ik"])
        self.assertEqual(a["conditions"], ["0H", "2H", "6H", "12H", "18H", "24H"])
        self.assertEqual(a["nPerm"], 300)
        self.assertEqual(self.job.classificationMeta["test"], "permutation")

    def test_amines_respond_and_bases_do_not(self):
        byKey = {e["key"]: e for e in self.activity["levels"]["2"]}
        amines = byKey["Peptides > Amines"]
        self.assertEqual(amines["n"], 4)
        self.assertGreater(amines["meanF"], 20)
        self.assertLess(amines["p"], 0.02)
        self.assertGreater(amines["meanF"], amines["nullQ95"])
        self.assertEqual(len(amines["eff"]), 6)
        self.assertLess(amines["eff"][-1], -1.0)        # down at 24 h
        bases = byKey["Nucleic acids > Bases"]
        self.assertGreater(bases["p"], 0.2)
        # Binomial counts ride along on every entry, per condition.
        self.assertEqual(len(amines["k"]), 1)
        self.assertEqual(len(amines["binomial"]["p"]), 1)

    def test_three_levels_and_the_one_name_two_ids_rule(self):
        levels = self.activity["levels"]
        self.assertEqual(set(levels), {"1", "2", "3"})
        l1 = {e["name"]: e for e in levels["1"]}
        self.assertIn("Peptides", l1)
        aa = {e["key"]: e for e in levels["2"]}["Peptides > Amino acids"]
        # Alanine under two ids is ONE member.
        self.assertEqual(aa["members"].count("Alanine"), 1)
        l3 = {e["key"] for e in levels["3"]}
        self.assertIn("Peptides > Amino acids > Common amino acids", l3)
        self.assertIn("Carbohydrates > Monosaccharides > Sugar alcohols", l3)

    def test_features_and_exclusions(self):
        f = self.activity["features"]
        self.assertEqual(sorted(f["Alanine"]["kegg"]), ["C00041", "C00133"])
        # The replicate columns are not stored a second time on this route;
        # the strip is painted from `eff`.
        self.assertNotIn("values", f["Alanine"])
        self.assertGreater(f["putrescine"]["F"], 50)
        self.assertTrue(f["putrescine"]["sig"])
        self.assertEqual(len(f["putrescine"]["eff"]), 6)
        excluded = self.activity["excluded"]
        # Names in the values file that the (subset) mapping never matched.
        self.assertIn("taurine", excluded["unmatched"])
        self.assertNotIn("alanine", excluded["unmatched"])
        self.assertEqual(excluded["unclassified"], [])

    def test_legacy_level2_fields_are_still_produced(self):
        self.assertIn("Amines", self.job.classificationDict)
        self.assertIn("Amines", self.job.pValueInDict[0])
        self.assertEqual(self.job.classificationMeta["nullKind"], "alpha")
        self.assertEqual(self.job.classificationMeta["alpha"], 0.05)


class BinomialRouteTest(unittest.TestCase):

    def test_no_design_means_binomial_with_alpha(self):
        job = _run(_job(withDesign=False), {"thresholdMetaboliteClass": "0.05"})
        a = job.classActivity
        self.assertEqual(a["test"], "binomial")
        self.assertEqual(a["nullKind"], "alpha")
        self.assertEqual(a["alpha"], 0.05)
        self.assertEqual(a["factors"], [])
        amines = {e["key"]: e for e in a["levels"]["2"]}["Peptides > Amines"]
        self.assertNotIn("meanF", amines)
        # putrescine and GABA are in the relevant list; ethanolamine and
        # beta-alanine are not -> 2 of 4 at alpha 0.05.
        self.assertEqual(amines["k"], [2])
        self.assertAlmostEqual(amines["binomial"]["p"][0],
                               6 * 0.05 ** 2 * 0.95 ** 2 + 4 * 0.05 ** 3 * 0.95 + 0.05 ** 4, places=9)
        # Direction from the values themselves: one column per values column.
        self.assertEqual(len(a["conditions"]), 36)
        self.assertEqual(len(amines["eff"]), 36)

    def test_no_threshold_means_the_competitive_null(self):
        job = _run(_job(withDesign=False), {})
        a = job.classActivity
        self.assertEqual(a["nullKind"], "relative")
        self.assertIsNone(a["alpha"])
        self.assertEqual(job.classificationMeta["thresholdSource"], "auto")

    def test_one_condition_falls_back_with_a_warning(self):
        """36 "replicates" of a single condition passed the replicate count and
        reported a permutation test with nothing tested."""
        job = _run(_job(withDesign=True, oneCondition=True), {"thresholdMetaboliteClass": "0.05"})
        a = job.classActivity
        self.assertEqual(a["test"], "binomial")
        self.assertTrue(any("single condition" in w for w in a["warnings"]), a["warnings"])
        amines = {e["key"]: e for e in a["levels"]["2"]}["Peptides > Amines"]
        self.assertNotIn("meanF", amines)
        self.assertEqual(amines["k"], [2])

    def test_a_second_compound_omic_is_named_as_untested(self):
        job = _run(_job(withDesign=True, secondOmic=True), {"thresholdMetaboliteClass": "0.05"})
        a = job.classActivity
        self.assertEqual(a["test"], "permutation")
        self.assertTrue(any("Lipidomics" in w and "not" in w for w in a["warnings"]), a["warnings"])
        steroids = [e for e in a["levels"]["2"] if e["name"] == "27-Carbon atoms"][0]
        self.assertEqual(steroids["tested"], 0)
        self.assertIsNone(steroids["p"])
        self.assertEqual(steroids["k"], [1])            # the binomial still counts it

    def test_measured_names_skip_a_leading_blank_line(self):
        job = _job(withDesign=False)
        with tempfile.NamedTemporaryFile("w", suffix=".tab", delete=False) as handle:
            handle.write("\n#compound\tC1\tC2\nAlanine\t1\t2\nTaurine\t3\t4\n")
            path = handle.name
        try:
            names = job._measuredCompoundNames({"inputDataFile": path, "isExample": True})
        finally:
            os.unlink(path)
        self.assertEqual(names, ["alanine", "taurine"])

    def test_one_replicate_per_condition_falls_back_with_a_warning(self):
        job = _run(_job(withDesign=True, thinDesign=True), {"thresholdMetaboliteClass": "0.05"})
        a = job.classActivity
        self.assertEqual(a["test"], "binomial")
        self.assertTrue(any("two replicates" in w for w in a["warnings"]), a["warnings"])
        self.assertNotIn("meanF", {e["key"]: e for e in a["levels"]["2"]}["Peptides > Amines"])


if __name__ == "__main__":
    unittest.main()
