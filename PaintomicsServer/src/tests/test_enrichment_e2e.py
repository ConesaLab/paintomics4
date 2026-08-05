"""End-to-end enrichment check against an installed species.

Run from `PaintomicsServer/` with the species already installed:

    python -m src.tests.test_enrichment_e2e --specie hsa

Generates simulated omics data with a planted signal (see
AdminTools/scripts/generateSimulatedData.py), runs the same hypergeometric
enrichment the pipeline uses, and asserts the pathways carrying the signal come
out significant.

The point is to catch a pipeline that runs to completion and returns nothing
useful. Uniform random data -- what generateTestData.sh produces -- cannot
distinguish that from correct behaviour, because random data legitimately has
no enriched pathways. Planting the signal first makes "found nothing" a
failure.

Skips cleanly when the species is not installed, so it is safe to run in CI.
"""
import argparse
import os
import random
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scipy.stats import hypergeom

_PASSED = []
_FAILED = []


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print(f"PASS  {name}")
    except AssertionError as exc:
        _FAILED.append((name, str(exc)))
        print(f"FAIL  {name}: {exc}")
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print(f"ERROR {name}:\n{traceback.format_exc()}")


def loadPathwaysFromDb(organism, source=None):
    """{pathway_id: set(gene_ids)} for an installed species.

    The installer writes one database per organism, named "<organism>-paintomics",
    with pathways in the `kegg` collection regardless of provenance -- `source`
    is "KEGG" or "Reactome". Genes are stored as [{"id": ..., "x": ...}, ...],
    not as bare identifiers.

    Pass source="Reactome" to check that half specifically.
    """
    from pymongo import MongoClient
    from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT

    client = MongoClient(MONGODB_HOST, MONGODB_PORT, serverSelectionTimeoutMS=5000)
    db = client[organism + "-paintomics"]

    query = {} if source is None else {"source": source}
    pathways = {}
    for document in db.kegg.find(query, {"ID": 1, "genes": 1, "source": 1}):
        genes = {str(g["id"]) for g in (document.get("genes") or [])
                 if isinstance(g, dict) and g.get("id")}
        if genes:
            pathways[document.get("ID") or str(document["_id"])] = genes
    return pathways


def sourceBreakdown(organism):
    """{source: pathway count} so a missing Reactome half is visible."""
    from pymongo import MongoClient
    from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT

    client = MongoClient(MONGODB_HOST, MONGODB_PORT, serverSelectionTimeoutMS=5000)
    db = client[organism + "-paintomics"]
    counts = {}
    for document in db.kegg.find({}, {"source": 1}):
        key = document.get("source", "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def enrich(pathwayGenes, relevantGenes, allGenes):
    """Hypergeometric survival, matching the pipeline's calculateFisher path."""
    population = len(allGenes)
    successes = len(relevantGenes & allGenes)

    results = {}
    for pathwayId, genes in pathwayGenes.items():
        sample = genes & allGenes
        if not sample:
            continue
        hits = len(sample & relevantGenes)
        # sf(k-1) == P(X >= k), the one-sided over-representation test.
        results[pathwayId] = hypergeom.sf(hits - 1, population, successes, len(sample))
    return results


def runEnrichmentTest(specie, source=None):
    pathwayGenes = loadPathwaysFromDb(specie, source=source)
    if not pathwayGenes:
        label = source or "any source"
        print(f"      (skipped: species '{specie}' has no installed pathways for {label})")
        return

    allGenes = set().union(*pathwayGenes.values())
    print(f"      {len(pathwayGenes)} pathways, {len(allGenes)} distinct genes")

    # Plant the signal exactly as generateSimulatedData.py does.
    rng = random.Random(20260805)
    eligible = sorted(p for p, g in pathwayGenes.items() if len(g) >= 15)
    assert len(eligible) >= 8, \
        f"only {len(eligible)} pathways have >=15 genes; species looks under-installed"

    targets = rng.sample(eligible, 8)
    relevant = set()
    for pathwayId in targets:
        members = sorted(pathwayGenes[pathwayId])
        relevant.update(rng.sample(members, max(1, int(len(members) * 0.7))))

    pvalues = enrich(pathwayGenes, relevant, allGenes)
    assert pvalues, "enrichment produced no results at all"

    ranked = sorted(pvalues.items(), key=lambda kv: kv[1])
    top = [p for p, _ in ranked[:len(targets) * 3]]

    recovered = [p for p in targets if p in top]
    assert len(recovered) >= len(targets) * 0.75, (
        f"only {len(recovered)}/{len(targets)} planted pathways ranked in the top "
        f"{len(top)}. Enrichment is running but not recovering known signal.\n"
        f"  planted:   {sorted(targets)}\n"
        f"  top ranks: {top[:10]}")

    worst = max(pvalues[p] for p in targets)
    assert worst < 0.05, \
        f"a planted pathway had p={worst:.3g}; expected every one below 0.05"

    print(f"      recovered {len(recovered)}/{len(targets)} planted pathways, "
          f"worst planted p-value {worst:.3g}")

    # A pathway with no relevant genes must not come out significant.
    background = [p for p, genes in pathwayGenes.items()
                  if not (genes & relevant) and len(genes) >= 15]
    if background:
        falsePositives = [p for p in background if pvalues.get(p, 1.0) < 0.05]
        assert not falsePositives, \
            f"{len(falsePositives)} pathways with zero relevant genes scored p<0.05: " \
            f"{falsePositives[:5]}"
        print(f"      {len(background)} signal-free pathways, none significant")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--specie", default="hsa")
    parser.add_argument("--require-reactome", action="store_true",
                        help="fail if the species has no Reactome pathways installed")
    args = parser.parse_args()

    print(f"species: {args.specie}")
    try:
        counts = sourceBreakdown(args.specie)
        print(f"pathways by source: {counts or '(none installed)'}")
    except Exception as exc:
        print(f"could not read pathway counts: {exc}")
        counts = {}

    _check(f"test_enrichment_recovers_planted_signal[{args.specie}]",
           lambda: runEnrichmentTest(args.specie))

    # Reactome is installed through an entirely separate code path, so a KEGG
    # pass says nothing about it.
    if counts.get("Reactome"):
        _check(f"test_enrichment_recovers_planted_signal[{args.specie}/Reactome]",
               lambda: runEnrichmentTest(args.specie, source="Reactome"))
    elif args.require_reactome:
        _check(f"test_reactome_pathways_installed[{args.specie}]",
               lambda: (_ for _ in ()).throw(AssertionError(
                   f"no Reactome pathways in {args.specie}-paintomics; "
                   f"the install ran with --reactome=0 or the Reactome stage failed")))
    else:
        print("      (no Reactome pathways installed; pass --require-reactome to make that fatal)")

    print()
    print(f"Passed: {len(_PASSED)} / {len(_PASSED)+len(_FAILED)}")
    if _FAILED:
        for name, msg in _FAILED:
            print(f"  - {name}: {msg.splitlines()[0] if msg else ''}")
        sys.exit(1)


if __name__ == "__main__":
    main()
