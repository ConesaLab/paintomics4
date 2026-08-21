#!/usr/bin/env python3
"""Run tests/perf/large_input/ through the pathway-acquisition pipeline the way
an uploaded submission goes through it, and print the wall clock per phase.

This is the profiling workload: the same job methods the servlets call, in
the same order (validateInput, processFilesContent, step-2 enrichment with
compound classification, hub analysis and metagenes, step-3 painting of
every matched pathway), on a whole-genome-sized input. The files are copied
into the job's input directory and registered exactly as
JobInformationManager.saveFiles registers an upload -- no `isExample`
shortcut -- so file validation and reading are part of what is measured.

Cold by construction: one job per interpreter, so every per-process cache
(the KEGG organism cache, the translation cache, the compound-neighbour
map) starts empty, as it does for the first request after a deploy.

    PAINTOMICS_KEGG_DATA=... PAINTOMICS_CLIENT_TMP=... \\
    python scripts/perf/perf_run.py [--input tests/perf/large_input] [--out timings.json]

Prints one JSON line: {"total": seconds, "phases": {...}, "pathways": N}.
"""
import argparse
import json
import os
import shutil
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SERVER = os.path.join(REPO, "PaintomicsServer")
sys.path.insert(0, SERVER)

for _var in ("PAINTOMICS_KEGG_DATA", "PAINTOMICS_CLIENT_TMP"):
    if not os.environ.get(_var):
        sys.exit("perf_run: %s must be set before any src import" % _var)

# bench_runner pins the fork start method, builds the KEGG singleton the way
# the server does, and carries the client's compound-selection rule and the
# job clean-up. Reusing it keeps this runner and the regression kernel in step.
from src.benchmarks import bench_runner  # noqa: E402
from src.benchmarks.bench_runner import (  # noqa: E402
    CLIENT_TMP_DIR, ROOT_DIRECTORY, Timer, cleanupJob, clientSelectedCompounds)
from src.common import DatabaseAvailability  # noqa: E402
from src.common.JobInformationManager import JobInformationManager  # noqa: E402


def stage_input(job, inputDir, manifest):
    """Copy the files into the job's input directory and register them as
    saveFiles does for an upload."""
    target = job.getInputDir()
    os.makedirs(target, exist_ok=True)
    for omic in manifest["omics"]:
        for key in ("dataFile", "relevantFile"):
            shutil.copy(os.path.join(inputDir, omic[key]), os.path.join(target, omic[key]))
        entry = {"omicName": omic["omicName"], "inputDataFile": omic["dataFile"],
                 "relevantFeaturesFile": omic["relevantFile"],
                 "configOptions": None, "enrichment": omic["enrichment"]}
        if omic["omicType"] == "compound":
            job.addCompoundBasedInputOmic(entry)
        else:
            entry.update({"associationsFile": None, "relevantAssociationsFile": None})
            job.addGeneBasedInputOmic(entry)


def run(inputDir, timer):
    from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

    with open(os.path.join(inputDir, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)

    jobID = "PF" + uuid.uuid4().hex[:10]
    job = PathwayAcquisitionJob(jobID, None, CLIENT_TMP_DIR)
    job.initializeDirectories()
    job.setOrganism(manifest["organism"])
    job.setDatabases(DatabaseAvailability.resolveDatabases(manifest["organism"]))
    job.setName("perf large input")
    job.setAIConsent("false")
    stage_input(job, inputDir, manifest)

    # step 1
    timer.time("step1.validateInput", job.validateInput)
    matchedMetabolites = timer.time("step1.processFilesContent", job.processFilesContent)
    job.setLastStep(2)
    job.getJobDescription(True, True)
    timer.time("step1.store", JobInformationManager().storeJobInstance, job, 1)
    job.cleanDirectories()

    # step 2
    job2 = JobInformationManager().loadJobInstance(jobID)
    job2.setDirectories(CLIENT_TMP_DIR)
    job2.initializeDirectories()
    selectedCompounds = clientSelectedCompounds(matchedMetabolites)
    timer.time("step2.updateCompounds", job2.updateSubmitedCompoundsList, selectedCompounds)
    timer.time("step2.generatePathwaysList", job2.generatePathwaysList)
    timer.time("step2.globalExpressionData", job2.getGlobalExpressionData)
    if selectedCompounds:
        timer.time("step2.compoundsClassification", job2.compundsClassification, {})
        timer.time("step2.hubAnalysis", job2.hubAnalysis, ROOT_DIRECTORY)
    job2.parseRegulationPerCondition()
    timer.time("step2.metagenes", job2.generateMetagenesList, ROOT_DIRECTORY, {})
    job2.setLastStep(3)
    timer.time("step2.store", JobInformationManager().storeJobInstance, job2, 2)

    # step 3 over every matched pathway
    selectedPathways = sorted((job2.getMatchedPathways() or {}).keys())
    timer.time("step3.generateSelectedPathwaysInformation",
               job2.generateSelectedPathwaysInformation, selectedPathways, [], True)
    timer.time("step3.store", JobInformationManager().storeJobInstance, job2, 3)

    job2.cleanDirectories()
    cleanupJob(jobID)
    # the staged copies in the user's input dir are this run's too
    shutil.rmtree(job.getInputDir(), ignore_errors=True)
    return len(selectedPathways)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", default=os.path.join(REPO, "tests", "perf", "large_input"))
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    import logging
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    logging.getLogger().setLevel(logging.WARNING)

    timer = Timer()
    started = time.perf_counter()
    pathways = run(os.path.abspath(args.input), timer)
    total = round(time.perf_counter() - started, 3)
    result = {"total": total, "phases": timer.phases, "pathways": pathways,
              "bench_runner": os.path.relpath(bench_runner.__file__, REPO)}
    line = json.dumps(result)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(line + "\n")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
