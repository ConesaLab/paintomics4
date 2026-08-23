#!/usr/bin/env python3
"""Two conditions must never reach the agent under the same name.

Why this exists
---------------
`_build_omic_header_map` (context_builder) and `_build_header_map` (tools)
turned each column header into "the part after the last underscore". On the
STATegra time course the pipeline was built against that is right and
readable: `Ikaros/Control_0h` -> `0h`, and the six labels stay distinct.

On a factorial design it deletes a factor. Measured on three blind runs of
harvested studies, 2026-08-23:

    CTRL_SHAM, CTRL_CLP, TCPOBOP_SHAM, TCPOBOP_CLP  ->  SHAM, CLP, SHAM, CLP
    WT_aCD40, WT_aCD40_TLR9, ROCK1cKO_aCD40, ...    ->  aCD40, TLR9, aCD40, TLR9
    WT_CD_5m .. FXRKO_WD_15m (12 conditions)        ->  5m, 10m, 15m, x4

Every value the agent then quotes is ambiguous -- `7.62@SHAM` names two
different columns -- and the contrast the study exists to make cannot be
stated. The reports show the damage rather than an error: one printed
`@TLR9` 67 times and `@aCD40` 44 times and never once named the genotype,
then told its reader "the pooled WT/KO design means specific changes cannot
be attributed to ROCK1 loss alone" -- a false claim about the experiment,
derived from the labels. The sepsis run reported "no TCPOBOP-specific
modulation is evident in any pathway" for the same reason, while its own
matrix carries the drug arm.

Nothing raises, which is why it survived: the pipeline completes and the
report reads fluently.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_condition_labels_stay_distinct
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.context_builder import (  # noqa: E402
    _build_omic_header_map, _shorten_condition_labels,
)
from src.classes.AIInterpret.tools import _build_header_map  # noqa: E402


class _Job(object):
    """The only surface both helpers touch."""

    def __init__(self, omics):
        self._omics = omics

    def getGeneBasedInputOmics(self):
        return self._omics


def _omic(name, columns):
    return {"omicName": name, "omicHeader": ["#featureID"] + list(columns)}


TIME_COURSE = ["Ikaros/Control_0h", "Ikaros/Control_2h", "Ikaros/Control_6h"]
FACTORIAL = ["CTRL_SHAM", "CTRL_CLP", "TCPOBOP_SHAM", "TCPOBOP_CLP"]
GENOTYPE_X_STIMULUS = ["WT_aCD40", "WT_aCD40_TLR9",
                       "ROCK1cKO_aCD40", "ROCK1cKO_aCD40_TLR9"]
THREE_FACTOR = ["WT_CD_5m", "WT_CD_10m", "WT_CD_15m",
                "FXRKO_CD_5m", "FXRKO_CD_10m", "FXRKO_CD_15m"]


class ShortenTest(unittest.TestCase):

    def test_a_time_course_still_shortens(self):
        """The behaviour the pipeline was built for is unchanged."""
        self.assertEqual(_shorten_condition_labels(TIME_COURSE),
                         ["0h", "2h", "6h"])

    def test_a_factorial_keeps_its_full_labels(self):
        self.assertEqual(_shorten_condition_labels(FACTORIAL), FACTORIAL)
        self.assertEqual(_shorten_condition_labels(GENOTYPE_X_STIMULUS),
                         GENOTYPE_X_STIMULUS)
        self.assertEqual(_shorten_condition_labels(THREE_FACTOR), THREE_FACTOR)

    def test_labels_are_always_distinct(self):
        """The invariant, stated once: shortening may never merge conditions."""
        for columns in (TIME_COURSE, FACTORIAL, GENOTYPE_X_STIMULUS,
                        THREE_FACTOR, ["a", "b"], ["x_1", "y_1", "z_2"]):
            labels = _shorten_condition_labels(columns)
            self.assertEqual(len(set(labels)), len(labels), columns)
            self.assertEqual(len(labels), len(columns), columns)

    def test_whitespace_and_empty_tails(self):
        self.assertEqual(_shorten_condition_labels([" A_0h ", "A_6h"]),
                         ["0h", "6h"])
        # a trailing underscore leaves nothing to shorten to: keep the column
        self.assertEqual(_shorten_condition_labels(["A_", "B_"]), ["A_", "B_"])


class HeaderMapTest(unittest.TestCase):
    """Both copies of the helper must agree -- they feed the same report."""

    def test_context_builder_and_tools_agree(self):
        for columns in (TIME_COURSE, FACTORIAL, GENOTYPE_X_STIMULUS):
            job = _Job([_omic("Gene expression", columns)])
            self.assertEqual(_build_omic_header_map(job)["Gene expression"],
                             _build_header_map(job)["Gene expression"],
                             columns)

    def test_the_factorial_reaches_the_agent_with_its_factors(self):
        job = _Job([_omic("Gene expression", FACTORIAL),
                    _omic("Proteomics", FACTORIAL)])
        labels = _build_omic_header_map(job)
        self.assertEqual(labels["Gene expression"], FACTORIAL)
        self.assertEqual(labels["Proteomics"], FACTORIAL)
        for name, got in labels.items():
            self.assertIn("TCPOBOP_CLP", got,
                          "the drug arm must be nameable in %s" % name)

    def test_a_short_or_missing_header_is_skipped_not_guessed(self):
        job = _Job([{"omicName": "Gene expression", "omicHeader": ["#featureID"]},
                    {"omicName": "Proteomics", "omicHeader": None}])
        self.assertEqual(_build_omic_header_map(job), {})
        self.assertEqual(_build_header_map(job),
                         {"Gene expression": None, "Proteomics": None})


if __name__ == "__main__":
    unittest.main(verbosity=2)
