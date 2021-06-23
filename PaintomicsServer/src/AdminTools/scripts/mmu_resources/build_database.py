import imp
import traceback

from sys import argv, stderr
from subprocess import CalledProcessError, check_call
#**************************************************************************
#STEP 1. READ CONFIGURATION AND PARSE INPUT FILES
#
# DO NOT CHANGE THIS CODE
#**************************************************************************
#SPECIE = "bta"
#ROOT_DIR = '/home/tian/Desktop/git/paintomics3/PaintomicsServer/src/AdminTools/'
#DATA_DIR = '/home/tian/Downloads/database/KEGG_DATA/current/bta/'
#LOG_FILE = "~/Downloads/database/KEGG_DATA/current/install.log"
#currentDataDir = "~/Downloads/database/KEGG_DATA/current"
#ROOT_DIRECTORY = "/home/tian/Desktop/git/paintomics3/PaintomicsServer/src/"


SPECIE      = argv[1]
ROOT_DIR    = argv[2].rstrip("/") + "/"      #Should be src/AdminTools
DATA_DIR    = argv[3].rstrip("/") + "/"
LOG_FILE    = argv[4]




COMMON_BUILD_DB_TOOLS = imp.load_source('common_build_database', ROOT_DIR + "scripts/common_build_database.py")
COMMON_BUILD_DB_TOOLS.SPECIE= SPECIE
COMMON_BUILD_DB_TOOLS.DATA_DIR= DATA_DIR

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
    COMMON_BUILD_DB_TOOLS.processKEGGMappingData()
    #**************************************************************************
    # STEP 2. PROCESS THE KEGG DATABASE
    #**************************************************************************
    COMMON_BUILD_DB_TOOLS.processKEGGPathwaysData()
    COMMON_BUILD_DB_TOOLS.processReactomePathwaysData(ROOT_DIR)
    #COMMON_BUILD_DB_TOOLS.mergeNetworkFiles()

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
