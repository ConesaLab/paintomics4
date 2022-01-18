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
from src.classes.JobInstances.PathwayAcquisitionJob import PathwayAcquisitionJob

from src.conf.serverconf import CLIENT_TMP_DIR, KEGG_DATA_DIR
from src.conf.organismDB import dicDatabases
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

            logging.info("STEP1 - READING FILES....")
            JobInformationManager().saveFiles(uploadedFiles, formFields, userID, jobInstance, CLIENT_TMP_DIR)
            logging.info("STEP1 - READING FILES....DONE")

        elif exampleMode == "example":
            #****************************************************************
            # Step 2.SAVE THE UPLOADED FILES
            #****************************************************************
            logging.info("STEP1 - EXAMPLE MODE SELECTED")
            logging.info("STEP1 - COPYING FILES....")

            exampleOmics = {"Gene expression": 'genes', "Metabolomics": 'features', "Proteomics": 'features', "miRNA-seq": 'genes', "DNase-seq": 'genes'}
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

        #************************************************************************
        # Step 3. Queue job
        #************************************************************************
        QUEUE_INSTANCE.enqueue(
            fn=pathwayAcquisitionStep2_PART2,
            args=(jobID, userID, selectedCompounds, clusterNumber, RESPONSE, ROOT_DIRECTORY,),
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

def pathwayAcquisitionStep2_PART2(jobID, userID, selectedCompounds, clusterNumber, RESPONSE, ROOT_DIRECTORY):
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



        logging.info("STEP2 - GENERATE COMPOUND CLASSIFICATION")

        if selectedCompounds:
            mappingComp, pValueInDict, classificationDict, exprssionMetabolites, adjustPvalue, totalRelevantFeaturesInCategory, featureSummary, compoundRegulateFeatures = jobInstance.compundsClassification()
            # Creat Global expression information for all genes
            globalExpressionData = jobInstance.getGlobalExpressionData()
            hubAnalysisResult = jobInstance.hubAnalysis( ROOT_DIRECTORY )


        #****************************************************************
        # Step 2. GENERATING PATHWAYS INFORMATION
        #****************************************************************
        logging.info("STEP2 - GENERATING PATHWAYS INFORMATION...")
        summary = jobInstance.generatePathwaysList()
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
        matchedPathwaysJSONList = []
        for matchedPathway in jobInstance.getMatchedPathways().values():
            matchedPathwaysJSONList.append(matchedPathway.toBSON())

        matchedClassJSONList = []
        for matchedclass in jobInstance.getMatchedClass().values():
            matchedClassJSONList.append(matchedclass.toBSON())

        if selectedCompounds:
            RESPONSE.setContent({
                "success": True,
                "organism" : jobInstance.getOrganism(),
                "jobID":jobInstance.getJobID(),
                "summary" : summary,
                "pathwaysInfo" : matchedPathwaysJSONList,
                # PaintOmics 4
                "classInfo": matchedClassJSONList,
                "geneBasedInputOmics":jobInstance.getGeneBasedInputOmics(),
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
                "timestamp": int(time())
            })
        else:
            RESPONSE.setContent( {
                "success": True,
                "organism": jobInstance.getOrganism(),
                "jobID": jobInstance.getJobID(),
                "summary": summary,
                "pathwaysInfo": matchedPathwaysJSONList,
                # PaintOmics 4
                "classInfo": matchedClassJSONList,
                "geneBasedInputOmics": jobInstance.getGeneBasedInputOmics(),
                "compoundBasedInputOmics": jobInstance.getCompoundBasedInputOmics(),
                "databases": jobInstance.getDatabases(),
                "omicsValuesID": jobInstance.getValueIdTable(),
                # Add classification metabolism
                "mappingComp": None,
                "pValueInDict": None,
                "classificationDict": None,
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

        logging.info("STEP3 - LOADING JOB " + jobID + "...")

        jobInstance = JobInformationManager().loadJobInstance(jobID)

        if(jobInstance == None):
            raise UserWarning("Job " + jobID + " was not found at database.")

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
                    "mappingComp": jobInstance.mappingComp,
                    "classificationDict": jobInstance.classificationDict,
                    "pValueInDict": jobInstance.pValueInDict,
                    "exprssionMetabolites": jobInstance.exprssionMetabolites,
                    "adjustPvalue": jobInstance.adjustPvalue,
                    "totalRelevantFeaturesInCategory": jobInstance.totalRelevantFeaturesInCategory,
                    "featureSummary":jobInstance.featureSummary,
                    # Add compound regulate features
                    "compoundRegulateFeatures": jobInstance.compoundRegulateFeatures,
                    # Add global gene expression information
                    "globalExpressionData":jobInstance.getGlobalExpressionData(),
                    # Add hub analysis result
                    'hubAnalysisResult': jobInstance.hubAnalysisResult,
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
                    "omicsValuesID": jobInstance.getValueIdTable()
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
        jobInstance = JobInformationManager().loadJobInstance(jobID)

        svgData = request.form.get("svgCode")
        fileName = "paintomics_" + request.form.get("fileName").replace(" ", "_").replace("/", "_") + "_" + jobID
        fileFormat = request.form.get("format")

        # userID = jobInstance.getUserID()
        # userDirID = userID if userID is not None else "nologin"
        # path = CLIENT_TMP_DIR + userDirID + jobInstance.getOutputDir().replace(CLIENT_TMP_DIR + userDirID, "")
        path = jobInstance.getOutputDir()
        logging.info("The path is xxx: " + path)

        if(fileFormat == "png"):
            def createImage(svgData):
                cairosvg.svg2png(bytestring=svgData, write_to=path + fileName + "." + fileFormat)
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

        jobInstance = JobInformationManager().loadJobInstance(jobID)

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
        jobInstance = JobInformationManager().loadJobInstance(jobID)

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
            savedJobInstance = JobInformationManager().loadJobInstance(savedJobID)

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