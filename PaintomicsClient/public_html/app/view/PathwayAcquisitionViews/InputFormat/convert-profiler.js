/*
 * The Python that describes an uploaded file without disclosing it.
 *
 * The model needs to know what shape the data is in. It does NOT need the
 * measurements, and sending them would mean unpublished omics data leaving the
 * user's machine for a third-party gateway -- which for this audience is the
 * difference between using the feature and not.
 *
 * So the profile carries structure and identifiers: sheet names, column names,
 * dtypes, row counts, null counts, min/max/mean for numeric columns, the first
 * few rows and a handful of example ID strings. Identifiers have to go
 * verbatim, because recognising "ENSMUSG00000000001" as a mouse Ensembl gene is
 * exactly the judgement being asked for. Measurements go as summary statistics
 * plus the first eight rows; the server refuses any payload carrying more.
 *
 * Three facts are counted over the WHOLE file rather than the sample, because
 * a sample cannot see them and a converter that does not know them writes the
 * wrong file: the true row count, how many identifiers repeat in EACH
 * candidate identifier column (a tidy per-tissue table repeats every gene once
 * per tissue, and counting only column 0 -- the tissue -- reported zero), and
 * where banner rows split a sheet into sections.
 */
(function (root, factory) {
    if (typeof module === "object" && module.exports) module.exports = factory();
    else root.PaintomicsInputFormat = Object.assign(root.PaintomicsInputFormat || {}, factory());
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    // String.raw keeps the backslashes in the Python source literally, so
    // '\t' below reaches Python as the two characters it is meant to be.
    var PROFILE_CODE = String.raw`
import json, io, os, re, glob
import pandas as pd

PATH = sorted(glob.glob('/work/*'))[0]
SAMPLE_TABLE_ROWS = 4000      # rows parsed for the per-column statistics
SHOW_ROWS = 8                 # rows shown verbatim (truncated cells)
SHOW_COLS = 24
MAX_COLUMNS_LISTED = 52       # beyond this, the middle is summarised as families
MAX_ID_CANDIDATES = 5

def is_blank(v):
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() == ''

MISSING_TOKENS = {'na', 'nan', 'n/a', 'null', 'none', 'filtered', '-', 'inf', '-inf', '#n/a'}

def numeric_share(cells):
    # Missing-value tokens count as numeric: a proteomics row that is mostly
    # "NA" with two intensities is a data row, not a text row.
    vals = [c for c in cells if not is_blank(c)]
    if not vals:
        return 0.0
    ok = 0
    for v in vals:
        s = str(v).strip()
        if s.lower() in MISSING_TOKENS:
            ok += 1
            continue
        try:
            float(s.replace(',', '.'))
            ok += 1
        except Exception:
            pass
    return ok / len(vals)

def find_header(raw):
    """Index of the header row, or None when row 0 is already data.

    Title rows (one filled cell) and banners are skipped. Among the text rows
    above the first data row, the header is the most completely filled one
    (nearest to the data on a tie). Two shapes decide this: a DESeq2 sheet
    with "Control: s1 s2" and "Treatment: s3 s4" lines ABOVE the real header,
    and a MetaboLights MAF whose second line names the samples under an
    otherwise empty first line -- "first text row" picks wrong in one, "last
    text row" in the other.
    """
    n = min(len(raw), 14)
    width = raw.shape[1]
    candidates = []
    for i in range(n):
        row = raw.iloc[i].tolist()
        filled = sum(1 for c in row if not is_blank(c))
        if width >= 3 and filled <= max(2, width * 0.34):
            continue                                  # title / banner
        if numeric_share(row[1:]) >= 0.3:
            if not candidates:
                return None                           # data already: no header
            candidates.sort(key=lambda c: (c[1], c[0]))
            return candidates[-1][0]
        candidates.append((i, filled))
    if candidates:
        return candidates[0][0]
    return 0 if len(raw) else None

def banner_rows(raw, header, limit=8):
    """Rows with one or two filled cells inside a wide table: section banners."""
    out = []
    width = raw.shape[1]
    if width < 3:
        return out
    start = 0 if header is None else header + 1
    for i in range(start, len(raw)):
        row = raw.iloc[i].tolist()
        filled = [str(c).strip() for c in row if not is_blank(c)]
        if 0 < len(filled) <= 2:
            out.append({'row': int(i), 'text': ' | '.join(filled)[:80]})
            if len(out) >= limit:
                break
    return out

def family_of(name):
    # "LFQ intensity AH1_WT_R1" -> "LFQ intensity"; "Peptides BN_010_01" -> "Peptides"
    m = re.match(r'^(.*?)[\s_\-.:]*[A-Za-z]*\d', name)
    prefix = (m.group(1).strip() if m else '')
    # "[1] Orbi5546_Sample01.PG.Quantity" -> ".PG.Quantity"
    m2 = re.search(r'(\.[A-Za-z][A-Za-z.]*)$', name)
    suffix = m2.group(1) if m2 else ''
    return prefix, suffix

def column_families(names):
    pre, suf = {}, {}
    for n in names:
        p, s = family_of(n)
        if p and p != n:
            pre.setdefault(p, []).append(n)
        if s and s != n:
            suf.setdefault(s, []).append(n)
    fams = []
    for key, members in list(pre.items()) + list(suf.items()):
        if len(members) >= 3:
            fams.append({'family': key, 'count': len(members), 'examples': members[:3]})
    fams.sort(key=lambda f: -f['count'])
    return fams[:24]

def describe_column(name, s):
    entry = {'name': str(name)[:80], 'nulls': int(s.isna().sum())}
    num = pd.to_numeric(s, errors='coerce')
    share = float(num.notna().sum() / max(1, s.notna().sum())) if len(s) else 0.0
    entry['numeric_fraction'] = round(share, 3)
    if share > 0.9 and num.notna().any():
        entry['kind'] = 'numeric'
        entry['min'] = float(num.min()); entry['max'] = float(num.max())
        entry['mean'] = round(float(num.mean()), 4)
    else:
        entry['kind'] = 'text'
        entry['examples'] = [str(v)[:40] for v in s.dropna().unique()[:5]]
        entry['distinct'] = int(s.nunique(dropna=True))
        entry['duplicates'] = int(len(s.dropna()) - s.nunique(dropna=True))
    return entry

def describe_table(body, names):
    """Per-column description; wide tables list the edges and summarise the middle."""
    ncol = body.shape[1]
    idx = list(range(ncol))
    omitted = 0
    if ncol > MAX_COLUMNS_LISTED:
        head = idx[:MAX_COLUMNS_LISTED - 12]
        tail = idx[-12:]
        omitted = ncol - len(head) - len(tail)
        idx = head + tail
    cols = []
    for i in idx:
        c = describe_column(names[i], body.iloc[:, i])
        c['index'] = int(i)
        cols.append(c)
    out = {'n_columns': int(ncol), 'columns': cols}
    if omitted:
        out['omitted_columns'] = int(omitted)
    fams = column_families([str(n) for n in names])
    if fams:
        out['column_families'] = fams
    return out

def id_candidates(names, body):
    """Text columns that could be the identifier, by position."""
    out = []
    for i in range(body.shape[1]):
        s = body.iloc[:, i]
        if s.notna().mean() < 0.5:
            continue
        num = pd.to_numeric(s, errors='coerce')
        if num.notna().sum() / max(1, s.notna().sum()) > 0.5:
            continue
        out.append(i)
        if len(out) >= MAX_ID_CANDIDATES:
            break
    return out

def exact_block(total_rows, header_rows, id_cols):
    """id_cols: [(name, index, Series over the WHOLE file)]."""
    cands = []
    for name, i, col in id_cols:
        col = col.dropna()
        col = col[col.astype(str).str.strip() != '']
        cands.append({'column': str(name)[:60], 'index': int(i),
                      'distinct': int(col.nunique()),
                      'duplicates': int(len(col) - col.nunique()),
                      'filled': int(len(col))})
    return {'total_rows': int(total_rows),
            'data_rows': int(total_rows - header_rows),
            'id_candidates': cands}

def table_profile(name, raw, extra):
    header = find_header(raw)
    hdr_names = []
    if header is None:
        hdr_names = ['column_%d' % (j + 1) for j in range(raw.shape[1])]
        body = raw.copy()
    else:
        for j, v in enumerate(raw.iloc[header].tolist()):
            n = '' if is_blank(v) else str(v).strip()
            n = n or ('column_%d' % (j + 1))
            while n in hdr_names:
                n = n + '_'
            hdr_names.append(n)
        body = raw.iloc[header + 1:].copy()
    body.columns = hdr_names
    body = body.dropna(how='all')
    prof = {'name': name,
            'header_row': header,
            'header': ('row %d is the header' % header) if header is not None
                      else 'no header: row 0 is data',
            'sampled_rows': int(len(body))}
    prof.update(describe_table(body, hdr_names))
    banners = banner_rows(raw, header)
    if banners:
        prof['banner_rows'] = banners
    prof['first_rows'] = [[('' if is_blank(v) else str(v)[:30]) for v in r[:SHOW_COLS]]
                          for r in raw.head(SHOW_ROWS).values.tolist()]
    prof.update(extra)
    prof['_header'] = header
    prof['_names'] = hdr_names
    prof['_body'] = body
    return prof

# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
def read_workbook(path):
    import openpyxl
    tables = []
    book = pd.read_excel(path, sheet_name=None, header=None, dtype=str, nrows=SAMPLE_TABLE_ROWS)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    dims = {}
    for ws in wb.worksheets:
        try:
            dims[ws.title] = int(ws.max_row or 0)
        except Exception:
            dims[ws.title] = 0
    for sheet, raw in book.items():
        raw = raw.dropna(how='all').dropna(axis=1, how='all').reset_index(drop=True)
        if raw.shape[0] == 0:
            tables.append({'name': sheet, 'empty': True})
            continue
        prof = table_profile(sheet, raw, {})
        total = dims.get(sheet, 0)
        if total < len(raw) + (0 if prof['_header'] is None else 1):
            total = len(raw)
        header_rows = 0 if prof['_header'] is None else prof['_header'] + 1
        body = prof['_body']
        cand_idx = id_candidates(prof['_names'], body)
        if total - header_rows <= len(body) + 2:
            cols = [(prof['_names'][i], i, body.iloc[:, i]) for i in cand_idx]
            prof['exact'] = exact_block(total, header_rows, cols)
        else:
            # Larger than the sample: stream only the candidate columns.
            ws = wb[sheet]
            keep = {i: [] for i in cand_idx}
            n = 0
            for r in ws.iter_rows(values_only=True):
                n += 1
                if n <= header_rows:
                    continue
                for i in cand_idx:
                    keep[i].append(r[i] if i < len(r) else None)
            cols = [(prof['_names'][i], i, pd.Series(keep[i], dtype='object')) for i in cand_idx]
            prof['exact'] = exact_block(n, header_rows, cols)
        tables.append(prof)
    return {'container': 'workbook', 'tables': tables}

def sniff_text(path):
    with open(path, 'rb') as fh:
        blob = fh.read(400000)
    enc = 'utf-8-sig'
    try:
        text = blob.decode('utf-8-sig')
    except UnicodeDecodeError:
        enc = 'latin-1'
        text = blob.decode('latin-1')
    lines = text.splitlines()
    raw_head = [l[:220] for l in lines[:10]]
    # Preamble: leading lines with fewer separators than the body (GCT's "#1.2").
    def count(l, s): return l.count(s)
    best = None
    for sep, label in (('\t', 'tab'), (';', 'semicolon'), (',', 'comma')):
        counts = [count(l, sep) for l in lines[:40] if l.strip()]
        if not counts:
            continue
        typical = sorted(counts)[len(counts) // 2]
        if typical >= 1 and (best is None or typical > best[2]):
            best = (sep, label, typical)
    if best is None:
        best = (r'\s+', 'whitespace', 0)
    sep, label, typical = best
    skip = 0
    if typical >= 1:
        for l in lines[:10]:
            if not l.strip():
                skip += 1
                continue
            if count(l, sep) < max(1, typical // 2):
                skip += 1
            else:
                break
    return enc, sep, label, skip, raw_head

def read_text(path):
    enc, sep, label, skip, raw_head = sniff_text(path)
    kwargs = dict(sep=sep, encoding=enc, engine='python', header=None, dtype=str,
                  keep_default_na=False, na_values=[''], skiprows=skip,
                  skip_blank_lines=True)
    try:
        raw = pd.read_csv(path, nrows=SAMPLE_TABLE_ROWS, **kwargs)
    except Exception as exc:
        return {'container': 'text', 'encoding': enc, 'separator': label,
                'preamble_lines': skip, 'raw_head': raw_head,
                'tables': [], 'parse_error': str(exc)[:300]}
    raw = raw.dropna(how='all').reset_index(drop=True)
    prof = table_profile('(single table)', raw, {})
    header_rows = 0 if prof['_header'] is None else prof['_header'] + 1
    body = prof['_body']
    cand_idx = id_candidates(prof['_names'], body)
    # Whole-file pass over the candidate identifier columns only.
    try:
        whole = pd.read_csv(path, usecols=cand_idx or [0], **kwargs)
        total = int(len(whole))
        cols = [(prof['_names'][i], i, whole.iloc[:, k]) for k, i in enumerate(cand_idx)]
    except Exception:
        with open(path, 'rb') as fh:
            total = sum(1 for _ in fh) - skip
        cols = [(prof['_names'][i], i, body.iloc[:, i]) for i in cand_idx]
    prof['exact'] = exact_block(total, header_rows, cols)
    return {'container': 'text', 'encoding': enc, 'separator': label,
            'preamble_lines': skip, 'raw_head': raw_head, 'tables': [prof]}

with open(PATH, 'rb') as fh:
    magic = fh.read(4)
result = read_workbook(PATH) if magic[:2] == b'PK' else read_text(PATH)
for t in result['tables']:
    for k in ('_header', '_names', '_body'):
        t.pop(k, None)
result['file_size'] = os.path.getsize(PATH)

# The prompt has a size budget. An eleven-sheet workbook described in full ran
# to 35,000 characters and was cut mid-JSON, so the model never learned that
# the last five sheets existed and converted the ones it could see. Shrink the
# verbatim rows first, then the column lists, until the description fits.
BUDGET = 26000
def size():
    return len(json.dumps(result, default=str))
for rows_shown in (6, 4, 3, 2):
    if size() <= BUDGET:
        break
    for t in result['tables']:
        if t.get('first_rows'):
            t['first_rows'] = t['first_rows'][:rows_shown]
for cols_listed in (36, 24, 16):
    if size() <= BUDGET:
        break
    for t in result['tables']:
        cols = t.get('columns') or []
        if len(cols) > cols_listed:
            t['omitted_columns'] = int(t.get('omitted_columns', 0) + len(cols) - cols_listed)
            t['columns'] = cols[:cols_listed - 6] + cols[-6:]
result['description_chars'] = size()
print(json.dumps(result, default=str))
`;

    return { PROFILE_CODE: PROFILE_CODE };
});
