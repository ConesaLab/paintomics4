#!/usr/bin/env python3
"""Build the bundled example datasets and their manifest.

    cd PaintomicsServer
    python -m src.AdminTools.scripts.exampledata                    # all scenarios
    python -m src.AdminTools.scripts.exampledata --scenario region-based
    python -m src.AdminTools.scripts.exampledata --list

Output goes to `src/examplefiles/datasets/` by default. The generated files are
**committed**: the deployed server then needs no KEGG snapshot to serve
examples, and the tests have something fixed to assert against.

Determinism is the property that makes committing them safe. Same seed, same
KEGG snapshot, byte-identical output -- so `git diff` after a regeneration is
empty unless the data genuinely changed, and a non-empty diff is a review item
rather than noise.

Regenerating one scenario rewrites only that scenario's directory, but always
rewrites the manifest, because the manifest is a whole-catalogue document.
"""
import argparse
import json
import os
import sys

# Run as `python -m src.AdminTools.scripts.exampledata` from PaintomicsServer/;
# this makes it work from anywhere by putting the server root on the path.
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..")))

from src.AdminTools.scripts.exampledata import legacy, scenarios      # noqa: E402
from src.AdminTools.scripts.exampledata.keggsource import (           # noqa: E402
    KeggSource, SpeciesNotInstalled)
from src.common import ExampleDatasets                                # noqa: E402

DEFAULT_SEED = 20260809
MANIFEST_VERSION = 1

# What "Load example" gives someone who does not choose. The real data, which is
# the behaviour that exists today; the simulated scenarios are opt-in.
DEFAULT_SCENARIO = "stategra-multiomics"


def serverRoot():
    return os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        "..", "..", "..", ".."))


def defaultOutputDir():
    return os.path.join(serverRoot(), "src", "examplefiles", "datasets")


def writeReadme(outputRoot, entry):
    """A human-readable card per scenario, generated from its manifest entry.

    Generated rather than hand-written so it cannot drift from the manifest --
    a README claiming a file that the manifest does not list is worse than no
    README, because it is believed.
    """
    folder = _folderFor(outputRoot, entry)
    if folder is None:
        return None

    lines = [
        "# %s" % entry["title"],
        "",
        entry["summary"],
        "",
        "|  |  |",
        "| --- | --- |",
        "| **id** | `%s`" % entry["id"] + " |",
        "| **pipeline** | `%s` |" % entry["pipeline"],
        "| **organism** | `%s` |" % entry["organism"],
        "| **conditions** | %d (%s) |" % (len(entry.get("conditions", [])),
                                          ", ".join(entry.get("conditions", []))),
        "| **simulated** | %s |" % ("yes" if entry.get("simulated") else "no, real data"),
        "",
        "## What it exercises",
        "",
    ]
    lines.extend("* %s" % item for item in entry.get("tests", []))
    lines += ["", "## Files", ""]

    for omic in entry.get("omics", []):
        lines.append("**%s**" % omic["omicName"])
        for label, key in (("values", "dataFile"),
                           ("relevant features", "relevantFile"),
                           ("associations", "associationsFile")):
            if omic.get(key):
                lines.append("* %s — `%s`" % (label, os.path.basename(omic[key])))
        lines.append("")

    if entry.get("target"):
        lines += ["**Target omic (MORE)**",
                  "* values — `%s`" % os.path.basename(entry["target"]["dataFile"]),
                  ""]
    if entry.get("design"):
        lines += ["**Experimental design**",
                  "* `%s`" % os.path.basename(entry["design"]["dataFile"]), ""]
    for reference in entry.get("references", []):
        lines += ["**Reference (%s)**" % reference["omicName"],
                  "* `%s`" % os.path.basename(reference["dataFile"]), ""]
    for extra in entry.get("extraFiles", []):
        lines += ["**Extra — %s**" % extra["role"],
                  "* `%s`" % os.path.basename(extra["path"]),
                  "* %s" % extra["note"], ""]

    expected = entry.get("expected", {})
    if expected:
        lines += ["## Expected result", ""]
        for key in sorted(expected):
            value = expected[key]
            if key.endswith("File"):
                value = "`%s`" % os.path.basename(str(value))
            lines.append("* **%s** — %s" % (key, value))
        lines.append("")

    # Where the data came from, for scenarios that carry measurements this
    # project did not produce. A simulated scenario needs no such section: its
    # generator *is* its provenance. A real one does, and the absence of it is
    # how a reduced copy came to be described as "the published dataset".
    provenance = entry.get("provenance", [])
    if provenance:
        lines += ["## Provenance", ""] + list(provenance) + [""]

    lines += ["---", ""]
    if provenance:
        lines += ["This README is generated by `src/AdminTools/scripts/exampledata` "
                  "from the manifest entry; do not edit it by hand, regenerate "
                  "instead. The **data files are registered, not generated** — "
                  "nothing in this project can rebuild them. See Provenance above.",
                  ""]
    else:
        lines += ["Generated by `src/AdminTools/scripts/exampledata`. Do not edit by "
                  "hand; regenerate instead.", ""]

    path = os.path.join(folder, "README.md")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    return path


def _folderFor(outputRoot, entry):
    """The scenario's directory, found from any path it declares.

    The manifest stores EXAMPLE_FILES_DIR-relative paths like
    `datasets/07-region-based/data/x.tab`; the folder is the grandparent of the
    first such path. Derived rather than stored so the entry has one fewer
    field to keep consistent.
    """
    candidates = []
    for omic in entry.get("omics", []):
        candidates.extend(omic.get(key) for key in
                          ("dataFile", "relevantFile", "associationsFile"))
    if entry.get("target"):
        candidates.append(entry["target"].get("dataFile"))
    for reference in entry.get("references", []):
        candidates.append(reference.get("dataFile"))

    for candidate in candidates:
        if not candidate:
            continue
        parts = candidate.split("/")
        if len(parts) >= 3:
            return os.path.join(outputRoot, parts[1])
    return None


def build(keggDataDir, outputRoot, seed, only=None, species="mmu"):
    kegg = KeggSource(keggDataDir, species)
    context = scenarios.BuildContext(kegg, outputRoot, "datasets", seed)

    entries = []
    for builder in scenarios.CATALOGUE:
        entry = builder(context)
        if only and entry["id"] != only:
            continue
        entries.append(entry)
        writeReadme(outputRoot, entry)
        print("  built  %-34s %s" % (entry["id"], entry["title"]))

    for builder in legacy.CATALOGUE:
        entry = builder(context)
        if entry is None:
            # The real files have not been moved into datasets/, or an optional
            # one (the mouse GTF) is absent. Not an error: the affected entry is
            # left out and everything else still builds.
            print("  skipped   %-33s (files not present)" % builder.__name__)
            continue
        if only and entry["id"] != only:
            continue
        entries.append(entry)
        writeReadme(outputRoot, entry)
        print("  registered %-32s %s" % (entry["id"], entry["title"]))

    return kegg, entries


def writeManifest(outputRoot, entries, seed, kegg):
    """The catalogue the server and client both read.

    Written last and always in full: a partial regeneration still produces a
    complete manifest, because a manifest that lists only what was just rebuilt
    would silently remove every other scenario from the picker.

    Scenarios are ordered by the number on their directory, not by id. Sorting
    by id put "Gene expression — six conditions" (02) ahead of "— single
    condition" (01) in the picker, which is the reverse of the order the
    datasets were numbered to be worked through. The number is also written out
    as `order` so a reader of the manifest does not have to re-derive it, and
    so a scenario could later be moved without renaming its directory.
    """
    for entry in entries:
        entry["order"] = ExampleDatasets.scenarioOrder(entry)

    manifest = {
        "version": MANIFEST_VERSION,
        "generator": "src/AdminTools/scripts/exampledata",
        "seed": seed,
        "keggVersion": _readVersion(kegg),
        "defaultScenario": DEFAULT_SCENARIO,
        # Stated in the published manifest because the constraint is invisible
        # in the data files themselves and has already produced one wrong
        # conclusion ("OmniPath maps far worse than KEGG"). Every `simulated`
        # scenario draws its whole feature universe from context.kegg.allGenes(),
        # so 100% of its features are KEGG pathway genes by construction and
        # KEGG scores ~100% on them no matter what. They measure the pipeline,
        # never the relative coverage of two pathway databases.
        "featureUniverseNote": (
            "Scenarios with simulated=true draw every feature from KEGG's own "
            "gene universe, so KEGG coverage on them is ~100% by construction. "
            "Use the simulated=false (STATegra) scenarios to compare pathway "
            "databases against each other."),
        "scenarios": sorted(entries, key=lambda entry: (entry["order"],
                                                        entry["id"])),
    }
    path = os.path.join(outputRoot, "manifest.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def _readVersion(kegg):
    path = os.path.join(kegg.speciesDir, "VERSION")
    if os.path.isfile(path):
        with open(path) as handle:
            return handle.read().strip()
    return "unknown"


def mergeIntoExisting(outputRoot, entries, only):
    """When rebuilding one scenario, keep the others' entries from disk.

    Without this, `--scenario x` would publish a manifest containing only x.
    """
    if not only:
        return entries
    path = os.path.join(outputRoot, "manifest.json")
    if not os.path.isfile(path):
        return entries
    with open(path, encoding="utf-8") as handle:
        existing = json.load(handle).get("scenarios", [])
    rebuilt = {entry["id"] for entry in entries}
    return entries + [entry for entry in existing if entry["id"] not in rebuilt]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outdir", default=None,
                        help="where the datasets tree lives "
                             "(default: src/examplefiles/datasets)")
    parser.add_argument("--kegg-data", default=None,
                        help="KEGG_DATA directory (default: serverconf.KEGG_DATA_DIR)")
    parser.add_argument("--species", default="mmu",
                        help="KEGG organism code the identifiers come from")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help="fixed so reruns are byte-identical")
    parser.add_argument("--scenario", default=None,
                        help="rebuild only this scenario id")
    parser.add_argument("--list", action="store_true",
                        help="list the scenario ids and exit")
    args = parser.parse_args()

    if args.list:
        for builder in scenarios.CATALOGUE:
            print(builder.__name__)
        return 0

    outputRoot = args.outdir or defaultOutputDir()
    keggDataDir = args.kegg_data
    if keggDataDir is None:
        from src.conf.serverconf import KEGG_DATA_DIR
        keggDataDir = KEGG_DATA_DIR

    os.makedirs(outputRoot, exist_ok=True)
    print("output   : %s" % outputRoot)
    print("KEGG data: %s" % keggDataDir)
    print("seed     : %d (fixed; reruns are byte-identical)" % args.seed)
    print()

    try:
        kegg, entries = build(keggDataDir, outputRoot, args.seed,
                              only=args.scenario, species=args.species)
    except SpeciesNotInstalled as error:
        sys.stderr.write("%s\n" % error)
        return 2

    if args.scenario and not entries:
        sys.stderr.write(
            "unknown scenario %r. Known ids:\n%s\n"
            % (args.scenario,
               "\n".join("  " + builder.__name__ for builder in scenarios.CATALOGUE)))
        return 2

    entries = mergeIntoExisting(outputRoot, entries, args.scenario)
    manifestPath = writeManifest(outputRoot, entries, args.seed, kegg)

    print()
    print("manifest : %s (%d scenarios)" % (manifestPath, len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
