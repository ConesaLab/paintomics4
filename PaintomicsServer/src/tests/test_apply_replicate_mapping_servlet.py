#!/usr/bin/env python3
"""Cover for pathwayAcquisitionApplyReplicateMapping (/pa_apply_replicate_mapping).

This endpoint destroyed data. featureDict was read at the reinsert step but
never assigned: the manual branch looked it up and threw it away into `_`, and
the auto/off branches never looked it up at all. The call immediately before
it is

    featDAO.removeAll({"jobID": jobID, "featureType": featureType})

so every invocation deleted the job's whole Gene (or Compound) collection and
then died with NameError before putting anything back. jobDAO.update runs
first, so the job document was left claiming the mapping had been applied
while the features it described no longer existed.

Observed by driving the endpoint with fakes:

    jobDAO.update
    featDAO.removeAll {'jobID': 'J1', 'featureType': 'Gene'}
    NameError: name 'featureDict' is not defined
    response success: False

The fix resolves the omic once for every mode. The persistence block also now
materialises the replacement list before deleting the old one -- removeAll +
insertAll is not atomic, and anything that can fail between them costs the
user their features.

These tests assert on the *order* of DAO calls, not just the response, because
a green response was never the thing at risk here.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_apply_replicate_mapping_servlet
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.Feature import Gene, OmicValue
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob
from src.servlets import PathwayAcquisitionServlet as SERVLET

DESIGN = "S1_R1\tWT\nS1_R2\tWT\nS2_R1\tKO\nS2_R2\tKO"


class FakeSession(object):
    raises = None

    def isValidUser(self, userID, sessionToken):
        if FakeSession.raises:
            raise FakeSession.raises
        return True


class FakeJobDAO(object):
    def __init__(self, log):
        self.log = log

    def update(self, *a, **k):
        self.log.append("jobDAO.update")

    def closeConnection(self):
        pass


class FakeFeatureDAO(object):
    def __init__(self, log):
        self.log = log

    def removeAll(self, params):
        self.log.append(("removeAll", params.get("featureType")))

    def insertAll(self, values, params):
        self.log.append(("insertAll", len(list(values))))

    def closeConnection(self):
        pass


class FakeRequest(object):
    def __init__(self, payload, cookies=None):
        self._payload = payload
        self.cookies = cookies or {"userID": "u1", "sessionToken": "t"}

    def get_json(self):
        return self._payload


class FakeResponse(object):
    def __init__(self):
        self.content = None
        self.status = None

    def setContent(self, content):
        self.content = content

    def setStatus(self, status):
        self.status = status


class ApplyReplicateMappingServletTest(unittest.TestCase):

    def setUp(self):
        self.log = []
        self._saved = {name: getattr(SERVLET, name) for name in
                       ("UserSessionManager", "JobInformationManager",
                        "PathwayAcquisitionJobDAO", "FeatureDAO")}
        FakeSession.raises = None
        SERVLET.UserSessionManager = lambda: FakeSession()
        SERVLET.PathwayAcquisitionJobDAO = lambda *a, **k: FakeJobDAO(self.log)
        SERVLET.FeatureDAO = lambda *a, **k: FakeFeatureDAO(self.log)

        self.job = self.buildJob()
        outer = self

        class FakeJIM(object):
            def loadJobInstance(self, jobID):
                return outer.job if jobID == "J1" else None

        SERVLET.JobInformationManager = lambda: FakeJIM()
        self.response = FakeResponse()

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(SERVLET, name, value)

    @staticmethod
    def buildJob(readOnly=False, nGenes=2):
        job = PathwayAcquisitionJob("J1", "u1", "/tmp/")
        job.setReadOnly(readOnly)
        job.geneBasedInputOmics = [{
            "omicName": "Gene expression",
            "omicHeader": ["ID", "S1_R1", "S1_R2", "S2_R1", "S2_R2"],
            "replicateDetection": {
                "status": "complete", "sampleHeader": ["S1", "S2"],
                "mapping": [0, 0, 1, 1], "groups": [[0, 1], [2, 3]],
                "unmatched": [],
            },
        }]
        genes = {}
        for i in range(nGenes):
            gid = "G%d" % i
            gene = Gene(gid)
            ov = OmicValue(gid)
            ov.setOmicName("Gene expression")
            ov.setValues([1.0, 3.0, 10.0, 20.0])
            gene.addOmicValue(ov)
            genes[gid] = gene
        job.inputGenesData = genes
        return job

    def call(self, **payload):
        body = {"jobID": "J1", "omicName": "Gene expression"}
        body.update(payload)
        SERVLET.pathwayAcquisitionApplyReplicateMapping(
            FakeRequest(body), self.response)
        return self.response.content

    def daoCalls(self):
        return [c for c in self.log if isinstance(c, tuple)]

    # -- the regression --------------------------------------------------
    def test_features_are_reinserted_after_being_removed(self):
        """The whole bug: removeAll ran, insertAll never did."""
        content = self.call(mode="auto")
        self.assertTrue(content["success"], content)
        self.assertEqual(self.daoCalls(), [("removeAll", "Gene"), ("insertAll", 2)])

    def test_every_mode_reinserts(self):
        for mode, extra in (("auto", {}), ("off", {}), ("manual", {"design": DESIGN})):
            with self.subTest(mode=mode):
                self.setUp()
                content = self.call(mode=mode, **extra)
                self.assertTrue(content["success"], content)
                self.assertIn(("insertAll", 2), self.daoCalls())

    def test_a_failure_before_the_delete_leaves_the_features_alone(self):
        """removeAll + insertAll is not atomic, so nothing that can fail may
        sit between them."""
        self.call(mode="manual", design="S1_R1\tWT")   # incomplete design -> raises
        self.assertFalse(self.response.content["success"])
        self.assertEqual(self.daoCalls(), [], "features were touched despite the error")

    # -- responses -------------------------------------------------------
    def test_auto_reports_the_detected_grouping(self):
        content = self.call(mode="auto")
        self.assertEqual(content["status"], "applied")
        self.assertEqual(content["sampleHeader"], ["S1", "S2"])
        self.assertEqual(content["mapping"], [0, 0, 1, 1])
        self.assertEqual(content["featuresUpdated"], 2)

    def test_off_reports_cleared_with_an_empty_grouping(self):
        content = self.call(mode="off")
        self.assertEqual(content["status"], "cleared")
        self.assertEqual(content["sampleHeader"], [])
        self.assertEqual(content["mapping"], [])

    def test_manual_uses_the_uploaded_design(self):
        content = self.call(mode="manual", design=DESIGN)
        self.assertEqual(content["status"], "applied")
        self.assertEqual(content["sampleHeader"], ["WT", "KO"])

    def test_manual_aggregates_by_the_design_not_the_detection(self):
        self.call(mode="manual",
                  design="S1_R1\tAll\nS1_R2\tAll\nS2_R1\tAll\nS2_R2\tAll")
        ov = self.job.inputGenesData["G0"].getOmicsValues()[0]
        self.assertEqual(ov.sampleValues, [8.5])

    # -- rejections ------------------------------------------------------
    def test_missing_job_id(self):
        SERVLET.pathwayAcquisitionApplyReplicateMapping(
            FakeRequest({"omicName": "Gene expression", "mode": "auto"}),
            self.response)
        self.assertFalse(self.response.content["success"])
        self.assertEqual(self.daoCalls(), [])

    def test_missing_omic_name(self):
        SERVLET.pathwayAcquisitionApplyReplicateMapping(
            FakeRequest({"jobID": "J1", "mode": "auto"}), self.response)
        self.assertFalse(self.response.content["success"])

    def test_an_invalid_mode_is_rejected(self):
        content = self.call(mode="sideways")
        self.assertFalse(content["success"])
        self.assertEqual(self.daoCalls(), [])

    def test_an_unknown_omic_is_rejected_before_any_dao_call(self):
        content = self.call(mode="auto", omicName="Nope")
        self.assertFalse(content["success"])
        self.assertEqual(self.daoCalls(), [])

    def test_an_unknown_job_is_rejected(self):
        SERVLET.pathwayAcquisitionApplyReplicateMapping(
            FakeRequest({"jobID": "other", "omicName": "Gene expression",
                         "mode": "auto"}), self.response)
        self.assertFalse(self.response.content["success"])

    def test_an_invalid_session_is_rejected_before_any_dao_call(self):
        FakeSession.raises = Exception("Invalid session")
        content = self.call(mode="auto")
        self.assertFalse(content["success"])
        self.assertEqual(self.daoCalls(), [])

    def test_another_users_readonly_job_cannot_be_modified(self):
        self.job = self.buildJob(readOnly=True)
        self.job.setUserID("someone-else")
        content = self.call(mode="auto")
        self.assertFalse(content["success"])
        self.assertEqual(self.daoCalls(), [])

    def test_the_response_object_is_always_returned(self):
        result = SERVLET.pathwayAcquisitionApplyReplicateMapping(
            FakeRequest({}), self.response)
        self.assertIs(result, self.response)


if __name__ == "__main__":
    unittest.main(verbosity=2)
