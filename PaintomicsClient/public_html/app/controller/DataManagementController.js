/* global SERVER_URL_DM_DOWNLOAD_FILE, response, application, ajaxErrorHandler, SERVER_URL_DM_DELETE_JOB, Ext, SERVER_URL_DM_GET_MYJOBS, SERVER_URL_DM_DELETE_FILE */

//# sourceURL=DataManagementController.js
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
* - DataManagementController
*
* EVENT HANDLERS MAPPING
* -  showMyDataPanelClickHandler
* -  loadMyFilesDataHandler
* -  loadGTFFilesHandler
* -  downloadFilesHandler
* -  viewFilesHandler
* -  deleteFilesHandler
* -  loadMyJobsDataHandler
* -  deleteJobsHandler
* -  recoverJobsHandler
* -  submitForm
* -  fromBed2GenesOnFormSubmitHandler
* -  getCredentialsParams
* -
*/
function DataManagementController() {
	/**
	*
	* @param {type} button
	* @param {type} jobView
	* @returns {undefined}
	*/
	this.showMyDataPanelClickHandler = function () {
		//Check if valid user
		if (Ext.util.Cookies.get('userID') === null) {
			return false;
		}

		//Get the MyData view (if any)
		var myDataView = application.getMainView("DM_MyDataView");
		if (myDataView == null) {
			myDataView = new DM_MyDataView();
			myDataView.setController(this);
		}

		application.updateMainView(myDataView, true);
		return myDataView;
	};

	this.loadMyFilesDataHandler = function (myDataFileListView) {
		var me = this;
		$.ajax({
			type: "POST", headers: {"Content-Encoding": "gzip"},
			url: SERVER_URL_DM_GET_MYFILES,
			data: me.getCredentialsParams(),
			success: function (response) {
				//LOAD DATA
				myDataFileListView.loadData(response.fileList, response.dataSummary);
			},
			error: ajaxErrorHandler
		});
	};

	this.loadGTFFilesHandler = function (GTFFileListView) {
		var me = this;
		$.ajax({
			type: "POST", headers: {"Content-Encoding": "gzip"},
			url: SERVER_URL_DM_GET_GTFFILES,
			data: me.getCredentialsParams(),
			success: function (response) {
				//LOAD DATA
				GTFFileListView.loadData(response.fileList);
			},
			error: ajaxErrorHandler
		});
	};

	this.downloadFilesHandler = function (myDataFileListView, fileName, fileType, jobID) {
		var elem = $("body").append("<a target='_blank' id='temporalLink' style='display:none' href='" + window.location.origin + window.location.pathname + SERVER_URL_DM_DOWNLOAD_FILE + "?fileName=" + fileName + "&fileType=" + fileType + (jobID ? "&jobID=" + jobID : "") + "'></a>");
		$("#temporalLink")[0].click();
		$("#temporalLink").remove();
	};

	this.viewFilesHandler = function (myDataFileListView, fileName, fileType, offset, messageDialog) {
		var me = this;

		offset = (offset | 0);

		$.ajax({
			url: SERVER_URL_DM_DOWNLOAD_FILE,
			data: {fileName: fileName, fileType: fileType, serve: true, offset: offset},
			success: function (response) {
				response = response.split("\n");

				var data = [], columns = [new Ext.grid.RowNumberer({width: 50}), ], fields = [];
				for (var i = 1; i < response.length - 1; i++) {
					data.push(response[i].split("\t"));
				}

				var store = null;
				if (messageDialog !== undefined) {
					store = messageDialog.queryById("fileContentGrid").getStore();
					store.loadData(data, true);
					messageDialog.offset = messageDialog.offset + 50;
				} else {
					response = response[0].split("\t");
					for (var i = 0; i < response.length; i++) {
						columns.push({text: response[i], dataIndex: response[i], flex: (i === 0 ? 2 : 1)})
						fields.push({name: response[i]});
					}

					var store = Ext.create('Ext.data.ArrayStore', {fields: fields, data: data});
					messageDialog = Ext.create('Ext.window.Window', {
						title: fileName,
						height: 600, width: 800,
						layout: 'fit',
						offset: 50,
						items: {
							xtype: 'livesearchgrid', itemId: "fileContentGrid", searchFor: response[0],
							columns: columns,
							store: store,
							bbar: [
								{xtype: "button", itemId: "loadMoreButton", text: 'Load more',
								renderTo: Ext.getBody(),
								handler: function () {
									me.viewFilesHandler(myDataFileListView, fileName, fileType, messageDialog.offset, messageDialog);
								}
							}
						]
					}
				});
				response = null;

				messageDialog.center();
				messageDialog.show();
			}

			messageDialog.queryById("loadMoreButton").setVisible((data.length > 0));

		}
	}).fail(ajaxErrorHandler);
};

this.deleteFilesHandler = function (myDataFileListView, fileName) {
	var me = this;
	Ext.MessageBox.confirm('Delete selected files?', 'Are you sure you want to do delete the selected files?', function (btn) {
		if (btn !== 'yes') {
			return;
		}
		showInfoMessage("Deleting files...", {logMessage: "Deleting files...", showSpin: true, icon: "clock-o"});

		$.ajax({
			type: "POST",
			url: SERVER_URL_DM_DELETE_FILE,
			data: me.getCredentialsParams({"fileName": fileName}),
			success: function (response) {
				//LOAD DATA
				if (myDataFileListView.parent !== null) {
					myDataFileListView.parent.updateContent(true, false);
				} else {
					myDataFileListView.updateContent();
				}
				showSuccessMessage("Done", {logMessage: "Deleting files...DONE", closeTimeout: 0.5});
			},
			error: ajaxErrorHandler
		});
	});
};

this.loadMyJobsDataHandler = function (myDataJobsListView) {
	var me = this;
	$.ajax({
		type: "POST", headers: {"Content-Encoding": "gzip"},
		url: SERVER_URL_DM_GET_MYJOBS,
		data: me.getCredentialsParams(),
		success: function (response) {
			//LOAD DATA
			myDataJobsListView.loadData(response.jobList, response.dataSummary);
		},
		error: ajaxErrorHandler
	});
};

this.deleteJobsHandler = function (myDataJobsListView, jobID, jobType) {
	var me = this;

	Ext.MessageBox.confirm('Delete selected Jobs?', 'Are you sure you want to do delete the selected Jobs?', function (btn) {
		if (btn !== 'yes') {
			return;
		}
		showInfoMessage("Deleting Jobs...", {logMessage: "Deleting Jobs...", showSpin: true, icon: "clock-o"});
		$.ajax({
			type: "POST",
			url: SERVER_URL_DM_DELETE_JOB,
			data: me.getCredentialsParams({"jobID": jobID, jobType: jobType}),
			success: function (response) {
				if (myDataJobsListView.parent !== null) {
					myDataJobsListView.parent.updateContent(false, true);
				} else {
					myDataJobsListView.updateContent();
				}
				showSuccessMessage("Done", {logMessage: "Deleting Jobs...DONE", closeTimeout: 0.5});
			},
			error: ajaxErrorHandler
		});
	});
};

/**
*
* @param {type} myDataJobsListView
* @param {type} jobID
* @param {type} jobType
* @param {type} jobDate
* @returns {undefined}
*/
this.recoverJobsHandler = function (myDataJobsListView, jobID, jobType, jobDate) {
	if (jobType === "PathwayAcquisitionJob") {
		application.getController("JobController").recoverPAJobHandler(jobID);
	} else {
		var prefix = ((jobType === "MiRNA2GeneJob")?"mirna2genes_":"bed2genes_");
		jobDate = jobDate;
		jobType = jobType.replace("Job", " Job");

		showInfoMessage(jobType + " successfully recovered", {
			message: "Click on the link below to download your files.</br>" +
			"<b>Note</b> that the main output (quantification at gene level) is also available at your data section.</br>" +
			"<a href='" + window.location.pathname + SERVER_URL_DM_DOWNLOAD_FILE + "?jobID=" + jobID + "&fileName=" + prefix + jobDate + ".zip" + "&fileType=job_result'>Download files.</a>",
			showButton: true
		});
	}
};

this.submitForm = function (URL, form) {
	if (form.isValid()) {
		showInfoMessage("Uploading and processing files...", {logMessage: "New Job created, submitting files...", showSpin: true});
		form.submit({
			method: 'POST', url: URL,
			success: function (form, action) {
				var response = JSON.parse(action.response.responseText);
				showSuccessMessage("Your Job was sent to queue successfully (job ID " + response.jobID + ")", {
					message: "In few minutes your data will be ready.<br>" +
					"Check your job status, at <b>My Jobs</b> table at <b>MyData</b> section",
					showButton: true
				});
			},
			failure: extJSErrorHandler
		});
	}
};

/*
 * The "Request an organism" dialog.
 *
 * It opened on a terracotta <h2> repeating the window's own title, then five
 * lines of prose before the first control: what KEGG installs, what KEGG
 * translates, what the Comments box is for, and a worked example in italics
 * about Entrez Gene IDs. All of it was setup for two fields, and the "here"
 * link that offered the list of installable species was written
 * `href=''` -- which is the current page, so the one link in the paragraph
 * reloaded the form the reader had just filled in.
 *
 * Two fields, one line above them, and the guidance that was worth keeping is
 * now where it is needed: inside the Comments box, as its placeholder.
 */
this.requestNewSpecieHandler = function(){
	var messageDialog = Ext.create('Ext.window.Window', {
		title: "Request an organism",
		/* No height: the window shrink-wraps its two fields. It was 400px for
		   content that measures about 300, so it opened with a band of empty
		   body under the Comments box. */
		width: 560, modal: true,
		bodyPadding: 22,
		cls: "po-dialog",
		layout: {type: "vbox", align: "stretch"},
		defaults: {
			/* On top, as on the form this dialog is opened from. Right-aligned
			   labels put "Organism:" and "Comments:" in a 100px gutter and the
			   fields in what was left. */
			labelAlign: "top",
			border: false
		},
		items: [
			{
				xtype: "box", cls: "po-dialog-intro",
				html: '<p>Any organism in KEGG can be installed &mdash; ' +
					'<a href="https://www.genome.jp/kegg/catalog/org_list.html"' +
					' target="_blank" rel="noopener">see the full list</a>.</p>'
			},
			{
				xtype: 'organismcombo', fieldLabel: 'Organism', name: 'specie',
				itemId: "speciesCombobox",
				allowBlank: false, forceSelection: false,
				emptyText: 'Please choose an organism',
				displayField: 'name',
				valueField: 'name',
				editable: true,
				store: Ext.create('Ext.data.ArrayStore', {
					fields: ['name', 'value'],
					autoLoad: true,
					proxy: {
						type: 'ajax',
						//TODO: MOVE THIS FILE TO KEGG_DATA FOLDER AND UPDATE
						url: "resources/data/all_species.json",
						reader: {
							type: 'json',
							root: 'species',
							successProperty: 'success'
						}
					}
				})
			},
			{
				xtype: 'textareafield', name: 'comments', itemId: 'commentsTextArea',
				fieldLabel: 'Anything we should know? (optional)', height: 96,
				/* The paragraph that used to be above the form, asked as a
				   question in the place where it is answered. Curly quotes and no
				   double quotes: ExtJS writes emptyText into a placeholder="..."
				   attribute, and a straight double quote closes it early (the
				   experiment-design field on Step 1 lost its example that way). */
				emptyText: 'Which identifiers are in your files? KEGG maps Entrez Gene IDs by default; ' +
					'say so if you need Ensembl, UniProt or others.'
			}
		],
		buttons: [
			{
				text: 'Send request',
				cls: 'po-dialog-primary',
				handler : function() {
					var type = "specie_request";
					var message= "<p><b>Specie:</b> " + messageDialog.queryById('speciesCombobox').getValue()+ "</p><p><b>Comments:</b>" +  messageDialog.queryById('commentsTextArea').getValue() + "</p>";
					messageDialog.close();
					sendReportMessage(type, message);
				}
			},
			{text: 'Cancel', handler : function() {messageDialog.close();}}
		]
	});

	messageDialog.center();
	messageDialog.show();
};

this.sendReportHandler = function(){
	var messageDialog = Ext.create('Ext.window.Window', {
		title: "Contact form",
		height: 400, width: 600,modal: true, bodyPadding:10,
		defaults: {
			labelAlign: "right",
			border: false
		},
		items: [
			{
				xtype:"box", html:
				"<h2>Contact form</h2>"+
				"<div style='margin-bottom:10px;'>We would love to hear from you! Please use this form if you have any question or suggestion about the application and we'll get back with you soon.<br><b>Note: </b>If you are using a guest account, please provide a valid email address that we can use to contact you if needed.</div>"
			},
			{xtype: 'textfield', itemId : 'nameTextField', fieldLabel: 'Your name', value: Ext.util.Cookies.get("userName")},
			{xtype: 'textfield', itemId : 'emailTextField', fieldLabel: 'Your email',  value: (Ext.util.Cookies.get("lastEmail") == null || Ext.util.Cookies.get("lastEmail").indexOf("guest") !== -1?"":Ext.util.Cookies.get("lastEmail"))},
			{xtype: 'textareafield', itemId : 'commentsTextArea', fieldLabel: 'Message', width: 500, height:100}
		],
		buttons: [
			{
				text: 'Send request',
				handler : function() {
					var type = "other";
					var userName = messageDialog.queryById('nameTextField').getValue();
					var userEmail = messageDialog.queryById('emailTextField').getValue();
					var message= "<p><b>From:</b> " + userName + "<" + userEmail +">" + "</p><p><b>Message:</b>" +  messageDialog.queryById('commentsTextArea').getValue() + "</p>";
					messageDialog.close();
					sendReportMessage(type, message, userEmail, userName);
				}
			},
			{text: 'Close', handler : function() {messageDialog.close();}}
		]
	});

	messageDialog.center();
	messageDialog.show();
};

this.getCredentialsParams = function (request_params) {
	var credentials = {};
	if (request_params != null) {
		credentials = request_params;
	}

	credentials.sessionToken = Ext.util.Cookies.get('sessionToken');
	credentials.userID = Ext.util.Cookies.get('userID');
	return credentials;
};
}
