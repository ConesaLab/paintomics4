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
* THIS FILE CONTAINS THE FOLLOWING MODULE DECLARATION
* - reports.reports.report-list
*
*/
(function(){
	var app = angular.module('reports.reports.report-list', []);

	app.factory("ReportList", ['$rootScope', function($rootScope) {
		var reports = [];
		var undelivered = 0;
		var old = new Date(0);

		var TYPE_LABELS = {
			specie_request: "Organism request",
			error: "Error report",
			other: "Other"
		};

		return {
			getReports: function() {
				return reports;
			},
			setReports: function(reportList) {
				reports = this.adaptReportsInformation(reportList || []);
				old = new Date();
				return this;
			},
			getUndelivered: function() {
				return undelivered;
			},
			setUndelivered: function(_undelivered) {
				undelivered = _undelivered || 0;
				return this;
			},
			deleteReport: function(report_id) {
				for(var i in reports){
					if(reports[i].report_id === report_id){
						reports.splice(i,1);
						return reports;
					}
				}
				return null;
			},
			adaptReportsInformation: function(reportList) {
				for(var i in reportList){
					this.adaptReportInformation(reportList[i]);
				}
				return reportList;
			},
			adaptReportInformation: function(report){
				report.type_label = TYPE_LABELS[report.report_type] || report.report_type;
				// The message is assembled as HTML by the request form. The panel
				// shows it as text, so strip the tags rather than trusting them:
				// this string is user input and must never be rendered as markup.
				report.message_text = String(report.message || "")
					.replace(/<br\s*\/?>/gi, "\n")
					.replace(/<\/p>/gi, "\n")
					.replace(/<[^>]*>/g, " ")
					.replace(/&nbsp;/gi, " ")
					.replace(/&amp;/gi, "&")
					.replace(/&lt;/gi, "<")
					.replace(/&gt;/gi, ">")
					.replace(/[ \t]+/g, " ")
					.replace(/\n\s*\n+/g, "\n")
					.trim();
				return report;
			},
			getOld: function(){
				return (new Date() - old)/120000;
			}
		};
	}]);
})();
