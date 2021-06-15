(function(){
	var app = angular.module('admin.controllers.systeminfo-controllers', [
		'ui.bootstrap',
		'ang-dialogs',
		'chart.js'
	]);

	app.controller('SystemInfoController', function($rootScope, $scope, $http, $dialogs, $state, $interval, APP_EVENTS) {

		this.retrieveSystemInfo = function(){
			$http($rootScope.getHttpRequestConfig("GET", "system-info", {})).
			then(
				function successCallback(response){
					$scope.cpu_load = [response.data.cpu_use, 100 - response.data.cpu_use];
					$scope.mem_load = [response.data.mem_use, 100 - response.data.mem_use];
					$scope.swap_use = [response.data.swap_use, 100 - response.data.swap_use];
					$scope.disk_use = response.data.disk_use;
				},
				function errorCallback(response){
					$dialogs.closeDialog();
					debugger;
					var message = "Failed while retrieving the system information.";
					$dialogs.showErrorDialog(message, {
						logMessage : message + " at SystemInfoController:retrieveSystemInfo."
					});
					console.error(response.data);
				}
			);
		};

		this.sendCleanDatabasesRequest = function(){
			$dialogs.showWaitDialog("This process may take few seconds, be patient!");
			$http($rootScope.getHttpRequestConfig("DELETE", "clean-databases", {})).
			then(
				function successCallback(response){
					$dialogs.closeDialog();
					$dialogs.showSuccessDialog("Databases have been succesfully cleaned.");
				},
				function errorCallback(response){
					$dialogs.closeDialog();

					debugger;
					var message = "Failed while cleaning databases.";
					$dialogs.showErrorDialog(message, {
						logMessage : message + " at SystemInfoController:sendCleanDatabasesRequest."
					});
					console.error(response.data);
				}
			);
		};
		//--------------------------------------------------------------------
		// INITIALIZATION
		//--------------------------------------------------------------------
		var me = this;

		this.retrieveSystemInfo();
		$rootScope.interval.push($interval(this.retrieveSystemInfo, 3000));

		$scope.cpu_load = [0, 100];
		$scope.cpu_options = {
			animation: {duration: 500},
			tooltip:{enabled:false},
			title: {display: true,text: 'CPU usage (%)'},
			maintainAspectRatio:false
		};
		$scope.mem_load = [0, 100];
		$scope.mem_options = {
			animation: {duration: 500},
			title: {display: true,text: 'Mem usage (%)'},
			tooltip:{enabled:false},
			maintainAspectRatio:false
		};
		$scope.swap_load = [0, 100];
		$scope.swap_options = {
			animation: {duration: 500},
			tooltip:{enabled:false},
			title: {display: true,text: 'Swap usage (%)'},
			maintainAspectRatio:false
		};

	});
})();
