#!/usr/bin/env python3
"""Both sides of the hypergeometric test must be counted in the same unit.

Why this exists
---------------
`calculateTotalFeaturesByOmic` builds the *background* of the enrichment test
(the population size N and the number of relevant features K).
`testPathwaySignificance` builds the *sample* for one pathway (n and k). They
were keyed differently:

    calculateTotalFeaturesByOmic   counterNames[db][omic][feature.getID()]
    testPathwaySignificance        counterNames[omic][enrichmentProperty]

`feature.getID()` is the *target* identifier -- the KEGG/Reactome/MapMan gene
id. `enrichmentProperty` is the *input* identifier the user chose to enrich
over (`genes` -> OmicValue.inputName, `features` -> originalName,
`associations` -> "inputName:::originalName"). The two are not the same unit,
because identifier mapping is many-to-many in both directions:

  * `mapFeatureIdentifiers` clones one input feature once per target id it
    resolves to (FeatureNamesToKeggIDsMapper.py:336-344), so one input on
    several KEGG genes was counted several times in N and once in n;
  * `Job.addInputGeneData` merges every input that resolved to the same target
    id into one Gene carrying several OmicValues (Job.py:239-244), so several
    inputs on one KEGG gene were counted once in N and several times in n.

Measured on a real job: 11359 KEGG mapping rows for 10406 distinct inputs, 272
inputs on more than one KEGG gene, and a worst case of 43 inputs collapsing
onto a single KEGG id.

The second direction is not merely imprecise, it is fatal. It makes the sample
larger than the population, `hypergeom.sf` returns NaN, and jsonify writes a
NaN as the bare token `NaN` -- not valid JSON -- so the client's JSON.parse
rejects the whole step-2 response. Reproduced before the fix with two inputs on
one KEGG id: N=2, n=3, p=nan.

The chosen unit is the enrichment property, for three reasons: it is the unit
the user explicitly selected in the interface, it is the unit the parser
already reports as "features processed" (Job.py:437), and
`calculateTotalFeaturesByOmic` already computed `enrichmentProperty` and threw
it away -- keying by it is what the function was written to do.

The KEGG id sets at the end of that loop (`totalFeaturesID` /
`totalFeaturesIDSig`) stay on `feature.getID()`: they are sets of identifiers,
not counters, and do not feed the test.

Usage:
    cd /path/to/paintomics4
    PYTHONPATH=PaintomicsServer python3 \
        PaintomicsServer/src/tests/test_enrichment_counting_unit.py
"""
import logging
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Feature import Compound, Gene, OmicValue
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.common.Statistics import calculateFisher

OMIC = "Gene expression"


def _gene(targetID, inputName, relevant, originalName=None):
    """One mapped clone: a target id carrying one omic value for one input."""
    gene = Gene(targetID)
    gene.setName(targetID)
    gene.setMatchingDB("KEGG")

    value = OmicValue(inputName)
    value.setOmicName(OMIC)
    value.setOriginalName(originalName if originalName is not None else inputName)
    value.setValues([0.0])
    value.setRelevant(relevant if isinstance(relevant, list) else [relevant])
    gene.addOmicValue(value)
    return gene


def _compound(targetID, inputName, relevant):
    compound = Compound(targetID)
    compound.setName(targetID)
    compound.setMatchingDB("KEGG")

    value = OmicValue(inputName)
    value.setOmicName(OMIC)
    value.setOriginalName(inputName)
    value.setValues([0.0])
    value.setRelevant([relevant])
    compound.addOmicValue(value)
    return compound


class _Counted(object):
    """The four hypergeometric arguments produced by one job, for one pathway."""

    def __init__(self, population, relevantInPopulation, sample, relevantInSample, pvalue):
        self.population = population                    # N
        self.relevantInPopulation = relevantInPopulation  # K
        self.sample = sample                            # n
        self.relevantInSample = relevantInSample        # k
        self.pvalue = pvalue

    def __repr__(self):
        return ("N=%r K=%r n=%r k=%r p=%r"
                % (self.population, self.relevantInPopulation,
                   self.sample, self.relevantInSample, self.pvalue))


def _count(features, pathwayIDs, enrichment="genes", multiCondition=False):
    """Run the real background + pathway counters over an in-memory job."""
    job = PathwayAcquisitionJob("UNITTEST", None, "/tmp/")
    job.setOrganism("test_org")
    job.setDatabases(["KEGG"])

    for feature in features:
        if isinstance(feature, Compound):
            job.addInputCompoundData(feature)
        else:
            job.addInputGeneData(feature)

    enrichmentByOmic = {OMIC: enrichment}
    # Everything we built is annotated to some pathway of the organism.
    mapped = set(job.getInputGenesData().keys()) | set(job.getInputCompoundsData().keys())

    totalFeatures, totalRelevant = job.calculateTotalFeaturesByOmic(
        enrichmentByOmic, {"KEGG": mapped}, {"KEGG": set()})

    geneIDs = set(job.getInputGenesData().keys())
    compoundIDs = set(job.getInputCompoundsData().keys())

    isValid, pathway = job.testPathwaySignificance(
        genesInPathway=[fid for fid in pathwayIDs if fid in geneIDs],
        compoundsInPathway=[fid for fid in pathwayIDs if fid in compoundIDs],
        inputGenesDict={gene.getID().lower(): gene
                        for gene in job.getInputGenesData().values()},
        inputCompoundsDict={compound.getID().lower(): compound
                            for compound in job.getInputCompoundsData().values()},
        totalFeaturesByOmic=totalFeatures.get("KEGG"),
        totalRelevantFeaturesByOmic=totalRelevant.get("KEGG"),
        mappedRatiosByOmic={OMIC: 1.0},
        enrichmentByOmic=enrichmentByOmic,
        sourceDB="KEGG",
        has_multi_cond=multiCondition)

    assert isValid, "the fixture built a pathway that matched nothing"
    significance = pathway.getSignificanceValues()[OMIC]
    return _Counted(totalFeatures["KEGG"][OMIC],
                    totalRelevant["KEGG"][OMIC],
                    significance[0][0],
                    significance[0][1],
                    significance[0][2])


class EnrichmentCountingUnitTest(unittest.TestCase):
    """The invariant: N and n are counted in the same unit, always."""

    def test_one_input_on_two_target_ids_counts_once_in_the_background(self):
        """The headline invariant, stated in the units the user chose.

        Two Genes sharing one inputName are one enrichable entity under `genes`
        enrichment, so they contribute 1 to the denominator, not 2.
        """
        counted = _count(
            [_gene("K1", "SYMBOL_A", True),   # same input, two KEGG ids
             _gene("K2", "SYMBOL_A", True),
             _gene("K3", "OTHER_B", False)],
            ["K1", "K2", "K3"])

        self.assertEqual(counted.population, 2,
                         "SYMBOL_A resolved to two KEGG ids and was counted "
                         "twice in the background: %r" % counted)
        self.assertEqual(counted.relevantInPopulation, [1],
                         "the relevant counter must use the same unit: %r" % counted)
        self.assertEqual(counted.sample, 2, repr(counted))
        self.assertEqual(counted.relevantInSample, 1, repr(counted))

    def test_two_inputs_on_one_target_id_count_twice_in_the_background(self):
        """The other direction, and the one that returned NaN.

        Two inputs that map onto the same KEGG id are merged into one Gene with
        two OmicValues. Keyed by the target id the background was 1 while the
        pathway sample was 3 -- a sample larger than the population.
        """
        counted = _count(
            [_gene("K1", "IN_A", True),       # both inputs land on K1
             _gene("K1", "IN_B", True),
             _gene("K2", "IN_C", False)],
            ["K1", "K2"])

        self.assertEqual(counted.population, 3,
                         "the merged Gene hid one of its two inputs: %r" % counted)
        self.assertEqual(counted.relevantInPopulation, [2], repr(counted))
        self.assertEqual(counted.sample, 3, repr(counted))
        self.assertEqual(counted.relevantInSample, 2, repr(counted))

    def test_the_sample_is_never_larger_than_the_population(self):
        """The property that makes the p-value a p-value at all."""
        features = []
        pathwayIDs = []
        # A deliberately nasty mapping: fan-out and collapse in the same job.
        for targetID, inputName in [("K1", "IN_A"), ("K2", "IN_A"), ("K3", "IN_A"),
                                    ("K4", "IN_B"), ("K4", "IN_C"), ("K4", "IN_D"),
                                    ("K5", "IN_E")]:
            features.append(_gene(targetID, inputName, True))
            pathwayIDs.append(targetID)

        counted = _count(features, pathwayIDs)

        self.assertLessEqual(counted.sample, counted.population, repr(counted))
        self.assertLessEqual(counted.relevantInSample, counted.relevantInPopulation[0],
                             repr(counted))
        # 5 distinct inputs: IN_A..IN_E.
        self.assertEqual(counted.population, 5, repr(counted))
        self.assertEqual(counted.sample, 5, repr(counted))

    def test_a_collapsed_mapping_no_longer_produces_a_nan_pvalue(self):
        """A NaN here is written as the bare token `NaN` and breaks JSON.parse."""
        counted = _count(
            [_gene("K1", "IN_A", True),
             _gene("K1", "IN_B", True),
             _gene("K2", "IN_C", False)],
            ["K1", "K2"])

        self.assertFalse(math.isnan(counted.pvalue),
                         "the enrichment p-value is NaN; jsonify writes that as "
                         "an invalid JSON token and the client rejects the whole "
                         "step-2 response: %r" % counted)
        self.assertTrue(0.0 < counted.pvalue <= 1.0, repr(counted))

    def test_features_enrichment_counts_by_the_original_name(self):
        """The unit follows the user's enrichment choice, not the target id."""
        counted = _count(
            [_gene("K1", "IN_A", True, originalName="PROTEIN_1"),
             _gene("K2", "IN_A", True, originalName="PROTEIN_1"),
             _gene("K3", "IN_B", False, originalName="PROTEIN_2")],
            ["K1", "K2", "K3"], enrichment="features")

        self.assertEqual(counted.population, 2,
                         "two clones of one originalName must be one feature "
                         "under `features` enrichment: %r" % counted)
        self.assertEqual(counted.sample, 2, repr(counted))

    def test_associations_enrichment_counts_each_pairing_separately(self):
        """One target measured against two regulators is two associations."""
        counted = _count(
            [_gene("K1", "IN_A", True, originalName="TF_1"),
             _gene("K1", "IN_A", True, originalName="TF_2")],
            ["K1"], enrichment="associations")

        # relevantAssociation defaults to False, so only the counts matter here.
        self.assertEqual(counted.population, 2,
                         "IN_A:::TF_1 and IN_A:::TF_2 are two associations: %r"
                         % counted)
        self.assertEqual(counted.sample, 2, repr(counted))

    def test_the_unit_holds_for_every_condition_of_a_multi_condition_job(self):
        counted = _count(
            [_gene("K1", "IN_A", [True, False]),
             _gene("K2", "IN_A", [True, False]),
             _gene("K3", "IN_B", [False, True])],
            ["K1", "K2", "K3"], multiCondition=True)

        self.assertEqual(counted.population, 2, repr(counted))
        self.assertEqual(counted.relevantInPopulation, [1, 1],
                         "per-condition relevance must be counted per input, "
                         "not per clone: %r" % counted)

    def test_a_one_to_one_mapping_is_left_exactly_as_it_was(self):
        """No fan-out, no collapse: the fix must not move an ordinary job."""
        counted = _count(
            [_gene("K%d" % i, "IN_%d" % i, i < 3) for i in range(10)],
            ["K0", "K1", "K2", "K3", "K4"])

        self.assertEqual(counted.population, 10, repr(counted))
        self.assertEqual(counted.relevantInPopulation, [3], repr(counted))
        self.assertEqual(counted.sample, 5, repr(counted))
        self.assertEqual(counted.relevantInSample, 3, repr(counted))

    def test_compounds_are_counted_in_the_same_unit_as_genes(self):
        """calculateTotalFeaturesByOmic walks compounds through the same loop."""
        counted = _count(
            [_compound("C1", "GLUCOSE", True),
             _compound("C2", "GLUCOSE", True),
             _compound("C3", "PYRUVATE", False)],
            ["C1", "C2", "C3"])

        self.assertEqual(counted.population, 2, repr(counted))
        self.assertEqual(counted.sample, 2, repr(counted))


class FisherDomainGuardTest(unittest.TestCase):
    """calculateFisher must never hand a non-p-value back to the pipeline.

    The counting fix above closes the route that produced these arguments, but
    the guard stays: a NaN reaching jsonify costs the entire response, and this
    function is called once per pathway per omic.
    """

    def test_a_sample_larger_than_the_population_is_not_a_nan(self):
        result = calculateFisher(10, 20, 5, 8)

        self.assertFalse(math.isnan(result),
                         "hypergeom.sf returned NaN for a sample larger than "
                         "the population and it was passed straight through")
        self.assertEqual(result, 1.0,
                         "with the sample clamped to the whole population every "
                         "success is already drawn, so the honest answer is 1.0")

    def test_more_successes_than_exist_is_not_reported_as_maximal_evidence(self):
        """The `_usablePvalues` failure mode: a silent 1e-300.

        Unclamped, hypergeom.sf(29, 20, 5, 8) is exactly 0.0, floored to 1e-300
        -- the strongest evidence the function can express, for arguments that
        are arithmetically impossible.
        """
        result = calculateFisher(20, 8, 5, 30)

        self.assertGreater(result, 1e-100,
                           "impossible counts produced a near-zero p-value, "
                           "which puts a meaningless pathway at the top of the "
                           "results table")
        self.assertLessEqual(result, 1.0)

    def test_negative_counts_do_not_escape_the_domain(self):
        for arguments in [(-5, 2, 1, 1), (10, -2, 5, 3), (10, 5, -1, 2),
                          (10, 5, 3, -1), (0, 0, 0, 0)]:
            with self.subTest(arguments=arguments):
                result = calculateFisher(*arguments)

                self.assertTrue(math.isfinite(result), repr(arguments))
                self.assertTrue(0.0 < result <= 1.0, repr((arguments, result)))

    def test_in_domain_arguments_are_untouched(self):
        """The guard must not move a legitimate enrichment p-value."""
        from scipy.stats import hypergeom

        for population, sample, successes, drawn in [(100, 30, 20, 10),
                                                     (1000, 80, 50, 12),
                                                     (500, 50, 100, 20),
                                                     (50, 10, 5, 3)]:
            with self.subTest(population=population):
                self.assertAlmostEqual(
                    calculateFisher(population, sample, successes, drawn),
                    hypergeom.sf(drawn - 1, population, successes, sample),
                    places=15)

    def test_the_clamp_is_reported_so_the_real_bug_can_be_found(self):
        """Silent correction of a counting bug is how it survives for years."""
        records = []

        class _Handler(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Handler()
        root = logging.getLogger()
        previousLevel = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        try:
            # A tuple no other test in this file uses, so the module-level
            # dedup set cannot have seen it already.
            calculateFisher(7, 99, 3, 4)
        finally:
            root.removeHandler(handler)
            root.setLevel(previousLevel)

        warnings = [record for record in records
                    if record.levelno >= logging.WARNING
                    and "hypergeometric domain" in record.getMessage()]
        self.assertEqual(len(warnings), 1,
                         "expected exactly one warning naming the counts, got %d"
                         % len(warnings))
        self.assertIn("foundElems=99", warnings[0].getMessage())

    def test_the_warning_does_not_repeat_for_the_same_counts(self):
        """One WARNING per pathway per omic would bury the log."""
        records = []

        class _Handler(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Handler()
        root = logging.getLogger()
        previousLevel = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        try:
            for _ in range(5):
                calculateFisher(6, 88, 3, 4)
        finally:
            root.removeHandler(handler)
            root.setLevel(previousLevel)

        warnings = [record for record in records
                    if record.levelno >= logging.WARNING
                    and "hypergeometric domain" in record.getMessage()]
        self.assertEqual(len(warnings), 1,
                         "the same bad counts were reported %d times"
                         % len(warnings))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
