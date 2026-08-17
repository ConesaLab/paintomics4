"""The in-memory kegg_compounds table answers exactly like the MongoDB query.

`findCompoundIDByFeatureName` used to run one case-insensitive substring
$regex per metabolite name against the 93k-document kegg_compounds
collection -- a full collection scan each (20-50 ms), 40 s for a 4,667-row
file even across six workers. `_CompoundNameTable` answers the same
`find({"name": {"$regex": ...}}).limit(n)` calls from a lower-cased
haystack string in RAM. This test is the equivalence proof:

  * against a FAKE collection with hand-picked tricky names, the table must
    return the same documents in the same order as evaluating the regex over
    the documents (what MongoDB does, natural order), for the substring
    shape, the anchored exact shape, and an arbitrary pattern that takes the
    generic fallback;
  * against the REAL local MongoDB (skipped when it is not reachable), for
    every distinct compound name in the bundled example files plus a set of
    generic/metacharacter/placeholder names, the table and Mongo must agree
    on the ordered list of (id, name) hits under the exact call sequence
    findCompoundIDByFeatureName makes.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_compound_name_table_matches_mongo
"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.common import FeatureNamesToKeggIDsMapper as mapper


TRICKY = ["Adenosine 5'-triphosphate", "NAD+", "NADH", "NADP+", "L-Leucine",
          "Leucine", "D-Glucose", "Glucose", "Glucose 6-phosphate", "(R)-Lactate",
          "Acid", "acid", "GlcA-β1,3-GlcNAc ", "20αH-PREDL ", "H2O", "h2o",
          "a.b", "a*b", "[x]", "x|y", "$5", "^start", "end$", "back\\slash"]


class _RegexCollection(object):
    """What MongoDB does: evaluate the regex over the documents in order."""

    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        pattern = query["name"]["$regex"]
        return mapper._CompoundNameCursor([d for d in self.docs if pattern.search(d["name"])])


def _docs(names):
    return [{"id": "C%05d" % i, "name": n} for i, n in enumerate(names)]


def _lookupCalls(name):
    """The exact patterns findCompoundIDByFeatureName issues for a name."""
    substring = re.compile(re.escape(name), re.IGNORECASE)
    exact = re.compile("^" + re.escape(name) + "$", re.IGNORECASE)
    return substring, exact


class TableAgreesWithRegexOnTrickyNamesTest(unittest.TestCase):

    def setUp(self):
        self.docs = _docs(TRICKY)
        self.table = mapper._CompoundNameTable(self.docs)
        self.reference = _RegexCollection(self.docs)

    def _same(self, pattern, limit=None):
        got = self.table.find({"name": {"$regex": pattern}})
        want = self.reference.find({"name": {"$regex": pattern}})
        if limit is not None:
            got, want = got.limit(limit), want.limit(limit)
        self.assertEqual(list(got), list(want), pattern.pattern)

    def test_substring_and_exact_shapes_for_every_tricky_name(self):
        for name in TRICKY + ["glucose", "acid", "a", "-", "leu", "GLC", "β1"]:
            substring, exact = _lookupCalls(name)
            self._same(substring)
            self._same(exact)
            self._same(substring, limit=3)

    def test_the_fast_path_is_taken_for_escaped_literals(self):
        substring, exact = _lookupCalls("(R)-Lactate")
        self.assertEqual(self.table._literalOf(substring), ("(R)-Lactate", False))
        self.assertEqual(self.table._literalOf(exact), ("(R)-Lactate", True))

    def test_an_arbitrary_pattern_takes_the_generic_path_and_still_agrees(self):
        for pattern in (re.compile(r"glu.*ose", re.IGNORECASE), re.compile(r"NAD[HP]")):
            self.assertIsNone(self.table._literalOf(pattern)[0])
            self._same(pattern)
        # Escaped literals without IGNORECASE also take the generic path.
        for pattern in (re.compile(r"^H2O$"), re.compile(r"acid", 0)):
            self._same(pattern)

    def test_findCompoundIDByFeatureName_gives_the_same_answer_through_the_table(self):
        for name in TRICKY + ["glucose", "-", "acid"]:
            viaTable = mapper.findCompoundIDByFeatureName("job", name, self.table)
            viaRegex = mapper.findCompoundIDByFeatureName("job", name, type("DB", (), {"kegg_compounds": self.reference})())
            self.assertEqual(viaTable, viaRegex, name)

    def test_a_name_with_a_newline_disables_the_fast_path_safely(self):
        table = mapper._CompoundNameTable(_docs(["ab\ncd", "abcd", "xx"]))
        self.assertFalse(table._fastPathOK)
        substring, _ = _lookupCalls("abcd")
        self.assertEqual([d["name"] for d in table.find({"name": {"$regex": substring}})], ["abcd"])


def _mongoAvailable():
    try:
        from pymongo import MongoClient
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        client = MongoClient(MONGODB_HOST, MONGODB_PORT, serverSelectionTimeoutMS=1500)
        return client["global-paintomics"].kegg_compounds.estimated_document_count() > 0
    except Exception:
        return False


@unittest.skipUnless(_mongoAvailable(), "MongoDB with global-paintomics not reachable")
class TableAgreesWithRealMongoTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from pymongo import MongoClient
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        cls.db = MongoClient(MONGODB_HOST, MONGODB_PORT)["global-paintomics"]
        cls.table = mapper.getCompoundNameTable(cls.db)

    def _exampleNames(self):
        root = os.path.join(os.path.dirname(__file__), "..", "examplefiles", "datasets")
        names = set()
        for path in glob.glob(os.path.join(root, "*", "data", "metabolomics_values.tab")):
            with open(path) as handle:
                for line in handle:
                    if line.startswith("#"):
                        continue
                    first = line.rstrip("\n").split("\t")[0]
                    if first:
                        names.add(first)
        return sorted(names)

    def test_every_example_and_probe_name_gets_the_same_hits(self):
        probes = ["glucose", "acid", "a", "-", "?", "NAD+", "(R)-Lactate", "L-Leucine",
                  "Leucine", "citrate", "Citric acid", "ATP", "H2O", "GlcA-β1,3-GlcNAc",
                  "PREDL", "hydroxy", "N/A", "C00001", "c00002"]
        names = self._exampleNames() + probes
        self.assertGreater(len(names), 100)
        checked = 0
        for name in names:
            got, gotFound = mapper.findCompoundIDByFeatureName("job", name, self.table)
            want, wantFound = mapper.findCompoundIDByFeatureName("job", name, self.db)
            self.assertEqual(gotFound, wantFound, name)
            self.assertEqual([(d.get("id"), d.get("name")) for d in got],
                             [(d.get("id"), d.get("name")) for d in want], name)
            checked += 1
        self.assertEqual(checked, len(names))


if __name__ == "__main__":
    unittest.main(verbosity=2)
