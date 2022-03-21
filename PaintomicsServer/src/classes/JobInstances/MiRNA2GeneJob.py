#***************************************************************
#  This file is part of PaintOmics 3
#
#  PaintOmics 3 is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  PaintOmics 3 is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with PaintOmics 3.  If not, see <http://www.gnu.org/licenses/>.
#  Contributors:
#     Rafael Hernandez de Diego <paintomics4@outlook.com>
#     Ana Conesa Cegarra
#     and others
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomics4@outlook.com
#
#**************************************************************

import logging

from src.classes.Job import Job
from src.classes.Feature import OmicValue, Gene
from src.servlets.DataManagementServlet import copyFile
from src.common.bioscripts.miRNA2Target import run as run_miRNA2Target

from os import path as os_path, mkdir as os_mkdir
from csv import reader as csv_reader
from random import randint
from collections import defaultdict
import shutil
from src.conf.serverconf import MAX_NUMBER_FEATURES

class MiRNA2GeneJob(Job):
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, jobID, userID, CLIENT_TMP_DIR):
        super(MiRNA2GeneJob, self).__init__(jobID, userID, CLIENT_TMP_DIR)
        self.omicName = None
        self.report               = "all" #all or DE
        self.score_method         = "kendall" #fc OR kendall OR spearman OR pearson
        self.selection_method     = "negative_correlation" #max_fc OR similar_fc OR abs_correlation OR positive_correlation OR negative_correlation
        self.cutoff               = -0.6
        self.enrichment           = "genes"

    def getOptions(self):
        return {
            "report": self.report,
            "score_method": self.score_method,
            "selection_method": self.selection_method,
            "cutoff": self.cutoff
        }

    def getJobDescription(self, generate=False, dataFile="", relevantFile="", targetsFile="", geneExpressionFile=""):
        if generate:
            self.description  = "Input data:" + os_path.basename(dataFile) + ";Relevant file: " + os_path.basename(relevantFile)  + ";Targets file: " + os_path.basename(targetsFile) + ";Gene expression file: " + os_path.basename(geneExpressionFile) + ";"
            self.description += "Params:;Report=" + str(self.report) + ";"
            self.description += "Score method=" + str(self.score_method)+ ";"
            self.description += "Selection method=" + str(self.selection_method)+ ";"
            self.description += "Cutoff=" + str(self.cutoff)+ ";"
        return self.description

    def validateInput(self):
        """
        This function check the content for files and returns an error message in case of invalid content

        @returns True if not error
        """
        error = ""
        #TODO: CHECK VALID SCORE AND SELECTION METHODS
        try:
            self.cutoff = float(self.cutoff)
        except:
            error +=  " -  Cutoff must be a numeric value"

        # Look using the name instead of relying in the dictionary order
        geneDataInputs = self.getGeneBasedInputOmics()

        miRNAdataInput = next((x for x in geneDataInputs if x["omicName"].lower() != "gene expression"))

        logging.info("VALIDATING miRNA-seq BASED FILES..." )
        nConditions, error = self.validateFile(miRNAdataInput, -1, error)

        if len(geneDataInputs) > 1:
            logging.info("VALIDATING RNA-seq BASED FILES..." )
            RNAdataInput = next((x for x in geneDataInputs if x["omicName"].lower() == "gene expression"))
            nConditions, error = self.validateFile(RNAdataInput, nConditions, error)

        if error != "":
            raise Exception("Errors detected in input files, please fix the following issues and try again:" + error)

        return True

    def validateFile(self, inputOmic, nConditions, error):
        """
        This function...

        @param {type}
        @returns
        """
        valuesFileName= inputOmic.get("inputDataFile")
        relevantFileName= inputOmic.get("relevantFeaturesFile", "")
        omicName = inputOmic.get("omicName")

        if inputOmic.get( "isExample", False ):
            return nConditions, error
        else:
            valuesFileName = "{path}/{file}".format(path=self.getInputDir(), file=valuesFileName)
            relevantFileName = "{path}/{file}".format(path=self.getInputDir(), file=relevantFileName)

        #*************************************************************************
        # STEP 1. VALIDATE THE RELEVANT FEATURES FILE
        #*************************************************************************
        logging.info("VALIDATING RELEVANT FEATURES FILE (" + omicName + ")..." )
        if os_path.isfile(relevantFileName):
            f = open(relevantFileName, 'rU')
            lines = f.readlines()

            if len(lines) > MAX_NUMBER_FEATURES:
                error += " - Errors detected while processing " + inputOmic.get("relevantFeaturesFile", "") + ": The file exceeds the maximum number of features allowed (" + str(MAX_NUMBER_FEATURES) + ")." + "\n"

            for line in lines:
                if len(line) > 80:
                    error +=  " - Errors detected while processing " + inputOmic.get("relevantFeaturesFile", "") + ": The file does not look like a Relevant Features file (some lines are longer than 80 characters)." + "\n"
                    break
            f.close()

        #*************************************************************************
        # STEP 2. VALIDATE THE VALUES FILE
        #*************************************************************************
        logging.info("VALIDATING VALUES FILE (" + omicName + ")..." )

        #IF THE USER UPLOADED VALUES FOR GENE EXPRESSION
        if os_path.isfile(valuesFileName):
            with open(valuesFileName, 'rU') as inputDataFile:
                nLine = -1
                erroneousLines = {}

                for line in csv_reader(inputDataFile, delimiter="\t"):
                    nLine = nLine+1
                    #TODO: HACER ALGO CON EL HEADER?
                    #*************************************************************************
                    # STEP 2.1 CHECK IF IT IS HEADER, IF SO, IGNORE LINE
                    #*************************************************************************
                    if(nLine == 0):
                        try:
                            float(line[1])
                        except Exception:
                            continue

                    if nConditions == -1:
                        if len(line) < 2:
                            erroneousLines[nLine] =  "Expected at least 2 columns, but found one."
                            break
                        nConditions = len(line)

                    # *************************************************************************
                    # STEP 2.2 CHECK IF IT EXCEEDS THE MAX NUMBER OF FEATURES ALLOWED
                    # *************************************************************************
                    if (nLine > MAX_NUMBER_FEATURES):
                        error += " - Errors detected while processing " + inputOmic.get("inputDataFile", "") + ": The file exceeds the maximum number of features allowed (" + str(MAX_NUMBER_FEATURES) + ")." + "\n"
                        break

                    #**************************************************************************************
                    # STEP 2.3 IF LINE LENGTH DOES NOT MATCH WITH EXPECTED NUMBER OF CONDITIONS, ADD ERROR
                    #**************************************************************************************
                    if(nConditions != len(line) and len(line)>0):
                        erroneousLines[nLine] = "Expected " +  str(nConditions) + " columns but found " + str(len(line)) + ";"

                    #**************************************************************************************
                    # STEP 2.4 IF CONTAINS NOT VALID VALUES, ADD ERROR
                    #**************************************************************************************
                    try:
                        map(float, line[1:len(line)])
                    except:
                        if(" ".join(line[1:len(line)]).count(",") > 0):
                            erroneousLines[nLine] = erroneousLines.get(nLine,  "") + "Perhaps you are using commas instead of dots as decimal mark?"
                        else:
                            erroneousLines[nLine] = erroneousLines.get(nLine,  "") + "Line contains invalid values or symbols."

                    if len(erroneousLines)  > 9:
                        break

            inputDataFile.close()

            #*************************************************************************
            # STEP 3. CHECK THE ERRORS AND RETURN
            #*************************************************************************
            if len(erroneousLines)  > 0:
                error += " - Errors detected while processing " + inputOmic.get("inputDataFile") + ":\n"
                error += "[ul]"
                for k in sorted(erroneousLines.keys()):
                    error+=  "[li]Line " + str(k) + ":" + erroneousLines.get(k) + "[/li]"
                error += "[/ul]"

                if len(erroneousLines)  > 9:
                    error +=  "Too many errors detected while processing " + inputOmic.get("inputDataFile") + ", skipping remaining lines...\n"
        else:
            error += " - Error while processing " + omicName + ": File " + inputOmic.get("inputDataFile") + "not found.\n"

        return nConditions, error

    ##*************************************************************************************************************
    # This function...
    #
    # @param {type}
    # @returns
    ##*************************************************************************************************************
    def fromMiRNA2Genes(self):
        #STEP 1. GET THE FILES PATH AND PREPRARE THE OPTIONS
        logging.info("READING FILES...")

        #inputRef = self.getReferenceInputs()[0]

        #referenceFile = self.getReferenceInputs()[0].get("inputDataFile")
        #if not inputRef.get( "isExample", False ):
        #    referenceFile = "{path}/{file}".format(path=self.getInputDir(), file=referenceFile)

        #relevantReferenceFile = self.getReferenceInputs()[0].get("inputDataFile", None)
        #if not inputRef.get( "isExample", False ):
        #    relevantReferenceFile = "{path}/{file}".format(path=self.getInputDir(), file=relevantReferenceFile)



        geneDataInputs = self.getGeneBasedInputOmics()

        miRNAinputOmic = next((x for x in geneDataInputs if x["omicName"].lower() != "gene expression"))
        referenceFile = miRNAinputOmic.get('associationsFile')
        if referenceFile != '':
            referenceFile = "{path}/{file}".format( path=self.getInputDir(), file=referenceFile )
            if not os_path.isfile( referenceFile ):
                raise Exception( "Reference file not found." )


        relevantReferenceFile = miRNAinputOmic.get('relevantAssociationsFile')
        if relevantReferenceFile != '':
            relevantReferenceFile = "{path}/{file}".format( path=self.getInputDir(), file=relevantReferenceFile )
            if relevantReferenceFile and not os_path.isfile( relevantReferenceFile ):
                raise Exception( "Relevant reference file not found." )

        dataFile = miRNAinputOmic.get("inputDataFile")
        relevantFile = miRNAinputOmic.get("relevantFeaturesFile")
        relevantFileRaw = relevantFile
        geneExpressionFile =  None
        if len(geneDataInputs) > 1:
            RNAinputOmic = next((x for x in geneDataInputs if x["omicName"].lower() == "gene expression"))
            geneExpressionFile = RNAinputOmic.get("inputDataFile")

        if not miRNAinputOmic.get( "isExample", False ):
            dataFile = "{path}{file}".format(path=self.getInputDir(), file=dataFile)
            relevantFile = "{path}{file}".format(path=self.getInputDir(), file=relevantFile)
            if geneExpressionFile is not None:
                geneExpressionFile = "{path}{file}".format(path=self.getInputDir(), file=geneExpressionFile)

        if not os_path.isdir(self.getTemporalDir()):
            os_mkdir(self.getTemporalDir())

        tmpFile = self.getTemporalDir() +"/miRNAMatch_output.txt"

        #STEP 2. CALL TO miRNA2Target SCRIPT AND GENERATE ASSOCIATION BETWEEN miRNAS AND TARGET GENES
        logging.info("STARTING miRNA2Target PROCESS.")
        run_miRNA2Target(referenceFile, relevantReferenceFile, dataFile, geneExpressionFile, tmpFile, self.score_method)
        logging.info("STARTING miRNA2Target PROCESS...Done")

        #STEP 3. PARSE RELEVANT FILE
        logging.info("PROCESSING RELEVANT FEATURES FILE...")
        relevantMiRNAS = self.parseSignificativeFeaturesFile(relevantFile, isBedFormat=False)
        logging.info("PROCESSING RELEVANT FEATURES FILE...DONE")

        # STEP 3.2. PARSE RELEVANT ASSOCIATIONS FILE
        relevantAssociations = {}

        if relevantReferenceFile:
            logging.info("PROCESSING RELEVANT ASSOCIATIONS FILE...")
            relevantAssociations = self.parseSignificativeFeaturesFile(relevantReferenceFile, isBedFormat=False)
            logging.info("PROCESSING RELEVANT ASSOCIATIONS FILE...DONE")

        #STEP 4. PARSE GENERATED TEMPORAL FILE, GET THE MIRNAS, TARGET GENES AND QUANTIFICATION
        logging.info("PROCESSING miRNA2Target OUTPUT...")

        # If no relevant associations file was provided, the script must generate one using
        # the correlation settings.
        useCorrelation = relevantReferenceFile is None or relevantReferenceFile == ""

        if os_path.isfile(tmpFile):
             with open(tmpFile, 'rU') as inputDataFile:
                mirnaID = geneID = score = methodsHasChanged = score_type = sortedScores = None
                scoresTable = defaultdict(list)

                csvReader = csv_reader(inputDataFile, delimiter="\t")

                #READ THE HEADER
                line = next(csvReader)
                #SAVE THE NAME OF THE CONDITIONS (e.g. COND1, COND2,...)
                header = "\t".join(line[4:])

                if self.selection_method == "negative_correlation":
                    self.cutoff *= -1 #INVERT VALUES

                for line in csvReader:
                    #STEP 5.1 GET THE mirna ID, THE ASSOCIATED GENE ID AND THE QUANTIFICATION VALUES
                    mirnaID    = line[0]
                    geneID     = line[1]
                    score      = float(line[2])
                    score_type = line[3]
                    values     =  map(float, line[4:])

                    #EVEN WHEN THE USER HAS CHOOSE THE OPTION "FC", if the conditions do no allow to calculate the
                    #correlation, the script will calculate the FC
                    isRelevant = mirnaID.lower() in relevantMiRNAS
                    isRelevantAssociation = False

                    if useCorrelation:
                        if score_type != "fc" and self.selection_method == "negative_correlation":
                            score *= -1  #INVERT VALUES
                        elif score_type != "fc" and self.selection_method == "abs_correlation":
                            score = abs(score)
                        #TODO: SIMILAR FC SELECTION

                        # Only those correlation with a score higher than the specified cutoff
                        # are considered relevant.
                        isRelevantAssociation = (score > self.cutoff)

                        #STEP 5.2 FILTER MIRNAS
                        #IF THE OPTION "ONLY RELEVANTS" WAS SELECTED, IGNORE ENTRY

                        # Add an extra check to ensure that the regulator is inside the list of
                        # relevant regulators (depends on configuration options).
                        if self.report == "DE":# and not isRelevant:
                            isRelevantAssociation = isRelevantAssociation and isRelevant
                            #continue

                        #FILTER BY SELECTION METHODS, IF CORRELATION OR FC IS LOWER THAN THE CUTOFF, IGNORE ENTRY
                        # if score < self.cutoff:
                        #     isRelevantAssociation = False
                        #     #continue
                    else:
                        isRelevantAssociation = geneID + ':::' + mirnaID in relevantAssociations

                    #STEP 5.3 CREATE A NEW OMIC VALUE WITH ROW DATA
                    omicValueAux = OmicValue(mirnaID)
                    #TODO: set omic name with chipseq, dnase,...?
                    omicValueAux.setOriginalName(mirnaID)
                    omicValueAux.setValues(values)
                    omicValueAux.setRelevant(isRelevant)
                    omicValueAux.setRelevantAssociation(isRelevantAssociation)

                    #STEP 5.4 CREATE A NEW TEMPORAL GENE INSTANCE
                    geneAux = Gene(geneID)
                    geneAux.setName(mirnaID)
                    geneAux.addOmicValue(omicValueAux)

                    #STEP 5.5 ADD THE TEMPORAL GENE INSTANCE TO THE LIST OF GENES, IF ALREADY EXISTS, MERGE
                    self.addInputGeneData(geneAux)

                    #STEP 5.6 ADD THE OMIC VALUE TO THE LIST, FOR FURTHER ORDERING
                    scoresTable[geneID].append((score, omicValueAux))

                logging.info("PROCESSING miRNA2Target OUTPUT...DONE")

                # Abort the process to let the user know that there were no results.
                if len(self.getInputGenesData()) < 1:
                    logging.info("MIRNA2GENES - NO RESULTS")
                    raise Exception(" - Your mirna2gene association process did not return any result. Please, check the files (same identifiers, etc) and parameters.")

                #EVEN WHEN THE USER HAS CHOOSE THE OPTION "FC", if the conditions do no allow to calculate the
                #correlation, the script will calculate the FC
                methodsHasChanged = (score_type == "fc" and self.score_method != "fc")

                #STEP 6. FOR EACH GENE, ORDER THE MIRNAS BY THE HIGHER CORRELATION OR FC
                filePrefix = '' if self.getUserID() is not None else self.getJobID() + '_'
                randomSeed = str(randint(0, 1000))
                genesToMiRNAFile = open(self.getTemporalDir() + '/' + filePrefix + 'genesToMiRNAFile.tab', 'w')
                regulator2genesOutput = open(self.getTemporalDir() + '/' + filePrefix + "regulator2Gene_output_" + self.date + "_" + randomSeed +  ".tab", 'w')
                regulator2genesRelevant = open(self.getTemporalDir() + '/' + filePrefix + "regulator2Gene_relevant_" + self.date + "_" + randomSeed + ".tab", 'w')

                # Associations files
                regulatorAssociations = open(self.getTemporalDir() + '/' + filePrefix + "regulator_associations" + self.date + "_" + randomSeed + ".tab", 'w')
                regulatorRelevantAssociations = open(self.getTemporalDir() + '/' + filePrefix + "regulator_relevant_associations" + self.date + "_" + randomSeed + ".tab", 'w')

                # PRINT HEADER
                genesToMiRNAFile.write("# Gene name\tmiRNA ID\tDE\tScore\tSelection\n")
                #TODO: RE-ENABLE THIS CODE
                regulator2genesOutput.write("# Gene name\t"+ header + "\n")
                #mirna2genesOutput.write("# Gene name\tmiRNA ID\t"+ header + "\n")
                regulator2genesRelevant.write("# Gene name\tmiRNA ID\n")
                regulatorRelevantAssociations.write("# Gene name\tmiRNA ID\n")

                logging.info("ORDERING miRNAS BY CORRELATION / FC...")
                for geneID, gene in self.getInputGenesData().items():
                    #GET ALL THE miRNAs AND SORT
                    sortedScores = sorted(scoresTable[geneID], key=lambda omicValue: omicValue[0], reverse=True)

                    #STEP 6.1 WRITE RESULTS
                    for omicValue in sortedScores:
                        score = omicValue[0]
                        omicValue = omicValue[1]

                        lineAux = geneID + "\t" + omicValue.getOriginalName() + "\t"

                        #Recover the original value for the score
                        if not methodsHasChanged and self.selection_method == "negative_correlation":
                            score *= -1

                        #WRITE RESULTS TO genesToMiRNAFile FILE -->   gen_id mirna relevant score
                        genesToMiRNAFile.write(lineAux + ("*" if omicValue.isRelevant() else "") + "\t" + str(score) + "\t" + self.selection_method + "\n")

                        #WRITE RESULTS TO miRNA2Gene_output FILE -->   gen_id mirna values
                        #TODO: RE-ENABLE THIS CODE
                        #mirna2genesOutput.write(lineAux + '\t'.join(map(str, omicValue.getValues())) + "\n")
                        # mirna2genesOutput.write(geneID + "\t" + '\t'.join(map(str, omicValue.getValues())) + "\n")
                        regulator2genesOutput.write(":::".join([geneID, omicValue.getOriginalName()]) + "\t" + '\t'.join(map(str, omicValue.getValues())) + "\n")

                        # Associations file (trimmed down version including only those regulators present on
                        # the values file).
                        regulatorAssociations.write(geneID + "\t" + omicValue.getOriginalName() + "\n")

                        # Relevant regulators file (not associations)
                        if omicValue.isRelevant():
                            #WRITE RESULTS TO mirna2genesRelevant FILE -->   gen_id mirna
                            regulator2genesRelevant.write(geneID + "\t" + omicValue.getOriginalName() + "\n")

                        # Relevant associations file
                        if omicValue.isRelevantAssociation():
                            #WRITE RESULTS TO mirna2genesRelevant FILE -->   gen_id mirna
                            regulatorRelevantAssociations.write(geneID + "\t" + omicValue.getOriginalName() + "\n")

                genesToMiRNAFile.close()
                regulator2genesOutput.close()
                regulator2genesRelevant.close()
                regulatorAssociations.close()
                regulatorRelevantAssociations.close()

                #STEP 7. GENERATE THE COMPRESSED FILE WITH RESULTS, COPY THE mirna2genesOutput FILE AT INPUT DIR AND CLEAN TEMPORAL FILES
                #COMPRESS THE RESULTING FILES AND CLEAN TEMPORAL DATA
                #TODO: REMOVE THE genesToMiRNAFile
                logging.info("COMPRESSING RESULTS...")
                fileName = "regu2genes_" + self.date

                shutil.make_archive(self.getOutputDir() + fileName, "zip", self.getTemporalDir() + "/")

                logging.info("COMPRESSING RESULTS...DONE")

                #TODO: The app can not run if there is no gene expression data

                if geneExpressionFile is not None:
                    fields = {
                        "omicType" : miRNAinputOmic.get("omicName"),
                        "dataType" : miRNAinputOmic.get("omicName").replace("data", "quantification"),
                        "description" : "File generated using regu2Target tool (regu2Target);" + self.getJobDescription(True, dataFile, relevantFile, referenceFile, geneExpressionFile)
                    }
                else:
                    fields = {
                        "omicType": miRNAinputOmic.get( "omicName" ),
                        "dataType": miRNAinputOmic.get( "omicName" ).replace( "data", "quantification" ),
                        "description": "File generated using regu2Target tool (regu2Target);" + self.getJobDescription(True, dataFile, relevantFile, referenceFile)
                    }

                mainOutputFileName = copyFile(self.getUserID(), os_path.split(regulator2genesOutput.name)[1], fields, self.getTemporalDir() +  "/", self.getInputDir())

                fields = {
                    "omicType" : miRNAinputOmic.get("omicName"),
                    "dataType" : "Relevant Genes list",
                    "description" : "File generated using regu2Target tool (regu2Target);"  + self.getJobDescription()
                }
                secondOutputFileName = copyFile(self.getUserID(), os_path.split(regulator2genesRelevant.name)[1], fields, self.getTemporalDir() + "/", self.getInputDir())

                fields = {
                    "omicType": miRNAinputOmic.get("omicName"),
                    "dataType": "Associations file",
                    "description": "Associations file filtered using regu2Target tool (regu2Target);" + self.getJobDescription()
                }
                thirdOutputFileName = copyFile(self.getUserID(), os_path.split(regulatorAssociations.name)[1], fields, self.getTemporalDir() + "/", self.getInputDir())

                fields = {
                    "omicType": miRNAinputOmic.get("omicName"),
                    "dataType": "Relevant associations file",
                    "description": "Relevant associations generated using regu2Target tool (regu2Target);" + self.getJobDescription()
                }
                fourthOutputFileName = copyFile(self.getUserID(), os_path.split(regulatorRelevantAssociations.name)[1], fields, self.getTemporalDir() + "/", self.getInputDir())

                #TODO: REMOVE FILES IF EXCEPTION
                inputDataFile.close()
                self.cleanDirectories()



                return [fileName + ".zip", mainOutputFileName, fourthOutputFileName, thirdOutputFileName,
                        secondOutputFileName]

