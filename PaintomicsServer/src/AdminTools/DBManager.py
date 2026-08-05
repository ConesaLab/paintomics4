#! /usr/bin/env python
import sys
import os
# sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + "/../../")

# Ensure this script always runs inside the expected virtualenv so required packages are available.
# Disabled for local deployment - using conda env instead.
# VENV_DIR = "/home/tian/paintomics/paintomics_env"
# VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python3")
# if os.path.exists(VENV_PYTHON) and sys.executable != VENV_PYTHON:
#     os.environ["VIRTUAL_ENV"] = VENV_DIR
#     os.environ["PATH"] = os.path.join(VENV_DIR, "bin") + os.pathsep + os.environ.get("PATH", "")
#     os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)

import datetime, traceback, shutil, inspect
import logging
import logging.config
import requests
import gzip
from io import BytesIO
from PIL import Image
from textwrap import wrap
from time import strftime, sleep, time
# STDOUT was previously reaching this module only through the wildcard
# `from scripts.downloadReactome import *` below, which is fragile -- reordering
# or trimming that import would have broken subprocess calls here at runtime.
from subprocess import check_call, check_output, CalledProcessError, DEVNULL, STDOUT

from conf.serverconf import KEGG_DATA_DIR, CLIENT_TMP_DIR, DOWNLOAD_DELAY_1, DOWNLOAD_DELAY_2, MAX_TRIES_1, MAX_TRIES_2
from scripts.downloadReactome import *

VERSION = 0.12


# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
# ---  MAIN FUNCTIONS                                                                   ----
# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------

def download_command(inputfile=None, specie=None, kegg=0, mapping=0, common=0, retry=0, reactome=0):
    """
    Download the information for given species
    Usage: AdminTools.py download <options>
    Examples:
              ./DBManager.py download --specie=mmu --kegg=1 --mapping=1 --common=0 --reactome=0 --updateReactome=0

    Keyword arguments:
        from_file -- a file containing a list of a list of species IDs (one per line), followed by (tabulated)
                            + [0,1]: download Kegg data for the specie
                            + [0,1]: download Mapping data,  where [0 = FALSE,1 = TRUE]
                            default ""
                            e.g.
                                mmu   1   0
                                hsa   1   1
                                ...
        specie    -- a valid KEGG specie code e.g. mmu, hsa

        kegg      -- (optional) download the KEGG data for the given specie. Default=0
        mapping   -- (optional) download the Mapping data for the given specie. Default=0
        common    -- (optional) 1 if Pathways info (classification, PNG images...) should be downloaded, 0 to keep from previous version. Default=0
        retry     -- (optional) 1 to retry the installation of ERRONEOUS SPECIES from previous version, 0 to ignore them. Default=0
    """
    if inputfile is None and specie is None:
        print("Organisms not specified, please type ./DBManager.py download -h for help")
        exit(-1)

    # **************************************************************************
    # STEP 1. READ CONFIGURATION AND PARSE INPUT FILES
    # **************************************************************************
    readConfigurationFile()
    download_dir = KEGG_DATA_DIR + "download/"
    downloadLog = download_dir + "download.log"
    currentStep = 0
    SPECIES_DOWNLOAD = None
    DOWNLOADED_SPECIES = []
    FAILED_SPECIES = []

    # Create the log files.
    #
    # A fresh deployment has an empty KEGG_DATA volume, so this directory does
    # not exist yet. The previous code shelled out to `touch`, whose failure
    # os.system() discards, and the error only surfaced on the next line as
    #   FileNotFoundError: '/data/KEGG_DATA/download/summary.log'
    # which says nothing about the missing parent directory.
    os.makedirs(download_dir, exist_ok=True)
    open(downloadLog, 'a').close()
    summary = open(download_dir + 'summary.log', 'w')

    if inputfile is None:
        n = 3  # Download mapping and kegg
        if mapping == 0:
            n -= 1  # Do not download mapping
        if kegg == 0:
            n -= 2  # Do not download kegg
        SPECIES_DOWNLOAD = {specie: n}  # THE IDS FOR THE SPECIES TO UPDATE
    # Check install options
    else:
        SPECIES_DOWNLOAD = readFile(inputfile)  # THE IDS FOR THE SPECIES TO UPDATE

    log("######################################################################")
    log("### PAINTOMICS 4.0 - DATABASE DOWNLOADER ")
    log("### v." + str(VERSION))
    log("######################################################################")
    log("")
    log("Download log is at: " + downloadLog)
    log("")
    log("STEP " + str(currentStep) + ". READ CONFIGURATION AND PARSE INPUT FILES...")
    log("       - " + str(len(SPECIES_DOWNLOAD.keys())) + " new organisms will be downloaded.")
    log("")

    if ((common == None and confirm(
            prompt='Download common KEGG information (pathway names, classifications, PNG images,...)?',
            resp=False)) or (common == "1")):
        common = True

    # ********************************************************************************
    # STEP 2. IF WE CHOSE TO DOWNLOAD THE GENERAL DATA (PATHWAYS CLASSIFICATION, ETC.) -> GO TO 2.A
    #        OTHERWISE --> GO TO 2.B
    # ********************************************************************************
    currentStep += 1

    # STEP 2.A Download common data
    if common:
        datadir = os.path.join(download_dir, "common/")
        try:
            # STEP 2.A.0 INITIALIZE THE NEW DIRECTORY
            if os.path.isdir(datadir):
                shutil.rmtree(datadir)
            os.mkdir(datadir)
            # Add the flag file "DOWNLOADING"
            version = open(datadir + "DOWNLOADING", 'w')
            version.write("# DOWNLOAD STARTS:" + strftime("%Y%m%d %H%M"))
            version.close()
            log('')
            log("New data will be stored at " + datadir)

            if reactome:

                log("STEP " + str(currentStep) + " Extra. DOWNLOAD THE COMMON REACTOME INFORMATION")

                reactomeURL = "https://reactome.org/download/current/"
                files_to_download = [
                    ("ReactomePathwaysRelation.txt", "ReactomePathwaysRelation.list"),
                    ("UniProt2Reactome_PE_All_Levels.txt", "UniProt2Reactome_PE_All_Levels.txt"),
                    ("ChEBI2Reactome_PE_All_Levels.txt", "ChEBI2Reactome_PE_All_Levels.txt"),
                    ("Ensembl2Reactome_PE_All_Levels.txt", "Ensembl2Reactome_PE_All_Levels.txt"),
                    ("NCBI2Reactome_PE_All_Levels.txt", "NCBI2Reactome_PE_All_Levels.txt")
                ]

                for file_name, output_name in files_to_download:
                    downloadKEGGFile("              * Downloading " + file_name, downloadLog, reactomeURL + file_name, datadir,
                                     output_name, DOWNLOAD_DELAY_1, MAX_TRIES_1)

            # STEP 2.A.1 DOWNLOAD THE DATA FILES
            log("    STEP " + str(currentStep) + ". DOWNLOAD THE COMMON KEGG INFORMATION")
            # KEGG retired /list/organism (HTTP 400). See downloadKEGGOrganismList.
            downloadKEGGOrganismList("              * LIST OF ORGANISMS", downloadLog,
                                     datadir, "organisms_all.list", DOWNLOAD_DELAY_1, MAX_TRIES_1)
            downloadKEGGFile("              * PATHWAYS CLASSIFICATION", downloadLog,
                             "https://rest.kegg.jp/get/br:br08901", datadir, "pathways_classification.list",
                             DOWNLOAD_DELAY_1, MAX_TRIES_1)
            downloadKEGGFile("              * LIST OF REFERENCE PATHWAYS", downloadLog,
                             "https://rest.kegg.jp/list/pathway", datadir, "pathways_all.list", DOWNLOAD_DELAY_1,
                             MAX_TRIES_1)
            downloadKEGGFile("              * LIST OF COMPOUND NAMES", downloadLog, "https://rest.kegg.jp/list/compound",
                             datadir, "compounds_all.list", DOWNLOAD_DELAY_1, MAX_TRIES_1)
            downloadKEGGFile("              * PATHWAY to COMPOUND TABLE", downloadLog,
                             "https://rest.kegg.jp/link/pathway/compound", datadir, "pathway2compound.list",
                             DOWNLOAD_DELAY_1, MAX_TRIES_1)

            # ChEBI mapping download
            # KEGG's /conv/compound/chebi endpoint has been deprecated/removed (returns 400 errors)
            # We now use ChEBI's own database as the source for KEGG-ChEBI mappings
            try:
                downloadChEBItoKEGGMapping("             * KEGG TO ChEBI (from ChEBI database)", downloadLog,
                                          datadir, "kegg2chebi.list", DOWNLOAD_DELAY_1, MAX_TRIES_1)
            except Exception as e:
                log("                      WARNING: ChEBI conversion data unavailable")
                log("                      Continuing without ChEBI mapping - metabolite identification via ChEBI IDs will not be available")
                errorlog("ChEBI-KEGG mapping download failed but continuing: " + str(e))

            # STEP 2.A.2 DOWNLOAD THE PNG IMAGES
            pathways = readFile(datadir + "pathways_all.list", {"forced": True, "forcedColumn": 0})
            total = len(pathways.keys())
            log("             DETECTED " + str(total) + " REFERENCE PATHWAYS " + calculateAproxTime(total,
                                                                                                    DOWNLOAD_DELAY_2 + 3))
            os.mkdir(datadir + "png/")
            os.mkdir(datadir + "png/thumbnails")

            i = 1
            for pathway in pathways.keys():
                pathway = pathway.replace("path:", "")
                downloadKEGGFile("                     - " + pathway + " [" + str(i) + "/" + str(total) + "]",
                                 downloadLog, "https://rest.kegg.jp/get/" + pathway + "/image", datadir + "png/",
                                 pathway + ".png", DOWNLOAD_DELAY_2, MAX_TRIES_1)
                generateThumbnail(datadir + "png/" + pathway + ".png")
                i += 1
                #if i == 5:
                #    break
            # STEP 2.A.3 REMOVE THE DOWNLOADING FLAG AND ADD THE VERSION FILE
            os.remove(datadir + "DOWNLOADING")
            version = open(datadir + "VERSION", 'w')
            version.write("# DOWNLOAD DATE:\t" + strftime("%Y%m%d %H%M"))
            version.close()
            DOWNLOADED_SPECIES.append("common")
            summary.write('\tDOWNLOAD\tSUCCESS\tcommon\n')
            log("DOWNLOAD COMMON KEGG INFORMATION... SUCCESS\n")

        except Exception as e:
            if os.path.isdir(download_dir + "error/common"):
                shutil.rmtree(download_dir + "error/common")
            if os.path.isdir(datadir):
                shutil.move(datadir, download_dir + "error/")

            log("        FAILED WHILE DOWNLOADING/COPYING COMMON KEGG INFORMATION. UNABLE TO CONTINUE. ABORTING!!")
            summary.write('FAILED WHILE DOWNLOADING/COPYING COMMON INFORMATION. UNABLE TO CONTINUE')
            errorlog(e)
            summary.close()
            exit(1)

    currentStep += 1

    # **************************************************************************
    # STEP 2B. GET DATA FOR "TO UPDATE" SPECIES
    # **************************************************************************
    log('')
    log("STEP " + str(currentStep) + ". DOWNLOADING THE INFORMATION FOR THE SELECTED ORGANISMS")
    specie_code_list = SPECIES_DOWNLOAD.keys()
    total = str(len(specie_code_list))
    log("       - " + str(total) + " new organisms will be downloaded.")
    step = 0
    for specie in specie_code_list:
        if specie[0] == "#":
            log("    IGNORING " + specie[1:] + "...")
            continue

        datadir = os.path.join(download_dir, specie + "/")
        try:
            # STEP 2.B.0 INITIALIZE THE NEW DIRECTORY
            if os.path.isdir(datadir):
                shutil.rmtree(datadir)
            os.mkdir(datadir)

            # Add the flag file "DOWNLOADING"
            version = open(datadir + "DOWNLOADING", 'w')
            version.write("# DOWNLOAD STARTS:" + strftime("%Y%m%d %H%M"))
            version.close()

            step += 1
            log("")
            log("New data will be stored at " + datadir)
            log("        DOWLOADING  " + specie + "...")

            kegg_errors = "";
            mapping_errors = "";

            if reactome:
                log("STEP " + str(currentStep) + " Extra. DOWNLOADING REACTOME Files...")
                downloadReactome(specie)

            # STEP 2.B.1 IF USER SPECIFIED THAT KEGG DATA SHOULD BE DOWNLOADED, DOWNLOAD THE KEGG DATA, OTHERWISE COPY PREVIOUS DATA (IF EXISTS)
            # 2 = updateKegg, 3 = updateKegg && updateMapping
            if (SPECIES_DOWNLOAD[specie] > 1 or (not os.path.exists(KEGG_DATA_DIR + "current/" + specie))):
                os.mkdir(datadir + "kgml")
                kegg_errors = getSpecieKeggData(specie, downloadLog, datadir, str(step) + "/" + total)
            else:
                log("COPYING PREVIOUS KEGG DATA FOR " + specie + "...")
                shutil.rmtree(datadir)
                shutil.copytree(KEGG_DATA_DIR + "current/" + specie, datadir,
                                symlinks=True)  # COPYT THE ENTIRE DIRECTORY
                shutil.rmtree(datadir + "mapping")
                # Add the flag file "DOWNLOADING"
                version = open(datadir + "DOWNLOADING", 'w')
                version.write("# DOWNLOAD STARTS:" + strftime("%Y%m%d %H%M"))
                version.close()
                if os.path.isfile(datadir + "VERSION"):
                    os.remove(datadir + "VERSION")

            # STEP 2.B.2 IF SELECTED, GET THE MAPPING DATA, OTHERWISE COPY PREVIOUS DATA
            # 1=updateMapping, 3 = updateKegg && updateMapping

            if (SPECIES_DOWNLOAD[specie] == 1 or SPECIES_DOWNLOAD[specie] == 3 or (
            not os.path.exists(KEGG_DATA_DIR + "species/" + specie + "/mapping/"))):
                log("DOWNLOADING MAPPING DATA...")
                os.mkdir(datadir + "mapping")
                mapping_errors = getSpecieMappingData(specie, downloadLog, datadir + "mapping/",
                                                      str(step) + "/" + total, ROOT_DIRECTORY + "AdminTools/scripts/")
            else:
                log("COPYING PREVIOUS MAPPING DATA...")
                shutil.copytree(KEGG_DATA_DIR + "current/" + specie + "/mapping", datadir + "mapping",
                                symlinks=True)  # COPYT THE ENTIRE DIRECTORY

            # IF SOMETHING WENT WRONG DURING THE DOWNLOAD BUT THE PROCESS CONTINUED (TOLERANCE)
            if kegg_errors != "" or mapping_errors != "":
                log("Errors detected during the download for organism " + specie)
                log("  - Errors during KEGG data download: " + kegg_errors)
                log("  - Errors during MAPPING data download: " + mapping_errors)
                log("The organism will be moved to the erroneous directory but could be valid for installation.")
                raise Exception("Errors detected during the download for organism " + specie + ". Aborting.")

            # STEP 2.B.3 REMOVE THE DOWNLOADING FLAG AND ADD THE VERSION FILE
            os.remove(datadir + "DOWNLOADING")
            version = open(datadir + "VERSION", 'w')
            version.write("# DOWNLOAD DATE:\t" + strftime("%Y%m%d %H%M"))
            version.close()

            DOWNLOADED_SPECIES.append(specie)
            summary.write(specie + '\tDOWNLOAD\tSUCCESS\t' + str(SPECIES_DOWNLOAD[specie]) + '\n')
            log("DOWNLOAD  " + str(SPECIES_DOWNLOAD[specie]) + " " + specie + "...SUCCESS\n")

        except Exception as e:
            if os.path.isdir(download_dir + "error/" + specie):
                shutil.rmtree(download_dir + "error/" + specie)
            if os.path.isdir(datadir):
                shutil.move(datadir, download_dir + "error/")
            summary.write(specie + '\tDOWNLOAD\tERROR\t' + str(SPECIES_DOWNLOAD[specie]) + '\n')
            log("DOWNLOAD  " + str(SPECIES_DOWNLOAD[specie]) + " " + specie + "...ERROR\n")
            errorlog(e)
            FAILED_SPECIES.append(specie)

    currentStep += 1

    # **************************************************************************
    # STEP 6. CLOSING LOG FILES, GENERATING VERSION FILE
    # **************************************************************************
    log('')
    log("STEP " + str(currentStep) + ". CLOSING LOG FILES, GENERATING VERSION FILE")
    summary.close()

    version = open(download_dir + 'VERSION', 'w')
    version.write("# CREATION DATE:\t" + strftime("%Y%m%d %H%M") + "\n\n")
    version.write("######################################################################\n")
    version.write("#### THIS FILE WAS CREATED USING PAINTOMICS DATABASE GENERATOR    ####\n")
    version.write("######################################################################\n\n")
    version.write("----------------------------------------------------------------------\n\n")
    version.write("# DOWNLOADED SPECIES\n\n")
    version.write("\n".join(wrap("\t".join(DOWNLOADED_SPECIES), 40)))
    version.write("\n\n")
    version.write("----------------------------------------------------------------------\n\n")
    version.write("# ERRONEOUS SPECIES\n\n")
    version.write("\n".join(wrap("\t".join(FAILED_SPECIES), 40)))
    version.write("\n\n")
    version.write("----------------------------------------------------------------------\n\n")
    version.close()

    if len(FAILED_SPECIES) > 0 and len(DOWNLOADED_SPECIES) > 0:
        exit(2)
    elif len(FAILED_SPECIES) > 0:
        exit(1)
    else:
        exit(0)


def install_command(inputfile=None, specie=None, common=0, hub=1):
    """
    Install the information for given species
    Usage: AdminTools.py install <options>
    Examples:
              ./DBManager.py install --specie=mmu --common=0 --hub=1

    Keyword arguments:
        from_file -- a file containing a list of a list of species IDs (one per line) to be installed
        specie    -- a valid KEGG specie code e.g. mmu, hsa
        common    -- (optional) 1 if Pathways info (classification, PNG images...) should be reinstalled, 0 to keep from previous version. Default=0
    """
    if inputfile == None and specie == None:
        print("Organisms not specified, please type ./DBManager.py install -h for help")
        exit(-1)

    readConfigurationFile()

    # **************************************************************************
    # STEP 1. READ CONFIGURATION AND PARSE INPUT FILES
    # **************************************************************************
    currentDataDir = os.path.join(KEGG_DATA_DIR, "current/")
    downloadDir = os.path.join(KEGG_DATA_DIR, "download/")
    oldDataDir = os.path.join(KEGG_DATA_DIR, "old/")
    if not os.path.exists(oldDataDir):
        os.mkdir(oldDataDir)

    # Add hub analysis result dir
    hubDir = os.path.join(downloadDir, specie.lower() + "/hubData/")
    currentHubDir = os.path.join(currentDataDir, specie.lower() + "/hubData/")

    # Create download hub directory if it doesn't exist
    if not os.path.exists(hubDir):
        os.makedirs(hubDir)

    installLog = currentDataDir + "install.log"
    summary = open(currentDataDir + 'summary.log', 'a')
    currentStep = 1;

    log("######################################################################")
    log("### PAINTOMICS 4.0 - DATABASE INSTALLER ")
    log("### v." + str(VERSION))
    log("######################################################################")
    log("")
    log("Installation log is at: " + installLog)
    log("")
    log("STEP " + str(currentStep) + ". READ CONFIGURATION AND PARSE INPUT FILES...")

    INSTALLED_SPECIES = []
    ERRONEOUS_SPECIES = []

    SPECIES_INSTALL = None
    if inputfile != None:
        SPECIES_INSTALL = readFile(inputfile)  # THE IDS FOR THE SPECIES TO UPDATE
    else:
        SPECIES_INSTALL = {specie: 1}  # THE IDS FOR THE SPECIES TO UPDATE

    INSTALLED_PREVIOUS = getCurrentInstalledSpecies()  # THE PREVIOUSLY DOWNLOADED SPECIES

    sleep(2)
    log("       - " + str(len(SPECIES_INSTALL.keys())) + " new organisms will be installed.")
    # log("       - " + str(len(DOWNLOADED_PREVIOUS)) + " organisms were downloaded on previous executions." )
    log("       - " + str(len(INSTALLED_PREVIOUS)) + " organisms were installed on previous executions.")
    # log("       - " + str(len(ERRONEOUS_PREVIOUS)) + " organisms failed during the installation on previous executions." )
    log("")

    if ((common == None and confirm(
            prompt='Do you want to install the common KEGG information (compound names, pathway names, ...)?',
            resp=False)) or (common == 1)):
        common = True

    # **************************************************************************
    # STEP 1.5. VALIDATE THAT SPECIES DATA EXISTS (either in download or current)
    # **************************************************************************
    for specie_to_check in SPECIES_INSTALL.keys():
        if specie_to_check[0] == "#":
            continue

        downloadSpecieDir = os.path.join(downloadDir, specie_to_check)
        currentSpecieDir = os.path.join(currentDataDir, specie_to_check)

        # Check if data exists in either download or current directory
        if not os.path.isdir(downloadSpecieDir) and not os.path.isdir(currentSpecieDir):
            error_msg = f"ERROR: Cannot find data for species '{specie_to_check}' in either download ({downloadSpecieDir}) or current ({currentSpecieDir}) directories. Please download the species data first using the download command."
            log(error_msg)
            summary.write(error_msg + '\n')
            summary.close()
            exit(1)

        # Log which directory will be used
        if os.path.isdir(downloadSpecieDir):
            log(f"Species '{specie_to_check}': will use new data from download directory")
        else:
            log(f"Species '{specie_to_check}': will reinstall using existing data from current directory")

    # **************************************************************************
    # STEP 2. INSTALLING KEGG GLOBAL/HUB DATA
    # **************************************************************************

    # ********************************************************************************
    # STEP 2.A.1 IF WE CHOOSED TO install THE hub analysis data
    # ********************************************************************************
    try:
        if hub:
            current_has_hub = directory_has_contents(currentHubDir)
            if current_has_hub:
                log("STEP EXTRA: Hub data already exists in current directory, skipping regeneration...")
            else:
                if not os.path.isdir(hubDir):
                    log("STEP EXTRA: Hub download directory not found. Creating it so we can reuse or regenerate data...")
                    os.makedirs(hubDir, exist_ok=True)

                if not directory_has_contents(hubDir):
                    log("STEP EXTRA: INSTALLING HUB ANALYSIS INFORMATION...")
                    # Capture the output rather than discarding it. This used to
                    # run with stderr=STDOUT, stdout=DEVNULL, which merges the R
                    # error into stdout and then throws it away -- so a missing R
                    # package surfaced only as "returned non-zero exit status 1"
                    # and had to be reproduced by hand to find out which one.
                    try:
                        hubOutput = check_output(
                            [
                                ROOT_DIRECTORY + "AdminTools/scripts/hubAnalysisInstall.R",
                                '--organism="' + specie + '"',
                                '--scriptDir="' + ROOT_DIRECTORY + 'AdminTools/scripts/' + '"',
                                '--outputDir="' + hubDir + '"'
                            ], stderr=STDOUT, universal_newlines=True
                        )
                    except CalledProcessError as hubError:
                        log("        hubAnalysisInstall.R failed (exit " +
                            str(hubError.returncode) + "). Last output:")
                        for outputLine in (hubError.output or "").splitlines()[-25:]:
                            log("          " + outputLine)
                        raise
                else:
                    log("Hub directory already contains data in download directory, skipping regeneration...")

                if directory_has_contents(hubDir):
                    log("STEP EXTRA: Transferring hub data to current directory...")
                    replaceNewVersionData(downloadDir, currentDataDir, specie.lower() + "/hubData", oldDataDir)
                elif directory_has_contents(currentHubDir):
                    log("STEP EXTRA: Hub download directory is empty but current directory has data. Continuing with existing hub data.")
                else:
                    raise Exception("Hub analysis data is missing in both download and current directories.")
    except Exception as e:
        log("        FAILED WHILE INSTALLING HUB ANALYSIS INFORMATION. UNABLE TO CONTINUE. ABORTING!!")
        summary.write('FAILED WHILE INSTALLING HUB ANALYSIS INFORMATION. UNABLE TO CONTINUE. ABORTING!!\n')
        # remove hub directory
        try:
            os.rmdir(hubDir)
        except OSError as rm_error:
            log(f"Failed to remove hub directory: {rm_error}")
        errorlog(e)
        summary.close()
        exit(1)
    # ********************************************************************************
    # STEP 2.A.1 IF WE CHOOSED TO DONWLOAD THE GENERAL DATA (PATHWAYS CLASSIFICATION, ETC.)
    # ********************************************************************************
    try:
        if common:
            log("STEP " + str(currentStep) + ". INSTALLING COMMON KEGG INFORMATION")
            replaceNewVersionData(downloadDir, currentDataDir, "common", oldDataDir)
            installCommonData(currentDataDir + "common/", ROOT_DIRECTORY + "AdminTools/scripts/")
            currentStep += 1
    except Exception as e:
        # TODO: RESTORE
        restorePreviousVersionData(oldDataDir, currentDataDir, "common", downloadDir + "error/")
        installCommonData(currentDataDir + "common/", ROOT_DIRECTORY + "AdminTools/scripts/")
        log("        FAILED WHILE INSTALLING COMMON INFORMATION. UNABLE TO CONTINUE. ABORTING!!")
        summary.write('FAILED WHILE INSTALLING COMMON INFORMATION. UNABLE TO CONTINUE. ABORTING!!')
        errorlog(e)
        summary.close()
        exit(1)

    # **************************************************************************
    # STEP 3. INSTALLING THE PROVIDED SPECIES
    # **************************************************************************
    log("")
    log("STEP " + str(currentStep) + ". INSTALLING NEW ORGANISMS")
    speciesAux = SPECIES_INSTALL.keys()
    total = str(len(speciesAux))
    log("       " + str(total) + " new organisms will be installed.")

    step = 0
    for specie in speciesAux:
        if specie[0] == "#":
            log("    IGNORING " + specie[1:] + "...")
            continue

        step += 1
        dirNameAux = os.path.join(currentDataDir, specie + "/")
        log("        INSTALLING  " + specie + "...")

        try:
            replaceNewVersionData(downloadDir, currentDataDir, specie, oldDataDir)
            installSpecieData(specie, installLog, dirNameAux, str(step) + "/" + total,
                              ROOT_DIRECTORY + "AdminTools/scripts/")
            INSTALLED_SPECIES.append(specie)
            summary.write(specie + '\tINSTALL\tSUCCESS\t' + str(SPECIES_INSTALL[specie]) + '\n')
            log("INSTALL  " + str(SPECIES_INSTALL[specie]) + " " + specie + "...SUCCESS\n")
        except Exception as e:
            restorePreviousVersionData(oldDataDir, currentDataDir, specie, downloadDir + "error/")
            installSpecieData(specie, installLog, dirNameAux, str(step) + "/" + total,
                              ROOT_DIRECTORY + "AdminTools/scripts/")
            summary.write(specie + '\tINSTALL\tERROR\t' + str(SPECIES_INSTALL[specie]) + '\n')
            log("INSTALL  " + str(SPECIES_INSTALL[specie]) + " " + specie + "...ERROR\n")
            errorlog(e)
            ERRONEOUS_SPECIES.append(specie)

    step = 0

    currentStep += 1

    # **************************************************************************
    # STEP 6. CREATE THE species.json FILE
    # **************************************************************************
    log("")
    log("STEP " + str(currentStep) + ". CREATING THE species.json FILE")
    generateAvailableSpeciesFile(INSTALLED_PREVIOUS + INSTALLED_SPECIES, currentDataDir + "common/organisms_all.list",
                                 currentDataDir + "species.json")

    currentStep += 1

    # **************************************************************************
    # STEP 7. CLOSING LOG FILES, GENERATING VERSION FILE
    # **************************************************************************
    log("")
    log("STEP " + str(currentStep) + ". CLOSING LOG FILES, GENERATING VERSION FILE")
    summary.close()

    version = open(currentDataDir + 'VERSION', 'a')

    version.write("\n\n")
    version.write("----------------------------------------------------------------------\n\n")
    version.write("# INSTALLED SPECIES\n\n")
    version.write("\n".join(wrap("\t".join(INSTALLED_SPECIES), 40)))
    version.write("\n\n")
    version.write("----------------------------------------------------------------------\n\n")
    version.write("# FAILED SPECIES (INSTALL)\n\n")
    version.write("\n".join(wrap("\t".join(ERRONEOUS_SPECIES), 40)))
    version.write("\n\n")
    version.write("----------------------------------------------------------------------\n\n")
    version.close()


def restore_command(remove=1, force=0):
    """
    Restores the last version of the database to previous version

    Keyword arguments:
        remove  -- 1 remove the current database directory, 0 keep the directory
        force   -- 1 force remove the current database directory and use previous version, 0  to prompt
    """

    readConfigurationFile()

    realPath = os.path.realpath(KEGG_DATA_DIR + "/last")
    currentFile = os.path.basename(realPath)

    older = '19870729_0534'
    limit = datetime.datetime.strptime(currentFile, "%Y%m%d_%H%M")
    for i in next(os.walk(KEGG_DATA_DIR))[1]:
        if i == "last" or i == "tmp" or i == "TEST_DATA":
            continue

        aux = datetime.datetime.strptime(i, "%Y%m%d_%H%M")
        aux2 = datetime.datetime.strptime(older, "%Y%m%d_%H%M")
        if (aux > aux2) and (aux < limit):
            older = i

    if older != '19870729_0534':
        if (force == 0 and not confirm(prompt='Restore to previous directory ' + older + '?', resp=False)):
            exit(1)

        if os.path.exists(KEGG_DATA_DIR + "/last"):
            os.remove(KEGG_DATA_DIR + "/last")
        os.symlink(KEGG_DATA_DIR + older, KEGG_DATA_DIR + "last")

        if remove == 1:
            if (force == 1 or confirm(prompt='Remove previous directory ' + realPath + '?', resp=False)):
                import shutil
                shutil.rmtree(realPath)


def findnew_command():
    """Find new available species in KEGG."""
    readConfigurationFile()


def findolder_command(nDays):
    """Find installed species older than nDays."""
    readConfigurationFile()


# ------------------------------------------------------------------------------------------
# ---  AUXILIAR FUNCTIONS                                                               ----
# ------------------------------------------------------------------------------------------

def replaceNewVersionData(origin, destination, dirname, backup_dir):
    """
    Replace data in destination with data from origin.
    If origin data doesn't exist, check if we're doing a reinstall (data already in destination).
    """
    source_path = os.path.join(origin, dirname)
    dest_path = os.path.join(destination, dirname)
    backup_path = os.path.join(backup_dir, dirname)

    # Ensure paths are absolute
    source_path = os.path.abspath(source_path)
    dest_path = os.path.abspath(dest_path)
    backup_path = os.path.abspath(backup_path)

    # Check if new data exists in download directory
    if os.path.isdir(source_path):
        # We have new data to install
        
        # 1. Handle Backup: If destination exists, move it to backup
        if os.path.exists(dest_path):
            # Ensure backup parent directory exists
            backup_parent = os.path.dirname(backup_path)
            if not os.path.exists(backup_parent):
                os.makedirs(backup_parent)
            
            # Remove existing backup if it exists
            if os.path.exists(backup_path):
                if os.path.isdir(backup_path):
                    shutil.rmtree(backup_path)
                else:
                    os.remove(backup_path)
            
            # Move current data to backup
            shutil.move(dest_path, backup_path)
            
        # 2. Move new data to destination
        # Ensure destination parent directory exists
        dest_parent = os.path.dirname(dest_path)
        if not os.path.exists(dest_parent):
            os.makedirs(dest_parent)
            
        # Move source to destination
        shutil.move(source_path, dest_path)
        log(f"Installed new data for {dirname}")
        
    elif os.path.isdir(dest_path):
        # Download directory doesn't have data, but current directory does
        # This is a reinstall scenario - data is already in place
        log(f"No new data found in {source_path}, using existing data in {dest_path} for reinstall")
    else:
        # Neither download nor current has the data
        error_msg = f"ERROR: Cannot find data for '{dirname}' in either download ({source_path}) or current ({dest_path}) directories"
        log(error_msg)
        raise Exception(error_msg)


def directory_has_contents(path):
    """
    Returns True if the directory exists and contains at least one file.
    """
    return os.path.isdir(path) and bool(os.listdir(path))


def restorePreviousVersionData(origin, destination, dirname, backup_dir):
    replaceNewVersionData(origin, destination, dirname, backup_dir)

def downloadKEGGOrganismList(message, logFile, dirName, fileName, delay, maxTries):
    """
    Download the KEGG organism list and write it in the layout the rest of the
    codebase expects.

    KEGG retired /list/organism -- it now answers HTTP 400 -- which made every
    fresh install abort at "FAILED WHILE DOWNLOADING/COPYING COMMON KEGG
    INFORMATION". /list/genome replaces it but uses a different shape:

        /list/organism (gone):  T01001<TAB>hsa<TAB>Homo sapiens (human)<TAB>Eukaryotes;...
        /list/genome  (live):   T01001<TAB>hsa; Homo sapiens (human)

    Rather than change every consumer, convert to the historic four-column form.
    AdminServlet, common_build_database and AIInterpret's context_builder all
    read only columns 1 (code) and 2 (name), so the taxonomy column -- which
    /list/genome does not provide -- is written empty.

    Rows without an organism code (viral and addendum genomes are listed as a
    bare description) are skipped: they have no KEGG organism to install.
    """
    log(message)

    url = "https://rest.kegg.jp/list/genome"
    outputPath = os.path.join(dirName, fileName)

    lastError = None
    for attempt in range(1, maxTries + 1):
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()

            rows = []
            for line in response.text.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                entry, description = parts[0], parts[1]
                # "hsa; Homo sapiens (human)" -> code "hsa", name "Homo sapiens (human)"
                if "; " not in description:
                    continue
                code, name = description.split("; ", 1)
                code = code.strip()
                if not code or " " in code:
                    continue
                rows.append((entry, code, name.strip()))

            if not rows:
                raise Exception("no organism rows parsed from " + url)

            with open(outputPath, "w") as handle:
                for entry, code, name in rows:
                    handle.write("\t".join([entry, code, name, ""]) + "\n")

            log("                      Parsed " + str(len(rows)) + " organisms from /list/genome")
            return True
        except Exception as exc:
            lastError = exc
            errorlog("                 FAIL! Trying again... " + str(attempt + 1) + " of " + str(maxTries))
            wait(delay)

    raise Exception("Unable to retrieve the KEGG organism list from " + url +
                    ": " + str(lastError) + "\n")


def downloadChEBItoKEGGMapping(message, logFile, dirName, fileName, delay, maxTries):
    """
    Downloads ChEBI database_accession.tsv.gz and extracts KEGG compound mappings.
    This is an alternative to KEGG's deprecated /conv/compound/chebi endpoint.

    Format: chebi:XXXXX<tab>cpd:CXXXXX
    """
    log(message)

    CHEBI_URL = "https://ftp.ebi.ac.uk/pub/databases/chebi/flat_files/database_accession.tsv.gz"
    KEGG_SOURCE_ID = "45"  # KEGG COMPOUND source ID in ChEBI database

    nTry = 1
    while nTry <= maxTries:
        wait(delay)
        try:
            # Download the gzipped TSV file
            response = requests.get(CHEBI_URL, timeout=120)  # Longer timeout for larger file
            response.raise_for_status()

            # Decompress and parse the TSV file
            with gzip.open(BytesIO(response.content), 'rt') as f:
                lines = f.readlines()

            # Extract KEGG compound mappings
            # Format: id, compound_id, accession_number, type, status_id, source_id
            # We want: compound_id (ChEBI ID) and accession_number (KEGG ID) where source_id=45
            kegg_mappings = []
            for line in lines[1:]:  # Skip header
                fields = line.strip().split('\t')
                if len(fields) >= 6:
                    compound_id = fields[1]
                    accession_number = fields[2]
                    source_id = fields[5]

                    # Filter for KEGG COMPOUND entries with valid KEGG ID format (C + 5 digits)
                    if source_id == KEGG_SOURCE_ID and accession_number.startswith('C') and len(accession_number) == 6:
                        kegg_mappings.append(f"chebi:{compound_id}\tcpd:{accession_number}\n")

            # Write to output file
            with open(dirName + fileName, 'w') as f:
                f.writelines(kegg_mappings)

            # Log success
            with open(logFile, 'a') as log_file:
                log_file.write(f"{strftime('%Y-%m-%d %H:%M:%S')} - Downloaded {fileName} from ChEBI database ({len(kegg_mappings)} mappings)\n")

            log(f"                      SUCCESS: {len(kegg_mappings)} ChEBI-KEGG mappings extracted")
            return True

        except requests.exceptions.RequestException as e:
            # Log the error details to the log file
            with open(logFile, 'a') as log_file:
                log_file.write(f"{strftime('%Y-%m-%d %H:%M:%S')} - Error downloading ChEBI mapping: {str(e)}\n")

            # Only log "Trying again" if we actually will try again
            if nTry < maxTries:
                errorlog("FAIL! Trying again... " + str(nTry + 1) + " of " + str(maxTries))
            nTry += 1
        except Exception as e:
            # Handle parsing errors
            with open(logFile, 'a') as log_file:
                log_file.write(f"{strftime('%Y-%m-%d %H:%M:%S')} - Error processing ChEBI data: {str(e)}\n")

            if nTry < maxTries:
                errorlog("FAIL! Trying again... " + str(nTry + 1) + " of " + str(maxTries))
            nTry += 1

    raise Exception('Unable to retrieve ChEBI-KEGG mapping from ' + CHEBI_URL)

def downloadKEGGFile(message, logFile, URL, dirName, fileName, delay, maxTries):
    log(message)

    nTry = 1
    while nTry <= maxTries:
        wait(delay)
        try:
            # Use requests library instead of wget to avoid C-level memory issues
            response = requests.get(URL, timeout=30)
            response.raise_for_status()  # Raises HTTPError for bad status codes (4xx, 5xx)

            # Write the content to file
            with open(dirName + fileName, 'wb') as f:
                f.write(response.content)

            # Log success to the log file
            with open(logFile, 'a') as log_file:
                log_file.write(f"{strftime('%Y-%m-%d %H:%M:%S')} - Downloaded {fileName} from {URL}\n")

            return True
        except requests.exceptions.RequestException as e:
            # Log the error details to the log file
            with open(logFile, 'a') as log_file:
                log_file.write(f"{strftime('%Y-%m-%d %H:%M:%S')} - Error downloading {fileName}: {str(e)}\n")

            # Only log "Trying again" if we actually will try again
            if nTry < maxTries:
                errorlog("FAIL! Trying again... " + str(nTry + 1) + " of " + str(maxTries))
            nTry += 1
    raise Exception('Unable to retrieve ' + fileName + " from " + URL)


def getSpecieKeggData(specie, downloadLog, dirName, step):
    start_time = time()
    kegg_errors = ""

    log("            FETCHING KEGG DATA FOR " + specie + " (" + step + ")...")
    version = open(dirName + 'KEGG_VERSION', 'w')
    version.write("# CREATION DATE:\t" + strftime("%Y%m%d %H%M"))
    version.close()

    downloadKEGGFile("              * GENE to PATHWAY TABLE", downloadLog, "https://rest.kegg.jp/link/pathway/" + specie,
                     dirName, "gene2pathway.list", DOWNLOAD_DELAY_1, MAX_TRIES_1)
    downloadKEGGFile("              * PATHWAYS LIST", downloadLog, "https://rest.kegg.jp/list/pathway/" + specie,
                     dirName, "pathways.list", DOWNLOAD_DELAY_1, MAX_TRIES_1)
    # downloadKEGGFile("              * PATHWAY to GENE TABLE", downloadLog,  "http://rest.kegg.jp/link/" + specie + "/pathway", dirName, "pathway2gene.list",  DOWNLOAD_DELAY_1, MAX_TRIES_1)

    # CREATE THE pathway2gene.list File
    check_call(
        "cat " + dirName + "/gene2pathway.list | awk '{print $2\"\t\"$1}' | sort > " + dirName + "/pathway2gene.list",
        shell=True)

    # GET THE PATHWAYS LIST AND DOWNLOAD THE IMAGES
    if os.path.isfile(dirName + "pathways.list"):
        if not os.path.isdir(dirName + "kgml/"):
            os.mkdir(dirName + "kgml/")

        pathways = readFile(dirName + "pathways.list", {"forced": True, "forcedColumn": 0})
        total = len(pathways.keys())
        log("                DETECTED " + str(total) + " PATHWAYS FOR " + specie + " " + calculateAproxTime(total,
                                                                                                            DOWNLOAD_DELAY_2 + 3))

        error_tolerance = int(total * 0.05)  # we tolerate that a 5% of the pathways fail on download
        i = 1
        for pathway in pathways.keys():
            try:
                pathway = pathway.replace("path:", "")
                downloadKEGGFile("                     - " + pathway + " [" + str(i) + "/" + str(total) + "]",
                                 downloadLog, "https://rest.kegg.jp/get/" + pathway + "/kgml", dirName + "kgml/",
                                 pathway + ".kgml", DOWNLOAD_DELAY_2, MAX_TRIES_1)
            except Exception as e:
                error_tolerance -= 1;
                kegg_errors += " " + pathway
                if error_tolerance == 0:
                    raise Exception(
                        "Too many errors while downloading the KGML files for organism " + specie + ": " + kegg_errors)
                log("                       Failed!! The download process will continue...")
            i += 1


    else:
        raise Exception('Unable to retrieve ' + dirName + "pathways.list")

    wait(DOWNLOAD_DELAY_2)

    log("        DOWNLOADED IN " + str((time() - start_time)) + " seconds ---")

    return kegg_errors


def getSpecieMappingData(specie, downloadLog, dirName, step, scriptsDir):
    start_time = time()
    mapping_errors = ""

    log("            FETCHING MAPPING DATA FOR " + specie + " (" + step + ")...")
    version = open(dirName + 'MAP_VERSION', 'w')
    version.write("# CREATION DATE:\t" + strftime("%Y%m%d %H%M"))
    version.close()

    downloadLogFile = open(downloadLog, 'a')
    try:
        if os.path.isfile(scriptsDir + specie + "_resources/download_others.py"):
            log("     * RETRIEVING EXTERNAL MAPPING DATA")
            try:
                check_call([sys.executable, scriptsDir + specie + "_resources/download_others.py", specie,
                            ROOT_DIRECTORY + "AdminTools/", dirName], stdout=downloadLogFile, stderr=downloadLogFile)
            except CalledProcessError as exc:
                raise Exception(
                    "Error while calling " + scriptsDir + specie + "_resources/download_others.py" + ": Exit status " + str(
                        exc.returncode) + ". Output is available at " + downloadLog)

        # we tolerate that some of the files fail on download
        error_tolerance = 3
        try:
            downloadKEGGFile("             * KEGG TO NCBI GeneID", downloadLog,
                             "https://rest.kegg.jp/conv/" + specie + "/ncbi-geneid", dirName, "ncbi-geneid2kegg.list",
                             DOWNLOAD_DELAY_1, MAX_TRIES_1)
        except Exception as e:
            error_tolerance -= 1;
            mapping_errors += " ncbi-geneid"
            if error_tolerance == 0:
                raise Exception(
                    "Too many errors while downloading the KEGG mapping files for organism " + specie + ": " + mapping_errors)
            log("                       Failed!! The download process will continue...")

        try:
            downloadKEGGFile("             * KEGG TO Uniprot", downloadLog,
                             "https://rest.kegg.jp/conv/" + specie + "/uniprot", dirName, "uniprot2kegg.list",
                             DOWNLOAD_DELAY_1, MAX_TRIES_1)
        except Exception as e:
            error_tolerance -= 1;
            mapping_errors += " uniprot2kegg"
            if error_tolerance == 0:
                raise Exception(
                    "Too many errors while downloading the KEGG mapping files for organism " + specie + ": " + mapping_errors)
            log("                       Failed!! The download process will continue...")

        try:
            downloadKEGGFile("             * KEGG TO Gene Symbol", downloadLog, "https://rest.kegg.jp/list/" + specie,
                             dirName, "kegg2genesymbol.list", DOWNLOAD_DELAY_1, MAX_TRIES_1)
        except Exception as e:
            error_tolerance -= 1;
            mapping_errors += " kegg2genesymbol"
            if error_tolerance == 0:
                raise Exception(
                    "Too many errors while downloading the KEGG mapping files for organism " + specie + ": " + mapping_errors)
            log("                       Failed!! The download process will continue...")

        # downloadKEGGFile("             * KEGG TO NCBI GI", downloadLog,  "http://rest.kegg.jp/conv/"+ specie +"/ncbi-gi", dirName, "ncbi-gi2kegg.list",  DOWNLOAD_DELAY_1, MAX_TRIES_1)

        log("            DOWNLOADED IN " + str(int((time() - start_time) / 60)) + " minutes ---")
    except Exception as ex:
        raise ex
    finally:
        downloadLogFile.close()
    return mapping_errors


def installSpecieData(specie, downloadLog, dirName, step, scriptsDir):
    start_time = time()
    log("                 INSTALLING MAPPING DATA FOR " + specie + " (" + step + ")...")
    downloadLogFile = open(downloadLog, 'a')

    try:
        if os.path.isfile(scriptsDir + specie + "_resources/build_database.py"):
            log("       * PROCESSING AND INSTALLING CUSTOM AND KEGG DATA ")
            try:
                check_call([sys.executable, scriptsDir + specie + "_resources/build_database.py", specie,
                            ROOT_DIRECTORY + "AdminTools/", dirName, downloadLog], stdout=downloadLogFile,
                           stderr=downloadLogFile)
            except CalledProcessError as exc:
                errorlog(traceback.extract_stack())
                raise Exception(
                    "Error while calling " + scriptsDir + specie + "_resources/build_database.py" + ": Exit status " + str(
                        exc.returncode) + ". Output is available at " + downloadLog)
        else:
            log("       * PROCESSING AND INSTALLING DEFAULT KEGG DATA ")
            try:
                check_call([sys.executable, scriptsDir + "default/build_database.py", specie, ROOT_DIRECTORY + "AdminTools/",
                            dirName, downloadLog], stdout=downloadLogFile, stderr=downloadLogFile)
            except CalledProcessError as exc:
                errorlog(traceback.extract_stack())
                raise Exception(
                    "Error while calling " + scriptsDir + "default/build_database.py" + ": Exit status " + str(
                        exc.returncode) + ". Output is available at " + downloadLog)

        log("        INSTALLED IN " + str(int((time() - start_time))) + " seconds ---")
    except Exception as ex:
        raise ex
    finally:
        downloadLogFile.close()
    return True


def installCommonData(dirName, scriptsDir):
    log("            INSTALLING COMMON DATA... ")

    try:
        import imp
        COMMON_BUILD_DB_TOOLS = imp.load_source('common_build_database', scriptsDir + "common_build_database.py")
        COMMON_BUILD_DB_TOOLS.processKEGGCommonData(dirName, ROOT_DIRECTORY)
    except Exception as ex:
        raise ex
    return True


def getCurrentInstalledSpecies():
    # ****************************************************************
    # Step 1.GET THE LIST OF INSTALLED SPECIES (DATABASES and SPECIES.JSON)
    # ****************************************************************
    organisms_names = {}
    import csv
    from conf.serverconf import MONGODB_HOST, MONGODB_PORT

    # Define the file paths
    current_file_path = KEGG_DATA_DIR + 'current/common/organisms_all.list'
    download_file_path = KEGG_DATA_DIR + 'download/common/organisms_all.list'

    # Check if the file exists in the current directory
    if os.path.isfile(current_file_path):
        file_path = current_file_path
    else:
        # If the file does not exist in the current directory, use the file in the download directory
        file_path = download_file_path

    # Open the file and read its contents
    with open(file_path) as organisms_all:
        reader = csv.reader(organisms_all, delimiter='\t')
        organisms_names = {}
        for row in reader:
            organisms_names[row[1]] = row[2]

    installedSpecies = []
    from pymongo import MongoClient

    client = MongoClient(MONGODB_HOST, MONGODB_PORT)
    databases = client.list_database_names()

    # ****************************************************************
    # Step 2.FOR EACH INSTALLED DATABASE GET THE INFORMATION
    # ****************************************************************
    databaseList = []
    common_info_date = ""

    for database in databases:
        if not "-paintomics" in database:
            continue
        elif "global-paintomics" == database:
            db = client[database]
            common_info_date = db.versions.find({"name": "COMMON"})[0].get("date")
        else:
            # Step 2.1 GET THE SPECIE CODE
            organism_code = database.replace("-paintomics", "")
            # Step 2.2 GET THE SPECIE NAME
            organism_name = organisms_names.get(organism_code, "Unknown specie")

            # Step 2.3 GET THE SPECIE VERSIONS
            db = client[database]
            kegg_date = db.versions.find({"name": "KEGG"})[0].get("date")
            mapping_date = db.versions.find({"name": "MAPPING"})[0].get("date")
            # count_documents replaces Cursor.count(), removed in pymongo 4.
            try:
                acceptedIDsDoc = db.versions.find_one({"name": "ACCEPTED_IDS"})
                acceptedIDs = acceptedIDsDoc.get("ids") if acceptedIDsDoc else ""
            except Exception as ex:
                acceptedIDs = ""

            # Step 2.4 Check if the organism has non installed data available
            if os.path.isfile(KEGG_DATA_DIR + 'download/' + organism_code + '/VERSION'):
                downloaded = True
            elif os.path.isfile(KEGG_DATA_DIR + 'download/' + organism_code + '/DOWNLOADING'):
                downloaded = "downloading"
            else:
                downloaded = False
                # Erroneous download not removed --> remove
                if os.path.isdir(KEGG_DATA_DIR + 'download/' + organism_code):
                    shutil.rmtree(KEGG_DATA_DIR + 'download/' + organism_code)

            databaseList.append({
                "organism_name": organism_name,
                "organism_code": organism_code,
                "kegg_date": kegg_date,
                "mapping_date": mapping_date,
                "acceptedIDs": acceptedIDs,
                "downloaded": downloaded
            })

    client.close()
    return databaseList


def generateAvailableSpeciesFile(VALID_SPECIES, species_file, installed_species_file):
    try:
        # rootName, "organisms_all.list",
        import csv
        species = {}
        with open(species_file, "r") as csvfile:
            rows = csv.reader(csvfile, delimiter='\t')
            # FILL THE TABLE specie_code -> specie_name
            for row in rows:
                species[row[1]] = row[2]
        csvfile.close()

        listAux = []
        for specie in VALID_SPECIES:
            if isinstance(specie, dict):
                listAux.append(specie.get("organism_code"))
            else:
                listAux.append(specie)

        VALID_SPECIES = listAux
        VALID_SPECIES.sort()
        VALID_SPECIES = set(VALID_SPECIES)

        total = len(VALID_SPECIES)

        file_content = '{"success": true, "species": [\n'
        for i, specieCode in enumerate(VALID_SPECIES):
            name = species.get(specieCode, "")
            if name != "":
                name = '\t{"name": "' + name + '", "value": "' + specieCode + '"}'
                if i < total - 1:
                    name += ","
                file_content += name + '\n'
            else:
                # continue
                errorlog("Error while writting specie files" + specieCode)
                raise Exception()
    except Exception as ex:
        errorlog(traceback.extract_stack())
        raise Exception("Error while writting specie " + specieCode)

    if os.path.isfile(installed_species_file):
        shutil.copy(installed_species_file, installed_species_file + "_prev")

    output_file = open(installed_species_file, 'w')
    output_file.write(file_content)
    output_file.write(']}')
    output_file.close()


# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
# ---  MORE AUXILIAR FUNCTIONS                                                          ----
# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------

def generateThumbnail(imagePath):
    from PIL import ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    destination = imagePath.replace("png/", "png/thumbnails/").replace(".png", "_thumb.png")
    thumb = Image.open(imagePath)
    # Generate the thumbnail
    s = thumb.size
    n = min(s)
    thumb = thumb.crop((s[0] / 2 - n / 4, s[1] / 2 - n / 4, s[0] / 2 + n / 4, s[1] / 2 + n / 4))
    thumb.thumbnail((300, 300))
    thumb.save(destination)


def readConfigurationFile():
    global ROOT_DIRECTORY
    ROOT_DIRECTORY = os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + "/../") + "/"
    # PREPARE LOGGING
    logging.config.fileConfig(ROOT_DIRECTORY + 'conf/logging.cfg')


def readFile(path, options=None):
    data = {}
    forced = False
    forcedColumn = 0

    if (options != None):
        options.get("forced", False)
        options.get("forcedColumn", 0)

    if os.path.isfile(path):
        with open(path, 'r') as inputDataFile:  # Change 'rU' to 'r'
            import csv
            for line in csv.reader(inputDataFile, delimiter="\t"):
                if len(line) == 3 and forced == False:  # IF IT IS UPDATE FILE
                    data[line[
                        0]] = 0  # 0= DO NOTHING (DEFAULT ACTION), 1 = updateMapping, 2 = updateKegg, 3 = updateKegg && updateMapping

                    if (line[2] == "1"):  # updateMapping = 1
                        data[line[0]] += 1
                    if (line[1] == "1"):  # updateKegg = 1
                        data[line[0]] += 2
                    if (data[line[0]] == 0):  # IF DO NOTHING, WE REMOVE THE SPECIE FROM THE LIST
                        del data[line[0]]
                else:
                    data[line[forcedColumn]] = 3  # updateKegg = 1, updateMapping = 1

        inputDataFile.close()
    return data


def confirm(prompt=None, resp=False):
    """
    prompts for yes or no response from the user. Returns True for yes and
    False for no.
    'resp' should be set to the default value assumed by the caller when
    user simply types ENTER.
    >>> confirm(prompt='Create Directory?', resp=True)
    Create Directory? [y]|n:
    True
    >>> confirm(prompt='Create Directory?', resp=False)
    Create Directory? [n]|y:
    False
    >>>
    Create Directory? [n]|y: y
    True
    """

    if prompt is None:
        prompt = 'Confirm'

    if resp:
        prompt = '%s [%s]|%s: ' % (prompt, 'y', 'n')
    else:
        prompt = '%s [%s]|%s: ' % (prompt, 'n', 'y')

    while True:
        ans = input(prompt)
        if not ans:
            return resp
        if ans not in ['y', 'Y', 'n', 'N']:
            print('please enter y or n.')
            continue
        if ans == 'y' or ans == 'Y':
            return True
        if ans == 'n' or ans == 'N':
            return False


def diff(a, b):
    b = set(b)
    return [aa for aa in a if aa not in b]


def log(msg):
    frame, filename, line_number, function_name, lines, index = inspect.getouterframes(
        inspect.currentframe())[1]
    line = lines[0]
    indentation_level = line.find(line.lstrip())
    logging.info('{i} {m}'.format(
        i=' ' * indentation_level,
        m=msg
    ))


def errorlog(msg):
    frame, filename, line_number, function_name, lines, index = inspect.getouterframes(
        inspect.currentframe())[1]
    line = lines[0]
    indentation_level = line.find(line.lstrip())
    logging.error('{i} {m}'.format(
        i=' ' * indentation_level,
        m=msg
    ))


def wait(nSeconds):
    # log(message)
    sleep(nSeconds)


def calculateAproxTime(nElems, delay):
    return "[" + str(int(nElems * delay / 60)) + " min aprox.]"


# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
# ---  RUN APP
# ------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------
if __name__ == '__main__':
    import scriptine

    scriptine.run()
