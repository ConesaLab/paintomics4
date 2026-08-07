#***************************************************************
#  This file is part of Paintomics v3
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomics4@outlook.com
#**************************************************************
import logging
import logging.config

import cairosvg
from time import time

from collections import defaultdict

from src.common.ServerErrorManager import handleException
from src.common.UserSessionManager import UserSessionManager
from src.common.JobInformationManager import JobInformationManager
from src.common.Statistics import calculateSignificance, calculateCombinedSignificancePvalues, adjustPvalues, calculateStoufferCombinedPvalue
from src.common.ReplicateDetection import detect_replicates, aggregate_replicates
from src.common.DAO.PathwayAcquisitionJobDAO import PathwayAcquisitionJobDAO
from src.common.DAO.FeatureDAO import FeatureDAO
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

from src.conf.serverconf import CLIENT_TMP_DIR, KEGG_DATA_DIR
from src.conf.organismDB import dicDatabases


def loadRequestedJob(jobID, action):
    """Load the job a request names, or say exactly what was wrong with it.

    Every job endpoint reads a jobID off the request and then immediately
    either concatenates it into a log line or calls a method on the loaded
    instance. Neither tolerates a missing or unknown ID, so a malformed request
    produced one of

        TypeError: can only concatenate str (not "NoneType") to str
        AttributeError: 'NoneType' object has no attribute 'getReadOnly'

    naming neither the field nor the job. Those reach the browser as an opaque
    failure the client cannot render into anything a user can act on.

    @param {String} jobID, as read from the request (may be None)
    @param {String} action, named in the message so the user knows what failed
    @returns {Job} the loaded job instance
    """
    if not jobID:
        raise UserWarning("Missing jobID parameter for " + action + ".")

    jobInstance = JobInformationManager().loadJobInstance(jobID)

    if jobInstance is None:
        raise UserWarning("Job " + str(jobID) + " was not found at database.")

    return jobInstance


#************************************************************************
#     _____ _______ ______ _____    __
#    / ____|__   __|  ____|  __ \  /_ |
#   | (___    | |  | |__  | |__) |  | |
#    \___ \   | |  |  __| |  ___/   | |
#    ____) |  | |  | |____| |       | |
#   |_____/   |_|  |______|_|       |_|
#
def pathwayAcquisitionStep1_PART1(REQUEST, RESPONSE, QUEUE_INSTANCE, JOB_ID, EXAMPLE_FILES_DIR, exampleMode):
    """
    This function corresponds to FIRST PART of the FIRST step in the Pathways acquisition process.
    First, it takes a Request object which contains the fields of the form that started the process.
    This is a summarization for the steps in the process:
        Step 0. VARIABLE DECLARATION
        Step 1. CHECK IF VALID USER SESSION
        Step 2. CREATE THE NEW INSTANCE OF JOB
        Step 3. SAVE THE UPLOADED FILES
        Step 4. QUEUE THE JOB INSTANCE
        Step 5. RETURN THE NEW JOB ID
    @param {Request} REQUEST
    @param {Response} RESPONSE
    @param {RQ QUEUE} QUEUE_INSTANCE
    @param {String} JOB_ID
    @param {Boolean} exampleMode
    @returns Response
    """
    # TODO: ALLOWED_EXTENSIONS http://flask.pocoo.org/docs/0.10/patterns/fileuploads/
    # TODO: secure_filename
    #****************************************************************
    #Step 0. VARIABLE DECLARATION
    #The following variables are defined:
    #  - jobInstance: instance of the PathwayAcquisitionJob class.
    #                 Contains all the information for the current job.
    #  - userID: the ID for the user
    #****************************************************************
    jobInstance = None
    userID = None

    try :
        #****************************************************************
        # Step 1. CHECK IF VALID USER SESSION
        #****************************************************************
        logging.info("STEP0 - CHECK IF VALID USER....")
        userID  = REQUEST.cookies.get('userID')
        sessionToken  = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        #****************************************************************
        # Step 2. CREATE THE NEW INSTANCE OF JOB
        #****************************************************************
        jobInstance = PathwayAcquisitionJob(JOB_ID, userID, CLIENT_TMP_DIR)
        jobInstance.initializeDirectories()
        logging.info("STEP1 - NEW JOB SUBMITTED " + jobInstance.getJobID())

        # Make sure to read the POST data always. UWSGI will fail if
        # not.
        uploadedFiles = REQUEST.files
        formFields = REQUEST.form

        #****************************************************************
        # Step 3. SAVE THE UPLOADED FILES
        #****************************************************************
        if not exampleMode:
            logging.info("STEP1 - FILE UPLOADING REQUEST RECEIVED")
            jobInstance.description=""
            jobInstance.setName(formFields.get("jobDescription", "")[:100])
            specie = formFields.get("specie") #GET THE SPECIES NAME
            databases = REQUEST.form.getlist('databases[]')
            jobInstance.setOrganism(specie)
            # Check the available databases for species
            organismDB = set(dicDatabases.get(specie, [{}])[0].keys())
            jobInstance.setDatabases(list(set([u'KEGG']) | set(databases).intersection(organismDB)))
            logging.info("STEP1 - SELECTED SPECIES IS " + specie)

            jobInstance.setAIConsent(formFields.get("aiConsent", "false"))
            jobInstance.setExperimentDesign(formFields.get("experimentDesign", ""))

            logging.info("STEP1 - READING FILES....")
            JobInformationManager().saveFiles(uploadedFiles, formFields, userID, jobInstance, CLIENT_TMP_DIR)
            logging.info("STEP1 - READING FILES....DONE")

        elif exampleMode == "example":
            #****************************************************************
            # Step 2.SAVE THE UPLOADED FILES
            #****************************************************************
            logging.info("STEP1 - EXAMPLE MODE SELECTED")
            logging.info("STEP1 - COPYING FILES....")

            exampleOmics = {"Gene expression": 'genes', "Metabolomics": 'features', "Proteomics": 'features', "miRNA-seq": 'genes', "DNase-seq": 'genes', "Transcription factor": 'genes'}
            for omicName, enrichment in exampleOmics.items():
                dataFileName = omicName.replace(" ", "_").replace("-seq", "").lower() + "_values.tab"
                logging.info("STEP1 - USING ALREADY SUBMITTED FILE (data file) " + EXAMPLE_FILES_DIR + dataFileName + " FOR  " + omicName)

                relevantFileName = omicName.replace(" ", "_").replace("-seq", "").lower() + "_relevant.tab"
                logging.info("STEP1 - USING ALREADY SUBMITTED FILE (relevant features file) " + EXAMPLE_FILES_DIR + relevantFileName + " FOR  " + omicName)

                if ["Metabolomics"].count( omicName ):
                    jobInstance.addCompoundBasedInputOmic({"omicName": omicName, "inputDataFile": EXAMPLE_FILES_DIR + dataFileName, "relevantFeaturesFile": EXAMPLE_FILES_DIR + relevantFileName, "isExample" : True, "enrichment": enrichment})
                else:
                    jobInstance.addGeneBasedInputOmic({"omicName": omicName, "inputDataFile": EXAMPLE_FILES_DIR + dataFileName, "relevantFeaturesFile": EXAMPLE_FILES_DIR + relevantFileName,  "isExample" : True, "enrichment": enrichment})

            specie = "mmu"
            jobInstance.setOrganism(specie)
            jobInstance.setDatabases(['KEGG', "Reactome"]) # TODO: cambiar

            jobInstance.setAIConsent(formFields.get("aiConsent", "false"))
            jobInstance.setExperimentDesign(formFields.get("experimentDesign", ""))
        else:
            raise NotImplementedError


        #************************************************************************
        # Step 4. Queue job
        #************************************************************************
        QUEUE_INSTANCE.enqueue(
            fn=pathwayAcquisitionStep1_PART2,
            args=(jobInstance, userID, exampleMode, RESPONSE),
            timeout=600,
            job_id= JOB_ID
        )

        #************************************************************************
        # Step 5. Return the Job ID
        #************************************************************************
        RESPONSE.setContent({
            "success": True,
            "jobID":JOB_ID
        })
    except Exception as ex:
        if jobInstance is not None:
            jobInstance.cleanDirectories(remove_output=True)

        handleException(RESPONSE, ex, __file__ , "pathwayAcquisitionStep1_PART1", userID=userID)
    finally:
        return RESPONSE

def pathwayAcquisitionStep1_PART2(jobInstance, userID, exampleMode, RESPONSE):
    """
    This function corresponds to SECOND PART of the FIRST step in the Pathways acquisition process.
    Given a JOB INSTANCE, first processes the uploaded files (identifiers matching and compound list generation)
    and finally generates the response.
    This code is executed at the PyQlite Queue.

    This is a summarization for the steps in the process:
        Step 0. CHECK FILES CONTENT
        Step 1. PROCESS THE FILES DATA
        Step 2. SAVE THE JOB INSTANCE AT THE DATABASE
        Step 3. GENERATE RESPONSE AND FINISH

    @param {PathwayAcquisitionJob} jobInstance
    @param {Response} RESPONSE
    @param {String} userID
    @param {Boolean} exampleMode

    @returns Response
    """
    try :
        #****************************************************************
        # Step 0.VALIDATE THE FILES DATA
        #****************************************************************
        logging.info("STEP0 - VALIDATING INPUT..." )
        jobInstance.validateInput()
        logging.info("STEP1 - VALIDATING INPUT...DONE" )

        #****************************************************************
        # Step 1.PROCESS THE FILES DATA
        #****************************************************************
        logging.info("STEP1 - PROCESSING FILES..." )
        matchedMetabolites = jobInstance.processFilesContent() #This function processes all the files and returns a checkboxes list to show to the user

        logging.info("STEP1 - PROCESSING FILES...DONE" )

        #************************************************************************
        # Step 2. Save the jobInstance in the MongoDB
        #************************************************************************
        logging.info("STEP1 - SAVING JOB DATA..." )
        jobInstance.setLastStep(2)
        jobInstance.getJobDescription(True, exampleMode == "example")
        JobInformationManager().storeJobInstance(jobInstance, 1)
        logging.info("STEP1 - SAVING JOB DATA...DONE" )

        jobInstance.cleanDirectories()

        #************************************************************************
        # Step 3. Update the response content
        #************************************************************************
        RESPONSE.setContent({
            "success": True,
            "organism" : jobInstance.getOrganism(),
            "jobID": jobInstance.getJobID(),
            "userID": jobInstance.getUserID(),
            "matchedMetabolites": list(map(lambda foundFeature: foundFeature.toBSON(), matchedMetabolites)),
            "geneBasedInputOmics": jobInstance.getGeneBasedInputOmics(),
            "compoundBasedInputOmics": jobInstance.getCompoundBasedInputOmics(),
            "databases": jobInstance.getDatabases(),
            "name": jobInstance.getName(),
            "timestamp": int(time())
        })

    except Exception as ex:
        jobInstance.cleanDirectories(remove_output=True)

        # TODO: at this point we should notify the queue system about the error, or else
        # will keep returning success to the job.
        handleException(RESPONSE, ex, __file__ , "pathwayAcquisitionStep1_PART2", userID=userID)
    finally:
        return RESPONSE

#************************************************************************
#     _____ _______ ______ _____    ___
#    / ____|__   __|  ____|  __ \  |__ \
#   | (___    | |  | |__  | |__) |    ) |
#    \___ \   | |  |  __| |  ___/    / /
#    ____) |  | |  | |____| |       / /_
#   |_____/   |_|  |______|_|      |____|
#
def pathwayAcquisitionStep2_PART1(REQUEST, RESPONSE, QUEUE_INSTANCE, ROOT_DIRECTORY):
    """
    This function corresponds to FIRST PART of the SECOND step in the Pathways acquisition process.
    First, it takes a Request object which contains the fields of the form that started the process.
    This is a summary for the steps in the process:
        Step 0. VARIABLE DECLARATION
        Step 1. CHECK IF VALID USER SESSION
        Step 2. LOAD THE INSTANCE OF JOB
        Step 3. QUEUE THE JOB INSTANCE
        Step 4. RETURN THE JOB ID

    @param {Request} REQUEST
    @param {Response} RESPONSE
    @param {RQ QUEUE} QUEUE_INSTANCE
    @returns Response
    """
    #****************************************************************
    #Step 0. VARIABLE DECLARATION
    #The following variables are defined:
    #  - jobID: the ID for the job instance
    #  - userID: the ID for the user
    #****************************************************************
    jobID  =""
    userID = ""

    try :
        #****************************************************************
        # Step 1. CHECK IF VALID USER SESSION
        #****************************************************************
        logging.info("STEP0 - CHECK IF VALID USER....")
        userID  = REQUEST.cookies.get('userID')
        sessionToken  = REQUEST.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        #****************************************************************
        # Step 2.LOAD THE INSTANCE OF JOB
        #****************************************************************
        formFields = REQUEST.form
        jobID  = formFields.get("jobID")
        selectedCompounds= REQUEST.form.getlist("selectedCompounds[]")
        # Retrieve the number of cluster on a per omic basis
        # Note: this will contain the omic name transformed to remove spaces and special chars
        clusterNumber = {key.replace("clusterNumber:", ""): value for key, value in formFields.items() if key.startswith("clusterNumber:")}
        metaboliteClassThreshold = {key.replace("clusterNumber:", ""): value for key, value in formFields.items() if key.startswith("thresholdMetaboliteClass")}

        #************************************************************************
        # Step 3. Queue job
        #************************************************************************
        QUEUE_INSTANCE.enqueue(
            fn=pathwayAcquisitionStep2_PART2,
            args=(jobID, userID, selectedCompounds, clusterNumber, RESPONSE, ROOT_DIRECTORY, metaboliteClassThreshold),
            timeout=600,
            job_id= jobID
        )

        #************************************************************************
        # Step 5. Return the Job ID
        #************************************************************************
        RESPONSE.setContent({
            "success": True,
            "jobID":jobID
        })

    except Exception as ex:
        handleException(RESPONSE, ex, __file__ , "pathwayAcquisitionStep2_PART1", userID=userID)
    finally:
        return RESPONSE

def pathwayAcquisitionStep2_PART2(jobID, userID, selectedCompounds, clusterNumber, RESPONSE, ROOT_DIRECTORY, metaboliteClassThreshold):
    """
    This function corresponds to SECOND PART of the SECOND step in the Pathways acquisition process.
    Given a JOB INSTANCE, first processes the uploaded files (identifiers matching and compound list generation)
    and finally generates the response.
    This code is executed at the Redis Queue.

    This is a summarization for the steps in the process:
        Step 1. READ AND UPDATE THE SELECTED METABOLITES
        Step 2. GENERATE PATHWAYS INFORMATION
        Step 3. GENERATE THE METAGENES INFORMATION
        Step 4. UPDATE JOB INFORMATION AT DATABASE
        Step 5. GENERATE RESPONSE AND FINISH

    @param {PathwayAcquisitionJob} jobInstance
    @param {String[]} selectedCompounds
    @param {Response} RESPONSE
    @param {String} userID
    @param {Boolean} exampleMode

    @returns Response
    """
    jobInstance = None

    try :
        logging.info("STEP2 - LOADING JOB " + jobID + "...")
        jobInstance = JobInformationManager().loadJobInstance(jobID)

        if jobInstance is None:
            raise UserWarning("Job " + jobID + " was not found at database.")

        jobInstance.setDirectories(CLIENT_TMP_DIR)
        jobInstance.initializeDirectories()

        logging.info("STEP2 - JOB " + jobInstance.getJobID() + " LOADED SUCCESSFULLY.")

        #****************************************************************
        # Step 1.READ THE SELECTED METABOLITES
        #****************************************************************
        logging.info("STEP2 - UPDATING SELECTED COMPOUNDS LIST...")
        #TODO: CHANGE THIS TO ALLOW BACK
        jobInstance.updateSubmitedCompoundsList(selectedCompounds)
        logging.info("STEP2 - UPDATING SELECTED COMPOUNDS LIST...DONE")

        logging.info("STEP2 - GENERATING PATHWAYS INFORMATION...")
        summary = jobInstance.generatePathwaysList()

        logging.info("STEP2 - GENERATE COMPOUND CLASSIFICATION")

        # Creat Global expression information for all genes
        globalExpressionData = jobInstance.getGlobalExpressionData()

        if selectedCompounds:
            mappingComp, pValueInDict, classificationDict, exprssionMetabolites, adjustPvalue, totalRelevantFeaturesInCategory, featureSummary, compoundRegulateFeatures = jobInstance.compundsClassification(metaboliteClassThreshold)
            hubAnalysisResult = jobInstance.hubAnalysis( ROOT_DIRECTORY )

            # set compound sources to all database
            #if len(jobInstance.databases) >= 2:
            #    foundCompoundsCopy = [i for i in jobInstance.foundCompounds]
            #    foundCompoundsCopy = jobInstance.foundCompounds.copy()

            #    if "Reactome" in jobInstance.databases:
            #        for compound in foundCompoundsCopy:
            #            compound.matchingDB = "KEGG"

            #    jobInstance.foundCompounds = jobInstance.foundCompounds + foundCompoundsCopy

        # MORE Regulation Analysis: parse the rpc table for the Step 3 panel.
        # Independent of metabolomics — runs whenever the job has MORE-produced
        # geneBasedInputOmics. Self-skips otherwise.
        jobInstance.parseRegulationPerCondition()

        #****************************************************************
        # Step 2. GENERATING PATHWAYS INFORMATION
        #****************************************************************

        #if selectedCompounds:
        #    hubAnalysisResult = jobInstance.hubAnalysis( ROOT_DIRECTORY )
        logging.info("STEP2 - GENERATING PATHWAYS INFORMATION...DONE")

        #****************************************************************
        # Step 3. GENERATING METAGENES INFORMATION
        #****************************************************************
        logging.info("STEP2 - GENERATING METAGENES INFORMATION...")
        jobInstance.generateMetagenesList(ROOT_DIRECTORY, clusterNumber)
        logging.info("STEP2 - GENERATING METAGENES INFORMATION...DONE")

        jobInstance.setLastStep(3)

        #************************************************************************
        # Step 4. Save the all the Matched Compounds and pathways in MongoDB
        #************************************************************************
        logging.info("STEP2 - SAVING NEW JOB DATA..." )
        JobInformationManager().storeJobInstance(jobInstance, 2)
        logging.info("STEP2 - SAVING NEW JOB DATA...DONE" )

        #************************************************************************
        # Step 5. Update the response content
        #************************************************************************
        matchedPathwaysJSON = {pathwayID: pathway.toBSON() for pathwayID, pathway in jobInstance.getMatchedPathways().items()}
        matchedClassJSON = {classID: matchedclass.toBSON() for classID, matchedclass in jobInstance.getMatchedClass().items()}

        if selectedCompounds:
            RESPONSE.setContent({
                "success": True,
                "organism" : jobInstance.getOrganism(),
                "jobID":jobInstance.getJobID(),
                "summary" : summary,
                "pathwaysInfo" : matchedPathwaysJSON,
                # PaintOmics 4
                "classInfo": matchedClassJSON,
                "geneBasedInputOmics": jobInstance.getGeneBasedInputOmics(),
                "compoundBasedInputOmics": jobInstance.getCompoundBasedInputOmics(),
                "databases": jobInstance.getDatabases(),
                "omicsValuesID": jobInstance.getValueIdTable(),
                # Add classification metabolism
                "mappingComp": mappingComp,
                "classificationDict": classificationDict,
                "pValueInDict": pValueInDict,
                "exprssionMetabolites": exprssionMetabolites,
                "adjustPvalue": adjustPvalue,
                "totalRelevantFeaturesInCategory": totalRelevantFeaturesInCategory,
                "featureSummary":featureSummary,
                # Add compound regulate features
                "compoundRegulateFeatures": compoundRegulateFeatures,
                # Add global gene expression information
                "globalExpressionData":globalExpressionData,
                # Add hub analysis result
                'hubAnalysisResult': hubAnalysisResult,
                # Add MORE RegulationPerCondition table for the Step 3 panel
                # (None when MORE wasn't run; panel hides itself in that case).
                "regulationPerConditionData": getattr(jobInstance, "regulationPerConditionData", None),
                "aiConsent": jobInstance.getAIConsent(),
                "experimentDesign": jobInstance.getExperimentDesign(),
                "conditionNames": getattr(jobInstance, "conditionNames", []),
                "timestamp": int(time())
            })
        else:
            RESPONSE.setContent( {
                "success": True,
                "organism": jobInstance.getOrganism(),
                "jobID": jobInstance.getJobID(),
                "summary": summary,
                "pathwaysInfo": matchedPathwaysJSON,
                # PaintOmics 4
                "classInfo": matchedClassJSON,
                "geneBasedInputOmics": jobInstance.getGeneBasedInputOmics(),
                "compoundBasedInputOmics": jobInstance.getCompoundBasedInputOmics(),
                "databases": jobInstance.getDatabases(),
                "omicsValuesID": jobInstance.getValueIdTable(),
                # Add classification metabolism
                "mappingComp": {},
                "pValueInDict": [],
                "classificationDict": {},
                "exprssionMetabolites": {},
                "adjustPvalue": [],
                "totalRelevantFeaturesInCategory": [],
                "featureSummary": [0, 0],
                "compoundRegulateFeatures": {},
                "hubAnalysisResult": {},
                "globalExpressionData": globalExpressionData,
                # MORE rpc table — populated when MORE was used, even without metabolomics.
                "regulationPerConditionData": getattr(jobInstance, "regulationPerConditionData", None),
                "aiConsent": jobInstance.getAIConsent(),
                "experimentDesign": jobInstance.getExperimentDesign(),
                "conditionNames": getattr(jobInstance, "conditionNames", []),
                "timestamp": int( time() )
            } )

    except Exception as ex:
        handleException(RESPONSE, ex, __file__ , "pathwayAcquisitionStep2_PART2", userID=userID)
    finally:
        jobInstance.cleanDirectories()
        return RESPONSE

#************************************************************************
#     _____ _______ ______ _____    ____
#    / ____|__   __|  ____|  __ \  |___ \
#   | (___    | |  | |__  | |__) |   __) |
#    \___ \   | |  |  __| |  ___/   |__ <
#    ____) |  | |  | |____| |       ___) |
#   |_____/   |_|  |______|_|      |____/
#
def pathwayAcquisitionStep3(request, response):
    #VARIABLE DECLARATION
    jobInstance = None
    jobID  = ""
    userID = ""

    try :
        #****************************************************************
        # Step 0.CHECK IF VALID USER SESSION
        #****************************************************************
        logging.info("STEP0 - CHECK IF VALID USER....")
        userID  = request.cookies.get('userID')
        sessionToken  = request.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        #****************************************************************
        # Step 1.LOAD THE INSTANCE OF JOB
        #****************************************************************
        formFields = request.form
        jobID  = formFields.get("jobID")

        #TODO: IN PREVIOUS STEPS THE USER COULD SPECIFY THE DEFAULT OMICS TO SHOW
        visibleOmics = []

        # Validated before the log line: concatenating a missing jobID here
        # raised TypeError before the "was not found" check could ever run.
        jobInstance = loadRequestedJob(jobID, "step 3")

        logging.info("STEP3 - LOADING JOB " + jobID + "...")

        logging.info("STEP3 - JOB " + jobInstance.getJobID() + " LOADED SUCCESSFULLY.")

        #****************************************************************
        # Step 2.READ THE SELECTED PATHWAYS
        #****************************************************************
        logging.info("STEP3 - GENERATING PATHWAYS INFORMATION...")
        selectedPathways= formFields.getlist("selectedPathways")
        #TODO: SOLO GENERAR INFO PARA LAS QUE NO LA TENGAN YA GUARDADA EN LA BBDD
        [selectedPathwayInstances, graphicalOptionsInstancesBSON, omicsValuesSubset] = jobInstance.generateSelectedPathwaysInformation(selectedPathways, visibleOmics, True)

        logging.info("STEP3 - GENERATING PATHWAYS INFORMATION...DONE")

        #************************************************************************
        # Step 3. Save the jobInstance in the MongoDB
        #************************************************************************
        logging.info("STEP 3 - SAVING NEW JOB DATA..." )
        JobInformationManager().storeJobInstance(jobInstance, 3)
        logging.info("STEP 3 - SAVING NEW JOB DATA...DONE" )

        response.setContent({
            "success": True,
            "jobID": jobInstance.getJobID(),
            "graphicalOptionsInstances" : graphicalOptionsInstancesBSON,
            "omicsValues": omicsValuesSubset,
            "organism" : jobInstance.getOrganism()
        })

    except Exception as ex:
        handleException(response, ex, __file__ , "pathwayAcquisitionStep3", userID=userID)
    finally:
        return response

def pathwayAcquisitionRecoverJob(request, response, QUEUE_INSTANCE):
    #VARIABLE DECLARATION
    jobInstance = None
    jobID=""
    userID = ""
    #TODO: COMPROBAR OWNERS
    try :
        #****************************************************************
        # Step 0.CHECK IF VALID USER SESSION
        #****************************************************************
        logging.info("STEP0 - CHECK IF VALID USER....")
        userID  = request.cookies.get('userID')
        sessionToken  = request.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        #****************************************************************
        # Step 1.LOAD THE INSTANCE OF JOB
        #****************************************************************


        formFields = request.form
        jobID  = formFields.get("jobID")

        # Concatenating a missing jobID into this log line raised TypeError
        # before any of the checks below could report the real problem. The
        # "not found" case keeps its own richer message further down, so only
        # absence is rejected here.
        if not jobID:
            raise UserWarning("Missing jobID parameter for recovering a job.")

        logging.info("RECOVER_JOB - LOADING JOB " + jobID + "...")
        jobInstance = JobInformationManager().loadJobInstance(jobID)
        queueJob = QUEUE_INSTANCE.fetch_job(jobID)

        if queueJob is not None and not queueJob.is_finished():
            logging.info("RECOVER_JOB - JOB " + jobID + " HAS NOT FINISHED ")
            response.setContent({"success": False, "message": "Your job " + jobID + " is still running in the queue. Please, try again later to check if it has finished."})
            return response

        if jobInstance == None:
            #TODO DIAS BORRADO?
            logging.info("RECOVER_JOB - JOB " + jobID + " NOT FOUND AT DATABASE.")
            response.setContent({"success": False, "errorMessage": "Job " + jobID + " not found at database.<br>Please, note that jobs are automatically removed after 7 days for guests and 14 days for registered users."})
            return response

        # Allow "no user" jobs to be viewed by anyone, logged or not
        if str( jobInstance.getUserID() ) != 'None' and jobInstance.getUserID() != userID and not jobInstance.getAllowSharing():
            logging.info("RECOVER_JOB - JOB " + jobID + " DOES NOT BELONG TO USER " + str(userID) + " JOB HAS USER " + str(jobInstance.getUserID()))
            response.setContent({"success": False, "errorMessage": "Invalid Job ID (" + jobID + ") for current user.<br>Please, check the Job ID and try again."})
            return response

        # Sanitize optional PaintOmics 4 fields that may come back as strings
        def _as_dict(value):
            return value if isinstance(value, dict) else {}

        def _as_list(value):
            return value if isinstance(value, list) else []

        def _as_dict_or_list(value):
            return value if isinstance(value, (dict, list)) else {}

        safe_mappingComp = _as_dict(jobInstance.mappingComp)
        safe_classificationDict = _as_dict(jobInstance.classificationDict)
        safe_pValueInDict = _as_dict_or_list(jobInstance.pValueInDict)
        safe_exprssionMetabolites = _as_dict(jobInstance.exprssionMetabolites)
        safe_adjustPvalue = _as_dict_or_list(jobInstance.adjustPvalue)
        safe_totalRelevantFeaturesInCategory = _as_dict_or_list(jobInstance.totalRelevantFeaturesInCategory)
        safe_featureSummary = jobInstance.featureSummary if isinstance(jobInstance.featureSummary, list) else [0, 0]
        safe_compoundRegulateFeatures = _as_dict(jobInstance.compoundRegulateFeatures)
        safe_globalExpressionData = _as_dict(jobInstance.getGlobalExpressionData())
        safe_hubAnalysisResult = _as_dict(jobInstance.hubAnalysisResult)

        logging.info("RECOVER_JOB - JOB " + jobInstance.getJobID() + " LOADED SUCCESSFULLY.")

        matchedCompoundsJSONList = list(map(lambda foundFeature: foundFeature.toBSON(), jobInstance.getFoundCompounds()))

        logging.info("RECOVER_JOB - GENERATING PATHWAYS CLASS INFORMATION...DONE")

        matchedPathwaysJSONList = []
        for matchedPathway in jobInstance.getMatchedPathways().values():
            matchedPathwaysJSONList.append(matchedPathway.toBSON())
        
        logging.info("RECOVER_JOB - GENERATING PATHWAYS INFORMATION...DONE")

        matchedClassJSONList = []
        for matchedclass in jobInstance.getMatchedClass().values():
            matchedClassJSONList.append( matchedclass.toBSON() )

        if len( matchedCompoundsJSONList ) == 0 and jobInstance.getLastStep() == 2 and len( jobInstance.getCompoundBasedInputOmics() ) > 0:
            logging.info("RECOVER_JOB - JOB " + jobID + " DOES NOT CONTAINS FOUND COMPOUNDS (STEP 2: OLD FORMAT?).")
            response.setContent({"success": False, "errorMessage": "Job " + jobID + " does not contains saved information about the found compounds, please run it again."})
        elif len( matchedPathwaysJSONList ) == 0 and jobInstance.getLastStep() > 2:
            logging.info("RECOVER_JOB - JOB " + jobID + " DOES NOT CONTAINS PATHWAYS.")
            response.setContent( {"success": False, "errorMessage":"Job " + jobID + " does not contains information about pathways. Please, run it again."})
        else:
            if len(matchedPathwaysJSONList) != 0 :
                response.setContent({
                    "success": True,
                    "jobID": jobInstance.getJobID(),
                    "userID": jobInstance.getUserID(),
                    "pathwaysInfo" : matchedPathwaysJSONList,
                    "geneBasedInputOmics": jobInstance.getGeneBasedInputOmics(),
                    "compoundBasedInputOmics": jobInstance.getCompoundBasedInputOmics(),
                    "organism" : jobInstance.getOrganism(),
                    "summary" : jobInstance.summary,
                    "visualOptions" : JobInformationManager().getVisualOptions(jobID),
                    "databases": jobInstance.getDatabases(),
                    "matchedMetabolites": matchedCompoundsJSONList,
                    "stepNumber": jobInstance.getLastStep(),
                    "name": jobInstance.getName(),
                    "timestamp": int(time()),
                    "allowSharing": jobInstance.getAllowSharing(),
                    "readOnly": jobInstance.getReadOnly(),
                    "omicsValuesID": jobInstance.getValueIdTable(),
                    #PaintOmics 4
                    "classInfo": matchedClassJSONList,
                    "mappingComp": safe_mappingComp,
                    "classificationDict": safe_classificationDict,
                    "pValueInDict": safe_pValueInDict,
                    "exprssionMetabolites": safe_exprssionMetabolites,
                    "adjustPvalue": safe_adjustPvalue,
                    "totalRelevantFeaturesInCategory": safe_totalRelevantFeaturesInCategory,
                    "featureSummary": safe_featureSummary,
                    # Add compound regulate features
                    "compoundRegulateFeatures": safe_compoundRegulateFeatures,
                    # Add global gene expression information
                    "globalExpressionData": safe_globalExpressionData,
                    # Add hub analysis result
                    'hubAnalysisResult': safe_hubAnalysisResult,
                    # Add MORE RegulationPerCondition table for the Step 3 panel.
                    # Persisted in Mongo (PAINTOMICS4_DICT_FIELDS), so reloads survive.
                    "regulationPerConditionData": getattr(jobInstance, "regulationPerConditionData", None),
                    "aiConsent": jobInstance.getAIConsent(),
                    "conditionNames": getattr(jobInstance, "conditionNames", []),
                })
            else:
                response.setContent({
                    "success": True,
                    "jobID": jobInstance.getJobID(),
                    "userID": jobInstance.getUserID(),
                    "pathwaysInfo" : matchedPathwaysJSONList,
                    "geneBasedInputOmics": jobInstance.getGeneBasedInputOmics(),
                    "compoundBasedInputOmics": jobInstance.getCompoundBasedInputOmics(),
                    "organism" : jobInstance.getOrganism(),
                    "summary" : jobInstance.summary,
                    "visualOptions" : JobInformationManager().getVisualOptions(jobID),
                    "databases": jobInstance.getDatabases(),
                    "matchedMetabolites": matchedCompoundsJSONList,
                    "stepNumber": jobInstance.getLastStep(),
                    "name": jobInstance.getName(),
                    "timestamp": int(time()),
                    "allowSharing": jobInstance.getAllowSharing(),
                    "readOnly": jobInstance.getReadOnly(),
                    "omicsValuesID": jobInstance.getValueIdTable(),
                    "aiConsent": jobInstance.getAIConsent(),
                    "conditionNames": getattr(jobInstance, "conditionNames", []),
                })

    except Exception as ex:
        handleException(response, ex, __file__ , "pathwayAcquisitionRecoverJob", userID=userID)
    finally:
        return response

def pathwayAcquisitionTouchJob(request, response):
    try:
        jobID = request.form.get("jobID")
        JobInformationManager().touchAccessDate(jobID)

        response.setContent({"success": True})
    except Exception as ex:
        handleException(response, ex, __file__, "pathwayAcquisitionTouchJob", jobID=jobID)
    finally:
        return response

def pathwayAcquisitionSaveImage(request, response):
    jobID=""
    try:
        #****************************************************************
        # Step 0.CHECK IF VALID USER SESSION
        #****************************************************************
        # logging.info("STEP0 - CHECK IF VALID USER....")
        # userID  = request.cookies.get('userID')
        # sessionToken  = request.cookies.get('sessionToken')
        # UserSessionManager().isValidUser(userID, sessionToken)

        jobID = request.form.get("jobID")
        jobInstance = loadRequestedJob(jobID, "saving the image")

        svgData = request.form.get("svgCode")

        # .replace() straight off the form raised AttributeError when the field
        # was absent, so a request missing it failed without naming it.
        requestedFileName = request.form.get("fileName")
        if not requestedFileName:
            raise UserWarning("Missing fileName parameter for saving the image.")

        fileName = "paintomics_" + requestedFileName.replace(" ", "_").replace("/", "_") + "_" + jobID
        fileFormat = request.form.get("format")

        # userID = jobInstance.getUserID()
        # userDirID = userID if userID is not None else "nologin"
        # path = CLIENT_TMP_DIR + userDirID + jobInstance.getOutputDir().replace(CLIENT_TMP_DIR + userDirID, "")
        path = jobInstance.getOutputDir()
        logging.info("The path is xxx: " + path)

        if(fileFormat == "png"):
            def createImage(svgData):
                cairosvg.svg2png(bytestring=svgData, write_to=path + fileName + "." + fileFormat, unsafe=True)
            try:
                logging.info("TRYING...")
                createImage(svgData=svgData)
            except Exception as ex:
                logging.info("TRYING again...")
                createImage(svgData=svgData)

        elif(fileFormat == "svg"):
            file_ = open(path + fileName + "." + fileFormat, 'w')
            file_.write(svgData)
            file_.close()

        path = "/get_cluster_image/" + jobID + "/output/"

        response.setContent({"success": True, "filepath": path + fileName + "." + fileFormat})
    except Exception as ex:
        handleException(response, ex, __file__ , "pathwayAcquisitionSaveImage")
    finally:
        return response

def pathwayAcquisitionSaveVisualOptions(request, response):
    #VARIABLE DECLARATION
    visualOptionsInstance = None
    jobID  = ""
    userID = ""

    try :
        #****************************************************************
        # Step 0.CHECK IF VALID USER SESSION
        #****************************************************************
        logging.info("STEP0 - CHECK IF VALID USER....")
        userID  = request.cookies.get('userID')
        sessionToken  = request.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        #****************************************************************
        # Step 1.GET THE INSTANCE OF visual Options
        #****************************************************************
        visualOptions = request.get_json()
        jobID  = visualOptions.get("jobID")

        jobInstance = loadRequestedJob(jobID, "saving visual options")

        if jobInstance.getReadOnly() and str(jobInstance.getUserID()) != str(userID):
            raise Exception("Invalid user for the job saving visual options")

        newTimestamp = int(time())
        visualOptions["timestamp"] = newTimestamp

        #************************************************************************
        # Step 3. Save the visual Options in the MongoDB
        #************************************************************************
        logging.info("STEP 3 - SAVING VISUAL OPTIONS FOR JOB " + jobID + "..." )
        JobInformationManager().storeVisualOptions(jobID, visualOptions)
        logging.info("STEP 3 - SAVING VISUAL OPTIONS FOR JOB " + jobID + "...DONE" )

        response.setContent({"success": True, "timestamp": newTimestamp})

    except Exception as ex:
        handleException(response, ex, __file__ , "pathwayAcquisitionSaveVisualOptions", userID=userID)
    finally:
        return response

def pathwayAcquisitionSaveSharingOptions(request, response):
    #VARIABLE DECLARATION
    jobID  = ""
    userID = ""

    try :
        #****************************************************************
        # Step 0.CHECK IF VALID USER SESSION
        #****************************************************************
        logging.info("STEP0 - CHECK IF VALID USER....")
        userID  = request.cookies.get('userID')
        sessionToken  = request.cookies.get('sessionToken')
        UserSessionManager().isValidUser(userID, sessionToken)

        #****************************************************************
        # Step 1.GET THE INSTANCE OF sharing options
        #****************************************************************
        jobID = request.form.get("jobID")
        jobInstance = loadRequestedJob(jobID, "saving sharing options")

        if str(jobInstance.getUserID()) != str(userID):
            raise Exception("Invalid user for this jobID")

        #************************************************************************
        # Step 3. Save the visual Options in the MongoDB
        #************************************************************************
        jobInstance.setAllowSharing(request.form.get("allowSharing", 'false') == 'true')
        jobInstance.setReadOnly(request.form.get("readOnly", 'false') == 'true')

        logging.info("STEP 3 - SAVING SHARING OPTIONS FOR JOB " + jobID + "..." )
        JobInformationManager().storeSharingOptions(jobInstance)
        logging.info("STEP 3 - SAVING SHARING OPTIONS FOR JOB " + jobID + "...DONE" )

        response.setContent({"success": True})
    except Exception as ex:
        handleException(response, ex, __file__ , "pathwayAcquisitionSaveSharingOptions", userID=userID)
    finally:
        return response

def pathwayAcquisitionApplyReplicateMapping(request, response):
    """
    Apply (or clear) a replicate→sample mapping for one omic of a job.

    The user reaches this endpoint from the Step-2 "Replicate detection" panel
    after their values file has been parsed. The endpoint takes their chosen
    mode and (for manual mode) a 2-column design file, computes the sample
    grouping, and writes per-sample aggregated values onto every OmicValue
    of the targeted omic.

    Request JSON
    ------------
    {
        "jobID":      str,
        "omicName":   str,                     # must match an inputOmic
        "mode":       "auto" | "manual" | "off",
        "design":     str (optional)           # 2-column TSV body, manual mode only.
                                               # Header row optional. Column 1 must
                                               # match omicHeader[1:]; column 2 is
                                               # the biological-sample label.
    }

    Response JSON
    -------------
    {
        "success":      True,
        "status":       "applied" | "cleared",
        "mode":         echo of input mode,
        "sampleHeader": list[str]              # empty when status == "cleared"
        "mapping":      list[int]              # parallel to omicHeader[1:]
        "featuresUpdated": int                 # number of Genes/Compounds touched
    }
    """
    userID = ""
    jobID = ""
    try:
        # ---- Step 0. Session check ----------------------------------------
        userID = request.cookies.get("userID")
        sessionToken = request.cookies.get("sessionToken")
        UserSessionManager().isValidUser(userID, sessionToken)

        # ---- Step 1. Parse and validate input -----------------------------
        payload = request.get_json() or {}
        jobID    = payload.get("jobID")
        omicName = payload.get("omicName")
        mode     = (payload.get("mode") or "").lower()

        if not jobID:
            raise Exception("Missing jobID.")
        if not omicName:
            raise Exception("Missing omicName.")
        if mode not in ("auto", "manual", "off"):
            raise Exception("Invalid mode '%s'; expected 'auto', 'manual', or 'off'." % mode)

        # ---- Step 2. Load job and locate the targeted omic ----------------
        jobInstance = JobInformationManager().loadJobInstance(jobID)
        if jobInstance is None:
            raise Exception("Job %s not found." % jobID)
        if jobInstance.getReadOnly() and str(jobInstance.getUserID()) != str(userID):
            raise Exception("Read-only job — replicate mapping cannot be modified by this user.")

        # ---- Step 3. Compute mapping & aggregate via the job's apply method.
        # The PathwayAcquisitionJob owns the single source of truth for both
        # the auto-apply path (Step-1 processFilesContent) and this endpoint —
        # no aggregation logic lives in the servlet.
        # Resolve the omic once, for every mode. featureDict is needed further
        # down to re-emit the affected feature collection; it used to be looked
        # up only inside the manual branch and discarded into `_`, so the
        # reinsert below raised NameError *after* the features had already been
        # deleted.
        inputOmic, featureDict, featureType = jobInstance._findInputOmicByName(omicName)
        if inputOmic is None:
            raise Exception("Omic '%s' not found in this job." % omicName)

        if mode == "manual":
            # Parse the design file here (servlet-level concern: reading uploaded
            # text). The job method handles the in-memory aggregation.
            designBody = payload.get("design") or ""
            omicHeader = inputOmic.get("omicHeader") or []
            replicateHeader = omicHeader[1:] if len(omicHeader) > 1 else []
            sampleHeader, mapping, groups = _parseDesignFile(designBody, replicateHeader)
            result = jobInstance.applyReplicateMappingForOmic(
                omicName, mode="manual",
                sampleHeader=sampleHeader, mapping=mapping, groups=groups,
            )
        else:
            result = jobInstance.applyReplicateMappingForOmic(omicName, mode=mode)

        sampleHeader     = result["sampleHeader"]
        mapping          = result["mapping"]
        featureType      = result["featureType"]
        featuresUpdated  = result["featuresUpdated"]

        # ---- Step 5. Persist ---------------------------------------------
        # Update the inputOmic dict on the job document (only the two list
        # fields can change), then re-emit the affected feature collection.
        # Reinsert the whole featureType bucket — same heavy-but-safe pattern
        # used by step-2 storeJobInstance for compounds.
        jobDAO = PathwayAcquisitionJobDAO()
        try:
            jobDAO.update(jobInstance, {"fieldList": ["geneBasedInputOmics", "compoundBasedInputOmics"]})
        finally:
            jobDAO.closeConnection()

        featDAO = FeatureDAO()
        try:
            # Materialise the replacement set *before* deleting the old one.
            # removeAll + insertAll is not atomic, so anything that can fail
            # between them costs the user their features -- which is exactly
            # what happened while featureDict was unbound here.
            featuresToStore = list(featureDict.values()) if featureDict else []
            featDAO.removeAll({"jobID": jobID, "featureType": featureType})
            if featuresToStore:
                featDAO.insertAll(featuresToStore, {"jobID": jobID})
        finally:
            featDAO.closeConnection()

        response.setContent({
            "success":          True,
            "status":           "cleared" if mode == "off" else "applied",
            "mode":             mode,
            "sampleHeader":     sampleHeader,
            "mapping":          mapping,
            "featuresUpdated":  featuresUpdated,
        })
    except Exception as ex:
        handleException(response, ex, __file__, "pathwayAcquisitionApplyReplicateMapping", userID=userID)
    finally:
        return response


def _parseDesignFile(body, replicateHeader):
    """
    Parse a user-supplied 2-column design file (tab- or comma-separated).

    Format:
        [optional header row]
        sample_column_1<sep>sample_label_1
        sample_column_2<sep>sample_label_2
        ...

    `sample_column_*` must match (after whitespace strip) one of the column
    names in ``replicateHeader``. ``sample_label_*`` is the biological-sample
    name the row collapses into. Sample-label order in the result follows the
    order in which each label is first seen in the file (so the user controls
    the display order via row order).

    Validation:
    - Every entry in ``replicateHeader`` must appear in the file (else hard error).
    - Sample labels must be non-empty (else hard error).

    Returns ``(sampleHeader, mapping, groups)`` matching the shape produced by
    :func:`detect_replicates`.
    """
    if not body:
        raise Exception("Design file is empty.")

    # Tab is the canonical separator; fall back to comma if the file has no
    # tabs (matches PaintOmics's auto-delimiter convention elsewhere).
    sep = "\t" if "\t" in body else ","

    column_to_sample = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(sep)]
        if len(parts) < 2:
            # Tolerate trailing empty lines / incomplete rows but skip them.
            continue
        col_name, sample_label = parts[0], parts[1]
        if not col_name:
            continue
        # Header detection: first row whose column-1 entry doesn't match any
        # actual column in the values-file header. We use the same heuristic
        # the MORE loader does — if it doesn't match, just skip it once.
        if col_name not in replicateHeader and not column_to_sample:
            continue
        if not sample_label:
            raise Exception("Design file: empty sample label for column '%s'." % col_name)
        column_to_sample[col_name] = sample_label

    # Sanity: every replicate column in the values file must have a label.
    missing = [c for c in replicateHeader if c not in column_to_sample]
    if missing:
        raise Exception(
            "Design file is missing entries for columns: %s" % ", ".join(missing[:10])
            + ("…" if len(missing) > 10 else "")
        )

    # Build sampleHeader in *file order* — the order the user wrote sample
    # labels in the design file. This lets users control how samples display
    # without reordering the values file.
    sampleHeader = []
    seen = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(sep)]
        if len(parts) < 2 or parts[0] not in column_to_sample:
            continue
        label = column_to_sample[parts[0]]
        if label not in seen:
            seen[label] = len(sampleHeader)
            sampleHeader.append(label)

    mapping = [seen[column_to_sample[c]] for c in replicateHeader]
    groups = [[] for _ in sampleHeader]
    for col_idx, s_idx in enumerate(mapping):
        groups[s_idx].append(col_idx)

    return sampleHeader, mapping, groups


def pathwayAcquisitionMetagenes_PART1(REQUEST, RESPONSE, QUEUE_INSTANCE, JOB_ID, ROOT_DIRECTORY):
        # ****************************************************************
        # Step 0. VARIABLE DECLARATION
        # The following variables are defined:
        #  - jobInstance: instance of the PathwayAcquisitionJob class.
        #                 Contains all the information for the current job.
        #  - userID: the ID for the user
        # ****************************************************************
        jobInstance = None
        userID = None

        try:
            # ****************************************************************
            # Step 1. CHECK IF VALID USER SESSION
            # ****************************************************************
            logging.info("STEP0 - CHECK IF VALID USER....")
            userID = REQUEST.cookies.get('userID')
            sessionToken = REQUEST.cookies.get('sessionToken')
            UserSessionManager().isValidUser(userID, sessionToken)

            # ****************************************************************
            # Step 2. LOAD THE JOB INSTANCE AND RETRIEVE FORM INFO
            # ****************************************************************
            savedJobID = REQUEST.form.get("jobID")
            savedJobInstance = loadRequestedJob(savedJobID, "generating clusters")

            if savedJobInstance.getReadOnly() and str(savedJobInstance.getUserID()) != str(userID):
                raise Exception("Invalid user for the job generating metagenes.")

            omicName = REQUEST.form.get("omic")
            clusterNumber = int(REQUEST.form.get("number"))
            database = REQUEST.form.get("database")

            # Make sure the number of clusters is inside [1, 20]
            clusterNumber = 1 if clusterNumber < 1 else 20 if clusterNumber > 20 else clusterNumber

            # ************************************************************************
            # Step 4. Queue job
            # ************************************************************************
            QUEUE_INSTANCE.enqueue(
                fn=pathwayAcquisitionMetagenes_PART2,
                args=(ROOT_DIRECTORY, userID, savedJobInstance, omicName, clusterNumber, database, RESPONSE),
                timeout=600,
                job_id=JOB_ID
            )

            # ************************************************************************
            # Step 5. Return the Job ID
            # ************************************************************************
            RESPONSE.setContent({
                "success": True,
                "jobID": JOB_ID
            })
        except Exception as ex:
            handleException(RESPONSE, ex, __file__, "pathwayAcquisitionMetagenes_PART1", userID=userID)
        finally:
            return RESPONSE

def pathwayAcquisitionMetagenes_PART2(ROOT_DIRECTORY, userID, savedJobInstance, omicName, clusterNumber, database, RESPONSE):
    #VARIABLE DECLARATION
    jobID  = ""
    userID = ""

    try :
        #************************************************************************
        # Step 3. Save the visual Options in the MongoDB
        #************************************************************************
        logging.info("UPDATE METAGENES - STEP 2 FOR JOB " + jobID + "..." )
        savedJobInstance.generateMetagenesList(ROOT_DIRECTORY, {omicName: clusterNumber}, [omicName], [database])
        logging.info("UPDATE METAGENES - STEP 2 FOR JOB " + jobID + "...DONE")
        JobInformationManager().storePathways(savedJobInstance)

        matchedPathwaysJSONList = []
        for matchedPathway in savedJobInstance.getMatchedPathways().values():
            logging.info("match_pathway:"+str(matchedPathway))
            matchedPathwaysJSONList.append(matchedPathway.toBSON())

        RESPONSE.setContent({
            "success": True,
            "jobID": jobID,
            # "timestamp": newTimestamp,
            "pathwaysInfo": matchedPathwaysJSONList
        })
        logging.info("matchedPathwaysJSONList:"+str(matchedPathwaysJSONList))

    except Exception as ex:
        handleException(RESPONSE, ex, __file__ , "pathwayAcquisitionMetagenes_PART2", userID=userID)
    finally:
        savedJobInstance.cleanDirectories()

        return RESPONSE

def pathwayAcquisitionAdjustPvalues(request, response):
    try:
        #****************************************************************
        # Step 1.GET THE INFO
        #****************************************************************
        formFields = request.get_json() #request.form

        # List of pathway => {pvalues}
        pvalues = formFields.get("pValues")

        # Check what kind of p-value we want to update
        if "stoufferWeights" in formFields:
            newStoufferWeights = formFields.get("stoufferWeights")
            visiblePathways = formFields.get("visiblePathways")

            newStoufferPvalues = defaultdict(dict)
            newAdjustedStoufferPvalues = defaultdict(dict)

            # Iterate over each database (adjusting it independently)
            for db_name, db_pvalues in pvalues.items():
                # Each pathway has a different set of matching omics and thus, Stouffer weights.
                # The new Stouffer p-value will be computed for each pathway, even those that are currently hidden.
                for pathway_id, pathway_pvalues in db_pvalues.items():
                    # Select those with a proper p-value number and present in Stouffer weights
                    valid_pvalues = {omic: pvalue for omic, pvalue in pathway_pvalues.items() if pvalue != "-" and omic in newStoufferWeights.keys()}

                    # Make sure to pass the Stouffer weights in the same order as the p-values
                    newStoufferValue = calculateStoufferCombinedPvalue(valid_pvalues.values(), [newStoufferWeights[omicName] for omicName in valid_pvalues.keys()])

                    newStoufferPvalues[db_name][pathway_id] = newStoufferValue

                # Adjust the new Stouffer p-values passing only those pathways that are currently visible
                newAdjustedStoufferPvalues[db_name] = adjustPvalues({pathway: pvalue for pathway, pvalue in newStoufferPvalues[db_name].items() if pathway in visiblePathways})

            response.setContent({
                "success": True,
                "stoufferPvalues": newStoufferPvalues,
                "adjustedStoufferPvalues": newAdjustedStoufferPvalues
            })
        else:

            # No new stouffer weights, just recalculate the provided p-values

            # Iterate over each database (adjusting it independently)
            adjustedPvaluesByOmic = defaultdict()

            for db_name, db_pvalues in pvalues.items():
                pvaluesByOmic = defaultdict(dict)

                for pathway, pathwayPvalues in db_pvalues.items():
                    for omic, omicPvalue in pathwayPvalues.items():
                        # Skip those in which there is no pValue (no matching in the pathway for that omic)
                        if omicPvalue != '-':
                            pvaluesByOmic[omic][pathway] = omicPvalue

                adjustedPvaluesByOmic[db_name] = {omic: adjustPvalues(omic_pvalues) for omic, omic_pvalues in pvaluesByOmic.items()}

            response.setContent({
                "success": True,
                "adjustedPvalues": adjustedPvaluesByOmic
            })

    except Exception as ex:
        handleException(response, ex, __file__ , "pathwayAcquisitionAdjustPvalues")
    finally:
        return response
