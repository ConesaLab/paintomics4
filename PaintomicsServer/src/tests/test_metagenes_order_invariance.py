#!/usr/bin/env python3
"""generateMetaGenes.R must not depend on the row order of its input file.

The defect
----------
``<omic>_matched.txt`` is written by ``Job.py`` in an order that is not stable
between runs of the same job on the same input: the md5 of the file changes run
to run while the md5 of its *sorted* lines does not -- same content, different
order. ``generateMetaGenes.R`` used to inherit that order all the way into the
clustering, so a user who re-ran an unchanged job got a different Step-4
picture, and two runs of the same data disagreed about which pathways group
together.

Measured on a real bundled mmu input (11 358 rows, single condition), before
the fix: 12 permutations of the *same* file produced 12 distinct metagene
tables, with cluster sizes ranging over 8 different signatures --
(176,174,14), (178,172,14), (179,171,14), (180,170,14), (185,165,14),
(186,164,14), (189,162,13), (190,160,14). On a 6-condition input, 8
permutations produced 8 distinct tables and even a different *number* of
metagenes each time (290 to 296).

Two independent mechanisms, both fixed inside R so the script is correct for
any writer:

1. Deduplication kept whichever copy of a repeated feature ID came first.
   Repeated IDs are common and they do not agree about the value -- in that
   real input, 193 IDs appear more than once and all 193 of them carry
   differing values. So "first in the file" silently rewrote 193 gene values on
   every run, which moved the pathway medians, which moved the clusters. This
   is the dominant term, and it is what this file's fixtures reproduce:
   ``_build_fixture`` plants duplicate IDs with conflicting values on purpose.
   Without them the script would look order-invariant here while still being
   broken in production.

2. Row order reached the numerics. The per-pathway submatrix handed to PCA
   followed the order of the input rows, and ``eigen()`` of a permuted
   covariance matrix agrees only to the last bits. PCA2GO.2's "single%"
   criterion *counts* components clearing a threshold, so those last bits
   decide how many metagenes a pathway contributes at all -- which is why the
   metagene count itself wandered on the multi-condition path.

Measured for the record while fixing this: the 1-D ``Mclust`` step is *not*
order-sensitive on real data -- permuting the rows of a fixed 364-metagene
matrix 12 times gave one identical partition every time. Term (1) accounted for
all of the observed single-condition instability. The canonical sort of the
metagene rows is kept anyway because ``kmeans`` samples rows for its starting
centres and because it decouples the answer from the order pathways happen to
appear in ``gene2pathway.list``, but do not expect removing it alone to make
this test fail.

What this file pins
-------------------
``test_single_condition_*`` and ``test_multi_condition_*`` are the real
assertions: permute the data rows, run the script, demand the resulting
``metagenes.tab`` be byte-identical. That covers both estimators
(CENTROID2GO + 1-D Mclust, and PC1 + kmeans) and both clusterers.

``test_duplicate_survivor_is_order_independent`` isolates mechanism (1) so a
failure says which of the two regressed, and ``test_row_identity_survives_sort``
guards the thing the sort could plausibly break: sorting must move whole rows,
never separate a pathway or a gene from its own values.
"""

import hashlib
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(TESTS_DIR)
BIOSCRIPTS_DIR = os.path.join(SRC_DIR, "common", "bioscripts")
R_SCRIPT = os.path.join(BIOSCRIPTS_DIR, "generateMetaGenes.R")

SPECIE = "mmu"
N_PATHWAYS = 24
GENES_PER_PATHWAY = 6
# Feature IDs that appear twice with *different* values. This is the defect
# trigger, not decoration -- see the module docstring.
N_DUPLICATED = 30
# Enough permutations that an order-dependent script is caught with near
# certainty (before the fix, 12 permutations of a real file gave 12 distinct
# answers), few enough that the whole file stays under a minute.
N_PERMUTATIONS = 12

# Three mutually uncorrelated profiles, so the multi-condition case has real
# cluster structure for PC1 + kmeans to find rather than noise.
SHAPES = [
    [-3.0, -2.0, -1.0, 1.0, 2.0, 3.0],
    [3.0, 2.0, 1.0, -1.0, -2.0, -3.0],
    [2.0, -1.0, -3.0, -3.0, -1.0, 2.0],
]


def _r_available():
    """Rscript plus every package generateMetaGenes.R loads at top level."""
    if shutil.which("Rscript") is None:
        return False
    probe = ('q(status = if (all(sapply(c("cluster","amap","mclust","factoextra"), '
             'requireNamespace, quietly = TRUE))) 0 else 1)')
    try:
        return subprocess.run(["Rscript", "-e", probe],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              timeout=300).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


R_AVAILABLE = _r_available()


def _build_fixture(root, n_conditions):
    """Write a synthetic KEGG tree and return (kegg_root, annotation, rows).

    ``rows`` are the data lines of a matched.txt in an arbitrary order; the
    tests permute them. Pathway IDs must not contain '_': the script turns the
    '_' separating pathway from metagene index into a tab when it writes the
    .tab file, so an underscore inside an ID would add a phantom column.
    """
    kegg_root = os.path.join(root, "kegg")
    species_dir = os.path.join(kegg_root, "current", SPECIE)
    os.makedirs(species_dir)

    rng = random.Random(4242)
    annotation = []
    rows = []
    gene_counter = 0

    for p in range(N_PATHWAYS):
        pathway_id = "synth%03d" % p
        shape = SHAPES[p % len(SHAPES)]
        amplitude = [0.05, 0.5, 4.0][p % 3]
        for _ in range(GENES_PER_PATHWAY):
            gene_counter += 1
            feature_id = "%d" % (100000 + gene_counter)
            annotation.append("%s:%s\tpath:%s" % (SPECIE, feature_id, pathway_id))
            if n_conditions == 1:
                values = [amplitude * shape[0] + rng.gauss(0, 0.01)]
            else:
                values = [amplitude * shape[c % len(shape)] + rng.gauss(0, 0.01)
                          for c in range(n_conditions)]
            rows.append(["INPUT%05d" % gene_counter, "Gene%05d" % gene_counter,
                         feature_id, "KEGG"]
                        + ["%.6f" % v for v in values]
                        + ["1" if rng.random() < 0.3 else "0"])

    # Duplicate feature IDs carrying *conflicting* values, under a different
    # input name -- exactly the shape Job.py emits when several probes or
    # transcripts map to one gene.
    for i in range(N_DUPLICATED):
        original = rows[i * (len(rows) // N_DUPLICATED)]
        clash = list(original)
        clash[0] = "ALTINPUT%05d" % i
        clash[1] = "Alt%05d" % i
        # A large, clearly different value: if the wrong copy survives, the
        # pathway median moves far enough to change the clustering.
        clash[4:4 + n_conditions] = ["%.6f" % (-7.0 - i)] * n_conditions
        rows.append(clash)

    with open(os.path.join(species_dir, "gene2pathway.list"), "w") as fh:
        fh.write("\n".join(annotation) + "\n")

    return kegg_root, rows


def _run_script(work_dir, kegg_root, rows, prefix="Synth"):
    """Write matched.txt in the given row order, run the script, return the tab."""
    data_dir = os.path.join(work_dir, "data")
    os.makedirs(data_dir)
    matched = "%s_matched.txt" % prefix
    with open(os.path.join(data_dir, matched), "w") as fh:
        for row in rows:
            fh.write("\t".join(row) + "\n")

    completed = subprocess.run(
        ["Rscript", R_SCRIPT,
         "--specie=%s" % SPECIE,
         "--input_file=%s" % matched,
         "--output_prefix=%s" % prefix,
         "--data_dir=%s%s" % (data_dir, os.sep),
         "--kegg_dir=%s%s" % (kegg_root, os.sep),
         "--sources_dir=%s" % BIOSCRIPTS_DIR],
        capture_output=True, text=True, timeout=900)

    tab = os.path.join(data_dir, "%s_metagenes.tab" % prefix)
    if not os.path.exists(tab):
        raise AssertionError(
            "generateMetaGenes.R produced no metagenes.tab (rc=%s)\n"
            "STDOUT:\n%s\nSTDERR:\n%s"
            % (completed.returncode, completed.stdout[-4000:],
               completed.stderr[-4000:]))
    with open(tab, "rb") as fh:
        return fh.read()


def _describe(tab_bytes):
    """Cluster-size signature, for a failure message that says what moved."""
    counts = {}
    n = 0
    for line in tab_bytes.decode().splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        counts[parts[2]] = counts.get(parts[2], 0) + 1
        n += 1
    return "%d metagenes, %d clusters, sizes %s" % (
        n, len(counts), sorted(counts.values(), reverse=True))


@unittest.skipUnless(R_AVAILABLE, "Rscript or an R dependency is unavailable")
class MetagenesOrderInvarianceTest(unittest.TestCase):
    """Permute the input rows; the metagene table must not move."""

    def _assert_invariant(self, n_conditions):
        root = tempfile.mkdtemp(prefix="mg_order_")
        try:
            kegg_root, rows = _build_fixture(root, n_conditions)
            rng = random.Random(20260809)
            reference = None
            for i in range(N_PERMUTATIONS):
                permuted = list(rows)
                if i > 0:            # run 0 is the unshuffled control
                    rng.shuffle(permuted)
                work = os.path.join(root, "run%02d" % i)
                os.makedirs(work)
                tab = _run_script(work, kegg_root, permuted)
                if reference is None:
                    reference = tab
                    continue
                self.assertEqual(
                    hashlib.md5(reference).hexdigest(),
                    hashlib.md5(tab).hexdigest(),
                    "permutation %d of the SAME input produced a different "
                    "metagene table.\n  run 0: %s\n  run %d: %s\n"
                    "generateMetaGenes.R must sort its input into a canonical "
                    "order before deduplicating and before clustering."
                    % (i, _describe(reference), i, _describe(tab)))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_single_condition_is_order_invariant(self):
        """CENTROID2GO + 1-D Mclust."""
        self._assert_invariant(n_conditions=1)

    def test_multi_condition_is_order_invariant(self):
        """PCA2GO.2 (PC1) + kmeans, including the metagene *count*."""
        self._assert_invariant(n_conditions=6)


def _build_identity_fixture(root):
    """A fixture whose right answer is known in closed form.

    Every gene of pathway ``p`` carries the value ``p + 1``, so the metagene
    CENTROID2GO computes -- the per-condition median of the member genes -- must
    come out as exactly ``p + 1``. Any value that is not its pathway's number
    means a row lost track of its own data.

    One gene per pathway is duplicated with a wildly different value under an
    alphabetically *earlier* input name, so the canonical sort really does swap
    which row survives rather than leaving the file as written. The median of
    five copies of ``p + 1`` and one outlier is still ``p + 1``, so the expected
    answer is unchanged -- which is the point: the test can tell "the sort moved
    rows around" apart from "the sort corrupted them".
    """
    kegg_root = os.path.join(root, "kegg")
    species_dir = os.path.join(kegg_root, "current", SPECIE)
    os.makedirs(species_dir)

    annotation = []
    rows = []
    expected = {}
    gene_counter = 0
    for p in range(N_PATHWAYS):
        pathway_id = "ident%03d" % p
        expected[pathway_id] = float(p + 1)
        first_id = None
        for _ in range(GENES_PER_PATHWAY):
            gene_counter += 1
            feature_id = "%d" % (500000 + gene_counter)
            first_id = first_id or feature_id
            annotation.append("%s:%s\tpath:%s" % (SPECIE, feature_id, pathway_id))
            rows.append(["INPUT%05d" % gene_counter, "Gene%05d" % gene_counter,
                         feature_id, "KEGG", "%.6f" % (p + 1), "0"])
        rows.append(["AAALT%05d" % p, "Alt%05d" % p, first_id, "KEGG",
                     "-999.000000", "0"])

    with open(os.path.join(species_dir, "gene2pathway.list"), "w") as fh:
        fh.write("\n".join(annotation) + "\n")
    return kegg_root, rows, expected


@unittest.skipUnless(R_AVAILABLE, "Rscript or an R dependency is unavailable")
class MetageneValueIdentityTest(unittest.TestCase):
    """Separate 'the numbers moved' from 'the clusterer moved'."""

    def test_metagene_values_are_order_invariant(self):
        """Mechanism (1) on its own: ignore the cluster column entirely.

        If this fails alongside the whole-file tests, the input data reaching
        the clustering changed -- deduplication or the estimator is picking up
        row order. If this passes and the whole-file tests fail, the data is
        stable and the clusterer is the order-sensitive part. The two failure
        modes want different fixes, so they are asserted separately.
        """
        root = tempfile.mkdtemp(prefix="mg_values_")
        try:
            kegg_root, rows = _build_fixture(root, n_conditions=1)
            self.assertLess(len({r[2] for r in rows}), len(rows),
                            "fixture must contain duplicate feature IDs or it "
                            "cannot exercise the defect")
            rng = random.Random(7)
            reference = None
            for i in range(4):
                permuted = list(rows)
                if i > 0:
                    rng.shuffle(permuted)
                work = os.path.join(root, "run%02d" % i)
                os.makedirs(work)
                tab = _run_script(work, kegg_root, permuted)
                # pathway, metagene index, then the values -- column 2 (the
                # cluster label) is dropped.
                values = sorted(
                    "\t".join(ln.split("\t")[:2] + ln.split("\t")[3:])
                    for ln in tab.decode().splitlines() if ln.strip())
                if reference is None:
                    reference = values
                else:
                    diff = [a for a, b in zip(reference, values) if a != b]
                    self.assertEqual(
                        reference, values,
                        "the metagene VALUES changed when the input rows were "
                        "permuted (%d of %d rows differ, e.g. %r). The data fed "
                        "to the clustering is order-dependent -- look at the "
                        "deduplication and the per-pathway submatrix order, "
                        "not at Mclust/kmeans."
                        % (len(diff), len(reference), diff[:3]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_pathway_keeps_its_own_values(self):
        """The sort must move whole rows, never re-pair a value with a gene.

        This is how the fix could be actively wrong rather than merely absent:
        ordering a column instead of the frame would give a perfectly
        deterministic table of thoroughly wrong numbers, and every other
        assertion in this file would still pass.
        """
        root = tempfile.mkdtemp(prefix="mg_ident_")
        try:
            kegg_root, rows, expected = _build_identity_fixture(root)
            rng = random.Random(11)
            for i in range(3):
                permuted = list(rows)
                if i > 0:
                    rng.shuffle(permuted)
                work = os.path.join(root, "run%02d" % i)
                os.makedirs(work)
                tab = _run_script(work, kegg_root, permuted)

                seen = {}
                for line in tab.decode().splitlines():
                    parts = line.split("\t")
                    if len(parts) < 4:
                        continue
                    seen[parts[0]] = float(parts[3])

                self.assertEqual(
                    set(seen), set(expected),
                    "permutation %d produced a different set of pathways" % i)
                for pathway, want in expected.items():
                    self.assertAlmostEqual(
                        seen[pathway], want, places=6,
                        msg="pathway %s should summarise to %.1f (every one of "
                            "its genes carries that value) but came out as %r "
                            "-- the sort separated rows from their data"
                            % (pathway, want, seen[pathway]))
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.path.insert(0, SRC_DIR)
    sys.path.insert(0, os.path.dirname(SRC_DIR))
    unittest.main(verbosity=2)
