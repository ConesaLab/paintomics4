# ***************************************************************
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
# **************************************************************

import logging
import math
from os import path as os_path, system as os_system, makedirs as os_makedirs
from csv import reader as csv_reader
from zipfile import ZipFile as zipFile

from subprocess import check_call, call, STDOUT, CalledProcessError

from src.classes.FoundFeature import FoundFeature
from src.common.Util import unifyAndSort

from collections import defaultdict, Counter
from itertools import chain

from src.common.Statistics import calculateSignificance, calculateCombinedSignificancePvalues, adjustPvalues
from src.common.Util import chunks, getImageSize

from src.common.KeggInformationManager import KeggInformationManager

from src.classes.Job import Job
from src.classes.Feature import Gene, Compound
from src.classes.Pathway import Pathway
from src.classes.PathwayGraphicalData import PathwayGraphicalData

from src.conf.serverconf import KEGG_DATA_DIR, MAX_THREADS, MAX_WAIT_THREADS, MAX_NUMBER_FEATURES


class PathwayAcquisitionJob(Job):
    # ******************************************************************************************************************
    # CONSTRUCTORS
    # ******************************************************************************************************************
    def __init__(self, jobID, userID, CLIENT_TMP_DIR):
        super(PathwayAcquisitionJob, self).__init__(jobID, userID, CLIENT_TMP_DIR)
        # TODO: OPTION TO CHANGE THESE VALUES
        self.test = "fisher"
        self.combinedTest = "fisher-combined"
        self.summary = None
        # In this table we save all the matched pathways and for each pathways the associated selected compounds and genes.
        self.matchedPathways = {}
        self.foundCompounds = []

        # PaintOmics 4
        self.mappingComp = None
        self.pValueInDict = None
        self.classificationDict = None
        self.exprssionMetabolites = None
        self.adjustPvalue = None
        self.totalRelevantFeaturesInCategory = None
        self.featureSummary = None
        self.compoundRegulateFeatures = None

        self.globalExpressionData = None
        self.hubAnalysisResult = None

        self.matchedClass = {}

        #self.reactomeClass = defaultdict(set)
    # ******************************************************************************************************************
    # GETTERS AND SETTER
    # ******************************************************************************************************************
    def setCombinedTest(self, combinedTest):
        self.combinedTest = combinedTest

    def getCombinedTest(self):
        return self.combinedTest

    def setTest(self, test):
        self.test = test

    def getTest(self):
        return self.test

    #PaintOmics 4
    def setMatchedClass(self, matchedClass):
        self.matchedClass = matchedClass

    def getMatchedClass(self):
        return self.matchedClass

    #def setReactomeClass(self, reactomeClass):
    #    self.reactomeClass = reactomeClass

    #def getReactomeClass(self):
    #    return  self.reactomeClass

    def setMatchedPathways(self, matchedPathways):
        self.matchedPathways = matchedPathways

    def getMatchedPathways(self):
        return self.matchedPathways

    def addMatchedPathway(self, matchedPathway):
        self.matchedPathways[matchedPathway.getID()] = matchedPathway

    def addFoundCompound(self, foundCompound):
        self.foundCompounds.append(foundCompound)

    def getFoundCompounds(self):
        return self.foundCompounds

    def getJobDescription(self, generate=False, isExampleJob=False):
        if generate:
            if isExampleJob:
                self.description = "Example Job;"
            from os.path import basename

            self.description += "Input data:;"

            # The client requires to have the config options inside double square brackets and separated by '!!'.
            # The different omics must use ';' as separator, and the mainFile/relevantFiles should be inside the same
            # simple square brackets, separated by '!!'.
            for omicAux in self.geneBasedInputOmics:
                omic_files = [basename(omicAux.get("inputDataFile"))]

                self.description += omicAux.get("omicName")

                if omicAux.get("relevantFeaturesFile"):
                    omic_files.append(basename(omicAux.get("relevantFeaturesFile")))

                if omicAux.get("configOptions"):
                    self.description += " [[" + omicAux.get("configOptions").replace(";", "!!") + "]] "

                self.description += " [" + '!!'.join(omic_files) + "]; "
            for omicAux in self.compoundBasedInputOmics:
                self.description += omicAux.get("omicName") + " [" + basename(omicAux.get("inputDataFile")) + "]; "

        return self.description

    def getMappedRatios(self):
        # Calculate the mapped/unmapped ratio of each omic
        mapped_ratios = {}

        for genericOmic in self.getGeneBasedInputOmics() + self.getCompoundBasedInputOmics():
            omicSummary = genericOmic.get("omicSummary")

            # First position: dictionary with identifiers.
            # With multiple databases "Total" is the maximum
            # Compounds omics only have one value (no dict)
            totalMapped = omicSummary[0].get("Total", list(omicSummary[0].values())[0]) if not isinstance(
                omicSummary[0], (int)) else omicSummary[0]

            # Second position: considering total if it exists
            totalUnmapped = omicSummary[1]

            try:
                mapped_ratios[genericOmic.get("omicName")] = float(totalMapped) / float(totalMapped + totalUnmapped)
            except ZeroDivisionError as e:
                mapped_ratios[genericOmic.get("omicName")] = 0

        return mapped_ratios

    # ******************************************************************************************************************
    # OTHER FUNCTIONS
    # ******************************************************************************************************************

    # VALIDATION FUNCTIONS  ----------------------------------------------------------------------------------------------------
    def validateInput(self):
        """
        This function check the content for files and returns an error message in case of invalid content

        @returns True if not error
        """
        error = ""

        nConditions = -1

        logging.info("VALIDATING GENE BASED FILES...")
        for inputOmic in self.geneBasedInputOmics:
            nConditions, error = self.validateFile(inputOmic, nConditions, error)

        logging.info("VALIDATING COMPOUND BASED FILES...")
        for inputOmic in self.compoundBasedInputOmics:
            nConditions, error = self.validateFile(inputOmic, nConditions, error)

        if error != "":
            logging.info("VALIDATING ERRORS. RAISING EXCEPTION. Error: " + error)
            raise Exception(
                "[b]Errors detected in input files, please fix the following issues and try again:[/b][br]" + error)

        return True

    def validateFile(self, inputOmic, nConditions, error):
        """
        This function...

        @param {type}
        @returns
        """
        valuesFileName = inputOmic.get("inputDataFile")
        relevantFileName = inputOmic.get("relevantFeaturesFile", "")
        associationsFileName = inputOmic.get("associationsFile", "")
        relevantAssociationsFileName = inputOmic.get("relevantAssociationsFile", "")
        omicName = inputOmic.get("omicName")

        if inputOmic.get("isExample", False):
            return nConditions, error
        else:
            valuesFileName = "{path}/{file}".format(path=self.getInputDir(), file=valuesFileName)
            relevantFileName = "{path}/{file}".format(path=self.getInputDir(), file=relevantFileName)
            associationsFileName = "{path}/{file}".format(path=self.getInputDir(), file=associationsFileName)
            relevantAssociationsFileName = "{path}/{file}".format(path=self.getInputDir(),
                                                                  file=relevantAssociationsFileName)

        # *************************************************************************
        # STEP 1. VALIDATE THE ASSOCIATIONS AND RELEVANT ASSOCIATIONS FILES
        # *************************************************************************
        logging.info("VALIDATING ASSOCIATION FILE (" + omicName + ")...")
        if os_path.isfile(associationsFileName):
            nLine = -1
            with open(associationsFileName, 'rU') as associationDataFile:
                for line in csv_reader(associationDataFile, delimiter="\t"):
                    nLine = nLine + 1

                    if nLine > MAX_NUMBER_FEATURES:
                        error += " - Errors detected while processing " + inputOmic.get("associationsFile", "") + \
                                 ": The file exceeds the maximum number of features allowed (" + str(
                            MAX_NUMBER_FEATURES) + ")." + "\n"
                        break

                    if len(line) != 2:
                        error += " - Errors detected while processing " + inputOmic.get("associationsFile",
                                                                                        "") + ": The file does not look like an associations file (some lines do not have 2 columns)." + "\n"
                        break

        logging.info("VALIDATING RELEVANT ASSOCIATION FILE (" + omicName + ")...")
        if os_path.isfile(relevantAssociationsFileName):
            nLine = -1
            with open(relevantAssociationsFileName, 'rU') as relevantAssociationDataFile:
                for line in csv_reader(relevantAssociationDataFile, delimiter="\t"):
                    nLine = nLine + 1

                    if nLine > MAX_NUMBER_FEATURES:
                        error += " - Errors detected while processing " + inputOmic.get("relevantAssociationsFile",
                                                                                        "") + \
                                 ": The file exceeds the maximum number of features allowed (" + str(
                            MAX_NUMBER_FEATURES) + ")." + "\n"
                        break

                    if len(line) != 2:
                        error += " - Errors detected while processing " + inputOmic.get("relevantAssociationsFile",
                                                                                        "") + ": The file does not look like a relevant associations file (some lines do not have 2 columns)." + "\n"
                        break

        # *************************************************************************
        # STEP 1. VALIDATE THE RELEVANT FEATURES FILE
        # *************************************************************************
        logging.info("VALIDATING RELEVANT FEATURES FILE (" + omicName + ")...")
        if os_path.isfile(relevantFileName):
            f = open(relevantFileName, 'rU')
            lines = f.readlines()

            # Ensure that relevant features files does not exceed the max number of features
            if len(lines) > MAX_NUMBER_FEATURES:
                error += " - Errors detected while processing " + inputOmic.get("relevantFeaturesFile",
                                                                                "") + ": The file exceeds the maximum number of features allowed (" + str(
                    MAX_NUMBER_FEATURES) + ")." + "\n"
            else:
                for line in lines:
                    if len(line) > 80:
                        error += " - Errors detected while processing " + inputOmic.get("relevantFeaturesFile",
                                                                                        "") + ": The file does not look like a Relevant Features file (some lines are longer than 80 characters)." + "\n"
                        break
            f.close()

        # *************************************************************************
        # STEP 2. VALIDATE THE VALUES FILE
        # *************************************************************************
        logging.info("VALIDATING VALUES FILE (" + omicName + ")...")

        # IF THE USER UPLOADED VALUES FOR GENE EXPRESSION
        if os_path.isfile(valuesFileName):
            with open(valuesFileName, 'rU') as inputDataFile:
                nLine = -1
                erroneousLines = {}

                for line in csv_reader(inputDataFile, delimiter="\t"):
                    nLine = nLine + 1
                    # TODO: HACER ALGO CON EL HEADER?
                    # *************************************************************************
                    # STEP 2.1 CHECK IF IT IS HEADER, IF SO, IGNORE LINE
                    # *************************************************************************
                    if nLine == 0:
                        try:
                            float(line[1])
                        except Exception:
                            continue

                    if nConditions == -1:
                        if len(line) < 2:
                            erroneousLines[nLine] = "Expected at least 2 columns, but found one."
                            break
                        nConditions = len(line)

                    # *************************************************************************
                    # STEP 2.2 CHECK IF IT EXCEEDS THE MAX NUMBER OF FEATURES ALLOWED
                    # *************************************************************************
                    if nLine > MAX_NUMBER_FEATURES:
                        error += " - Errors detected while processing " + inputOmic.get("inputDataFile", "") + \
                                 ": The file exceeds the maximum number of features allowed (" + str(
                            MAX_NUMBER_FEATURES) + ")." + "\n"
                        break

                    # **************************************************************************************
                    # STEP 2.3 IF LINE LENGTH DOES NOT MATCH WITH EXPECTED NUMBER OF CONDITIONS, ADD ERROR
                    # **************************************************************************************
                    if nConditions != len(line) and len(line) > 0:
                        erroneousLines[nLine] = "Expected " + str(nConditions) + " columns but found " + str(
                            len(line)) + ";"

                    # **************************************************************************************
                    # STEP 2.4 IF CONTAINS NOT VALID VALUES, ADD ERROR
                    # **************************************************************************************
                    try:
                        list(map(float, line[1:len(line)]))
                    except:
                        if " ".join(line[1:len(line)]).count(",") > 0:
                            erroneousLines[nLine] = erroneousLines.get(nLine,
                                                                       "") + "Perhaps you are using commas instead of dots as decimal mark?"
                        else:
                            erroneousLines[nLine] = erroneousLines.get(nLine,
                                                                       "") + "Line contains invalid values or symbols."

                    if len(erroneousLines) > 9:
                        break

            inputDataFile.close()

            # *************************************************************************
            # STEP 3. CHECK THE ERRORS AND RETURN
            # *************************************************************************
            if len(erroneousLines) > 0:
                error += "Errors detected while processing " + inputOmic.get("inputDataFile") + ":\n"
                error += "[ul]"
                for k in sorted(erroneousLines.keys()):
                    error += "[li]Line " + str(k) + ":" + erroneousLines.get(k) + "[/li]"
                error += "[/ul]"

                if len(erroneousLines) > 9:
                    error += "Too many errors detected while processing " + inputOmic.get(
                        "inputDataFile") + ", skipping remaining lines...\n"
            elif nLine < 1:
                error += "The file " + inputOmic.get(
                    "inputDataFile") + " <b>does not seem to have any feature lines</b>. Maybe the association process returned empty files, check the files and configuration options just in case."

        else:
            error += " - Error while processing " + omicName + ": File " + inputOmic.get(
                "inputDataFile") + "not found.\n"

        return nConditions, error

    def processFilesContent(self):
        """
        This function processes all the files and returns a checkboxes list to show to the user

        @returns list of matched Metabolites
        """
        if not os_path.exists(self.getTemporalDir()):
            os_makedirs(self.getTemporalDir())

        omicSummary = None

        logging.info("CREATING THE TEMPORAL CACHE FOR JOB " + self.getJobID() + "...")
        KeggInformationManager().createTranslationCache(self.getJobID())

        try:
            logging.info("PROCESSING GENE BASED FILES...")
            for inputOmic in self.geneBasedInputOmics:
                [omicName, omicSummary, omicHeader] = self.parseGeneBasedFiles(inputOmic)
                logging.info("   * PROCESSED " + omicName + "...")
                inputOmic["omicSummary"] = omicSummary
                inputOmic["omicHeader"] = omicHeader
            logging.info("PROCESSING GENE BASED FILES...DONE")

            logging.info("PROCESSING COMPOUND BASED FILES...")
            checkBoxesData = []
            for inputOmic in self.compoundBasedInputOmics:
                [omicName, checkBoxesData, omicSummary, omicHeader] = self.parseCompoundBasedFile(inputOmic,
                                                                                                  checkBoxesData)
                logging.info("   * PROCESSED " + omicName + "...")
                inputOmic["omicSummary"] = omicSummary
                inputOmic["omicHeader"] = omicHeader
            # REMOVE REPETITIONS AND ORDER ALPHABETICALLY
            # checkBoxesData = unifyAndSort(checkBoxesData, lambda checkBoxData: checkBoxData["title"].lower())
            checkBoxesData = unifyAndSort(checkBoxesData, lambda checkBoxData: checkBoxData.getTitle().lower())

            logging.info("PROCESSING COMPOUND BASED FILES...DONE")

            # GENERATE THE COMPRESSED FILE WITH MATCHING, COPY THE FILE AT RESULTS DIR AND CLEAN TEMPORAL FILES
            # COMPRESS THE RESULTING FILES AND CLEAN TEMPORAL DATA
            # TODO: MOVE THIS CODE TO JOBINFORMATIONMANAGER
            logging.info("COMPRESSING RESULTS...")
            fileName = "mapping_results_" + self.getJobID()
            logging.info("OUTPUT FILES IS " + self.getOutputDir() + fileName)
            logging.info("TEMPORAL DIR IS " + self.getTemporalDir() + "/")

            self.compressDirectory(self.getOutputDir() + fileName, "zip", self.getTemporalDir() + "/")

            logging.info("COMPRESSING RESULTS...DONE")

            # Save the metabolites matching data to allow recovering the job
            self.foundCompounds = checkBoxesData

            return checkBoxesData

        except Exception as ex:
            raise ex
        finally:
            logging.info("REMOVING THE TEMPORAL CACHE FOR JOB " + self.getJobID() + "...")
            KeggInformationManager().clearTranslationCache(self.getJobID())

    # GENERATE PATHWAYS LIST FUNCTIONS -----------------------------------------------------------------------------------------
    def updateSubmitedCompoundsList(self, selectedCompounds):
        """
        This function is used to generate the final list of selected compounds

        @param selectedCompounds, list of selected compounds in format originalName#comopundCode
        """

        # 1. GET THE PREVIOUS COMPOUND TABLE
        initialCompounds = self.getInputCompoundsData()

        # 2. CLEAN THE COMPOUNDS TABLE FOR THE JOB INSTANCE
        self.setInputCompoundsData({})

        # 3. FOR EACH SELECTED COMPOUND
        #   The input includes the ID for the selected compound followed by the name
        #   this is important because some compounds could appear in several boxes with different name (but same ID)
        #   and we need to distinguish which one the user selected
        #   e.g. C00075#Uridine 5'-triphosphate, Uridine triphosphate
        #   e.g. C00075#UTP
        mappedCompounds = set()
        compoundID = compoundName = initialCompound = newCompound = None
        for selectedCompound in selectedCompounds:
            selectedCompound = selectedCompound.split("#")
            compoundID = selectedCompound[0]
            compoundName = selectedCompound[1]
            originalName = selectedCompound[2]
            initialCompound = initialCompounds.get(compoundID)
            newCompound = self.getInputCompoundsData().get(compoundID, None)

            if initialCompound is None:
                continue
            # If there is not any entry for the current compound yet, add a new empty compound
            if newCompound is None:
                newCompound = initialCompound.clone()
                newCompound.setOmicsValues([])  # Clean the entry
                self.addInputCompoundData(newCompound)

            # TODO: this could ignore multiple values of different omics types for the same feature
            for i in sorted(range(len(initialCompound.omicsValues)), reverse=True):
                omicValue = initialCompound.omicsValues[i]
                # Add the omic value name (original feature) to the list
                mappedCompounds.add(omicValue.getOriginalName())

                if omicValue.inputName in compoundName.split(
                        ", ") and omicValue.originalName.lower() == originalName.lower():  # Some compounds can have combined names, separated by commas
                    newCompound.addOmicValue(omicValue)
                    del initialCompound.omicsValues[i]
            #
            #
            # for compoundID in selectedCompound:
            #     compoundName = compoundID.split
            #     self.addInputCompoundData(initialCompounds.get(compoundID))

            # initialCompoundName = selectedCompound.split("#")[0]
            # selectedCompoundID= selectedCompound.split("#")[1]

            # 4. CLONE THE ORIGINAL COMPOUND, SET THE ID AND THE NAME (GET NAME COMPOUND USING KEGGINFOMANAGER)
            # compoundAux = initialCompounds.get(initialCompoundName).clone()
            # compoundAux.setID(selectedCompoundID)
            # compoundAux.setName(keggInformationManager.getCompoundNameByID(selectedCompoundID))

            # 5. UPDATE THE FIELD NAME OF THE OMIC VALUE OBJECT USING THE COMPOUND NAME + THE ORIGINAL NAME (SOMETIMES THE
            #   COMPOUND MATCHES TO VARIOS ORIGINAL COMPOUNDS e.g. if input is beta-alanine and alanine and user checks both, the
            #   COMPOUND C00099 (beta-alanine) WILL HAVE 2 OMICS VALUES COMING FROM DIFFERENT COMPOUNDS
            # compoundAux.getOmicsValues()[0].setInputName(compoundAux.getName() + " [" + initialCompoundName + "]")
            # 6. ADD THE COMPOUND TO THE JOB

        # Update the omicSummary for the compoundOmic
        # TODO: at the moment it only considers "one whole compound omic" with the same mapped ratio
        for cpdOmic in self.getCompoundBasedInputOmics():
            # Get the original number of CPDs
            cpdSummary = cpdOmic.get("omicSummary")
            cpdTotal = cpdSummary[0] + cpdSummary[1]

            # Change the summary stats to reflect the user provided options
            cpdSummary[0] = len(mappedCompounds)
            cpdSummary[1] = cpdTotal - len(mappedCompounds)

        return True

    def generatePathwaysList(self):
        """selectedCompounds
        This function gets a list of selected compounds and the list of matched genes and
        find out all the pathways which contain at least one feature.

        @param {type}
        @returns
        """
        from multiprocessing import Process, cpu_count, Manager
        from math import ceil

        # ****************************************************************
        # Step 1. GET THE KEGG DATA AND PREPARE VARIABLES
        # ****************************************************************
        inputGenes = list(self.getInputGenesData().values())
        inputCompounds = list(self.getInputCompoundsData().values())
        pathwaysList = KeggInformationManager().getAllPathwaysByOrganism(self.getOrganism())

        enrichmentByOmic = {x.get("omicName"): x.get("enrichment", "genes") for x in
                            self.getGeneBasedInputOmics() + self.getCompoundBasedInputOmics()}

        # Retrieve all features per pathway in order to calculate the total amount
        organismGenes = defaultdict(lambda: defaultdict(set))
        organismCompounds = defaultdict(lambda: defaultdict(set))

        # GET THE IDS FOR ALL PATHWAYS FOR CURRENT SPECIE
        for pathwayID, pathway in pathwaysList.items():
            organismGenes[pathway["source"]][pathwayID], organismCompounds[pathway["source"]][
                pathwayID] = KeggInformationManager().getAllFeatureIDsByPathwayID(self.getOrganism(), pathwayID)

        # Add new function to classify Reactome pathways based on category: PaintOmics 4
        reactomeClass = defaultdict(set)

        if 'Reactome' in self.databases:
            reactomePathways = organismGenes['Reactome'].keys()
            for pathwayID in reactomePathways:
                className = KeggInformationManager().getPathwayClassificationByID(self.organism, pathwayID).split(';')[0]
                reactomeClass[className].add(pathwayID)


            classGene = defaultdict(set)
            classComp = defaultdict(set)
            for key,pathwaySetName in enumerate(reactomeClass):
                classGene[pathwaySetName] = set()
                classComp[pathwaySetName] = set()
                for pathwayName in reactomeClass[pathwaySetName]:
                    classGene[pathwaySetName].update(organismGenes['Reactome'][pathwayName])


        # Calculate the total number of genes and compounds per database
        totalGenes = {sourceDB: set(chain.from_iterable(pathways.values())) for sourceDB, pathways in
                      organismGenes.items()}
        totalCompounds = {sourceDB: set(chain.from_iterable(pathways.values())) for sourceDB, pathways in
                          organismCompounds.items()}

        totalFeaturesByOmic, totalRelevantFeaturesByOmic = self.calculateTotalFeaturesByOmic(enrichmentByOmic,
                                                                                             totalGenes, totalCompounds)
        totalInputMatchedCompounds = len(self.getInputCompoundsData())
        totalInputMatchedGenes = len(self.getInputGenesData())
        totalKeggPathways = len(pathwaysList)

        mappedRatiosByOmic = self.getMappedRatios()

        # ****************************************************************
        # Step 2. FOR EACH PATHWAY OF THE SPECIES, CHECK IF THERE IS ONE OR
        #         MORE FEATURES FROM THE INPUT (USING MULTITHREADING)
        # ****************************************************************
        # try:
        #     #CALCULATE NUMBER OF THREADS
        #     nThreads = min(cpu_count(), MAX_THREADS)
        # except NotImplementedError as ex:
        #     nThreads = MAX_THREADS
        nThreads = MAX_THREADS
        logging.info("USING " + str(nThreads) + " THREADS")

        def matchPathways(jobInstance, pathwaysList, genesInAllPathways, compoundsInAllPathways, inputGenes,
                          inputCompounds, totalFeaturesByOmic, totalRelevantFeaturesByOmic, matchedPathways,
                          mappedRatiosByOmic, enrichmentByOmic):
            # ****************************************************************
            # Step 2.1. FOR EACH PATHWAY IN THE LIST, GET ALL FEATURE IDS
            #           AND CALCULATE THE SIGNIFICANCE FOR THE PATHWAY
            # ****************************************************************
            keggInformationManager = KeggInformationManager()

            genesInPathway = compoundsInPathway = pathway = None
            for pathwayID in pathwaysList:
                genesInPathway = genesInAllPathways.get(pathwayID)
                compoundsInPathway = compoundsInAllPathways.get(pathwayID)
                sourceDB = keggInformationManager.getPathwaySourceByID(jobInstance.getOrganism(), pathwayID)

                # Add PaintOmics 4 sourceDB
                if "Unknown Pathway" in sourceDB:
                    sourceDB = 'Reactome'

                # genesInPathway, compoundsInPathway = keggInformationManager.getAllFeatureIDsByPathwayID(jobInstance.getOrganism(), pathwayID)
                isValidPathway, pathway = self.testPathwaySignificance(genesInPathway, compoundsInPathway, inputGenes,
                                                                       inputCompounds,
                                                                       totalFeaturesByOmic.get(sourceDB),
                                                                       totalRelevantFeaturesByOmic.get(sourceDB),
                                                                       mappedRatiosByOmic,
                                                                       enrichmentByOmic,
                                                                       sourceDB)
                if isValidPathway:
                    pathway.setID(pathwayID)
                    pathway.setName(keggInformationManager.getPathwayNameByID(jobInstance.getOrganism(), pathwayID))
                    pathway.setClassification(
                        keggInformationManager.getPathwayClassificationByID(jobInstance.getOrganism(), pathwayID))
                    pathway.setSource(sourceDB)

                    # for omic in jobInstance.getGeneBasedInputOmics()
                    #

                    matchedPathways[pathwayID] = pathway

        manager = Manager()
        matchedPathways = manager.dict()  # WILL STORE THE OUTPUT FROM THE THREADS
        #matchedPathways = {}
        nPathwaysPerThread = int(
            ceil(len(pathwaysList) / nThreads)) + 1  # GET THE NUMBER OF PATHWAYS TO BE PROCESSED PER THREAD

        pathwaysListParts = chunks(list(pathwaysList.keys()), nPathwaysPerThread)  # SPLIT THE ARRAY IN n PARTS
        #pathwaysListParts = list(pathwaysList.keys())
        threadsList = []

        # Flattened dict
        allGenesInPathway = {pathwayID: pathway for dbSource, dbPathways in organismGenes.items() for
                             pathwayID, pathway in
                             dbPathways.items()}

        allCompoundsInPathway = {pathwayID: pathway for dbSource, dbPathways in organismCompounds.items() for
                                 pathwayID, pathway in
                                 dbPathways.items()}

        #matchPathways( self, pathwaysListParts, allGenesInPathway, allCompoundsInPathway, inputGenes, inputCompounds,
        #                 totalFeaturesByOmic, totalRelevantFeaturesByOmic, matchedPathways, mappedRatiosByOmic,
        #                 enrichmentByOmic )

        # LAUNCH THE THREADS
        for pathwayIDsList in pathwaysListParts:
            thread = Process(target=matchPathways, args=(
                self, pathwayIDsList, allGenesInPathway, allCompoundsInPathway, inputGenes, inputCompounds,
                totalFeaturesByOmic, totalRelevantFeaturesByOmic, matchedPathways, mappedRatiosByOmic,
                enrichmentByOmic))
            threadsList.append(thread)
            thread.start()

        # Add class enrichment for PaintOmics 4
        if 'Reactome' in self.databases:
            matchedClass = manager.dict()  # WILL STORE THE OUTPUT FROM THE THREADS
            nClassPerThread = int(
                ceil(
                    len( classGene.keys() ) / nThreads ) ) + 1  # GET THE NUMBER OF PATHWAYS TO BE PROCESSED PER THREAD
            classListParts = chunks( list( classGene.keys() ), nClassPerThread )  # SPLIT THE ARRAY IN n PARTS
            for classNameList in classListParts:
                threadClass = Process( target=matchPathways, args=(
                    self, classNameList, classGene, classComp, inputGenes, inputCompounds,
                    totalFeaturesByOmic, totalRelevantFeaturesByOmic, matchedClass, mappedRatiosByOmic,
                    enrichmentByOmic) )
                threadsList.append( threadClass )
                threadClass.start()

        # WAIT UNTIL ALL THREADS FINISH
        for thread in threadsList:
            thread.join(MAX_WAIT_THREADS)

        isFinished = True
        for thread in threadsList:
            if thread.is_alive():
                isFinished = False
                thread.terminate()
                logging.info("THREAD TERMINATED IN generatePathwaysList")

        if not isFinished:
            raise Exception(
                'Your data took too long to process and it was killed. Try again later or upload smaller files if it persists.')

        self.setMatchedPathways(dict(matchedPathways))
        totalMatchedKeggPathways = len(self.getMatchedPathways())

        #PaintOmics 4
        if 'Reactome' in self.databases:
            self.setMatchedClass(dict(matchedClass))
            #self.setReactomeClass(reactomeClass)

        # Get the adjusted p-values (they need to be passed as a whole)
        pvalues_list = defaultdict(dict)
        combined_pvalues_list = defaultdict(dict)

        for pathway_id, pathway in self.getMatchedPathways().items():
            for omic, pvalue in pathway.getSignificanceValues().items():
                pvalues_list[omic][pathway_id] = pvalue[2]

            for method, combined_pvalue in pathway.getCombinedSignificancePvalues().items():
                combined_pvalues_list[method][pathway_id] = combined_pvalue

        adjusted_pvalues = {omic: adjustPvalues(omicPvalues) for omic, omicPvalues in pvalues_list.items()}
        adjusted_combined_pvalues = {method: adjustPvalues(methodCombinedPvalues) for method, methodCombinedPvalues in
                                     combined_pvalues_list.items()}

        # Set the adjusted p-value on a pathway basis
        for pathway_id, pathway in self.getMatchedPathways().items():
            for omic, pvalue in pathway.getSignificanceValues().items():
                pathway.setOmicAdjustedSignificanceValues(omic,
                                                          {adjust_method: pvalues[pathway_id] for adjust_method, pvalues
                                                           in adjusted_pvalues[omic].items()})

            for method, combined_pvalue in pathway.getCombinedSignificancePvalues().items():
                pathway.setMethodAdjustedCombinedSignificanceValues(method,
                                                                    {adjust_method: combined_pvalues[pathway_id] for
                                                                     adjust_method, combined_pvalues in
                                                                     adjusted_combined_pvalues[method].items()})

        logging.info("SUMMARY: " + str(totalMatchedKeggPathways) + " Matched Pathways of " + str(
            totalKeggPathways) + "in KEGG; Total input Genes = " + str(
            totalInputMatchedGenes) + "; SUMMARY: Total input Compounds  = " + str(totalInputMatchedCompounds))

        for key in totalFeaturesByOmic:
            logging.info("SUMMARY: Total " + key + " Features = " + str(totalFeaturesByOmic.get(key)))
            logging.info("SUMMARY: Total " + key + " Relevant Features = " + str(totalRelevantFeaturesByOmic.get(key)))

        self.summary = [totalKeggPathways, totalMatchedKeggPathways, totalInputMatchedGenes, totalInputMatchedCompounds,
                        totalFeaturesByOmic, totalRelevantFeaturesByOmic]
        # TODO: REVIEW THE SUMMARY GENERATION
        return self.summary

    def calculateTotalFeaturesByOmic(self, enrichmentByOmic, totalGenes, totalCompounds):
        """
        This function...

        @param {type}
        @returns
        """
        totalFeaturesID = set()
        totalFeaturesIDSig = set()
        totalFeaturesByOmic = defaultdict(Counter)
        totalRelevantFeaturesByOmic = defaultdict(Counter)
        totalAssociationsByOmic = defaultdict(Counter)
        totalRelevantAssociationsByOmic = defaultdict(Counter)

        # Three enrichment methods available: gene, feature and association enrichment.
        # By default use gene enrichment unless specified otherwise.
        enrichments = {
            'genes': lambda x: x.getInputName(),
            'features': lambda x: x.getOriginalName(),
            'associations': lambda x: ':::'.join([x.getInputName(), x.getOriginalName()])
        }

        counterNames = defaultdict(lambda: defaultdict(lambda: defaultdict(bool)))

        # Total features depends on the source DB
        totalFeatures = {dbSource: dbGenes.union(totalCompounds.get(dbSource)) for dbSource, dbGenes in
                         totalGenes.items()}

        for feature in chain(self.getInputCompoundsData().values(), self.getInputGenesData().values()):
            # Count only those present in at least one pathway
            if feature.getID() in totalFeatures.get(feature.getMatchingDB()):
                for omicValue in feature.getOmicsValues():
                    # Select the appropriate enrichment property
                    enrichmentType = enrichmentByOmic[omicValue.getOmicName()]
                    enrichmentProperty = enrichments.get(enrichmentType)(omicValue).lower()

                    # Only for association enrichment type the relevant feature must come from the associations files.
                    relevantValue = omicValue.isRelevantAssociation() if enrichmentType == 'associations' else omicValue.isRelevant()

                    #counterNames[feature.getMatchingDB()][omicValue.getOmicName()][enrichmentProperty] = (
                    #            counterNames[feature.getMatchingDB()][omicValue.getOmicName()][
                    #                enrichmentProperty] or relevantValue)

                    counterNames[feature.getMatchingDB()][omicValue.getOmicName()][feature.getID()] = (
                                counterNames[feature.getMatchingDB()][omicValue.getOmicName()][
                                   feature.getID()] or relevantValue)

                    if feature.getMatchingDB() == 'KEGG':
                        totalFeaturesID.add(feature.getID())
                        if relevantValue:
                            totalFeaturesIDSig.add(feature.getID())
            else:
                logging.error("STEP2 - Feature not present in at least one pathway " + feature.getID())

        for sourceDB, countersDB in counterNames.items():
            for omicName, featuresNames in countersDB.items():
                totalFeaturesByOmic[sourceDB][omicName] = len(featuresNames.keys())
                totalRelevantFeaturesByOmic[sourceDB][omicName] = list(featuresNames.values()).count(True)

        return totalFeaturesByOmic, totalRelevantFeaturesByOmic

    def testPathwaySignificance(self, genesInPathway, compoundsInPathway, inputGenes, inputCompounds,
                                totalFeaturesByOmic, totalRelevantFeaturesByOmic, mappedRatiosByOmic, enrichmentByOmic,
                                sourceDB):
        """
        This function takes a list of genes and compounds from the input and check if those features are at the
        list of feautures involved into a specific pathway.
        After that, the function calculates the significance for each omic type for the current pathway

        @param {List} genesInPathway, list of gene IDs in the pathway (ordered)
        @param {List} compoundsInPathway, list of compound IDs in the pathway (ordered)
        @param {List} inputGenes, list of genes (class Gene) in the input
        @param {List} inputCompounds, list of compounds (class Compound) in the input
        @param {Dict} totalFeaturesByOmic, contains the total features for each omic type (for statistics)
        @param {Dict} totalRelevantFeaturesByOmic, contains the total relevant features for each omic type (for statistics)
        @returns {Boolean} isValidPathway, True if at least one feature was matched, False in other cases.
        @returns {Pathway} pathwayInstance a new Pathway instance containing the matched info. None if pathway is not valid.
        """
        isValidPathway = False
        pathwayInstance = Pathway("")

        # Keep track of the original names so as to only count them once, for both genes and compounds.
        counterNames = defaultdict(lambda: defaultdict(bool))

        # Three enrichment methods available: gene, feature and association enrichment.
        # By default use gene enrichment unless specified otherwise.
        enrichments = {
            'genes': lambda x: x.getInputName(),
            'features': lambda x: x.getOriginalName(),
            'associations': lambda x: ':::'.join([x.getInputName(), x.getOriginalName()])
        }

        # TODO: RETURN AS A SET IN KEGG INFORMATION MANAGER
        genesInPathway = set([x.lower() for x in genesInPathway])
        for gene in inputGenes:
            if gene.getID().lower() in genesInPathway and gene.getMatchingDB() == sourceDB:
                isValidPathway = True
                pathwayInstance.addMatchedGeneID(gene.getID())
                for omicValue in gene.getOmicsValues():
                    # SIGNIFICANCE-VALUES LIST STORES FOR EACH OMIC 3 VALUES: [TOTAL MATCHED, TOTAL RELEVANT, PVALUE]
                    # IN THIS LINE WE JUST ADD A NEW MATCH AND, IF RELEVANT, A NEW RELEVANT FEATURE, BUT KEEP PVALUE TO -1
                    # AS WE WILL CALCULATE IT LATER.
                    enrichmentType = enrichmentByOmic[omicValue.getOmicName()]
                    enrichmentProperty = enrichments.get(enrichmentType)(omicValue).lower()

                    # Only for association enrichment type the relevant feature must come from the associations files.
                    relevantValue = omicValue.isRelevantAssociation() if enrichmentType == 'associations' else omicValue.isRelevant()

                    counterNames[omicValue.getOmicName()][enrichmentProperty] = (
                                counterNames[omicValue.getOmicName()][enrichmentProperty] or relevantValue)

        # First we get the list of IDs for the compounds that participate in the pathway
        compoundsInPathway = set([x.lower() for x in compoundsInPathway])
        # Keeps a track of which compounds participates in the pathway, without counting twice compounds that come from the
        # same measurement (it occurs due to disambiguation step).
        # Now, for each compound in the input
        for compound in inputCompounds:
            # Check if the compound participates in the pathway
            if compound.getID().lower() in compoundsInPathway and compound.getMatchingDB() == sourceDB:
                # If at least one compound participates, then the pathway is valid
                isValidPathway = True
                # Register that the compound participates in the pathway
                pathwayInstance.addMatchedCompoundID(compound.getID())
                # Register the original name for the compound (to avoid duplicate counts for significance test)

                for omicValue in compound.getOmicsValues():
                    # Add the original name to the table for the corresponding omics type, specifying if the feature is relevant or not.
                    # Metabolomics --> Glutamine --> [prev value for isRelevant] or [current feature isRelevant]
                    enrichmentType = enrichmentByOmic[omicValue.getOmicName()]
                    enrichmentProperty = enrichments.get(enrichmentType)(omicValue).lower()

                    # Only for association enrichment type the relevant feature must come from the associations files.
                    relevantValue = omicValue.isRelevantAssociation() if enrichmentType == 'associations' else omicValue.isRelevant()

                    # TODO: what if L-Glutamine coming from "Glutamine" is in the list of relevants but Glutamine not? Now we consider Glutamine as relevant
                    counterNames[omicValue.getOmicName()][enrichmentProperty] = (
                                counterNames[omicValue.getOmicName()][enrichmentProperty] or relevantValue)

        for omicName, featureNames in counterNames.items():
            for isRelevant in featureNames.values():
                # SIGNIFICANCE-VALUES LIST STORES FOR EACH OMIC 3 VALUES: [TOTAL MATCHED, TOTAL RELEVANT, PVALUE]
                # IN THIS LINE WE JUST ADD A NEW MATCH AND, IF RELEVANT, A NEW RELEVANT FEATURE, BUT KEEP PVALUE TO -1
                # AS WE WILL CALCULATE IT LATER.
                pathwayInstance.addSignificanceValues(omicName, isRelevant)

        if isValidPathway:
            for omicName, values in pathwayInstance.getSignificanceValues().items():
                # values = pathwayInstance.getSignificanceValues().get(omicName)
                # FOR EACH OMIC TYPE, SIGNIFICANCE IS CALCULATED TAKING IN ACCOUNT, AND CONSIDERING ONLY THE ORIGINAL NAME:
                #  - THE TOTAL NUMBER OF MATCHED FEATURES FOR CURRENT OMIC (i.e. IF WE INPUT PROTEINS, THE TOTAL NUMBER WILL BE
                #    THE TOTAL OF PROTEINS THAT WE MANAGED TO MAP TO GENES).
                #  - THE TOTAL NUMBER OF RELEVANT FEATURES FOR THE CURRENT OMIC
                #  - THE TOTAL FOUND FEATURES FOR CURRENT PATHWAY
                #  - THE TOTAL RELEVANT FEATURES FOR CURRENT PATHWAY
                pValue = calculateSignificance(self.getTest(),
                                               totalFeaturesByOmic.get(omicName, 0),
                                               totalRelevantFeaturesByOmic.get(omicName, 0),
                                               values[0],
                                               values[1])
                pathwayInstance.setSignificancePvalue(omicName, pValue)

            # SIGNIFICANCE VALUES PER OMIC in format OmicName -> [totalFeatures, totalRelevantFeatures, pValue]

            # Ensure the same order in both values and weights
            omicSignificanceValues = pathwayInstance.getSignificanceValues()
            keyOrder = omicSignificanceValues.keys()

            stouferWeights = [mappedRatiosByOmic[omicName] for omicName in keyOrder]
            omicPvalues = [omicSignificanceValues[omicName] for omicName in keyOrder]

            pathwayInstance.setCombinedSignificancePvalues(
                calculateCombinedSignificancePvalues(omicPvalues, stouferWeights))

        else:
            pathwayInstance = None

        return isValidPathway, pathwayInstance

    def generateSelectedPathwaysInformation(self, selectedPathways, visibleOmics, toBSON=False):
        """
        This function...

        @param {type}
        @returns
        """

        # ************************************************************************
        # Step 1. Prepare the variables
        # ************************************************************************
        pathwayInstance = None
        selectedPathwayInstances = []
        graphicalOptionsInstancesBSON = []
        omicsValuesSubset = {}
        bsonAux = None

        keggInformationManager = KeggInformationManager()

        if (len(visibleOmics) > 0):
            # TODO: IN PREVIOUS STEPS THE USER COULD SPECIFY THE DEFAULT OMICS TO SHOW
            pass
        else:
            # By default try to show 3 genes based omics and 1 Compound based omic
            visibleOmics = [inputData.get("omicName") + "#genebased" for inputData in
                            self.getGeneBasedInputOmics()[0:3]]
            visibleOmics.extend(
                [inputData.get("omicName") + "#compoundbased" for inputData in self.getCompoundBasedInputOmics()[0:1]])

        # ************************************************************************
        # Step 2. For each provided pathway, get the graphical information
        # ************************************************************************
        for pathwayID in selectedPathways:
            pathwayInstance = self.getMatchedPathways().get(pathwayID)

            # AQUI RECORRER PARA CADA ELEMENTO DE LA PATHWAY Y VER SI
            #  SI ES GEN Y ESTA EN LA LISTA DE GENES METIDOS -> GUARDAR VALORES, POSICIONES, SIGNIFICATIVO
            #  SI ES COMPOUND Y ESTA EN LA LISTA DE COMPOUND METIDOS -> GUARDAR VALORES, POSICIONES, SIGNIFICATIVO
            #  ...

            # ************************************************************************
            # Step 2.1 Create the graphical information object -> features coordinates,
            #          box height,...
            # ************************************************************************
            genesInPathway, compoundsInPathway = keggInformationManager.getAllFeaturesByPathwayID(self.getOrganism(),
                                                                                                  pathwayID)

            graphicalOptions = PathwayGraphicalData()
            graphicalOptions.setFeaturesGraphicalData(genesInPathway + compoundsInPathway)
            # graphicalOptions.setImageSize(getImageSize(keggInformationManager.getKeggDataDir() + 'png/' + pathwayID.replace(self.getOrganism(), "map") + ".png"))
            graphicalOptions.setImageSize(getImageSize(
                keggInformationManager.getDataDir(pathwayInstance.getSource()) + 'png/' + pathwayID.replace(
                    self.getOrganism(), "map") + ".png"))
            graphicalOptions.setVisibleOmics(visibleOmics)

            # Set the graphical options for the pathway
            pathwayInstance.setGraphicalOptions(graphicalOptions)

            # ************************************************************************
            # Step 2.2 Get the subset of genes and compounds that are in the current
            #          pathway and add them to the list of features that will be send
            #          to the client side with the expression values
            # ************************************************************************
            # TODO: MEJORABLE, MULTHREADING U OTRAS OPCIONES
            auxDict = self.getInputGenesData()

            for geneID in pathwayInstance.getMatchedGenes():
                if toBSON:
                    omicsValuesSubset[geneID] = auxDict.get(geneID).toBSON()
                else:
                    omicsValuesSubset[geneID] = auxDict.get(geneID)

            auxDict = self.getInputCompoundsData()

            for compoundID in pathwayInstance.getMatchedCompounds():
                if toBSON:
                    omicsValuesSubset[compoundID] = auxDict.get(compoundID).toBSON()
                else:
                    omicsValuesSubset[compoundID] = auxDict.get(compoundID)

            if toBSON:
                bsonAux = pathwayInstance.getGraphicalOptions().toBSON()
                bsonAux["pathwayID"] = pathwayID
                graphicalOptionsInstancesBSON.append(bsonAux)
            # Add the pathway to the list
            selectedPathwayInstances.append(pathwayInstance)

        return [selectedPathwayInstances, graphicalOptionsInstancesBSON, omicsValuesSubset]

    # GENERATE METAGENES LIST FUNCTIONS -----------------------------------------------------------------------------------------
    def generateMetagenesList(self, ROOT_DIRECTORY: object, clusterNumber: object, omicList: object = None,
                              database: object = None) -> object:
        """
        This function obtains the metagenes for each pathway in KEGG based on the input values.

        @param {type}
        @returns
        """
        # STEP 1. EXTRACT THE COMPRESSED FILE WITH THE MAPPING FILES
        zipFile(self.getOutputDir() + "/mapping_results_" + self.getJobID() + ".zip").extractall(
            path=self.getTemporalDir())

        # STEP 2. GENERATE THE DATA FOR EACH OMIC DATA TYPE
        filtered_omics = self.geneBasedInputOmics
        filtered_databases = self.getDatabases()

        if omicList:
            filtered_omics = [inputOmic for inputOmic in self.geneBasedInputOmics if
                              inputOmic.get("omicName") in omicList]

        if database:
            filtered_databases = set(database).intersection(set(filtered_databases))

        for inputOmic in filtered_omics:
            try:
                # STEP 2.1 EXECUTE THE R SCRIPT FOR EACH DATABASE
                for dbname in filtered_databases:
                    logging.info("GENERATING METAGENES INFORMATION FOR " + str(dbname) + "...CALLING")
                    inputFile = self.getTemporalDir() + "/" + inputOmic.get("omicName") + '_matched.txt'
                    # Select number of clusters, default to dynamic

                    kClusters = str(dict(clusterNumber).get(inputOmic.get("omicName"), "dynamic"))
                    logging.info("kClusters=" + str(kClusters))
                    logging.info(str(ROOT_DIRECTORY))

                    logging.info("dbname is " + str(dbname))

                    check_call([
                        ROOT_DIRECTORY + "common/bioscripts/generateMetaGenes.R",
                        '--specie="' + self.getOrganism() + '"',
                        '--input_file="' + inputFile + '"',
                        '--output_prefix="' + inputOmic.get("omicName") + '"',
                        '--data_dir="' + self.getTemporalDir() + '"',
                        '--kegg_dir="' + KEGG_DATA_DIR + '"',
                        '--sources_dir="' + ROOT_DIRECTORY + 'common/bioscripts/"',
                        '--kclusters="' + kClusters + '"' if kClusters.isdigit() else '',
                        '--database="' + dbname + '"' if dbname != "KEGG" else ''], stderr=STDOUT)
                    # STEP 2.2 PROCESS THE RESULTING FILE

                    # Reset all pathways metagenes for the omic
                    for pathway in self.matchedPathways.values():
                        # Only reset metagenes for current DB
                        if pathway.getSource().lower() == str(dbname).lower():
                            pathway.resetMetagenes(inputOmic.get("omicName"))

                    metagenesFileName: object = self.getTemporalDir() + "/" + inputOmic.get("omicName") + "_metagenes" + \
                                                ("_" + str(dbname).lower() + ".tab" if dbname != "KEGG" else ".tab")

                    # Clean previous metagene
                    #for line in self.matchedPathways:
                    #    self.matchedPathways[line].metagenes = dict()

                    with open(metagenesFileName, 'rU') as inputDataFile:
                        for line in csv_reader(inputDataFile, delimiter="\t"):
                            if line[0] in self.matchedPathways:
                                self.matchedPathways.get(line[0]).addMetagenes(inputOmic.get("omicName"),
                                                                               {"metagene": line[1], "cluster": line[2],
                                                                                "values": line[3:]})
                                logging.info(
                                    "pathway:" + str(line[0]) + " metaGene:" + str(line[1]) + " cluster:" + str(
                                        line[2]) + " values:" + str(line[3:]))
                    inputDataFile.close()
            except CalledProcessError as ex:
                logging.error("STEP2 - Error while generating metagenes information for " + inputOmic.get("omicName"))


        call("rm " +  self.getOutputDir()  + "*.png", shell=True)
        call("mv " + self.getTemporalDir() + "/" + "*.png " + self.getOutputDir(), shell=True)
        return self

    # JSON <-> BSON FUNCTIONS ------------------------------------------------------------------------------------------------------
    def parseBSON(self, bsonData):
        """
        This function...

        @param {type}
        @returns
        """
        bsonData.pop("_id")
        for (attr, value) in bsonData.items():
            if attr == "matchedPathways":
                pathwayInstance = None
                self.matchedPathways.clear()
                for (pathwayID, pathwayData) in value.items():
                    pathwayInstance = Pathway(pathwayID)
                    pathwayInstance.parseBSON(pathwayData)
                    self.addMatchedPathway(pathwayInstance)
            if attr == "foundCompounds":
                self.foundCompounds[:] = []
                for foundCompoundID in value:
                    foundFeatureInstance = FoundFeature("")
                    self.addFoundCompound({
                        'mainCompounds': [Compound(compoundData["ID"]).parseBSON(compoundData) for compoundData in
                                          value.getMainCompounds()],
                        'otherCompounds': [Compound(compoundData["ID"]).parseBSON(compoundData) for compoundData in
                                           value.getOtherCompounds()]
                    })
            elif attr == "inputCompoundsData":
                compoundInstance = None
                self.inputCompoundsData.clear()
                for (compoundID, compoundData) in value.items():
                    compoundInstance = Compound(compoundID)
                    compoundInstance.parseBSON(compoundData)
                    self.addInputCompoundData(compoundInstance)
            elif attr == "inputGenesData":
                geneInstance = None
                self.inputGenesData.clear()
                for (geneID, genData) in value.items():
                    geneInstance = Gene(geneID)
                    geneInstance.parseBSON(genData)
                    self.addInputGeneData(geneInstance)
            elif attr == "userID":
                setattr(self, attr, value if value != 'None' else None)
            elif not isinstance(value, dict):
                setattr(self, attr, value)

    def toBSON(self, recursive=True):
        """
        This function...

        @param recursive:
        @return:
        """
        bson = {}
        for attr, value in self.__dict__.items():
            # Special case: "foundCompounds" is a list (not a dict) that contains recursive object data
            if not isinstance(value, dict) and (
                    ["svgDir", "inputDir", "outputDir", "temporalDir", "foundCompounds"].count(attr) == 0):
                bson[attr] = value

            elif recursive:
                if attr == "matchedPathways":
                    matchedPathways = {}
                    for (pathwayID, pathwayInstance) in value.items():
                        matchedPathways[pathwayID] = pathwayInstance.toBSON()
                    value = matchedPathways
                elif attr == "inputCompoundsData":
                    compounds = {}
                    for (compoundID, compoundInstance) in value.items():
                        compounds[compoundID] = compoundInstance.toBSON()
                    value = compounds
                elif attr == "inputGenesData":
                    genes = {}
                    for (geneID, geneInstance) in value.items():
                        genes[geneID] = geneInstance.toBSON()
                    value = genes
                elif attr == "foundCompounds":
                    compounds = []
                    for compoundCB in value:
                        compounds.append({
                            'mainCompounds': [compoundInstance.toBSON() for compoundInstance in
                                              compoundCB.getMainCompounds()],
                            'otherCompounds': [compoundInstance.toBSON() for compoundInstance in
                                               compoundCB.getOtherCompounds()]
                        })
                    value = compounds
                bson[attr] = value
        return bson

    def compundsClassification(self):

        import json, os
        from collections import defaultdict

        brPath = os.path.dirname(__file__) + "/../../common/br08001.json"
        interactionJSONPath = self.inputDir + "../../../KEGG_DATA/current/" + self.organism + '/hubData/kegg_interaction.json'

        # Load classification File
        with open(brPath, 'r') as f:
            temp = json.loads(f.read())
            print(temp)

        with open(interactionJSONPath, 'r') as e:
            compoundRegulateFeatures = json.dumps(json.JSONDecoder().decode(e.read()))
        compoundRegulateFeatures = json.loads(compoundRegulateFeatures)

        temp2 = temp["children"]

        keggCompondsList = defaultdict(set)
        for i in temp2:
            for j in i['children']:
                for w in j['children']:
                    for t in w['children']:
                        subt = t['name'].split()[0]
                        keggCompondsList[j['name']].add(subt)

        # Creat a non-redundant compound set
        compoundIDSet = set()
        # compoundNameSet = set()

        for key, inputCompound in self.inputCompoundsData.items():
            #    if inputCompound.omicsValues[0].inputName not in compoundNameSet and inputCompound.omicsValues[0].inputName.lower() == inputCompound.omicsValues[0].originalName.lower():
            #        compoundNameSet.add(inputCompound.omicsValues[0].inputName)
            compoundIDSet.add(key)

        # Only keep compounds in the classification file
        classificationDict = defaultdict(list)
        for compoundID in compoundIDSet:
            for key, IDs in keggCompondsList.items():
                if compoundID in IDs:
                    classificationDict[key].append(compoundID)

        # Prepare values to test category significance
        totalFeatures = sum(map(len, classificationDict.values()))
        totalFeaturesInCategory = defaultdict(int)
        totalRelevantFeaturesInCategory = defaultdict(int)
        pValueInDict = {}

        for key, items in classificationDict.items():
            totalFeaturesInCategory[key] = len(items)
            totalRelevantFeaturesInCategory[key] = 0
            for item in items:
                if self.inputCompoundsData.get(item).omicsValues[0].relevant:
                    totalRelevantFeaturesInCategory[key] = totalRelevantFeaturesInCategory[key] + 1

        totalRelevantFeatures = sum(totalRelevantFeaturesInCategory.values())

        for key in classificationDict:
            import math, scipy
            z_score: float = (totalRelevantFeaturesInCategory.get(key)/totalFeaturesInCategory.get(key)-0.5)/math.sqrt(0.25/totalFeaturesInCategory.get(key))
            pValueInDict[key] = scipy.stats.norm.sf(z_score)
                
                #round(
                #calculateSignificance(self.test, totalFeatures, totalRelevantFeatures, totalFeaturesInCategory.get(key),
                #                      totalRelevantFeaturesInCategory.get(key)), 4)

        featureSummary = [totalFeatures, totalRelevantFeatures]

        adjustPvalue = adjustPvalues(pValueInDict)

        for keys, items in adjustPvalue.items():
            for item in items:
                adjustPvalue.get(keys)[item] = round(items[item], 4)

        # Save the expression values
        valuesSet = set()
        for items in classificationDict.values():
            for item in items:
                valuesSet.add(item)

        expressionValueComp = defaultdict(list)
        mappingComp = {}
        for value in self.inputCompoundsData:
            expressionValueComp[value] = self.inputCompoundsData.get(value).omicsValues[0].values
            mappingComp[value] = self.inputCompoundsData.get(value).omicsValues[0].inputName

        # Save the expression values of Metabolites
        exprssionMetabolites = {}
        for i in self.inputCompoundsData:
            exprssionMetabolites[i] = self.inputCompoundsData[i].omicsValues[0].values

        # mappingCompList = list()
        # mappingCompList.append(mappingComp)
        # pValueInDictList = list()
        # pValueInDictList.append(pValueInDict)
        # classificationDictList = list()
        # classificationDictList.append(classificationDict)
        self.mappingComp = dict(mappingComp)
        self.pValueInDict = dict(pValueInDict)
        self.classificationDict = dict(classificationDict)
        self.exprssionMetabolites = dict(exprssionMetabolites)
        self.adjustPvalue = dict(adjustPvalue)
        self.totalRelevantFeaturesInCategory = dict(totalRelevantFeaturesInCategory)
        self.featureSummary = featureSummary
        self.compoundRegulateFeatures = compoundRegulateFeatures

        return self.mappingComp, self.pValueInDict, self.classificationDict, self.exprssionMetabolites, self.adjustPvalue, self.totalRelevantFeaturesInCategory, self.featureSummary, self.compoundRegulateFeatures

    def getGlobalExpressionData(self):
        globalExpressionDataGene = defaultdict(dict)
        globalExpressionDataComp = defaultdict(dict)
        globalExpressionData = defaultdict(dict)


        for j in self.inputCompoundsData:
            expressionID = self.inputCompoundsData[j].ID
            expressionDetail = {
                'keggName': self.inputCompoundsData[j].name,
                'inputName': self.inputCompoundsData[j].omicsValues[0].inputName,
                'originalName': self.inputCompoundsData[j].omicsValues[0].originalName,
                'isRelevant': self.inputCompoundsData[j].omicsValues[0].relevant,
                'isRelevantAssociation': self.inputCompoundsData[j].omicsValues[0].relevantAssociation,
                'values': self.inputCompoundsData[j].omicsValues[0].values
            }
            globalExpressionDataComp[expressionID] = expressionDetail

        for i in self.inputGenesData:
            expressionID = self.inputGenesData[i].ID
            expressionDetail = {
                'keggName': self.inputGenesData[i].name,
                'inputName': self.inputGenesData[i].omicsValues[0].inputName,
                'originalName': self.inputGenesData[i].omicsValues[0].originalName,
                'isRelevant': self.inputGenesData[i].omicsValues[0].relevant,
                'isRelevantAssociation': self.inputGenesData[i].omicsValues[0].relevantAssociation,
                'values': self.inputGenesData[i].omicsValues[0].values
            }
            globalExpressionDataGene[expressionID] = expressionDetail

        globalExpressionData["inputGene"] = globalExpressionDataGene
        globalExpressionData["inputCompound"] = globalExpressionDataComp
        self.globalExpressionData = globalExpressionData
        return self.globalExpressionData

    def hubAnalysis(self, ROOT_DIRECTORY):

        userDEfeatures = set()
        userDataset = set()
        #userGenePathway = set()

        # Only test gene inside the pathway
        #for pathway in self.matchedPathways:
        #    for gene in self.matchedPathways[pathway].matchedGenes:
        #        userGenePathway.add(gene)

        for i in self.inputGenesData:
            for k in self.inputGenesData[i].omicsValues:
                if k.omicName == 'Gene expression':
                    #if i in userGenePathway:
                    if k.relevant or k.relevantAssociation:
                      userDEfeatures.add( i )
                    userDataset.add( i )

        for j in self.inputCompoundsData:
            if self.inputCompoundsData[j].omicsValues[0].relevant:
                userDEfeatures.add(j)
            userDataset.add(j)

        # IF there is no relevant features, we can not do metabolite hub analysis
        if not userDEfeatures:
            return False

        import csv
        with open(self.outputDir + "userDataset.csv", 'w') as w:
            writer = csv.writer(w)
            writer.writerow(userDataset)

        with open(self.outputDir + "userDEfeatures.csv", 'w') as w:
            writer = csv.writer(w)
            writer.writerow(userDEfeatures)

        check_call(
            [
                ROOT_DIRECTORY + "common/bioscripts/hubAnalysis.R",
                '--data_dir="' + self.outputDir + '"',
                '--inputDir="' + KEGG_DATA_DIR + 'current/' + self.organism + '/hubData/' + '"'
            ], stderr=STDOUT
        )

        hubResult = {}

        with open(self.outputDir + 'hub_result.csv', "r") as f:
            reader = csv.reader(f, delimiter="\t")
            for i, line in enumerate(reader):
                hubResult[i] = line

        self.hubAnalysisResult = hubResult

        return self.hubAnalysisResult
