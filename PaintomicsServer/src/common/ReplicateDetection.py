#***************************************************************
#  This file is part of Paintomics v4
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomicsai@gmail.com
#**************************************************************
"""
ReplicateDetection
==================

Conservative replicate-suffix detector for Paintomics value-file headers.

The function ``detect_replicates(replicateHeader)`` inspects the per-column
labels of a values file (i.e. ``omicHeader[1:]`` — the ID column has already
been stripped) and decides whether the columns look like *technical/biological
replicates* of a smaller set of *samples*.

Design constraints
------------------
- **Conservative whitelist only.** We accept only suffixes that are
  unambiguously replicate markers in the bioinformatics community:
  ``_R1``, ``_rep1``, ``_replicate_1``, ``.r1``, ``-rep1`` … (case-insensitive,
  separator one of ``._-``). Patterns such as ``T0/T1/T2`` (time points),
  ``Patient1/Patient2`` (subjects) or bare ``Sample_1/Sample_2`` are
  intentionally rejected — silent collapse there would corrupt the science.
- **No partial guessing.** If only some columns match, we surface that as
  ``status="partial"`` and let the UI ask the user to upload an explicit
  design file. We never auto-collapse a partial match.
- **Replication required.** Even if every column matches the regex, we only
  return ``status="complete"`` when at least one resulting *sample* groups
  ≥2 replicate columns. Otherwise the file is effectively per-sample already
  and aggregation would be a no-op.

Return contract
---------------
``detect_replicates(replicateHeader)`` returns a dict::

    {
        "status": "complete" | "partial" | "none",
        "sampleHeader": list[str],          # ordered, deduplicated sample names
        "mapping":      list[int],          # len == len(replicateHeader);
                                            #   mapping[i] = index into sampleHeader
                                            #   for replicate column i, or -1 if
                                            #   the column did not match.
        "groups":       list[list[int]],    # sampleHeader[s] → indices of its
                                            #   replicate columns in replicateHeader.
        "unmatched":    list[int],          # indices of unmatched columns
                                            #   (always [] when status == "complete").
    }

The same shape is always returned — empty lists where appropriate — so callers
can branch on ``status`` and use the rest of the dict uniformly.
"""

import re
from collections import OrderedDict

import numpy as np


# ----------------------------------------------------------------------------
# Whitelist regex
# ----------------------------------------------------------------------------
# Matches a trailing replicate suffix on a column name. Captures:
#   sample : the column name with the suffix stripped (the biological sample)
#   sep    : the separator before the suffix (one of . _ -) — preserved only
#            internally, callers do not need it.
#   tag    : the literal suffix tag matched (R / rep / replicate, case-insens.)
#   num    : the replicate number (one or more digits)
#
# Notes:
# - ``.+?`` (non-greedy) ensures we strip the *last* replicate suffix only,
#   so e.g. ``Ctrl_24h_R1`` collapses to sample ``Ctrl_24h`` rather than ``Ctrl``.
# - The optional separator between the tag and the number (e.g. ``_replicate_1``
#   vs ``_R1``) is required to be either nothing or one of ``._- ``.
# - ``re.IGNORECASE`` covers ``R1 / r1 / Rep1 / REPLICATE_1`` etc.
# - Anchored at end of string (``$``) — no partial trailing match allowed.
_REPLICATE_SUFFIX = re.compile(
    r'^(?P<sample>.+?)'
    r'(?P<sep>[._\-])'
    r'(?P<tag>replicate|rep|r)'
    r'(?:[._\-\s])?'
    r'(?P<num>\d+)$',
    re.IGNORECASE,
)


def _strip_replicate_suffix(columnName):
    """
    Try to split ``columnName`` into (sampleName, replicateNumber).

    Returns ``(sampleName, replicateNumber)`` if the conservative whitelist
    matches, otherwise ``(None, None)``. ``replicateNumber`` is returned as
    an int for downstream sortability, but callers should not rely on its
    value — only on whether it is ``None``.
    """
    if not columnName or not isinstance(columnName, str):
        return None, None

    stripped = columnName.strip()
    if not stripped:
        return None, None

    m = _REPLICATE_SUFFIX.match(stripped)
    if m is None:
        return None, None

    sample = m.group("sample").strip()
    if not sample:
        # Pathological case: a header like "_R1" with no real prefix.
        return None, None

    try:
        num = int(m.group("num"))
    except (TypeError, ValueError):
        return None, None

    return sample, num


def detect_replicates(replicateHeader):
    """
    Detect a replicate-grouping in the columns of a values-file header.

    Parameters
    ----------
    replicateHeader : list[str]
        Per-column labels (i.e. ``omicHeader[1:]`` — the ID column already
        stripped). May contain whitespace; entries are stripped internally.
        ``None`` / empty list / single-column input always yields ``status="none"``.

    Returns
    -------
    dict
        See module docstring for the schema. Always non-``None``.
    """
    # Empty / None / single-column inputs cannot have replicates by definition.
    if not replicateHeader or len(replicateHeader) < 2:
        return _none_result(replicateHeader or [])

    # First pass: try to strip a replicate suffix off every column.
    # We preserve insertion order of sample names so the resulting display
    # matches the user's original column order (no surprise reorder).
    sample_to_idx = OrderedDict()      # sampleName -> idx in sampleHeader
    groups = []                        # parallel to sampleHeader; list of col indices
    mapping = [-1] * len(replicateHeader)
    unmatched = []

    for col_idx, raw in enumerate(replicateHeader):
        sample, _num = _strip_replicate_suffix(raw)
        if sample is None:
            unmatched.append(col_idx)
            continue

        if sample not in sample_to_idx:
            sample_to_idx[sample] = len(sample_to_idx)
            groups.append([])
        s_idx = sample_to_idx[sample]
        groups[s_idx].append(col_idx)
        mapping[col_idx] = s_idx

    sampleHeader = list(sample_to_idx.keys())

    # Decide status.
    if not sampleHeader:
        # Nothing matched the regex.
        return _none_result(replicateHeader)

    if unmatched:
        # Some columns matched, others did not — refuse to silently aggregate.
        return {
            "status":       "partial",
            "sampleHeader": sampleHeader,
            "mapping":      mapping,
            "groups":       groups,
            "unmatched":    unmatched,
        }

    # All columns matched. Require ≥1 sample with ≥2 replicates; otherwise
    # the file is effectively already per-sample and aggregation would be a
    # no-op (and the user would be presented with a confusing panel showing
    # every original column unchanged).
    if not any(len(g) >= 2 for g in groups):
        return _none_result(replicateHeader)

    return {
        "status":       "complete",
        "sampleHeader": sampleHeader,
        "mapping":      mapping,
        "groups":       groups,
        "unmatched":    [],
    }


def _none_result(replicateHeader):
    """Empty-shape result used for ``status="none"``."""
    return {
        "status":       "none",
        "sampleHeader": [],
        "mapping":      [-1] * len(replicateHeader),
        "groups":       [],
        "unmatched":    list(range(len(replicateHeader))),
    }


# ----------------------------------------------------------------------------
# Aggregation
# ----------------------------------------------------------------------------

def aggregate_replicates(values, relevant, groups, n_samples):
    """
    Collapse a per-replicate row into per-sample mean values + relevance.

    Parameters
    ----------
    values : sequence[float]
        Numeric values, one per replicate column. Length must equal the total
        number of replicate columns covered by ``groups``. Missing entries
        should be ``float('nan')``; ``None`` is also tolerated.
    relevant : sequence[bool] | bool | None
        Per-replicate relevance flags. Three accepted shapes:

        - list[bool] of length == len(values): one flag per replicate column.
        - bool: scalar flag applied uniformly to every replicate (legacy
          single-condition jobs treat ``OmicValue.relevant`` as a single bool).
        - empty list / None: treated as all-False.
    groups : list[list[int]]
        ``groups[s]`` lists the replicate-column indices that belong to
        sample ``s``. Produced by :func:`detect_replicates` or by parsing a
        manual design file.
    n_samples : int
        Number of biological samples — must equal ``len(groups)``. Passed
        explicitly so the function can return a fixed-shape result even when
        a sample has zero replicates (defensive, should not happen in practice).

    Returns
    -------
    (sampleValues, sampleRelevant) : (list[float], list[bool])
        - ``sampleValues[s]`` = ``nanmean`` over ``values[groups[s]]``.
          NaN if every replicate of that sample is NaN.
        - ``sampleRelevant[s]`` = ``any(relevant[i] for i in groups[s])``
          (OR-collapse: a sample is significant if at least one of its
          replicates is significant).

    Notes
    -----
    Big-O: O(total_replicates). Vectorised per-sample with ``np.nanmean``;
    the relevance OR-collapse is a Python ``any()`` because boolean lists are
    short (a few thousand at most) and ``any()`` short-circuits.

    Edge cases handled:
    - Empty group → NaN value, False relevance.
    - All-NaN group → NaN value (warned by numpy; we suppress).
    - Scalar / missing ``relevant`` → broadcast to a per-replicate list.
    """
    if n_samples != len(groups):
        raise ValueError(
            "n_samples (%d) does not match len(groups) (%d)" % (n_samples, len(groups))
        )

    arr = np.asarray(values, dtype=float)  # NaN-safe; coerces None → nan via float()
    n_reps = arr.size

    # Normalise the relevance argument into a length-n_reps boolean array so
    # we can index into it the same way for every shape of input.
    rel_arr = _broadcast_relevant(relevant, n_reps)

    # Detect *feature-level* relevance (a scalar / None / length-≤1 list),
    # which carries the "this whole feature is relevant" semantic rather than
    # any per-condition information. The pre-existing renderer convention is
    # to emit a row-label `*` for these cases instead of per-cell stars
    # (see OmicValue.isRelevant's `relevant.length <= 1` guard). We preserve
    # that convention by emitting a length-1 sampleRelevant — its `length<=1`
    # state is what tells the renderer not to draw per-cell stars.
    feature_level_relevant = (
        relevant is None
        or isinstance(relevant, (bool, str))
        or (hasattr(relevant, "__len__") and len(relevant) <= 1)
    )

    sampleValues = [float("nan")] * n_samples

    # Suppress the "Mean of empty slice" / "All-NaN slice encountered" warnings
    # numpy emits for empty / fully-NaN groups — we *want* NaN there.
    with np.errstate(invalid="ignore"):
        for s_idx, cols in enumerate(groups):
            if not cols:
                continue
            # Clamp to the width this row actually has. `groups` is derived from
            # the *header* (detect_replicates on omicHeader[1:], or the design
            # file), while `values` is built per row in Job.py as
            # list(map(float, line[1:])) -- nothing pads the row out to the
            # header. A row narrower than the header therefore indexes past the
            # end here and used to kill the whole request with IndexError. The
            # relevance path below already clamps these same indices.
            in_range = [c for c in cols if c < n_reps]
            slice_vals = arr[in_range]
            if slice_vals.size == 0 or np.all(np.isnan(slice_vals)):
                sampleValues[s_idx] = float("nan")
            else:
                sampleValues[s_idx] = float(np.nanmean(slice_vals))

    if feature_level_relevant:
        # Single bool, regardless of sample count. Length-1 → renderer's guard.
        sampleRelevant = [bool(rel_arr.any())] if n_reps > 0 else [False]
    else:
        # Per-sample OR-collapse over the replicate columns of each sample.
        sampleRelevant = [
            bool(any(rel_arr[c] for c in cols if c < rel_arr.size))
            for cols in groups
        ]

    return sampleValues, sampleRelevant


def _broadcast_relevant(relevant, n_reps):
    """
    Normalise the ``relevant`` argument of :func:`aggregate_replicates` into a
    length-``n_reps`` numpy bool array.

    Accepted shapes (matching the ambient OmicValue.relevant contract):
      - None / empty list  → all False.
      - bool / "True" / "False" string → uniform broadcast.
      - list[bool] of length n_reps → as-is.
      - list[bool] of any other length → padded / truncated to n_reps with
        False fill. Defensive: keeps the function from raising on slightly
        misaligned legacy inputs; the *caller* is responsible for matching
        relevance and value shapes in well-formed cases.
    """
    if relevant is None:
        return np.zeros(n_reps, dtype=bool)
    if isinstance(relevant, bool):
        return np.full(n_reps, relevant, dtype=bool)
    if isinstance(relevant, str):
        return np.full(n_reps, relevant == "True" or relevant == True, dtype=bool)
    # List/tuple/iterable path
    coerced = [bool(v == "True" or v == True) for v in relevant]
    if len(coerced) == n_reps:
        return np.asarray(coerced, dtype=bool)
    out = np.zeros(n_reps, dtype=bool)
    out[: min(len(coerced), n_reps)] = coerced[: min(len(coerced), n_reps)]
    return out
