#!/usr/bin/env python3
"""The real STATegra data against a curated TF network, as a MORE example.

    cd PaintomicsServer
    python -m src.AdminTools.scripts.exampledata.stategramore --source <raw dir>

Why this exists
---------------
`06-regulatory-more` is simulated: every target is a noisy linear function of
one known regulator, which is what makes its recall assertable. That is the
right shape for a test and the wrong shape for a demonstration -- nobody's data
looks like that, and a user who loads it learns what MORE does to a fixture
rather than what it does to an experiment. This scenario is the other half:
real measurements, a real regulatory network, and no ground truth to check
against.

Provenance
----------
Expression   GEO **GSE75417** -- STATegra RNA-seq, mouse B3 pre-B cells,
             Ikaros induction versus control, CQN-normalised and ComBat-
             corrected. 36 samples, 12 groups (Ctr/Ik x 0,2,6,12,18,24 h),
             three biological replicates per group.
Network      **TFLink v1.0**, *Mus musculus*, restricted to the interactions
             TFLink flags as `Small-scale.evidence = Yes` -- supported by a
             low-throughput, single-interaction experiment rather than by a
             genome-wide screen.

Why the network is the small-scale subset, and not TFLink "All"
---------------------------------------------------------------
This is the whole point of the rebuild, so it is worth stating plainly.

TFLink "All" is 99.7% GTRD ChIP-seq peaks. Peak-derived edges are dominated by
promiscuous binders: in the previous version of this scenario -- 600 genes
against the "All" network, at most 30 regulators per target -- **Myc alone was
an annotated regulator of 573 of the 600 targets (95.5%)**, with Jun, Nr1d1,
Irf4 and Ets1 each above 90%.

That interacts badly with how MORE's red stars reach pathway enrichment.
`MOREServlet.fromMOREtoGenes_STEP2` marks a gene relevant when **any** of its
regulators appears in the user's significant-regulator list, and Myc genuinely
does respond to Ikaros induction, so one true positive starred 95% of the
submission. The measured result: 600 of 600 targets relevant, and therefore a
hypergeometric p of exactly 1.0 for all 309 matched pathways -- zero
significant pathways, before any FDR correction, with no threshold able to
change it. The pathway half of the example demonstrated nothing.

Tightening the statistics does not fix that, because the cause is the network's
degree distribution and not the flagging rule. Measured on the old files: at
FDR < 1e-12 the list falls from 176 TFs to 43 and 99.2% of targets are still
starred; at a four-fold effect-size floor, 21 TFs still star 98.3%.

The small-scale subset is a different network rather than a smaller one:

    TFLink "All"          1,152 TFs   21,160 targets   4.02M edges   top TF 89.7%
    Small-scale evidence    846 TFs    2,501 targets   8,682 edges   top TF 16.3%

Intersected with what this experiment measures it gives ~3 regulators per
target instead of 30, which is also the range MORE can actually identify from
36 samples. The resulting star rate is ~31%, and the enrichment separates.

Why there is no subsample any more
----------------------------------
The old version drew 600 targets uniformly at random from 9,835, seeded, and
argued at length for uniform over signal-led selection -- the argument was
sound (top-F selection saturated PLS1 at 97.1% significant pairs against 79.7%
for a uniform draw) but the whole problem it solved came from the "All"
network's size. The curated network is small enough to ship whole, so this
module now emits **every** gene that has both a measured expression profile and
at least one small-scale association. Nothing is sampled, no seed is involved,
and the dataset is fully determined by the two public inputs plus the filters
stated here.

The relevant-regulators list
----------------------------
Still the one non-random choice, and it mirrors what a user would upload: the
regulators they consider differentially expressed. Where the old list asked
"does this TF move at all across the 12 groups" -- a one-way ANOVA, which also
answers yes for anything with a plain time trend present in both arms, and
passed 51% of the TFs -- this asks the question the experiment was designed
around: **does this TF respond to Ikaros induction?** A Welch t-test of the 18
Ik samples against the 18 Ctr samples, Benjamini-Hochberg FDR < 0.01, and a
two-fold floor on the difference of means. It is both better posed and more
selective, keeping 56 of 387.

What a fresh checkout can and cannot do
---------------------------------------
The generated files are **committed**, like every other bundled example. This
module needs the source data, which lives outside the repository and is not
redistributed here; without `--source` it does nothing and says so. That is the
same bargain `legacy.py` strikes for the other three STATegra scenarios.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..")))

from src.AdminTools.scripts.exampledata import writers          # noqa: E402

FOLDER = "11-stategra-more"

# Significance AND effect size, the pair any ordinary differential-expression
# cut uses. 0.01 rather than 0.05 because 36 samples give the test enough power
# that 0.05 is a statement about the design; a two-fold floor because
# significance alone still passes TFs that move by a few percent.
RELEVANT_FDR = 0.01
RELEVANT_MIN_LOG2_FOLD = 1.0

# Six decimals, matching what the source pipeline wrote and what the previous
# generation of these files carried. Fixed width so regeneration is
# byte-identical: a non-empty `git diff` after regenerating is a review item.
VALUE_FORMAT = "%.6f"

# The arm labels embedded in the STATegra sample names, `Batch_<n>_<arm>_<t>H`.
INDUCED_ARM = "Ik"
CONTROL_ARM = "Ctr"

_DEFAULT_SOURCE = os.path.expanduser(
    "~/Desktop/github_dev/paintomics4_data/more-scale-test/raw")


class SourceMissing(Exception):
    """The source data is not where it was said to be."""


# ---------------------------------------------------------------------------
# Reading the source
# ---------------------------------------------------------------------------

def readExpression(path):
    """The GSE75417 matrix: Ensembl row names, an MGI symbol, then samples.

    Returns (sampleNames, valuesByGene, symbolByGene). Duplicated Ensembl IDs
    would make a target ambiguous and would also break `writeMatrix`, so the
    first is kept and the rest dropped; an all-missing row carries no signal
    and is dropped too. Both are reported by the caller rather than silently.
    """
    import csv

    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if len(header) < 3 or header[1] != "MGI_Symbol":
            raise SourceMissing(
                "%s: expected an Ensembl row-name column then MGI_Symbol, got "
                "%r" % (os.path.basename(path), header[:3]))
        samples = header[2:]

        values, symbols, duplicates, empty = {}, {}, 0, 0
        for row in reader:
            if not row:
                continue
            gene = row[0]
            if gene in values:
                duplicates += 1
                continue
            cells = row[2:]
            if len(cells) != len(samples):
                raise SourceMissing(
                    "%s: row %r has %d values for %d samples"
                    % (os.path.basename(path), gene, len(cells), len(samples)))
            if all(cell.strip() in ("", "NA", "NaN") for cell in cells):
                empty += 1
                continue
            values[gene] = [float(cell) for cell in cells]
            symbols[gene] = row[1]
    return samples, values, symbols, duplicates, empty


def symbolToEnsembl(symbols):
    """Invert the symbol column, dropping ambiguous symbols rather than guessing.

    A symbol that names two Ensembl IDs cannot be resolved from this file, and
    picking one would silently attach a TFLink edge to an arbitrary gene. There
    are few of them and they are reported.
    """
    mapping, ambiguous = {}, set()
    for gene, symbol in symbols.items():
        if symbol in ("", "nan", "NA", "NaN"):
            continue
        if symbol in mapping and mapping[symbol] != gene:
            ambiguous.add(symbol)
        else:
            mapping[symbol] = gene
    for symbol in ambiguous:
        mapping.pop(symbol, None)
    return mapping, len(ambiguous)


def readSmallScalePairs(path):
    """TFLink's simple pair export: `TF<TAB>Target<TAB>Small-scale.evidence`.

    Only the `Yes` rows are kept -- see the module docstring for why that
    single column is what makes this dataset work at all.
    """
    pairs = set()
    scanned = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            scanned += 1
            if fields[2].strip() == "Yes":
                pairs.add((fields[0], fields[1]))
    if not pairs:
        raise SourceMissing(
            "%s: no row is flagged Small-scale.evidence = Yes; this is not "
            "TFLink's simple pair export" % os.path.basename(path))
    return pairs, scanned


def parseDesign(samples):
    """`Batch_<n>_<arm>_<t>H` -> group `<arm>_<t>H`, in chronological order.

    Chronological and not lexicographic: sorted as text, `Ctr_12H` precedes
    `Ctr_2H`, and MORE would then report the time course out of order in every
    downstream table.
    """
    arms, groups = [], []
    for sample in samples:
        parts = sample.split("_")
        if len(parts) != 4 or not parts[3].endswith("H"):
            raise SourceMissing(
                "unexpected sample name %r: expected Batch_<n>_<arm>_<t>H"
                % sample)
        arms.append(parts[2])
        groups.append(parts[2] + "_" + parts[3])

    def chronological(group):
        arm, time = group.split("_")
        return (arm != CONTROL_ARM, int(time.rstrip("H")))

    return sorted(set(groups), key=chronological), groups, arms


# ---------------------------------------------------------------------------
# The one statistic this module computes
# ---------------------------------------------------------------------------

def benjaminiHochberg(pValues):
    """Adjusted p-values, in the input's order.

    Written out rather than imported so this module does not add a statsmodels
    dependency for six lines; scipy supplies the t distribution and nothing
    else is needed.
    """
    ordered = sorted(range(len(pValues)), key=lambda i: pValues[i])
    total = len(pValues)
    adjusted = [1.0] * total
    running = 1.0
    for rank, index in enumerate(reversed(ordered), start=1):
        position = total - rank + 1
        running = min(running, pValues[index] * total / position)
        adjusted[index] = running
    return adjusted


def inductionResponders(regulators, arms):
    """The TFs a user would plausibly flag after this experiment.

    Welch's t-test of the induced samples against the controls -- unequal
    variances, because an induction that fires in only part of the time course
    inflates the variance on one side and Student's test would read that as
    significance. BH across the tested TFs, then a two-fold floor on the
    difference of arm means.

    Deterministic, and stated in the manifest, so a reader can disagree with it
    on the merits rather than wonder where the list came from.
    """
    from scipy import stats

    induced = [index for index, arm in enumerate(arms) if arm == INDUCED_ARM]
    control = [index for index, arm in enumerate(arms) if arm == CONTROL_ARM]
    if not induced or not control:
        raise SourceMissing(
            "the design has no %s/%s split; the relevance rule for this "
            "scenario is the induction contrast and cannot be computed"
            % (INDUCED_ARM, CONTROL_ARM))

    names = sorted(regulators)
    pValues, effects = [], []
    for name in names:
        values = regulators[name]
        left = [values[index] for index in induced]
        right = [values[index] for index in control]
        statistic, pValue = stats.ttest_ind(left, right, equal_var=False)
        pValues.append(float(pValue) if pValue == pValue else 1.0)
        effects.append(abs(sum(left) / len(left) - sum(right) / len(right)))

    adjusted = benjaminiHochberg(pValues)
    return [name for name, q, effect in zip(names, adjusted, effects)
            if q < RELEVANT_FDR and effect >= RELEVANT_MIN_LOG2_FOLD]


def variance(values):
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def buildFiles(sourceDir, outputRoot):
    """Write the dataset and return the paths and counts, keyed by role."""
    required = {
        "expression": "stategra_rnaseq.csv",
        "network": "tflink_pairs.tsv",
    }
    paths = {}
    for role, name in required.items():
        path = os.path.join(sourceDir, name)
        if not os.path.isfile(path):
            raise SourceMissing(
                "the STATegra MORE source is incomplete: %s is not in %s"
                % (name, sourceDir))
        paths[role] = path

    samples, values, symbols, duplicates, empty = readExpression(paths["expression"])
    groups, sampleGroups, arms = parseDesign(samples)
    sym2ens, ambiguous = symbolToEnsembl(symbols)
    pairs, scanned = readSmallScalePairs(paths["network"])

    # Both ends must be measured here, or the edge cannot enter a model. Self
    # regulation is dropped: a regulator that is its own target predicts its
    # own row perfectly and tells the user nothing.
    mapped = {(tf, sym2ens[tf], sym2ens[target])
              for tf, target in pairs
              if tf in sym2ens and target in sym2ens
              and sym2ens[tf] != sym2ens[target]}

    # A regulator with no variation cannot explain anything, and MORE's own
    # minVariation filter would drop it later -- doing it here keeps the
    # shipped matrix honest about what is actually in play.
    varying = {tf for tf, tfGene, _target in mapped
               if variance(values[tfGene]) > 0.0}
    edges = sorted((target, tf) for tf, _tfGene, target in mapped
                   if tf in varying)

    chosen = sorted({target for target, _tf in edges})
    keptRegulators = sorted({tf for _target, tf in edges})
    if not chosen or not keptRegulators:
        raise SourceMissing(
            "no association survived mapping to the expression matrix; the "
            "network and the expression file are probably different species")

    def formatted(gene):
        return [VALUE_FORMAT % value for value in values[gene]]

    dataDir = os.path.join(outputRoot, FOLDER, "data")
    targetFile = writers.writeMatrix(
        os.path.join(dataDir, "gene_expression_targets.tab"),
        "GeneID", samples, [(gene, formatted(gene)) for gene in chosen])

    # TF symbols read better than Ensembl IDs everywhere the regulator is shown
    # -- the Step 3 network view labels nodes with exactly this column.
    regulatorFile = writers.writeMatrix(
        os.path.join(dataDir, "transcription_factor_regulators.tab"),
        "RegulatorID", samples,
        [(tf, formatted(sym2ens[tf])) for tf in keptRegulators])

    associationFile = writers.writeAssociations(
        os.path.join(dataDir, "transcription_factor_associations.tab"),
        edges, header=("Target", "Regulator"))

    designFile = writers.writeDesign(
        os.path.join(dataDir, "experimental_design.tab"),
        samples, groups, sampleGroups)

    flagged = inductionResponders(
        {tf: values[sym2ens[tf]] for tf in keptRegulators}, arms)
    relevantFile = writers.writeIdList(
        os.path.join(dataDir, "transcription_factor_relevant_regulators.tab"),
        flagged)

    # The property that broke the previous version of this scenario, recorded
    # so the manifest can carry it and a test can assert it.
    flaggedSet = set(flagged)
    regulatorsOf = {}
    for target, tf in edges:
        regulatorsOf.setdefault(target, set()).add(tf)
    starred = sum(1 for target in chosen if regulatorsOf[target] & flaggedSet)

    return {
        "targetFile": targetFile,
        "regulatorFile": regulatorFile,
        "associationFile": associationFile,
        "designFile": designFile,
        "relevantFile": relevantFile,
        "samples": samples,
        "groups": groups,
        "targets": chosen,
        "regulators": keptRegulators,
        "pairs": edges,
        "flagged": flagged,
        "starred": starred,
        "duplicates": duplicates,
        "emptyRows": empty,
        "ambiguousSymbols": ambiguous,
        "networkRowsScanned": scanned,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=_DEFAULT_SOURCE,
                        help="directory holding the raw STATegra and TFLink files")
    parser.add_argument("--output-dir", default=None,
                        help="datasets root (defaults to src/examplefiles/datasets)")
    arguments = parser.parse_args()

    outputRoot = arguments.output_dir or os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "examplefiles", "datasets"))

    try:
        built = buildFiles(arguments.source, outputRoot)
    except SourceMissing as error:
        parser.error(str(error))
        return 2

    targets = len(built["targets"])
    print("%s: %d targets, %d regulators, %d associations (%.1f per target)"
          % (FOLDER, targets, len(built["regulators"]), len(built["pairs"]),
             len(built["pairs"]) / float(targets)))
    print("  dropped %d duplicate and %d all-missing expression rows, and %d "
          "ambiguous symbols" % (built["duplicates"], built["emptyRows"],
                                 built["ambiguousSymbols"]))
    print("  %d of %d regulators respond to induction; they star %d of %d "
          "targets (%.1f%%)"
          % (len(built["flagged"]), len(built["regulators"]), built["starred"],
             targets, 100.0 * built["starred"] / targets))
    print("Now regenerate the manifest:")
    print("    python -m src.AdminTools.scripts.exampledata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
