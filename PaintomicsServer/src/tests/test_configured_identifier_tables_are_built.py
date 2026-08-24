"""A species may only name an identifier table its own build script produces.

`organismDB.dicDatabases` says which xref table each pathway database translates
INTO -- KEGG for `dme` translates into `kegg_id`. That table exists only if the
species' `build_database.py` calls `processKEGGMappingData()`, which is the one
function that inserts `kegg_id`, `kegg_gene_symbol` and
`kegg_gene_symbol_synonyms`.

`dme` and `bta` declared `kegg_id` while their build scripts carried the call
COMMENTED OUT, so the table was never built. Nothing warned: the mismatch only
surfaced at job time, inside `resolveDatabaseIds`, as

    db.dbname.find_one({"dbname": "kegg_id"}).get("_id")
    AttributeError: 'NoneType' object has no attribute 'get'

which reached the user as "Oops..Internal error!" and killed EVERY gene-based
job on those species -- 7 consecutive submissions from one user on 2026-08-24,
each with different files, none of which could ever have worked.

Two invariants, one per failure mode:
  * the declared table is actually built (would have caught dme/bta at commit);
  * a missing table names itself instead of raising AttributeError, so the next
    such gap is diagnosable from the user's error message alone.

Run:
    PYTHONPATH=PaintomicsServer python PaintomicsServer/src/tests/test_configured_identifier_tables_are_built.py
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.conf.organismDB import dicDatabases
from src.common.FeatureNamesToKeggIDsMapper import (
    GENE_LEVEL_BRIDGE_DATABASES, resolveDatabaseIds)

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "AdminTools", "scripts")
COMMON_BUILDER = os.path.join(SCRIPTS_DIR, "common_build_database.py")

#: Every name the builders file NCBI *gene* ids under. They are one identifier
#: space with two names -- `processEnsemblData` says `entrezgene`,
#: `processKEGGMappingData` says `ncbi_geneid` -- so a species built by both
#: carries two mate islands, and only a bridge that knows BOTH names can cross
#: between them.
NCBI_GENE_TABLE_PATTERN = re.compile(
    r'DBNAME_Entry\("(entrezgene|ncbi_geneid)"')

#: The tables `processKEGGMappingData()` -- and only it -- inserts.
KEGG_MAPPING_TABLES = ("kegg_id", "kegg_gene_symbol", "kegg_gene_symbol_synonyms")

#: getDatabasesByOrganismCode's fallback for any species absent from dicDatabases.
FALLBACK_TABLES = ("kegg_id", "kegg_gene_symbol")


def buildScriptFor(organism):
    """The species' own build script, or None when it uses scripts/default/."""
    path = os.path.join(SCRIPTS_DIR, organism + "_resources", "build_database.py")
    return path if os.path.isfile(path) else None


def callsKeggMappingBuilder(scriptPath):
    """True only for a LIVE call -- a commented-out one is what caused this bug."""
    with open(scriptPath, encoding="utf-8") as handle:
        for line in handle:
            if re.match(r"\s*(COMMON_BUILD_DB_TOOLS\.)?processKEGGMappingData\(\)", line):
                return True
    return False


class FakeCollection(object):
    """A `dbname` collection that holds nothing -- the state dme was actually in."""

    @staticmethod
    def find_one(*_args, **_kwargs):
        return None

    @staticmethod
    def find(*_args, **_kwargs):
        return iter(())


class FakeDatabase(object):
    name = "dme-paintomics"
    dbname = FakeCollection()


class TestConfiguredIdentifierTablesAreBuilt(unittest.TestCase):

    def test_species_declaring_a_kegg_table_actually_build_it(self):
        """Declaring `kegg_id` without building it crashes every job on the species."""
        broken = []
        for organism, (geneTables, symbolTables) in sorted(dicDatabases.items()):
            declared = set(geneTables.values()) | set(symbolTables.values())
            if not declared & set(KEGG_MAPPING_TABLES):
                continue
            scriptPath = buildScriptFor(organism)
            if scriptPath is None:
                continue  # scripts/default/build_database.py calls it unconditionally
            if not callsKeggMappingBuilder(scriptPath):
                broken.append("%s declares %s but its build script never calls "
                              "processKEGGMappingData()"
                              % (organism, sorted(declared & set(KEGG_MAPPING_TABLES))))
        self.assertEqual([], broken, "\n  ".join([""] + broken))

    def test_species_falling_back_to_kegg_tables_actually_build_them(self):
        """A species absent from dicDatabases inherits kegg_id -- same requirement."""
        broken = []
        for entry in sorted(os.listdir(SCRIPTS_DIR)):
            if not entry.endswith("_resources"):
                continue
            organism = entry[: -len("_resources")]
            # `common_resources` holds shared download config, not a species.
            if organism in dicDatabases or organism == "common":
                continue
            scriptPath = buildScriptFor(organism)
            if scriptPath is None or not callsKeggMappingBuilder(scriptPath):
                broken.append("%s is absent from dicDatabases, so it falls back to %s, "
                              "but its build script never calls processKEGGMappingData()"
                              % (organism, list(FALLBACK_TABLES)))
        self.assertEqual([], broken, "\n  ".join([""] + broken))

    def test_every_name_for_the_ncbi_gene_space_can_bridge(self):
        """Both builder names for NCBI gene ids must be bridgeable, or islands form.

        dme is built by processEnsemblData AND processKEGGMappingData, so its
        FlyBase ids sat in the Ensembl island and kegg_id sat in the KEGG island.
        Every one of a real user's 1,325 identifiers had a complete path across
        (FBgn0000147 -> entrezgene 41446 -> ncbi_geneid 41446 -> kegg_id
        Dmel_CG3068) and not one could be walked: `ncbi_geneid` was not a
        declared bridge, so the job mapped 0 features and reported success.
        """
        with open(COMMON_BUILDER, encoding="utf-8") as handle:
            built = set(NCBI_GENE_TABLE_PATTERN.findall(handle.read()))

        self.assertTrue(built, "no NCBI gene table found in common_build_database.py")
        missing = sorted(built - set(GENE_LEVEL_BRIDGE_DATABASES))
        self.assertEqual(
            [], missing,
            "the builders file NCBI gene ids as %s, but %s cannot be bridged "
            "through, so those groups cannot reach the others"
            % (sorted(built), missing))

    def test_missing_identifier_table_names_itself(self):
        """The failure must be diagnosable from the message the user is shown."""
        with self.assertRaises(Exception) as caught:
            resolveDatabaseIds("dme", ["KEGG"], db=FakeDatabase())

        self.assertNotIsInstance(
            caught.exception, AttributeError,
            "a missing identifier table must not surface as AttributeError: "
            "'NoneType' object has no attribute 'get'")

        message = str(caught.exception)
        for expected in ("dme", "KEGG", "kegg_id"):
            self.assertIn(expected, message,
                          "the error must name " + expected + ", got: " + message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
