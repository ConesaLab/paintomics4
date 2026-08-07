#!/usr/bin/env python3
"""Synthetic omics files, one builder per omic type the app accepts.

Why this exists
---------------
The suite validates the omic types the bundled STATegra example happens to
cover, in the one shape that example happens to have. Everything else -- a
region-based BED, a miRNA table, a metabolite file with a duplicate compound,
a header that forgot its hash -- is only ever exercised by a human uploading a
file. Those paths reject bad input by *accumulating a message string*, so a
validator that stops accumulating does not crash; it accepts the file and the
job produces a quietly wrong answer.

Simulated data is what makes the negative cases reachable. The example files
are, by construction, valid: they cannot tell you what happens to a file with
three columns where four were expected, because no such file ships.

Every builder writes a real file to `directory` and returns its path, so the
validators can be called exactly as the servlets call them. Values are
deterministic (no RNG) so a failure names one input rather than a seed.

The shapes here are taken from the validators themselves, not from the docs:

  * gene/protein/miRNA values: `#header`, then `id` + one column per condition
  * region-based values:       `id  chr  start  end  <values...>` (>= 4 columns)
  * relevant features:         one ID per line, short lines
  * region relevant features:  exactly 3 columns
  * associations (MORE):       `regulator  target` pairs

Usage:
    from src.tests.fake_omics import geneExpressionFile, regionBasedFile
"""
import os


def _write(directory, name, lines):
    path = os.path.join(directory, name)
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def _conditionHeader(nConditions, first="#ID"):
    return "\t".join([first] + ["Cond%d" % i for i in range(1, nConditions + 1)])


# ---------------------------------------------------------------------------
# Gene-based omics: expression, proteomics, miRNA, transcription factor
# ---------------------------------------------------------------------------

def geneExpressionFile(directory, name="geneexpression.tab", nFeatures=6,
                       nConditions=3, ids=None):
    """`#header` + one row per gene, tab separated, all values numeric."""
    ids = ids or ["ENSMUSG%011d" % (i + 1) for i in range(nFeatures)]
    lines = [_conditionHeader(nConditions)]
    for index, featureID in enumerate(ids):
        values = ["%.3f" % (index + column * 0.5 - 1) for column in range(nConditions)]
        lines.append("\t".join([featureID] + values))
    return _write(directory, name, lines)


def proteomicsFile(directory, name="proteomics.tab", **kwargs):
    kwargs.setdefault("ids", ["P%05d" % (i + 1) for i in range(kwargs.get("nFeatures", 6))])
    return geneExpressionFile(directory, name, **kwargs)


def miRNAFile(directory, name="mirna.tab", nFeatures=6, nConditions=3):
    ids = ["mmu-miR-%d-5p" % (100 + i) for i in range(nFeatures)]
    return geneExpressionFile(directory, name, nFeatures, nConditions, ids=ids)


def metabolomicsFile(directory, name="metabolomics.tab", nFeatures=6, nConditions=3):
    """KEGG compound IDs, the identifier space the compound matcher expects."""
    ids = ["C%05d" % (42 + i) for i in range(nFeatures)]
    return geneExpressionFile(directory, name, nFeatures, nConditions, ids=ids)


def transcriptionFactorFile(directory, name="tf.tab", nFeatures=6, nConditions=3):
    ids = ["TF%04d" % (i + 1) for i in range(nFeatures)]
    return geneExpressionFile(directory, name, nFeatures, nConditions, ids=ids)


# ---------------------------------------------------------------------------
# Region-based omic (BED-like), validated by Bed2GeneJob
# ---------------------------------------------------------------------------

def regionBasedFile(directory, name="regions.tab", nFeatures=6, nConditions=3):
    """`id chr start end <values>`; the validator floats everything from col 3."""
    lines = [_conditionHeader(nConditions, first="#RegionID\tChr\tStart")]
    for index in range(nFeatures):
        start = 1000 + index * 500
        values = ["%.3f" % (index + column * 0.25) for column in range(nConditions)]
        lines.append("\t".join(
            ["region_%d" % (index + 1), "chr1", str(start)] + values))
    return _write(directory, name, lines)


def regionRelevantFile(directory, name="regions_relevant.tab", nFeatures=3):
    """Exactly three columns -- the validator rejects any other width."""
    lines = ["\t".join(["region_%d" % (i + 1), "chr1", str(1000 + i * 500)])
             for i in range(nFeatures)]
    return _write(directory, name, lines)


# ---------------------------------------------------------------------------
# Relevant-features and association sidecars
# ---------------------------------------------------------------------------

def relevantFeaturesFile(directory, name="relevant.tab", ids=None, nFeatures=3):
    ids = ids or ["ENSMUSG%011d" % (i + 1) for i in range(nFeatures)]
    return _write(directory, name, list(ids))


def associationsFile(directory, name="associations.tab", pairs=None):
    """MORE regulator->target pairs, tab separated."""
    pairs = pairs or [("TF0001", "ENSMUSG00000000001"),
                      ("TF0002", "ENSMUSG00000000002")]
    return _write(directory, name,
                  ["\t".join(pair) for pair in pairs])


# ---------------------------------------------------------------------------
# Deliberately malformed variants -- the whole point of simulating
# ---------------------------------------------------------------------------

def headerWithoutHash(directory, name="no_hash.tab", nConditions=3):
    """A non-numeric first row that does not start with '#'."""
    lines = ["\t".join(["ID"] + ["Cond%d" % i for i in range(1, nConditions + 1)])]
    lines.append("\t".join(["ENSMUSG00000000001"] + ["1.0"] * nConditions))
    return _write(directory, name, lines)


def raggedFile(directory, name="ragged.tab", nConditions=3, shortRow=1):
    """One row narrower than the header promised."""
    lines = [_conditionHeader(nConditions)]
    lines.append("\t".join(["ENSMUSG00000000001"] + ["1.0"] * nConditions))
    lines.append("\t".join(["ENSMUSG00000000002"] + ["1.0"] * (nConditions - shortRow)))
    return _write(directory, name, lines)


def nonNumericValuesFile(directory, name="non_numeric.tab", nConditions=3):
    """Well-shaped, but a value column holds text."""
    lines = [_conditionHeader(nConditions)]
    lines.append("\t".join(["ENSMUSG00000000001"] + ["1.0"] * nConditions))
    lines.append("\t".join(["ENSMUSG00000000002"] + ["not_a_number"] * nConditions))
    return _write(directory, name, lines)


def manyBrokenLinesFile(directory, name="many_broken.tab", nConditions=3, nBroken=25):
    """More broken rows than the validator's error cap, to pin the cap.

    The first data row must be well formed: the validator takes its width as
    the expected column count when none was passed in (`nConditions == -1`),
    so a file whose rows are uniformly wrong is uniformly *right* by that rule.
    Only rows after the first can be ragged.
    """
    lines = [_conditionHeader(nConditions)]
    lines.append("\t".join(["ENSMUSG00000000000"] + ["1.0"] * nConditions))
    for index in range(nBroken):
        lines.append("\t".join(["ENSMUSG%011d" % (index + 1)] + ["1.0"] * (nConditions - 1)))
    return _write(directory, name, lines)


def regionFileWithTwoColumns(directory, name="too_narrow.tab"):
    """Region file below the 4-column floor the validator requires."""
    return _write(directory, name, ["#RegionID\tChr", "region_1\tchr1"])


def omicInput(dataFile, relevantFile=None, omicName="Gene expression"):
    """The dict shape the validators read, built from written file paths."""
    entry = {"omicName": omicName,
             "inputDataFile": os.path.basename(dataFile),
             "isExample": False}
    if relevantFile is not None:
        entry["relevantFeaturesFile"] = os.path.basename(relevantFile)
    return entry
