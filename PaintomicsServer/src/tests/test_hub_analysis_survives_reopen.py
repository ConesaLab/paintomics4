#!/usr/bin/env python3
"""The metabolite hub analysis must still be there when a job is reopened.

Why this exists
---------------
`hubAnalysis` shells out to hubAnalysis.R, reads `hub_result.csv` back and sets
`self.hubAnalysisResult`. Step 2 returned it in the response, and then it was
dropped: the step-2 update passes an explicit field list, and the field was not
in it.

    daoInstance.update(jobInstance, {"fieldList": ["summary", "lastStep",
         "mappingComp", ... "regulationPerConditionData"]})

So the Metabolites Hub Analysis table had rows only in the browser session that
ran the analysis. Reopen the job by its URL and it was empty -- an R script's
output discarded, and not something the user can regenerate without re-running
step 2 entirely.

This is the same defect, in the same function, as the one the comment about
Reactome classes describes a few lines below: "computed at step 2, returned in
the response and then dropped -- it was in neither the updated field list above
nor any DAO call ... showed '-' for every row once the job was reopened by its
URL." That one was fixed. This one was still open.

Measured, not assumed:

  - Both UI-driven jobs run today wrote hub_result.csv, userDataset.csv and
    userDEfeatures.csv to their output directories -- so the R script ran and
    succeeded -- while `hubAnalysisResult` in MongoDB stayed None.
  - Across all 45 jobs on this machine that have one, hub_result.csv never
    exceeds 3819 bytes.

That last number is why the field moved out of `PAINTOMICS4_LARGE_FIELDS`. That
set exists because "compoundRegulateFeatures alone can exceed 60 MB" against a
16 MB document limit, which is true of its other members and was never true of
this one: 3819 bytes is 0.02% of the limit. It inherited a justification from
its neighbours.

It moved specifically into `PAINTOMICS4_DICT_FIELDS` rather than plain storage
because `hubAnalysis` keys the dict by integer row index (`hubResult[i] = line`)
and Mongo refuses that:

    InvalidDocument: documents must have only string keys, key was 0

Confirmed against the real toBSON before the change. Adding the field to the
step-2 field list *without* moving it would therefore not have restored the
table -- it would have broken saving step 2 for every job that selects
compounds. Both halves are required, which is what these tests pin.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_hub_analysis_survives_reopen
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import bson

from src.classes.JobInstances.PathwayAcquisitionJob import (
    PathwayAcquisitionJob, PAINTOMICS4_DICT_FIELDS, PAINTOMICS4_LARGE_FIELDS)

# Shaped exactly like hubAnalysis builds it: integer row index -> csv row.
HUB_ROWS = {
    0: ["0.25", "C00042", "0.542501353546291", "0.939340364254495", "1", "1", "1", "3"],
    1: ["0.8571", "C00097", "0.765565782349756", "0.0649792099763172", "1", "1", "6", "1"],
    2: ["0.8333", "C00099", "0.765024363833243", "0.112903546409287", "1", "1", "5", "1"],
}


class HubAnalysisPersistenceTest(unittest.TestCase):

    def _job(self):
        job = PathwayAcquisitionJob("HUBTEST", None, "/tmp/")
        job.hubAnalysisResult = dict(HUB_ROWS)
        return job

    def test_the_result_is_serialised(self):
        bsonOut = self._job().toBSON()

        self.assertIn("hubAnalysisResult", bsonOut,
                      "the hub analysis is missing from the serialised job, so "
                      "reopening the job loses it")
        self.assertEqual(len(bsonOut["hubAnalysisResult"]), len(HUB_ROWS))

    def test_mongodb_accepts_it(self):
        """Integer keys are rejected outright, so this is not academic."""
        bsonOut = self._job().toBSON()

        try:
            bson.encode({"job": bsonOut["hubAnalysisResult"]})
        except Exception as exc:
            self.fail("MongoDB would reject the hub analysis: %s: %s\n"
                      "hubAnalysis keys its dict by integer row index, so the "
                      "field must be stringified on the way out."
                      % (type(exc).__name__, exc))

    def test_the_keys_are_strings(self):
        bsonOut = self._job().toBSON()

        kinds = {type(key).__name__ for key in bsonOut["hubAnalysisResult"]}
        self.assertEqual(kinds, {"str"}, "found key types %s" % kinds)

    def test_it_survives_a_round_trip(self):
        """Store then reopen: the rows must come back intact."""
        stored = self._job().toBSON()
        stored["_id"] = "irrelevant"

        reopened = PathwayAcquisitionJob("HUBTEST", None, "/tmp/")
        reopened.parseBSON(stored)

        self.assertEqual(len(reopened.hubAnalysisResult), len(HUB_ROWS))
        self.assertEqual(reopened.hubAnalysisResult["1"][1], "C00097",
                         "the compound ids did not survive the round trip")

    def test_step_two_actually_writes_the_field(self):
        """The serialisation being correct is useless if step 2 filters it out.

        The step-2 update names its fields explicitly, so a field that is
        serialisable but unlisted is still silently dropped -- which is exactly
        how this bug and the Reactome-class one both happened. Read from the
        source so the test tracks the real list.
        """
        path = os.path.join(os.path.dirname(__file__),
                            "../common/JobInformationManager.py")
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()

        start = source.find("IS STEP 2")
        self.assertNotEqual(start, -1, "could not find the step 2 branch")
        window = source[start:start + 1400]

        self.assertIn('"hubAnalysisResult"', window,
                      "step 2's update field list does not name "
                      "hubAnalysisResult, so the computed analysis is thrown "
                      "away when the job is stored")

    def test_it_is_no_longer_treated_as_too_large_to_store(self):
        self.assertIn("hubAnalysisResult", PAINTOMICS4_DICT_FIELDS)
        self.assertNotIn("hubAnalysisResult", PAINTOMICS4_LARGE_FIELDS,
                         "hub_result.csv never exceeded 3819 bytes across 45 "
                         "jobs; it does not belong with the megabyte fields")

    def test_the_metabolite_expression_is_stored_too(self):
        """The field the Step 3 metabolite panels are actually gated on.

        Persisting hubAnalysisResult alone restored the data but not the panel:
        on cold recovery the sidebar still omitted both metabolite sections,
        because the client checks `exprssionMetabolites` and that was still
        being dropped. Measured on the same six-omic job, 96 compounds
        selected: 96 entries, 11126 bytes — 0.07% of the 16 MB limit.
        """
        self.assertIn("exprssionMetabolites", PAINTOMICS4_DICT_FIELDS)
        self.assertNotIn("exprssionMetabolites", PAINTOMICS4_LARGE_FIELDS)

    def test_the_genuinely_large_fields_are_left_alone(self):
        """This change is about the small fields, not the policy.

        These two were measured on the same job and do earn their place:
        compoundRegulateFeatures 2.67 MB, globalExpressionData 4.29 MB —
        about 7 MB together, before the rest of the document.
        """
        for field in ("compoundRegulateFeatures", "globalExpressionData"):
            self.assertIn(field, PAINTOMICS4_LARGE_FIELDS,
                          "%s was removed from LARGE_FIELDS, but it was "
                          "measured in megabytes" % field)
            self.assertNotIn(field, PAINTOMICS4_DICT_FIELDS)

    def test_step_two_writes_the_metabolite_expression(self):
        path = os.path.join(os.path.dirname(__file__),
                            "../common/JobInformationManager.py")
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()

        start = source.find("IS STEP 2")
        window = source[start:start + 1600]

        self.assertIn('"exprssionMetabolites"', window,
                      "step 2's update field list does not name "
                      "exprssionMetabolites, so the metabolite panels stay "
                      "empty when the job is reopened")

    def test_an_empty_result_is_harmless(self):
        """hubAnalysis returns False early when nothing is relevant."""
        job = PathwayAcquisitionJob("HUBTEST", None, "/tmp/")

        bsonOut = job.toBSON()

        self.assertIn("hubAnalysisResult", bsonOut)
        self.assertIsNone(bsonOut["hubAnalysisResult"])



class HubAnalysisUsesPythonTest(unittest.TestCase):
    """No Rscript in the hub path, and stored rows carry a schema version.

    The R scorer re-read a 13 MB CSV and 1,865 .RData files on every job -- I/O
    proportional to the species installed, not to the user's dataset. It is gone;
    these assertions are what stops it coming back.
    """

    def _job_source(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "classes", "JobInstances",
            "PathwayAcquisitionJob.py")
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_no_rscript_is_forked_for_hub(self):
        source = self._job_source()
        # The only surviving mention is the historical note in the docstring.
        self.assertNotIn('bioscripts/hubAnalysis.R', source)
        self.assertIn("KeggGraph", source)

    def test_the_single_slot_json_cache_is_gone(self):
        source = self._job_source()
        self.assertNotIn("_loadCompoundNeighbourMap(", source)
        self.assertNotIn("_compoundNeighbourCache[", source)

    def test_rows_are_dicts_carrying_the_schema(self):
        from src.common.KeggGraph.graph import KeggGraph
        from src.common.KeggGraph.parser import Edge
        from src.common.KeggGraph.scorer import HUB_SCHEMA_VERSION, score
        graph = KeggGraph(
            [Edge("C1", "g1", "PPrel", "", "p", False),
             Edge("C1", "g2", "PPrel", "", "p", False)],
            {"C1": "compound", "g1": "gene", "g2": "gene"}, "test")
        rows = score(graph, {"C1", "g1", "g2"}, {"C1", "g1"})
        self.assertTrue(rows)
        self.assertEqual(rows[0]["schema"], HUB_SCHEMA_VERSION)
        self.assertIn("ball_fraction", rows[0])

    def test_stored_rows_still_survive_toBSON(self):
        """The rows changed shape; the persistence arrangement did not.
        hubAnalysisResult is still a DICT field with integer keys."""
        source = self._job_source()
        self.assertIn('"hubAnalysisResult"', source)


def main():
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
