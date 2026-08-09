#!/usr/bin/env python3
"""A selected compound that matched no omic value must not reach the consumers.

Why this exists
---------------
`updateSubmitedCompoundsList` adds a compound to the table empty and fills it
only if one of its omic values matches the selection:

    newCompound = initialCompound.clone()
    newCompound.setOmicsValues([])                       # added empty
    ...
    if omicValue.inputName in compoundName.split(", ") \
       and omicValue.originalName.lower() == originalName.lower():
        newCompound.addOmicValue(omicValue)              # only then

so a selection whose name does not match leaves the compound in
`inputCompoundsData` carrying nothing. Nineteen places then read
`omicsValues[0]`, and the first reached ends step 2 with

    IndexError: list index out of range

after enrichment has already been computed -- the same expensive loss the
malformed-selection branch in the same function exists to prevent.

Reproduced with a single selection, "C00075#SomeOtherName#UTP" against a C00075
whose only value is named UTP:

    compounds kept: ['C00075']
      C00075 omicsValues = []
    getGlobalExpressionData() -> IndexError: list index out of range

Two of those nineteen readers already carry `if feature.omicsValues` /
`if comp and comp.omicsValues`, so this has been met before and patched where
it surfaced rather than where it starts.

Note the asymmetry that makes a mismatch easy: the originalName comparison is
case-insensitive (`.lower() == .lower()`) while the inputName test is an exact
membership check against `compoundName.split(", ")`. This file does not change
that -- narrowing the match would drop values that currently match -- it only
stops the empty compound from surviving.

The drop happens after the selection loop rather than inside it, because one
compound ID legitimately appears in several selections under different names
(the function's own comment gives C00075 as that case), so "carries no value"
only means anything once every selection has been seen. Pruning inside the loop
was tried as a mutation and reaches the same answer -- a compound removed on a
non-matching pass is cloned again from initialCompound on the next one -- so
that is a preference for not depending on the recovery, not a bug being
avoided. `test_a_later_selection_can_still_fill_it` pins the behaviour either
way.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_selected_compound_without_values
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Feature import Feature, OmicValue
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob


def _job(values=(("UTP", "UTP", [1.0, 2.0]),), compoundID="C00075"):
    """A job holding one compound with the given omic values."""
    job = PathwayAcquisitionJob("TESTJOB", "1", "/tmp/paintomics-test/")
    compound = Feature(compoundID)
    compound.setName("UTP")
    for inputName, originalName, numbers in values:
        omicValue = OmicValue(inputName)
        omicValue.setOriginalName(originalName)
        omicValue.omicName = "Metabolomics"
        omicValue.values = list(numbers)
        compound.addOmicValue(omicValue)
    job.setInputCompoundsData({compoundID: compound})
    return job


class SelectedCompoundWithoutValuesTest(unittest.TestCase):

    def test_a_compound_that_matched_nothing_is_dropped(self):
        job = _job()

        job.updateSubmitedCompoundsList(["C00075#SomeOtherName#UTP"])

        self.assertEqual(list(job.getInputCompoundsData()), [],
                         "a compound that matched no omic value survived with "
                         "an empty omicsValues, which every consumer indexes "
                         "at [0]")

    def test_the_consumer_no_longer_raises(self):
        """The user-visible failure, not just the internal state."""
        job = _job()

        job.updateSubmitedCompoundsList(["C00075#SomeOtherName#UTP"])

        try:
            job.getGlobalExpressionData()
        except IndexError as exc:
            self.fail("getGlobalExpressionData raised IndexError (%s), ending "
                      "step 2 after enrichment had already been computed" % exc)

    def test_no_surviving_compound_has_an_empty_value_list(self):
        """The invariant the consumers actually rely on."""
        job = _job()

        job.updateSubmitedCompoundsList(["C00075#SomeOtherName#UTP",
                                         "C00075#AlsoWrong#UTP"])

        empty = [cid for cid, compound in job.getInputCompoundsData().items()
                 if not compound.omicsValues]
        self.assertEqual(empty, [], "these carry no omic value: %s" % empty)

    def test_a_matching_selection_is_untouched(self):
        """The fix must not drop compounds that did match."""
        job = _job()

        job.updateSubmitedCompoundsList(["C00075#UTP#UTP"])

        kept = job.getInputCompoundsData()
        self.assertEqual(list(kept), ["C00075"])
        self.assertEqual([v.values for v in kept["C00075"].omicsValues],
                         [[1.0, 2.0]])

    def test_a_later_selection_can_still_fill_it(self):
        """A non-matching selection must not cost a compound a matching one.

        One compound ID appears in several selections under different names --
        the function's own comment gives C00075 as exactly that case -- so the
        first pass seeing nothing says nothing about the second.
        """
        job = _job()

        job.updateSubmitedCompoundsList(["C00075#WrongName#UTP", "C00075#UTP#UTP"])

        kept = job.getInputCompoundsData()
        self.assertEqual(list(kept), ["C00075"],
                         "the compound was dropped on the first, non-matching "
                         "selection instead of being filled by the second")
        self.assertEqual([v.values for v in kept["C00075"].omicsValues],
                         [[1.0, 2.0]])

    def test_the_global_expression_data_is_right_for_a_kept_compound(self):
        """Dropping the empty ones must not disturb the real payload."""
        job = _job()
        job.updateSubmitedCompoundsList(["C00075#UTP#UTP"])

        data = job.getGlobalExpressionData()

        self.assertTrue(data,
                        "getGlobalExpressionData returned nothing for a "
                        "compound that matched, so the payload is empty")
        flattened = {}
        for section in data.values():
            if isinstance(section, dict):
                flattened.update(section)
        self.assertIn("C00075", flattened,
                      "the compound that matched is missing from the global "
                      "expression data: %s" % list(flattened)[:5])
        self.assertEqual(flattened["C00075"]["values"], [1.0, 2.0])

    def test_several_values_are_all_preserved(self):
        """A compound measured under two names keeps both."""
        job = _job(values=(("UTP", "UTP", [1.0]), ("UTP", "utp", [9.0])))

        job.updateSubmitedCompoundsList(["C00075#UTP#UTP"])

        kept = job.getInputCompoundsData()["C00075"]
        self.assertEqual(sorted(v.values[0] for v in kept.omicsValues), [1.0, 9.0],
                         "the originalName comparison is case-insensitive, so "
                         "both of these match and both must be kept")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
