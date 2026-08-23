#!/usr/bin/env python3
"""Numbers reach prose as fact ids, and the gate can prove it.

Why this exists
---------------
The old verification pass ATTRIBUTED numbers after writing: find "412" in a
sentence, search the tool results for something that could have said it. The
measured failure is misattribution -- a real number with the wrong subject.
The FactsLedger inverts the direction: tools register numbers, prose carries
``{{fN}}`` tokens, the gate substitutes. These tests pin the whole contract:
ids are stable, the same fact never mints two ids, substitution is exact,
unknown tokens stay visible, and the bare-number scan catches what must not
be in a Results sentence while sparing what may (citations, years, figure
references, condition labels, digits inside gene names).

Usage:
    cd PaintomicsServer
    python -m src.tests.test_facts_ledger_substitution
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

os.environ.setdefault("AI_CSIC_API_KEY", "test-key-not-used")

from src.classes.AIInterpret.facts import (  # noqa: E402
    FactsLedger, bare_numbers, format_value)


class LedgerTest(unittest.TestCase):

    def test_ids_are_sequential_and_stable(self):
        ledger = FactsLedger()
        a = ledger.add("pvalue", 3.2e-4, {"pathway": "mmu04110"}, "enrich")
        b = ledger.add("count", 412, {"set": "shared"}, "compare_sets")
        self.assertEqual((a, b), ("f1", "f2"))
        self.assertEqual(len(ledger), 2)

    def test_the_same_fact_never_mints_two_ids(self):
        ledger = FactsLedger()
        a = ledger.add("pvalue", 3.2e-4, {"pathway": "mmu04110"}, "enrich")
        again = ledger.add("pvalue", 3.2e-4, {"pathway": "mmu04110"}, "enrich")
        other = ledger.add("pvalue", 3.2e-4, {"pathway": "mmu04151"}, "enrich")
        self.assertEqual(a, again)
        self.assertNotEqual(a, other)

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            FactsLedger().add("vibes", 1.0)

    def test_tag_prints_the_marker_a_tool_embeds(self):
        ledger = FactsLedger()
        self.assertEqual(ledger.tag("count", 7), "[f1]")


class FormattingTest(unittest.TestCase):

    def test_small_p_is_scientific(self):
        self.assertEqual(format_value("pvalue", 3.2e-4), "3.2×10^-4")

    def test_ordinary_p_is_plain(self):
        self.assertEqual(format_value("pvalue", 0.032), "0.032")

    def test_percent_count_r2(self):
        # 42.65 is not representable in binary and rounds DOWN under %.1f;
        # the rule under test is one-decimal-and-strip, not half-up rounding.
        self.assertEqual(format_value("percent", 42.68), "42.7%")
        self.assertEqual(format_value("percent", 42.0), "42%")
        self.assertEqual(format_value("count", 412.0), "412")
        self.assertEqual(format_value("r2", 0.8712), "0.87")

    def test_coef_keeps_its_sign(self):
        self.assertEqual(format_value("coef", -1.847), "-1.85")


class SubstitutionTest(unittest.TestCase):

    def test_tokens_become_formatted_values(self):
        ledger = FactsLedger()
        fid = ledger.add("pvalue", 3.2e-4, {}, "enrich")
        out, used, unknown = ledger.substitute(
            "the cell cycle was enriched (p = {{%s}})" % fid)
        self.assertEqual(out, "the cell cycle was enriched (p = 3.2×10^-4)")
        self.assertEqual(used, [fid])
        self.assertEqual(unknown, [])

    def test_an_unknown_token_stays_visible(self):
        out, used, unknown = FactsLedger().substitute("p = {{f99}}")
        self.assertIn("{{f99}}", out)
        self.assertEqual(unknown, ["f99"])

    def test_whitespace_inside_the_token_is_tolerated(self):
        ledger = FactsLedger()
        fid = ledger.add("count", 412)
        out, _, _ = ledger.substitute("{{ %s }} genes" % fid)
        self.assertEqual(out, "412 genes")


class BareNumberTest(unittest.TestCase):

    def test_a_bare_count_is_caught(self):
        offenders = bare_numbers("we found 412 shared genes")
        self.assertEqual([o[0] for o in offenders], ["412"])

    def test_a_token_is_not_a_bare_number(self):
        self.assertEqual(bare_numbers("we found {{f2}} shared genes"), [])

    def test_citations_figures_years_are_allowed(self):
        text = ("as reported [3] and reviewed [4-6], consistent with Fig. 2 "
                "and Supplementary Table S1, first shown in 2024")
        self.assertEqual(bare_numbers(text), [])

    def test_condition_labels_are_names_not_measurements(self):
        text = "expression rose between Day 0 and Day 7"
        self.assertEqual(bare_numbers(text, ["Day 0", "Day 7"]), [])
        # ...but only the labels the job declares are spared.
        self.assertTrue(bare_numbers(text, ["Day 0"]))

    def test_digits_inside_identifiers_are_not_numbers(self):
        self.assertEqual(bare_numbers("p53 and IL6 via mmu04110"), [])

    def test_scientific_notation_is_caught(self):
        offenders = bare_numbers("enriched at p = 3.2e-4")
        self.assertEqual([o[0] for o in offenders], ["3.2e-4"])


class SupplementaryTableTest(unittest.TestCase):

    def test_tsv_traces_value_scope_and_tool(self):
        ledger = FactsLedger()
        ledger.add("pvalue", 3.2e-4, {"pathway": "mmu04110", "omic": "RNA"},
                   "enrich_collection", call_seq=5)
        tsv = ledger.to_tsv()
        lines = tsv.strip().splitlines()
        self.assertEqual(lines[0].split("\t")[0], "fact_id")
        self.assertIn("omic=RNA; pathway=mmu04110", lines[1])
        self.assertIn("enrich_collection", lines[1])
        self.assertIn("3.2×10^-4", lines[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
