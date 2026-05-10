"""
Regression test for the multi-database clone-dedup fix in
FeatureNamesToKeggIDsMapper.mapFeatureIdentifiers.

Bug: for organisms whose KEGG and second-database namespace use the same ID
strings (e.g. ath: KEGG and MapMan both return AGI codes), the mapper used to
clone the input feature once per database. Both clones landed in the same
inputGenesData bucket via Job.addInputGeneData, and addOmicValues blindly
appended — every OmicValue showed up twice (G1 G1 R1 R1 R2 R2 in PA Step 4
instead of G1 R1 R2). The fix tracks already-cloned featureIDs per input
feature and skips duplicate clones across the database loop.

Run from PaintomicsServer/:
    python -m src.tests.test_mapper_multidb_dedup
"""

import os
import sys
import traceback
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_PASS, _FAIL = [], []


def _check(name, fn):
    try:
        fn()
        _PASS.append(name)
        print(f"  PASS  {name}")
    except AssertionError as e:
        _FAIL.append((name, str(e)))
        print(f"  FAIL  {name}: {e}")
    except Exception:
        _FAIL.append((name, traceback.format_exc()))
        print(f"  ERROR {name}")
        traceback.print_exc()


# Stand-ins for the MongoDB pieces mapFeatureIdentifiers calls. We don't need
# real MongoDB to verify the dedup logic — only the per-feature ID lookups.

class _FakeDBNameCollection:
    def __init__(self, dbname_to_id):
        self._map = dbname_to_id

    def find_one(self, filt, projection=None):
        # mapFeatureIdentifiers calls db.dbname.find_one({"dbname": <name>}, ...)
        name = filt.get("dbname")
        if name in self._map:
            return {"_id": self._map[name], "item": "x", "qty": 1}
        return None


class _FakeDB:
    def __init__(self, dbname_to_id):
        self.dbname = _FakeDBNameCollection(dbname_to_id)


class _FakeClient:
    def close(self):
        pass


def _make_feature(name):
    """Build a Gene with one OmicValue that has originalName == name."""
    from src.classes.Feature import Gene, OmicValue
    g = Gene("")
    g.setName(name)
    ov = OmicValue(name)
    ov.setOmicName("MORE_TF")
    ov.setOriginalName(name)
    ov.setValues([1.0, 2.0])
    ov.setRelevant([False])
    g.addOmicValue(ov)
    return g


def test_same_id_in_two_databases_clones_once():
    """ath-shaped scenario: KEGG and MapMan both resolve AT1G20290 → AT1G20290.
    Expect ONE clone in matchedFeatures (not two), so a downstream
    addInputGeneData merge cannot double the OmicValue list.
    """
    from src.common import FeatureNamesToKeggIDsMapper as M

    # Both databases return the same ID for the input AGI code.
    fake_findIDs = lambda jobID, names, db, dbname_id: {n: [n] for n in names}

    # Stub the MongoDB connection. db.dbname.find_one returns a dict shaped
    # so the .get("_id") chain works; the actual id values are opaque tags.
    fake_db = _FakeDB({"kegg_id": "kegg_dbname_id", "mapman_gene_id": "mapman_dbname_id"})
    fake_client = object()

    feature = _make_feature("AT1G20290")
    matched, notMatched, found = [], [], []

    with patch.object(M, "getConnectionByOrganismCode", return_value=(_FakeClient(), fake_db)), \
         patch.object(M, "findIDsByFeaturesName", side_effect=fake_findIDs):
        M.mapFeatureIdentifiers(
            jobID="testjob",
            organism="ath",
            databases=["KEGG", "MapMan"],
            featureList=[feature],
            matchedFeatures=matched,
            notMatchedFeatures=notMatched,
            foundFeatures=found,
            enrichment="genes",
        )

    assert len(matched) == 1, (
        f"Expected exactly 1 clone after dedup, got {len(matched)}. "
        f"Cloning twice would later double OmicValues in addInputGeneData."
    )
    assert matched[0].getID() == "AT1G20290"
    # The first DB seen wins (MORE-v2 convention; PathwayAcquisitionJob
    # later overwrites with the full ["KEGG","MapMan"] list).
    assert matched[0].getMatchingDB() == "KEGG"
    # Per-DB and Total counters still reflect both DB matches.
    assert "AT1G20290" in found[0]["KEGG"]
    assert "AT1G20290" in found[0]["MapMan"]
    assert "AT1G20290" in found[0]["Total"]


def test_distinct_ids_across_databases_clones_each():
    """Negative control: when two databases return DIFFERENT featureIDs (the
    typical mmu/hsa case where KEGG=entrezgene, Reactome=reactome_gene_id),
    dedup must NOT merge them — both clones are needed because they live in
    different inputGenesData buckets and represent distinct gene records.
    """
    from src.common import FeatureNamesToKeggIDsMapper as M

    # Per-database ID resolution: KEGG → entrez-style, Reactome → reactome-style.
    db_to_returned = {"kegg_dbname_id": ["12345"], "reactome_dbname_id": ["R-MMU-9"]}

    def fake_findIDs(jobID, names, db, dbname_id):
        # Return the per-DB stub for any input feature name.
        if dbname_id in db_to_returned:
            return {n: db_to_returned[dbname_id] for n in names}
        return {}

    fake_db = _FakeDB({"entrezgene": "kegg_dbname_id", "reactome_gene_id": "reactome_dbname_id"})

    # Patch the dicDatabases lookup so the test doesn't depend on real org config.
    fake_org_table = [
        {"KEGG": "entrezgene", "Reactome": "reactome_gene_id"},
        {"KEGG": "entrezgene", "Reactome": "reactome_gene_id"},
    ]

    feature = _make_feature("Gata1")
    matched, notMatched, found = [], [], []

    with patch.object(M, "getConnectionByOrganismCode", return_value=(_FakeClient(), fake_db)), \
         patch.object(M, "findIDsByFeaturesName", side_effect=fake_findIDs), \
         patch.object(M, "getDatabasesByOrganismCode", return_value=fake_org_table):
        M.mapFeatureIdentifiers(
            jobID="testjob",
            organism="mmu",
            databases=["KEGG", "Reactome"],
            featureList=[feature],
            matchedFeatures=matched,
            notMatchedFeatures=notMatched,
            foundFeatures=found,
            enrichment="genes",
        )

    ids = sorted(f.getID() for f in matched)
    assert ids == ["12345", "R-MMU-9"], (
        f"Distinct IDs from different DBs must produce two clones; got {ids}"
    )


def test_unmatched_feature_added_to_notMatched():
    """Sanity: a feature that resolves in NO database goes to notMatchedFeatures
    and the dedup change does not regress this branch.
    """
    from src.common import FeatureNamesToKeggIDsMapper as M

    fake_findIDs = lambda jobID, names, db, dbname_id: {}  # nothing matches
    fake_db = _FakeDB({"kegg_id": "kegg_dbname_id", "mapman_gene_id": "mapman_dbname_id"})

    feature = _make_feature("NOT_A_REAL_GENE")
    matched, notMatched, found = [], [], []

    with patch.object(M, "getConnectionByOrganismCode", return_value=(_FakeClient(), fake_db)), \
         patch.object(M, "findIDsByFeaturesName", side_effect=fake_findIDs):
        M.mapFeatureIdentifiers(
            jobID="testjob",
            organism="ath",
            databases=["KEGG", "MapMan"],
            featureList=[feature],
            matchedFeatures=matched,
            notMatchedFeatures=notMatched,
            foundFeatures=found,
            enrichment="genes",
        )

    assert len(matched) == 0
    assert len(notMatched) == 1
    assert notMatched[0].getName() == "NOT_A_REAL_GENE"


print("\n── Mapper multi-DB dedup regression ─────────────────────────")
_check("ath: same ID in two DBs clones once (no doubled OmicValues downstream)", test_same_id_in_two_databases_clones_once)
_check("mmu: distinct IDs across DBs still produce two clones", test_distinct_ids_across_databases_clones_each)
_check("unmatched feature still routed to notMatchedFeatures", test_unmatched_feature_added_to_notMatched)

print(f"\n{'─'*55}")
print(f"  Results: {len(_PASS)} passed, {len(_FAIL)} failed")
if _FAIL:
    print("\nFailed tests:")
    for name, msg in _FAIL:
        print(f"  ✗ {name}")
        print(f"    {msg.splitlines()[0]}")

sys.exit(1 if _FAIL else 0)
