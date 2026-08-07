#!/usr/bin/env python3
"""Cover for the MORE submission-form coercion in src/servlets/MOREServlet.py.

Why these are separate functions
--------------------------------
fromMOREtoGenes_STEP1/STEP2 need a Mongo-backed session, a writable job
directory and an Rscript subprocess, so neither is reachable from a unit test.
The form-parsing inside them is pure, though, and it was where the bugs were,
so it now lives in _toFloat / _parseMinVariation / _nonEmpty and is tested
here directly.

The bug that motivated the extraction
-------------------------------------
Step 1 read the model parameters as::

    jobInstance.alpha = float(formFields.get("more_alpha", 0.05))

``dict.get``'s default only applies when the key is *absent*. A form posts
fields that are present and empty, so ``more_alpha=`` gave ``float("")`` and

    ValueError: could not convert string to float: ''

which the blanket ``except Exception`` turned into that raw text as the user's
error message. The client marks these ``allowBlank: false``, but it also
*hides* the alpha and VIP fields whenever the method is not PLS1 -- and a
hidden ExtJS field still posts its value. The endpoint is in any case reachable
by any HTTP client, so client-side validation cannot be the only guard.

The same handler already parsed ``more_minvar_<i>`` defensively, which is what
marked the difference as an oversight rather than a decision.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_more_servlet_params
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.servlets.MOREServlet import _nonEmpty, _parseMinVariation, _toFloat


class ToFloatTest(unittest.TestCase):

    def test_parses_a_normal_value(self):
        self.assertEqual(_toFloat("0.01", 0.05), 0.01)
        self.assertEqual(_toFloat("1", 0.05), 1.0)

    def test_accepts_a_value_that_is_already_numeric(self):
        self.assertEqual(_toFloat(0.02, 0.05), 0.02)
        self.assertEqual(_toFloat(3, 0.05), 3.0)

    def test_blank_falls_back_to_the_default(self):
        """The regression: a present-but-empty field used to raise."""
        for blank in ["", "   ", "\t", None]:
            with self.subTest(blank=repr(blank)):
                self.assertEqual(_toFloat(blank, 0.05), 0.05)

    def test_junk_falls_back_to_the_default(self):
        for junk in ["abc", "0.5.5", "--", "1e", "NaN-ish"]:
            with self.subTest(junk=junk):
                self.assertEqual(_toFloat(junk, 0.05), 0.05)

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(_toFloat("  0.01  ", 0.05), 0.01)

    def test_never_raises_for_any_input(self):
        """This runs inside a request handler; raising becomes a 'failed' job."""
        for value in ["", None, "x", [], {}, object(), b"0.5", "1,5"]:
            with self.subTest(value=repr(value)):
                self.assertIsInstance(_toFloat(value, 0.05), float)

    def test_the_real_default_for_each_field(self):
        self.assertEqual(_toFloat("", 0.05), 0.05)   # more_alpha
        self.assertEqual(_toFloat("", 0.8), 0.8)     # more_vip
        self.assertEqual(_toFloat("", 0.0), 0.0)     # more_filter_r2


class ParseMinVariationTest(unittest.TestCase):

    def test_blank_and_sentinels_become_the_auto_marker(self):
        """runMORE.R reads "NA" as 'use 10% of max observed variability'."""
        for value in ["", "   ", None, "auto", "AUTO", "na", "NA", "Na"]:
            with self.subTest(value=repr(value)):
                self.assertEqual(_parseMinVariation(value), "NA")

    def test_parses_a_numeric_threshold(self):
        self.assertEqual(_parseMinVariation("0.1"), 0.1)
        self.assertEqual(_parseMinVariation(" 0.25 "), 0.25)

    def test_negative_is_clamped_to_zero(self):
        """A negative variation threshold is meaningless to MORE."""
        self.assertEqual(_parseMinVariation("-1"), 0.0)

    def test_junk_falls_back_to_mores_documented_default(self):
        for junk in ["abc", "0.1.2", "--"]:
            with self.subTest(junk=junk):
                self.assertEqual(_parseMinVariation(junk), 0.0)

    def test_result_is_always_stringifiable_for_the_r_command_line(self):
        """STEP2 builds --min_variation by str()-joining these."""
        for value in ["", "auto", "0.1", "-3", "junk", None]:
            with self.subTest(value=repr(value)):
                self.assertIsInstance(str(_parseMinVariation(value)), str)

    def test_zero_is_kept_and_not_confused_with_blank(self):
        """0.0 means 'keep all but constant regulators'; NA means 'auto'."""
        self.assertEqual(_parseMinVariation("0"), 0.0)
        self.assertNotEqual(_parseMinVariation("0"), "NA")


class NonEmptyTest(unittest.TestCase):

    def test_keeps_a_real_choice(self):
        self.assertEqual(_nonEmpty("MLR", "PLS1"), "MLR")

    def test_blank_falls_back(self):
        for blank in ["", "   ", None]:
            with self.subTest(blank=repr(blank)):
                self.assertEqual(_nonEmpty(blank, "PLS1"), "PLS1")

    def test_strips_whitespace(self):
        self.assertEqual(_nonEmpty("  MLR  ", "PLS1"), "MLR")

    def test_enrichment_default(self):
        self.assertEqual(_nonEmpty("", "genes"), "genes")
        self.assertEqual(_nonEmpty("compounds", "genes"), "compounds")


class SubmittedFormTest(unittest.TestCase):
    """The combinations a real submission actually produces."""

    def test_an_mlr_submission_with_the_hidden_pls1_fields_cleared(self):
        """The client hides alpha/VIP for MLR; hidden ExtJS fields still post."""
        form = {"more_method": "MLR", "more_alpha": "", "more_vip": "",
                "more_filter_r2": "0.3", "more_enrichment": ""}
        self.assertEqual(_nonEmpty(form.get("more_method"), "PLS1"), "MLR")
        self.assertEqual(_toFloat(form.get("more_alpha"), 0.05), 0.05)
        self.assertEqual(_toFloat(form.get("more_vip"), 0.8), 0.8)
        self.assertEqual(_toFloat(form.get("more_filter_r2"), 0.0), 0.3)
        self.assertEqual(_nonEmpty(form.get("more_enrichment"), "genes"), "genes")

    def test_a_completely_empty_post_yields_every_documented_default(self):
        form = {}
        self.assertEqual(_nonEmpty(form.get("more_method"), "PLS1"), "PLS1")
        self.assertEqual(_toFloat(form.get("more_alpha"), 0.05), 0.05)
        self.assertEqual(_toFloat(form.get("more_vip"), 0.8), 0.8)
        self.assertEqual(_toFloat(form.get("more_filter_r2"), 0.0), 0.0)
        self.assertEqual(_nonEmpty(form.get("more_enrichment"), "genes"), "genes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
