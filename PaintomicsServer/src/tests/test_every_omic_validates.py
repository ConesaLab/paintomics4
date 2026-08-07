#!/usr/bin/env python3
"""Every omic type the main upload accepts, run through the same guard.

Why this exists
---------------
`PathwayAcquisitionJob.validateFile` is the one guard every omic in the main
workflow passes through -- gene expression, proteomics, miRNA-seq, transcription
factor, DNase-seq and metabolomics alike. The tests it had covered two specific
regressions (a non-UTF-8 upload, and the multi-condition relevant-features rule)
on whichever omic reproduced them. Nothing asked whether the *other* omic types
behave the same way, and the difference matters: gene-based and compound-based
omics are validated in two separate loops, against a `nConditions` that the
first loop may already have fixed.

That shared `nConditions` is the contract worth pinning hardest. It is
established **once**, from the first values file found, and then threaded
through every remaining omic:

    for inputOmic in self.geneBasedInputOmics:
        nConditions, error = self.validateFile(inputOmic, nConditions, error)
    for inputOmic in self.compoundBasedInputOmics:
        nConditions, error = self.validateFile(inputOmic, nConditions, error)

So a six-omic job where the metabolomics table has five conditions and
everything else has six is not a metabolomics problem -- it is caught, or not
caught, depending on which file happened to be read first. A user who uploads
mismatched omics gets either a clear refusal or a job that runs on a silently
truncated matrix, and which one they get should not depend on ordering.

The bundled example cannot test any of it. Its six omics agree by construction,
and `validateFile` returns immediately when `isExample` is set, so the example
never enters the parsing code at all. Every file here is built by `fake_omics`.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_every_omic_validates
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.tests import fake_omics

# The gene-based omic types the form offers, and the builder for each. Named so
# a failure says "proteomics", not "case 3".
GENE_BASED_OMICS = [
    ("Gene expression", fake_omics.geneExpressionFile),
    ("Proteomics", fake_omics.proteomicsFile),
    ("miRNA-seq", fake_omics.miRNAFile),
    ("Transcription factor", fake_omics.transcriptionFactorFile),
]

COMPOUND_BASED_OMICS = [
    ("Metabolomics", fake_omics.metabolomicsFile),
]


class _OmicCase(unittest.TestCase):
    """Shared scratch job. Files must live in the job's own input dir."""

    def setUp(self):
        self._tmpRoot = tempfile.mkdtemp(prefix="paintomics_omics_") + "/"
        self.job = PathwayAcquisitionJob(jobID="omicmatrix", userID=None,
                                         CLIENT_TMP_DIR=self._tmpRoot)
        self.inputDir = self.job.getInputDir()
        os.makedirs(self.inputDir, exist_ok=True)
        self.job.geneBasedInputOmics = []
        self.job.compoundBasedInputOmics = []

    def tearDown(self):
        shutil.rmtree(self._tmpRoot, ignore_errors=True)

    def _error(self):
        try:
            self.job.validateInput()
            return ""
        except Exception as exc:
            return str(exc)


class EveryOmicTypeTest(_OmicCase):
    """The same shape, accepted or refused identically whatever the omic."""

    def test_each_gene_based_omic_is_accepted_on_its_own(self):
        for omicName, builder in GENE_BASED_OMICS:
            with self.subTest(omic=omicName):
                self.setUp()
                path = builder(self.inputDir, "%s.tab" % omicName.replace(" ", "_"))
                self.job.geneBasedInputOmics = [
                    fake_omics.omicInput(path, omicName=omicName)]

                self.assertEqual(self._error(), "",
                                 "a well-formed %s file was rejected" % omicName)
                self.tearDown()

    def test_each_compound_based_omic_is_accepted_on_its_own(self):
        for omicName, builder in COMPOUND_BASED_OMICS:
            with self.subTest(omic=omicName):
                self.setUp()
                path = builder(self.inputDir, "%s.tab" % omicName)
                self.job.compoundBasedInputOmics = [
                    fake_omics.omicInput(path, omicName=omicName)]

                self.assertEqual(self._error(), "",
                                 "a well-formed %s file was rejected" % omicName)
                self.tearDown()

    def test_a_ragged_row_is_refused_for_every_omic_type(self):
        """The guard must not be shape-blind for some omics and not others."""
        for omicName, _ in GENE_BASED_OMICS:
            with self.subTest(omic=omicName):
                self.setUp()
                path = fake_omics.raggedFile(self.inputDir, "ragged.tab",
                                             nConditions=4)
                self.job.geneBasedInputOmics = [
                    fake_omics.omicInput(path, omicName=omicName)]

                self.assertNotEqual(
                    self._error(), "",
                    "a ragged %s file was accepted" % omicName)
                self.tearDown()

    def test_a_non_numeric_value_is_refused_for_every_omic_type(self):
        for omicName, _ in GENE_BASED_OMICS:
            with self.subTest(omic=omicName):
                self.setUp()
                path = fake_omics.nonNumericValuesFile(self.inputDir,
                                                       "text.tab", nConditions=4)
                self.job.geneBasedInputOmics = [
                    fake_omics.omicInput(path, omicName=omicName)]

                self.assertNotEqual(
                    self._error(), "",
                    "a %s file holding text in a value column was accepted"
                    % omicName)
                self.tearDown()

    def test_a_missing_file_is_refused_for_every_omic_type(self):
        for omicName, _ in GENE_BASED_OMICS:
            with self.subTest(omic=omicName):
                self.setUp()
                self.job.geneBasedInputOmics = [{"omicName": omicName,
                                                 "inputDataFile": "absent.tab",
                                                 "isExample": False}]

                self.assertNotEqual(
                    self._error(), "",
                    "a missing %s file was accepted" % omicName)
                self.tearDown()


class CrossOmicConditionCountTest(_OmicCase):
    """nConditions is fixed once and reused, so mismatches are cross-omic."""

    def _sixOmicJob(self, metabolomicsConditions=3):
        """The example's shape: several gene-based omics plus metabolomics."""
        self.job.geneBasedInputOmics = [
            fake_omics.omicInput(
                builder(self.inputDir, "%s.tab" % name.replace(" ", "_"),
                        nConditions=3),
                omicName=name)
            for name, builder in GENE_BASED_OMICS]
        self.job.compoundBasedInputOmics = [
            fake_omics.omicInput(
                fake_omics.metabolomicsFile(
                    self.inputDir, "metabolomics.tab",
                    nConditions=metabolomicsConditions),
                omicName="Metabolomics")]

    def test_a_consistent_multi_omic_job_is_accepted(self):
        self._sixOmicJob(metabolomicsConditions=3)

        self.assertEqual(self._error(), "",
                         "a consistent five-omic job was rejected")

    def test_a_compound_omic_with_fewer_conditions_is_refused(self):
        """The mismatch a user actually makes: one table exported short.

        Metabolomics is validated in the second loop, against the nConditions
        the gene-based loop already fixed, so this is the case where the shared
        counter earns its keep.
        """
        self._sixOmicJob(metabolomicsConditions=2)

        error = self._error()
        self.assertNotEqual(
            error, "",
            "metabolomics with 2 conditions was accepted alongside gene-based "
            "omics with 3; the shared nConditions did not catch it")
        self.assertIn("metabolomics.tab", error,
                      "the refusal does not name the file that disagrees")

    def test_a_gene_omic_with_more_conditions_is_refused(self):
        self.job.geneBasedInputOmics = [
            fake_omics.omicInput(
                fake_omics.geneExpressionFile(self.inputDir, "ge.tab",
                                              nConditions=3),
                omicName="Gene expression"),
            fake_omics.omicInput(
                fake_omics.proteomicsFile(self.inputDir, "prot.tab",
                                          nConditions=5),
                omicName="Proteomics"),
        ]

        error = self._error()
        self.assertNotEqual(error, "",
                            "proteomics with 5 conditions was accepted next to "
                            "gene expression with 3")
        self.assertIn("prot.tab", error)

    def test_the_refusal_does_not_depend_on_upload_order(self):
        """The counter comes from whichever file is read first, so swap them.

        If ordering decided the outcome, a user could make the same mistake
        twice and be told about it only once.
        """
        outcomes = []
        for wideFirst in (False, True):
            self.setUp()
            widths = (5, 3) if wideFirst else (3, 5)
            self.job.geneBasedInputOmics = [
                fake_omics.omicInput(
                    fake_omics.geneExpressionFile(self.inputDir, "a.tab",
                                                  nConditions=widths[0]),
                    omicName="Gene expression"),
                fake_omics.omicInput(
                    fake_omics.proteomicsFile(self.inputDir, "b.tab",
                                              nConditions=widths[1]),
                    omicName="Proteomics"),
            ]
            outcomes.append(self._error() != "")
            self.tearDown()

        self.assertEqual(
            outcomes, [True, True],
            "a condition-count mismatch is refused in one upload order and "
            "accepted in the other: %s" % outcomes)


class AssociationsFileTest(_OmicCase):
    """The regulatory-omic sidecar, read by the MORE workflow."""

    def _regulatoryOmic(self, associations=None, relevantAssociations=None):
        entry = fake_omics.omicInput(
            fake_omics.transcriptionFactorFile(self.inputDir, "tf.tab"),
            omicName="Transcription factor")
        if associations is not None:
            entry["associationsFile"] = os.path.basename(associations)
        if relevantAssociations is not None:
            entry["relevantAssociationsFile"] = os.path.basename(relevantAssociations)
        self.job.geneBasedInputOmics = [entry]

    def test_a_two_column_associations_file_is_accepted(self):
        self._regulatoryOmic(associations=fake_omics.associationsFile(self.inputDir))

        self.assertEqual(self._error(), "")

    def test_an_associations_file_with_a_third_column_is_refused(self):
        """A p-value column pasted in from a stats table is the usual cause."""
        path = os.path.join(self.inputDir, "three_col.tab")
        with open(path, "w") as handle:
            handle.write("TF0001\tENSMUSG00000000001\t0.01\n")
        self._regulatoryOmic(associations=path)

        self.assertIn("does not look like an associations file", self._error())

    def test_a_relevant_associations_file_may_be_one_or_two_columns(self):
        """Both shapes are legal here, unlike the associations file itself."""
        for columns in (1, 2):
            self.setUp()
            path = os.path.join(self.inputDir, "rel_assoc_%d.tab" % columns)
            with open(path, "w") as handle:
                handle.write("\t".join(["TF0001", "ENSMUSG00000000001"][:columns]) + "\n")
            self._regulatoryOmic(relevantAssociations=path)

            self.assertEqual(self._error(), "",
                             "a %d-column relevant associations file was refused"
                             % columns)
            self.tearDown()

    def test_a_three_column_relevant_associations_file_is_refused(self):
        path = os.path.join(self.inputDir, "rel_assoc_3.tab")
        with open(path, "w") as handle:
            handle.write("TF0001\tENSMUSG00000000001\textra\n")
        self._regulatoryOmic(relevantAssociations=path)

        self.assertIn("expected 1 or 2 columns", self._error())


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
