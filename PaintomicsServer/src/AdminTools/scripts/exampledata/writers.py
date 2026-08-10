#!/usr/bin/env python3
"""One writer per input format PaintOmics accepts.

Every shape here was taken from the code that reads it, not from the prose
documentation, and each writer names its reader so the pairing can be checked:

  writeValues            <- Job.parseGeneBasedFiles / PathwayAcquisitionJob.validateFile
  writeRelevantSingle    <- Job.parseSignificativeFeaturesFile, 1-column branch
  writeRelevantPerCondition <- ditto, multi-condition branch (Job.py:865)
  writeRegionValues      <- Bed2GeneJob, and validateFile's >= 4 column floor
  writeRelevantRegions   <- Job.parseSignificativeFeaturesFile, isBedFormat branch
  writeAssociations      <- validateFile's "exactly 2 columns" rule
  writeMirnaAssociations <- miRNA2Target.py (miRNA, gene, PLR)
  writeMatrix            <- runMORE.R read_matrix (header=TRUE, row.names=1)
  writeDesign            <- runMORE.R read_matrix, then MORE's edesign
  writeGtf               <- DHS_exon_association.py, which needs `exon` rows

Conventions that are not negotiable
-----------------------------------
* **`\\n` endings, UTF-8, no BOM.** `original/dnase_values.dat` ships classic-Mac
  `CR` endings, which is why `wc -l` reports 0 lines for a 1.9 MB file. Nothing
  generated here repeats that.
* **A `#` on the values header.** The header detector treats a leading `#` as an
  explicit "this row is not data" marker; without it the first row is guessed at
  by heuristic, and a condition named e.g. `WT_1234` would be read as a feature.
* **No `#` on a per-condition relevant header.** There the `#` means "schema
  comment, keep legacy two-column detection alive" (Job.py:836); a plain header
  is what commits the file to the multi-condition reading.
* **Padded rows.** A per-condition relevant file whose columns differ in length
  is padded with empty cells, because validateFile takes the first line's width
  as the file's width and the parser indexes by column position.
"""
import os


def _write(path, lines):
    """Write `lines` (no trailing newlines of their own) and return `path`."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line + "\n")
    return path


def _row(*fields):
    return "\t".join(str(field) for field in fields)


# ---------------------------------------------------------------------------
# Gene-, protein-, miRNA- and compound-based values
# ---------------------------------------------------------------------------

def writeValues(path, idHeader, conditionNames, rows):
    """`#<idHeader><TAB>Cond1…CondN`, then one row per feature.

    `rows` is an iterable of (featureID, [formattedValue, ...]). Values arrive
    pre-formatted as text so a caller can mix numbers and the `NA` token
    without this function having to know which is which.
    """
    lines = [_row("#" + idHeader, *conditionNames)]
    for featureID, values in rows:
        lines.append(_row(featureID, *values))
    return _write(path, lines)


def writeRelevantSingle(path, featureIDs):
    """One identifier per line -- relevance shared by every condition."""
    return _write(path, list(featureIDs))


def writeRelevantPerCondition(path, conditionNames, perCondition):
    """One column per condition; a cell names a feature relevant *there*.

    `perCondition` is a list of iterables, parallel to `conditionNames`. The
    columns are independent and typically differ in length, so the file is as
    tall as the longest and shorter columns are padded with empty cells --
    which the parser skips (`if featureID.strip()`), and which keeps every row
    the width validateFile measured from row one.
    """
    columns = [sorted(ids) for ids in perCondition]
    if len(columns) != len(conditionNames):
        raise ValueError(
            "perCondition has %d columns but %d condition names were given"
            % (len(columns), len(conditionNames)))

    height = max((len(column) for column in columns), default=0)
    lines = [_row(*conditionNames)]
    for index in range(height):
        lines.append(_row(*[column[index] if index < len(column) else ""
                            for column in columns]))
    return _write(path, lines)


# ---------------------------------------------------------------------------
# Region-based omics
# ---------------------------------------------------------------------------

def writeRegionValues(path, conditionNames, regions):
    """`#CHR<TAB>start<TAB>end<TAB>values…`.

    `regions` is an iterable of (chrom, start, end, [formattedValue, ...]).
    Coordinates are half-open and 0-based on the start, matching BED, which is
    what RGmatch assumes when it compares a region against an exon.
    """
    lines = [_row("#CHR", "start", "end", *conditionNames)]
    for chrom, start, end, values in regions:
        lines.append(_row(chrom, start, end, *values))
    return _write(path, lines)


def writeRelevantRegions(path, regions):
    """Exactly three columns -- chrom, start, end. Any other width is rejected.

    The parser keys these as `chrom_start_end` lowercased, so the coordinates
    must be written exactly as they appear in the values file: a region written
    `1 63176480 63177113` here and `chr1 …` there matches nothing, and the only
    symptom is zero relevant regions with no error.
    """
    return _write(path, [_row(chrom, start, end) for chrom, start, end in regions])


def writeGtf(path, genes):
    """A minimal but complete GTF: `gene`, `transcript` and `exon` rows.

    RGmatch reads `exon` rows and reconstructs transcript and gene extents from
    them, so the exons are the load-bearing part; the `gene` and `transcript`
    rows are written because real GTFs have them and their presence exercises
    the reader's geneFlag/transFlag branches.

    `genes` is an iterable of (geneID, chrom, start, end, strand, [(exonStart,
    exonEnd), ...]). GTF coordinates are 1-based and inclusive -- unlike the BED
    regions above -- which is exactly the off-by-one that region-to-gene
    assignment gets wrong when it gets it wrong, so it is worth having a fixture
    that models both conventions correctly.
    """
    lines = ['#!genome-build paintomics-synthetic-v1',
             '#!note coordinates are synthetic; gene IDs are real Ensembl IDs']
    for geneID, chrom, start, end, strand, exons in genes:
        transcriptID = geneID.replace("ENSMUSG", "ENSMUST")
        attributes = 'gene_id "%s"; transcript_id "%s";' % (geneID, transcriptID)
        lines.append(_row(chrom, "synthetic", "gene", start, end, ".", strand, ".",
                          'gene_id "%s";' % geneID))
        lines.append(_row(chrom, "synthetic", "transcript", start, end, ".", strand,
                          ".", attributes))
        for number, (exonStart, exonEnd) in enumerate(exons, start=1):
            lines.append(_row(
                chrom, "synthetic", "exon", exonStart, exonEnd, ".", strand, ".",
                '%s exon_number "%d";' % (attributes, number)))
    return _write(path, lines)


# ---------------------------------------------------------------------------
# Association sidecars
# ---------------------------------------------------------------------------

def writeAssociations(path, pairs, header=None):
    """Two columns, nothing else -- validateFile rejects any other width.

    `header` is optional because the two consumers disagree: PaintOmics's
    association validator counts columns and would treat a header as a row
    (harmless -- it is still two columns), while runMORE.R reads associations
    with `header=TRUE` and would eat the first real pair without one.
    """
    lines = [_row(*header)] if header else []
    lines.extend(_row(left, right) for left, right in pairs)
    return _write(path, lines)


def writeMirnaAssociations(path, triples):
    """`miRNA<TAB>EnsemblGeneID<TAB>PLR`, with the header miRNA2Target expects.

    PLR is the target-prediction score; larger means a more confident call. The
    bundled `mmu_mirBase_to_ensembl.tab` is this shape at 31 MB, and the
    simulated version is the same shape at a size a test can read.
    """
    lines = [_row("miRNA", "Ensembl.Gene.ID", "PLR")]
    lines.extend(_row(mirna, gene, "%.2f" % score) for mirna, gene, score in triples)
    return _write(path, lines)


# ---------------------------------------------------------------------------
# MORE: per-sample matrices and the experimental design
# ---------------------------------------------------------------------------

def writeMatrix(path, idHeader, sampleNames, rows):
    """`<idHeader><TAB>Sample1…SampleN` -- no leading `#`.

    runMORE.R parses this with `read.table(header=TRUE, row.names=1)`. R would
    keep a `#` as part of the first column name, and more importantly treats
    `#` as a comment character elsewhere, so the PaintOmics convention of
    marking the header is wrong for exactly these files.

    Feature IDs must be unique: a duplicate makes the tab parse fail with
    "duplicate 'row.names' are not allowed", the comma attempt returns a
    zero-column frame, and the job proceeds with no data at all.
    """
    seen = set()
    lines = [_row(idHeader, *sampleNames)]
    for featureID, values in rows:
        if featureID in seen:
            raise ValueError(
                "duplicate feature ID %r in %s: read.table would fail on it "
                "and runMORE.R would silently proceed with an empty matrix"
                % (featureID, os.path.basename(path)))
        seen.add(featureID)
        lines.append(_row(featureID, *values))
    return _write(path, lines)


def writeDesign(path, sampleNames, groupNames, sampleGroups):
    """MORE's `edesign`: one row per sample, one 0/1 column per group.

    `sampleGroups` is parallel to `sampleNames` and holds the group name each
    sample belongs to. Written as indicator columns rather than a single
    factor column because read_matrix rejects a non-numeric cell outright --
    a `Group` column holding "Ctrl"/"Treat" fails with "has non-numeric values
    in column(s): Group", which is a clear error but not an accepted input.

    Sample order must match the matrices' column order; MORE pairs them by
    position as well as by name.
    """
    if len(sampleGroups) != len(sampleNames):
        raise ValueError("sampleGroups must be parallel to sampleNames")

    lines = [_row("Sample", *groupNames)]
    for sample, group in zip(sampleNames, sampleGroups):
        lines.append(_row(sample, *[1 if group == name else 0
                                    for name in groupNames]))
    return _write(path, lines)


def writeIdList(path, ids):
    """A bare list of identifiers -- MORE's "significant regulators" export."""
    return _write(path, list(ids))


def writeExpected(path, entries, title):
    """Ground truth for assertions: what the pipeline is supposed to recover.

    Written with a `#` comment header naming what the list means, because these
    files are read by humans debugging a failing test at least as often as by
    the test itself.
    """
    lines = ["# " + title,
             "# Generated by src/AdminTools/scripts/exampledata; do not edit by hand."]
    lines.extend(str(entry) for entry in entries)
    return _write(path, lines)
