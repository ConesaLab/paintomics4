#!/usr/bin/env python3
"""Regulator IDs must survive MORE's prefix removal intact.

MORE 1.0.1's RegulationPerCondition finishes with

    prefix = paste0(names(output$arguments$omicType), "-", collapse = "|")
    myresults$regulator = gsub(prefix, "", myresults$regulator)

to drop the "<omic>-" prefix it uses internally. The gsub is unanchored and
global, so it deletes the omic name plus a hyphen anywhere in the ID. For an
omic named "TF", a regulator genuinely called "TF-1" comes back as "1"; for an
omic named "miRNA", "miRNA-21" becomes "21". runMORE.R then applied its own
unconditional strip on top.

Observed before the fix, from one run over regulators named TF-1..TF-4:

    MORE_output_TF_*.tab          G1:::TF-1     (from input data -- correct)
    MORE_relevant_assoc_TF_*.tab  G1  TF-1      (from input data -- correct)
    MORE_relevant_pairs_TF_*.tab  G1:::1        (from MORE     -- truncated)
    MORE_rpc_*.tab                regulator 1   (from MORE     -- truncated)

The two halves disagreeing is what makes it damaging rather than cosmetic.
Job.parseGeneBasedFiles looks a values row up in the pairs file by
GENE:::REGULATOR, so "g1:::tf-1" is searched for in a file containing
"g1:::1", every lookup misses, every star for that omic disappears, and
pathway enrichment shifts with it because enrichment counts significance.

runMORE.R now inverts the mangling against the regulator IDs it loaded, and
its own strip skips any value that is already a real regulator ID.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_runmore_regulator_ids
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
SAMPLES = ["C1", "C2", "C3", "C4", "T1", "T2", "T3", "T4"]
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


class RunFixture(unittest.TestCase):
    """One MORE run per subclass, parameterised by the regulator ID style."""

    omicName = "TF"
    regulators = []

    @classmethod
    def setUpClass(cls):
        if not HAS_MORE:
            raise unittest.SkipTest("Rscript with MORE and optparse is not available")
        cls.tmp = tempfile.mkdtemp(prefix="runmore_ids_")
        data = os.path.join(cls.tmp, "in")
        cls.out = os.path.join(cls.tmp, "out")
        os.makedirs(data)
        os.makedirs(cls.out)

        base = [1.0, 1.2, 0.9, 1.1, 4.0, 4.3, 3.8, 4.1]
        reg = {n: [v + i * 0.35 for v in base] for i, n in enumerate(cls.regulators)}

        with open(os.path.join(data, "regulators.tab"), "w") as fh:
            fh.write("RegulatorID\t" + "\t".join(SAMPLES) + "\n")
            for n in cls.regulators:
                fh.write(n + "\t" + "\t".join("%.4f" % v for v in reg[n]) + "\n")

        cls.edges = []
        with open(os.path.join(data, "targets.tab"), "w") as fh:
            fh.write("GeneID\t" + "\t".join(SAMPLES) + "\n")
            for i, g in enumerate(TARGETS):
                driver = cls.regulators[i % len(cls.regulators)]
                cls.edges.append((g, driver))
                fh.write(g + "\t" + "\t".join(
                    "%.4f" % (2.0 + 1.5 * v + 0.01 * i) for v in reg[driver]) + "\n")

        with open(os.path.join(data, "conditions.tab"), "w") as fh:
            fh.write("Sample\tCtrl\tTreat\n")
            for s in SAMPLES:
                t = int(s.startswith("T"))
                fh.write("%s\t%d\t%d\n" % (s, 1 - t, t))

        with open(os.path.join(data, "assoc.tab"), "w") as fh:
            fh.write("Target\tRegulator\n")
            for g, d in cls.edges:
                fh.write("%s\t%s\n" % (g, d))

        cls.proc = subprocess.run([
            "Rscript", R_SCRIPT,
            "--target_file", os.path.join(data, "targets.tab"),
            "--condition_file", os.path.join(data, "conditions.tab"),
            "--omic_names", cls.omicName,
            "--data_files", os.path.join(data, "regulators.tab"),
            "--assoc_files", os.path.join(data, "assoc.tab"),
            "--min_variation", "NA", "--method", "PLS1", "--alpha", "0.05",
            "--vip", "0.8", "--filter_r2", "0.0",
            "--output_dir", cls.out, "--date_seed", DATE,
        ], capture_output=True, text=True, timeout=900)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def read(self, name):
        path = os.path.join(self.out, "%s_%s.tab" % (name, DATE))
        self.assertTrue(os.path.exists(path), "%s was not written" % path)
        with open(path) as fh:
            return fh.read()

    def regulatorsInPairs(self):
        return {line.split(":::")[1]
                for line in self.read("MORE_relevant_pairs_%s" % self.omicName).splitlines()
                if ":::" in line}

    def regulatorsInRpc(self):
        rows = self.read("MORE_rpc").splitlines()
        return {r.split("\t")[1] for r in rows[1:] if "\t" in r}


class CollidingRegulatorIdsTest(RunFixture):
    """Regulator IDs that begin with the omic name and a hyphen -- the shape
    MORE's gsub destroys. "miRNA" as an omic name with miRNA-* regulators is
    the realistic instance of this."""

    omicName = "TF"
    regulators = ["TF-1", "TF-2", "TF-3", "TF-4"]

    def test_the_run_succeeds(self):
        self.assertEqual(self.proc.returncode, 0,
                         self.proc.stdout[-800:] + self.proc.stderr[-800:])

    def test_the_values_file_keeps_the_full_id(self):
        """Written from the input data, so it was always right -- it is the
        reference the other files have to match."""
        self.assertIn("G1:::TF-1", self.read("MORE_output_%s" % self.omicName))

    def test_the_pairs_file_keeps_the_full_id(self):
        """The regression: this file used to say G1:::1."""
        self.assertTrue(self.regulatorsInPairs(),
                        "no significant pairs were produced, so nothing was tested")
        for reg in self.regulatorsInPairs():
            self.assertIn(reg, self.regulators,
                          "pairs file has a truncated regulator ID: %r" % reg)

    def test_the_rpc_table_keeps_the_full_id(self):
        for reg in self.regulatorsInRpc():
            self.assertIn(reg, self.regulators,
                          "rpc table has a truncated regulator ID: %r" % reg)

    def test_pairs_and_values_agree(self):
        """The contract relevance lookup depends on: parseGeneBasedFiles takes
        the values file's GENE:::REGULATOR key and looks it up in the pairs
        file. A mismatch silently removes every star for the omic."""
        values = {line.split("\t")[0]
                  for line in self.read("MORE_output_%s" % self.omicName).splitlines()
                  if ":::" in line}
        pairs = {line.strip()
                 for line in self.read("MORE_relevant_pairs_%s" % self.omicName).splitlines()
                 if ":::" in line}
        self.assertTrue(pairs)
        self.assertTrue(pairs <= values,
                        "pairs not present in the values file: %s" % sorted(pairs - values))

    def test_the_associations_file_keeps_the_full_id(self):
        self.assertIn("TF-1", self.read("MORE_relevant_assoc_%s" % self.omicName))

    def test_the_restoration_is_reported(self):
        """Silent repair of user IDs would be its own problem; the log has to
        say what was changed."""
        self.assertIn("restored", self.proc.stdout)


class OrdinaryRegulatorIdsTest(RunFixture):
    """Control: IDs that do not collide with the prefix must pass through
    untouched. A repair that fires here would be a new corruption."""

    omicName = "TF"
    regulators = ["TFA", "TFB", "TFC", "TFD"]

    def test_the_run_succeeds(self):
        self.assertEqual(self.proc.returncode, 0,
                         self.proc.stdout[-800:] + self.proc.stderr[-800:])

    def test_ids_are_unchanged_in_the_pairs_file(self):
        for reg in self.regulatorsInPairs():
            self.assertIn(reg, self.regulators)

    def test_ids_are_unchanged_in_the_rpc_table(self):
        for reg in self.regulatorsInRpc():
            self.assertIn(reg, self.regulators)

    def test_nothing_was_restored(self):
        self.assertNotIn("restored", self.proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
