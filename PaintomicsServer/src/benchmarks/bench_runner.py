#!/usr/bin/env python3
"""Run ONE example scenario through the real pipeline, headless, and dump
timings plus every result the client would see.

This is the measurement kernel for the performance work: it calls the same
job methods, in the same order, as the servlets do (pathwayAcquisitionStep1_
PART2 / Step2_PART2 / Step3, Bed2GenesServlet STEP2, MiRNA2GenesServlet STEP2,
MOREServlet STEP2), so its artifacts are the equivalence contract between two
builds. One scenario per process: a fresh interpreter defeats the job cache,
the KEGG organism cache and the per-job translation cache, exactly like the
first request after a deploy.

Usage (from PaintomicsServer/):

    PAINTOMICS_KEGG_DATA=... PAINTOMICS_CLIENT_TMP=... \
    python -m src.benchmarks.bench_runner --scenario gene-single-condition \
        --out /tmp/bench/baseline/run1

Outputs in --out:
    timings.json         phase -> seconds (plus scraped STEP2 TIMING line)
    artifacts.json.gz    everything the client would see, per step
"""
import argparse
import glob
import gzip
import io
import json
import logging
import multiprocessing
import os
import sys
import time
import uuid
import zipfile

# Production (Linux) forks its mapper/enrichment workers; macOS defaults to
# spawn, which changes both the cost profile (full re-import + re-pickle per
# worker, cold KEGG singleton per child) and cache-inheritance semantics.
# Benchmarks must measure the production behaviour.
multiprocessing.set_start_method("fork", force=True)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

for _var in ("PAINTOMICS_KEGG_DATA", "PAINTOMICS_CLIENT_TMP"):
    if not os.environ.get(_var):
        sys.exit("bench_runner: %s must be set before any src import "
                 "(serverconf reads it at import time)" % _var)

from src.conf.serverconf import CLIENT_TMP_DIR, KEGG_DATA_DIR  # noqa: E402
from src.common.KeggInformationManager import KeggInformationManager  # noqa: E402

# First construction wins for the singleton; the server does exactly this
# (paintomicsserver.py:107) and step 3's PNG reads depend on it.
KeggInformationManager(KEGG_DATA_DIR)

from src.common.JobInformationManager import JobInformationManager  # noqa: E402
from src.common import ExampleDatasets  # noqa: E402
from src.common import DatabaseAvailability  # noqa: E402

EXAMPLE_FILES_DIR = os.path.join(ROOT, "src", "examplefiles") + os.sep
ROOT_DIRECTORY = os.path.join(ROOT, "src") + os.sep


class FakeResponse(object):
    """The two methods the servlet code calls on a Response."""

    def __init__(self):
        self.content = None

    def setContent(self, content):
        self.content = content

    def getContent(self):
        return self.content

    def getResponse(self):
        return self


class Timer(object):
    def __init__(self):
        self.phases = {}

    def time(self, name, fn, *args, **kwargs):
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        self.phases[name] = round(time.perf_counter() - start, 4)
        return result


class LogScraper(logging.Handler):
    """Collect the pipeline's own timing lines (e.g. STEP2 TIMING ...)."""

    def __init__(self):
        logging.Handler.__init__(self)
        self.lines = []

    def emit(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return
        if "TIMING" in message:
            self.lines.append(message)


def clientSelectedCompounds(matchedMetabolites):
    """Replicate the client's default compound selection.

    JobController.js:527-541 dedups across CompoundSets: for every unique
    compound ID appearing in any mainCompounds list, exactly one occurrence
    ends selected -- the one with the highest similarity, later entries
    winning ties (>=). otherCompounds keep the server-side selected flags.
    PA_Step2Views.js getSelectedCompounds then collects "ID#name#title" in
    list order. This runs on the BSON dicts so the job objects stay untouched.
    """
    sets = [foundFeature.toBSON() for foundFeature in matchedMetabolites]

    winners = {}
    for compoundSet in sets:
        for compound in compoundSet.get("mainCompounds", []):
            compound["selected"] = False
            kept = winners.get(compound.get("ID"))
            if kept is None or compound.get("similarity", 0) >= kept.get("similarity", 0):
                if kept is not None:
                    kept["selected"] = False
                compound["selected"] = True
                winners[compound.get("ID")] = compound

    selected = []
    for compoundSet in sets:
        for compound in compoundSet.get("mainCompounds", []):
            if compound.get("selected") is True:
                selected.append("%s#%s#%s" % (compound.get("ID"),
                                              compound.get("name"),
                                              compoundSet.get("title")))
        for compound in compoundSet.get("otherCompounds", []):
            if compound.get("selected") is True:
                selected.append("%s#%s#%s" % (compound.get("ID"),
                                              compound.get("name"),
                                              compoundSet.get("title")))
    return selected


def jsonSafe(obj):
    """Encode with full fidelity; unknown types become tagged markers so a
    type drift between builds shows up as a diff instead of a crash."""
    return {"__unserializable__": type(obj).__name__, "repr": repr(obj)}


def dumpArtifacts(outDir, artifacts):
    path = os.path.join(outDir, "artifacts.json.gz")
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(artifacts, handle, default=jsonSafe)


def readMappingZip(job):
    """Per-omic matched/unmatched lines from the mapping results zip.

    Line order across mapper workers is nondeterministic on master, so the
    lines are sorted here; content, not order, is the contract.
    """
    zipPath = os.path.join(job.getOutputDir(),
                           "mapping_results_" + job.getJobID() + ".zip")
    if not os.path.isfile(zipPath):
        return {}
    result = {}
    with zipfile.ZipFile(zipPath) as bundle:
        for name in sorted(bundle.namelist()):
            with bundle.open(name) as member:
                text = io.TextIOWrapper(member, encoding="utf-8",
                                        errors="replace").read()
            result[name] = sorted(text.splitlines())
    return result


def pathwaysBSON(job):
    return {pathwayID: pathway.toBSON()
            for pathwayID, pathway in (job.getMatchedPathways() or {}).items()}


def cleanupJob(jobID):
    """Best-effort removal of the benchmark job's Mongo footprint."""
    try:
        from src.common.DAO.PathwayAcquisitionJobDAO import PathwayAcquisitionJobDAO
        from src.common.DAO.FeatureDAO import FeatureDAO
        from src.common.DAO.FoundFeatureDAO import FoundFeatureDAO
        from src.common.DAO.PathwayDAO import PathwayDAO
        PathwayAcquisitionJobDAO().remove(jobID)
        FeatureDAO().removeAll(otherParams={"jobID": jobID})
        FoundFeatureDAO().removeAll(otherParams={"jobID": jobID})
        PathwayDAO().removeAll(otherParams={"jobID": jobID})
    except Exception as exc:  # pragma: no cover - cleanup only
        logging.warning("bench cleanup failed for %s: %s", jobID, exc)


# ---------------------------------------------------------------------------
# Pathway acquisition (scenarios 01-04, 08)
# ---------------------------------------------------------------------------

def runPathwayAcquisition(scenarioId, outDir, timer):
    from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

    jobID = "BM" + uuid.uuid4().hex[:10]
    job = PathwayAcquisitionJob(jobID, None, CLIENT_TMP_DIR)
    job.initializeDirectories()

    scenario = ExampleDatasets.applyScenario(job, EXAMPLE_FILES_DIR, scenarioId)
    # The servlet overrides the manifest's databases with everything installed
    # for the organism (PathwayAcquisitionServlet.py:257-258).
    job.setDatabases(DatabaseAvailability.resolveDatabases(job.getOrganism()))
    job.setName(scenario.get("title", "")[:100])
    job.setAIConsent("false")

    # --- step 1 (mirrors pathwayAcquisitionStep1_PART2) ---
    timer.time("step1.validateInput", job.validateInput)
    matchedMetabolites = timer.time("step1.processFilesContent",
                                    job.processFilesContent)
    job.setLastStep(2)
    job.getJobDescription(True, True)
    timer.time("step1.store", JobInformationManager().storeJobInstance, job, 1)

    step1Artifacts = {
        "organism": job.getOrganism(),
        "databases": job.getDatabases(),
        "matchedMetabolites": [f.toBSON() for f in matchedMetabolites],
        "geneBasedInputOmics": job.getGeneBasedInputOmics(),
        "compoundBasedInputOmics": job.getCompoundBasedInputOmics(),
        "mappingFiles": readMappingZip(job),
    }
    job.cleanDirectories()

    # --- step 2 (mirrors pathwayAcquisitionStep2_PART2) ---
    job2 = JobInformationManager().loadJobInstance(jobID)
    job2.setDirectories(CLIENT_TMP_DIR)
    job2.initializeDirectories()

    selectedCompounds = clientSelectedCompounds(matchedMetabolites)
    timer.time("step2.updateCompounds",
               job2.updateSubmitedCompoundsList, selectedCompounds)
    summary = timer.time("step2.generatePathwaysList", job2.generatePathwaysList)
    globalExpressionData = timer.time("step2.globalExpressionData",
                                      job2.getGlobalExpressionData)

    classification = None
    hubResult = None
    if selectedCompounds:
        classification = timer.time("step2.compoundsClassification",
                                    job2.compundsClassification, {})
        hubResult = timer.time("step2.hubAnalysis",
                               job2.hubAnalysis, ROOT_DIRECTORY)
    job2.parseRegulationPerCondition()
    timer.time("step2.metagenes",
               job2.generateMetagenesList, ROOT_DIRECTORY, {})
    job2.setLastStep(3)
    timer.time("step2.store", JobInformationManager().storeJobInstance, job2, 2)

    step2Artifacts = {
        "summary": summary,
        "selectedCompounds": selectedCompounds,
        "pathwaysInfo": pathwaysBSON(job2),
        "classInfo": {classID: matchedClass.toBSON() for classID, matchedClass
                      in (job2.getMatchedClass() or {}).items()},
        "omicsValuesID": job2.getValueIdTable(),
        "globalExpressionData": globalExpressionData,
        "conditionNames": getattr(job2, "conditionNames", []),
        "regulationPerConditionData": getattr(job2, "regulationPerConditionData", None),
        "hubAnalysisResult": hubResult,
    }
    if classification is not None:
        (mappingComp, pValueInDict, classificationDict, exprssionMetabolites,
         adjustPvalue, totalRelevantFeaturesInCategory, featureSummary,
         compoundRegulateFeatures) = classification
        step2Artifacts.update({
            "mappingComp": mappingComp,
            "pValueInDict": pValueInDict,
            "classificationDict": classificationDict,
            "exprssionMetabolites": exprssionMetabolites,
            "adjustPvalue": adjustPvalue,
            "totalRelevantFeaturesInCategory": totalRelevantFeaturesInCategory,
            "featureSummary": featureSummary,
            "compoundRegulateFeatures": compoundRegulateFeatures,
        })

    # --- step 3 (mirrors pathwayAcquisitionStep3) over every matched pathway ---
    selectedPathways = sorted((job2.getMatchedPathways() or {}).keys())
    step3 = timer.time(
        "step3.generateSelectedPathwaysInformation",
        job2.generateSelectedPathwaysInformation, selectedPathways, [], True)
    timer.time("step3.store", JobInformationManager().storeJobInstance, job2, 3)
    step3Artifacts = {
        "selectedPathways": selectedPathways,
        "graphicalOptionsInstances": step3[1],
        "omicsValues": step3[2],
    }

    job2.cleanDirectories()
    cleanupJob(jobID)
    return {"step1": step1Artifacts, "step2": step2Artifacts,
            "step3": step3Artifacts}


# ---------------------------------------------------------------------------
# Conversion pipelines (scenarios 05, 07, 09, 10)
# ---------------------------------------------------------------------------

def _fileContents(directory, patterns):
    """{pattern: [file contents]} for glob patterns under directory. Filenames
    embed dates/random seeds, so content is stored under the pattern key."""
    collected = {}
    for pattern in patterns:
        matches = sorted(glob.glob(os.path.join(directory, pattern)))
        collected[pattern] = []
        for path in matches:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                collected[pattern].append(handle.read())
    return collected


def runMiRNA2Genes(scenarioId, outDir, timer):
    from src.classes.JobInstances.MiRNA2GeneJob import MiRNA2GeneJob

    jobID = "BM" + uuid.uuid4().hex[:10]
    job = MiRNA2GeneJob(jobID, None, CLIENT_TMP_DIR)
    job.initializeDirectories()
    scenario = ExampleDatasets.applyScenario(job, EXAMPLE_FILES_DIR, scenarioId)

    regulator = next((omic for omic in scenario.get("omics", [])
                      if omic.get("role") == "regulator"),
                     scenario["omics"][0])
    # The defaults the servlet applies when the form carries no override
    # (MiRNA2GenesServlet.py:138-149).
    job.omicName = regulator["omicName"]
    job.report = "all"
    job.score_method = "kendall"
    job.selection_method = "negative_correlation"
    job.cutoff = 0.5
    job.enrichment = "genes"

    timer.time("mirna.validateInput", job.validateInput)
    timer.time("mirna.fromMiRNA2Genes", job.fromMiRNA2Genes)
    timer.time("mirna.store", JobInformationManager().storeJobInstance, job, 1)

    artifacts = {
        "temporalFiles": _fileContents(job.getTemporalDir(), [
            "miRNAMatch_output.txt",
        ]),
        "outputFiles": _fileContents(job.getOutputDir(), [
            "regulator2Gene_output_*.tab",
            "regulator2Gene_relevant_*.tab",
            "regulator_associations*.tab",
            "regulator_relevant_associations*.tab",
            "genesToMiRNA*",
        ]),
    }
    job.cleanDirectories()
    return {"conversion": artifacts}


def runRegions2Genes(scenarioId, outDir, timer):
    from src.classes.JobInstances.Bed2GeneJob import Bed2GeneJob

    jobID = "BM" + uuid.uuid4().hex[:10]
    job = Bed2GeneJob(jobID, None, CLIENT_TMP_DIR)
    job.initializeDirectories()
    scenario = ExampleDatasets.applyScenario(job, EXAMPLE_FILES_DIR, scenarioId)

    regionOmic = scenario["omics"][0]
    # Servlet defaults (Bed2GenesServlet.py:135-165).
    job.omicName = regionOmic["omicName"]
    job.presortedGTF = False
    job.report = "gene"
    job.distance = 10
    job.tss = 200
    job.promoter = 1300
    job.geneAreaPercentage = 90
    job.regionAreaPercentage = 50
    job.ignoreMissing = False
    job.enrichment = "genes"
    job.geneIDtag = "gene_id"
    job.summarizationMethod = "mean"
    job.reportRegions = ["all"]

    timer.time("bed.validateInput", job.validateInput)
    timer.time("bed.fromBED2Genes", job.fromBED2Genes)
    timer.time("bed.store", JobInformationManager().storeJobInstance, job, 1)

    artifacts = {
        "temporalFiles": _fileContents(job.getTemporalDir(), [
            "RGMatch_output.txt",
            "regionsToGene.tab",
            "genesToRegions.tab",
        ]),
        "outputFiles": _fileContents(job.getOutputDir(), [
            "B2G_output_*.tab",
            "B2G_relevant_*.tab",
        ]),
    }
    job.cleanDirectories()
    return {"conversion": artifacts}


# ---------------------------------------------------------------------------
# MORE (scenarios 06, 11)
# ---------------------------------------------------------------------------

def runMore(scenarioId, outDir, timer):
    from src.classes.JobInstances.MOREJob import MOREJob
    from src.servlets import MOREServlet

    jobID = "BM" + uuid.uuid4().hex[:10]
    job = MOREJob(jobID, None, CLIENT_TMP_DIR)
    job.initializeDirectories()
    ExampleDatasets.applyMoreScenario(job, EXAMPLE_FILES_DIR, scenarioId)

    response = FakeResponse()
    timer.time("more.step2", MOREServlet.fromMOREtoGenes_STEP2,
               job, None, response, {})

    content = response.getContent() or {}
    artifacts = {"responseKeys": sorted(content.keys()),
                 "success": content.get("success"),
                 "response": content,
                 "outputFiles": _fileContents(job.getOutputDir(), ["*.tab", "*.csv"])}
    job.cleanDirectories()
    return {"more": artifacts}


# ---------------------------------------------------------------------------

PIPELINES = {
    "pathway-acquisition": runPathwayAcquisition,
    "mirna2genes": runMiRNA2Genes,
    "regions2genes": runRegions2Genes,
    "more": runMore,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(message)s",
                        stream=sys.stderr)
    scraper = LogScraper()
    root = logging.getLogger()
    root.addHandler(scraper)
    # logging.cfg (loaded via serverconf import) leaves the root above INFO;
    # the pipeline's own STEP2 TIMING lines are logged at INFO.
    root.setLevel(logging.INFO)

    scenario = ExampleDatasets.getScenario(EXAMPLE_FILES_DIR, args.scenario)
    pipeline = scenario.get("pipeline")
    if pipeline not in PIPELINES:
        sys.exit("bench_runner: no driver for pipeline %r" % pipeline)

    timer = Timer()
    started = time.perf_counter()
    artifacts = PIPELINES[pipeline](args.scenario, args.out, timer)
    total = round(time.perf_counter() - started, 4)

    timings = {"scenario": args.scenario, "pipeline": pipeline,
               "total": total, "phases": timer.phases,
               "pipeline_timing_lines": scraper.lines}
    with open(os.path.join(args.out, "timings.json"), "w") as handle:
        json.dump(timings, handle, indent=2)
    dumpArtifacts(args.out, artifacts)

    print(json.dumps({"scenario": args.scenario, "total": total,
                      "phases": timer.phases}))


if __name__ == "__main__":
    main()
