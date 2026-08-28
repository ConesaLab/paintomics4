#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build ``12-stategra-metabolomics-replicates``: the STATegra metabolomics
time course at SAMPLE level, with its experimental design.

Why a second STATegra metabolomics example
------------------------------------------
``08-stategra-multiomics`` ships metabolomics as six Ikaros/Control ratios,
one per time point -- the replicates averaged away. That is enough to paint
pathways, and not enough to test a metabolite class: a class of four
metabolites described by 4 x 6 ratios has no noise estimate, so no test can
tell a real shift from a noisy one. This dataset keeps the 36 samples
(2 arms x 6 time points x 3 biological replicates) and adds the design that
maps each column to its condition, which is what lets PaintOmics run the
permutation-based class activity test (``src/common/ClassActivity.py``).

Source
------
MetaboLights MTBLS283, processed exactly as in the authors' script
(``Script_STATegra_Metabolomics``): targeted GC-MS + LC-MS, 13C internal
standard normalisation, batch 12 removed, fused, natural-log, per-sample
median centring -- the ``Metabolomics_fused_log_mean_2019.txt`` matrix that
ships with the deposited data. This script only:

* converts natural log to log2 (so effects read as log2 fold changes);
* renames the 58 analytes to the names ``08-stategra-multiomics`` uses, so
  both examples map to the same KEGG compounds;
* names the columns ``<Ctr|Ik>_<t>H_B<batch>`` and writes the long-form
  design (``column<TAB>condition``);
* derives the relevant list by a RECORDED rule: per metabolite, the F-test
  for Ikaros (main effect + Ikaros x time, adjusting for time) at BH < 0.05.
  The list in ``08`` has no recorded rule; this one does.

Usage::

    cd PaintomicsServer
    PYTHONPATH=. python src/AdminTools/scripts/exampledata/stategrametabolomics.py \
        /path/to/Metabolomics_fused_log_mean_2019.txt

The fused matrix is not in the repository; the outputs are.
"""
import os
import re
import sys
from collections import OrderedDict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if SERVER_ROOT not in sys.path:
    sys.path.insert(0, SERVER_ROOT)

from src.common import ClassActivity as CA  # noqa: E402

FOLDER = "12-stategra-metabolomics-replicates"
DATASETS = os.path.join(SERVER_ROOT, "src", "examplefiles", "datasets")
REFERENCE_VALUES = os.path.join(DATASETS, "08-stategra-multiomics", "data", "metabolomics_values.tab")
FDR = 0.05


def _normalise(name):
    return re.sub(r"mz\d+$", "", re.sub(r"[^a-z0-9]", "", name.lower()))


def displayNames(fusedNames):
    """The 08 dataset's spelling of every fused-file analyte, asserted 1:1."""
    with open(REFERENCE_VALUES, "r") as handle:
        reference = [line.split("\t")[0] for line in handle.read().strip().split("\n")[1:]]
    byNorm = {_normalise(v): v for v in reference}
    out = []
    for name in fusedNames:
        key = "5hydroxyltryptophan" if name == "hydroxyLtryptophan" else _normalise(name)
        if key in byNorm:
            out.append(byNorm[key])
        elif key.startswith("l") and key[1:] in byNorm:
            out.append(byNorm[key[1:]])
        else:
            raise SystemExit("no reference name for fused analyte '%s'" % name)
    if len(set(out)) != len(out):
        raise SystemExit("display names are not unique")
    return out


def build(fusedPath):
    with open(fusedPath, "r") as handle:
        lines = handle.read().strip().split("\n")
    header = lines[0].split("\t")[1:]
    names = [line.split("\t")[0] for line in lines[1:]]
    matrix = np.array([[float(x) for x in line.split("\t")[1:]] for line in lines[1:]]) / np.log(2)

    # Control_0_h_batch_10 -> (Ctr_0H, Ctr_0H_B10)
    conditions, columns = [], []
    for label in header:
        parts = label.split("_")
        arm = "Ik" if parts[0].startswith("Ikaros") else "Ctr"
        condition = "%s_%sH" % (arm, parts[1])
        conditions.append(condition)
        columns.append("%s_B%s" % (condition, parts[-1]))
    sampleHeader = list(OrderedDict.fromkeys(conditions))
    mapping = [sampleHeader.index(c) for c in conditions]

    # The recorded rule for the relevant list.
    factors = CA.designFactors(sampleHeader, mapping)
    treatment = min(factors, key=lambda f: len(f["levels"]))
    F, P, df1, df2 = CA.factorTest(matrix, np.array(treatment["columnLevel"]), np.array(treatment["strata"]))
    bh = CA.benjaminiHochberg({i: float(P[i]) for i in range(len(names)) if np.isfinite(P[i])})
    shown = displayNames(names)
    relevant = [shown[i] for i in range(len(names)) if bh.get(i, 1.0) < FDR]

    outDir = os.path.join(DATASETS, FOLDER, "data")
    os.makedirs(outDir, exist_ok=True)
    with open(os.path.join(outDir, "metabolomics_replicates.tab"), "w") as handle:
        handle.write("#compound\t" + "\t".join(columns) + "\n")
        for i, name in enumerate(shown):
            handle.write(name + "\t" + "\t".join("%.6f" % v for v in matrix[i]) + "\n")
    with open(os.path.join(outDir, "experimental_design.tab"), "w") as handle:
        handle.write("#sample\tcondition\n")
        for column, condition in zip(columns, conditions):
            handle.write(column + "\t" + condition + "\n")
    with open(os.path.join(outDir, "metabolomics_relevant.tab"), "w") as handle:
        handle.write("\n".join(relevant) + "\n")
    print("%s: %d metabolites x %d samples, %d conditions, %d relevant at BH<%.2f "
          "(F(%d,%d) for %s, stratified by %s)"
          % (FOLDER, len(shown), len(columns), len(sampleHeader), len(relevant), FDR,
             int(df1[0]), int(df2[0]), treatment["label"], ", ".join(treatment["strataLabels"][:3]) + "…"))
    return sampleHeader, relevant


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(sys.argv[1])
