#!/usr/bin/env python3
"""Value simulation: planted pathway signal against a quiet background.

Two shapes, because PaintOmics consumes two
-------------------------------------------
* **Ratios** -- what the pathway-acquisition pipeline takes: one column per
  condition, each value a log2 fold change against a reference. Background sits
  at zero; a signal feature moves coherently across conditions.
* **Per-sample matrices** -- what MORE takes: one column per *sample*, with
  replicates, plus a design matrix naming the groups. These are absolute
  (log-)expression values, not ratios, because MORE regresses targets on
  regulators sample by sample and a ratio matrix has no replicate structure to
  regress over.

Determinism
-----------
Every function takes an explicit `random.Random`. No module-level RNG, no
wall-clock, no set iteration feeding a sample. Two runs at the same seed
produce identical bytes, which is what makes a regeneration diff meaningful:
an empty diff proves nothing changed, and a non-empty one is a real change.

Effect sizes
------------
Defaults are chosen so enrichment recovers the planted pathways comfortably
without the data looking synthetic: a 2.5 log2 shift is large but within the
range real perturbation experiments produce, and 0.35 background noise keeps
|background| under ~1 for 99.7% of features.
"""
import math


# A signal feature moves this far, in log2 units, at the last condition.
DEFAULT_EFFECT_SIZE = 2.5

# Background standard deviation, log2 units.
DEFAULT_NOISE = 0.35

# Fraction of a target pathway's members that actually move. Real perturbations
# do not move every member, and 100% would make the relevant-features list
# identical to the pathway definition -- a test that cannot fail.
DEFAULT_SIGNAL_FRACTION = 0.70

# Fraction of signal features that move DOWN. Mixed direction is what real data
# looks like, and it exercises the diverging colour scale in both halves.
DEFAULT_DOWN_FRACTION = 0.25

# Fraction of features OUTSIDE the target pathways that are also called
# relevant. Not decoration: without it the only relevant features in the whole
# submission are the planted ones, so the enrichment background is the planted
# signal itself and every pathway sharing a gene with a target looks enriched
# against it.
#
# Real differential expression is not confined to one program. Measured on the
# real STATegra example, the mean per-pathway relevant rate divided by the
# global relevant rate is 0.26 (miRNA, TF) to 1.06 (DNase) -- i.e. relevance is
# spread roughly as thinly inside a pathway as outside it, with a few pathways
# standing out. With no diffuse relevance at all that ratio sits near 0.1: the
# fixture says "nothing anywhere is differential except these eight pathways",
# which no real dataset does.
#
# 5% is what makes the ratio land at 0.7-1.0 while the planted pathways still
# take the top ranks; see the calibration in the module docstring of
# src/tests/test_example_enrichment_calibration.py.
DEFAULT_DIFFUSE_RATE = 0.05

# A diffusely-relevant feature moves, but less, and with no shared direction:
# it is a gene that passed the differential test on its own, not part of the
# planted program. Keeping it visibly weaker than DEFAULT_EFFECT_SIZE is what
# lets a heatmap still show the planted pathways as the coherent block.
DIFFUSE_EFFECT_SIZE = 1.25


def rampedRatios(rng, nConditions, isSignal,
                 effectSize=DEFAULT_EFFECT_SIZE, noise=DEFAULT_NOISE,
                 downFraction=DEFAULT_DOWN_FRACTION):
    """Log2 ratios for one feature across `nConditions` conditions.

    A signal feature ramps: half the effect at the first condition, the full
    effect at the last. That is what a time course or a dose response looks
    like, and it makes the per-condition heatmaps show a gradient rather than a
    flat block -- so a bug that collapses conditions together is visible.

    The direction is drawn once per feature, not once per condition: a feature
    that flipped sign between adjacent conditions would be noise, not signal.
    """
    if not isSignal:
        return [rng.gauss(0, noise) for _ in range(nConditions)]

    direction = -1.0 if rng.random() < downFraction else 1.0
    values = []
    for index in range(nConditions):
        # 0.5 -> 1.0 across the conditions; with nConditions == 1 this is the
        # full effect, so the single-condition scenario is not half-strength.
        ramp = 1.0 if nConditions == 1 else 0.5 + 0.5 * index / (nConditions - 1)
        values.append(direction * effectSize * ramp + rng.gauss(0, noise))
    return values


def groupProfile(rng, nGroups, isSignal, effectSize=DEFAULT_EFFECT_SIZE):
    """One regulator's own mean per experimental group.

    Every regulator gets an **independent** profile, which is the difference
    between a MORE example that proves something and one that does not.

    An earlier version gave each responding regulator the same monotone ramp,
    scaled only by index. The result was a regulator matrix whose columns were
    near-collinear: within a group every responder had almost the same value, so
    a target's true driver and its two decoys were statistically
    indistinguishable and PLS picked among them close to arbitrarily. Measured
    against the planted ground truth, recovery was 63% for TFs and 64% for
    miRNAs, against a ~52% chance baseline -- a real signal, but far too weak to
    assert on.

    Drawing each group mean independently decorrelates the candidates, so
    "which regulator explains this target" has a discoverable answer.

    A non-responding regulator stays flat: it has no variance across groups to
    explain anything with, which is what MORE's minVariation filter drops.
    """
    if not isSignal:
        return [0.0] * nGroups
    return [rng.gauss(0, effectSize) for _ in range(nGroups)]


def perSampleExpression(rng, groupSizes, profile, baseline=6.0,
                        noise=DEFAULT_NOISE):
    """Absolute per-sample values with replicates, for MORE.

    `groupSizes` is one replicate count per experimental group, so `[3, 3, 3]`
    means three replicates in each of three groups, in that order. `profile` is
    that feature's mean shift per group, from `groupProfile`.

    Values are centred on `baseline` rather than zero because MORE fits linear
    models on these directly: a matrix centred on zero has features whose sign
    flips between replicates, which makes ratio-like downstream summaries
    unstable for no benefit. 6.0 is a typical log2 count-per-million.
    """
    if len(profile) != len(groupSizes):
        raise ValueError("profile must have one entry per group")

    values = []
    for groupIndex, size in enumerate(groupSizes):
        for _ in range(size):
            values.append(baseline + profile[groupIndex] + rng.gauss(0, noise))
    return values


def drivenExpression(rng, regulatorValues, slope, intercept, noise):
    """A target that is a noisy linear function of one regulator.

    This is what makes the MORE scenario assertable. MORE looks for regulators
    whose values explain a target's; if targets are simulated independently of
    the regulators, MORE correctly finds nothing and the scenario proves only
    that the script runs. Here the relationship is real and known, so the
    expected regulator-target pairs can be written to disk and checked.

    `noise` is kept well below `slope` * spread(regulator) so the association
    survives model selection without being noiseless -- a perfect fit would let
    a broken p-value calculation pass.
    """
    return [intercept + slope * value + rng.gauss(0, noise)
            for value in regulatorValues]


# No missing-value helper here, deliberately.
#
# An earlier draft blanked a fraction of cells with "NA", on the assumption that
# real quantification tables have gaps and the example should too. PaintOmics
# does not accept them: PathwayAcquisitionJob.validateFile runs
#
#     list(map(float, line[1:len(line)]))
#
# over every data row and records "Line contains invalid values or symbols" for
# anything that will not parse. `NA`, `NaN`, and an empty cell all fail it. A
# values file with gaps is a file the user cannot upload, so shipping one as an
# example would be teaching a format the application rejects.
#
# Malformed input is still covered -- by src/tests/fake_omics.py, which exists
# to build files that *should* be refused. This package builds files that should
# be accepted, and every cell it writes is a finite number.


def chooseSignalFeatures(rng, pathwayToMembers, targetPathways,
                         signalFraction=DEFAULT_SIGNAL_FRACTION):
    """The set of features carrying the planted signal.

    Iterates `targetPathways` in the given order and samples from each
    pathway's sorted member list, so the result depends only on the seed and
    the inputs -- not on set or dict ordering.
    """
    signal = set()
    for pathway in targetPathways:
        members = pathwayToMembers.get(pathway, ())
        if not members:
            continue
        count = max(1, int(round(len(members) * signalFraction)))
        signal.update(rng.sample(sorted(members), min(count, len(members))))
    return signal


def chooseDiffuseFeatures(rng, features, exclude=(), rate=DEFAULT_DIFFUSE_RATE):
    """Relevant features scattered over the background, independent of pathways.

    Drawn by an independent Bernoulli trial per feature rather than by sampling
    a fixed count, because the property that matters is that relevance is
    *uncorrelated with pathway membership*: a fixed-size sample over a sorted
    list would be uncorrelated too, but a per-feature trial says so directly and
    costs one `rng.random()` each.

    `features` is iterated in the order given, so the caller's ordering (always
    sorted here) is what makes the result reproducible.
    """
    excluded = set(exclude)
    return sorted(feature for feature in features
                  if feature not in excluded and rng.random() < rate)


def formatValue(value, decimals=4):
    """Numbers as fixed-point text; the missing-value token passes through.

    `repr(float)` would emit `1e-05`, which every downstream parser here does
    accept, but which reads as an error to a human opening the file. Fixed
    point keeps the shipped examples readable.
    """
    if isinstance(value, str):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NA"
    return "%.*f" % (decimals, value)
