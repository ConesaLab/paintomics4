"""The mapping checker must recognise every shape this fault has taken.

Four species have shipped with a KEGG mapping that could not work, and only one
of them crashed. The other three reported success while translating nothing,
which is the reason this check exists at all -- an empty result reads to a user
as biology, not as a bug:

    dme/dre   the configured table was never built        -> AttributeError
    dosa      the table is registered and EMPTY           -> silent, 0 features
    cel       the table is populated with the WRONG space -> silent, 0 features
    sly       the table holds only part of the space      -> silent, 32% lost

Each is reproduced below against a fake MongoDB, so the check is proven to
catch the fault it was written for rather than assumed to.

Run:
    PYTHONPATH=PaintomicsServer python PaintomicsServer/src/tests/test_identifier_mapping_check.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.AdminTools.checkIdentifierMapping import (
    ERROR, INFO, WARNING, checkOrganism)

#: Every check below states the configuration it is checking rather than
#: reading organismDB.py. A test that depends on the live config fails the day
#: someone fixes the species it names -- which is exactly what these fixes do.
KEGG_BY_ID = [{"KEGG": "kegg_id"}, {"KEGG": "kegg_gene_symbol"}]
KEGG_BY_ENTREZ = [{"KEGG": "entrezgene"}, {"KEGG": "refseq_gene_symbol"}]


class FakeCollection(object):
    def __init__(self, documents):
        self.documents = documents

    def find(self, query=None, projection=None):
        return iter(self._matching(query or {}))

    def distinct(self, field, query=None):
        return sorted({document[field] for document in self._matching(query or {})
                       if field in document})

    def count_documents(self, query):
        return len(self._matching(query))

    def _matching(self, query):
        matched = []
        for document in self.documents:
            if self._matches(document, query):
                matched.append(document)
        return matched

    @staticmethod
    def _matches(document, query):
        for field, condition in query.items():
            if field == "$or":
                if not any(FakeCollection._matches(document, sub) for sub in condition):
                    return False
            elif isinstance(condition, dict):
                if "$in" in condition and document.get(field) not in condition["$in"]:
                    return False
                if "$exists" in condition and (field in document) != condition["$exists"]:
                    return False
            elif document.get(field) != condition:
                return False
        return True


class FakeDatabase(object):
    """A species database built from table -> [identifiers] and its pathways."""

    def __init__(self, tables, pathways):
        self.dbname = FakeCollection(
            [{"_id": index, "dbname": name} for index, name in enumerate(sorted(tables))])
        tableIDs = {name: index for index, name in enumerate(sorted(tables))}
        self.xref = FakeCollection(
            [{"_id": "%s:%s" % (name, value), "dbname_id": tableIDs[name],
              "display_id": value}
             for name, values in tables.items() for value in values])
        self.kegg = FakeCollection(pathways)


def keggPathways(geneIDs, source="KEGG"):
    return [{"source": source, "genes": [{"id": geneID} for geneID in geneIDs]}]


def severitiesFor(findings, severity):
    return [finding for finding in findings if finding.severity == severity]


class TestIdentifierMappingCheck(unittest.TestCase):

    def test_a_configured_table_that_was_never_built_is_an_error(self):
        """dme/dre: find_one returns None and every job dies at step 1."""
        db = FakeDatabase({"reactome_gene_id": ["MYCA"]},
                          keggPathways(["323107", "327165"]))
        findings = checkOrganism(db, "dre", KEGG_BY_ID)
        errors = severitiesFor(findings, ERROR)
        self.assertTrue(errors, "a missing configured table must be an error")
        self.assertIn("does not exist", errors[0].message)
        self.assertIn("kegg_id", errors[0].message)

    def test_a_registered_but_empty_table_is_an_error(self):
        """dosa: resolves fine, maps nothing, reports success -- the worst shape."""
        db = FakeDatabase({"kegg_id": [], "kegg_gene_symbol": ["OsX"]},
                          keggPathways(["Os01g0147900", "Os01g0841600"]))
        findings = checkOrganism(db, "dosa", [{"KEGG": "kegg_id"},
                                              {"KEGG": "kegg_gene_symbol"}])
        errors = severitiesFor(findings, ERROR)
        self.assertTrue(errors, "an empty identifier table must be an error")
        self.assertIn("EMPTY", errors[0].message)

    def test_a_table_in_the_wrong_identifier_space_is_an_error(self):
        """cel: populated, resolves, and matches none of the pathway genes."""
        db = FakeDatabase(
            {"kegg_id": ["13222292", "179427"],          # numeric NCBI ids
             "kegg_gene_symbol": ["set-10"]},
            keggPathways(["CELE_C17G1.7", "CELE_F59A7.9"]))   # KEGG's own space
        findings = checkOrganism(db, "cel", KEGG_BY_ID)
        errors = severitiesFor(findings, ERROR)
        self.assertTrue(errors, "0% coverage must be an error, not a warning")
        self.assertIn("0 of 2", errors[0].message)

    def test_a_partially_covering_table_is_reported_with_the_better_one(self):
        """sly: 68% is not an annotation gap, and the fix is already installed."""
        pathwayGenes = ["1", "2", "3", "4", "5"]
        db = FakeDatabase(
            {"entrezgene": ["1", "2"],                    # covers 40%
             "kegg_id": pathwayGenes,                     # covers 100%
             "refseq_gene_symbol": ["symA"]},
            keggPathways(pathwayGenes))
        # `ptr` still names entrezgene, and correctly so -- KEGG really does key
        # chimpanzee on NCBI gene ids. It stands in here for the shape sly had.
        findings = checkOrganism(db, "ptr", KEGG_BY_ENTREZ)
        flagged = severitiesFor(findings, WARNING) + severitiesFor(findings, ERROR)
        self.assertTrue(flagged, "40% coverage must be reported")
        self.assertIn("kegg_id", flagged[0].message,
                      "the finding must name the better table that is installed")

    def test_an_empty_gene_symbol_table_is_a_warning_not_an_error(self):
        """18 installed bacteria and fungi are in this state and work fine.

        KEGG publishes no gene symbols for them. Identifiers still map; only
        the display pass has nothing to say. Grading it as an error would bury
        the four species that really are broken under eighteen that are not.
        """
        db = FakeDatabase({"kegg_id": ["a", "b"], "kegg_gene_symbol": []},
                          keggPathways(["a", "b"]))
        findings = checkOrganism(db, "afm", KEGG_BY_ID)
        self.assertEqual([], severitiesFor(findings, ERROR),
                         "an empty symbol table does not stop a job mapping")
        warnings = severitiesFor(findings, WARNING)
        self.assertTrue(warnings)
        self.assertIn("cannot be matched by symbol", warnings[0].message)

    def test_a_missing_gene_symbol_table_is_still_an_error(self):
        """Absent is not the same as empty: resolveDatabaseIds raises on absent."""
        db = FakeDatabase({"kegg_id": ["a"]}, keggPathways(["a"]))
        findings = checkOrganism(db, "dre", KEGG_BY_ID)
        errors = severitiesFor(findings, ERROR)
        self.assertTrue(errors, "a missing symbol table crashes the job")
        self.assertIn("kegg_gene_symbol", errors[0].message)

    def test_a_correct_species_produces_no_error_or_warning(self):
        """The check has to stay quiet on the 129 species that are fine."""
        genes = ["Os01g0147900", "Os02g0171100"]
        db = FakeDatabase({"kegg_id": genes, "kegg_gene_symbol": ["symA"]},
                          keggPathways(genes))
        findings = checkOrganism(db, "dosa", KEGG_BY_ID)
        self.assertEqual([], severitiesFor(findings, ERROR))
        self.assertEqual([], severitiesFor(findings, WARNING))

    def test_installed_pathways_with_no_configured_mapping_are_information(self):
        """bvu's MapMan: unreachable, but never offered, so not a broken job."""
        db = FakeDatabase({"kegg_id": ["a"], "kegg_gene_symbol": ["s"],
                           "mapman_gene_id": ["1.1"]},
                          keggPathways(["a"]) + keggPathways(["1.1"], source="MapMan"))
        findings = checkOrganism(db, "bvu", KEGG_BY_ID)
        self.assertEqual([], severitiesFor(findings, ERROR))
        infos = severitiesFor(findings, INFO)
        self.assertTrue(infos)
        self.assertEqual("MapMan", infos[0].database)

    def test_a_species_absent_from_the_config_is_checked_on_the_fallback(self):
        """ptr and acs were broken precisely because nobody checked the fallback."""
        db = FakeDatabase({"entrezgene": ["1"]}, keggPathways(["1"]))
        findings = checkOrganism(db, "no-such-species")   # falls back to kegg_id
        errors = severitiesFor(findings, ERROR)
        self.assertTrue(errors, "the fallback tables must be checked too")
        self.assertIn("kegg_id", errors[0].message)

    def test_the_mandatory_database_says_it_cannot_be_deselected(self):
        """A KEGG fault is unavoidable; the report should say so."""
        db = FakeDatabase({"reactome_gene_id": ["X"]}, keggPathways(["1"]))
        findings = checkOrganism(db, "dre", KEGG_BY_ID)
        self.assertIn("KEGG cannot be deselected",
                      severitiesFor(findings, ERROR)[0].message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
