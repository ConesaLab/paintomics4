#!/usr/bin/env python3
"""The organism picker must find what the user means, not what they spelt.

What this guards
----------------
Step 1's organism combo (and the "Request a new organism" dialog's) used the
stock ExtJS local query, which keeps a row only when the display name STARTS
with the typed text. So "mouse" found nothing -- the row is "Mus musculus
(house mouse)" -- and a single typo emptied the list. Users type the common
name, the KEGG code, a genus, a strain, or a misspelling of any of those, and
the picker has to rank the organism they mean first for all of them.

The ranking lives in app/view/common/OrganismSearch.js, a module with no
DOM or ExtJS dependency so node can run it exactly as the browser does. The
list it is run against here is the one paintomics.uv.es served on 2026-08-21
(organisms_paintomics_uv.json): 133 real organisms, the population the picker
actually searches in production, with the collisions that matter -- two
yeasts, three rices, "licorice" hiding "rice", "Streptococcus mutans" hiding
"mus", two Nostocs and a quoted name.

Why a Python file runs a JavaScript module
------------------------------------------
The client has no test harness of its own; every client contract in this
directory is checked from here (see test_validator_agrees_with_server for the
same pattern). The module is loaded with node's require, so what is tested is
the file as shipped, not an extract.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_organism_search
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_ROOT = os.path.abspath(os.path.join(HERE, "../../../PaintomicsClient/public_html"))
MODULE = os.path.join(CLIENT_ROOT, "app/view/common/OrganismSearch.js")
FIXTURE = os.path.join(HERE, "organisms_paintomics_uv.json")
ALL_SPECIES = os.path.join(CLIENT_ROOT, "resources/data/all_species.json")
STEP1_VIEWS = os.path.join(CLIENT_ROOT, "app/view/PathwayAcquisitionViews/PA_Step1Views.js")
DATA_MANAGEMENT = os.path.join(CLIENT_ROOT, "app/controller/DataManagementController.js")
INDEX_HTML = os.path.join(CLIENT_ROOT, "index.html")

NODE = shutil.which("node")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def node(expression, listPath=FIXTURE):
    """Evaluates `expression` with the module as S and the organism list as L."""
    script = (
        "const S = require(%s);"
        "const L = require(%s).species;"
        "process.stdout.write(JSON.stringify(%s));"
    ) % (json.dumps(MODULE), json.dumps(listPath), expression)
    result = subprocess.run([NODE, "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise AssertionError("node failed: " + result.stderr.decode("utf-8", "replace"))
    return json.loads(result.stdout.decode("utf-8"))


def codes(query):
    """KEGG codes in the order the picker would list them for `query`."""
    return node("S.rank(%s, L).map(r => r.value)" % json.dumps(query))


@unittest.skipIf(NODE is None, "node is not available")
class CommonNamesAndCodes(unittest.TestCase):
    """The ways people actually refer to an organism all have to land first."""

    def test_common_name_word_finds_house_mouse_first(self):
        # The report that started this: "mouse" found nothing.
        self.assertEqual("mmu", codes("mouse")[0])
        self.assertEqual("mmu", codes("Mouse")[0])
        self.assertEqual("mmu", codes("  MOUSE ")[0])

    def test_kegg_code_is_an_exact_hit(self):
        self.assertEqual("hsa", codes("hsa")[0])
        self.assertEqual("mmu", codes("mmu")[0])
        self.assertEqual("rno", codes("rno")[0])

    def test_genus_word_beats_a_prefix_elsewhere(self):
        # "pan" is the chimpanzee's genus and the start of the pangolin's name.
        ranked = codes("pan")
        self.assertEqual("ptr", ranked[0])
        self.assertIn("mjv", ranked)
        self.assertEqual("mmu", codes("mus")[0])

    def test_the_whole_common_name_beats_a_word_of_one(self):
        # "rat" is all of the rat's common name, and a word of no other.
        self.assertEqual("rno", codes("rat")[0])

    def test_scientific_name_prefix(self):
        self.assertEqual("ath", codes("arab")[0])
        self.assertEqual("hsa", codes("homo")[0])
        self.assertEqual("hsa", codes("sapiens")[0])

    def test_every_match_for_a_shared_common_name_is_kept(self):
        ranked = codes("rice")
        # The three rices first (two share a name), licorice after them.
        self.assertEqual({"osa", "dosa", "ogl"}, set(ranked[:3]))
        self.assertIn("aprc", ranked[3:])

    def test_two_yeasts_both_listed(self):
        ranked = codes("yeast")
        self.assertEqual({"sce", "spo"}, set(ranked[:2]))
        self.assertEqual("sce", ranked[0])


@unittest.skipIf(NODE is None, "node is not available")
class Typos(unittest.TestCase):
    """One slip in a word of four or more letters still finds the organism."""

    def test_transposed_letters(self):
        self.assertEqual("mmu", codes("mosue")[0])
        self.assertEqual("mmu", codes("muose")[0])

    def test_one_wrong_letter(self):
        self.assertEqual("hsa", codes("humna")[0])
        self.assertEqual("hsa", codes("hunan")[0])
        self.assertEqual("ath", codes("arabidpsis")[0])

    def test_a_missing_letter(self):
        self.assertEqual("dre", codes("zebrfish")[0])
        self.assertEqual("sly", codes("tomto")[0])

    def test_two_slips_in_a_long_word(self):
        self.assertEqual("ath", codes("arabadopsos")[0])
        self.assertEqual("dme", codes("drosofila")[0])

    def test_short_tokens_are_not_fuzzed(self):
        # Three letters is too short to guess at: "cat" must not become "rat".
        self.assertNotIn("rno", codes("cat"))
        self.assertEqual([], codes("qzx"))

    def test_nonsense_finds_nothing(self):
        self.assertEqual([], codes("qzxvwy"))
        self.assertEqual([], codes("xxxxxxxxxxxx"))


@unittest.skipIf(NODE is None, "node is not available")
class MultiWordQueries(unittest.TestCase):
    """Every word of the query has to match; the words may be in any order."""

    def test_initial_plus_species(self):
        self.assertEqual("eco", codes("e coli")[0])
        self.assertEqual("cel", codes("c elegans")[0])
        self.assertEqual("sce", codes("s cerevisiae")[0])

    def test_split_common_name(self):
        self.assertEqual("dre", codes("zebra fish")[0])
        self.assertEqual("dme", codes("fruit fly")[0])
        self.assertEqual("mmu", codes("house mouse")[0])

    def test_word_order_does_not_matter(self):
        self.assertEqual("mmu", codes("mouse house")[0])
        self.assertEqual("hsa", codes("sapiens homo")[0])

    def test_a_word_that_matches_nothing_empties_the_list(self):
        self.assertEqual([], codes("mouse qzxvwy"))

    def test_joined_and_hyphenated_strains(self):
        self.assertEqual("eco", codes("k12")[0])
        self.assertEqual("eco", codes("K-12")[0])
        self.assertEqual("eco", codes("ecoli")[0])

    def test_a_single_letter_is_a_genus_initial(self):
        # "x" is a whole word of "Citrus x clementina"; an initial is not a word.
        self.assertEqual(["xtr"], codes("x"))
        self.assertEqual("hsa", codes("h sapiens")[0])

    def test_quoted_names_search_by_their_words(self):
        self.assertEqual("naz", codes("azollae")[0])
        self.assertEqual({"naz", "ncf"}, set(codes("nostoc")[:2]))


@unittest.skipIf(NODE is None, "node is not available")
class EmptyQueryAndOrder(unittest.TestCase):

    def test_empty_query_lists_every_organism_alphabetically(self):
        listed = codes("")
        names = node("S.rank('', L).map(r => r.name)")
        self.assertEqual(133, len(listed))
        self.assertEqual(sorted(names, key=lambda n: n.lower()), names)

    def test_whitespace_only_is_empty(self):
        self.assertEqual(133, len(codes("   ")))

    def test_results_carry_name_value_and_score(self):
        top = node("S.rank('mouse', L)[0]")
        self.assertEqual({"name": "Mus musculus (house mouse)", "value": "mmu"},
                         {"name": top["name"], "value": top["value"]})
        self.assertGreater(top["score"], 0)

    def test_ties_are_broken_by_name(self):
        # Both Oryza sativa rows match "japanese rice" identically.
        ranked = codes("japanese rice")
        self.assertEqual(["osa", "dosa"], ranked[:2])


@unittest.skipIf(NODE is None, "node is not available")
class Highlighting(unittest.TestCase):
    """The dropdown marks what matched, and never injects markup from a name."""

    def highlight(self, name, query):
        return node("S.highlight(%s, %s)" % (json.dumps(name), json.dumps(query)))

    def test_marks_the_matched_word(self):
        self.assertEqual("Mus musculus (house <mark>mouse</mark>)",
                         self.highlight("Mus musculus (house mouse)", "mouse"))

    def test_marks_a_prefix(self):
        self.assertEqual("Mus musculus (<mark>hous</mark>e mouse)",
                         self.highlight("Mus musculus (house mouse)", "hous"))

    def test_marks_the_whole_word_a_typo_matched(self):
        self.assertEqual("Mus musculus (house <mark>mouse</mark>)",
                         self.highlight("Mus musculus (house mouse)", "mosue"))

    def test_marks_every_query_word(self):
        self.assertEqual("<mark>Homo</mark> <mark>sapiens</mark> (human)",
                         self.highlight("Homo sapiens (human)", "sapiens homo"))

    def test_escapes_html_in_the_name(self):
        self.assertEqual("a &lt;b&gt; &amp; c", self.highlight("a <b> & c", ""))
        self.assertEqual("<mark>a</mark> &lt;b&gt; &amp; c", self.highlight("a <b> & c", "a"))

    def test_no_query_returns_the_escaped_name(self):
        self.assertEqual("Mus musculus (house mouse)",
                         self.highlight("Mus musculus (house mouse)", ""))


@unittest.skipIf(NODE is None, "node is not available")
class RequestDialogScale(unittest.TestCase):
    """The request dialog searches every KEGG organism (11,550), per keystroke."""

    def test_ranks_eleven_thousand_organisms_in_well_under_a_keystroke(self):
        millis = node(
            "(() => { S.rank('mo', L); const t = process.hrtime.bigint();"
            " for (const q of ['m', 'mo', 'mou', 'mous', 'mouse']) S.rank(q, L);"
            " return Number(process.hrtime.bigint() - t) / 5e6; })()",
            listPath=ALL_SPECIES)
        self.assertLess(millis, 150, "%.1f ms per query" % millis)

    def test_an_english_word_beats_a_code_that_spells_it(self):
        # 253 KEGG codes spell a word of another organism's name: "fly" is a
        # Flavobacterium, "dog" a Desulfobulbus. The animal is what was meant.
        full = lambda q: node("S.rank(%s, L).map(r => r.value)" % json.dumps(q), listPath=ALL_SPECIES)
        self.assertEqual("dme", full("fly")[0])
        self.assertEqual("cfa", full("dog")[0])
        self.assertEqual("bta", full("cow")[0])
        # ...while a code nothing else spells is still an exact hit.
        self.assertEqual("hsa", full("hsa")[0])

    def test_initial_plus_species_over_the_full_list_finds_the_model_strain(self):
        # 286 E. coli strains; K-12 MG1655 is the one the initial means.
        full = lambda q: node("S.rank(%s, L).map(r => r.value)" % json.dumps(q), listPath=ALL_SPECIES)
        self.assertEqual("eco", full("e coli")[0])

    def test_fuzzy_query_over_the_full_list_finds_the_mouse(self):
        ranked = node("S.rank('mosue', L).map(r => r.value)", listPath=ALL_SPECIES)
        self.assertEqual("mmu", ranked[0])


class Wiring(unittest.TestCase):
    """Both organism combos use the ranked picker, and the page loads it."""

    def combo(self, source):
        start = source.index('itemId: "speciesCombobox"')
        return source[source.rindex("xtype:", 0, start):start]

    def test_step1_combo_is_the_organism_picker(self):
        self.assertIn("xtype: 'organismcombo'", self.combo(read(STEP1_VIEWS)))

    def test_request_dialog_combo_is_the_organism_picker(self):
        self.assertIn("xtype: 'organismcombo'", self.combo(read(DATA_MANAGEMENT)))

    def test_index_html_loads_the_module_before_the_app(self):
        html = read(INDEX_HTML)
        module = re.search(r'src="app/view/common/OrganismSearch\.js\?v=[0-9.]+"', html)
        self.assertIsNotNone(module, "OrganismSearch.js is not loaded with a ?v= marker")
        self.assertLess(module.start(), html.index('src="app.js'))

    def test_the_combo_never_uses_callparent(self):
        # The module is strict so node runs it as the browser does, and ExtJS
        # 4's callParent reads Function.caller, which strict mode removes. The
        # failure is "Cannot read properties of null (reading 'apply')" in
        # initComponent, the Step 1 view never builds, and the app shows its
        # generic boot-failure dialog. Superclass calls go through the
        # prototype instead.
        source = read(MODULE)
        self.assertEqual(-1, source.find("callParent"), "callParent in OrganismSearch.js")
        self.assertIn('"use strict"', source)

    def test_module_is_loadable_without_extjs(self):
        # node has no Ext; the ranking half must not need it.
        self.assertIsNotNone(NODE)
        result = subprocess.run([NODE, "-e", "require(%s)" % json.dumps(MODULE)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
