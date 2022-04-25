#***************************************************************
#  This file is part of Paintomics v3
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomics4@outlook.com
#**************************************************************
import logging.config

from flask import Flask, request, send_from_directory, jsonify
from flask.json import JSONEncoder
from re import sub

from src.common.PySiQ import Queue

from src.conf.serverconf import *

from src.servlets.PathwayAcquisitionServlet import *
from src.servlets.DataManagementServlet import *
from src.servlets.UserManagementServlet import *
from src.servlets.Bed2GenesServlet import *
from src.servlets.MiRNA2GenesServlet import *
from src.servlets.AdminServlet import *
from src.common.KeggInformationManager import KeggInformationManager
from src.common.JobInformationManager import JobInformationManager

import os.path

class Application(object):
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self):
        ##*******************************************************************************************
        ##****SERVLET DEFINITION*********************************************************************
        ##*******************************************************************************************
        self.readConfigurationFile()
        self.app = Flask(__name__)

        self.app.config['MAX_CONTENT_LENGTH'] =  SERVER_MAX_CONTENT_LENGTH
        self.app.json_encoder = MyJSONEncoder

        KeggInformationManager(KEGG_DATA_DIR) #INITIALIZE THE SINGLETON
        JobInformationManager()#INITIALIZE THE SINGLETON

        self.startScheludeTasks() #CLEAN DATA EVERY N HOURS

        self.queue = Queue()
        self.queue.start_worker(N_WORKERS)

        #******************************************************************************************
        #     ______ _____ _      ______  _____
        #   |  ____|_   _| |    |  ____|/ ____|
        #   | |__    | | | |    | |__  | (___
        #   |  __|   | | | |    |  __|  \___ \
        #   | |     _| |_| |____| |____ ____) |
        #   |_|    |_____|______|______|_____/
        #
        #  COMMON STEPS HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/')
        def main():
            return send_from_directory(self.ROOT_DIRECTORY + 'public_html','index.html')
        ##*******************************************************************************************
        ##* GET THUMBNAILS, PATHWAY IMAGE, etc
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/kegg_data/<path:filename>')
        def get_kegg_data(filename):
            logging.info("filename is:" + str(filename))
            if str(filename) == "species.json":
                return send_from_directory(KEGG_DATA_DIR + 'current/', 'species.json')
            else:
                # Possible accepted format <path>_<source>_thumb
                split_name = filename.replace('_thumb', '').split('_')

                logging.info("split_name is:" + str(split_name))

                # Sanitize input
                source_type = sub(r'\W+', '', split_name[-1]) if len(split_name) > 1 else None
                source_dir = 'current/' + source_type.lower() if source_type is not None else 'current/common'
                logging.info("split_name is:" + str(source_dir))

                # Add "map" prefix for KEGG pathways
                filename_prefix = 'map' if source_type is None else str()

                def convert_list_to_string(org_list, seperator='_'):
                    """ Convert list to string, by joining all item in list with given separator.
                        Returns the concatenated string """
                    return seperator.join( org_list )


                if source_type is None:
                    filename_cleaned = sub("[^0-9]", "", split_name[0]) if source_type is None else split_name[0]
                elif source_type.lower() == "mapman":
                    filename_cleaned = convert_list_to_string(split_name[:-1])
                    logging.info("filenamecleaned is:" + filename_cleaned)
                else:
                    filename_cleaned = sub("[^0-9]", "", split_name[0]) if source_type is None else split_name[0]


                #logging.info( "Name is: " + str( KEGG_DATA_DIR ) + str( source_dir ) + '/png/thumbnails/',
                #                  str( filename_prefix ) + str( filename_cleaned ) + '_thumb.png' )

                if str(filename).endswith("_thumb"):
                    return send_from_directory(KEGG_DATA_DIR + source_dir + '/png/thumbnails/', filename_prefix + filename_cleaned + '_thumb.png')
                else:
                    return send_from_directory(KEGG_DATA_DIR + source_dir + '/png/', filename_prefix + filename_cleaned + '.png')
        ##*******************************************************************************************
        ##* GET PATHWAY IMAGE
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/kegg_data/pathway_network/<path:specie>')
        def get_pathway_network(specie):
            return send_from_directory(KEGG_DATA_DIR + 'current/' + specie, 'pathways_network.json')

        @self.app.route(SERVER_SUBDOMAIN + '/kegg_data/pathway_network_reactome/<path:specie>')
        def get_pathway_network_reactome(specie):
            return send_from_directory(KEGG_DATA_DIR + 'current/' + specie, 'pathways_network_Reactome.json')

        @self.app.route( SERVER_SUBDOMAIN + '/kegg_data/pathway_network_mapman/<path:specie>' )
        def get_pathway_network_mapman(specie):
            return send_from_directory( KEGG_DATA_DIR + 'current/' + specie, 'pathways_network_MapMan.json' )


        ##*******************************************************************************************
        ##* GET DATA FROM CLIENT TMP DIR
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/CLIENT_TMP/<path:filename>')
        def get_client_file(filename):
            #TODO: CHECK CREDENTIALS?
            UserSessionManager().isValidUser(request.cookies.get('userID'), request.cookies.get('sessionToken'))
            return send_from_directory(self.ROOT_DIRECTORY + 'CLIENT_TMP', filename)

        @self.app.route(SERVER_SUBDOMAIN + '/get_cluster_image/<path:filename>')
        def get_cluster_image(filename):
            jobID = filename.split('/')[0]
            logging.info("filename:" + str(filename))

            jobInstance = JobInformationManager().loadJobInstance(jobID)

            # Check if the file really exist, if not, then we are probably accessing a public job from a logged
            # account.
            userDir = "nologin" if jobInstance.getUserID() is None else jobInstance.getUserID()
            image_path = CLIENT_TMP_DIR + userDir + "/jobsData/"

            return send_from_directory(image_path, filename)
        ##*******************************************************************************************
        ##* GET FILE
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/<path:filename>')
        def get_static(filename):
            return send_from_directory(self.ROOT_DIRECTORY + 'public_html', filename)


        #******************************************************************************************
        #    _    _  _____ ______ _____   _____
        #   | |  | |/ ____|  ____|  __ \ / ____|
        #   | |  | | (___ | |__  | |__) | (___
        #   | |  | |\___ \|  __| |  _  / \___ \
        #   | |__| |____) | |____| | \ \ ____) |
        #    \____/|_____/|______|_|  \_\_____/
        #
        #  USER MANAGEMENT SERVLETS HANDLERS
        #*******************************************************************************************
        ##* LOGIN
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/um_signin', methods=['OPTIONS', 'POST'])
        def signInHandler():
            return userManagementSignIn(request, Response()).getResponse()
        #*******************************************************************************************
        ##* SIGN OUT
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/um_signout', methods=['OPTIONS', 'POST'])
        def signOutHandler():
            return userManagementSignOut(request, Response()).getResponse()
        #*******************************************************************************************
        ##* SIGN UP
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/um_signup', methods=['OPTIONS', 'POST'])
        def signUpHandler():
            return userManagementSignUp(request, Response(), self.ROOT_DIRECTORY).getResponse()
        #*******************************************************************************************
        ##* LOGOUT
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/um_guestsession', methods=['OPTIONS', 'POST'])
        def newGuestSessionHandler():
            return userManagementNewGuestSession(request, Response()).getResponse()
        #*******************************************************************************************
        ##* NO USER SESSION
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/um_nologinsession', methods=['OPTIONS', 'POST'])
        def newNoLoginSessionHandler():
            return userManagementNewNoLoginSession(request, Response()).getResponse()
        #*******************************************************************************************
        ##* CHANGE PASS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/um_changepassword', methods=['OPTIONS', 'POST'])
        def changePasswordHandler():
            return userManagementChangePassword(request, Response()).getResponse()
        #*******************************************************************************************
        ##* RESET PASSWORD
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/um_resetpassword', methods=['OPTIONS', 'GET'])
        def resetPasswordHandler():
            return userManagementResetPassword(request, Response(), self.ROOT_DIRECTORY).getResponse()
        #*******************************************************************************************
        ##* USER MANAGEMENT SERVLETS HANDLERS - END
        #******************************************************************************************



        #******************************************************************************************
        #     ______ _____ _      ______  _____
        #   |  ____|_   _| |    |  ____|/ ____|
        #   | |__    | | | |    | |__  | (___
        #   |  __|   | | | |    |  __|  \___ \
        #   | |     _| |_| |____| |____ ____) |
        #   |_|    |_____|______|______|_____/
        #
        #   FILE UPLOAD HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_upload_file', methods=['OPTIONS', 'POST'])
        def uploadFileHandler():
            return dataManagementUploadFile(request, Response(), CLIENT_TMP_DIR).getResponse()
        #*******************************************************************************************
        ##* FILE LIST HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_get_myfiles', methods=['OPTIONS', 'POST'])
        def getMyFilesHandler():
            return dataManagementGetMyFiles(request, Response(), CLIENT_TMP_DIR, MAX_CLIENT_SPACE).getResponse()
        #*******************************************************************************************
        ##* FILE DELETION HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_delete_file', methods=['OPTIONS', 'POST'])
        def deleteFileHandler():
            return dataManagementDeleteFile(request, Response(), CLIENT_TMP_DIR, MAX_CLIENT_SPACE).getResponse()
        #*******************************************************************************************
        ##* JOB LIST HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_get_myjobs', methods=['OPTIONS', 'POST'])
        def getMyJobsHandler():
            return dataManagementGetMyJobs(request, Response()).getResponse()
        #*******************************************************************************************
        ##* JOB DELETION HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_delete_job', methods=['OPTIONS', 'POST'])
        def deleteJobHandler():
            return dataManagementDeleteJob(request, Response()).getResponse()
        #*******************************************************************************************
        ##* JOB RESULTS HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_downloadFile', methods=['OPTIONS', 'GET'])
        def downloadFileHandler():
            response =  dataManagementDownloadFile(request, Response())
            if hasattr(response,"getResponse") :
                response = response.getResponse()
            return response
        #*******************************************************************************************
        ##* GFT FILES HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_get_gtffiles', methods=['OPTIONS', 'POST'])
        def getGTFFilesHandler():
            return dataManagementGetMyFiles(request, Response(), self.EXAMPLE_FILES_DIR, MAX_CLIENT_SPACE, isReference=True).getResponse()
        #*******************************************************************************************
        ##* DATA MANIPULATION SERVLETS HANDLERS - END
        #*******************************************************************************************




        #*******************************************************************************************
        #         _  ____  ____   _____
        #        | |/ __ \|  _ \ / ____|
        #        | | |  | | |_) | (___
        #    _   | | |  | |  _ < \___ \
        #   | |__| | |__| | |_) |____) |
        #    \____/ \____/|____/|_____/
        #
        #############################################################################################
        #  COMMON JOB HANDLERS
        #
        #  CHECK JOB STATUS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/check_job_status/<path:jobID>', methods=['OPTIONS', 'POST'])
        def checkJobStatus(jobID):
            jobInstance = self.queue.fetch_job(jobID)
            # calculate job running time based on the length of the inputGenesData and databases used
            # this is a rough estimation, but it is better than nothing
            if hasattr(jobInstance.args[0], 'geneBasedInputOmics'):
                omicType = len(jobInstance.args[0].geneBasedInputOmics)
                inputGenesDataLen = len(jobInstance.args[0].inputGenesData)
                databasesLen = len(jobInstance.args[0].databases)
                jobRunningTime = inputGenesDataLen * databasesLen * omicType / 20000 * 15
                startTime = jobInstance.args[0].startTime
                import time
                timeSpent = round((time.time() - startTime), 2)
                jobRunningTime = round(jobRunningTime, 2)
                if (jobRunningTime - timeSpent) < 0:
                    jobRunningTime = 0
                else:
                    jobRunningTime = round((jobRunningTime - timeSpent), 2)

            #elif hasattr(jobInstance, 'result'):
            #    inputGenesDataLen = jobInstance.result.content["summary"][2]
            #    databasesLen = len(jobInstance.result.content["databases"])
            #    jobRunningTime = inputGenesDataLen * databasesLen / 20000 * 25
            #    timeSpent = 0

            # keep jobRunningTime to 2 digits after the decimal point


            if jobInstance is None:
                return Response().setStatus(400).setContent({"success": False, "status" : "failed", "message": "Your job is not on the queue anymore. Check your job list, if it's not there the process stopped and you must resend the data again."}).getResponse()
            elif jobInstance.is_finished():
                return self.queue.get_result(jobID).getResponse()
            elif jobInstance.is_failed():
                self.queue.get_result(jobID) #remove job
                return Response().setStatus(400).setContent({"success": False, "status" : str(jobInstance.get_status()), "message": jobInstance.error_message}).getResponse()
            else:
                if hasattr(jobInstance.args[0], 'geneBasedInputOmics'):
                    return Response().setContent({"success": False, "status" : str(jobInstance.get_status()), "estimatedFinishTime": jobRunningTime, "timeSpent": timeSpent}).getResponse()
                else:
                    return Response().setContent({"success": False, "status" : str(jobInstance.get_status()), "estimatedFinishTime": 0, "timeSpent": 0}).getResponse()
        #*******************************************************************************************
        ##* COMMON JOB HANDLERS - END
        #############################################################################################
        #############################################################################################
        #
        # PATHWAY ACQUISITION SERVLETS HANDLERS
        #
        # STEP 1 HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_step1/<path:exampleMode>', methods=['OPTIONS', 'POST'])
        @self.app.route(SERVER_SUBDOMAIN + '/pa_step1', methods=['OPTIONS', 'POST'])
        def pathwayAcquisitionStep1Handler(exampleMode=False):
            return pathwayAcquisitionStep1_PART1(request, Response(), self.queue, self.generateRandomID(), self.EXAMPLE_FILES_DIR, exampleMode).getResponse()
        #*******************************************************************************************
        # STEP 2 HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_step2', methods=['OPTIONS', 'POST'])
        def pathwayAcquisitionStep2Handler():
            return pathwayAcquisitionStep2_PART1(request, Response(), self.queue, self.ROOT_DIRECTORY).getResponse()
        #*******************************************************************************************
        # STEP 3 HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_step3', methods=['OPTIONS', 'POST'])
        def pathwayAcquisitionStep3Handler():
            return pathwayAcquisitionStep3(request, Response()).getResponse()
        #*******************************************************************************************
        # RECOVER JOB HANDLER
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_recover_job', methods=['OPTIONS', 'POST'])
        def recoverJobHandler():
            return pathwayAcquisitionRecoverJob(request, Response(), self.queue).getResponse()

        # *******************************************************************************************
        # TOUCH JOB HANDLER
        # *******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_touch_job', methods=['OPTIONS', 'POST'])
        def touchJobHandler():
            return pathwayAcquisitionTouchJob(request, Response()).getResponse()
        #*******************************************************************************************
        # SAVE IMAGE HANDLER
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_save_image', methods=['OPTIONS', 'POST'])
        def saveImageHandler():
            return pathwayAcquisitionSaveImage(request, Response()).getResponse()
        #*******************************************************************************************
        # SAVE VISUAL OPTIONS HANDLER
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_save_visual_options', methods=['OPTIONS', 'POST'])
        def saveVisualOptionsHandler():
            return pathwayAcquisitionSaveVisualOptions(request, Response()).getResponse()
        #*******************************************************************************************
        # SAVE SHARING OPTIONS HANDLER
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_save_sharing_options', methods=['OPTIONS', 'POST'])
        def saveSharingOptionsHandler():
            return pathwayAcquisitionSaveSharingOptions(request, Response()).getResponse()
        # *******************************************************************************************
        # RETRIEVE NEW P-VALUES HANDLER
        # *******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_adjust_pvalues', methods=['OPTIONS', 'POST'])
        def adjustPvaluesHandler():
            return pathwayAcquisitionAdjustPvalues(request, Response()).getResponse()

        # *******************************************************************************************
        # REGENERATE METAGENES HANDLER
        # *******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/pa_get_clusters', methods=['OPTIONS', 'POST'])
        def metagenesHandler():
            return pathwayAcquisitionMetagenes_PART1(request, Response(), self.queue, self.generateRandomID(), self.ROOT_DIRECTORY).getResponse()
        #*******************************************************************************************
        # PATHWAY SERVLETS HANDLERS - END
        #############################################################################################
        #############################################################################################
        #
        # ALTERNATIVE PIPELINES SERVLETS HANDLERS
        #
        # fromBEDtoGenes HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_fromBEDtoGenes/<path:exampleMode>', methods=['OPTIONS', 'POST'])
        @self.app.route(SERVER_SUBDOMAIN + '/dm_fromBEDtoGenes', methods=['OPTIONS', 'POST'])
        def fromBEDtoGenesHandler(exampleMode=False):
            result = fromBEDtoGenes_STEP1(request, Response(), self.queue, self.generateRandomID(), self.EXAMPLE_FILES_DIR, exampleMode).getResponse()
            return result
        #*******************************************************************************************
        # fromMiRNAtoGenes HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_fromMiRNAtoGenes/<path:exampleMode>', methods=['OPTIONS', 'POST'])
        @self.app.route(SERVER_SUBDOMAIN + '/dm_fromMiRNAtoGenes', methods=['OPTIONS', 'POST'])
        def fromMiRNAtoGenesHandler(exampleMode=False):
            result = fromMiRNAtoGenes_STEP1(request, Response(), self.queue, self.generateRandomID(), self.EXAMPLE_FILES_DIR, exampleMode).getResponse()
            return result
        #*******************************************************************************************
        ##* ALTERNATIVE PIPELINES SERVLETS HANDLERS - END
        #############################################################################################


        #*******************************************************************************************
        #             _____  __  __ _____ _   _
        #       /\   |  __ \|  \/  |_   _| \ | |
        #      /  \  | |  | | \  / | | | |  \| |
        #     / /\ \ | |  | | |\/| | | | | . ` |
        #    / ____ \| |__| | |  | |_| |_| |\  |
        #   /_/    \_\_____/|_|  |_|_____|_| \_|
        #
        ##* ADMIN SERVLETS HANDLERS
        ##*
        ##* GET ADMIN SITE FILES HANDLERS
        ##*******************************************************************************************
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/admin/')
        def get_admin_static():
            try :
                userID = request.cookies.get('userID')
                sessionToken = request.cookies.get('sessionToken')
                userName = request.cookies.get('userName')
                UserSessionManager().isValidAdminUser(userID, userName, sessionToken)
                return send_from_directory(self.ROOT_DIRECTORY + 'public_html/admin', "index.html")
            except Exception as ex:
                return send_from_directory(self.ROOT_DIRECTORY + 'public_html/admin', "404.html")
        ##*******************************************************************************************
        ##* GET LIST OF INSTALLED SPECIES
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/databases/', methods=['OPTIONS', 'GET'])
        def getInstalledDatabasesInfo():
            return adminServletGetInstalledOrganisms(request, Response()).getResponse()
        ##*******************************************************************************************
        ##* GET AVAILABLE SPECIES
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/databases/available', methods=['OPTIONS', 'GET'])
        def getAvailableDatabasesInfo():
            return adminServletGetAvailableOrganisms(request, Response()).getResponse()
        ##*******************************************************************************************
        ##* INSTALL OR UPDATE SELECTED SPECIE
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/databases/<path:organism_code>', methods=['OPTIONS', 'POST'])
        def installOrganismDatabaseData(organism_code):
            return adminServletInstallOrganism(request, Response(), organism_code, self.ROOT_DIRECTORY).getResponse()
        ##* DELETE SELECTED SPECIE
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/databases/<path:organism_code>', methods=['OPTIONS', 'DELETE'])
        def deleteOrganismDatabaseData(organism_code):
            response = Response()
            response.setContent({"success": False})
            return response.getResponse()
            #return adminServletDeleteOrganism(request, Response(), organism_code, self.ROOT_DIRECTORY).getResponse()

        ##*******************************************************************************************
        ##* MONITOR THE USAGE OF RAM AND CPU
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/system-info/', methods=['OPTIONS', 'GET'])
        def systemInformation():
            return adminServletSystemInformation(request, Response()).getResponse()

        ##*******************************************************************************************
        ##* GET ALL USERS AND DISK USAGE
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/users/', methods=['OPTIONS', 'GET'])
        def getAllUsers():
            return adminServletGetAllUsers(request, Response()).getResponse()
        ##*******************************************************************************************
        ##* REMOVE USERS
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/users/<path:userID>', methods=['OPTIONS', 'DELETE'])
        def deleteUser(userID):
            return adminServletDeleteUser(request, Response(), userID).getResponse()
        ##*******************************************************************************************
        ##* REMOVE OLD USERS AND CLEAN OLD DATA
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/clean-databases/', methods=['OPTIONS', 'DELETE'])
        def cleanDatabases():
            return adminCleanDatabases(request, Response()).getResponse()

        ##*******************************************************************************************
        ##* ADD FILES HANDLERS
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/files/', methods=['OPTIONS', 'POST'])
        def addReferenceFileHandler():
            return dataManagementUploadFile(request, Response(), self.EXAMPLE_FILES_DIR, isReference=True).getResponse()
        #*******************************************************************************************
        ##* FILE LIST HANDLERS
        #*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/files/', methods=['OPTIONS', 'GET'])
        def getReferenceFilesHandler():
            return dataManagementGetMyFiles(request, Response(), self.EXAMPLE_FILES_DIR, MAX_CLIENT_SPACE, isReference=True).getResponse()
        ##*******************************************************************************************
        ##* GFT FILE DELETION HANDLERS
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/files/<path:fileName>', methods=['OPTIONS', 'DELETE'])
        def deleteReferenceFileHandler(fileName):
            return dataManagementDeleteFile(request, Response(), self.EXAMPLE_FILES_DIR, MAX_CLIENT_SPACE, isReference=True, fileName=fileName).getResponse()

        ##*******************************************************************************************
        ##* SAVE THE  MESSAGE
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/messages/', methods=['OPTIONS', 'POST'])
        def saveMessage():
            return adminServletSaveMessage(request, Response()).getResponse()
        ##*******************************************************************************************
        ##* RETRIEVE THE MESSAGES
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/um_get_message', methods=['OPTIONS', 'POST'])
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/messages/', methods=['OPTIONS', 'GET'])
        def getMessage():
            return adminServletGetMessage(request, Response()).getResponse()
        ##*******************************************************************************************
        ##* DELETE MESSAGE
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/api/admin/messages/<path:message_type>', methods=['OPTIONS', 'DELETE'])
        def deleteMessage(message_type):
            return adminServletDeleteMessage(request, Response(), message_type).getResponse()

        ##*******************************************************************************************
        ##* SEND A REPORT MESSAGE
        ##*******************************************************************************************
        @self.app.route(SERVER_SUBDOMAIN + '/dm_sendReport', methods=['OPTIONS', 'POST'])
        def sendReportHandler():
            return adminServletSendReport(request, Response(), self.ROOT_DIRECTORY).getResponse()
        ##*******************************************************************************************
        ##* ADMIN SERVLETS HANDLERS - END
        #############################################################################################
        #############################################################################################
    def launch(self):
        ##*******************************************************************************************
        ##* LAUNCH APPLICATION
        ##*******************************************************************************************
        self.app.run(host=SERVER_HOST_NAME, port=SERVER_PORT_NUMBER,  debug=SERVER_ALLOW_DEBUG)

    ##*************************************************************************************************************
    # This function returns a new random job id
    #
    # @returns jobID
    ##*************************************************************************************************************
    def generateRandomID(self):
        #RANDOM GENERATION OF THE JOB ID
        #TODO: CHECK IF NOT EXISTING ID
        import string, random
        jobID = ''.join(random.sample(string.ascii_letters+string.octdigits*5,10))
        return jobID

    def readConfigurationFile(self):
        self.ROOT_DIRECTORY = ROOT_DIRECTORY
        import os
        if self.ROOT_DIRECTORY == "":
            self.ROOT_DIRECTORY = os.path.abspath(os.path.dirname(os.path.realpath(__file__))) + "/"
        else:
            self.ROOT_DIRECTORY = os.path.abspath(self.ROOT_DIRECTORY) + "/"

        self.EXAMPLE_FILES_DIR = self.ROOT_DIRECTORY + "examplefiles/"

        #PREPARE LOGGING
        logging.config.fileConfig(self.ROOT_DIRECTORY + 'conf/logging.cfg')

        #self.app.config['MAX_CONTENT_LENGTH'] = SERVER_MAX_CONTENT_LENGTH * pow(1024, 2)

    def startScheludeTasks(self):
        from apscheduler.schedulers.background import BackgroundScheduler
        import atexit
        from src.AdminTools.scripts.clean_databases import cleanDatabases

        cron = BackgroundScheduler(daemon=True)
        # Explicitly kick off the background thread
        cron.start()

        #@cron.interval_schedule(seconds=1)
        def scheludeTask():
            cleanDatabases(force=True)
            clearFailedData()

        cron.add_job(scheludeTask, 'interval', hours=24, id='my_job_id')
        # Shutdown your cron thread if the web process is stopped
        atexit.register(lambda: cron.shutdown(wait=False))

#################################################################################################################
#################################################################################################################
##* SUBCLASSES
##*************************************************************************************************************
class Response(object):
    """This class is used to specify the custom response object"""

    #****************************************************************
    # CONSTRUCTORS
    #****************************************************************
    def __init__(self):
        self.content=""
        self.status= 200
        #TODO: ENABLE THIS CODE??
        self.JSON_CONTENT_TYPE = {'Content-Type': 'application/json; charset=utf-8'}
        self.content_type = self.JSON_CONTENT_TYPE

    #****************************************************************
    # GETTERS AND SETTER
    #****************************************************************
    def setContent(self, content):
        self.content=content
        return self
    def getContent(self):
        return self.content

    def setStatus(self, status):
        self.status=status
        return self
    def getStatus(self):
        return self.status

    def setContentType(self, content_type):
        self.content_type=content_type
        return self
    def getContentType(self):
        return self.content_type

    def getResponse(self):
        return jsonify( self.content ), self.status, self.content_type

class MyJSONEncoder(JSONEncoder):
    def default(self, obj):
        if hasattr(obj,"toBSON"):
            return obj.toBSON()
        return super(MyJSONEncoder, self).default(object)
