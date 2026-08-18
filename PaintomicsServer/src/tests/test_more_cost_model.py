#!/usr/bin/env python3
"""Cover for src/common/MORECostModel.py -- the MORE pre-flight runtime guard.

Why this needs real coverage
----------------------------
The guard *refuses submissions*. A bug here does not produce a wrong number in
a report, it stops a scientist running an analysis they are entitled to run,
with a message telling them their data is too big when it is not. That asymmetry
drives most of what is tested below: the probe must never over-count, the
estimate must never over-predict, and any failure to read the inputs must
degrade to "let it through" rather than to a refusal or a 500.

The two probe behaviours worth spelling out:

* **Column orientation.** runMORE.R decides which association column holds the
  regulator by counting matches against the regulator matrix's row names, and
  swaps if needed -- so both layouts are legal input. A probe that assumed
  "column 0 is the gene" would, on a swapped file, report ~600 genes with 17
  regulators each instead of ~10,000 genes with 30: a 16x under-estimate, which
  would wave through exactly the jobs the guard exists to stop.
* **Bytes, not text.** ensure_utf8 runs in STEP2, after this. At the gate a
  file may still be cp1252, so the probe must not decode.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_cost_model
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common.MORECostModel import (
    MOREShape, checkBudget, estimateSeconds, probeShape)


def write(path, text, encoding="utf-8", newline="\n"):
    body = text.replace("\n", newline)
    with open(path, "wb") as handle:
        handle.write(body.encode(encoding))
    return path


class ProbeTestCase(unittest.TestCase):
    """Shared fixture: a small but structurally real MORE submission."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="morecost")
        # 4 samples in 2 groups.
        write(os.path.join(self.dir, "design.tab"),
              "Sample\tCtr\tTrt\nS1\t1\t0\nS2\t1\t0\nS3\t0\t1\nS4\t0\t1\n")
        # 3 genes x 4 samples.
        write(os.path.join(self.dir, "targets.tab"),
              "Gene\tS1\tS2\tS3\tS4\n"
              "G1\t1\t2\t3\t4\nG2\t2\t3\t4\t5\nG3\t3\t4\t5\t6\n")
        # 2 regulators x 4 samples.
        write(os.path.join(self.dir, "regs.tab"),
              "RegulatorID\tS1\tS2\tS3\tS4\n"
              "TF1\t1\t2\t3\t4\nTF2\t2\t3\t4\t5\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def omic(self, associations="assoc.tab"):
        return [{"name": "TF", "file": "regs.tab", "associations": associations}]

    def probe(self, omics=None):
        return probeShape(self.dir, "targets.tab", "design.tab",
                          omics if omics is not None else self.omic())


class ShapeProbe(ProbeTestCase):

    def test_reads_the_submitted_shape(self):
        write(os.path.join(self.dir, "assoc.tab"),
              "Target\tRegulator\nG1\tTF1\nG1\tTF2\nG2\tTF1\nG3\tTF2\n")
        shape = self.probe()
        self.assertEqual(shape.modelledGenes, 3)
        self.assertEqual(shape.samples, 4)
        self.assertEqual(shape.groups, 2)
        self.assertEqual(shape.associations, 4)
        self.assertEqual(shape.regulators, 2)
        self.assertAlmostEqual(shape.regPerGene, 4 / 3.0, places=4)
        self.assertFalse(shape.unassociated)

    def test_a_gene_without_associations_is_not_modelled(self):
        """The cost is per modelled gene, not per uploaded row.

        G3 has no regulator, so MORE never fits it. Counting it would inflate
        the estimate by a third on this fixture, and by far more on real data
        where most genes have no annotated regulator.
        """
        write(os.path.join(self.dir, "assoc.tab"),
              "Target\tRegulator\nG1\tTF1\nG2\tTF1\n")
        self.assertEqual(self.probe().modelledGenes, 2)

    def test_detects_a_swapped_association_file(self):
        """Regulator-first is legal input; runMORE.R swaps it. So must we."""
        write(os.path.join(self.dir, "assoc.tab"),
              "Regulator\tTarget\nTF1\tG1\nTF2\tG1\nTF1\tG2\nTF2\tG3\n")
        shape = self.probe()
        self.assertEqual(shape.modelledGenes, 3, "counted regulators as genes")
        self.assertEqual(shape.associations, 4)

    def test_no_association_file_is_the_cartesian_case(self):
        """No associations means every regulator against every gene."""
        for missing in (None, "NULL"):
            shape = self.probe(self.omic(associations=missing))
            self.assertTrue(shape.unassociated)
            self.assertEqual(shape.modelledGenes, 3)
            self.assertEqual(shape.associations, 6)  # 2 regulators x 3 genes

    def test_multi_omic_sums_edges_but_not_genes(self):
        """One model per gene uses every omic at once -- genes must not double.

        Summing genes across omics would report 6 genes for a 3-gene dataset
        regulated by both a TF and a miRNA, and estimate twice the runtime.
        """
        write(os.path.join(self.dir, "assoc.tab"),
              "Target\tRegulator\nG1\tTF1\nG2\tTF1\n")
        write(os.path.join(self.dir, "mirna.tab"),
              "RegulatorID\tS1\tS2\tS3\tS4\nmir1\t1\t2\t3\t4\n")
        write(os.path.join(self.dir, "massoc.tab"),
              "Target\tRegulator\nG1\tmir1\nG3\tmir1\n")
        shape = self.probe([
            {"name": "TF", "file": "regs.tab", "associations": "assoc.tab"},
            {"name": "miRNA", "file": "mirna.tab", "associations": "massoc.tab"},
        ])
        self.assertEqual(shape.modelledGenes, 2)
        self.assertEqual(shape.associations, 4)
        self.assertEqual(shape.regulators, 3)

    def test_never_reports_more_genes_than_have_expression(self):
        """An association file may name genes absent from the target matrix."""
        write(os.path.join(self.dir, "assoc.tab"),
              "Target\tRegulator\nG1\tTF1\nG2\tTF1\nG3\tTF1\n"
              "GHOST1\tTF1\nGHOST2\tTF1\n")
        self.assertEqual(self.probe().modelledGenes, 3)


class ProbeRobustness(ProbeTestCase):
    """Malformed, unusual and unreadable input must not produce a refusal."""

    def test_crlf(self):
        write(os.path.join(self.dir, "assoc.tab"),
              "Target\tRegulator\nG1\tTF1\nG2\tTF2\n", newline="\r\n")
        shape = self.probe()
        self.assertEqual(shape.associations, 2)
        self.assertEqual(shape.modelledGenes, 2)

    def test_no_trailing_newline(self):
        with open(os.path.join(self.dir, "assoc.tab"), "wb") as handle:
            handle.write(b"Target\tRegulator\nG1\tTF1\nG2\tTF2")
        self.assertEqual(self.probe().associations, 2)

    def test_cp1252_does_not_raise(self):
        """ensure_utf8 has not run yet at the gate -- decoding would throw."""
        write(os.path.join(self.dir, "assoc.tab"),
              u"Target\tRegulator\nGéne1\tTF1\nG2\tTF2\n",
              encoding="cp1252")
        shape = self.probe()
        self.assertEqual(shape.associations, 2)
        self.assertEqual(shape.modelledGenes, 2)

    def test_comma_separated(self):
        write(os.path.join(self.dir, "assoc.tab"),
              "Target,Regulator\nG1,TF1\nG2,TF2\n")
        self.assertEqual(self.probe().associations, 2)

    def test_missing_files_yield_an_empty_shape_not_an_exception(self):
        shape = probeShape(self.dir, "nope.tab", "gone.tab",
                           [{"name": "TF", "file": "absent.tab",
                             "associations": "vanished.tab"}])
        self.assertEqual(shape.modelledGenes, 0)
        self.assertEqual(estimateSeconds(shape, "MLR", "r"), 0.0)
        self.assertIsNone(checkBudget(shape, "MLR", "r", 1800),
                          "an unreadable job must reach STEP2's file errors, "
                          "not be refused as too large")

    def test_header_only_association_file(self):
        write(os.path.join(self.dir, "assoc.tab"), "Target\tRegulator\n")
        shape = self.probe()
        self.assertEqual(shape.associations, 0)
        self.assertEqual(shape.modelledGenes, 0)

    def test_no_regulatory_omics(self):
        shape = self.probe([])
        self.assertEqual(shape.modelledGenes, 0)
        self.assertIsNone(checkBudget(shape, "MLR", "r", 1800))


class Estimate(unittest.TestCase):

    def shape(self, genes=1000, regPerGene=30.0, samples=36, groups=12):
        return MOREShape(modelledGenes=genes, samples=samples, groups=groups,
                         regPerGene=regPerGene)

    def test_linear_in_genes(self):
        """Measured 1.28 s/gene at 25 genes and 1.21 at 200 -- linear holds."""
        one = estimateSeconds(self.shape(genes=100), "MLR", "r")
        ten = estimateSeconds(self.shape(genes=1000), "MLR", "r")
        self.assertAlmostEqual(ten / one, 10.0, places=3)

    def test_monotonic_in_every_axis(self):
        base = estimateSeconds(self.shape(), "MLR", "r")
        self.assertGreater(estimateSeconds(self.shape(genes=2000), "MLR", "r"), base)
        self.assertGreater(estimateSeconds(self.shape(regPerGene=60), "MLR", "r"), base)
        self.assertGreater(estimateSeconds(self.shape(groups=24), "MLR", "r"), base)

    def test_regulators_per_gene_is_not_quadratic(self):
        """p=5 -> 102.7 s and p=10 -> 106.2 s at 100 genes: 2x in p bought 3%.

        A quadratic term would over-predict a wide dataset by an order of
        magnitude and refuse jobs that finish comfortably.
        """
        base = estimateSeconds(self.shape(regPerGene=30), "MLR", "r")
        doubled = estimateSeconds(self.shape(regPerGene=60), "MLR", "r")
        self.assertLess(doubled / base, 1.5)

    def test_mlr_costs_more_than_pls1_on_r(self):
        self.assertGreater(estimateSeconds(self.shape(), "MLR", "r"),
                           estimateSeconds(self.shape(), "PLS1", "r"))

    def test_the_port_is_orders_of_magnitude_cheaper(self):
        """The engine, not just the method, decides -- that is the whole point."""
        self.assertLess(estimateSeconds(self.shape(), "PLS1", "rust"),
                        estimateSeconds(self.shape(), "PLS1", "r") / 100.0)

    def test_the_port_wins_on_pls1_but_barely_on_mlr(self):
        """The engine asymmetry is not symmetric across methods, and assuming
        it was put a 66x error in this table.

        `ropls` has no compiled core, so PLS1 on R is interpreted R and the port
        routs it 660x. R's MLR is `glmnet.so` -- tuned Fortran -- where the port
        wins only ~4.7x, and that purely from rayon. An earlier draft
        extrapolated the MLR row from the PLS1 ratio and got 0.0040 s/gene
        against a measured 0.263: a 30-minute job quoted at 30 seconds, in
        exactly the case this module exists to catch. No longer latent --
        `rust-mlr` is a catalogue entry and _resolveMOREBackend routes MLR to
        the port when a caller names `rust` -- so this is now guarding a live
        code path rather than a dormant one.
        """
        shape = self.shape()
        pls1Speedup = (estimateSeconds(shape, "PLS1", "r")
                       / estimateSeconds(shape, "PLS1", "rust"))
        mlrSpeedup = (estimateSeconds(shape, "MLR", "r")
                      / estimateSeconds(shape, "MLR", "rust"))
        self.assertGreater(pls1Speedup, 100)
        self.assertLess(mlrSpeedup, 20,
                        "the port does not beat Fortran glmnet by an order of "
                        "magnitude; a large ratio here means the MLR constant "
                        "was extrapolated rather than measured")

    def test_a_large_design_is_not_over_predicted(self):
        """The design exponent is ~0.27, not 1.0.

        The first draft assumed the cost scaled linearly with samples x groups,
        because the design matrix is ~p*G columns wide. Measured over a 9x in
        n*G, runtime rose 1.8-1.9x. At an exponent of 1.0 a 100-sample,
        20-group study is quoted 4.6x its true cost and refused outright.
        """
        base = estimateSeconds(self.shape(samples=36, groups=12), "MLR", "r")
        big = estimateSeconds(self.shape(samples=100, groups=20), "MLR", "r")
        ratio = big / base
        self.assertGreater(ratio, 1.0)
        self.assertLess(ratio, 2.0, "design term is scaling far too steeply")

    def test_reproduces_the_calibration_measurements(self):
        """Fitted model vs the cells it was fitted on, one process at a time.

        Guards against a constant being edited in isolation and silently
        detaching the model from the sweep behind it. Tolerance is 25%: the
        worst genuine residual is 17%, and a repeated shape (p=30) measured
        62.6 s and 72.1 s on the same machine, so ~15% is the noise floor.
        """
        # (genes, regPerGene, samples, groups, method, measured seconds)
        cells = [
            (25, 30.0, 36, 12, "PLS1", 18.4), (25, 30.0, 36, 12, "MLR", 32.1),
            (50, 29.5, 36, 12, "PLS1", 32.8), (50, 29.5, 36, 12, "MLR", 61.2),
            (100, 30.0, 36, 12, "PLS1", 62.6), (100, 30.0, 36, 12, "MLR", 123.0),
            (200, 29.6, 36, 12, "PLS1", 124.6), (200, 29.6, 36, 12, "MLR", 241.8),
            (100, 5.0, 36, 12, "PLS1", 38.9), (100, 5.0, 36, 12, "MLR", 102.7),
            (100, 20.0, 36, 12, "PLS1", 53.7), (100, 20.0, 36, 12, "MLR", 125.0),
            (100, 30.0, 12, 4, "PLS1", 35.4), (100, 30.0, 12, 4, "MLR", 71.4),
            (100, 30.0, 24, 8, "PLS1", 54.9), (100, 30.0, 24, 8, "MLR", 119.0),
        ]
        for genes, regs, samples, groups, method, measured in cells:
            predicted = estimateSeconds(
                self.shape(genes=genes, regPerGene=regs, samples=samples,
                           groups=groups), method, "r")
            error = abs(predicted - measured) / measured
            self.assertLess(
                error, 0.25,
                "%s at %d genes / p=%g / n=%d / G=%d: predicted %.1f s vs "
                "measured %.1f s (%.0f%% off)"
                % (method, genes, regs, samples, groups, predicted, measured,
                   100 * error))

    def test_an_uncalibrated_combination_is_not_free(self):
        """A method added to runMORE.R but not here must be gated, not waved on."""
        unknown = estimateSeconds(self.shape(), "GLMNET", "r")
        self.assertGreater(unknown, 0.0)
        self.assertGreaterEqual(
            unknown, estimateSeconds(self.shape(), "MLR", "r") * 0.99)

    def test_an_unknown_engine_falls_back_to_r_for_a_known_method(self):
        self.assertAlmostEqual(estimateSeconds(self.shape(), "MLR", "wasm"),
                               estimateSeconds(self.shape(), "MLR", "r"))


class Budget(unittest.TestCase):

    def bigShape(self):
        """The real STATegra set: 9,835 genes, 36 samples, 12 groups, ~30 p/gene."""
        return MOREShape(modelledGenes=9835, samples=36, groups=12,
                         regPerGene=29.6, regulators=564, associations=291353)

    def test_the_real_dataset_is_refused_on_r(self):
        """Measured ~3.4 h for MLR and ~1.7 h for PLS1 -- both over 1800 s."""
        for method in ("MLR", "PLS1"):
            self.assertIsNotNone(
                checkBudget(self.bigShape(), method, "r", 1800),
                "%s on R must be refused at genome scale" % method)

    def test_the_same_dataset_is_allowed_on_the_port(self):
        """~9 s measured. Gating this would be a pure false positive."""
        self.assertIsNone(checkBudget(self.bigShape(), "PLS1", "rust", 1800))

    def test_a_realistic_small_job_is_allowed(self):
        """~500 DE genes is the shape the guard must never touch."""
        shape = MOREShape(modelledGenes=500, samples=36, groups=12,
                          regPerGene=30.0)
        self.assertIsNone(checkBudget(shape, "MLR", "r", 1800))

    def test_a_zero_budget_disables_the_guard(self):
        self.assertIsNone(checkBudget(self.bigShape(), "MLR", "r", 0))
        self.assertIsNone(checkBudget(self.bigShape(), "MLR", "r", None))

    def test_the_estimate_under_predicts_the_measurement(self):
        """Deliberately optimistic: refusing a job that would finish is worse
        than the status quo of hitting the queue timeout. R MLR on the real set
        measured ~3.4 h; the estimate must sit at or below that."""
        estimate = estimateSeconds(self.bigShape(), "MLR", "r")
        self.assertLess(estimate, 3.4 * 3600)
        # ...but not so low it stops firing.
        self.assertGreater(estimate, 1800)

    def test_the_refusal_names_the_numbers_and_a_way_out(self):
        message = checkBudget(self.bigShape(), "MLR", "r", 1800)
        self.assertIn("9835 genes", message)
        self.assertIn("30 minutes", message)
        self.assertIn("PLS1", message, "an MLR refusal must offer the faster method")

    def test_an_mlr_refusal_does_not_promise_pls1_will_fix_it(self):
        """Only offer the method switch when the switch actually works.

        PLS1 is ~2x faster than MLR on R, which does not rescue a genome-scale
        job: the real dataset is 3.3 h as MLR and still 1.7 h as PLS1, both
        refused. Telling that user to "switch to PLS1" walks them into a second
        refusal.
        """
        message = checkBudget(self.bigShape(), "MLR", "r", 1800)
        self.assertIn("will not be enough on its own", message)
        self.assertIn("reduce the number of genes", message)

    def test_an_mlr_refusal_does_promise_it_when_it_is_true(self):
        """The mirror case: small enough that PLS1 clears the budget."""
        shape = MOREShape(modelledGenes=2200, samples=36, groups=12,
                          regPerGene=30.0)
        self.assertIsNotNone(checkBudget(shape, "MLR", "r", 1800),
                             "fixture must be over budget as MLR")
        message = checkBudget(shape, "MLR", "r", 1800)
        self.assertIn("inside the limit", message)
        self.assertNotIn("will not be enough", message)

    def test_a_pls1_refusal_does_not_suggest_pls1(self):
        message = checkBudget(self.bigShape(), "PLS1", "r", 1800)
        self.assertNotIn("switching to it", message)
        self.assertIn("reduce the number of genes", message)

    def test_a_cartesian_job_is_told_why_it_is_expensive(self):
        shape = MOREShape(modelledGenes=9835, samples=36, groups=12,
                          regPerGene=564.0, unassociated=True)
        message = checkBudget(shape, "MLR", "r", 1800)
        self.assertIn("association file", message)


class RustMlrShapeModel(unittest.TestCase):
    """The port's MLR cost against every shape actually measured.

    The R rows fit a power law in `samples * groups`. That form cannot describe
    the port, because its cost is dominated by the cross-validation fold count
    and MORE's fold rule (`mynfolds`, auxFunctions.R:452) is a step function
    that steps **down** at 50 samples: below 50 it is leave-one-out, at 50 it
    collapses to 5. Measured consequence, p = 12: a 60-sample study costs
    0.0391 s/gene where a 36-sample one costs 0.1928 -- five times *less* work
    from more data, while `samples * groups` says 1.7x more.

    With the R exponents the estimate under-predicted rust MLR by up to 1.35x
    just below the fold cliff, and under-prediction is the failure that matters:
    it waves a job through to die on the queue timeout, which is the exact
    outcome this module exists to prevent.
    """

    def shape(self, genes, regPerGene, samples, groups):
        return MOREShape(modelledGenes=genes, samples=samples, groups=groups,
                         regPerGene=regPerGene)

    # (label, genes, regPerGene, samples, groups, measured seconds-per-gene).
    # Synthetic rows are 60-200 target sweeps on this machine; `rand1` and
    # `stategra` are the two real datasets.
    MEASURED = [
        ("p=3",              200,  3.00, 36, 12, 0.05180),
        ("p=6",              200,  6.00, 36, 12, 0.12200),
        ("p=12",             200, 12.00, 36, 12, 0.22540),
        ("p=20",             200, 20.00, 36, 12, 0.23460),
        ("p=30",             200, 30.00, 36, 12, 0.22570),
        ("rand1",             98, 29.71, 36, 12, 0.23469),
        ("stategra",         957,  3.04, 36, 12, 0.02612),
        ("n=48 G=12 (LOO)",   60, 30.00, 48, 12, 0.32042),
        ("n=48 G=16 (LOO)",   60, 30.00, 48, 16, 0.41430),
        ("n=51 G=17 (5-fold)", 60, 30.00, 51, 17, 0.05040),
        ("n=60 G=12 (5-fold)", 100, 12.00, 60, 12, 0.03912),
    ]

    def test_never_under_predicts_any_measured_shape(self):
        """Over-prediction refuses a job that would have fitted; that is
        recoverable and visible. Under-prediction accepts one that cannot, and
        the user waits out the whole timeout to learn nothing."""
        for label, genes, reg, samples, groups, measured in self.MEASURED:
            est = estimateSeconds(self.shape(genes, reg, samples, groups),
                                  "MLR", "rust") / genes
            self.assertGreaterEqual(
                est, measured,
                "%s: model %.5f s/gene under-predicts the measured %.5f"
                % (label, est, measured))

    def test_does_not_over_predict_by_more_than_a_factor_of_three(self):
        """A guard that quotes ten times the truth refuses analyses a
        scientist is entitled to run, which is its other failure mode."""
        for label, genes, reg, samples, groups, measured in self.MEASURED:
            est = estimateSeconds(self.shape(genes, reg, samples, groups),
                                  "MLR", "rust") / genes
            self.assertLess(est / measured, 3.0,
                            "%s: model over-predicts by %.2fx"
                            % (label, est / measured))

    def test_the_fold_cliff_makes_more_samples_cheaper(self):
        """The property no power law in samples*groups can express."""
        loo = estimateSeconds(self.shape(100, 12.0, 48, 12), "MLR", "rust")
        fiveFold = estimateSeconds(self.shape(100, 12.0, 51, 12), "MLR", "rust")
        self.assertLess(fiveFold, loo,
                        "51 samples cross-validates 5-fold and 48 samples "
                        "leave-one-out, so the larger study must be cheaper")

    def test_the_r_rows_are_untouched_by_the_rust_shape_model(self):
        """The new term is scoped to ("MLR", "rust"); R's calibration stands."""
        shape = self.shape(1000, 30.0, 36, 12)
        self.assertAlmostEqual(estimateSeconds(shape, "MLR", "r"), 1198.0, places=3)
        self.assertAlmostEqual(estimateSeconds(shape, "PLS1", "r"), 607.0, places=3)



if __name__ == "__main__":
    unittest.main(verbosity=2)


