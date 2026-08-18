#!/usr/bin/env python3
"""Regenerate gene-to-entrez_osa.tsv.gz -- rice MSU v7 locus -> NCBI GeneID.

GoMapMan keys its rice mapping on MSU v7 loci (LOC_Os01g01010) and publishes a
gene-to-entrez export for ath, sly and stu only, so PaintOmics has to derive
rice's KEGG cross-link. processMapManMappingData() joins column 2 of this file
through KEGG's ncbi-geneid2kegg.list, and KEGG `osa` gene ids ARE NCBI GeneIDs,
so NCBI GeneID is the identifier to land on.

Routes, in priority order:

  1. MSU -> RAP -> GeneID.  RAP-DB's RAP-MSU correspondence table gives
     MSU <-> RAP locus (Os01g0100100). NCBI's gene_info carries the RAP locus
     as an OSNPB_-prefixed locus tag (OSNPB_010100100), which maps back by a
     pure string transform. This is the authoritative route.

  2. Direct MSU citation, as a FALLBACK ONLY for MSU ids route 1 does not
     reach. NCBI gene_info sometimes names the MSU locus in Synonyms or
     Other_designations. Used only where route 1 is silent, never unioned into
     an id route 1 already resolved -- letting it merge inflates fan-out, and
     fan-out is multiplied downstream by the xref `mates` join.

Dead ends, recorded so they are not re-explored: NCBI's Oryza_sativa.gene_info
uses OSNPB_ (RAP-style) locus tags, never MSU, so it cannot be joined to
GoMapMan directly; and KEGG gene entries (rest.kegg.jp/get/osa:4326813) carry
NCBI-GeneID/ProteinID/UniProt but no MSU locus.

Coverage is asymmetric and that is expected: MSU v7 has ~56k loci including
transposable elements and non-coding models that NCBI's curated ~26k gene set
excludes, so the GoMapMan-side percentage is capped near 46% by construction.
The number that matters is the KEGG-side one -- what fraction of KEGG osa genes
a MapMan bin can reach.

Usage:  python3 build_gene_to_entrez_osa.py [--out DIR]
Sources download to a cache dir alongside the output unless already present.
"""
import argparse
import collections
import gzip
import os
import re
import sys
from subprocess import check_call

RAP_MSU_URL = "https://rapdb.dna.affrc.go.jp/download/archive/RAP-MSU_2023-09-07.txt.gz"
GENE_INFO_URL = ("https://ftp.ncbi.nih.gov/gene/DATA/GENE_INFO/Plants/"
                 "Oryza_sativa.gene_info.gz")

MSU_EXACT = re.compile(r'^LOC_Os\d{2}g\d{5}$')
MSU_ANY = re.compile(r'LOC_Os\d{2}g\d{5}')
OSNPB_TAG = re.compile(r'^OSNPB_(\d{2})(\d{7})$')


def fetch(url, target):
    """Download `url` to `target` unless it is already there and non-empty."""
    if os.path.isfile(target) and os.stat(target).st_size > 0:
        sys.stderr.write("using cached " + target + "\n")
        return target
    sys.stderr.write("downloading " + url + "\n")
    # -f so an error page is never stored as data; -L for redirects.
    check_call(["curl", "-f", "-L", "--connect-timeout", "120",
                "--max-time", "1800", url, "-o", target])
    return target


def loadRapToMsu(path):
    """RAP locus -> MSU loci, from RAP-DB's correspondence table."""
    msu2rap = collections.defaultdict(set)
    with gzip.open(path, 'rt', errors='replace') as handle:
        for line in handle:
            fields = line.rstrip('\n').split('\t')
            if len(fields) < 2:
                continue
            rap, msus = fields[0].strip(), fields[1].strip()
            # RAP-DB writes the literal string "None" for an absent side.
            if rap == 'None' or msus == 'None':
                continue
            for msu in msus.split(','):
                # Entries carry transcript suffixes (LOC_Os01g01010.2).
                msu = msu.strip().split('.')[0]
                if MSU_EXACT.match(msu):
                    msu2rap[msu].add(rap)
    return msu2rap


def loadGeneInfo(path):
    """Return (RAP locus -> GeneIDs, MSU locus -> GeneIDs) from NCBI gene_info."""
    rap2gid = collections.defaultdict(set)
    directMsu2gid = collections.defaultdict(set)
    with gzip.open(path, 'rt', errors='replace') as handle:
        for line in handle:
            if line.startswith('#'):
                continue
            fields = line.rstrip('\n').split('\t')
            if len(fields) < 14:
                continue
            geneId, locusTag, synonyms, otherDesignations = (
                fields[1], fields[3], fields[4], fields[13])
            tag = OSNPB_TAG.match(locusTag)
            if tag:
                rap2gid['Os%sg%s' % (tag.group(1), tag.group(2))].add(geneId)
            for token in set(MSU_ANY.findall(synonyms)) | set(MSU_ANY.findall(otherDesignations)):
                directMsu2gid[token].add(geneId)
    return rap2gid, directMsu2gid


def build(msu2rap, rap2gid, directMsu2gid):
    """Apply route 1, then route 2 only where route 1 found nothing."""
    resolved = collections.defaultdict(set)
    for msu, raps in msu2rap.items():
        for rap in raps:
            resolved[msu] |= rap2gid.get(rap, set())
    resolved = {msu: gids for msu, gids in resolved.items() if gids}

    fallbackOnly = 0
    for msu, gids in directMsu2gid.items():
        if msu not in resolved:
            resolved[msu] = set(gids)
            fallbackOnly += 1

    return resolved, fallbackOnly


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)),
                        help="directory to write gene-to-entrez_osa.tsv.gz into")
    parser.add_argument("--cache", default=None,
                        help="directory for downloaded sources (default: --out)")
    args = parser.parse_args()

    cache = args.cache or args.out
    if not os.path.isdir(cache):
        os.makedirs(cache)

    rapMsuPath = fetch(RAP_MSU_URL, os.path.join(cache, "RAP-MSU.txt.gz"))
    geneInfoPath = fetch(GENE_INFO_URL, os.path.join(cache, "Oryza_sativa.gene_info.gz"))

    msu2rap = loadRapToMsu(rapMsuPath)
    rap2gid, directMsu2gid = loadGeneInfo(geneInfoPath)
    resolved, fallbackOnly = build(msu2rap, rap2gid, directMsu2gid)

    rows = sorted((msu, gid) for msu, gids in resolved.items() for gid in gids)
    outPath = os.path.join(args.out, "gene-to-entrez_osa.tsv.gz")
    # mtime=0 so rebuilding identical input produces an identical archive.
    with gzip.GzipFile(outPath, 'wb', compresslevel=9, mtime=0) as out:
        for msu, gid in rows:
            out.write(('%s\t%s\n' % (msu, gid)).encode('ascii'))

    fanOut = sum(1 for gids in resolved.values() if len(gids) > 1)
    sys.stderr.write(
        "wrote %s\n  %d pairs, %d distinct MSU loci, %d distinct GeneIDs\n"
        "  %d MSU loci resolved by the gene_info fallback only\n"
        "  %d MSU loci map to more than one GeneID\n"
        % (outPath, len(rows), len(resolved),
           len({gid for _, gid in rows}), fallbackOnly, fanOut))


if __name__ == "__main__":
    main()
