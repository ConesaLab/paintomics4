#!/usr/bin/env python3
"""The real STATegra data, subsampled into a MORE regulatory example.

    cd PaintomicsServer
    python -m src.AdminTools.scripts.exampledata.stategramore --source <dir>

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
Network      **TFLink v1.0**, *Mus musculus*, "All simple" format. Curated and
             predicted TF->target edges; the source set keeps at most 30
             regulators per target.

The full set is 9,835 targets x 564 regulators x 291,353 associations. That is
too large to bundle and too slow to demonstrate on R -- measured, not guessed:
R PLS1 runs the bundled subset in minutes and the full set in hours, where the
Rust port does the same work in under a second. So this ships a subsample.

Why the subsample is RANDOM, and not the most responsive genes
--------------------------------------------------------------
The obvious selection -- rank targets by how strongly they move with the design
and keep the top N -- produces a dataset that looks impressive and measures
nothing. Selecting on the same variation the model is about to fit saturates
the result: on this data, PLS1 called **97.1%** of candidate pairs significant
for a top-F subsample of 600, against **79.7%** for a uniform random subsample
of the same size. The first number says the selection worked; only the second
says anything about the method.

A uniform random subsample is unbiased in every distribution that matters --
expression level, variance, regulator degree, pathway membership -- so what the
user sees is what MORE does to this experiment, scaled down. The seed is fixed
so the files are reproducible.

The one non-random choice is the "relevant regulators" list, which mirrors what
a user would upload: the regulators they consider differentially expressed. It
is computed here by a stated, ordinary criterion (one-way ANOVA across the 12
groups, Benjamini-Hochberg FDR < 0.01) rather than curated by hand, so it can
be recomputed and argued with.

What a fresh checkout can and cannot do
---------------------------------------
The generated files are **committed**, like every other bundled example. This
module needs the source dataset, which lives outside the repository and is not
redistributed here; without `--source` it does nothing and says so. That is the
same bargain `legacy.py` strikes for the other three STATegra scenarios.
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..")))

from src.AdminTools.scripts.exampledata import writers          # noqa: E402

FOLDER = "11-stategra-more"

# 600 targets. Chosen against measured runtime rather than taste: the Rust port
# fits this in well under a second, R PLS1 in single-digit minutes, and R MLR
# inside the 1800 s job timeout -- so all three engines the interface offers can
# actually be run on it, which is the point of bundling it.
TARGET_COUNT = 600

# Fixed so regeneration is byte-identical. Same rule as the simulated
# scenarios: a non-empty `git diff` after regenerating is a review item.
SEED = 20260811

# The "relevant regulators" list is significance AND effect size, the pair any
# ordinary differential-expression cut uses -- 0.01 rather than the usual 0.05
# because at 0.05 two thirds of the 564 TFs qualify, and a two-fold floor
# because significance alone still passes 441 of them. Together they keep 276.
#
# That is still 49%, and it is not a threshold that wants tightening: this is a
# 24-hour Ikaros induction time course, a strong perturbation, and half the
# measured transcription factors really do move two-fold across it. Standard
# thresholds and an honest count beat tuned thresholds and a tidy one.
RELEVANT_FDR = 0.01
RELEVANT_MIN_LOG2_RANGE = 1.0

_DEFAULT_SOURCE = os.path.expanduser(
    "~/Desktop/github_dev/paintomics4_data/more-scale-test/data")


class SourceMissing(Exception):
    """The source dataset is not where it was said to be."""


# ---------------------------------------------------------------------------
# Reading the source
# ---------------------------------------------------------------------------

def readMatrix(path):
    """`ID<TAB>sample…` with a plain header -- runMORE.R's read_matrix shape.

    Values are kept as text as well as floats: the text is what gets written
    back out, so a round trip cannot introduce a formatting difference of its
    own (13.594162 must not become 13.594161999999999).
    """
    with open(path, encoding="utf-8") as handle:
        samples = handle.readline().rstrip("\n").split("\t")[1:]
        numeric, raw = {}, {}
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != len(samples) + 1:
                raise SourceMissing(
                    "%s: row %r has %d values for %d samples"
                    % (os.path.basename(path), parts[0], len(parts) - 1, len(samples)))
            numeric[parts[0]] = [float(value) for value in parts[1:]]
            raw[parts[0]] = parts[1:]
    return samples, numeric, raw


def readDesign(path):
    """MORE's edesign: one row per sample, one 0/1 column per group."""
    with open(path, encoding="utf-8") as handle:
        groups = handle.readline().rstrip("\n").split("\t")[1:]
        order, membership = [], {}
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            indicators = [int(value) for value in parts[1:]]
            if sum(indicators) != 1:
                raise SourceMissing(
                    "%s: sample %r belongs to %d groups; MORE's edesign needs "
                    "exactly one" % (os.path.basename(path), parts[0],
                                     sum(indicators)))
            order.append(parts[0])
            membership[parts[0]] = groups[indicators.index(1)]
    return groups, order, membership


def readAssociations(path):
    """`Target<TAB>Regulator`, header included -- runMORE.R reads header=TRUE."""
    associations = {}
    with open(path, encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            target, regulator = line.rstrip("\n").split("\t")[:2]
            associations.setdefault(target, set()).add(regulator)
    return associations


# ---------------------------------------------------------------------------
# The one statistic this module computes
# ---------------------------------------------------------------------------

def anovaF(values, sampleGroups):
    """One-way F across the design's groups.

    Zero when the within-group variance is zero, which is the degenerate case
    a constant row produces; MORE's own minVariation filter would drop such a
    row anyway, and returning 0.0 keeps it out of the relevance list without a
    division by zero on the way.
    """
    byGroup = {}
    for value, group in zip(values, sampleGroups):
        byGroup.setdefault(group, []).append(value)

    grandMean = sum(values) / len(values)
    between = sum(len(members) * (sum(members) / len(members) - grandMean) ** 2
                  for members in byGroup.values())
    within = sum((value - sum(members) / len(members)) ** 2
                 for members in byGroup.values() for value in members)

    dfBetween = len(byGroup) - 1
    dfWithin = len(values) - len(byGroup)
    if within <= 0 or dfBetween <= 0 or dfWithin <= 0:
        return 0.0
    return (between / dfBetween) / (within / dfWithin)


def benjaminiHochberg(pValues):
    """Adjusted p-values, in the input's order.

    Written out rather than imported so this module does not add a statsmodels
    dependency for six lines; scipy supplies the F distribution and nothing
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


def groupMeanRange(values, sampleGroups):
    """Largest minus smallest group mean -- the effect size, in log2 units."""
    byGroup = {}
    for value, group in zip(values, sampleGroups):
        byGroup.setdefault(group, []).append(value)
    means = [sum(members) / len(members) for members in byGroup.values()]
    return max(means) - min(means)


def relevantRegulators(regulators, sampleGroups, groupCount):
    """The TFs a user would plausibly have flagged as differentially expressed.

    One-way ANOVA across the design's groups, BH-adjusted, and a two-fold floor
    on the effect size. Both halves are needed: with 36 samples the F test alone
    passes 441 of 564 TFs, which is a statement about the experiment's power
    rather than about the regulators.

    Deterministic, and stated in the README, so a reader can disagree with it on
    the merits rather than wonder where the list came from.
    """
    from scipy import stats

    names = sorted(regulators)
    dfBetween = groupCount - 1
    dfWithin = len(sampleGroups) - groupCount

    statistics = [anovaF(regulators[name], sampleGroups) for name in names]
    pValues = [float(stats.f.sf(value, dfBetween, dfWithin)) if value > 0 else 1.0
               for value in statistics]
    adjusted = benjaminiHochberg(pValues)

    return [name for name, q in zip(names, adjusted)
            if q < RELEVANT_FDR
            and groupMeanRange(regulators[name], sampleGroups) >= RELEVANT_MIN_LOG2_RANGE]


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def buildFiles(sourceDir, outputRoot):
    """Write the subsampled dataset and return the paths, keyed by role."""
    required = {
        "targets": "gene_expression_targets.tab",
        "regulators": "transcription_factor_regulators.tab",
        "associations": "transcription_factor_associations.tab",
        "design": "experimental_design.tab",
    }
    paths = {}
    for role, name in required.items():
        path = os.path.join(sourceDir, name)
        if not os.path.isfile(path):
            raise SourceMissing(
                "the STATegra MORE source is incomplete: %s is not in %s"
                % (name, sourceDir))
        paths[role] = path

    samples, targets, targetText = readMatrix(paths["targets"])
    regulatorSamples, regulators, regulatorText = readMatrix(paths["regulators"])
    groups, designOrder, membership = readDesign(paths["design"])
    associations = readAssociations(paths["associations"])

    # Sample order has to agree across all three files. MORE pairs them by name
    # AND by position, so a set-equal-but-reordered header fits a model against
    # values from the wrong samples and reports nothing wrong.
    if samples != regulatorSamples or samples != designOrder:
        raise SourceMissing(
            "the source files disagree about sample order: targets %d, "
            "regulators %d, design %d columns/rows, and MORE pairs them by "
            "position" % (len(samples), len(regulatorSamples), len(designOrder)))

    sampleGroups = [membership[sample] for sample in samples]

    # Uniform, seeded, and taken from the targets that have both measurements
    # and at least one association -- a target with no candidate regulator
    # contributes a row MORE cannot model and a user cannot interpret.
    modellable = sorted(set(targets) & set(associations))
    if len(modellable) < TARGET_COUNT:
        raise SourceMissing(
            "only %d targets have both values and associations; %d were asked "
            "for" % (len(modellable), TARGET_COUNT))
    chosen = sorted(random.Random(SEED).sample(modellable, TARGET_COUNT))

    # Every regulator that still has an edge, and no others: carrying the full
    # 564 would leave 250-odd regulators in the matrix that no association
    # points at, which MORE reads, filters and discards -- work whose only
    # visible effect is a slower job.
    keptRegulators = sorted({regulator
                             for target in chosen
                             for regulator in associations[target]}
                            & set(regulators))

    dataDir = os.path.join(outputRoot, FOLDER, "data")
    targetFile = writers.writeMatrix(
        os.path.join(dataDir, "gene_expression_targets.tab"),
        "GeneID", samples, [(gene, targetText[gene]) for gene in chosen])
    regulatorFile = writers.writeMatrix(
        os.path.join(dataDir, "transcription_factor_regulators.tab"),
        "RegulatorID", samples,
        [(name, regulatorText[name]) for name in keptRegulators])

    keptSet = set(keptRegulators)
    pairs = [(target, regulator)
             for target in chosen
             for regulator in sorted(associations[target] & keptSet)]
    associationFile = writers.writeAssociations(
        os.path.join(dataDir, "transcription_factor_associations.tab"),
        pairs, header=("Target", "Regulator"))

    designFile = writers.writeDesign(
        os.path.join(dataDir, "experimental_design.tab"),
        samples, groups, sampleGroups)

    flagged = relevantRegulators(
        {name: regulators[name] for name in keptRegulators},
        sampleGroups, len(groups))
    relevantFile = writers.writeIdList(
        os.path.join(dataDir, "transcription_factor_relevant_regulators.tab"),
        flagged)

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
        "pairs": pairs,
        "flagged": flagged,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=_DEFAULT_SOURCE,
                        help="directory holding the full STATegra MORE dataset")
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

    print("%s: %d targets, %d regulators, %d associations, %d flagged"
          % (FOLDER, len(built["targets"]), len(built["regulators"]),
             len(built["pairs"]), len(built["flagged"])))
    print("Now regenerate the manifest:")
    print("    python -m src.AdminTools.scripts.exampledata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
