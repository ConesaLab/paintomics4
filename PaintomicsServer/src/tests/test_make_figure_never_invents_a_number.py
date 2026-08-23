#!/usr/bin/env python3
"""A figure may only carry values the job holds — and all of them.

Why this exists
---------------
`make_figure` is the one tool that turns the agent's words into a picture, and
a picture is read as evidence. So the resolver is the whole safety argument:
the model names an archetype and a slice (genes, or a pathway), and the values
come from the job. There is no parameter through which a number can be passed
in.

Two ways that argument could be quietly broken, both checked here:

  * **Reading the rendered profile instead of the job.** The per-gene profile
    the agent *reads* is a formatted string -- `-0.42@0h, 1.30@2h` -- rounded
    to two decimals, and above twelve conditions it prints first-three + peak +
    last-three with an ellipsis. A figure built from that string would drop
    conditions from a long design and call the result the data. The resolver
    therefore reads the raw values off the job's own omic objects.
  * **Dropping what it could not find.** A figure of six of the ten genes the
    agent asked for, unremarked, is a misleading figure. Unresolved symbols
    come back to the caller, which names them in the tool result.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_make_figure_never_invents_a_number
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret import figures  # noqa: E402


class _OmicValue(object):
    """The OmicValue surface both the context builder and figures.py touch."""

    def __init__(self, omic_name, values, relevant=True):
        self._omic_name, self._values = omic_name, values
        self._relevant = relevant

    def getOmicName(self):
        return self._omic_name

    def getValues(self):
        return list(self._values)

    def isRelevant(self):
        return self._relevant


class _Gene(object):
    def __init__(self, name, omics):
        self._name, self._omics = name, omics

    def getName(self):
        return self._name

    def getOmicsValues(self):
        return list(self._omics)


class _Job(object):
    """Only the surface figures.py touches."""

    def __init__(self, genes, header, out_dir="/tmp"):
        self._genes = genes
        self._header = header
        self._out = out_dir

    def getInputGenesData(self):
        return self._genes

    def getGeneBasedInputOmics(self):
        return [{"omicName": "Gene expression", "omicHeader": self._header}]

    def getOutputDir(self):
        return self._out


# Thirteen conditions: one more than the point at which the rendered profile
# starts eliding, and enough decimals to catch a round-trip through the "@"
# string. Values are deliberately not round numbers.
CONDITIONS = ["C%02d" % i for i in range(1, 14)]
PRECISE = [0.123456, -1.987654, 2.5, 3.14159, -0.000123, 8.7654321,
           1.1, 2.2, 3.3, 4.4, 5.5, 6.6, 7.7]


def _job():
    genes = {"g1": _Gene("Ikzf1", [_OmicValue("Gene expression", PRECISE)]),
             "g2": _Gene("Ccnd2", [_OmicValue("Gene expression",
                                              [1.0] * len(PRECISE))])}
    return _Job(genes, ["#featureID"] + CONDITIONS)


class ResolverTest(unittest.TestCase):

    def test_every_condition_survives_a_long_design(self):
        """Thirteen conditions in, thirteen out -- no elision, no rounding."""
        rows, missing = figures.resolve_genes(_job(), ["Ikzf1"])
        self.assertEqual(missing, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["values"], PRECISE)
        self.assertEqual(len(rows[0]["values"]), len(CONDITIONS))

    def test_values_are_exact_not_two_decimals(self):
        rows, _ = figures.resolve_genes(_job(), ["Ikzf1"])
        self.assertAlmostEqual(rows[0]["values"][0], 0.123456, places=6)
        self.assertAlmostEqual(rows[0]["values"][4], -0.000123, places=6)

    def test_an_unknown_symbol_is_reported_not_dropped(self):
        rows, missing = figures.resolve_genes(_job(), ["Ikzf1", "NotAGene"])
        self.assertEqual([r["label"] for r in rows], ["Ikzf1"])
        self.assertIn("NotAGene", missing)

    def test_conditions_come_from_the_shared_header_map(self):
        """The axis and the prose must name a condition the same way."""
        self.assertEqual(figures._conditions(_job()), CONDITIONS)


class SlugTest(unittest.TestCase):

    def test_a_figure_id_is_readable_and_bounded(self):
        self.assertEqual(figures._slug("Cholesterol rises in G12V"),
                         "cholesterol-rises-in-g12v")
        # over the limit: cut at a word boundary, never mid-word
        long_id = figures._slug("Cholesterol biosynthesis rises together in G12V")
        self.assertLessEqual(len(long_id), 32)
        self.assertEqual(long_id, "cholesterol-biosynthesis-rises")
        self.assertLessEqual(len(figures._slug("x" * 200)), 32)
        self.assertTrue(figures._slug("!!!"))          # never empty


class BlockTest(unittest.TestCase):
    """What the agent reads back must not overstate the figure."""

    class _Result(object):
        ok = False
        stderr_tail = "Traceback: boom"
        seconds = 0.1

    def test_a_failed_render_says_so(self):
        block = figures.figure_block(
            "fig1-x", 1, {"archetype": "timecourse", "conclusion": "C rises"},
            False, ["FAIL bundle_complete: no figure.svg"], self._Result())
        self.assertIn("RENDER FAILED", block)
        self.assertIn("QA: FAILS", block)
        self.assertIn("bundle_complete", block)

    def test_a_passing_figure_offers_its_callout(self):
        class Ok(object):
            ok, stderr_tail, seconds = True, "", 1.0
        block = figures.figure_block(
            "fig2-y", 2, {"archetype": "heatmap", "conclusion": "C falls"},
            True, ["PASS bundle_complete: all six files"], Ok())
        self.assertIn("![Fig. 2](figure:fig2-y)", block)
        self.assertIn("QA: passes", block)
        self.assertNotIn("RENDER FAILED", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
