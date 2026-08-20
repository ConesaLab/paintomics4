"""Build the corpus of broken files the AI converter is measured against.

Every case is made by CORRUPTING a file that already ships as a working example,
which is the whole point: the original is the ground truth. A converter that
merely produces something the format validator accepts has done half the job --
it also has to produce the *same information*. Comparing against the original
catches a conversion that silently drops rows, swaps two conditions, coerces
values to NaN, or transposes a matrix the wrong way, none of which a format
check can see.

Cases span the three modules a user can run: gene expression, regulatory omics
(MORE) and region-based. They include files that are the wrong shape and files
that are simply ABSENT -- a missing experimental design has to be reconstructed
from the sample names, which is a different capability from repairing a table.

    python src/tests/build_conversion_corpus.py [--out DIR]
"""

import argparse
import csv
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.abspath(os.path.join(HERE, ".."))
DATASETS = os.path.join(SERVER, "examplefiles", "datasets")
DEFAULT_OUT = os.path.join(HERE, "inputformat_corpus")


def read_tsv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [row for row in csv.reader(fh, delimiter="\t")]


def write_tsv(path, rows, delimiter="\t", encoding="utf-8", newline="\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as fh:
        for row in rows:
            fh.write(delimiter.join(str(c) for c in row) + newline)


CASES = []


def case(cid, module, role, breakage, expects):
    """Register a corpus case.

    expects: what a correct conversion must reproduce. "truth" means the output
    must match the untouched original file exactly once parsed; "derived" means
    the original cannot be recovered byte-for-byte and the check is described in
    `note` instead.
    """
    def wrap(fn):
        CASES.append({"id": cid, "module": module, "role": role,
                      "breakage": breakage, "expects": expects, "build": fn})
        return fn
    return wrap


# ---------------------------------------------------------------------------
# Gene expression
# ---------------------------------------------------------------------------

GE = os.path.join(DATASETS, "02-gene-multi-condition", "data")


@case("ge-decimal-comma", "gene expression", "values",
      "European export: comma decimal mark", "truth")
def _(out):
    rows = read_tsv(os.path.join(GE, "gene_expression_values.tab"))
    broken = [rows[0]] + [[r[0]] + [c.replace(".", ",") for c in r[1:]] for r in rows[1:]]
    write_tsv(os.path.join(out, "ge-decimal-comma", "expression.tab"), broken)


@case("ge-semicolon", "gene expression", "values",
      "semicolon-separated, comma decimal mark", "truth")
def _(out):
    rows = read_tsv(os.path.join(GE, "gene_expression_values.tab"))
    broken = [rows[0]] + [[r[0]] + [c.replace(".", ",") for c in r[1:]] for r in rows[1:]]
    write_tsv(os.path.join(out, "ge-semicolon", "expression.csv"), broken, delimiter=";")


@case("ge-transposed", "gene expression", "values",
      "samples as rows, genes as columns", "truth")
def _(out):
    rows = read_tsv(os.path.join(GE, "gene_expression_values.tab"))[:301]
    transposed = [list(col) for col in zip(*rows)]
    write_tsv(os.path.join(out, "ge-transposed", "expression.tab"), transposed)


@case("ge-title-rows", "gene expression", "values",
      "two title rows above the header, blank row after", "truth")
def _(out):
    rows = read_tsv(os.path.join(GE, "gene_expression_values.tab"))
    width = len(rows[0])
    broken = ([["RNA-seq results — Experiment 4"] + [""] * (width - 1),
               ["Generated 2026-08-20"] + [""] * (width - 1)]
              + [rows[0], [""] * width] + rows[1:])
    write_tsv(os.path.join(out, "ge-title-rows", "expression.tab"), broken)


@case("ge-annotation-columns", "gene expression", "values",
      "annotation columns interleaved with measurements", "truth")
def _(out):
    rows = read_tsv(os.path.join(GE, "gene_expression_values.tab"))
    header = [rows[0][0], "biotype", rows[0][1], rows[0][2], "chromosome",
              rows[0][3], rows[0][4], "description", rows[0][5], rows[0][6]]
    broken = [header]
    for i, r in enumerate(rows[1:]):
        broken.append([r[0], "protein_coding", r[1], r[2], str(1 + i % 19),
                       r[3], r[4], "predicted gene", r[5], r[6]])
    write_tsv(os.path.join(out, "ge-annotation-columns", "expression.tab"), broken)


@case("ge-latin1", "gene expression", "values",
      "latin-1 encoding, non-UTF-8 bytes", "truth")
def _(out):
    rows = read_tsv(os.path.join(GE, "gene_expression_values.tab"))
    broken = [["#geneID (µ-normalised)"] + rows[0][1:]] + rows[1:]
    write_tsv(os.path.join(out, "ge-latin1", "expression.tab"), broken, encoding="latin-1")


@case("ge-duplicate-ids", "gene expression", "values",
      "duplicated identifiers with conflicting values", "derived")
def _(out):
    rows = read_tsv(os.path.join(GE, "gene_expression_values.tab"))
    broken = list(rows)
    for r in rows[1:41]:
        broken.append([r[0]] + [str(round(float(c) + 0.05, 4)) for c in r[1:]])
    write_tsv(os.path.join(out, "ge-duplicate-ids", "expression.tab"), broken)


@case("ge-crlf-quoted", "gene expression", "values",
      "CRLF line endings and every field quoted", "truth")
def _(out):
    rows = read_tsv(os.path.join(GE, "gene_expression_values.tab"))
    path = os.path.join(out, "ge-crlf-quoted", "expression.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=",", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# Regulatory omics (MORE)
# ---------------------------------------------------------------------------

MORE = os.path.join(DATASETS, "06-regulatory-more", "data")


@case("more-missing-design", "regulatory", "design",
      "experimental design file absent; must be rebuilt from sample names", "derived")
def _(out):
    d = os.path.join(out, "more-missing-design")
    os.makedirs(d, exist_ok=True)
    for name in ("gene_expression_targets.tab", "mirna_regulators.tab",
                 "mirna_associations.tab", "mirna_relevant_regulators.tab"):
        shutil.copy(os.path.join(MORE, name), os.path.join(d, name))
    # experimental_design.tab is deliberately NOT copied.


@case("more-design-labels", "regulatory", "design",
      "design uses condition labels instead of 0/1 indicator columns", "truth")
def _(out):
    rows = read_tsv(os.path.join(MORE, "experimental_design.tab"))
    header, body = rows[0], rows[1:]
    conditions = header[1:]
    broken = [["Sample", "Condition"]]
    for r in body:
        label = next((conditions[i] for i, v in enumerate(r[1:]) if v.strip() == "1"), "")
        broken.append([r[0], label])
    write_tsv(os.path.join(out, "more-design-labels", "experimental_design.tab"), broken)


@case("more-associations-3col", "regulatory", "associations",
      "associations carry a third annotation column", "truth")
def _(out):
    rows = read_tsv(os.path.join(MORE, "mirna_associations.tab"))
    broken = [rows[0] + ["Source"]] + [r + ["TargetScan"] for r in rows[1:]]
    write_tsv(os.path.join(out, "more-associations-3col", "mirna_associations.tab"), broken)


@case("more-associations-swapped", "regulatory", "associations",
      "Target and Regulator columns in the wrong order", "truth")
def _(out):
    rows = read_tsv(os.path.join(MORE, "mirna_associations.tab"))
    broken = [["Regulator", "Target"]] + [[r[1], r[0]] for r in rows[1:]]
    write_tsv(os.path.join(out, "more-associations-swapped", "mirna_associations.tab"), broken)


@case("more-regulators-transposed", "regulatory", "values",
      "regulator matrix transposed", "truth")
def _(out):
    rows = read_tsv(os.path.join(MORE, "mirna_regulators.tab"))
    write_tsv(os.path.join(out, "more-regulators-transposed", "mirna_regulators.tab"),
              [list(col) for col in zip(*rows)])


# ---------------------------------------------------------------------------
# Region-based
# ---------------------------------------------------------------------------

REG = os.path.join(DATASETS, "07-region-based", "data")


@case("region-locus-string", "region-based", "values",
      "coordinates collapsed into one chr1:start-end column", "truth")
def _(out):
    rows = read_tsv(os.path.join(REG, "dnase_regions_values.tab"))
    broken = [["locus"] + rows[0][3:]]
    for r in rows[1:]:
        broken.append(["chr%s:%s-%s" % (r[0], r[1], r[2])] + r[3:])
    write_tsv(os.path.join(out, "region-locus-string", "regions.tab"), broken)


@case("region-chr-prefix", "region-based", "values",
      "chr-prefixed chromosome names and no header", "truth")
def _(out):
    rows = read_tsv(os.path.join(REG, "dnase_regions_values.tab"))
    broken = [["chr" + r[0]] + r[1:] for r in rows[1:]]
    write_tsv(os.path.join(out, "region-chr-prefix", "regions.bed"), broken)


@case("region-extra-bed-columns", "region-based", "values",
      "BED6 layout: name and strand between coordinates and values", "truth")
def _(out):
    rows = read_tsv(os.path.join(REG, "dnase_regions_values.tab"))
    broken = [rows[0][:3] + ["name", "score", "strand"] + rows[0][3:]]
    for i, r in enumerate(rows[1:]):
        broken.append(r[:3] + ["peak_%d" % i, "0", "+" if i % 2 else "-"] + r[3:])
    write_tsv(os.path.join(out, "region-extra-bed-columns", "regions.tab"), broken)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out, exist_ok=True)

    manifest = []
    for c in CASES:
        c["build"](args.out)
        manifest.append({k: c[k] for k in ("id", "module", "role", "breakage", "expects")})

    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    by_module = {}
    for m in manifest:
        by_module.setdefault(m["module"], []).append(m["id"])
    print("built %d cases in %s" % (len(manifest), args.out))
    for mod, ids in by_module.items():
        print("  %-16s %d  %s" % (mod, len(ids), ", ".join(ids)))


if __name__ == "__main__":
    main()
