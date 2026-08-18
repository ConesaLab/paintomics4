#***************************************************************
#  This file is part of Paintomics v4
#**************************************************************
"""Estimate how long a MORE job will take, before agreeing to run it.

Why this exists
---------------
``MOREServlet`` enqueues every MORE job with ``timeout=1800``. That ceiling was
never reachable by the bundled example, so nothing checked against it -- but it
is comfortably reachable by real data. Measured on the STATegra TF->gene set
(9,835 targets, 36 samples, 564 regulators, ~30 regulators/gene), one process
at a time on an M4 Pro:

    R MLR      ~3.4 h      6.8x over budget
    R PLS1     ~1.7 h      3.4x over budget
    Rust PLS1  ~9 s        fine

So a user who uploads a genome-scale dataset today waits half an hour and then
gets a timeout, having learned nothing. This module lets the servlet say no
immediately, and say why, and say what to change.

Note what that table implies: **this is not an MLR problem.** R's PLS1 -- the
default method -- blows the same budget, because `ropls` has no compiled core
and PLS1 is interpreted R. Gating MLR alone would leave the default path
failing exactly as it does now on any host without ``more-rs``, which includes
the Drago deployment. The estimate is therefore keyed on (method, engine), not
on method.

What the model is
-----------------
    seconds = C(method, engine)
              * modelledGenes
              * (regPerGene / P0) ** B(method)
              * (samples * groups / (N0 * G0)) ** C_DESIGN

Fitted from a sequential sweep over the three axes a dataset grows along
(``paintomics4_data/more-scale-test/calibrate.py``). Two things the measurements
settled that guesswork got wrong:

* **Linear in genes.** MORE loops gene by gene and the per-gene cost is stable:
  1.28 s/gene at 25 genes, 1.21 s/gene at 200. Extrapolating along this axis --
  the axis a real dataset actually explodes along -- is safe.
* **Weakly dependent on regulators-per-gene, NOT quadratic.** MORE's MLR path
  runs a p x p collinearity filter (`CollinearityFilter1`, MORE_MLR.R:793) and
  then `glmnet::cv.glmnet` over an alpha grid (`seq(0,1,0.1)`,
  auxFunctions.R:534) with leave-one-out folds whenever n < 50
  (auxFunctions.R:452). The correlation filter reads as O(p^2), so a quadratic
  term looked right. Measured at 100 genes: p=5 -> 102.7 s, p=30 -> 126.2 s,
  a fitted exponent of **0.13**. A 6x in p bought 23%. Per-gene fixed costs --
  the LOO cross-validation in particular, which is driven by n and not by p --
  dominate at realistic p, so a quadratic term would have over-predicted wide
  datasets by an order of magnitude and refused jobs that finish fine.

  (There is no stepwise selection anywhere in MORE. An earlier draft of this
  module said there was; `grep -rn 'step(\|stepAIC\|regsubsets' MORE/R` returns
  nothing. Selection is elastic-net shrinkage alone -- a regulator is
  "relevant" iff glmnet leaves its coefficient non-zero. This also means MLR
  reports coefficients with **no p-value column**, where PLS1 reports both
  (`MORE_MLR.R:689` vs `MORE_PLS.R:599`), which is why the submission form
  disables the alpha field for MLR.)

* **Design size matters far less than assumed.** The first draft used an
  exponent of 1.0 on samples x groups, reasoning that the design matrix is
  ~p*G columns wide. Measured across n*G = 48 -> 432 (a 9x): PLS1 rose 1.9x and
  MLR 1.8x, fitting exponents of **0.29 and 0.26**. At 1.0 a 100-sample,
  20-group study would have been quoted 4.6x its true cost and refused
  outright.

Deliberately optimistic
-----------------------
The estimate is tuned to *under*-predict. A false positive (refusing a job that
would have finished) is a user blocked from a legitimate analysis with no
recourse; a false negative is the status quo -- the job starts and hits the
1800 s timeout, which is exactly what happens today. So the guard only fires
when a job is clearly over, and ``SAFETY`` is below 1 rather than above it.

Not swept: sample count independent of group count. The design here is 12
groups x 3 replicates, and dropping timepoints drops both together, which is
how real designs grow anyway. The two are modelled as one ``samples * groups``
term. Treat a dataset with many replicates and few groups as the case this
model knows least about.
"""

import logging
import os

# ---------------------------------------------------------------------------
# Reference shape: the sweep's centre cell, against which the exponents apply.
# ---------------------------------------------------------------------------
P0 = 30.0   # regulators per gene
N0 = 36.0   # samples
G0 = 12.0   # experimental groups

# Per-gene seconds at the reference shape, by (method, engine).
#
# The two R rows are the slope of a least-squares fit over T = 25/50/100/200
# (calibrate.py), which separates the per-gene cost from R's ~2-3 s startup.
# They cross-validate against an independent earlier measurement on
# more-scale-test/subsets/rand1: 98 genes at 61.4 s PLS1 / 122.3 s MLR, i.e.
# 0.627 and 1.248 s/gene against the 0.607 and 1.198 fitted here.
#
# The two `rust` rows are more-rs, and they are NOT symmetric with R:
#
#   PLS1  0.09 s / 98 genes   -- a 660x win. `ropls` has no compiled core, so
#                               PLS1 on R is interpreted R and the port routs
#                               it. This is why a host with the port installed
#                               is effectively never gated, and the whole
#                               reason the estimate must know the engine.
#   MLR   25.74 s / 98 genes  -- only a 4.7x win, and that purely from rayon
#                               fanning targets across cores. R's MLR is
#                               `glmnet.so`, tuned Fortran; the port actually
#                               burns ~2.3x more CPU and wins wall-clock only
#                               on parallelism.
#
# An earlier draft of this table had ("MLR", "rust") at 0.0040 -- extrapolated
# from the PLS1 ratio rather than measured, and wrong by 66x. It was latent
# (_resolveMOREBackend sends MLR to R unconditionally, so the cell is
# unreachable today) but it was a landmine in exactly the case this module
# exists to prevent: a 30-minute job would have been quoted at 30 seconds and
# the guard would never have fired.
_PER_GENE_SECONDS = {
    ("PLS1", "r"): 0.607,
    ("MLR", "r"): 1.198,
    ("PLS1", "rust"): 0.00092,
    ("MLR", "rust"): 0.263,
}

# MORE's own cross-validation fold rule (`mynfolds`, auxFunctions.R:452), which
# the port reproduces exactly. It is a *step* function and it steps DOWN: below
# 50 samples MORE cross-validates leave-one-out, so the fold count equals the
# sample count, and at 50 it collapses to 5.
def _moreFolds(samples):
    samples = int(samples or 0)
    if samples < 50:
        return max(samples, 1)
    if samples < 100:
        return 5
    if samples < 200:
        return 7
    return 10


# Fold count at the reference shape (36 samples -> leave-one-out).
_FOLDS0 = _moreFolds(N0)

# Above this many regulators per gene the port's MLR cost stops rising. With
# `interactions = TRUE` the design carries G + p*G columns, so by p ~ 12 on a
# 12-group study it already exceeds the sample count and glmnet's active set is
# bounded by n rather than by p. Measured at n=36, G=12, 200 targets:
#
#   p =  3 -> 0.0518 s/gene      p = 20 -> 0.2346 s/gene
#   p =  6 -> 0.1220 s/gene      p = 30 -> 0.2257 s/gene
#   p = 12 -> 0.2254 s/gene
#
# i.e. linear to p=12 and flat after, which no single exponent expresses.
_RUST_MLR_P_SATURATION = 12.0

# Exponent on regulators-per-gene, fitted per method over p = 5..30. Both well
# under 1 -- see the module docstring for why the obvious O(p^2) reading is
# wrong.
_REG_EXPONENT = {"PLS1": 0.30, "MLR": 0.13}

# Exponent on the combined samples*groups design term, fitted over n*G = 48..432.
_DESIGN_EXPONENT = {"PLS1": 0.29, "MLR": 0.27}

# Both exponent tables were fitted on R. Whether they carry to the port is
# untested: R's large per-gene overhead partly masks the p and design terms,
# and the port has far less of it, so the true exponents there are probably
# steeper. The rust rows are therefore trustworthy at the reference shape and
# progressively less so away from it. Fitting them properly needs a rust sweep,
# which nothing has run.
_DEFAULT_REG_EXPONENT = 0.30
_DEFAULT_DESIGN_EXPONENT = 0.29

# Applied to the final figure, as a tuning knob for an operator who finds the
# guard too eager or too slack on their hardware.
#
# It sits at 1.0 rather than below it because the fitted model *already* errs
# optimistic without help: it under-predicts on 9 of the 10 calibration cells,
# by 1-17%. That margin is measured, so stacking an invented factor on top of
# it would only make the bias harder to reason about.
#
# The larger unmodelled variable is the machine. Calibration ran on an M4 Pro;
# Drago is an 8-vCPU VM where PySiQ workers contend with request handling, so
# R will be slower there and the estimate will under-predict further. That is
# the tolerable direction -- a job slips through and hits the 1800 s timeout,
# which is the behaviour that existed before this module -- whereas
# over-predicting refuses an analysis the user is entitled to run and offers
# them no way to find out it would have worked.
SAFETY = 1.0

# Host calibration. Every constant above was fitted on one developer machine
# (an M4 Pro), and the estimate is only as good as that machine resembles the
# one running the job. It often does not. Measured 2026-08-18 on
# paintomics.uv.es -- 6 QEMU vCPUs -- against the same 957-target dataset:
#
#   | method | dev machine | paintomics.uv.es | ratio |
#   | PLS1   |  ~1 s       |    3 s           |  ~3x  |
#   | MLR    |   25 s      |  571 s           |  23x  |
#
# The asymmetry is the point. A merely slower box would slow both by the same
# factor; MLR slowing 8x more than PLS1 is the port's allocation-heavy inner
# loops meeting musl's allocator across rayon threads on few cores, which is a
# property of the *build and host*, not of the model. No single fitted constant
# can carry across that, so it is an operator setting rather than a guess.
#
# Set `PAINTOMICS_MORE_COST_SCALE` to (this host's seconds) / (the estimate) for
# a job you have actually timed. Above 1 makes the guard more willing to refuse.
# Leaving it at 1.0 reproduces the previous behaviour exactly.
#
# Getting this wrong low is the failure that matters: the job is accepted, runs
# past MORE_JOB_TIMEOUT and is killed, and the user waits out the whole timeout
# to learn nothing. Getting it wrong high refuses an analysis that would have
# fitted -- worse than nothing, but visible and immediately fixable.
try:
    HOST_SCALE = float(os.getenv("PAINTOMICS_MORE_COST_SCALE", "1") or 1)
except (TypeError, ValueError):
    HOST_SCALE = 1.0
if not (HOST_SCALE > 0):
    HOST_SCALE = 1.0

# An unknown (method, engine) must not silently become "free". Falls back to
# the most expensive known combination, so a method added to runMORE.R without
# being calibrated here is gated conservatively rather than waved through.
_FALLBACK_PER_GENE = max(_PER_GENE_SECONDS.values())

# Association files can be very large -- 291k rows for one omic in the STATegra
# set, and nothing stops a user uploading ten times that. The probe runs inside
# a request handler, so the scan is capped and the remainder extrapolated by
# byte ratio.
_MAX_SCAN_ROWS = 2_000_000

# Rows used to decide which association column holds the regulator. runMORE.R
# makes the same decision by counting matches against the regulator matrix's
# row names; this mirrors it on a prefix rather than the whole file.
_ORIENTATION_SAMPLE_ROWS = 5000


class MOREShape(object):
    """What a MORE job will actually fit, as opposed to what was uploaded.

    ``modelledGenes`` is the count that matters and is not the target file's
    row count: a gene with no association is never modelled and costs nothing.
    """

    __slots__ = ("modelledGenes", "samples", "groups", "regPerGene",
                 "regulators", "associations", "truncated", "unassociated")

    def __init__(self, modelledGenes=0, samples=0, groups=0, regPerGene=0.0,
                 regulators=0, associations=0, truncated=False,
                 unassociated=False):
        self.modelledGenes = modelledGenes
        self.samples = samples
        self.groups = groups
        self.regPerGene = regPerGene
        self.regulators = regulators
        self.associations = associations
        # True when an association file exceeded _MAX_SCAN_ROWS and the counts
        # past that point are extrapolated.
        self.truncated = truncated
        # True when at least one omic had no association file, so MORE pairs
        # every regulator with every gene. The expensive case, and the one a
        # user is least likely to have anticipated.
        self.unassociated = unassociated

    def describe(self):
        """One line for an error message or a log."""
        return ("%d genes x %.0f regulators/gene, %d samples in %d groups"
                % (self.modelledGenes, self.regPerGene, self.samples,
                   self.groups))

    def __repr__(self):
        return "<MOREShape %s>" % self.describe()


def _countRowsAndWidth(path):
    """(data rows, header column count) for a delimited file, read as bytes.

    Bytes, not text, for two reasons. ``ensure_utf8`` does not run until STEP2,
    so at the gate a file may still be cp1252 and decoding it could raise --
    turning a size check into a failed submission. And counting newlines over
    64 KiB blocks is several times faster than iterating decoded lines, which
    matters inside a request handler.
    """
    rows = 0
    width = 0
    try:
        with open(path, "rb") as handle:
            first = handle.readline()
            if not first:
                return 0, 0
            # Whichever delimiter yields more fields is the one in use, the
            # same test read_matrix applies in runMORE.R.
            width = max(first.count(b"\t"), first.count(b",")) + 1
            while True:
                block = handle.read(65536)
                if not block:
                    break
                rows += block.count(b"\n")
            # A final line with no trailing newline still holds a row. Cheap to
            # get wrong by one and it only matters on tiny files, but a
            # one-gene test fixture is exactly a tiny file.
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size:
                handle.seek(size - 1)
                if handle.read(1) != b"\n":
                    rows += 1
    except (IOError, OSError) as error:
        logging.warning("MORE cost model: cannot read %s (%s)", path, error)
        return 0, 0
    return rows, width


def _readIdColumn(path, limit=None):
    """The first column of each data row, as bytes, skipping the header.

    Returns a set. Used for regulator IDs, which are few (564 in the STATegra
    set) -- do not point this at a target file with a million rows.
    """
    ids = set()
    try:
        with open(path, "rb") as handle:
            handle.readline()  # header
            for line in handle:
                if limit is not None and len(ids) >= limit:
                    break
                line = line.rstrip(b"\r\n")
                if not line:
                    continue
                for delimiter in (b"\t", b","):
                    if delimiter in line:
                        ids.add(line.split(delimiter, 1)[0])
                        break
                else:
                    ids.add(line)
    except (IOError, OSError) as error:
        logging.warning("MORE cost model: cannot read %s (%s)", path, error)
    return ids


def _probeAssociations(path, regulatorIds):
    """(distinct target genes, association rows, truncated) for one omic.

    Which column holds the target is decided the way runMORE.R decides it: by
    counting how many values in each column match the regulator data file's row
    names, and taking the *other* column as the target. Guessing "column 0 is
    the gene" would silently swap the two on a file written the other way round
    -- and runMORE.R accepts both -- which would report ~600 "genes" with 17
    regulators each instead of ~10,000 genes with 30.
    """
    targets = set()
    rows = 0
    truncated = False
    col1Hits = 0
    col2Hits = 0
    targetColumn = 0

    try:
        with open(path, "rb") as handle:
            handle.readline()  # header

            # Pass 1: orientation, over a prefix.
            sample = []
            for line in handle:
                line = line.rstrip(b"\r\n")
                if not line:
                    continue
                parts = line.split(b"\t") if b"\t" in line else line.split(b",")
                if len(parts) < 2:
                    continue
                sample.append(parts)
                if regulatorIds:
                    if parts[0] in regulatorIds:
                        col1Hits += 1
                    if parts[1] in regulatorIds:
                        col2Hits += 1
                if len(sample) >= _ORIENTATION_SAMPLE_ROWS:
                    break

            # Ties -- including the no-regulator-ids case -- keep column 0 as
            # the target, which is the documented layout (Target, Regulator).
            if col1Hits > col2Hits:
                targetColumn = 1

            for parts in sample:
                targets.add(parts[targetColumn])
            rows = len(sample)

            # Pass 2: the rest of the file, same orientation.
            for line in handle:
                line = line.rstrip(b"\r\n")
                if not line:
                    continue
                parts = line.split(b"\t") if b"\t" in line else line.split(b",")
                if len(parts) <= targetColumn:
                    continue
                targets.add(parts[targetColumn])
                rows += 1
                if rows >= _MAX_SCAN_ROWS:
                    truncated = True
                    break

            if truncated:
                # Scale the row count by how much of the file went unread. The
                # distinct-gene count stays as measured: it is a lower bound,
                # and a lower bound on genes with a fixed row count inflates
                # regulators-per-gene, which is the conservative direction.
                consumed = handle.tell()
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                if consumed > 0 and size > consumed:
                    rows = int(rows * (float(size) / consumed))
    except (IOError, OSError) as error:
        logging.warning("MORE cost model: cannot read %s (%s)", path, error)
        return 0, 0, False

    return len(targets), rows, truncated


def probeShape(inputDir, targetFile, conditionsFile, regulatoryOmics):
    """Measure a submitted job without loading any of it into memory.

    Paths are resolved the way ``fromMOREtoGenes_STEP2`` resolves them --
    ``os.path.join(inputDir, name)`` -- so the shape described here is the
    shape the backend will see. A file that cannot be read contributes zero
    rather than raising: this runs on the submission path, and a probe failure
    must degrade to "cannot estimate, let it through", never to a 500.
    """
    def resolve(name):
        return os.path.join(inputDir, name) if name else None

    conditionRows, conditionWidth = (0, 0)
    if conditionsFile:
        conditionRows, conditionWidth = _countRowsAndWidth(resolve(conditionsFile))
    # The conditions file is samples x groups with an ID column.
    samples = conditionRows
    groups = max(conditionWidth - 1, 0)

    targetRows, targetWidth = (0, 0)
    if targetFile:
        targetRows, targetWidth = _countRowsAndWidth(resolve(targetFile))
    if not samples:
        # No usable conditions file: fall back to the target matrix's width.
        samples = max(targetWidth - 1, 0)

    totalAssociations = 0
    totalRegulators = 0
    truncated = False
    unassociated = False
    # Genes are counted per omic and the maximum taken, not the sum: MORE fits
    # one model per gene using every omic at once, so a gene regulated by both
    # a TF and a miRNA is one model, not two.
    modelledGenes = 0

    for omic in regulatoryOmics or []:
        dataFile = omic.get("file")
        assocFile = omic.get("associations")

        regulatorRows, _ = (0, 0)
        if dataFile:
            regulatorRows, _ = _countRowsAndWidth(resolve(dataFile))
        totalRegulators += regulatorRows

        if not assocFile or str(assocFile).upper() == "NULL":
            # No association file: MORE pairs every regulator with every gene.
            unassociated = True
            modelledGenes = max(modelledGenes, targetRows)
            totalAssociations += regulatorRows * targetRows
            continue

        regulatorIds = _readIdColumn(resolve(dataFile)) if dataFile else set()
        genes, rows, wasTruncated = _probeAssociations(
            resolve(assocFile), regulatorIds)
        truncated = truncated or wasTruncated
        modelledGenes = max(modelledGenes, genes)
        totalAssociations += rows

    # A gene cannot be modelled if it has no expression row.
    if targetRows:
        modelledGenes = min(modelledGenes, targetRows)

    regPerGene = (float(totalAssociations) / modelledGenes) if modelledGenes else 0.0

    return MOREShape(
        modelledGenes=modelledGenes,
        samples=samples,
        groups=groups,
        regPerGene=regPerGene,
        regulators=totalRegulators,
        associations=totalAssociations,
        truncated=truncated,
        unassociated=unassociated,
    )


def estimateSeconds(shape, method, engine):
    """Predicted wall-clock seconds for ``shape`` under ``method`` on ``engine``.

    ``engine`` is "r" or "rust". Returns 0.0 when the shape is empty, which
    reads as "nothing to gate" -- an unreadable or absent input is STEP2's
    error to raise with a message about the file, not this module's to turn
    into a runtime refusal.
    """
    if not shape or shape.modelledGenes <= 0:
        return 0.0

    perGene = _PER_GENE_SECONDS.get(
        (method, engine),
        # An unknown engine for a known method is likelier to be an R variant
        # than a fast port, so prefer that row before the global fallback.
        _PER_GENE_SECONDS.get((method, "r"), _FALLBACK_PER_GENE))

    if (method, engine) == ("MLR", "rust"):
        return SAFETY * HOST_SCALE * perGene * shape.modelledGenes * _rustMlrShapeTerm(shape)

    regTerm = 1.0
    if shape.regPerGene > 0:
        regTerm = (shape.regPerGene / P0) ** _REG_EXPONENT.get(
            method, _DEFAULT_REG_EXPONENT)

    designTerm = 1.0
    if shape.samples > 0 and shape.groups > 0:
        designTerm = ((shape.samples * shape.groups) / (N0 * G0)) ** (
            _DESIGN_EXPONENT.get(method, _DEFAULT_DESIGN_EXPONENT))

    return SAFETY * HOST_SCALE * perGene * shape.modelledGenes * regTerm * designTerm


def _rustMlrShapeTerm(shape):
    """Shape multiplier for MLR on the port, which the R exponents get wrong.

    The R rows fit a power law in `samples * groups`. That form cannot describe
    the port, because the port's cost is dominated by the fold count and MORE's
    fold rule steps *down* at 50 samples. Measured, 60 targets, p = 30:

    | samples | groups | folds | measured s/gene | R-exponent model |
    | --- | --- | --- | --- | --- |
    | 36 | 12 | 36 (LOO) | 0.2257 | 0.2630 |
    | 48 | 12 | 48 (LOO) | 0.3204 | 0.2842  **under by 1.13x** |
    | 48 | 16 | 48 (LOO) | 0.4143 | 0.3072  **under by 1.35x** |
    | 51 | 17 | 5        | 0.0504 | 0.3174  over by 6.3x |

    Under-prediction is the failure that matters: it waves through a job that
    then runs to the queue timeout, which is exactly what this module exists to
    prevent. A power law cannot avoid it here, because a 60-sample study is
    *cheaper* than a 36-sample one (5 folds against 36) while `samples*groups`
    says the opposite -- measured 0.0391 against 0.1928 s/gene at p = 12.

    So the port's MLR cost is modelled on the terms that actually drive it:
    linear in `folds + 1` (the folds plus the full-data fit), linear in groups,
    and linear in regulators-per-gene up to the saturation point above. Against
    every shape measured -- including the two real datasets, `rand1` at 0.2347
    and the STATegra example at 0.0261 s/gene -- this over-predicts by between
    1.08x and 2.55x and never under-predicts.
    """
    folds = _moreFolds(shape.samples) if shape.samples > 0 else _FOLDS0
    foldTerm = (folds + 1.0) / (_FOLDS0 + 1.0)

    groupTerm = (shape.groups / G0) if shape.groups > 0 else 1.0

    regTerm = 1.0
    if shape.regPerGene > 0:
        regTerm = min(shape.regPerGene, _RUST_MLR_P_SATURATION) / _RUST_MLR_P_SATURATION

    return foldTerm * groupTerm * regTerm


def _formatDuration(seconds):
    if seconds < 90:
        return "%d seconds" % int(round(seconds))
    if seconds < 5400:
        return "%.0f minutes" % (seconds / 60.0)
    return "%.1f hours" % (seconds / 3600.0)


def checkBudget(shape, method, engine, budgetSeconds):
    """``None`` if the job may run, otherwise the refusal to show the user.

    A non-positive budget disables the guard, which is how an operator with a
    longer queue timeout or a faster machine opts out (see
    ``MORE_RUNTIME_BUDGET_SECONDS``).
    """
    if not budgetSeconds or budgetSeconds <= 0:
        return None

    estimate = estimateSeconds(shape, method, engine)
    if estimate <= budgetSeconds:
        return None

    # Every number the user needs to act on, and the two actions that actually
    # work. Naming the shape matters: "too large" without the measurement
    # leaves them guessing which axis to cut.
    message = [
        "This MORE job is too large to finish inside the %s the server allows "
        "for a single analysis." % _formatDuration(budgetSeconds),
        "",
        "Submitted: %s." % shape.describe(),
        "Estimated %s runtime: about %s."
        % (method, _formatDuration(estimate)),
    ]

    if shape.unassociated:
        message += [
            "",
            "At least one regulatory omic was submitted without an association "
            "file, so every regulator is paired with every gene. Supplying "
            "associations is usually the single biggest reduction available.",
        ]

    if method == "MLR":
        # Only promise that switching method fixes it when it actually would.
        # PLS1 is ~2x faster than MLR on R, which is not enough to rescue a
        # genome-scale job: the real dataset is 3.3 h as MLR and still 1.7 h as
        # PLS1, both refused. Telling that user to "switch to PLS1" sends them
        # to a second refusal, so the estimate decides the wording.
        #
        # Compared on the SAME engine deliberately. MLR always runs on R, and
        # if this host has more-rs then PLS1 would be faster still -- so a
        # same-engine comparison understates the gain and can only make this
        # suggestion more conservative, never less.
        alternative = estimateSeconds(shape, "PLS1", engine)
        if alternative <= budgetSeconds:
            message += [
                "",
                "MLR is the slower method and is not the recommended default. "
                "The same analysis as PLS1 is estimated at about %s, which is "
                "inside the limit -- and PLS1 handles many correlated "
                "regulators better when samples are few, so it is worth "
                "trying first."
                % _formatDuration(alternative),
            ]
        else:
            message += [
                "",
                "Switching to PLS1 will not be enough on its own: the same "
                "data is estimated at about %s that way, still over the "
                "limit. PLS1 remains the better-suited method here, but this "
                "job needs to be smaller as well."
                % _formatDuration(alternative),
            ]

    message += [
        "",
        "Otherwise, reduce the number of genes analysed -- filtering to "
        "differentially expressed genes before submitting is the usual "
        "approach -- or split the analysis into several smaller jobs.",
    ]

    if shape.truncated:
        message += [
            "",
            "(The association file was too large to count exactly; the "
            "estimate above uses a sampled count.)",
        ]

    return "\n".join(message)
