#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Reading an experimental design into a replicate -> sample grouping.

Why this module exists
----------------------
PaintOmics already knows how to collapse replicate columns into one column per
biological sample: ``PathwayAcquisitionJob.applyReplicateMappingForOmic``
consumes a ``(sampleHeader, mapping, groups)`` triple and averages the columns
of each group. What it could not do was *obtain* that triple for a design that
states the grouping in a matrix rather than in the column names.

Two file shapes carry the same information:

**Long form** — two columns, what the Step-2 "upload a design" box accepts::

    Batch_1_Ctr_0H    Ctr_0H
    Batch_2_Ctr_0H    Ctr_0H

**Indicator matrix** — what MORE requires as its ``edesign``, and what the
bundled ``11-stategra-more`` example ships::

    Sample            Ctr_0H  Ctr_2H  ...  Ik_24H
    Batch_1_Ctr_0H    1       0       ...  0
    Batch_2_Ctr_0H    1       0       ...  0

The long-form reader was fed the matrix verbatim once, and the result was not
an error: column 1 of a matrix row is an indicator, so every sample collapsed
into two groups named "1" and "0". Silence like that is why the shape is
detected here rather than assumed by the caller.

The detection is deliberately narrow. A file is treated as a matrix only when
it has three or more columns AND every value cell is one of "", "0", "1" —
a two-column design whose labels happen to be "0"/"1" stays long form, and a
matrix with a stray value is rejected loudly rather than half-read.
"""

from collections import OrderedDict

__all__ = ["parse_design", "derive_groupings", "looks_like_indicator_matrix"]


# Cells an indicator matrix is allowed to contain. "1.0"/"0.0" appear when a
# design has been round-tripped through a spreadsheet or pandas.
_TRUE_CELLS = ("1", "1.0", "TRUE", "True", "true")
_FALSE_CELLS = ("", "0", "0.0", "FALSE", "False", "false", "NA")


def _split_rows(body):
    """(separator, [[cell, ...], ...]) for the non-comment, non-blank rows."""
    sep = "\t" if "\t" in body else ","
    rows = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append([cell.strip() for cell in line.split(sep)])
    return sep, rows


def looks_like_indicator_matrix(rows):
    """True when ``rows`` is a 0/1 design matrix rather than a long-form list.

    Requires at least one data row and at least two condition columns; a
    single-condition matrix is indistinguishable from a long-form file whose
    labels are all "1", and the long-form reading of it is the harmless one.
    """
    if len(rows) < 2:
        return False

    width = len(rows[0])
    if width < 3:
        return False

    for row in rows[1:]:
        if len(row) != width:
            return False
        for cell in row[1:]:
            if cell not in _TRUE_CELLS and cell not in _FALSE_CELLS:
                return False
    return True


def _matrix_to_pairs(rows):
    """[(sample_column, condition_label), ...] from an indicator matrix.

    A row must mark exactly one condition. Zero marks means the sample belongs
    to no group and cannot be averaged into one; more than one means the design
    is crossed in a way this collapsing cannot express. Either is an error
    rather than a guess -- averaging a sample into the wrong condition would
    silently corrupt every value drawn from it.
    """
    conditions = rows[0][1:]
    pairs = []

    for row in rows[1:]:
        sample = row[0]
        if not sample:
            continue
        marked = [condition for condition, cell in zip(conditions, row[1:])
                  if cell in _TRUE_CELLS]
        if len(marked) != 1:
            raise Exception(
                "Design file: sample '%s' marks %d conditions; exactly one is "
                "required." % (sample, len(marked)))
        pairs.append((sample, marked[0]))

    return pairs


def parse_design(body, replicateHeader):
    """
    Parse a design file into ``(sampleHeader, mapping, groups)``.

    Accepts either shape described in the module docstring. ``replicateHeader``
    is the omic's column labels with the ID column already stripped.

    Sample-label order follows first appearance in the file, so the author of
    the design controls the display order without reordering the values file.

    Validation:
    - every entry in ``replicateHeader`` must appear in the file (hard error);
    - sample labels must be non-empty (hard error);
    - an indicator row marking other than exactly one condition (hard error).
    """
    if not body:
        raise Exception("Design file is empty.")

    _sep, rows = _split_rows(body)

    if looks_like_indicator_matrix(rows):
        pairs = _matrix_to_pairs(rows)
    else:
        pairs = []
        for row in rows:
            if len(row) < 2:
                # Tolerate trailing empty lines / incomplete rows but skip them.
                continue
            pairs.append((row[0], row[1]))

    column_to_sample = OrderedDict()
    for col_name, sample_label in pairs:
        if not col_name:
            continue
        # Header detection: the first row whose column-1 entry doesn't match any
        # actual column in the values-file header is a header row -- skip it once.
        if col_name not in replicateHeader and not column_to_sample:
            continue
        if not sample_label:
            raise Exception("Design file: empty sample label for column '%s'." % col_name)
        column_to_sample[col_name] = sample_label

    missing = [c for c in replicateHeader if c not in column_to_sample]
    if missing:
        raise Exception(
            "Design file is missing entries for columns: %s" % ", ".join(missing[:10])
            + ("…" if len(missing) > 10 else ""))

    sampleHeader = []
    seen = {}
    for col_name, _label in pairs:
        if col_name not in column_to_sample:
            continue
        label = column_to_sample[col_name]
        if label not in seen:
            seen[label] = len(sampleHeader)
            sampleHeader.append(label)

    mapping = [seen[column_to_sample[c]] for c in replicateHeader]
    groups = [[] for _ in sampleHeader]
    for col_idx, s_idx in enumerate(mapping):
        groups[s_idx].append(col_idx)

    return sampleHeader, mapping, groups


# ---------------------------------------------------------------------------
# Coarser groupings derived from the condition names
# ---------------------------------------------------------------------------

_SEPARATORS = ("_", "-", ".")


def _factor_positions(conditionNames):
    """[(separator, position, [value, ...]), ...] for each usable factor.

    A design like ``Ctr_0H … Ik_24H`` is 2 treatments crossed with 6
    timepoints, and a reader may want either axis on its own. A token position
    qualifies when every condition name splits into the same number of tokens
    and that position takes more than one value but fewer than all of them --
    a constant position groups nothing, a unique one is the conditions again.

    Positions are returned, never named. Nothing in the file says the first
    token means "treatment"; calling it that would be inventing biology from
    the string "Ctr". The caller labels a grouping with its own values.
    """
    if len(conditionNames) < 2:
        return []

    for sep in _SEPARATORS:
        tokenised = [name.split(sep) for name in conditionNames]
        width = len(tokenised[0])
        if width < 2 or any(len(tokens) != width for tokens in tokenised):
            continue

        factors = []
        for position in range(width):
            values = list(OrderedDict.fromkeys(tokens[position] for tokens in tokenised))
            if 1 < len(values) < len(conditionNames):
                factors.append((sep, position, values))
        if factors:
            return factors

    return []


def derive_groupings(replicateHeader, sampleHeader, mapping):
    """
    The groupings a reader can choose between, coarsest last.

    ``sampleHeader``/``mapping`` are a design already parsed by
    :func:`parse_design`: the replicate columns and which condition each falls
    in. Returned entries are ready for ``applyReplicateMappingForOmic``:

        {"id", "label", "sampleHeader", "mapping", "groups"}

    Always includes the identity grouping ("every column on its own") and the
    full design. Adds one entry per usable factor position, labelled with the
    values it groups by rather than with an invented factor name.
    """
    groupings = []

    def _add(gid, label, labels, columnToGroup):
        groups = [[] for _ in labels]
        for col_idx, g_idx in enumerate(columnToGroup):
            groups[g_idx].append(col_idx)
        groupings.append({
            "id": gid,
            "label": label,
            "sampleHeader": list(labels),
            "mapping": list(columnToGroup),
            "groups": groups,
        })

    # Identity: what the job shows with no aggregation at all.
    _add("columns", "Individual columns (%d)" % len(replicateHeader),
         list(replicateHeader), list(range(len(replicateHeader))))

    # The design itself.
    _add("design", "Condition (%d)" % len(sampleHeader), sampleHeader, mapping)

    # One grouping per factor position within the condition names.
    for sep, position, values in _factor_positions(sampleHeader):
        valueToIndex = dict((value, idx) for idx, value in enumerate(values))
        conditionToFactor = [valueToIndex[name.split(sep)[position]] for name in sampleHeader]
        columnToGroup = [conditionToFactor[condition_idx] for condition_idx in mapping]
        _add("factor%d" % position,
             "%s (%d)" % (", ".join(values[:4]) + ("…" if len(values) > 4 else ""),
                          len(values)),
             values, columnToGroup)

    return groupings
