#!/usr/bin/env python
"""Generate simulated multi-omics data for end-to-end testing.

    python src/AdminTools/scripts/generateSimulatedData.py \
        --specie hsa --outdir /data/CLIENT_TMP/SIMULATED --conditions 3

Why not the existing generateTestData.sh: it assigns every feature an
independent random value. Uniform noise has no pathway structure, so
enrichment finds nothing significant and an end-to-end test built on it cannot
distinguish "the pipeline works" from "the pipeline silently returns nothing".

This plants a known signal instead. A set of target pathways is chosen up
front, their members are given a large consistent shift, and everything else
stays near zero. The chosen pathways are written to `expected_pathways.txt`, so
a test can assert that the pipeline actually recovered them.

Reads `<KEGG_DATA>/current/<specie>/gene2pathway.list` and
`pathway2compound.list` to learn real identifiers, so the output exercises the
same mapping code paths as real user data.
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))


def readTwoColumnMap(filePath, stripPrefixes=()):
    """Parse a `<feature>\\t<pathway>` list into {pathway: [feature, ...]}."""
    grouped = {}
    if not os.path.isfile(filePath):
        return grouped

    with open(filePath) as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            feature, pathway = parts[0], parts[1]
            for prefix in stripPrefixes:
                if feature.startswith(prefix):
                    feature = feature[len(prefix):]
                if pathway.startswith(prefix):
                    pathway = pathway[len(prefix):]
            grouped.setdefault(pathway, []).append(feature)
    return grouped


def writeOmicsFile(path, rows, conditionNames):
    """Write a PaintOmics omics file: name<TAB>value per condition."""
    with open(path, "w") as handle:
        handle.write("#NAME\t" + "\t".join(conditionNames) + "\n")
        for name, values in rows:
            handle.write(name + "\t" + "\t".join(f"{v:.4f}" for v in values) + "\n")
    return path


def writeRelevantFile(path, names):
    with open(path, "w") as handle:
        for name in names:
            handle.write(name + "\n")
    return path


def simulateValues(rng, conditions, isSignal, effectSize, noise):
    """Log2-ratio-like values.

    Signal features get a consistent shift that grows across conditions, which
    is what a dose-response or time-course looks like. Background features are
    centred on zero.
    """
    values = []
    for index in range(conditions):
        if isSignal:
            direction = 1.0 if rng.random() < 0.75 else -1.0
            magnitude = effectSize * (0.5 + 0.5 * (index + 1) / conditions)
            values.append(direction * magnitude + rng.gauss(0, noise))
        else:
            values.append(rng.gauss(0, noise))
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--specie", required=True, help="KEGG organism code, e.g. hsa")
    parser.add_argument("--outdir", required=True, help="where to write the files")
    parser.add_argument("--kegg-data", default=None,
                        help="KEGG_DATA directory (defaults to serverconf.KEGG_DATA_DIR)")
    parser.add_argument("--conditions", type=int, default=3)
    parser.add_argument("--target-pathways", type=int, default=8,
                        help="how many pathways carry a planted signal")
    parser.add_argument("--effect-size", type=float, default=2.5,
                        help="log2 shift applied to signal features")
    parser.add_argument("--noise", type=float, default=0.35)
    parser.add_argument("--seed", type=int, default=20260805,
                        help="fixed so runs are reproducible and comparable")
    args = parser.parse_args()

    keggData = args.kegg_data
    if keggData is None:
        from src.conf.serverconf import KEGG_DATA_DIR
        keggData = KEGG_DATA_DIR

    specieDir = os.path.join(keggData, "current", args.specie)
    if not os.path.isdir(specieDir):
        sys.exit(f"species not installed: {specieDir}\n"
                 f"Run DBManager.py download/install for '{args.specie}' first.")

    rng = random.Random(args.seed)
    os.makedirs(args.outdir, exist_ok=True)

    # ---- genes -----------------------------------------------------------
    pathway2genes = readTwoColumnMap(os.path.join(specieDir, "gene2pathway.list"),
                                     stripPrefixes=("trd:",))
    if not pathway2genes:
        sys.exit(f"no gene2pathway.list under {specieDir}; is the species fully installed?")

    # Only pathways big enough for enrichment to have power.
    eligible = sorted(p for p, g in pathway2genes.items() if len(g) >= 15)
    if len(eligible) < args.target_pathways:
        sys.exit(f"only {len(eligible)} pathways have >=15 genes; "
                 f"cannot plant {args.target_pathways} signals")

    targetPathways = rng.sample(eligible, args.target_pathways)
    signalGenes = set()
    for pathway in targetPathways:
        members = pathway2genes[pathway]
        # 70% of each target pathway moves, which is strong but not artificial.
        signalGenes.update(rng.sample(members, max(1, int(len(members) * 0.7))))

    allGenes = sorted({gene for genes in pathway2genes.values() for gene in genes})
    conditionNames = [f"cond{i+1}" for i in range(args.conditions)]

    geneRows = [
        (gene, simulateValues(rng, args.conditions, gene in signalGenes,
                              args.effect_size, args.noise))
        for gene in allGenes
    ]

    # ---- compounds -------------------------------------------------------
    pathway2compounds = readTwoColumnMap(
        os.path.join(keggData, "current", "common", "pathway2compound.list"),
        stripPrefixes=("path:", "cpd:"))
    # That file is keyed by compound in column 0 and pathway in column 1 for
    # some KEGG releases and the reverse in others. Take whichever orientation
    # actually yields compound identifiers.
    compounds = {c for members in pathway2compounds.values() for c in members
                 if c.startswith("C")}
    if not compounds:
        compounds = {p for p in pathway2compounds if p.startswith("C")}

    allCompounds = sorted(compounds)
    signalCompounds = set(rng.sample(allCompounds, max(1, len(allCompounds) // 10))) \
        if allCompounds else set()
    compoundRows = [
        (compound, simulateValues(rng, args.conditions, compound in signalCompounds,
                                  args.effect_size, args.noise))
        for compound in allCompounds
    ]

    # ---- write -----------------------------------------------------------
    written = []
    written.append(writeOmicsFile(os.path.join(args.outdir, "gene_expression.tab"),
                                  geneRows, conditionNames))
    # A second gene-based omic so multi-omic integration is exercised, drawn
    # from the same signal genes but independently noised.
    proteomicsRows = [
        (gene, simulateValues(rng, args.conditions, gene in signalGenes,
                              args.effect_size * 0.8, args.noise * 1.2))
        for gene, _ in geneRows
    ]
    written.append(writeOmicsFile(os.path.join(args.outdir, "proteomics.tab"),
                                  proteomicsRows, conditionNames))
    written.append(writeRelevantFile(os.path.join(args.outdir, "gene_expression_relevant.tab"),
                                     sorted(signalGenes)))
    written.append(writeRelevantFile(os.path.join(args.outdir, "proteomics_relevant.tab"),
                                     sorted(signalGenes)))

    if compoundRows:
        written.append(writeOmicsFile(os.path.join(args.outdir, "metabolomics.tab"),
                                      compoundRows, conditionNames))
        written.append(writeRelevantFile(os.path.join(args.outdir, "metabolomics_relevant.tab"),
                                         sorted(signalCompounds)))

    expectedPath = os.path.join(args.outdir, "expected_pathways.txt")
    with open(expectedPath, "w") as handle:
        for pathway in sorted(targetPathways):
            handle.write(pathway + "\n")
    written.append(expectedPath)

    print(f"species          : {args.specie}")
    print(f"conditions       : {args.conditions} ({', '.join(conditionNames)})")
    print(f"genes            : {len(geneRows)} ({len(signalGenes)} carrying signal)")
    print(f"compounds        : {len(compoundRows)} ({len(signalCompounds)} carrying signal)")
    print(f"target pathways  : {len(targetPathways)} -> {os.path.basename(expectedPath)}")
    print(f"seed             : {args.seed} (fixed; reruns are identical)")
    print()
    for path in written:
        print("  " + path)


if __name__ == "__main__":
    main()
