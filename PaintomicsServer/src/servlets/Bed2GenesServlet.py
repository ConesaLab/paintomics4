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
#  Technical contact paintomics@cipf.es
#**************************************************************
import logging
import logging.config

from src.classes.JobInstances.Bed2GeneJob import Bed2GeneJob
from src.common.UserSessionManager import UserSessionManager
from src.common.JobInformationManager import JobInformationManager
from src.common.ServerErrorManager import handleException

from src.conf.serverconf import CLIENT_TMP_DIR

def fromBEDtoGenes_STEP1(REQUEST, RESPONSE, QUEUE_INSTANCE, JOB_ID, EXAMPLE_FILES_DIR, exampleMode=False):
    """
    This function corresponds to FIRST PART of the FIRST step in the Bed2Genes process.
    First, it takes a Request object which contains the fields of the form that started the process.
    This is a summary for the steps in the process:
        Step 0. VARIABLE DECLARATION
        Step 1. CHECK IF VALID USER SESSION
        Step 2. CREATE THE NEW INSTANCE OF JOB
        Step 3. SAVE THE UPLOADED FILES
        Step 4. READ PARAMS
        Step 5. QUEUE THE JOB INSTANCE
        Step 6. RETURN THE NEW JOB ID

    @param {Request} REQUEST
    @param {Response} RESPONSE
    @param {RQ QUEUE} QUEUE_INSTANCE
    @param {String} JOB_ID
    @param {Boolean} exampleMode
    @returns Response
    """
    #TODO: ALLOWED_EXTENSIONS http://flask.pocoo.org/docs/0.10/patterns/fileuploads/
    #TODO: secure_filename
    #****************************************************************
    #Step 0. VARIABLE DECLARATION
    #The following variables are defined:
    #  - jobInstance: instance of the Bed2GeneJob class. Contains all the information for the current job.
    #  - userID: the ID for the user
    #****************************************************************
    jobInstance = None
    userID= None

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
        jobInstance = Bed2GeneJob(JOB_ID, userID, CLIENT_TMP_DIR)
        jobInstance.initializeDirectories()
        logging.info("STEP1 - NEW JOB SUBMITTED " + jobInstance.getJobID())

        #****************************************************************
        # Step 3. SAVE THE UPLOADED FILES
        #****************************************************************
        formFields   = REQUEST.form

        if(exampleMode == False):
            logging.info("STEP1 - FILE UPLOADING REQUEST RECEIVED")
            uploadedFiles  = REQUEST.files

            logging.info("STEP1 - READING FILES....")
            JobInformationManager().saveFiles(uploadedFiles, formFields, userID, jobInstance, CLIENT_TMP_DIR,  EXAMPLE_FILES_DIR)
            logging.info("STEP1 - READING FILES....DONE")

        elif(exampleMode == "example"):
            #****************************************************************
            # Step 2.SAVE THE UPLOADED FILES
            #****************************************************************
            logging.info("STEP1 - EXAMPLE MODE SELECTED")
            logging.info("STEP1 - COPYING FILES....")

            exampleOmics = ["DNase unmapped"]
            for omicName in exampleOmics:
                dataFileName = omicName.replace(" ", "_").lower() + "_values.tab"
                logging.info("STEP1 - USING ALREADY SUBMITTED FILE (data file) " + EXAMPLE_FILES_DIR + dataFileName + " FOR  " + omicName)
                relevantFileName =omicName.replace(" ", "_").lower() + "_relevant.tab"
                logging.info("STEP1 - USING ALREADY SUBMITTED FILE (relevant features file) " + EXAMPLE_FILES_DIR + relevantFileName + " FOR  " + omicName)

                jobInstance.addGeneBasedInputOmic({"omicName": omicName, "inputDataFile": EXAMPLE_FILES_DIR + dataFileName, "relevantFeaturesFile": EXAMPLE_FILES_DIR + relevantFileName,  "isExample" : True})

                jobInstance.addReferenceInput({"omicName": omicName, "fileType":  "Reference file", "inputDataFile": EXAMPLE_FILES_DIR + "GTF/sorted_mmu.gtf"})

            specie = "mmu"
            jobInstance.setOrganism(specie)
        else:
            raise NotImplementedError

        #****************************************************************
        # Step 4. READ PARAMS
        #****************************************************************
        namePrefix = formFields.get("name_prefix")
        logging.info("STEP2 - INPUT VALUES ARE:")
        jobInstance.omicName= formFields.get(namePrefix + "_omic_name", "DNase-seq")
        logging.info("  - omicName             :" + jobInstance.omicName)
        jobInstance.presortedGTF= formFields.get(namePrefix + "_presortedGTF", False)
        logging.info("  - presortedGTF         :" + str(jobInstance.presortedGTF))
        jobInstance.report= formFields.get(namePrefix + "_report", "gene")
        logging.info("  - report               :" + jobInstance.report)
        jobInstance.distance= formFields.get(namePrefix + "_distance", 10)
        logging.info("  - distance             :" + str(jobInstance.distance))
        jobInstance.tss= formFields.get(namePrefix + "_tss", 200)
        logging.info("  - tss                  :" + str(jobInstance.tss))
        jobInstance.promoter= formFields.get(namePrefix + "_promoter", 1300)
        logging.info("  - promoter             :" + str(jobInstance.promoter))
        jobInstance.geneAreaPercentage= formFields.get(namePrefix + "_geneAreaPercentage", 90)
        logging.info("  - geneAreaPercentage   :" + str(jobInstance.geneAreaPercentage))
        jobInstance.regionAreaPercentage= formFields.get(namePrefix + "_regionAreaPercentage", 50)
        logging.info("  - regionAreaPercentage :" + str(jobInstance.regionAreaPercentage))
        jobInstance.ignoreMissing = True if namePrefix + "_ignoremissing" in formFields.keys() else False
        logging.info("  - ignore missing       :" + str(jobInstance.ignoreMissing))
        jobInstance.enrichment = formFields.get(namePrefix + "_enrichment_pre", 'genes')
        logging.info("  - Enrichment   :" + str(jobInstance.enrichment))

        #rules
        jobInstance.geneIDtag= formFields.get(namePrefix + "_geneIDtag", "gene_id")
        logging.info("  - geneIDtag            :" + str(jobInstance.geneIDtag))
        jobInstance.summarizationMethod= formFields.get(namePrefix + "_summarization_method", "mean")
        logging.info("  - summarization_method :" + jobInstance.summarizationMethod)
        jobInstance.reportRegions= formFields.getlist(namePrefix + "_reportRegions")
        if len(jobInstance.reportRegions) == 0:
            jobInstance.reportRegions = ["all"]
        logging.info("  - reportRegions :" + str(jobInstance.reportRegions))


        #************************************************************************
        # Step 4. Queue job
        #************************************************************************
        QUEUE_INSTANCE.enqueue(
            fn=fromBEDtoGenes_STEP2,
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
        handleException(RESPONSE, ex, __file__ , "fromBEDtoGenes_STEP1")
    finally:
        return RESPONSE



def fromBEDtoGenes_STEP2(jobInstance, userID, exampleMode, RESPONSE):
    """
    This function corresponds to SECOND PART of the FIRST step in the Bed2Genes process.
    Given a JOB INSTANCE, first executes the Bed2Gene function (map regions to genes)
    and finally generates the response.
    This code is executed at the PyQlite Queue.

    This is a summarization for the steps in the process:
        Step 1. PROCESS THE FILES DATA
        Step 2. SAVE THE JOB INSTANCE AT THE DATABASE
        Step 3. GENERATE RESPONSE AND FINISH

    @param {Bed2GeneJob} jobInstance
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
        logging.info("STEP1 - Executing Bed2Gene function...")
        fileNames=jobInstance.fromBED2Genes()
        logging.info("STEP1 - Executing Bed2Gene function... DONE")

        #************************************************************************
        # Step 2. Save the jobInstance in the MongoDB
        #************************************************************************
        logging.info("STEP1 - SAVING JOB DATA..." )
        JobInformationManager().storeJobInstance(jobInstance, 1)
        #TODO: JOB DESCRIPTION?
        logging.info("STEP1 - SAVING JOB DATA...DONE" )

        #************************************************************************
        # Step 3. Update the response content
        #************************************************************************
        RESPONSE.setContent({
            "success": True,
            "jobID":jobInstance.getJobID(),
            "compressedFileName": fileNames[0],
            "mainOutputFileName":  fileNames[1],
            "secondOutputFileName":  fileNames[2],
            "description": jobInstance.description,
            "enrichment": jobInstance.enrichment
        })

    except Exception as ex:
        #****************************************************************
        # DELETE JOB FROM USER DIRECTORY
        #****************************************************************
        jobInstance.cleanDirectories(remove_output=True)

        handleException(RESPONSE, ex, __file__ , "fromBEDtoGenes_STEP2")

    finally:
        return RESPONSE

