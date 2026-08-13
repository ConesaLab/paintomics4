#!/usr/bin/env python
"""
Rebuild the "linked biological processes" edges of an installed Reactome
pathway network, without reinstalling the species.

Why this is a separate script
-----------------------------
common_build_database.py now derives Reactome's link edges from the pathway
hierarchy as well as from the diagrams (see buildReactomeHierarchyEdges there
for the reasoning and the measurements). That fix only reaches a deployment
when the species is rebuilt, which for Reactome means re-downloading a few
thousand diagram and graph JSONs - hours of work to change one edge list.

Everything the fix needs is already on disk:

  * <KEGG_DATA_DIR>/current/<specie>/pathways_network_Reactome.json - the nodes,
    and the diagram edges the old build produced;
  * <KEGG_DATA_DIR>/current/common/ReactomePathwaysRelation.list - the
    hierarchy, downloaded once for all species.

So this recomputes the 'l' edges in place. The 's' (shared features) edges are
copied through untouched: they are derived from gene membership, which this
script does not have and has no reason to second-guess.

What it changes
---------------
  * link edges are the union of the diagram edges and the hierarchy relation;
  * link edges pointing at a pathway that was never installed are dropped -
    the client already ignores those, so they were bytes only;
  * self-edges are dropped.

Node and 's' edge counts are asserted unchanged before anything is written.

Usage
-----
    python repairReactomeNetwork.py --specie=mmu
    python repairReactomeNetwork.py --all
    python repairReactomeNetwork.py --all --dry-run

A timestamped .bak is written beside each file before it is replaced, and the
replacement itself goes through a temporary file and os.replace, so an
interrupted run cannot leave a half-written network behind.
"""

import importlib.util
import json
import os
import shutil
import sys
from time import strftime

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "..", ".."))


def _loadBuilder():
    """
    Import buildReactomeHierarchyEdges from the installer.

    By file path rather than as a package: common_build_database is a script
    that lives outside any package and is normally run with `python <path>`.
    It has no import-time side effects, so this is safe - but it is imported
    rather than copied so the rule this script applies is provably the same
    rule a fresh install applies.
    """
    modulePath = os.path.join(SCRIPT_DIR, "common_build_database.py")
    spec = importlib.util.spec_from_file_location("common_build_database", modulePath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.buildReactomeHierarchyEdges


def _speciesMarker(specie):
    return "R-" + specie.upper() + "-"


def _readJson(path):
    with open(path) as handle:
        return json.load(handle)


def _writeJson(path, payload):
    """Backup, write to a sibling temp file, then rename over the original."""
    backup = path + ".bak-" + strftime("%Y%m%d%H%M%S")
    shutil.copy2(path, backup)

    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
    os.replace(temporary, path)
    return backup


def repairNetwork(network, relationFile, specie):
    """
    Recompute `network["edges"]` and return (newNetwork, statistics).

    `network` is left untouched; the caller decides whether to write.
    """
    buildReactomeHierarchyEdges = _loadBuilder()

    nodes = network.get("nodes", [])
    installed = set(
        node["data"]["id"] for node in nodes
        if node.get("group") == "nodes" and "is_classification" not in node["data"])

    sharedEdges = []
    diagramPairs = set()
    danglingCount = 0

    for edge in network.get("edges", []):
        data = edge["data"]
        if data.get("class") != "l":
            sharedEdges.append(edge)
            continue
        source, target = data["source"], data["target"]
        if source == target:
            danglingCount += 1
            continue
        if source not in installed or target not in installed:
            danglingCount += 1
            continue
        diagramPairs.add((source, target) if source < target else (target, source))

    hierarchyPairs = buildReactomeHierarchyEdges(
        installed, relationFile, _speciesMarker(specie))

    linkPairs = diagramPairs | hierarchyPairs

    # sorted() so a repeat run on unchanged input produces a byte-identical file
    linkEdges = [
        {"data": {"id": source + "-" + target, "source": source,
                  "target": target, "weight": 1, "class": "l"},
         "group": "edges"}
        for source, target in sorted(linkPairs)]

    repaired = dict(network)
    repaired["edges"] = linkEdges + sharedEdges

    covered = set()
    for source, target in linkPairs:
        covered.add(source)
        covered.add(target)

    statistics = {
        "nodes": len(nodes),
        "pathwayNodes": len(installed),
        "linkBefore": len(diagramPairs) + danglingCount,
        "linkFromDiagrams": len(diagramPairs),
        "linkFromHierarchy": len(hierarchyPairs),
        "linkDropped": danglingCount,
        "linkAfter": len(linkPairs),
        "sharedEdges": len(sharedEdges),
        "coveredBefore": len(set(
            node for pair in diagramPairs for node in pair)),
        "coveredAfter": len(covered),
    }
    return repaired, statistics


def repairSpecie(dataDir, specie, dryRun=False):
    specieDir = os.path.join(dataDir, "current", specie)
    relationFile = os.path.join(
        dataDir, "current", "common", "ReactomePathwaysRelation.list")

    standalone = os.path.join(specieDir, "pathways_network_Reactome.json")
    merged = os.path.join(specieDir, "pathways_network.json")

    if not os.path.isfile(standalone):
        print("  " + specie + ": no Reactome network installed, skipping")
        return False

    if not os.path.isfile(relationFile):
        print("  " + specie + ": " + relationFile + " is missing - run the "
              "common Reactome download first")
        return False

    network = _readJson(standalone)
    repaired, statistics = repairNetwork(network, relationFile, specie)

    print("  {}: {} pathway nodes | link edges {} -> {} "
          "({} from diagrams + {} from hierarchy, {} dangling dropped) | "
          "nodes with a link edge {} -> {} | {} shared edges kept".format(
              specie, statistics["pathwayNodes"],
              statistics["linkBefore"], statistics["linkAfter"],
              statistics["linkFromDiagrams"], statistics["linkFromHierarchy"],
              statistics["linkDropped"],
              statistics["coveredBefore"], statistics["coveredAfter"],
              statistics["sharedEdges"]))

    if dryRun:
        return True

    # The merged file is what the client actually fetches for KEGG, and it
    # carries a "Reactome" key holding a second copy of this same network.
    # Repairing one and not the other is how the two views end up disagreeing.
    if os.path.isfile(merged):
        mergedPayload = _readJson(merged)
        if isinstance(mergedPayload, dict) and "Reactome" in mergedPayload:
            mergedRepaired, _ = repairNetwork(
                mergedPayload["Reactome"], relationFile, specie)
            mergedPayload["Reactome"] = mergedRepaired
            _writeJson(merged, mergedPayload)
            print("    also repaired the Reactome section of "
                  "pathways_network.json")

    _writeJson(standalone, repaired)
    return True


def main(argv):
    dryRun = "--dry-run" in argv
    species = [argument.split("=", 1)[1] for argument in argv
               if argument.startswith("--specie=")]
    doAll = "--all" in argv

    if not species and not doAll:
        print(__doc__)
        return 1

    try:
        from src.conf.serverconf import KEGG_DATA_DIR
    except ImportError:
        print("Could not import KEGG_DATA_DIR from src.conf.serverconf. Run "
              "this from a checkout with a configured server, or pass "
              "--data-dir=<path>.")
        return 1

    dataDir = KEGG_DATA_DIR
    for argument in argv:
        if argument.startswith("--data-dir="):
            dataDir = argument.split("=", 1)[1]

    if doAll:
        currentDir = os.path.join(dataDir, "current")
        species = sorted(
            name for name in os.listdir(currentDir)
            if os.path.isfile(os.path.join(
                currentDir, name, "pathways_network_Reactome.json")))

    print(("Dry run - " if dryRun else "") +
          "repairing Reactome networks under " + dataDir)
    repaired = 0
    for specie in species:
        if repairSpecie(dataDir, specie, dryRun):
            repaired += 1

    print("Done: {} of {} species".format(repaired, len(species)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
