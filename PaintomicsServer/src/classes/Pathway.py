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
#  Technical contact paintomics4@gmail.com
#**************************************************************

from .PathwayGraphicalData import PathwayGraphicalData
from src.common.Util import Model
from collections import defaultdict

class Pathway(Model):
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, ID):
        self.ID = ID
        self.name = ""
        self.classification = ""
        self.source = "KEGG"
        #IDENTIFIERS OF MATCHED COMPOUNDS, THE DATA IS AT JOBINSTANCE
        self.matchedCompounds =[]
        #IDENTIFIERS OF MATCHED GENES, THE DATA IS AT JOBINSTANCE
        self.matchedGenes = []
        #METAGENES INFORMATION FOR EACH OMIC DATA TYPE
        self.metagenes = {}
        #SIGNIFICANCE VALUES PER OMIC in format OmicName -> [[totalFeatures, totalRelevantFeatures, pValue], ...] (one per condition)
        self.significanceValues= {}
        self.globalOmicPvalues = {}
        self.totalGlobalPvalues = {}
        self.adjustedSignificanceValues = {}
        #self.combinedSignificancePvalue=1
        self.combinedSignificancePvalues = {}
        self.adjustedCombinedSignificanceValues = {}
        self.masterRegulators = defaultdict(list)
        #GRAPHICAL INFORMATION
        self.graphicalOptions = None

    #******************************************************************************************************************
    # GETTERS AND SETTER
    #******************************************************************************************************************
    def setID(self, ID):
        self.ID = ID
    def getID(self):
        return self.ID

    def setName(self, name):
        self.name = name
    def getName(self):
        return self.name

    def setClassification(self, classification):
        self.classification = classification
    def getClassification(self):
        return self.classification

    def setSource(self, source):
        self.source = source
    def getSource(self):
        return self.source

    def setMatchedCompounds(self, matchedCompounds):
        self.matchedCompounds = matchedCompounds
    def getMatchedCompounds(self):
        return self.matchedCompounds
    def addMatchedCompound(self, matchedCompound):
        self.matchedCompounds.append(matchedCompound.getID())
    def addMatchedCompoundID(self, matchedCompoundID):
        self.matchedCompounds.append(matchedCompoundID)

    def setMatchedGenes(self, matchedGenes):
        self.matchedGenes = matchedGenes
    def getMatchedGenes(self):
        return self.matchedGenes
    def addMatchedGene(self, matchedGen):
        self.matchedGenes.append(matchedGen.getID())
    def addMatchedGeneID(self, matchedGenID):
        self.matchedGenes.append(matchedGenID)

    def setMetagenes(self, metagenes):
        self.metagenes= metagenes
    def getMetagenes(self):
        return self.metagenes
    def addMetagenes(self, omicName, metagene):
        if not omicName in self.metagenes:
            self.metagenes[omicName] = []
        self.metagenes[omicName].append(metagene)
    def resetMetagenes(self, omicName):
        self.metagenes[omicName] = []

    def setMasterRegulators(self, omic, masterRegulators):
        self.masterRegulators[omic] = masterRegulators
    def getMasterRegulators(self):
        return self.masterRegulators
    def addMasterRegulator(self, omic, masterRegulator):
        self.masterRegulators[omic].add(masterRegulator)

    #OmicName -> [[totalFeatures, totalRelevantFeatures, pValue], ...] (one per condition)
    def setSignificanceValues(self, significanceValues):
        self.significanceValues = significanceValues
    def getSignificanceValues(self):
        return self.significanceValues
    def addSignificanceValues(self, omicName, isRelevantFeatureList):
        # Ensure isRelevantFeatureList is a list
        if not isinstance(isRelevantFeatureList, (list, tuple)):
            isRelevantFeatureList = [isRelevantFeatureList]
        
        nConditionsInput = len(isRelevantFeatureList)
        currentValues = self.significanceValues.get(omicName)

        if currentValues is None:
            # Initialize with zeros for each condition
            currentValues = [[0, 0, -1.0] for _ in range(nConditionsInput)]
            currentLen = nConditionsInput
        else:
            currentLen = len(currentValues)
        
        # Use the maximum number of conditions seen so far for this omic
        nConditions = max(currentLen, nConditionsInput)
        
        if currentLen < nConditions:
            # New condition slots start at zero. A feature only contributes to
            # totalMatched of conditions where it actually has a value, so
            # earlier features (shorter lists) MUST NOT seed later slots.
            for _ in range(nConditions - currentLen):
                currentValues.append([0, 0, -1.0])

        for i in range(nConditions):
            # Only contribute to a condition when the feature has a slot for it.
            if i < nConditionsInput:
                currentValues[i][0] += 1 # totalMatched
                if isRelevantFeatureList[i]:
                    currentValues[i][1] += 1 # totalRelevant

        self.significanceValues[omicName] = currentValues

    def setGlobalOmicPvalue(self, omicName, pValue):
        self.globalOmicPvalues[omicName] = pValue
    def getGlobalOmicPvalues(self):
        return self.globalOmicPvalues

    def setTotalGlobalPvalues(self, pValues):
        self.totalGlobalPvalues = pValues
    def getTotalGlobalPvalues(self):
        return self.totalGlobalPvalues

    def setSignificancePvalues(self, adjustedSignificanceValues):
        self.adjustedSignificanceValues = adjustedSignificanceValues
    def getAdjustedSignificanceValues(self):
        return self.adjustedSignificanceValues
    def setOmicAdjustedSignificanceValues(self, omic, adjustedSignificanceValues):
        self.adjustedSignificanceValues[omic] = adjustedSignificanceValues

    def setSignificancePvalue(self, omicName, pValues):
        # pValues is now a list of p-values for the omic (one per condition)
        if not isinstance(pValues, list):
             pValues = [pValues]
        
        for i, pVal in enumerate(pValues):
            if i < len(self.significanceValues[omicName]):
                self.significanceValues[omicName][i][2] = pVal

    # def setCombinedSignificancePvalue(self, pValue):
    #     self.combinedSignificancePvalue = pValue
    # def getCombinedSignificancePvalue(self):
    #     return self.combinedSignificancePvalue
    def setCombinedSignificancePvalues(self, pValues):
        self.combinedSignificancePvalues = pValues
    def getCombinedSignificancePvalues(self):
        return self.combinedSignificancePvalues

    # NOTE: the populated attribute is `adjustedCombinedSignificanceValues`
    # (no "P"); the per-method setter at the bottom writes there. The bulk
    # setAdjustedCombinedSignificancePvalues() (with "P") below remained for
    # historical reasons; we route it to the same attribute so the getter
    # works regardless of which setter was used.
    def setAdjustedCombinedSignificancePvalues(self, pValues):
        self.adjustedCombinedSignificanceValues = pValues
    def getAdjustedCombinedSignificancePvalues(self):
        return self.adjustedCombinedSignificanceValues
    def setMethodAdjustedCombinedSignificanceValues(self, method, adjustedCombinedSignificanceValues):
        self.adjustedCombinedSignificanceValues[method] = adjustedCombinedSignificanceValues

    def setGraphicalOptions(self, graphicalOptions):
        self.graphicalOptions = graphicalOptions
    def getGraphicalOptions(self):
        return self.graphicalOptions

    #******************************************************************************************************************
    # OTHER FUNCTIONS
    #******************************************************************************************************************
    def parseBSON(self, bsonData):
        for (attr, value) in bsonData.items():
            setattr(self, attr, value)
        return self

    def toBSON(self):
        bson = {}
        for attr, value in self.__dict__.items():
            if (attr != "graphicalOptions"):
                bson[attr] = value
        return bson