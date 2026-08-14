#!/usr/bin/env python3
"""The scenario catalogue -- the only file that changes to add an example.

Each builder returns the manifest entry for one scenario and writes that
scenario's files underneath it. Adding a scenario means writing one function and
appending it to `CATALOGUE`; nothing in the servlets, the client or the loader
needs to know it exists.

Design notes that apply to every builder
----------------------------------------
* **Paths in the returned entry are relative to EXAMPLE_FILES_DIR**, never
  absolute, so the manifest survives the tree being mounted elsewhere (the
  deploy image and the dev checkout do not agree on a prefix).
* **Every scenario gets its own RNG**, seeded from the run seed and a CRC of the
  scenario id. `hash()` is not usable for this: Python randomises string hashing
  per process, so a `hash`-derived seed would produce different data on every
  run while looking deterministic.
* **Condition names must not look like feature IDs.** The header-vs-data
  heuristic (Job._row_looks_like_data) calls any cell with 4+ consecutive digits
  or a colon a data cell, so `T00h` is a safe condition name and `T2024` is not.
* **Sizes are chosen against a cost model, not by taste.** MORE costs roughly
  0.29 s per target gene, so its scenario is deliberately the smallest: a user
  who clicks "load example" should get a result, not a coffee break.
"""
import os
import zlib
import random

from . import simulate
from . import writers


# Six-point time course, matching the shape of the real STATegra example so the
# simulated and real scenarios are directly comparable.
TIME_COURSE = ["T00h", "T02h", "T06h", "T12h", "T18h", "T24h"]

# How many pathways carry a planted signal. Enough that enrichment has something
# to rank, few enough that the background is genuinely background.
DEFAULT_TARGET_PATHWAYS = 8

# A target pathway of the multi-omic scenario must hold at least this many
# metabolites, or its Metabolomics p-value is 1.0 by construction and the
# "compound enrichment" the manifest advertises is untested for that pathway.
MIN_TARGET_COMPOUNDS = 5

# The compound equivalent of PERIPHERAL_LEAKAGE_LADDER. Metabolites are shared
# between pathways far more freely than genes -- ATP is in 90 of them -- so a
# compound signal planted without a cap leaks everywhere: measured, planting
# every compound of eight target pathways made 18% of the compound-bearing
# pathways significant. Restricting the planting to compounds that appear in at
# most six of this species' pathways brings that to 5.7% with the targets still
# in the top ten. Pathways whose metabolites are all promiscuous fall back to
# their full list rather than planting nothing.
MAX_COMPOUND_SHARING = 6
MIN_PLANTABLE_COMPOUNDS = 3

# Rows in the name-keyed metabolomics variant. Enough that the
# matched-metabolites table is worth looking at, small enough that the
# per-name MongoDB regex it triggers stays quick.
BY_NAME_COMPOUNDS = 400


class BuildContext(object):
    """Everything a builder needs, and nothing it does not."""

    def __init__(self, kegg, outputRoot, manifestRelativeRoot, seed):
        self.kegg = kegg
        self.outputRoot = outputRoot                    # absolute, where files land
        self.relativeRoot = manifestRelativeRoot        # e.g. "datasets"
        self.seed = seed

    def rng(self, scenarioId):
        """A per-scenario RNG, stable across processes and Python versions."""
        return random.Random(self.seed ^ zlib.crc32(scenarioId.encode("utf-8")))

    def directory(self, folder):
        path = os.path.join(self.outputRoot, folder)
        os.makedirs(os.path.join(path, "data"), exist_ok=True)
        os.makedirs(os.path.join(path, "expected"), exist_ok=True)
        return path

    def dataPath(self, folder, name):
        return os.path.join(self.outputRoot, folder, "data", name)

    def expectedPath(self, folder, name):
        return os.path.join(self.outputRoot, folder, "expected", name)

    def relative(self, absolutePath):
        """Absolute path -> the manifest's EXAMPLE_FILES_DIR-relative form."""
        relativeToRoot = os.path.relpath(absolutePath, self.outputRoot)
        return "/".join([self.relativeRoot] + relativeToRoot.split(os.sep))


def _pickTargets(context, scenarioId, count=DEFAULT_TARGET_PATHWAYS,
                 minCompounds=0):
    """Target pathways plus the features that will carry their signal.

    Targets come from the *peripheral* pathways -- those whose genes are mostly
    not also somebody else's -- and that restriction is the whole reason these
    fixtures discriminate. KEGG's hub pathways share so many genes that planting
    70% of one marks a large slice of a hundred others; the enrichment
    background is then the planted signal itself and 57% of pathways come back
    significant. See KeggSource.pathwayLeakage.

    `minCompounds` additionally demands that a target carry metabolites, for the
    scenario that plants a compound signal in the same pathways as the gene
    signal.
    """
    rng = context.rng(scenarioId)
    pool, leakageCap = context.kegg.peripheralPathways(
        count, minCompounds=minCompounds)
    if len(pool) < count:
        raise RuntimeError(
            "only %d pathways are both large enough and peripheral enough to "
            "plant a signal in; %d were requested. Is the species fully "
            "installed?" % (len(pool), count))
    targets = sorted(rng.sample(pool, count))
    signal = simulate.chooseSignalFeatures(rng, context.kegg.pathwayToGenes, targets)
    return rng, targets, sorted(signal), leakageCap


def _relevantFor(rng, features, signalSet):
    """(diffuseSet, relevantList) for one omic over its own feature universe.

    The relevant list an omic ships is the planted signal it actually measures,
    plus a scattering of features that are differential on their own. The
    scatter is drawn per omic, so the layers of a multi-omic scenario agree on
    the planted program and disagree on the noise -- which is what real
    multi-omic data looks like, and what stops the integration view from being
    trivially self-confirming.
    """
    diffuse = set(simulate.chooseDiffuseFeatures(rng, features, signalSet))
    relevant = sorted(feature for feature in features
                      if feature in signalSet or feature in diffuse)
    return diffuse, relevant


def _plantCompounds(context, rng, targets,
                    signalFraction=simulate.DEFAULT_SIGNAL_FRACTION):
    """The compound signal, planted in the same pathways as the gene signal.

    Mirrors simulate.chooseSignalFeatures, with one extra rule: a compound that
    belongs to many of this species' pathways is skipped, because planting it
    marks all of them. See MAX_COMPOUND_SHARING.
    """
    signal = set()
    for pathway in targets:
        members = context.kegg.compoundsIn([pathway])
        plantable = [compound for compound in members
                     if context.kegg.compoundLeakage(compound) <= MAX_COMPOUND_SHARING]
        if len(plantable) < MIN_PLANTABLE_COMPOUNDS:
            plantable = members
        if not plantable:
            continue
        count = max(1, int(round(len(plantable) * signalFraction)))
        signal.update(rng.sample(plantable, min(count, len(plantable))))
    return sorted(signal)


def _valuesRows(rng, features, signalSet, conditions, effectSize=None,
                noise=None, diffuseSet=frozenset()):
    """(featureID, [text, ...]) pairs, ready for writers.writeValues.

    Every cell is a finite number. See the note in simulate.py: the validator
    floats every value column, so there is no missing-value token an example
    could legitimately carry.

    A feature in `diffuseSet` moves too -- a relevant feature with a flat
    profile would be a contradiction the heatmap makes obvious -- but by less
    and with no shared direction, so the planted pathways stay the coherent
    block in the picture.
    """
    kwargs = {}
    if effectSize is not None:
        kwargs["effectSize"] = effectSize
    if noise is not None:
        kwargs["noise"] = noise

    diffuseKwargs = dict(kwargs)
    diffuseKwargs["effectSize"] = simulate.DIFFUSE_EFFECT_SIZE
    diffuseKwargs["downFraction"] = 0.5

    for feature in features:
        if feature in signalSet:
            raw = simulate.rampedRatios(rng, len(conditions), True, **kwargs)
        elif feature in diffuseSet:
            raw = simulate.rampedRatios(rng, len(conditions), True, **diffuseKwargs)
        else:
            raw = simulate.rampedRatios(rng, len(conditions), False, **kwargs)
        yield feature, [simulate.formatValue(value) for value in raw]


def _pathwayExpectations(context, folder, targets, signal, extra=None,
                         leakageCap=None, universe=None):
    """Write the ground-truth files and return the manifest's `expected` block.

    `targetCoverage` is written out because it is the invariant that makes the
    expected-pathways file honest: it is the share of each declared target's
    genes that actually carry the planted signal. A scenario that declares a
    pathway it planted nothing in is not a fixture with a weak signal, it is a
    fixture that lies -- and the number is here so a test can say so.

    `universe` is the set of features the scenario actually MEASURES, and it is
    the denominator whenever a scenario measures less than the whole gene space.
    That is the honest one: the hypergeometric's population is the submission,
    so what has to be dense in a target pathway is the planted share of the
    pathway's *submitted* members. Only MORE needs it -- it models a fixed
    number of genes -- and passing nothing keeps the whole-membership
    denominator every other scenario has always used.
    """
    pathwayFile = context.expectedPath(folder, "expected_pathways.txt")
    signalSet = set(signal)
    measured = set(universe) if universe is not None else None
    coverage = []
    rows = []
    for pathway in targets:
        members = context.kegg.pathwayToGenes.get(pathway, ())
        submitted = ([gene for gene in members if gene in measured]
                     if measured is not None else list(members))
        planted = sum(1 for gene in submitted if gene in signalSet)
        share = planted / float(len(submitted)) if submitted else 0.0
        coverage.append(round(share, 3))
        # The "(of N in the pathway)" tail appears only when the two
        # denominators differ, so the scenarios that measure everything keep the
        # line they have always written and a regeneration of them still diffs
        # empty.
        rows.append("%s\t%s\t%d/%d planted%s"
                    % (pathway, context.kegg.describe(pathway),
                       planted, len(submitted),
                       "" if measured is None
                       else " (of %d in the pathway)" % len(members)))
    writers.writeExpected(
        pathwayFile, rows,
        "Pathways carrying a planted signal; enrichment should rank these highly")

    featureFile = context.expectedPath(folder, "signal_features.txt")
    writers.writeExpected(featureFile, signal,
                          "Features given a coherent shift (the planted signal)")

    expected = {
        "pathwaysFile": context.relative(pathwayFile),
        "signalFeaturesFile": context.relative(featureFile),
        "targetPathways": len(targets),
        "signalFeatures": len(signal),
        "targetCoverage": coverage,
        "minTargetCoverage": min(coverage) if coverage else 0.0,
        "diffuseRelevantRate": simulate.DEFAULT_DIFFUSE_RATE,
    }
    if leakageCap is not None:
        expected["targetLeakageCap"] = leakageCap
    if extra:
        expected.update(extra)
    return expected


# ---------------------------------------------------------------------------
# 01 -- gene expression, one condition
# ---------------------------------------------------------------------------

def buildGeneSingleCondition(context):
    folder = "01-gene-single-condition"
    scenarioId = "gene-single-condition"
    context.directory(folder)

    rng, targets, signal, leakageCap = _pickTargets(context, scenarioId)
    conditions = ["Treated_vs_Control"]
    genes = context.kegg.allGenes()
    signalSet = set(signal)
    diffuse, relevant = _relevantFor(rng, genes, signalSet)

    valuesFile = writers.writeValues(
        context.dataPath(folder, "gene_expression_values.tab"),
        "geneID", conditions,
        _valuesRows(rng, genes, signalSet, conditions, diffuseSet=diffuse))

    relevantFile = writers.writeRelevantSingle(
        context.dataPath(folder, "gene_expression_relevant.tab"), relevant)

    return {
        "id": scenarioId,
        "title": "Gene expression — single condition",
        "summary": ("One condition and one relevant-features list: the smallest "
                    "input PaintOmics accepts, and the fastest way to see a "
                    "pathway light up."),
        "tests": ["Pathway enrichment", "Single-condition pathway colouring",
                  "Feature-to-KEGG identifier translation"],
        "pipeline": "pathway-acquisition",
        "organism": "mmu",
        "databases": ["KEGG"],
        "conditions": conditions,
        "simulated": True,
        "omics": [{
            "omicName": "Gene expression",
            "omicType": "gene",
            "enrichment": "genes",
            "dataFile": context.relative(valuesFile),
            "relevantFile": context.relative(relevantFile),
        }],
        "references": [],
        "expected": _pathwayExpectations(
            context, folder, targets, signal,
            {"relevantFeatures": len(relevant)}, leakageCap=leakageCap),
    }


# ---------------------------------------------------------------------------
# 02 -- gene expression, six conditions, one shared relevance list
# ---------------------------------------------------------------------------

def buildGeneMultiCondition(context):
    folder = "02-gene-multi-condition"
    scenarioId = "gene-multi-condition"
    context.directory(folder)

    rng, targets, signal, leakageCap = _pickTargets(context, scenarioId)
    genes = context.kegg.allGenes()
    signalSet = set(signal)
    diffuse, relevant = _relevantFor(rng, genes, signalSet)

    valuesFile = writers.writeValues(
        context.dataPath(folder, "gene_expression_values.tab"),
        "geneID", TIME_COURSE,
        _valuesRows(rng, genes, signalSet, TIME_COURSE, diffuseSet=diffuse))

    relevantFile = writers.writeRelevantSingle(
        context.dataPath(folder, "gene_expression_relevant.tab"), relevant)

    return {
        "id": scenarioId,
        "title": "Gene expression — six conditions",
        "summary": ("A six-point time course with one relevance list shared by "
                    "every condition — the ordinary shape of a time-course "
                    "submission, and the closest simulated counterpart to the "
                    "real STATegra example."),
        "tests": ["Multi-condition heatmaps", "Per-condition pathway colouring",
                  "Stouffer combination across conditions"],
        "pipeline": "pathway-acquisition",
        "organism": "mmu",
        "databases": ["KEGG", "Reactome"],
        "conditions": TIME_COURSE,
        "simulated": True,
        "supersededBy": "stategra-multiomics",
        "omics": [{
            "omicName": "Gene expression",
            "omicType": "gene",
            "enrichment": "genes",
            "dataFile": context.relative(valuesFile),
            "relevantFile": context.relative(relevantFile),
        }],
        "references": [],
        "expected": _pathwayExpectations(
            context, folder, targets, signal,
            {"relevantFeatures": len(relevant)}, leakageCap=leakageCap),
    }


# ---------------------------------------------------------------------------
# 03 -- six conditions with PER-CONDITION relevance
# ---------------------------------------------------------------------------

def buildGenePerConditionRelevance(context):
    """The case no bundled example reaches today.

    Job.parseSignificativeFeaturesFile carries a multi-column branch that gives
    each feature one relevance flag per condition, feeding per-condition
    p-values. Every file that ships is single-column, so that branch -- and the
    80-character-per-field rule that had to be fixed for it to be satisfiable at
    all (see test_multicondition_validation.py) -- has never been reachable from
    example mode.
    """
    folder = "03-gene-multi-condition-relevance"
    scenarioId = "gene-multi-condition-relevance"
    context.directory(folder)

    rng, targets, signal, leakageCap = _pickTargets(context, scenarioId)
    genes = context.kegg.allGenes()
    signalSet = set(signal)
    diffuse, relevant = _relevantFor(rng, genes, signalSet)

    valuesFile = writers.writeValues(
        context.dataPath(folder, "gene_expression_values.tab"),
        "geneID", TIME_COURSE,
        _valuesRows(rng, genes, signalSet, TIME_COURSE, diffuseSet=diffuse))

    # Relevance grows over the time course, mirroring the ramped effect size: a
    # feature crosses significance at the point its shift becomes detectable.
    # Written this way the columns have genuinely different lengths, which is
    # what forces the padding path in writeRelevantPerCondition.
    #
    # Sampled from the whole relevant set, not from the planted signal alone:
    # the diffusely-relevant features have to appear in the per-condition
    # columns too, or this scenario's enrichment background would be the planted
    # signal by itself while every other scenario's is not.
    perCondition = []
    for index in range(len(TIME_COURSE)):
        share = 0.30 + 0.70 * index / (len(TIME_COURSE) - 1)
        count = max(1, int(round(len(relevant) * share)))
        perCondition.append(rng.sample(relevant, min(count, len(relevant))))

    relevantFile = writers.writeRelevantPerCondition(
        context.dataPath(folder, "gene_expression_relevant.tab"),
        TIME_COURSE, perCondition)

    return {
        "id": scenarioId,
        "title": "Gene expression — per-condition relevance",
        "summary": ("Six conditions with a relevant-features file holding one "
                    "column per condition, so significance is tracked "
                    "separately at each time point rather than shared."),
        "tests": ["Per-condition relevant features",
                  "Per-condition p-values and FDR",
                  "Relevant-features files wider than 80 characters"],
        "pipeline": "pathway-acquisition",
        "organism": "mmu",
        "databases": ["KEGG"],
        "conditions": TIME_COURSE,
        "simulated": True,
        "omics": [{
            "omicName": "Gene expression",
            "omicType": "gene",
            "enrichment": "genes",
            "dataFile": context.relative(valuesFile),
            "relevantFile": context.relative(relevantFile),
        }],
        "references": [],
        "expected": _pathwayExpectations(
            context, folder, targets, signal,
            {"relevantPerCondition": [len(column) for column in perCondition],
             "relevantFeatures": len(relevant)},
            leakageCap=leakageCap),
    }


# ---------------------------------------------------------------------------
# 04 -- five omics over the same six conditions
# ---------------------------------------------------------------------------

def buildMultiomics(context):
    folder = "04-multiomics-integration"
    scenarioId = "multiomics-integration"
    context.directory(folder)

    # minCompounds: this is the one scenario whose targets have to carry a
    # compound signal as well as a gene signal, and roughly two thirds of the
    # peripheral pathways hold no metabolites at all. Demanding them up front is
    # what lets the two layers name the same pathways; picking targets on genes
    # alone and hoping they have compounds is what left six of eight targets
    # with a metabolomics p-value of exactly 1.0.
    rng, targets, signal, leakageCap = _pickTargets(
        context, scenarioId, minCompounds=MIN_TARGET_COMPOUNDS)
    signalSet = set(signal)
    genes = context.kegg.allGenes()

    omics = []

    # -- transcriptomics: the full gene universe -------------------------
    geneEntry, relevant = _geneOmic(
        context, folder, rng, "Gene expression", "gene_expression",
        genes, signalSet, TIME_COURSE)
    omics.append(geneEntry)

    # -- proteomics: a subset, noisier, weaker effect ---------------------
    # Protein abundance tracks transcript abundance loosely, so the same signal
    # genes move but by less and with more scatter. A perfect copy of the
    # transcriptomics layer would make multi-omic integration look better than
    # it is.
    proteinGenes = sorted(rng.sample(genes, min(3000, len(genes))))
    omics.append(_geneOmic(
        context, folder, rng, "Proteomics", "proteomics",
        proteinGenes, signalSet, TIME_COURSE,
        effectSize=simulate.DEFAULT_EFFECT_SIZE * 0.8,
        noise=simulate.DEFAULT_NOISE * 1.2)[0])

    # -- transcription factors -------------------------------------------
    factorGenes = sorted(rng.sample(genes, min(1200, len(genes))))
    omics.append(_geneOmic(
        context, folder, rng, "Transcription factor", "transcription_factor",
        factorGenes, signalSet, TIME_COURSE,
        effectSize=simulate.DEFAULT_EFFECT_SIZE * 0.6)[0])

    # -- metabolomics, keyed by KEGG compound ID --------------------------
    # The compound signal is planted in the SAME target pathways as the gene
    # signal, which is the claim this scenario's summary makes and the reason
    # its manifest lists "Gene- and compound-based enrichment side by side".
    compounds = context.kegg.allCompounds()
    signalCompounds = _plantCompounds(context, rng, targets)
    diffuseCompounds, relevantCompounds = _relevantFor(
        rng, compounds, set(signalCompounds))
    compoundValues = writers.writeValues(
        context.dataPath(folder, "metabolomics_values.tab"),
        "compound", TIME_COURSE,
        _valuesRows(rng, compounds, set(signalCompounds), TIME_COURSE,
                    diffuseSet=diffuseCompounds))
    compoundRelevant = writers.writeRelevantSingle(
        context.dataPath(folder, "metabolomics_relevant.tab"), relevantCompounds)
    omics.append({
        "omicName": "Metabolomics",
        "omicType": "compound",
        "enrichment": "features",
        "dataFile": context.relative(compoundValues),
        "relevantFile": context.relative(compoundRelevant),
    })

    # -- miRNA, already mapped to its targets -----------------------------
    # PA step 1 takes miRNA rows keyed GENE:::MIRNA -- the shape MiRNA2Genes
    # emits. Scenario 05 produces that mapping itself; here it is pre-mapped so
    # the integration view can be reached without running the extra pipeline.
    mirnaPairs = []
    mirnaTargets = sorted(rng.sample(genes, min(900, len(genes))))
    for index, gene in enumerate(mirnaTargets):
        mirnaPairs.append((gene, "mmu-miR-%d-5p" % (100 + index % 400)))
    diffuseMirnaGenes = set(simulate.chooseDiffuseFeatures(
        rng, mirnaTargets, signalSet))
    pairRows = []
    relevantPairs = []
    for gene, mirna in mirnaPairs:
        key = "%s:::%s" % (gene, mirna)
        isSignal = gene in signalSet
        isDiffuse = gene in diffuseMirnaGenes
        # A repressor: when its target is up, the miRNA is down.
        values = simulate.rampedRatios(
            rng, len(TIME_COURSE), isSignal or isDiffuse,
            effectSize=(simulate.DEFAULT_EFFECT_SIZE * 0.7 if isSignal
                        else simulate.DIFFUSE_EFFECT_SIZE))
        if isSignal or isDiffuse:
            values = [-value for value in values]
            relevantPairs.append(key)
        pairRows.append((key, [simulate.formatValue(v) for v in values]))

    mirnaValues = writers.writeValues(
        context.dataPath(folder, "mirna_values.tab"),
        "geneID:::miRNA", TIME_COURSE, pairRows)
    mirnaRelevant = writers.writeRelevantSingle(
        context.dataPath(folder, "mirna_relevant.tab"), relevantPairs)
    omics.append({
        "omicName": "miRNA-seq",
        "omicType": "gene",
        "enrichment": "genes",
        "dataFile": context.relative(mirnaValues),
        "relevantFile": context.relative(mirnaRelevant),
    })

    # -- a name-keyed metabolomics variant, shipped but not wired in ------
    # Compound *names* go through the matched-metabolites selection step, where
    # one name can resolve to several KEGG compounds. Keyed by ID that step is
    # skipped entirely, so the alternative file ships alongside for anyone
    # testing the matcher; the manifest lists it under `extraFiles` rather than
    # `omics` because loading both at once would double-count the metabolites.
    #
    # The names are REAL KEGG names, read from the same compounds_all.list that
    # `common_build_database.py` loads into `kegg_compounds`. The previous
    # version invented them -- "Compound 00001" through "Compound 00400" -- and
    # a user who followed the note in the manifest got mapped=0, unmapped=400,
    # no compound panel and no hub analysis: the file exercised the matching
    # step only in the sense that the matching step rejected all of it.
    #
    # A slice of the planted signal comes first so the same metabolites move
    # here as in the ID-keyed file, but only up to a third of the rows: a panel
    # in which everything moves is not a panel, and the rest is filled in
    # compound-ID order so the file is stable across runs.
    signalCompoundSet = set(signalCompounds)
    signalHead = context.kegg.namedCompounds(
        signalCompounds)[:BY_NAME_COMPOUNDS // 3]
    taken = {compound for compound, _name in signalHead}
    filler = [pair for pair in context.kegg.namedCompounds(compounds)
              if pair[0] not in taken
              and pair[1].lower() not in {name.lower()
                                          for _c, name in signalHead}]
    namedPairs = (signalHead + filler)[:BY_NAME_COMPOUNDS]
    nameRows = []
    for compound, name in sorted(namedPairs, key=lambda pair: pair[0]):
        isSignal = compound in signalCompoundSet
        isDiffuse = compound in diffuseCompounds
        nameRows.append((name, [
            simulate.formatValue(value) for value in simulate.rampedRatios(
                rng, len(TIME_COURSE), isSignal or isDiffuse,
                effectSize=(simulate.DEFAULT_EFFECT_SIZE if isSignal
                            else simulate.DIFFUSE_EFFECT_SIZE))]))
    nameFile = writers.writeValues(
        context.dataPath(folder, "metabolomics_by_name_values.tab"),
        "compound", TIME_COURSE, nameRows)

    # Its own relevance list, keyed the same way. Relevance is matched against
    # the identifier as submitted, so metabolomics_relevant.tab -- a list of
    # KEGG ids -- matches nothing in a file whose rows are named "Water".
    # Measured with the by-name file against the ID-keyed relevance list: 400
    # compounds mapped and 0 of them relevant, which is a compound panel with
    # no enrichment behind it.
    relevantNameSet = set(relevantCompounds)
    nameRelevantFile = writers.writeRelevantSingle(
        context.dataPath(folder, "metabolomics_by_name_relevant.tab"),
        [name for compound, name in sorted(namedPairs, key=lambda pair: pair[0])
         if compound in relevantNameSet])

    return {
        "id": scenarioId,
        "title": "Multi-omic integration — five omics",
        "summary": ("Transcriptomics, proteomics, transcription factors, "
                    "metabolomics and miRNA over the same six time points, "
                    "sharing one planted signal so the layers agree."),
        "tests": ["Multi-omic pathway enrichment", "Compound matching",
                  "Metabolite hub analysis", "Pathway network",
                  "Gene- and compound-based enrichment side by side"],
        "pipeline": "pathway-acquisition",
        "organism": "mmu",
        "databases": ["KEGG", "Reactome"],
        "conditions": TIME_COURSE,
        "simulated": True,
        "supersededBy": "stategra-multiomics",
        "omics": omics,
        "references": [],
        "extraFiles": [{
            "role": "compound-name-keyed metabolomics",
            "note": ("Alternative to metabolomics_values.tab, keyed by real "
                     "KEGG compound name instead of KEGG ID, to exercise the "
                     "matched-metabolites selection step. Load it *instead of* "
                     "the ID-keyed file, never alongside."),
            "path": context.relative(nameFile),
            "rows": len(nameRows),
        }, {
            "role": "compound-name-keyed relevant features",
            "note": ("The relevance list for metabolomics_by_name_values.tab. "
                     "Relevance is keyed by the identifier as submitted, so "
                     "the ID-keyed metabolomics_relevant.tab matches nothing "
                     "in a name-keyed values file."),
            "path": context.relative(nameRelevantFile),
        }],
        "expected": _pathwayExpectations(
            context, folder, targets, signal,
            {"signalCompounds": len(signalCompounds),
             "relevantCompounds": len(relevantCompounds),
             "compoundUniverse": len(compounds),
             "compoundTargetCoverage": [
                 round(len(signalCompoundSet
                           & set(context.kegg.compoundsIn([pathway])))
                       / float(len(context.kegg.compoundsIn([pathway]))), 3)
                 for pathway in targets],
             "namedCompounds": len(nameRows),
             "relevantFeatures": len(relevant),
             "omicCount": len(omics)},
            leakageCap=leakageCap),
    }


def _geneOmic(context, folder, rng, omicName, stem, features, signalSet,
              conditions, effectSize=None, noise=None):
    """Write a gene-based omic's two files.

    Returns `(manifestEntry, relevantFeatures)`; the caller needs the list as
    well as the entry because how many features an omic called relevant is what
    the enrichment background is made of, and the manifest records it.
    """
    diffuse, relevant = _relevantFor(rng, features, signalSet)
    valuesFile = writers.writeValues(
        context.dataPath(folder, stem + "_values.tab"),
        "geneID", conditions,
        _valuesRows(rng, features, signalSet, conditions,
                    effectSize=effectSize, noise=noise, diffuseSet=diffuse))
    relevantFile = writers.writeRelevantSingle(
        context.dataPath(folder, stem + "_relevant.tab"), relevant)
    return {
        "omicName": omicName,
        "omicType": "gene",
        "enrichment": "genes",
        "dataFile": context.relative(valuesFile),
        "relevantFile": context.relative(relevantFile),
    }, relevant


# ---------------------------------------------------------------------------
# 05 -- regulatory omics, the classic miRNA -> gene route
# ---------------------------------------------------------------------------

def buildRegulatoryMirna(context):
    """Inputs for /dm_fromMiRNAtoGenes, which produces GENE:::miRNA values.

    The bundled reference for this route is `mmu_mirBase_to_ensembl.tab` at
    31 MB, which no test can reasonably read. This writes the same three-column
    shape at a size that fits in a fixture, over real gene IDs.
    """
    folder = "05-regulatory-mirna"
    scenarioId = "regulatory-mirna"
    context.directory(folder)

    rng, targets, signal, leakageCap = _pickTargets(context, scenarioId, count=6)
    signalSet = set(signal)
    genes = context.kegg.allGenes()

    # Each miRNA gets a handful of predicted targets, which is what a
    # prediction table looks like: one miRNA to many genes, many-to-many overall.
    mirnas = ["mmu-miR-%d-%s" % (100 + index // 2, "5p" if index % 2 else "3p")
              for index in range(300)]
    # The prediction table has to cover the planted genes, or the declared
    # target pathways cannot be recovered from it. Sampling the pool out of the
    # whole gene universe left roughly a quarter of each target's planted genes
    # in the file, and the smallest target then ranked 272nd of 360 -- a
    # declared expectation the data could not meet.
    targetPool = sorted(signalSet | set(rng.sample(
        [gene for gene in genes if gene not in signalSet],
        max(0, min(2500 - len(signalSet), len(genes) - len(signalSet))))))
    associations = []
    mirnaToTargets = {}
    for mirna in mirnas:
        picked = rng.sample(targetPool, rng.randint(4, 12))
        mirnaToTargets[mirna] = sorted(picked)
        for gene in sorted(picked):
            associations.append((mirna, gene, round(rng.uniform(1.5, 8.0), 2)))

    referenceFile = writers.writeMirnaAssociations(
        context.dataPath(folder, "mirna_to_gene_associations.tab"), associations)

    # A miRNA is "relevant" when it represses a gene carrying the signal.
    relevantMirnas = sorted(
        mirna for mirna, geneList in mirnaToTargets.items()
        if any(gene in signalSet for gene in geneList))

    mirnaRows = []
    for mirna in mirnas:
        isSignal = mirna in set(relevantMirnas)
        values = simulate.rampedRatios(rng, len(TIME_COURSE), isSignal,
                                       effectSize=simulate.DEFAULT_EFFECT_SIZE * 0.8)
        if isSignal:
            values = [-value for value in values]      # repressor
        mirnaRows.append((mirna, [simulate.formatValue(v) for v in values]))

    mirnaValues = writers.writeValues(
        context.dataPath(folder, "mirna_values.tab"),
        "miRNA", TIME_COURSE, mirnaRows)
    mirnaRelevant = writers.writeRelevantSingle(
        context.dataPath(folder, "mirna_relevant.tab"), relevantMirnas)

    diffuseGenes, relevantGenes = _relevantFor(rng, targetPool, signalSet)
    geneValues = writers.writeValues(
        context.dataPath(folder, "gene_expression_values.tab"),
        "geneID", TIME_COURSE,
        _valuesRows(rng, targetPool, signalSet, TIME_COURSE,
                    diffuseSet=diffuseGenes))
    geneRelevant = writers.writeRelevantSingle(
        context.dataPath(folder, "gene_expression_relevant.tab"), relevantGenes)

    return {
        "id": scenarioId,
        "title": "Regulatory omics — miRNA to genes",
        "summary": ("miRNA quantification plus a target-prediction table. The "
                    "Regulatory Omics step pairs each miRNA with its targets "
                    "and hands GENE:::miRNA rows on to the pathway analysis."),
        "tests": ["miRNA-to-gene association", "Regulator/target pairing",
                  "Correlation filtering of predicted targets"],
        "pipeline": "mirna2genes",
        "organism": "mmu",
        "databases": ["KEGG"],
        "conditions": TIME_COURSE,
        "simulated": True,
        "supersededBy": "stategra-mirna",
        "omics": [
            {
                "omicName": "miRNA-seq",
                "omicType": "gene",
                "enrichment": "genes",
                "role": "regulator",
                "dataFile": context.relative(mirnaValues),
                "relevantFile": context.relative(mirnaRelevant),
            },
            {
                "omicName": "Gene expression",
                "omicType": "gene",
                "enrichment": "genes",
                "role": "target",
                "dataFile": context.relative(geneValues),
                "relevantFile": context.relative(geneRelevant),
            },
        ],
        "references": [{
            "omicName": "miRNA-seq",
            "fileType": "Reference file",
            "dataFile": context.relative(referenceFile),
        }],
        "expected": _pathwayExpectations(
            context, folder, targets, signal,
            {"miRNAs": len(mirnas), "relevantMiRNAs": len(relevantMirnas),
             "associations": len(associations),
             "relevantFeatures": len(relevantGenes)},
            leakageCap=leakageCap),
    }


# ---------------------------------------------------------------------------
# 06 -- regulatory omics through MORE
# ---------------------------------------------------------------------------

# MORE fits one model per target gene, measured at ~0.29 s/gene. 250 targets is
# about 75 seconds -- slow enough to be a real run, fast enough that a user who
# clicked "load example" does not think it hung.
MORE_TARGETS = 250
MORE_REGULATORS = 40

# How many of the MORE_TARGETS modelled genes are members of a declared target
# pathway. The remaining MORE_TARGETS - MORE_IN_PATHWAY_GENES are background:
# genes in none of them.
#
# This number is the whole scenario, and it has been wrong twice in opposite
# directions.
#
#   * Originally the modelled genes were a random draw from the 10406-gene mouse
#     universe, so the declared targets held 0, 0, 1 and 2 of them: the
#     ground-truth file claimed pathways the data could not produce, and one
#     full run gave 0 significant of 289 matched.
#   * The correction confined EVERY modelled gene to the declared targets. Per
#     target coverage reached 1.00 and the contrast vanished with it: with the
#     background made entirely of the signal, 90.4% of modelled genes were
#     flagged relevant, only 96 pathways were matched at all, and one full run
#     gave 1 significant of 96 -- mmu01100, not a declared target, with the
#     declared ones at Fisher p 0.109 to 0.976 (two of them ranked 38th and
#     39th of 96).
#
# A hypergeometric test needs both halves. 80 in-pathway genes carry the planted
# program (56 of them, the ones chooseSignalFeatures planted in) and 170
# background genes give the test something to contrast it against. Measured by
# a full run -- real runMORE.R, then PathwayAcquisitionJob -- of the files this
# produces: 283 of 364 KEGG pathways matched, 15 significant (5.3%, inside the
# 0.8-12% band the real STATegra job occupies), and all eight declared targets
# significant at ranks 1, 2, 3, 7, 8, 9, 11 and 13, worst Fisher p 0.024.
# Offline, raising this to 100 pushed the weakest target to rank 15 at p 0.047
# and lowering it to 70 left one at p 0.016, so 80 is a maximum, not a floor.
MORE_IN_PATHWAY_GENES = 80

# Candidate regulators proposed per target per omic. Two of the three are
# decoys, so "which regulator explains this target" has a wrong answer available.
MORE_CANDIDATES = 3

# Four replicates, not three. Every regulator's profile lives in a space with
# one dimension per GROUP, so with three groups any two candidates are similar
# by chance often enough that PLS cannot separate them -- measured recall of the
# planted pairs was 48%. Replicates add the sample-level degrees of freedom that
# make a driver distinguishable from its decoys. Cost is linear in targets, not
# samples, so this is nearly free.
MORE_REPLICATES = 3

# Independent per-sample variation for regulators, well above the 0.35 used for
# ratio data. This is what gives each regulator a distinctive fingerprint: a
# target built from a driver inherits that driver's exact per-sample deviations,
# which no decoy shares. With the group effect dominant instead, every responder
# in a group looked alike and the choice among them was close to arbitrary.
MORE_REGULATOR_NOISE = 1.5

# The group effect stays LARGE, and that is not a free choice. MORE's
# `minVariation` filter (the "NA" sentinel) drops any regulator whose
# variability *across conditions* falls under 10% of the maximum observed. An
# earlier attempt raised the per-sample noise to 2.0 and dropped this to 1.0 to
# decorrelate the candidates; it decorrelated them and then filtered the true
# drivers out, because their across-condition variability had become small.
# Recall went 63% -> 48% -> 66% across those attempts. Both terms have to be
# big: the group effect to survive the filter, the per-sample noise to make the
# driver identifiable.
MORE_GROUP_EFFECT = 2.5
MORE_GROUPS = ["Control", "Early", "Mid", "Late"]

# (display name, regulator-name prefix, filename stem). Order matters: targets
# are assigned a driving omic by position, alternating through this list.
MORE_OMICS = [
    ("Transcription factor", "TF", "transcription_factor"),
    ("miRNA-seq", "mmu-miR", "mirna"),
]


def buildRegulatoryMore(context):
    """Per-sample matrices, a design matrix and association files for MORE.

    Unlike every other scenario here, MORE does not take log ratios: it
    regresses each target on its candidate regulators sample by sample, so it
    needs replicate structure that a per-condition ratio matrix has thrown away.

    Targets are simulated as noisy linear functions of one regulator each
    (simulate.drivenExpression), so the regulator-target pairs MORE is supposed
    to recover are known and written to expected/. Without that, a MORE run that
    finds nothing is indistinguishable from one that works.
    """
    folder = "06-regulatory-more"
    scenarioId = "regulatory-more"
    context.directory(folder)

    rng, targets, signal, leakageCap = _pickTargets(context, scenarioId, count=8)

    # The modelled set has two halves, and needs both. See
    # MORE_IN_PATHWAY_GENES: a set drawn entirely from the target pathways has
    # no background to be enriched against, and a set drawn entirely at random
    # from the mouse universe puts almost nothing in the pathways the scenario
    # declares. So: a sample of the targets' members, of which the ones
    # `_pickTargets` already planted in carry the signal, plus background genes
    # taken from OUTSIDE every declared target -- outside, not merely
    # not-planted, so a background gene cannot quietly reinforce a target.
    pathwayGenes = set(context.kegg.genesIn(targets))
    inPathway = sorted(rng.sample(sorted(pathwayGenes),
                                  min(MORE_IN_PATHWAY_GENES, len(pathwayGenes))))
    outside = [gene for gene in context.kegg.allGenes()
               if gene not in pathwayGenes]
    background = sorted(rng.sample(
        outside, min(MORE_TARGETS - len(inPathway), len(outside))))

    targetGenes = sorted(set(inPathway) | set(background))
    # The planted signal is what survives BOTH filters: a gene the target
    # pathways' planting chose and that this scenario actually models. Writing
    # the unrestricted set to expected/ would claim a signal in genes no MORE
    # model ever sees.
    signalSet = set(signal) & set(inPathway)

    groupSizes = [MORE_REPLICATES] * len(MORE_GROUPS)
    sampleNames = []
    sampleGroups = []
    for group in MORE_GROUPS:
        for replicate in range(1, MORE_REPLICATES + 1):
            sampleNames.append("%s_R%d" % (group, replicate))
            sampleGroups.append(group)

    designFile = writers.writeDesign(
        context.dataPath(folder, "experimental_design.tab"),
        sampleNames, MORE_GROUPS, sampleGroups)

    regulatoryOmics = []
    expectedEdges = []
    driverOf = {}

    for omicIndex, (omicName, prefix, stem) in enumerate(MORE_OMICS):
        names = (["%s%03d" % (prefix, index) for index in range(MORE_REGULATORS)]
                 if prefix == "TF" else
                 ["%s-%d-5p" % (prefix, 200 + index) for index in range(MORE_REGULATORS)])

        regulatorValues = {}
        rows = []
        for index, name in enumerate(names):
            # Half the regulators respond to the perturbation; the rest are
            # flat. A regulator with no variance across groups explains nothing,
            # which is what MORE's minVariation filter exists to drop.
            #
            # Each responder gets its OWN group profile rather than a shared
            # ramp, so a target's true driver is distinguishable from its
            # decoys. See simulate.groupProfile for what the shared version
            # cost: 63% recovery of the planted pairs against a 52% chance
            # baseline.
            profile = simulate.groupProfile(rng, len(MORE_GROUPS),
                                            isSignal=(index % 2 == 0),
                                            effectSize=MORE_GROUP_EFFECT)
            values = simulate.perSampleExpression(
                rng, groupSizes, profile, noise=MORE_REGULATOR_NOISE)
            regulatorValues[name] = values
            rows.append((name, [simulate.formatValue(v) for v in values]))

        dataFile = writers.writeMatrix(
            context.dataPath(folder, stem + "_regulators.tab"),
            "RegulatorID", sampleNames, rows)

        # Three disjoint pools, because red stars in a MORE job are not written
        # by this generator: MOREServlet expands the user's
        # "significant regulators" file to every GENE:::REGULATOR pair in the
        # ASSOCIATION file, so the only levers on which genes come back relevant
        # are (a) which regulators the file flags and (b) which genes each
        # flagged regulator is associated with.
        #
        # Flagging every responder and drawing candidates uniformly -- what this
        # did before -- gave each gene a 1 - (1/2)^3 = 87.5% chance of a flagged
        # candidate, and 225 of 249 modelled genes (90.4%) came back relevant.
        # No dataset shape survives that: it is the relevance rate itself, not
        # the gene set, that leaves the hypergeometric nothing to contrast.
        #
        # So: `flagged` are the regulators a user's own differential test would
        # have returned, and they are wired to the planted program. A background
        # gene is associated only with regulators that test did not return, and
        # is starred only if the per-omic diffuse draw picks it -- the same 5%
        # scatter every other scenario ships. `unflaggedResponders` exists so a
        # background gene still has a regulator with real across-condition
        # variability, which minVariation would otherwise filter away along with
        # the gene's whole model.
        flagged = [name for index, name in enumerate(names) if index % 4 == 0]
        unflaggedResponders = [name for index, name in enumerate(names)
                               if index % 4 == 2]
        flat = [name for index, name in enumerate(names) if index % 2 == 1]
        unflagged = sorted(unflaggedResponders + flat)
        flaggedSet, responderSet = set(flagged), set(flagged + unflaggedResponders)

        # Relevance scattered over the genes the program did NOT touch, drawn
        # per omic so the two omics agree on the planted program and disagree on
        # the noise. See _relevantFor, which does the same for the ratio omics.
        diffuse = set(simulate.chooseDiffuseFeatures(rng, targetGenes, signalSet))

        # Each target is driven by exactly ONE regulator, in ONE omic. The
        # omics alternate, so roughly half the targets are TF-driven and half
        # miRNA-driven; the non-driving omic still proposes three candidates for
        # every target, none of which explain it.
        #
        # Previously every target was driven by one regulator from *each* omic
        # and the two contributions were averaged. That halved each driver's
        # share of the target's variance while adding the other's as noise, and
        # it left no target for which the correct answer was "this omic
        # regulates nothing here" -- so the scenario could not show a true
        # negative either.
        pairs = []
        for position, gene in enumerate(targetGenes):
            drivenByThisOmic = (position % len(MORE_OMICS)) == omicIndex
            wantsStar = gene in signalSet or gene in diffuse
            slot = position // len(MORE_OMICS)

            candidates = set()
            if drivenByThisOmic:
                # A planted gene is driven by a regulator the user flagged --
                # that is what "this program is under regulatory control" means
                # here, and it is what earns the gene its red star. Background
                # genes are driven by regulators the user did not flag, half of
                # them flat, so minVariation and the true-negative case are both
                # still exercised.
                if gene in signalSet:
                    driver = flagged[slot % len(flagged)]
                elif slot % 2 == 0:
                    driver = unflaggedResponders[(slot // 2) % len(unflaggedResponders)]
                else:
                    driver = flat[(slot // 2) % len(flat)]
                driverOf[gene] = (omicName, driver)
                expectedEdges.append((gene, omicName, driver))
                candidates.add(driver)

            if wantsStar and not candidates & flaggedSet:
                candidates.add(flagged[rng.randrange(len(flagged))])
            if not candidates & responderSet:
                candidates.add(
                    unflaggedResponders[rng.randrange(len(unflaggedResponders))])
            while len(candidates) < MORE_CANDIDATES:
                candidates.add(unflagged[rng.randrange(len(unflagged))])
            for candidate in sorted(candidates):
                pairs.append((gene, candidate))

        associationFile = writers.writeAssociations(
            context.dataPath(folder, stem + "_associations.tab"),
            pairs, header=("Target", "Regulator"))

        relevantFile = writers.writeIdList(
            context.dataPath(folder, stem + "_relevant_regulators.tab"),
            flagged)

        regulatoryOmics.append({
            "omicName": omicName,
            "omicType": "regulator",
            "dataFile": context.relative(dataFile),
            "associationsFile": context.relative(associationFile),
            "relevantFile": context.relative(relevantFile),
            "minVariation": "NA",
            "_regulatorValues": regulatorValues,     # stripped below
        })

    # Targets are built from their driver, so the association MORE is supposed
    # to find is genuinely in the data rather than merely asserted.
    targetRows = []
    for gene in targetGenes:
        omicName, driver = driverOf[gene]
        source = next(omic["_regulatorValues"][driver]
                      for omic in regulatoryOmics
                      if omic["omicName"] == omicName)
        values = simulate.drivenExpression(
            rng, source, slope=1.4, intercept=1.0, noise=0.25)
        targetRows.append((gene, [simulate.formatValue(v) for v in values]))

    targetFile = writers.writeMatrix(
        context.dataPath(folder, "gene_expression_targets.tab"),
        "GeneID", sampleNames, targetRows)

    for omic in regulatoryOmics:
        del omic["_regulatorValues"]

    edgesFile = writers.writeExpected(
        context.expectedPath(folder, "expected_regulator_pairs.txt"),
        ["%s\t%s\t%s" % edge for edge in expectedEdges],
        "target<TAB>omic<TAB>driving regulator -- MORE should recover these")

    return {
        "id": scenarioId,
        "title": "Regulatory omics — MORE joint model",
        "summary": ("Per-sample expression with three replicates per group, an "
                    "experimental design matrix, and two candidate regulatory "
                    "omics with association files. Each target is a noisy "
                    "linear function of one known regulator, so what MORE "
                    "should find is written down."),
        "tests": ["MORE PLS1 and MLR models", "Experimental design parsing",
                  "Per-omic minVariation filter", "Regulator significance (VIP, alpha, R2)",
                  "GENE:::REGULATOR hand-off to pathway analysis"],
        "pipeline": "more",
        "organism": "mmu",
        "databases": ["KEGG"],
        "conditions": MORE_GROUPS,
        "simulated": True,
        "supersededBy": "stategra-more",
        "samples": sampleNames,
        "target": {
            "omicName": "Gene expression",
            "dataFile": context.relative(targetFile),
        },
        "design": {"dataFile": context.relative(designFile)},
        "omics": regulatoryOmics,
        "references": [],
        "parameters": {"method": "PLS1", "alpha": 0.05, "vip": 0.8,
                       "filter_r2": 0.0, "enrichment": "genes"},
        "expected": _pathwayExpectations(
            context, folder, targets, sorted(signalSet),
            {"regulatorPairsFile": context.relative(edgesFile),
             "regulatorPairs": len(expectedEdges),
             # Measured by one full run of the real runMORE.R against THESE
             # files (PLS1, alpha 0.05, VIP 0.8, minVariation NA, 78.8 s):
             # 220 of 250 planted driver pairs recovered. Selecting the same
             # number of pairs at random from the 1500 candidates would recover
             # ~58%, so this is a real signal rather than an artefact of how
             # many pairs MORE reports.
             #
             # A test asserts the floor (>= 0.7), never this number: MORE's
             # model selection is not bit-stable across versions, and the recall
             # splits sharply by driver -- 55/56 for the flagged responders that
             # drive the planted program, 101/101 for the unflagged responders,
             # 64/93 for the flat drivers, where only the variation minVariation
             # is there to filter separates a driver from its decoys.
             "measuredRecall": 0.880,
             "recallFloor": 0.70,
             "modelledTargets": len(targetGenes),
             "inPathwayGenes": len(inPathway),
             "backgroundGenes": len(background),
             "flaggedRegulatorsPerOmic": MORE_REGULATORS // 4,
             "estimatedRuntimeSeconds": int(len(targetGenes) * 0.29)},
            leakageCap=leakageCap, universe=targetGenes),
    }


# ---------------------------------------------------------------------------
# 07 -- region-based omic with its own genome annotation
# ---------------------------------------------------------------------------

REGION_CHROMOSOMES = ["1", "2", "3", "4", "5"]

# How many genes the synthetic annotation carries, and therefore how large the
# enrichment background is once the regions have been assigned to genes.
#
# 900 was too few. Half of them were signal genes by construction, so 31% of the
# background was relevant and one 247-gene pathway held 174 of the 278 relevant
# genes -- a background made mostly of the signal, which is the same defect as
# planting in hub pathways, arriving by a different route. At 2400 the planted
# genes are ~10% of the annotation, which is what a real accessibility
# experiment over an annotated genome looks like.
REGION_GENE_COUNT = 2400
GENE_SPACING = 120000          # bp between synthetic gene starts
GENE_LENGTH = 30000


def buildRegionBased(context):
    """A BED-like omic plus the GTF it needs, both synthetic and consistent.

    `examplefiles/GTF/` ships only a zero-byte `.dummy`; the real mouse GTF is
    fetched by a manual deploy step, so the bundled region example cannot run on
    a fresh checkout at all. This scenario carries its own annotation instead:
    synthetic coordinates, but real Ensembl gene IDs, so regions map to genes
    and those genes map to KEGG pathways.

    Coordinate conventions are deliberately different between the two files --
    GTF is 1-based inclusive, the region file is 0-based half-open, as BED is --
    because collapsing them to one convention would hide exactly the off-by-one
    that region-to-gene assignment gets wrong.
    """
    folder = "07-region-based"
    scenarioId = "region-based"
    context.directory(folder)

    rng, targets, signal, leakageCap = _pickTargets(context, scenarioId, count=6)
    signalSet = set(signal)

    # Signal genes first so they are certain to be represented, then background.
    # The cap keeps the signal a minority of the annotation even if a snapshot
    # produces an unusually large planted set.
    chosen = sorted(signalSet)[:REGION_GENE_COUNT // 3]
    remaining = [gene for gene in context.kegg.allGenes() if gene not in set(chosen)]
    chosen += rng.sample(remaining, min(REGION_GENE_COUNT - len(chosen), len(remaining)))
    chosen = sorted(set(chosen))
    diffuseGenes = set(simulate.chooseDiffuseFeatures(rng, chosen, signalSet))

    layout = []            # (geneID, chrom, start, end, strand, exons)
    tssOf = {}
    for index, gene in enumerate(chosen):
        chrom = REGION_CHROMOSOMES[index % len(REGION_CHROMOSOMES)]
        slot = index // len(REGION_CHROMOSOMES)
        start = 10000 + slot * GENE_SPACING              # 1-based inclusive
        end = start + GENE_LENGTH - 1
        strand = "+" if index % 3 else "-"
        exons = [(start, start + 2000),
                 (start + 9000, start + 11000),
                 (end - 2000, end)]
        layout.append((gene, chrom, start, end, strand, exons))
        tssOf[gene] = (chrom, start if strand == "+" else end, strand)

    gtfFile = writers.writeGtf(
        context.dataPath(folder, "synthetic_mmu.gtf"), layout)

    # One region per gene, sitting in the promoter, plus intergenic decoys that
    # belong to no gene -- so "every region found a gene" is not the trivial
    # outcome.
    regions = []
    relevantRegions = []
    for gene, chrom, start, end, strand, _exons in layout:
        _chrom, tss, _strand = tssOf[gene]
        # 500 bp UPSTREAM of the TSS, which is a lower coordinate on the plus
        # strand and a higher one on the minus strand. Subtracting regardless of
        # strand puts a third of the regions inside the gene body instead of in
        # its promoter -- still assigned to the gene by RGmatch, but under the
        # wrong area rule, so the scenario would not test what it claims to.
        # The -1 converts the 1-based GTF coordinate to the 0-based BED one.
        if strand == "+":
            regionStart = max(0, tss - 1 - 500)
        else:
            regionStart = tss - 1 + 100
        regionEnd = regionStart + 400
        isSignal = gene in signalSet
        isDiffuse = gene in diffuseGenes
        values = simulate.rampedRatios(
            rng, len(TIME_COURSE), isSignal or isDiffuse,
            effectSize=(simulate.DEFAULT_EFFECT_SIZE * 0.7 if isSignal
                        else simulate.DIFFUSE_EFFECT_SIZE),
            downFraction=(simulate.DEFAULT_DOWN_FRACTION if isSignal else 0.5))
        regions.append((chrom, regionStart, regionEnd,
                        [simulate.formatValue(v) for v in values]))
        if isSignal or isDiffuse:
            relevantRegions.append((chrom, regionStart, regionEnd))

    for index in range(200):
        chrom = REGION_CHROMOSOMES[index % len(REGION_CHROMOSOMES)]
        slot = index // len(REGION_CHROMOSOMES)
        # Parked in the gap between two genes, far from any TSS.
        regionStart = 10000 + slot * GENE_SPACING + GENE_LENGTH + 20000
        regions.append((chrom, regionStart, regionStart + 400,
                        [simulate.formatValue(v)
                         for v in simulate.rampedRatios(rng, len(TIME_COURSE), False)]))

    regions.sort(key=lambda region: (region[0], region[1]))
    valuesFile = writers.writeRegionValues(
        context.dataPath(folder, "dnase_regions_values.tab"), TIME_COURSE, regions)
    relevantFile = writers.writeRelevantRegions(
        context.dataPath(folder, "dnase_regions_relevant.tab"),
        sorted(relevantRegions, key=lambda region: (region[0], region[1])))

    return {
        "id": scenarioId,
        "title": "Region-based omic — DNase-like regions",
        "summary": ("Genomic regions in BED-like form with a matching synthetic "
                    "GTF, so region-to-gene assignment runs without the large "
                    "mouse annotation a fresh checkout does not have. Signal "
                    "regions sit in promoters; 200 intergenic decoys do not."),
        "tests": ["RGmatch region-to-gene assignment", "Promoter/TSS area rules",
                  "Three-column relevant-regions parsing",
                  "Region omics feeding pathway enrichment"],
        "pipeline": "regions2genes",
        "organism": "mmu",
        "databases": ["KEGG"],
        "conditions": TIME_COURSE,
        "simulated": True,
        "supersededBy": "stategra-regions",
        "omics": [{
            "omicName": "DNase-seq",
            "omicType": "region",
            "enrichment": "genes",
            "dataFile": context.relative(valuesFile),
            "relevantFile": context.relative(relevantFile),
        }],
        "references": [{
            "omicName": "DNase-seq",
            "fileType": "Reference file",
            "dataFile": context.relative(gtfFile),
        }],
        "expected": _pathwayExpectations(
            context, folder, targets, signal,
            {"regions": len(regions), "relevantRegions": len(relevantRegions),
             "intergenicDecoys": 200, "annotatedGenes": len(layout)},
            leakageCap=leakageCap),
    }


CATALOGUE = [
    buildGeneSingleCondition,
    buildGeneMultiCondition,
    buildGenePerConditionRelevance,
    buildMultiomics,
    buildRegulatoryMirna,
    buildRegulatoryMore,
    buildRegionBased,
]
