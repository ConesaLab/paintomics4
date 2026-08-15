#!/usr/bin/env python3
"""Rebuild the real STATegra example data at full published scale.

    cd PaintomicsServer
    python -m src.AdminTools.scripts.exampledata.stategrafull --source <dir>

Why this exists
---------------
The STATegra files PaintOmics has always shipped are a reduced derivative of
the published release (Gomez-Cabrero et al., Sci Data 6:256, 2019): 6,336 of
12,762 genes, 1,109 of 2,396 protein groups, 5,000 arbitrarily-capped
gene-miRNA pairs over 238 of 469 miRNAs, and 18,330 of 52,788 DNase consensus
regions. The reduction predates this repository and nothing here could
regenerate the files -- until this module. It rebuilds every reduced layer of
`08-stategra-multiomics` and `09-stategra-regions` from the published data at
full scale. Metabolomics (58/58, already complete) and `10-stategra-mirna`
(469/469 measured miRNAs) are left untouched, as is `11-stategra-more`
(already built from the full matrix by stategramore.py).

The shipped values were ratios from an unrecorded normalisation that the
public releases do not reproduce, so this is a re-derivation, not an
extension: every number changes, and the published preprocessing scripts in
github.com/STATegraData/STATegraData are followed instead.

What the source directory must contain
--------------------------------------
    stategra_rnaseq.csv
        GSE75417 counts after the published pipeline: filter (>=10 reads in
        >=20 samples), CQN (gene GC/length), ComBat over LIBRARY_PREP, shifted
        positive. 12,762 genes x 36 samples plus an MGI_Symbol column -- the
        same file stategramore.py consumes.
    STATegra_Proteomics_NOT_imputed.txt
        From Script_STATegra_Proteomics.zip: log2 iBAQ, per-sample medians
        aligned to arm means, filtered to the published 2,396 protein groups.
        Missing values still missing.
    dnase_rpkm_tmm_arsyn.tsv
        The 52,788 consensus DHS regions after the published pipeline
        (NOISeq: rpkm on region length, tmm, ARSyNseq on the arm-time factor),
        columns `region  length?  CT0h_rep4 ...`. Produced from
        rawcounts_DNaseSeq_SD.RData by running Script_STATegra_DNaseseq's R
        steps verbatim; kept as an input here because this module does not
        shell out to R.

The mouse GTF (GRCm38 release-102, trimmed and sorted exactly as
deploy/fetch-example-gtf.sh builds it) must exist too: the gene-level DNase
layer is produced by the server's own RGmatch, not by a private reimplementation.

Derivation rules, stated so they can be disagreed with
------------------------------------------------------
*Values* are what the reduced files always claimed to be: per-time-point
log2 Ikaros-over-Control, the mean of the three biological replicates in each
arm. Gene expression and DNase matrices are already log2-scale after their
published pipelines; the DNase matrix is log2-transformed here (its ARSyN
output is positive linear scale).

*Relevance* is the induction contrast this experiment was designed around,
the same rule stategramore.py uses for its TF list: Welch's t-test of the 18
induced samples against the 18 controls, Benjamini-Hochberg FDR, and a floor
on the difference of arm means. Proteomics alone uses the per-time-point
variant (`timepointRelevant`): its 3-replicate groups and missingness leave
the pooled test blind and a groups ANOVA indiscriminate -- the numbers are in
that function's docstring. Per-omic thresholds are constants below. The
published DE analyses used maSigPro time-course models whose exact calls were
never recorded with the data; a stated, reproducible rule beats a
half-remembered one.

*miRNA pairs* are the server's own pairing semantics (MiRNA2GeneJob with its
defaults): every measured miRNA crossed with every annotated target in
mmu_mirBase_to_ensembl.tab that has a measured expression profile -- the
"report=all" output a user gets from the miRNA example, minus the arbitrary
5,000-row cap the old file carried. A pair is relevant when its miRNA is in
the curated relevant-miRNA list of scenario 10, which is exactly what the
server's regulator2genesRelevant output flags.

*DNase gene rows* are Bed2GeneJob's semantics run for real: RGmatch at gene
level with the job's default options, then per-gene mean -- over the relevant
regions only when the gene has any (the job summarises relevant regions and
ignores the rest), else over all assigned regions. A gene is relevant when
any of its regions is.

*Proteomics* rows keep all 2,396 published groups. A (arm, time) group with
no measurement at all takes a below-detection placeholder, the
Perseus/MaxQuant downshift convention (column mean - 1.8 sd, log2), applied
deterministically -- no noise term -- so regeneration is byte-stable. Groups keyed
by their first MaxQuant gene symbol; the 9 groups with no symbol cannot enter
a gene-keyed omic and are dropped; a duplicated symbol keeps the group with
the most measured values.

Determinism: no RNG anywhere, fixed float formats, sorted or source-ordered
output. Two runs over the same inputs produce identical bytes.
"""
import argparse
import os
import sys
from collections import defaultdict
from csv import reader as csv_reader

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..")))

from src.AdminTools.scripts.exampledata.stategramore import benjaminiHochberg  # noqa: E402

MULTIOMICS_FOLDER = "08-stategra-multiomics"
REGIONS_FOLDER = "09-stategra-regions"
MIRNA_FOLDER = "10-stategra-mirna"

TIMES = [0, 2, 6, 12, 18, 24]

# The induction-contrast relevance rule, per omic. FDR is Benjamini-Hochberg
# over that omic's features; the floor is on |mean(Ikaros) - mean(Control)|
# in the matrix's own log2 units. Floors differ because the assays do: a
# two-fold protein shift is ordinary, a two-fold accessibility shift is huge.
GE_FDR, GE_MIN_EFFECT = 0.05, 0.58            # 1.5-fold on expression
PROT_FDR, PROT_MIN_EFFECT = 0.01, 1.0         # 2-fold on protein abundance
DNASE_FDR, DNASE_MIN_EFFECT = 0.05, 0.5       # 1.4-fold on accessibility

# The redundancy cap on the derived gene-miRNA pair file. All 194,881
# annotation pairs over the measured miRNAs are computed, ranked by Kendall
# tau between the gene's and the miRNA's six-timepoint ratio profiles (the
# statistic the server's own miRNA2Target uses in the interactive scenario,
# where repression = negative correlation), and only each gene's strongest
# negative regulators plus each miRNA's strongest targets are shipped. The
# union keeps every one of the 333 miRNAs and every targeted gene present
# while dropping the redundant weak pairs: pathway painting and enrichment
# are gene-level, so a gene's 23rd-weakest regulator adds a parse row, a
# Mongo feature document and enrichment-count work but no biology the top
# five did not already carry. Measured on production, the uncapped file made
# the example ~2x slower end to end (step 1: 41 s -> 59 s local) and wrote
# ~195k feature documents per run.
MIRNA_TOP_PER_GENE = 5
MIRNA_TOP_PER_MIRNA = 20

VALUE_FORMAT = "%.6f"

GE_CONDITIONS = ["Ikaros/Control_%dh" % t for t in TIMES]
DNASE_GENE_CONDITIONS = ["I/C_%dh" % t for t in TIMES]
PROT_CONDITIONS = ["Ratio_%d" % t for t in TIMES]


class SourceMissing(Exception):
    """The source data is not where it was said to be."""


def _sourcePath(sourceDir, name):
    path = os.path.join(sourceDir, name)
    if not os.path.isfile(path):
        raise SourceMissing("the STATegra full source is incomplete: %s is "
                            "not in %s" % (name, sourceDir))
    return path


def _dataDir(outputRoot, folder):
    path = os.path.join(outputRoot, folder, "data")
    if not os.path.isdir(path):
        raise SourceMissing("dataset folder %s does not exist; this module "
                            "rewrites files in place, it does not create "
                            "scenarios" % path)
    return path


# ---------------------------------------------------------------------------
# The two statistics shared by every omic
# ---------------------------------------------------------------------------

def armRatios(matrix, groupColumns):
    """Per-time-point mean(Ikaros) - mean(Control), one column per time.

    `matrix` may contain NaN (proteomics); a group mean is the mean of what
    was measured. Callers guarantee every (arm, time) group has at least one
    value by the time this runs.
    """
    columns = []
    for time in TIMES:
        ik = np.nanmean(matrix[:, groupColumns[("Ik", time)]], axis=1)
        ctr = np.nanmean(matrix[:, groupColumns[("Ctr", time)]], axis=1)
        columns.append(ik - ctr)
    return np.column_stack(columns)


def inductionRelevant(matrix, ikColumns, ctrColumns, fdr, minEffect):
    """Boolean mask of features passing the induction contrast.

    Welch's test, not Student's: an induction that fires in only part of the
    time course inflates one arm's variance, and equal-variance t would read
    that as significance. NaNs are omitted pairwise (proteomics); a feature
    without two values per arm cannot be tested and is not relevant.
    """
    left = matrix[:, ikColumns]
    right = matrix[:, ctrColumns]
    with np.errstate(invalid="ignore", divide="ignore"):
        result = stats.ttest_ind(left, right, axis=1,
                                 equal_var=False, nan_policy="omit")
        pValues = np.asarray(result.pvalue, dtype=float)
        pValues[~np.isfinite(pValues)] = 1.0
        adjusted = np.array(benjaminiHochberg(pValues.tolist()))
        effect = np.abs(np.nanmean(left, axis=1) - np.nanmean(right, axis=1))
        effect[~np.isfinite(effect)] = 0.0
    return (adjusted < fdr) & (effect >= minEffect)


def timepointRelevant(matrix, groupColumns, fdr, minEffect):
    """The induction contrast for an omic the pooled arm test cannot see.

    Proteomics: three replicates per group, heavy missingness, and responses
    confined to part of the time course. Pooling 18-vs-18 washes those out
    (16 of 2,384 passed), while a groups ANOVA also accepts plain time trends
    present in both arms (~50% passed) -- the exact failure stategramore.py
    documents for its TF list. So the question is asked where the design puts
    it: Welch per time point on the observed replicates, the six p-values
    combined with Fisher's method, BH across features, and a floor on the
    largest per-time-point arm difference.
    """
    features = matrix.shape[0]
    combined = np.ones(features)
    maxEffect = np.zeros(features)
    for index in range(features):
        pValues = []
        for time in TIMES:
            ik = matrix[index, groupColumns[("Ik", time)]]
            ctr = matrix[index, groupColumns[("Ctr", time)]]
            ik, ctr = ik[~np.isnan(ik)], ctr[~np.isnan(ctr)]
            if len(ik) >= 2 and len(ctr) >= 2:
                _, pValue = stats.ttest_ind(ik, ctr, equal_var=False)
                if np.isfinite(pValue):
                    pValues.append(max(pValue, 1e-300))
            if len(ik) and len(ctr):
                maxEffect[index] = max(maxEffect[index],
                                       abs(ik.mean() - ctr.mean()))
        if pValues:
            _, combined[index] = stats.combine_pvalues(pValues, method="fisher")
    adjusted = np.array(benjaminiHochberg(combined.tolist()))
    return (adjusted < fdr) & (maxEffect >= minEffect)


# ---------------------------------------------------------------------------
# Writers -- shipped formats, byte-stable
# ---------------------------------------------------------------------------

def writeValues(path, header, ids, matrix):
    with open(path, "w") as handle:
        if header is not None:
            handle.write("\t".join(header) + "\n")
        for identifier, row in zip(ids, matrix):
            handle.write(identifier + "\t" +
                         "\t".join(VALUE_FORMAT % value for value in row) + "\n")
    return path


def writeIds(path, ids, header=None):
    with open(path, "w") as handle:
        if header is not None:
            handle.write(header + "\n")
        for identifier in ids:
            handle.write(identifier + "\n")
    return path


# ---------------------------------------------------------------------------
# Gene expression
# ---------------------------------------------------------------------------

def parseArmTime(sample, armNames=("Ctr", "Ik")):
    """`Batch_1_Ctr_0H` / `CT0h_rep4` / `con_0h_5` -> ("Ctr"/"Ik", hours)."""
    for token in sample.replace("_", " ").split():
        lowered = token.lower()
        for raw, arm in (("ctr", "Ctr"), ("con", "Ctr"), ("ct", "Ctr"),
                         ("ika", "Ik"), ("ik", "Ik")):
            if lowered.startswith(raw) and lowered[len(raw):].rstrip("h").isdigit():
                return arm, int(lowered[len(raw):].rstrip("h"))
            if lowered == raw:
                arm_only = arm
                break
        else:
            if lowered.rstrip("h").isdigit() and lowered.endswith("h"):
                return arm_only, int(lowered.rstrip("h"))
            continue
    raise SourceMissing("cannot read arm/time from sample name %r" % sample)


def groupColumnsFor(samples):
    groups = defaultdict(list)
    for index, sample in enumerate(samples):
        groups[parseArmTime(sample)].append(index)
    missing = [(arm, t) for arm in ("Ik", "Ctr") for t in TIMES
               if not groups.get((arm, t))]
    if missing:
        raise SourceMissing("no samples for groups %r" % missing)
    return groups


def buildGeneExpression(sourceDir, outputRoot):
    path = _sourcePath(sourceDir, "stategra_rnaseq.csv")
    ids, rows = [], []
    with open(path, newline="") as handle:
        reader = csv_reader(handle)
        header = next(reader)
        if header[1] != "MGI_Symbol":
            raise SourceMissing("%s: expected MGI_Symbol second column" % path)
        samples = header[2:]
        for row in reader:
            if not row or row[0] in ids[-1:]:
                continue
            ids.append(row[0])
            rows.append([float(cell) for cell in row[2:]])
    matrix = np.array(rows)
    groups = groupColumnsFor(samples)

    ratios = armRatios(matrix, groups)
    ikCols = sum((groups[("Ik", t)] for t in TIMES), [])
    ctrCols = sum((groups[("Ctr", t)] for t in TIMES), [])
    relevant = inductionRelevant(matrix, ikCols, ctrCols, GE_FDR, GE_MIN_EFFECT)

    dataDir = _dataDir(outputRoot, MULTIOMICS_FOLDER)
    writeValues(os.path.join(dataDir, "gene_expression_values.tab"),
                ["#geneID"] + GE_CONDITIONS, ids, ratios)
    relevantIds = sorted(identifier for identifier, keep in zip(ids, relevant) if keep)
    writeIds(os.path.join(dataDir, "gene_expression_relevant.tab"), relevantIds)
    # geneIndex carries each gene's shipped six-ratio profile so that
    # buildMirnaPairs can rank annotation pairs by profile correlation.
    return {"genes": len(ids), "relevant": len(relevantIds),
            "geneIndex": dict(zip(ids, ratios))}


# ---------------------------------------------------------------------------
# Proteomics
# ---------------------------------------------------------------------------

def buildProteomics(sourceDir, outputRoot):
    path = _sourcePath(sourceDir, "STATegra_Proteomics_NOT_imputed.txt")
    with open(path, newline="") as handle:
        reader = csv_reader(handle, delimiter="\t")
        header = next(reader)
        sampleStart = header.index("Gene.names") + 1
        samples = header[sampleStart:]
        symbols, rows = [], []
        for row in reader:
            symbol = (row[header.index("Gene.names")] or "").split(";")[0].strip()
            symbols.append(symbol)
            rows.append([float(cell) if cell not in ("", "NA", "NaN") else np.nan
                         for cell in row[sampleStart:]])
    matrix = np.array(rows)
    groups = groupColumnsFor(samples)

    # A group with no measurement at all takes a below-detection placeholder:
    # the Perseus/MaxQuant downshift convention, column mean minus 1.8 column
    # standard deviations, without the width noise so regeneration is
    # byte-stable. Not the original script's mins[j]/2 -- that halves a log2
    # value (a square root in linear space) and, applied to the 24% of groups
    # that are empty here rather than its 57 whole-arm cases, it threw
    # on/off ratios out to +/-25 because iBAQ column minima sit 15 log2 units
    # under the mean. Partially-measured groups just average what was
    # measured. Relevance is tested on the observed values alone -- a
    # placeholder says the protein was not seen, it is not a measurement, and
    # letting it into the test inflates the within-arm variance until almost
    # nothing passes.
    observed = matrix.copy()
    noSymbol = sum(1 for symbol in symbols if not symbol)
    placeholder = np.nanmean(matrix, axis=0) - 1.8 * np.nanstd(matrix, axis=0)
    filledGroups = 0
    for (arm, time), columns in groups.items():
        empty = np.all(np.isnan(matrix[:, columns]), axis=1)
        filledGroups += int(empty.sum())
        for column in columns:
            matrix[empty, column] = placeholder[column]

    # One row per symbol: a duplicate keeps the group with the most measured
    # values, because that is the group the instrument actually saw.
    measured = np.sum(~np.isnan(matrix), axis=1)
    keptRow = {}
    for index, symbol in enumerate(symbols):
        if not symbol:
            continue
        best = keptRow.get(symbol)
        if best is None or measured[index] > measured[best]:
            keptRow[symbol] = index
    order = sorted(keptRow)  # deterministic; the old file's order was arbitrary
    indices = [keptRow[symbol] for symbol in order]

    ratios = armRatios(matrix[indices], groups)
    relevant = timepointRelevant(observed[indices], groups,
                                 PROT_FDR, PROT_MIN_EFFECT)

    dataDir = _dataDir(outputRoot, MULTIOMICS_FOLDER)
    writeValues(os.path.join(dataDir, "proteomics_values.tab"),
                ["Protein"] + PROT_CONDITIONS, order, ratios)
    relevantIds = [symbol for symbol, keep in zip(order, relevant) if keep]
    writeIds(os.path.join(dataDir, "proteomics_relevant.tab"), relevantIds)
    return {"groups": len(symbols), "shipped": len(order),
            "droppedNoSymbol": noSymbol, "filledGroups": filledGroups,
            "relevant": len(relevantIds)}


# ---------------------------------------------------------------------------
# miRNA pairs
# ---------------------------------------------------------------------------

def _pairwiseDifferenceSigns(profile):
    """The C(6,2)=15 pairwise-difference signs of a six-value profile.

    Kendall's tau-a between two profiles is then the mean elementwise product
    of their sign vectors -- one dot product per candidate pair instead of a
    scipy call, and identical ordering for tie-free float profiles.
    """
    n = len(profile)
    return np.sign(np.array([profile[j] - profile[i]
                             for i in range(n) for j in range(i + 1, n)]))


def buildMirnaPairs(outputRoot, geneIndex):
    mirnaDir = _dataDir(outputRoot, MIRNA_FOLDER)

    values = {}
    profiles = {}
    with open(os.path.join(mirnaDir, "mirna_unmapped_values.tab")) as handle:
        next(handle)  # header (six condition labels, no ID label)
        for line in handle:
            cells = line.rstrip("\n").split("\t")
            # Keep the source text verbatim: re-formatting 469 floats gains
            # nothing and loses byte-identity with scenario 10.
            values[cells[0]] = "\t".join(cells[1:])
            profiles[cells[0]] = _pairwiseDifferenceSigns(
                np.array([float(cell) for cell in cells[1:]]))

    with open(os.path.join(mirnaDir, "mirna_unmapped_relevant.tab")) as handle:
        relevantMirnas = {line.strip() for line in handle if line.strip()}

    pairs = set()
    with open(os.path.join(mirnaDir, "mmu_mirBase_to_ensembl.tab")) as handle:
        next(handle)
        for line in handle:
            cells = line.rstrip("\n").split("\t")
            if cells[0] in values and cells[1] in geneIndex:
                pairs.add((cells[1], cells[0]))

    # Rank every annotation pair by tau between the gene's and the miRNA's
    # shipped profiles (most negative = strongest repression candidate), then
    # keep the union of each gene's top MIRNA_TOP_PER_GENE regulators and each
    # miRNA's top MIRNA_TOP_PER_MIRNA targets. A tau that cannot be computed
    # (a constant or NaN profile) sorts last via the 2.0 sentinel; name-level
    # tie-breaks keep the selection deterministic across runs.
    geneSigns = {}
    byGene = defaultdict(list)
    byMirna = defaultdict(list)
    for gene, mirna in pairs:
        signs = geneSigns.get(gene)
        if signs is None:
            signs = geneSigns[gene] = _pairwiseDifferenceSigns(
                np.asarray(geneIndex[gene], dtype=float))
        tau = float(np.dot(signs, profiles[mirna])) / len(signs)
        if not np.isfinite(tau):
            tau = 2.0
        byGene[gene].append((tau, mirna))
        byMirna[mirna].append((tau, gene))

    kept = set()
    for gene, candidates in byGene.items():
        for tau, mirna in sorted(candidates)[:MIRNA_TOP_PER_GENE]:
            kept.add((gene, mirna))
    for mirna, candidates in byMirna.items():
        for tau, gene in sorted(candidates)[:MIRNA_TOP_PER_MIRNA]:
            kept.add((gene, mirna))

    dataDir = _dataDir(outputRoot, MULTIOMICS_FOLDER)
    relevantPairs = 0
    with open(os.path.join(dataDir, "mirna_values.tab"), "w") as valuesOut, \
         open(os.path.join(dataDir, "mirna_relevant.tab"), "w") as relevantOut:
        # The `#` schema header is the contract that makes Job.py parse this
        # as a [TARGET, REGULATOR] pair file (see _isPairSchemaHeader). The
        # old headerless copy parsed correctly only because its first miRNA
        # happened to contain four digits; sorted output starts at let-7 and
        # the identifier heuristic then read the file as bare gene IDs --
        # 44,091 relevant pairs became 0 matching relevant features.
        relevantOut.write("# Gene name\tmiRNA ID\n")
        for gene, mirna in sorted(kept):
            valuesOut.write(gene + ":::" + mirna + "\t" + values[mirna] + "\n")
            if mirna in relevantMirnas:
                relevantOut.write(gene + "\t" + mirna + "\n")
                relevantPairs += 1
    return {"pairs": len(kept),
            "annotationPairs": len(pairs),
            "mirnas": len({mirna for _gene, mirna in kept}),
            "genes": len({gene for gene, _mirna in kept}),
            "relevantPairs": relevantPairs}


# ---------------------------------------------------------------------------
# DNase: regions (09) and their gene collapse (08)
# ---------------------------------------------------------------------------

def buildDnase(sourceDir, outputRoot, gtfFile):
    path = _sourcePath(sourceDir, "dnase_rpkm_tmm_arsyn.tsv")
    ids, rows = [], []
    with open(path, newline="") as handle:
        reader = csv_reader(handle, delimiter="\t")
        header = next(reader)
        samples = [column for column in header[1:] if column != "length"]
        offset = len(header) - len(samples)
        for row in reader:
            ids.append(row[0])
            rows.append([float(cell) for cell in row[offset:]])
    # ARSyN output is positive linear scale; the ratios are log2 like every
    # other layer. The pipeline guarantees strictly positive values.
    matrix = np.log2(np.array(rows))
    groups = groupColumnsFor(samples)

    ratios = armRatios(matrix, groups)
    ikCols = sum((groups[("Ik", t)] for t in TIMES), [])
    ctrCols = sum((groups[("Ctr", t)] for t in TIMES), [])
    relevant = inductionRelevant(matrix, ikCols, ctrCols,
                                 DNASE_FDR, DNASE_MIN_EFFECT)

    regionsDir = _dataDir(outputRoot, REGIONS_FOLDER)
    regionCells = [identifier.split("_") for identifier in ids]
    valuesPath = os.path.join(regionsDir, "dnase_unmapped_values.tab")
    with open(valuesPath, "w") as handle:
        handle.write("\t".join(["#CHR", "start", "end"] + GE_CONDITIONS) + "\n")
        for cells, row in zip(regionCells, ratios):
            handle.write("\t".join(cells) + "\t" +
                         "\t".join(VALUE_FORMAT % value for value in row) + "\n")
    with open(os.path.join(regionsDir, "dnase_unmapped_relevant.tab"), "w") as handle:
        for cells, keep in zip(regionCells, relevant):
            if keep:
                handle.write("\t".join(cells) + "\n")

    geneStats = collapseRegionsToGenes(
        valuesPath, gtfFile, outputRoot,
        {identifier for identifier, keep in zip(ids, relevant) if keep})
    geneStats.update({"regions": len(ids), "relevantRegions": int(relevant.sum())})
    return geneStats


def collapseRegionsToGenes(regionValuesPath, gtfFile, outputRoot, relevantRegions):
    """Bed2GeneJob's gene collapse, run through the server's own RGmatch.

    Options are Bed2GeneJob defaults verbatim (distance already scaled to bp,
    exactly as its getOptions() sends them). Aggregation mirrors
    fromBED2Genes: a gene with any relevant region averages only its relevant
    regions and is itself relevant; anything else averages all its regions.
    """
    from src.common.bioscripts.DHS_exon_association import run as runRGmatch

    if not os.path.isfile(gtfFile):
        raise SourceMissing(
            "the mouse GTF is not at %s; build it as deploy/fetch-example-gtf.sh "
            "does (Ensembl GRCm38 release-102, exon/transcript/gene rows, sorted)"
            % gtfFile)

    tmpFile = regionValuesPath + ".rgmatch.tmp"
    options = {"presortedGTF": False, "level": "gene", "distance": 10000,
               "tss": 200, "promoter": 1300, "perc_area": 90,
               "perc_region": 50, "gene_id_tag": "gene_id",
               "ignore_missing": True}
    runRGmatch(gtfFile, regionValuesPath, tmpFile, None, options, None)

    allValues = defaultdict(list)
    relevantValues = defaultdict(list)
    with open(tmpFile) as handle:
        reader = csv_reader(handle, delimiter="\t")
        next(reader)
        for line in reader:
            regionID, geneID = line[0], line[2]
            values = [float(cell) for cell in line[11:]]
            allValues[geneID].append(values)
            if regionID in relevantRegions:
                relevantValues[geneID].append(values)
    os.remove(tmpFile)
    if not allValues:
        raise SourceMissing("RGmatch associated no region with any gene; the "
                            "GTF and the regions disagree about chromosomes")

    dataDir = _dataDir(outputRoot, MULTIOMICS_FOLDER)
    genes = sorted(allValues)
    with open(os.path.join(dataDir, "dnase_values.tab"), "w") as valuesOut, \
         open(os.path.join(dataDir, "dnase_relevant.tab"), "w") as relevantOut:
        valuesOut.write("\t".join(["#Gene name"] + DNASE_GENE_CONDITIONS) + "\n")
        relevantOut.write("#Gene name\n")
        relevantGenes = 0
        for gene in genes:
            selected = relevantValues.get(gene) or allValues[gene]
            if gene in relevantValues:
                relevantOut.write(gene + "\n")
                relevantGenes += 1
            summarized = np.mean(np.array(selected), axis=0)
            valuesOut.write(gene + "\t" +
                            "\t".join(VALUE_FORMAT % value for value in summarized) + "\n")
    return {"genes": len(genes), "relevantGenes": relevantGenes}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_DEFAULT_SOURCE = os.path.expanduser(
    "~/Desktop/github_dev/paintomics4_data/stategra-full")


def serverRoot():
    return os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        "..", "..", "..", ".."))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=_DEFAULT_SOURCE,
                        help="directory holding the published STATegra matrices")
    parser.add_argument("--gtf", default=os.path.join(
        serverRoot(), "src", "examplefiles", "GTF", "sorted_mmu.gtf"),
        help="the trimmed sorted mouse GTF (deploy/fetch-example-gtf.sh)")
    parser.add_argument("--output-dir", default=None,
                        help="datasets root (defaults to src/examplefiles/datasets)")
    arguments = parser.parse_args()

    outputRoot = arguments.output_dir or os.path.join(
        serverRoot(), "src", "examplefiles", "datasets")

    try:
        ge = buildGeneExpression(arguments.source, outputRoot)
        print("gene expression: %(genes)d genes, %(relevant)d relevant" % ge)
        prot = buildProteomics(arguments.source, outputRoot)
        print("proteomics: %(shipped)d of %(groups)d groups shipped "
              "(%(droppedNoSymbol)d without a symbol dropped, %(filledGroups)d "
              "empty groups placeholdered), %(relevant)d relevant" % prot)
        mirna = buildMirnaPairs(outputRoot, ge["geneIndex"])
        print("miRNA: %(pairs)d of %(annotationPairs)d annotation pairs kept "
              "(top %(topGene)d/gene + top %(topMirna)d/miRNA by tau) over "
              "%(mirnas)d miRNAs and %(genes)d genes, %(relevantPairs)d "
              "relevant pairs" % dict(mirna, topGene=MIRNA_TOP_PER_GENE,
                                      topMirna=MIRNA_TOP_PER_MIRNA))
        dnase = buildDnase(arguments.source, outputRoot, arguments.gtf)
        print("DNase: %(regions)d regions (%(relevantRegions)d relevant) -> "
              "%(genes)d genes (%(relevantGenes)d relevant)" % dnase)
    except SourceMissing as error:
        parser.error(str(error))
        return 2

    print("Now regenerate the manifest:")
    print("    python -m src.AdminTools.scripts.exampledata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
