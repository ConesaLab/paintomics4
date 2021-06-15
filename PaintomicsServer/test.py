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



print("STEP0 - CHECK IF VALID USER....")
#****************************************************************
# Step 2. CREATE THE NEW INSTANCE OF JOB
#****************************************************************
JOB_ID = "test321"
userID = "admin"
jobInstance = PathwayAcquisitionJob(JOB_ID, userID, CLIENT_TMP_DIR)
jobInstance.initializeDirectories()
print("STEP1 - NEW JOB SUBMITTED " + jobInstance.getJobID())

logging.info("STEP1 - EXAMPLE MODE SELECTED")

EXAMPLE_FILES_DIR = '/home/tian/Desktop/git/paintomics3/PaintomicsServer/src/examplefiles/'
logging.info("STEP1 - COPYING FILES....")

exampleOmics = {"Gene expression": 'genes', "Metabolomics": 'features', "Proteomics": 'features', "miRNA-seq": 'genes', "DNase-seq": 'genes'}
for omicName, enrichment in exampleOmics.items():
    dataFileName = omicName.replace(" ", "_").replace("-seq", "").lower() + "_values.tab"
    logging.info("STEP1 - USING ALREADY SUBMITTED FILE (data file) " + EXAMPLE_FILES_DIR + dataFileName + " FOR  " + omicName)

    relevantFileName = omicName.replace(" ", "_").replace("-seq", "").lower() + "_relevant.tab"
    logging.info("STEP1 - USING ALREADY SUBMITTED FILE (relevant features file) " + EXAMPLE_FILES_DIR + relevantFileName + " FOR  " + omicName)

    if(["Metabolomics"].count(omicName)):
        jobInstance.addCompoundBasedInputOmic({"omicName": omicName, "inputDataFile": EXAMPLE_FILES_DIR + dataFileName, "relevantFeaturesFile": EXAMPLE_FILES_DIR + relevantFileName, "isExample" : True, "enrichment": enrichment})
    else:
        jobInstance.addGeneBasedInputOmic({"omicName": omicName, "inputDataFile": EXAMPLE_FILES_DIR + dataFileName, "relevantFeaturesFile": EXAMPLE_FILES_DIR + relevantFileName,  "isExample" : True, "enrichment": enrichment})

specie = "mmu"
jobInstance.setOrganism(specie)
jobInstance.setDatabases(['KEGG', "Reactome"]) # TODO: cambiar



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
exampleMode = "example"
jobInstance.getJobDescription(True, exampleMode == "example")
JobInformationManager().storeJobInstance(jobInstance, 1)
logging.info("STEP1 - SAVING JOB DATA...DONE" )

jobInstance.cleanDirectories()




logging.info("STEP2 - LOADING JOB " + JOB_ID + "...")
jobInstance = JobInformationManager().loadJobInstance(JOB_ID)

if(jobInstance == None):
    raise UserWarning("Job " + JOB_ID + " was not found at database.")

jobInstance.setDirectories(CLIENT_TMP_DIR)
jobInstance.initializeDirectories()

logging.info("STEP2 - JOB " + jobInstance.getJobID() + " LOADED SUCCESSFULLY.")

#****************************************************************
# Step 1.READ THE SELECTED METABOLITES
#****************************************************************
logging.info("STEP2 - UPDATING SELECTED COMPOUNDS LIST...")
#TODO: CHANGE THIS TO ALLOW BACK
logging.info("STEP2 - UPDATING SELECTED COMPOUNDS LIST...DONE")

#****************************************************************
# Step 2. GENERATING PATHWAYS INFORMATION
#****************************************************************
logging.info("STEP2 - GENERATING PATHWAYS INFORMATION...")
summary = jobInstance.generatePathwaysList()
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



































