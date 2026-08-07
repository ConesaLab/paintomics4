#!/usr/bin/env python3
"""End-to-end smoke test of the R backend, src/common/bioscripts/runMORE.R.

Everything else around MORE is tested with doubles, which is what let the
package mismatch survive: the failure lived entirely inside R. This test runs
the real script over a tiny fixture and checks the artefacts PA Step 1 goes on
to consume. It is the only test in the suite that actually executes MORE.

Deliberately small -- 8 targets, 4 regulators, 8 samples -- because cost is
linear in targets (~0.29 s/gene measured) and a suite that takes minutes stops
being run. Skips when Rscript or MORE is unavailable, so it never becomes a
hard R dependency.

What it covers that the contract test cannot
--------------------------------------------
* read_matrix, the association-orientation detection and parse_min_variation
  are top-level helpers in a script that runs its own argument parsing on
  source, so they cannot be sourced in isolation -- driving the script is the
  only way to reach them.
* The output file NAMES are a contract with MOREServlet.fromMOREtoGenes_STEP2,
  which reconstructs them independently from omic name and job date. If either
  side changes the pattern, STEP2 silently finds nothing and the user gets an
  empty result instead of an error.
* The values file must be keyed GENE:::REGULATOR, which is what
  parseGeneBasedFiles matches relevance against.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_runmore_r_endtoend
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

R_SCRIPT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "common", "bioscripts", "runMORE.R"))

DATE = "209901011200"
SAMPLES = ["Ctrl_R1", "Ctrl_R2", "Ctrl_R3", "Ctrl_R4",
           "Treat_R1", "Treat_R2", "Treat_R3", "Treat_R4"]
REGULATORS = ["TFA", "TFB", "TFC", "TFD"]
TARGETS = ["G%d" % i for i in range(1, 9)]


def rHasMore():
    if not shutil.which("Rscript"):
        return False
    proc = subprocess.run(
        ["Rscript", "-e",
         'cat(requireNamespace("MORE", quietly=TRUE) && '
         'requireNamespace("optparse", quietly=TRUE))'],
        capture_output=True, text=True, timeout=180)
    return proc.returncode == 0 and "TRUE" in proc.stdout


@unittest.skipUnless(rHasMore(), "Rscript with MORE and optparse is not available")
class RunMoreEndToEndTest(unittest.TestCase):
    """One MORE run shared by every assertion -- it is the expensive part."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="runmore_e2e_")
        cls.dataDir = os.path.join(cls.tmp, "in")
        cls.outDir = os.path.join(cls.tmp, "out")
        os.makedirs(cls.dataDir)
        os.makedirs(cls.outDir)
        cls.writeFixture(cls.dataDir)
        cls.proc = cls.runScript(cls.dataDir, cls.outDir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- fixture ---------------------------------------------------------
    @staticmethod
    def writeFixture(directory, swapAssociationColumns=False):
        """Targets are exact linear functions of their regulators, so MORE has
        unambiguous signal and the test does not depend on a p-value threshold
        landing a particular way."""
        base = [1.0, 1.2, 0.9, 1.1, 4.0, 4.3, 3.8, 4.1]
        reg = {}
        for idx, name in enumerate(REGULATORS):
            reg[name] = [v + idx * 0.35 for v in base]

        with open(os.path.join(directory, "regulators.tab"), "w") as fh:
            fh.write("RegulatorID\t" + "\t".join(SAMPLES) + "\n")
            for name in REGULATORS:
                fh.write(name + "\t" + "\t".join("%.4f" % v for v in reg[name]) + "\n")

        edges = []
        with open(os.path.join(directory, "targets.tab"), "w") as fh:
            fh.write("GeneID\t" + "\t".join(SAMPLES) + "\n")
            for i, gene in enumerate(TARGETS):
                driver = REGULATORS[i % len(REGULATORS)]
                edges.append((gene, driver))
                values = [2.0 + 1.5 * v + 0.01 * i for v in reg[driver]]
                fh.write(gene + "\t" + "\t".join("%.4f" % v for v in values) + "\n")

        with open(os.path.join(directory, "conditions.tab"), "w") as fh:
            fh.write("Sample\tCtrl\tTreat\n")
            for s in SAMPLES:
                t = int(s.startswith("Treat"))
                fh.write("%s\t%d\t%d\n" % (s, 1 - t, t))

        assocPath = os.path.join(directory, "assoc.tab")
        with open(assocPath, "w") as fh:
            if swapAssociationColumns:
                # Regulator first: runMORE.R must detect and swap this.
                fh.write("Regulator\tTarget\n")
                for gene, driver in edges:
                    fh.write("%s\t%s\n" % (driver, gene))
            else:
                fh.write("Target\tRegulator\n")
                for gene, driver in edges:
                    fh.write("%s\t%s\n" % (gene, driver))
        return edges

    @staticmethod
    def runScript(dataDir, outDir, omicName="TF"):
        cmd = [
            "Rscript", R_SCRIPT,
            "--target_file", os.path.join(dataDir, "targets.tab"),
            "--condition_file", os.path.join(dataDir, "conditions.tab"),
            "--omic_names", omicName,
            "--data_files", os.path.join(dataDir, "regulators.tab"),
            "--assoc_files", os.path.join(dataDir, "assoc.tab"),
            "--min_variation", "NA",
            "--method", "PLS1", "--alpha", "0.05", "--vip", "0.8",
            "--filter_r2", "0.0",
            "--output_dir", outDir, "--date_seed", DATE,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=900)

    # -- the run itself --------------------------------------------------
    def test_exits_cleanly(self):
        self.assertEqual(self.proc.returncode, 0,
                         "runMORE.R failed:\n%s" % (self.proc.stdout or "")[-3000:])

    def test_reports_completion(self):
        self.assertIn("Analysis complete", self.proc.stdout)

    def test_loads_both_matrices(self):
        self.assertIn("Loaded target data with %d features" % len(TARGETS),
                      self.proc.stdout)
        self.assertIn("Loaded regulatory omic TF with %d features" % len(REGULATORS),
                      self.proc.stdout)

    def test_aligns_every_sample(self):
        self.assertIn("Found %d common samples" % len(SAMPLES), self.proc.stdout)

    def test_honours_the_auto_min_variation_sentinel(self):
        self.assertIn("TF=NA (auto)", self.proc.stdout)

    # -- artefacts STEP2 reconstructs by name ----------------------------
    def test_writes_the_values_file_under_the_expected_name(self):
        self.assertTrue(os.path.exists(
            os.path.join(self.outDir, "MORE_output_TF_%s.tab" % DATE)))

    def test_writes_the_association_and_pairs_files(self):
        for prefix in ("MORE_relevant_assoc", "MORE_relevant_pairs"):
            path = os.path.join(self.outDir, "%s_TF_%s.tab" % (prefix, DATE))
            self.assertTrue(os.path.exists(path), path)

    def test_writes_the_regulation_per_condition_table(self):
        self.assertTrue(os.path.exists(
            os.path.join(self.outDir, "MORE_rpc_%s.tab" % DATE)))

    def test_values_file_is_keyed_gene_colon_regulator(self):
        """parseGeneBasedFiles matches relevance on this exact key shape."""
        path = os.path.join(self.outDir, "MORE_output_TF_%s.tab" % DATE)
        with open(path) as fh:
            rows = [l for l in fh if l.strip()]
        self.assertTrue(rows, "values file is empty")
        keyed = [r for r in rows if ":::" in r.split("\t")[0]]
        self.assertTrue(keyed, "no GENE:::REGULATOR keys in %s" % path)

    def test_rpc_table_carries_r2(self):
        """The Step-3 network view filters on this column client-side."""
        path = os.path.join(self.outDir, "MORE_rpc_%s.tab" % DATE)
        with open(path) as fh:
            header = fh.readline().rstrip("\n").split("\t")
        for column in ("targetF", "regulator", "omic", "R2"):
            self.assertIn(column, header)

    def test_rpc_table_has_rows(self):
        path = os.path.join(self.outDir, "MORE_rpc_%s.tab" % DATE)
        with open(path) as fh:
            rows = fh.readlines()[1:]
        self.assertTrue([r for r in rows if r.strip()],
                        "MORE found no regulations on a fixture built from "
                        "exact linear relationships")

    def test_recovers_the_planted_regulators(self):
        """Each target is an exact linear function of one regulator, so the
        edges MORE reports should be the ones that were planted."""
        path = os.path.join(self.outDir, "MORE_rpc_%s.tab" % DATE)
        with open(path) as fh:
            header = fh.readline().rstrip("\n").split("\t")
            ti, ri = header.index("targetF"), header.index("regulator")
            found = set()
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) > max(ti, ri):
                    found.add((parts[ti], parts[ri]))
        planted = {(g, REGULATORS[i % len(REGULATORS)])
                   for i, g in enumerate(TARGETS)}
        self.assertTrue(found & planted,
                        "none of the planted edges were recovered: %s" % sorted(found))


@unittest.skipUnless(rHasMore(), "Rscript with MORE and optparse is not available")
class AssociationOrientationTest(unittest.TestCase):
    """runMORE.R auto-detects a reversed association file by counting which
    column matches the regulator IDs. Users do supply them either way round."""

    def test_a_regulator_first_association_file_still_runs(self):
        tmp = tempfile.mkdtemp(prefix="runmore_swap_")
        try:
            dataDir = os.path.join(tmp, "in")
            outDir = os.path.join(tmp, "out")
            os.makedirs(dataDir)
            os.makedirs(outDir)
            RunMoreEndToEndTest.writeFixture(dataDir, swapAssociationColumns=True)
            proc = RunMoreEndToEndTest.runScript(dataDir, outDir)
            self.assertEqual(proc.returncode, 0,
                             "swapped association file failed:\n%s"
                             % (proc.stdout or "")[-3000:])
            self.assertIn("Detected Regulator in Column 1", proc.stdout)
            self.assertTrue(os.path.exists(
                os.path.join(outDir, "MORE_rpc_%s.tab" % DATE)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
