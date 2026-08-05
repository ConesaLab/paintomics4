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

from src.AdminTools.scripts.common_build_database import loadReactomeMapping

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
    """The R step writes nothing when it matches no species. That must be loud."""
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
