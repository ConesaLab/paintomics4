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
* - PA_Step2CompoundSetView
* - PA_Step2CompoundView
*
*/
//Ext.require('Ext.chart.*');

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
		var foundCompounds = this.model.getFoundCompounds();
		var compoundSetView = null;
		for (var i in foundCompounds) {
			compoundSetView = new PA_Step2CompoundSetView();
			compoundSetView.loadModel(foundCompounds[i]);
			foundCompounds[i].addObserver(compoundSetView);
			this.items.push(compoundSetView);
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
			'  <h2 >Feature ID/name translation summary <span class="helpTip" title="For example, for Gene Expression data, the diagram indicated the percentage of the input genes (names or identifiers) which were successfully mapped to a Kegg Gene Identifier."></h2>' +
			'  <p>' +
			'    Below you will find an overview of the results after matching the input files against the PaintOmics databases.<br>' +
			'    As a general rule, the bigger the percentage of mapped features, the better the results obtained in later stages.<br>' +
			'    If the mapping percentage was low, manually check your results and input data.<br><br>' +
			((Object.keys(dataDistribution).length > 0) ? '  <a href="javascript:void(0)" id="download_mapping_file"><i class="fa fa-download"></i> Download ID/Name mapping results.</a>' : "") +
			'  </p>' +
			'</div>'
		},
		{
			xtype: 'box',
			cls: "contentbox omicSummaryBox", minHeight: 240,
			html: '<div id="about">' +
			'  <h2 >Data distribution summary <span class="helpTip" title=" "></h2>' +
			'  <p>' +
			'    The following diagrams show the data distribution summary of each data set provided.<br>' +
			'    By default the percentiles 10 and 90 will be taken as a reference for the colour scale when generating the heatmaps, but <b>in the <span style="text-decoration: underline;">next step</span> you will be able to change the setting</b> using the "Visual settings" button located in the toolbar, the one showed here.<br>' +
			'		 <div style="margin: 15px auto;text-align:center;"><img src="resources/images/settingsbutton.png" width="400" height="73" /></div>' +
			'  </p>' +
			'</div>'
		}];

		/* INFO PANEL ABOUT DATABASES USED */
		var databases = me.getModel().getDatabases();
		var compoundOmics = me.getModel().getCompoundBasedInputOmics().map(x => x.omicName);
		var matchingPerDB = {};
		var numberOfClusters = [];

		for (var omicName in dataDistribution) {
			// Get total features
			var totalFeatures = dataDistribution[omicName][1];
			var isCompoundBased = (compoundOmics.indexOf(omicName) > -1);

			// Add the largest matched set of features or just KEGG if there is only 1 DB		
			if (dataDistribution[omicName][0].hasOwnProperty("Total")) {
				totalFeatures += dataDistribution[omicName][0]["Total"];
			} else {
				totalFeatures += dataDistribution[omicName][0][0] || dataDistribution[omicName][0][Object.keys(dataDistribution[omicName][0])[0]];
			}

			databases.forEach(function(dbname) {
				// Look for DB name in feature table matches ID
				var featureTable = Object.keys(dataDistribution[omicName][0]).find(function(el) {return el.indexOf(dbname) != -1; });

				matchingPerDB[dbname] = $.extend(matchingPerDB[dbname] || {}, {
					[omicName]: {
						"matched": dataDistribution[omicName][0][featureTable],
						"percentage": Math.ceil(dataDistribution[omicName][0][featureTable]/totalFeatures * 100)
					}});
			});
			
			if ( ! isCompoundBased) {
				numberOfClusters.push({
					xtype: 'combo',
					fieldLabel: omicName,
					name: 'clusterNumber:' + omicName,
					value: 'dynamic',
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					labelWidth: 300,
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
					html: '<p>In the next step Paintomics will calculate the clusters present in the data provided for each omic. It will use the method k-means using a automatically calculated number of cluster or the ones you define here. In the next step you will also be able to modify them by selecting individual omics in the network.<br><br></p>'
				},{
					xtype: 'form',
					maxWidth: 600,
					bodyCls: "divForm",
					style: "margin: 0 auto 20px auto;",
					layout: {type: 'vbox', align: 'stretch'},
					defaults: {labelAlign: "right", border: false},
					items: numberOfClusters
				}]
			}, {xtype: 'container', html:'<div style="display: none;"></div>'});
		}

		if (databases.length > 1) {

			var dbs_descriptions = {
				"KEGG": '<a href="http://www.kegg.jp/kegg/" target="_blank">Kyoto Encyclopedia of Genes and Genomes</a> is a database resource for understanding high-level functions and utilities of the biological system, such as the cell, the organism and the ecosystem, from molecular-level information, especially large-scale molecular datasets generated by genome sequencing and other high-throughput experimental technologies.',
				"MapMan": 'Oriented towards plant species, in combination with <a href="http://www.gomapman.org/" target="_blank">GoMapMan</a>, it provides additional pathways as well as an improved and more consolidated annotation for the model species Arabidopsis, and several crop species (potato, tomato, rice).',
				"Reactome": '<a href="http://www.reactome.org/" target="_blank">Reactome</a> is an open-source, open access, manually curated and peer-reviewed pathway database, containing information of around 20 organisms, including human, mouse and arabidopsis, among others.'
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
				html:
				'<h2>Multiple databases used</h2>' +
				'<div>' +
				'  <p>The selected species had more than one database available. Your final analysis contains information about the following databases: ' +
				'			<dl id="dbs_dl">' + dl_dbs + '</dl>' +
				'     <br>' +
				'    The following diagrams combine the matched & unmatched elements considering <b>all</b> databases; for a desambiguation please place the cursor over the graph and check the emerging tooltip.<br>' +
				'  </p>' +
				'</div>'
			};

			/* Add an empty container to restore "odd" position of next sibling elements */
			omicSummaryPanelComponents.splice(2, 0, dbs_message, {xtype: 'container', html:'<div style="display: none;"></div>'});
		}

		var compoundsComponents = [];
		if (me.items.length > 0) {
			compoundsComponents.push({
				xtype: 'box', cls: "contentbox omicSummaryBox",
				html: '<div id="about">' +
				'  <h2>Compounds disambiguation</h2>' +
				'  <p>Some compounds names need to be disambiguated.</p>' +
				'  <p>Please check the list below and choose the compounds in which you are interested.</p> ' +
				'</div>'
			});

			for (var i in me.items) {
				compoundsComponents.push(me.items[i].getComponent());
			}
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
					xtype: "container", itemId: "compoundsPanelsContainer",
					cls: "compoundsPanelsContainer",
					layout: 'column',
					items: compoundsComponents
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
					initializeTooltips(".helpTip");
				},
				beforedestroy: function() {
					me.getModel().deleteObserver(me);
				}
			}
		});

		return this.component;
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
	this.checkForm = function() {
		return ($(".compoundsPanelsContainer input[type=checkbox]").length === 0 || $(".compoundsPanelsContainer  :checked").length > 0);
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

function PA_Step2CompoundSetView() {
	/***********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.mainCompoundsPanelItems = [];
	this.otherCompoundsPanelItems = [];

	/***********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	this.loadModel = function(model) {
		this.model = model;

		var panelAux;
		var compounds = this.model.getMainCompounds();
		for (var i in compounds) {
			panelAux = new PA_Step2CompoundView(25, 200);
			panelAux.loadModel(compounds[i]);
			compounds[i].addObserver(panelAux);
			this.mainCompoundsPanelItems.push(panelAux);
		}
		compounds = this.model.getOtherCompounds();
		for (var i in compounds) {
			panelAux = new PA_Step2CompoundView(30, 250);
			panelAux.loadModel(compounds[i]);
			this.otherCompoundsPanelItems.push(panelAux);
		}
	};
	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.initComponent = function() {
		var me = this;

		var mainCompoundsPanelComponents = [];
		for (var i in this.mainCompoundsPanelItems) {
			mainCompoundsPanelComponents.push(this.mainCompoundsPanelItems[i].getComponent());
		}

		this.component = Ext.widget({
			xtype: "container", cls: "contentbox metaboliteBox",
			items: [{
				xtype: "label", itemId: "titleBox",
				html:
				'<h3 class="metaboliteTitle">' + this.getModel().getTitle() + '</h3>' +
				'<h4 style="padding-left: 10px;">' + mainCompoundsPanelComponents.length + ' compounds founds</h4>'
			}, {
				xtype: 'container',
				itemId: "mainCompoundsPanel",
				style: "padding: 3px 15px;",
				layout: 'column',
				items: mainCompoundsPanelComponents
			}, {
				xtype: "label",
				html: '<h4 style="padding-left: 10px;">' + this.otherCompoundsPanelItems.length + ' alternative compounds founds <a class="showOtherCompoundsButton" href="javascript:void(0)"><i class="fa fa-eye"></i> Show</a></h4> '
			}, {
				xtype: 'container', itemId: "otherCompoundsPanel",
				style: "padding: 3px 15px;", layout: 'column', hidden: true,
				items: []
			}],
			listeners: {
				boxready: function() {
					var container = this.queryById("otherCompoundsPanel");

					var inputSelectionHandler = function() {
						var id = $(this).val();
						var selected = $(this).is(":checked");
						var compound = me.model.findOtherCompound(id) || me.model.findMainCompound(id);
						compound.selected = selected;

						if(selected){
							//If the user select a compound which is repeated and already selected, warn
							var others = $("input[value=" + id + "]:checked");
							if(others.length > 1){
								var message = "<b>Duplicated compounds:</b><ul>";
								others.each(function(){
									message += "<li>" + $(this).next().text() + "</li>";
								});
								message += "</ul>";

								showWarningMessage("Compound already selected", {
									message : "This compound has been already selected in other box. Duplicated compounds may affect to the results in next stages.<br>" + message,
									showButton : true
								});
							}
						}
					};

					//TODO: Event fired when a checkbox is checked
					$(this.el.dom).find("input").change(inputSelectionHandler);

					$(this.el.dom).find(".showOtherCompoundsButton").click(function() {
						var isVisible = $(this).hasClass("visible");
						if (!isVisible) {
							//If the items haven't been created yet, create them
							if (container.items.length === 0) {
								var otherCompoundsPanelComponents = [];
								for (var i in me.otherCompoundsPanelItems) {
									otherCompoundsPanelComponents.push(me.otherCompoundsPanelItems[i].getComponent());
								}
								container.add(otherCompoundsPanelComponents);
								//Add the event for the new checboxes
								setTimeout(function(){
									$(container.el.dom).find("input").change(inputSelectionHandler);
								}, 2000);

							}
							$(this).parents(".metaboliteBox").addClass("expandedBox");
							$(this).addClass("visible");
							$(this).html('<i class="fa fa-eye-slash"></i> Hide');
						} else {
							$(this).parents(".metaboliteBox").removeClass("expandedBox");
							$(this).removeClass("visible");
							$(this).html('<i class="fa fa-eye"></i> Show');
						}
						container.setVisible(!isVisible);
					});
				},
				beforedestroy: function() {
					me.getModel().deleteObserver(me);
				}
			}
		});

		return this.component;
	};

	return this;
}
PA_Step2CompoundSetView.prototype = new View();

function PA_Step2CompoundView(maxLength, columnWidth) {
	/***********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.title = "";
	this.columnWidth = columnWidth;
	this.maxLength = maxLength;
	/***********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	this.loadModel = function(model) {
		this.model = model;
		this.title = this.model.getName();
	};
	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.initComponent = function() {
		var me = this;
		var titleAux = this.title;
		// if (this.title.length > this.maxLength) {
		// 	titleAux = this.title.substr(0, this.maxLength) + "[...]";
		// }
		this.component = Ext.widget({
			xtype: "box",
			html:
			'<div style="max-width:' + this.columnWidth + 'px; white-space: nowrap; overflow: hidden; text-overflow:ellipsis;">' +
			'  <input type="checkbox"' + (this.model.isSelected() ? "checked" : "") + ' name="metabolite" value="' + this.model.getID() + '">' +
			'  <a href="http://www.kegg.jp/dbget-bin/www_bget?' + this.model.getID() + '" target="_blank">' + titleAux +'</a>' +
			'</div>',
			style: {
				marginTop: "5px",
				width: this.columnWidth + "px",
				display: "inline-box",
				textOverflow : "ellipsis"
			},
			listeners: {
				beforedestroy: function() {
					me.getModel().deleteObserver(me);
				}
			}
		});

		this.component.tip =
		'<b>' + this.title + '</b> (' + this.model.getID() + ')' +
		'<div>'+
		'  <div style="display: block; text-align:center; padding: 20px;"><i class="fa fa-circle-o-notch fa-spin fa-fw"></i> Loading image...</div>' +
		'  <img style="display: block; margin:auto;" src="http://rest.kegg.jp/get/' + this.model.getID() + '/image">' +
		'</div>';
		this.component.addListener("afterrender", function(c) {
			Ext.create('Ext.tip.ToolTip', {
				target: c.getEl(),
				html: c.tip,
				listeners: {
					boxready: function() {
						var tip = this;
						$(this.el.dom).find("img").on('load', function() {
							$(this).prev().remove();
							tip.doLayout();
						});
					}
				}
			});
		});
		return this.component;
	};
	return this;
}
PA_Step2CompoundView.prototype = new View();

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
			'  <div style="height:195px; overflow:hidden; width:50%; " id="' + divName + 'mapping_summary_plot"></div>' +
			'	 <div style="margin: 0 auto; text-align: center" id="customvalues_' + divName + '_summary"></div>' +
			'</div>',
			listeners: {
				boxready: function() {
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

						//WHEN THE BOX IS READY, CALL HIGHCHARTS AND CREATE THE PIE WITH MAPPING SUMMARY AND THE BOXPLOT FOR DATA DISTRIBUTION
						$('#' + divName + 'mapping_summary_plot').highcharts({
							chart: {type: 'pie',height: 195},
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
									dataLabels: {
										useHTML: true,
										enabled: true,
										distance: 10,
										formatter: function() {
											return "<p style='text-align:center'>" + this.y + "</br>" + this.point.name.replace(" ", "</br>") + '</p>';
										}
									},
									center: ['50%', '30%']
								}
							},
							series: [{
								type: 'pie',
								name: me.omicName,
								size: 100,
								innerSize: '30%',
								data: [{
									name: 'Unmapped features',
									y: Number.parseFloat(me.dataDistribution[1]),
									color: "rgb(250, 112, 112)",
									note: ""
								}, {
									name: 'Mapped features',
									y: Number.parseFloat(mappedFeatures),
									color: "rgb(106, 208, 150)",
									note: added_info
								}]
							}]
						});
					} else {
						$('#' + divName + 'mapping_summary_plot').html("<b>See Compounds disambiguation</b>");
					}

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
