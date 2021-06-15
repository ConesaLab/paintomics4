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
        #SIGNIFICANCE VALUES PER OMIC in format OmicName -> [totalFeatures, totalRelevantFeatures, pValue]
        self.significanceValues= {}
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

    #OmicName -> [totalFeatures, totalRelevantFeatures, pValue]
    def setSignificanceValues(self, significanceValues):
        self.significanceValues = significanceValues
    def getSignificanceValues(self):
        return self.significanceValues
    def addSignificanceValues(self, omicName, isRelevantFeature):
        nFeatures = (self.significanceValues.get(omicName, [0])[0] + 1)
        nRelevantFeatures = self.significanceValues.get(omicName, [0,0])[1]
        if(isRelevantFeature):
            nRelevantFeatures += 1
        pValue = (self.significanceValues.get(omicName, [0,0,-1])[2])
        self.significanceValues[omicName] = [nFeatures, nRelevantFeatures, pValue]

    def setSignificanceValues(self, adjustedSignificanceValues):
        self.adjustedSignificanceValues = adjustedSignificanceValues
    def getAdjustedSignificanceValues(self):
        return self.adjustedSignificanceValues
    def setOmicAdjustedSignificanceValues(self, omic, adjustedSignificanceValues):
        self.adjustedSignificanceValues[omic] = adjustedSignificanceValues

    def setSignificancePvalue(self, omicName, pValue):
        self.significanceValues[omicName][2] = pValue

    # def setCombinedSignificancePvalue(self, pValue):
    #     self.combinedSignificancePvalue = pValue
    # def getCombinedSignificancePvalue(self):
    #     return self.combinedSignificancePvalue
    def setCombinedSignificancePvalues(self, pValues):
        self.combinedSignificancePvalues = pValues
    def getCombinedSignificancePvalues(self):
        return self.combinedSignificancePvalues

    def setAdjustedCombinedSignificancePvalues(self, pValues):
        self.adjustedCombinedSignificancePvalues = pValues
    def getAdjustedCombinedSignificancePvalues(self):
        return self.adjustedCombinedSignificancePvalues
    def setMethodAdjustedCombinedSignificanceValues(self, method, adjustedCombinedSignificanceValues):
        self.adjustedCombinedSignificanceValues[method] = adjustedCombinedSignificanceValues

    def setGraphicalOptions(self, graphicalOptions):
        self.graphicalOptions = graphicalOptions
    def getGraphicalOptions(self):
        return self.graphicalOptions

    #******************************************************************************************************************
    # OTHER FUNCTIONS
    #******************************************************************************************************************
    def toBSON(self):
        bson = {}
        for attr, value in self.__dict__.items():
            if (attr != "graphicalOptions"):
                bson[attr] = value
        return bson