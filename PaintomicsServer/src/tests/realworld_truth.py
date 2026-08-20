"""Truth extraction for the real-world conversion harness.

Reads one JSON spec on stdin and writes the table a correct conversion must
contain as TSV on stdout. The spec is written by a person who has read the
file -- which sheet, which header row, which columns are measurements, which
rows are flagged -- so the agent is graded against an expert's reading of the
same file rather than against its own output.

Spec keys (all optional unless stated):
  file            path (required)
  sheet           workbook sheet name or index
  sep, encoding, skiprows     text files (defaults: tab, utf-8, 0)
  read_kwargs     when present the file is read with pandas' own header
                  handling (R write.table output) and `header` is ignored
  header          0-based row index of the header in the raw table (default 0)
  skip_after_header   rows to drop directly under the header (second header)
  section         1-based: take only the Nth block of rows between banner rows
  drop_banners    drop rows with <= 2 filled cells
  rows            [from, to] inclusive raw row indices, instead of the body
  filter          [{col, eq|ne|lt|gt|notempty|regex}]
  id              column name, or a list to coalesce (first non-empty wins)
  id_transform    "lead" (first accession of a ';'-joined group), "unquote"
  values          list of names | {"regex": r} | {"all_except": [names]}
  pivot           {"category": col}: wide table, one column per (category x value)
  aggregate       "mean" | "sum" | "first" over repeated identifiers
  mode            "ids" -> write the distinct identifiers only (relevant lists)
"""

import json
import re
import sys

import numpy as np
import pandas as pd

MISSING = {"", "na", "nan", "n/a", "null", "none", "filtered", "#n/a", "-", "inf", "-inf"}


def is_missing(v):
    return v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip().lower() in MISSING


def read_raw(spec):
    path = spec["file"]
    if "read_kwargs" in spec:
        df = pd.read_csv(path, dtype=str, **spec["read_kwargs"])
        if not isinstance(df.index, pd.RangeIndex):
            df = df.reset_index()
        df.columns = [str(c).strip().strip('"') for c in df.columns]
        return None, df
    if path.lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(path, sheet_name=spec.get("sheet", 0), header=None, dtype=str)
        raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
        return raw, None
    raw = pd.read_csv(path, sep=spec.get("sep", "\t"), header=None, dtype=str,
                      keep_default_na=False, encoding=spec.get("encoding", "utf-8"),
                      skiprows=spec.get("skiprows", 0), engine="python",
                      quotechar='"', skip_blank_lines=True)
    raw = raw.replace({"": np.nan}).dropna(how="all").reset_index(drop=True)
    return raw, None


def banner_mask(raw):
    filled = raw.notna().sum(axis=1)
    return (filled > 0) & (filled <= 2) & (raw.shape[1] >= 3)


def frame(spec):
    raw, df = read_raw(spec)
    if df is not None:
        return df
    h = spec.get("header", 0)
    names = []
    for j, v in enumerate(raw.iloc[h].tolist()):
        n = "" if is_missing(v) else str(v).strip()
        n = n or "column_%d" % (j + 1)
        while n in names:
            n += "_"
        names.append(n)
    if "rows" in spec:
        body = raw.iloc[spec["rows"][0]:spec["rows"][1] + 1]
    else:
        body = raw.iloc[h + 1 + spec.get("skip_after_header", 0):]
    body = body.copy()
    body.columns = names
    if spec.get("section"):
        mask = banner_mask(body)
        section_id = mask.cumsum()
        # Rows before the first banner are section 0 when the sheet starts
        # with data; a sheet whose banner comes first starts at section 1.
        wanted = spec["section"] - (0 if mask.iloc[0] else 1) if len(mask) else 0
        body = body[(section_id == wanted) & ~mask]
    elif spec.get("drop_banners"):
        body = body[~banner_mask(body)]
    return body


def apply_filters(body, filters):
    for f in filters or []:
        col = body[f["col"]]
        if "eq" in f:
            body = body[col.fillna("") == f["eq"]]
        elif "ne" in f:
            body = body[col.fillna("") != f["ne"]]
        elif "lt" in f:
            body = body[pd.to_numeric(col, errors="coerce") < f["lt"]]
        elif "gt" in f:
            body = body[pd.to_numeric(col, errors="coerce") > f["gt"]]
        elif f.get("notempty"):
            body = body[~col.map(is_missing)]
        elif "regex" in f:
            body = body[col.fillna("").str.contains(f["regex"], regex=True)]
    return body


def ids_of(body, spec):
    idspec = spec["id"]
    if isinstance(idspec, list):
        out = pd.Series([np.nan] * len(body), index=body.index, dtype="object")
        for name in idspec:
            col = body[name]
            take = out.isna() & ~col.map(is_missing)
            out[take] = col[take]
        ids = out
    else:
        ids = body[idspec]
    ids = ids.map(lambda v: np.nan if is_missing(v) else str(v).strip())
    t = spec.get("id_transform")
    if t == "lead":
        ids = ids.map(lambda v: v if not isinstance(v, str) else re.split(r"[;,]", v)[0].strip())
    elif t == "unquote":
        ids = ids.map(lambda v: v if not isinstance(v, str) else v.strip('"').strip("'"))
    return ids


def value_columns(body, spec):
    v = spec.get("values")
    names = [str(c) for c in body.columns]
    if isinstance(v, list):
        return v
    if isinstance(v, dict) and "regex" in v:
        return [n for n in names if re.search(v["regex"], n)]
    if isinstance(v, dict) and "all_except" in v:
        skip = set(v["all_except"])
        idn = spec["id"] if isinstance(spec["id"], str) else None
        return [n for n in names if n not in skip and n != idn]
    return []


def main():
    spec = json.load(sys.stdin)
    body = frame(spec)
    body = apply_filters(body, spec.get("filter"))
    ids = ids_of(body, spec)
    keep = ids.notna()
    body, ids = body[keep], ids[keep]

    if spec.get("mode") == "ids":
        out = pd.DataFrame({"id": pd.unique(ids)})
        out.to_csv(sys.stdout, sep="\t", index=False, header=False)
        return

    vcols = value_columns(body, spec)
    vals = body[vcols].apply(lambda s: pd.to_numeric(
        s.map(lambda x: np.nan if is_missing(x) else str(x).replace(",", ".") if spec.get("decimal_comma") else x),
        errors="coerce"))
    vals.columns = vcols

    if spec.get("pivot"):
        cat = body[spec["pivot"]["category"]].astype(str)
        agg = spec.get("aggregate", "first")
        pieces = []
        for m in vcols:
            wide = pd.pivot_table(pd.DataFrame({"id": ids.values, "cat": cat.values, "v": vals[m].values}),
                                  index="id", columns="cat", values="v", aggfunc=agg, dropna=False)
            wide.columns = ["%s|%s" % (c, m) for c in wide.columns]
            pieces.append(wide)
        df = pd.concat(pieces, axis=1).reset_index().rename(columns={"index": "id"})
    else:
        df = pd.concat([ids.rename("id").reset_index(drop=True), vals.reset_index(drop=True)], axis=1)
        agg = spec.get("aggregate")
        if agg:
            df = df.groupby("id", sort=False, as_index=False).agg(agg)

    if spec.get("dropna_all", True) and len(vcols):
        df = df[df.iloc[:, 1:].notna().any(axis=1)]
    df.to_csv(sys.stdout, sep="\t", index=False, na_rep="nan", float_format="%.10g")


if __name__ == "__main__":
    main()
