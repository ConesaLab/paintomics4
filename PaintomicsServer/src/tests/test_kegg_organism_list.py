"""KEGG organism list download and format conversion.

Run from `PaintomicsServer/`:

    python -m src.tests.test_kegg_organism_list

KEGG retired /list/organism -- it answers HTTP 400 -- which aborted every fresh
install at "FAILED WHILE DOWNLOADING/COPYING COMMON KEGG INFORMATION" with only
"Unable to retrieve organisms_all.list" to go on. /list/genome replaces it with
a different shape:

    /list/organism (gone):  T01001<TAB>hsa<TAB>Homo sapiens (human)<TAB>Eukaryotes;...
    /list/genome  (live):   T01001<TAB>hsa; Homo sapiens (human)

downloadKEGGOrganismList() converts to the historic four-column layout so
AdminServlet, common_build_database and AIInterpret's context_builder keep
working unchanged.

The network test is skipped when KEGG is unreachable; the parsing tests are not.
"""
import os
import shutil
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_ADMIN_TOOLS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AdminTools")
if _ADMIN_TOOLS not in sys.path:
    sys.path.insert(0, _ADMIN_TOOLS)

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


# The conversion, mirrored from downloadKEGGOrganismList so the parsing rules
# can be tested without a network round-trip.
def convertGenomeListing(text):
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        entry, description = parts[0], parts[1]
        if "; " not in description:
            continue
        code, name = description.split("; ", 1)
        code = code.strip()
        if not code or " " in code:
            continue
        rows.append((entry, code, name.strip()))
    return rows


def test_converts_genome_listing_to_legacy_columns():
    sample = (
        "T01001\thsa; Homo sapiens (human)\n"
        "T01005\tptr; Pan troglodytes (chimpanzee)\n"
        "T00001\tmmu; Mus musculus (house mouse)\n"
    )
    rows = convertGenomeListing(sample)
    assert len(rows) == 3, f"expected 3 organisms, got {len(rows)}"
    assert rows[0] == ("T01001", "hsa", "Homo sapiens (human)"), rows[0]
    assert rows[2] == ("T00001", "mmu", "Mus musculus (house mouse)"), rows[2]


def test_skips_entries_without_an_organism_code():
    """Viral and addendum genomes are listed as a bare description."""
    sample = (
        "T01001\thsa; Homo sapiens (human)\n"
        "T40001\tHuman papillomavirus type 16\n"      # no "code; " prefix
        "T90001\t\n"                                   # empty description
        "T01005\tptr; Pan troglodytes (chimpanzee)\n"
    )
    rows = convertGenomeListing(sample)
    codes = [r[1] for r in rows]
    assert codes == ["hsa", "ptr"], f"unexpected codes: {codes}"


def test_names_containing_semicolons_are_not_truncated():
    """Only the first '; ' separates code from name."""
    sample = "T03333\tabc; Some organism; strain X (weird)\n"
    rows = convertGenomeListing(sample)
    assert rows[0] == ("T03333", "abc", "Some organism; strain X (weird)"), rows[0]


def test_output_layout_matches_what_consumers_read():
    """AdminServlet, common_build_database and context_builder read row[1] and row[2]."""
    import csv as _csv
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "organisms_all.list")
        rows = convertGenomeListing("T01001\thsa; Homo sapiens (human)\n")
        with open(path, "w") as handle:
            for entry, code, name in rows:
                handle.write("\t".join([entry, code, name, ""]) + "\n")

        with open(path) as handle:
            parsed = list(_csv.reader(handle, delimiter='\t'))

        assert len(parsed) == 1
        assert len(parsed[0]) >= 3, \
            "context_builder requires len(row) >= 3 before indexing row[2]"
        assert parsed[0][1] == "hsa", "row[1] must be the organism code"
        assert parsed[0][2] == "Homo sapiens (human)", "row[2] must be the display name"
    finally:
        shutil.rmtree(tmp)


def test_kegg_endpoint_is_live_and_organism_is_still_gone():
    """Pins the reason this code exists. If /list/organism returns, revisit."""
    try:
        import requests
        genome = requests.get("https://rest.kegg.jp/list/genome", timeout=30)
        organism = requests.get("https://rest.kegg.jp/list/organism", timeout=30)
    except Exception as exc:
        print(f"      (skipped: KEGG unreachable: {exc})")
        return

    assert genome.status_code == 200, \
        f"/list/genome returned {genome.status_code}; the organism list source has moved again"

    rows = convertGenomeListing(genome.text)
    assert len(rows) > 1000, f"only {len(rows)} organisms parsed from live KEGG data"

    codes = {r[1] for r in rows}
    for required in ("hsa", "mmu"):
        assert required in codes, f"'{required}' missing from the live KEGG organism list"

    if organism.status_code == 200:
        print("      NOTE: /list/organism answers again; the conversion may no longer be needed")


def main():
    tests = [
        test_converts_genome_listing_to_legacy_columns,
        test_skips_entries_without_an_organism_code,
        test_names_containing_semicolons_are_not_truncated,
        test_output_layout_matches_what_consumers_read,
        test_kegg_endpoint_is_live_and_organism_is_still_gone,
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
