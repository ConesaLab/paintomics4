#!/usr/bin/env python3
"""A malformed selectedCompounds[] entry must not destroy the whole analysis.

Step 2 receives the user's compound choices as "ID#name#originalName". All
three parts are needed because one KEGG compound ID can appear in several
boxes under different names, so the (name, originalName) pair is what says
which box was ticked.

updateSubmitedCompoundsList indexed [1] and [2] straight off the split, so a
single entry missing a part aborted the entire step with

    IndexError: list index out of range

Confirmed against the deployed server: posting bare IDs to /pa_step2 returned
HTTP 400 carrying exactly that, naming neither the offending entry nor the
field -- and it happened *after* enrichment, so minutes of completed work were
thrown away over one malformed string.

An entry that cannot be parsed identifies no compound. That is the same
situation as an ID that is not part of this job, which the function already
skips, so it is now skipped the same way and logged.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_compound_selection_parsing
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.classes.Feature import Compound, OmicValue


def compound(compoundID, inputName, originalName, values=(1.0,)):
    """A compound carrying one omic value, as step 1 would have left it."""
    entry = Compound(compoundID)
    entry.setName(inputName)
    omicValue = OmicValue(inputName)
    omicValue.setOriginalName(originalName)
    omicValue.setValues(list(values))
    entry.addOmicValue(omicValue)
    return entry


class CompoundSelectionParsingTest(unittest.TestCase):

    def setUp(self):
        self.job = PathwayAcquisitionJob(jobID="compounds", userID=None,
                                         CLIENT_TMP_DIR="/tmp/paintomics-test/")
        self.job.setInputCompoundsData({
            "C00022": compound("C00022", "Pyruvate", "Pyruvic acid"),
            "C00025": compound("C00025", "L-Glutamate", "Glutamic acid"),
        })
        # updateSubmitedCompoundsList rewrites the compound omic's summary, so
        # one has to exist or the tail of the function has nothing to update.
        self.job.addCompoundBasedInputOmic({
            "omicName": "Metabolomics",
            "inputDataFile": "values.tab",
            "relevantFeaturesFile": "relevant.tab",
            "omicSummary": [2, 0],
        })

    def test_wellformed_selection_is_kept(self):
        self.assertTrue(self.job.updateSubmitedCompoundsList(
            ["C00022#Pyruvate#Pyruvic acid"]))

        self.assertIn("C00022", self.job.getInputCompoundsData())

    def test_bare_id_is_skipped_instead_of_raising_IndexError(self):
        """The exact shape the deployed server died on."""
        try:
            result = self.job.updateSubmitedCompoundsList(["C00022", "C00025"])
        except IndexError as exc:
            self.fail("bare IDs still abort step 2: IndexError: %s" % exc)

        self.assertTrue(result)

    def test_two_part_entry_is_skipped(self):
        """ID#name with no originalName -- the [2] index."""
        try:
            self.assertTrue(self.job.updateSubmitedCompoundsList(["C00022#Pyruvate"]))
        except IndexError as exc:
            self.fail("two-part entry still aborts step 2: IndexError: %s" % exc)

    def test_empty_entry_is_skipped(self):
        """"".split("#") is [''], so even [1] is out of range."""
        try:
            self.assertTrue(self.job.updateSubmitedCompoundsList([""]))
        except IndexError as exc:
            self.fail("empty entry still aborts step 2: IndexError: %s" % exc)

    def test_one_bad_entry_does_not_discard_the_good_ones(self):
        """The point of skipping rather than raising."""
        self.assertTrue(self.job.updateSubmitedCompoundsList([
            "C00022",                          # malformed
            "C00025#L-Glutamate#Glutamic acid",  # valid
        ]))

        self.assertIn("C00025", self.job.getInputCompoundsData(),
                      "a valid selection was lost because another entry was malformed")

    def test_unknown_but_wellformed_id_is_still_skipped(self):
        """Pre-existing behaviour that must survive the change."""
        self.assertTrue(self.job.updateSubmitedCompoundsList(
            ["C99999#Nonexistent#Nonexistent"]))

        self.assertNotIn("C99999", self.job.getInputCompoundsData())

    def test_extra_hash_parts_keep_the_original_three_field_reading(self):
        """A name containing '#' must not change which fields are used."""
        self.job.setInputCompoundsData({
            "C00022": compound("C00022", "Pyruvate", "Pyruvic acid"),
        })

        self.assertTrue(self.job.updateSubmitedCompoundsList(
            ["C00022#Pyruvate#Pyruvic acid#trailing"]))
        self.assertIn("C00022", self.job.getInputCompoundsData())


if __name__ == "__main__":
    unittest.main(verbosity=2)
