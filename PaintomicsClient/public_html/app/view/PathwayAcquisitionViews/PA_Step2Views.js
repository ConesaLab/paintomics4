//# sourceURL=PA_Step2Views.js
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
* - PA_Step2JobView
* - PA_Step2ReplicateDetectionView
* - PA_Step2CompoundSetView
* - PA_OmicSummaryPanel
*
*/
//Ext.require('Ext.chart.*');

/**
* Normalises the "mapped" slot of an omic summary (omicSummary[0]) into a
* matched-feature count per database.
*
* That slot arrives in two different shapes from the server:
*
*   - Gene based omics: a dict of feature-table name -> matched count, e.g.
*     {"mmu_kegg_genes": 5620, "mmu_reactome_genes": 2827, "Total": 6103}.
*     The table name embeds the database name, and "Total" holds the unique
*     count across every database.
*
*   - Compound based omics: a plain integer. Compounds are matched once
*     against KEGG compound IDs and that single set backs every database, so
*     the server has no per-database breakdown to report.
*
* Indexing the dict shape into an integer yields undefined, which is how the
* "Multiple databases used" table came to print "undefined (NaN%)" for the
* metabolomics omic.
*
* @param {Object|Number} mappedSummary the omicSummary[0] value
* @param {Array} databases names of the databases used in this analysis
* @returns {Object} {perDatabase: {dbname: count}, totalMapped: count}
*/
function matchedFeaturesByDatabase(mappedSummary, databases) {
	var perDatabase = {};

	// Compound based omic: one count, shared by every database.
	if (typeof mappedSummary === "number") {
		databases.forEach(function (dbname) {
			perDatabase[dbname] = mappedSummary;
		});
		return {perDatabase: perDatabase, totalMapped: mappedSummary};
	}

	var tableNames = Object.keys(mappedSummary || {});

	databases.forEach(function (dbname) {
		var featureTable = tableNames.find(function (el) {
			return el.indexOf(dbname) !== -1;
		});
		// An omic with no table for this database matched nothing in it.
		perDatabase[dbname] = (featureTable !== undefined) ? mappedSummary[featureTable] : 0;
	});

	// "Total" is the de-duplicated count across databases; with a single
	// database there is no "Total" entry and the only table is the total.
	var totalMapped = 0;
	if (mappedSummary && mappedSummary.hasOwnProperty("Total")) {
		totalMapped = mappedSummary["Total"];
	} else if (tableNames.length > 0) {
		totalMapped = mappedSummary[tableNames[0]];
	}

	return {perDatabase: perDatabase, totalMapped: totalMapped};
}

function PA_Step2JobView() {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step2JobView";
	this.items = [];

	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	this.loadModel = function(jobModel) {
		if (this.model !== null) {
			this.model.deleteObserver(this);
		}

		this.model = jobModel;

		// JobController.showJobInstance re-loads the model into an existing view
		// on its "force" path, so the list has to be rebuilt from scratch or the
		// second load stacks a duplicate card set on top of the first.
		this.items = [];

		var foundCompounds = this.model.getFoundCompounds();
		var compoundSetView = null;
		for (var i in foundCompounds) {
			compoundSetView = new PA_Step2CompoundSetView();
			compoundSetView.loadModel(foundCompounds[i]);
			// Only the sets that still need a decision get a card. The *model*
			// keeps every set: PA_Step3Views gates Hub Analysis and Class
			// Activity on model.foundCompounds.length, and getSelectedCompounds()
			// reads the model, so the auto-resolved sets still reach the server
			// with their selection intact. Nothing observes a CompoundSet
			// (nothing ever calls notifyObservers on one), so registering 6592
			// dead observers - and logging one line per registration - is pure
			// cost and is gone.
			if (compoundSetView.needsDisambiguation()) {
				this.items.push(compoundSetView);
			}
		}
	};

	/*********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.initComponent = function() {
		var me = this;

		var dataDistribution = me.getModel().getDataDistributionSummaries(), aux = null;

		var omicSummaryPanelComponents = [{
			xtype: 'box',
			cls: "contentbox omicSummaryBox", minHeight: 240,
			html: '<div id="about">' +
			// The heading's tip carries the long form. The body used to repeat
			// most of it across four lines -- an overview sentence that only said
			// "below is an overview", a rule of thumb, an instruction, and a
			// paragraph on comparing databases that restated this tip almost
			// word for word. Two lines say the same things once.
			'  <h2 >Feature ID/name translation summary <span class="helpTip" title="The percentage of your input features (names or identifiers) that could be translated into the identifier each database is keyed on - for example an NCBI Gene ID for KEGG, or a UniProt accession for OmniPath. A feature counts as soon as its name resolves, even if it belongs to no pathway in that database, so these figures are not a ranking - Step 3 reports pathway coverage."></h2>' +
			'  <p>' +
			'    How many of your features resolved into each database\'s identifiers. ' +
			'The more that map, the more there is to work with later &mdash; if one ' +
			'looks low, check that file\'s identifiers.<br>' +
			'    <b>Not a ranking:</b> the databases use different identifier types ' +
			'and differ in scope by design. Step 3 reports pathway coverage.<br><br>' +
			((Object.keys(dataDistribution).length > 0) ? '  <a href="javascript:void(0)" id="download_mapping_file"><i class="fa fa-download"></i> Download ID/Name mapping results.</a>' : "") +
			'  </p>' +
			'</div>'
		},
		{
			xtype: 'box',
			cls: "contentbox omicSummaryBox", minHeight: 240,
			html: '<div id="about">' +
			// Was title=" ": the icon rendered, invited a hover, and showed an
			// empty tooltip.
			'  <h2 >Data distribution summary <span class="helpTip" title="How each omic\'s values are spread across your samples. The box is the interquartile range, the red line the median, and the whiskers reach the 10th and 90th percentiles - the same two percentiles the heatmap colour scale uses by default."></h2>' +
			'  <p>' +
			'    By default, percentiles 10 and 90 set the reference range for the heatmap colours. You can change this in the pathway view: open <b>Settings</b> in the toolbar and edit <b>Reference values</b>.<br>' +
			// This figure replaces settingsbutton.png, a 2022 screenshot of the
			// old dark Bootstrap toolbar. It is not an image at all: it is the
			// step-4 toolbar's own markup, styled by the same .button rules the
			// real toolbar uses (extended to .paToolbarMiniature in main.css and
			// dark.css), so it renders as vector text at any zoom, follows the
			// theme, and cannot fall out of date when the toolbar is restyled.
			// Order matches PA_Step4Views' secondTopToolbar; the ring marks the
			// Settings button the caption above is pointing at.
			'		 <div class="paToolbarMiniature" aria-hidden="true">' +
			'			<span class="button btn-danger paMiniatureTarget"><i class="fa fa-wrench"></i> Settings</span>' +
			'			<span class="button btn-info"><i class="fa fa-search"></i> Search</span>' +
			'			<span class="button btn-secondary"><i class="fa fa-th"></i> Show Heatmap</span>' +
			'			<span class="button btn-primary"><i class="fa fa-sitemap"></i> Show Pathway</span>' +
			'			<span class="button btn-default"><i class="fa fa-arrow-left"></i> Go back</span>' +
			'		 </div>' +
			'  </p>' +
			'</div>'
		}];

		/* INFO PANEL ABOUT DATABASES USED */
		var databases = me.getModel().getDatabases();
		var compoundOmics = me.getModel().getCompoundBasedInputOmics().map(x => x.omicName);
		var matchingPerDB = {};
		var numberOfClusters = [];
		var thresholdMetaboliteClass = [];

		for (var omicName in dataDistribution) {
			var isCompoundBased = (compoundOmics.indexOf(omicName) > -1);

			// Matched counts per database, plus the unique count across all of
			// them; handles both the gene based (dict) and compound based
			// (integer) shapes of the summary.
			var matched = matchedFeaturesByDatabase(dataDistribution[omicName][0], databases);

			// Total input features = unmapped + uniquely mapped.
			var totalFeatures = dataDistribution[omicName][1] + matched.totalMapped;

			databases.forEach(function(dbname) {
				var matchedCount = matched.perDatabase[dbname];

				matchingPerDB[dbname] = $.extend(matchingPerDB[dbname] || {}, {
					[omicName]: {
						"matched": matchedCount,
						// An omic with no input features must not divide by zero.
						"percentage": (totalFeatures > 0) ? Math.ceil(matchedCount / totalFeatures * 100) : 0
					}});
			});

			if (!isCompoundBased) {
				numberOfClusters.push({
					xtype: 'combo',
					fieldLabel: omicName,
					name: 'clusterNumber:' + omicName,
					value: 'dynamic',
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					/* ExtJS aligns field labels right by default, so a 300px
					   label column pushed "Gene expression:" 198px away from
					   the card's own left edge - the heading and the paragraph
					   above it start there, and the one control the card exists
					   to offer did not. Left labels put the text on that rail,
					   and 240px is the width of the longest of them
					   ("Metabolite class activity threshold") with room to
					   spare, so every row's field starts on one edge too. */
					labelAlign: 'left',
					labelWidth: 240,
					width: 300,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Generate automatically', 'dynamic'],
							['One cluster', 1],
							['Two clusters', 2],
							['Three clusters', 3],
							['Four clusters', 4],
							['Five clusters', 5],
							['Six clusters', 6],
							['Seven clusters', 7],
							['Eight clusters', 8],
							['Nine clusters', 9],
							['Ten clusters', 10],
						]
					}),
					helpTip: "Define the number of clusters per omic or let the program calculate them dynamically using silhouette."
				});
			}

			if (isCompoundBased) {
				thresholdMetaboliteClass.push({
					xtype: 'combo',
					fieldLabel: 'Metabolite class activity threshold',
					name: 'thresholdMetaboliteClass',
					value: 'default',
					displayField: 'name', valueField: 'value',
					editable: true,
					allowBlank: false,
					/* Same rail as the cluster combo above. */
					labelAlign: 'left',
					labelWidth: 240,
					width: 300,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [['Generate automatically', 'default'],
							['0.1', 0.1],
							['0.2', 0.2],
							['0.3', 0.3],
							['0.4', 0.4],
							['0.5', 0.5],
							['0.6', 0.6],
							['0.7', 0.7],
							['0.8', 0.8],
							['0.9', 0.9],
							['1.0', 1.0]]
					}),
					// "Average percentage" is what the paragraph above this panel used
					// to say and it is not what the code does. compundsClassification
					// falls back to `totalRelevantFeatures / totalFeatures`
					// (PathwayAcquisitionJob.py:2280-2283) - the proportion of
					// significant metabolites across the whole dataset, not an average
					// of per-class percentages. The two differ whenever the classes are
					// unequally sized, which they always are.
					helpTip: "With 'Generate automatically', the threshold is the proportion of significant metabolites across your whole dataset. Otherwise choose a value between 0 and 1."
				});

			}
			omicSummaryPanelComponents.push(new PA_OmicSummaryPanel(omicName, dataDistribution[omicName], isCompoundBased).getComponent());
		}

		if (numberOfClusters.length) {
			/* Add an empty container to restore "odd" position of next sibling elements */
			omicSummaryPanelComponents.splice(2, 0, {
				xtype: 'container',
				layout: {type: 'vbox', align: 'stretch'},
				cls: "contentbox", minHeight: 240, id: "clusternumber_box",
				items: [{
					html: '<h2 style="width: 100%;">Configure the number of clusters</h2>'
				}, {
					html: '<p>In the next step Paintomics will calculate the clusters present in the data provided for each omic, using k-means with either an automatically calculated number of clusters or the ones you define here. You will also be able to modify them there by selecting individual omics in the network.<br><br></p>'
				},{
					xtype: 'form',
					maxWidth: 600,
					bodyCls: "divForm",
					style: "margin: 0 auto 20px auto;",
					layout: {type: 'vbox', align: 'stretch'},
					defaults: {labelAlign: "right", border: false},
					items: numberOfClusters
				}]
			}, {xtype: 'container', cls: 'paLayoutPad', html:'<div style="display: none;"></div>'});
		}

		if (databases.length > 1) {

			var dbs_descriptions = {
				"KEGG": '<a href="http://www.kegg.jp/kegg/" target="_blank">Kyoto Encyclopedia of Genes and Genomes</a> is a database resource for understanding high-level functions and utilities of the biological system, such as the cell, the organism and the ecosystem, from molecular-level information, especially large-scale molecular datasets generated by genome sequencing and other high-throughput experimental technologies.',
				"MapMan": 'Oriented towards plant species, in combination with <a href="http://www.gomapman.org/" target="_blank">GoMapMan</a>, it provides additional pathways as well as an improved and more consolidated annotation for the model species Arabidopsis, and several crop species (potato, tomato, rice).',
				"Reactome": '<a href="http://www.reactome.org/" target="_blank">Reactome</a> is an open-source, open access, manually curated and peer-reviewed pathway database, containing information of around 20 organisms, including human, mouse and arabidopsis, among others.',
				"OmniPath": '<a href="https://omnipathdb.org/" target="_blank">OmniPath</a> integrates over 100 resources into a prior-knowledge network of signed, directed molecular interactions, available for human, mouse and rat. Its pathways are defined by the curated SIGNOR and NetPath annotations and carry no diagram, so they open as an interactive interaction network rather than as a painted map.'
			};

			var dl_dbs = databases.map(function(dbname) {
				var divContent =
				'<table>' +
					'<tr><th>Omic</th><th>Matched</th></tr>' +
					Object.keys(matchingPerDB[dbname]).map(function(omicName) {
						return '<td>' + omicName + '</td><td>' + matchingPerDB[dbname][omicName]["matched"] + " (" + matchingPerDB[dbname][omicName]["percentage"] + "%)</td>";
					}).join('</tr><tr>') +
				'</table>';

				return '<dt>' + dbname + '</dt><dd>' + dbs_descriptions[dbname] + '<div id="matching_table_' + dbname + '">' + divContent + '</div></dd>';
			}).join('');

			var dbs_message = {
				xtype: 'box',
				cls: "contentbox", minHeight: 240, id: "dbs_message",
				// The <dl> and the closing sentence were both inside the opening <p>.
				// A description list is not phrasing content, so the parser closed
				// that paragraph before the list and left the last sentence in no
				// paragraph at all - which is why it ignored the card's reading
				// measure and ran the full width of the box while the first sentence
				// wrapped at 105 characters.
				html:
				'<h2>Multiple databases used</h2>' +
				'<div>' +
				'  <p>Your analysis includes the following databases:</p>' +
				'  <dl id="dbs_dl">' + dl_dbs + '</dl>' +
				'  <p>The diagrams below combine the matched and unmatched features of <b>all</b> databases. Hover over a diagram for the per-database breakdown.</p>' +
				'</div>'
			};

			/* Add an empty container to restore "odd" position of next sibling elements */
			omicSummaryPanelComponents.splice(2, 0, dbs_message, {xtype: 'container', cls: 'paLayoutPad', html:'<div style="display: none;"></div>'});
		}

		// Replicate-detection card — only renders when at least one omic has
		// a complete or partial replicate detection result. Built via its own
		// view so the wiring (radios, file picker, server POST) lives in one
		// self-contained component instead of leaking into PA_Step2JobView.
		var replicateDetectionView = new PA_Step2ReplicateDetectionView();
		replicateDetectionView.loadModel(me.getModel());
		if (replicateDetectionView.hasContent()) {
			var repComponent = replicateDetectionView.initComponent();
			if (repComponent) {
				// Append after the data-distribution box; pad with an empty
				// container to keep the column-layout "odd/even" alignment
				// consistent with the existing Step-2 cards.
				omicSummaryPanelComponents.push(repComponent,
					{xtype: 'container', cls: 'paLayoutPad', html:'<div style="display: none;"></div>'});
			}
		}

		var compoundsPanelHTML = "";

		// This guard is deliberately NOT me.items.length. items only holds the
		// sets that still need disambiguation, and the threshold combo below
		// belongs to the job, not to the cards: its value is posted as
		// thresholdMetaboliteClass and PathwayAcquisitionServlet feeds it to
		// compundsClassification(). A job whose compounds all resolved
		// automatically must still be able to set it, so it is gated on the
		// model having matched compounds at all.
		if (me.getModel().getFoundCompounds().length > 0) {
			// create a box named "Configure the metabolite class activity threshold"
			omicSummaryPanelComponents.splice(5, 0, {
				xtype: 'container',
				layout: {type: 'vbox', align: 'stretch'},
				cls: "contentbox", minHeight: 240, id: "threshold_box",
				items: [{
					html: '<h2 style="width: 100%;">Configure the metabolite class activity threshold</h2>'
				}, {
					html: '<p>To test the hypothesis of a\n' +
						'metabolite class being regulated, PaintOmics implements\n' +
						'a metabolite class activity analysis tool, where a binomial\n' +
						'test is used to assess the hypothesis of the proportion of significant compounds in a given measured metabolite class\n' +
						'being higher than a user-defined threshold.</p>'
				},{
					xtype: 'form',
					maxWidth: 600,
					bodyCls: "divForm",
					style: "margin: 0 auto 20px auto;",
					layout: {type: 'vbox', align: 'stretch'},
					defaults: {labelAlign: "right", border: false},
					items: thresholdMetaboliteClass
				}]
			}, {xtype: 'container', cls: 'paLayoutPad', html:'<div style="display: none;"></div>'});
		}

		if (me.items.length > 0) {
			compoundsPanelHTML = me.renderCompoundsPanel();
		}

		this.component = Ext.widget({
			xtype: "container",
			minHeight: 800,
			padding: '10',
			items: [{
				xtype: "box",
				cls: "toolbar secondTopToolbar",
				html:
				'<a href="javascript:void(0)" class="button btn-danger btn-right" id="resetButton"><i class="fa fa-refresh"></i> Reset</a>' +
				'<a href="javascript:void(0)" class="button btn-success btn-right" id="runButton"><i class="fa fa-play"></i> Next step</a>' +
				'<a href="javascript:void(0)" class="button btn-default btn-right backButton"><i class="fa fa-arrow-left"></i> Go back</a>'
			}, {
				xtype: 'container', itemId: "omicSummaryPanel",
				cls: "omicSummaryContainer",
				layout: 'column',  style: "margin-top:50px;",
				items: omicSummaryPanelComponents
			}, {
				xtype: 'form', cls: "omicSummaryContainer",
				border: 0, style: "margin-top:30px;", defaults: {labelAlign: "right",border: 0},
				items: [{
					xtype: "textfield", itemId: "jobIDField",
					name: "jobID",
					hidden: true,
					value: this.model.getJobID()
				}, {
					xtype: "box", itemId: "compoundsPanelsContainer",
					cls: "compoundsPanelsContainer",
					html: compoundsPanelHTML
				}]
			}],
			listeners: {
				boxready: function() {
					$("#runButton").click(function() {
						me.submitFormHandler();
					});
					$(".backButton").click(function() {
						me.backButtonHandler();
					});
					$("#resetButton").click(function() {
						me.resetViewHandler();
					});
					$('#download_mapping_file').click(function() {
						application.getController("DataManagementController").downloadFilesHandler(me, "mapping_results_" + me.getModel().getJobID() + ".zip", "job_result", me.getModel().getJobID());
					});
					me.initAISuggestButton();
					initializeTooltips(".helpTip");
					me.initCompoundsPanelHandlers(this.queryById("compoundsPanelsContainer"));
				},
				beforedestroy: function() {
					me.getModel().deleteObserver(me);
				}
			}
		});

		return this.component;
	};
	/**
	* Show the button only where it can actually do something.
	*
	* Three conditions, all of which have to hold: this deployment has AI
	* switched on AND has a token (`/ai_provider` answers both), the job carries
	* consent, and there is at least one card to decide. A button that appears
	* and then reports that the server has no API key is worse than no button.
	*/
	this.initAISuggestButton = function() {
		var me = this;
		if (me.items.length === 0) {
			return;
		}
		if (me.getModel().aiConsent !== true) {
			return;
		}
		if (typeof withAIProviderInfo !== "function") {
			return;
		}
		withAIProviderInfo(function(info) {
			if (!info || info.enabled !== true || info.configured !== true) {
				return;
			}
			// Kept on the view rather than only in the DOM: the panel is
			// re-rendered whenever picks are applied or undone, and the answer
			// to "may this job use the AI" must survive that.
			me.aiAvailable = true;
			$(".aiSuggestActions").show();
		});
	};

	/**
	* The AI controls, inside the card that introduces the section.
	*
	* Deliberately here rather than in the step's toolbar. The toolbar's buttons
	* act on the whole step - go back, run the next step, reset everything - and
	* this one acts on the compound cards immediately below it. Next to them it
	* can also say what it does and what it costs the user, which a toolbar
	* button has no room for.
	*
	* @returns {String}
	*/
	this.renderAIActions = function() {
		var hidden = this.aiAvailable ? "" : ' style="display:none;"';
		var undo = this.aiSnapshot
			? '<a href="javascript:void(0)" class="button btn-ai-quiet" id="aiUndoButton" ' +
			  'title="Put every tick back as it was">' +
			  '<i class="fa fa-undo"></i></a>'
			: "";

		var mark = (typeof getAIMark === "function") ? getAIMark() : "";

		return '' +
		'<div class="aiSuggestActions"' + hidden + '>' +
		'  <div class="aiSuggestActionsBody">' +
		// data-guides="ignore": the alignment overlay measures where TYPE starts,
		// and an icon-led label starts its type one icon in. The mark is on the
		// panel's rail, which is the edge a reader sees; the offset is the icon,
		// and it is declared here rather than left for the HUD to rediscover.
		'    <h3 class="aiSuggestActionsTitle" data-guides="ignore">' +
		       mark + '<span>PaintOmics AI</span></h3>' +
		'    <p class="aiSuggestHint">Picks the most likely compound for each name, from ' +
		'your organism and experiment design.</p>' +
		'  </div>' +
		'  <div class="aiSuggestActionsRow">' +
		'    <a href="javascript:void(0)" class="button btn-ai" id="aiSuggestButton">' +
		       mark + '<span>Choose for me</span></a>' +
		     undo +
		'  </div>' +
		'</div>';
	};

	/**
	* The button's four states, in one place so none of them can be half-applied.
	*
	* @param {String} state one of "idle", "working", "done"
	* @param {String} label optional text for the "done" state
	*/
	this.setAIButtonState = function(state, label) {
		var button = $("#aiSuggestButton");
		if (button.length === 0) {
			return;
		}
		var mark = (typeof getAIMark === "function") ? getAIMark() : "";

		if (state === "working") {
			button.addClass("aiWorking")
				.html('<i class="fa fa-circle-o-notch fa-spin"></i><span>Choosing\u2026</span>');
		} else if (state === "done") {
			button.removeClass("aiWorking")
				.html(mark + '<span>' + (label || "Choose again") + '</span>');
		} else {
			button.removeClass("aiWorking")
				.html(mark + '<span>Choose for me</span>');
		}
	};

	this.aiSuggestHandler = function() {
		if ($("#aiSuggestButton").hasClass("aiWorking")) {
			return;
		}
		this.setAIButtonState("working");
		this.controller.step2SuggestCompoundsHandler(this);
	};

	/**
	* The whole disambiguation panel as one string of HTML.
	*
	* It used to be a column layout holding one container per matched name, each
	* holding one Ext box per candidate plus an Ext.tip.ToolTip per candidate; a
	* job with 6592 matched names built tens of thousands of components and froze
	* the tab for minutes before the first paint. This markup reproduces the same
	* DOM (the cards are laid out by .metaboliteBox:nth-child in main.css, not by
	* the column layout) at a fraction of the cost.
	*
	* Extracted from the component definition so that accepting the AI's picks
	* can rebuild it. Re-rendering rather than patching checkboxes in place is
	* deliberate: a collapsed card's alternatives are not in the document at all,
	* so a DOM-only update would silently miss exactly the candidates the AI is
	* most likely to have turned OFF.
	*
	* @returns {String}
	*/
	this.renderCompoundsPanel = function() {
		var me = this;
		return '' +
		// `compoundsIntroBox` takes this card out of the 49%-wide odd/even
		// float grid the metabolite cards use. As one of those it was a
		// half-width block of prose with an empty half-row beside it.
		//
		// Two columns inside it: what the user has to do, and the offer to do
		// it for them. A lone button under a line of prose in a 1360px card
		// read as an afterthought -- it had no surface of its own and nothing
		// to balance against.
		'<div class="contentbox omicSummaryBox compoundsIntroBox">' +
		'  <div id="about" class="compoundsIntroLayout">' +
		'    <div class="compoundsIntroText">' +
		'      <h2>Compounds disambiguation</h2>' +
		'      <p><b>' + me.items.length + '</b> of your compound names matched more than ' +
		'one KEGG compound. Pick the one you measured on each card below.</p>' +
		'    </div>' +
		     me.renderAIActions() +
		'  </div>' +
		'</div>' +
		me.renderAISummary() +
		me.items.map(function(compoundSetView, index) {
			return compoundSetView.renderCard(index);
		}).join("") +
		// The cards are floated; the column layout used to supply the clearfix,
		// so without this the panel would collapse to no height and the cards
		// would spill out of the step-2 form.
		'<div style="clear: both;"></div>';
	};

	/**
	* The banner that says what the AI did, or nothing at all before it has run.
	*
	* The counts are of cards actually CHANGED, not of decisions received: the
	* server ranks every compound set it has, including ones this view draws no
	* card for, and reporting those would credit the feature with work the user
	* cannot see.
	*
	* @returns {String}
	*/
	this.renderAISummary = function() {
		var summary = this.aiSummary;
		if (!summary) {
			return "";
		}

		var parts = [];
		if (summary.byRule > 0) {
			parts.push('<b>' + summary.byRule + '</b> by name');
		}
		if (summary.byAI > 0) {
			parts.push('<b>' + summary.byAI + '</b> by PaintOmics AI');
		}

		// The count is of cards CHANGED. Saying "selected" would claim the ones
		// that were already right, which is most of them on a typical job.
		var headline = parts.length
			? 'Changed ' + parts.join(' and ') + '.'
			: 'Nothing needed changing.';

		var tail = summary.unsure > 0
			? ' <b>' + summary.unsure + '</b> left for you.'
			: '';

		var model = summary.model
			? '<div class="aiSuggestModel">' + Ext.String.htmlEncode(summary.model) +
			  ' \u00b7 every choice checked against its own card</div>'
			: '';

		return '' +
		'<div class="contentbox aiSuggestSummary">' +
		'  <div class="aiSuggestSummaryHead">' +
		'    <span class="aiSuggestSummaryMark">' +
		       ((typeof getAIMark === "function") ? getAIMark() : "") + '</span>' +
		'    <span>' + headline + tail + '</span>' +
		'  </div>' +
		model +
		'</div>';
	};

	/**
	* Accept a suggestion payload: tick what it chose, untick its rivals.
	*
	* Only ever touches candidates INSIDE a set the server named, and only sets
	* this view actually drew a card for. A decision for an input name this view
	* has no card for is dropped rather than applied blind - the server's idea of
	* which sets need a decision is deliberately more permissive than this one
	* (`selected` does not exist server-side), and the cards are what the user
	* consented to by pressing the button.
	*
	* @param {Object} payload as returned by /pa_suggest_compounds_status
	* @returns {Object} {byRule, byAI, unsure} counts of cards actually changed
	*/
	this.applyAISuggestions = function(payload) {
		var me = this;
		var byTitle = {};
		me.items.forEach(function(compoundSetView) {
			byTitle[compoundSetView.getModel().getTitle()] = compoundSetView;
		});

		// One snapshot of every tick before anything moves, so Undo is exact
		// rather than an attempt to invert the decisions one at a time.
		me.aiSnapshot = me.items.map(function(compoundSetView) {
			var model = compoundSetView.getModel();
			return {
				view: compoundSetView,
				state: model.getMainCompounds().concat(model.getOtherCompounds())
					.map(function(compound) { return compound.selected === true; }),
				aiState: compoundSetView.aiState || null
			};
		});

		var counts = {byRule: 0, byAI: 0, unsure: 0};

		(payload.decisions || []).forEach(function(decision) {
			var compoundSetView = byTitle[decision.title];
			if (!compoundSetView || !decision.keggID) {
				return;
			}

			// Only a card whose ticks actually MOVED gets marked. The server
			// decides every set it has, and on a typical job most of those
			// decisions agree with what was already selected -- badging those
			// too put a chip on 52 of 47 cards, at which point the chip stops
			// meaning anything and the eye cannot find the changes.
			if (!compoundSetView.selectOnly(decision.keggID)) {
				return;
			}

			if (decision.tier === "ai") { counts.byAI++; } else { counts.byRule++; }
			compoundSetView.aiState = {
				status: "picked", keggID: decision.keggID, tier: decision.tier,
				confidence: decision.confidence || "", reason: decision.reason || ""
			};
		});

		(payload.unresolved || []).forEach(function(entry) {
			var compoundSetView = byTitle[entry.title];
			if (!compoundSetView) {
				return;
			}
			counts.unsure++;
			compoundSetView.aiState = {
				status: "unsure", keggID: null, tier: "ai", confidence: "",
				reason: entry.reason || entry.detail || ""
			};
		});

		me.aiSummary = {byRule: counts.byRule, byAI: counts.byAI,
		                unsure: counts.unsure, model: payload.model || ""};
		me.refreshCompoundsPanel();
		return counts;
	};

	/**
	* Put every tick back exactly as it was before the button was pressed.
	*/
	this.undoAISuggestions = function() {
		var snapshot = this.aiSnapshot;
		if (!snapshot) {
			return;
		}
		snapshot.forEach(function(entry) {
			var model = entry.view.getModel();
			var compounds = model.getMainCompounds().concat(model.getOtherCompounds());
			compounds.forEach(function(compound, index) {
				compound.selected = entry.state[index];
			});
			entry.view.aiState = entry.aiState;
		});
		this.aiSnapshot = null;
		this.aiSummary = null;
		this.refreshCompoundsPanel();
	};

	/**
	* Rebuild the cards and rebind the delegated handlers they depend on.
	*/
	this.refreshCompoundsPanel = function() {
		var container = this.component && this.component.queryById
			? this.component.queryById("compoundsPanelsContainer") : null;
		if (!container) {
			return;
		}
		container.update(this.renderCompoundsPanel());
		// update() replaces the element's children, so the delegated handlers
		// bound to the OLD element are gone with it.
		this.initCompoundsPanelHandlers(container);
	};

	this.submitFormHandler = function() {
		this.controller.step2OnFormSubmitHandler(this);
	};
	this.backButtonHandler = function() {
		this.controller.backButtonClickHandler(this, update=true);
	};
	this.resetViewHandler = function() {
		this.controller.resetButtonClickHandler(this);
	};
	/**
	* Every card shares one set of delegated jQuery handlers and one tooltip,
	* bound once to the panel that contains them. Binding per candidate - and
	* creating an Ext.tip.ToolTip per candidate - was the other half of the
	* step-2 freeze: that cost scales with the number of matched compounds,
	* this does not. Delegation also covers the alternative candidates, which
	* are only inserted into the document when a card is expanded (which is why
	* the old code needed a 2 second setTimeout to re-bind them).
	*
	* @param {Ext.Component} panelComponent the compoundsPanelsContainer box
	*/
	this.initCompoundsPanelHandlers = function(panelComponent) {
		var me = this;

		if (me.items.length === 0 || !panelComponent || !panelComponent.el) {
			return;
		}

		// Scoped to this view's own element: a previous step-2 job may still be
		// in the DOM behind the card layout, and its cards index into a
		// different items array.
		var panel = $(panelComponent.el.dom);

		panel.on("change", "input[type=checkbox][name=metabolite]", function() {
			me.compoundSelectionHandler($(this));
		});

		panel.on("click", ".showOtherCompoundsButton", function() {
			me.showOtherCompoundsHandler($(this));
		});

		// Delegated, like everything else bound here: the AI controls live
		// inside this panel now, and the panel's HTML is replaced wholesale
		// each time picks are applied or undone. A handler bound straight to
		// the button would be thrown away with the element it was bound to,
		// and Undo would stop responding after the first use.
		panel.on("click", "#aiSuggestButton", function() {
			me.aiSuggestHandler();
		});

		panel.on("click", "#aiUndoButton", function() {
			me.undoAISuggestions();
			me.setAIButtonState("idle");
		});

		Ext.create('Ext.tip.ToolTip', {
			target: panel[0],
			delegate: '.metaboliteCompound',
			listeners: {
				beforeshow: function(tip) {
					var compound = $(tip.triggerElement);
					// The browser has already decoded the attributes, so the
					// values go back through htmlEncode before being re-injected.
					var compoundID = compound.attr("data-compound-id") || "";
					var compoundName = compound.attr("data-compound-name") || "";

					tip.update(
						'<b>' + Ext.String.htmlEncode(compoundName) + '</b> (' + Ext.String.htmlEncode(compoundID) + ')' +
						'<div>' +
						'  <div style="display: block; text-align:center; padding: 20px;"><i class="fa fa-circle-o-notch fa-spin fa-fw"></i> Loading image...</div>' +
						'  <img style="display: block; margin:auto;" src="http://rest.kegg.jp/get/' + encodeURIComponent(compoundID) + '/image">' +
						'</div>');
				},
				show: function(tip) {
					// The KEGG structure image arrives late; drop the spinner and
					// re-measure the tip once it does.
					$(tip.el.dom).find("img").on('load', function() {
						$(this).prev().remove();
						tip.doLayout();
					});
				}
			}
		});
	};

	/**
	* Mirrors a checkbox onto the model, which is the only place the selection
	* is read from (see getSelectedCompounds).
	*/
	this.compoundSelectionHandler = function(checkbox) {
		var compoundID = checkbox.val();
		var selected = checkbox.is(":checked");
		var setIndex = parseInt(checkbox.closest(".metaboliteBox").attr("data-compoundset"), 10);
		var compoundSetView = this.items[setIndex];

		if (compoundSetView === undefined) {
			return;
		}

		var compoundSet = compoundSetView.getModel();
		var compound = compoundSet.findOtherCompound(compoundID) || compoundSet.findMainCompound(compoundID);

		if (compound === null) {
			return;
		}

		compound.selected = selected;

		if (selected) {
			//If the user selects a compound which is repeated and already selected, warn.
			//The duplicates are looked up in the model rather than by scanning the
			//rendered checkboxes: the resolved compound sets have no card at all and
			//the alternatives of a collapsed card are not in the document, so a DOM
			//scan would silently miss real duplicates.
			var duplicates = this.findSelectedDuplicates(compoundID, compoundSet);

			if (duplicates.length > 0) {
				var message = "<b>Also selected for:</b><ul>";
				for (var i in duplicates) {
					message += "<li>" + Ext.String.htmlEncode(duplicates[i]) + "</li>";
				}
				message += "</ul>";

				showWarningMessage("Compound already selected", {
					message : "This compound has been already selected in other box. Duplicated compounds may affect to the results in next stages.<br>" + message,
					showButton : true
				});
			}
		}
	};

	/**
	* Titles of the other compound sets that already have this KEGG compound
	* selected. Excludes ownerSet, whose selection is the one just made.
	*/
	this.findSelectedDuplicates = function(compoundID, ownerSet) {
		var foundCompounds = this.model.getFoundCompounds();
		var duplicates = [], compoundSet, compound;

		for (var i in foundCompounds) {
			compoundSet = foundCompounds[i];
			if (compoundSet === ownerSet) {
				continue;
			}

			compound = compoundSet.findMainCompound(compoundID) || compoundSet.findOtherCompound(compoundID);
			if (compound !== null && compound.selected === true) {
				duplicates.push(compoundSet.getTitle());
			}
		}

		return duplicates;
	};

	/**
	* Expands/collapses the alternative candidates of one card, building their
	* markup the first time it is opened. A name can match a hundred KEGG
	* compounds, so rendering every card's alternatives up front would put
	* hundreds of thousands of nodes in the document that nobody asked for.
	*/
	this.showOtherCompoundsHandler = function(button) {
		var card = button.closest(".metaboliteBox");
		var otherCompoundsPanel = card.find(".otherCompoundsPanel");
		var isVisible = button.hasClass("visible");

		if (!isVisible) {
			if (otherCompoundsPanel.is(":empty")) {
				var setIndex = parseInt(card.attr("data-compoundset"), 10);
				otherCompoundsPanel.html(this.items[setIndex].renderOtherCompounds());
			}
			card.addClass("expandedBox");
			button.addClass("visible").html('<i class="fa fa-eye-slash"></i> Hide');
		} else {
			card.removeClass("expandedBox");
			button.removeClass("visible").html('<i class="fa fa-eye"></i> Show');
		}

		otherCompoundsPanel.toggle(!isVisible);
	};

	this.checkForm = function() {
		// Asked of the model, not of the rendered checkboxes. Only the sets that
		// need disambiguation have a card, so counting checkboxes would report
		// "nothing to choose" for a job whose compounds all resolved
		// automatically - and would ignore the selections of the collapsed
		// alternatives, which are not in the document.
		return (this.model.getFoundCompounds().length === 0 || this.getSelectedCompounds().length > 0);
	};

	this.getSelectedCompounds = function() {
		var foundCompounds = this.model.getFoundCompounds();
		var checkedCompoundsIDs = [], compoundSet, compound;
		for(var i in foundCompounds){
			compoundSet = foundCompounds[i];
			for(var j in compoundSet.mainCompounds){
				compound = compoundSet.mainCompounds[j];
				if(compound.selected === true){
					checkedCompoundsIDs.push(compound.ID + "#" + compound.name + "#" + compoundSet.title);
				}
			}
			for(var j in compoundSet.otherCompounds){
				compound = compoundSet.otherCompounds[j];
				if(compound.selected === true){
					checkedCompoundsIDs.push(compound.ID + "#" + compound.name + "#" + compoundSet.title);
				}
			}
		}
		return checkedCompoundsIDs;
	};

	return this;
}
PA_Step2JobView.prototype = new View();

/***********************************************************************
* PA_Step2ReplicateDetectionView
*
* Step-2 confirmation panel for the replicate→sample aggregation feature.
* Renders one card per omic whose values-file column headers match the
* conservative replicate-suffix detector (see ReplicateDetection.py on the
* server). Each card lets the user choose between three modes:
*
*   - Show all replicates  (the existing visualisation, no aggregation).
*   - Average replicates    (auto: use the server-detected sample grouping).
*   - Upload design file    (manual: 2-column TSV mapping each column to a
*                            biological sample label).
*
* On confirm, the panel POSTs to /pa_apply_replicate_mapping per-omic. The
* server walks every Feature, computes per-sample means, and stores
* sampleValues/sampleRelevant on each OmicValue. Step-4 reads those when
* the visualisation toggle flips to "samples" mode.
***********************************************************************/
function PA_Step2ReplicateDetectionView() {
	this.name = "PA_Step2ReplicateDetectionView";
	this.omics = [];

	this.loadModel = function(jobModel) {
		this.model = jobModel;
		// Pull every gene/compound omic. We surface a card whenever the server
		// produced *any* detection result — including partial — so the user
		// always has the option to upload an explicit design file.
		var allOmics = (jobModel.getGeneBasedInputOmics() || [])
			.concat(jobModel.getCompoundBasedInputOmics() || []);
		this.omics = allOmics.filter(function(o) {
			var det = o.replicateDetection;
			return det && (det.status === "complete" || det.status === "partial");
		});
	};

	this.hasContent = function() {
		return this.omics.length > 0;
	};

	/**
	 * Build the contentbox HTML for one omic card. Rendered into a single
	 * outer box so the styling matches the existing Step-2 cards (the
	 * `omicSummaryBox` / `contentbox` pattern).
	 */
	this._renderOmicCard = function(omic) {
		var det = omic.replicateDetection;
		var omicId = omic.omicName.replace(/[^a-zA-Z0-9]/g, "_");
		var nSamples = det.sampleHeader.length;
		var nReplicates = det.mapping.filter(function(m) { return m >= 0; }).length;

		// Build a small preview list — capped to keep the UI compact.
		var previewRows = det.sampleHeader.slice(0, 12).map(function(sample, idx) {
			var replicateCols = det.groups[idx].map(function(colIdx) {
				return omic.omicHeader[colIdx + 1];
			}).join(", ");
			return '<li><b>' + sample + '</b> ← ' + replicateCols + '</li>';
		}).join("");
		if (det.sampleHeader.length > 12) {
			previewRows += '<li class="repDetectionMore">…and ' + (det.sampleHeader.length - 12) + ' more</li>';
		}

		var statusNote = "";
		if (det.status === "partial") {
			var unmatchedCols = det.unmatched.map(function(idx) {
				return omic.omicHeader[idx + 1];
			}).slice(0, 5).join(", ");
			statusNote =
				'<p class="repDetectionWarn"><i class="fa fa-exclamation-triangle"></i> ' +
				'Detection is incomplete — ' + det.unmatched.length + ' column(s) ' +
				'do not look like replicates (' + unmatchedCols +
				(det.unmatched.length > 5 ? ', …' : '') +
				'). Upload a design file to confirm the grouping.</p>';
		}

		// Default radio: "auto" if complete, otherwise "off".
		var autoChecked   = (det.status === "complete") ? "checked" : "";
		var offChecked    = (det.status === "complete") ? "" : "checked";

		return '' +
			'<div class="repDetectionCard" data-omic="' + omic.omicName + '" data-omicid="' + omicId + '">' +
			'  <h3>' + omic.omicName + '</h3>' +
			'  <p class="repDetectionSummary">' +
			       nSamples + ' sample(s) detected across ' + nReplicates + ' replicate column(s).' +
			'  </p>' +
			   statusNote +
			'  <ul class="repDetectionPreview">' + previewRows + '</ul>' +
			'  <div class="repDetectionRadios">' +
			'    <label><input type="radio" name="repMode_' + omicId + '" value="off" ' + offChecked + '> Show all replicates</label>' +
			'    <label><input type="radio" name="repMode_' + omicId + '" value="auto" ' + autoChecked + ' ' +
			          (det.status === "complete" ? "" : "disabled") +
			          '> Average replicates' + (det.status === "complete" ? " <span class=\"repDetectionRecommended\">(recommended)</span>" : "") + '</label>' +
			'    <label><input type="radio" name="repMode_' + omicId + '" value="manual"> Upload design file</label>' +
			'  </div>' +
			'  <div class="repDetectionManual" style="display: none;">' +
			'    <input type="file" class="repDetectionFile" accept=".tsv,.txt,.tab,.csv" />' +
			'    <p class="repDetectionFormatHint">2 columns, tab- or comma-separated: <code>sample_column &lt;TAB&gt; sample_label</code>. Header row optional.</p>' +
			'  </div>' +
			'  <div class="repDetectionStatus"></div>' +
			'</div>';
	};

	this.initComponent = function() {
		var me = this;
		if (!this.hasContent()) {
			return null;
		}

		var cards = this.omics.map(function(o) { return me._renderOmicCard(o); }).join("");

		this.component = Ext.widget({
			xtype: 'box',
			cls: "contentbox omicSummaryBox repDetectionBox",
			minHeight: 240,
			html:
				'<div id="repDetection">' +
				'  <h2>Replicate detection ' +
				'    <span class="helpTip" title="When your values file contains technical or biological replicates of the same biological sample (e.g., Ctrl_R1, Ctrl_R2), Paintomics can collapse them to one cell per sample in the pathway visualization. Choose how each omic should be handled below."></span>' +
				'  </h2>' +
				'  <p>The column headers below look like <i>replicates</i> of a smaller set of biological samples. ' +
				'     Choose how Paintomics should display them in the pathway visualization. ' +
				'     You can change this later from the visualization toolbar.</p>' +
				   cards +
				'</div>',
			listeners: {
				boxready: function() {
					me._wireHandlers();
					initializeTooltips(".helpTip");
				}
			}
		});

		return this.component;
	};

	/**
	 * Per-card jQuery wiring: switching the auto/off radios applies the
	 * mode immediately (no explicit Apply step). Switching to "manual"
	 * just reveals the file picker — the apply call fires once the user
	 * actually chooses a design file.
	 */
	this._wireHandlers = function() {
		var me = this;

		$(".repDetectionCard").each(function() {
			var $card = $(this);

			$card.find("input[type=radio]").change(function() {
				var mode = $card.find("input[type=radio]:checked").val();
				$card.find(".repDetectionManual").toggle(mode === "manual");
				$card.find(".repDetectionStatus")
					.removeClass("repDetectionError repDetectionOK")
					.text("");
				if (mode === "auto" || mode === "off") {
					me._applyForCard($card);
				}
			});

			$card.find(".repDetectionFile").change(function() {
				me._applyForCard($card);
			});
		});
	};

	this._applyForCard = function($card) {
		var omicName = $card.attr("data-omic");
		var mode = $card.find("input[type=radio]:checked").val();
		var $status = $card.find(".repDetectionStatus");

		$status.removeClass("repDetectionError repDetectionOK").text("Applying…");

		var send = function(designBody) {
			$.ajax({
				type: "POST",
				url: SERVER_URL_PA_APPLY_REPLICATE_MAPPING,
				contentType: "application/json",
				data: JSON.stringify({
					jobID:    this.model.getJobID(),
					omicName: omicName,
					mode:     mode,
					design:   designBody || null
				}),
				context: this,
				success: function(response) {
					if (response.success) {
						$status.addClass("repDetectionOK");
						if (response.status === "cleared") {
							$status.text("Cleared — replicates will be shown individually.");
						} else {
							$status.text(
								"Applied — " + response.sampleHeader.length + " sample(s), " +
								response.featuresUpdated + " feature(s) updated."
							);
						}
						// Mirror the result onto the model so Step-4 picks it up
						// without an extra server round-trip.
						var omic = this._findInputOmic(omicName);
						if (omic) {
							omic.sampleHeader     = response.sampleHeader;
							omic.replicateMapping = response.mapping;
							omic.replicateSource  = response.mode;
						}
					} else {
						$status.addClass("repDetectionError");
						$status.text(response.errorMessage || "Server returned an error.");
					}
				},
				error: function(xhr) {
					$status.addClass("repDetectionError");
					var msg = "Network error.";
					try {
						var parsed = JSON.parse(xhr.responseText);
						if (parsed && parsed.errorMessage) msg = parsed.errorMessage;
					} catch (e) { /* keep default */ }
					$status.text(msg);
				}
			});
		}.bind(this);

		if (mode === "manual") {
			var fileInput = $card.find(".repDetectionFile")[0];
			if (!fileInput || !fileInput.files || !fileInput.files[0]) {
				$status.addClass("repDetectionError").text("Please choose a design file first.");
				return;
			}
			var reader = new FileReader();
			reader.onload = function(e) {
				send(e.target.result);
			};
			reader.onerror = function() {
				$status.addClass("repDetectionError").text("Could not read file.");
			};
			reader.readAsText(fileInput.files[0]);
		} else {
			send(null);
		}
	};

	this._findInputOmic = function(omicName) {
		var omics = (this.model.getGeneBasedInputOmics() || [])
			.concat(this.model.getCompoundBasedInputOmics() || []);
		for (var i = 0; i < omics.length; i++) {
			if (omics[i].omicName === omicName) return omics[i];
		}
		return null;
	};

	return this;
}
PA_Step2ReplicateDetectionView.prototype = new View();

/**
* "1 compound found" / "4 compounds found": the noun agrees with the count and
* the verb is the past participle. This read "compounds founds" - and, for a
* single match, "1 compounds founds" - since 2014.
*
* @param {Number} count how many candidates were matched
* @param {String} noun "compound" or "alternative compound"
* @returns {String}
*/
function foundCountLabel(count, noun) {
	return count + " " + noun + ((count === 1) ? "" : "s") + " found";
}

/**
* One candidate compound as plain HTML: a checkbox, the KEGG link and the data
* attributes that the delegated handlers in PA_Step2JobView read back.
*
* This replaces PA_Step2CompoundView, which built an Ext box plus its own
* Ext.tip.ToolTip per candidate. Those components, multiplied by the number of
* matched compounds, are what froze step 2 on a compound-heavy job.
*
* @param {Compound} compound the candidate
* @param {Number} columnWidth width in px of the cell, as the old view had it
* @returns {String}
*/
function renderCompoundCandidate(compound, columnWidth, aiPickedID) {
	var compoundID = compound.getID();
	var safeID = Ext.String.htmlEncode(compoundID);
	var safeName = Ext.String.htmlEncode(compound.getName());
	// Marks the one candidate the AI chose, so a card with four ticked-looking
	// rows still says WHICH row the machine is responsible for.
	var picked = (aiPickedID && compoundID === aiPickedID) ? " aiPickedCandidate" : "";

	return '' +
	'<div class="metaboliteCompound' + picked + '" data-compound-id="' + safeID + '" data-compound-name="' + safeName + '"' +
	' style="float:left; width:' + columnWidth + 'px; max-width:' + columnWidth + 'px; margin-top:5px;' +
	' white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' +
	'  <input type="checkbox"' + (compound.isSelected() ? " checked" : "") + ' name="metabolite" value="' + safeID + '">' +
	'  <a href="http://www.kegg.jp/dbget-bin/www_bget?' + encodeURIComponent(compoundID) + '" target="_blank">' + safeName + '</a>' +
	'</div>';
}

function PA_Step2CompoundSetView() {
	/***********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step2CompoundSetView";

	/***********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	this.loadModel = function(model) {
		this.model = model;
	};

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* True when this input name actually leaves the user something to decide.
	*
	* A set with exactly one candidate, no alternatives, and that candidate
	* already selected is fully resolved: its card was a single pre-ticked
	* checkbox that could only be turned off. Skipping those is what makes a
	* job with thousands of matched names openable.
	*
	* The "already selected" half of the test is not cosmetic. The cross-box
	* de-duplicator in JobController.step1OnFormSubmitHandler unselects the
	* losing copy when two input names propose the same KEGG compound, so a
	* lone candidate can arrive with selected === false. That one renders
	* unchecked today and the user must be able to tick it, so it keeps its
	* card.
	*
	* @returns {Boolean}
	*/
	this.needsDisambiguation = function() {
		var mainCompounds = this.model.getMainCompounds();
		var otherCompounds = this.model.getOtherCompounds();

		// Nothing matched at all: there is no card to draw.
		if (mainCompounds.length + otherCompounds.length === 0) {
			return false;
		}
		if (otherCompounds.length > 0) {
			return true;
		}

		return !(mainCompounds.length === 1 && mainCompounds[0].isSelected() === true);
	};

	/**
	* The whole card as HTML. `index` is this view's position in
	* PA_Step2JobView.items and is written into the card so a delegated handler
	* can map a click back to this view without walking a component tree.
	*
	* @param {Number} index
	* @returns {String}
	*/
	/**
	* Tick exactly one candidate in this set and untick every other.
	*
	* The only mutation the AI path performs on the model. It is scoped to this
	* one compound set by construction, so a suggestion can never reach across
	* to another input name's candidates.
	*
	* @param {String} keggID the candidate to keep
	* @returns {Boolean} whether anything actually changed
	*/
	this.selectOnly = function(keggID) {
		var compounds = this.model.getMainCompounds().concat(this.model.getOtherCompounds());

		// Membership is decided BEFORE anything moves. Written the other way -
		// untick as you scan, check afterwards - an id this set does not
		// contain clears every tick in it on the way to returning false, which
		// is the worst outcome available: the user loses a selection they made,
		// to an answer that was never valid for this card.
		var found = compounds.some(function(compound) {
			return compound.getID() === keggID;
		});
		if (!found) {
			return false;
		}

		var changed = false;
		compounds.forEach(function(compound) {
			var wanted = (compound.getID() === keggID);
			if (compound.selected !== wanted) {
				compound.selected = wanted;
				changed = true;
			}
		});
		return changed;
	};

	/**
	* The "AI" / "AI unsure" chip on a card, with its reason as the tooltip.
	*
	* @returns {String}
	*/
	this.renderAIBadge = function() {
		var state = this.aiState;
		if (!state) {
			return "";
		}
		// Three states, three colours, and the deterministic one is NOT the
		// AI colour. A rule that matched a name did not consult a model, and
		// dressing it in the AI blue would claim credit the feature has not
		// earned -- the point of the chip is to say what touched this card.
		var kind = state.status === "unsure" ? "unsure"
			: (state.tier === "ai" ? "ai" : "auto");
		var label = {unsure: "AI unsure", ai: "AI", auto: "Auto"}[kind];
		var icon = {unsure: "fa-question-circle", ai: "fa-magic", auto: "fa-check"}[kind];
		var reason = Ext.String.htmlEncode(state.reason || "");

		return '<span class="aiBadge aiBadge-' + kind + '"' +
		       (reason ? ' title="' + reason + '"' : "") + '>' +
		       '<i class="fa ' + icon + '"></i> ' + label + '</span>';
	};

	this.renderCard = function(index) {
		var mainCompounds = this.model.getMainCompounds();
		var otherCompounds = this.model.getOtherCompounds();

		var aiPickedID = (this.aiState && this.aiState.keggID) || null;
		var cardClass = "contentbox metaboliteBox";
		if (this.aiState) {
			cardClass += this.aiState.status === "unsure" ? " aiBox-unsure"
				: (this.aiState.tier === "ai" ? " aiBox-ai" : " aiBox-auto");
		}

		var html =
		'<div class="' + cardClass + '" data-compoundset="' + index + '">' +
		'  <h3 class="metaboliteTitle">' + Ext.String.htmlEncode(this.model.getTitle()) +
		     this.renderAIBadge() + '</h3>' +
		'  <h4 style="padding-left: var(--pa-card-inset);">' + foundCountLabel(mainCompounds.length, "compound") + '</h4>' +
		'  <div class="mainCompoundsPanel" style="padding: 3px 15px; overflow: hidden;">' +
		mainCompounds.map(function(compound) {
			return renderCompoundCandidate(compound, 200, aiPickedID);
		}).join("") +
		'  </div>';

		// Only offer the control when there is something behind it: the old
		// markup printed "0 alternative compounds founds" with a Show link over
		// an empty container.
		if (otherCompounds.length > 0) {
			html +=
			'  <h4 style="padding-left: var(--pa-card-inset);">' + foundCountLabel(otherCompounds.length, "alternative compound") +
			'    <a class="showOtherCompoundsButton" href="javascript:void(0)"><i class="fa fa-eye"></i> Show</a>' +
			'  </h4>' +
			'  <div class="otherCompoundsPanel" style="padding: 3px 15px; overflow: hidden; display: none;"></div>';
		}

		return html + '</div>';
	};

	/**
	* The alternative candidates, built on demand when the card is expanded.
	*
	* @returns {String}
	*/
	this.renderOtherCompounds = function() {
		var aiPickedID = (this.aiState && this.aiState.keggID) || null;
		return this.model.getOtherCompounds().map(function(compound) {
			return renderCompoundCandidate(compound, 250, aiPickedID);
		}).join("");
	};

	return this;
}
PA_Step2CompoundSetView.prototype = new View();

/**
* The mapping donut's own data labels cannot be trusted at this size:
* Highcharts drops any label that does not fit, and in a 327x195 chart neither
* of the two fits - "Mapped features", the number the whole panel exists to
* report, was never drawn on any omic, and an omic mapped at 100% drew a bare
* ring with no number at all. Rather than fight the label distributor, the
* counts are printed under the chart as HTML, which also gives the compound
* based omics - which have no donut, only a "See Compounds disambiguation"
* note - somewhere to state their numbers.
*
* @param {Number} mappedFeatures features matched against the databases
* @param {Number} unmappedFeatures features left unmatched
* @returns {String} the caption markup
*/
function mappingSummaryCaption(mappedFeatures, unmappedFeatures) {
	var mapped = Number(mappedFeatures) || 0;
	var unmapped = Number(unmappedFeatures) || 0;
	var total = mapped + unmapped;

	// An omic with no input features at all must not divide by zero.
	var mappedPct = (total > 0) ? Math.round(mapped / total * 100) : 0;
	var unmappedPct = (total > 0) ? (100 - mappedPct) : 0;

	var row = function(color, count, label, percentage) {
		return '<div>' +
			'<span style="display:inline-block; width:9px; height:9px; border-radius:50%; vertical-align:middle; background:' + color + ';"></span> ' +
			'<b>' + count.toLocaleString() + '</b> ' + label + ' (' + percentage + '%)' +
			'</div>';
	};

	return '<div class="mappingSummaryCaption" style="text-align:center; font-size:12px; line-height:1.6; padding:0 5px 8px;">' +
		row("rgb(106, 208, 150)", mapped, "mapped", mappedPct) +
		row("rgb(250, 112, 112)", unmapped, "unmapped", unmappedPct) +
		'</div>';
}

/**
* The mapped/unmapped ring, drawn the same way for every omic.
*
* Extracted because the compound omics were not getting one. The old code drew
* this only for gene-based omics and gave a compound omic
* `<b>See Compounds disambiguation</b>`, 60px down an otherwise empty 327x195
* box -- a slot that looked broken beside four cards that all had a chart, and
* a line that looked like a link and was not one.
*
* The reason given was that a compound omic has no per-database breakdown, and
* that is true -- but the breakdown was only ever the tooltip's `note`. The
* ring itself is mapped against unmapped, which every omic has.
*
* @param {String} divName the panel's id prefix
* @param {String} omicName series name, shown in the tooltip
* @param {Number} mapped features that resolved to an identifier
* @param {Number} unmapped features that did not
* @param {String} note per-database detail for the tooltip, "" when there is none
*/
function renderMappingDonut(divName, omicName, mapped, unmapped, note) {
	$('#' + divName + 'mapping_summary_plot').highcharts({
		chart: {type: 'pie', height: 195},
		title: {
			text: "Mapped/Unmapped features",
			style: {"fontSize": "13px"}
		},
		credits: {enabled: false},
		tooltip: {
			pointFormat: '{series.name}: <b>{point.y}</b><br/><br/>{point.options.note}<br/>'
		},
		plotOptions: {
			pie: {
				// Off on purpose: see mappingSummaryCaption. At this size
				// Highcharts hid the "Mapped features" label on every omic and
				// clipped the other one, so the ring is now the proportion and
				// the caption underneath carries the numbers. With no labels to
				// leave room for, the ring can sit in the middle of its box.
				dataLabels: {enabled: false},
				center: ['50%', '45%']
			}
		},
		series: [{
			type: 'pie',
			name: omicName,
			size: 100,
			innerSize: '30%',
			data: [{
				name: 'Unmapped features',
				y: Number.parseFloat(unmapped),
				color: "rgb(250, 112, 112)",
				note: ""
			}, {
				name: 'Mapped features',
				y: Number.parseFloat(mapped),
				color: "rgb(106, 208, 150)",
				note: note
			}]
		}]
	});
}

function PA_OmicSummaryPanel(omicName, dataDistribution, isCompoundOmic) {
	/***********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.omicName = omicName;
	//   0        1       2    3    4    5     6,   7   8      9        10
	//[MAPPED, UNMAPPED, MIN, P10, Q1, MEDIAN, Q3, P90, MAX, MIN_IR, Max_IR]
	this.dataDistribution = dataDistribution;

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.initComponent = function() {
		var me = this;

		var divName = this.omicName.replace(/[^A-Z0-9]/ig, "_").toLowerCase() + "_";

		this.component = Ext.widget({
			xtype: "box",
			cls: "contentbox omicSummaryBox",
			html: '<h3 class = "metaboliteTitle" style="display:inline-block;margin-right: 20px;">' + this.omicName + '</h3>' +
			'<div>' +
			'  <div style="height:195px; overflow:hidden; width:50%; float: right;" id="' + divName + 'data_dstribution_plot"></div>' +
			// The chart keeps its fixed height; the caption sits below it inside
			// the same half-width column, which is what makes the counts
			// readable regardless of what the chart decides to draw.
			'  <div style="width:50%;">' +
			'    <div style="height:195px; overflow:hidden;" id="' + divName + 'mapping_summary_plot"></div>' +
			'    <div id="' + divName + 'mapping_summary_caption"></div>' +
			'  </div>' +
			'	 <div style="margin: 0 auto; text-align: center" id="customvalues_' + divName + '_summary"></div>' +
			'</div>',
			listeners: {
				boxready: function() {
					// Declared here so the caption below can read it whichever
					// branch filled it in; these three used to be implicit globals.
					var mappedFeatures, mappedInfo, added_info;

					// if (me.dataDistribution[1] !== -1 && me.dataDistribution[0] !== -1) {
					if (! isCompoundOmic) {
						// Mapped features can differ between used databases
						mappedInfo = me.dataDistribution[0];

						added_info = "";

						if (! Object.keys(mappedInfo).length) {
							mappedFeatures = mappedInfo;
						} else {
							if ("Total" in mappedInfo) {
								mappedFeatures = mappedInfo["Total"];

								added_info = Object.keys(mappedInfo).map(function(db) {
									return("• " + db + ": " + mappedInfo[db]);
								}).join('<br />');
							} else {
								mappedFeatures = mappedInfo[Object.keys(mappedInfo)[0]];
								added_info = "(KEGG database)";
							}
						}

						renderMappingDonut(divName, me.omicName, mappedFeatures,
							me.dataDistribution[1], added_info);
					} else {
						// A compound omic is matched once against KEGG compound ids, so
						// there is no per-database breakdown for the TOOLTIP -- and that
						// is all that is missing. The mapped and unmapped counts it does
						// have are the same two numbers every other omic's ring is drawn
						// from. They were being discarded, and the slot printed a bold
						// line 60px down an otherwise empty 327x195 box.
						mappedFeatures = me.dataDistribution[0];
						added_info = "";
						renderMappingDonut(divName, me.omicName, mappedFeatures,
							me.dataDistribution[1], added_info);
					}

					// A real control now. It used to be a bare <b> styled like a
					// link: it looked clickable and did nothing when clicked.
					$('#' + divName + 'mapping_summary_caption')
						.html(mappingSummaryCaption(mappedFeatures, me.dataDistribution[1]) +
							(isCompoundOmic
								? '<div class="mappingSummaryJump">' +
								  '<a href="javascript:void(0)" class="compoundsJumpLink">' +
								  'See compounds disambiguation</a></div>'
								: ''))
						.off("click.paJump")
						.on("click.paJump", ".compoundsJumpLink", function() {
							var target = document.querySelector(".compoundsIntroBox");
							if (target) {
								target.scrollIntoView({block: "start", behavior: "smooth"});
							}
						});

					//   0        1       2    3    4    5     6,   7   8      9        10
					//[MAPPED, UNMAPPED, MIN, P10, Q1, MEDIAN, Q3, P90, MAX, MIN_IR, Max_IR]
					//TODO REVISAR...
					//                    var yAxisMin = Math.floor(me.dataDistribution[9]) ;
					//                    var yAxisMax = Math.floor(me.dataDistribution[10]) + 0.5;
					//                    debugger;


					// TODO: leave this prepared in case it's needed in the frontpage
					// Ext.create('Ext.slider.MultiCustom', {
					// 		 renderTo: "customvalues_" + divName + '_summary',
					// 		 name: "customslider_" + me.omicName,
					// 		 width: 240,
					// 		 minValue: me.dataDistribution[2],
					// 		 maxValue: me.dataDistribution[8],
					// 		 customValues: [me.dataDistribution[2], me.dataDistribution[8]]
					//  });

					$('#' + divName + 'data_dstribution_plot').highcharts({
						chart: {
							type: 'boxplot',
							height: 195,
							inverted: true
						},
						credits: {enabled: false},
						title: {
							text: "Data distribution",
							style: {
								"fontSize": "13px"
							}
						},
						legend: {enabled: false},
						plotOptions: {
							boxplot: {
								medianColor: "#ff0000"
							}
						},
						xAxis: {
							labels: {
								enabled: false
							},
							title: null
						},
						tooltip: {
							formatter: function() {
								var text = '<span style="font-size:9px; text-align: right;"><em>' + me.omicName + '</em><br/>';
								text += "<b>Min (outliers inc.): </b>" + (me.dataDistribution[2]).toFixed(4) + '<br/>';
								text += "<b>Min value    : </b>" + (this.point.low / 10).toFixed(4) + '<br/>';
								text += "<b>Percentile 10: </b>" + (me.dataDistribution[3]).toFixed(4) + '<br/>';
								text += "<b>Q1           : </b>" + (this.point.q1 / 10).toFixed(4) + '<br/>';
								text += "<b>Median       : </b>" + (this.point.median / 10).toFixed(4) + '<br/>';
								text += "<b>Q3           : </b>" + (this.point.q3 / 10).toFixed(4) + '<br/>';
								text += "<b>Percentile 90: </b>" + (me.dataDistribution[7]).toFixed(4) + '<br/>';
								text += "<b>Max value    : </b>" + (this.point.high / 10).toFixed(4) + '<br/>';
								text += "<b>Max (outliers inc.): </b>" + (me.dataDistribution[8]).toFixed(4) + '<br/></span>';

								return text;
							}
						},
						yAxis: {
							labels: {
								formatter: function() {
									return this.value / 10;
								}
							},
							gridLineWidth: 0.1,
							plotLines: [{
								value: me.dataDistribution[3] * 10,
								color: '#001dff',
								width: 1,
								dashstyle: "DashDot",
								label: {
									text: 'p10',
									align: 'center',
									style: {
										color: 'gray'
									}
								}
							}, {
								value: me.dataDistribution[7] * 10,
								color: '#001dff',
								width: 1,
								dashstyle: "DashDot",
								label: {text: 'p90',align: 'center', style: {color: 'gray'}}
							}]
						},
						//   0        1       2    3    4    5     6,   7   8      9        10
						//[MAPPED, UNMAPPED, MIN, P10, Q1, MEDIAN, Q3, P90, MAX, MIN_IR, Max_IR]
						series: [{
							name: 'Values',
							data: [
								[me.dataDistribution[9] * 10, me.dataDistribution[4] * 10, me.dataDistribution[5] * 10, me.dataDistribution[6] * 10, me.dataDistribution[10] * 10]
							],
							tooltip: null
						}],
					});


				}
			}
		});

		return this.component;
	};
	return this;
}
PA_OmicSummaryPanel.prototype = new View();
