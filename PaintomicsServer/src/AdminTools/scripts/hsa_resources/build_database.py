import imp
import traceback
import pymongo
from sys import argv, stderr
from subprocess import CalledProcessError

#**************************************************************************
#STEP 1. READ CONFIGURATION AND PARSE INPUT FILES
#
# DO NOT CHANGE THIS CODE
#**************************************************************************
ListToInstall = ["bta","mtu","cel", "cfa"]


SPECIE = "hsa"
#ROOT_DIR    = argv[2].rstrip("/") + "/"      #Should be src/AdminTools
ROOT_DIR = '/home/tian/Desktop/git/paintomics3/PaintomicsServer/src/AdminTools/'
#DATA_DIR    = argv[3].rstrip("/") + "/"
DATA_DIR = '/home/tian/Downloads/database/KEGG_DATA/current/hsa/'
#LOG_FILE    = argv[4]
LOG_FILE = "~/Downloads/database/KEGG_DATA/current/install.log"
currentDataDir = "~/Downloads/database/KEGG_DATA/current"
ROOT_DIRECTORY = "/home/tian/Desktop/git/paintomics3/PaintomicsServer/src/"
#installCommonData(currentDataDir + "common/", ROOT_DIRECTORY + "AdminTools/scripts/")

COMMON_BUILD_DB_TOOLS = imp.load_source('common_build_database', ROOT_DIR + "scripts/common_build_database.py")
COMMON_BUILD_DB_TOOLS.SPECIE= SPECIE
COMMON_BUILD_DB_TOOLS.DATA_DIR= DATA_DIR
COMMON_BUILD_DB_TOOLS.EXTERNAL_RESOURCES = imp.load_source('download_conf',  ROOT_DIR + "scripts/" + SPECIE + "_resources/download_conf.py").EXTERNAL_RESOURCES
COMMON_BUILD_DB_TOOLS.COMMON_RESOURCES = imp.load_source('download_conf',  ROOT_DIR + "scripts/common_resources/download_conf.py").EXTERNAL_RESOURCES
COMMON_BUILD_DB_TOOLS.SERVER_SETTINGS = imp.load_source('serverconf.py',  ROOT_DIR + "../conf/serverconf.py")

#**************************************************************************
# CHANGE THE CODE FROM HERE
#
# STEP 2. INSTALL FILES
#**************************************************************************
try:
    #**************************************************************************
    # STEP 1. EXTRACT THE MAPPING DATABASE
    #**************************************************************************
    COMMON_BUILD_DB_TOOLS.processEnsemblData()
    COMMON_BUILD_DB_TOOLS.processRefSeqData()
    #COMMON_BUILD_DB_TOOLS.processUniProtData()
    COMMON_BUILD_DB_TOOLS.processRefSeqGeneSymbolData()
    COMMON_BUILD_DB_TOOLS.processKEGGMappingData()


    #**************************************************************************
    # STEP 2. PROCESS THE KEGG  & OTHER DATABASES
    #**************************************************************************
    COMMON_BUILD_DB_TOOLS.processKEGGPathwaysData()
    COMMON_BUILD_DB_TOOLS.processReactomePathwaysData()
    #COMMON_BUILD_DB_TOOLS.mergeNetworkFiles()


    #**************************************************************************
    # RESULTS
    #**************************************************************************
    #COMMON_BUILD_DB_TOOLS.printResults()

    #**************************************************************************
    # DUMP AND INSTALL
    #**************************************************************************
    COMMON_BUILD_DB_TOOLS.dumpDatabase()
    COMMON_BUILD_DB_TOOLS.dumpErrors()
    COMMON_BUILD_DB_TOOLS.createDatabase()


except CalledProcessError as ex:
    stderr.write("FAILED WHILE PROCESSING DATA " + str(ex))
    traceback.print_exc(file=stderr)
    exit(1)
except Exception as ex:
    stderr.write("FAILED WHILE PROCESSING DATA " + str(ex))
    traceback.print_exc(file=stderr)
    exit(1)

exit(0)
