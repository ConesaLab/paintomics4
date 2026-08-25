//# sourceURL=PA_Step3Views.js
/*jshint esversion: 6 */
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
* THIS FILE CONTAINS THE FOLLOWING COMPONENT DECLARATION
* - PA_Step3JobView
* - PA_Step3PathwayClassificationView
* - PA_Step3PathwayNetworkView
* - PA_Step3PathwayNetworkTooltipView
* - PA_Step3PathwayDetailsView
* - PA_Step3PathwayTableView
* - PA_Step3StatsView
*
*/

function PA_Step3JobView() {
	/**
	* About this view: this view (PA_Step3JobView) is used to visualize an instance for a Pathway acquisition
	* job when current step is STEP 3.
	* The view shows different information for the Job instance, in particular:
	*  - First it show a summary panel with the number of matched pathways
	*  - A panel containing a summary for the classifications for the matched pathways (PA_Step3PathwayClassificationView):
	*     · A pie chart with an overview of the distribution of the classifications
	*     · A tree view containing each classification, the corresponding subclassifications
	*       and pathways. This panel allows to show/hide elements in the view (pathways)
	*  - A panel showing a network (PA_Step3PathwayNetworkView) where nodes represents pathways and edges relationships between them.
	*    This view also contains:
	*     · A tooltip showing some information for pathways when hovering the nodes (PA_Step3PathwayNetworkTooltipView)
	*     · A detailed view for each pathway in the network (PA_Step3PathwayDetailsView)
	*  - A table (PA_Step3PathwayTableView) showing a ranking for the matched pathways, ordered by relevance.
	**/
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step3JobView";
	this.visualOptions = null;
	this.classificationData = {};
	this.indexedPathways = {};

	this.pathwayClassificationViews = {};
	this.pathwayNetworkViews = {};
	this.pathwayTableView = null;
	this.statsView = null;
	this.significativePathways = 0;
	this.significativePathwaysByDB = {};
	this.isFiltered = {};
	this.isOwner = false;


	this.metaboliteView = null;
	this.regulationView = null;
	this.regTargetNetworkView = null;

	this.hubAnalysisView = null;
	this.hubNetworkView = null;
	this.aiWidget = null;
	this.aiJobID = null;
	// Shared-feature pathway partition from the AI report (cluster mode), or null.
	this.aiClusters = null;
	this.pollTimerID = null;

	/**
	* Does this job have metabolomics worth showing the two metabolite panels for?
	*
	* This used to ask `foundCompounds.length`, which is the list of *candidate*
	* compound names awaiting disambiguation at step 2. Those candidates are
	* deleted once step 2 resolves them -- storeJobInstance calls
	* FoundFeatureDAO().removeAll() and never re-inserts them, the only use of
	* that DAO in the file -- so a job reopened from its URL has none, and both
	* panels disappeared even though everything they draw was still there.
	*
	* What they actually draw is the *resolved* compounds: the hub table reads
	* hubAnalysisResult and mappingComp, the class activity table reads
	* mappingComp, classificationDict, exprssionMetabolites, pValueInDict,
	* adjustPvalue and totalRelevantFeaturesInCategory. All of those are written
	* back at step 2, so asking about mappingComp answers the question the gate
	* was trying to ask.
	*
	* foundCompounds was checked first, ahead of mappingComp, and that is the
	* half that had to go. Candidates exist from the moment a metabolite file is
	* uploaded, whether or not anything resolves out of it: upload a compound
	* file none of whose names reach a pathway and the job has candidates, an
	* empty mappingComp, and no hub or class-activity data whatsoever -- and the
	* first clause returned true anyway, so both panels rendered with nothing in
	* them. It only showed in the session that produced the job, because
	* candidates are deleted at step 2 and a reopened job has none, which is why
	* the case reads as working every time it is checked on a reopened job.
	*
	* So the question is asked of the resolved compounds alone, which is what
	* the paragraph above says these panels actually draw. All four cases land
	* correctly: metabolomics that resolves is shown, in the session and after a
	* reopen; metabolomics that resolves to nothing is hidden; no compound omic
	* at all is hidden, as before.
	*/
	this.hasMetaboliteData = function () {
		var model = this.getModel();
		if (!model) {
			return false;
		}
		return !!(model.mappingComp && Object.keys(model.mappingComp).length);
	};

	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	/**
	* This function load of the given model.
	* @chainable
	* @param {JobInstance} model
	* @returns {PA_Step3JobView}
	*/
	this.loadModel = function(model) {
		/********************************************************/
		/* STEP 1: SET THE MODEL		                        */
		/********************************************************/
		if (this.model !== null) {
			this.model.deleteObserver(this);
		}
		this.model = model;
		this.model.addObserver(this);

		// Assign the
		this.isOwner = (String(Ext.util.Cookies.get("userID")) ==  String(this.model.getUserID()));

		/********************************************************/
		/* STEP 2: PROCESS DATA AND GENERATE THE TABLES         */
		/********************************************************/
		var pathways = this.getModel().getPathways();
		var databases = this.getModel().getDatabases();

		/********************************************************/
		/* STEP 2.1.A LOAD VISUAL OPTIONS IF ANY                */
		/********************************************************/
		// TODO: KEEP COMPATIBILITY WITH ALREADY SAVED VISUAL OPTIONS
		var defaultVisualOptions = {
			//GENERAL OPTIONS
			pathwaysVisibility: [],
			//OPTIONS FOR NETWORK
			minFeatures: 0.50,
			minPValue: 0.05,
			/* 0.10, not 0.90.
			   Every other statement of this default in the application says
			   10%: the slider's own markup ships `<span ...>10</span>`, and the
			   help tooltip beside it works its example at "Taking min=10%". The
			   code said 0.9, so the first thing the observer did on load was
			   drag the control to 90% and the documented example described a
			   filter nine times looser than the one in force.

			   It only bites in "Shared biological features" mode, where the
			   threshold is compared against a Sorensen-Dice coefficient - and a
			   Dice coefficient of 0.9 between two pathways means they share
			   nine tenths of their matched features, which essentially nothing
			   does. Measured on a mmu KEGG+Reactome job: the Reactome network
			   drew 11 nodes and 1 edge at 0.9, 3 at 0.1 and 10 with the filter
			   off entirely. So the mode existed and returned almost nothing. */
			minSharedFeatures: 0.10,
			colorBy : "classification",
			backgroundLayout : false,
			showNodeLabels : true,
			useCombinedPvalCheckbox: true,
			autoSaveNodePositions: false,
			//showEdgeLabels : false,
			edgesClass : 'l',
			minNodeSize: 1,
			maxNodeSize: 8,
			networkPvalMethod: 'none',
			fontSize: 14
		};

        var globalDefaultVisualOptions = {
            selectedCombinedMethod: 'Fisher',
            selectedAdjustedMethod: 'None',
            stoufferWeights: {},
			timestamp: this.model.getTimestamp()
        };

		// Initialize dictionaries with databases used
		databases.map((function(db) {
			this.indexedPathways[db] = {};
			this.classificationData[db] = {};
			this.isFiltered[db] = false;
			this.significativePathwaysByDB[db] = 0;
		}).bind(this));

		// Ensure that the visual options timestamp is on par with the model (could be new due to 'Go back' feature)
		if (window.sessionStorage && sessionStorage.getItem("visualOptions") !== null) {
			this.visualOptions = jQuery.extend(jQuery.extend({}, globalDefaultVisualOptions),
                                               JSON.parse(sessionStorage.getItem("visualOptions")));

			// The visualOptions session info can come from an old job (after 'Go back') or updated
			// by recovering the job. Check that the time stamps match or invalidate this block.
			if (this.visualOptions.timestamp >= this.model.getTimestamp()) {
				// If the visualOptions does not contain at least the key KEGG (mandatory)
				// then it has the old format, convert it to the new one.
				databases.map((function(db) {
					if (!(db in this.visualOptions)) {
						/* Avoid referencing to the same object */
						var defaultDBsettings =  jQuery.extend(true, {}, defaultVisualOptions);
						this.visualOptions[db] = {};

						$.each(Object.keys(defaultVisualOptions), (function(index, option) {
							this.visualOptions[db][option] = this.visualOptions[option] ||  defaultDBsettings[option];
							delete this.visualOptions[option];
						}).bind(this));
					}
				}).bind(this));
			} else {
				this.visualOptions = null;
			}
		}
		/********************************************************/
		/* STEP 2.1.B GENERATE DEFAULT VISUAL OPTIONS           */
		/********************************************************/

		this.visualOptions = jQuery.extend(true, {}, globalDefaultVisualOptions, this.visualOptions);

		databases.map((function(db) {
			// jQuery extend with deep copy will merge the arrays, so if we are creating the
			// visual options from scratch we assign all the DB pathways and if not, the very
			// same filtered pathways already saved so the merge won t do anything wrong.
			var dbPathways;

			if (this.visualOptions[db]) {
				dbPathways = $.isEmptyObject(this.visualOptions[db].pathwaysVisibility) ?
					this.getModel().getPathwaysByDB(db).map(x => x.getID()) :
					this.visualOptions[db].pathwaysVisibility;
			} else {
				dbPathways = this.getModel().getPathwaysByDB(db).map(x => x.getID());
			}

			this.visualOptions[db] = jQuery.extend(true, {}, defaultVisualOptions, {pathwaysVisibility: dbPathways}, this.visualOptions[db]);
		}).bind(this));

		this.getController().updateStoredApplicationData("visualOptions", this.visualOptions);


		/********************************************************/
		/* STEP 2.2 GENERATE THE INDEX FOR PATHWAYS             */
		/********************************************************/
		this.indexPathways(pathways);

		/************************************************************/
		/* STEP 2.3 GENERATE THE TABLE WITH PATHWAY CLASSIFICATIONS */
		/************************************************************/
		/*	human_diseases : {
		*		name: "Human diseases",
		*		count: 6,
		*		children: {
		*			"colon_..." : {
		*				name: "Colon...",
		*				count: 10,
		*				children: ["mmu10100", "mmu10340", ...]
		*			},
		*			"wherever..." : {
		*				...
		*			},
		*		},
		*	}
		*/

		/* Duplicate this for each source of pathways */
		for (var i in pathways) {
			pathwayInstance =  pathways[i];
			pathwayDB = pathwayInstance.getSource();

			var isSignificant = false;
			var combinedMethod = this.visualOptions.selectedCombinedMethod;

			if (Object.keys(this.model.summary[4]).length > 1) {
				var totalGlobal = pathwayInstance.getTotalGlobalPvalues();
				var pVal = (totalGlobal && totalGlobal[combinedMethod] !== undefined) ? totalGlobal[combinedMethod] : pathwayInstance.getCombinedSignificanceValueByMethod(combinedMethod);
				if (Array.isArray(pVal)) pVal = pVal[0];
				isSignificant = (pVal !== undefined && pVal !== null && pVal !== "-" && pVal <= 0.05);
			} else {
				var omicName = Object.keys(pathwayInstance.getSignificanceValues())[0];
				var globalOmics = pathwayInstance.getGlobalOmicPvalues();
				var pVal = (globalOmics && globalOmics[omicName] !== undefined) ? globalOmics[omicName] : pathwayInstance.getSignificanceValues()[omicName];
				
				if (Array.isArray(pVal) && pVal.length > 0 && Array.isArray(pVal[0])) pVal = pVal[0][2];
				else if (Array.isArray(pVal) && pVal.length > 2 && !Array.isArray(pVal[0])) pVal = pVal[2];
				else if (Array.isArray(pVal)) pVal = pVal[0];
				
				isSignificant = (pVal !== undefined && pVal !== null && pVal !== "-" && pVal <= 0.05);
			}

			if (isSignificant) {
				this.significativePathways += 1
				this.significativePathwaysByDB[pathwayDB] += 1
			}

			mainClassificationName = pathwayInstance.getClassification().split(";");
			secClassificationName = mainClassificationName[1] || '';
			mainClassificationName = mainClassificationName[0];
			mainClassificationID = mainClassificationName.toLowerCase().replace(/ /g, "_");
			secClassificationID = secClassificationName.toLowerCase().replace(/ /g, "_");

			if(this.classificationData[pathwayDB][mainClassificationID] === undefined){
				this.classificationData[pathwayDB][mainClassificationID] = {
					name: mainClassificationName,
					count: 0,
					children: {}
				};
			}
			this.classificationData[pathwayDB][mainClassificationID].count++;

			if(this.classificationData[pathwayDB][mainClassificationID].children[secClassificationID] === undefined){
				this.classificationData[pathwayDB][mainClassificationID].children[secClassificationID] = {
					name: secClassificationName,
					count: 0,
					children: []
				};
			}
			this.classificationData[pathwayDB][mainClassificationID].children[secClassificationID].count++;
			this.classificationData[pathwayDB][mainClassificationID].children[secClassificationID].children.push(pathwayInstance.getID());
		}

		/************************************************************/
		/* STEP 3 CREATE THE SUBVIEWS                               */
		/************************************************************/
		if(this.pathwayTableView=== null){
			this.pathwayTableView = new PA_Step3PathwayTableView();
			this.pathwayTableView.setController(this.getController());
			this.pathwayTableView.setParent(this);
		}
		this.pathwayTableView.loadModel(model);

		if ( this.metaboliteView === null && this.hasMetaboliteData()) {
			this.metaboliteView = new PA_Step3MetaboliteView();
			this.metaboliteView.setController(this.getController());
			this.metaboliteView.setParent(this);
			this.metaboliteView.loadModel(model);
		}

		if (this.hubAnalysisView === null) {
			this.hubAnalysisView = new PA_Step3HubAnalysis();
			this.hubAnalysisView.setController(this.getController());
			this.hubAnalysisView.setParent(this);
		}
		this.hubAnalysisView.loadModel(model);

		// The metabolite hop-ring network. Constructed unconditionally -- it
		// renders a hidden container until a hub row asks for a compound.
		if (this.hubNetworkView === null) {
			this.hubNetworkView = new PA_Step3HubNetworkView();
			this.hubNetworkView.setController(this.getController());
			this.hubNetworkView.setParent(this);
		}
		this.hubNetworkView.loadModel(model);

		// MORE Regulation panel — instantiate unconditionally; the view itself
		// self-suppresses when the model has no rpc data, so we don't have to
		// branch on MORE-vs-Pairwise here.
		if (this.regulationView === null) {
			this.regulationView = new PA_Step3RegulationView();
			this.regulationView.setController(this.getController());
			this.regulationView.setParent(this);
		}
		this.regulationView.loadModel(model);

		// MORE Regulator–Target Network panel — same self-suppression contract
		// as the regulation table, so wiring is unconditional.
		if (this.regTargetNetworkView === null) {
			this.regTargetNetworkView = new PA_Step3RegTargetNetworkView();
			this.regTargetNetworkView.setController(this.getController());
			this.regTargetNetworkView.setParent(this);
		}
		this.regTargetNetworkView.loadModel(model);

		this.statsView = new PA_Step3StatsView();
		this.statsView.loadModel(model);

		$.each(databases, (function(index, db) {
			if(!(db in this.pathwayClassificationViews)){
				this.pathwayClassificationViews[db] = new PA_Step3PathwayClassificationView(db);
				this.pathwayClassificationViews[db].setController(this.getController());
				this.pathwayClassificationViews[db].setParent(this);
			}
			this.pathwayClassificationViews[db].loadModel(model);

			if(!(db in this.pathwayNetworkViews)){
				this.pathwayNetworkViews[db] = new PA_Step3PathwayNetworkView(db);
				this.pathwayNetworkViews[db].setController(this.getController());
				this.pathwayNetworkViews[db].setParent(this);
			}
			this.pathwayNetworkViews[db].loadModel(model);

			// Determine if the table for the DB is filtered or not
			this.isFiltered[db] = (this.model.getPathwaysByDB(db).length != this.getTotalVisiblePathways(db).visible);
		}).bind(this));

		if (this.getModel().isRecoveredJob && this.getModel().getStepNumber() === 3) {
			$(".backButton").hide();
		}


		return this;
	};



	this.canEdit = function() {
		return (this.isOwner || ! this.model.getReadOnly());
	};

	this.getVisualOptions = function(db = null){
		return (db == null) ? this.visualOptions : this.visualOptions[db];
	};
	this.setVisualOptions = function(propertyName, value, db = null) {
		if (db == null) {
			this.visualOptions[propertyName] = value;
		} else {
			this.visualOptions[db][propertyName] = value;
		}
	};
	this.getClassificationData = function(db = null){
		return (db == null) ? this.classificationData : this.classificationData[db];
	};
	this.getIndexedPathways = function(db = null){
		return (db == null) ? this.indexedPathways : this.indexedPathways[db];
	};

	this.indexPathways = function(pathways) {
		var pathwayInstance;
		for (var i in pathways) {
			pathwayInstance =  pathways[i];
			pathwayInstance.setVisible(this.visualOptions[pathwayInstance.getSource()].pathwaysVisibility.indexOf(pathwayInstance.getID()) !== -1);
			this.indexedPathways[pathwayInstance.getSource()][pathwayInstance.getID()] = pathwayInstance;
		}
		$.each(this.getModel().getDatabases(), (function(index, db) {
			if(this.visualOptions[db].pathwaysPositions !== undefined){
				var data;
				for(var i in this.visualOptions[db].pathwaysPositions){
					data = this.visualOptions[db].pathwaysPositions[i].split("#");
					this.indexedPathways[db][data[0]].networkCoordX = Number.parseFloat(data[1]);
					this.indexedPathways[db][data[0]].networkCoordY = Number.parseFloat(data[2]);
				}
			}
		}).bind(this));
	};

	this.getTotalVisiblePathways = function(db){
		var visible = 0;
		var significative = 0;
		var pathways = (db == undefined ? this.getModel().getPathways() : this.getModel().getPathwaysByDB(db));
		var combinedMethod = this.visualOptions.selectedCombinedMethod;
		for (var i in pathways) {
			visible += (pathways[i].isVisible() ? 1 : 0);
			if (!pathways[i].isVisible()) continue;

			var isSignificant = false;
			if (Object.keys(this.model.summary[4]).length > 1) {
				var totalGlobal = pathways[i].getTotalGlobalPvalues();
				var pVal = (totalGlobal && totalGlobal[combinedMethod] !== undefined) ? totalGlobal[combinedMethod] : pathways[i].getCombinedSignificanceValueByMethod(combinedMethod);
				if (Array.isArray(pVal)) pVal = pVal[0];
				isSignificant = (pVal !== undefined && pVal !== null && pVal !== "-" && pVal <= 0.05);
			} else {
				var omicName = Object.keys(pathways[i].getSignificanceValues())[0];
				var globalOmics = pathways[i].getGlobalOmicPvalues();
				var pVal = (globalOmics && globalOmics[omicName] !== undefined) ? globalOmics[omicName] : pathways[i].getSignificanceValues()[omicName];
				
				if (Array.isArray(pVal) && pVal.length > 0 && Array.isArray(pVal[0])) pVal = pVal[0][2];
				else if (Array.isArray(pVal) && pVal.length > 2 && !Array.isArray(pVal[0])) pVal = pVal[2];
				else if (Array.isArray(pVal)) pVal = pVal[0];

				isSignificant = (pVal !== undefined && pVal !== null && pVal !== "-" && pVal <= 0.05);
			}
			significative += isSignificant ? 1 : 0;
		}

		var visiblePathways = {
			visible: visible,
			significative : significative
		};
		return visiblePathways;
	};

	/*********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* This function returns the corresponding color for the given classification id
	* @param {String} classificationID, the id for the classification
	* @param {String[]} otherColors, list of colors in case that the classification is not found
	* @returns {String} the hexadecimal color code
	**/
	this.getClassificationColor = function(classificationID, otherColors){
		var colors = ["#007AFF",  "#4CD964", "#FF2D55", "#FFCD02", "#5AC8FB", "#C644FC", "#FF9500",
					  "#6b5b95", "#b2ad7f", "#a2b9bc", "#b5e7a0", "#b9936c", "#d6cbd3", "#eca1a6", "#bdcebe", "#e3eaa7", "#c1946a", "#034f84", "#92a8d1", "#deeaee", "#ffef96", "#50394c",
					  "#618685", "#c1502e", "#7a3b2e", "#99ffcc", "#ffff00", "#990033", "#990099", "#994d00", "#269900", "#009999", "#008888", "#007777", "#006666", "#005555"];
		var pos = ["cellular_processes", "environmental_information_processing", "genetic_information_processing", "human_diseases", "metabolism", "organismal_systems", "overview",
				  // Added Reactome classification
				  "cell_cycle", "cell-cell_communication", "cellular_responses_to_external_stimuli", "chromatin_organization", "circadian_clock", "developmental_biology",
				  "digestion_and_absorption", "disease", "dna_repair", "dna_replication", "extracellular_matrix_organization", "gene_expression_(transcription)",
				  "hemostasis", "immune_system", "metabolism_of_proteins", "metabolism_of_rna", "mitophagy", "muscle_contraction", "neuronal_system",
				  "organelle_biogenesis_and_maintenance", "programmed_cell_death", "reproduction", "signal_transduction", "transport_of_small_molecules",
			      "vesicle-mediated_transport", "cellular_responses_to_stimuli", "autophagy", "sensory_preception", "protein_localization"].indexOf(classificationID);

		if(pos !== -1){
			return colors[pos];
		}
		if(otherColors && otherColors.length > 0){
			return otherColors.shift();
		}

		/* The list above names only KEGG's and Reactome's classifications, and
		   three callers inside generateNetwork pass no `otherColors` at all --
		   they never needed to, because for those two sources the lookup always
		   hit. Any other source fell straight through to `otherColors.length`
		   and threw, which killed the network build with the "Building
		   network..." spinner still on screen and no visible error. OmniPath's
		   categories are the first to reach here.

		   The fallback is derived from the name rather than taken from a shared
		   palette because those three calls ask about the SAME node (its fill,
		   its glyph text and its glyph stroke): shifting a palette would hand
		   one node three different colours. */
		if(!classificationID){
			return "#333";
		}
		var hash = 0;
		for(var c = 0; c < classificationID.length; c++){
			hash = ((hash << 5) - hash + classificationID.charCodeAt(c)) | 0;
		}
		return colors[Math.abs(hash) % colors.length];
	};

	this.backButtonHandler = function() {
		this.controller.backButtonClickHandler(this);
	};
	this.resetViewHandler = function() {
		this.controller.resetButtonClickHandler(this);
	};

	/**
	* This function updates the visual representation of the model.
	* - STEP 1: LOAD SUMMARY
	* - STEP 2: GENERATE THE PATHWAYS CLASSIFICATION PLOT
	* - STEP 3: GENERATE THE TABLE
	* - STEP 4: GENERATE THE PATHWAYS NETWORK
	* - STEP 5: UPDATE THE SUMMARY
	* @returns {PA_Step3JobView}
	*/
	this.updateObserver = function() {
		var me = this;

		/********************************************************/
		/* STEP 1: LOAD SUMMARY      		                    */
		/********************************************************/
		$("#jobIdField").text(this.getModel().getJobID());
		/* The anchor is a glyph button now; the URL is its target, not its text.
		   Writing the href as text was what made the old card read as a
		   paragraph about itself. */
		$("#jobURL").attr('href', window.location.href);

		// Update Job name (description) if available. Long names are clipped
		// with an ellipsis by the stylesheet, so the full text rides the title.
		if (this.getModel().getName()) {
			$("#jobName").text(this.getModel().getName())
				.attr('title', this.getModel().getName()).show();
		}

		/********************************************************/
		/* STEP 2: GENERATE THE PATHWAYS CLASSIFICATION PLOT    */
		/********************************************************/
		$.each(this.pathwayClassificationViews, function(index, view) {
			view.updateObserver();
		});
		/********************************************************/
		/* STEP 3: GENERATE THE TABLE						     /
		/********************************************************/
		this.pathwayTableView.updateObserver();

		if (this.metaboliteView) {
			this.metaboliteView.updateObserver();
		}

		this.hubAnalysisView.updateObserver();
		/********************************************************/
		/* STEP 4: GENERATE THE PATHWAYS NETWORK                */
		/********************************************************/
		$.each(this.pathwayNetworkViews, function(index, view) {
			view.updateObserver();
		});
		/********************************************************/
		/* STEP 5: UPDATE THE SUMMARY                           */
		/********************************************************/
		setTimeout(function() {
			var databases = me.model.getDatabases();
			var totalFound = totalSignificative = 0;

			databases.forEach(function(dbname) {
				var visiblePathways = me.getTotalVisiblePathways(dbname);

				$("#foundPathwaysTag_" + dbname).html(visiblePathways.visible);
				$("#significantPathwaysTag_" + dbname).html(visiblePathways.significative);

				totalFound += visiblePathways.visible;
				totalSignificative += visiblePathways.significative;
			});

			$("#foundPathwaysTag").html(totalFound);
			$("#significantPathwaysTag").html(totalSignificative);
		}, 1000);

		initializeTooltips(".helpTip");

		me.refreshAIWidget();

		return this;
	};

	/**
	* This function apply the settings that user can change
	* for the visual representation of the model (w/o reload everything).
	* - STEP 1: DO WHEREVER (include here code if necessary)
	* - STEP 2. UPDATE THE TABLE WITH THE SELECTED OPTIONS (only if updating from categories panel)
	* - STEP 3. UPDATE THE pathwayNetworkView VIEW
	* - STEP 4. UPDATE THE CACHE
	* @chainable
	* @param {String} caller, the name of the view that calls this function
	* @returns {PA_Step3JobView}
	*/
	this.applyVisualSettings = function(caller, db = "KEGG") {
		var me = this;
		/********************************************************/
		/* STEP 1: DO WHEREVER (include here code if necessary) */
		/********************************************************/

		if(caller === "PA_Step3PathwayClassificationView"){
			/* Mark databases as filtered or not */
			this.model.databases.forEach(function(db) {
				me.isFiltered[db] = (me.model.getPathwaysByDB(db).length != me.getTotalVisiblePathways(db).visible);
			});

			/********************************************************/
			/* STEP 2. UPDATE THE TABLE WITH THE SELECTED OPTIONS   */
			/*         (only if updating from categories panel)     */
			/********************************************************/
			this.pathwayTableView.updateVisiblePathways(true);
			/* Guarded, because the metabolite view is only constructed when the
			   job resolved compounds - see hasMetaboliteData() at the top of this
			   file - and the hub view only when it has a result to show.

			   Unguarded, this line threw `Cannot read properties of null` on
			   every job without metabolomics, and it threw *here*: before the
			   network refresh below it, before the summary counts, and before the
			   cache write. So on a gene-only job, choosing categories and pressing
			   Apply redrew the pie beside the filter - that happens earlier, in
			   the classification view - and then silently did nothing else. The
			   network kept every node you had just hidden and the Found/
			   Significant counts kept their unfiltered totals, which is the one
			   reading a user would take as "the filter did not work".

			   Verified on this build before the guard: hide one KEGG category,
			   Apply, and 94 of 364 pathways go unchecked while the network still
			   reports "25 of 364" and the summary still reports 364. */
			if (this.metaboliteView) {
				this.metaboliteView.updateVisiblePathways(true);
			}
			if (this.hubAnalysisView) {
				this.hubAnalysisView.updateObserver(true);
			}
		}
		/********************************************************/
		/* STEP 3. UPDATE THE pathwayNetworkView VIEW           */
		/********************************************************/
		this.pathwayNetworkViews[db].updateObserver();

		/********************************************************/
		/* STEP 4. UPDATE THE CACHE
		/********************************************************/
		me.getController().updateStoredVisualOptions(me.getModel().getJobID(), me.visualOptions);

		/********************************************************/
		/* STEP 5: UPDATE THE SUMMARY                           */
		/********************************************************/
		setTimeout(function() {
			var databases = me.model.getDatabases();
			var totalFound = totalSignificative = 0;

			databases.forEach(function(dbname) {
				var visiblePathways = me.getTotalVisiblePathways(dbname);

				$("#foundPathwaysTag_" + dbname).html(visiblePathways.visible);
				$("#significantPathwaysTag_" + dbname).html(visiblePathways.significative);

				totalFound += visiblePathways.visible;
				totalSignificative += visiblePathways.significative;
			});

			$("#foundPathwaysTag").html(totalFound);
			$("#significantPathwaysTag").html(totalSignificative);
		}, 1000);

		return this;
	};

	/**
	* This function opens a new view (STEP4 VIEW) for the selected pathway.
	* @chainable
	* @param {String} pathwayID, the ID for the selected pathway
	* @returns {PA_Step3JobView}
	*/
	this.paintSelectedPathway = function(pathwayID) {
		$.each(this.pathwayNetworkViews, function(index, network) { network.stopNetworkLayout(); });
		this.getController().step3OnFormSubmitHandler(this, pathwayID);
		return this;
	};

	this.shareHandler = function(){
		var me = this;
		var model = me.getModel();
		var userID = Ext.util.Cookies.get("userID");
		// A job created without an account has no owner (userID null), so the
		// server cannot tell "the owner came back" from "anyone arrived
		// anonymously" and never enforces the flags saved here. String(null) ==
		// String(null) used to make every anonymous visitor the owner of an
		// ownerless job, offering a Read-only promise nobody keeps; those jobs
		// belong in the explanatory branch below, which already names this case.
		var jobOwner = model.getUserID();
		var hasOwner = (jobOwner !== null && jobOwner !== undefined && String(jobOwner) !== "null" && String(jobOwner) !== "None");
		var isOwner = (hasOwner && userID !== null && userID !== undefined && String(jobOwner) == String(userID));

		var messageDialog = Ext.create('Ext.window.Window', {
			title: "Sharing options",
			height: 350, width: 600, modal: true, bodyPadding:10,
			defaults: {
				labelAlign: "right",
				border: false
			},
			items: [
				{
					xtype:"box", html:
					// The last sentence is owner-only. It points at the Read-only
					// checkbox, and that checkbox is inside the `isOwner` branch below -
					// so a non-owner was being told to use a control that is not on their
					// screen, directly above the line explaining they cannot change
					// anything here.
					"<div style='margin-bottom:10px;'>Jobs created while you are signed in are private by default; jobs created without an account are public.<br><br>Filtering and visual settings are stored on the server, so anyone you share the link with sees the same view &mdash; and can change it." + (isOwner ? " Use the read-only option below to prevent that." : "") + "</div>" +
					"<div>The link to this job is: <a href='" + window.location.href + "' target='_blank'>" + window.location.href +"</a></div><br><br>"
				},
				(isOwner ?
				 {
					xtype: 'fieldcontainer',
            		defaultType: 'checkboxfield',
            		items: [
						{
							boxLabel  : 'Allow link sharing',
							name      : 'linksharing',
							checked   : model.getAllowSharing(),
							id        : 'linksharing'
                		},
						{
							boxLabel  : 'Read-only (for others)',
							name      : 'readonly',
							checked   : model.getReadOnly(),
							id        : 'readonly'
                		},

					]
				 }
				 :
				 {xtype: "box", html: "<br><div style='text-align: center;'><b>You are not the owner or the job does not have an owner account so sharing options cannot be modified.</b></div>"}
				)
			],
			// An empty object here still renders as a button: a blank blue pill
			// beside Close for everyone in the non-owner branch. Concat, so the
			// Save button either exists whole or not at all.
			buttons: (isOwner ? [{
					text: 'Save options',
					handler : function() {
						var allowSharing = messageDialog.queryById('linksharing').getValue();
						var readOnly = messageDialog.queryById('readonly').getValue();

						messageDialog.close();
						me.getController().updateSharingOptions(model, allowSharing, readOnly);
					}
				}] : []).concat([
				{text: 'Close', handler : function() {messageDialog.close();}}
			])
		});

		messageDialog.center();
		messageDialog.show();
	};

	// The poll is a self-rescheduling chain, so every answer -- including the
	// ones that are not answers -- has to decide what happens next. This
	// rescheduled only from `success` and declared no `error` handler at all,
	// so a single request that did not land ended the chain for good.
	// Measured in Chrome against a real job: five healthy polls, a server
	// restart, a sixth answering `ERR http=0`, and the page never issued
	// another status request. The interpretation finished and was stored,
	// while the widget sat at "Generating interpretation..." with an empty
	// message area until the page was reloaded -- which is exactly how the bug
	// was reported. A run polls every 3s for 5-15 minutes, so one blip (a
	// deploy, a sleep/wake, a VPN reconnect) was enough to trigger it.
	//
	// Only done/error/cancelled end the chain now. A transport failure backs
	// off so a server that is down is not hammered, and the normal cadence
	// returns as soon as it answers again.
	this.pollAIStatus = function() {
		var me = this;
		var BACKOFF_CEILING = 30000;
		var schedule = function(delay) {
			if (!me.aiWidget) { return; }   // widget gone: nothing left to update
			me.pollTimerID = setTimeout(function() { me.pollAIStatus(); }, delay);
		};
		$.ajax({
			type: "POST", url: SERVER_URL_AI_INTERPRET_STATUS,
			data: { jobID: me.getModel().getJobID() },
			success: function(r) {
				if (!me.aiWidget) { return; }
				// success:false is what the servlet returns for any handled
				// exception. Most are worth another look -- a Mongo hiccup, a
				// momentary blip -- but two are not, and treating those as
				// transient is what left the widget saying "Starting..." with
				// an empty panel for as long as the tab stayed open.
				//
				// The job going missing is the one that bites. A reopened job
				// is drawn from the copy the browser keeps in sessionStorage,
				// so the page never asks the server whether the job is still
				// there; the AI report is the only thing that does. Once the
				// job has been removed -- 7 days for guests, 14 for registered
				// users -- the report request is refused and no amount of
				// asking again will change that. Measured before this change:
				// four polls in twenty seconds, still going, nothing shown.
				if (!r || !r.success) {
					var why = String((r && r.message) || "");
					if (/not found|Invalid Job ID/i.test(why)) {
						me.aiWidget.updateProgress(
							"unavailable", 100,
							"This job is no longer stored on the server, so its " +
							"AI interpretation cannot be loaded. Jobs are removed " +
							"after 7 days for guests and 14 days for registered " +
							"users.");
						return;              // permanent: stop the chain
					}
					// Anything else may well clear. Keep trying, but not for
					// ever, and say so rather than leaving the panel blank.
					me.aiPollFailures = (me.aiPollFailures || 0) + 1;
					if (me.aiPollFailures >= AI_POLL_MAX_FAILURES) {
						me.aiWidget.updateProgress(
							"error", 100,
							"The server stopped answering while tracking this " +
							"interpretation. Reload the page to try again.");
						return;
					}
					schedule(AI_POLL_INTERVAL);
					return;
				}
				me.aiPollFailures = 0;
				me.aiWidget.updateProgress(r.status, r.percent, r.detail,
				                           r.toolTrace, r.toolCalls);
				if (r.status !== "done" && r.status !== "error" && r.status !== "cancelled") {
					schedule(AI_POLL_INTERVAL);
				}
			},
			error: function(jqXHR) {
				// Retrying is right for a TRANSPORT failure and wrong for a
				// permanent one. Both used to back off and retry forever.
				//
				// Measured on the live server: after a restart invalidated one
				// user's in-process session, their browser polled
				// /ai_interpret_status every 31 s and got
				// "400 CredentialException: User not valid ... please log-in
				// again" for FOUR HOURS -- about 460 requests -- with nothing
				// shown to them. A session that has expired cannot un-expire by
				// being asked again.
				//
				// 401/403 are unambiguous. A 400 is only treated as permanent
				// when the body says so, because the servlet also returns 400
				// for ordinary handled errors that a retry may well clear.
				var code = jqXHR && jqXHR.status;
				var body = (jqXHR && jqXHR.responseText) || "";
				var expired = code === 401 || code === 403 ||
				              (code === 400 && /session|log-in|log in|not valid/i.test(body));
				if (expired) {
					if (me.aiWidget) {
						me.aiWidget.updateProgress(
							"error", 100,
							"Your session expired, so progress can no longer be " +
							"tracked. Your job is safe on the server \u2014 sign in " +
							"again and reopen it from My Jobs.");
					}
					return;      // stop the chain: nothing here can recover it
				}

				// THE JOB IS GONE. This arrives HERE, not in the success
				// handler, and that distinction is the whole bug: the servlet
				// renders a UserWarning as HTTP 400, so jQuery routes it to
				// `error`. A `success:false` body never carries this case at
				// all, which is why guarding only that looked right and
				// changed nothing.
				//
				// A reopened job is drawn from the copy the browser holds, so
				// the page never asks whether the job still exists; the status
				// poll is the only thing that does. Once the job has been
				// removed -- 7 days for guests, 14 for registered users -- the
				// answer is a refusal, and asking again cannot change it.
				// Measured before this: four polls in twenty seconds, still
				// going, "Starting..." and an empty panel.
				var missing = (code === 400 || code === 404) &&
				              /not found|Invalid Job ID/i.test(body);
				if (missing) {
					if (me.aiWidget) {
						me.aiWidget.updateProgress(
							"unavailable", 100,
							"This job is no longer stored on the server, so its " +
							"AI interpretation cannot be loaded. Jobs are removed " +
							"after 7 days for guests and 14 days for registered " +
							"users.");
					}
					return;      // permanent: stop the chain
				}

				me.aiPollFailures = (me.aiPollFailures || 0) + 1;
				if (me.aiPollFailures >= AI_POLL_MAX_FAILURES) {
					// A server that has stopped answering is not made to answer
					// by asking a hundred more times, and the user should be
					// told rather than watching a bar that never moves.
					if (me.aiWidget) {
						me.aiWidget.updateProgress(
							"error", 100,
							"The server stopped answering while tracking this " +
							"interpretation. Reload the page to try again.");
					}
					return;
				}
				schedule(Math.min(AI_POLL_INTERVAL * Math.pow(2, me.aiPollFailures - 1),
				                  BACKOFF_CEILING));
			}
		});
	};

	this.cleanupAIWidget = function() {
		if (this.pollTimerID) {
			clearTimeout(this.pollTimerID);
			this.pollTimerID = null;
		}
		if (this.aiWidget) {
			this.aiWidget.destroy();
			this.aiWidget = null;
		}
		this.aiClusters = null;
		this.aiJobID = null;
		$("#aiInterpretButton").hide();
	};

	this.refreshAIWidget = function() {
		var me = this;
		var jobID = me.getModel().getJobID();
		var hasConsent = me.getModel().aiConsent;

		if (!hasConsent || !jobID) {
			me.cleanupAIWidget();
			return;
		}

		// Same job — skip recreation
		if (me.aiJobID === jobID && me.aiWidget) {
			return;
		}

		// Different job or first time — clean old, create new
		me.cleanupAIWidget();
		me.aiJobID = jobID;

		$("#aiInterpretButton").show();
		me.aiWidget = new PA_AIInterpretView();
		me.aiWidget.init(jobID);
		// Cluster mode: the report carries the shared-feature partition it was
		// written from. Keep it on the Step 3 view and let each pathway network
		// offer "AI pathway clusters" as a colouring; the network itself is
		// only redrawn when the user applies the option.
		me.aiWidget.onClustersLoaded = function(clusters) {
			me.aiClusters = (clusters && clusters.clusters && clusters.clusters.length) ? clusters : null;
			$.each(me.pathwayNetworkViews, function(db, view) {
				try { view.updateObserver(); } catch (e) { console.warn(e); }
			});
		};
		me.aiWidget.onRetry = function() {
			$.ajax({
				type: "POST", url: SERVER_URL_AI_INTERPRET_INITIATE,
				data: {
					jobID: jobID,
					experimentDesign: me.getModel().experimentDesign || ""
				},
				success: function() { me.pollAIStatus(); }
			});
		};
		me.aiWidget.show();
		me.pollAIStatus();
	};

	this.toggleAIWidget = function() {
		if (this.aiWidget) {
			this.aiWidget.toggle();
		}
	};

	/**
	* This function generates the component (EXTJS) using the content of the
	* JobInstance model
	* @returns {Ext.ComponentView} The visual component
	*/
	this.initComponent = function() {
		var me = this;

		/* Initialize tab content */
		var tabContent = [];

		/* If there is only one database, use a container instead of tabpanel */
		$.each(this.getModel().getDatabases(), (function(index, db) {
			var tabDB = {
				title: db,
				/* One card, not four.

				   A database tab used to draw four separate bordered surfaces:
				   "Pathways classification", "Pathways network", and the network's
				   two 216px side panels, "Tools" and "Details". They are one
				   activity - choose which pathways you are looking at, then look at
				   them - and splitting the controls for it across four boxes meant
				   that changing what the graph shows was a matter of finding which
				   box the control was in. The category filter and the node filters
				   in particular sit 900px apart on screen while doing the same job.

				   They are one .contentbox now. That is also what the contents
				   strip reads: paTocSections() takes one entry per card, so the
				   sidebar lists one "Pathway explorer" per database rather than a
				   classification entry and a network entry that scroll to the same
				   card. */
				items: [{
					xtype: 'container',
					cls: 'contentbox paExploreCard',
					items: [
						this.pathwayClassificationViews[db].getComponent(),
						this.pathwayNetworkViews[db].getComponent()
					]
				}]
			}

			tabContent.push(tabDB)
		}).bind(this));

		this.component = Ext.widget({
			xtype: "container",
			padding: '10', border: 0, maxWidth: 1900,
			items: [
				// AI widget is created in boxready handler
				{ //THE TOOLBAR
					xtype: "box",cls: "toolbar secondTopToolbar", html:
					/* Short labels, and they are short on purpose. This is the widest
					   toolbar in the app and it shares the header row with the nav:
					   when the two meet, MainView's fitHeaderNav() drops the nav's
					   words and leaves bare icons, which is what this screen looked
					   like at "Reset view / Hide mapping info / Sharing options / AI
					   Interpret". Trimming the three verbose labels - the icon beside
					   each already carries the verb - gives back ~110px, enough for
					   the nav to keep its words at the widths this is used at. The
					   ladder in fitHeaderNav is still there for narrower windows; it
					   is just no longer the normal state of the results page.

					   "Hide mapping" keeps the word Hide: the handler below toggles
					   this label by string-replacing Hide with Show, so a label
					   without it silently stops toggling. */
					'<a href="javascript:void(0)" class="button btn-danger btn-right" id="resetButton"><i class="fa fa-refresh"></i> Reset</a>' +
					//'<a href="javascript:void(0)" class="button btn-default btn-right backButton"><i class="fa fa-arrow-left"></i> Go back</a>'
					'<a href="javascript:void(0)" class="button btn-default btn-right mappingButton"><i class="fa fa-database"></i> Hide mapping</a>' +
					'<a href="javascript:void(0)" class="button btn-default btn-right" id="sharingButton"><i class="fa fa-share-alt"></i> Share</a>' +
					'<a href="javascript:void(0)" class="button btn-info btn-right" id="aiInterpretButton" style="display:none;">' + getAIMark() + ' AI Interpret</a>' +
					'<div id="warningMessage" style="display: none;"></div>'
				},{ //THE SUMMARY BAND
					/* One band, not three cards.

					   This region used to be two side-by-side cards ("Pathways
					   selection" - four lines of prose about how significance is
					   computed - and "Pathways summary" - job ID, the full URL
					   written out, two counts) plus a third full-width card
					   ("Multiple databases used" - two more paragraphs and a
					   table). Roughly 700px of reading before the first real
					   control, and almost none of it data: the prose never
					   changes, the URL is the one in the address bar, and the
					   paint link scrolled nowhere.

					   Everything that varies by job now sits in one card: the
					   counts, the per-database split, the job identity. The
					   explanation of how significance is computed - true for
					   every job - lives in the heading's tooltip, and the two
					   paragraphs about database tabs became the one-line note
					   beside the table they described. The IDs are unchanged
					   on purpose: jobIdField/jobURL/jobName are filled by
					   updateObserver, the two odometers by the summary refresh,
					   and #multisource_summary by the per-database table built
					   in afterrender. */
					xtype: 'box', itemId: "pathwaysSummaryPanel",
					cls: "contentbox po-band-card",
					style: "max-width:1900px; margin: 5px 10px; margin-top:50px;",
					html:
					'<div class="po-band-head">' +
					'  <h2>Pathways summary<span class="helpTip" title="Each pathway is scored per submitted omic type: its significance comes from how many of its features (genes and compounds) are present in your input, against the total the pathway contains. When two or more omic types are submitted, a Combined Significance Value ranks pathways across all of them."></span></h2>' +
					'  <span id="jobName" class="po-job-name" style="display: none"></span>' +
					'  <div class="po-band-actions">' +
					'    <span class="po-job-chip">Job <b id="jobIdField">&mdash;</b>' +
					// Two glyph buttons, labelled for readers since neither has text:
					// open the shareable URL, and put it on the clipboard.
					'      <a id="jobURL" target="_blank" href="#" title="Open the shareable link for this job" aria-label="Open the shareable link for this job"><i class="fa fa-external-link"></i></a>' +
					'      <a id="copyJobURL" href="javascript:void(0)" title="Copy the shareable link" aria-label="Copy the shareable link"><i class="fa fa-clipboard"></i></a>' +
					'    </span>' +
					'    <a id="paint_link" class="button btn-info" href="javascript:void(0)"><i class="fa fa-paint-brush"></i> Pick pathways to paint</a>' +
					'  </div>' +
					'</div>' +
					// The icons are decorative -- the label beside each count
					// already names it -- so they are hidden from screen
					// readers rather than read out as "star".
					'<div class="po-band">' +
					'  <div class="po-pathway-stat">' +
					'    <span class="po-pathway-icon" aria-hidden="true"><i class="fa fa-sitemap"></i></span>' +
					'    <span class="po-band-figure">' +
					'      <div id="foundPathwaysTag" class="odometer odometer-theme-default po-pathway-count">000</div>' +
					'      <span class="po-pathway-label">Pathways found</span>' +
					'    </span>' +
					'  </div>' +
					'  <div class="po-pathway-stat">' +
					'    <span class="po-pathway-icon is-significant" aria-hidden="true"><i class="fa fa-star"></i></span>' +
					'    <span class="po-band-figure">' +
					'      <div id="significantPathwaysTag" class="odometer odometer-theme-default po-pathway-count">000</div>' +
					'      <span class="po-pathway-label">Significant</span>' +
					'    </span>' +
					'  </div>' +
					((me.getModel().getDatabases().length < 2) ? '' :
					'  <div class="po-band-dbs">' +
					'    <div id="multisource_summary"></div>' +
					// data-guides="ignore": a lone flex item beside a table whose
					// cells key per-column - the guides overlay has no group that
					// can hold both, so measured raw it reports against the card
					// rail 400px to its left while sitting in the cell's own flow.
					'    <p class="po-band-note" data-guides="ignore">One explorer tab per database below; the enrichment table lists all of them, filterable from its search bar.</p>' +
					'  </div>') +
					'</div>'
				},
				me.statsView.getComponent(),
				{
						xtype: 'tabpanel', id: 'tabcontainer_network', plain: true,
						deferredRender: false, items: tabContent, border: false,
						cls: ((me.getModel().getDatabases().length < 2) ? 'onedatabase' : ''),
						style: "max-width:1900px; margin: 5px 10px; margin-top:20px; height: auto;",
						tabBar: {
							/* Hide tab bar when there is only one database */
							hidden: (me.getModel().getDatabases().length < 2),
							defaults: {
								height: 40,
								/* The gap between tabs, and it has to be stated here
								   rather than in CSS: a tab bar is an ExtJS box layout,
								   which measures each tab and writes an absolute
								   position for it, so a `margin-right` from the
								   stylesheet is overwritten inline and a wider tab just
								   overlaps its neighbour. Measured that way - "KEGG"
								   ended at 299 and "Reactome" began at 303, four pixels
								   between two words that name different databases, so
								   the strip read as the single phrase "KEGG Reactome"
								   rather than as two controls.

								   22px was the answer while the tabs were bare
								   words. They are bookmark tabs now - see "The
								   database tabs" in main.css - and a box does
								   its own separating: at 22 the two read as
								   unrelated buttons that happened to land side
								   by side rather than as one control with two
								   positions.

								   4, not 6: tabs on a folder sit close enough
								   that the sheets behind read as a stack. At 6
								   they were still two objects with air between
								   them. */
								margin: '0 4 0 0'
							},
							/* The bar is exactly as tall as a tab. It was 50
							   against a 38px tab, so the tabs floated in a
							   12px band and could not meet the card below
							   them - which is the whole of what a bookmark
							   tab has to do. */
							height: 36,
						},
						listeners: {
							/* A card layout writes the width it measured onto its
							   child as an inline style and never re-derives it, so
							   a tab panel that is laid out before the page column
							   settles keeps the wrong width for the rest of the
							   session.

							   That is what happens here. The contents sidebar
							   reserves its column only once the sections it lists
							   exist, which is a second or so after this panel first
							   renders, and `paTocSyncRail` re-lays out the viewport
							   when it does - but that run stops at this panel, whose
							   own width is by then correct, and never asks the card
							   layout to re-place a child whose width is already
							   written. Measured on a KEGG+Reactome job at 1440: this
							   panel 1114 wide with its active child still 1184, so
							   "Pathways classification" and the network's Details
							   panel ran to x=1450 while every card outside the tabs
							   stopped at 1380. On a job with metabolites the overhang
							   escaped as a horizontal scrollbar on the whole page.

							   Hooked on resize rather than on the sidebar, because
							   the panel being narrower than its child is the fault
							   itself - whatever caused it, and including a window
							   resize. Clearing the width is what allows a re-measure;
							   the panel's own updateLayout is what reaches the card
							   layout. Deferred out of the layout run that raised this
							   event, and self-limiting: after the correction no child
							   is wider than the panel, so it does not fire again. */
							resize: function(tabPanel, width) {
								var stale = [];

								tabPanel.items.each(function(child) {
									if (child.getWidth && child.getWidth() > width) {
										child.setWidth(null);
										stale.push(child);
									}
								});

								if (stale.length) {
									setTimeout(function() {
										if (!tabPanel.isDestroyed) {
											tabPanel.updateLayout();
										}
									}, 0);
								}
							},
							tabchange: function(tabPanel, newCard, oldCard, eOpts) {
								/* Looked up by id rather than by position. The two views
								   are wrapped in one card now, so the network is no longer
								   the tab's second child - and a position that is wrong is
								   silent here, because fireEvent on the classification box
								   simply matches no listener and the network never draws
								   itself on first switch. */
								var networkCmp = Ext.getCmp('networkview_' + newCard.title.replace(' ', '__'));
								if (networkCmp) {
									networkCmp.fireEvent('tabchange');
								}

								// Rebuild the contents list for the database now
								// showing. paTocSections() skips headings whose
								// offsetParent is null, which is right when the
								// list is built -- but both databases' sections
								// live in the DOM at once and the tabs only
								// switch which is visible, so the list built on
								// first render kept naming KEGG after a switch
								// to Reactome. The entries then pointed at
								// hidden headings while the visible ones,
								// "Pathways classification (Reactome database)"
								// and its network, were missing from it
								// entirely. Only reachable with two databases,
								// which is why the single-database case never
								// showed it. Deferred so the new card has been
								// laid out and its headings measure as visible.
								$.wait(function () {
									buildAnalysisTOC('#mainViewCenterPanel');
								}, 0.3);
							}
						}
				},
				// See hasMetaboliteData: gated on the resolved compounds these
				// panels draw, not on the candidate list that step 2 consumes.
				// The hub grid was replaced by the network panel below: a
				// nine-column table of one row per (metabolite, radius) that
				// needed its own step filter to be readable, describing a
				// network the browser could not draw. PA_Step3HubAnalysis is
				// left in the file for the moment but is no longer mounted.
				(!this.hasMetaboliteData()?null:me.hubNetworkView.getComponent()),
				(!this.metaboliteView?null:me.metaboliteView.getComponent()),
				// MORE Regulation panel — independent of metabolomics presence.
				// The view returns a hidden container when no rpc data; safe to
				// always include here.
				me.regulationView.getComponent(),
				// MORE Regulator–Target Network — also self-suppresses; mounted
				// directly under the table for thematic grouping.
				me.regTargetNetworkView.getComponent(),
				me.pathwayTableView.getComponent() //THE TABLE PANEL
			],
			listeners: {
				boxready: function() {
					//SOME EVENT HANDLERS
//					$(".backButton").click(function() {
//						me.backButtonHandler();
//					});
					$(".mappingButton").click(function() {
						var cmp = Ext.getCmp('statsViewContainer');
						cmp.getEl().toggle();

						var buttonHTML = $(this).html();

						$(this).html(buttonHTML.includes('Hide') ? buttonHTML.replace(/Hide/g, 'Show') : buttonHTML.replace(/Show/g, 'Hide'));

						$('#mainViewCenterPanel').scrollTop(cmp.getEl().dom.offsetTop - 60);
					}).trigger('click');

					$("#resetButton").click(function() {
						me.resetViewHandler();
					});
					$("#sharingButton").click(function() {
						me.shareHandler();
					});

					/* The old "Choose the pathways below and Paint!" anchor had
					   no handler at all - an instruction dressed as a control.
					   The button goes where the instruction pointed: the
					   enrichment table, via the contents rail's own jump so the
					   scroll animates inside the ExtJS scroller (a smooth
					   scrollTo on that element is silently swallowed - see
					   paTocJumpTo in Util.js). */
					$("#paint_link").click(function() {
						if (typeof paTocJumpTo === "function") {
							paTocJumpTo("Pathway enrichment");
						} else {
							var section = document.getElementById("pathwayEnrichmentSection");
							if (section && section.scrollIntoView) {
								section.scrollIntoView({block: "start"});
							}
						}
					});

					/* Copy the shareable URL. The glyph is the feedback: a tick
					   for a moment, then back - no dialog, because a modal here
					   would block every later browser command in automated runs
					   and interrupt a human for a success they can see. */
					$("#copyJobURL").click(function() {
						var link = $(this);
						var url = window.location.href;
						var showCopied = function() {
							link.addClass("is-copied").find("i").attr("class", "fa fa-check");
							window.setTimeout(function() {
								link.removeClass("is-copied").find("i").attr("class", "fa fa-clipboard");
							}, 1500);
						};
						/* execCommand path for the http:// deploys where the
						   async clipboard API is withheld from the page. */
						var fallbackCopy = function() {
							var scratch = document.createElement("textarea");
							scratch.value = url;
							scratch.setAttribute("readonly", "");
							scratch.style.position = "absolute";
							scratch.style.left = "-9999px";
							document.body.appendChild(scratch);
							scratch.select();
							try {
								if (document.execCommand("copy")) { showCopied(); }
							} catch (e) { /* the open-link button remains */ }
							document.body.removeChild(scratch);
						};
						if (navigator.clipboard && navigator.clipboard.writeText) {
							navigator.clipboard.writeText(url).then(showCopied, fallbackCopy);
						} else {
							fallbackCopy();
						}
					});

					// AI widget lifecycle managed by refreshAIWidget() via updateObserver()
					$("#aiInterpretButton").click(function() {
						me.toggleAIWidget();
					});

					// Show a warning if it is read only
					if (! me.canEdit()) {
						$('#warningMessage').text("The current job is read-only, changes will not be saved in the server.").show();
					}
					//INITIALIZE THE COUNTERS IN SUMMARY PANEL
					new Odometer({el: $("#foundPathwaysTag")[0],value: 0});
					new Odometer({el: $("#significantPathwaysTag")[0],value: 0});
					// SUMMARY PANEL PER DATABASE
					if (me.getModel().getDatabases().length > 1) {
						var DB_COLORS = ["#007AFF",  "#4CD964", "#FF2D55", "#FFCD02", "#5AC8FB", "#C644FC"];
						// The two count cells must stay the sole content of their id'd
						// element -- the pathway filters refresh them with .html(number)
						// (see the $("#foundPathwaysTag_" + dbname) calls above), so any
						// wrapper markup placed inside them would be wiped on first filter.
						var table_html =
							'<table>' +
							/* The badge column gets its own empty header rather than
							   being swallowed by a colspan on "Database". The colspan
							   broke this header row in two ways at once: "Database"
							   started at the badge's edge, 50px left of the names it
							   labels, and - because it counted as one cell - "Found"
							   and "Significant" landed on nth-child 2 and 3, so the
							   `th:nth-child(n+3)` rule that right-aligns the count
							   columns missed them and both headers sat left-aligned
							   over right-aligned numbers. */
							'<thead><tr>' +
								'<th class="db_chip"></th>' +
								'<th>Database</th>' +
								'<th>Found</th>' +
								'<th>Significant</th>' +
							'</tr></thead><tbody>';

						for (var i = 0; i < me.getModel().getDatabases().length; i++) {
							var database = me.getModel().getDatabases()[i];
							var db_color = (i < DB_COLORS.length) ? DB_COLORS[i] : "#000000";

							table_html +=
							'<tr>' +
								// Both sides improved this row: master named the cells so the
								// stylesheet can address them, and the branch moved the badge colours
								// into classificationBadgeStyle, which fills the chip and picks ink
								// that contrasts with the fill rather than outlining it. Keep both.
								'<td class="db_chip"><i class="classificationNameBox" id="icon_' + database + '" style="' + classificationBadgeStyle(db_color) + '">' + database.charAt(0) + '</i></td>' +
								'<td class="db_name">' + database + '</td>' +
								'<td id="foundPathwaysTag_' + database + '">0</td><td class="db_significant" id="significantPathwaysTag_' + database + '">0</td>' +
							'</tr>';
						}

						table_html += "</tbody></table>"

						$("#multisource_summary").html(table_html);
					}

					// Built last, and on a delay, because it reads the headings
					// that are actually on the page: the classification, network
					// and enrichment sections are rendered by their own views
					// after this handler runs, so scanning immediately would find
					// only the first two and silently produce a short list.
					$.wait(function () { buildAnalysisTOC('#mainViewCenterPanel'); }, 1.2);
				},
				beforedestroy: function() {
					me.cleanupAIWidget();
					me.getModel().deleteObserver(me);
				}
			}
		});

		return this.component;
	};

	return this;
}
PA_Step3JobView.prototype = new View();

function PA_Step3PathwayClassificationView(db = "KEGG") {
	/**
	* About this view: this view (PA_Step3PathwayClassificationView) is used to visualize
	* a summary for the classifications for the matched pathways.
	* The view shows different information for the Job instance, in particular:
	*  - A pie chart with an overview of the distribution of the classifications
	*  - A tree view containing each classification, the corresponding subclassifications
	*    and pathways. This panel allows to show/hide elements in the view (pathways)
	**/
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step3PathwayClassificationView";
	this.database = db;
	this.dbid = this.database.replace(' ', '__');
	this.highcharts = null;
	this.OTHER_COLORS = ["#FF9500", "#E0F8D8", "#55EFCB", "#FFD3E0"];

	/*********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* This function updates the visual representation of the model.
	*  - STEP 1. INITIALIZE VARIABLES
	*  - STEP 2. GENERATE THE PIE CHART FOR THE CLASSIFICATIONS
	*  - STEP 3. GENERATE THE CLASSIFICATION SELECTOR PANEL
	* @chainable
	* @returns {PA_Step3PathwayClassificationView}
	*/
	this.updateObserver = function() {
		/********************************************************/
		/* STEP 1. INITIALIZE VARIABLES                         */
		/********************************************************/
		var me = this;
		var OTHER_COLORS = $.extend(true, [], me.OTHER_COLORS);
		var classificationData = this.getParent().getClassificationData(this.database);
		var indexedPathways = this.getParent().getIndexedPathways(this.database);
		var pathways = this.getModel().getPathwaysByDB(this.database);

		/**********************************************************/
		/* STEP 2. GENERATE THE PIE CHART FOR THE CLASSIFICATIONS */
		/**********************************************************/
		var mainClassifications = [], secondClassifications = [], mainClassificationInstance, secClassificationInstance, drilldownAux;
		var classificationID, secondClassificationID;

		// var totalPathways = 0;
		// for(var i in pathways){
		// 	if(pathways[i].visible){totalPathways++;}
		// }

		for (classificationID in classificationData){
			mainClassificationInstance = classificationData[classificationID];

			mainClassifications.push({
				name: mainClassificationInstance.name,
				y: (mainClassificationInstance.count/pathways.length) * 100,
				color: this.getParent().getClassificationColor(classificationID, OTHER_COLORS),
				drilldown: classificationID
			});

			drilldownAux = {
				name: mainClassificationInstance.name,
				id: classificationID,
				data: []
			};

			for (secondClassificationID in mainClassificationInstance.children){
				secClassificationInstance = mainClassificationInstance.children[secondClassificationID];
				drilldownAux.data.push([secClassificationInstance.name, (secClassificationInstance.count/pathways.length) * 100]);
			}
			secondClassifications.push(drilldownAux);
		}

		me.highcharts = Highcharts.chart('pathwayDistributionsContainer_' + me.dbid, {
			chart: {type: 'pie'},
			title: null, credits: {enabled: false},
			plotOptions: {
				series: {
					animation: false,
					dataLabels: {
						enabled: true,  useHTML:true,
						formatter: function(){
							if(this.point.drilldown !== undefined){
								return '<i class="classificationNameBox" style="line-height: 20px;' + classificationBadgeStyle(this.point.color) + '">' + this.point.name.charAt(0).toUpperCase() + '</i>' + this.y.toFixed(2) + "%";
							}else{
								return "<b>" + this.point.name + "</b><br>" + this.y.toFixed(2) + "%";
							}
						}
					}
				}
			},
			tooltip: {
				headerFormat: '<span style="font-size:11px">{series.name}</span><br>',
				pointFormat: '<span style="color:{point.color}">{point.name}</span>: <b>{point.y:.2f}%</b> of total<br/>'
			},
			series: [{
				name: "Pathways Classification",
				colorByPoint: true,
				data: mainClassifications
			}],
			drilldown: {
				series: secondClassifications
			}
		});

		/**********************************************************/
		/* STEP 3. GENERATE THE CLASSIFICATION SELECTOR PANEL     */
		/**********************************************************/
		/* STEP 3.1 INITIALIZE VARIABLES                          */
		/**********************************************************/
		OTHER_COLORS = ["#FF9500", "#E0F8D8", "#55EFCB", "#FFD3E0"];
		var htmlContent = "", mainClassificationHTMLcode, secClassificationHTMLcode,
		pathClassificationHTMLcode, color, pathwayID, temporalCodeTable, namesAux, posAux,
		isCustomMainClass, isHiddenMainClass, isCustomSecClass, isHiddenSecClass;

		var mainClassificationIDs = Object.keys(classificationData).sort();
		/***********************************************************/
		/* STEP 3.2 GENERATE THE HTML CODE FOR MAIN CLASSIFICATIONS*/
		/***********************************************************/
		while (mainClassificationIDs.length > 0){
			classificationID = mainClassificationIDs.shift();
			mainClassificationInstance = classificationData[classificationID];

			color = this.getParent().getClassificationColor(classificationID, OTHER_COLORS);
			secClassificationHTMLcode = ""; //HTML code for children (pathways and secondary classifications)
			isCustomMainClass = false; //Determine if visibility for main classification should be Show/Custom/Hide
			isHiddenMainClass = true; //Determine if visibility for main classification should be Show/Custom/Hide

			var secClassificationIDs = Object.keys(mainClassificationInstance.children).sort();
			/******************************************************************/
			/* STEP 3.2.1 GENERATE THE HTML CODE FOR SECONDARY CLASSIFICATIONS*/
			/******************************************************************/
			while (secClassificationIDs.length > 0){
				secondClassificationID  = secClassificationIDs.shift();
				//Initialize variables
				secClassificationInstance = mainClassificationInstance.children[secondClassificationID];
				pathClassificationHTMLcode = "";
				isCustomSecClass = false;
				isHiddenSecClass = true;

				/********************************************************************/
				/* STEP 3.2.1.1 GENERATE THE HTML CODE FOR PATHWAYS                 */
				/********************************************************************/
				temporalCodeTable = [];
				namesAux = [];
				for (var i in secClassificationInstance.children){
					pathwayID = secClassificationInstance.children[i];
					posAux = Array.binaryInsert(indexedPathways[pathwayID].getName(), namesAux);
					temporalCodeTable.splice(posAux, 0,
						'<div class="checkbox step3ClassificationsPathway">'+
						'  <input type="checkbox" '+ (indexedPathways[pathwayID].isVisible()?"checked":"")+' id="' + pathwayID +'">'+
						'  <label for="' + pathwayID +'">'+ indexedPathways[pathwayID].getName() +'</label>'+
						'</div>');
						isCustomSecClass = isCustomSecClass || !indexedPathways[pathwayID].isVisible();
						isHiddenSecClass = isHiddenSecClass && !indexedPathways[pathwayID].isVisible();
					}
					pathClassificationHTMLcode += temporalCodeTable.join("\n");

					/********************************************************************/
					/* STEP 3.2.1.2 GENERATE THE CODE FOR CURRENT SUBCATEGORY           */
					/********************************************************************/
					secClassificationHTMLcode +='<div class="step3ClassificationsWrapper'+ (isHiddenSecClass?" disabled":"") +'">' +
					'  <div class="step3ClassificationsTitle'+ (isHiddenSecClass?" disabled":"") +'">'+
					'   <i class="fa fa-caret-right" style="color: #B1B1B1; margin-right: 5px;"></i>' +  secClassificationInstance.name +
					'   <div class="step3ClassificationsOptions">'+
					'     <a class="hideOption'+ (isHiddenSecClass?" selected":"") +'">Hide</a>'+
					'     <a class="showOption'+ (!(isHiddenSecClass || isCustomSecClass)?" selected":"") +'">Show</a>'+
					'     <a class="customOption'+ (isCustomSecClass && !isHiddenSecClass?" selected":"") +'">Custom</a>'+
					'   </div>'+
					'  </div>' +
					'  <div class="step3ClassificationsChildrenContainer">'+ pathClassificationHTMLcode + '</div>'+
					'</div>';

					/********************************************************************/
					/* STEP 3.2.1.3 CHECK THE VISIBILITY FOR THE SUBCLASSIFICATION         */
					/********************************************************************/
					isCustomMainClass = isCustomMainClass || isCustomSecClass;
					isHiddenMainClass = isHiddenMainClass && isHiddenSecClass;
				}

				/********************************************************************/
				/* STEP 3.2.2 GENERATE THE CODE FOR CURRENT SUBCATEGORY             */
				/********************************************************************/
				htmlContent +='<div class="step3ClassificationsWrapper'+ (isHiddenMainClass?" disabled":"") +'">' +
				'  <div class="step3ClassificationsTitle'+ (isHiddenMainClass?" disabled":"") +'">'+
				'   <i class="classificationNameBox" style="' + classificationBadgeStyle(color) + '">' + mainClassificationInstance.name.charAt(0).toUpperCase() + '</i>' +
				'   <i class="fa fa-caret-right" style="color: #B1B1B1; margin-right: 5px;"></i>' + mainClassificationInstance.name +
				'   <div class="step3ClassificationsOptions">'+
				'     <a class="hideOption'+ (isHiddenMainClass?" selected":"") +'">Hide</a>'+
				'     <a class="showOption'+ (!(isCustomMainClass || isHiddenMainClass)?" selected":"") +'">Show</a>'+
				'     <a class="customOption'+ (isCustomMainClass && !isHiddenMainClass?" selected":"") +'">Custom</a>'+
				'   </div>'+
				'  </div>' +
				'  <div class="step3ClassificationsChildrenContainer" style="padding-left: 25px;">'+ secClassificationHTMLcode + '</div>'+
				'</div>';
			}

		/********************************************************************/
		/* STEP 3.3 UPDATE THE CONTENT FOR THE DOM                          */
		/********************************************************************/
		$("#pathwayClassificationContainer_" + me.dbid).html(htmlContent);

		/********************************************************************/
		/* STEP 3.4 SET THE BEHAVIOUR WHEN CLIKING THE NODES OF THE TREE    */
		/********************************************************************/
		var updateStatus = function(elem){
			$(elem).parents(".step3ClassificationsWrapper").last().find(".step3ClassificationsWrapper").andSelf().each(function(){
				var totalPathways = $(this).find("input").size();
				var totalCheckedPathways = $(this).find("input:checked").size();
				var className = "";
				if(totalCheckedPathways === 0){
					$(this).children(".step3ClassificationsTitle").addClass("disabled");
					className = ".hideOption";
				}else if(totalCheckedPathways === totalPathways){
					$(this).children(".step3ClassificationsTitle").removeClass("disabled");
					className = ".showOption";
				}else{
					$(this).children(".step3ClassificationsTitle").removeClass("disabled");
					className = ".customOption";
				}

				//* SET TO "CUSTOM" ALL INMEDIATE CHILDREN OPTIONS
				$(this).children(".step3ClassificationsTitle").find("a").removeClass("selected");
				$(this).children(".step3ClassificationsTitle").find("a" + className).addClass("selected");
			});
		};

		$("#pathwayClassificationContainer_" + me.dbid + " .step3ClassificationsTitle").click(function(event){
			if(event.target.nodeName === "A"){
				//IGNORE IF CLIKING ON CURRENT OPTION
				if($(event.target).hasClass("selected")){
					return;
				}

				if(event.target.text === "Show"){
					$(this).next(".step3ClassificationsChildrenContainer").find("input").prop("checked",true);
				}else if(event.target.text === "Hide"){
					$(this).next(".step3ClassificationsChildrenContainer").find("input").removeAttr("checked");
				}

				updateStatus(this);
			}else{
				//EXPAND/COLLAPSE
				$(this).next(".step3ClassificationsChildrenContainer").slideToggle();
				$(this).find("i.fa").each(function(){
					if($(this).hasClass("fa-caret-right")){
						$(this).removeClass("fa-caret-right").addClass("fa-caret-down");
					}else{
						$(this).removeClass("fa-caret-down").addClass("fa-caret-right");
					}
				});
			}
		});

		$("#pathwayClassificationContainer_" + me.dbid + " .step3ClassificationsPathway > input").change(function(){
			updateStatus(this);
		});

		this.applyVisualSettings(false);

		return this;
		};

		/**
		* This function apply the settings that user can change
		* for the visual representation of the model (w/o reload everything).
		* - STEP 1. UPDATE THE pathways Visibility
		* - STEP 2. NOTIFY THE CHANGES TO PARENT
		* @chainable
		* @returns {PA_Step3PathwayClassificationView}
		*/
	this.applyVisualSettings =  function(updateSettings=true) {
		var me = this;

		/********************************************************/
		/* STEP 1. UPDATE THE pathways Visibility               */
		/*         (indexedPathways TABLE)                      */
		/********************************************************/
		var pathwaysVisibility = [];
		var indexedPathways = me.getParent().getIndexedPathways(this.database);
		$("#pathwayClassificationContainer_" + me.dbid).find("input").each(function(){
			indexedPathways[this.id].setVisible($(this).is(":checked"));
			if(indexedPathways[this.id].isVisible()){
				pathwaysVisibility.push(this.id);
			}
		});

		var classificationData = me.getParent().getClassificationData(me.database);
		var mainClassificationID, secClassificationID;
		var mainClassifications = [], secondClassifications = [];

		// Avoid this when no pathways are visible.
		if (pathwaysVisibility.length) {
			Object.keys(classificationData).forEach(function(classificationID) {
				var mainClassificationInstance = classificationData[classificationID];
				var mainVisiblePathways = 0;

				drilldownAux = {
					name: mainClassificationInstance.name,
					id: classificationID,
					data: []
				};

				for (secondClassificationID in mainClassificationInstance.children){
					var secClassificationInstance = mainClassificationInstance.children[secondClassificationID];
					var secVisiblePathways = secClassificationInstance.children.filter(x => pathwaysVisibility.includes(x));

					// Check if there are visible pathways in this classification
					if (secVisiblePathways.length) {
						mainVisiblePathways += secVisiblePathways.length;
						drilldownAux.data.push([secClassificationInstance.name, (secVisiblePathways.length/pathwaysVisibility.length) * 100]);
					}
				}

				if (mainVisiblePathways) {
					secondClassifications.push(drilldownAux);

					mainClassifications.push({
						name: mainClassificationInstance.name,
						y: (mainVisiblePathways/pathwaysVisibility.length) * 100,
						color: me.getParent().getClassificationColor(classificationID, me.OTHER_COLORS),
						drilldown: classificationID
					});
				}
			});

			me.highcharts.series[0].setData(mainClassifications);
			me.highcharts.options.drilldown.series[0] = secondClassifications;
		} else {
			me.highcharts.series[0].setData([{
					name: 'No pathways',
					y: 100,
					color: "#FF0000"
			}]);
		}

		if (updateSettings) {
			me.getParent().setVisualOptions("pathwaysVisibility", pathwaysVisibility, me.database);

			/********************************************************/
			/* STEP 2. NOTIFY THE CHANGES TO PARENT                 */
			/********************************************************/
			me.getParent().applyVisualSettings(me.getName(), me.database);
		}

		return this;
	};

		/**
		* This function generates the component (EXTJS) using the content of the model
		* @returns {Ext.ComponentView} The visual component
		*/
	this.initComponent = function() {
		var me = this;

		this.component = Ext.widget({
			/* No `contentbox` any more: this view and the network below it share
			   one card, which the job view wraps around both. This is the half
			   that carries the card's own <h2>. */
			xtype: 'box', cls: "paExploreSection paExploreOverview",
			maxWidth: 1900, html:
			'<h2>Pathway explorer (' + me.database + ' database)<span class="helpTip" title="Choose which pathways to keep by category, then explore how the ones that remain relate to each other. Every control on this card acts on the same set of pathways, and on the table at the foot of the page."></span></h2>' +
			/* The classification block is foldable because it is the half of the
			   card you set once. Folded, the network gets the whole card; the
			   button says which state it is in rather than which state it will
			   move to, so the row reads as a label with a control on it. */
			'<div class="paExploreBand">' +
			'  <h3>Pathway categories</h3>' +
			'  <a href="javascript:void(0)" class="paExploreFold" id="foldClassificationButton_' + me.dbid + '"><i class="fa fa-chevron-up"></i> Hide</a>' +
			'</div>' +
			'<div class="paExploreFoldable" id="classificationBody_' + me.dbid + '">' +
			/* The card's own inset, not 10px: "Category Distribution" is the
			   first thing under the card's heading and started 16px left of
			   it. */
			'<div id="pathwayClassificationPlot1Box_' + me.dbid + '" style="padding-left: var(--pa-card-inset);overflow:hidden;  min-height:300px; width: 45%; float: left;">'+
			'  <h4>Category Distribution<span class="infoTip">Click on each slice to view the distribution of the subcategories.</span></h4> '+
			'  <div id="pathwayDistributionsContainer_' + me.dbid + '" style="height: 240px;"></div>'+
			'</div>' +
			/* The card's own inset on the right, like the column beside it takes on
			   the left. 30px was 4px past it, which is what put the Apply button
			   below on a right edge of its own. */
			'<div id="pathwayClassificationPlot2Box_' + me.dbid + '" style="overflow:hidden;  min-height:300px; width: 55%; display:inline-block; padding: 0px var(--pa-card-inset)">'+
			'  <h4>Filter by category<span class="infoTip">Use this tool to <b>Show or Hide Pathways</b> based on their classification</span></h4> '+
			'  <div id="pathwayClassificationContainer_' + me.dbid + '"></div>'+
			/* No right margin. The 50px here stopped the only action in this card
			   54px short of the rail its own heading, its "Filter by category"
			   label and every classification row are squared to - measured at
			   x=1369 against a card rail of 1423 - and 50px is not a spacing
			   anything else on the page uses, so it read as the button having
			   come loose rather than as an inset. */
			'  <a href="javascript:void(0)" class="button btn-success btn-right helpTip" id="applyClassificationSettingsButton_' + me.dbid + '" style="margin: 0px 0px 17px 0px;" title="Apply changes"><i class="fa fa-check"></i> Apply</a>' +
			'</div>' +
			'</div>',
			listeners: {
				boxready: function() {
					$("#applyClassificationSettingsButton_" + me.dbid).click(function() {
						me.applyVisualSettings();
					});

					$("#foldClassificationButton_" + me.dbid).click(function() {
						var button = $(this);
						var body = $("#classificationBody_" + me.dbid);
						var folding = body.is(":visible");

						body.slideToggle(200, function() {
							/* Highcharts sizes itself against a container it can
							   measure, and a container inside a hidden parent
							   measures zero. Unfolding without this leaves the pie
							   drawn at whatever width it had when it was last
							   visible, which is the wrong one if the window has
							   been resized in between. */
							if (!folding && me.highcharts) {
								me.highcharts.reflow();
							}
						});

						button.html(folding
							? '<i class="fa fa-chevron-down"></i> Show'
							: '<i class="fa fa-chevron-up"></i> Hide');
					});

					initializeTooltips(".helpTip");
				}
			}
		});
		return this.component;
	};
	return this;
}
PA_Step3PathwayClassificationView.prototype = new View();

/**
* The ink sigma paints node labels with. Sigma renders to canvas, so dark.css
* cannot reach the labels the way it reaches the rest of the page: the colour
* has to be resolved here and handed over as a settings value. --pa-chart-ink
* is defined only under [data-theme="dark"], so in the light theme the lookup
* comes back empty and the historical black stands.
*
* @returns {String}
*/
function paNetworkLabelInk() {
	var ink = window.getComputedStyle(document.documentElement).getPropertyValue("--pa-chart-ink").trim();
	return (ink !== "") ? ink : "#000";
}

function PA_Step3PathwayNetworkView(db = "KEGG") {
	/**
	* About this view: this view (PA_Step3PathwayNetworkView) is used to visualize
	* a network where nodes represents pathways and edges relationships between them.
	* This view also contains:
	*  - A tooltip showing some information for pathways when hovering the nodes (PA_Step3PathwayNetworkTooltipView)
	*  - A detailed view for each pathway in the network (PA_Step3PathwayDetailsView)
	**/
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step3PathwayNetworkView";
	this.network = null;
	this.themeObserver = null;
	this.tooltips = null;
	this.filters = null;
	this.select = null;
	this.multinodeSelector = null;
	this.pathwayDetailsView = null;
	this.database = db;
	this.dbid = this.database.replace(' ', '__');
	this.showTooltips = true;

	/*********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/

	/**
	* This function generates the network using the values from visualOptions
	*  - STEP 0. CLEAN PREVIOUS NETWORK
	*  - STEP 1. GENERATE NODES
	*  - STEP 2. GENERATE EDGES
	*  - STEP 3. GENERATE THE NETWORK
	*  - STEP 4. GENERATE THE GLYPS
	*  - STEP 5. START PLUGINS
	*  - STEP 6. INITIALIZE THE TOOLTIPS
	*  - STEP 7. GENERATE THE CLUSTERS DETAILS PANEL
	*  - STEP 8. CONFIGURE THE LAYOUT (ForceAtlas2 algorithm)
	*  - STEP 9. WAIT 2 SECONDS AND START THE LAYOUT
	* @chainable
	* @param {Object} data, an object containing the Network stucture
	* @returns {PA_Step3PathwayNetworkView}
	*/
	this.generateNetwork = function(data, forceStop=false) {
		var me = this;
		var visualOptions = this.getParent().getVisualOptions(this.database);
		// A colouring saved from an earlier visit may name the AI clusters
		// before this visit's report has loaded (or for a job with no cluster
		// report at all); without a partition every node would draw grey with
		// an empty legend, so fall back to the classification colouring.
		if (visualOptions.colorBy === "aiclusters" && !this.getParent().aiClusters) {
			visualOptions.colorBy = "classification";
		}
		var indexedPathways = this.getParent().getIndexedPathways(this.database);
		var CLUSTERS = {};
		var TOTAL_CLUSTERS = this.getModel().getClusterNumber()[this.database];

		/* The old format data does not have keys */
		if (me.database in data) {
			data = data[me.database];
		}

		/********************************************************/
		/* STEP 0. CLEAN PREVIOUS NETWORK                       */
		/********************************************************/
		$("#pathwayNetworkWaitBox_" + me.dbid).fadeIn();

		//FORCE STOPPING OF PLUGIN ALWAYS
		sigma.layouts.killForceLink();

		//CLEAN PREVIOUS NETWORK
		if (this.network !== null) {
			sigma.plugins.killFilter(this.network);
			this.filters = null;
			this.network.kill();
			this.network = null;
		}

		/********************************************************/
		/* STEP 1. GENERATE NODES                               */
		/********************************************************/
		var elem, nodesAux = [], edgesAux = [], matchedPathway=null, ignoredPathways = {};
		var nElems = data.nodes.length;
		for (var i = nElems; i--;) {
			elem = data.nodes[i];
			matchedPathway = indexedPathways[elem.data.id];

			/********************************************************/
			/* STEP 1.A.1 EXCLUDE NODE IF:                           */
			/*  - If elem is not a NODE                             */
			/*  - If node is a classification or is not a pathway   */
			/*  - Is a special case (e.g. mmu01100)                 */
			/*  - If is not visible                                 */
			/********************************************************/
			if ((elem.group !== "nodes") ||
			(elem.data.is_classification !== undefined) ||
			(matchedPathway === undefined) ||
			(elem.data.id === this.getModel().getOrganism() + "01100") ||
			(!matchedPathway.isVisible())){
				ignoredPathways[elem.data.id] = true;
				continue;
			}
			/********************************************************/
			/* STEP 1.A.2 EXCLUDE NODE IF:                           */
			/*  - If number of total features * n% is bigger than   */
			/*    the sum of matched features in the pathway.		*/
			/*  - If the pValue of the pathways is greater than 	*/
			/*	  the maximum allowed.								*/
			/********************************************************/
			var pValue = 1;
			try{
				var selectedCombinedPvalueMethod = me.getParent().visualOptions.selectedCombinedMethod;
				var selectedAdjustingMethod = visualOptions.networkPvalMethod;
				var useCombinedPvalue = visualOptions.useCombinedPvalCheckbox;
				var methodSelected =  (visualOptions.colorBy === "classification" || visualOptions.colorBy === "aiclusters" || useCombinedPvalue) ? selectedCombinedPvalueMethod : visualOptions.colorBy;

				/*
					The adjusted p-values are different in the job has been category filtered (number of tests decreases).
					These new "filtered adjusted p-values" are kept on a layer inside visualOptions.
				*/
				if (selectedAdjustingMethod != 'none') {
					var useLayer = visualOptions.adjustedPvalues && visualOptions.adjustedPvalues[methodSelected];

					if (useLayer) {
						pValue = visualOptions.adjustedPvalues[methodSelected][selectedAdjustingMethod];
					} else {
						pValue = matchedPathway.getAllAdjustedSignificanceValues()[methodSelected][selectedAdjustingMethod];
					}
				} else {
					pValue = matchedPathway.getAllSignificanceValues()[methodSelected];
				}

				// If pValue is an array (multi-condition), use the minimum (most significant value) or the first element
				if (Array.isArray(pValue)) {
					// Paintomics 4: if we have global p-values for this omic/method, they are usually at index 0 or as a single value.
					// But we take the minimum to ensure if it is significant in ANY condition, it is shown.
					// pValue = Math.min(...pValue.filter(v => !isNaN(v) && v !== null));
					// Actually, consistent with other views, we try to use the most representative value.
					pValue = Math.min.apply(null, pValue.filter(v => !isNaN(v) && v !== null && v !== "-"));
				}
			} catch(error) {
				//pass
				pValue = 1;
			}

			matchedPathway.setTotalFeatures(matchedPathway.getMatchedGenes().length + matchedPathway.getMatchedCompounds().length);
			if (elem.data.total_features * visualOptions.minFeatures > matchedPathway.getTotalFeatures() || pValue > visualOptions.minPValue){
				ignoredPathways[elem.data.id] = true;
				continue;
			}
			/********************************************************/
			/* STEP 1.B GENERATE NODE                               */
			/********************************************************/
			else {
				// elem.data = {
				//	x, y,  --> The node coordinates
				//  size,  --> Size of the node (depends on p-value)
				//  colors,--> List of colors for the node
				//  parent,--> The classification for the node
				//  clusters, --> The cluster numbers
				//  glyphs --> info for the glyphs (complements the node with classification info)
				//}

				/********************************************************/
				/* STEP 1.B.1 SET NODE POSITION                         */
				/********************************************************/
				if(matchedPathway.networkCoordX !== undefined && matchedPathway.networkCoordY !== undefined){
					elem.data.x = matchedPathway.networkCoordX; //RING LAYOUT
					elem.data.y = matchedPathway.networkCoordY;
				}

				/********************************************************/
				/* STEP 1.B.2 SET NODE SIZE BASED ON PATHWAY RELEVANCE  */
				/********************************************************/
				//elem.data.size = (pValue <= visualOptions.minPValue)? 20 + 2 * (visualOptions.minPValue - pValue):12;
				elem.data.size = 20 + 2 * (visualOptions.minPValue - pValue);

				/********************************************************/
				/* STEP 1.B.3 COLOR THE NODE BASED ON VISUAL OPTIONS    */
				/********************************************************/
				elem.data.colors =  [];
				elem.data.clusters =  [];
				if(visualOptions.colorBy === "classification"){ //Color by classification
					elem.data.colors.push(this.getParent().getClassificationColor(elem.data.parent[0]));
				}else if(visualOptions.colorBy === "aiclusters"){ //Color by the AI report's shared-feature clusters
					var aiCluster = me.getAIClusterOf(elem.data.id);
					if(aiCluster){
						CLUSTERS[aiCluster.id] = me.getAIClusterColor(aiCluster.id);
						elem.data.colors.push(CLUSTERS[aiCluster.id]);
						elem.data.clusters.push(aiCluster.id);
					}else{
						elem.data.colors.push("#dfdfdf"); // standalone / further: not in any cluster
					}
				}else{ //Color by metagenes clusters
					var metagenes = matchedPathway.metagenes[visualOptions.colorBy];
					if(metagenes){
						for(var n in metagenes){
							CLUSTERS[metagenes[n].cluster] = this.getClusterColor(metagenes[n].cluster);
							elem.data.colors.push(this.getClusterColor(metagenes[n].cluster));
							elem.data.clusters.push(metagenes[n].cluster);
						}
					}else{
						elem.data.colors.push("#dfdfdf");
					}
				}

				// Assign "color" attribute for svg renderer
				elem.data.color = elem.data.colors;

				/*********************************************************/
				/* STEP 1.B.4 ADD GLYP INDICATING THE MAIN CLASSIFICATION*/
				/*********************************************************/
				elem.data.glyphs = [{
					position: 'bottom-right',
					textColor: this.getParent().getClassificationColor(elem.data.parent[0]),
					strokeColor: this.getParent().getClassificationColor(elem.data.parent[0]),
					content: elem.data.parent[0].charAt(0).toUpperCase()
				}];

				//NOTE: Other settings are at network initialization

				/*********************************************************/
				/* STEP 1.B.4 ADD THE NODE                               */
				/*********************************************************/
				nodesAux.push(elem.data);
			}
		}
		/********************************************************/
		/* STEP 2. GENERATE EDGES                               */
		/********************************************************/
		nElems = data.edges.length;
		for (var i = nElems; i--;) {
			elem = data.edges[i];

			/********************************************************/
			/* STEP 2.A.1 EXCLUDE ELEM IF:                           */
			/*  - If elem is not an EDGE                            */
			/*  - If source/target were ignored previously          */
			/*  - If source/target are not valid pathways           */
			/*  - If source/target are not visible                  */
			/*  - Is source/target are special cases (e.g. mmu01100)*/
			/********************************************************/
			if ((elem.group !== "edges") || (elem.data.class !== visualOptions.edgesClass) ||
			(ignoredPathways[elem.data.source] || ignoredPathways[elem.data.target]) ||
			(indexedPathways[elem.data.source] === undefined || indexedPathways[elem.data.target] === undefined) ||
			(!indexedPathways[elem.data.source].isVisible() || !indexedPathways[elem.data.target].isVisible()) ||
			(elem.data.source === this.getModel().getOrganism() + "01100" || elem.data.target === this.getModel().getOrganism() + "01100")) {
				continue;
			}

			var similarity = 1;
			if(visualOptions.edgesClass === 's'){
				//CALCULATE THE Sorensen–Dice similarity coefficient (https://en.wikipedia.org/wiki/S%C3%B8rensen%E2%80%93Dice_coefficient)
				var totalIntersection =  Array.intersect(indexedPathways[elem.data.target].getMatchedGenes(),indexedPathways[elem.data.source].getMatchedGenes()).length;
				totalIntersection +=  Array.intersect(indexedPathways[elem.data.target].getMatchedCompounds(),indexedPathways[elem.data.source].getMatchedCompounds()).length;
				//S(A,B) = 2 * |AnB| / |A| + |B|
				//0 <= S(A,B) <= 1
				similarity = 2 * totalIntersection / ((indexedPathways[elem.data.target].getMatchedGenes().length + indexedPathways[elem.data.target].getMatchedCompounds().length) + (indexedPathways[elem.data.source].getMatchedGenes().length + indexedPathways[elem.data.source].getMatchedCompounds().length));
			}
			/********************************************************/
			/* STEP 2.A.2 EXCLUDE ELEM IF:                           */
			/*  - If number of total shared features * N % is bigger than   */
			/*    the sum of matched features in the pathway,       */
			/********************************************************/
			if (visualOptions.minSharedFeatures > similarity){
				continue;
			}
			/********************************************************/
			/* STEP 2.B GENERATE THE EDGE                               */
			/********************************************************/
			else {
				// elem.data.label = '' + similarity;
				elem.data.type = 'dotted';
				elem.data.size = similarity;
				edgesAux.push(elem.data);
			}
		}

		/********************************************************/
		/* STEP 2.C DESCRIBE WHAT WAS ACTUALLY DRAWN            */
		/********************************************************/
		me.updateNetworkSubtitle(nodesAux.length, edgesAux.length,
			Object.keys(indexedPathways).length, visualOptions);

		/********************************************************/
		/* STEP 3. GENERATE THE NETWORK                         */
		/********************************************************/
		me.network = new sigma({
			graph: {nodes: nodesAux, edges: edgesAux},
			renderers: [
				{container: $('#pathwayNetworkBox_' + me.dbid)[0], type: 'canvas' },
				//{container: $('#pathwayNetworkBoxSVG_' + me.dbid)[0], type: 'svg' }
			],
			//renderers: [{container: $('#pathwayNetworkBox')[0], type: 'svg' }],
			settings: {
				zoomMin: 0.01,
				zoomMax: 10,
				zoomingRatio:1.2,
				//nodes --------------------------------------------------------
				dragNodeStickiness: 0.01,
				labelThreshold: 10, //Show or hide labels, change using settings
				labelMaxLength : 15,
				//edges --------------------------------------------------------
				drawEdges: false, //show after layout
				batchEdgesDrawing: false,
				hideEdgesOnMove: true,
				defaultEdgeType: 'line',
				defaultEdgeColor: '#A9A9A9',
				edgeColor: 'default',
				//glyph --------------------------------------------------------
				drawGlyphs: false, //show after layout
				glyphScale : 0.4,
				glyphFillColor: '#fff',
				glyphFontStyle : "bold",
				glyphLineWidth: 4,
				glyphTextThreshold: 3,
				glyphThreshold: 2,
				//select --------------------------------------------------------
				borderSize: 2,
				outerBorderSize: 3,
				defaultNodeBorderColor: '#fff',
				defaultNodeOuterBorderColor: 'rgb(236, 81, 72)',
				//halo --------------------------------------------------------
				nodeHaloColor: '#ff8e8e',
				edgeHaloColor: '#ff8e8e',
				nodeHaloSize: 5,
				edgeHaloSize: 3,
				// min/maxNodeSize:
				minNodeSize: visualOptions.minNodeSize,
				maxNodeSize: visualOptions.maxNodeSize,
				defaultLabelSize: visualOptions.fontSize,
				defaultLabelColor: paNetworkLabelInk()
			}
		});

		/* The label ink is baked into canvas pixels at render time, so a theme
		   flip after this point would strand black labels on the dark ground
		   (or pale ones on white). One observer per view, registered on the
		   first render only: updateObserver re-runs on every Apply and kills
		   the old sigma instance, so the callback reads me.network at fire
		   time instead of closing over an instance that may be dead. */
		if (me.themeObserver === null && window.MutationObserver !== undefined) {
			me.themeObserver = new MutationObserver(function () {
				if (me.network !== null) {
					me.network.settings({defaultLabelColor: paNetworkLabelInk()});
					me.network.renderers[0].render();
				}
			});
			me.themeObserver.observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
		}

		/********************************************************/
		/* STEP 4. GENERATE THE GLYPS                           */
		/********************************************************/
		me.drawGlyphs = false; //ONLY RENDERED WHEN LAYOUT IS STOPPED
		me.network.renderers[0].bind('render', function(e) {
			if(me.drawGlyphs){
				me.network.renderers[0].glyphs({draw : me.drawGlyphs});
			}
		});

		/********************************************************/
		/* STEP 5. START PLUGINS                                */
		/********************************************************/
		var activeState = sigma.plugins.activeState(me.network);

		//select plugin
		this.select = sigma.plugins.select(me.network, activeState);
		this.select.selectAllNodes= function() {
			activeState.dropEdges();

			if (activeState.nodes().length === me.network.graph.nodes().length) {
				activeState.dropNodes();
			}
			else {
				activeState.addNodes();
			}
			me.network.refresh({skipIndexation: true});
		};
		this.select.selectAllNeighbors= function() {
			// Select neighbors of selected nodes
			activeState.addNeighbors();
			me.network.refresh({skipIndexation: true});
		};
		this.select.selectByCategory= function() {
			var nodes = activeState.nodes();
			var categories = [];
			for(var i in nodes){
				categories = categories.concat((me.getParent().getVisualOptions(this.database).colorBy === "classification")?nodes[i].parent:nodes[i].clusters);
			}
			// Remove duplicates:
			categories = Array.unique(categories);
			nodes = me.network.graph.nodes();
			var selection = [];
			for(var i in nodes){
				if(Array.intersect(categories, ((me.getParent().getVisualOptions(this.database).colorBy === "classification")?nodes[i].parent:nodes[i].clusters)).length > 0){
					selection.push(nodes[i].id);
				}
			}
			activeState.addNodes(selection);
			// Select neighbors of selected nodes
			me.network.refresh({skipIndexation: true});
		};

		//drag & drop plugin
		var dragListener = sigma.plugins.dragNodes(me.network, me.network.renderers[0], activeState);
		dragListener.bind('startdrag', function(event) {
			$('html,body').css('cursor','move');
		});
		dragListener.bind('dragend', function(event) {
			$('html,body').css('cursor','inherit');
		});
		//Filtering plugin
		this.filters = sigma.plugins.filter(me.network);

		//Multi-node selector plugin
		this.multinodeSelector = new sigma.plugins.lasso(me.network, me.network.renderers[0], {
			'strokeStyle': 'black',
			'lineWidth': 2,
			'fillWhileDrawing': true,
			'fillStyle': 'rgba(41, 41, 41, 0.2)',
			'cursor': 'crosshair'
		});
		this.select.bindLasso(this.multinodeSelector);
		this.multinodeSelector.deactivate();

		// Listen for selectedNodes event
		this.multinodeSelector.bind('selectedNodes', function (event) {
			setTimeout(function() {
				me.multinodeSelector.deactivate();
				me.network.refresh({ skipIdexation: true });
			}, 0);
		});

		//Show halo when hovering a node
		me.network.bind('hovers', function(e) {
			var adjacentNodes = [],
			adjacentEdges = [];

			if (!e.data.enter.nodes.length) return;

			// Get adjacent nodes:
			e.data.enter.nodes.forEach(function(node) {
				adjacentNodes = adjacentNodes.concat(me.network.graph.adjacentNodes(node.id));
			});

			// Add hovered nodes to the array and remove duplicates:
			adjacentNodes = Array.unique(adjacentNodes.concat(e.data.enter.nodes));

			// Get adjacent edges:
			e.data.enter.nodes.forEach(function(node) {
				adjacentEdges = adjacentEdges.concat(me.network.graph.adjacentEdges(node.id));
			});

			// Remove duplicates:
			adjacentEdges = Array.unique(adjacentEdges);

			// Render halo:
			me.network.renderers[0].halo({
				nodes: adjacentNodes,
				edges: adjacentEdges
			});
		});

		/********************************************************/
		/* STEP 6. INITIALIZE THE TOOLTIPS                      */
		/********************************************************/
		this.tooltips = new PA_Step3PathwayNetworkTooltipView().setParent(this);
		this.network.bind('hovers', function(e) {
			if(e.data.current.nodes.length > 0 && me.showTooltips){
				PA_Step3PathwayNetworkTooltipView().timeoutID = setTimeout(function(){
					PA_Step3PathwayNetworkTooltipView().show(e.data.captor.clientX, e.data.captor.clientY, me.getModel().getPathway(e.data.current.nodes[0].id), (visualOptions.colorBy === "aiclusters" ? [] : [visualOptions.colorBy]), me.getModel().getDataDistributionSummaries(), visualOptions);
				}, 600);
			}else{
				clearTimeout(PA_Step3PathwayNetworkTooltipView().timeoutID);
			}
		});
		$('#pathwayNetworkBox_' + me.dbid + ' canvas.sigma-mouse').mouseleave(function(){
			clearTimeout(PA_Step3PathwayNetworkTooltipView().timeoutID);
			PA_Step3PathwayNetworkTooltipView().hide();
		});

		/********************************************************/
		/* STEP 7. GENERATE THE CLUSTERS DETAILS PANEL          */
		/********************************************************/
		var htmlCode = "";
		$("#networkClustersContainer_" + me.dbid + " h4").text("Coloring by " + visualOptions.colorBy);
		$("#networkClustersContainer_" + me.dbid + " span.infoTip").toggle(visualOptions.colorBy !== "classification");
		$("#networkClustersContainer_" + me.dbid + " h5").toggle(visualOptions.colorBy !== "classification");

		if(visualOptions.colorBy === "classification"){
			var color, classification;
			for (var classificationID in me.getParent().classificationData[me.database]){
				classification = me.getParent().classificationData[me.database][classificationID];
				color = color = this.getParent().getClassificationColor(classificationID, []);
				htmlCode += '<div style="text-align:left;"><i class="classificationNameBox" style="' + classificationBadgeStyle(color) + '">' + classification.name.charAt(0).toUpperCase() + '</i>' +  classification.name + "</div>";
			}
			$("#networkClustersContainer_" + me.dbid + " div").html(htmlCode);
			$("#sliderClusterNumberContainer_" + me.dbid).hide();
		}else if(visualOptions.colorBy === "aiclusters"){
			// One legend entry per AI cluster with a node in this network:
			// colour, label, member count; grey = not in any cluster.
			var ai = me.getParent().aiClusters || {clusters: []};
			var drawnIds = Object.keys(CLUSTERS);
			$("#networkClustersContainer_" + me.dbid + " h4").text("Coloring by AI pathway clusters");
			$("#networkClustersContainer_" + me.dbid + " h5").text(drawnIds.length + " of " + ai.clusters.length + " clusters have nodes in this network. Grey nodes belong to no cluster.");
			$.each(ai.clusters, function(i, c){
				if(!CLUSTERS[c.id]){ return; }
				var members = (c.members || []).length + (c.satellites || []).length;
				htmlCode += '<span class="networkClusterImage networkAICluster" name="' + c.id + '" title="' + Ext.String.htmlEncode((c.core || []).slice(0, 8).join(", ")) + '">' +
					'<i class="fa fa-eye-slash fa-2x"></i>' +
					'<p><i class="fa fa-square" style="color:' + CLUSTERS[c.id] + '"></i> ' + c.id + ' &middot; ' + Ext.String.htmlEncode(c.label || "") + ' (' + members + ')</p></span>';
			});
			$("#networkClustersContainer_" + me.dbid + " div").html(htmlCode);
			$("#sliderClusterNumberContainer_" + me.dbid).hide();
			// Same click-to-hide behaviour as the metagene clusters.
			$("#networkClustersContainer_" + me.dbid + " .networkClusterImage").click(function(){
				var cluster = $(this).attr("name");
				if($(this).hasClass("disabled")){
					$(this).removeClass("disabled");
					me.filters.undo('cluster-filter-' + cluster).apply();
				}else{
					$(this).addClass("disabled");
					me.filters.nodesBy(function(node, params) {
						return node.clusters.indexOf(params.cluster) === -1;
					}, {cluster: cluster}, 'cluster-filter-' + cluster).apply();
				}
			});
		}else{
			var clusterNumber = Object.keys(CLUSTERS).length;
			var totalClusters = TOTAL_CLUSTERS[visualOptions.colorBy].size;

			$("#sliderClusterNumberShow_" + me.dbid).html(totalClusters);
			$("#sliderClusterNumber_" + me.dbid).slider("option", "value", totalClusters);

			$("#networkClustersContainer_" + me.dbid + " h5").text(clusterNumber + " Clusters found from " + totalClusters + " in total.");
			//Generate the images and the containers
			var img_path;
			var db_suffix = (me.dbid != "KEGG" ? "_" + me.dbid.toLowerCase(): '');

			for(var cluster in CLUSTERS){
				img_path = SERVER_URL_GET_CLUSTER_IMAGE + "/" + this.getModel().getJobID() + "/output/" + visualOptions.colorBy + "_cluster_" + cluster + db_suffix + ".png";
				htmlCode+= '<span class="networkClusterImage" name="'+ cluster + '"><i class="fa fa-eye-slash fa-2x"></i><img src="' + img_path +'"><p><i class="fa fa-square" style="color:' + CLUSTERS[cluster] +'"></i> Cluster ' + cluster + '</p></span>';
			}
			$("#networkClustersContainer_" + me.dbid + " div").html(htmlCode);

			// Update the cluster number slider value
			if (me.getParent().canEdit()) {
				$("#sliderClusterNumberContainer_" + me.dbid).show();
			} else {
				$("#sliderClusterNumberContainer_" + me.dbid).hide();
			}

			//Initialize the events when clicking a cluster images (filter)
			$("#networkClustersContainer_" + me.dbid + " .networkClusterImage").click(function(){
				var cluster = $(this).attr("name");
				if($(this).hasClass("disabled")){
					$(this).removeClass("disabled");
					me.filters.undo('cluster-filter-' + cluster).apply();
				}else{
					$(this).addClass("disabled");
					me.filters.nodesBy(function(node, params) {
						return node.clusters.indexOf(params.cluster) === -1;
					}, {cluster: cluster}, 'cluster-filter-' + cluster).apply();
				}
			});
		}

		/********************************************************/
		/* STEP 8. CONFIGURE THE LAYOUT (ForceAtlas2 algorithm) */
		/********************************************************/
		var afterStopEvent =  function(){
			/********************************************************/
			/* STEP 7.1 SET THE BEHAVIOUR WHEN STOPPING THE LAYOUT  */
			/********************************************************/
			//Change the button for Stop/Resume layout
			$('#resumeLayoutButton_' + me.dbid).addClass("resumeLayout");
			$('#resumeLayoutButton_' + me.dbid).html('<i class="fa fa-play"></i> Resume layout');

			//Draw glyps and edges
			me.drawGlyphs = true;
			me.network.renderers[0].glyphs({draw: me.drawGlyphs});
			me.network.settings({
				drawEdges:true,
				drawEdgeLabels:false,
				//edgeLabelThreshold: ((visualOptions.showEdgeLabels===true?0:8)),
				labelThreshold : ((visualOptions.showNodeLabels===true?1:8))
			});
			me.network.renderers[0].render();

			//Clear timeout, in case that layout stops automatically
			clearTimeout(me.timeoutID);
			me.timeoutID = null;

			$("#pathwayNetworkWaitBox_" + me.dbid).fadeOut();
		};

		var sigmaForceLink = sigma.layouts.configForceLink(me.network, {
			linLogMode: true,       //provides the most readable placement
			//edgeWeightInfluence: 1, //If the edges are weighted, this weight will be taken into consideration in the computation of the attraction force
			// scalingRatio: 3,        //the larger the graph will be
			gravity: 2,           // It attracts nodes to the center of the spatialization space
			// barnesHutOptimize: true, //NOT WORKING
			//Rendering options
			startingIterations: 1,
			iterationsPerRender: 2,
			//Stopping conditions
			maxIterations: 20000,
			avgDistanceThreshold: 0.05,
			autoStop:true,
			//Node sibling alignment
			alignNodeSiblings : true,
			nodeSiblingsAngleMin : 0.55,
			nodeSiblingsScale: 2,
			//Supervisor options
			worker: true,
			easing: 'cubicInOut',
			background:  (visualOptions.backgroundLayout === true), //Calculate in background
			randomize: 'globally'
		});

		sigmaForceLink.bind('stop', afterStopEvent);

		/********************************************************/
		/* STEP 9. WAIT 2 SECONDS AND START THE LAYOUT          */
		/********************************************************/
		if(visualOptions.pathwaysPositions !== undefined){
			// If the number of saved pathways is different from the new filtered, we first perform
			// the layout with forceAtlas, then save the positions saving the old ones and redraw.
			var savedPathways = visualOptions.pathwaysPositions.map(x => x.split('#')[0].trim());
			var allSaved = nodesAux.map(x => savedPathways.includes(x.id)).every(x => x);

			if (allSaved) {
				setTimeout(function() {
					afterStopEvent();
				}, 2000);
			} else {
				var addNewNodes = function() {
					// Save new node positions keeping the old saved ones
					me.updateNodePositions(false, true);

					// Make sure we don t enter in an infinite loop in
					// case some error occur.
					if (! forceStop) {
						me.generateNetwork(data, true);
					} else {
						console.log("WARNING: called generateNetwork with forceStop.")
					}
				};

				sigmaForceLink.bind('stop', addNewNodes);

				setTimeout(function() {
					me.startNetworkLayout();
				}, 2000);
			}

		}else{
			setTimeout(function() {
				me.startNetworkLayout();
			}, 2000);
		}

		return this;
	};

	/**
	* Fills the status line under the toolbar.
	*
	* The MORE regulator-target network has carried one of these from the start
	* ("445 nodes · 400 of 1382 edges · condition Ctr_0H"), and it is the single
	* most useful thing in that panel: it tells you whether you are looking at a
	* thin graph or at a filter that threw the graph away. The pathways network
	* had no equivalent, so an empty canvas was indistinguishable from a broken
	* one - a Reactome network that drew 11 nodes and exactly 1 edge looked
	* identical to a rendering failure, and had to be diagnosed by reading the
	* sigma instance out of the browser console.
	*
	* @param {Number} nodeCount    pathways drawn
	* @param {Number} edgeCount    edges drawn
	* @param {Number} totalPathways pathways this database matched at all
	* @param {Object} visualOptions the filter state the counts came from
	* @chainable
	* @returns {PA_Step3PathwayNetworkView}
	*/
	this.updateNetworkSubtitle = function(nodeCount, edgeCount, totalPathways, visualOptions) {
		var element = document.getElementById("step3-network-subtitle_" + this.dbid);
		if (!element) return this;

		var relation = (visualOptions.edgesClass === "s")
			? "shared biological features"
			: "linked biological processes";

		var parts = [
			"<b>" + nodeCount + "</b> of " + totalPathways + " " +
				this.database + " pathways",
			"<b>" + edgeCount + "</b> edge" + (edgeCount === 1 ? "" : "s") +
				" — " + relation,
			"p &le; " + visualOptions.minPValue
		];

		if (visualOptions.edgesClass === "s") {
			parts.push("similarity &ge; " +
				Math.round(visualOptions.minSharedFeatures * 100) + "%");
		}

		/* Named separately from "nothing is significant": a graph with nodes
		   but no edges is the case a user reads as a bug, and it is worth
		   saying which of the two filters produced it. */
		if (nodeCount > 1 && edgeCount === 0) {
			parts.push('<span class="pa-net-warn">no pathway pair passes this ' +
				'edge filter — try the other edge type in <b>Tools</b></span>');
		}

		element.innerHTML = parts.join(" &middot; ");
		return this;
	};

	/**
	* This function starts/resumes the network layout
	* @chainable
	* @returns {PA_Step3PathwayNetworkView}
	*/
	this.startNetworkLayout = function() {
		var me = this;
		$("#pathwayNetworkWaitBox_" + me.dbid).fadeIn();

		$("#resumeLayoutButton_" + me.dbid).removeClass("resumeLayout");
		$("#resumeLayoutButton_" + me.dbid).html('<i class="fa fa-pause"></i> Stop layout');

		//Hide glyps and edges
		this.drawGlyphs = false;
		this.network.renderers[0].glyphs({draw: false});
		this.network.settings({drawEdges:false});
		sigma.layouts.startForceLink(me.network);

		//Stops automatically in 20seconds, after N iterations or if mean(movement) < 0.01
		this.timeoutID = setTimeout(function() {
			me.stopNetworkLayout();
		}, 20000);

		return this;
	};

	/**
	* This function stops the network layout
	* @chainable
	* @returns {PA_Step3PathwayNetworkView} the view
	*/
	this.stopNetworkLayout = function() {
		sigma.layouts.stopForceLink();
		return this;
	};

	/**
	* Show one of the two panes in the network's rail, and make sure the rail
	* itself is on screen.
	*
	* The rail replaced two 216px panels that stood side by side and were shown
	* and hidden independently - which meant the graph's width depended on how
	* many of them happened to be open, and that "Configure" opened a second
	* column rather than switching one.
	*
	* @chainable
	* @param {String} pane, either "tools" or "details"
	* @returns {PA_Step3PathwayNetworkView} the view
	*/
	this.showRailPane = function(pane) {
		var me = this;
		var isDetails = (pane === "details");

		$("#networkview_" + me.dbid).removeClass("is-railHidden");
		$("#networkDetailsPanel_" + me.dbid).toggle(isDetails);
		$("#networkSettingsPanel_" + me.dbid).toggle(!isDetails);

		$("#networkview_" + me.dbid + " .paNetRailTab").each(function() {
			$(this).toggleClass("is-active", $(this).attr("data-pane") === pane);
		});

		/* The rail appearing, or the panes swapping, changes nothing about the
		   canvas' box - but coming back from a hidden rail does, and that is the
		   same call, so it is made unconditionally rather than guessed at. */
		me.resizeNetwork();

		return this;
	};

	/**
	* Re-measure the canvas and redraw. sigma reads its container's size once, at
	* construction, so every change to the space around the graph - the rail
	* opening or closing, full screen, the resizer at the foot of the card - has
	* to be followed by this or the drawing keeps the old dimensions and the graph
	* sits in a corner of its own panel.
	* @chainable
	* @returns {PA_Step3PathwayNetworkView} the view
	*/
	this.resizeNetwork = function() {
		var me = this;

		if (!me.network) {
			return me;
		}

		/* Deferred one frame: called from a click handler, the layout that the
		   class change causes has not happened yet, so an immediate resize
		   measures the box the graph is leaving rather than the one it is
		   entering. */
		paDeferFrame(function() {
			if (!me.network) {
				return;
			}
			me.network.renderers.forEach(function(renderer) {
				if (renderer.resize) {
					renderer.resize();
				}
			});
			me.network.refresh();
		});

		return me;
	};

	/**
	* Expand the network to fill the screen, or put it back into the page.
	*
	* The previous implementation handed sigma's fullScreen plugin the canvas
	* `div` on its own, and two things followed from that. The canvas keeps the
	* height it has in the page (--pa-net-canvas-height, 720px), so full screen
	* showed a 720px band on a black backdrop rather than a filled screen. And the
	* toolbar holding the button is a *sibling* of that canvas, not a child, so
	* once the browser was showing the canvas alone there was nothing on screen
	* left to click: Escape was the only way out, and nothing said so. That is the
	* reported fault - full screen could not be exited.
	*
	* Expanding the whole panel fixes both at once: the toolbar comes with it, and
	* the button in it now reads "Exit full screen". The native request is still
	* made where the browser allows it, so the screen really is filled; where it is
	* refused - no user gesture, a permissions policy, an embedded frame - the
	* class alone still covers the viewport, so the control can never leave the
	* user somewhere they cannot get back from. Escape is bound for the same
	* reason.
	*
	* @chainable
	* @param {Boolean} expand
	* @returns {PA_Step3PathwayNetworkView} the view
	*/
	this.setFullScreenNetwork = function(expand) {
		var me = this;
		/* The whole area, graph and rail together - not the graph alone. Full
		   screen is where you have the most room to adjust what you are looking
		   at, and leaving the rail behind in the page would have left
		   "Configure" in the expanded toolbar as a control that does nothing
		   visible. */
		var panel = $("#networkview_" + me.dbid);
		var button = $("#fullscreenSettingsPanelButton_" + me.dbid);
		var caption = expand
			? "Put the network back into the page"
			: "Expand the network to the whole window";

		if (!panel.length) {
			return me;
		}

		panel.toggleClass("paNetExpanded", expand);
		button.html(expand
			? '<i class="fa fa-compress"></i> Exit full screen'
			: '<i class="fa fa-expand"></i> Full screen');
		button.attr("title", caption);
		/* tooltipster copies the title into its own store at initialisation and
		   never looks at the attribute again, so without this the button says
		   "Exit full screen" and its tooltip still offers to expand it. */
		if (button.hasClass("tooltipstered")) {
			button.tooltipster("content", caption);
		}

		if (expand) {
			var element = panel[0];
			var request = element.requestFullscreen || element.webkitRequestFullscreen || element.msRequestFullscreen;

			if (request && !me.getFullScreenElement()) {
				/* Both shapes of failure are swallowed: older engines throw, and
				   current ones return a promise that rejects when the click was
				   not a user gesture. Either way the class above has already done
				   the visible work, and an unhandled rejection here would be the
				   only thing the user ever saw of it. */
				try {
					var pending = request.call(element);
					if (pending && pending.catch) {
						pending.catch(function() {});
					}
				} catch (ignored) {}
			}
		} else if (me.getFullScreenElement()) {
			var release = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen;

			if (release) {
				try {
					var leaving = release.call(document);
					if (leaving && leaving.catch) {
						leaving.catch(function() {});
					}
				} catch (ignored) {}
			}
		}

		me.resizeNetwork();

		return me;
	};

	/**
	* The element the browser is currently showing full screen, across the vendor
	* prefixes this application's browsers still answer to.
	* @returns {Element|null}
	*/
	this.getFullScreenElement = function() {
		return document.fullscreenElement || document.webkitFullscreenElement ||
			document.mozFullScreenElement || document.msFullscreenElement || null;
	};

	/**
	* This function activate the fullscreen mode for the network
	* @chainable
	* @returns {PA_Step3PathwayNetworkView} the view
	*/
	this.fullScreenNetwork = function() {
		return this.setFullScreenNetwork(!$("#networkview_" + this.dbid).hasClass("paNetExpanded"));
	};


	/**
	* This function shows the detailed view for selected pathway
	* @chainable
	* @param  {Pathway} pathway the instance to show
	* @returns {PA_Step3PathwayNetworkView} the view
	*/
	this.showPathwayDetails = function(pathway){
		var me = this;

		if(this.pathwayDetailsView === null){
			this.pathwayDetailsView = new PA_Step3PathwayDetailsView();
			this.pathwayDetailsView.getComponent("patwaysDetailsContainer_" + pathway.getSource());
			this.pathwayDetailsView.setParent(this);
		}

		this.pathwayDetailsView.loadModel(pathway);

		var omicNames = [];
		var inputOmics = this.getModel().getGeneBasedInputOmics();
		for(var i in inputOmics){
			omicNames.push(inputOmics[i].omicName);
		}
		this.pathwayDetailsView.updateObserver(omicNames, this.getModel().getDataDistributionSummaries(), this.getParent().getVisualOptions());

		/* One rail, so clicking a node is a pane switch rather than a panel
		   swap: bring Details to the front, then show the pathway inside it in
		   place of the cluster summary. */
		var wasShowing = $("#networkDetailsPanel_" + me.dbid).is(":visible");

		this.showRailPane("details");

		if (wasShowing) {
			$("#networkClustersContainer_" + me.dbid).slideUp(200, function(){
				$("#patwaysDetailsWrapper_" + me.dbid).slideDown();
			});
		} else {
			$("#networkClustersContainer_" + me.dbid).hide();
			$("#patwaysDetailsWrapper_" + me.dbid).show();
		}

		return this;
	};

	/**
	* This function hides the detailed view
	* @chainable
	* @returns	{PA_Step3PathwayNetworkView} the view
	*/
	this.hidePathwayDetails = function(){
		$("#networkClustersContainer_" + this.dbid).slideDown();
		$("#patwaysDetailsWrapper_" + this.dbid).slideUp();
		return this;
	};

	/**
	* This function handles the event when choosing the option "Paint"
	* @chainable
	* @param  {String} pathwayID the ID for the pathway
	* @returns	{PA_Step3PathwayNetworkView} the view
	*/
	this.paintSelectedPathway = function(pathwayID){
		//Propagate to parent
		this.getParent().paintSelectedPathway(pathwayID);
		return this;
	};

	/**
	* This function returns the corresponding color for a given cluster number
	* @param  {String} cluster the cluster number
	* @returns	{String} the hexadecimal color code
	*/
	// The palette lives in Util.js now - Step 4 held a second copy of it that had
	// drifted, so the same cluster was drawn in two different colours depending on
	// which view you were looking at. See getClusterColor there.
	this.getClusterColor= function(cluster){
		return getClusterColor(cluster);
	};
	/**
	 * The AI report's shared-feature cluster containing a pathway, or null.
	 * Read from the partition the Step 3 view keeps (aiClusters).
	 */
	this.getAIClusterOf = function(pathwayID){
		var ai = this.getParent().aiClusters;
		if(!ai || !ai.clusters){ return null; }
		for(var i = 0; i < ai.clusters.length; i++){
			var c = ai.clusters[i];
			if((c.members || []).indexOf(pathwayID) !== -1 || (c.satellites || []).indexOf(pathwayID) !== -1){
				return c;
			}
		}
		return null;
	};
	/**
	 * A stable colour per AI cluster id ("C01" -> palette slot 1), so the same
	 * cluster is drawn in the same colour in the KEGG and the Reactome network.
	 */
	this.getAIClusterColor = function(clusterID){
		var n = parseInt(String(clusterID).replace(/[^0-9]/g, ""), 10);
		if(isNaN(n)){ n = 0; }
		return getClusterColor(n % 20);
	};

	this.updateNodePositions = function(updateCache, preserveExisting=false){
		var visualOptions = this.getParent().getVisualOptions(this.database);
		var indexedPathways = this.getParent().getIndexedPathways(this.database);
		//Invalidate previous position
		for(var pathwayID in indexedPathways){
			delete indexedPathways[pathwayID].networkCoordX;
			delete indexedPathways[pathwayID].networkCoordY;
		}

		//Get new coordinates
		var nodes = this.network.graph.nodes();
		// Save the current positions using keys
		var savedPositions = {};
		if (visualOptions.pathwaysPositions) {
			visualOptions.pathwaysPositions.map(x => savedPositions[x.split('#')[0].trim()] = x);
		}

		delete visualOptions.pathwaysPositions;
		visualOptions.pathwaysPositions=[];

		for(var i in nodes){
			var nodeID = nodes[i].id;
			var existingPosition = preserveExisting && savedPositions[nodeID] ? savedPositions[nodeID].split('#') : null;

			visualOptions.pathwaysPositions.push(existingPosition ? savedPositions[nodeID] : nodes[i].id + "# " + nodes[i].x + "#" + nodes[i].y);

			indexedPathways[nodeID].networkCoordX = existingPosition ? parseFloat(existingPosition[1]) : nodes[i].x;
			indexedPathways[nodeID].networkCoordY = existingPosition ? parseFloat(existingPosition[2]) : nodes[i].y;
		}

		if(updateCache){
			this.getController().updateStoredVisualOptions(this.getModel().getJobID(), this.getParent().getVisualOptions());
		}
		return this;
	};

	this.clearNodePositions = function(){
		var visualOptions = this.getParent().getVisualOptions(this.database);
		var indexedPathways = this.getParent().getIndexedPathways(this.database);

		//Invalidate previous position
		for(var pathwayID in indexedPathways){
			delete indexedPathways[pathwayID].networkCoordX;
			delete indexedPathways[pathwayID].networkCoordY;
		}

		delete visualOptions.pathwaysPositions;

		return this;
	};


	this.getNewClusters = function() {
		var me = this;
		var numberClusters = $("#sliderClusterNumberShow_" + me.dbid).html();
		var omicName = me.getParent().visualOptions[me.dbid].colorBy;
		var databaseName = me.dbid;

		if (numberClusters && omicName !== "classification") {
			me.getParent().controller.updateMetagenesSubmitHandler(me, numberClusters, omicName, databaseName);
		}
	};


	/**
	* This function selects nodes from the network following different approaches
	* @param  {String} option the selection strategy
	* @return {PA_Step3PathwayNetworkView}        this view
	*/
	this.selectNodes = function(option){
		var me = this;

		if(option === "category"){
			this.select.selectByCategory();
		}else if(option === "free"){
			$("#step3-network-toolbar-message_" + me.dbid).removeClass("successMessage").html("<i class='fa fa-info-circle'></i> Select the region that contains the nodes and drag to move.")
			.fadeIn(
				100,
				function(){
					setTimeout(function(){
						$("#step3-network-toolbar-message_" + me.dbid).fadeOut(100);
					}, 1500);
				}
			);
			this.multinodeSelector.activate();
		}else if(option === "adjacent"){
			this.select.selectAllNeighbors();
		}else if(option === "all"){
			this.select.selectAllNodes();
		}
		return this;
	};

	/**
	* This function download the network following different approaches
	* @param  {String} option the download strategy
	* @return {PA_Step3PathwayNetworkView}        this view
	*/
	this.downloadNetwork = function(option){
		if(option === "png"){
			// sigma.plugins.image(this.network, this.network.renderers[0], {
			// 	download:true,
			// 	clip: true,
			// 	labels: true,
			// 	margin: 30,
			// 	// size: 400,
			// 	format: 'png',
			// 	background: 'white',
			// 	zoom: true,
			// 	filename:'paintomics_network_plugin' + this.getParent("PA_Step3JobView").getModel().getJobID() + '.png'
			// });

			var newCanvas =  $('<canvas/>')[0];
			// var scaleFactor = 2;
			newCanvas.height = $("#pathwayNetworkBox_" + this.dbid).height();// * scaleFactor;
			newCanvas.width = $("#pathwayNetworkBox_" + this.dbid).width();// * scaleFactor;
			// newCanvas.style.width = $("#pathwayNetworkBox").width() + "px";
			// newCanvas.style.height = $("#pathwayNetworkBox").height() + "px"

			var ctx3 = newCanvas.getContext('2d');
			// ctx3.scale(scaleFactor, scaleFactor);
			ctx3.drawImage($("#pathwayNetworkBox_" + this.dbid + " canvas.sigma-scene")[0], 0, 0);
			ctx3.drawImage($("#pathwayNetworkBox_" + this.dbid + " canvas.sigma-glyphs")[0], 0, 0);

			// Avoid network error when image is too large
			// function dataURLtoBlob(dataurl) {
			//     var arr = dataurl.split(','), mime = arr[0].match(/:(.*?);/)[1],
			//         bstr = atob(arr[1]), n = bstr.length, u8arr = new Uint8Array(n);
			//     while(n--){
			//         u8arr[n] = bstr.charCodeAt(n);
			//     }
			//     return new Blob([u8arr], {type:mime});
			// }
			//
			// var imgData = newCanvas.toDataURL('image/png')
			// var strDataURI = imgData.substr(22, imgData.length);
			// var blob = dataURLtoBlob(imgData);
			// URL.createObjectURL(blob)

			$('<a target="_blank" id="downloadNetworkLink_' + this.dbid + '" download="paintomics_network_' + this.dbid + '_' + this.getParent("PA_Step3JobView").getModel().getJobID() + '.png" style="display:none;"></a>').attr("href", newCanvas.toDataURL('image/png'))[0].click();

		}
		else if(option === "svg"){
				// Get sigma instance
				this.network.toSVG({
					download: true,
					labels: true,
					data: true,
					filename: 'paintomics_network_' + this.dbid + '_' + this.getParent("PA_Step3JobView").getModel().getJobID() + '.svg'
				})
		}
		return this;
	};

	/**
	* This function reorder the selected nodes following different approaches
	* @param  {String} option the reorder strategy
	* @return {PA_Step3PathwayNetworkView}        this view
	*/
	this.reorderNodes = function(option, size){
		var selectedNodes = sigma.plugins.activeState(this.network).nodes();
		if(selectedNodes.length === 0){
			return this;
		}

		if(option === "random"){
			var nodes = this.network.graph.nodes();

			var minX=Number.MAX_VALUE, maxX=Number.MIN_VALUE, minY=Number.MAX_VALUE, maxY=Number.MIN_VALUE, node;
			for(var i in nodes){
				node = nodes[i];
				minX=((node.x < minX)?node.x:minX);
				maxX=((node.x > maxX)?node.x:maxX);
				minY=((node.y < minY)?node.y:minY);
				maxY=((node.y > maxY)?node.y:maxY);
			}

			for(var i in selectedNodes){
				selectedNodes[i].x = (Math.random()*maxX) + minX;
				selectedNodes[i].y = (Math.random()*maxY) + minY;
			}
			this.network.refresh();
			return this;
		}else if(option === "block"){
			var initX=selectedNodes[0].x, y=selectedNodes[0].y, x = initX;
			size = (size|| $('#reorderOptions_' + this.dbid + ' h3[name="block"]').attr("value"));

			for(var i=0; i< selectedNodes.length; i++){
				selectedNodes[i].x = x;
				selectedNodes[i].y = y;
				x+= 30;
				if((i+1) % size === 0){
					x=initX;
					y+=30;
				}
			}
		}else if(option === "ring"){
			size = (size|| $('#reorderOptions_' + this.dbid + ' h3[name="ring"]').attr("value"));
			var x=selectedNodes[0].x, y=selectedNodes[0].y;
			for(var i=0; i< selectedNodes.length; i++){
				selectedNodes[i].x = x + Math.cos(2 * i * Math.PI / selectedNodes.length) * selectedNodes.length*size; //RING LAYOUT
				selectedNodes[i].y = y + Math.sin(2 * i * Math.PI / selectedNodes.length)* selectedNodes.length*size;
			}
		}
		$('#reorderOptions_' + this.dbid + ' h3').each(function(index) {
			$(this).toggle($(this).attr("name") === option);
		});
		$("#reorderOptions_" + this.dbid).slideDown();

		this.network.refresh();
		return this;
	};

	/**
	* This function changes different node attributes
	* @param  {String} option the attribute to change
	* @return {PA_Step3PathwayNetworkView}        this view
	*/
	this.configureNodes = function(option, size){
		var selectedNodes = sigma.plugins.activeState(this.network).nodes();
		if(selectedNodes.length === 0){
			return this;
		}

		// Modify the point size
		if(option === "size-conf"){
			var nodes = this.network.graph.nodes();
			size = parseInt((size|| $('#reorderOptions_' + this.dbid + ' h3[name="size-conf"]').attr("value")));

			console.log("Increasing node by size ", size)

			for(var i in selectedNodes){
				console.log(selectedNodes[i].size)
				selectedNodes[i].size = selectedNodes[i].size + size
			}
		}
		$('#reorderOptions_' + this.dbid + ' h3').each(function(index) {
			$(this).toggle($(this).attr("name") === option);
		});
		$("#reorderOptions_" + this.dbid).slideDown();

		this.network.refresh();
		return this;
	};

	/**
	* This function apply the settings that user can change
	* for the visual representation of the model (w/o reload everything).
	* - STEP 1. UPDATE THE VALUES FOR THE SLIDERS
	* - STEP 2. UPDATE THE VALUE FOR COLOR BY OPTION
	* - STEP 3. UPDATE THE VALUE FOR THE EDGES CLASS OPTION
	* - STEP 4. SAVE THE POSITION FOR NODES (IF SELECTED)
	* - STEP 5. 2 ALTERNATIVES
	*    - STEP 5.A NOTIFY THE CHANGES TO PARENT (RECALCULATE NETWORK)
	*    - STEP 5.B.1 HIDE/SHOW LABELS W/O RECALCULATE NETWORK
	* @chainable
	* @returns {PA_Step3PathwayClassificationView}
	*/
	this.applyVisualSettings =  function() {
		var me = this;
		var visualOptions = this.getParent().getVisualOptions(this.database);

		$("#pathwayNetworkWaitBox_" + me.dbid).fadeIn();

		/********************************************************/
		/* STEP 1. UPDATE THE VALUES FOR THE SLIDERS            */
		/********************************************************/
		var updateNeeded = false;
		var newValue, id, autosave;

		$("#pathwayNetworkToolsBox_" + me.dbid + "  div.slider-ui").each(function() {
			/* Remove database name from id */
			id = $(this).attr("id").replace("_" + me.database, "");
			newValue = ($.inArray(id,
			 ["minPValueSlider", "maxNodeSizeSlider", "minNodeSizeSlider", "fontSizeSlider"]) === -1 ?
			 $(this).slider("value") / 100 : $(this).slider("value"));

			id = id.replace("Slider", "");
			updateNeeded = updateNeeded || (visualOptions[id] !== newValue);
			visualOptions[id] = newValue;
		});

		/*******************************************************************/
		/* STEP 2. UPDATE THE VALUE FOR COLOR BY OPTION AND OTHER SETTINGS */
		/*******************************************************************/
		newValue = $("#colorByContainer_" + me.dbid + " div.radio input:checked").val();
		updateNeeded = updateNeeded || (visualOptions.colorBy !== newValue);
		visualOptions.colorBy = newValue;

		pvalNewValue = $("#pvaluemethod_" + me.dbid + " div.radio input:checked").val();
		updateNeeded = updateNeeded || (visualOptions.networkPvalMethod !== pvalNewValue);
		visualOptions.networkPvalMethod = pvalNewValue;

		visualOptions.backgroundLayout =  $("#background-layout-check_" + me.dbid).is(":checked");
		visualOptions.showNodeLabels =  $("#show-node-labels-check_" + me.dbid).is(":checked");
		visualOptions.useCombinedPvalCheckbox =  $("#use-combined-pval-check_" + me.dbid).is(":checked");
		//visualOptions.showEdgeLabels =  $("#show-edge-labels-check").is(":checked");


		/********************************************************/
		/* STEP 3. UPDATE THE VALUE FOR THE EDGES CLASS OPTION
		/********************************************************/
		newValue = $("#edgesClassContainer_" + me.dbid + " div.radio input:checked").val();
		updateNeeded = updateNeeded || (visualOptions.edgesClass !== newValue);
		visualOptions.edgesClass = newValue;

		/********************************************************/
		/* STEP 4. SAVE THE POSITION FOR NODES (IF SELECTED)    */
		/********************************************************/
		newValue = $("#save-node-positions-check_" + me.dbid).is(":checked");
		autosave = $("#auto-save-node-positions-check_" + me.dbid).is(":checked");

		if(newValue && (autosave || visualOptions.pathwaysPositions === undefined)){
			/***************************************************************/
			/* STEP 4.1 IF SAVE=true AND NO PREVIOUS POSITION DATA -> SAVE */
			/* SAVE ALSO IF AUTO-SAVE DATA IS SET						   */
			/***************************************************************/
			this.updateNodePositions(false);
		}else if(!newValue && visualOptions.pathwaysPositions !== undefined){
			/***************************************************************/
			/* STEP 4.2 IF SAVE=false AND PREVIOUS POSITION DATA -> CLEAN  */
			/***************************************************************/
			this.clearNodePositions();
		}
		updateNeeded=true;

		/********************************************************/
		/* STEP 5. HIDE THE SETTINGS PANEL                      */
		/********************************************************/
		// $("#networkSettingsPanel").hide(200, function(){
		// 	$("#networkDetailsPanel").show();
		// 	$("#patwaysDetailsWrapper").slideUp();
		// 	$("#networkClustersContainer").slideDown();
		// });

		if(updateNeeded){
			/**************************************************************/
			/* STEP 5.A NOTIFY THE CHANGES TO PARENT (RECALCULATE NETWORK)*/
			/**************************************************************/
			me.getParent().applyVisualSettings(me.getName(), me.database);
		}else{
			/********************************************************/
			/* STEP 5.B.1 HIDE/SHOW LABELS W/O RECALCULATE NETWORK    */
			/********************************************************/
			me.network.settings({
				drawEdges:true,
				//edgeLabelThreshold: ((visualOptions.showEdgeLabels===true?0:8)),
				labelThreshold : ((visualOptions.showNodeLabels===true?1:8))
			});
			me.network.renderers[0].render();

			/********************************************************/
			/* STEP 5.B.2 UPDATE THE CACHE
			/********************************************************/
			me.getController().updateStoredVisualOptions(me.getModel().getJobID(), me.getParent().getVisualOptions());

			$("#pathwayNetworkWaitBox_" + me.dbid).fadeOut();
		}
	};

	/**
	* This function updates the visual representation of the model.
	*  - STEP 1. GENERATE THE COLORBY SELECTOR
	*  - STEP 2. GENERATE THE REMAINIG SELECTORS
	*  - STEP 3. GENERATE THE NETWORK
	* @chainable
	* @returns {PA_Step3PathwayNetworkView}
	*/
	this.updateObserver = function() {
		var me = this;
		var visualOptions = this.getParent().getVisualOptions(this.database);

		/********************************************************/
		/* STEP 1. GENERATE THE COLORBY SELECTOR                */
		/********************************************************/
		var htmlContent = '<div class="radio"><input type="radio" ' + ((visualOptions.colorBy === "classification")? "checked": "") + ' id="classification-check_' + this.dbid + '"  name="colorByCheckbox_' + this.dbid + '" value="classification"><label for="classification-check_' + this.dbid + '">Classification</label></div>';
		var inputOmics = this.getModel().getGeneBasedInputOmics();
		for(var i in inputOmics){
			htmlContent +=
			'<div class="radio">' +
			'  <input type="radio" ' + ((visualOptions.colorBy === inputOmics[i].omicName)? "checked": "")+ ' id="' + inputOmics[i].omicName.replace(/ /g, "_").toLowerCase() + '-check_' + this.dbid + '" name="colorByCheckbox_' + this.dbid + '" value="' + inputOmics[i].omicName + '">' +
			'  <label for="' + inputOmics[i].omicName.replace(/ /g, "_").toLowerCase() + '-check_' + this.dbid + '">' + inputOmics[i].omicName + '</label>' +
			'</div>';
		}
		if(this.getParent().aiClusters){
			htmlContent +=
			'<div class="radio">' +
			'  <input type="radio" ' + ((visualOptions.colorBy === "aiclusters")? "checked": "")+ ' id="aiclusters-check_' + this.dbid + '" name="colorByCheckbox_' + this.dbid + '" value="aiclusters">' +
			'  <label for="aiclusters-check_' + this.dbid + '">AI pathway clusters</label>' +
			'</div>';
		}
		$("#colorByContainer_" + this.dbid).html(htmlContent);

		/********************************************************/
		/* STEP 2. GENERATE THE REMAINIG SELECTORS              */
		/********************************************************/
		$("#minFeaturesSlider_" + this.dbid).slider({value: visualOptions.minFeatures * 100});
		$("#minFeaturesValue_" + this.dbid).html(visualOptions.minFeatures * 100);

		$("#minSharedFeaturesSlider_" + this.dbid).slider({value: visualOptions.minSharedFeatures * 100});
		$("#minSharedFeaturesValue_" + this.dbid).html(visualOptions.minSharedFeatures * 100);

		$("#minPValueSlider_" + this.dbid).slider({value: visualOptions.minPValue});
		$("#minPValue_" + this.dbid).html(visualOptions.minPValue);

		$("#minNodeSizeSlider_" + this.dbid).slider({value: visualOptions.minNodeSize});
		$("#minNodeSizeValue_" + this.dbid).html(visualOptions.minNodeSize);

		$("#maxNodeSizeSlider_" + this.dbid).slider({value: visualOptions.maxNodeSize});
		$("#maxNodeSizeValue_" + this.dbid).html(visualOptions.maxNodeSize);

		$("#fontSizeSlider_" + this.dbid).slider({value: visualOptions.fontSize});
		$("#fontSizeValue_" + this.dbid).html(visualOptions.fontSize);

		$("#background-layout-check_" + this.dbid).attr("checked", visualOptions.backgroundLayout===true);
		$("#show-node-labels-check_" + this.dbid).attr("checked", visualOptions.showNodeLabels===true);
		//$("#show-edge-labels-check").attr("checked", visualOptions.showEdgeLabels===true);
		$("#save-node-positions-check_" + this.dbid).attr("checked", visualOptions.pathwaysPositions!==undefined);
		$("#auto-save-node-positions-check_" + this.dbid).attr("checked", visualOptions.autoSaveNodePositions === true);
		$("#pre-auto-save-node-positions-check_" + me.dbid).toggle(visualOptions.pathwaysPositions!==undefined);
		$("#use-combined-pval-check_" + this.dbid).attr("checked", visualOptions.useCombinedPvalCheckbox === true);

		var pvalHtmlContent = '<div class="radio"><input type="radio" ' + ((visualOptions.networkPvalMethod === "none")? "checked": "") + ' id="none-pvalcheck_' + this.dbid + '" name="pvaluemethodCheckbox_' + this.dbid + '" value="none">' +
			'  <label for="none-pvalcheck_' + this.dbid + '">None</label>' +
			'</div>';
		var adjustMethods = this.getModel().getMultiplePvaluesMethods();

		adjustMethods.forEach(function(i){
			pvalHtmlContent +=
			'<div class="radio">' +
			'  <input type="radio" ' + ((visualOptions.networkPvalMethod === i)? "checked": "")+ ' id="' + i.replace(/ /g, "_").toLowerCase() + '-pvalcheck_' + me.dbid + '" name="pvaluemethodCheckbox_' + me.dbid + '" value="' + i + '">' +
			'  <label for="' + i.replace(/ /g, "_").toLowerCase() + '-pvalcheck_' + me.dbid + '">' + i + '</label>' +
			'</div>';
		});
		$("#pvaluemethod_" + this.dbid).html(pvalHtmlContent);

		// Adjust the height of the other panels
		var currentHeight = this.getComponent().getHeight();

		//this.getComponent().items.getAt(0).setHeight(currentHeight);
		this.getComponent().doLayout();

		/********************************************************/
		/* STEP 3. GENERATE THE NETWORK                         */
		/********************************************************/
		/* Delay the drawing of the database if it is not active */
		var active_db = this.getParent().component.down("#tabcontainer_network").getActiveTab().title;

		if (active_db == this.database) {
			this.getController().step3GetPathwaysNetworkDataHandler(this);
		}

		initializeTooltips(".helpTip");

		return this;
	};

	/**
	* This function generates the component (EXTJS) using the content of the model
	* @returns {Ext.ComponentView} The visual component
	*/
	this.initComponent = function() {
		var me = this;
		var visualOptions = this.getParent().getVisualOptions(this.database);

		this.component = Ext.widget({
			xtype: 'container', id: 'networkview_' + me.dbid,
			/* `paNetArea` is the flex row: the graph on the left, one rail of
			   controls on the right. It was two floated 216px panels before -
			   "Tools" and "Details" side by side - which took 462px of a 1114px
			   card for two columns that are never both being read, and left the
			   diagram they annotate with less than half the space. One rail with
			   two panes gives that back, and stretches to the graph's height on
			   its own rather than through the 876px literal the floats needed. */
			cls: 'paNetArea',
			/*autoHeight: true,
			layout:
			{
			   type: "hbox",
			   align: "stretch"
			},*/
			//style: "max-width:1800px; margin: 5px 10px; ",
			items: [ {
				xtype: 'box', id: 'networkDetailsPanel_' + me.dbid,
				//autoHeight: true, flex: 1,
				/* No `contentbox`, and no <h2> of its own: this is a pane inside
				   the card's rail, and the rail's tab already names it. It keeps
				   `lateralOptionsPanel` because that is what dresses the controls
				   inside it - and what paTocSections() looks for when deciding
				   that a heading in here titles a control, not an analysis. */
				cls: "lateralOptionsPanel paNetRailPane", html:
				//THE PANEL WITH THE CLUSTERS SUMMARY
				'<div id="networkClustersContainer_' + me.dbid + '">' +
				'  <h4>TheName For AnOmic</h4><span class="infoTip">Click on each cluster to hide/show the nodes in the network</span>' +
				'  <h5>N Clusters founds</h5>' +
				'  <div style="text-align: center;"> </div>' +
				'  <hr/>' +
				'</div>' +
				'<div id="sliderClusterNumberContainer_' + me.dbid + '" style="display: none;">' +
				'  <h5>Modify number of clusters</h5>' +
				'  <span class="infoTip">Change the number of the desired clusters and apply the results. Be aware that this is an <b>intensive</b> process that will use the queue system so the results may take some time to be retrieved.</span>' +
				'  <p style="margin:10px;">Generate <span id="sliderClusterNumberShow_' + me.dbid + '"></span> clusters.</p>' +
				'  <div class="slider-ui" id="sliderClusterNumber_' + me.dbid + '"></div>' +
				'  <a href="javascript:void(0)" class="button btn-success btn-right helpTip" id="applyClusterNumber_' + me.dbid + '" style="margin: 20px auto;"><i class="fa fa-check"></i> Apply</a>' +
				'</div>' +
				//THE PANEL WITH THE PATHWAY DETAILS
				'<div id="patwaysDetailsWrapper_' + me.dbid + '" style="display:none;">'+
				'  <a href="javascript:void(0)" id="backToClusterDetailsButton_' + me.dbid + '" style="margin: 5px 0px;"><i class="fa fa-long-arrow-left"></i> Back to Cluster details</a>'+
				'  <div id="patwaysDetailsContainer_' + me.dbid + '"></div>'+
				'</div>'
			},{
				xtype: 'box',  id : 'networkSettingsPanel_' + me.dbid,
				//autoHeight: true, flex: 1,
				// paSettingsPanel: a column of grouped controls, so its h4s are
				// group labels rather than names and main.css tracks them out.
				// Deliberately not on the Details panel beside it, whose h4 is
				// whatever the network is currently coloured by.
				cls: "lateralOptionsPanel paSettingsPanel paNetRailPane", html:
				//THE PANEL WITH THE VISUAL OPTIONS
				'<div id="pathwayNetworkToolsBox_' + me.dbid + '" style="overflow:hidden;">' +
				'  <h4>Visual settings</h4>' +
				'  <h5>Node coloring: <span class="helpTip" style="float:right;" title="Change the way in which nodes are colored."></span></h5>' +
				'  <div id="colorByContainer_' + me.dbid + '"></div>' +
				/* The tooltip used to describe only the KEGG case ("links to other
				   KEGG pathways"), which left a Reactome or MapMan user reading
				   an explanation of a database they were not looking at. Each
				   database states process relatedness its own way, so say which
				   one is being used. */
				'  <h5>Choose what edges represents: <span class="helpTip" style="float:right;" title="<b>Linked biological processes</b> means the two pathways are related in biological terms, as the database itself states it. In KEGG that is a link drawn on a pathway map to another map; in Reactome it is the pathway hierarchy - two processes under a common parent, or a process and one nested inside it - together with any sub-pathway a diagram embeds.<br><br><b>Shared biological features</b> instead draws an edge wherever two pathways have genes or compounds in common, with the thickness increasing with the similarity between the two sets of matched features. Use the <i>Min shared features</i> slider below to set how much overlap is enough."></span></h5>' +
				'  <div id="edgesClassContainer_' + me.dbid + '">' +
				'    <div class="radio">' +
				'      <input type="radio" ' + ((visualOptions.edgesClass === "l")? "checked": "")+ ' id="edgesLinkedPathways_' + me.dbid + '" name="edgesClassCheckbox-check_' + me.dbid + '" value="l">' +
				'      <label for="edgesLinkedPathways_' + me.dbid + '">Linked biological processes</label>' +
				'    </div>'+
				'    <div class="radio">' +
				'      <input type="radio" ' + ((visualOptions.edgesClass === "s")? "checked": "")+ ' id="edgesSharedFeatures_' + me.dbid + '" name="edgesClassCheckbox-check_' + me.dbid + '" value="s">' +
				'      <label for="edgesSharedFeatures_' + me.dbid + '">Shared biological features</label>' +
				'    </div>'+
				'  </div>'+
				'  <h5>Other settings:</h5>' +
				'  <div class="checkbox"><input type="checkbox" id="show-node-labels-check_' + me.dbid + '" name="showNodeLabelsCheckbox">' +
				'    <label for="show-node-labels-check_' + me.dbid + '">Show all node labels <span class="helpTip" style="float:right;" title="Shows labels for nodes (reduces performance). By default labels are visible when zooming the network."</span></label>' +
				'  </div>'+
				'  <h5>Label font size (<span id="fontSizeValue_' + me.dbid + '">14</span>)<span class="helpTip" style="float:right;" title="Font size of the labels."></span></h5>' +
				'  <div class="slider-ui" id="fontSizeSlider_' + me.dbid + '"></div>' +
				'  <div style="display: none;">' +
				'  <h5>Max node size (<span id="maxNodeSizeValue_' + me.dbid + '">8</span>)<span class="helpTip" style="float:right;" title="Determines the maximum size that a node can have, scaling the others to maintain the correct ratio."</span></h5>' +
				'  <div class="slider-ui" id="maxNodeSizeSlider_' + me.dbid + '"></div>' +
				'  <h5>Min node size (<span id="minNodeSizeValue_' + me.dbid + '">1</span>)<span class="helpTip" style="float:right;" title="Determines the minimum size that a node can have, scaling the others to maintain the correct ratio."</span></h5>' +
				'  <div class="slider-ui" id="minNodeSizeSlider_' + me.dbid + '"></div>' +
				' </div>' +
				// '  <div class="checkbox"><input type="checkbox" id="show-edge-labels-check" name="showEdgeLabelsCheckbox">' +
				// '    <label for="show-edge-labels-check">Show all edge labels <span class="helpTip" style="float:right;" title="Shows labels for edges (reduces performance). Edge labels indicate the percentage of shared features (genes + metabolites) shared between 2 pathways."</span></label>' +
				// '  </div>'+
				'  <h4>Network layout settings</h4>' +
				'  <div class="checkbox"><input type="checkbox" id="save-node-positions-check_' + me.dbid + '" name="saveNodePositionsCheckbox">' +
				'    <label for="save-node-positions-check_' + me.dbid + '">Save the nodes positions<span class="helpTip" style="float:right;" title="Use this option if you want to save the position for nodes in the network (increases performance)."></span><span class="commentTip" style="padding-left:21px;">Disable the auto-layout for network.</span></label>' +
				'  </div>'+
				'  <div class="checkbox" id="pre-auto-save-node-positions-check_' + me.dbid + '"><input type="checkbox" id="auto-save-node-positions-check_' + me.dbid + '" name="autoSaveNodePositionsCheckbox">' +
				'    <label for="auto-save-node-positions-check_' + me.dbid + '">Auto-save positions<span class="helpTip" style="float:right;" title="Use this option if you want to save the position for nodes in the network when clicking the \'Apply\' button, instead of having to click \'Save node positions\' before."></span><span class="commentTip" style="padding-left:21px;">Save positions after clicking "Apply".</span></label>' +
				'  </div>'+
				'  <div class="checkbox"><input type="checkbox" id="background-layout-check_' + me.dbid + '" name="backgroundLayoutCheckbox">' +
				'    <label for="background-layout-check_' + me.dbid + '">Calculate layout on background <span class="helpTip" style="float:right;" title="Run the layout on background, apply the new nodes position on stop (increases performance)."></span><span class="commentTip" style="padding-left:21px;">Increases performance.</span></label>' +
				'  </div>'+
				"  <h4>Node filtering options</h4>" +
				'  <h5>Min features in pathway (<span id="minFeaturesValue_' + me.dbid + '">50</span>%)<span class="helpTip" style="float:right;" title="Min % of features (genes + compounds) of a pathway found at the input. Pathways with lower values will be excluded from the network. E.g. Using min=50%, if we find 80 features from the input data, at a Pathway that contains 200 features, the pathway will be excluded (80 < 100)."></span></h5>' +
				'  <div class="slider-ui" id="minFeaturesSlider_' + me.dbid + '"></div>' +
				'  <h5>Min shared features (<span id="minSharedFeaturesValue_' + me.dbid + '">10</span>%)<span class="helpTip" style="float:right;" title="Min. % of features shared between 2 pathways (using the smaller pathway as reference). Edges showing a smaller relationship will be excluded.<br>E.g. Taking min=10%, Pathway A (60 features) and B (90 features), if shared features=5 the edge will be ignored (5 < Min(60,90) * 0.1)"></span></h5>' +
				'  <div class="slider-ui" id="minSharedFeaturesSlider_' + me.dbid + '"></div>' +
				'  <h5>Min p-value for the pathway (<span id="minPValue_' + me.dbid + '">0.05</span>)<span class="helpTip" style="float:right;" title="Pathways with lower p-value (more significant) will be represented with bigger nodes. Pathways with higher p-value (less significant), will be shown as small nodes."</span></h5>' +
				'  <div class="slider-ui" id="minPValueSlider_' + me.dbid + '"></div>' +
				'  <div class="checkbox"><input type="checkbox" id="use-combined-pval-check_' + me.dbid + '" name="useCombinedPvalCheckbox">' +
				'    <label for="use-combined-pval-check_' + me.dbid + '">Always use combined p-value <span class="helpTip" style="float:right;" title="When coloring for one omic, use always the combined p-value for filtering if enabled, otherwise rely on the omic p-value."</span></label>' +
				'  </div>'+
				'  <h5>P-value selection criteria: <span class="helpTip" style="float:right;" title="Select which adjust method to choose the p-values from."></span></h5>' +
				'  <div id="pvaluemethod_' + me.dbid + '"></div>' +
				'  <a href="javascript:void(0)" class="button btn-success btn-right helpTip" id="applyNetworkSettingsButton_' + me.dbid + '" style="margin-top: 20px;" title="Apply changes"><i class="fa fa-check"></i> Apply</a>' +
				'</div>'
			},{
				/* The rail's own tab strip. The two panes above are placed into one
				   grid cell by paNetArea, so exactly one is on screen at a time and
				   this is what says which - and what names them, now that neither
				   pane carries a heading of its own.

				   A fourth sibling rather than a wrapper around the panes: this
				   layout is a CSS grid precisely so that the rail can be assembled
				   without nesting the two panes inside a container, which is a
				   change that would have had to be made inside every id-addressed
				   selector the network code already relies on. */
				xtype: 'box', cls: "paNetRailTabs", html:
				'<a href="javascript:void(0)" class="paNetRailTab is-active helpTip" data-pane="tools" title="Everything that changes what the graph shows. Some options also affect the table below."><i class="fa fa-sliders"></i> Tools</a>' +
				'<a href="javascript:void(0)" class="paNetRailTab helpTip" data-pane="details" title="The colour legend, and the detail for whichever pathway you last clicked"><i class="fa fa-info-circle"></i> Details</a>' +
				'<a href="javascript:void(0)" class="paNetRailHide helpTip" title="Hide this panel and give the graph the whole card"><i class="fa fa-times"></i></a>'
			},{
				xtype: 'box', id: 'networkPanel_' + me.dbid,
				//autoHeight: true, flex: 4,
				/* `paNetMain` is the graph half of the grid, and the element that
				   full screen expands - see setFullScreenNetwork. No `contentbox`:
				   the card around the whole explorer draws the only border here. */
				cls: "paNetMain",
				style: 'overflow: hidden; margin:0;', html:
				//THE PANEL WITH THE NETWORK
				/* One band, two groups. The controls that change what you are
				   looking at sit left; the ones that act on the current view -
				   the layout toggle, pinning positions, tooltips, and the two
				   downloads that used to float over the title - sit right.
				   Shapes and spacing come from .pa-net-tool in
				   network-views.css, which the MORE network's buttons share. */
				/* h3, not h2. The card's one h2 is "Pathway explorer" a few hundred
				   pixels above; this names the second block inside it. The contents
				   strip counts h2s, so a second one here would have put the network
				   in the sidebar as an analysis separate from the card it lives
				   in. */
				'<h3 class="paNetTitle">Pathways network<span class="helpTip" title="This Network represents the relationships between matched pathways."></span></h3>' +
				'<div id="step3-network-toolbar_' + me.dbid + '" class="pa-net-toolbar">' +
				' <div class="lateralOptionsPanel" id="reorderOptions_' + me.dbid + '" style="display:none;">' +
				'  <div class="lateralOptionsPanel-toolbar">' +
				'    <a href="javascript:void(0)" class="toolbarOption helpTip hideOption" title="Hide this panel"><i class="fa fa-times"></i></a>' +
				'  </div>' +
				'  <h3 name="block" value="10">Nodes per row:</h3>' +
				'  <h3 name="ring" style="display: none;" value="2">Ring size:</h3>' +
				'  <h3 name="size-conf" style="display: none;" value="0">Node size:</h3>' +
				'  <span>' +
				'    <i class="fa fa-minus-square fa-2x" name="less" style="margin-right: 22px;padding-top: 5px; color: #DA643D;"></i>' +
				'    <i class="fa fa-plus-square fa-2x"  name="more" style="color: #DA643D;"></i>' +
				'  </span>' +
				' </div>' +
				'  <a href="javascript:void(0)" class="pa-net-tool helpTip" id="showNetworkSettingsPanelButton_' + me.dbid + '" title="Show the Tools panel"><i class="fa fa-sliders"></i> Configure</a>' +
				'  <a href="javascript:void(0)" class="pa-net-tool helpTip" id="fullscreenSettingsPanelButton_' + me.dbid + '" title="Expand the network to the whole window"><i class="fa fa-expand"></i> Full screen</a>' +
				'  <div class="menu">'+
				'    <a href="javascript:void(0)" class="pa-net-tool menuOption helpTip" style="display: none"><i class="fa fa-mouse-pointer"></i> Node selection</a>' +
				'    <div class="menuBody">' +
				'      <a href="javascript:void(0)" class="pa-net-tool helpTip submenuOption selectNodesOption" name="category" title="Select all nodes based on the categories/clusters for current selection"><i class="fa fa-object-ungroup"></i> Category-based selection</a>' +
				'      <a href="javascript:void(0)" class="pa-net-tool helpTip submenuOption selectNodesOption" name="free" title="Select nodes at a hand-drawn region"><i class="fa fa-cut"></i> Free select tool</a>' +
				'      <a href="javascript:void(0)" class="pa-net-tool helpTip submenuOption selectNodesOption" name="adjacent" title="Select adjacent nodes for selected nodes"><i class="fa fa-share-alt"></i> Select adjacent nodes</a>' +
				'      <a href="javascript:void(0)" class="pa-net-tool helpTip submenuOption selectNodesOption" name="all" title="Select all nodes in the network"><i class="fa fa-object-group"></i> Select all nodes</a>' +
				'    </div>'+
				'  </div>' +
				'  <div class="menu">'+
				'    <a href="javascript:void(0)" class="pa-net-tool menuOption helpTip"  style="display: none"><i class="fa fa-mouse-pointer"></i> Reorder selected nodes</a>' +
				'    <div class="menuBody">' +
				'      <a href="javascript:void(0)" class="pa-net-tool helpTip submenuOption reorderNodesOption" name="block" title="Organize selected nodes in to a block"><i class="fa fa-th"></i> Display as block</a>' +
				'      <a href="javascript:void(0)" class="pa-net-tool helpTip submenuOption reorderNodesOption" name="ring" title="Organize selected nodes into a ring"><i class="fa fa-spinner"></i> Display as ring</a>' +
				'      <a href="javascript:void(0)" class="pa-net-tool helpTip submenuOption reorderNodesOption" name="random" title="Set random positions for selected nodes"><i class="fa fa-random"></i> Randomize positions</a>' +
				'    </div>'+
				'  </div>' +
				'  <div class="menu">'+
				'    <a href="javascript:void(0)" class="pa-net-tool menuOption helpTip"  style="display: none"><i class="fa fa-cog"></i> Node attributes</a>' +
				'    <div class="menuBody">' +
				'      <a href="javascript:void(0)" class="pa-net-tool helpTip submenuOption configureNodesOption" name="size-conf" title="Increase or decrease point size"><i class="fa fa-th"></i> Change point size</a>' +
				'    </div>'+
				'  </div>' +
				'  <span class="pa-net-toolbar-gap"></span>' +
				'  <a href="javascript:void(0)" class="pa-net-tool helpTip resumeLayout" id="resumeLayoutButton_' + me.dbid + '" title="Start or stop the force-directed layout"><i class="fa fa-play"></i> Resume layout</a>' +
				/* A floppy disk for "remember where I put these nodes" is a
				   metaphor for a device none of this application's users have
				   owned. A pin is what the action does. */
				'  <a href="javascript:void(0)" class="pa-net-tool helpTip" id="saveNodePositionsButton_' + me.dbid + '" title="Pin the nodes where they are now, so this layout is restored next time"><i class="fa fa-thumb-tack"></i> Save positions</a>' +
				'  <a href="javascript:void(0)" class="pa-net-tool helpTip" id="toggleTooltipsButton_' + me.dbid + '" title="Show or hide the tooltip that follows the cursor over a node"><i class="fa fa-commenting-o"></i> Tooltips</a>' +
				'  <span class="pa-net-toolbar-sep"></span>' +
				'  <a href="javascript:void(0)" class="pa-net-tool helpTip" id="downloadNetworkTool_' + me.dbid + '" title="Download the network (PNG)"><i class="fa fa-download"></i> PNG</a>' +
				'  <a href="javascript:void(0)" class="pa-net-tool helpTip" id="downloadNetworkToolSVG_' + me.dbid + '" title="Download the network (SVG)"><i class="fa fa-download"></i> SVG</a>' +
				'  <p id="step3-network-toolbar-message_' + me.dbid + '"></p>'+
				'</div>' +
				/* The status line the MORE network already had. It is filled in
				   by updateNetworkSubtitle() every time the graph is rebuilt. */
				'<div class="pa-net-subtitle" id="step3-network-subtitle_' + me.dbid + '">Building network&hellip;</div>' +
				/* No height here any more. It was 775px inline while MORE's canvas was
			   600px in its own stylesheet, so the two graph panels on this page
			   were different shapes for no reason either file could see. Both now
			   read --pa-net-canvas-height from network-views.css. */
			'<div id="pathwayNetworkBox_' + me.dbid + '" class="pa-net-canvas" style="overflow:hidden; width: 100%;"><div id="pathwayNetworkWaitBox_' + me.dbid + '"><i class="fa fa-cog fa-spin"></i> Building network...</div></div>' +
				'<div id="pathwayNetworkBoxSVG_' + me.dbid + '" style="display: none;">'
			}],
			listeners: {
				tabchange: function() {
					/* When the tab becomes activated, force the network drawing */
					if (me.network === null) {
							me.getController().step3GetPathwaysNetworkDataHandler(me);
					}
				},
				afterrender: function() {
					//SOME EVENT HANDLERS
					$("#minFeaturesSlider_" + me.dbid).slider({
						range: "min",value: 0,min: 0,max: 100,step: 5,
						slide: function(event, ui) {
							$("#minFeaturesValue_" + me.dbid).html(ui.value);
						}
					});
					$("#minSharedFeaturesSlider_" + me.dbid).slider({
						range: "min",value: 0,min: 0,max: 100,step: 5,
						slide: function(event, ui) {
							$("#minSharedFeaturesValue_" + me.dbid).html(ui.value);
						}
					});
					$("#minPValueSlider_" + me.dbid).slider({
						range: "min",value: 0,min: 0.005,max: 1,step: 0.005,
						slide: function(event, ui) {
							$("#minPValue_" + me.dbid).html(ui.value);
						}
					});
					$("#maxNodeSizeSlider_" + me.dbid).slider({
						range: "min",value: 0,min: 1,max: 50,step: 1,
						slide: function(event, ui) {
							$("#maxNodeSizeValue_" + me.dbid).html(ui.value);
						}
					});
					$("#minNodeSizeSlider_" + me.dbid).slider({
						range: "min",value: 0,min: 1,max: 50,step: 1,
						slide: function(event, ui) {
							$("#minNodeSizeValue_" + me.dbid).html(ui.value);
						}
					});
					$("#fontSizeSlider_" + me.dbid).slider({
						range: "min",value: 0,min: 1,max: 50,step: 1,
						slide: function(event, ui) {
							$("#fontSizeValue_" + me.dbid).html(ui.value);
						}
					});
					$("#sliderClusterNumber_" + me.dbid).slider({
						range: "min",value: 0,min: 1,max: 20,step: 1,
						slide: function(event, ui) {
							$("#sliderClusterNumberShow_" + me.dbid).html(ui.value);
						}
					});
					$("#applyNetworkSettingsButton_" + me.dbid).click(function() {
						me.applyVisualSettings();
					});
					$("#applyClusterNumber_" + me.dbid).click(function() {
						me.getNewClusters();
					});

					//HANDLERS FOR BUTTONS IN THE NETWORK TOOLBAR
					$("#downloadNetworkTool_" + me.dbid).click(function() {
						me.stopNetworkLayout();
						me.downloadNetwork("png");
					});
					$("#downloadNetworkToolSVG_" + me.dbid).click(function() {
						me.stopNetworkLayout();
						me.downloadNetwork("svg");
					});
					$("#step3-network-toolbar_" + me.dbid + " .selectNodesOption").click(function() {
						me.stopNetworkLayout();
						me.selectNodes($(this).attr("name"));
					});
					$("#step3-network-toolbar_" + me.dbid + " .reorderNodesOption").click(function() {
						me.stopNetworkLayout();
						me.reorderNodes($(this).attr("name"));
					});
					$("#step3-network-toolbar_" + me.dbid + " .configureNodesOption").click(function() {
						me.stopNetworkLayout();
						me.configureNodes($(this).attr("name"));
					});
					$("#resumeLayoutButton_" + me.dbid).click(function() {
						if ($(this).hasClass("resumeLayout")) {
							var visualOptions = me.getParent().getVisualOptions(this.database);
							if(visualOptions.pathwaysPositions !== undefined){
								Ext.MessageBox.confirm('Confirm', 'This option will invalidate current node positions,</br> Are you sure you want resume layout?', function(option){
									if(option==="yes"){
										$("#save-node-positions-check_" + me.dbid).attr("checked", false);
										$("#save-node-positions-check_" + me.dbid).prop("checked", false);
										$("#pre-auto-save-node-positions-check_" + me.dbid).fadeOut();

										$("#applyNetworkSettingsButton_" + me.dbid).click();
									}
								});
							}else{
								me.startNetworkLayout();
							}
						} else {
							me.stopNetworkLayout();
						}
					});
					$("#saveNodePositionsButton_" + me.dbid).click(function() {
						$("#save-node-positions-check_" + me.dbid).prop("checked", true);
						$("#pre-auto-save-node-positions-check_" + me.dbid).fadeIn();
						me.stopNetworkLayout();
						me.updateNodePositions(true);
						$("#step3-network-toolbar-message_" + me.dbid).addClass("successMessage").html("<i class='fa fa-check'></i> Saved").fadeIn(100, function(){
							setTimeout(function(){
								$("#step3-network-toolbar-message_" + me.dbid).fadeOut(100);
							}, 1500);
						});
					});
					$("#save-node-positions-check_" + me.dbid).click(function() {
						$("#pre-auto-save-node-positions-check_" + me.dbid).toggle($(this).is(":checked"));
					});
					$("#toggleTooltipsButton_" + me.dbid).click(function() {
						me.showTooltips = ! me.showTooltips;

						var message = 'Tooltips ' + (me.showTooltips ? ' enabled' : 'disabled');

						$("#step3-network-toolbar-message_" + me.dbid).addClass("successMessage").html("<i class='fa fa-check'></i> " + message).fadeIn(100, function(){
							setTimeout(function(){
								$("#step3-network-toolbar-message_" + me.dbid).fadeOut(100);
							}, 1500);
						});
					});
					$("#fullscreenSettingsPanelButton_" + me.dbid).click(function() {
						me.fullScreenNetwork();
					});

					/* Two ways out of full screen that are not the button, both of
					   which have to leave the panel and the button agreeing with
					   each other:

					     - the browser's own exit (Escape, or the notification bar
					       Chrome shows), which fires fullscreenchange and would
					       otherwise leave the panel still class-expanded over the
					       page with a button reading "Exit full screen";
					     - Escape when the native request was refused and only the
					       class is holding the panel open, where no fullscreenchange
					       ever comes.

					   Namespaced per database and detached first: a job reload
					   builds these views again, and document-level handlers from the
					   previous one would otherwise accumulate and act on panels that
					   no longer exist. */
					var fullScreenEvents = "fullscreenchange.paNet" + me.dbid +
						" webkitfullscreenchange.paNet" + me.dbid +
						" msfullscreenchange.paNet" + me.dbid;

					$(document).off(fullScreenEvents).on(fullScreenEvents, function() {
						if (!me.getFullScreenElement() && $("#networkview_" + me.dbid).hasClass("paNetExpanded")) {
							me.setFullScreenNetwork(false);
						}
					});

					$(document).off("keydown.paNet" + me.dbid).on("keydown.paNet" + me.dbid, function(event) {
						if (event.key === "Escape" && $("#networkview_" + me.dbid).hasClass("paNetExpanded")) {
							me.setFullScreenNetwork(false);
						}
					});
					$("#step3-network-toolbar-message_" + me.dbid).hover(function(){
						$(this).fadeOut(100);
					});
					$("#step3-network-toolbar_" + me.dbid + " .menuOption").click(function() {
						var isVisible = $(this).siblings(".menuBody").first().is(":visible");
						$("#step3-network-toolbar_" + me.dbid + " .menuBody").hide();
						$(this).siblings(".menuBody").first().toggle(!isVisible);
					});
					$("#step3-network-toolbar_" + me.dbid + " .submenuOption").click(function() {
						$(this).parent(".menuBody").first().toggle();
					});
					/* Tools is the pane the card opens on. Both panes were visible at
					   once before, side by side; one has to be chosen now, and it is
					   the one that does something - Details is a legend until a node
					   has been clicked, and clicking a node brings it forward
					   itself. */
					me.showRailPane("tools");

					$("#showNetworkSettingsPanelButton_" + me.dbid).click(function() {
						me.showRailPane("tools");
					});
					$("#networkview_" + me.dbid + " .paNetRailTab").click(function() {
						me.showRailPane($(this).attr("data-pane"));
					});
					$("#networkview_" + me.dbid + " .paNetRailHide").click(function() {
						$("#networkview_" + me.dbid).addClass("is-railHidden");
						me.resizeNetwork();
					});
					$("#reorderOptions_" + me.dbid + " span i").click(function() {
						var option = $("#reorderOptions_" + me.dbid + " h3:visible");

						if (option.attr("name").indexOf("-conf") === -1) {
							var value = Math.max(Number.parseInt(option.attr("value")) + ($(this).attr("name")==="less"?-1:1), 1);
							option.attr("value", value);

							me.reorderNodes(option.attr("name"), value);
						} else {
							// Keep the value in the range [-1, +1]
							var value = $(this).attr("name")==="less"?-1:1;
							option.attr("value", value);

							me.configureNodes(option.attr("name"), value);
						}
					});

					$("#networkview_" + me.dbid + " .hideOption").click(function() {
						$(this).parents(".lateralOptionsPanel").first().hide();
						me.network.refresh();
					});

					$("#backToClusterDetailsButton_" + me.dbid).click(function() {
						me.hidePathwayDetails();
					});

					//Add a resizer to network panel
					Ext.create('Ext.resizer.Resizer', {
						target: this,
						handles: 's',
						pinned:true,
						maxWidth:1900,
						minHeight: 700,
						dynamic: true,
						transparent:true,
						listeners: {
							beforeresize: function(resizer, width, height){
								resizer.prevHeight= height;
							},
							/* Only the canvas is sized here now, and it is addressed by
							   its real id.

							   Both of those were faults. The four ids in the list had
							   no database suffix - `#pathwayNetworkBox` where the
							   element is `pathwayNetworkBox_KEGG` - so every selector
							   matched nothing and dragging the handle resized
							   precisely one thing: the Ext panel's own frame, with
							   the graph inside it unchanged. And the three side
							   panels were in the list because floats had to be told
							   each other's heights; the grid stretches the rail to
							   the graph on its own, so telling it a height now is how
							   the two get out of step. */
							resize: function(resizer, width, height){
								var diff = height - resizer.prevHeight;
								var canvas = $('#pathwayNetworkBox_' + me.dbid);

								canvas.height(canvas.height() + diff);
								me.resizeNetwork();
							}
						}
					});

					initializeTooltips(".helpTip");
				}
			}

		});
		return this.component;
	};

	return this;
}
PA_Step3PathwayNetworkView.prototype = new View();

function PA_Step3PathwayNetworkTooltipView() {
	/**
	* About this view: this view (PA_Step3PathwayNetworkTooltipView) is used to visualize
	* a tooltip showing some information for pathways when hovering the nodes in the
	* pathways network
	* @implements Singleton
	**/
	if (arguments.callee._singletonInstance) {
		return arguments.callee._singletonInstance;
	}
	arguments.callee._singletonInstance = this;

	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step3PathwayNetworkTooltipView";
	this.featureView = null;

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	//TODO: DOCUMENTAR
	this.show = function(x,y, model, omicDataType, dataDistributionSummaries, visualOptions) {
		this.getComponent().showAtPos(x,y);
		if (this.featureView.getModel() !== model) {
			this.featureView.loadModel(model);
			this.featureView.updateObserver(omicDataType, dataDistributionSummaries, visualOptions);
		}
		return this;
	};

	//TODO: DOCUMENTAR
	this.hide = function(){
		this.getComponent().hide();
	};

	//TODO: DOCUMENTAR
	this.showPathwayDetails = function(){
		this.getParent().showPathwayDetails(this.featureView.getModel());
	};

	//TODO: DOCUMENTAR
	this.hidePathwayDetails = function(){
		this.getParent().hidePathwayDetails();
	};

	/**
	* This function generates the component (EXTJS) using the content of the model
	* @returns {Ext.ComponentView} The visual component
	*/
	this.initComponent = function() {
		var me = this;
		this.featureView = new PA_Step3PathwayDetailsView();
		this.featureView.setParent(me);

		this.component = Ext.create('Ext.tip.ToolTip', {
			target: "", id: "sigmaTooltip",
			style: "background:#fff; padding:2px 5px;",
			dismissDelay: 0, trackMouse: false,
			autoHeight: true, width: 270,
			items: [
				this.featureView.getComponent(),{
					xtype: "box", html:
					"  <div style='text-align: center;margin: 10px 0px;'>" +
					'     <a href="javascript:void(0)" class="button" id="step3TooltipMoreButton" style="float: none;"><i class="fa fa-search-plus"></i> Show details</a>'+
					'     <a href="javascript:void(0)" class="button" id="step3TooltipPaintButton" style="float: none; background-color:var(--pa-link);"><i class="fa fa-paint-brush"></i> Paint</a>'+
					"  </div>"
				}
			],
			showAtPos: function(x, y) {
				if (this.el == null) {
					this.show();
				}
				this.showAt([x,y + 10]);
			},
			listeners: {
				boxready: function() {
					$("#otherFeaturesLabel").click(function() {
						me.getComponent().hide();
					});
					$("#sigmaTooltip").mouseleave(function(){
						me.getComponent().hide();
					});

					$("#step3TooltipMoreButton").click(function(){
						me.showPathwayDetails();
					});
					$("#step3TooltipPaintButton").click(function(){
						me.getParent().paintSelectedPathway(me.featureView.getModel().getID());
					});
				},
				beforehide: function() {
					var me = this;
					if ($("#sigmaTooltip") .length > 0 && $("#sigmaTooltip").is(":hover")) {
						return false;
					}
				}
			}
		});

		return this.component;
	};

	return this;
}
PA_Step3PathwayNetworkTooltipView.prototype = new View();

function PA_Step3PathwayDetailsView() {
	/**
	* About this view: this view shows the details for a given pathway.
	* Some examples of details are: a table showing the # of matched features
	* for each omics type and the computed p-value, the main and secondary
	* classification and the line charts showing the trend for each omics type.
	* This view is used both in Step 3 and in Step 4
	**/
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step3PathwayDetailsView";

	/***********************************************************************
	* GETTER AND SETTERS
	***********************************************************************/

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* This function apply the settings that user can change
	* for the visual representation of the model (w/o reloading everything).
	* - STEP 1. Update the name of the pathway and the classification
	* - STEP 2. Fill the information about metagenes, 3 ALTERNATIVES
	*    - STEP 2.A IF WE ARE COLORING BY CLASSIFICATION JUST IGNORE
	*    - STEP 2.B IF WE DO NOT HAVE DATA FOR CURRENT PATHWAY
	*    - STEP 2.C UPDATE THE HEATMAP AND THE PLOT
	* - STEP 3. ENABLE SOME EVENT HANDLERS
	* @chainable
	* @returns {PA_Step3PathwayDetailsView}
	*/
	this.updateObserver = function(omicDataType, dataDistributionSummaries, visualOptions) {
		var me = this;
		var componentID = "#" + this.getComponent().getId();

		/*****************************************************************/
		/* STEP 1. Update the name of the pathway and the classification */
		/*****************************************************************/
		$(componentID + " .pathwayNameLabel h4").text(this.getModel().getName());
		/* Chips instead of a bulleted list: the two classification levels are
		   tags, not sentences, and a <ul> spent two full lines and bullet
		   glyphs saying so. Built with .text() per chip so a classification
		   name can never be read as markup. */
		var classificationChips = $("<div class='pa-details-chips'></div>");
		this.getModel().getClassification().split(";").forEach(function(levelName) {
			levelName = levelName.trim();
			if (levelName !== "") {
				classificationChips.append($("<span class='pa-details-chip'></span>").text(levelName));
			}
		});
		$(componentID + " .pathwayClassificationLabel")
			.empty()
			.append("<span class='pa-details-label'>Classification</span>")
			.append(classificationChips);

			/*******************************************************************/
			/* STEP 2. Fill the information about matched features and p-values*/
			/*******************************************************************/
			if(this.getParent().getName() !== "PA_Step3PathwayNetworkTooltipView"){
				var htmlCode = '<thead><tr><th></th><th title="Matched features (relevant)">Matched</th><th title="Global p-value">p-value</th><th></th></tr></thead><tbody>';
				var significanceValues = this.getModel().getSignificanceValues();
				var globalOmicPvalues = this.getModel().getGlobalOmicPvalues() || {};
				var jobView = this.getParent("PA_Step3JobView") || this.getParent("PA_Step4JobView");
				var conditionNames = (jobView !== null) ? (jobView.getModel().conditionNames || []) : [];
				
				var PA4View = this.getParent("PA_Step4PathwayView");
				var foundFeatures = (PA4View !== null) ? PA4View.getMatchedFeatures() : {};
				
				for (var omicName in significanceValues) {
					var globalP = (globalOmicPvalues[omicName] !== undefined) ? globalOmicPvalues[omicName] : significanceValues[omicName][0][2]; // Fallback to first condition if global not present
					var renderedGlobalP = (globalP > 0.001 || globalP === 0) ? parseFloat(globalP).toFixed(6) : parseFloat(globalP).toExponential(4);
					
					var omicID = omicName.replace(/ /g, "_");
					
					htmlCode += '<tr class="omic-row" data-omic="' + omicID + '"><td class="pa-details-omic">' + omicName + '</td><td class="pa-details-num">' + significanceValues[omicName][0][0] + ' (' + significanceValues[omicName][0][1] + ')</td><td class="pa-details-num">' + renderedGlobalP + '</td>' +
					            '<td class="pa-details-actions">' +
					            '<i class="fa fa-chevron-right expandConditions" title="Show per-condition p-values" data-omic="' + omicID + '"></i>' +
					            (! Ext.Object.isEmpty(foundFeatures[omicName]) ? '<i class="fa fa-plus-square-o expandMatched" title="Show matched features" data-id="' + omicID + '"></i>' : '') +
					            '</td></tr>';

					// Add per-condition rows (hidden by default). Styled by class,
					// not inline: an inline background is unreachable by dark.css.
					for (var c = 0; c < significanceValues[omicName].length; c++) {
						var condP = significanceValues[omicName][c][2];
						var renderedCondP = (condP > 0.001 || condP === 0) ? parseFloat(condP).toFixed(6) : parseFloat(condP).toExponential(4);
						var condName = conditionNames[c] || ("Condition " + (c+1));

						htmlCode += '<tr class="condition-row cond-row-' + omicID + '" style="display:none;">' +
						            '<td class="pa-details-cond">' + condName + '</td>' +
						            '<td class="pa-details-num">' + significanceValues[omicName][c][0] + ' (' + significanceValues[omicName][c][1] + ')</td>' +
						            '<td class="pa-details-num">' + renderedCondP + '</td><td></td></tr>';
					}
				}
				htmlCode+='</tbody>';
				$(componentID + " .pathwaySummaryTable").html('<table class="pa-details-table">'+ htmlCode + '</table>');

				var detailedHTMLcode = '';
				Object.keys(foundFeatures).forEach(function(omicName) {
					detailedHTMLcode += '<div id="matchedlist_' + omicName.replace(/ /g, "_") + '" class="pa-details-matchedlist" style="display: none;"><h5>Matched features: ' + omicName + '</h5>';

					if (! Ext.Object.isEmpty(foundFeatures[omicName])) {
						// Sort alphabetically
						var omicFeatures = foundFeatures[omicName];

						var sortKeys = Object.keys(omicFeatures);
						sortKeys.sort();

						var relevantTags = function(feature) {
							var tmpHTML = '';

							if (omicFeatures[feature].isRelevant) {
								tmpHTML += '<i class="featureNameLabelRelevant relevantFeature" title="Relevant feature"></i>';
							}

							if (omicFeatures[feature].isRelevantAssociation) {
								tmpHTML += '<i class="featureNameLabelRelevant relevantAssociationFeature" title="Relevant association"></i>';
							}

							return(tmpHTML);
						};

						detailedHTMLcode += '<ul>';

						sortKeys.forEach(function(feature) {
							detailedHTMLcode += '<li>' + feature + ' (' + Array.from(new Set(omicFeatures[feature].inputNames)).join(', ') + ')' +
								relevantTags(feature) + '</li>';
						});

						detailedHTMLcode += '</ul></div>';
					}
				});

				$(componentID + " .pathwaySummaryTable").append(detailedHTMLcode);

				$('i.expandMatched').click(function() {
					var el = $(this);
					var dataID = el.attr('data-id');

					el.toggleClass('fa-plus-square-o fa-minus-square-o');
					$('#matchedlist_' + dataID).toggle();
				});

				$('i.expandConditions').click(function() {
					var el = $(this);
					var omicID = el.attr('data-omic');
					el.toggleClass('fa-chevron-right fa-chevron-down');
					$('.cond-row-' + omicID).toggle();
				});
			}

			/****************************************************************/
			/* STEP 3. Fill the information about metagenes                 */
			/****************************************************************/
			var pathwayPlotwrappers = $(componentID + " .pathwayPlotwrappers");
			pathwayPlotwrappers.empty();

			//For each omics type
			for(var i in omicDataType){
				var metagenes = this.getModel().metagenes[omicDataType[i]];
				if(omicDataType[i] === "classification"){
					/****************************************************************/
					/* STEP 3.A IF WE ARE COLORING BY CLASSIFICAITON JUST IGNORE    */
					/****************************************************************/
					var pathwaySource = this.getModel().getSource();
					var thumbnail_suffix = (pathwaySource == undefined || pathwaySource == 'KEGG') ? '_thumb' : '_' + pathwaySource + '_thumb'
					/* The quotes around the url() argument have to be escaped, not
					   closed: written as url('/' + ... the leading string literal
					   ended early and the whole expression parsed as a chain of
					   divisions, handing jQuery a NaN. Colouring by classification
					   is the default, so the panel came up blank every time. Same
					   construction as the Step 4 thumbnails. */
					pathwayPlotwrappers.html('<div class="step3ChartWrapper" style="background-image: url(\'' + location.pathname + "kegg_data/" + this.getModel().getID() + thumbnail_suffix + '\')"></div>');
					break;
				}else if (metagenes === undefined){
					/****************************************************************/
					/* STEP 3.B IF WE DO NOT HAVE DATA FOR CURRENT PATHWAY          */
					/****************************************************************/
					pathwayPlotwrappers.append(
						"<h4 style='color: #D16949;font-size: 13px;margin: 0;'>" + omicDataType[i] + "</h4>"+
						"<b>No data for this pathway.</b>"
					);
				}else{
					/****************************************************************/
					/* STEP 3.C UPDATE THE HEATMAP AND THE PLOT                     */
					/****************************************************************/
					var divName = this.getComponent().getId() + "_" + omicDataType[i].replace(/ /g, "_").toLowerCase();
					pathwayPlotwrappers.append(
						"<div>"+
						"  <h4>" + omicDataType[i] + "</h4>"+
						"  <span class='tooltipDetailsSpan'><i class='fa fa-info-circle'></i> " + metagenes.length + " major trend" + (metagenes.length === 1 ? "" : "s") + " in this pathway.</span></br>"+
						"  <div class='twoOptionsButtonWrapper'>" +
						'      <a href="javascript:void(0)" class="button twoOptionsButton" name="heatmap-chart">Heatmap</a>'+
						'      <a href="javascript:void(0)" class="button twoOptionsButton selected" name="line-chart">Line chart</a>'+
						"  </div>" +
						"  <div class='step3-tooltip-plot-container' name='heatmap-chart'  style='display:none;'>" +
						/* +34px on top of the row height: that is the band the rotated
					   condition labels occupy under the x axis. Without it they
					   would come out of the 35px allowed per trend. */
					"    <div id='" + divName + "_heatmapcontainer' name='heatmap-chart' style='height:"+ (metagenes.length * 35 + 44 )+ "px;width: 230px;'></div>" +
						"  </div>" +
						"  <div class='step3-tooltip-plot-container selected' name='line-chart'>" +
						"    <div id='" + divName + "_plotcontainer' style='height:100px;width: 230px;'></div>" +
						"  </div>"+
						"</div>"
					);

					var heatmap = this.generateHeatmap(divName +  "_heatmapcontainer", omicDataType[i], metagenes, dataDistributionSummaries);
					this.generatePlot(divName + "_plotcontainer", omicDataType[i], metagenes, dataDistributionSummaries, heatmap);
				}
			}
			/****************************************************************/
			/* STEP 4. ENABLE SOME EVENT HANDLERS                           */
			/****************************************************************/
			$("#" + me.getComponent().getId() + " a.twoOptionsButton").click( function(){
				var parent = $(this).parent(".twoOptionsButtonWrapper");
				var target = $(this).attr("name").replace("show", "");
				$(this).siblings("a.twoOptionsButton.selected").removeClass("selected");
				$(this).addClass("selected");
				parent.siblings("div.step3-tooltip-plot-container.selected").removeClass("selected").toggle();
				parent.siblings("div.step3-tooltip-plot-container[name="+ target + "]").addClass("selected").toggle();
				/* The heatmap is 35px per trend, the line chart a flat 100px, so
				   the panel is a different height on either side of this toggle. */
				me.fitToContent();
			});

			this.fitToContent();

			return this;
		};

	/**
	* Size the box to the content it actually holds.
	*
	* The three branches above used to pin it to 200/120/230px whatever they had
	* just rendered. 230px is short of what a single omic needs (242px measured
	* on a one-line pathway name), and the box does not clip, so the tail of the
	* chart ran out of it and under the Show details / Paint row below. A second
	* omic, a name that wraps to two lines or the taller heatmap made the overlap
	* worse. Measure instead of guessing.
	* @chainable
	* @returns {PA_Step3PathwayDetailsView}
	*/
	this.fitToContent = function() {
			var component = this.getComponent(), el = component.getEl();
			var panel = (el != null) ? el.dom.querySelector(".mainInfoPanel") : null;
			if (panel !== null) {
				component.setHeight(panel.offsetHeight);
			}
			return this;
		};

	//TODO: DOCUMENTAR
	this.generateHeatmap = function (targetID, omicName, metagenes, dataDistributionSummaries) {
			var featureValues, x = 0, y = 0, maxX = -1, series = [], yAxisCat = [], serie;
			for (var i in metagenes) {
				//restart the x coordinate
				x = 0;
				//Get the values and the name for the new serie
				featureValues = metagenes[i].values.map(Number);
				serie = {name: "Trend " + (i + 1), data: []};
				//Add the name for the row (e.g. MagoHb or "miRNA my_mirnaid_1")
				yAxisCat.push("Trend " + (i + 1) + "#Cluster " + metagenes[i].cluster);

				/* Coloured against the METAGENES' own range, not the omic's.

				   A metagene is a trend -- a component summarising how a
				   cluster of features moves -- and it is centred on zero, so it
				   goes negative whatever the omic did. Colouring it with the
				   omic's distribution asks a scale built for one quantity to
				   describe another: on a real job here the omic ran 0.79..1.41
				   while its metagenes reached +/-9.4, eight times outside the
				   scale in both directions.

				   getColor's outlier term then runs far past 1 and drives
				   channels out of range. Measured on the live server, this line
				   produced "rgb(0, 0,-2744)" and "rgb(255, 255,-410)" -- not
				   colours. Chrome clamped the second to yellow and rejected the
				   first outright, painting it black, so the trend rows showed
				   two arbitrary colours that meant nothing.

				   Their own min/max crosses zero, so paColourRange returns a
				   symmetric range and the diverging blue-white-red scale reads
				   the way it is supposed to: blue for down, red for up, white
				   for no change. */
				var limits = paMetageneLimits(metagenes);


				for (var j in featureValues) {
					if (typeof visualOptions != "undefined") {

					if (visualOptions.colorScale) {
						var colorGet = getColor(limits, featureValues[j], visualOptions.colorScale)

					}
					} else {
						var colorGet = getColor(limits, featureValues[j], "bwr")
					}
					serie.data.push({
						x: x, y: y,
						value: featureValues[j],
						color : colorGet
					});
					x++;
					maxX = Math.max(maxX, x);
				}
				series.push(serie);
				y++;
			}

			/* Condition names instead of "Timepoint n" placeholders - see
			 * paConditionAxis(). The header is looked up per omic because each
			 * metagene chart plots exactly one omic. */
			var xAxisConfig = paConditionAxis(maxX, paOmicHeaders(paJobModel(this), omicName), {maxChars: 9});
			var omicHeaderPD = xAxisConfig.categories;

			var replaceSymbols = {
				"*": '<i class="relevantFeature"></i>',
				"^": '<i class="relevantAssociationFeature"></i>'
			};

			var heatmap = new Highcharts.Chart({
				chart: {type: 'heatmap', renderTo: targetID},
				title: null, legend: {enabled: false}, credits: {enabled: false},
				tooltip: {
					borderColor: "#333",
					formatter: function () {
						var title = this.point.series.name.split("#");
						title[1] = (title.length > 1) ? title[1] : "";
						/* Name the column in the tooltip too: the axis label is
						 * length-capped, this is where the full name is readable. */
						if (omicHeaderPD[this.point.x] !== undefined) {
							title[0] = title[0] + " [" + omicHeaderPD[this.point.x] + "]";
						}
						return "<b>" + title[0].replace(/[\*\^]/g, function(c) { return replaceSymbols[c]; }) + "</b><br/>" + "<i class='tooltipInputName'>" + title[1] + "</i>" + (this.point.value === null ? "No data" : this.point.value);
					},
					useHTML: true
				},
				xAxis: xAxisConfig,
				yAxis: {
					categories: yAxisCat, title: null, width: 100,
					labels: {
						formatter: function () {
							var title = this.value.split("#");
							title[1] = (title.length > 1) ? title[1] : "No data";
							return paRowLabel(title[0], title[1], {width: 55, maxChars: 12});
						},
						style: {fontSize: "9px"}, useHTML: true
					}
				},
				series: series,
				plotOptions: {
					heatmap: {borderColor: "#000000",borderWidth: 0.5},
					series: {
						point: {
							events: {
								mouseOver: function() {
									var plot = $("#" + this.series.chart.renderTo.id.replace("heatmap", "plot")).highcharts();
									for (var i in plot.series) {
										plot.series[i].setVisible(this.series.name.split("#")[0] === plot.series[i].name);
									}
								},
								mouseOut: function() {
									var plot = $("#" + this.series.chart.renderTo.id.replace("heatmap", "plot")).highcharts();
									for (var i in plot.series) {
										plot.series[i].setVisible(true);
									}
								}
							}
						}
					}
				}
			});

			return heatmap;
		};

	//TODO: DOCUMENTAR
	this.generatePlot = function (targetID, omicName, metagenes, dataDistributionSummaries, heatmap) {
			var series = [],
			scaledValues, min, max,
			maxVal = -100000000,
			minVal = 100000000,
			tmpValue,
			yAxis = [],
			yAxisItem;


			//1.FILL THE STORE DATA [{name:"timepoint 1", "Gene Expression": -0.8, "Proteomics":-1.2,... },{name:"timepoint2", ...}]
			for (var i in metagenes) {
				scaledValues = [];
				featureValues = metagenes[i].values.map(Number);

				var limits = getMinMax(dataDistributionSummaries[omicName], 'p10p90');
				for (var j in featureValues) {
					//SCALE THE VALUE
					tmpValue = scaleValue(featureValues[j], limits.min, limits.max);
					tmpValue = featureValues[j];
					//UPDATE MIN MAX (TO ADJUST THE AXIS)
					maxVal = Math.max(tmpValue, maxVal);
					minVal = Math.min(tmpValue, minVal);
					//ADD THE VALUE (CUSTOM MARKER IF OUTLIER)
					scaledValues.push({
						y: tmpValue,
						marker: ((tmpValue > 1 || tmpValue < -1) ? {
							fillColor: '#ff6e00'
						} : null)
					});
				}

				var parentAux = this.getParent("PA_Step3PathwayNetworkView");
				if(parentAux === null){
					parentAux = this.getParent();
				}

				series.push({
					name: "Cluster " + metagenes[i].cluster,
					type: 'spline',
					color: parentAux.getClusterColor(metagenes[i].cluster),
					startOnTick: false,
					endOnTick: false,
					data: scaledValues,
					yAxis: 0
				});
			}

			maxVal = Math.ceil(Math.max(maxVal, 1));
			minVal = Math.floor(Math.min(minVal, -1));

			/* The three reference lines mark the +/-1 band that turns a point's
			   marker orange. Their labels used to be unconditional, so on a
			   pathway whose metagene range is wide (+/-6, +/-10) all three
			   landed within a few pixels of each other in a 100px chart and
			   piled up into an unreadable smudge on the right edge. Draw the
			   lines either way; label the +/-1 pair only when the text has room
			   to clear the zero label. */
			var referenceLine = function(value, labelled) {
				var line = {color: '#dedede', value: value, width: 1};
				if (labelled) {
					line.label = {
						text: String(value), align: 'right', x: -3, y: -2,
						style: {color: 'gray', fontSize: '9px'}
					};
				}
				return line;
			};

			var plot = new Highcharts.Chart({
				chart: {renderTo: targetID},
				title: null,
				credits: {enabled: false},
				xAxis: [{labels: {enabled: false}}],
				yAxis: {
					title: null,
					min: minVal,
					max: maxVal,
					plotLines: [
						referenceLine(-1, true),
						referenceLine(0, true),
						referenceLine(1, true)
					]},
					series: series,
					legend: {
						itemStyle: {fontSize: "9px",fontWeight: 'lighter'},
						margin: 5,
						padding: 5
					},
					tooltip: {enabled: false},
					plotOptions: {
						series: {
							point: {
								events: {
									mouseOver: function() {
										heatmap.tooltip.refresh(heatmap.series[heatmap.series.length - this.series.index - 1].data[this.x]);
									}
								}
							}
						}
					}
				}
			);

			plot.yAxis[0].setExtremes(minVal, maxVal);

			/* Now that the axis has real pixel dimensions, drop the +/-1 labels
			   if they would collide. 11px is the smallest gap at which the 9px
			   label text still clears its neighbour. */
			var yAxis0 = plot.yAxis[0];
			if (Math.abs(yAxis0.toPixels(0) - yAxis0.toPixels(1)) < 11) {
				yAxis0.update({
					plotLines: [
						referenceLine(-1, false),
						referenceLine(0, true),
						referenceLine(1, false)
					]
				}, true);
			}

			return plot;
		};

	/**
	* This function generates the component (EXTJS) using the content of the model
	* @param {String}  renderTo  the ID for the DOM element where this component should be rendered
	* @returns {Ext.ComponentView} The visual component
	*/
	this.initComponent = function(renderTo) {
			var me = this;
			this.component = Ext.widget({
				xtype: "box", renderTo: renderTo, html:
				"<div class='mainInfoPanel' >" +
				"  <div class='pathwayNameLabel' style='padding:2px 0px'><h4 style='font-size: 13px;margin: 0;'></h4></div>" +
				"  <div class='pathwayClassificationLabel' style='padding:2px 0px'></div>" +
				"  <div class='pathwaySummaryTable'></div>" +
				"  <div class='pathwayPlotwrappers'></div>" +
				"</div>",
				listeners: {
					beforedestroy: function() {
						me.getModel().deleteObserver(me);
					}
				}
			});

			return this.component;
		};

	return this;
}
PA_Step3PathwayDetailsView.prototype = new View();

function PA_Step3PathwayTableView() {
	/**
	* About this view: TODO: DOCUMENTAR
	**/
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step3PathwayTableView";
	this.tableData = null;

	/***********************************************************************
	* GETTER AND SETTERS
	***********************************************************************/
	//TODO: DOCUMENTAR
	this.loadModel= function(model){
		var me = this;

		/********************************************************/
		/* STEP 1. LOAD THE MODEL                               */
		/********************************************************/
		if (this.model !== null) {
			this.model.deleteObserver(this);
		}
		this.model = model;
		this.model.addObserver(this);

		/********************************************************/
		/* STEP 2. GENERATE THE ROWS CONTENT                    */
		/********************************************************/
		this.tableData = [];

		var pathways = this.model.getPathways();
		var pathwayData, pathwayModel, omicName, significanceValues;
		var defaultCombinedPvaluesMethod = me.getParent().visualOptions.selectedCombinedMethod;

		var significativePathways = 0;
		/*
			Current browsers have a limit on the amount of space available for
			sessionStorage. In jobs with multiple omics the "omicsValue" property can
			be large enough to produce a JSON string too big to be saved.

			As an alternative be keep a list of identifiers already parsed.
						*/
		var getIdentifiersFromMatched = function(matchedIds) {
			var parsedIDs = me.model.getOmicsValuesID();
			var allIdentifiers = new Set([]);

			matchedIds.map(function(matchID) {
				if (parsedIDs[matchID]) {
					allIdentifiers.add(parsedIDs[matchID]);
				}
				else if (me.model.omicsValues[matchID]) {
					allIdentifiers.add(me.model.omicsValues[matchID].name);

					me.model.omicsValues[matchID].omicsValues.map(function(omicValue) {
						allIdentifiers.add(omicValue.inputName);
						allIdentifiers.add(omicValue.originalName);
					});
				}
			});

			return(Array.from(allIdentifiers).join('|'));
		};

		let classificationDataReactome = this.getParent().getClassificationData("Reactome");
		let reactomeClidren = {};
		let classes = this.model.getClasses();

		// ADD Reactome class enrichment part: PaintOmics 4
		if (this.model.databases.includes("Reactome")) {
				// creat a dictionary with class name as key and pathway name as children.
				for (className in classificationDataReactome) {
					for (classDetail in classificationDataReactome[className].children) {
						if (typeof reactomeClidren[className] == "undefined") {
							reactomeClidren[className] = [];
						}
 						reactomeClidren[className] =  [...reactomeClidren[className], ...classificationDataReactome[className].children[classDetail].children];
					}
				}
		}

		for (var i in pathways) {
			pathwayModel = pathways[i];

			//NOTE: IGNORE Metabolic pathways (HUGE PATHWAY)
			if (pathwayModel.getID() === this.getModel().getOrganism() + "01100") {
				continue;
			}

			pathwayData = {
				// selected: pathwayModel.isSelected(),
				pathwayID: pathwayModel.getID(),
				title: pathwayModel.getName(),
				matchedGenes: pathwayModel.getMatchedGenes().length,
				matchedCompounds: pathwayModel.getMatchedCompounds().length,
				// combinedSignificancePvalues: pathwayModel.getCombinedSignificanceValues(),
				mainCategory: pathwayModel.getClassification().split(";")[0],
				secCategory: pathwayModel.getClassification().split(";")[1],
				visible: pathwayModel.isVisible(),
				source: pathwayModel.getSource(),
				identifiers: getIdentifiersFromMatched(pathwayModel.getMatchedGenes().concat(pathwayModel.getMatchedCompounds()))
			};

			significanceValues = pathwayModel.getSignificanceValues();
			for (var j in significanceValues) {
				omicName = "-" + j.toLowerCase().replace(/ /g, "-");
				
				// Keep global backward compatibility
				pathwayData['totalMatched' + omicName] = significanceValues[j][0][0];
				pathwayData['totalRelevantMatched' + omicName] = significanceValues[j][0][1];
				pathwayData['pValue' + omicName] = significanceValues[j][0][2];
				
				// Multi-condition support
				for (var c = 0; c < significanceValues[j].length; c++) {
					pathwayData['totalMatched_c' + c + omicName] = significanceValues[j][c][0];
					pathwayData['totalRelevantMatched_c' + c + omicName] = significanceValues[j][c][1];
					pathwayData['pValue_c' + c + omicName] = significanceValues[j][c][2];
				}
			}

			var globalOmicPvalues = pathwayModel.getGlobalOmicPvalues();
			if (globalOmicPvalues) {
				for (var j in globalOmicPvalues) {
					omicName = "-" + j.toLowerCase().replace(/ /g, "-");
					if (globalOmicPvalues[j] !== undefined) {
					    pathwayData['pValue' + omicName] = globalOmicPvalues[j];
					}
				}
			}

			adjustedSignificanceValues = pathwayModel.getAdjustedSignificanceValues();
			for (var j in adjustedSignificanceValues) {
				omicName = "-" + j.toLowerCase().replace(/ /g, "-");

				for (var k in adjustedSignificanceValues[j]) {
					pathwayData["adjpval" + k + omicName] = adjustedSignificanceValues[j][k];
				}
			}

			combinedSignificanceValues = pathwayModel.getCombinedSignificanceValues();
			var totalGlobalPvalues = pathwayModel.getTotalGlobalPvalues() || {};
			for (var m in combinedSignificanceValues) {
				var val = totalGlobalPvalues[m];
				if (val === undefined || val === null) {
					val = combinedSignificanceValues[m];
					if (Array.isArray(val)) {
						val = val[0];
					}
				}
				pathwayData["combinedSignificancePvalue" + m] = val;
			}

			adjustedCombinedSignificanceValues = pathwayModel.getAdjustedCombinedSignificanceValues();
			for (var m in adjustedCombinedSignificanceValues) {
				for (var k in adjustedCombinedSignificanceValues[m]) {
					var adjVal = adjustedCombinedSignificanceValues[m][k];
					// Multi-condition jobs send a list (one adjusted p-value per condition);
					// expose each as adjustedCombinedSignificancePvalue<m><k>_c<n>, and also
					// keep the legacy scalar key (= condition 0) for back-compat with existing
					// table column definitions.
					if (Array.isArray(adjVal)) {
						pathwayData["adjustedCombinedSignificancePvalue" + m + k] = adjVal.length > 0 ? adjVal[0] : null;
						for (var c = 0; c < adjVal.length; c++) {
							pathwayData["adjustedCombinedSignificancePvalue" + m + k + "_c" + c] = adjVal[c];
						}
					} else {
						pathwayData["adjustedCombinedSignificancePvalue" + m + k] = adjVal;
					}
				}
			}
			// ADD Reactome class enrichment
			if (this.model.databases.includes("Reactome")) {
				let foundKey = false
				for (className in reactomeClidren) {
					foundKey = reactomeClidren[className].includes(pathwayData.pathwayID);
					if (foundKey) {
						break;
					}
				}

				if (foundKey) {
					for (reactomeClass in classes) {
						if (classes[reactomeClass].ID.toLowerCase().replace(/\s/g,'_') == className) {
							let significanceValuesCombine = classes[reactomeClass].combinedSignificancePvalues
							for (let m in significanceValuesCombine) {
								// Multi-condition jobs hold one value per condition here, as
								// they do for the combined p-value above. Assigning the array
								// straight into the cell rendered it as "0.5775,0.6226,0.7325,..."
								// in a single column. Collapse to the first condition to match
								// how the combined column behaves, and expose each condition
								// under its own key for anyone rendering them separately.
								let classValue = significanceValuesCombine[m];
								if (Array.isArray(classValue)) {
									for (let c = 0; c < classValue.length; c++) {
										pathwayData["classSignificanePvalue" + m + "_c" + c] = classValue[c];
									}
									classValue = classValue.length > 0 ? classValue[0] : '';
								}
								pathwayData["classSignificanePvalue" + m] = classValue;
							}
							break;
						} else {
							for (let m in combinedSignificanceValues) {
								pathwayData["classSignificanePvalue" + m] = '';
							}
						}
					}
				} else {
					for (let m in combinedSignificanceValues) {
						pathwayData["classSignificanePvalue" + m] = '';
					}
				}
			}



			this.tableData.push(pathwayData);

			significativePathways += (combinedSignificanceValues[defaultCombinedPvaluesMethod] <= 0.05) ? 1 : 0;
		}
	};

	/*********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	//TODO: DOCUMENTAR
	this.updateObserver = function() {
		var me = this;
		var defaultCombinedPvaluesMethod = me.getParent().visualOptions.selectedCombinedMethod;
		var selectedAdjustedMethod = me.getParent().getVisualOptions().selectedAdjustedMethod;

		/*STEP 3.1 GENERATE THE COLUMNS AND THE ROW MODEL*/
		var columns = [ //DEFINE FIXED COLUMNS
			{
				xtype: 'customactioncolumn',
				text: "Paint",
				menuDisabled: true,
				width: 55,
				items: [{
					icon: "fa-paint-brush-o",
					text: "",
					tooltip: 'Paint this pathway',
					style: "font-size: 20px;",
					handler: function(grid, rowIndex, colIndex) {
						me.getParent().paintSelectedPathway(grid.getStore().getAt(rowIndex).get('pathwayID'));
					}
				}]
				// }, {
				// 	xtype: 'customcheckcolumn',
				// 	header: 'Select',
				// 	dataIndex: 'selected',
				// 	width: 55,
				// 	menuDisabled: true,
				// 	listeners: {
				// 		checkchange: {
				// 			scope: gridPanel,
				// 			fn: function(elem, rowIndex) {
				// 				var record = this.getStore().getAt(rowIndex);
				//
				// 				var model = me.getModel().getPathway(record.get("pathwayID"));
				// 				model.setSelected(!model.isSelected());
				//
				// 				this.getView().select(rowIndex);
				// 				this.getStore().sort();
				// 			}
				// 		}
				// 	}
			}, {
				text: 'ID',
				dataIndex: 'pathwayID',
				hidden: true
			},
			((me.model.getDatabases().length < 2) ? {text: '', width: 0} : {
				text: '', dataIndex: 'sourcedb',
				filterable: true, width:30, resizable: false,
				renderer: function(value, metadata, record) {
					var sourcedb = record.get("source");
					/* 8px of top padding centred the 24px badge in the 41px row,
					   but nothing else in the row is centred in the row: every
					   text cell is top-padded 5px, so its 15px line sits with
					   its middle 7.5px higher. The badge was the only thing on
					   its own centre line, and against 877 rows of text it read
					   as every badge sitting low. Zero here puts the badge's
					   middle on the text's middle. */
					metadata.style = "height: 40px; padding: 0 3px;width: 40px;";
					metadata.tdAttr = 'data-qtip="' + "<b>Database</b><br>" + sourcedb + '"';
					return '<i class="classificationNameBox" style="' + $('#icon_' + sourcedb).attr('style') + ';line-height: 21px;">' + sourcedb.charAt(0) + '</i>';
				}
			}),
			{
				text: 'Pathway name', dataIndex: 'title', filterable: true, flex: 1,
				/* The pathway name is the identifier for the row, and the long
				   Reactome ones ("Regulation of Insulin-like Growth Factor...")
				   do not fit any column width this table can afford. Truncated
				   on screen but recoverable on hover, rather than simply lost. */
				renderer: truncatableTextRenderer,
				/* flex alone is not enough here. This grid declares 52 leaf
				   columns - one per omic per statistic - and hides most of them
				   when a job carries more than five omics. Whatever ExtJS does
				   with the flex share across that many hidden siblings, it stops
				   handing this column anything: measured on a six-omic job it came
				   out at 40px, the framework's default column minimum, while 500px
				   of the grid sat unused. 40px is two characters and an ellipsis,
				   so the column that names the row became the only unreadable one
				   in the table.

				   A real minimum is what survives that arithmetic. 220px fits the
				   median KEGG name outright and leaves the long Reactome ones
				   recoverable on hover, and when the omic columns are expanded the
				   grid scrolls sideways rather than crushing this one. */
				minWidth: 220
			},{
				text: '', dataIndex: 'classification',
				filterable: true, width:10, resizable: false,
				renderer: function(value, metadata, record) {
					metadata.style = "height: 40px; padding: 0; width: 10px; background-color:"+me.getParent().getClassificationColor(record.get("mainCategory").toLowerCase().replace(/ /g, "_"), [])+";";
					metadata.tdAttr = 'data-qtip="' + "<b>Classification</b><br>" + record.get("mainCategory") + "<br>" + record.get("secCategory") + '"';
					return '';
				}
			}, {
				text: 'Features',
				columns: [{
					text: 'Unique</br>genes', cls:"header-90deg",
					sortable: true,
					align: "center", width: 50,
					filter: {type: 'numeric'},
					dataIndex: 'matchedGenes'
				}, {
					text: 'Unique</br>metabol.', cls:"header-90deg",
					sortable: true,
					/* 50px ellipsised the label to "Unique metabol" - the one header
					   in this grid that still did not fit its own column. */
					align: "center", width: 58,
					filter: {type: 'numeric'},
					dataIndex: 'matchedCompounds'
				}]
			}
		];
		//DEFINE FIXED FIELDS FOR THE MODEL
		var rowModel = {
			// selected: {name: "selected", defaultValue: false},
			pathwayID: {name: "pathwayID"},
			title: {name: "title", defaultValue: ''},
			matchedGenes: {name: "matchedGenes", defaultValue: '0'},
			matchedCompounds: {name: "matchedCompounds", defaultValue: '0'},
			//combinedSignificancePvalue: {name: "combinedSignificancePvalue", defaultValue: ''},
			mainCategory: {name: "mainCategory",defaultValue: ''},
			secCategory: {name: "secCategory",defaultValue: ''},
			visible: {name: "visible", defaultValue: true},
			source: {name: "source", defaultValue: "KEGG"},
			identifiers: {name: "identifiers", defaultValue: ''}
		};

		//CALL THE PREVIOUS FUNCTION ADDING THE INFORMATION FOR GENE BASED OMIC AND COMPOUND BASED OMICS
		var secondaryColumns = [];
		var modelPathways = this.model.getPathways();
		var hidden = (Object.keys(this.model.getGeneBasedInputOmics()).length  + Object.keys(this.model.getCompoundBasedInputOmics()).length  > 5 || $("#mainViewCenterPanel").hasClass("mobileMode"))  ;

		var adjustedPvalueMethods = this.model.getMultiplePvaluesMethods();
		var combinedPvaluesMethods = this.model.getCombinedPvaluesMethods();

		this.generateColumns(this.model.getGeneBasedInputOmics(), secondaryColumns, rowModel, hidden, adjustedPvalueMethods, combinedPvaluesMethods);
		this.generateColumns(this.model.getCompoundBasedInputOmics(), secondaryColumns, rowModel, hidden, adjustedPvalueMethods, combinedPvaluesMethods);

		//ADD AN ADDITIONAL COLUMN WITH THE COMBINED pValue IF #OMIC > 1
		if (secondaryColumns.length > 1) {

			var rendererMethod = function(value, metadata, record) {
				var myToolTipText = "<b style='display:block; width:200px'>" + metadata.column.text + "</b>";
				metadata.style = "height: 40px; font-size:12px;"
				if (value === '') {
					myToolTipText = myToolTipText + "<i>No data for this pathway</i>";
					metadata.tdAttr = 'data-qtip="' + myToolTipText + '"';
					metadata.style += " background-color:var(--pa-cell-empty,#D4D4D4);";
					return "-";
				}

				if (Array.isArray(value)) {
					value = value[0];
				}
				
				var numericValue = parseFloat(value);

				if(numericValue <= 0.065){
					var color = Math.round(161 * (numericValue/0.065));
					var tint = 172 + Math.round(color * 0.32);
				metadata.style += "background-color:rgb(255, " + tint + "," + tint + "); color:#9B1C1C;";
				}

				//RENDER THE VALUE -> IF LESS THAN 0.05, USE SCIENTIFIC NOTATION
				return (numericValue > 0.001 || numericValue === 0) ? numericValue.toFixed(5) : numericValue.toExponential(4);
			};

			combinedPvaluesMethods.forEach(function(m) {

				rowModel['combinedSignificancePvalue' + m] = {
					name: 'combinedSignificancePvalue' + m,
					defaultValue: "-"
				};

				secondaryColumns.push({
					text: 'Combined </br>pValue</br>(' + m + ')', cls:"header-45deg",
					dataIndex: 'combinedSignificancePvalue' + m,
					sortable: true, filter: {type: 'numeric'}, align: "center",
					minWidth: 100, flex:1, height:75, hidden: (m != defaultCombinedPvaluesMethod),
					renderer: rendererMethod
				});

				// The adjusted combined values should have the same methods
				adjustedPvalueMethods.forEach(function(fdr) {

					rowModel['adjustedCombinedSignificancePvalue' + m + fdr] = {
						name: 'adjustedCombinedSignificancePvalue' + m + fdr,
						defaultValue: "-"
					};

					secondaryColumns.push({
						text: 'Combined </br>pValue</br>(' + m + ')</br>[' + fdr + ']', cls:"header-45deg",
						dataIndex: 'adjustedCombinedSignificancePvalue' + m + fdr,
						sortable: true, filter: {type: 'numeric'}, align: "center",
						minWidth: 100, flex:1, height:75, hidden: (selectedAdjustedMethod != m),
						renderer: rendererMethod
					});
				});
			});

			if (this.model.databases.includes("Reactome")) {
				combinedPvaluesMethods.forEach(function(m) {

				rowModel['classSignificanePvalue' + m] = {
					name: 'classSignificanePvalue' + m,
					defaultValue: "-"
				};

				secondaryColumns.push({
					text: 'Reactome Class</br>pValue</br>(' + m + ')', cls:"header-45deg",
					dataIndex: 'classSignificanePvalue' + m,
					sortable: true, filter: {type: 'numeric'}, align: "center",
					minWidth: 100, flex:1, height:75, hidden: (m != defaultCombinedPvaluesMethod),
					renderer: rendererMethod
				});
			});

			}

		}
		//GROUP ALL COLUMNS INTO A NEW COLUMN 'Significance tests'
		columns.push({text: 'Significance tests', columns: secondaryColumns});

		columns.push({
			/* Centred, because its contents are. An action column renders its
			   items centred in the cell, and with no `align` here the header
			   defaulted to left: "External links" started at x=1383 while every
			   "KEGG PubMed" pair below it started at 1407.5, so the only column
			   in the grid whose label and values disagreed about their own axis
			   was the one at the far right, with nothing after it to line up
			   with instead. Every other value column here is already
			   `align: "center"`. */
			xtype: 'customactioncolumn', align: "center",
			text: "External links", width: 150,
			items: [{
				icon: "fa-external-link",
				text: function(v, meta, record, rowIdx, colIdx, store, view) {
					return store.getAt(rowIdx).get('source');
				},
				tooltip: function(v, meta, record, rowIdx, colIdx, store, view) {
					return 'Find pathway in ' + store.getAt(rowIdx).get('source') + ' Database';
				},
				handler: function(grid, rowIndex, colIndex) {
					var record = grid.getStore().getAt(rowIndex);
					var term = record.get('pathwayID');
					var db = record.get('source');
					var db_link = {
						"KEGG": "http://www.genome.jp/dbget-bin/www_bget?pathway+%term%",
						"MapMan": "http://www.gomapman.org/search/gmm/%term%?entity=pathway",
						"Reactome": "https://reactome.org/content/query?q=%term%",
						"OmniPath": "https://omnipathdb.org/annotations?resources=%source%&format=json"
					};

					/* OmniPath pathway IDs are slugs this installer mints, not accessions
					   any external site knows, so the pathway is looked up by its name. */
					if (db === "OmniPath") {
						var classification = String(record.get('classification') || '');
						var resource = classification.indexOf('NetPath') !== -1 ? 'NetPath' : 'SIGNOR';
						window.open("https://omnipathdb.org/annotations?resources=" + resource +
							"&format=json", '_blank');
						return;
					}

					/* A source with no entry here used to throw on the missing key and
					   leave the button silently dead. */
					if (!db_link[db]) {
						console.warn("No external database link configured for source: " + db);
						return;
					}

					window.open(db_link[db].replace("%term%", term), '_blank');
				}
			}, {
				icon: "fa-search", text: "PubMed",
				tooltip: 'Find related publications',
				handler: function(grid, rowIndex, colIndex) {
					var term = grid.getStore().getAt(rowIndex).get('title');
					window.open("http://www.ncbi.nlm.nih.gov/pubmed/?term=" + term.replace(" ", "%20"), '_blank');
				}
			}]
		});

		var tableStore = Ext.create('Ext.data.Store', {
			fields: Object.values(rowModel),
			data: this.tableData,
			sorters: [{
				property: (secondaryColumns.length > 1) ? 'combinedSignificancePvalue' + defaultCombinedPvaluesMethod : secondaryColumns[0].dataIndex,
				direction: 'ASC'
			}]
		});

		var gridPanel = this.getComponent().queryById("pathwaysGridPanel");

		gridPanel.initialConfig.columns = columns;
		gridPanel.reconfigure(tableStore, columns);

		// Multi-condition column expansion handler
		gridPanel.el.on('click', function(e, t) {
			var el = Ext.get(t);
			if (el.hasCls('expandOmicConditions')) {
				var omicName = el.getAttribute('data-omic');
				var isExpanded = el.hasCls('fa-chevron-down');
				
				// Toggle icon
				el.toggleCls('fa-chevron-right');
				el.toggleCls('fa-chevron-down');
				
				// Toggle columns
				gridPanel.headerCt.getGridColumns().forEach(function(column) {
					if (column.cls && column.cls.indexOf('condition-column-' + omicName) !== -1) {
						if (isExpanded) column.hide(); else column.show();
					}
				});
			}
		}, null, {delegate: '.expandOmicConditions'});

		// Make sure that the updated adjusted p-values layer exists
		// when at least one database is filtered.


		this.updateVisiblePathways();
	};

	this.getAssociatedPathways = function(onlyVisible = false) {
		var associatedPathways = {};

		/* Flatten the dictionary */
		$.each(this.getParent().getIndexedPathways(), function(db, pathways) {
			associatedPathways = $.extend(associatedPathways, pathways);
		});

		/* Filter by visibility */
		if (onlyVisible) {
			var visiblePathways = {};

			for (var pathwayID in associatedPathways) {
				if (associatedPathways[pathwayID].visible == true) {
					visiblePathways[pathwayID] = associatedPathways[pathwayID];
				}
			}

			associatedPathways = visiblePathways;
		}

		return(associatedPathways);
	};

	//TODO: DOCUMENTAR
	this.updateVisiblePathways = function(loadRemote=false){
		var store = this.getComponent().queryById("pathwaysGridPanel").getStore();
		var indexedPathways = this.getAssociatedPathways();
		var parent = this.getParent();
		var visualOptions = parent.getVisualOptions();
		var adjustedPvalueMethods = this.model.getMultiplePvaluesMethods();

		var filterBy = function(elem){
			return indexedPathways[elem.get("pathwayID")].isVisible();
		};

		store.filterBy(filterBy);

		// First load: update the grid contained p-values
		this.updatePvaluesFromStore();

		if (adjustedPvalueMethods !== null) {
			/*
				Check if any database is filtered. It that is the case we retrieve the new
				p-values from server.

				If not filtered (or no longer filtered) remove the layer of "false" adjusted
				p-values to restore the original, unless there are custom Stouffer weights
				in which case we retrieve the new ones.
			*/
			var isFiltered = Object.values(parent.isFiltered).includes(true);
			var customStouffer = ! Ext.Object.isEmpty(visualOptions.stoufferWeights);
			var retrieveNewValues = false;

			if (loadRemote) {
				if (isFiltered) {
					retrieveNewValues = true;
				} else {
					/*
						Unfiltered data: remove options and update grid.
					*/
					this.model.getDatabases().forEach(function(db) {
						delete visualOptions[db].adjustedPvalues;
					});

					this.updatePvaluesFromStore();

					if (customStouffer) {
						var visiblePathways = Object.keys(this.getAssociatedPathways(true));

						console.log("Unfiltered pathways and custom Stouffer: removing old visualOptions and retrieving adjusted Stouffer.");

						parent.getController().step3GetUpdatedPvalues(this, this.getPvaluesFromStore(), visualOptions.stoufferWeights, visiblePathways);
					} else {
						console.log("Unfiltered pathways: removing old visualOptions and updating the table.");

						parent.getController().updateStoredApplicationData("visualOptions", visualOptions);
					}
				}
			} else {
				/*
					If we are first loading from session, make sure that if filtered the layer exists
					in the visual options or retrieve it.
				*/
				var layerAdjusted = ! Ext.Object.isEmpty(visualOptions[this.model.getDatabases()[0]].adjustedPvalues);
				var layerStouffer = ! Ext.Object.isEmpty(visualOptions[this.model.getDatabases()[0]].Stouffer);

				if ((isFiltered && ! layerAdjusted) || (customStouffer && ! layerStouffer)) {
					retrieveNewValues = true;
				}
			}

			if (retrieveNewValues) {
				parent.getController().step3GetUpdatedPvalues(this, this.getPvaluesFromStore());
			}
		}
	};

	this.updatePvaluesFromStore = function(){
		var me = this;
		var gridView = me.getComponent().queryById("pathwaysGridPanel");
		var store = gridView.getStore();
		var visualOptions = me.getParent().getVisualOptions();

		var databases = me.model.getDatabases();

		/* Suspend events */
		store.suspendEvents();

		databases.forEach(function(db) {

			/* If new Stouffer values are available, update ALL records in store, else
			   set the default data. */
			var allRecords = store.snapshot || store.data;
			var restoreRawStouffer = (visualOptions[db].Stouffer == undefined);

			allRecords.each(function(storeRecord) {
				var pathwayID = storeRecord.raw.pathwayID;

				/* Skip record if it is from another DB.

				   Without this the outer loop over databases writes every record once
				   per database: the KEGG pass sets the KEGG pathways correctly, then
				   the Reactome pass looks each of those same KEGG IDs up in
				   visualOptions.Reactome.Stouffer, misses, and overwrites them with
				   undefined. Only the last database in the list kept its combined
				   p-value; every other database's rows rendered NaN as soon as custom
				   Stouffer weights were applied. The adjusted p-value loop below has
				   always had this guard. */
				if (storeRecord.raw.source != db) {
					return;
				}

				storeRecord.set("combinedSignificancePvalueStouffer", restoreRawStouffer ? storeRecord.raw.combinedSignificancePvalueStouffer : visualOptions[db].Stouffer[pathwayID]);
			});

			/* New adjusted p-values: iterate over filtered records */
			var filteredRecords = store.data;
			var adjustedPvalueMethods = me.model.getMultiplePvaluesMethods();
			var combinedPvaluesMethods = me.model.getCombinedPvaluesMethods();
			var omicNames = me.model.getOmicNames();
			var restoreRawAdjusted = (visualOptions[db].adjustedPvalues == undefined);

			if (adjustedPvalueMethods !== null) {
				filteredRecords.each(function(storeRecord) {
					var pathwayID = storeRecord.raw.pathwayID;
					var dbID = storeRecord.raw.source;

					/* Skip record if it is from another DB */
					if (dbID == db) {
						/* Iterate over all adjusted columns (omics and combined p-values methods) */
						omicNames.concat(combinedPvaluesMethods).forEach(function(adjustedColumn) {
							var keyField;

							/* Set the correct name for the rowModel */
							if (combinedPvaluesMethods.indexOf(adjustedColumn) != -1) {
								keyField = "adjustedCombinedSignificancePvalue" + adjustedColumn + "%fdrterm%";
							} else {
								keyField = "adjpval%fdrterm%-" + adjustedColumn.toLowerCase().replace(/ /g, "-");
							}

							/* Iterate over multiple test adjustment methods */
							adjustedPvalueMethods.forEach(function(fdrMethod) {
								var rowModelKey = keyField.replace("%fdrterm%", fdrMethod);
								var newPvalue;

								/* 	If the column is present, it must contain all the adjustment methods but not necessarily
									all the pathways, as not all omics match in all pathways. */
								if ( ! restoreRawAdjusted && visualOptions[db].adjustedPvalues[adjustedColumn]) {
									newPvalue = visualOptions[db].adjustedPvalues[adjustedColumn][fdrMethod][pathwayID] || "-";
								} else {
									newPvalue = storeRecord.raw[rowModelKey];
								}

								storeRecord.set(rowModelKey, newPvalue);
							});
						});
					}
				});
			}
		});

		/* Resume events */
		store.resumeEvents();

		gridView.down("gridview").refresh();
	};

	this.getPvaluesFromStore = function(includeHidden = false){
		var store = this.getComponent().queryById("pathwaysGridPanel").getStore();
		var selectedRecords = (includeHidden ? store.snapshot || store.data : store.data);

		var omicNames = this.getParent().getModel().getOmicNames();
		var combinedPvaluesMethods = this.model.getCombinedPvaluesMethods();

		var visiblePvalues = {};

		this.model.getDatabases().forEach(function(db) {
			visiblePvalues[db] = {};
		});

		selectedRecords.each(function(rowRecord) {
			var rowData = rowRecord.data;

			visiblePvalues[rowData.source][rowData.pathwayID] = {};

			omicNames.forEach(function(omic) {
				visiblePvalues[rowData.source][rowData.pathwayID][omic] = rowData["pValue-" + omic.toLowerCase().replace(/ /g, "-")];
			});

			combinedPvaluesMethods.forEach(function(combMethod) {
				visiblePvalues[rowData.source][rowData.pathwayID][combMethod] = rowData["combinedSignificancePvalue" + combMethod];
			});
		});

		return(visiblePvalues);
	};

	/**
	* This function generates a new column for the table (pValue column) for a given OMIC, and add the corresponding data to the row model.
	* @chainable
	* @param {Object} omics, list of omics for the current JOBINSTANCE
	* @param {Array} columns, list of Objects defining the columns content
	* @param {Object} rowModel, Object containing a description for the row model for the table
	* @return {PA_Step3PathwayTableView}
	*/
	this.generateColumns = function(omics, columns, rowModel, hidden, adjustedPvaluesMethods, combinedPvaluesMethods) {
		//FOR EACH OMIC -> ADD COLUM FOR p-value AND CREATE THE HOVER PANEL WITH SUMMARY
		var omicName;
		var me = this;

		var selectedAdjustedMethod = me.getParent().getVisualOptions().selectedAdjustedMethod;
		var conditionNames = me.model.conditionNames || [];

		//TODO: REMOVE THIS SPAGETTI CODE :/
		var renderFunction = function(value, metadata, record) {
			var myToolTipText = "<b style='display:block; width:200px'>" + metadata.column.text.replace(/<\/br>/g, " ") + "</b>";
			metadata.style = "height: 40px; font-size:12px;"

			//IF THERE IS NOT DATA FOR THIS PATHWAY, FOR THIS OMIC, PRINT A '-'
			if (value === "-" || value == undefined || isNaN(value)) {
				myToolTipText = myToolTipText + "<i>No data for this pathway</i>";
				metadata.tdAttr = 'data-qtip="' + myToolTipText + '"';
				metadata.style += "background-color:var(--pa-cell-empty,#D4D4D4);";
				return "-";
			}
			//ELSE, GENERATE SUMMARY TIP

			//RENDER THE VALUE -> IF LESS THAN 0.05, USE SCIENTIFIC NOTATION
			var renderedValue = (value > 0.001 || value === 0) ? parseFloat(value).toFixed(5) : parseFloat(value).toExponential(4);
			
			// Detect if it is a condition-specific column
			var isCondition = metadata.column.isCondition || metadata.column.dataIndex.indexOf('pValue_c') !== -1;
			var nCond = metadata.column.nConditions || 1;
			var omicPart = metadata.column.dataIndex.split('pValue')[1];
			if (isCondition) {
				omicPart = metadata.column.dataIndex.split(/pValue_c\d+/)[1];
			}
			var omicNameSuffix = omicPart;

			if(value <= 0.065){
				var color = Math.round(225 * (value/0.065));
				var tint = 172 + Math.round(color * 0.32);
				metadata.style += "background-color:rgb(255, " + tint + "," + tint + "); color:#9B1C1C;";
			}

			try {
				var sourceDB = record.get("source");
				var totalFeatures, totalRelevant;
				
				var rawOmicName = metadata.column.text.replace(/<\/br>/g, " ");
				// If it is a condition column, the header might be just the condition name.
				// We need the omic name to look up total features.
				if (isCondition) {
					// We find the omic name by looking at the parent/sibling column or from the dataIndex
					// For now, we try to extract it from the dataIndex which we know is 'pValue_c' + c + omicName
					// or we can use the 'omic' property if we added it to the column definition.
					rawOmicName = metadata.column.omic || rawOmicName;
				}

				// Keep compatibility with old jobs
				if (me.model.summary[4].hasOwnProperty(sourceDB)) {
					totalFeatures = me.model.summary[4][sourceDB][rawOmicName] || 0;
					totalRelevant = me.model.summary[5][sourceDB][rawOmicName] || 0;
				} else {
					totalFeatures = me.model.summary[4][rawOmicName] || 0;
					totalRelevant = me.model.summary[5][rawOmicName] || 0;
				}

				// Handle multi-condition array formats for totalRelevant
				if (Array.isArray(totalRelevant)) {
					var condIdx = isCondition ? parseInt(metadata.column.dataIndex.split('_c')[1] || 0) : 0;
					totalRelevant = totalRelevant[condIdx] !== undefined ? totalRelevant[condIdx] : totalRelevant[0];
				}

				var prefix = isCondition ? metadata.column.dataIndex.split(omicNameSuffix)[0].replace('pValue', 'totalMatched') : 'totalMatched';
				var relPrefix = isCondition ? metadata.column.dataIndex.split(omicNameSuffix)[0].replace('pValue', 'totalRelevantMatched') : 'totalRelevantMatched';

				var foundFeatures = record.get(prefix + omicNameSuffix);
				var foundRelevant = record.get(relPrefix + omicNameSuffix);

				var foundNotRelevant = foundFeatures - foundRelevant;
				var notFoundRelevant = totalRelevant - foundRelevant;
				var notFoundNotRelev = (totalFeatures - foundFeatures) - notFoundRelevant;

				if (foundRelevant !== undefined) {

					// Only show tooltip for condition-specific columns OR single-condition jobs
					if (isCondition || nCond <= 1) {
						myToolTipText += '<b>p-value:</b>'  + (value === -1 ? "-" : renderedValue) + "</br>";
						myToolTipText +=
						"<table class='contingencyTable'>" +
						' <thead><th></th><th>Relevant</th><th>Not Relevant</th><th></th></thead>' +
						'  <tr><td>Found</td><td>' + foundRelevant + '</td><td>' + foundNotRelevant + '</td><td>' + foundFeatures + '</td></tr>' +
						'  <tr><td>Not found</td><td>' + notFoundRelevant + '</td><td>' + notFoundNotRelev + '</td><td>' + (totalFeatures - foundFeatures) + '</td></tr>' +
						'  <tr><td></td><td>' + totalRelevant + '</td><td>' + (totalFeatures - totalRelevant) + '</td><td>' + (totalFeatures) + '</td></tr>' +
						'</table>';
						metadata.tdAttr = 'data-qtip="' + myToolTipText + '"';
					}
				}

			} catch (e) {
				console.error("Error while creating tooltip", e);
			}

			return renderedValue;
		};

		for (var i in omics) {
			var omic = omics[i];
			omicName = "-" + omic.omicName.toLowerCase().replace(/ /g, "-");
			
			// Detect number of conditions across all pathways for this omic
			var nConditions = 0;
			var allPathways = Object.values(me.model.getPathways());
			for (var pIdx = 0; pIdx < allPathways.length; pIdx++) {
				var sigVals = allPathways[pIdx].getSignificanceValues();
				if (sigVals && sigVals[omic.omicName]) {
					nConditions = Math.max(nConditions, sigVals[omic.omicName].length);
				}
			}
			if (nConditions === 0 && conditionNames && conditionNames.length > 1) {
				nConditions = conditionNames.length;
			} else if (nConditions === 0) {
				nConditions = 1;
			}

			var omicColumn = {
				text: (nConditions > 1 ? '<i class="fa fa-chevron-right expandOmicConditions" style="cursor:pointer;" data-omic="' + omicName + '"></i> ' : '') + omic.omicName.replace(" ","</br>"), 
				cls:"header-45deg",
				dataIndex: 'pValue' + omicName, width:90,
				flex: 1, hidden : hidden, sortable: true, align: "center",
				filter: {type: 'numeric'},
				renderer: renderFunction,
				omic: omic.omicName, // Custom property for the renderer
				nConditions: nConditions,
				isCondition: false
			};

			if (nConditions > 1) {
				var subColumns = [Ext.apply({}, omicColumn)];
				// Remove the expand icon from the actual data column if we are nesting
				subColumns[0].text = "Global";
				subColumns[0].flex = 1;
				
				for (var c = 0; c < nConditions; c++) {
					var condName = conditionNames[c] || ("Cond " + (c+1));
					subColumns.push({
						text: condName,
						dataIndex: 'pValue_c' + c + omicName,
						width: 90, flex: 1, hidden: true, // Hidden by default
						sortable: true, align: "center",
						filter: {type: 'numeric'},
						renderer: renderFunction,
						omic: omic.omicName,
						isCondition: true,
						nConditions: nConditions,
						cls: "header-45deg condition-column-" + omicName
					});
					
					// Add fields to row model for conditions
					rowModel['totalMatched_c' + c + omicName] = { name: 'totalMatched_c' + c + omicName, defaultValue: 0 };
					rowModel['totalRelevantMatched_c' + c + omicName] = { name: 'totalRelevantMatched_c' + c + omicName, defaultValue: 0 };
					rowModel['pValue_c' + c + omicName] = { name: 'pValue_c' + c + omicName, defaultValue: "-", type: 'floatOrString' };
				}
				
				columns.push({
					text: (nConditions > 1 ? '<i class="fa fa-chevron-right expandOmicConditions" style="cursor:pointer; margin-right:5px;" data-omic="' + omicName + '"></i> ' : '') + omic.omicName.replace(" ","</br>"),
					columns: subColumns,
					omic: omic.omicName
				});
			} else {
				columns.push(omicColumn);
			}

			//ADD THE CUSTOM FIELD TO ROW MODEL
			rowModel['totalMatched' + omicName] = {
				name: 'totalMatched' + omicName,
				defaultValue: 0
			};
			rowModel['totalRelevantMatched' + omicName] = {
				name: 'totalRelevantMatched' + omicName,
				defaultValue: 0
			};
			rowModel['pValue' + omicName] = {
				name: 'pValue' + omicName,
				defaultValue: "-",
				type: 'floatOrString'
			};

			//Apply only when there are adjusted p-values
			adjustedPvaluesMethods.forEach(function(m) {
				columns.push({
					text: omics[i].omicName.replace(" ","</br>") + '</br>(' + m + ')', cls:"header-45deg",
					dataIndex: 'adjpval' + m + omicName, width:90,
					flex: 1, hidden: (hidden || selectedAdjustedMethod != m),
					sortable: true, align: "center",
					filter: {type: 'numeric'},
					renderer: renderFunction,
					omic: omics[i].omicName
				});

				rowModel['adjpval' + m + omicName] = {
					name: 'adjpval' + m + omicName,
					defaultValue: "-",
					type: 'floatOrString'
				};
			});
		}
		return this;
	};

	//TODO: DOCUMENTAR
	this.getSelectedPathways = function() {
		var selectedPathways = [];
		this.getComponent().queryById("pathwaysGridPanel").getStore().query("selected", true).each(function(item) {
			selectedPathways.push(item.get("pathwayID"));
		});
		return selectedPathways;
	};

	/**
	* Filters this table down to the enriched pathways that contain the given
	* feature ID (a MORE target or regulator), then scrolls the table into view.
	* Called by the MORE Regulation panels (PA_Step3RegulationView) so the user
	* can jump from a regulator↔target pair straight to "which enriched pathways
	* is this feature in". Reuses the per-row hidden `identifiers` field that
	* already carries every ID form of each matched gene/compound.
	* @param {String} featureID  Target/regulator ID to look up.
	*/
	this.searchFeatureInPathways = function(featureID) {
		if (!featureID) {
			return;
		}
		var grid = this.getComponent().queryById("pathwaysGridPanel");
		if (!grid || !grid.searchByFeatureID) {
			return;
		}
		grid.searchByFeatureID(featureID);
		// The MORE panels render below this table; bring it back into view.
		var section = document.getElementById("pathwayEnrichmentSection");
		if (section && section.scrollIntoView) {
			section.scrollIntoView({behavior: "smooth", block: "start"});
		}
	};

	/**
	* This function generates the component (EXTJS) using the content of the model
	* @param {String}  renderTo  the ID for the DOM element where this component should be rendered
	* @returns {Ext.ComponentView} The visual component
	*/
	this.initComponent = function() {
		var me = this;
		this.component = Ext.widget({
			/* overflowX was 'scroll' to cope with the toolbar, which needed 1753px to
			   lay out on one line. It sits on two rows now and fits, but the scroll
			   was still making the grid size to its content rather than to the card:
			   1318px inside a 1112px box, so "External links" was only reachable by
			   scrolling the table sideways. Sized to the card, all nine columns fit. */
			/* Every other card on this step carries this margin, so without it
			   the enrichment card - the last thing on the page - hung 10px
			   outside the rail the four cards above it share, and its heading
			   started 10px left of theirs. */
			xtype: 'container', cls: "contentbox", style: "max-width:1900px; margin: 5px 10px;", items: [
				{xtype: 'box', flex: 1, html: '<h2 id="pathwayEnrichmentSection">Pathway enrichment</h2>'},
				{
					xtype: "livesearchgrid", itemId: 'pathwaysGridPanel',
					searchFor: "title",
					defaults: {border: false}, columnLines: true, stripeRows:false,
					download: {
						title: 'Paintomics pathways ' + me.getModel().getJobID(),
						ignoreColums: [1]
					},
					store: Ext.create('Ext.data.Store', {
						fields: ['name', 'email', 'phone']
					}),
					columns: [{text: 'name', flex: 1, dataIndex: 'name'}],
					databases: me.model.getDatabases(),
					adjustedPvaluesMethods: me.model.getMultiplePvaluesMethods(),
					combinedPvaluesMethods: me.model.getCombinedPvaluesMethods(),
					selectedAdjustedMethod: me.getParent().visualOptions.selectedAdjustedMethod,
					selectedCombinedMethod: me.getParent().visualOptions.selectedCombinedMethod,
					enableConfigure: (me.getParent().visualOptions.selectedCombinedMethod == 'Stouffer'),
					listeners: {
						'adjustedMethodChanged': function(records) {
								me.getParent().setVisualOptions("selectedAdjustedMethod", records[0].raw[0]);
								me.getParent().getController().updateStoredVisualOptions(me.getParent().getModel().getJobID(), me.getParent().getVisualOptions());
						},
						'combinedMethodChanged': function(records) {
								me.getParent().setVisualOptions("selectedCombinedMethod", records[0].raw[0]);
								me.getParent().applyVisualSettings();

								// Disable configure element for not Stouffer values
								var isStouffer = (records[0].raw[0] == "Stouffer");

								me.component.query("[id=configureButton]")[0].setDisabled(! isStouffer);
						},
						'clickConfigure': function(iconLink) {

							if (me.tipComponent == null) {
								// Retrieve the default weights used (mapped ratio)
								var mappingInfo = me.getModel().getMappingSummary();
								var customStouffers = me.getParent().getVisualOptions().stoufferWeights;
								var defaultValues = {};

								// Calculate the original mapping ratio used as Stouffer weight.
								Object.keys(mappingInfo).map(function(omic) {
									// An omic with no features at all would make this 0/0 = NaN, which the
									// slider silently coerces to its minimum. Resolve it here instead so the
									// weight that reaches the server is always a number we chose deliberately.
									var total = mappingInfo[omic].mapped + mappingInfo[omic].unmapped;
									var ratio = (total > 0) ? (mappingInfo[omic].mapped / total) : 0;

									defaultValues[omic] = Math.max(0, Math.min(10, parseFloat(ratio.toFixed(1)) * 10));
								});

								// Writes the current weight onto the field label so it is readable without
								// dragging. The label text itself is untouched, because the Apply handler
								// maps sliders back to omics through getFieldLabel().
								var showWeight = function(slider, value) {
									if (slider.labelEl && slider.labelEl.dom) {
										slider.labelEl.dom.setAttribute("data-pa-weight", value);
									}
								};

								// Pick the stored weight only when one actually exists for this omic.
								// visualOptions.stoufferWeights is persisted as {} for any job that never
								// applied custom weights, and {} != undefined, so the previous check sent
								// every slider to customStouffers[omic] === undefined and the widget
								// silently clamped it to its minimum. Every weight opened at 0, and
								// applying that would drop all omics out of the combined p-value.
								var weightFor = function(omic) {
									var stored = customStouffers ? customStouffers[omic] : undefined;

									return (stored === undefined || stored === null || isNaN(stored)) ? defaultValues[omic] : stored;
								};

								// Create an slider for each omic
								var omicSliders = me.getModel().getOmicNames().map(function(omic) {
									return({
										xtype: 'slider',
										fieldLabel: omic,
										minValue: 0,
										maxValue: 10,
										increment: 1,
										value: weightFor(omic),
										// The label needs room for the longest omic name ("Transcription
										// factor"); whatever is left has to be a draggable track, so both
										// halves are sized explicitly rather than left to '100%'.
										labelWidth: 160,
										width: 320,
										listeners: {
											afterrender: function(slider) { showWeight(slider, slider.getValue()); },
											change: showWeight
										}
									})
								});

								me.tipComponent = Ext.create('Ext.tip.Tip', {
									closable: true,
									title: 'Stouffer weights',
									width: 356,
									itemId: 'stoufferTip',
									cls: 'paWeightsTip',
									bodyPadding: 4,
									// Floating to the document body on purpose: rendering into
									// mainViewCenterPanel puts the tip inside that panel's overflow, so a
									// panel this tall gets clipped and scrolls away with the table.
									constrain: true,
									items: [
										{
											xtype: 'container',
											layout: 'vbox',
											align: 'center',
											flex: 1,
											items: omicSliders.concat({
												xtype: 'container',
												layout: {
													type: 'hbox',
													align: 'middle'
												},
												flex: 1,
												items: [
													{
														xtype: 'button',
														text: 'Apply',
														margin: '10 5 10 10',
														width: 80,
														//cls: 'button btn-success btn-right',
														handler: function() {
															var tip = Ext.ComponentQuery.query("[itemId=stoufferTip]")[0];
															var sliders = tip.query("slider");
															var stoufferWeigths = {};
															var currentPValues = me.getPvaluesFromStore(true);
															var visiblePathways = Object.keys(me.getAssociatedPathways(true));

															sliders.forEach(function(omicSlider) {
																stoufferWeigths[omicSlider.getFieldLabel()] = parseFloat(omicSlider.getValue());
															});

															me.getParent().setVisualOptions("stoufferWeights", stoufferWeigths);

															me.getParent().getController().updateStoredApplicationData("visualOptions", me.getParent().getVisualOptions());

															me.getParent().getController().step3GetUpdatedPvalues(me, currentPValues, stoufferWeigths, visiblePathways);

															tip.close();
														}
													},
													{
														xtype: 'button',
														text: 'Defaults',
														width: 80,
														margin: '10 10 10 5',
														handler: function() {
															var sliders = Ext.ComponentQuery.query("[itemId=stoufferTip]")[0].query("slider");

															sliders.forEach(function(omicSlider) {
																omicSlider.setValue(defaultValues[omicSlider.getFieldLabel()]);
															});
														}
													}
												]
											})
										}
									]
								});
							}

							// Drop below the toolbar rather than above it: opening upward covered the
						// very control the user just clicked. "?" lets Ext flip it back if there
						// is no room underneath.
						me.tipComponent.showBy(iconLink, "tl-bl?", [0, 6]);
						}
					}
				}]
			}
		);
		return this.component;
	};

	return this;
}
PA_Step3PathwayTableView.prototype = new View();

function PA_Step3StatsView() {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step3StatsView";

	/***********************************************************************
	* GETTER AND SETTERS
	***********************************************************************/
	//TODO: DOCUMENTAR
	this.loadModel= function(model){
		var me = this;

		me.model = model;
	};

	/**
	* This function generates the component (EXTJS) using the content of the model
	* @param {String}  renderTo  the ID for the DOM element where this component should be rendered
	* @returns {Ext.ComponentView} The visual component
	*/
	this.initComponent = function() {
		var me = this;

		var omicSummaryPanelComponents = [];
		var dataDistribution = me.getModel().getDataDistributionSummaries();

		for (var omicName in dataDistribution) {
			omicSummaryPanelComponents.push(new PA_OmicSummaryPanel(omicName, dataDistribution[omicName], false).getComponent());
		}

		this.component = Ext.widget({
			xtype: 'container', cls: "contentbox", id: 'statsViewContainer', hidden: false, items: [
				{xtype: 'box', flex: 1,
				 html: '<h2>Mapping and data statistics</h2>' + (omicSummaryPanelComponents.length ? '<a href="javascript:void(0)" id="download_mapping_file"><i class="fa fa-download"></i> Download ID/Name mapping results.</a>' : "")},
				{
						xtype: 'container', itemId: "omicSummaryPanelStep3",
						cls: "omicSummaryContainer",
						layout: 'column',  style: "margin-top:20px;width: 100%;",
						items: omicSummaryPanelComponents
				}
			],
			listeners: {
					boxready: function() {
						$('#download_mapping_file').click(function() {
							application.getController("DataManagementController").downloadFilesHandler(me, "mapping_results_" + me.getModel().getJobID() + ".zip", "job_result", me.getModel().getJobID());
						});
					}
				}
		});

		return this.component;
	};

	return this;
}
PA_Step3StatsView.prototype = new View();

/*
FOR PaintOmics 4
 */
/**
 * Map one hub-analysis row to the grid's field names.
 *
 * Rows used to arrive as a headerless 8-element array whose column order was
 * stated in exactly one place on each side and versioned nowhere: reordering
 * the R frame silently relabelled the whole grid with no error anywhere.
 * Since schema 2 they are named dicts, and this is the only place the names
 * are read.
 *
 * There is deliberately NO legacy branch. A job stored before schema 2 is
 * re-scored on the server (PathwayAcquisitionServlet, recovery path) rather
 * than translated here -- the rows expire in at most 14 days, and a re-score
 * returns the corrected numbers instead of faithfully preserving the wrong
 * ones, which came from a graph with 28% mis-attributed subtypes.
 */
var paHubRow = function (raw) {
	return {
		ID: raw.name,
		Step: raw.step,
		Percentage: raw.density,
		Percentile: raw.percentile,
		DEN: raw.DEN,
		noDEN: raw.noDEN,
		pvalue: raw.pvalue,
		padjust: raw.pvalue_adjust,
		ballFraction: raw.ball_fraction
	};
};

function PA_Step3HubAnalysis () {
	let me = this;
	this.name = "PA_Step3HubAnalysis";
	this.tableData = null;
	let hubTable =[];
	let globalExpressionGene = [];
	let globalExpressionComp = [];
	let compRegulateFeatures = [];
	let distributionSummaries = null;
	let visualOptions = null;

	this.loadModel = function (model) {
		if (this.model !== null) {
			this.model.deleteObserver(this);
		}
		this.model = model;
		this.model.addObserver(this);
		const hubAnalysisResult = this.model.getHubAnalysisResult();
		// loadModel runs on every model load, and the view is constructed once
		// (PA_Step3Views.js:350-354). Appending without clearing meant job B's
		// rows were pushed onto job A's array on the controller's force path.
		hubTable.length = 0;
		for (let key in hubAnalysisResult) {
			let row = paHubRow(hubAnalysisResult[key]);
			row.Metabolite = this.model.mappingComp[row.ID] || row.ID;
			hubTable.push(row);
		}

		compRegulateFeatures = this.model.compoundRegulateFeatures
		if (this.model.globalExpressionData) {
			if (typeof this.model.globalExpressionData['inputCompound'] !== 'undefined') {
				globalExpressionComp = this.model.globalExpressionData['inputCompound']
			}
			if (typeof this.model.globalExpressionData['inputGene'] !== 'undefined') {
			globalExpressionGene = this.model.globalExpressionData['inputGene']
		}
		}
		distributionSummaries = this.model.getDataDistributionSummaries()
		visualOptions = me.getParent().visualOptions

	}

	this.initComponent = function () {
		Ext.define('User', {
			extend: 'Ext.data.Model',
			fields: ['Metabolite', 'ID', 'Step', 'Percentage', "Percentile", 'DEN', 'noDEN', 'pvalue', 'padjust']
		});

		var userStore = Ext.create('Ext.data.Store', {
			model: 'User',
			data: hubTable
		});


		this.component = Ext.widget(
			{
				xtype: 'container',

				border: 0,
				maxWidth: 1900,
				/* Same inset as every other card on this step - see the
				   metabolite-class grid below, which had the same omission. */
				style: "margin: 5px 10px;",
				layout: 'column',
				items: [
					{
						xtype: "gridpanel",
						itemId: 'hubAnalysisGrid',
						cls: "contentbox paWrapHeaders",
						columnWidth: 1,
						store: userStore,
						height: 350,
						header: {
							xtype: 'box',
							flex: 2,
							border: 0,
							// A minimum, not a height. Pinned at 70 this clipped its
							// own second line: an h2 and two .infoTip lines measure
							// 76px, so the last one was cut in half by the column
							// headers below it. A minimum keeps the spacing this was
							// chosen for and still lets the header grow when the
							// text wraps, which it also does at narrow widths.
							minHeight: 70,
							html: '<h2 id="EnrichmentSection">Metabolite hub analysis</h2>' +
								' <span class="infoTip">Neighbouring genes for each metabolite at <b> 1 to 4 network steps </b> are identified.</b></span> ' +
								' <span class="infoTip">The percentile and binomial tests are used to identify metabolites with a high density of DEGs in their proximal network.</span>',

							style: {
								backgroundColor: 'white'
							}
						},

						columns: [
							{
								xtype: 'customactioncolumn',
								text: "Paint",
								menuDisabled: true,
								width: 55,
								items: [{
									icon: "fa-paint-brush-o",
									text: "",
									tooltip: 'Paint this feature',
									style: "font-size: 20px;",
									handler: function (grid, rowIndex) {
										revealPlotPanel('hubAnalysisPlotPanel');

										let elem = $("#hubAnalysisPlot");
										elem.empty();
										/* The heatmap is a fixed 300px block and the plot sits beside
										   it, so the plot may only claim what is left. Giving it the
										   full width pushed it onto its own line, where a 300px strip
										   above a 1240px chart of the same samples read as a broken
										   figure. The floor keeps a usable chart if the panel is ever
										   too narrow for the pair, in which case they stack. */
										let divWidth = Math.max(260, elem.width() - 400);

										let hubTable = {};

										for (let i = 0; i < grid.getStore().data.items.length; i++) {
											hubTable[i] = grid.getStore().data.items[i].data
										}
										// Expression value of this set
										let ID = hubTable[rowIndex]['ID'];
										let compExpression = globalExpressionComp[ID];
										if (compExpression && !(compExpression instanceof OmicValue)) {
											compExpression = OmicValue.loadFromJSON(compExpression);
										}
										let divIdComp = 'divIdComp'
										htmlCode =
											'<h2 style="background-color: white"> Metabolite Expression Value</h2>' +
											"<div class='contentbox'>" +
											"  <div class='PA_step5_heatmapContainer' id='" + divIdComp + "'  style='height: " + 130 + "px'><i class='fa fa-cog fa-spin'></i> Loading..</div>" +
											"  <div class='PA_step5_plotContainer' id='" + divIdComp + "_plotContainer'  style='width:" + divWidth + "px;height: " + 130 + "px'><i class='fa fa-cog fa-spin'></i> Loading..</div>" +
											"</div>" +
											'<h2 style="background-color: white">Neighbouring features</h2>'
										elem.append(htmlCode);

										heatmapSite = generateHeatmap(divIdComp, "Metabolomics", [compExpression], distributionSummaries, visualOptions, paOmicHeaders(me.model, "Metabolomics"))
										plotSite = generatePlot(divIdComp + "_plotContainer", "Metabolomics", [compExpression], distributionSummaries, divIdComp + "_plotlegendContainer", visualOptions, paOmicHeaders(me.model, "Metabolomics"));

										// Expression value of regulate features.
										//
										// compRegulateFeatures[ID][step] was indexed without a guard,
										// so any metabolite missing from the map threw a TypeError
										// here - after the "Metabolite regulates Features" heading
										// had already been appended. The section then rendered as a
										// title with nothing whatsoever under it, which is what the
										// missing DE neighbours look like from the outside. The map
										// is absent for every job reopened by its URL, because
										// compoundRegulateFeatures is not among the fields written
										// back at step 2 (see PAINTOMICS4_LARGE_FIELDS).
										let stepNames = {'One Step': 1, 'Two Steps': 2, 'Three Steps': 3, 'Four Steps': 4};
										let rawStep = hubTable[rowIndex]['Step'];
										let step = stepNames[rawStep] || parseInt(rawStep, 10);
										let neighboursByStep = compRegulateFeatures ? compRegulateFeatures[ID] : null;
										let regulateFeatures = (neighboursByStep && step) ? neighboursByStep[step] : null;

										if (!regulateFeatures || !regulateFeatures.length) {
											elem.append(
												'<div class="contentbox paEmptyNote">' +
												'  <p>No expression data is available for the neighbours of this metabolite.</p>' +
												'  <p>Neighbour identities are held only for the run that produced them, so they are not restored when a job is reopened from its link. Re-run the analysis to see them.</p>' +
												'</div>');
											fitPlotPanel('hubAnalysisPlotPanel', 'hubAnalysisPlot');
											return;
										}

										// Every omic can legitimately have no measured neighbour, in
										// which case the loop below draws nothing - the same dangling
										// heading by another route.
										let paintedAnyOmic = false;

										for (key in distributionSummaries) {
											let omicName = key
											let divId = key.replace(/\s/g, '_') + 'hubAnlysis'
											let regulateOmicsValue = []
											for (let i = 0; i < regulateFeatures.length; i++) {
												let regulateFeature = regulateFeatures[i]
												try {
													let ov = null;
													if (key == "Gene expression") {
														ov = globalExpressionGene[regulateFeature];
													} else if (key == "Metabolomics") {
														ov = globalExpressionComp[regulateFeature];
													}
													if (ov) {
														if (!(ov instanceof OmicValue)) {
															ov = OmicValue.loadFromJSON(ov);
														}
														regulateOmicsValue.push(ov);
													}
												} catch (e) {
													console.log('No expression data for: ' + regulateFeature)
												}
											}
											regulateOmicsValue = regulateOmicsValue.filter(function (x) {
													return x !== undefined;
												}
											);
											if (regulateOmicsValue.length === 0) {
												continue;
											}
											paintedAnyOmic = true;
											htmlCode =
												"<div class='contentbox'>" +
												"  <h3>" + omicName + "<span><input type='checkbox' id='" + divId + "_cb_relevant' value='" + omicName + "'/>Only relevant</span></h3>" +
												"  <div class='PA_step5_heatmapContainer' id='" + divId + "'  style='height: " + ((regulateOmicsValue.length * 30) + 100) + "px'><i class='fa fa-cog fa-spin'></i> Loading..</div>" +
												"  <div class='PA_step5_plotContainer' id='" + divId + "_plotContainer'  style='width:" + divWidth + "px;height: " + ((regulateOmicsValue.length * 30) + 100) + "px'><i class='fa fa-cog fa-spin'></i> Loading..</div>" +
												"</div>";
											elem.append(htmlCode);
											// expression of this site


											// expression of regulate features
											heatmapGene = generateHeatmap(divId, omicName, regulateOmicsValue, distributionSummaries, visualOptions, paOmicHeaders(me.model, omicName))
											plot = generatePlot(divId + "_plotContainer", omicName, regulateOmicsValue, distributionSummaries, divId + "_plotlegendContainer", visualOptions, paOmicHeaders(me.model, omicName));
											$("div.contentbox h3 :checkbox").change(function () {
												let onlyRelevants = $(this).is(":checked");
												// Highcharts does not automatically hide Y labels when hiding series, so it is easier and faster
												// to recreate the whole graphic.
												let omicValues = regulateOmicsValue;
												if (onlyRelevants) {
													omicValues = omicValues.filter(x => x.isRelevant() || x.isRelevantAssociation());
												}
												$('#' + divId + "_heatmapContainer").height(omicValues.length * 30 + 100);
												generateHeatmap(divId, omicName, omicValues, distributionSummaries, visualOptions, paOmicHeaders(me.model, omicName))
												generatePlot(divId + "_plotContainer", omicName, omicValues, distributionSummaries, divId + "_plotlegendContainer", visualOptions, paOmicHeaders(me.model, omicName));
											})
										}

										if (!paintedAnyOmic) {
											elem.append(
												'<div class="contentbox paEmptyNote">' +
												'  <p>This metabolite has ' + regulateFeatures.length + ' neighbour' + (regulateFeatures.length === 1 ? '' : 's') + ' at ' + step + ' step' + (step === 1 ? '' : 's') + ', but none of them carry measured values in the omics you uploaded.</p>' +
												'</div>');
										}

										fitPlotPanel('hubAnalysisPlotPanel', 'hubAnalysisPlot');
									}
								}]
							},
							{
								xtype: 'customactioncolumn',
								text: "Network",
								menuDisabled: true,
								width: 70,
								items: [{
									icon: "fa-share-alt",
									text: "",
									tooltip: 'Draw this metabolite\'s neighbourhood',
									style: "font-size: 20px;",
									handler: function (grid, rowIndex) {
										// The hub table reports numbers about a
										// network nobody could see; this draws it.
										let row = grid.getStore().data.items[rowIndex].data;
										let view = me.getParent().hubNetworkView;
										if (view) {
											view.showCompound(row.ID, row.Step);
										}
									}
								}]
							},
							{
								xtype: 'customactioncolumn',
								text: "Search",
								menuDisabled: true,
								width: 66,
								items: [{
									icon: "fas fa-search",
									text: "",
									tooltip: 'Find this feature in pathways',
									style: "font-size: 20px;",
									handler: function (grid, rowIndex) {

										//update hubTable
										let hubTable = {};
										for (let i = 0; i < grid.getStore().data.items.length; i++) {
											hubTable[i] = grid.getStore().data.items[i].data
										}
										let ID = hubTable[rowIndex]['Metabolite'];
										$(document).ready(function () {
												$("[name = 'searchField']")[0].value = ID
												if (document.getElementsByClassName("x-field x-table-plain x-form-item x-form-type-checkbox x-field-toolbar x-box-item x-toolbar-item x-field-default-toolbar x-hbox-form-item")[2].classList.contains("x-form-cb-checked")) {
													document.getElementsByClassName('x-form-field x-form-checkbox x-form-cb')[2].click()
													document.getElementsByClassName('x-form-field x-form-checkbox x-form-cb')[2].click()
												} else {
													document.getElementsByClassName('x-form-field x-form-checkbox x-form-cb')[2].click()
												}
											}
										)
									}
								}]
							},
							{
								text: 'Metabolite',
								flex: 21 / 100,
								sortable: true,
								hideable: false,
								dataIndex: 'Metabolite',
								renderer: truncatableTextRenderer
							},
							{
								text: 'ID',
								flex: 9 / 100,
								sortable: true,
								hideable: false,
								dataIndex: 'ID'
							},
							{
								text: 'Step',
								flex: 7 / 100,
								sortable: true,
								hideable: false,
								dataIndex: 'Step'
							},
							{
							    text: 'DE neighbors',
								flex: 9.5 / 100,
								sortable: true,
								hideable: false,
								dataIndex: 'DEN'
							},
							{
								text: 'not DE neighbors',
								flex: 9.5 / 100,
								sortable: true,
								hideable: false,
								dataIndex: 'noDEN'
							},
							/* "Percentage" and "Percentile" are single words, so unlike the
							   neighbour columns they cannot wrap out of a narrow share - they
							   just ellipsise into "Percentage." and "Percentile..". The width
							   they need comes from the columns above, whose headers now wrap
							   and whose values are one or two digits. */
							{
								text: 'Percentage',
								flex: 13 / 100,
								sortable: true,
								hideable: false,
								dataIndex: 'Percentage'
							},
							{
								text: 'Percentile',
								flex: 12 / 100,
								sortable: true,
								hideable: false,
								dataIndex: 'Percentile',
								renderer: renderFunctionHub
							},
							{
								text: 'P-values',
								flex:10/100,
								sortable: true,
								hideable: false,
								dataIndex: 'pvalue',
								renderer: renderFunctionLimit
							},
							{
								text: 'FDR BH',
								flex:9/100,
								sortable: true,
								hideable: false,
								dataIndex: 'padjust',
								renderer: renderFunctionLimit
							}

							/*
							{
								text: "DE neighbors",
								flex: 20 / 100,
								sortable: true,
								dataIndex: 'DE_neighbors'

							},

							{
								text: "not DE neighbors",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "not_DE_neighbors"

							},

							{
								text: "% DE neighbors",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "Percentage"
							},

							{
								text: "RDE neighbors",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "RDE_neighbors"
							},
							{
								text: "Rnot DE neighbors",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "Rnot_DE_neighbors"
							},

							{
								text: "% RDE neighbors",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "RPercentage"

							},

							{
								text: "P value",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "P_value",
								renderer: renderFunctionLimit


							},
							{
								text: "P adjusted",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "P_adjusted",
								renderer: renderFunctionLimit
							},
							{
								text: "fisher",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "fisher",
								renderer: renderFunctionLimit
							},
							{
								text: "fisher adjusted",
								flex: 20 / 100,
								sortable: true,
								dataIndex: "fisher_adjusted",
								renderer: renderFunctionLimit
							}
							 */
						],
						bbar: {
							xtpe: 'toolbar',
							items: [
								'-', {
									xtype: 'combo',
									fieldLabel: 'Select a step:',
									labelAlign: 'right',
									forceSelection: true,
									emptyText: '--Select--',
									store: {
										fields: ['Step'],
										data: [
											{
												Step: 'One Step'
											}, {
												Step: 'Two Steps'
											}, {
												Step: 'Three Steps'
											}, {
												Step: 'Four Steps'
											}, {
												Step: 'All Steps'
											}
										]
									},
									displayField: 'Step',
									valueField: 'Step',
									listeners: {
										change: function (combo, value) {
											let grid = this.up('grid'), store = grid.getStore();
											if (!value || value === 'All Steps') {
												store.clearFilter();
											} else {
												store.clearFilter();
												if (value == 'One Step') {
													value = 1
												} else if (value == 'Two Steps') {
													value = 2
												} else if (value == 'Three Steps') {
													value = 3
												} else if (value == 'Four Steps') {
													value = 4
												}
												store.filter([{
														property: 'Step',
														value: value
													}]);
											}
										}
									}

								}
							]
						}
					},
					{
						xtype: 'container',
						itemId: 'hubAnalysisPlotPanel',
						cls: "contentbox",
						/* Hidden until a row is painted, then full width beneath the table
						   rather than a 300px column beside it - see revealPlotPanel(). */
						hidden: true,
						columnWidth: 1,
						padding: '30',
						height: 350,
						autoScroll: true,
						items: [
							{
								xtype: "box",
								html:
									' <h4>Expression Value<span class="infoTip">Use this tool to show expression details of a metabolite and its <b>neighbouring features</b></span></h4> '
							},
							{
								xtype: 'box',
								html:
									' <div id="hubAnalysisPlot" style="height: 100%; overflow: auto;" ></div>'
							}
						]

					}
				]
			}
		);


	};

	return this;

}
PA_Step3HubAnalysis.prototype = new View();

function PA_Step3MetaboliteView() {


	this.name = "PA_Step3MetaboliteView";
	this.tableData = null;
	let dataFinal = new Object();
	var dataShow2 = [];
	let userStore;
	let globalExpressionComp = [];
	let distributionSummaries = null;
	let visualOptions = null;
	let nCond = 1;
	let conditionNames = [];
	let me = this;



	this.loadModel = function (model) {

		if (this.model !== null) {
			this.model.deleteObserver(this);
		}
		this.model = model;
		this.model.addObserver(this);

		// Reset data structures to avoid stale data
		dataFinal = new Object();
		dataShow2 = [];

		var mappingComp = this.model.mappingComp;
		var pValueClassification = this.model.getpValueInDict();
		var classificationDict = this.model.getClassificationDict();
		var exprssionMetabolites = this.model.getExprssionMetabolites();
		var adjustPValue_raw = this.model.getAdjustPvalue();
		var totalRelevantFeaturesInCategory_raw = this.model.getTotalRelevantFeaturesInCategory();
		var featureSummary = this.model.getFeatureSummary();
		var headerComp = this.model.getCompoundBasedInputOmics()[0].omicHeader

		// Handle both single and multi-condition structures
		var isMulti = Array.isArray(pValueClassification);
		var pValueClassification_list = isMulti ? pValueClassification : [pValueClassification];
		
		// Ensure list is not empty and elements are defined
		if (pValueClassification_list.length === 0 || pValueClassification_list[0] === undefined || pValueClassification_list[0] === null) {
			pValueClassification_list = [{}];
		}

		var adjustPValueBH_list = isMulti ? (adjustPValue_raw ? adjustPValue_raw.map(a => a ? a["FDR BH"] : {}) : [{}]) : [adjustPValue_raw ? adjustPValue_raw["FDR BH"] : {}];
		var adjustPValueBY_list = isMulti ? (adjustPValue_raw ? adjustPValue_raw.map(a => a ? a["FDR BY"] : {}) : [{}]) : [adjustPValue_raw ? adjustPValue_raw["FDR BY"] : {}];
		var totalRelevantFeaturesInCategory_list = isMulti ? (totalRelevantFeaturesInCategory_raw || [{}]) : [totalRelevantFeaturesInCategory_raw || {}];
		
		nCond = pValueClassification_list.length;
		conditionNames = this.model.conditionNames || [];

		tableData = {
			mappingComp: mappingComp,
			classificationDict: classificationDict,
			exprssionMetabolites: exprssionMetabolites,
			pValueClassification_list: pValueClassification_list,
			adjustPValueBH_list: adjustPValueBH_list,
			adjustPValueBY_list: adjustPValueBY_list,
			totalRelevantFeaturesInCategory_list: totalRelevantFeaturesInCategory_list
		}

		for (var keys in tableData.classificationDict) {
			dataFinal[keys] = []
			dataFinal[keys]["ID"] = []
			dataFinal[keys]["expressionVal"] = []
			for (var elements in tableData.classificationDict[keys]) {
				dataFinal[keys]["ID"].push(tableData.classificationDict[keys][elements])
				
				// P-values and adjusted P-values per condition
				for (var c = 0; c < nCond; c++) {
					var pValObj = tableData.pValueClassification_list[c] || {};
					var bhObj = tableData.adjustPValueBH_list[c] || {};
					var byObj = tableData.adjustPValueBY_list[c] || {};
					var relObj = tableData.totalRelevantFeaturesInCategory_list[c] || {};

					dataFinal[keys]["pValue_c" + c] = pValObj[keys];
					dataFinal[keys]["FDR BH_c" + c] = bhObj[keys];
					dataFinal[keys]["FDR BY_c" + c] = byObj[keys];
					dataFinal[keys]["foundRelevant_c" + c] = relObj[keys];
				}

				dataFinal[keys]["totalFeatures"] = featureSummary[0];
				// totalRelevant might be a list too
				dataFinal[keys]["totalRelevant"] = Array.isArray(featureSummary[1]) ? featureSummary[1] : [featureSummary[1]];

				dataFinal[keys]["foundFeatures"] = tableData.classificationDict[keys].length;
				
				dataFinal[keys]['header'] = headerComp
			}
		}

		var fields = ['name', 'totalFeatures', 'foundFeatures'];
		for (var c = 0; c < nCond; c++) {
			fields.push('pValue_c' + c);
			fields.push('FDR_BH_c' + c);
			fields.push('FDR_BY_c' + c);
			fields.push('foundRelevant_c' + c);
		}

		for (var keys in dataFinal) {
			var row = {
				name: keys,
				totalFeatures: dataFinal[keys]["totalFeatures"],
				foundFeatures: dataFinal[keys]["foundFeatures"]
			};
			for (var c = 0; c < nCond; c++) {
				row['pValue_c' + c] = dataFinal[keys]["pValue_c" + c];
				row['FDR_BH_c' + c] = dataFinal[keys]["FDR BH_c" + c];
				row['FDR_BY_c' + c] = dataFinal[keys]["FDR BY_c" + c];
				row['foundRelevant_c' + c] = dataFinal[keys]["foundRelevant_c" + c];
			}
			dataShow2.push(row);
		}

		Ext.define('User', {
			extend: 'Ext.data.Model',
			fields: fields
		});

		userStore = Ext.create('Ext.data.Store', {
			model: 'User',
			data: dataShow2
		});

		if (typeof this.model.globalExpressionData['inputCompound'] !== 'undefined') {
			globalExpressionComp = this.model.globalExpressionData['inputCompound']
		}

		distributionSummaries = this.model.getDataDistributionSummaries()
		visualOptions = me.getParent().visualOptions
	}


	this.initComponent = function () {
		this.component = Ext.widget(
			{
				xtype: 'container',
				border: 0,
				maxWidth: 1900,
				/* The inset every other card on this step carries. Without it
				   the metabolite card sat 10px left of the four above it and
				   its heading started 10px left of theirs - only visible on a
				   dataset with metabolites, which is why it outlived the same
				   fix on the enrichment card. */
				style: "margin: 5px 10px;",
				layout:'column',

				items: [
					{
						xtype: "gridpanel",
						itemId: 'classificationGrid',
						cls: "contentbox paWrapHeaders",
						columnWidth: 1,

						autoScroll: true,
						store: userStore,
						height: 350,
						listeners: {
							afterrender: function(grid) {
								grid.el.on('click', function(e, t) {
									var target = $(t);
									if (target.hasClass('expandMetaboliteConditions')) {
										var isExpanded = target.hasClass('fa-chevron-down');
										if (isExpanded) {
											target.removeClass('fa-chevron-down').addClass('fa-chevron-right');
										} else {
											target.removeClass('fa-chevron-right').addClass('fa-chevron-down');
										}
										
										// Toggle visibility of condition columns
										var columns = grid.headerCt.getGridColumns();
										columns.forEach(function(col) {
											if (col.conditionIndex !== undefined) {
												if (isExpanded) col.hide();
												else col.show();
											}
										});
									}
								});
							}
						},
						header: {
							xtype: 'box',
							flex: 1,
							border: 0,
							minHeight: 35,
							html: '<h2 id="EnrichmentSection"> Metabolite class activity analysis</h2>',
							style: {
								backgroundColor: 'white'
							}
						},

						columns: (function() {
							var baseCols = [
								{
									xtype: 'customactioncolumn',
									text: "Paint",
									menuDisabled: true,
									width: 55,
									items: [{
										icon: "fa-paint-brush-o",
										text: "",
										tooltip: 'Paint this classification',
										style: "font-size: 20px;",
										handler: function (grid, rowIndex) {

											revealPlotPanel('classificationPlotPanel');

											let elem = $("#classificationPlot");
											elem.empty();
											/* Reserve the fixed-width heatmap that sits beside the
											   plot, as in the hub table above - otherwise the pair
											   wraps and the strip is left stranded above a chart
											   four times its width. */
											let divWidth = Math.max(260, elem.width() - 400);
											let regulateFeatures = dataFinal[grid.getStore().getAt(rowIndex).data.name].ID;
											let regulateOmicsValueComp = []
											let omicName =  "Metabolomics"
											let divId = "Compound_expression_heatmapContainer_class"


											for (let i = 0; i < regulateFeatures.length; i++) {
												let regulateFeature = regulateFeatures[i]
												try {
													let ov = globalExpressionComp[regulateFeature];
													if (ov) {
														if (!(ov instanceof OmicValue)) {
															ov = OmicValue.loadFromJSON(ov);
														}
														regulateOmicsValueComp.push(ov);
													}
												} catch (e) {
													console.log('No expression data for: ' + regulateFeature)
												}
											}

											regulateOmicsValueComp = regulateOmicsValueComp.filter(function (x) {
													return x !== undefined;
												}
											);

											if (regulateOmicsValueComp.length > 0) {
												htmlCode =
													"<div class='contentbox'>" +
													"  <h3>" + omicName + "<span><input type='checkbox' id='" + divId + "_cb_relevant' value='" + omicName + "'/>Only relevant</span></h3>" +
													"  <div class='PA_step5_heatmapContainer' id='Compound_expression_heatmapContainer_class'  style='height: " + ((regulateOmicsValueComp.length * 30) + 100) + "px'><i class='fa fa-cog fa-spin'></i> Loading..</div>" +
													"  <div class='PA_step5_plotContainer' id='" + divId + "_plotContainer'  style='width:" + divWidth + "px;height: " + ((regulateOmicsValueComp.length * 30) + 100) + "px'><i class='fa fa-cog fa-spin'></i> Loading..</div>" +

													"</div>";
												elem.append(htmlCode);
												heatmapComp = generateHeatmap(divId, omicName, regulateOmicsValueComp, distributionSummaries, visualOptions, paOmicHeaders(me.model, omicName))
												plot = generatePlot(divId + "_plotContainer", omicName, regulateOmicsValueComp, distributionSummaries, divId + "_plotlegendContainer", visualOptions, paOmicHeaders(me.model, omicName));

												$("#" + divId + "_cb_relevant").change(function () {
													let onlyRelevants = $(this).is(":checked");

													// Highcharts does not automatically hide Y labels when hiding series, so it is easier and faster
													// to recreate the whole graphic.
													let omicValues = regulateOmicsValueComp;

													if (onlyRelevants) {
														omicValues = omicValues.filter(x => x.isRelevant() || x.isRelevantAssociation());
													}

													$('#' + divId).height(omicValues.length * 30 + 100);

													heatmapComp = generateHeatmap(divId, omicName, omicValues, distributionSummaries, visualOptions, paOmicHeaders(me.model, omicName))
													plot = generatePlot(divId + "_plotContainer", omicName, omicValues, distributionSummaries, divId + "_plotlegendContainer", visualOptions, paOmicHeaders(me.model, omicName));

												});

											} else {
												// The panel is revealed before the data is checked, so
												// without this the class opens an empty white box.
												elem.append(
													'<div class="contentbox paEmptyNote">' +
													'  <p>None of the ' + regulateFeatures.length + ' metabolite' + (regulateFeatures.length === 1 ? '' : 's') + ' in this class carry measured values in the omics you uploaded.</p>' +
													'</div>');
											}

											fitPlotPanel('classificationPlotPanel', 'classificationPlot');
										}
									}]
								},
								{
									text: 'Name',
									flex: 25 / 100,
									sortable: true,
									hideable: false,
									dataIndex: 'name'
								},
								{
									text: 'Unique Features',
									flex: 15 / 100,
									sortable: true,
									hideable: false,
									dataIndex: 'foundFeatures'
								}
							];

							var pValueCol = {
								text: (nCond > 1 ? '<i class="fa fa-chevron-right expandMetaboliteConditions" style="cursor:pointer;"></i> ' : '') + "P Value",
								flex: 15 / 100,
								sortable: true,
								dataIndex: 'pValue_c0',
								renderer: renderFunctionLimit
							};

							if (nCond > 1) {
								var subCols = [{
									text: 'Global',
									dataIndex: 'pValue_c0', // Placeholder or minimum?
									flex: 1,
									renderer: renderFunctionLimit,
									hidden: false
								}];
								for (var c = 0; c < nCond; c++) {
									subCols.push({
										text: conditionNames[c] || ("Cond " + (c+1)),
										dataIndex: 'pValue_c' + c,
										flex: 1,
										renderer: renderFunctionLimit,
										hidden: true,
										conditionIndex: c
									});
								}
								pValueCol.columns = subCols;
								pValueCol.flex = (subCols.length) * 10 / 100;
							}

							baseCols.push(pValueCol);
							
							// Add FDR columns (can be simple or expanded too, keep simple for now or expanded if needed)
							baseCols.push({
								text: "FDR BH",
								flex: 15 / 100,
								sortable: true,
								dataIndex: "FDR_BH_c0",
								renderer: renderFunctionLimit
							});
							
							return baseCols;
						})(),
					},
					{
						xtype: 'box',
						itemId: 'classificationPlotPanel',
						cls: "contentbox",
						hidden: true,
						columnWidth: 1,
						padding: '30',
						height: 350,
						html:
							' <h4>Expression Value<span class="infoTip">Use this tool to <b> show expression details of metabolites</b> based on their classification </span></h4> ' +
							' <div id="classificationPlot" style="height: 100%; overflow: auto;" ></div>'
					}
				]
			}
		);


	};
	return this;
}

PA_Step3MetaboliteView.prototype = new View();


/**
 * PA_Step3RegulationView — surfaces MORE's RegulationPerCondition table.
 *
 * Data shape (set by Job.parseRegulationPerCondition on the server):
 *   { columns: ["targetF","regulator","omic","area","Group_<cond>",...],
 *     rows:    [[...], ...],
 *     truncated: bool }
 *
 * The view self-suppresses (returns a hidden container) when the model
 * carries no rpc data — i.e. for Pairwise jobs or jobs that predate Step 4
 * deployment. So the wiring in PA_Step3JobView can be unconditional.
 *
 * No paint/visualisation column. Regulator coefficients aren't continuous
 * expression series, so the existing heatmap pattern from Hub / Metabolite
 * views doesn't apply. The pathway visualisation (Step 4) is the canonical
 * place where target↔regulator relationships are painted; we don't
 * duplicate that here.
 */
function PA_Step3RegulationView() {
	this.name = "PA_Step3RegulationView";

	this.loadModel = function (model) {
		if (this.model !== null && this.model !== undefined) {
			this.model.deleteObserver(this);
		}
		this.model = model;
		this.model.addObserver(this);

		var payload = model.getRegulationPerConditionData();
		this.hasData = !!(payload && payload.rows && payload.rows.length);
		if (this.hasData) {
			this.columns = payload.columns;
			this.rows = payload.rows;
			this.truncated = !!payload.truncated;
			this.symbols = payload.symbols || {};
		}
	};

	// Tolerant blank-cell test: handles real null/undefined, the literal
	// string "None" (legacy server data — see Step 4 fix note in
	// PathwayAcquisitionJob.parseRegulationPerCondition), and empty string.
	var _isBlank = function (v) {
		return v === null || v === undefined || v === "" || v === "None";
	};

	// Numeric coefficient renderer: 3 decimals, left-aligned to match the
	// string columns. Treats NaN / blank / the "None" sentinel as empty.
	var _coefficientRenderer = function (val) {
		if (_isBlank(val)) return "";
		var n = Number(val);
		if (isNaN(n)) return "";
		return n.toFixed(3);
	};

	var _stringRenderer = function (val) {
		return _isBlank(val) ? "" : val;
	};

	this.initComponent = function () {
		var me = this;

		if (!this.hasData) {
			// Empty hidden container — the parent view can still grab .getComponent()
			// without a null check.
			this.component = Ext.widget({ xtype: "container", hidden: true });
			return this.component;
		}

		// Build a dynamic Ext.data.Model from the actual column list. Future
		// server-side additions to rpc_df (e.g. R^2) won't require a frontend
		// change. The model name is fixed; Ext.define with overwrite-on-redefine
		// keeps re-renders safe.
		var fields = this.columns.map(function (c) {
			return {
				name: c,
				type: c.indexOf("Group_") === 0 ? "float" : "string"
			};
		});
		Ext.define("PA.model.RegulationRow", {
			extend: "Ext.data.Model",
			fields: fields
		});

		// Convert rows-of-arrays → array of dicts keyed by column name.
		var columns = this.columns;
		var data = this.rows.map(function (row) {
			var rec = {};
			for (var i = 0; i < columns.length; i++) {
				rec[columns[i]] = row[i];
			}
			return rec;
		});

		var store = Ext.create("Ext.data.Store", {
			model: "PA.model.RegulationRow",
			data: data,
			pageSize: 100
		});

		// Symbol-aware renderer for Target/Regulator. When the server resolved
		// a gene symbol (FeatureNamesToKeggIDsMapper), render as "SYMBOL (AGI)"
		// — keeps the underlying ID visible for sorting/search/paper-ready copy.
		var symbols = this.symbols || {};
		var _idRenderer = function (val) {
			if (_isBlank(val)) return "";
			var key = String(val).toUpperCase();
			var symbol = symbols[key];
			if (symbol && symbol !== val) {
				return Ext.String.htmlEncode(symbol) +
				       ' <span style="color:#888;font-size:0.85em;">(' +
				       Ext.String.htmlEncode(val) + ')</span>';
			}
			return Ext.String.htmlEncode(val);
		};

		// Column definitions — fixed display order regardless of the server-side
		// column order. Group_* columns are appended in the order they appear in
		// the data (preserves condition labels from the user's experimental
		// design, e.g. "22" / "28" or "Control" / "Disease").
		var displayCols = [
			{ text: "Target",         dataIndex: "targetF",        flex: 1.4, sortable: true, renderer: _idRenderer },
			{ text: "Regulator",      dataIndex: "regulator",      flex: 1.4, sortable: true, renderer: _idRenderer },
			{ text: "Omic",           dataIndex: "omic",           flex: 1.0, sortable: true, renderer: _stringRenderer },
			{ text: "Area",           dataIndex: "area",           flex: 0.7, sortable: true, renderer: _stringRenderer },
			{ text: "Representative", dataIndex: "representative", flex: 1.2, sortable: true, renderer: _stringRenderer }
		];
		this.columns
			.filter(function (c) { return c.indexOf("Group_") === 0; })
			.forEach(function (c) {
				displayCols.push({
					text: c.replace(/^Group_/, "Coef_"),
					dataIndex: c,
					width: 120,
					sortable: true,
					renderer: _coefficientRenderer
				});
			});

		// --- "Find in pathways" hand-off -----------------------------------
		// Each row exposes two magnifiers that filter the sibling Pathway
		// Enrichment table down to the enriched pathways containing this row's
		// target / regulator (see PA_Step3PathwayTableView.searchFeatureInPathways).
		// Targets are gene-expression features and map onto pathway genes
		// directly; a regulator only matches when it is itself a pathway gene
		// (TFs frequently are; miRNA / methylation regulators are not) — the
		// table then simply shows no rows, which is itself informative.
		var findInPathways = function (featureID) {
			if (!featureID) return;
			var parent    = me.getParent && me.getParent();
			var tableView = parent && parent.pathwayTableView;
			if (tableView && tableView.searchFeatureInPathways) {
				tableView.searchFeatureInPathways(featureID);
			}
		};
		displayCols.push({
			xtype: "customactioncolumn",
			text: "In pathways",
			menuDisabled: true,
			sortable: false,
			width: 100,
			align: "center",
			items: [
				{
					icon: "fa-dot-circle-o",
					text: "",
					tooltip: "Show enriched pathways containing this <b>target</b>",
					style: "font-size:15px;margin-right:10px;",
					handler: function (grid, rowIndex) {
						findInPathways(grid.getStore().getAt(rowIndex).get("targetF"));
					}
				},
				{
					icon: "fa-bolt",
					text: "",
					tooltip: "Show enriched pathways containing this <b>regulator</b>",
					style: "font-size:15px;",
					handler: function (grid, rowIndex) {
						findInPathways(grid.getStore().getAt(rowIndex).get("regulator"));
					}
				}
			]
		});

		// --- Filters ---
		// Combined predicate: omic combo + free-text search. Stored on the
		// component so each control just updates its slice and re-applies.
		var filterState = { omic: "__all__", search: "" };
		var applyFilters = function () {
			store.clearFilter(true);  // suppress refresh until filterBy runs
			store.filterBy(function (rec) {
				if (filterState.omic !== "__all__" && rec.get("omic") !== filterState.omic) {
					return false;
				}
				if (filterState.search) {
					var s = filterState.search.toLowerCase();
					var target = String(rec.get("targetF") || "").toLowerCase();
					var regulator = String(rec.get("regulator") || "").toLowerCase();
					// Also match resolved symbols so users can search by either
					// the AGI ID or the gene name they recognise.
					var tSym = (symbols[String(rec.get("targetF") || "").toUpperCase()] || "").toLowerCase();
					var rSym = (symbols[String(rec.get("regulator") || "").toUpperCase()] || "").toLowerCase();
					if (target.indexOf(s) === -1 && regulator.indexOf(s) === -1 &&
					    tSym.indexOf(s) === -1 && rSym.indexOf(s) === -1) {
						return false;
					}
				}
				return true;
			});
		};

		var omicIdx = this.columns.indexOf("omic");
		var omicValues = Ext.Array.unique(this.rows.map(function (r) { return r[omicIdx]; }));
		var omicComboData = [["__all__", "All omics"]].concat(
			omicValues.map(function (o) { return [o, o]; })
		);

		var omicCombo = Ext.create("Ext.form.field.ComboBox", {
			fieldLabel: "Omic",
			labelWidth: 40,
			width: 240,
			store: omicComboData,
			value: "__all__",
			editable: false,
			listeners: {
				change: function (combo, val) {
					filterState.omic = val || "__all__";
					applyFilters();
				}
			}
		});

		var searchField = Ext.create("Ext.form.field.Text", {
			fieldLabel: "Search",
			labelWidth: 50,
			width: 320,
			emptyText: "Target / Regulator (ID or symbol)",
			enableKeyEvents: true,
			listeners: {
				// Debounce-free: typing is cheap with bufferedRenderer + in-memory store.
				change: function (field, val) {
					filterState.search = (val || "").trim();
					applyFilters();
				}
			}
		});

		// --- TSV download ---
		// Builds a TSV of the CURRENTLY VISIBLE rows (so the filter state is
		// honoured — users get exactly what they see). Format matches MORE_rpc_*.tab
		// on disk, so downloaded files can be diffed against the original.
		var jobID = this.model.getJobID();
		var downloadBtn = Ext.create("Ext.button.Button", {
			text: "Download (TSV)",
			iconCls: "fa fa-download",
			handler: function () {
				var visible = [];
				store.each(function (rec) { visible.push(rec); });
				var headerLine = columns.join("\t");
				var bodyLines = visible.map(function (rec) {
					return columns.map(function (c) {
						var v = rec.get(c);
						if (v === null || v === undefined) return "";
						return String(v);
					}).join("\t");
				});
				var tsv = headerLine + "\n" + bodyLines.join("\n") + "\n";
				var blob = new Blob([tsv], { type: "text/tab-separated-values" });
				var url = URL.createObjectURL(blob);
				var a = document.createElement("a");
				a.href = url;
				a.download = "MORE_RegulationPerCondition_" + jobID + ".tab";
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(url);
			}
		});

		var bbarItems = [omicCombo, "-", searchField, "->", downloadBtn];
		var tbar = null;
		if (this.truncated) {
			tbar = [{
				xtype: "tbtext",
				html: '<i class="fa fa-exclamation-triangle"></i> ' +
				      'Table truncated to 100,000 rows.'
			}];
		}

		this.component = Ext.widget({
			xtype: "container",
			border: 0,
			maxWidth: 1900,
			items: [{
				xtype: "gridpanel",
				cls: "contentbox",
				/* Every other card on Step 3 is laid out by a container carrying
				   `margin: 5px 10px`; this grid had none, so it started 10px left
				   of them and ended 10px right - the one block on a 3,000px page
				   whose edges did not coincide with anything above or below it,
				   and the reason its own heading sat off the rail the rest of the
				   page's headings share. */
				margin: "5 10",
				store: store,
				height: 350,
				autoScroll: true,
				bufferedRenderer: true,
				header: {
					xtype: "box",
					flex: 2,
					border: 0,
					// See the Hub Analysis header above: a minimum rather than a
					// height. This one carries a single long .infoTip that wraps to
					// three lines well before the window gets narrow.
					minHeight: 70,
					html: '<h2 id="MORERegulationSection">MORE regulation analysis</h2>' +
					      ' <span class="infoTip">Per-condition regression coefficients from MORE\'s ' +
					      '<b>RegulationPerCondition</b>. Each row is a target↔regulator pair; Group columns ' +
					      'are the coefficients for each experimental condition. Zero means no effect in that condition.</span>',
					style: { backgroundColor: "white" }
				},
				columns: displayCols,
				bbar: bbarItems,
				tbar: tbar,
				listeners: {
					// Bridge to the sibling network view: clicking a row pins
					// that row's (regulator, target) pair as the network's
					// highlight. The parent view (PA_Step3JobView) holds both
					// sibling views, and the network panel's IDs are prefixed
					// "reg:" / "tgt:" — see PA_Step3RegTargetNetworkView's
					// buildBipartiteGraph.
					itemclick: function (grid, record, item, index, e) {
						// The "In pathways" action icons carry their own handlers;
						// don't also pin the network edge when one is clicked.
						if (e && e.getTarget && e.getTarget(".x-action-col-icon")) {
							return;
						}
						var reg = record.get("regulator");
						var tgt = record.get("targetF");
						if (!reg || !tgt) return;
						var parent  = me.getParent && me.getParent();
						var network = parent && parent.regTargetNetworkView;
						if (network && network._focusEdge) {
							network._focusEdge("reg:" + reg, "tgt:" + tgt);
						}
					}
				}
			}]
		});

		return this.component;
	};

	this.updateObserver = function () {
		// No-op for now — the rpc data is immutable for the lifetime of a Step 3
		// session. If the model is ever re-loaded, PA_Step3JobView will rebuild
		// the view via loadModel + initComponent.
	};

	return this;
}
PA_Step3RegulationView.prototype = new View();


/**
 * The colour range for one observed (low, high) pair.
 *
 * Every branch of getMinMax below used to do this inline, identically:
 *
 *     max = ((high < 0) ? 0 : Math.max(Math.abs(low), Math.abs(high)));
 *     min = ((low  > 0) ? 0 : -max);
 *
 * i.e. force the range to be symmetric about zero, always. For data that
 * crosses zero that is exactly right and is kept: bwr and rbg are DIVERGING
 * scales whose whole meaning is a zero midpoint, and a range of -2..+8 drawn
 * asymmetrically would paint -2 and +2 in different intensities and claim a
 * difference the data does not contain.
 *
 * For data that never crosses zero it threw the range away. An omic measured
 * 1.93..20.93 -- all positive, which is the normal shape for abundances,
 * counts, intensities and MORE's regulator expression -- came back as 0..20.93,
 * so:
 *
 *   * `value > 0` in getColor is true for every point, so red is pinned at 255
 *     and the entire blue half of blue-white-red is unreachable;
 *   * the 0..1.93 stretch at the pale end carries no data at all, and the
 *     interquartile range (half the points, 10.99..13.73) was compressed into
 *     rgb(255,121,121)..rgb(255,88,88) -- 33 of 255, 13% of the strip. Whole
 *     diagrams came out one flat red.
 *
 * Neither could be worked around from the interface. The custom-range slider
 * runs through the same clamp: dragging its low end to 5 sets
 * dataDistributionSummaries[11] = 5, `(5 > 0)` is true, and min is 0 again --
 * the control silently did nothing.
 *
 * And all-negative data was worse than compressed, it was broken: high < 0 made
 * max 0, low < 0 made min -0, and getColor divided by (absMin - min) = 0 and
 * returned the string "rgb(255, 255,-Infinity)" for every value.
 *
 * So: symmetric when the data crosses zero, the observed range when it does
 * not.
 *
 * @param {Number} low
 * @param {Number} high
 * @returns {Object} {min, max}
 */
var paColourRange = function (low, high) {
	/* An inverted pair is not impossible -- [11] and [12] come from a slider --
	   and it would otherwise flow into a negative denominator downstream. */
	if (low > high) {
		var swap = low; low = high; high = swap;
	}

	if (low < 0 && high > 0) {
		/* Diverging: keep the symmetry, so equal magnitudes read equally. */
		var extent = Math.max(Math.abs(low), Math.abs(high));
		return {min: -extent, max: extent};
	}

	/* Sequential: the data's own range is the ramp. */
	return {min: low, max: high};
};

/**
 * The colour range for a set of metagene trends, from the trends themselves.
 *
 * Every other caller colours a feature against the distribution of the omic
 * that feature came from, which is right, because they are the same quantity.
 * A metagene is not: it is a component describing how a whole cluster moves,
 * centred on zero and on its own scale entirely. It needs its own range, and
 * this is the only place that computes one.
 *
 * No clipping: absMin/absMax are the same as min/max, so getColor's outlier
 * term is zero everywhere rather than being measured against a percentile the
 * trends were never summarised at. There is no p10/p90 for a metagene.
 *
 * @param {Array} metagenes  [{values: [...]}, ...]
 * @returns {Object} the {min, max, absMin, absMax} getColor expects
 */
var paMetageneLimits = function (metagenes) {
	var low = null, high = null;

	(metagenes || []).forEach(function (metagene) {
		((metagene && metagene.values) || []).forEach(function (raw) {
			var value = Number(raw);
			/* Metagene values arrive as strings and a cluster with a gap in it
			   yields NaN, which would poison both ends of the range and take
			   every colour on the chart with it. */
			if (!isFinite(value)) { return; }
			if (low === null || value < low) { low = value; }
			if (high === null || value > high) { high = value; }
		});
	});

	if (low === null) {
		/* Nothing usable. A degenerate range makes paRampPosition return 0 for
		   everything, which is the pale end -- honest for "no data" and, unlike
		   the alternative, a valid colour. */
		return {min: 0, max: 0, absMin: 0, absMax: 0};
	}

	var range = paColourRange(low, high);
	return {min: range.min, max: range.max,
	        absMin: range.min, absMax: range.max};
};

/**
		* This function returns the MIN/MAX values that will be used as references
		* for painting (i.e. min and max colors).
		*
		* @param {type} dataDistributionSummaries
		* @param {type} option [absoluteMinMax, riMinMax, localMinMax, p10p90]
		* @returns {Array}
		*/
var getMinMax = function(dataDistributionSummaries, option) {
	// The two last positions are not always present, and are added when restoring
	// visual settings options on some views. Thus, they are not saved in the omicSummary
	// property, but on visual settings table.
	//
	//   0        1       2    3    4    5     6,   7   8      9        10      11          12
	//[MAPPED, UNMAPPED, MIN, P10, Q1, MEDIAN, Q3, P90, MAX, MIN_IR, Max_IR, MIN_CUSTOM, MAX_CUSTOM]]
	var range, absRange;

	// absMin/absMax are the FULL observed range and are only consulted when the
	// selected reference clips (p10p90, riMinMax, custom): getColor measures how
	// far past the clip an outlier sits against them. They therefore have to be
	// derived the same way, or a clipped range could sit outside the range it is
	// measured against.
	absRange = paColourRange(dataDistributionSummaries[2], dataDistributionSummaries[8]);

	if (option === "absoluteMinMax") { //IF USE MIN MAX FOR ORIGINAL DATA (INCLUDE OUTLIERS)
		range = paColourRange(dataDistributionSummaries[2], dataDistributionSummaries[8]);
	} else if (option === "riMinMax") { //IF USE MIN MAX FOR INTERQUARTIL RANGE (OMIT OUTLIERS)
		range = paColourRange(dataDistributionSummaries[9], dataDistributionSummaries[10]);

		//    } else if (option === "localMinMax") {//IF USE MIN MAX FOR INTERQUARTIL RANGE (OMIT OUTLIERS)
		//        //TODO: IMPLEMENT
	} else if (option === "p10p90") { //IF USE PERCENTILES 10 AND 90
		range = paColourRange(dataDistributionSummaries[3], dataDistributionSummaries[7]);
		absRange = paColourRange(dataDistributionSummaries[2], dataDistributionSummaries[8]);
	} else if (option == "custom") { //USE SLIDER CUSTOM VALUES
		if (dataDistributionSummaries.length < 12) {
			console.error("No custom range provided: using absolute min/max");

			range = absRange;
		} else {
			range = paColourRange(dataDistributionSummaries[11], dataDistributionSummaries[12]);
		}
	} else {
		console.error("getMinMax:" + option + "Not implemented!!");
		debugger;
		range = absRange;
	}

	return {
		min: range.min,
		max: range.max,
		absMin: absRange.min,
		absMax: absRange.max
	};

};

/**
		* This function returns the corresponding RGB color (for heatmap) for
		* a given value, based var getColor = on a min/max values.
		*
		* @param {type} min
		* @param {type} max
		* @param {type} value
		* @param {String} colorScale the color scale (RED-BLACK-GREEN -> "rbg", BLUE-WHITE-RED -> "bwr")
		* @returns {String}
		*/
/**
 * How far `value` sits from the pale end of the ramp, as 0..1.
 *
 * Two problems live here, and they are the same problem.
 *
 * Every scale below used to divide by `limits.max` or `limits.min` directly.
 * For an omic whose values never cross zero -- MORE's regulator expression is
 * the case that surfaced it, 0.00 to 14.71 -- `limits.min` is 0, so a value of
 * exactly 0 computed 0/0 and returned `rgb(NaN, NaN,NaN)`. A single NaN stop
 * voids an entire CSS gradient, which is why the colour legend beside those
 * heatmaps rendered as an empty white box rather than a ramp.
 *
 * The second problem is what the ramp MEANS there. bwr and rbg are diverging
 * scales built around a zero midpoint; on all-positive data the whole blue (or
 * green) half is unreachable, and anchoring at zero wastes the pale end too --
 * an omic spanning 5..14.71 started at pink, so a third of the scale carried
 * no data. When the range does not cross zero the ramp is stretched across the
 * real min..max instead, which uses the whole strip and leaves diverging data
 * -- where the zero anchor is the entire point -- untouched.
 */
var paRampPosition = function (limits, value) {
	var crossesZero = (limits.min < 0 && limits.max > 0);
	var lo, hi;

	if (crossesZero) {
		/* Diverging: distance from zero, against whichever end this side of
		 * the axis is bounded by. Unchanged behaviour. */
		lo = 0;
		hi = (value > 0) ? limits.max : limits.min;
	} else {
		/* Sequential: the observed range is the ramp, anchored at the end
		 * NEARER ZERO. For all-positive data that is the minimum, which is
		 * what "palest is the smallest value" means. For all-negative data it
		 * is the maximum: -12..-5 anchored at the minimum would paint -12
		 * palest and -5 the deepest blue, i.e. announce the least negative
		 * point as the strongest downward effect. Saturation tracks distance
		 * from zero in both directions, which is the one thing the diverging
		 * scale is for. */
		if (Math.abs(limits.min) <= Math.abs(limits.max)) {
			lo = limits.min;
			hi = limits.max;
		} else {
			lo = limits.max;
			hi = limits.min;
		}
	}

	if (hi === lo) {
		/* A degenerate range has no position to report; treat every value as
		 * the pale end rather than emitting NaN. */
		return 0;
	}

	/* Clamped below, NOT Math.abs. The absolute value was safe only while `lo`
	 * was always 0 and the ramp could not be entered from underneath. Now that
	 * `lo` can be a real clip -- p10 = 8.5 on data reaching down to 1.93 --
	 * a point below the clip gives a negative position, and abs() would fold
	 * it back up the ramp and paint the SMALLEST value the most intense. It
	 * belongs at the pale end. Positions above 1 are left alone: getColor
	 * reads them to darken outliers past the clip. */
	var position = (value - lo) / (hi - lo);

	return (position < 0) ? 0 : position;
};

var getColor = function (limits, value, colorScale) {
			var red, blue, green;
			//RED-BLACK-GREEN
			if (colorScale === "rbg") {
				var percentage = paRampPosition(limits, value);
				green = (value > 0) ? 0 : 255 * percentage;
				red = (value > 0) ? 255 * percentage : 0;
				blue = 0;
			} else if (colorScale === "bwr") {
				//BLUE-WHITE-RED
				var percentage = Math.max(0, 1 - paRampPosition(limits, value));

				var outlierPercentage = paOutlierFraction(limits, value);
				green = percentage * 255;
				red = (value > 0) ? ((value > limits.max) ? 255 - (outlierPercentage * 128) : 255) : (percentage * 255);
				blue = (value < 0) ? ((value < limits.min) ? 255 - (outlierPercentage * 128) : 255) : (percentage * 255);

			} else if (colorScale === "bwr2") {
				//BLUE-WHITE-RED
				var percentage = Math.max(0, 1 - paRampPosition(limits, value));
				var outlierPercentage = paOutlierFraction(limits, value);

				green = (value > limits.max || value < limits.min) ? (outlierPercentage * 128) : (percentage * 255);
				red = (value > 0) ? 255 : (percentage * 255);
				blue = (value > 0) ? (percentage * 255) : 255;
			} else {
				console.error("Color scale " + colorScale + "Not implemented!!");
				debugger;
			}
			/* Whatever the arithmetic above decided, what leaves here is a
			   colour. Channels were free to run out of range and did: measured
			   on paintomics.uv.es, `rgb(255, 255,-402)` and `rgb(0, 0,-2744)`,
			   and before the ramp was clamped, `rgb(247, 247,-Infinity)`.
			   Neither is a colour. Chrome clamps the first to yellow and
			   rejects the second outright, painting it black -- so cells that
			   should have been pale showed as two loud, arbitrary colours.

			   The cause is upstream and there is more than one of it: a value
			   outside [absMin, absMax] makes the outlier term above exceed 1,
			   and every caller that colours one quantity against another
			   quantity's distribution can produce that. Two such call sites
			   have been found and fixed so far -- the metagene trend heatmap,
			   and this file's other generateHeatmap -- which is the reason for
			   putting the guarantee HERE instead: getColor is the one place
			   every colour in the application comes from, so this is the only
			   place the invariant can be stated once and hold for all of them.

			   Clamping is not a substitute for fixing a caller that is asking
			   the wrong question -- it turns a broken colour into the nearest
			   real one, which is honest for "off the end of the scale" and
			   nothing like as wrong as black. */
			return "rgb(" + paChannel(red) + ", " + paChannel(green) + "," + paChannel(blue) + ")";
		};

/**
 * One RGB channel: a whole number in 0..255, whatever it was handed.
 *
 * NaN maps to 0 rather than propagating. A NaN channel makes the whole
 * `rgb(...)` string invalid, and a single invalid stop voids an entire CSS
 * gradient -- which is how the colour legend beside these heatmaps once
 * rendered as an empty white box rather than a ramp.
 */
/**
 * How far past the clipped range a value sits, as 0..1.
 *
 * Only meaningful when the colour reference clips (p10p90, riMinMax, custom):
 * it is the distance from the clip to the value, over the distance from the
 * clip to the real extreme, and getColor uses it to darken outliers.
 *
 * It is a FRACTION, so it cannot exceed 1 -- but nothing said so, and the
 * arithmetic exceeds it freely whenever `value` falls outside
 * [absMin, absMax]. Measured on production: 5.19 and 21.4, which multiplied by
 * 128 and subtracted from 255 gave -410 and -2744. Callers that colour one
 * quantity against another quantity's distribution produce exactly that, and
 * there is more than one of them.
 *
 * A denominator of zero means the reference does not clip at all, so there is
 * no "past the clip" to measure and the answer is 0 -- previously this was
 * value/0, i.e. Infinity, and thence an -Infinity channel.
 */
var paOutlierFraction = function (limits, value) {
	var clip = (value > 0) ? limits.max : limits.min;
	var extreme = (value > 0) ? limits.absMax : limits.absMin;
	var span = extreme - clip;

	if (!span) { return 0; }

	var fraction = Math.abs((value - clip) / span);

	if (!isFinite(fraction)) { return 0; }

	return (fraction > 1) ? 1 : fraction;
};

var paChannel = function (value) {
	var rounded = Math.round(value);
	if (isNaN(rounded)) { return 0; }
	if (rounded < 0) { return 0; }
	if (rounded > 255) { return 255; }
	return rounded;          /* Infinity and -Infinity fall out of the two above */
};

/* =====================================================================
 * Shared heatmap / line-chart labelling helpers.
 *
 * These live next to getMinMax() and getColor() because they have the same
 * lifetime and the same two consumers: the charts drawn in PA_Step3Views.js
 * and the ones drawn in PA_Step4Views.js. app.js loads step 3 before step 4
 * and both files are evaluated long before any chart is drawn, so step 4 can
 * call these the same way it already calls getColor().
 * ===================================================================== */

/**
 * Escapes a string so it is safe inside a double-quoted HTML attribute.
 * Needed because the row labels below put the untruncated feature name in a
 * title attribute, and feature names come from user-uploaded files.
 */
var paEscapeAttribute = function (text) {
	return String((text === undefined || text === null) ? "" : text)
		.replace(/&/g, "&amp;")
		.replace(/"/g, "&quot;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;");
};

/**
 * Truncation that keeps the END of the string.
 *
 * Every truncation in these two files used to keep the head - "first 14", or
 * "5 head + 4 tail". For a column of Ensembl gene identifiers that keeps the
 * species prefix that every single row shares and throws away the digits that
 * tell the rows apart: a heatmap of 164 distinct identifiers rendered as 164
 * copies of "ENSMU...7533". The discriminating characters of an accession
 * (ENSMUSG00000036438), of a gene symbol pair (Calm1 / Calm2) and of a
 * replicate column (Ctrl_R1 / Ctrl_R2) are all at the end, so the end is what
 * survives here.
 *
 * A leading relevance marker ("* " / "^ ") is held aside and re-attached: it
 * is the flag that says the row is significant, and front-ellipsising would
 * silently drop it.
 */
var paTruncateTail = function (text, maxChars) {
	text = String((text === undefined || text === null) ? "" : text);

	var markers = text.match(/^[\*\^\s]*/)[0];
	var body = text.substring(markers.length);

	if (!maxChars || markers.length + body.length <= maxChars) {
		return text;
	}

	var budget = Math.max(1, maxChars - markers.length - 1);

	return markers + "…" + body.substring(body.length - budget);
};

/**
 * Keep the FRONT of a label, ellipsis at the end.
 *
 * The mirror of paTruncateTail, and which one is right depends entirely on
 * where the information sits. An input identifier is a shared prefix plus a
 * discriminating tail (every mouse gene starts "ENSMUSG0000"), so the tail is
 * what must survive. A display name is the opposite: "Slc22a3 (20497)" front-
 * truncated reads "…2a3 (20497)", which names nothing. Ellipsising both lines
 * the same way was measured on the live app -- Gnai3, Adcy9 and Prkaca all came
 * out as "…ai3", "…cy9", "…aca".
 */
var paTruncateHead = function (text, maxChars) {
	text = String((text === undefined || text === null) ? "" : text);

	var markers = text.match(/^[\*\^\s]*/)[0];
	var body = text.substring(markers.length);

	if (!maxChars || markers.length + body.length <= maxChars) {
		return text;
	}

	var budget = Math.max(1, maxChars - markers.length - 1);

	return markers + body.substring(0, budget) + "…";
};

/**
 * The JobInstance a view belongs to, or null.
 *
 * The chart-drawing views are mounted under the step-3 job view, under the
 * step-4 job view, or (for the pathway details panel) under the network view,
 * and getParent() walks up until it runs out of parents, so asking for the
 * wrong one is safe. Everything downstream treats null as "no header
 * available" and falls back to positional labels rather than failing.
 */
var paJobModel = function (view) {
	var jobView = null;

	try {
		if (view && view.getParent) {
			jobView = view.getParent("PA_Step4JobView") || view.getParent("PA_Step3JobView");
		}
	} catch (error) {
		console.error(Date.logFormat() + " could not resolve the job view for condition labels.", error);
		return null;
	}

	return (jobView && jobView.getModel) ? jobView.getModel() : null;
};

/**
 * The name a heatmap row should carry for a feature: its symbol together with
 * the KEGG identifier that links the symbol to the uploaded identifier.
 *
 * The symbol on its own does not identify a row. The identifier map is
 * many-to-many, so one uploaded identifier can be matched to several KEGG
 * genes: the mouse Rap1 heatmap printed 166 rows for 164 identifiers, two of
 * them reading "Calm2 # ENSMUSG00000036438" and "Calm1 # ENSMUSG00000036438"
 * - the same measurement under two symbols - while a third row paired "Calm1"
 * with a different identifier entirely. Painting one measurement onto several
 * KEGG boxes is what the mapping says; the label just has to say which box.
 *
 * The id is appended on the symbol side because every consumer of these
 * labels splits them on "#" and expects the identifier on the right.
 */
var paFeatureRowName = function (feature) {
	if (!feature) {
		return "";
	}

	var name = (feature.getName ? feature.getName() : feature.name);
	var featureID = (feature.getID ? feature.getID() : feature.ID);

	name = String((name === undefined || name === null) ? "" : name);

	if (featureID && String(featureID) !== name) {
		return name + " (" + featureID + ")";
	}

	return name;
};

/**
 * The column headers of one omic, in the replicate/sample mode the user has
 * selected, as ["<id column>", "<condition 1>", ...]. Empty when unavailable
 * (a job model restored from an older session may not carry them).
 */
var paOmicHeaders = function (jobModel, omicName) {
	if (!jobModel || !jobModel.getOmicHeaders) {
		return [];
	}

	var mode = jobModel.getReplicateMode ? jobModel.getReplicateMode() : "replicates";
	var headers = jobModel.getOmicHeaders(null, mode) || {};

	return headers[omicName] || [];
};

/**
 * The column header shared by several omics, or an empty array if they do not
 * all agree on it.
 *
 * The per-feature popup stacks one row per omic under a single x axis. Omics
 * are uploaded independently and need not share a design, so labelling that
 * axis from whichever omic happened to be first would print one omic's
 * condition names over another omic's cells. An unlabelled axis is bad; a
 * confidently mislabelled one is worse, so disagreement falls back to
 * positional labels.
 */
var paSharedOmicHeader = function (jobModel, omicNames, columnCount) {
	var reference = null, signature = null, header, current, i;

	for (i = 0; i < omicNames.length; i++) {
		header = paOmicHeaders(jobModel, omicNames[i]);

		if (header.length < columnCount + 1) {
			return [];
		}

		current = header.slice(1, columnCount + 1).join("");

		if (signature === null) {
			signature = current;
			reference = header;
		} else if (signature !== current) {
			return [];
		}
	}

	return reference || [];
};

/**
 * The x-axis fragment shared by every heatmap and line chart that plots one
 * column per experimental condition.
 *
 * All of them used to push "Timepoint 1..n" and then set labels.enabled to
 * false, so a six-condition job drew six anonymous columns and the only way
 * to tell T02h from T18h was to hover a cell - even though the real names
 * travel with the job the whole time, in the uploaded file's header row, and
 * the tooltips already print them.
 *
 * The labels cannot merely be switched back on. These charts sit in
 * containers as narrow as 230px minus a 100px label gutter - about 21px per
 * column - where horizontal labels overlap and Highcharts starts dropping
 * every other one, which looks exactly like the unlabelled axis being fixed.
 * So the rotation and the length cap are part of the same change, applied
 * here once instead of at each of the seven call sites.
 *
 * @param {Number} columnCount  conditions actually plotted
 * @param {Array}  omicHeader   the omic's header row, id column first
 * @param {Object} options      {maxChars, rotation, fontSize}
 */
/**
 * The values to plot for one feature, in the same space as `omicHeader`.
 *
 * An OmicValue can carry two parallel series: `values`, one per uploaded
 * column, and `sampleValues`, one per biological sample once a replicate or
 * design grouping has been applied. `paOmicHeaders` returns whichever header
 * matches the job's current mode, so a renderer that labels its axis from that
 * header and then plots `values` unconditionally is labelling one space with
 * the names of the other.
 *
 * Measured on the bundled MORE example after the design grouping landed: the
 * heatmap drew 36 replicate columns and captioned the first twelve of them
 * "Ctr_0H … Ik_24H" -- so column 2 was labelled Ctr_2H while holding
 * Batch_2_Ctr_0H. Wrong labels on real data beat missing ones only in the
 * sense that they are harder to notice.
 *
 * Choosing by LENGTH rather than by mode is deliberate: it is the property the
 * axis actually depends on, and it stays correct for an omic that has no
 * aggregation, one whose aggregation is stale, and one rendered by a caller
 * that never learned about modes.
 */
/**
 * Which neighbour list a "Neighbouring features" request resolves to, or the
 * reason there is none -- in words the panel can print.
 *
 * The Step-4 details panel asked for the list inline and guarded each way it
 * could come back empty with `console.warn(...); return`. Four of them, and the
 * first one every user meets is the level box: it opens blank, so the very
 * first click lands on `neighbourMap[featureID][""]`, warns to a console nobody
 * has open, and draws nothing. From the outside that is a button that does not
 * work, which is exactly how it was reported.
 *
 * Deciding here, and returning the reason rather than nothing, is what lets the
 * panel say which of the four it hit. They are genuinely different situations:
 * a level that was never typed is the user's next action, a species installed
 * without hubData is not something they can fix, and a metabolite that KEGG's
 * interaction network does not cover is a fact about the metabolite.
 *
 * `level` is checked against /^[1-4]$/ on the trimmed string rather than parsed:
 * `parseInt("1.9")` and `parseInt("1e9")` are both 1, and the input is a
 * number field the user can type anything into.
 *
 * @param {Object} request {featureID, featureType, neighbourMap, level}
 * @return {Object} {ok:true, level, neighbours} | {ok:false, reason, message}
 */
var paNeighbourRequest = function (request) {
	request = request || {};

	var featureID = request.featureID;
	var featureType = (request.featureType === undefined || request.featureType === null)
		? "" : String(request.featureType).toLowerCase();
	var neighbourMap = request.neighbourMap;
	var typed = (request.level === undefined || request.level === null)
		? "" : String(request.level).trim();

	/* Feature type first: no level will ever help a gene box, so saying
	   "enter a level" there would be a wrong instruction, not a partial one. */
	if (featureType !== "" && featureType.indexOf("compound") === -1) {
		return {
			ok: false, reason: "not-a-metabolite",
			message: "Neighbouring features are defined for metabolites only — " +
				"they come from the KEGG compound interaction network. This box holds " +
				"features of another type."
		};
	}

	if (typed === "") {
		return {
			ok: false, reason: "no-level",
			message: "Enter how many network steps to look out from this metabolite " +
				"(1 to 4), then press Show Features."
		};
	}

	if (!/^[1-4]$/.test(typed)) {
		return {
			ok: false, reason: "bad-level",
			message: "Neighbours are held for 1 to 4 network steps. “" + typed +
				"” is not one of them."
		};
	}

	var level = parseInt(typed, 10);

	if (!neighbourMap || Object.keys(neighbourMap).length === 0) {
		return {
			ok: false, reason: "no-map", level: level,
			message: "No metabolite interaction network is available for this " +
				"analysis. It comes from the species' hubData, which not every " +
				"installed species ships."
		};
	}

	/* JSON object keys are strings; the level is read back as a number above. */
	var byStep = neighbourMap[featureID];
	if (!byStep) {
		return {
			ok: false, reason: "not-in-network", level: level,
			message: "This metabolite is not in the KEGG compound interaction " +
				"network, so it has no neighbours to show."
		};
	}

	var neighbours = byStep[level] !== undefined ? byStep[level] : byStep[String(level)];
	if (!neighbours || !neighbours.length) {
		return {
			ok: false, reason: "no-neighbours-at-level", level: level,
			message: "This metabolite has no neighbours at " + level + " step" +
				(level === 1 ? "" : "s") + "."
		};
	}

	return {ok: true, level: level, neighbours: neighbours};
};

/**
 * OmicValues rendered as the plain rows the Step-4 details heatmap/plot pair
 * reads -- the same shape `addTableEntrie()` builds.
 *
 * `globalExpressionData` arrives as JSON and `setGlobalExpressionData` turns
 * every entry into an OmicValue, on which `isRelevant` and
 * `isRelevantAssociation` are METHODS. The neighbours panel handed those
 * instances straight to a renderer written for `addTableEntrie` rows, where the
 * same two names are booleans. Nothing threw -- the names, ids and values are
 * plain properties either way, so the charts drew -- but every test of them
 * silently inverted:
 *
 *   `omicsValue.isRelevant === true`            a function is not true, so no
 *                                               row ever got its `*` marker
 *   `x.isRelevant || x.isRelevantAssociation`   a function is truthy, so the
 *                                               "Only relevant" checkbox kept
 *                                               all 69 rows and looked dead
 *
 * and `significance` was absent entirely, so the per-condition stars the rest
 * of the panel draws were missing here. Converting at the boundary fixes all
 * three at once and keeps one row shape in the renderer.
 *
 * @param {Array}  omicValues    OmicValue instances (or already-plain rows)
 * @param {String} replicateMode "replicates" | "samples"
 */
var paNeighbourRows = function (omicValues, replicateMode) {
	var rows = [];

	for (var i = 0; i < (omicValues ? omicValues.length : 0); i++) {
		var omicValue = omicValues[i];
		if (!omicValue) {
			continue;
		}

		var values = omicValue.getValues ? omicValue.getValues(replicateMode) : omicValue.values;

		/* One boolean per drawn cell, same contract as addTableEntrie(). */
		var significance = [];
		for (var c = 0; c < (values ? values.length : 0); c++) {
			significance.push(omicValue.isRelevant
				? omicValue.isRelevant(c, replicateMode) === true
				: false);
		}

		rows.push({
			keggName: omicValue.keggName !== undefined ? omicValue.keggName : omicValue.inputName,
			inputName: omicValue.inputName,
			originalName: omicValue.originalName,
			isRelevant: omicValue.isRelevant
				? omicValue.isRelevant(undefined, replicateMode) === true
				: omicValue.relevant === true,
			isRelevantAssociation: omicValue.isRelevantAssociation
				? omicValue.isRelevantAssociation() === true
				: omicValue.relevantAssociation === true,
			significance: significance,
			/* No `sampleValues` on purpose: the mode is already applied above,
			   and paValuesForHeader() would otherwise apply it a second time. */
			values: values
		});
	}

	return rows;
};

var paValuesForHeader = function (omicValue, omicHeader) {
	/* Position 0 of a header row is the feature-id column. */
	var labelled = (omicHeader && omicHeader.length > 1) ? omicHeader.length - 1 : 0;
	var samples = (omicValue.getSampleValues ? omicValue.getSampleValues() : omicValue.sampleValues);

	if (labelled && Array.isArray(samples) && samples.length === labelled) {
		return samples;
	}
	return omicValue.values;
};

var paConditionAxis = function (columnCount, omicHeader, options) {
	options = options || {};

	/* A header that does not describe the columns being drawn is not a partial
	 * label, it is a wrong one: pasting its first N names onto unrelated
	 * columns and padding the rest with "Condition N" reads as authoritative.
	 * Positional labels are the honest fallback -- same rule paSharedOmicHeader
	 * applies when two omics disagree. */
	if (omicHeader && omicHeader.length > 1 && (omicHeader.length - 1) !== columnCount) {
		omicHeader = null;
	}

	var maxChars = options.maxChars || 12;
	var categories = [];
	var name, i;

	for (i = 0; i < columnCount; i++) {
		/* Column i is header[i + 1]: position 0 of the header row is the
		 * feature-id column ("#geneID"). */
		name = (omicHeader && omicHeader[i + 1] !== undefined && omicHeader[i + 1] !== null && omicHeader[i + 1] !== "")
			? String(omicHeader[i + 1])
			: ("Condition " + (i + 1));
		categories.push(name);
	}

	return {
		categories: categories,
		labels: {
			enabled: true,
			rotation: (options.rotation === undefined) ? -45 : options.rotation,
			align: "right",
			/* step:1 forbids Highcharts' automatic thinning. A label it decides
			 * to skip is indistinguishable from no label at all. */
			step: 1,
			style: {fontSize: (options.fontSize || "9px")},
			formatter: function () {
				return paTruncateTail(this.value, maxChars);
			}
		}
	};
};

/**
 * One two-line heatmap row label: display name above, the identifier it was
 * matched from below.
 *
 * The two lines are ellipsised from opposite ends, because the information is
 * at opposite ends: the display name keeps its front (paTruncateHead) and the
 * identifier keeps its tail (paTruncateTail). The full untruncated pair goes
 * into a title attribute, because the tooltip is not a fallback for what is
 * lost here - it truncates to 12 characters as well.
 */
var paRowLabel = function (primary, secondary, options) {
	options = options || {};

	var width = options.width || 100;
	var maxChars = options.maxChars || 14;
	var replaceSymbols = {
		"*": '<i class="relevantFeature"></i>',
		"^": '<i class="relevantAssociationFeature"></i>'
	};

	primary = String((primary === undefined || primary === null) ? "" : primary);
	secondary = String((secondary === undefined || secondary === null) ? "" : secondary);

	/* Regulator rows embed markup (e.g. "WRKY40<br><span ...>AT2G25000</span>")
	 * in the primary side; slicing characters there would cut a tag in half, so
	 * those are rendered verbatim. */
	var primaryHasHTML = primary.indexOf("<") >= 0;
	var renderedPrimary = primaryHasHTML
		? primary
		: paTruncateHead(primary, maxChars).replace(/[\*\^]/g, function (c) { return replaceSymbols[c]; });
	var renderedSecondary = paTruncateTail(secondary, maxChars);
	var fullText = (primaryHasHTML ? primary.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim() : primary) +
		(secondary ? "  |  " + secondary : "");

	return '<span title="' + paEscapeAttribute(fullText) + '" style="width: ' + width + 'px;display: block;text-align: right;">' +
		renderedPrimary +
		'</br><i class="tooltipInputName yAxisLabel">' + renderedSecondary + '</i></span>';
};

/**
 * The colour scale a heatmap was painted with, as a standalone HTML strip.
 *
 * The heatmaps all carry legend:{enabled:false} for a good reason - a
 * Highcharts legend lists series, and there is one series per row, so it would
 * have printed hundreds of entries. The side effect was that nothing on screen
 * said what red or blue meant. This draws the real ramp by sampling the very
 * getColor() the cells were painted with, so it cannot drift away from them.
 *
 * Styles are inline because this markup is injected into containers owned by
 * several different views, none of which has a stylesheet rule for it.
 */
var paColorLegend = function (limits, colorScale, options) {
	options = options || {};

	if (!limits || !isFinite(limits.min) || !isFinite(limits.max) || limits.min === limits.max) {
		/* A degenerate range (a single-valued omic, or a summary that never
		 * loaded) would produce "rgb(NaN,...)" stops, and one invalid stop
		 * voids the whole CSS gradient. Draw nothing instead. */
		return "";
	}

	var steps = options.steps || 24;
	var barWidth = options.width || 120;
	var stops = [];
	var i, ratio;

	for (i = 0; i <= steps; i++) {
		ratio = i / steps;
		stops.push(getColor(limits, limits.min + ratio * (limits.max - limits.min), colorScale) +
			" " + Math.round(ratio * 100) + "%");
	}

	var format = function (value) {
		return (Math.abs(value) >= 1000 || (value !== 0 && Math.abs(value) < 0.01))
			? value.toExponential(1)
			: value.toFixed(2);
	};

	return '<div class="paColorLegend" style="display:inline-block;font-size:10px;color:#555;margin:2px 0 6px 0;white-space:nowrap;">' +
		'<span style="vertical-align:middle;">' + format(limits.min) + '</span>' +
		'<span title="Colour scale used by this heatmap. Values outside the range are drawn as outliers." ' +
		'style="display:inline-block;vertical-align:middle;margin:0 5px;width:' + barWidth + 'px;height:10px;border:1px solid #999;' +
		'background:linear-gradient(to right,' + stops.join(",") + ');"></span>' +
		'<span style="vertical-align:middle;">' + format(limits.max) + '</span>' +
		'</div>';
};


var renderFunctionLimit = function (value, metadata, record) {
		var myToolTipText = "<b style='display:block; width:200px'>" + "Metabolism" + "</b>";
		metadata.style = "height: 40px; font-size:12px;"

		//IF THERE IS NOT DATA FOR THIS PATHWAY, FOR THIS OMIC, PRINT A '-'
		if (value === "-" || value == undefined || isNaN(value)) {
			myToolTipText = myToolTipText + "<i>No data for this pathway</i>";
			metadata.tdAttr = 'data-qtip="' + myToolTipText + '"';
			metadata.style += "background-color:var(--pa-cell-empty,#D4D4D4);";
			return "-";
		}
		//ELSE, GENERATE SUMMARY TIP

		//RENDER THE VALUE -> IF LESS THAN 0.05, USE SCIENTIFIC NOTATION
		var renderedValue = (value > 0.001 || value === 0) ? parseFloat(value).toFixed(5) : parseFloat(value).toExponential(4);
		var omicName = "-" + metadata.column.text.toLowerCase().replace(/ /g, "-").replace(/<\/br>/g, "-");

		if (value <= 0.1) {
			var color = Math.round(225 * (value / 0.1));
			var tint = 172 + Math.round(color * 0.32);
				metadata.style += "background-color:rgb(255, " + tint + "," + tint + "); color:#9B1C1C;";
		}

		try {
			var totalFeatures = record.data.totalFeatures;
			var condIdx = metadata.column.conditionIndex;
			var totalRelevant = (condIdx !== undefined && Array.isArray(record.data.totalRelevant)) ? record.data.totalRelevant[condIdx] : (Array.isArray(record.data.totalRelevant) ? record.data.totalRelevant[0] : record.data.totalRelevant);

			// Keep compatibility with old jobs
			var foundFeatures = record.data.foundFeatures;
			var foundRelevant = (condIdx !== undefined) ? record.get('foundRelevant_c' + condIdx) : record.get('foundRelevant_c0') || record.data.foundRelevant;

			var foundNotRelevant = foundFeatures - foundRelevant;
			var notFoundRelevant = totalRelevant - foundRelevant;
			var notFoundNotRelev = (totalFeatures - foundFeatures) - notFoundRelevant;

			if (foundRelevant !== undefined) {
				myToolTipText +=
					'<b>p-value:</b>' + (value === -1 ? "-" : renderedValue) + "</br>" +
					"<table class='contingencyTable'>" +
					' <thead><th></th><th>Relevant</th><th>Not Relevant</th><th></th></thead>' +
					'  <tr><td>Found</td><td>' + foundRelevant + '</td><td>' + foundNotRelevant + '</td><td>' + foundFeatures + '</td></tr>' +
					'  <tr><td>Not found</td><td>' + notFoundRelevant + '</td><td>' + notFoundNotRelev + '</td><td>' + (totalFeatures - foundFeatures) + '</td></tr>' +
					'  <tr><td></td><td>' + totalRelevant + '</td><td>' + (totalFeatures - totalRelevant) + '</td><td>' + (totalFeatures) + '</td></tr>' +
					'</table>';
				// myToolTipText = myToolTipText + "Features matched: " + ) + "</br>";
				// myToolTipText = myToolTipText + "Relevant features matched: " +  + "</br>";
				metadata.tdAttr = 'data-qtip="' + myToolTipText + '"';
			}

		} catch (e) {
			console.error("Error while creating tooltip", e);
		}

		return renderedValue;
	};

var renderFunctionHub= function (value, metadata, record) {
		var myToolTipText = "<b style='display:block; width:200px'>" + "Metabolism" + "</b>";

		value = Number(value)

		metadata.style = "height: 40px; font-size:12px;"

		//IF THERE IS NOT DATA FOR THIS PATHWAY, FOR THIS OMIC, PRINT A '-'
		if (value === "-" || value == undefined || isNaN(value)) {
			myToolTipText = myToolTipText + "<i>No data for this metabolite</i>";
			metadata.tdAttr = 'data-qtip="' + myToolTipText + '"';
			metadata.style += "background-color:var(--pa-cell-empty,#D4D4D4);";
			return "-";
		}

		var renderedValue = parseFloat(value).toFixed(2);

		// This was `225 * (1 - value / 0.05)`, which for any percentile in the
		// [0.90, 1.0] range it guards evaluates to between -3825 and -4275. The
		// browser clamps that to 0, so every qualifying cell rendered flat pure
		// red and the intended gradient never existed at all - the formula had
		// been copied from a p-value renderer, where dividing by 0.05 makes
		// sense because the values are below it. Here the values are above 0.9.
		//
		// Mapped over the range that is actually guarded: 0.90 is barely tinted,
		// 1.00 is the strongest. Clamped both ends so a value outside the range
		// can never produce an out-of-gamut channel again.
		if (value >= 0.90) {
			var t = Math.max(0, Math.min(1, (value - 0.90) / 0.10));
			var tint = 244 - Math.round(t * 72);   // 244 -> 172
			metadata.style += "background-color:rgb(255, " + tint + "," + tint + "); color:#9B1C1C;";
		}
		
		return renderedValue;
	};


/* `omicHeader` was added so the metabolite and hub panels can label the x axis
 * with the real condition names. These two are plain module functions with no
 * view of their own, so unlike the chart methods elsewhere they cannot walk up
 * to the job model themselves - the caller, which does have it, passes it in.
 * Omitting it is allowed and falls back to positional labels. */
let generateHeatmap = function (targetID, omicName, omicsValues, dataDistributionSummaries, visualOptions, omicHeader) {
	var featureValues, x = 0, y = 0, maxX = -1, series = [], yAxisCat = [], serie;

	for (var i in omicsValues) {
		if (!omicsValues[i]) continue;
		//restart the x coordinate
		x = 0;
		//Get the values and the name for the new serie
		featureValues = paValuesForHeader(omicsValues[i], omicHeader);
		var shownameValue = omicsValues[i].inputName != omicsValues[i].originalName && omicsValues[i].originalName !== undefined ?
			omicsValues[i].originalName + ": " + omicsValues[i].inputName :
			omicsValues[i].inputName;

		var relevantSymbols = "";
if (omicsValues[i].isRelevant()) {
	relevantSymbols += "* ";
}

if (omicsValues[i].isRelevantAssociation()) {
	relevantSymbols += "** ";
}

		serie = {name: relevantSymbols + omicsValues[i].keggName + "#" + shownameValue, data: []};
		//Add the name for the row (e.g. MagoHb or "miRNA my_mirnaid_1")
		yAxisCat.push(relevantSymbols + omicsValues[i].keggName + "#" + shownameValue);

		if (visualOptions.colorReferences) {
			var limits = getMinMax(dataDistributionSummaries[omicName], visualOptions.colorReferences[omicName]);
		} else {
			var limits = getMinMax(dataDistributionSummaries[omicName], "p10p90")
		}


		for (var j in featureValues) {

			if (visualOptions.colorScale) {
				var colorGet = getColor(limits, featureValues[j], visualOptions.colorScale)

			} else {
				var colorGet = getColor(limits, featureValues[j], "bwr")

			}

			serie.data.push({
				x: x,
				y: y,
				value: featureValues[j],
				color: colorGet,
				isSignificant: omicsValues[i].isRelevant(j)
			});
			x++;
			maxX = Math.max(maxX, x);
		}
		series.push(serie);
		y++;
	}

	/* Real condition names on the x axis - see paConditionAxis(). */
	var xAxisConfig = paConditionAxis(maxX, omicHeader, {maxChars: 12});
	var xAxisCat = xAxisConfig.categories;

	var replaceSymbols = {
		"*": '<i class="relevantFeature"></i>',
		"^": '<i class="relevantAssociationFeature"></i>'
	};

	var clusterize = omicsValues.length > 5 ? {
		algorithm: "hierarchical",
		distance: "euclidean",
		linkage: "complete",
		dendogram: false
	} : false;

	var heatmap = new Highcharts.Chart({
		chart: {type: 'heatmap', renderTo: targetID},
		heatmapSelector: {color: '#000', lineWidth: 3},
		title: null, legend: {enabled: false}, credits: {enabled: false},
		clusterize: clusterize,
		tooltip: {
			borderColor: "#333",
			formatter: function () {
				var title = this.point.series.name.split("#");
				title[1] = (title.length > 1) ? title[1] : "";
				/* The axis label is length-capped; the tooltip carries the full
				 * condition name so nothing is only ever shown truncated. */
				if (xAxisCat[this.point.x] !== undefined) {
					title[0] = title[0] + " [" + xAxisCat[this.point.x] + "]";
				}
				return "<b>" + title[0].replace(/[\*\^]/g, function(c) { return replaceSymbols[c]; }) + "</b><br/>" + "<i class='tooltipInputName'>" + title[1] + "</i>" + (this.point.value === null ? "No data" : this.point.value);
			},
			useHTML: true
		},
		xAxis: xAxisConfig,
		yAxis: {
			categories: yAxisCat, title: null, width: 100,
			labels: {
				formatter: function () {
					var title = this.value.split("#");
					title[1] = (title.length > 1) ? title[1] : "No data";
					return paRowLabel(title[0], title[1], {width: 100, maxChars: 16});
				},
				style: {fontSize: "9px"}, useHTML: true
			}
		},
		series: series,
		plotOptions: {
			heatmap: {
				borderColor: "#000000",
				borderWidth: 0.5,
				dataLabels: {
					enabled: true,
					useHTML: true,
					formatter: function() {
						if (this.point.isSignificant && maxX > 1) {
							return '<i class="fa fa-star" style="color: white !important; font-size: 8px; padding: 0;"></i>';
						}
					}
				}
			},
			series: {
				point: {
					events: {
						mouseOver: function () {
							var plot = $(this.series.chart.container).parent().next().highcharts();
							for (var i in plot.series) {
								if (plot.series[i].name !== this.series.name) {
									plot.series[i].graph && plot.series[i].graph.attr("stroke", "#E2E2E2");
									plot.series[i].markerGroup && plot.series[i].markerGroup.attr("visibility", "hidden");
								}
							}
						},
						mouseOut: function () {
							var plot = $(this.series.chart.container).parent().next().highcharts();
							for (var i in plot.series) {
								plot.series[i].graph && plot.series[i].graph.attr("stroke", plot.series[i].color);
								plot.series[i].markerGroup && plot.series[i].markerGroup.attr("visibility", "visible");
							}
						}
					}
				}
			}
		}
	});

	return heatmap;
};

/* `omicHeader` - see the note on generateHeatmap above. */
let generatePlot = function (targetID, omicName, omicsValues, dataDistributionSummaries, legendContainerId, visualOptions, omicHeader) {
	var series = [], maxX = -1;
	var yAxisItem = {title: null}, omicsValue, auxValues;

	if (visualOptions.colorReferences) {
		var limits = getMinMax(dataDistributionSummaries[omicName], visualOptions.colorReferences[omicName]);
	} else {
		var limits = getMinMax(dataDistributionSummaries[omicName], "p10p90")
	}


	for (var i in omicsValues) {
		if (!omicsValues[i]) continue;
		auxValues = [];
		omicsValue = omicsValues[i];
		/* Same space as the axis labels -- see paValuesForHeader(). */
		var plottedValues = paValuesForHeader(omicsValue, omicHeader);
		maxX = Math.max(maxX, plottedValues.length);

		for (var j in plottedValues) {
			auxValues.push({y: plottedValues[j], marker: ((plottedValues[j] > limits.max || plottedValues[j] < limits.min) ? {fillColor: '#ff6e00'} : null)});
		}

		var relevantSymbols = "";
if (omicsValues[i].isRelevant()) {
	relevantSymbols += "* ";
}

if (omicsValues[i].isRelevantAssociation()) {
	relevantSymbols += "** ";
}

		series.push({
			name: relevantSymbols + omicsValue.keggName + "#" + omicsValue.inputName,
			type: 'spline',
			data: auxValues
		});
	}

	if (limits.max !== limits.absMax && limits.min !== limits.absMin) {
		yAxisItem.plotLines = [
			{label: {text: 'min', align: 'right', style: {color: 'gray'}}, color: '#dedede', value: limits.min, width: 1},
			{label: {text: 'max', align: 'right', style: {color: 'gray'}}, color: '#dedede', value: limits.max, width: 1}
		];
	}

	/* Real condition names on the x axis - see paConditionAxis(). */
	var xAxisConfig = paConditionAxis(maxX, omicHeader, {maxChars: 12});
	var xAxisCat = xAxisConfig.categories;

	var replaceSymbols = {
		"*": '<i class="relevantFeature"></i>',
		"^": '<i class="relevantAssociationFeature"></i>'
	};
	var plot = new Highcharts.Chart({
		chart: {renderTo: targetID},
		title: null, legend: {enabled: false}, credits: {enabled: false},
		tooltip: {
			borderColor: "#333",
			formatter: function () {
				var title = this.point.series.name.split("#");
				title[1] = (title.length > 1) ? title[1] : "";
				if (xAxisCat[this.point.x] !== undefined) {
					title[0] = title[0] + " [" + xAxisCat[this.point.x] + "]";
				}
				return "<b>" + title[0].replace(/[\*\^]/g, function(c) { return replaceSymbols[c]; }) + "</b><br/>" + "<i class='tooltipInputName'>" + title[1] + "</i>" + (this.point.y === null ? "No data" : this.point.y);
			},
			useHTML: true
		},
		xAxis: [xAxisConfig],
		yAxis: yAxisItem,
		series: series
	});

	return plot;
};
