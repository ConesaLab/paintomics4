"""Unit tests for the MapMan installer inputs.

Run from `PaintomicsServer/`:

    python -m src.tests.test_mapman_install_sources

Each test prints PASS/FAIL and exits non-zero on any failure.

The MapMan organisms (ath, bvu, sly, sot) used to be built by copying five
files out of `/home/tian/mapman/`, a directory that exists on exactly one
machine and nowhere in the repository. Any other host - a fresh checkout, CI,
the Drago image - could not rebuild them at all, and the failure surfaced as a
`FileNotFoundError` deep inside the download step.

All five files are published by GoMapMan, which maintains a "paintomics"
export target alongside its MapMan/GSEA/BioMine ones. These tests pin that
arrangement down:

  * no organism config may reference a local absolute path again
  * every config still declares the resources the build step reads
  * `output` names stay fixed, because processMapManMappingData and
    processMapManPathwaysData look the files up by those names
  * bin-code normalisation, without which three diagrams import with far
    fewer features than they should and two import completely empty

These tests are offline: they read the configs and exercise pure functions.
Nothing here contacts GoMapMan.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAPMAN_SPECIES = ("ath", "bvu", "sly", "sot")

# Everything processMapManMappingData / processMapManPathwaysData reads.
# "mapman_kegg" is deliberately absent: sugar beet has no gene-to-Entrez
# export, and the download step treats that key as optional.
REQUIRED_RESOURCES = ("mapman_gene", "mapman_pathways",
                      "mapman_classification", "metabolites")

# The build step resolves each file as DATA_DIR/mapping/<output>, so these
# names are an interface, not a detail.
EXPECTED_OUTPUTS = {
    "ath": {"mapman_kegg": "gene-to-entrez_ath.list",
            "mapman_gene": "gene-to-mapman_ath.list"},
    "bvu": {"mapman_gene": "gene-to-mapman_bvu.list"},
    "sly": {"mapman_kegg": "gene-to-entrez_sly.list",
            "mapman_gene": "gene-to-mapman_sly.list"},
    "sot": {"mapman_kegg": "sot_pgsc_ncbi.list",
            "mapman_gene": "sot_mapman_gene.list"},
}

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AdminTools", "scripts")


def _loadConfig(specie):
    """Load one organism's download_conf.py without importing the package."""
    import importlib.util

    path = os.path.join(_SCRIPTS_DIR, specie + "_resources", "download_conf.py")
    spec = importlib.util.spec_from_file_location("download_conf_" + specie, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EXTERNAL_RESOURCES


def _mapmanResources(resources):
    """Just the MapMan entries; ensembl/refseq/uniprot are fetched elsewhere."""
    keys = ("mapman_kegg", "mapman_gene", "mapman_pathways",
            "mapman_classification", "metabolites")
    return {k: resources[k] for k in keys if resources.get(k)}


def _normaliseMapManBin():
    import importlib.util

    path = os.path.join(_SCRIPTS_DIR, "common_build_database.py")
    spec = importlib.util.spec_from_file_location("common_build_database", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.normaliseMapManBin


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_mapman_input_comes_from_a_local_path():
    """A machine-local path makes the organism unbuildable everywhere else."""
    for specie in MAPMAN_SPECIES:
        for name, entries in _mapmanResources(_loadConfig(specie)).items():
            url = entries[0].get("url", "")
            assert url.startswith("http"), \
                f"{specie}/{name} is fetched from {url!r}, not a URL"
            assert not url.startswith("/") and "/home/" not in url, \
                f"{specie}/{name} points at a local path: {url!r}"


def test_every_species_declares_the_resources_the_build_step_reads():
    """A missing key crashes the download step with a TypeError, not a message."""
    for specie in MAPMAN_SPECIES:
        resources = _loadConfig(specie)
        for name in REQUIRED_RESOURCES:
            assert resources.get(name), f"{specie} declares no {name}"
            assert resources[name][0].get("file"), f"{specie}/{name} has no file"
            assert resources[name][0].get("output"), f"{specie}/{name} has no output"


def test_output_names_are_the_ones_the_build_step_looks_up():
    """processMapManMappingData resolves DATA_DIR/mapping/<output> by name."""
    for specie, expected in EXPECTED_OUTPUTS.items():
        resources = _loadConfig(specie)
        for name, output in expected.items():
            assert resources[name][0]["output"] == output, \
                (f"{specie}/{name} output is {resources[name][0]['output']!r}, "
                 f"the build step reads {output!r}")

    # Shared files must keep their shared names across every organism.
    for specie in MAPMAN_SPECIES:
        resources = _loadConfig(specie)
        assert resources["mapman_pathways"][0]["output"] == "mapman_pathways.tar.gz"
        assert resources["mapman_classification"][0]["output"] == "mapman_classification.txt"
        assert resources["metabolites"][0]["output"] == "mapman_metabolites.txt"


def test_compressed_downloads_are_marked_for_decompression():
    """A .gz left compressed parses as one unreadable binary line, not an error."""
    for specie in MAPMAN_SPECIES:
        for name, entries in _mapmanResources(_loadConfig(specie)).items():
            entry = entries[0]
            if entry["file"].endswith(".gz") and entry["output"].endswith(".gz"):
                continue  # tarballs stay packed; the build step untars them
            if entry["file"].endswith(".gz"):
                assert entry.get("decompress"), \
                    f"{specie}/{name} downloads {entry['file']} but never gunzips it"


def test_metabolite_export_header_is_dropped():
    """Its BINCODE/NAME header would otherwise become a compound named 'NAME'."""
    for specie in MAPMAN_SPECIES:
        entry = _loadConfig(specie)["metabolites"][0]
        assert entry.get("skip_header"), \
            f"{specie} keeps the metabolite header row, which becomes a fake compound"


def test_bin_normalisation_matches_padded_diagram_codes_to_mappings():
    """Diagrams spell bins '18.4.01'; mappings spell the same bin '18.4.1'."""
    normalise = _normaliseMapManBin()
    assert normalise("18.4.01") == "18.4.1"
    assert normalise("17.8.1.1.02") == "17.8.1.1.2"
    assert normalise("18.4.001") == "18.4.1"


def test_bin_normalisation_leaves_everything_else_alone():
    """Metabolite bins end in 1001+; truncating those would break compounds."""
    normalise = _normaliseMapManBin()
    for unchanged in ("1.1.1001", "20.1.10", "35.2", "1", "13.1.1.3.10001"):
        assert normalise(unchanged) == unchanged, \
            f"{unchanged} was rewritten to {normalise(unchanged)}"


def test_bin_normalisation_survives_degenerate_input():
    """A bin of '0' must not normalise to the empty string."""
    normalise = _normaliseMapManBin()
    assert normalise("0") == "0"
    assert normalise("00") == "0"
    assert normalise("1.0.2") == "1.0.2"
    assert normalise("") == ""
    assert normalise(None) is None
    # Non-numeric segments are passed through rather than mangled.
    assert normalise("1.1.1a") == "1.1.1a"


def _extraDiagramManifest():
    import json

    path = os.path.join(_SCRIPTS_DIR, "common_resources", "mapman_extra_diagrams.json")
    with open(path) as handle:
        return json.load(handle)


def test_every_species_asks_for_the_extra_diagrams():
    """GoMapMan ships 20 diagrams and omits every general map."""
    for specie in MAPMAN_SPECIES:
        entries = _loadConfig(specie).get("mapman_extra_pathways")
        assert entries, f"{specie} would install the 20-diagram subset only"
        manifest = entries[0].get("manifest")
        assert manifest, f"{specie} declares mapman_extra_pathways with no manifest"
        assert os.path.isfile(os.path.join(os.path.dirname(_SCRIPTS_DIR), manifest)), \
            f"{specie} points at a manifest that does not exist: {manifest}"


def test_extra_diagram_manifest_is_complete_and_unambiguous():
    """A duplicate name would overwrite a diagram; a blank field breaks the URL."""
    diagrams = _extraDiagramManifest()["diagrams"]
    assert len(diagrams) >= 50, f"manifest lists only {len(diagrams)} diagrams"

    names = [d["name"] for d in diagrams]
    assert len(names) == len(set(names)), "duplicate diagram names in the manifest"

    ids = [d["ressourceId"] for d in diagrams]
    assert len(ids) == len(set(ids)), "duplicate RessourceIds in the manifest"

    for diagram in diagrams:
        for field in ("name", "ressourceId", "primary", "secondary"):
            assert str(diagram.get(field, "")).strip(), \
                f"{diagram.get('name')} has an empty {field}"
        # Names become pathway ids and then file names inside the tarball.
        assert "/" not in diagram["name"] and not diagram["name"].startswith("."), \
            f"unsafe diagram name: {diagram['name']!r}"


def test_extra_diagrams_are_all_the_same_ontology_era():
    """X4 diagrams renumber the ontology - they place wrong genes without erroring."""
    for diagram in _extraDiagramManifest()["diagrams"]:
        assert not diagram["name"].startswith("X4"), \
            (f"{diagram['name']} is an X4-era diagram; GoMapMan's mappings are 3.6-era "
             "and the mismatch is silent")


def test_extra_diagrams_do_not_collide_with_the_gomapman_set():
    """Reusing a shipped name would replace a pathway id that is live in MongoDB."""
    # The 20 GoMapMan names, spelled as they appear inside mapman_pathways.tar.gz.
    shipped = {
        "ABA metabolism", "Biotic Stress", "Carotenoid", "Coenzyme A Biosynthesis",
        "Flavonoid", "GA Synthesis", "GA synthesis later stages", "Isopentenyl PP",
        "JA Synthesis", "Phenylpropanoids", "Polyamine Synthesis", "SA synthesis",
        "Shikimate Synthesis", "Terpenoid", "Tocopherol Biosynthesis",
        "Volatile Carotenoid", "Volatile Mevalonic Pathway", "Volatile PhenylPropanoids",
        "Volatile PhenylPropanoids 2", "receptor like kinases",
    }
    clash = shipped.intersection(d["name"] for d in _extraDiagramManifest()["diagrams"])
    assert not clash, f"extra diagrams reuse GoMapMan pathway ids: {sorted(clash)}"


def main():
    tests = [
        test_no_mapman_input_comes_from_a_local_path,
        test_every_species_asks_for_the_extra_diagrams,
        test_extra_diagram_manifest_is_complete_and_unambiguous,
        test_extra_diagrams_are_all_the_same_ontology_era,
        test_extra_diagrams_do_not_collide_with_the_gomapman_set,
        test_every_species_declares_the_resources_the_build_step_reads,
        test_output_names_are_the_ones_the_build_step_looks_up,
        test_compressed_downloads_are_marked_for_decompression,
        test_metabolite_export_header_is_dropped,
        test_bin_normalisation_matches_padded_diagram_codes_to_mappings,
        test_bin_normalisation_leaves_everything_else_alone,
        test_bin_normalisation_survives_degenerate_input,
    ]
    for t in tests:
        _check(t.__name__, t)

    print()
    print(f"Passed: {len(_PASSED)} / {len(_PASSED)+len(_FAILED)}")
    if _FAILED:
        for name, msg in _FAILED:
            print(f"  - {name}: {msg.splitlines()[0] if msg else ''}")
        sys.exit(1)


if __name__ == "__main__":
    main()
