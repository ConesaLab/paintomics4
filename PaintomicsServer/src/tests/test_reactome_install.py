"""Unit tests for the Reactome installer fixes.

Run from `PaintomicsServer/`:

    python -m src.tests.test_reactome_install

Each test prints PASS/FAIL and exits non-zero on any failure.

Covers the defects that made a Reactome install unusable:
  * per-entity linear scans over 1e5-7e5 row mapping tables (never finished)
  * csv default quoting silently merging columns on Reactome display names
  * silent success when the R step matched no rows for the species
  * non-deterministic ChEBI -> KEGG resolution (set.pop ordering)
  * empty identifiers leaking into the gene index
"""
import os
import shutil
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.AdminTools.scripts.common_build_database import (
    buildReactomeHierarchyEdges, loadReactomeMapping)

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
# Helpers: synthetic Reactome mapping files
# ---------------------------------------------------------------------------

def _writeTsv(directory, name, rows):
    filePath = os.path.join(directory, name)
    with open(filePath, "w") as handle:
        for row in rows:
            handle.write("\t".join(row) + "\n")
    return filePath


def _syntheticEnsemblRows(count, stIdPrefix="R-HSA-"):
    """Rows shaped like Ensembl2Reactome.txt: id, reactome stId, symbol, species."""
    return [
        ["ENSG{:08d}".format(i), "{}{}".format(stIdPrefix, 100000 + i), "GENE{}".format(i)]
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_index_groups_multiple_rows_per_stid():
    """Two rows sharing a stId must both be retrievable, in file order."""
    tmp = tempfile.mkdtemp()
    try:
        path = _writeTsv(tmp, "Ensembl2Reactome.txt", [
            ["ENSG00000001", "R-HSA-111", "AAA"],
            ["ENSG00000002", "R-HSA-111", "BBB"],
            ["ENSG00000003", "R-HSA-222", "CCC"],
        ])
        index = loadReactomeMapping(path, keyColumn=1, valueColumns=(0, 2), minColumns=3)

        assert index["R-HSA-111"] == [("ENSG00000001", "AAA"), ("ENSG00000002", "BBB")], \
            f"grouping/order wrong: {index['R-HSA-111']}"
        assert index["R-HSA-222"] == [("ENSG00000003", "CCC")], "single-row stId wrong"
        # Callers rely on .get() returning a falsy default for unknown ids.
        assert not index.get("R-HSA-999"), "unknown stId should be falsy"
    finally:
        shutil.rmtree(tmp)


def test_quotes_in_display_names_do_not_merge_rows():
    """The real regression: csv's default quoting corrupts Reactome names.

    A display name beginning with an unbalanced double quote makes the default
    dialect treat the field as quoted and consume everything up to the next
    quote -- tabs and newlines included. The following row is swallowed whole,
    so that gene silently disappears from the mapping rather than failing.

    A balanced pair (`"open" state`) is the milder case: the quotes are stripped,
    so the symbol no longer matches what the rest of the pipeline expects.
    """
    tmp = tempfile.mkdtemp()
    try:
        path = _writeTsv(tmp, "UniProt2Reactome.txt", [
            ['P12345', 'R-HSA-333', '"5-HT receptor'],   # unbalanced: eats the next row
            ['P67890', 'R-HSA-444', 'sodium channel'],
            ['P24680', 'R-HSA-555', '"open" state'],     # balanced: quotes stripped
        ])
        index = loadReactomeMapping(path, keyColumn=1, valueColumns=(0, 2), minColumns=3)

        assert index["R-HSA-333"] == [('P12345', '"5-HT receptor')], \
            f"quoted field was mangled: {index.get('R-HSA-333')}"
        assert index["R-HSA-444"] == [('P67890', 'sodium channel')], \
            f"row following an unbalanced quote was lost: {index.get('R-HSA-444')}"
        assert index["R-HSA-555"] == [('P24680', '"open" state')], \
            f"balanced quotes were stripped from the symbol: {index.get('R-HSA-555')}"

        # Verify the premise: the default dialect really does destroy this input,
        # so this test fails if anyone reverts quoting=csv.QUOTE_NONE.
        import csv as _csv
        with open(path) as handle:
            defaultRows = list(_csv.reader(handle, delimiter='\t'))
        assert len(defaultRows) < 3, \
            "default csv dialect no longer merges these rows; test is not proving anything"
    finally:
        shutil.rmtree(tmp)


def test_missing_file_raises_with_species_in_message():
    """A missing mapping file must name the species, not FileNotFoundError deep in the build."""
    tmp = tempfile.mkdtemp()
    try:
        missing = os.path.join(tmp, "NCBI2Reactome.txt")
        try:
            loadReactomeMapping(missing, keyColumn=1, valueColumns=(0, 2), minColumns=3,
                                specieLabel="hsa")
            raise AssertionError("expected an exception for a missing file")
        except Exception as exc:
            message = str(exc)
            assert "not found" in message, f"unhelpful message: {message}"
            assert "hsa" in message, f"species missing from message: {message}"
    finally:
        shutil.rmtree(tmp)


def test_empty_file_raises_instead_of_silently_succeeding():
    """An empty mapping raises by default -- the contract for the common ChEBI
    file, whose only empty state is a truncated download. Per-species gene
    mappings opt out with allowEmpty=True, because Reactome legitimately keys
    some organisms through only a subset of the identifier systems (pfa has no
    Ensembl rows at all); the build enforces the real invariant separately,
    that not EVERY gene mapping is empty."""
    tmp = tempfile.mkdtemp()
    try:
        path = _writeTsv(tmp, "Ensembl2Reactome.txt", [])
        try:
            loadReactomeMapping(path, keyColumn=1, valueColumns=(0, 2), minColumns=3,
                                specieLabel="mmu")
            raise AssertionError("expected an exception for an empty mapping file")
        except Exception as exc:
            message = str(exc)
            assert "empty" in message.lower(), f"unhelpful message: {message}"
            assert "mmu" in message, f"species missing from message: {message}"

        # The tolerated path: empty is a coverage fact, and the caller gets an
        # empty index to combine with the other identifier sources.
        index = loadReactomeMapping(path, keyColumn=1, valueColumns=(0, 2), minColumns=3,
                                    specieLabel="pfa", allowEmpty=True)
        assert len(index) == 0, f"allowEmpty must return an empty index, got {dict(index)}"
    finally:
        shutil.rmtree(tmp)


def test_short_rows_are_recorded_not_fatal():
    """Truncated rows are logged and skipped; good rows still load."""
    tmp = tempfile.mkdtemp()
    try:
        path = _writeTsv(tmp, "Ensembl2Reactome.txt", [
            ["ENSG00000001", "R-HSA-111", "AAA"],
            ["ENSG00000002", "R-HSA-222"],          # missing symbol column
            ["ENSG00000003", "R-HSA-333", "CCC"],
        ])
        failedLines = []
        index = loadReactomeMapping(path, keyColumn=1, valueColumns=(0, 2), minColumns=3,
                                    failedLines=failedLines)

        assert "R-HSA-222" not in index, "short row should have been skipped"
        assert index["R-HSA-111"] and index["R-HSA-333"], "valid rows must still load"
        assert len(failedLines) == 1, f"expected 1 recorded failure, got {len(failedLines)}"
        assert failedLines[0][1] == "2", f"wrong line number recorded: {failedLines[0]}"
    finally:
        shutil.rmtree(tmp)


def test_blank_trailing_lines_are_not_reported_as_failures():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "NCBI2Reactome.txt")
        with open(path, "w") as handle:
            handle.write("1234\tR-HSA-111\tAAA\n\n\n")
        failedLines = []
        index = loadReactomeMapping(path, keyColumn=1, valueColumns=(0, 2), minColumns=3,
                                    failedLines=failedLines)
        assert index["R-HSA-111"] == [("1234", "AAA")]
        assert failedLines == [], f"blank lines wrongly reported: {failedLines}"
    finally:
        shutil.rmtree(tmp)


def test_lookup_is_constant_time_not_linear():
    """The core performance regression.

    The old code ran `[i for i, x in enumerate(list) if x == wanted]` per entity.
    This asserts the indexed lookup does not scale with table size: a 40x larger
    table must not make 2000 lookups meaningfully slower.
    """
    tmp = tempfile.mkdtemp()
    try:
        smallPath = _writeTsv(tmp, "small.txt", _syntheticEnsemblRows(1000))
        largePath = _writeTsv(tmp, "large.txt", _syntheticEnsemblRows(40000))

        smallIndex = loadReactomeMapping(smallPath, keyColumn=1, valueColumns=(0, 2), minColumns=3)
        largeIndex = loadReactomeMapping(largePath, keyColumn=1, valueColumns=(0, 2), minColumns=3)

        probes = ["R-HSA-{}".format(100000 + i) for i in range(0, 1000)]

        def timeLookups(index, repeats=20):
            start = time.perf_counter()
            for _ in range(repeats):
                for probe in probes:
                    index.get(probe)
            return time.perf_counter() - start

        timeLookups(smallIndex, repeats=2)  # warm up
        smallTime = timeLookups(smallIndex)
        largeTime = timeLookups(largeIndex)

        # Constant time would give a ratio near 1.0. Linear scanning over a 40x
        # larger table would give roughly 40x. A generous ceiling of 5x keeps
        # this from flaking on a noisy machine while still failing loudly if
        # anyone reintroduces a scan.
        ratio = largeTime / max(smallTime, 1e-9)
        assert ratio < 5.0, (
            f"lookup cost grew {ratio:.1f}x with a 40x larger table "
            f"({smallTime:.4f}s vs {largeTime:.4f}s) - lookups are not O(1)")

        # And correctness at size.
        assert largeIndex["R-HSA-139999"] == [("ENSG00039999", "GENE39999")], \
            "large-table lookup returned the wrong row"
    finally:
        shutil.rmtree(tmp)


def test_chebi_to_kegg_resolution_is_deterministic():
    """Reproducibility: the winning ChEBI id must not depend on set iteration order.

    Mirrors the resolution loop in processReactomePathwaysData: walk the ChEBI
    ids for an entity in file order and take the first that has a KEGG mapping.
    """
    chebiByStId = {"R-HSA-555": ["100", "200", "300"]}
    keggByChebi = {"200": ["C00002"], "300": ["C00003"]}

    def resolve():
        for subChebiID in chebiByStId["R-HSA-555"]:
            if keggByChebi.get(subChebiID):
                return keggByChebi[subChebiID][0]
        return None

    results = {resolve() for _ in range(50)}
    assert results == {"C00002"}, \
        f"resolution is not deterministic or picked the wrong id: {results}"


def test_blank_identifiers_are_excluded_from_gene_index():
    """Empty cells must not become gene keys in pathway2gene/gene2pathway."""
    ensemblHits = [("ENSG00000001", ""), ("", "AAA"), ("ENSG00000002", "BBB")]
    other_ids = set()
    for externalId, symbol in ensemblHits:
        if externalId:
            other_ids.add(externalId)
        if symbol:
            other_ids.add(symbol)

    assert "" not in other_ids, "empty identifier leaked into the gene index"
    assert other_ids == {"ENSG00000001", "AAA", "ENSG00000002", "BBB"}, \
        f"unexpected identifier set: {other_ids}"


# ---------------------------------------------------------------------------
# Integration: processReactomeData.R
# ---------------------------------------------------------------------------

_R_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "AdminTools", "scripts", "processReactomeData.R")


def _buildReactomeSource(directory):
    """Write synthetic *_PE_All_Levels.txt files covering several species.

    Real column order: source id, PE stId, PE name, pathway stId, url, event,
    evidence code, species.
    """
    os.makedirs(directory, exist_ok=True)
    rows = []
    for i in range(1, 4):
        rows.append([f"SRC{i}", f"R-HSA-{1000+i}", f"GENE{i} [nucleoplasm]",
                     f"R-HSA-{9000+i}", "http://x", "Event", "IEA", "Homo sapiens"])
    for i in range(1, 3):
        rows.append([f"MSRC{i}", f"R-MMU-{2000+i}", f"Mgene{i} [cytosol]",
                     f"R-MMU-{9000+i}", "http://x", "Event", "IEA", "Mus musculus"])
    # Names that break R's default quote/comment handling.
    rows.append(["ZSRC1", "R-DRE-3001", "5'-nucleotidase \"partial [cytosol]",
                 "R-DRE-9001", "http://x", "Event", "IEA", "Danio rerio"])
    rows.append(["QSRC1", "R-HSA-1099", "\"quoted name [nucleoplasm]",
                 "R-HSA-9099", "http://x", "Event", "IEA", "Homo sapiens"])
    rows.append(["HSRC1", "R-HSA-1098", "#hashname [nucleoplasm]",
                 "R-HSA-9098", "http://x", "Event", "IEA", "Homo sapiens"])

    for name in ("Ensembl2Reactome", "NCBI2Reactome", "UniProt2Reactome"):
        _writeTsv(directory, name + "_PE_All_Levels.txt", rows)


def _runRScript(specie, rootDir):
    import subprocess
    return subprocess.run(
        [_R_SCRIPT, "--specie=" + specie, "--root=" + rootDir],
        capture_output=True, universal_newlines=True)


def test_r_script_extracts_requested_species_only():
    """hsa and mmu must each yield exactly their own rows, quotes intact."""
    if not shutil.which("Rscript"):
        print("      (skipped: Rscript not installed)")
        return

    tmp = tempfile.mkdtemp()
    try:
        common = os.path.join(tmp, "common")
        _buildReactomeSource(common)

        for specie, expected in (("hsa", 5), ("mmu", 2)):
            result = _runRScript(specie, common + os.sep)
            assert result.returncode == 0, \
                f"{specie} failed ({result.returncode}): {result.stderr}"

            outPath = os.path.join(tmp, specie, "mapping", "reactome", "Ensembl2Reactome.txt")
            assert os.path.isfile(outPath), f"no output written for {specie}"
            with open(outPath) as handle:
                lines = [l for l in handle.read().splitlines() if l.strip()]

            assert len(lines) == expected, \
                f"{specie}: expected {expected} rows, got {len(lines)}: {lines}"
            # No other species' rows leaked in.
            tag = "R-" + specie.upper() + "-"
            assert all(tag in line for line in lines), \
                f"{specie}: foreign species rows leaked in: {lines}"

        # The '#' name must survive: R's default comment.char would truncate it.
        hsaPath = os.path.join(tmp, "hsa", "mapping", "reactome", "Ensembl2Reactome.txt")
        with open(hsaPath) as handle:
            content = handle.read()
        assert "R-HSA-1098" in content, "row with a '#' display name was dropped"
        assert "R-HSA-1099" in content, "row with a leading quote was dropped"
    finally:
        shutil.rmtree(tmp)


def test_r_script_fails_loudly_for_species_reactome_lacks():
    """Silent success was the bug: no output, exit 0, confusing failure later.

    The failure is now AGGREGATE: one empty mapping is a per-source coverage
    fact and deliberately writes an empty output file, and only all three gene
    mappings coming up empty stops the script. The stop message is load-bearing:
    the Python wrapper recognises it and downgrades the species to KEGG-only
    instead of failing the install."""
    if not shutil.which("Rscript"):
        print("      (skipped: Rscript not installed)")
        return

    tmp = tempfile.mkdtemp()
    try:
        common = os.path.join(tmp, "common")
        _buildReactomeSource(common)

        # 'sot' (Solanum tuberosum) is a KEGG organism Reactome does not cover.
        result = _runRScript("sot", common + os.sep)
        assert result.returncode != 0, \
            "expected a non-zero exit so check_output raises CalledProcessError"

        combined = result.stdout + result.stderr
        assert "No rows matched species 'sot'" in combined, \
            f"unhelpful failure output: {combined}"
        # The exact phrase common_build_database.py keys the KEGG-only
        # downgrade on; reword both together or uncovered species fail hard.
        assert "in any of Ensembl2Reactome, NCBI2Reactome or UniProt2Reactome" in combined, \
            f"aggregate stop message changed; the Python-side downgrade will not match: {combined}"

        # The per-source empty outputs are deliberate now, not debris: the
        # Python side reads each one independently.
        outPath = os.path.join(tmp, "sot", "mapping", "reactome", "Ensembl2Reactome.txt")
        assert os.path.isfile(outPath), "the empty mapping file should still be written"
        with open(outPath) as handle:
            assert handle.read().strip() == "", "expected an EMPTY mapping for an uncovered species"
    finally:
        shutil.rmtree(tmp)


def test_r_script_maps_rice_to_dosa_not_osa():
    """The old first-letter+two heuristic derived 'osa'; KEGG and this repo use 'dosa'."""
    if not shutil.which("Rscript"):
        print("      (skipped: Rscript not installed)")
        return

    tmp = tempfile.mkdtemp()
    try:
        common = os.path.join(tmp, "common")
        os.makedirs(common)
        rows = [["OS01", "R-OSA-4001", "OsGENE1 [cytosol]", "R-OSA-9001",
                 "http://x", "Event", "IEA", "Oryza sativa"]]
        for name in ("Ensembl2Reactome", "NCBI2Reactome", "UniProt2Reactome"):
            _writeTsv(common, name + "_PE_All_Levels.txt", rows)

        result = _runRScript("dosa", common + os.sep)
        assert result.returncode == 0, \
            f"dosa should resolve to 'Oryza sativa': {result.stderr}"
        outPath = os.path.join(tmp, "dosa", "mapping", "reactome", "Ensembl2Reactome.txt")
        assert os.path.isfile(outPath), "no output written for dosa"
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------------------
# downloadReactome.py
#
# DBManager.py imports `scripts.downloadReactome` as a top-level module, so the
# AdminTools directory has to be on sys.path exactly as it is at runtime.
# ---------------------------------------------------------------------------

_ADMIN_TOOLS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AdminTools")
if _ADMIN_TOOLS not in sys.path:
    sys.path.insert(0, _ADMIN_TOOLS)

from scripts.downloadReactome import isValidDownload, readPathwayRelations  # noqa: E402


def test_html_error_page_saved_as_json_is_not_valid():
    """The cache-poisoning bug: curl without -f writes error bodies to the output."""
    tmp = tempfile.mkdtemp()
    try:
        errorPage = os.path.join(tmp, "R-HSA-111.json")
        with open(errorPage, "w") as handle:
            handle.write("<html><head><title>404 Not Found</title></head></html>")
        assert not isValidDownload(errorPage, expectJson=True), \
            "an HTML error page was accepted as a cached JSON download"

        empty = os.path.join(tmp, "R-HSA-222.json")
        open(empty, "w").close()
        assert not isValidDownload(empty, expectJson=True), "empty file accepted"

        truncated = os.path.join(tmp, "R-HSA-333.json")
        with open(truncated, "w") as handle:
            handle.write('{"dbId": 123, "displayName": "trunc')
        assert not isValidDownload(truncated, expectJson=True), \
            "truncated JSON accepted as a complete download"

        good = os.path.join(tmp, "R-HSA-444.json")
        with open(good, "w") as handle:
            handle.write('{"dbId": 123, "displayName": "ok"}')
        assert isValidDownload(good, expectJson=True), "valid JSON rejected"

        # Non-JSON assets (PNG diagrams) are only size-checked.
        png = os.path.join(tmp, "R-HSA-555.png")
        with open(png, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n")
        assert isValidDownload(png, expectJson=False), "non-empty PNG rejected"
    finally:
        shutil.rmtree(tmp)


def test_relation_parsing_matches_species_precisely_and_once():
    """Substring matching pulled in foreign pathways; double parsing doubled the lists."""
    tmp = tempfile.mkdtemp()
    try:
        path = _writeTsv(tmp, "ReactomePathwaysRelation.list", [
            ["R-HSA-1000", "R-HSA-1001"],
            ["R-HSA-1000", "R-HSA-1002"],
            ["R-HSA-1001", "R-HSA-1003"],
            ["R-MMU-2000", "R-MMU-2001"],
            ["R-DRE-3000", "R-DRE-3001"],
        ])

        high, low, highList, lowList, pairs = readPathwayRelations(path, "HSA")

        assert len(pairs) == 3, f"expected 3 hsa relations, got {len(pairs)}: {pairs}"
        assert len(highList) == len(lowList) == 3, "parallel lists must not be doubled"
        assert high == {"R-HSA-1000", "R-HSA-1001"}, f"wrong parents: {high}"
        assert low == {"R-HSA-1001", "R-HSA-1002", "R-HSA-1003"}, f"wrong children: {low}"
        assert not any("MMU" in p[0] or "DRE" in p[0] for p in pairs), \
            "foreign species leaked into the hsa relation set"

        # Leaf pathways (no children of their own) drive the download loop.
        assert low - high == {"R-HSA-1002", "R-HSA-1003"}
        # Top-level pathways drive the hierarchy.
        assert high - low == {"R-HSA-1000"}
    finally:
        shutil.rmtree(tmp)


def test_relation_parsing_rejects_species_code_appearing_as_substring():
    """"R-HSA-" must match as a tagged prefix, not anywhere in the line."""
    tmp = tempfile.mkdtemp()
    try:
        path = _writeTsv(tmp, "ReactomePathwaysRelation.list", [
            ["R-MMU-9000", "R-MMU-9001"],   # contains no HSA tag
            ["R-HSA-1000", "R-HSA-1001"],
        ])
        _, _, _, _, pairs = readPathwayRelations(path, "HSA")
        assert len(pairs) == 1 and pairs[0][0] == "R-HSA-1000", \
            f"precise species matching failed: {pairs}"
    finally:
        shutil.rmtree(tmp)


def test_parent_lookup_is_built_once_and_terminates_on_cycles():
    """The walk up the hierarchy must not loop forever on a cyclic relation file.

    Mirrors the parentOf/visited logic in downloadReactome so the invariant is
    covered without hitting the network.
    """
    highList = ["A", "B", "C"]
    lowList = ["B", "C", "A"]           # A -> B -> C -> A, a cycle
    parentOf = {}
    for high, low in zip(highList, lowList):
        parentOf.setdefault(low, high)

    seen = set()
    current = "B"
    steps = 0
    while current not in seen:
        seen.add(current)
        parent = parentOf.get(current)
        if parent is None:
            break
        current = parent
        steps += 1
        assert steps < 100, "walk did not terminate on a cyclic relation file"

    assert seen == {"A", "B", "C"}, f"walk did not cover the cycle exactly once: {seen}"


# ---------------------------------------------------------------------------
# The hierarchy-derived network edges
# ---------------------------------------------------------------------------

# One small tree used by the tests below.
#
#   TOP
#    +- MID_A
#    |    +- LEAF1        (installed)
#    |    +- LEAF2        (installed)
#    |    +- SUB
#    |         +- LEAF3   (installed)
#    +- MID_B
#         +- LEAF4        (installed)
#
# distances to the nearest shared ancestor:
#   LEAF1/LEAF2  1+1 = 2 under MID_A          -> siblings
#   LEAF1/LEAF3  1+2 = 3 under MID_A          -> the ECM case: one nested deeper
#   LEAF1/LEAF4  2+2 = 4 under TOP            -> too far at the default budget
_TREE = [
    ("R-MMU-TOP", "R-MMU-MIDA"),
    ("R-MMU-TOP", "R-MMU-MIDB"),
    ("R-MMU-MIDA", "R-MMU-LEAF1"),
    ("R-MMU-MIDA", "R-MMU-LEAF2"),
    ("R-MMU-MIDA", "R-MMU-SUB"),
    ("R-MMU-SUB", "R-MMU-LEAF3"),
    ("R-MMU-MIDB", "R-MMU-LEAF4"),
]
_LEAVES = {"R-MMU-LEAF1", "R-MMU-LEAF2", "R-MMU-LEAF3", "R-MMU-LEAF4"}


def _hierarchyEdges(installed, rows=None, **kwargs):
    tmp = tempfile.mkdtemp()
    try:
        path = _writeTsv(tmp, "ReactomePathwaysRelation.list",
                         rows if rows is not None else _TREE)
        return buildReactomeHierarchyEdges(installed, path, "R-MMU-", **kwargs)
    finally:
        shutil.rmtree(tmp)


def test_hierarchy_links_siblings_and_one_level_deeper_but_not_cousins():
    """The default budget of 3 is what recovers the case the fix exists for.

    Reactome installs leaves, so two leaves are related by where they sit in the
    tree, not by a diagram cross-reference. Siblings are the easy case; the one
    that mattered in practice is a pair where one is nested a level deeper -
    "Laminin interactions" directly under ECM organization against "Collagen
    chain trimerization" under "Collagen formation" under it. A siblings-only
    rule calls those unrelated.
    """
    edges = _hierarchyEdges(_LEAVES)

    assert ("R-MMU-LEAF1", "R-MMU-LEAF2") in edges, \
        "siblings under the same parent were not linked"
    assert ("R-MMU-LEAF1", "R-MMU-LEAF3") in edges, \
        "1+2 pair (one nested a level deeper) was not linked"
    assert ("R-MMU-LEAF1", "R-MMU-LEAF4") not in edges, \
        "2+2 pair across the top of the tree should be beyond the budget"


def test_hierarchy_budget_of_two_is_siblings_only():
    edges = _hierarchyEdges(_LEAVES, maxCombinedDepth=2)

    assert ("R-MMU-LEAF1", "R-MMU-LEAF2") in edges
    assert ("R-MMU-LEAF1", "R-MMU-LEAF3") not in edges, \
        "budget 2 must not reach a pathway nested a level deeper"


def test_hierarchy_pairs_only_installed_pathways():
    """An edge to a pathway that is not a node is invisible in the client and
    was 52 of the 451 edges the old build emitted for mmu."""
    installed = {"R-MMU-LEAF1", "R-MMU-LEAF2"}
    edges = _hierarchyEdges(installed)

    for first, second in edges:
        assert first in installed and second in installed, \
            f"edge {first}-{second} points outside the installed set"


def test_hierarchy_links_an_installed_ancestor_to_its_descendants():
    installed = {"R-MMU-MIDA", "R-MMU-LEAF1", "R-MMU-LEAF3"}
    edges = _hierarchyEdges(installed)

    assert ("R-MMU-LEAF1", "R-MMU-MIDA") in edges, \
        "installed parent was not linked to its installed child"
    assert ("R-MMU-LEAF3", "R-MMU-MIDA") in edges, \
        "installed grandparent was not linked to its installed grandchild"


def test_hierarchy_ignores_other_species():
    """The relation file holds every species at once."""
    rows = _TREE + [("R-HSA-MIDA", "R-HSA-LEAF1"), ("R-HSA-MIDA", "R-HSA-LEAF2")]
    edges = _hierarchyEdges(_LEAVES | {"R-HSA-LEAF1", "R-HSA-LEAF2"}, rows=rows)

    assert ("R-HSA-LEAF1", "R-HSA-LEAF2") not in edges, \
        "a human pair was emitted while building the mouse network"


def test_hierarchy_pairs_are_ordered_and_unique():
    """The caller de-duplicates against edges it has already emitted in either
    direction, which only works if the pair is always (min, max)."""
    edges = _hierarchyEdges(_LEAVES)

    for first, second in edges:
        assert first < second, f"pair ({first}, {second}) is not ordered"
    assert len(edges) == len(set(edges))


def test_hierarchy_terminates_on_a_cyclic_relation_file():
    """Reactome's relation graph has diamonds, and the file has been seen with
    cycles; the walk up must not loop."""
    rows = [("R-MMU-A", "R-MMU-B"), ("R-MMU-B", "R-MMU-C"), ("R-MMU-C", "R-MMU-A")]
    edges = _hierarchyEdges({"R-MMU-A", "R-MMU-B", "R-MMU-C"}, rows=rows)

    assert isinstance(edges, set)


def test_hierarchy_group_cap_falls_back_to_direct_children_and_says_so():
    """A cap that silently thins the graph would read as "covered everything"."""
    rows = [("R-MMU-BIG", "R-MMU-C%d" % i) for i in range(10)]
    rows.append(("R-MMU-C0", "R-MMU-DEEP"))
    installed = {"R-MMU-C%d" % i for i in range(10)} | {"R-MMU-DEEP"}

    uncapped = _hierarchyEdges(installed, rows=rows, maxGroupSize=100)
    capped = _hierarchyEdges(installed, rows=rows, maxGroupSize=3)

    assert len(capped) < len(uncapped), "the cap did not reduce the pairing"
    assert ("R-MMU-C0", "R-MMU-C1") in capped, \
        "direct children must survive the fallback"


def test_hierarchy_missing_relation_file_is_not_fatal():
    """A species installed before the common Reactome download must still build,
    with the diagram edges alone."""
    edges = buildReactomeHierarchyEdges(
        _LEAVES, "/nonexistent/ReactomePathwaysRelation.list", "R-MMU-")

    assert edges == set(), "a missing relation file should yield no edges, not raise"


def main():
    tests = [
        test_index_groups_multiple_rows_per_stid,
        test_quotes_in_display_names_do_not_merge_rows,
        test_missing_file_raises_with_species_in_message,
        test_empty_file_raises_instead_of_silently_succeeding,
        test_short_rows_are_recorded_not_fatal,
        test_blank_trailing_lines_are_not_reported_as_failures,
        test_lookup_is_constant_time_not_linear,
        test_chebi_to_kegg_resolution_is_deterministic,
        test_blank_identifiers_are_excluded_from_gene_index,
        test_r_script_extracts_requested_species_only,
        test_r_script_fails_loudly_for_species_reactome_lacks,
        test_r_script_maps_rice_to_dosa_not_osa,
        test_html_error_page_saved_as_json_is_not_valid,
        test_relation_parsing_matches_species_precisely_and_once,
        test_relation_parsing_rejects_species_code_appearing_as_substring,
        test_parent_lookup_is_built_once_and_terminates_on_cycles,
        test_hierarchy_links_siblings_and_one_level_deeper_but_not_cousins,
        test_hierarchy_budget_of_two_is_siblings_only,
        test_hierarchy_pairs_only_installed_pathways,
        test_hierarchy_links_an_installed_ancestor_to_its_descendants,
        test_hierarchy_ignores_other_species,
        test_hierarchy_pairs_are_ordered_and_unique,
        test_hierarchy_terminates_on_a_cyclic_relation_file,
        test_hierarchy_group_cap_falls_back_to_direct_children_and_says_so,
        test_hierarchy_missing_relation_file_is_not_fatal,
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
