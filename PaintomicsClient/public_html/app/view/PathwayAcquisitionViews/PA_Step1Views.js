/* global Ext, APP_VERSION, dragula */

//# sourceURL=PA_Step1Views.js
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
* - PA_Step1JobView
* - OmicSubmittingPanel
* - RegionBasedOmicSubmittingPanel
*/
function PA_Step1JobView() {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step1JobView";
	this.nFiles = 0;
	this.exampleMode = false;

	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	this.isExampleMode = function() {
		return this.exampleMode;
	};

	/*********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* This function remove all panels and reset the application.
	*/
	this.resetViewHandler = function() {
		this.controller.resetButtonClickHandler(this);
	};
	/**
	* This function adds a new OmicSubmittingPanel for the given type.
	* @param {type} type for the new omic panel.
	*/
	this.addNewOmicSubmittingPanel = function(type) {
		var newElem, submitForm;

		if (type === "geneexpression") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "Gene expression",
				fileType: "Gene Expression file",
				relevantFileType: "Relevant Genes list"
			});
		} else if (type === "proteomics") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "Proteomics",
				fileType: "Proteomic quatification",
				relevantFileType: "Relevant proteins list",
				featureEnrichment: "features"
			});
		} else if (type === "metabolomics") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "Metabolomics",
				fileType: "Metabolomic quatification",
				relevantFileType: "Relevant Compound list",
				featureEnrichment: "features"
			});
		} else if (type === "mirnaseq") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "miRNA-Seq",
				fileType: "miRNA-Seq quatification",
				relevantFileType: "Relevant miRNA-Seq list"
			});
		} else if (type === "dnaseseq") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "DNAse-Seq",
				fileType: "DNAse-Seq quatification",
				relevantFileType: "Relevant DNAse-Seq list"
			});
		} else if (type === "mirnabasedomic") {
			newElem = new MiRNAOmicSubmittingPanel(this.nFiles);
		} else if (type === "bedbasedomic") {
			newElem = new RegionBasedOmicSubmittingPanel(this.nFiles);
		} else if (type === "otheromic") {
			newElem = new OmicSubmittingPanel(this.nFiles);
		}
		newElem.setParent(this);

		submitForm = this.getComponent().queryById("submittingPanelsContainer");
		submitForm.insert(1, newElem.getComponent()).focus();

		if (type !== "otheromic" && type !== "bedbasedomic" && type !== "mirnabasedomic") {
			$("div.availableOmicsBox[title=" + type + "]").css("display", "none");
		}

		if (submitForm.items.getCount() > 2) {
			$(".dragHerePanel").fadeOut();
		}

		this.nFiles++;

		return newElem;
	};
	/**
	* This function removes a given omicSubmittingPanel and restores the omic type
	* at the availableOmics panel.
	*
	* @param {OmicSubmittingPanel} omicSubmittingPanel
	*/
	this.removeOmicSubmittingPanel = function(omicSubmittingPanel) {
		var submitForm = this.getComponent().queryById("submittingPanelsContainer");
		submitForm.remove(omicSubmittingPanel.getComponent());

		if (omicSubmittingPanel.type !== "otheromic" && omicSubmittingPanel.type !== "bedbasedomic" &&
		    omicSubmittingPanel.type !== "mirnabasedomic" && !this.exampleMode) {
			$("div.availableOmicsBox[title=" + omicSubmittingPanel.type + "]").fadeIn();
		}

		if (submitForm.items.getCount() === 2 && !this.exampleMode) {
			$(".dragHerePanel").fadeIn();
		}

		delete omicSubmittingPanel;
	};
	/**
	* This function sets the Example mode for the first step.
	*/
	this.setExampleModeHandler = function() {
		var panel, fileField, omicSubmittingPanels;

		this.exampleMode = true;

		this.getComponent().queryById("speciesCombobox").setValue("mmu");
		this.getComponent().queryById("speciesCombobox").setReadOnly(true);

		omicSubmittingPanels = this.getComponent().queryById("submittingPanelsContainer").query("[cls=omicbox]");

		for (var i in omicSubmittingPanels) {
			$("#" + omicSubmittingPanels[i].el.id + " a.deleteOmicBox").click();
		}

		this.addNewOmicSubmittingPanel("mirnaseq").setExampleMode();
		this.addNewOmicSubmittingPanel("dnaseseq").setExampleMode();
		this.addNewOmicSubmittingPanel("proteomics").setExampleMode();
		this.addNewOmicSubmittingPanel("metabolomics").setExampleMode();
		this.addNewOmicSubmittingPanel("geneexpression").setExampleMode();


		$("#availableOmicsContainer").css("display", "none");
		$("#exampleButton").css("display", "none");


		showInfoMessage("About this example", {
			message: 'The following example data was loaded:' +
			'<ul>' +
			'  <li>Gene Expression data: 6337 genes [5524 relevant genes].</li>' +
			'  <li>Proteomics data: 1110 proteins [148 relevant proteins].</li>' +
			'  <li>Metabolomics data: 59 compounds [41 relevant compounds].</li>' +
			'  <li>DNase-seq data: 5101 regions [3596 relevant regions].</li>'+
			'  <li>miRNA-seq data: 4998 genes with miRNA values [605 relevant genes].</li>'+
			'</ul>',
			showButton: true,
			height: 240
		});
	};

	/**
	* This function is called when the user press the "Run Paintomics" button.
	* First we get all the RegionBasedOmic panels.
	* If there is one or more panel which contains to-be-processed BED files then
	* we send first those panels to server for processing "step1SubmitRegionBasedOmics".
	*
	* If there is not RegionBasedOmic panels or they contain already processed files
	* then we call to normal execution "step1OnFormSubmitHandler".
	*
	*/
	this.submitFormHandler = function() {
		var aux, omicBoxes;

		omicBoxes = this.getComponent().queryById("submittingPanelsContainer").query("container[cls=omicbox regionBasedOmic],[cls=omicbox miRNABasedOmic]");
		for (var i = omicBoxes.length; i--;) {
			aux = omicBoxes[i].queryById("itemsContainer");
			if (aux === null || aux.isDisabled()) {
				omicBoxes.splice(i, 1);
			}
		}

		if (omicBoxes.length > 0) {
			this.controller.step1ComplexFormSubmitHandler(this, omicBoxes);
		} else {
			this.controller.step1OnFormSubmitHandler(this);
		}
	};
	/**
	* This function checks the validity for each OmicSubmittingPanel
	*
	* @returns Boolean
	*/
	this.checkForm = function() {
		var items, valid, emptyFields;

		items = this.getComponent().query("container[cls=omicbox], container[cls=omicbox regionBasedOmic],[cls=omicbox miRNABasedOmic]");
		valid = this.getComponent().queryById("speciesCombobox").isValid();
		for (var i in items) {
			valid = valid && items[i].isValid();
		}

		emptyFields = 0;
		for (var i in items) {
			if (items[i].isEmpty() === true) {
				emptyFields++;
				$(items[i].getEl().dom).find("a.deleteOmicBox").click();
			}
		}

		return valid && (emptyFields < items.length);
	};

	//    this.showMyDataPanel = function () {
	//        this.controller.showMyDataPanelClickHandler(this);
	//    };

	this.initComponent = function() {
		var me = this;
		this.component = Ext.widget({
			xtype: "container",
			minHeight: 800,
			padding: '10',
			items: [{
				xtype: "box",
				cls: "toolbar secondTopToolbar",
				html:
				'<a class="button btn-danger btn-right" id="resetButton"><i class="fa fa-refresh"></i> Reset</a>' +
				'<a class="button btn-success btn-right" id="submitButton"><i class="fa fa-play"></i> Run PaintOmics</a>' +
				'<a class="button btn-secondary btn-right" id="exampleButton"><i class="fa fa-file-text-o"></i> Load example</a>'
			}, {
				xtype: 'box',
				cls: "contentbox",
				style: "margin-top:50px; max-width:1300px",
				html: '<div id="about">' +
				' <h2>Welcome to PaintOmics (' + APP_VERSION + ')</h2>' +
				' <p>' +
				'   <b>Paintomics</b>  is a web tool for the integrative visualization of multiple omic datasets onto KEGG pathways. Currently Paintomics supports integrated visualization of multiple species of different biological kingdoms and offers user the possibility to request any other organism present in the KEGG database.<br/><br/>' +
				'   <b>Paintomics</b> is easy to run because the application itself guides you through the three different steps that are detailed next:' +
				' </p>' +
				' <ul style="float: left;width: 65%;"> ' +
				'   <li><b>Data uploading:</b>' +
				'	<ol>' +
				'		<li>Choose your organism (see selection box below).</li>' +
				'		<li>Upload your multi-omic data (see form below). You can <a href="resources/paintomics_example_data.zip">download the example data from here</a> to check the format of the files. You can also load an example (<a class="button btn-secondary btn-inline btn-small" href="javascript:void(0)"><i class="fa fa-file-text-o"></i> Load example</a> button in the upper right corner of the screen) to explore Paintomics functionalities.</li>' +
				'		<li>Click on <a class="button btn-success btn-inline btn-small" href="javascript:void(0)"><i class="fa fa-play"></i> Run PaintOmics</a> button.</li>' +
				'	</ol><br/></li> ' +
				'   <li><b>Identifier and Name Matching and Metabolite assignment:</b> Paintomics requires Entrez IDs for working with KEGG pathways, so the tool will convert the names and identifiers from different sources and databases in user’s the input data. This screen give users information about the number of features successfully mapped to KEGG pathways. It also shows the data distribution that will be used for pathway colouring, which can be modified when visualizing a pathway. Additionally, the metabolite names assignments are displayed and users can choose their favourite option in case of ambiguity. Click <a href="javascript:void(0)" class="button btn-success btn-inline btn-small"><i class="fa fa-play"></i> Next step</a> button when you are ready.<br/><br/></li>' +
				'   <li><b>Results:</b> Pathways summary, Pathways classification, Pathways network, Pathways enrichment, Pathways visualization (by clicking <a href="javascript:void(0)" class="button btn-inline btn-small"  style="background-color:#ADA6A6;font-size: 14px;"><i class="fa fa-paint-brush"></i></a> for any of the displayed pathways in Pathways enrichment section). Read more about these analyses in <a href="http://paintomics.readthedocs.io/en/latest/" target="_blank">our documentation</a>.</li>' +
				' </ul>' +
				' <div id="graphicalAbstract" style="float:left;text-align:center;cursor:pointer;width: 34%;"><img style="margin: 30px auto;border:1px solid #222;" src="resources/images/GraphicalAbstract_thumb.png" /></div>' +
				' <p style="clear:both;">' +
				'   Please check the <b><a href="http://paintomics.readthedocs.org/en/latest/" target="_blank">User guide</a></b> for further information. For any question on <b>Paintomics</b>, you can send an e-mail to <a href="mailto:paintomics@cipf.es">paintomics@cipf.es</a>.' +
				' </p>' +
				'</div>'
			}, {
				xtype: 'form',
				maxWidth: 1300,
				bodyCls: "contentbox",
				layout: {type: 'vbox', align: 'stretch'},
				defaults: {labelAlign: "right", border: false},
				items: [
					{xtype: "box", flex: 1, html:'<h2>Data uploading</h2><h3>1. Organism selection </h3>'},
					{xtype: "container", flex: 1, layout: {type: "hbox"}, items: [
						{
							xtype: "container", layout: { type: "vbox", align: "stretch" }, flex: 0.4, items: [
							{
								xtype: 'combo',fieldLabel: 'Organism', name: 'specie',
								style: "margin: 10px 10px 10px 20px;",
								flex: 1,
								maxWidth: 450,
								itemId: "speciesCombobox",
								allowBlank: false,
								forceSelection: true,
								emptyText: 'Please choose an organism',
								displayField: 'name',
								valueField: 'value',
								queryMode: 'local',
								labelWidth: 150,
								store: Ext.create('Ext.data.ArrayStore', {
									fields: ['name', 'value'],
									autoLoad: true,
									sortOnLoad: true,
									remoteSort: false,
									sorters: [{
							        property: 'name',
							        direction: 'ASC'
							    }],
									proxy: {
										type: 'ajax',
										url: SERVER_URL_GET_AVAILABLE_SPECIES,
										reader: {
											type: 'json',
											root: 'species',
											successProperty: 'success'
										}
									}
								})
							},
							{
								xtype: "box", flex: 1, html:
								'<span class="infoTip" style=" font-size: 12px; margin-left: 190px; margin-bottom: 10px;">'+
								' Not your organism? Request new organisms <a href="javascript:void(0)" id="newOrganismRequest" style="color: rgb(211, 21, 108);">clicking here</a>.' +
								'</span>'
							}]
						},
						{
							xtype: "container", layout: { type: "vbox", align: "stretch" }, flex: 0.5, items: [
							{
								xtype: "textfield", 
								fieldLabel: "Enter a job description", 
								allowBlank: true,
								name: 'jobDescription',
								style: "margin: 10px 20px;",
								labelWidth: 150,
								width: 650,
								flex: 0,
								maxLength: 100
							},
							{
								xtype: "container", layout: { type: "vbox", align: "stretch" }, flex: 0.6, hidden: false, items: [
								{
									xtype: 'checkboxgroup', fieldLabel: 'Databases',
									style: "margin: 10px 10px 10px 20px;",
									maxWidth: 650,
									allowBlank: false,
									columns: 2,
									disabled: false,
									labelWidth: 148,
									// Hardcoded DBs (as they can be considered static) 
									items: [
											// Only for information, KEGG database is added always on server side 
											{ boxLabel: 'KEGG (required)', name: 'databases[]', inputValue: 'KEGG', checked: true, disabled: true },
											{ boxLabel: 'MapMan', name: 'databases[]', inputValue: 'MapMan', checked: false },
											{ boxLabel: 'Reactome', name: 'databases[]', inputValue: 'Reactome', checked: false },
									]
								},
								{
									xtype: "box", flex: 1, html:
									'<span class="infoTip" style=" font-size: 12px; margin: 0 20px 10px 190px;">'+
									' For <span style="color: rgb(211, 21, 108);">some</span> species more than one database might be available. Choose which ones do you want to include in the analysis.' +
									'</span>'
								}
								]
							}
							]
						}
						]
					},
					/*{
							xtype: "container",
							layout: "hbox",
							flex: 1,
							items: [{
								xtype: "textfield", 
								fieldLabel: "Enter a job description", 
								allowBlank: true,
								name: 'jobDescription',
								style: "margin: 20px 20px;",
								labelWidth: 150,
								width: 450,
								flex: 0
							}]
					}*/,
					{
						xtype: "box",
						html: '<h3>2. Choose the files to upload <a class="button btn-right btn-small" href="http://www.paintomics.org/resources/paintomics_example_data.zip"><i class="fa fa-download"></i> Download example data</a></h3>'
					},
					{
						xtype: "container",
						layout: 'hbox',
						items: [{
							xtype: "box",
							id: "availableOmicsContainer",
							minHeight: 400,
							width: 250,
							padding: 10,
							html: '<h2 style="text-align:center;">Available omics</h2>' +
							'<div class="availableOmicsBox" title="geneexpression"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Gene Expression</h4></div>' +
							'<div class="availableOmicsBox" title="metabolomics"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Metabolomics</h4></div>' +
							'<div class="availableOmicsBox" title="proteomics"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Proteomics</h4></div>' +
							'<div class="availableOmicsBox" title="mirnabasedomic"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Regulatory omic</h4></div>' +
							'<div class="availableOmicsBox" title="bedbasedomic"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Region based omic</h4></div>' +
							'<div class="availableOmicsBox" title="otheromic"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Other omics</h4></div>'
						}, {
							xtype: "container",
							id: "submittingPanelsContainer",
							minHeight: 150,
							minWidth: 200,
							maxWidth: 600,
							margin: 10,
							flex: 1,
							layout: {type: 'vbox',align: "stretch"},
							items: [
								{xtype: 'box',html: '<h2  style="text-align:center;">Selected omics</h2>'},
								{xtype: 'box',html: '<p class="dragHerePanel">Drag and drop here your selected <i>omics</i></p>'}
							]
						},
				   		{
							xtype: "container",
							id: "additionalInfoContainer",
							minHeight: 150,
							minWidth: 200,
							maxWidth: 300,
							margin: 10,
							flex: 1,
							layout: {type: 'vbox',align: "stretch"},
							items: [
								{xtype: 'box',html: '<div class="content"><h5><i class="fa fa-info-circle" style="color: #2C7FDD; font-size: 50px;"></i> Help</h5><p>Drag and drop omics from <i>"Available"</i> to <i>"Selected"</i> area or click the <i class="fa fa-plus-circle"  style="font-size: 18px;"></i> button.</p><p>If you do not need them, delete with with <i class="fa fa-trash" style="font-size: 18px;"></i>.</p><p>Once you are done, click on the "Run PaintOmics" button on the upper-right corner.</p><p>Make sure to <span style="text-decoration: underline;">choose an organism</span> from the select box first!</p></div>.'}
							]
						}]
					}					
				]
			}],
			listeners: {
				boxready: function() {
					$("#submitButton").click(function() {
						me.submitFormHandler();
					});
					$("#exampleButton").click(function() {
						me.setExampleModeHandler();
					});
					$("#resetButton").click(function() {
						me.resetViewHandler();
					});
					$("#addOtherDataButton").click(function() {
						me.addNewOmicSubmittingPanel();
					});
					$("#newOrganismRequest").click(function() {
						application.getController("DataManagementController").requestNewSpecieHandler();
					});

					$(".availableOmicsBox a").click(function(){
						var type = $(this).parents(".availableOmicsBox").first().attr("title");
						me.addNewOmicSubmittingPanel(type);
					});
			
					$("#graphicalAbstract").click(function(){
						var imageWindow = new Ext.Window({
							modal:true,
							border:false,
							plain:true,
							width: '80%',
							height: '90%',
							constrain:true,
							html:'<img style="margin: 0 auto;max-height:100%; max-width:100%;" src="resources/images/GraphicalAbstract.png" />',
							resizable:{preserveAspectRatio: true}
						});
						imageWindow.show();
					});

					var containers = [$("#availableOmicsContainer")[0], $("#submittingPanelsContainer-targetEl")[0]];

					//INITIALIZE THE DRAG AND DROP
					dragula(containers, {
						moves: function(el, container, handle) {
							// elements are always draggable by default
							return el.tagName !== "H5" && container.id !== "submittingPanelsContainer-targetEl";
						}
					}).on("drop", function(el, container, source) {
						if (container.id === "submittingPanelsContainer-targetEl") {
							var type = $(el).attr("title");
							me.addNewOmicSubmittingPanel(type);
						}
						this.cancel(true);
					});


					me.addNewOmicSubmittingPanel("metabolomics");
					me.addNewOmicSubmittingPanel("geneexpression");
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
PA_Step1JobView.prototype = new View();

function DefaultSubmittingPanel(nElem, options) {
	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	this.getOmicName = function() {
		return this.omicName;
	};
	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.toogleContent = function(alternativeComponent="itemsContainerAlt") {
		var component = this.getComponent().queryById(alternativeComponent);
		var isVisible = component.isVisible();
		component.setVisible(!isVisible);
		component.setDisabled(isVisible);

		component = this.getComponent().queryById("itemsContainer");
		if (component) {
			component.setVisible(isVisible);
			component.setDisabled(!isVisible);
		}
		return this;
	};

	this.removeOmicSubmittingPanel = function() {
		this.getParent().removeOmicSubmittingPanel(this);
		return this;
	};
}
DefaultSubmittingPanel.prototype = new View;

function OmicSubmittingPanel(nElem, options) {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	options = (options || {});

	this.title = "Other data type";
	this.namePrefix = "omic" + nElem;
	this.omicName = "";
	this.mapTo = "Gene";
	this.fileType = null;
	this.relevantFileType = null;
	this.featureEnrichment = "genes";

	this.class = "otherFileBox";

	/*IF THE TYPE WAS SPECIFIED (e.g. gene_expression)*/
	if (options.type !== undefined) {
		//TODO CAPITALIZE THE FIRST LETTER
		this.omicName = options.type;
		this.title = options.type;

		if (['Metabolomics'].indexOf(options.type) !== -1) {
			this.mapTo = "Compound";
		}

		this.fileType = options.fileType;
		this.relevantFileType = options.relevantFileType;
		this.type = this.title.replace(" ", "").toLowerCase();
		this.class = this.type + "FileBox";
		this.featureEnrichment = options.featureEnrichment || "genes";
	}
	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.setExampleMode = function(){
		var fileField = this.getComponent().queryById("mainFileSelector");
		fileField.setValue("example/" + this.type + "_example.tab");
		fileField.setDisabled(true);

		fileField = this.getComponent().queryById("secondaryFileSelector");
		fileField.setValue("example/" + this.type + "_relevant_example");
		fileField.setDisabled(true);
	};
	/*********************************************************************
	* COMPONENT DECLARATION
	***********************************************************************/
	this.initComponent = function() {
		var me = this;

		this.component = Ext.widget({
			xtype: "container", flex: 1, cls: "omicbox",
			type: me.type, layout: {align: 'stretch',type: 'vbox'},
			items: [
				{
					xtype: "box", flex: 1, cls: "omicboxTitle " + this.class, html:
					'<h4>' +
					' <a class="deleteOmicBox" href="javascript:void(0)" style="margin: 0; float:right;  padding-right: 15px;"><i class="fa fa-trash"></i></a>' +
					this.title +
					'</h4>'
				}, {
					xtype: "container",
					layout: {align: 'stretch',type: 'vbox'},
					padding: 10,
					defaults: {
						labelAlign: "right",
						labelWidth: 150,
						maxLength: 100,
						maxWidth: 500
					},
					items: [
						{
							xtype: 'combo',
							fieldLabel: 'Omic Name',
							name: this.namePrefix + '_omic_name',
							value: this.omicName,
							hidden: this.omicName !== "",
							itemId: "omicNameField",
							displayField: 'name',
							valueField: 'name',
							emptyText: 'Type or choose the omic type',
							editable: true,
							allowBlank: false,
							queryMode: 'local',
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name'],
								autoLoad: true,
								proxy: {
									type: 'ajax',
									url: 'resources/data/all_omics.json',
									reader: {
										type: 'json',
										root: 'omics',
										successProperty: 'success'
									}
								}
							})
						}, {
							xtype: "myFilesSelectorButton",
							fieldLabel: 'Data file',
							namePrefix: this.namePrefix,
							itemId: "mainFileSelector",
							helpTip: "Upload the feature quantification file (Gene expression, proteomics quantification,...) or choose it from your data folder."
						}, {
							xtype: 'combo', itemId: "fileTypeSelector",
							fieldLabel: 'File Type', emptyText: 'Type or choose the file type',
							name: this.namePrefix + '_file_type',
							hidden: this.omicName !== "",
							displayField: 'name', valueField: ' name',
							editable: true, allowBlank: false,
							value: (this.fileType !== null) ? this.fileType : null,
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name', 'type'],
								autoLoad: true,
								proxy: {
									type: 'ajax',
									url: 'resources/data/file_types.json',
									reader: {type: 'json', root: 'types', successProperty: 'success'}
								},
								filterOnLoad:true,
								filters: [{property: 'type', value : 'data'}]
							}),
							helpTip: "Specify the type of data for uploaded file (Gene Expression file, Proteomic quatification,...)."
						}, {
							xtype: "myFilesSelectorButton",
							fieldLabel: 'Relevant features file',
							namePrefix: this.namePrefix + '_relevant',
							itemId: "secondaryFileSelector",
							helpTip: "Upload the list of relevant features (relevant genes, relevant proteins,...)."
						}, {
							xtype: 'combo', itemId: "relevantFileTypeSelector",
							fieldLabel: 'File Type', emptyText: 'Type or choose the file type',
							name: this.namePrefix + '_relevant_file_type',
							hidden: this.omicName !== "",
							displayField: 'name', valueField: 'name',
							editable: true, allowBlank: false,
							value: (this.relevantFileType !== null) ? this.relevantFileType : null,
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name', 'type'],
								autoLoad: true,
								proxy: {
									type: 'ajax',
									url: 'resources/data/file_types.json',
									reader: {type: 'json', root: 'types', successProperty: 'success'}
								},
								filterOnLoad:true,
								filters: [{property: 'type', value : 'list'}]
							}),
							helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
						}, {
							xtype: 'combo',
							fieldLabel: 'Can be mapped to',
							name: this.namePrefix + '_match_type',
							hidden: this.omicName !== "",
							itemId: "mapToSelector",
							displayField: 'name', valueField: 'value',
							emptyText: 'Choose the file type',
							value: this.mapTo,
							editable: false,
							allowBlank: false,
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name', 'value'],
								data: [
									['Genes', 'gene'],
									['Metabolites', 'compound']
								]
							}),
							helpTip: "Defines whether the data can be assigned to Genes or to Metabolites, for example  the values of concentration for proteins that can be mapped to the corresponding codifying gene."
						},
						{
							xtype: 'combo',
							fieldLabel: 'Enrichment type',
							name: this.namePrefix + '_enrichment',
							hidden: this.omicName !== "",
							value: this.featureEnrichment.toString(),
							displayField: 'name', valueField: 'value',
							editable: false,
							allowBlank: false,
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name', 'value'],
								data: [
									['Genes', 'genes'],
									['Features', 'features']
								]
							}),
							helpTip: "Define how the Fisher contingency table must be done: counting genes or features (i.e: microRNA, proteins...)."
						}
					]
				}
			],
			isValid: function() {
				var valid = true;

				if (this.isEmpty) {
					return true;
				}

				if (this.queryById("omicNameField").getValue() === "") {
					valid = false;
					this.queryById("omicNameField").markInvalid("Please, specify a Omic Name.");
				}
				if (this.queryById("mainFileSelector").getValue() === "") {
					valid = false;
					this.queryById("mainFileSelector").markInvalid("Please, provide a Data file.");
				}
				if (this.queryById("fileTypeSelector").getValue() === null) {
					valid = false;
					this.queryById("fileTypeSelector").markInvalid("Please, specify a File type.");
				}
				if (this.queryById("secondaryFileSelector").getValue() !== "" && this.queryById("relevantFileTypeSelector").getValue() === null) {
					valid = false;
					this.queryById("relevantFileTypeSelector").markInvalid("Please, specify a File type.");
				}
				if (this.queryById("mapToSelector").getValue() === null) {
					valid = false;
					this.queryById("mapToSelector").markInvalid("Please, specify a this field.");
				}

				return valid;
			},
			isEmpty: function() {
				return (this.queryById("secondaryFileSelector").getValue() === "" && this.queryById("mainFileSelector").getValue() === "");
			},
			listeners: {
				boxready: function() {
					initializeTooltips(".helpTip");

					$(this.getEl().dom).find("a.deleteOmicBox").click(function() {
						me.removeOmicSubmittingPanel();
					});
				}
			}
		});

		return this.component;
	};
	return this;
}
OmicSubmittingPanel.prototype = new DefaultSubmittingPanel;

function RegionBasedOmicSubmittingPanel(nElem, options) {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	options = (options || {});

	this.title = "Region based omic";
	this.namePrefix = "omic" + nElem;
	this.omicName = "";
	this.mapTo = "Gene";
	this.fileType = null;
	this.relevantFileType = null;
	this.featureEnrichment = "genes";

	this.allowToogle = options.allowToogle !== false;
	this.removable = options.removable !== false;

	this.class = "bedbasedFileBox";

	/*IF THE TYPE WAS SPECIFIED (e.g. gene_expression)*/
	if (options.type !== undefined) {
		//TODO CAPITALIZE THE FIRST LETTER
		this.omicName = options.type;
		this.title = options.type;

		this.fileType = options.fileType;
		this.relevantFileType = options.relevantFileType;
		this.type = this.title.replace(" ", "").toLowerCase();
		this.class = this.type + "FileBox";
	}
	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.setExampleMode = function(){
		var component = this.getComponent();
		//component.queryById("toogleMapRegions").setVisible(false);

		component = component.queryById("itemsContainer");

		var field = component.queryById("mainFileSelector");
		field.setValue("example/" + this.type + "_example.tab");
		field.setDisabled(true);

		field = component.queryById("secondaryFileSelector");
		field.setValue("example/" + this.type + "_relevant_example");
		field.setDisabled(true);

		field = component.queryById("tertiaryFileSelector");
		field.setValue("example/mmu_reference.gtf");
		field.setDisabled(true);

		field = component.queryById("omicNameField");
		field.setValue("Region-omic");
		field.setDisabled(true);

		var otherFields = ["distanceField", "tssDistanceField", "promoterDistanceField", "geneAreaPercentageField", "regionAreaPercentageField", "gtfTagField", "summarizationMethodField", "reportSelector1","reportSelector2"];
		for(var i in otherFields){
			field = component.queryById(otherFields[i]);
			field.setReadOnly(true);
		}
	};
	this.setContent = function(target, values) {
		var component = this.getComponent().queryById(target);

		if (values.title) {
			component.queryById("omicNameField").setValue(values.title);
		}
		if (values.omicName) {
			component.queryById("omicNameField").setValue(values.omicName);
		}
		if (values.mainFile) {
			component.queryById("mainFileSelector").setValue(values.mainFile);
		}
		if (values.mainFileType) {
			component.queryById("fileTypeSelector").setValue(values.mainFileType);
		}
		if (values.secondaryFile) {
			component.queryById("secondaryFileSelector").setValue(values.secondaryFile);
		}
		if (values.secondaryFileType) {
			component.queryById("relevantFileTypeSelector").setValue(values.secondaryFileType);
		}
		if (values.toogleMapRegions) {
			component.queryById("toogleMapRegions").setVisible(values.toogleMapRegions === true);
		}
		if (values.configVars) {
			component.queryById("configVars").setValue(values.configVars);
		}
		if (values.enrichmentType) {
			component.queryById("enrichmentType").setValue(values.enrichmentType);
		}
		if (values.ignoreMissing) {
			component.queryById("ignoreMissing").setValue(values.ignoreMissing);
		}

		if (!component.isVisible()) {
			this.toogleContent();
		}
		return this;
	};

	/*********************************************************************
	* COMPONENT DECLARATION
	***********************************************************************/
	this.initComponent = function() {
		var me = this;
		this.component = Ext.widget({
			xtype: "container",
			flex: 1,
			type: me.type,
			cls: "omicbox regionBasedOmic",
			layout: {
				align: 'stretch',
				type: 'vbox'
			},
			items: [{
				xtype: "box",
				flex: 1,
				cls: "omicboxTitle " + this.class,
				html: '<h4><a class="deleteOmicBox" href="javascript:void(0)" style="margin: 0; float:right;  padding-right: 15px;">' +
				(me.removable ? ' <i class="fa fa-trash"></i></a>' : "</a>") + this.title +
				'</h4>'
			}, {
				xtype: "box",
				itemId: "toogleMapRegions",
				hidden: !this.allowToogle,
				html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_mapRegions"><label for="' + this.namePrefix + '_mapRegions">My regions are already mapped to Gene IDs, skip this step.</label></div>'
			},
			{
				xtype: "box",
				itemId: "toogleUseAssociations",
				hidden: !this.allowToogle,
				html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_useAssociations"><label for="' + this.namePrefix + '_useAssociations">Provide own associations lists.</label></div>'
			}, {
				xtype: "container",
				itemId: "itemsContainerAlt",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				padding: 10,
				hidden: true,
				disabled: true,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100,
					maxWidth: 500
				},
				items: [{
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					value: this.omicName,
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					queryMode: 'local',
					hidden: this.omicName !== "",
					editable: true,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Data file',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the feature quantification file (Gene expression, proteomics quantification,...) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					itemId: "fileTypeSelector",
					value: "Bed file (regions mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Gene Expression file, Proteomic quatification,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant features file',
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant features (relevant genes, relevant proteins,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					itemId: "relevantFileTypeSelector",
					value: "Relevant regions list (mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo,
					hidden: true
				},{
					xtype: 'textfield',
					name: this.namePrefix + '_config_args',
					hidden: true,
					itemId: 'configVars',
					maxLength: 1000
				}, {
					xtype: 'combo',
					itemId: 'enrichmentType',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or associations (combination of feature & gene)."
				}]
			}, {
				xtype: "container",
				itemId: "itemsContainerAssociations",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				disabled: true,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100,
					maxWidth: 500
				},
				hidden: true,
				items: [{
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					value: this.omicName,
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					queryMode: 'local',
					hidden: this.omicName !== "",
					editable: true,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Data file',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the feature quantification file (Gene expression, proteomics quantification,...) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					itemId: "fileTypeSelector",
					value: "Map file (features mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Gene Expression file, Proteomic quatification,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant features file',
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant features (relevant genes, relevant proteins,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					itemId: "relevantFileTypeSelector",
					value: "Relevant regulators list (mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Associations file',
					namePrefix: this.namePrefix + '_associations',
					itemId: "mainAssociationFileSelector",
					helpTip: "Upload the 2 column association file associating genes with features or choose it from your data folder."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant associations file',
					namePrefix: this.namePrefix + '_relevant_associations',
					itemId: "secondaryAssociationFileSelector",
					helpTip: "Upload the 2 column list of relevant associations (gene - feature) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo,
					hidden: true
				},{
					xtype: 'textfield',
					name: this.namePrefix + '_config_args',
					hidden: true,
					itemId: 'configVars',
					maxLength: 1000
				},
				{
					xtype: 'combo',
					itemId: 'enrichmentType',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or the relevant associations (combination of genes & features)."
				}]
			}, {
				xtype: "container",
				itemId: "itemsContainer",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				padding: 10,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100,
					maxWidth: 500
				},
				items: [{
					xtype: 'textfield',
					name: "name_prefix",
					hidden: true,
					itemId: "namePrefix",
					value: this.namePrefix
				}, {
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					hidden: this.omicName !== "",
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					editable: true,
					queryMode: 'local',
					allowBlank: false,
					value: (this.fileType !== null) ? this.fileType : null,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: 'textfield',
					hidden: true,
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo
				},
				/*REGIONS FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Regions file <br>(BED + Quantification)',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the regions file (BED format + Quantification) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					hidden: true,
					itemId: "fileTypeSelector",
					value: "Bed file (regions)"
				},
				/*RELEVANT REGIONS FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Relevant regions file",
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant regions (TAB format) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					hidden: true,
					itemId: "relevantFileTypeSelector",
					value: "Relevant regions list"
				},
				/*ANNOTATIONS FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Annotations file (GTF)",
					namePrefix: this.namePrefix + '_annotations',
					itemId: "tertiaryFileSelector",
					extraButtons: [{
						text: 'Use a GTF from Paintomics',
						handler: function() {
							var me = this;
							var _callback = function(selectedItem) {
								if (selectedItem !== null) {
									me.up("myFilesSelectorButton").queryById("visiblePathField").setValue("[inbuilt GTF files]/" + selectedItem[0].get("fileName"));
									me.up("myFilesSelectorButton").queryById("originField").setValue("inbuilt_gtf");
								}
							};
							Ext.widget("GTFSelectorDialog").showDialog(_callback);
						}
					}],
					helpTip: "Upload the Annotations file (GTF format), choose it from your data folder or browse the GFT files included in Paintomics."
				}, {
					xtype: 'textfield',
					hidden: true,
					fieldLabel: 'File Type',
					name: this.namePrefix + '_annotations_file_type',
					itemId: "referenceFileTypeSelector",
					value: "GTF file"
				},
				/*
				* OTHER FIELDS
				*/
				//report
				{
					xtype: 'textfield',
					hidden: true,
					name: this.namePrefix + '_report',
					fieldLabel: 'Report',
					value: "gene"
				},
				// allow missing
				{
					xtype: 'checkbox',
					itemId: "ignoreMissing",
					name: this.namePrefix + '_ignoremissing',
					fieldLabel: 'Ignore missing entries',
					checked: true,
					allowBlank: false,
					helpTip: "Allow those BED regions with chromosome names not present in the GTF file to be ignored instead of throwing an error."					
				},
				//distance
				{
					xtype: 'numberfield',
					itemId: "distanceField",
					name: this.namePrefix + '_distance',
					fieldLabel: 'Distance (kb)',
					value: 10,
					minValue: 0,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "Maximum distance in kb to report associations. Default: 10 (10kb)"
				},
				//tss
				{
					xtype: 'numberfield',
					itemId: "tssDistanceField",
					name: this.namePrefix + '_tss',
					fieldLabel: 'TSS region distance (bps)',
					value: 200,
					minValue: 0,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "TSS region distance. Default: 200 bps"
				},
				//promoter
				{
					xtype: 'numberfield',
					itemId: "promoterDistanceField",
					name: this.namePrefix + '_promoter',
					fieldLabel: 'Promoter region distance (bps)',
					value: 1300,
					minValue: 0,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "Promoter region distance. Default: 1300 bps"
				},
				//geneAreaPercentage
				{
					xtype: 'numberfield',
					itemId: "geneAreaPercentageField",
					name: this.namePrefix + '_geneAreaPercentage',
					fieldLabel: 'Overlapped gene area (%)',
					value: 50,
					minValue: 0,
					maxValue: 100,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "Percentage of the area of the gene overlapped to be considered to discriminate at transcript and gene level. Default: 90 (90%)"
				},
				//regionAreaPercentage
				{
					xtype: 'numberfield',
					itemId: "regionAreaPercentageField",
					name: this.namePrefix + '_regionAreaPercentage',
					fieldLabel: 'Overlapped region area (%)',
					value: 50,
					minValue: 0,
					maxValue: 100,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "Percentage of the region overlapped by the gene to be considered to discriminate at transcript and gene level. Default: 50 (50%)"
				},
				//rules //TODO
				//{xtype: 'textfield', hidden: true, fieldLabel: 'rules', name: this.namePrefix + '_report', itemId: "reportSelector", value: "gene"},
				//geneIDtag
				{
					xtype: 'textfield',
					itemId: "gtfTagField",
					name: this.namePrefix + '_geneIDtag',
					fieldLabel: 'GTF Tag for gene ID/name ',
					value: "gene_id",
					allowBlank: false,
					helpTip: "GTF tag used to get gene ids/names. Default: gene_id"
				},
				//summarization_method
				{
					xtype: 'combo',
					itemId: "summarizationMethodField",
					name: this.namePrefix + '_summarization_method',
					fieldLabel: 'Summarization method',
					editable: false,
					allowBlank: false,
					value: "mean",
					displayField: 'label',
					valueField: 'value',
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['label', 'value'],
						data: [
							["None", "none"],
							["Mean", "mean"],
							["Maximum", "max"]
						]
					}),
					helpTip: "Choose the strategy used to resolve regions mapping to the same gen region. Default: 'Mean'"
				},{
					xtype: 'combo',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment_pre',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or associations (combination of genes & features)."
				},{
					xtype: 'fieldcontainer',
					fieldLabel: 'Report',
					defaultType: 'radiofield',
					items: [{
						boxLabel: 'All regions',
						itemId: "reportSelector1",
						name: this.namePrefix + '_report',
						submitValue: false,
						checked: true,
						listeners: {
							change: function(radio, newValue, oldValue) {
								radio.up().queryById("reportOptionsContainer").setVisible(!newValue);
								var elems = radio.up().queryById("reportOptionsContainer").query("checkboxfield");
								for (var i in elems) {
									elems[i].setDisabled(newValue);
								}
								elems = radio.up().queryById("reportAllRegionsOption");
								elems.setDisabled(!newValue);
								elems.setValue(newValue);
							}
						}
					}, {
						boxLabel: 'Let me choose',
						itemId: "reportSelector2",
						name: this.namePrefix + '_report',
						submitValue: false,
						helpTip: "Indicates which regions will be selected from rgmatch output. E.g. Option 'First exon' will filter out all regions that do not map into the first exon of the corresponding gene."
					}, {
						xtype: 'container',
						defaultType: 'checkboxfield',
						hidden: true,
						itemId: 'reportOptionsContainer',
						items: [{
							xtype: 'label',
							text: 'Regions mapping at...'
						}, {
							boxLabel: 'All regions',
							name: this.namePrefix + '_reportRegions',
							inputValue: 'all',
							itemId: 'reportAllRegionsOption',
							checked: true,
							hidden: true
						}, {
							xtype: 'container',
							layout: 'hbox',
							defaultType: 'checkboxfield',
							defaults: {
								hideLabel: false,
								labelAlign: 'top',
								boxLabel: '',
								labelSeparator: "",
								style: 'text-align: center'
							},
							items: [{
								fieldLabel: 'Upstream',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'UPSTREAM',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #E3CEB0;'
							}, {
								fieldLabel: 'Promoter',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'PROMOTER',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #FFF2C0;'
							}, {
								fieldLabel: 'TSS',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'TSS',
								labelAlign: 'top',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #FFF6D3;'
							}, {
								fieldLabel: '1st Exon',
								name: this.namePrefix + '_reportRegions',
								inputValue: '1st_EXON',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #FFC4AD;'
							}, {
								fieldLabel: 'Introns',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'INTRON',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #D0DFF1;'
							}, {
								fieldLabel: 'Gene body',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'GENE_BODY',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #FFE0D3;'
							}, {
								xtype: 'label',
								text: 'Intr.',
								style: 'padding: 5px 3px; font-size:9px; margin-top:4px; background-color: #D0DFF1;'
							}, {
								xtype: 'label',
								text: 'G.B.',
								style: 'padding: 5px 3px; font-size:9px; margin-top:4px;  background-color: #FFE0D3;'
							}, {
								fieldLabel: 'Downstream',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'DOWNSTREAM',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #B2C9E3;'
							}]
						}]
					}]
				},
			]
		}],
		setContent: function(target, values) {
			me.setContent(target, values);
		},
		isValid: function() {
			var valid = true;
			var component = this.queryById("itemsContainerAlt");
			if (!component.isVisible()) {
				component = this.queryById("itemsContainerAssociations");

				if (!component.isVisible()) {
					component = this.queryById("itemsContainer");
				}
			}
			var items = component.query("field");
			for (var i in items) {
				valid = valid && (this.items[i] || items[i].validate());
			}

			if (component.queryById("mainFileSelector").getValue() === "") {
				valid = false;
				component.queryById("mainFileSelector").markInvalid("Please, provide a Data file.");
			}
			if (component.queryById("tertiaryFileSelector") && component.queryById("tertiaryFileSelector").getValue() === "") {
				valid = false;
				component.queryById("tertiaryFileSelector").markInvalid("Please, provide a GTF file.");
			}

			if (this.queryById("reportOptionsContainer").query("checkboxfield[checked=true]") < 1) {
				valid = false;
				this.queryById("reportOptionsContainer").query("checkboxfield").forEach(function(elem) {
					elem.markInvalid("Please, check at least one gene region.");
				});
			}

			return valid;
		},
		isEmpty: function() {
			var component = this.queryById("itemsContainerAlt");
			if (!component.isVisible()) {
				component = this.queryById("itemsContainerAssociations");

				if (!component.isVisible()) {
					component = this.queryById("itemsContainer");
				}
			}
			var empty = true;
			if (component.queryById("mainFileSelector").getValue() !== "") {
				empty = false;
			}
			if (component.queryById("tertiaryFileSelector") && component.queryById("tertiaryFileSelector").getValue() !== "") {
				empty = false;
			}

			return empty;
		},
		listeners: {
			boxready: function() {
				initializeTooltips(".helpTip");

				$("#" + me.namePrefix + "_mapRegions").change(function() {
					me.getComponent().queryById("toogleUseAssociations").setVisible(! $(this).is(':checked'));
					me.toogleContent();
				});

				$("#" + me.namePrefix + "_useAssociations").change(function() {
					me.getComponent().queryById("toogleMapRegions").setVisible(! $(this).is(':checked'));
					me.toogleContent("itemsContainerAssociations");
				});

				$(this.getEl().dom).find("a.deleteOmicBox").click(function() {
					me.removeOmicSubmittingPanel();
				});
			}
		}
	});

	return this.component;
};

return this;
}
RegionBasedOmicSubmittingPanel.prototype = new DefaultSubmittingPanel;

function MiRNAOmicSubmittingPanel(nElem, options) {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	options = (options || {});

	this.title = "Regulatory omic";
	this.namePrefix = "omic" + nElem;
	this.omicName = "";
	this.mapTo = "Gene";
	this.fileType = null;
	this.relevantFileType = null;
	this.featureEnrichment = "genes";

	this.allowToogle = options.allowToogle !== false;
	this.removable = options.removable !== false;

	this.class = "miRNAbasedFileBox";

	/*IF THE TYPE WAS SPECIFIED (e.g. gene_expression)*/
	if (options.type !== undefined) {
		//TODO CAPITALIZE THE FIRST LETTER
		this.omicName = options.type;
		this.title = options.type;

		this.fileType = options.fileType;
		this.relevantFileType = options.relevantFileType;
		this.type = this.title.replace(" ", "").toLowerCase();
		this.class = this.type + "FileBox";
	}
	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.setExampleMode = function(){
		var component = this.getComponent();
		//component.queryById("toogleMapRegions").setVisible(false);
		component = component.queryById("itemsContainer");

		var field = component.queryById("mainFileSelector");
		field.setValue("example/mirna_unmapped.tab");
		field.setDisabled(true);

		field = component.queryById("secondaryFileSelector");
		field.setValue("example/mirna_unmapped_relevant.tab");
		field.setDisabled(true);

		field = component.queryById("mirnaTargetsFileSelector");
		field.setValue("example/mmu_mirBase_to_ensembl.tab");
		field.setDisabled(true);

		field = component.queryById("rnaseqauxFileSelector");
		field.setValue("example/gene_expression_values.tab");
		field.setDisabled(true);

		field = component.queryById("omicNameField");
		field.setValue("miRNA");
		field.setDisabled(true);

		var otherFields = ["summarizationMethodField"];
		for(var i in otherFields){
			field = component.queryById(otherFields[i]);

			if (field != null) {
			    field.setReadOnly(true);
			}
		}
	};
	this.setContent = function(target, values) {
		var component = this.getComponent().queryById(target);

		if (values.title) {
			component.queryById("omicNameField").setValue(values.title);
		}
		if (values.omicName) {
			component.queryById("omicNameField").setValue(values.omicName);
		}
		if (values.mainFile) {
			component.queryById("mainFileSelector").setValue(values.mainFile);
		}
		if (values.mainFileType) {
			component.queryById("fileTypeSelector").setValue(values.mainFileType);
		}
		if (values.secondaryFile) {
			component.queryById("secondaryFileSelector").setValue(values.secondaryFile);
		}
		if (values.secondaryFileType) {
			component.queryById("relevantFileTypeSelector").setValue(values.secondaryFileType);
		}
		if (values.thirdFile) {
			component.queryById("thirdFileSelector").setValue(values.secondaryFile);
		}
		if (values.thirdFileType) {
			component.queryById("thirdFileTypeSelector").setValue(values.secondaryFileType);
		}
		if (values.fourthFile) {
			component.queryById("fourthFileSelector").setValue(values.secondaryFile);
		}
		if (values.ourthFileType) {
			component.queryById("fourthFileTypeSelector").setValue(values.secondaryFileType);
		}
		if (values.toogleMapRegions) {
			component.queryById("toogleMapRegions").setVisible(values.toogleMapRegions === true);
		}
		if (values.configVars) {
			component.queryById("configVars").setValue(values.configVars);
		}
		if (values.enrichmentType) {
			component.queryById("enrichmentType").setValue(values.enrichmentType);
		}

		if (!component.isVisible()) {
			this.toogleContent();
		}
		return this;
	};

	/*********************************************************************
	* COMPONENT DECLARATION
	***********************************************************************/
	this.initComponent = function() {
		var me = this;
		this.component = Ext.widget({
			xtype: "container",
			flex: 1,
			type: me.type,
			cls: "omicbox miRNABasedOmic",
			layout: {
				align: 'stretch',
				type: 'vbox'
			},
			items: [{
				xtype: "box",
				flex: 1,
				cls: "omicboxTitle " + this.class,
				html: '<h4><a class="deleteOmicBox" href="javascript:void(0)" style="margin: 0; float:right;  padding-right: 15px;">' +
				(me.removable ? ' <i class="fa fa-trash"></i></a>' : "</a>") + this.title +
				'</h4>'
			},
			{
				xtype: "box",
				itemId: "toogleMapRegions",
				hidden: !this.allowToogle,
				html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_mapRegions"><label for="' + this.namePrefix + '_mapRegions">My features are already mapped to Gene IDs, skip this step.</label></div>'
			},
			// {
			// 	xtype: "box",
			// 	itemId: "toogleUseAssociations",
			// 	hidden: !this.allowToogle,
			// 	html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_useAssociations"><label for="' + this.namePrefix + '_useAssociations">Provide own associations lists.</label></div>'
			// },
			{
				xtype: "container",
				itemId: "itemsContainerAlt",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				disabled: true,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100,
					maxWidth: 500
				},
				hidden: true,
				items: [{
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					value: this.omicName,
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					queryMode: 'local',
					hidden: this.omicName !== "",
					editable: true,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Data file',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the feature quantification file (Gene expression, proteomics quantification,...) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					itemId: "fileTypeSelector",
					value: "Map file (features mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Gene Expression file, Proteomic quatification,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant features file',
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant features (relevant genes, relevant proteins,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					itemId: "relevantFileTypeSelector",
					value: "Relevant regulators list (mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				},  {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Regulator associations file',
					namePrefix: this.namePrefix + '_associations',
					itemId: "thirdFileSelector",
					helpTip: "Upload the association list."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_associations_file_type',
					itemId: "associationsFileTypeSelector",
					value: "Regulator associations",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo,
					hidden: true
				},{
					xtype: 'textfield',
					name: this.namePrefix + '_config_args',
					hidden: true,
					itemId: 'configVars',
					maxLength: 1000
				},
				{
					xtype: 'combo',
					itemId: 'enrichmentType',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or associations (combination of genes & features)."
				}]
			}, {
				xtype: "container",
				itemId: "itemsContainer",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				padding: 10,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100,
					maxWidth: 500
				},
				items: [{
					xtype: 'textfield',
					name: "name_prefix",
					hidden: true,
					itemId: "namePrefix",
					value: this.namePrefix
				}, {
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					hidden: this.omicName !== "",
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					editable: true,
					queryMode: 'local',
					allowBlank: false,
					value: (this.fileType !== null) ? this.fileType : null,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: 'textfield',
					hidden: true,
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo
				},
				/*miRNA FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Regulators expression file <br>(ie: miRNA expression)',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the quantification file (i.e. miRNA Quantification) or choose it from your data folder. See above the accepted format for the file."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					hidden: true,
					itemId: "fileTypeSelector",
					value: "Gene Expression file"
				},
				/*RELEVANT miRNA FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Relevant regulators file<br> (optional)",
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant (differentially expressed) features (TAB format) or choose it from your data folder. See above the accepted format for the file."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					hidden: true,
					itemId: "relevantFileTypeSelector",
					value: "Relevant gene list"
				},
				{
					xtype: 'combo',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment_pre',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or associations (combination of genes & features)."
				},
				/*TARGETS FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Associations file",
					namePrefix: this.namePrefix + '__annotations',
					itemId: "mirnaTargetsFileSelector",
					helpTip: "Upload the reference file that relates each feature (i.e. miRNA) with its potential targets. This information is usually extracted from popular databases such as miRbase for miRNAs. See above the accepted format for the file."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_annotations_file_type',
					hidden: true,
					itemId: "mirnaTargetsFileTypeSelector",
					value: "Associations file"
				}, /*{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Associations file',
					namePrefix: this.namePrefix + '_associations',
					itemId: "mainAssociationFileSelector",
					helpTip: "Upload the 2 column association file associating genes with features or choose it from your data folder."
				}*/,
				/*{
					xtype: "box",
					itemId: "toogleCorrOptions",
					hidden: !this.allowToogle,
					html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_corrOptions"><label for="' + this.namePrefix + '_corrOptions">Additional options using correlation.</label></div>'
				},*/
				/* CORRELATION OPTIONS */
				{
					xtype: 'box',
					html: '<hr><p>You can provide a relevant associations file or let the program to automatically retrieve them based on correlation with a gene expression dataset.</p>'
				},
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant associations file<br>(optional)',
					namePrefix: this.namePrefix + '_relevant_associations',
					itemId: "secondaryAssociationFileSelector",
					helpTip: "Upload the 2 column list of relevant associations (gene - feature) or choose it from your data folder."
				},
				{
					xtype: "box",
					itemId: "toogleCorrOptions",
					hidden: !this.allowToogle,
					html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 14px; "><input type="checkbox" id="' + this.namePrefix + '_corrOptions"><label for="' + this.namePrefix + '_corrOptions">Automatically select relevant associations using correlation.</label></div>'		
				},
				/* CORRELATION OPTIONS */
				{
					xtype: "container",
					itemId: "itemsContainerCorrOptions",
					layout: {
						align: 'stretch',
						type: 'vbox'
					},
					disabled: true,
					defaults: {
						labelAlign: "right",
						labelWidth: 150,
						maxLength: 100,
						maxWidth: 500
					},
					items: [
						{
							xtype: 'textfield',
							fieldLabel: 'Omic Name',
							name: this.namePrefix + '_rnaseqaux_omic_name',
							hidden: true,
							itemId: "rnaseqauxOmicNameField",
							value: "Gene Expression"
						},
						{
							xtype: "myFilesSelectorButton",
							fieldLabel: "Gene expression dataset"/*<br> (optional)"*/,
							namePrefix: this.namePrefix + '_rnaseqaux',
							extraButtons: [{
								text: 'Use a file from other omic',
								handler: function() {
									var me = this;
									var _callback = function(selectedItem) {
										if (selectedItem !== null) {
											me.up("myFilesSelectorButton").queryById("visiblePathField").setValue(selectedItem[0].get("omic") + ": " + selectedItem[0].get("file"));
											me.up("myFilesSelectorButton").queryById("originField").setValue(selectedItem[0].get("name"));
										}
									};
									Ext.widget("OmicInputSelectorDialog").showDialog(_callback);
								}
							}],
							itemId: "rnaseqauxFileSelector",
							helpTip: "Upload the quantification file for the gene expression. This file is used to calculate the correlation of the expression of the genes and their associated features. Using this correlation we can filter and order the features that will be assigned to each gene. See above the accepted format for the file."
						}, {
							xtype: 'textfield',
							fieldLabel: 'File Type',
							name: this.namePrefix + '_rnaseqaux_file_type',
							hidden: true,
							itemId: "rnaseqauxFileTypeSelector",
							value: "Gene Expression file"
						},
						{
							xtype: 'textfield',
							hidden: true,
							fieldLabel: 'Map to',
							name: this.namePrefix + '_rnaseqaux_match_type',
							itemId: "rnaseqauxFileMapToSelector",
							value: 'gene'
						},
						/*
						* OTHER FIELDS
						*/
						//report
						{
							xtype: 'combo',
							itemId: "reportMethodField",
							name: this.namePrefix + '_report',
							fieldLabel: 'Report',
							editable: false,
							allowBlank: false,
							value: "all",
							displayField: 'label',
							valueField: 'value',
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['label', 'value'],
								data: [
									["All features", "all"],
									["Only relevant features (e.g. DE)", "DE"]
								]
							}),
							helpTip: "Choose between consider all features in the quantification file or just those features that are differentially expressed. Default: 'All features'"
						},
						{
							xtype: 'combo',
							itemId: "scoreMethodField",
							name: this.namePrefix + '_score_method',
							fieldLabel: 'Score method',
							editable: false,
							allowBlank: false,
							value: "kendall",
							displayField: 'label',
							valueField: 'value',
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['label', 'value'],
								data: [
									// ["Fold Change of miRNA expression", "fc"],
									["Correlation with gene expression (Spearman)", "spearman"],
									["Correlation with gene expression (Kendall)", "kendall"],
									["Correlation with gene expression (Pearson)", "pearson"]
								]
							}),
							helpTip:
							"As en example in miRNA, usually a single miRNA has multiple potential target genes, but not all targets are being " +
							"regulated by a certain miRNA at certain moment. Consequently, we need to discriminate the real targets for a miRNA."+
							"If Gene expression (GE) data is available, then we calculate the correlation between each miRNA " +
							"and each target gene and filter out all those miRNAs that has a lower correlation value than a given threadhold." +
							"If no GE is available then we filter based on the fold-change for the expression of the miRNAs." +
							"Default: 'Kendall correlation' if GE is available. 'Fold Change' in other case."
						},
						{
							xtype: 'combo',
							itemId: "selectionMethodField",
							name: this.namePrefix + '_selection_method',
							fieldLabel: 'Selection method',
							editable: false,
							allowBlank: false,
							value: "negative_correlation",
							displayField: 'label',
							valueField: 'value',
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['label', 'value'],
								data: [
									["by max. fold-change of feature expression", "fc"],
									["by absolute correlation with gene expression", "abs_correlation"],
									["by positive correlation with gene expression", "positive_correlation"],
									["by negative correlation with gene expression", "negative_correlation"]
								]
							}),
							//TODO: THIS HELP TOOL IS NOT DISPLAYED, WHY??
							helpTip:
							"Determines how we select the potential features that are regulating a certain gene. " +
							"For instance, usually miRNA act as inhibitors of gene expression so we should expect an opposite behavior " +
							"to the regulated gene. A negative correlation will fit better to this expected profile. " +
							"Default: If gene expression (GE) if avilable, select and order by 'negative correlation'. 'Max fold-change' in other case.",
							listeners:{
								change: function(elem, newValue, oldValue){
									elem = elem.nextSibling("numberfield");
									if(newValue === "negative_correlation"){
										elem.setValue(Math.abs(elem.value) * -1);
									}else{
										elem.setValue(Math.abs(elem.value));
									}
								}
							}
						},
						{
							xtype: 'numberfield',
							itemId: "cutoffField",
							name: this.namePrefix + '_cutoff',
							fieldLabel: 'Filter cutoff',
							value: -0.5,
							minValue: -1,
							maxValue: 1,
							step: 0.1,
							allowDecimals: true,
							allowBlank: false,
							helpTip: "The value for the threadhold. All features with a lower value of correlation or FC will be filterd out from the results. Default: 0.5"
						}
					]
				}
		]
		}],
		setContent: function(target, values) {
			me.setContent(target, values);
		},
		isValid: function() {
			var valid = true;
			var component = this.queryById("itemsContainerAlt");
			if (!component.isVisible()) {
				component = this.queryById("itemsContainer");
			}
			var items = component.query("field");
			for (var i in items) {
				valid = valid && (this.items[i] || items[i].validate());
			}

			if (component.queryById("mainFileSelector").getValue() === "") {
				valid = false;
				component.queryById("mainFileSelector").markInvalid("Please, provide a data file.");
			}
			if (component.queryById("mirnaTargetsFileSelector") && component.queryById("mirnaTargetsFileSelector").getValue() === "") {
				valid = false;
				component.queryById("mirnaTargetsFileSelector").markInvalid("Please, provide a features targets reference file.");
			}

			var corrEnabled = $("#" + me.namePrefix + "_corrOptions").is(':checked');

			if (corrEnabled && component.queryById("rnaseqauxFileSelector") && component.queryById("rnaseqauxFileSelector").getValue() === "") {
				valid = false;
				component.queryById("rnaseqauxFileSelector").markInvalid("Please, provide a transcriptomics file.");
			} else if(! corrEnabled && component.queryById("secondaryAssociationFileSelector") && component.queryById("secondaryAssociationFileSelector").getValue() === "") {
				valid = false;
				component.queryById("secondaryAssociationFileSelector").markInvalid("Please, provide a relevant associations file or enable the automatic mode instead.");
			}
			return valid;
		},
		isEmpty: function() {
			var component = this.queryById("itemsContainerAlt");
			if (!component.isVisible()) {
				component = this.queryById("itemsContainer");
			}
			var empty = true;
			if (component.queryById("mainFileSelector").getValue() !== "") {
				empty = false;
			}
			if (component.queryById("mirnaTargetsFileSelector") && component.queryById("mirnaTargetsFileSelector").getValue() !== "") {
				empty = false;
			}

			return empty;
		},
		listeners: {
			boxready: function() {
				initializeTooltips(".helpTip");

				$("#" + me.namePrefix + "_mapRegions").change(function() {
					//$("#" + me.namePrefix + "_useAssociations").prop('disabled', $(this).is(':checked'));
					// me.getComponent().queryById("toogleUseAssociations").setVisible(! $(this).is(':checked'));
					me.toogleContent();
				});

				// $("#" + me.namePrefix + "_useAssociations").change(function() {
				// 	// $("#" + me.namePrefix + "_mapRegions").prop('disabled', $(this).is(':checked'));
				// 	me.getComponent().queryById("toogleMapRegions").setVisible(! $(this).is(':checked'));
				// 	me.toogleContent("itemsContainerAssociations");
				// });

				$("#" + me.namePrefix + "_corrOptions").change(function() {
					// $("#" + me.namePrefix + "_mapRegions").prop('disabled', $(this).is(':checked'));
					me.getComponent().queryById("secondaryAssociationFileSelector").down('container').setDisabled($(this).is(':checked'));
					me.getComponent().queryById("itemsContainerCorrOptions").setDisabled(! $(this).is(':checked'));
				});

				$(this.getEl().dom).find("a.deleteOmicBox").click(function() {
					me.removeOmicSubmittingPanel();
				});
			}
		}
	});

	return this.component;
};

return this;
}
MiRNAOmicSubmittingPanel.prototype = new DefaultSubmittingPanel;
