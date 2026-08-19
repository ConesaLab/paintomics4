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
* - ReportListController
*
*/
(function(){
	var app = angular.module('admin.controllers.report-controllers', [
		'ui.bootstrap',
		'ang-dialogs',
		'reports.reports.report-list'
	]);

	app.controller('ReportListController', function($rootScope, $scope, $http, $dialogs, $state, APP_EVENTS, ReportList) {
		//--------------------------------------------------------------------
		// CONTROLLER FUNCTIONS
		//--------------------------------------------------------------------
		this.retrieveReportsListData = function(force){
			$scope.isLoading = true;

			if(ReportList.getOld() > 1 || force){ //Max age for data 2min.
				$http($rootScope.getHttpRequestConfig("GET", "reports", {})).
				then(
					function successCallback(response){
						$scope.isLoading = false;
						$scope.reports = ReportList.setReports(response.data.reportList).getReports();
						$scope.undelivered = ReportList.setUndelivered(response.data.undelivered).getUndelivered();
					},
					function errorCallback(response){
						$scope.isLoading = false;
						var message = "Failed while retrieving the reports list.";
						$dialogs.showErrorDialog(message, {
							logMessage : message + " at ReportListController:retrieveReportsListData."
						});
						console.error(response.data);
					}
				);
			}else{
				$scope.reports = ReportList.getReports();
				$scope.isLoading = false;
			}
		};

		$scope.formatDate = function(submitted_at){
			// Stored as an ISO-8601 UTC stamp (2026-08-19T14:36:40Z).
			if(!submitted_at){ return ""; }
			return String(submitted_at).replace("T", " ").replace("Z", " UTC");
		};

		//--------------------------------------------------------------------
		// EVENT HANDLERS
		//--------------------------------------------------------------------
		this.deleteReportHandler = function (report){
			var sendRemoveRequest = function(option){
				if(option === "ok"){
					$http($rootScope.getHttpRequestConfig("DELETE", "reports", {
						extra: report.report_id
					})).then(
						function successCallback(response){
							if(response.data.success){
								me.retrieveReportsListData(true);
							}
						},
						function errorCallback(response){
							$scope.isLoading = false;
							var message = "Failed while dismissing the report.";
							$dialogs.showErrorDialog(message, {
								logMessage : message + " at ReportListController:deleteReportHandler."
							});
							console.error(response.data);
						}
					);
				}
			};
			$dialogs.showConfirmationDialog("This cannot be undone.", {title: "Dismiss this report?", callback : sendRemoveRequest});
		};

		this.refreshHandler = function(){
			me.retrieveReportsListData(true);
		};

		//--------------------------------------------------------------------
		// INITIALIZATION
		//--------------------------------------------------------------------
		var me = this;
		$scope.reports = ReportList.getReports();
		$scope.undelivered = ReportList.getUndelivered();

		this.retrieveReportsListData(true);
	});
})();
