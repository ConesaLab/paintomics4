"""LayerMatrix — one honest view of the job's numbers, shared by every tool.

Why this exists
---------------
Every analysis module so far has re-derived its own matrix from the job:
`ordination.py` walks features for one omic, `differential.py` walks them
again with its own rules, `figures.py` resolves genes a third way. Three
walks, three chances to disagree about which rows exist, what a column is
called, and what happens to a clone. The Paper Agent multiplies the number of
consumers, so the walk happens ONCE, here, and everything downstream reads the
same table.

What one Layer holds, per omic (gene-based and compound-based alike):

  * `feature_ids` / `labels` — the job's id and the display name;
  * `values` — one row per feature, floats, `nan` where the upload had a hole
    (a hole is a fact about the data, not a zero);
  * `columns` — the condition labels from the omic's own header, shortened by
    the same rule the report text uses, so an axis and a sentence cannot
    disagree about what a condition is called;
  * `relevant` — the user's own relevance flags;
  * counters for everything that was DROPPED or MERGED, because a table that
    silently loses rows reads as complete when it is not.

Clone handling. PaintOmics maps one uploaded row to every feature it matches,
so the same measurements can appear under several feature ids ("clones").
For per-feature statistics and for enrichment universes that inflation is a
bias: a gene present as five clones votes five times. `deduplicated()` merges
rows whose (label, values) are identical, keeps the first id, records how many
were merged, and marks the merged row relevant if ANY clone was. The full,
undeduplicated view stays available -- pathway mapping legitimately needs
clones -- so the choice is the caller's, and both choices read the same data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

MIN_COLUMNS = 1


def _as_float(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else float("nan")
    if isinstance(value, str):
        try:
            v = float(value.strip())
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else float("nan")
    return None


@dataclass
class Layer:
    """One omic's features x conditions, plus the truth about what was lost."""
    omic: str
    kind: str                                   # "gene" | "compound"
    columns: List[str] = field(default_factory=list)
    feature_ids: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    values: List[List[float]] = field(default_factory=list)
    relevant: List[bool] = field(default_factory=list)
    n_dropped_nonnumeric: int = 0               # a cell that was not a number
    n_dropped_ragged: int = 0                   # row length != the header's
    n_clones_merged: int = 0                    # filled by deduplicated()

    @property
    def n_features(self):
        return len(self.feature_ids)

    @property
    def n_conditions(self):
        return len(self.columns)

    def row(self, feature_id):
        try:
            idx = self.feature_ids.index(str(feature_id))
        except ValueError:
            return None
        return self.values[idx]

    def deduplicated(self):
        """A new Layer with identical (label, values) rows merged.

        The first feature id of a clone group survives; `relevant` is the OR
        of the group (the user flagged the measurement, not the mapping);
        `n_clones_merged` says how many rows disappeared. Order is preserved.
        """
        seen = {}
        out = Layer(self.omic, self.kind, list(self.columns))
        merged = 0
        for i, label in enumerate(self.labels):
            key = (label, tuple(repr(v) for v in self.values[i]))
            kept = seen.get(key)
            if kept is None:
                seen[key] = len(out.feature_ids)
                out.feature_ids.append(self.feature_ids[i])
                out.labels.append(label)
                out.values.append(list(self.values[i]))
                out.relevant.append(bool(self.relevant[i]))
            else:
                merged += 1
                out.relevant[kept] = out.relevant[kept] or bool(self.relevant[i])
        out.n_dropped_nonnumeric = self.n_dropped_nonnumeric
        out.n_dropped_ragged = self.n_dropped_ragged
        out.n_clones_merged = merged
        return out

    def describe(self):
        """One sentence a tool can print without lying by omission."""
        bits = ["%s: %d features x %d conditions"
                % (self.omic, self.n_features, self.n_conditions)]
        if self.n_clones_merged:
            bits.append("%d clone rows merged" % self.n_clones_merged)
        if self.n_dropped_ragged:
            bits.append("%d rows dropped (wrong column count)"
                        % self.n_dropped_ragged)
        if self.n_dropped_nonnumeric:
            bits.append("%d non-numeric cells set to NaN"
                        % self.n_dropped_nonnumeric)
        return "; ".join(bits)


class LayerMatrix:
    """Every layer of one job, built with one walk."""

    def __init__(self, layers):
        self._layers: Dict[str, Layer] = dict(layers)

    def omics(self):
        return list(self._layers)

    def get(self, omic) -> Optional[Layer]:
        return self._layers.get(str(omic))

    def gene_layers(self):
        return [l for l in self._layers.values() if l.kind == "gene"]

    def compound_layers(self):
        return [l for l in self._layers.values() if l.kind == "compound"]

    def __len__(self):
        return len(self._layers)

    # -- construction ------------------------------------------------------

    @classmethod
    def from_job(cls, job_instance):
        from .context_builder import _build_omic_header_map
        header_map = _build_omic_header_map(job_instance) or {}

        declared = []
        for input_omic in (job_instance.getGeneBasedInputOmics() or []):
            declared.append((input_omic.get("omicName", ""), "gene"))
        for input_omic in (job_instance.getCompoundBasedInputOmics() or []):
            declared.append((input_omic.get("omicName", ""), "compound"))

        layers = {}
        for omic_name, kind in declared:
            if not omic_name or omic_name in layers:
                continue
            layers[omic_name] = Layer(omic_name, kind,
                                      list(header_map.get(omic_name) or []))

        features = dict(job_instance.getInputGenesData() or {})
        features.update(job_instance.getInputCompoundsData() or {})
        for fid, feature in features.items():
            for ov in (feature.getOmicsValues() or []):
                omic = ov.getOmicName() or ""
                layer = layers.get(omic)
                if layer is None:
                    # An omic the job never declared; declaring it here would
                    # invent a layer with no header. Skip, and let the counts
                    # of the declared layers stand for themselves.
                    continue
                raw = ov.getValues() or []
                row, holes = [], 0
                for v in raw:
                    f = _as_float(v)
                    if f is None:
                        holes += 1
                        row.append(float("nan"))
                    else:
                        row.append(f)
                if not layer.columns:
                    # No usable header came with this omic: name the columns
                    # by index, visibly, rather than borrowing another omic's.
                    layer.columns = [str(i) for i in range(len(row))]
                if len(row) != len(layer.columns) or len(row) < MIN_COLUMNS:
                    layer.n_dropped_ragged += 1
                    continue
                layer.n_dropped_nonnumeric += holes
                layer.feature_ids.append(str(fid))
                layer.labels.append(feature.getName() or str(fid))
                layer.values.append(row)
                try:
                    layer.relevant.append(bool(ov.isRelevant()))
                except Exception:
                    layer.relevant.append(False)

        return cls(layers)
