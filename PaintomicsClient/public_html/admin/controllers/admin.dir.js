/*
* (C) Copyright 2016 SLU Global Bioinformatics Centre, SLU
* (http://sgbc.slu.se) and the B3Africa Project (http://www.b3africa.org/).
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
*     Rafael Hernandez de Diego <rafahdediego@gmail.com>
*     Erik Bongcam-Rudloff
*     and others.
*
* THIS FILE CONTAINS THE FOLLOWING MODULE DECLARATION
*
*/
(function(){
	var app = angular.module('admin.directives.admin-directives', []);

	app.directive("userRow", function() {
		return {
			templateUrl: 'templates/user-row.tpl.html'
		};
	});

	app.directive("fileRow", function() {
		return {
			templateUrl: 'templates/file-row.tpl.html'
		};
	});

	app.directive("messageRow", function() {
		return {
			templateUrl: 'templates/message-row.tpl.html'
		};
	});

	app.directive("databaseRow", function() {
		return {
			templateUrl: 'templates/database-row.tpl.html'
		};
	});

	app.directive('fileModel', ['$parse', function ($parse) {
		return {
			restrict: 'A',
			link: function($scope, element, attrs) {
				element.bind('change', function(){
					$scope.$apply(function(){
						$scope.file = element[0].files[0];
					});
				});
			}
		};
	}]);
})();
