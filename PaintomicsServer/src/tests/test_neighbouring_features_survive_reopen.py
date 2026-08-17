#!/usr/bin/env python3
"""The metabolite neighbour map must still be there when a job is reopened.

Why this exists
---------------
Step 4's "Neighbouring features" panel (Feature set overview -> enter a level
1-4 -> Show Features) reads `compoundRegulateFeatures` off the job model. The
field is in `PAINTOMICS4_LARGE_FIELDS`, so it is never written to MongoDB, and
`pa_recover_job` returned `jobInstance.compoundRegulateFeatures` verbatim --
which is `None` on any process that did not run step 2 itself. Measured on this
machine against the six-omic STATegra example, job e6rwH1sB3o:

    same process as the run:  crf=57  gedGene=25770  hub=156
    after a server restart:   crf=0   gedGene=25770  hub=156

`globalExpressionData` is in the same LARGE_FIELDS set and survives, because
`getGlobalExpressionData()` *recomputes* it from `inputGenesData` on every call
instead of returning a stored attribute. The neighbour map has exactly the same
property and was the one field that did not use it: it is
`kegg_interaction.json` (static per organism, already parsed once per process
by `_loadCompoundNeighbourMap`) intersected with `inputCompoundsData` -- and
both of those survive a reopen. Nothing had to be stored; it had to be derived.

So the button was dead on every job opened from its link, and the failure was
silent: the click handler's guard is `console.warn('No regulate data for', id);
return`, which from the outside is a button that does nothing.

These tests pin the two halves:

  - `getCompoundRegulateFeatures()` derives the map, so a job with a cleared
    cache still resolves its compounds' neighbours.
  - `pa_recover_job` calls the getter rather than reading the attribute; the
    servlet assertion is a string check because standing up a request needs a
    live MongoDB, and the regression being prevented is precisely someone
    putting `jobInstance.compoundRegulateFeatures` back.

A job with no compounds must not touch the filesystem at all: the file is 34 MB
locally and 79 MB on production mmu, and gene-only jobs are the majority.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_neighbouring_features_survive_reopen
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances import PathwayAcquisitionJob as job_module
from src.classes.JobInstances.PathwayAcquisitionJob import (
    PathwayAcquisitionJob, PAINTOMICS4_LARGE_FIELDS)

SERVLET = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "servlets", "PathwayAcquisitionServlet.py"))

# Shaped exactly like kegg_interaction.json: {compoundID: {step: [geneID, ...]}}
# with the steps as the string keys "1".."4" (checked against the installed ath
# and mmu files, both of which key them that way).
NETWORK = {
    "C00025": {"1": ["11302", "12974"], "2": ["11302", "12974", "71832"],
               "3": ["11302"], "4": ["11302"]},
    "C00026": {"1": ["104112"], "2": ["104112"], "3": ["104112"],
               "4": ["104112"]},
    # In the network but not in this job's input -- must not be emitted.
    "C99999": {"1": ["1"], "2": ["1"], "3": ["1"], "4": ["1"]},
}


class _Compound(object):
    """Stands in for src.classes.Feature.Compound: only the key matters here."""

    def __init__(self, compoundID):
        self.ID = compoundID


class NeighbourMapDerivationTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="paintomics-hubdata-")
        self.organism = "tst"
        hubData = os.path.join(self.directory, "current", self.organism, "hubData")
        os.makedirs(hubData)
        self.interactionPath = os.path.join(hubData, "kegg_interaction.json")
        with open(self.interactionPath, "w", encoding="utf-8") as handle:
            json.dump(NETWORK, handle)

        # _loadCompoundNeighbourMap keeps one organism per process; a stale
        # entry from another test would make this pass for the wrong reason.
        job_module._compoundNeighbourCache["key"] = None
        job_module._compoundNeighbourCache["map"] = None

        self.keggDataDir = job_module.KEGG_DATA_DIR
        job_module.KEGG_DATA_DIR = self.directory

    def tearDown(self):
        job_module.KEGG_DATA_DIR = self.keggDataDir
        job_module._compoundNeighbourCache["key"] = None
        job_module._compoundNeighbourCache["map"] = None
        shutil.rmtree(self.directory, ignore_errors=True)

    def _job(self, compoundIDs):
        instance = PathwayAcquisitionJob("NBRTEST", None, self.directory)
        instance.setOrganism(self.organism)
        instance.inputCompoundsData = dict(
            (compoundID, _Compound(compoundID)) for compoundID in compoundIDs)
        return instance

    def test_the_field_is_still_cache_only(self):
        """Premise: if it ever gets persisted, these tests are answering a
        question nobody is asking any more."""
        self.assertIn("compoundRegulateFeatures", PAINTOMICS4_LARGE_FIELDS)

    def test_the_getter_exists(self):
        self.assertTrue(
            hasattr(PathwayAcquisitionJob, "getCompoundRegulateFeatures"),
            "getCompoundRegulateFeatures() has been renamed or removed")

    def test_a_cold_cache_still_resolves_the_neighbours(self):
        instance = self._job(["C00025", "C00026"])
        # Exactly the state a reopened job is in: the attribute never came back
        # from MongoDB.
        instance.compoundRegulateFeatures = None

        resolved = instance.getCompoundRegulateFeatures()

        self.assertEqual(sorted(resolved.keys()), ["C00025", "C00026"])
        self.assertEqual(resolved["C00025"]["1"], ["11302", "12974"])
        self.assertEqual(resolved["C00025"]["2"], ["11302", "12974", "71832"])

    def test_compounds_outside_the_input_are_dropped(self):
        instance = self._job(["C00025"])
        instance.compoundRegulateFeatures = None

        self.assertEqual(list(instance.getCompoundRegulateFeatures()), ["C00025"])

    def test_the_string_none_a_reopened_job_carries_is_not_mistaken_for_data(self):
        """DAO.adaptBSON turns every None leaf into the STRING "None" -- its own
        comment says so and ~193k leaves in foundFeaturesCollection depend on
        it. So a reopened job's attribute is `'None'`, which is truthy: a guard
        that only tested truthiness handed that string back, the servlet's
        _as_dict() turned it into {}, and the panel stayed as dead as it was.
        Measured against the real job e6rwH1sB3o after a restart:

            repr(job.compoundRegulateFeatures) == 'None'
            pa_recover_job -> crf=0
        """
        instance = self._job(["C00025"])
        instance.compoundRegulateFeatures = "None"

        resolved = instance.getCompoundRegulateFeatures()

        self.assertIsInstance(resolved, dict)
        self.assertEqual(resolved["C00025"]["1"], ["11302", "12974"])

    def test_any_other_non_dict_is_also_recomputed(self):
        for junk in ("{}", "", 0, [], None):
            instance = self._job(["C00025"])
            instance.compoundRegulateFeatures = junk
            self.assertEqual(
                sorted(instance.getCompoundRegulateFeatures().keys()), ["C00025"],
                "%r was taken for a neighbour map" % (junk,))

    def test_an_already_populated_map_is_returned_untouched(self):
        """The step-2 path must keep handing over what it computed -- and must
        not pay for the file again."""
        instance = self._job(["C00025"])
        instance.compoundRegulateFeatures = {"C00025": {"1": ["sentinel"]}}

        self.assertEqual(instance.getCompoundRegulateFeatures(),
                         {"C00025": {"1": ["sentinel"]}})

    def test_a_gene_only_job_never_reads_the_file(self):
        instance = self._job([])
        instance.compoundRegulateFeatures = None

        opened = []
        realOpen = job_module.open if hasattr(job_module, "open") else open

        def tracking_open(path, *args, **kwargs):
            opened.append(path)
            return realOpen(path, *args, **kwargs)

        job_module.open = tracking_open
        try:
            self.assertEqual(instance.getCompoundRegulateFeatures(), {})
        finally:
            del job_module.open

        self.assertEqual(
            [path for path in opened if "kegg_interaction" in str(path)], [],
            "a job with no compounds parsed the interaction file anyway")

    def test_a_species_without_hubdata_degrades_to_empty(self):
        os.remove(self.interactionPath)
        instance = self._job(["C00025"])
        instance.compoundRegulateFeatures = None

        self.assertEqual(instance.getCompoundRegulateFeatures(), {})

    def test_the_result_is_json_safe(self):
        """It goes straight into a response body."""
        instance = self._job(["C00025", "C00026"])
        instance.compoundRegulateFeatures = None

        json.dumps(instance.getCompoundRegulateFeatures())


class RecoverJobUsesTheGetterTest(unittest.TestCase):

    def setUp(self):
        with open(SERVLET, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_the_servlet_is_where_this_test_thinks(self):
        self.assertIn("safe_compoundRegulateFeatures", self.source)

    def test_recovery_derives_the_map_instead_of_reading_the_attribute(self):
        self.assertIn("getCompoundRegulateFeatures()", self.source,
                      "pa_recover_job is not deriving the neighbour map")
        self.assertNotIn("_as_dict(jobInstance.compoundRegulateFeatures)",
                         self.source,
                         "pa_recover_job is back to reading the cache-only "
                         "attribute, which is None on a reopened job")


if __name__ == "__main__":
    unittest.main(verbosity=2)
