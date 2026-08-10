#!/usr/bin/env python3
"""A compound omic cannot map more features than it was given.

`updateSubmitedCompoundsList` rewrites the compound omic's `omicSummary` to
reflect the user's selection. It used to count the mapped features like this:

    for i in sorted(range(len(initialCompound.omicsValues)), reverse=True):
        omicValue = initialCompound.omicsValues[i]
        mappedCompounds.add(omicValue.getOriginalName())     # every value...
        if omicValue.inputName in compoundName.split(", ") \
           and omicValue.originalName.lower() == originalName.lower():
            newCompound.addOmicValue(omicValue)              # ...only some kept

...and then

    cpdTotal    = cpdSummary[0] + cpdSummary[1]
    cpdSummary[0] = len(mappedCompounds)
    cpdSummary[1] = cpdTotal - len(mappedCompounds)

Two things put that set on a different scale from the summary it overwrites:
values belonging to boxes the user did *not* tick were counted, and
`originalName` is lower-cased for a main compound but keeps the input's own
case for an "other" compound (FeatureNamesToKeggIDsMapper.mapCompoundsIdentifiers
only calls setOriginalName on the latter), so one metabolite could enter the
set twice.

Measured on the bundled six-omic STATegra example -- 58 input metabolites, 51
of them matched -- driving the client's own auto-selection:

    before: Metabolomics omicSummary = [62, -4], mapped ratio 1.0689655
    after : Metabolomics omicSummary = [51,  7], mapped ratio 0.8793103

62 of 58 is impossible, and the ratio is not cosmetic: generatePathwaysList
passes getMappedRatios() into the Stouffer/Fisher combination as the per-omic
weight, so metabolomics was over-weighted in every combined pathway p-value.
It also reaches the browser (PathwayAcquisitionServlet.py) as "62 mapped of 58".

These tests pin the invariants rather than the one dataset:
    mapped + unmapped == total,  0 <= mapped <= total,  0 <= ratio <= 1.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_compound_mapping_summary_invariants
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.classes.Feature import Compound, OmicValue

OMIC = "Metabolomics"


def omicValue(inputName, originalName, omicName=OMIC, values=(1.0,)):
    value = OmicValue(inputName)
    value.setOriginalName(originalName)
    value.setOmicName(omicName)
    value.setValues(list(values))
    return value


def compound(compoundID, name, omicValues):
    entry = Compound(compoundID)
    entry.setName(name)
    entry.setOmicsValues(list(omicValues))
    return entry


class CompoundMappingSummaryInvariantsTest(unittest.TestCase):

    def makeJob(self, compounds, total, omicName=OMIC):
        """A job holding `compounds` for a compound omic whose input file had
        `total` features, of which len(compounds-worth of values) matched."""
        job = PathwayAcquisitionJob(jobID="cpd-summary", userID=None,
                                    CLIENT_TMP_DIR="/tmp/paintomics-test/")
        job.setInputCompoundsData(dict(compounds))
        matched = len({v.getOriginalName().lower()
                       for entry in compounds.values()
                       for v in entry.getOmicsValues()})
        job.addCompoundBasedInputOmic({
            "omicName": omicName,
            "inputDataFile": "values.tab",
            # [mapped, unmapped] as parseCompoundBasedFile leaves it.
            "omicSummary": [matched, total - matched],
        })
        return job

    def assertSummaryInvariants(self, job, total):
        for omic in job.getCompoundBasedInputOmics():
            summary = omic.get("omicSummary")
            mapped, unmapped = summary[0], summary[1]
            self.assertGreaterEqual(
                mapped, 0, "'%s' reports a negative mapped count %r" % (
                    omic.get("omicName"), mapped))
            self.assertGreaterEqual(
                unmapped, 0,
                "'%s' reports %r unmapped features -- more features were counted "
                "as mapped than the omic has" % (omic.get("omicName"), unmapped))
            self.assertLessEqual(
                mapped, total,
                "'%s' reports %d mapped features of %d input features" % (
                    omic.get("omicName"), mapped, total))
            self.assertEqual(
                mapped + unmapped, total,
                "'%s' summary %r no longer sums to the %d input features" % (
                    omic.get("omicName"), summary[:2], total))

        for omicName, ratio in job.getMappedRatios().items():
            self.assertGreaterEqual(ratio, 0.0, "%s mapped ratio %r < 0" % (omicName, ratio))
            self.assertLessEqual(
                ratio, 1.0,
                "%s mapped ratio %r > 1 -- this value weights the Stouffer/Fisher "
                "combination in generatePathwaysList" % (omicName, ratio))

    # -- the two mechanisms that produced 62 of 58 ------------------------

    def test_one_metabolite_matching_two_compounds_counts_once(self):
        """The casing split: a main compound keeps originalName lower-cased,
        an "other" compound keeps the input's own case. Same metabolite."""
        job = self.makeJob({
            "C00022": compound("C00022", "Pyruvate",
                               [omicValue("Pyruvate", "pyruvate")]),
            "C00033": compound("C00033", "Pyruvic acid",
                               [omicValue("Pyruvic acid", "Pyruvate")]),
        }, total=1)

        job.updateSubmitedCompoundsList([
            "C00022#Pyruvate#pyruvate",
            "C00033#Pyruvic acid#Pyruvate",
        ])

        self.assertEqual([1, 0], job.getCompoundBasedInputOmics()[0]["omicSummary"][:2],
                         "one input metabolite counted twice because its two "
                         "matches store originalName in different cases")
        self.assertSummaryInvariants(job, total=1)

    def test_values_the_user_did_not_select_are_not_counted_as_mapped(self):
        """Counting before the name-match test credited unticked boxes."""
        job = self.makeJob({
            "C00025": compound("C00025", "L-Glutamate", [
                omicValue("L-Glutamate", "glutamate"),
                omicValue("L-Glutamine", "glutamine"),   # a different metabolite
            ]),
        }, total=2)

        # Only the glutamate box is ticked.
        job.updateSubmitedCompoundsList(["C00025#L-Glutamate#glutamate"])

        summary = job.getCompoundBasedInputOmics()[0]["omicSummary"]
        self.assertEqual([1, 1], summary[:2],
                         "the unselected glutamine value was still counted as mapped")
        self.assertSummaryInvariants(job, total=2)

    def test_selecting_nothing_maps_nothing(self):
        job = self.makeJob({
            "C00025": compound("C00025", "L-Glutamate",
                               [omicValue("L-Glutamate", "glutamate")]),
        }, total=3)

        job.updateSubmitedCompoundsList([])

        self.assertEqual([0, 3], job.getCompoundBasedInputOmics()[0]["omicSummary"][:2])
        self.assertSummaryInvariants(job, total=3)
        self.assertEqual(0.0, job.getMappedRatios()[OMIC])

    def test_selecting_everything_maps_every_matched_metabolite(self):
        job = self.makeJob({
            "C00022": compound("C00022", "Pyruvate",
                               [omicValue("Pyruvate", "pyruvate")]),
            "C00025": compound("C00025", "L-Glutamate",
                               [omicValue("L-Glutamate", "glutamate")]),
        }, total=5)

        job.updateSubmitedCompoundsList([
            "C00022#Pyruvate#pyruvate",
            "C00025#L-Glutamate#glutamate",
        ])

        self.assertEqual([2, 3], job.getCompoundBasedInputOmics()[0]["omicSummary"][:2])
        self.assertSummaryInvariants(job, total=5)

    def test_rewrite_is_idempotent(self):
        """mapped + unmapped is the input size, so re-running step 2 with the
        same selection must not drift."""
        job = self.makeJob({
            "C00022": compound("C00022", "Pyruvate",
                               [omicValue("Pyruvate", "pyruvate")]),
        }, total=4)

        job.updateSubmitedCompoundsList(["C00022#Pyruvate#pyruvate"])
        first = list(job.getCompoundBasedInputOmics()[0]["omicSummary"][:2])
        job.updateSubmitedCompoundsList(["C00022#Pyruvate#pyruvate"])

        self.assertEqual(first, job.getCompoundBasedInputOmics()[0]["omicSummary"][:2])
        self.assertSummaryInvariants(job, total=4)

    # -- several compound omics no longer share one count -----------------

    def test_two_compound_omics_are_counted_separately(self):
        job = PathwayAcquisitionJob(jobID="cpd-summary-2", userID=None,
                                    CLIENT_TMP_DIR="/tmp/paintomics-test/")
        job.setInputCompoundsData({
            "C00022": compound("C00022", "Pyruvate", [
                omicValue("Pyruvate", "pyruvate", omicName="Metabolomics"),
                omicValue("Pyruvate", "pyruvate", omicName="Metabolomics 2"),
            ]),
            "C00025": compound("C00025", "L-Glutamate", [
                omicValue("L-Glutamate", "glutamate", omicName="Metabolomics"),
            ]),
        })
        job.addCompoundBasedInputOmic({"omicName": "Metabolomics",
                                       "omicSummary": [2, 8]})     # 10 features
        job.addCompoundBasedInputOmic({"omicName": "Metabolomics 2",
                                       "omicSummary": [1, 2]})     # 3 features

        job.updateSubmitedCompoundsList([
            "C00022#Pyruvate#pyruvate",
            "C00025#L-Glutamate#glutamate",
        ])

        byName = {omic["omicName"]: omic["omicSummary"][:2]
                  for omic in job.getCompoundBasedInputOmics()}
        self.assertEqual([2, 8], byName["Metabolomics"])
        self.assertEqual([1, 2], byName["Metabolomics 2"],
                         "the second metabolomics omic inherited the first one's count")
        ratios = job.getMappedRatios()
        self.assertAlmostEqual(0.2, ratios["Metabolomics"])
        self.assertAlmostEqual(1.0 / 3.0, ratios["Metabolomics 2"])

    # -- the defensive bound ----------------------------------------------

    def test_getMappedRatios_clamps_an_impossible_summary(self):
        """Last line of defence: whatever wrote the summary, the weight handed
        to the Stouffer/Fisher combination stays a proportion."""
        job = PathwayAcquisitionJob(jobID="cpd-ratio", userID=None,
                                    CLIENT_TMP_DIR="/tmp/paintomics-test/")
        job.addCompoundBasedInputOmic({"omicName": OMIC, "omicSummary": [62, -4]})

        self.assertEqual(1.0, job.getMappedRatios()[OMIC])

    def test_getMappedRatios_handles_an_empty_omic(self):
        job = PathwayAcquisitionJob(jobID="cpd-ratio-empty", userID=None,
                                    CLIENT_TMP_DIR="/tmp/paintomics-test/")
        job.addCompoundBasedInputOmic({"omicName": OMIC, "omicSummary": [0, 0]})

        self.assertEqual(0, job.getMappedRatios()[OMIC])

    def test_a_summary_that_is_not_two_counts_is_left_alone(self):
        """Nothing meaningful to rewrite, and it must not raise."""
        job = PathwayAcquisitionJob(jobID="cpd-odd", userID=None,
                                    CLIENT_TMP_DIR="/tmp/paintomics-test/")
        job.setInputCompoundsData({})
        job.addCompoundBasedInputOmic({"omicName": OMIC, "omicSummary": [{"KEGG": 3}, 1]})

        self.assertTrue(job.updateSubmitedCompoundsList([]))
        self.assertEqual([{"KEGG": 3}, 1],
                         job.getCompoundBasedInputOmics()[0]["omicSummary"][:2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
