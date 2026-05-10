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
from chardet import detect # get the encoding of a file

from os import path as os_path, system as os_system, makedirs as os_makedirs
from csv import reader as csv_reader
from zipfile import ZipFile as zipFile

from subprocess import check_call, check_output, call, STDOUT, CalledProcessError

from src.classes.FoundFeature import FoundFeature
from src.common.Util import unifyAndSort

from collections import defaultdict, Counter
from itertools import chain

from src.common.Statistics import calculateSignificance, calculateCombinedSignificancePvalues, adjustPvalues
from src.common.Util import chunks, getImageSize
from src.common.ReplicateDetection import detect_replicates, aggregate_replicates

from src.common.KeggInformationManager import KeggInformationManager

from src.classes.Job import Job
from src.classes.Feature import Gene, Compound
from src.classes.Pathway import Pathway
from src.classes.PathwayGraphicalData import PathwayGraphicalData

from src.conf.serverconf import KEGG_DATA_DIR, MAX_THREADS, MAX_WAIT_THREADS, MAX_NUMBER_FEATURES

# Small dict fields safe to persist in the main MongoDB document
PAINTOMICS4_DICT_FIELDS = {
    "mappingComp", "classificationDict", "pValueInDict",
    "adjustPvalue", "totalRelevantFeaturesInCategory", "featureSummary"
}

# Large dict fields that stay in-memory cache only (too large for a single
# MongoDB document — compoundRegulateFeatures alone can exceed 60 MB).
# On cold recovery the safe_* defaults in the servlet return {}/[].
PAINTOMICS4_LARGE_FIELDS = {
    "exprssionMetabolites", "compoundRegulateFeatures",
    "globalExpressionData", "hubAnalysisResult"
}


def _matchPathways(jobInstance, pathwaysList, genesInAllPathways, compoundsInAllPathways, inputGenes,
                    inputCompounds, totalFeaturesByOmic, totalRelevantFeaturesByOmic, matchedPathways,
                    mappedRatiosByOmic, enrichmentByOmic):
    """Module-level wrapper so multiprocessing.Process can pickle the target."""
    keggInformationManager = KeggInformationManager()

    # OPTIMIZATION: Pre-calculate lookups once per thread instead of per pathway
    inputGenesDict = {g.getID().lower(): g for g in inputGenes}
    inputCompoundsDict = {c.getID().lower(): c for c in inputCompounds}

    # OPTIMIZATION: Determine multi-condition mode once per thread
    max_conditions = 1
    for feature in chain(inputGenes, inputCompounds):
        for ov in feature.getOmicsValues():
            if isinstance(ov.relevant, list):
                max_conditions = max(max_conditions, len(ov.relevant))
    has_multi_cond = max_conditions > 1

    for pathwayID in pathwaysList:
        genesInPathway = genesInAllPathways.get(pathwayID)
        compoundsInPathway = compoundsInAllPathways.get(pathwayID)
        sourceDB = keggInformationManager.getPathwaySourceByID(jobInstance.getOrganism(), pathwayID)

        if "Unknown Pathway" in sourceDB:
            sourceDB = 'Reactome'

        if sourceDB not in totalFeaturesByOmic:
            continue

        isValidPathway, pathway = jobInstance.testPathwaySignificance(
            genesInPathway, compoundsInPathway, inputGenesDict, inputCompoundsDict,
            totalFeaturesByOmic.get(sourceDB), totalRelevantFeaturesByOmic.get(sourceDB),
            mappedRatiosByOmic, enrichmentByOmic, sourceDB, has_multi_cond)

        if isValidPathway:
            pathway.setID(pathwayID)
            pathway.setName(keggInformationManager.getPathwayNameByID(jobInstance.getOrganism(), pathwayID))
            pathway.setClassification(
                keggInformationManager.getPathwayClassificationByID(jobInstance.getOrganism(), pathwayID))
            pathway.setSource(sourceDB)
            matchedPathways[pathwayID] = pathway


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

        # AI Interpretation
        self.aiConsent = False
        self.experimentDesign = ""

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

    def getAIConsent(self):
        return self.aiConsent
    def setAIConsent(self, v):
        self.aiConsent = (v == True or v == "true" or v == "True")
    def getExperimentDesign(self):
        return self.experimentDesign
    def setExperimentDesign(self, v):
        self.experimentDesign = str(v) if v else ""

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

        # Establish nConditions from the first available data file
        all_omics = self.geneBasedInputOmics + self.compoundBasedInputOmics
        for inputOmic in all_omics:
            valuesFileName = inputOmic.get("inputDataFile")
            if not inputOmic.get("isExample", False) and valuesFileName:
                valuesFileName = "{path}/{file}".format(path=self.getInputDir(), file=valuesFileName)
                if os_path.isfile(valuesFileName):
                    values_delimiter = Job.detect_delimiter(valuesFileName)
                    with open(valuesFileName, 'r', encoding='utf-8-sig', newline='') as f:
                        for line in csv_reader(f, delimiter=values_delimiter):
                            if len(line) > 1:
                                try:
                                    float(line[1])
                                    nConditions = len(line)
                                    break
                                except ValueError:
                                    continue
                if nConditions != -1:
                    break

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
            assoc_delimiter = Job.detect_delimiter(associationsFileName)
            with open(associationsFileName, 'r', encoding='utf-8-sig', newline='') as associationDataFile:
                for line in csv_reader(associationDataFile, delimiter=assoc_delimiter):
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
            rel_assoc_delimiter = Job.detect_delimiter(relevantAssociationsFileName)
            with open(relevantAssociationsFileName, 'r', encoding='utf-8-sig', newline='') as relevantAssociationDataFile:
                for line in csv_reader(relevantAssociationDataFile, delimiter=rel_assoc_delimiter):
                    nLine = nLine + 1

                    if nLine > MAX_NUMBER_FEATURES:
                        error += " - Errors detected while processing " + inputOmic.get("relevantAssociationsFile",
                                                                                        "") + \
                                 ": The file exceeds the maximum number of features allowed (" + str(
                            MAX_NUMBER_FEATURES) + ")." + "\n"
                        break

                    if len(line) != 2 and len(line) != 1:
                        error += " - Errors detected while processing " + inputOmic.get("relevantAssociationsFile",
                                                                                        "") + ": The file does not look like a relevant associations file (expected 1 or 2 columns)." + "\n"
                        break

        # *************************************************************************
        # STEP 1. VALIDATE THE RELEVANT FEATURES FILE
        # *************************************************************************
        logging.info("VALIDATING RELEVANT FEATURES FILE (" + omicName + ")...")
        if os_path.isfile(relevantFileName):
            f = open(relevantFileName, 'r', encoding='utf-8-sig')
            lines = f.readlines()

            # Ensure that relevant features files does not exceed the max number of features
            if len(lines) > MAX_NUMBER_FEATURES:
                error += " - Errors detected while processing " + inputOmic.get("relevantFeaturesFile",
                                                                                "") + ": The file exceeds the maximum number of features allowed (" + str(
                    MAX_NUMBER_FEATURES) + ")." + "\n"
            else:
                # Check column count if multi-condition
                if len(lines) > 0:
                    rf_delimiter = Job.detect_delimiter(relevantFileName)
                    first_line = lines[0].strip().split(rf_delimiter)
                    rf_conditions = len(first_line)
                    
                    # If nConditions is already set (from a previous values file or previous RF file), check for match
                    if nConditions != -1:
                        # nConditions is the number of columns in the DATA file (ID + Conditions)
                        # rf_conditions is the number of columns in the RF file (Conditions only)
                        # So we expect nConditions == rf_conditions + 1
                        if rf_conditions > 1 and rf_conditions != (nConditions - 1):
                             # A 2-col file is the legacy [TARGET, REGULATOR] pair-list that
                             # MiRNA2GenesServlet emits for the Regulatory Omics workflow,
                             # regardless of how many conditions the values file declares.
                             # parseSignificativeFeaturesFile (Job.py:740) detects this shape
                             # via its isLegacyTwoCol branch and produces GENE:::REGULATOR keys.
                             if rf_conditions != 2:
                                 error += " - Errors detected while processing " + inputOmic.get("relevantFeaturesFile", "") + \
                                          ": The number of columns (" + str(rf_conditions) + ") does not match the number of conditions in the data file (" + str(nConditions - 1) + ").\n"

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
            # get file encoding type
            def get_encoding_type(file):
                with open( file, 'rb' ) as f:
                    raw_data = f.read()
                return detect( raw_data )['encoding']

            fileEncodingType = get_encoding_type( valuesFileName )
            # convert file to utf-8
            if fileEncodingType != 'utf-8':
                with open( valuesFileName, 'r', encoding=fileEncodingType ) as f:
                    text = f.read()
                with open( valuesFileName, 'w', encoding='utf-8' ) as f:
                    f.write( text )

            values_delimiter = Job.detect_delimiter(valuesFileName)
            with open(valuesFileName, newline='', encoding='utf-8-sig' ) as inputDataFile:
                nLine = -1
                erroneousLines = {}
                for line in csv_reader(inputDataFile, delimiter=values_delimiter):
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

    def _detectReplicatesForOmic(self, omicName, omicHeader):
        """
        Run replicate detection on a single omic's column labels.

        ``omicHeader`` is the raw header captured by the parsers — list[str]
        where index 0 is the ID column and indices 1..n are sample columns.
        We pass only the sample slice to ``detect_replicates``; an absent or
        malformed header degrades safely to ``status="none"`` so the rest of
        the pipeline (which only reads the dict shape) keeps working.
        """
        replicateHeader = omicHeader[1:] if omicHeader and len(omicHeader) > 1 else []
        result = detect_replicates(replicateHeader)
        logging.info(
            "REPLICATE DETECTION (%s): status=%s, samples=%d, unmatched=%d",
            omicName, result["status"], len(result["sampleHeader"]), len(result["unmatched"])
        )
        return result

    def _findInputOmicByName(self, omicName):
        """
        Locate an inputOmic + its feature dict + feature type by omic name.

        Returns ``(inputOmic, featureDict, featureType)`` or ``(None, None, None)``.
        Used by both the auto-apply path (this file) and the servlet apply
        endpoint (PathwayAcquisitionServlet) — kept on the job so the two
        callers share a single source of truth for the lookup convention.
        """
        for inputOmic in self.getGeneBasedInputOmics():
            if inputOmic.get("omicName") == omicName:
                return inputOmic, self.getInputGenesData(), "Gene"
        for inputOmic in self.getCompoundBasedInputOmics():
            if inputOmic.get("omicName") == omicName:
                return inputOmic, self.getInputCompoundsData(), "Compound"
        return None, None, None

    def applyReplicateMappingForOmic(self, omicName, mode, sampleHeader=None,
                                     mapping=None, groups=None):
        """
        Apply (or clear) a replicate→sample mapping for one omic.

        This is the single source of truth for the aggregation step: invoked
        both by the auto-apply path inside ``processFilesContent`` (mode=auto,
        no extra args) and by the servlet ``/pa_apply_replicate_mapping``
        endpoint (mode auto/manual/off). For ``mode="manual"`` the caller is
        responsible for parsing the design file and supplying ``sampleHeader``,
        ``mapping`` and ``groups``.

        Mutates:
        - ``inputOmic`` dict: writes ``replicateSource``, ``sampleHeader``,
          ``replicateMapping``.
        - Each affected ``OmicValue``: writes ``sampleValues`` /
          ``sampleRelevant`` (or clears them when mode="off").

        Returns ``{omicName, status, mode, sampleHeader, mapping,
        featuresUpdated, featureType}`` for the caller to persist / serialize.
        """
        inputOmic, featureDict, featureType = self._findInputOmicByName(omicName)
        if inputOmic is None:
            raise ValueError("Omic '%s' not found in this job." % omicName)

        if mode == "off":
            inputOmic["replicateSource"]   = "off"
            inputOmic["sampleHeader"]      = []
            inputOmic["replicateMapping"]  = []
            n_touched = self._walkAndAggregateOmicValues(
                featureDict, omicName, mapping=[], groups=[], n_samples=0, clear=True
            )
            return {
                "omicName":         omicName,
                "status":           "cleared",
                "mode":             mode,
                "sampleHeader":     [],
                "mapping":          [],
                "featuresUpdated":  n_touched,
                "featureType":      featureType,
            }

        if mode == "auto":
            detection = inputOmic.get("replicateDetection") or {}
            if detection.get("status") != "complete":
                raise ValueError(
                    "Auto-apply not possible for omic '%s' (detection status=%s)."
                    % (omicName, detection.get("status"))
                )
            sampleHeader = detection["sampleHeader"]
            mapping      = detection["mapping"]
            groups       = detection["groups"]
        elif mode == "manual":
            if not (sampleHeader and mapping is not None and groups is not None):
                raise ValueError("Manual apply requires sampleHeader, mapping and groups.")
        else:
            raise ValueError("Invalid mode '%s'." % mode)

        inputOmic["replicateSource"]   = mode
        inputOmic["sampleHeader"]      = sampleHeader
        inputOmic["replicateMapping"]  = mapping

        n_touched = self._walkAndAggregateOmicValues(
            featureDict, omicName,
            mapping=mapping, groups=groups, n_samples=len(sampleHeader),
            clear=False,
        )
        return {
            "omicName":         omicName,
            "status":           "applied",
            "mode":             mode,
            "sampleHeader":     sampleHeader,
            "mapping":          mapping,
            "featuresUpdated":  n_touched,
            "featureType":      featureType,
        }

    def _walkAndAggregateOmicValues(self, featureDict, omicName, mapping, groups,
                                    n_samples, clear):
        """
        Walk every Feature, find its OmicValue for ``omicName``, and either
        compute / clear ``sampleValues`` / ``sampleRelevant``. Returns the
        number of OmicValues touched.
        """
        n_touched = 0
        for feature in featureDict.values():
            for ov in feature.getOmicsValues():
                if ov.getOmicName() != omicName:
                    continue
                if clear:
                    ov.setSampleValues(None)
                    ov.setSampleRelevant(None)
                else:
                    sampleValues, sampleRelevant = aggregate_replicates(
                        values=ov.getValues() or [],
                        relevant=ov.relevant,
                        groups=groups,
                        n_samples=n_samples,
                    )
                    ov.setSampleValues(sampleValues)
                    ov.setSampleRelevant(sampleRelevant)
                n_touched += 1
        return n_touched

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
                # Replicate detection runs once per omic on the column labels
                # (omicHeader[1:] — index column stripped). Result is surfaced
                # to the Step-2 UI so the user can confirm/override; no
                # aggregation happens here, the values stay per-replicate.
                inputOmic["replicateDetection"] = self._detectReplicatesForOmic(omicName, omicHeader)
            logging.info("PROCESSING GENE BASED FILES...DONE")

            logging.info("PROCESSING COMPOUND BASED FILES...")
            checkBoxesData = []
            for inputOmic in self.compoundBasedInputOmics:
                [omicName, checkBoxesData, omicSummary, omicHeader] = self.parseCompoundBasedFile(inputOmic,
                                                                                                  checkBoxesData)
                logging.info("   * PROCESSED " + omicName + "...")
                inputOmic["omicSummary"] = omicSummary
                inputOmic["omicHeader"] = omicHeader
                inputOmic["replicateDetection"] = self._detectReplicatesForOmic(omicName, omicHeader)
            # REMOVE REPETITIONS AND ORDER ALPHABETICALLY
            # checkBoxesData = unifyAndSort(checkBoxesData, lambda checkBoxData: checkBoxData["title"].lower())
            checkBoxesData = unifyAndSort(checkBoxesData, lambda checkBoxData: checkBoxData.getTitle().lower())

            logging.info("PROCESSING COMPOUND BASED FILES...DONE")

            # AUTO-APPLY complete replicate detections so users get the
            # collapsed view without an extra click in Step 2. The Step-2 panel
            # still surfaces the detection (and the user can switch back to
            # "Show all replicates" or upload a custom design), but the default
            # is the average — most jobs with `_R1/_R2`-style headers want this.
            for inputOmic in (self.geneBasedInputOmics + self.compoundBasedInputOmics):
                detection = inputOmic.get("replicateDetection") or {}
                if detection.get("status") != "complete":
                    continue
                try:
                    res = self.applyReplicateMappingForOmic(inputOmic["omicName"], "auto")
                    logging.info(
                        "REPLICATE AUTO-APPLY (%s): %d sample(s), %d feature(s) updated.",
                        inputOmic["omicName"], len(res["sampleHeader"]), res["featuresUpdated"]
                    )
                except Exception as ex:
                    # Auto-apply must never break Step-1: log and continue, the
                    # user can still pick a mode in the Step-2 panel.
                    logging.warning(
                        "REPLICATE AUTO-APPLY (%s) failed: %s — continuing without aggregation.",
                        inputOmic.get("omicName"), str(ex)
                    )

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
        # if there is multi database make compounds available for both database
        if len(self.databases) >= 2:
            if "MapMan" in self.databases:
                for metabolite in self.inputCompoundsData:
                    self.inputCompoundsData[metabolite].matchingDB = ["KEGG", "MapMan"]
                    
                for gene_id in self.inputGenesData:
                    self.inputGenesData[gene_id].matchingDB = ["KEGG", "MapMan"]

            elif "Reactome" in self.databases:
                for metabolite in self.inputCompoundsData:
                    self.inputCompoundsData[metabolite].matchingDB = ["KEGG", "Reactome"]
                    
                for gene_id in self.inputGenesData:
                    self.inputGenesData[gene_id].matchingDB = ["KEGG", "Reactome"]
                    
        else:
            # make sure the database in the inputs is the as the one in the self.databases
            for compound in inputCompounds:
                compound.matchingDB = self.databases[0]
            for gene in inputGenes:
                gene.matchingDB = self.databases[0]

        self.inputCompunds = inputCompounds

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
            thread = Process(target=_matchPathways, args=(
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
                threadClass = Process( target=_matchPathways, args=(
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

        pvalues_list = defaultdict(dict)
        combined_pvalues_list = defaultdict(dict)

        for pathway_id, pathway in self.getMatchedPathways().items():
            for omic, pvalue in pathway.getSignificanceValues().items():
                # Multi-condition support: use global p-value if available, else first condition
                globalP = pathway.getGlobalOmicPvalues().get(omic)
                if globalP is not None:
                    pvalues_list[omic][pathway_id] = globalP
                elif len(pvalue) > 0:
                    pvalues_list[omic][pathway_id] = pvalue[0][2]
                else:
                    pvalues_list[omic][pathway_id] = 1.0

            for method, combined_pvalue in pathway.getCombinedSignificancePvalues().items():
                if not isinstance(combined_pvalue, list):
                    combined_pvalue = [combined_pvalue]
                nCond = len(combined_pvalue)
                for c in range(nCond):
                    combined_pvalues_list[method + "_c" + str(c)][pathway_id] = combined_pvalue[c]

        adjusted_pvalues = {omic: adjustPvalues(omicPvalues) for omic, omicPvalues in pvalues_list.items()}
        
        adjusted_combined_pvalues = {}
        for method_cond, methodPvalues in combined_pvalues_list.items():
            adjusted_combined_pvalues[method_cond] = adjustPvalues(methodPvalues)

        # Set the adjusted p-value on a pathway basis
        for pathway_id, pathway in self.getMatchedPathways().items():
            # Update omic adjusted p-values (using global/first condition as before)
            for omic, pvalue in pathway.getSignificanceValues().items():
                pathway.setOmicAdjustedSignificanceValues(omic,
                                                          {adjust_method: pvalues[pathway_id] for adjust_method, pvalues
                                                           in adjusted_pvalues[omic].items()})

            # Update combined adjusted p-values per condition.
            # Storage shape: pathway.adjustedCombinedSignificanceValues[method][adjMethod]
            #   - scalar (single-condition jobs) — preserved for back-compat with old jobs.
            #   - list[float] (multi-condition jobs) — one entry per condition, ordered by
            #     condition index. Frontend (PA_Step3Views.js:3515-3520) accepts both shapes
            #     and emits per-condition keys when a list is detected.
            for method, combined_pvalue in pathway.getCombinedSignificancePvalues().items():
                if not isinstance(combined_pvalue, list):
                    combined_pvalue = [combined_pvalue]
                nCond = len(combined_pvalue)

                first_cond_key = method + "_c0"
                if first_cond_key not in adjusted_combined_pvalues:
                    continue
                adj_methods = adjusted_combined_pvalues[first_cond_key].keys()
                if nCond == 1:
                    # Single-condition: keep scalars (back-compat).
                    pathway.setMethodAdjustedCombinedSignificanceValues(method, {
                        adj: adjusted_combined_pvalues[first_cond_key][adj][pathway_id]
                        for adj in adj_methods
                    })
                else:
                    # Multi-condition: per-condition list, padded with 1.0 if a condition
                    # had no entry in adjusted_combined_pvalues.
                    pathway.setMethodAdjustedCombinedSignificanceValues(method, {
                        adj: [
                            adjusted_combined_pvalues.get(method + "_c" + str(c), {})
                                                    .get(adj, {})
                                                    .get(pathway_id, 1.0)
                            for c in range(nCond)
                        ]
                        for adj in adj_methods
                    })

        logging.info("SUMMARY: " + str(totalMatchedKeggPathways) + " Matched Pathways of " + str(
            totalKeggPathways) + "in KEGG; Total input Genes = " + str(
            totalInputMatchedGenes) + "; SUMMARY: Total input Compounds  = " + str(totalInputMatchedCompounds))

        for key in totalFeaturesByOmic:
            logging.info("SUMMARY: Total " + key + " Features = " + str(totalFeaturesByOmic.get(key)))
            logging.info("SUMMARY: Total " + key + " Relevant Features = " + str(totalRelevantFeaturesByOmic.get(key)))

        # PaintOmics 4
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

        # Determine the maximum number of conditions across all omics
        max_conditions = 1
        for feature in chain(self.getInputCompoundsData().values(), self.getInputGenesData().values()):
            for ov in feature.getOmicsValues():
                if isinstance(ov.relevant, list):
                    max_conditions = max(max_conditions, len(ov.relevant))
        
        has_multi_cond = max_conditions > 1

        # counterNames[db][omicName][featureID] = [isRelevant_C1, isRelevant_C2, ...]
        counterNames = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

        # Total features depends on the source DB
        totalFeatures = {dbSource: dbGenes.union(totalCompounds.get(dbSource)) for dbSource, dbGenes in
                         totalGenes.items()}

        for feature in chain(self.getInputCompoundsData().values(), self.getInputGenesData().values()):
            # Count only those present in at least one pathway
            if type(feature.getMatchingDB()) is str:
                dbList = [feature.getMatchingDB()]
            else:
                dbList = feature.getMatchingDB()
            found_in_any_db = False
            for db in dbList:
                db_features = totalFeatures.get(db, set())
                if feature.getID() in db_features or feature.getName() in db_features:
                    found_in_any_db = True
                    for omicValue in feature.getOmicsValues():
                        # Select the appropriate enrichment property
                        enrichmentType = enrichmentByOmic[omicValue.getOmicName()]
                        enrichmentProperty = enrichments.get(enrichmentType)(omicValue).lower()

                        # relevantValue is now a list [True, False, ...]
                        relevantValue = [omicValue.isRelevantAssociation()] if enrichmentType == 'associations' else omicValue.relevant
                        if not isinstance(relevantValue, list):
                            relevantValue = [relevantValue]
                        elif len(relevantValue) == 0:
                            relevantValue = [False] * max_conditions
                        
                        if not has_multi_cond:
                            # Scalar fast-path
                            is_rel = relevantValue[0]
                            old_val = counterNames[db][omicValue.getOmicName()].get(feature.getID())
                            if old_val is None:
                                counterNames[db][omicValue.getOmicName()][feature.getID()] = is_rel
                            else:
                                counterNames[db][omicValue.getOmicName()][feature.getID()] = old_val or is_rel
                        else:
                            # List-based multi-condition path
                            if not isinstance(relevantValue, list):
                                relevantValue = [relevantValue]

                            old_val = counterNames[db][omicValue.getOmicName()].get(feature.getID())
                            if not old_val:
                                counterNames[db][omicValue.getOmicName()][feature.getID()] = list(relevantValue)
                            else:
                                # Combine lists with OR logic
                                nCond = max(len(old_val), len(relevantValue))
                                combined = [False] * nCond
                                for i in range(nCond):
                                    v1 = old_val[i] if i < len(old_val) else False
                                    v2 = relevantValue[i] if i < len(relevantValue) else False
                                    combined[i] = v1 or v2
                                counterNames[db][omicValue.getOmicName()][feature.getID()] = combined

                        if db == 'KEGG':
                            totalFeaturesID.add(feature.getID())
                            is_any_rel = any(relevantValue) if isinstance(relevantValue, list) else relevantValue
                            if is_any_rel:
                                totalFeaturesIDSig.add(feature.getID())
            if not found_in_any_db:
                logging.error("STEP2 - Feature not present in at least one pathway " + feature.getID())

        for sourceDB, countersDB in counterNames.items():
            for omicName, featureRelevanceLists in countersDB.items():
                totalFeaturesByOmic[sourceDB][omicName] = len(featureRelevanceLists.keys())
                
                # Calculate counts per condition
                all_vals = list(featureRelevanceLists.values())
                if not all_vals:
                    totalRelevantFeaturesByOmic[sourceDB][omicName] = []
                    continue

                if not has_multi_cond:
                    # Scalar fast-path: sum the booleans
                    totalRelevantFeaturesByOmic[sourceDB][omicName] = [sum(all_vals)]
                else:
                    # List-based multi-condition path
                    nConditions = max((len(v) for v in all_vals if isinstance(v, list)), default=1)
                    condition_counts = [0] * nConditions
                    for rel_val in all_vals:
                        if isinstance(rel_val, list):
                            for i in range(min(nConditions, len(rel_val))):
                                if rel_val[i]:
                                    condition_counts[i] += 1
                        elif rel_val:
                            condition_counts[0] += 1
                    totalRelevantFeaturesByOmic[sourceDB][omicName] = condition_counts

        return totalFeaturesByOmic, totalRelevantFeaturesByOmic

    def testPathwaySignificance(self, genesInPathway, compoundsInPathway, inputGenesDict, inputCompoundsDict,
                                totalFeaturesByOmic, totalRelevantFeaturesByOmic, mappedRatiosByOmic, enrichmentByOmic,
                                sourceDB, has_multi_cond):
        """
        This function takes a list of genes and compounds from the input and check if those features are at the
        list of feautures involved into a specific pathway.
        After that, the function calculates the significance for each omic type for the current pathway

        @param {List} genesInPathway, list of gene IDs in the pathway (ordered)
        @param {List} compoundsInPathway, list of compound IDs in the pathway (ordered)
        @param {Dict} inputGenesDict, dictionary of genes (class Gene) indexed by lowercase ID
        @param {Dict} inputCompoundsDict, dictionary of compounds (class Compound) indexed by lowercase ID
        @param {Dict} totalFeaturesByOmic, contains the total features for each omic type (for statistics)
        @param {Dict} totalRelevantFeaturesByOmic, contains the total relevant features for each omic type (for statistics)
        @param {Boolean} has_multi_cond, True if the job has multiple experimental conditions
        @returns {Boolean} isValidPathway, True if at least one feature was matched, False in other cases.
        @returns {Pathway} pathwayInstance a new Pathway instance containing the matched info. None if pathway is not valid.
        """
        isValidPathway = False
        pathwayInstance = Pathway("")

        # Derive max_conditions from totalRelevantFeaturesByOmic for proper padding
        max_conditions = max(
            (len(v) for v in (totalRelevantFeaturesByOmic or {}).values() if isinstance(v, list)),
            default=1
        )

        # counterNames[omicName][enrichmentProperty] = [isRelevant_C1, isRelevant_C2, ...]
        counterNames = defaultdict(lambda: defaultdict(list))

        # Three enrichment methods available: gene, feature and association enrichment.
        # By default use gene enrichment unless specified otherwise.
        enrichments = {
            'genes': lambda x: x.getInputName(),
            'features': lambda x: x.getOriginalName(),
            'associations': lambda x: ':::'.join([x.getInputName(), x.getOriginalName()])
        }

        # TODO: RETURN AS A SET IN KEGG INFORMATION MANAGER
        genesInPathway = set([x.lower() for x in genesInPathway])
        
        # Iterate over genes in pathway instead of all input genes
        for geneID in genesInPathway:
            gene = inputGenesDict.get(geneID)
            if gene:
                matchingDB = gene.getMatchingDB()
                db_matches = sourceDB in matchingDB if isinstance(matchingDB, list) else matchingDB == sourceDB
                if db_matches:
                    isValidPathway = True
                    pathwayInstance.addMatchedGeneID(gene.getID())
                    for omicValue in gene.getOmicsValues():
                        enrichmentType = enrichmentByOmic[omicValue.getOmicName()]
                        enrichmentProperty = enrichments.get(enrichmentType)(omicValue).lower()

                        # relevantValue is now a list [True, False, ...]
                        relevantValue = [omicValue.isRelevantAssociation()] if enrichmentType == 'associations' else omicValue.relevant
                        if not isinstance(relevantValue, list):
                            relevantValue = [relevantValue]
                        elif len(relevantValue) == 0:
                            relevantValue = [False] * max_conditions

                        if not has_multi_cond:
                            # Scalar fast-path
                            is_rel = relevantValue[0]
                            old_val = counterNames[omicValue.getOmicName()].get(enrichmentProperty)
                            if old_val is None:
                                counterNames[omicValue.getOmicName()][enrichmentProperty] = is_rel
                            else:
                                counterNames[omicValue.getOmicName()][enrichmentProperty] = old_val or is_rel
                        else:
                            # List-based multi-condition path
                            old_val = counterNames[omicValue.getOmicName()].get(enrichmentProperty)
                            if not old_val:
                                counterNames[omicValue.getOmicName()][enrichmentProperty] = list(relevantValue)
                            else:
                                nCond = max(len(old_val), len(relevantValue))
                                combined = [False] * nCond
                                for i in range(nCond):
                                    v1 = old_val[i] if i < len(old_val) else False
                                    v2 = relevantValue[i] if i < len(relevantValue) else False
                                    combined[i] = v1 or v2
                                counterNames[omicValue.getOmicName()][enrichmentProperty] = combined

        # First we get the list of IDs for the compounds that participate in the pathway
        compoundsInPathway = set([x.lower() for x in compoundsInPathway])

        for compoundID in compoundsInPathway:
            compound = inputCompoundsDict.get(compoundID)
            if compound:
                # Check if the compound participates in the pathway safely (using list support)
                matchingDB = compound.getMatchingDB()
                db_matches = sourceDB in matchingDB if isinstance(matchingDB, list) else matchingDB == sourceDB
                
                if db_matches:
                    isValidPathway = True
                    pathwayInstance.addMatchedCompoundID(compound.getID())

                    for omicValue in compound.getOmicsValues():
                        enrichmentType = enrichmentByOmic[omicValue.getOmicName()]
                        enrichmentProperty = enrichments.get(enrichmentType)(omicValue).lower()

                        relevantValue = [omicValue.isRelevantAssociation()] if enrichmentType == 'associations' else omicValue.relevant
                        if not isinstance(relevantValue, list):
                            relevantValue = [relevantValue]
                        elif len(relevantValue) == 0:
                            relevantValue = [False] * max_conditions

                        if not has_multi_cond:
                            # Scalar fast-path
                            is_rel = relevantValue[0]
                            old_val = counterNames[omicValue.getOmicName()].get(enrichmentProperty)
                            if old_val is None:
                                counterNames[omicValue.getOmicName()][enrichmentProperty] = is_rel
                            else:
                                counterNames[omicValue.getOmicName()][enrichmentProperty] = old_val or is_rel
                        else:
                            # List-based multi-condition path
                            old_val = counterNames[omicValue.getOmicName()].get(enrichmentProperty)
                            if not old_val:
                                counterNames[omicValue.getOmicName()][enrichmentProperty] = list(relevantValue)
                            else:
                                nCond = max(len(old_val), len(relevantValue))
                                combined = [False] * nCond
                                for i in range(nCond):
                                    v1 = old_val[i] if i < len(old_val) else False
                                    v2 = relevantValue[i] if i < len(relevantValue) else False
                                    combined[i] = v1 or v2
                                counterNames[omicValue.getOmicName()][enrichmentProperty] = combined

        for omicName, featureNames in counterNames.items():
            for rel_val in featureNames.values():
                pathwayInstance.addSignificanceValues(omicName, rel_val)

        if isValidPathway:
            # print(f"DEBUG: Pathway {pathwayInstance.getID()} sig values: {pathwayInstance.getSignificanceValues()}")
            # significanceValues format: OmicName -> [[totalMatched, totalRelevant, pValue], ...] (one per condition)
            for omicName, conditionValues in pathwayInstance.getSignificanceValues().items():
                pvalues_per_condition = []
                total_features = totalFeaturesByOmic.get(omicName, 0)
                total_relevant_list = totalRelevantFeaturesByOmic.get(omicName, [])

                # Optimization: if single condition, just do one calculation
                if not has_multi_cond:
                    total_relevant_cond = total_relevant_list[0] if total_relevant_list else 0
                    val = conditionValues[0]
                    pValue = calculateSignificance(self.getTest(), total_features, total_relevant_cond, val[0], val[1])
                    pvalues_per_condition = [pValue]
                else:
                    for i, values in enumerate(conditionValues):
                        total_relevant_cond = total_relevant_list[i] if i < len(total_relevant_list) else 0
                        
                        pValue = calculateSignificance(self.getTest(),
                                                       total_features,
                                                       total_relevant_cond,
                                                       values[0], # totalMatched in pathway
                                                       values[1]) # totalRelevant in pathway for this condition
                        pvalues_per_condition.append(pValue)

                pathwayInstance.setSignificancePvalue(omicName, pvalues_per_condition)
                
                # Global Omic P-value: combine p-values from all conditions
                if pvalues_per_condition:
                    if not has_multi_cond:
                        pathwayInstance.setGlobalOmicPvalue(omicName, pvalues_per_condition[0])
                    else:
                        # We use uniform weights for conditions
                        weights_cond = [1] * len(pvalues_per_condition)
                        globalP_dict = calculateCombinedSignificancePvalues(pvalues_per_condition, weights_cond)
                        pathwayInstance.setGlobalOmicPvalue(omicName, globalP_dict.get("Fisher", 1.0))

            # Cross-Omic Integration PER CONDITION
            omicSignificanceValues = pathwayInstance.getSignificanceValues()
            keyOrder = list(omicSignificanceValues.keys())
            
            if keyOrder:
                nConditions = len(omicSignificanceValues[keyOrder[0]])
                combined_pvalues_per_condition = defaultdict(list)
                
                # Integration optimization
                if not has_multi_cond:
                    omicPvalues_cond = [omicSignificanceValues[omicName][0][2] for omicName in keyOrder]
                    weights_cond = [mappedRatiosByOmic.get(omicName, 0) for omicName in keyOrder]
                    integratedP_dict = calculateCombinedSignificancePvalues(omicPvalues_cond, weights_cond)
                    for method, val in integratedP_dict.items():
                        combined_pvalues_per_condition[method] = [val]
                else:
                    for i in range(nConditions):
                        omicPvalues_cond = []
                        weights_cond = []
                        for omicName in keyOrder:
                            if i < len(omicSignificanceValues[omicName]):
                                omicPvalues_cond.append(omicSignificanceValues[omicName][i][2])
                            else:
                                omicPvalues_cond.append(1.0)
                            weights_cond.append(mappedRatiosByOmic.get(omicName, 0))
                        
                        integratedP_dict = calculateCombinedSignificancePvalues(omicPvalues_cond, weights_cond)
                        for method, val in integratedP_dict.items():
                            combined_pvalues_per_condition[method].append(val)
                
                pathwayInstance.setCombinedSignificancePvalues(combined_pvalues_per_condition)

                # Step 4.1: Total Global P-value (Combine global p-values of each omic)
                globalOmicPvalues = pathwayInstance.getGlobalOmicPvalues()
                if globalOmicPvalues:
                    globalKeyOrder = list(globalOmicPvalues.keys())
                    globalWeights = [mappedRatiosByOmic.get(omicName, 0) for omicName in globalKeyOrder]
                    globalPvalues = [globalOmicPvalues[omicName] for omicName in globalKeyOrder]
                    
                    totalGlobalP_dict = calculateCombinedSignificancePvalues(globalPvalues, globalWeights)
                    pathwayInstance.setTotalGlobalPvalues(totalGlobalP_dict)

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
            # STEP 2.1 EXECUTE THE R SCRIPT FOR EACH DATABASE
            for dbname in filtered_databases:
                try:
                    logging.info("GENERATING METAGENES INFORMATION FOR " + str(dbname) + "...CALLING")
                    inputFile = self.getTemporalDir() + "/" + inputOmic.get("omicName") + '_matched.txt'
                    # Select number of clusters, default to dynamic

                    kClusters = str(dict(clusterNumber).get(inputOmic.get("omicName"), "dynamic"))
                    logging.info("kClusters=" + str(kClusters))
                    logging.info(str(ROOT_DIRECTORY))

                    logging.info("dbname is " + str(dbname))

                    try:
                        output = check_output([
                            "Rscript",
                            ROOT_DIRECTORY + "common/bioscripts/generateMetaGenes.R",
                            '--specie=' + self.getOrganism(),
                            '--input_file=' + inputFile,
                            '--output_prefix=' + inputOmic.get("omicName"),
                            '--data_dir=' + self.getTemporalDir(),
                            '--kegg_dir=' + KEGG_DATA_DIR,
                            '--sources_dir=' + ROOT_DIRECTORY + 'common/bioscripts/',
                            '--kclusters=' + kClusters if kClusters.isdigit() else '',
                            '--database=' + dbname if dbname != "KEGG" else ''], stderr=STDOUT)
                    except CalledProcessError as ex:
                        error_detail = ex.output.decode('utf-8') if ex.output else str(ex)
                        logging.error("STEP2 - Error while generating metagenes information for " + inputOmic.get("omicName") + " db: " + str(dbname))
                        logging.error(f"Subprocess output: {error_detail}")
                        raise RuntimeError(f"Metagenes generation failed for omic '{inputOmic.get('omicName')}' and database '{dbname}'. Details: {error_detail}")

                    # STEP 2.2 PROCESS THE RESULTING FILE

                    # Reset all pathways metagenes for the omic
                    for pathway in self.matchedPathways.values():
                        # Only reset metagenes for current DB
                        if pathway.getSource().lower() == str(dbname).lower():
                            pathway.resetMetagenes(inputOmic.get("omicName"))

                    metagenesFileName: object = self.getTemporalDir() + "/" + inputOmic.get("omicName") + "_metagenes" + \
                                                ("_" + str(dbname).lower() + ".tab" if dbname != "KEGG" else ".tab")

                    if os_path.exists(metagenesFileName):
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
                    else:
                        logging.warning(f"Metagenes file {metagenesFileName} not found. This is expected if no matches were found for db {dbname}.")

                except IOError as ex:
                    logging.error("STEP2 - File not found or read error for metagenes " + inputOmic.get("omicName") + " db: " + str(dbname))


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
            elif attr in PAINTOMICS4_DICT_FIELDS or attr in PAINTOMICS4_LARGE_FIELDS:
                setattr(self, attr, value)
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

            elif attr in PAINTOMICS4_DICT_FIELDS:
                # Ensure all dict keys are strings for MongoDB compatibility
                if isinstance(value, dict):
                    bson[attr] = {str(k): v for k, v in value.items()}
                else:
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

    def compundsClassification(self,metaboliteClassThreshold):

        import json, os
        from collections import defaultdict

        brPath = os.path.dirname(__file__) + "/../../common/br08001.json"
        interactionJSONPath = os.path.join(KEGG_DATA_DIR, "current", self.organism, "hubData", "kegg_interaction.json")

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
        
        # Determine number of conditions
        nConditions = 1
        for feature in self.inputCompoundsData.values():
            if feature.omicsValues and isinstance(feature.omicsValues[0].relevant, list):
                nConditions = max(nConditions, len(feature.omicsValues[0].relevant))
        
        # totalRelevantFeaturesInCategory[conditionIndex][category] = count
        totalRelevantFeaturesInCategory_cond = [defaultdict(int) for _ in range(nConditions)]
        # pValueInDict[conditionIndex][category] = pValue
        pValueInDict_cond = [{} for _ in range(nConditions)]

        for key, items in classificationDict.items():
            totalFeaturesInCategory[key] = len(items)
            for item in items:
                comp = self.inputCompoundsData.get(item)
                if comp and comp.omicsValues:
                    rel = comp.omicsValues[0].relevant
                    if not isinstance(rel, list):
                        rel = [rel]
                    for c in range(min(nConditions, len(rel))):
                        if rel[c]:
                            totalRelevantFeaturesInCategory_cond[c][key] += 1

        totalRelevantFeatures_cond = [sum(counts.values()) for counts in totalRelevantFeaturesInCategory_cond]

        from scipy import stats
        threshold = metaboliteClassThreshold.get("thresholdMetaboliteClass")
        if threshold:
            try:
                threshold = float(threshold)
            except:
                threshold = None

        for c in range(nConditions):
            totalRel = totalRelevantFeatures_cond[c]
            for key in classificationDict:
                try:
                    if threshold and 0 < threshold <= 1:
                        p_param = threshold
                    else:
                        p_param = totalRel / totalFeatures if totalFeatures > 0 else 0
                    
                    pValueInDict_cond[c][key] = stats.binomtest(
                        totalRelevantFeaturesInCategory_cond[c].get(key, 0),
                        n=totalFeaturesInCategory.get(key),
                        p=p_param, alternative='greater').pvalue
                except Exception as e:
                    pValueInDict_cond[c][key] = 1.0

        featureSummary = [totalFeatures, totalRelevantFeatures_cond]

        # adjustPvalue[conditionIndex] = {category: adjustedPValue}
        adjustPvalue_cond = [adjustPvalues(p_dict) for p_dict in pValueInDict_cond]

        for c in range(nConditions):
            for method, items in adjustPvalue_cond[c].items():
                for item in items:
                    adjustPvalue_cond[c][method][item] = round(items[item], 4)

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

        self.mappingComp = dict(mappingComp)
        # For multi-condition, we store the lists/dicts of per-condition data
        self.pValueInDict = pValueInDict_cond
        self.classificationDict = dict(classificationDict)
        self.exprssionMetabolites = dict(exprssionMetabolites)
        self.adjustPvalue = adjustPvalue_cond
        self.totalRelevantFeaturesInCategory = totalRelevantFeaturesInCategory_cond
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
                'relevant': self.inputCompoundsData[j].omicsValues[0].relevant,
                'relevantAssociation': self.inputCompoundsData[j].omicsValues[0].relevantAssociation,
                'values': self.inputCompoundsData[j].omicsValues[0].values
            }
            globalExpressionDataComp[expressionID] = expressionDetail

        for i in self.inputGenesData:
            expressionID = self.inputGenesData[i].ID
            expressionDetail = {
                'keggName': self.inputGenesData[i].name,
                'inputName': self.inputGenesData[i].omicsValues[0].inputName,
                'originalName': self.inputGenesData[i].omicsValues[0].originalName,
                'relevant': self.inputGenesData[i].omicsValues[0].relevant,
                'relevantAssociation': self.inputGenesData[i].omicsValues[0].relevantAssociation,
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
