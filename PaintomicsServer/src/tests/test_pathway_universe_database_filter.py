#!/usr/bin/env python3
"""The reported pathway total must count only the databases the job selected.

An organism's collection holds every database PaintOmics knows for that
species in one dict. For mmu that is 888 pathways = 364 KEGG + 524 Reactome
(measured straight against MongoDB: `Counter(source)` over mmu-paintomics.kegg).

`generatePathwaysList` took the whole dict and reported

    totalKeggPathways = len(pathwaysList)          # 888, whatever was selected

while `_matchPathways` skips any pathway whose source is not in
`totalFeaturesByOmic` -- a dictionary keyed by the job's own databases. So on a
KEGG-only job 524 of the 888 could never match, yet the log line

    "SUMMARY: N Matched Pathways of 888 in KEGG"

and `summary[0]`, which the client renders as the job's pathway total, both
counted them.

Measured on the bundled KEGG-only `gene-single-condition` scenario, two real
runs of the same code differing only in the filter:

    before: totalPathways 888, matched 364
    after : totalPathways 364, matched 364   (identical pathway IDs, md5
                                              01351f53741a43079a5c538c983182c9)

and on the KEGG+Reactome `gene-multi-condition` scenario the total stays 888
with the same 878 matched pathways.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_pathway_universe_database_filter
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob


def fakePathways():
    """Two KEGG pathways, two Reactome ones, and one legacy document written
    before the `source` field existed (which getPathwaySourceByID reads as
    KEGG)."""
    return {
        "mmu00010": {"ID": "mmu00010", "source": "KEGG"},
        "mmu00020": {"ID": "mmu00020", "source": "KEGG"},
        "R-MMU-1234": {"ID": "R-MMU-1234", "source": "Reactome"},
        "R-MMU-5678": {"ID": "R-MMU-5678", "source": "Reactome"},
        "mmu99999": {"ID": "mmu99999"},
    }


def job(databases, organism="mmu"):
    instance = PathwayAcquisitionJob(jobID="pathway-universe", userID=None,
                                     CLIENT_TMP_DIR="/tmp/paintomics-test/")
    instance.setOrganism(organism)
    instance.setDatabases(databases)
    return instance


class PathwayUniverseDatabaseFilterTest(unittest.TestCase):

    def test_kegg_only_job_drops_the_reactome_half(self):
        kept = job(["KEGG"]).filterPathwaysBySelectedDatabases(fakePathways())

        self.assertEqual({"mmu00010", "mmu00020", "mmu99999"}, set(kept),
                         "a KEGG-only job still counts pathways it can never match")

    def test_reactome_only_job_keeps_only_reactome(self):
        kept = job(["Reactome"]).filterPathwaysBySelectedDatabases(fakePathways())

        self.assertEqual({"R-MMU-1234", "R-MMU-5678"}, set(kept))

    def test_both_databases_keep_everything(self):
        kept = job(["KEGG", "Reactome"]).filterPathwaysBySelectedDatabases(fakePathways())

        self.assertEqual(set(fakePathways()), set(kept))

    def test_a_document_without_a_source_counts_as_kegg(self):
        """Matches getPathwaySourceByID's `pathway.get("source", "KEGG")`, so
        the denominator and the matching agree on the legacy documents."""
        kept = job(["Reactome"]).filterPathwaysBySelectedDatabases(fakePathways())

        self.assertNotIn("mmu99999", kept)

    def test_no_database_on_the_job_keeps_the_old_behaviour(self):
        for databases in ([], None):
            kept = job(databases).filterPathwaysBySelectedDatabases(fakePathways())
            self.assertEqual(set(fakePathways()), set(kept),
                             "a job with no recorded database must not report zero "
                             "pathways")

    def test_an_unknown_database_name_falls_back_instead_of_matching_nothing(self):
        """If the source names and the job's database names ever disagree, the
        job must keep running with the old inflated total, not with an empty
        pathway universe."""
        kept = job(["NotADatabase"]).filterPathwaysBySelectedDatabases(fakePathways())

        self.assertEqual(set(fakePathways()), set(kept))

    def test_an_empty_pathway_dict_is_returned_unchanged(self):
        self.assertEqual({}, job(["KEGG"]).filterPathwaysBySelectedDatabases({}))

    def test_the_kept_documents_are_the_same_objects(self):
        pathways = fakePathways()
        kept = job(["KEGG"]).filterPathwaysBySelectedDatabases(pathways)

        self.assertIs(pathways["mmu00010"], kept["mmu00010"])


class RealOrganismPathwayCountsTest(unittest.TestCase):
    """The numbers a user is actually shown, against the real mmu collection.

    Skipped when MongoDB is not reachable, so the suite still runs on a
    checkout without a loaded database.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from src.common.KeggInformationManager import KeggInformationManager
            cls.pathways = KeggInformationManager().getAllPathwaysByOrganism("mmu")
        except Exception as error:                       # noqa: BLE001
            raise unittest.SkipTest("mmu pathways unavailable: %s" % error)
        if not cls.pathways:
            raise unittest.SkipTest("no mmu pathways loaded")

    def counts(self, databases):
        return len(job(databases).filterPathwaysBySelectedDatabases(self.pathways))

    def test_mmu_universe_splits_into_364_kegg_and_524_reactome(self):
        self.assertEqual(888, len(self.pathways),
                         "the mmu snapshot changed; the expected counts below "
                         "come from Counter(source) over mmu-paintomics.kegg")
        self.assertEqual(364, self.counts(["KEGG"]))
        self.assertEqual(524, self.counts(["Reactome"]))
        self.assertEqual(888, self.counts(["KEGG", "Reactome"]))

    def test_every_kept_pathway_belongs_to_a_selected_database(self):
        for databases in (["KEGG"], ["Reactome"], ["KEGG", "Reactome"]):
            kept = job(databases).filterPathwaysBySelectedDatabases(self.pathways)
            sources = {pathway.get("source", "KEGG") for pathway in kept.values()}
            self.assertTrue(sources <= set(databases),
                            "%s leaked into a %s job" % (sources - set(databases),
                                                         databases))


if __name__ == "__main__":
    unittest.main(verbosity=2)
