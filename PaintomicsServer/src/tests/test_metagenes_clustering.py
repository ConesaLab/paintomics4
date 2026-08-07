#!/usr/bin/env python3
"""Regression cover for metagene generation and clustering.

Two independent defects made the Step 3 cluster panel useless, and this file
pins both.

1. The relevance flag was read as an extra condition
---------------------------------------------------
``Job.py`` writes one row per mapped feature into ``<omic>_matched.txt``::

    inputName | featureName | featureID | matchingDB | v1..vn | relevanceFlag

The trailing flag is a 0/1 significance indicator. Commit 6c7a7934 ("Add
multi-condition support for PaintOmics4") appended it; ``generateMetaGenes.R``
still sliced ``5:ncol(input_data)`` and so consumed it as one more condition.

A binary column next to log-ratios of order 1e-2 dominates the per-pathway PCA
outright. PC1 stopped describing the temporal response and became "what
fraction of this pathway's genes are significant", every metagene came out as a
flat line with a spike at the last point, and the cluster thumbnails then
differed only in the height of that spike -- the user-visible symptom was six
requested clusters rendering as six near-identical pictures.

The R script recovers the condition count as ``ncol - 5``, which is right only
while exactly one flag column is written. ``test_matched_file_contract`` pins
that: ``isRelevant()`` is called with no ``conditionIndex``, and in that mode it
collapses a per-condition list to a single boolean. If anyone makes it return
the list, this test fails and names generateMetaGenes.R as the thing to update.

2. kmeans() was handed a `dist` object
--------------------------------------
The script computed ``dist.res <- Dist(dataScaled, method = "pearson")`` and
then called ``stats::kmeans(dist.res, centers = k)``. ``kmeans`` opens with
``as.matrix(x)``, and ``as.matrix.dist`` expands a dist into the full n x n
distance matrix -- so it clustered the *rows of the distance matrix*, n points
in n dimensions, under Euclidean distance. The pearson metric was never
applied.

Besides being O(n^2), it produced badly unbalanced partitions: on the example
dataset k = 6 gave sizes 1, 5, 11, 36, 140, 166. Clusters that small usually
have no pathway left after Step 3's p-value filter, and PA_Step3Views.js only
renders clusters that still own a visible node -- which is the second half of
"I asked for 6 and got 4".

The fix centres each metagene and rescales it to unit length before clustering.
For centred unit-norm vectors ||x-y||^2 == 2*(1-pearson), so ordinary k-means on
that matrix minimises exactly the intended dissimilarity, i.e. it clusters on
the shape of the response and ignores amplitude. ``test_recovers_planted_shapes``
locks that in with three orthogonal planted profiles at deliberately different
amplitudes: an amplitude-sensitive clustering splits them the wrong way.

Running
-------
    PYTHONPATH=PaintomicsServer python3 PaintomicsServer/src/tests/test_metagenes_clustering.py

The R-backed tests skip themselves when Rscript or the CRAN packages the script
loads (cluster, amap, mclust, factoextra) are unavailable.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(TESTS_DIR)
BIOSCRIPTS_DIR = os.path.join(SRC_DIR, "common", "bioscripts")
R_SCRIPT = os.path.join(BIOSCRIPTS_DIR, "generateMetaGenes.R")

N_CONDITIONS = 6

# Three profiles over six conditions, chosen to be mutually uncorrelated:
# RISING vs FALLING is r = -1, and V_SHAPE is exactly orthogonal to both
# (their dot products are 0). Correlation-based clustering must separate all
# three no matter what amplitude each pathway is scaled to.
SHAPES = {
    "rising":  [-3.0, -2.0, -1.0,  1.0,  2.0,  3.0],
    "falling": [3.0,  2.0,  1.0, -1.0, -2.0, -3.0],
    "vshape":  [2.0, -1.0, -3.0, -3.0, -1.0,  2.0],
}
PATHWAYS_PER_SHAPE = 12
GENES_PER_PATHWAY = 8
# Amplitudes deliberately span more than an order of magnitude within each
# shape group, so a clustering that keys on magnitude rather than shape cannot
# reproduce the planted grouping.
AMPLITUDES = [0.05, 0.5, 4.0]


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
                              timeout=180).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


R_AVAILABLE = _r_available()


def _build_fixture(root, write_relevance_flag=True):
    """Write a synthetic KEGG tree + matched file with known cluster structure.

    Returns (kegg_dir, data_dir, expected_shape_of_pathway).

    Pathway IDs must not contain '_': generateMetaGenes.R turns the '_' that
    separates pathway from metagene index into a tab when it writes the .tab,
    so an underscore inside the ID would silently add a column.
    """
    kegg_dir = os.path.join(root, "kegg")
    species_dir = os.path.join(kegg_dir, "current", "mmu")
    data_dir = os.path.join(root, "data")
    os.makedirs(species_dir)
    os.makedirs(data_dir)

    annotation = []
    matched_rows = []
    expected = {}

    gene_counter = 0
    pathway_counter = 0
    for shape_name, profile in SHAPES.items():
        for p in range(PATHWAYS_PER_SHAPE):
            pathway_counter += 1
            pathway_id = "synth%03d" % pathway_counter
            expected[pathway_id] = shape_name
            amplitude = AMPLITUDES[p % len(AMPLITUDES)]

            for g in range(GENES_PER_PATHWAY):
                gene_counter += 1
                gene_id = "g%05d" % gene_counter
                annotation.append("mmu:%s\tpath:%s" % (gene_id, pathway_id))

                # Deterministic jitter -- no RNG, so the fixture is identical on
                # every run and the assertions below cannot flake.
                values = []
                for c in range(N_CONDITIONS):
                    jitter = 0.01 * (((gene_counter * 7 + c * 13) % 11) - 5)
                    values.append(amplitude * profile[c] + jitter)

                # The flag deliberately correlates with the planted group. If it
                # is ever read back as a condition it injects a large, group
                # specific offset, which is exactly the failure being guarded.
                flag = "1" if shape_name in ("rising", "falling") else "0"
                row = [gene_id, gene_id, gene_id, "KEGG"] + ["%.10f" % v for v in values]
                if write_relevance_flag:
                    row.append(flag)
                matched_rows.append("\t".join(row))

    with open(os.path.join(species_dir, "gene2pathway.list"), "w") as fh:
        fh.write("\n".join(annotation) + "\n")
    with open(os.path.join(data_dir, "Synth_matched.txt"), "w") as fh:
        fh.write("\n".join(matched_rows) + "\n")

    return kegg_dir, data_dir, expected


def _run_r(kegg_dir, data_dir, kclusters):
    cmd = ["Rscript", R_SCRIPT,
           "--specie=mmu",
           "--input_file=" + os.path.join(data_dir, "Synth_matched.txt"),
           "--output_prefix=Synth",
           "--data_dir=" + data_dir + os.sep,
           "--kegg_dir=" + kegg_dir + os.sep,
           "--sources_dir=" + BIOSCRIPTS_DIR + os.sep,
           "--kclusters=" + str(kclusters)]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=900, universal_newlines=True)


def _read_tab(data_dir):
    """-> {pathwayID: (clusterIndex, [values])} from Synth_metagenes.tab.

    Layout is rowname, cluster, values..., and the rowname itself carries a tab
    because '<pathway>_<metageneIndex>' has its underscore substituted, so the
    fields are: pathway | metageneIndex | cluster | v1..vn
    """
    out = {}
    path = os.path.join(data_dir, "Synth_metagenes.tab")
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            fields = line.split("\t")
            out[fields[0]] = (int(fields[2]), [float(v) for v in fields[3:]])
    return out


@unittest.skipUnless(R_AVAILABLE, "Rscript or required CRAN packages unavailable")
class MetagenesClusteringTest(unittest.TestCase):
    """End-to-end runs of generateMetaGenes.R over a planted fixture."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="pa4_metagenes_")
        cls.kegg_dir, cls.data_dir, cls.expected = _build_fixture(cls.root)
        cls.result = _run_r(cls.kegg_dir, cls.data_dir, kclusters=3)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        if self.result.returncode != 0:
            self.fail("generateMetaGenes.R exited %d:\n%s"
                      % (self.result.returncode, self.result.stdout))

    def test_relevance_flag_is_not_read_as_a_condition(self):
        """The .tab carries N_CONDITIONS values, not N_CONDITIONS + 1.

        This is the direct assertion for defect 1. Before the fix each metagene
        had a seventh value -- the flag-driven spike that made every cluster
        thumbnail look the same.
        """
        table = _read_tab(self.data_dir)
        self.assertTrue(table, "no metagenes were written")
        for pathway, (_cluster, values) in table.items():
            self.assertEqual(
                len(values), N_CONDITIONS,
                "%s has %d values; the trailing relevance flag is being read as "
                "a condition again (generateMetaGenes.R input slicing)"
                % (pathway, len(values)))

    def test_requested_cluster_count_is_honoured(self):
        """k clusters are assigned and k thumbnails written, none empty."""
        table = _read_tab(self.data_dir)
        assigned = sorted({cluster for cluster, _values in table.values()})
        self.assertEqual(assigned, [1, 2, 3],
                         "expected exactly 3 non-empty clusters, got %s" % assigned)

        for i in (1, 2, 3):
            png = os.path.join(self.data_dir, "Synth_cluster_%d.png" % i)
            self.assertTrue(os.path.exists(png), "missing thumbnail %s" % png)
            self.assertGreater(os.path.getsize(png), 0, "%s is empty" % png)

    def test_recovers_planted_shapes(self):
        """Each planted profile lands in its own cluster, across amplitudes.

        Guards defect 2. Clustering the rows of the distance matrix, or
        clustering on raw amplitude, both fail here: the three groups span the
        same amplitude range and differ only in shape.
        """
        table = _read_tab(self.data_dir)
        shape_to_clusters = {}
        for pathway, (cluster, _values) in table.items():
            shape = self.expected[pathway]
            shape_to_clusters.setdefault(shape, set()).add(cluster)

        self.assertEqual(set(shape_to_clusters), set(SHAPES),
                         "not every planted shape survived to the output")
        for shape, clusters in shape_to_clusters.items():
            self.assertEqual(
                len(clusters), 1,
                "shape '%s' was split across clusters %s; clustering is not "
                "keying on profile shape" % (shape, sorted(clusters)))

        merged = [c for clusters in shape_to_clusters.values() for c in clusters]
        self.assertEqual(len(set(merged)), len(SHAPES),
                         "two planted shapes were merged into one cluster")


@unittest.skipUnless(R_AVAILABLE, "Rscript or required CRAN packages unavailable")
class ClusterCountClampTest(unittest.TestCase):
    """k larger than the number of metagenes must not kill the run.

    kmeans() raises "more cluster centers than distinct data points" and the
    whole omic-and-database pair dies with it -- reachable from the Step 3
    slider whenever a secondary database matches only a handful of pathways.
    """

    def test_more_clusters_than_metagenes_is_clamped(self):
        root = tempfile.mkdtemp(prefix="pa4_metagenes_clamp_")
        try:
            kegg_dir, data_dir, _expected = _build_fixture(root)
            # 36 pathways in the fixture; ask for far more.
            result = _run_r(kegg_dir, data_dir, kclusters=500)
            self.assertEqual(result.returncode, 0,
                             "script died instead of clamping k:\n%s" % result.stdout)
            table = _read_tab(data_dir)
            assigned = {cluster for cluster, _values in table.values()}
            self.assertLessEqual(max(assigned), len(table))
            self.assertGreaterEqual(len(assigned), 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class MatchedFileContractTest(unittest.TestCase):
    """Pins the file contract generateMetaGenes.R's `ncol - 5` depends on.

    No R needed -- this is the Python half of the same invariant.
    """

    def test_is_relevant_collapses_to_a_single_flag(self):
        """isRelevant() with no conditionIndex never returns a list.

        Job.py writes `relStr` from exactly this call, so one flag column is
        appended regardless of how many conditions the omic has. If this
        changes, generateMetaGenes.R must stop deriving the condition count as
        `ncol - 5`.
        """
        from src.classes.Feature import OmicValue

        value = OmicValue("feature1")
        value.setRelevant([True, False, True])
        self.assertNotIsInstance(
            value.isRelevant(), list,
            "isRelevant() now returns a per-condition list, so Job.py writes "
            "more than one relevance column; generateMetaGenes.R still assumes "
            "exactly one (see its input-slicing comment)")

        value.setRelevant(False)
        self.assertNotIsInstance(value.isRelevant(), list)

    def test_matched_row_has_one_flag_column(self):
        """Reproduces Job.py's row construction and counts the columns."""
        from src.classes.Feature import OmicValue

        value = OmicValue("feature1")
        value.setValues([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        value.setRelevant([True, False, True, False, False, False])

        relevant = value.isRelevant()
        if not isinstance(relevant, list):
            relevant = [relevant]
        row = ["inputName", "featureName", "featureID", "KEGG"]
        row += [str(v) for v in value.getValues()]
        row += ["1" if r else "0" for r in relevant]

        self.assertEqual(len(row), 4 + N_CONDITIONS + 1)
        # This is the arithmetic generateMetaGenes.R performs.
        self.assertEqual(len(row) - 5, N_CONDITIONS)


if __name__ == "__main__":
    sys.path.insert(0, SRC_DIR)
    sys.path.insert(0, os.path.dirname(SRC_DIR))
    unittest.main(verbosity=2)
