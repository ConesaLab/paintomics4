#!/usr/bin/env python3
"""A citation with no supporting quote must be reported, not passed.

Why this exists
---------------
`verify_report_v2` exists to catch claims the papers do not support. Two of its
checks had nothing holding them:

    if not cited_text:
        failed_citations.append({... "reason": "Reference [N] has no Cited Text" ...})
        continue

Replace that condition with `if False:` and the whole suite still passes -- so a
reference carrying no quotation at all would come back verified. That is the
exact failure the stage is for: an unsupported claim reported as supported, in a
tool whose output is meant to be publication-ready.

The same run showed `_fuzzy_contains` has no direct tests either. Its empty-input
branch is unreachable from this caller, which guards both arguments before
calling it, so the branch is defensive rather than load-bearing -- but the
matcher's actual contract, that a quote absent from the paper does not match, is
worth pinning since it is what separates a grounded citation from an invented
one.

Found by mutating guards this session did not write: five of six mutations were
caught by an existing test, and this was the one that was not.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_citation_grounding
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.verification import _fuzzy_contains, verify_report_v2

PAPER_TEXT = ("Ikaros drives B-cell differentiation and represses the myeloid "
              "programme in murine progenitors.")


def _paper(refIndex=1, pmid="12345"):
    return {"ref_index": refIndex, "pmid": pmid, "title": "Smith 2020",
            "abstract": PAPER_TEXT, "sections": {}}


class _StubJob:
    """The minimum _check_pvalues touches.

    verify_report_v2 always receives a real job from the pipeline, so this
    stands in rather than the production code being loosened to accept None --
    that would be widening the contract to suit a fixture.
    """

    def getMatchedPathways(self):
        return {}


def _report(citedTextBlock):
    """A minimal report whose single reference carries the given quote block."""
    return ("Ikaros represses the myeloid programme [1].\n\n"
            "### References\n"
            "[1] Smith 2020. PMID: 12345\n" + citedTextBlock)


class CitationGroundingTest(unittest.TestCase):

    def _verify(self, report):
        return verify_report_v2(report, ["IKZF1"], [_paper()], _StubJob())

    def _reasons(self, result):
        return " | ".join(f.get("reason", "") for f in result["failed_citations"])

    def test_a_reference_with_no_quote_is_flagged(self):
        """The guard the mutation run found unprotected."""
        result = self._verify(_report(""))

        self.assertTrue(result["failed_citations"],
                        "a reference carrying no Cited Text was reported as "
                        "verified, which is the unsupported claim this stage "
                        "exists to catch")

    def test_the_reason_says_the_quote_is_missing(self):
        result = self._verify(_report(""))

        self.assertIn("no Cited Text", self._reasons(result),
                      "the failure should say the quotation is absent rather "
                      "than blaming the match: %s" % self._reasons(result))

    def test_a_quote_that_is_not_in_the_paper_is_flagged(self):
        """An invented quotation is the other half of the same job."""
        result = self._verify(
            _report('**Cited Text:** "Ikaros was shown to cure diabetes in humans."\n'))

        self.assertIn("not found in paper", self._reasons(result),
                      "an invented quotation should fail on the match, not be "
                      "skipped as unparsed -- the parser needs the quote in "
                      "double quotes: %s" % self._reasons(result))

    def test_a_quote_that_is_in_the_paper_passes(self):
        """The check must not simply fail everything."""
        result = self._verify(
            _report('**Cited Text:** "Ikaros drives B-cell differentiation"\n'))

        self.assertEqual(result["failed_citations"], [],
                         "a genuine quotation was rejected: %s"
                         % self._reasons(result))

    def test_the_matcher_finds_a_quote_that_is_present(self):
        self.assertTrue(_fuzzy_contains(PAPER_TEXT, "represses the myeloid programme"))

    def test_the_matcher_rejects_a_quote_that_is_absent(self):
        self.assertFalse(_fuzzy_contains(PAPER_TEXT, "cures diabetes in humans"))

    def test_the_matcher_treats_empty_input_as_no_match(self):
        """Defensive rather than reachable -- verify_report_v2 guards both
        arguments before calling -- but the direction matters: empty must mean
        "not grounded", never "grounded"."""
        self.assertFalse(_fuzzy_contains("", "something"))
        self.assertFalse(_fuzzy_contains(PAPER_TEXT, ""))
        self.assertFalse(_fuzzy_contains("", ""))


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
