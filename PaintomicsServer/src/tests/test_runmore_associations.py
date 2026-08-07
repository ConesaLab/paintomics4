#!/usr/bin/env python3
"""runMORE.R's association-file handling: orientation, shape, and ID overlap.

The association file decides which regulators are candidates for which target,
and runMORE.R has to guess its column order because users produce these files
by hand and from half a dozen databases. Guessing wrong inverts every edge in
the analysis; guessing on a file whose IDs match nothing produces an empty
result that looks exactly like "no significant regulation".

That last case was silent. runMORE.R logged the match counts and carried on,
so a job pairing (say) Ensembl-keyed associations with a symbol-keyed
regulator matrix ran to completion, wrote its output files, and told the user
nothing was significant. Both no-overlap cases now stop with a diagnostic that
prints the two ID spaces side by side, in the same shape as the existing
sample-alignment error.

The failure cases here exit before more() is ever called, so they cost an R
startup each rather than a model fit.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_runmore_associations
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


HAS_MORE = rHasMore()


def writeInputs(directory):
    """Targets are exact linear functions of one regulator each, so any run
    that gets as far as the model has unambiguous signal."""
    base = [1.0, 1.2, 0.9, 1.1, 4.0, 4.3, 3.8, 4.1]
    reg = {name: [v + i * 0.35 for v in base] for i, name in enumerate(REGULATORS)}

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
            fh.write(gene + "\t" + "\t".join(
                "%.4f" % (2.0 + 1.5 * v + 0.01 * i) for v in reg[driver]) + "\n")

    with open(os.path.join(directory, "conditions.tab"), "w") as fh:
        fh.write("Sample\tCtrl\tTreat\n")
        for s in SAMPLES:
            t = int(s.startswith("Treat"))
            fh.write("%s\t%d\t%d\n" % (s, 1 - t, t))
    return edges


def writeAssociations(directory, rows, header):
    path = os.path.join(directory, "assoc.tab")
    with open(path, "w") as fh:
        fh.write("\t".join(header) + "\n")
        for row in rows:
            fh.write("\t".join(row) + "\n")
    return path


def runScript(dataDir, outDir):
    return subprocess.run([
        "Rscript", R_SCRIPT,
        "--target_file", os.path.join(dataDir, "targets.tab"),
        "--condition_file", os.path.join(dataDir, "conditions.tab"),
        "--omic_names", "TF",
        "--data_files", os.path.join(dataDir, "regulators.tab"),
        "--assoc_files", os.path.join(dataDir, "assoc.tab"),
        "--min_variation", "NA",
        "--method", "PLS1", "--alpha", "0.05", "--vip", "0.8",
        "--filter_r2", "0.0",
        "--output_dir", outDir, "--date_seed", DATE,
    ], capture_output=True, text=True, timeout=900)


class AssociationCaseMixin(object):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="runmore_assoc_")
        self.dataDir = os.path.join(self.tmp, "in")
        self.outDir = os.path.join(self.tmp, "out")
        os.makedirs(self.dataDir)
        os.makedirs(self.outDir)
        self.edges = writeInputs(self.dataDir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_with(self, rows, header):
        writeAssociations(self.dataDir, rows, header)
        return runScript(self.dataDir, self.outDir)


@unittest.skipUnless(HAS_MORE, "Rscript with MORE and optparse is not available")
class RejectedAssociationsTest(AssociationCaseMixin, unittest.TestCase):
    """Shapes the script must refuse. All exit before the model call."""

    def assertFailsWith(self, proc, *fragments):
        self.assertNotEqual(proc.returncode, 0,
                            "script succeeded; stdout tail:\n%s" % proc.stdout[-800:])
        combined = proc.stdout + proc.stderr
        for fragment in fragments:
            self.assertIn(fragment, combined)

    def test_regulator_ids_matching_neither_column_is_an_error(self):
        """The silent case: nothing in the file names a regulator that exists,
        so every target ends up unregulated and the run finishes empty."""
        rows = [(gene, "ENSG%08d" % i) for i, (gene, _) in enumerate(self.edges)]
        self.assertFailsWith(self.run_with(rows, ["Target", "Regulator"]),
                             "shares no regulator IDs with its data file")

    def test_the_no_regulator_overlap_error_shows_both_id_spaces(self):
        """A count alone does not tell the user which file to fix."""
        rows = [(gene, "ENSG%08d" % i) for i, (gene, _) in enumerate(self.edges)]
        proc = self.run_with(rows, ["Target", "Regulator"])
        self.assertIn("ENSG00000000", proc.stdout + proc.stderr)
        self.assertIn("TFA", proc.stdout + proc.stderr)

    def test_targets_matching_nothing_in_the_expression_file_is_an_error(self):
        """Regulators line up but targets do not -- equally unmodellable, and
        equally silent before."""
        rows = [("ENSG%08d" % i, driver) for i, (_, driver) in enumerate(self.edges)]
        self.assertFailsWith(self.run_with(rows, ["Target", "Regulator"]),
                             "shares no target IDs with the target expression file")

    def test_a_single_column_file_is_rejected(self):
        rows = [(gene,) for gene, _ in self.edges]
        self.assertFailsWith(self.run_with(rows, ["Target"]), "has only 1 column")

    def test_a_four_column_file_is_rejected(self):
        """Truncating silently could hide a malformed upload."""
        rows = [(g, r, "PROMOTER", "extra") for g, r in self.edges]
        self.assertFailsWith(
            self.run_with(rows, ["Target", "Regulator", "Area", "Extra"]),
            "has 4 columns")


@unittest.skipUnless(HAS_MORE, "Rscript with MORE and optparse is not available")
class OrientationTest(AssociationCaseMixin, unittest.TestCase):
    """Column-order detection, including the three-column form. These do run
    the model, on 8 targets."""

    def test_target_first_is_left_alone(self):
        proc = self.run_with([(g, r) for g, r in self.edges],
                             ["Target", "Regulator"])
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:] + proc.stderr[-800:])
        self.assertNotIn("Detected Regulator in Column 1", proc.stdout)

    def test_regulator_first_is_swapped(self):
        proc = self.run_with([(r, g) for g, r in self.edges],
                             ["Regulator", "Target"])
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:] + proc.stderr[-800:])
        self.assertIn("Detected Regulator in Column 1", proc.stdout)

    def test_a_three_column_file_keeps_its_area_column(self):
        proc = self.run_with([(g, r, "PROMOTER") for g, r in self.edges],
                             ["Target", "Regulator", "Area"])
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:] + proc.stderr[-800:])
        self.assertIn("Detected optional interaction-type column", proc.stdout)

    def test_a_swapped_three_column_file_keeps_area_in_place(self):
        """The swap reorders columns 1 and 2 only -- an area column dragged
        into the regulator slot would corrupt every association."""
        proc = self.run_with([(r, g, "PROMOTER") for g, r in self.edges],
                             ["Regulator", "Target", "Area"])
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:] + proc.stderr[-800:])
        self.assertIn("Detected Regulator in Column 1", proc.stdout)
        self.assertIn("Detected optional interaction-type column", proc.stdout)
        # If area had been swapped into the regulator column, no regulator
        # would resolve and the run would have died on the overlap check.
        self.assertNotIn("shares no regulator IDs", proc.stdout + proc.stderr)

    def test_partial_regulator_overlap_still_runs(self):
        """Association files routinely list regulators absent from the
        measured matrix; only a total miss is an error."""
        rows = [(g, r) for g, r in self.edges] + [("G1", "TF_NOT_MEASURED")]
        proc = self.run_with(rows, ["Target", "Regulator"])
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:] + proc.stderr[-800:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
