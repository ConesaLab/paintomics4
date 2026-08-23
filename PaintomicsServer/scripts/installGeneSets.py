#!/usr/bin/env python3
"""Install GO (from an OBO + a GAF) and/or a GMT collection for one organism.

Usage (mouse GO from the GO Consortium's current release):

    python scripts/installGeneSets.py --organism mmu \
        --obo http://purl.obolibrary.org/obo/go/go-basic.obo \
        --gaf http://current.geneontology.org/annotations/mgi.gaf.gz

    python scripts/installGeneSets.py --organism hsa \
        --gmt h.all.v2024.1.Hs.symbols.gmt --gmt-source Hallmark

What it writes: one document per set into `<organism>-paintomics.geneSets`
({source, id, name, genes, parents}), replacing the SOURCE being installed
and nothing else. Annotations are propagated to every ancestor before
storage (the true-path rule), so runtime enrichment needs no DAG walk; the
parent links are stored anyway because the elim refinement does need them.

Honesty rules learned from the other installers in this tree: a download is
verified by CONTENT, not status (a 200 serving an HTML error page must not
become the database); `NOT` qualifiers are skipped; obsolete terms are
skipped; an install that parsed nothing refuses to touch Mongo.
"""
from __future__ import annotations

import argparse
import gzip
import io
import os
import sys
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def fetch(path_or_url):
    """Bytes of a local file or URL; .gz is transparently decompressed."""
    if "://" in path_or_url:
        req = urllib.request.Request(path_or_url,
                                     headers={"User-Agent": "paintomics4"})
        with urllib.request.urlopen(req, timeout=300) as fh:
            blob = fh.read()
    else:
        with open(path_or_url, "rb") as fh:
            blob = fh.read()
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return blob


def parse_obo(text):
    """({term_id: {name, namespace, parents}}, {alt_id: canonical}).

    Keeps `is_a` and `relationship: part_of` (the two edges the true-path
    rule runs over), skips obsolete terms, records alt_ids so an annotation
    to a merged id still lands.
    """
    terms, alt = {}, {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if line == "[Term]":
            current = {"id": None, "name": "", "namespace": "",
                       "parents": [], "obsolete": False, "alts": []}
            continue
        if line.startswith("[") and line != "[Term]":
            current = None
            continue
        if current is None or not line:
            if current is not None and not line and current.get("id"):
                if not current["obsolete"]:
                    terms[current["id"]] = {
                        "name": current["name"],
                        "namespace": current["namespace"],
                        "parents": current["parents"]}
                    for a in current["alts"]:
                        alt[a] = current["id"]
                current = None
            continue
        if line.startswith("id: "):
            current["id"] = line[4:].strip()
        elif line.startswith("name: "):
            current["name"] = line[6:].strip()
        elif line.startswith("namespace: "):
            current["namespace"] = line[11:].strip()
        elif line.startswith("is_a: "):
            current["parents"].append(line[6:].split("!")[0].strip())
        elif line.startswith("relationship: part_of "):
            current["parents"].append(
                line[len("relationship: part_of "):].split("!")[0].strip())
        elif line.startswith("is_obsolete: true"):
            current["obsolete"] = True
        elif line.startswith("alt_id: "):
            current["alts"].append(line[8:].strip())
    if current is not None and current.get("id") and not current["obsolete"]:
        terms[current["id"]] = {"name": current["name"],
                                "namespace": current["namespace"],
                                "parents": current["parents"]}
        for a in current["alts"]:
            alt[a] = current["id"]
    return terms, alt


def parse_gaf(text):
    """[(symbol, go_id, aspect)] with NOT-qualified rows skipped."""
    out = []
    for raw in text.splitlines():
        if not raw or raw.startswith("!"):
            continue
        cols = raw.split("\t")
        if len(cols) < 9:
            continue
        qualifier, go_id, aspect = cols[3], cols[4], cols[8]
        symbol = cols[2].strip()
        if not symbol or not go_id.startswith("GO:"):
            continue
        if "NOT" in (qualifier or "").split("|"):
            continue
        out.append((symbol.upper(), go_id, aspect.strip().upper()))
    return out


NAMESPACE_SOURCE = {"biological_process": "GO_BP",
                    "molecular_function": "GO_MF",
                    "cellular_component": "GO_CC"}
ASPECT_NAMESPACE = {"P": "biological_process", "F": "molecular_function",
                    "C": "cellular_component"}


def propagate(terms, alt, annotations):
    """{term_id: set(symbols)} with every annotation on every ancestor."""
    ancestors_cache = {}

    def ancestors(term):
        if term in ancestors_cache:
            return ancestors_cache[term]
        out, stack = set(), list(terms.get(term, {}).get("parents") or [])
        while stack:
            p = stack.pop()
            if p in out or p not in terms:
                continue
            out.add(p)
            stack.extend(terms[p].get("parents") or [])
        ancestors_cache[term] = out
        return out

    sets = {}
    dropped = 0
    for symbol, go_id, aspect in annotations:
        go_id = alt.get(go_id, go_id)
        if go_id not in terms:
            dropped += 1
            continue
        expected = ASPECT_NAMESPACE.get(aspect)
        if expected and terms[go_id]["namespace"] != expected:
            # A GAF row whose aspect disagrees with the ontology is a data
            # defect; trust the ontology.
            pass
        sets.setdefault(go_id, set()).add(symbol)
        for anc in ancestors(go_id):
            sets.setdefault(anc, set()).add(symbol)
    return sets, dropped


def looks_like_html(blob):
    head = blob[:200].lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def install_go(db, organism, obo_src, gaf_src, min_genes=3):
    obo_blob = fetch(obo_src)
    if looks_like_html(obo_blob) or b"format-version:" not in obo_blob[:200]:
        raise SystemExit("OBO from %s does not look like an OBO file "
                         "(a 200 serving an error page?); nothing installed"
                         % obo_src)
    gaf_blob = fetch(gaf_src)
    if looks_like_html(gaf_blob):
        raise SystemExit("GAF from %s looks like HTML; nothing installed"
                         % gaf_src)
    terms, alt = parse_obo(obo_blob.decode("utf-8", "replace"))
    annotations = parse_gaf(gaf_blob.decode("utf-8", "replace"))
    if not terms or not annotations:
        raise SystemExit("parsed %d terms and %d annotations; refusing to "
                         "write an empty install" % (len(terms),
                                                     len(annotations)))
    sets, dropped = propagate(terms, alt, annotations)
    docs_by_source = {}
    for go_id, symbols in sets.items():
        if len(symbols) < min_genes:
            continue
        source = NAMESPACE_SOURCE.get(terms[go_id]["namespace"])
        if source is None:
            continue
        parents = [p for p in terms[go_id]["parents"] if p in terms]
        docs_by_source.setdefault(source, []).append(
            {"source": source, "id": go_id, "name": terms[go_id]["name"],
             "genes": sorted(symbols), "parents": parents})
    for source, docs in sorted(docs_by_source.items()):
        db["geneSets"].delete_many({"source": source})
        db["geneSets"].insert_many(docs)
        print("%s: %d sets installed for %s" % (source, len(docs), organism))
    if dropped:
        print("(%d annotations referenced terms absent from the OBO)" % dropped)


def install_gmt(db, organism, gmt_src, source, min_genes=3):
    blob = fetch(gmt_src)
    if looks_like_html(blob):
        raise SystemExit("GMT from %s looks like HTML; nothing installed"
                         % gmt_src)
    docs = []
    for line in blob.decode("utf-8", "replace").splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3 or not parts[0]:
            continue
        genes = sorted({g.upper() for g in parts[2:] if g})
        if len(genes) < min_genes:
            continue
        docs.append({"source": source, "id": parts[0],
                     "name": parts[1] or parts[0], "genes": genes,
                     "parents": []})
    if not docs:
        raise SystemExit("parsed no sets from %s; refusing to write" % gmt_src)
    db["geneSets"].delete_many({"source": source})
    db["geneSets"].insert_many(docs)
    print("%s: %d sets installed for %s" % (source, len(docs), organism))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--organism", required=True, help="KEGG code, e.g. mmu")
    ap.add_argument("--obo", help="go-basic.obo path or URL")
    ap.add_argument("--gaf", help="GAF path or URL (may be .gz)")
    ap.add_argument("--gmt", help="GMT path or URL")
    ap.add_argument("--gmt-source", default="Hallmark",
                    help="source label for the GMT (default Hallmark)")
    ap.add_argument("--min-genes", type=int, default=3)
    args = ap.parse_args()

    if not ((args.obo and args.gaf) or args.gmt):
        ap.error("give --obo with --gaf, and/or --gmt")

    from pymongo import MongoClient
    from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
    client = MongoClient(MONGODB_HOST, MONGODB_PORT)
    db = client[args.organism + "-paintomics"]
    db["geneSets"].create_index([("source", 1), ("id", 1)], unique=True)
    try:
        if args.obo and args.gaf:
            install_go(db, args.organism, args.obo, args.gaf, args.min_genes)
        if args.gmt:
            install_gmt(db, args.organism, args.gmt, args.gmt_source,
                        args.min_genes)
    finally:
        client.close()


if __name__ == "__main__":
    main()
