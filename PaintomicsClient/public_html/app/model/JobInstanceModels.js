//# sourceURL=JobInstanceModels.js
/*
* (C) Copyright 2014 The Genomics of Gene Expression Lab, CIPF
* (http://bioinfo.cipf.es/aconesawp) and others.
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of the GNU Lesser General Public License
* (LGPL) version 3 which accompanies this distribution, and is available at
* http://www.gnu.org/licenses/lgpl.html
*
* This library is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
* Lesser General Public License for more details.
*
* Contributors:
*     Rafael Hernandez de Diego
*     rhernandez@cipf.es
*     Ana Conesa Cegarra
*     aconesa@cipf.es
*
* THIS FILE CONTAINS THE FOLLOWING COMPONENT DECLARATION
* - JobInstance
*
*/

function JobInstance(jobID) {
	this.jobID = jobID;
	this.userID;
	this.stepNumber = 1;
	this.organism = null;
	this.name = null;

	this.pathways = [];
	this.databases = null;
	this.clusters = null;
	this.summary = null;
	this.mappingSummary = null;

	this.geneBasedInputOmics = null;
	this.compoundBasedInputOmics = null;

	this.omicsHeaders = null;
	this.omicsValues = null;
	this.omicsValuesID = null;
	this.foundCompounds = [];

	this.selectedPathway = null;
	this.timestamp = null;
	
	this.readOnly = false;
	this.allowSharing = false;

	// add Metabolism Classification Part
	this.mappingComp = null;
	this.pValueInDict = null;
	this.classificationDict = null;
	this.exprssionMetabolites = null;
	this.adjustPvalue = null;
	this.totalRelevantFeaturesInCategory = null;
	this.compoundRegulateFeatures =null;
	this.globalExpressionData = null;
	this.hubAnalysisResult = null;


	/*****************************
	** GETTERS AND SETTERS
	*****************************/
	this.setJobID = function (jobID) {
		this.jobID = jobID;
	};
	this.getJobID = function () {
		return this.jobID;
	};
	this.setUserID = function (userID) {
		this.userID = userID;
	};
	this.getUserID = function () {
		return this.userID;
	};
	this.setTimestamp = function(timestamp) {
		this.timestamp = timestamp;
	};
	this.getTimestamp = function() {
		return this.timestamp;	
	};
	this.setName = function (name) {
		this.name = name;
	};
	this.getName = function () {
		return this.name;
	};
	this.setReadOnly = function(readOnly) {
		this.readOnly = readOnly;
	};
	this.getReadOnly = function() {
		return this.readOnly;	
	};
	this.setAllowSharing = function(allowSharing) {
		this.allowSharing = allowSharing;
	};
	this.getAllowSharing = function() {
		return this.allowSharing;	
	};
	this.setStepNumber = function (stepNumber) {
		this.stepNumber = stepNumber;
	};
	this.getStepNumber = function () {
		return this.stepNumber;
	};
	this.setOrganism = function (organism) {
		this.organism = organism;
	};
	this.getOrganism = function () {
		return this.organism;
	};
	this.setPathways = function (pathways) {
		this.pathways = pathways;
	};
	this.getPathways = function () {
		return this.pathways;
	};
	this.getPathwaysByDB = function (db) {
		return this.pathways.filter(function(pathway) {
			return pathway.getSource() == db
		});
	};
	this.getPathway = function (pathwayID) {
		for (var i in this.pathways) {
			if (pathwayID == this.pathways[i].getID()) {
				return this.pathways[i];
			}
		}
		return null;
	};
	this.addPathway = function (pathway) {
		//TODO: CHECK CLASSES?
		this.pathways.push(pathway);
	};
    this.getOmicNames = function() {
        var omicNames = this.getGeneBasedInputOmics().concat(this.getCompoundBasedInputOmics()).map(x => x.omicName);
        
        return omicNames;
	};
	this.getGeneOmicNames = function() {
        var omicNames = this.getGeneBasedInputOmics().map(x => x.omicName);
        
        return omicNames;
	};
	this.getCompoundOmicNames = function() {
        var omicNames =this.getCompoundBasedInputOmics().map(x => x.omicName);
        
        return omicNames;
	};
	this.getDatabases = function() {
		if (! this.databases || ! this.databases.length) {
			// Check databases present in pathways
			var pathways = this.getPathways();

			// ES6/ES2015
			this.databases = [...new Set(pathways.map(item => item.getSource()))];
		}
		return this.databases.sort();
	}
	this.setDatabases = function (databases) {
		this.databases = databases;
	};
	this.getClusterNumber = function() {
		// Double check in case they are empty.
		var me = this;
		
		if (this.clusters === null || me.getDatabases().every(function(db) {
			return Object.keys(me.clusters[db]).every(function(x) { return !me.clusters[db][x].size; })})) {
			this.clusters = {};
			
			// For each database initialize a new set containing all omic names
			this.getDatabases().forEach(function(db) {
				this.clusters[db] = {};
				
				this.getOmicNames().map(x => this.clusters[db][x] = new Set());
				
				// For each pathway and each omic present in its metagene info,
				// add to the set the different clusters found.
				this.getPathwaysByDB(db).forEach(function(pathway) {
					var metagenes = pathway.getMetagenes();
					
					Object.keys(metagenes).forEach(function(omicName) {
						metagenes[omicName].map(x => this.clusters[db][omicName].add(x.cluster));
					}, this);
				}, this);
			}, this);
		}
		
		return this.clusters;
	};
	this.getClusterNumberByDbAndOmic = function(database, omic) {
		return this.getClusterNumber()[database][omic];
	};
	this.setClusterNumber = function(clusters) {
		this.clusters = clusters;
	};
	this.setSummary = function (summary) {
		this.summary = summary;
	};
	this.getSummary = function () {
		return this.summary;
	};
	this.setMappingSummary = function (mappingSummary) {
		this.mappingSummary = mappingSummary;
	};
	this.getMappingSummary = function () {
        
        if (this.mappingSummary == null) {
            var mappingSummary = {};
            
            this.getGeneBasedInputOmics().concat(this.getCompoundBasedInputOmics()).map(function(currentValue, index, omics) {
                var mappedInfo = currentValue.omicSummary[0];
                var mappedFeatures = Number.isInteger(mappedInfo) ? mappedInfo : (parseFloat(mappedInfo.Total || mappedInfo[Object.keys(mappedInfo)[0]]));
                var unmappedFeatures = parseFloat(currentValue.omicSummary[1]);
                
                mappingSummary[currentValue.omicName] = {mapped: mappedFeatures, unmapped: unmappedFeatures};
            });
            
            this.mappingSummary = mappingSummary;
        }
        
		return this.mappingSummary;
	};
	this.setGeneBasedInputOmics = function (geneBasedInputOmics) {
		this.geneBasedInputOmics = geneBasedInputOmics;
	};
	this.getGeneBasedInputOmics = function () {
		return this.geneBasedInputOmics == null ? [] : this.geneBasedInputOmics;
	};
	this.setCompoundBasedInputOmics = function (compoundBasedInputOmics) {
		this.compoundBasedInputOmics = compoundBasedInputOmics;
	};
	this.getCompoundBasedInputOmics = function () {
		return this.compoundBasedInputOmics == null ? [] : this.compoundBasedInputOmics;
	};
	this.setFoundCompounds = function (foundCompounds) {
		this.foundCompounds = foundCompounds;
	};
	this.getFoundCompounds = function () {
		return this.foundCompounds;
	};
	this.addFoundCompound = function (compoundSet) {
		//TODO: CHECK CLASSES?
		this.foundCompounds.push(compoundSet);
	};
	this.getOmicHeaders = function(omicName = null) {	
		if (this.omicHeaders == null) {
			
			this.omicHeaders = {};
			
			this.getGeneBasedInputOmics().concat(this.getCompoundBasedInputOmics()).map(function(currentValue, index, omics) {
				this.omicHeaders[currentValue["omicName"]] = currentValue["omicHeader"];
			}.bind(this));
		}
		
		return this.omicHeaders;
	};




	this.updatePathway = function (pathway) {
		for (var i in this.pathways) {
			if (pathway.getID() == this.pathways[i].getID()) {
				this.pathways.splice(i, 1);
				break;
			}
		}
		this.pathways.push(pathway);
	};
	this.setSelectedPathway = function (pathwayID) {
		this.selectedPathway = pathwayID;
	};
	this.getSelectedPathway = function () {
		return this.selectedPathway;
	};
	this.setOmicsValues = function (omicsValues) {
		this.omicsValues = omicsValues;
	};
	this.getOmicsValues = function () {
		if (this.omicsValues === null) {
			this.omicsValues = {};
		}
		return this.omicsValues;
	};
	this.setOmicsValuesID = function (omicsValuesID) {
		this.omicsValuesID = omicsValuesID;
	};
	this.getOmicsValuesID = function () {
		return this.omicsValuesID;
	};
	this.addOmicValue = function (omicsValue) {
		this.getOmicsValues()[omicsValue.getID()] = omicsValue;
	};


	// add Metabolism method
	this.setMappingComp = function (mappingComp) {
		this.mappingComp = mappingComp;
	}

	this.getMappingComp = function () {
		return this.mappingComp == null ? [] : this.mappingComp;
	}


	this.setpValueInDict = function (pValueInDict) {
		this.pValueInDict = pValueInDict;
	}

	this.getpValueInDict = function () {
		return this.pValueInDict == null ? {} : this.pValueInDict;
	}

	this.setExprssionMetabolites = function (exprssionMetabolites) {
		this.exprssionMetabolites = exprssionMetabolites;
	}

	this.getExprssionMetabolites = function () {
		return this.exprssionMetabolites == null ? {} : this.exprssionMetabolites;
	}
	this.setAdjustPvalue = function (adjustPvalue) {
		this.adjustPvalue = adjustPvalue
	}
	this.getAdjustPvalue = function () {
		return this.adjustPvalue == null ? {} : this.adjustPvalue
	}
	this.setTotalRelevantFeaturesInCategory = function (totalRelevantFeaturesInCategory) {
		this.totalRelevantFeaturesInCategory = totalRelevantFeaturesInCategory
	}
	this.getTotalRelevantFeaturesInCategory = function () {
		return this.totalRelevantFeaturesInCategory == null ? {} : this.totalRelevantFeaturesInCategory
	}

	this.setCompoundRegulateFeatures = function (compoundRegulateFeatures) {
		this.compoundRegulateFeatures = compoundRegulateFeatures
	}
	this.getCompoundRegulateFeatures = function () {
		return this.compoundRegulateFeatures == null ? {} : this.compoundRegulateFeatures
	}

	this.setGlobalExpressionData = function (globalExpressionData) {
		this.globalExpressionData = globalExpressionData
	}
	this.getGlobalExpressionData = function () {
		return this.globalExpressionData == null ? {} : this.globalExpressionData
	}
	this.getHubAnalysisResult = function () {
		return this.hubAnalysisResult == null ? {} : this.hubAnalysisResult
	}

	this.setHubAnalysisResult = function (hubAnalysisResult) {
		this.hubAnalysisResult = hubAnalysisResult
	}

	this.setFeatureSummary = function (featureSummary) {
		this.featureSummary = featureSummary
	}
	this.getFeatureSummary = function () {
		return this.featureSummary == null ? {} : this.featureSummary
	}

	this.setClassificationDict = function (classificationDict) {
		this.classificationDict = classificationDict;
	}

	this.getClassificationDict = function () {
		return this.classificationDict == null ? [] : this.classificationDict;
	}


	this.getMultiplePvaluesMethods = function() {
		var multipleMethods = [];

		if (this.pathways.length && this.pathways[0].getAdjustedSignificanceValues) {
			var omicPvalues = this.pathways[0].getAdjustedSignificanceValues();

			multipleMethods = omicPvalues && Object.keys(omicPvalues).length ? Object.keys(omicPvalues[Object.keys(omicPvalues)[0]]) : [];
		}

		return multipleMethods;
	};
	this.getCombinedPvaluesMethods = function() {
		var combinedMethods = [];

		if (this.pathways.length && this.pathways[0].getCombinedSignificanceValues) {
			var omicPvalues = this.pathways[0].getCombinedSignificanceValues();

			combinedMethods = Object.keys(omicPvalues);
		}

		return combinedMethods;
	};

	/**
	* This function returns the values for min/max for each omic type.
	* This information is calculated during first step and returned as part of
	* the matching summary.
	* The information is stored as part of the Objects stored in geneBasedInputOmics
	* and compoundBasedInputOmics, but using this function we adapt extract only the min/max
	* (i.e. p10 and p90) and store it in an appropriate format (which PA_Step4PathwayView).
	*
	* @returns {minMaxValues}, an object containing 2 arrays: pos 0 contains the min values
	*   for each omic (indexed by omic name), and pos 1 contains max values for each omic
	*   (indexed by omic name)
	*/
	this.getDataDistributionSummaries = function (omicName) {
		//   0        1       2    3   4     5     6    7    8     9       10      11          12
		//[MAPPED, UNMAPPED, MIN, P10, Q1, MEDIAN, Q3, P90, MAX, MIN_IR, Max_IR, MIN_CUSTOM, MAX_CUSTOM]
		if(this.dataDistributionSummaries === undefined){
			this.dataDistributionSummaries = {};

			var omicsAux = this.getGeneBasedInputOmics();
			for (var i in omicsAux) {
				if (omicsAux[i].omicSummary === undefined) {
					showWarningMessage("No information about min/max available.", {
						message: "The current job instance do not include information about min/max values for each omic type.</br>" +
						"A possible explanation for this issue could be that the data was generated using an older version of Paintomics.</br>" +
						"Instead of using the percentiles 10 and 90 for each omics as reference to obtain the colors for the heatmap, Paintomics " +
						"will calculate locally the min / max for each omics for each selected pathway.", showButton: true, height: 260
					});
					return null;
				}
				//TODO: SAVE SUMMARY AS DICT??
				this.dataDistributionSummaries[omicsAux[i].omicName] = omicsAux[i].omicSummary;
			}
			omicsAux = this.getCompoundBasedInputOmics();
			for (var i in omicsAux) {
				if (omicsAux[i].omicSummary === undefined) {
					showWarningMessage("No information about min/max available.", {
						message: "The current job instance do not include information about min/max values for each omic type.</br>" +
						"A possible explanation for this issue could be that the data was generated using an older version of Paintomics.</br>" +
						"Instead of using the percentiles 10 and 90 for each omics as reference to obtain the colors for the heatmap, Paintomics" +
						" will calculate locally the min / max for each omics for each selected pathway."
					});
					return null;
				}
				//TODO: SAVE SUMMARY AS DICT??
				this.dataDistributionSummaries[omicsAux[i].omicName] = omicsAux[i].omicSummary;
			}
		}


		return (omicName? this.dataDistributionSummaries[omicName]: this.dataDistributionSummaries);
	};

	this.setDataDistributionSummaries = function(dataDistributionSummaries, omicName) {
		if (omicName) {
			this.dataDistributionSummaries[omicName] = dataDistributionSummaries;
		} else {
			this.dataDistributionSummaries = dataDistributionSummaries;
		}
 	};

	this.loadFromJSON = function (jsonObject) {
		for(var i in jsonObject){
			if(i === "geneBasedInputOmics"){
				this.geneBasedInputOmics = jsonObject.geneBasedInputOmics;
				this.geneBasedInputOmics.sort(function(a,b) {return (a.omicName > b.omicName) ? 1 : ((b.omicName > a.omicName) ? -1 : 0);} );
			}else if(i === "compoundBasedInputOmics"){
				this.compoundBasedInputOmics = jsonObject.compoundBasedInputOmics;
				this.compoundBasedInputOmics.sort(function(a,b) {return (a.omicName > b.omicName) ? 1 : ((b.omicName > a.omicName) ? -1 : 0);} );
			}else if(i === "foundCompounds"){
				this.foundCompounds = [];
				for (var i in jsonObject.foundCompounds){
					this.addFoundCompound(new CompoundSet("").loadFromJSON(jsonObject.foundCompounds[i]));
				}
			}else if(i === "pathways"){
				this.pathways = [];
				for (var i in jsonObject.pathways){
					this.addPathway(new Pathway("").loadFromJSON(jsonObject.pathways[i]));
				}
			}else if(i === "omicsValues"){
				this.omicsValues = {};
				for (var i in jsonObject.omicsValues){
					this.addOmicValue(new Feature(i).loadFromJSON(jsonObject.omicsValues[i]));
				}
			}else{
				this[i] = jsonObject[i];
			}
		}
	};
}
JobInstance.prototype = new Model();
