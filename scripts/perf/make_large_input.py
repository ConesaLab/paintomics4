#!/usr/bin/env python3
"""Generate tests/perf/large_input/: a realistically sized multi-omics
submission for profiling, built from REAL identifiers of the installed mouse
database so that mapping, enrichment and painting do the work a real job does.

This is deliberately not one of the example fixtures (they are small and
curated to light up planted pathways). The shape here is what a whole-genome
experiment looks like when it arrives through the submission form:

    gene expression   20,000 Ensembl gene IDs  x 6 conditions   (relevant: 2,000)
    proteomics         5,000 UniProt accessions x 6 conditions  (relevant:   500)
    metabolomics         400 KEGG compound IDs  x 6 conditions  (relevant:    80)

Identifiers are sampled from the mmu-paintomics `xref` collection (ensembl_gene,
uniprot_acc) and from the compounds the mmu KEGG pathways carry, sorted before
sampling so the draw is a pure function of the seed. Values are log2 ratios:
N(0, 0.6) noise, plus a condition-dependent shift for the relevant features so
that the enrichment has something to find. Everything is seeded (20260822).

    PAINTOMICS_KEGG_DATA=... python scripts/perf/make_large_input.py

Writes the six data files, a manifest.json perf_run.py reads, and a README.
Re-running produces byte-identical files as long as the database snapshot is
the same.
"""
import argparse
import json
import os
import sys

import numpy as np
from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(REPO, "tests", "perf", "large_input")

SEED = 20260822
CONDITIONS = ["T00h", "T02h", "T06h", "T12h", "T24h", "T48h"]
ORGANISM = "mmu"

OMICS = [
    # name, identifier source, how many, how many relevant, file stem, enrichment
    ("Gene expression", "ensembl_gene", 20000, 2000, "gene_expression", "genes"),
    ("Proteomics", "uniprot_acc", 5000, 500, "proteomics", "features"),
    ("Metabolomics", "kegg_compound", 400, 80, "metabolomics", "features"),
]


def identifiers(client, source):
    db = client[ORGANISM + "-paintomics"]
    if source == "kegg_compound":
        ids = set()
        for pathway in db.kegg.find({}, {"compounds.id": 1}):
            for compound in pathway.get("compounds", []):
                cid = compound.get("id")
                if cid and cid.startswith("C") and cid[1:].isdigit():
                    ids.add(cid)
        return sorted(ids)
    dbname = db.dbname.find_one({"dbname": source})
    if dbname is None:
        raise SystemExit("no %s namespace in %s-paintomics" % (source, ORGANISM))
    return sorted({doc["display_id"] for doc in db.xref.find({"dbname_id": dbname["_id"]}, {"display_id": 1})})


def write_omic(rng, name, ids, count, relevant_count, stem, enrichment):
    if len(ids) < count:
        raise SystemExit("only %d %s identifiers available, %d wanted" % (len(ids), name, count))
    chosen = sorted(rng.choice(ids, size=count, replace=False).tolist())
    relevant = set(rng.choice(chosen, size=relevant_count, replace=False).tolist())
    values = rng.normal(0.0, 0.6, size=(count, len(CONDITIONS)))
    # the relevant features move together along the time course: a ramp with
    # a per-feature sign and amplitude, so the signal is real but not uniform
    ramp = np.linspace(0.0, 1.0, len(CONDITIONS))
    for row, feature in enumerate(chosen):
        if feature in relevant:
            amplitude = rng.uniform(1.5, 4.0) * rng.choice([-1.0, 1.0])
            values[row] += amplitude * ramp
    data_path = os.path.join(OUT, stem + "_values.tab")
    with open(data_path, "w", encoding="utf-8") as handle:
        handle.write("#ID\t" + "\t".join(CONDITIONS) + "\n")
        for row, feature in enumerate(chosen):
            handle.write(feature + "\t" + "\t".join("%.4f" % v for v in values[row]) + "\n")
    relevant_path = os.path.join(OUT, stem + "_relevant.tab")
    with open(relevant_path, "w", encoding="utf-8") as handle:
        for feature in chosen:
            if feature in relevant:
                handle.write(feature + "\n")
    return {"omicName": name, "dataFile": os.path.basename(data_path),
            "relevantFile": os.path.basename(relevant_path),
            "omicType": "compound" if enrichment == "features" and stem == "metabolomics" else "gene",
            "enrichment": enrichment, "features": count, "relevant": relevant_count}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mongo-host", default=os.environ.get("MONGODB_HOST", "localhost"))
    parser.add_argument("--mongo-port", type=int, default=int(os.environ.get("MONGODB_PORT", "27017")))
    args = parser.parse_args(argv)

    client = MongoClient(args.mongo_host, args.mongo_port, serverSelectionTimeoutMS=10000)
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(SEED)
    manifest = {"organism": ORGANISM, "conditions": CONDITIONS, "seed": SEED, "omics": []}
    for name, source, count, relevant, stem, enrichment in OMICS:
        ids = identifiers(client, source)
        entry = write_omic(rng, name, ids, count, relevant, stem, enrichment)
        entry["identifierSource"] = source
        entry["identifiersAvailable"] = len(ids)
        manifest["omics"].append(entry)
        print("%-16s %6d of %6d %-13s ids, %4d relevant -> %s" % (
            name, count, len(ids), source, relevant, entry["dataFile"]))
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as handle:
        handle.write(README)
    return 0


README = """# Large profiling input

A whole-genome-scale mouse submission for `scripts/perf/perf_run.py` and the
py-spy profile in `reports/profile-*.txt`. Generated by
`scripts/perf/make_large_input.py` from real identifiers of the installed
mmu database (KEGG snapshot 20260813), seeded, so it reproduces byte for byte
against the same snapshot. It is not one of the example fixtures and is not
part of the regression baseline.

| omic | identifiers | features x conditions | relevant |
|---|---|---:|---:|
| Gene expression | Ensembl gene IDs | 20,000 x 6 | 2,000 |
| Proteomics | UniProt accessions | 5,000 x 6 | 500 |
| Metabolomics | KEGG compound IDs | 400 x 6 | 80 |

Values are log2 ratios: N(0, 0.6) noise plus a ramp over the time course for
the relevant features. `manifest.json` tells perf_run.py which file is which.
"""


if __name__ == "__main__":
    sys.exit(main())
