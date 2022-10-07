#SERVER SETTINGS
SERVER_HOST_NAME          = "0.0.0.0" ##THE IP ADDRESS FOR GALAKSIO, LEAVE 0.0.0.0 FOR LISTENING ALL REQUESTS
SERVER_PORT_NUMBER        = 8080 ##THE PORT NUMBER THAT GALAKSIO LISTENS FOR REQUESTS
SERVER_ALLOW_DEBUG        = False ##ENABLE DEBUG, THIS OPTION IS JUST FOR DEVELOPMENT
SERVER_SUBDOMAIN          = "" ##USE THIS OPTION IF GALAKSIO RUNS UNDER AN SPECIFIC SUBDOMAIN, E.G. myserver.com/paintomics (w/o proxy)
SERVER_MAX_CONTENT_LENGTH = 200 * pow(1024,2) ##THE MAX SIZE FOR THE REQUESTS SENT BY THE CLIENTS, IN MB
ADMIN_ACCOUNTS            = "admin,qqqq,aaa,Tian"

#FILES SETTINGS
ROOT_DIRECTORY            = "" ##THE LOCATION FOR THE PAINTOMICS FILES, LEAVE BLANK TO AUTO DETECT
CLIENT_TMP_DIR            = "/home/tian/database/CLIENT_TMP/"
KEGG_DATA_DIR             = "/home/tian/database/KEGG_DATA/"
MAX_CLIENT_SPACE          = 200 * pow(1024,2) #MAX_CLIENT_SPACE IN MB
MAX_GUEST_DAYS            = 90
MAX_JOB_DAYS              = 365
MAX_NUMBER_FEATURES      = 1000000

#MONGO DB SETTINGS
MONGODB_HOST      = "localhost"
MONGODB_PORT      = 27017
MONGODB_DATABASE  = "PaintomicsDB"

#MULTI-THREADING OPTIONS
MAX_THREADS      = 6
MAX_WAIT_THREADS = 300 #IN SECONDS
N_WORKERS        = 4

#CACHE SIZES
JOB_CACHE_MAX_SIZE  = 10
KEGG_CACHE_MAX_SIZE = 5

#DOWNLOAD SETTINGS
DOWNLOAD_DELAY_1    =2
DOWNLOAD_DELAY_2    =2
MAX_TRIES_1 = 3
MAX_TRIES_2 = 5

#SMTP CONFIGURATION
smtp_host       = "smtp-mail.outlook.com"    #Sets Gmail, Office... as the SMTP server
smtp_port       = 587                        #Set the SMTP port for the GMAIL
use_smtp_auth   = True                       #Enable SMTP authentication
use_smtp_ssl    = False                      #Whether use normal SMTP or SMTP_SSL
smtp_secure     = "tls"                      #Use tls, etc.
smpt_username   = "paintomics4@outlook.com"  #THE SENDER EMAIL, DEPENDS ON THE SMTP SETTINGS
smpt_pass       = "UGFpbnQzMjEj"             #THE SENDER PASS IN BASE64 CODIFICATION, DEPENDS ON THE SMTP SETTINGS
smpt_sender     = "paintomics4@outlook.com"  #Sender email (From value at the email)
smpt_sender_name= "Paintomics 4"             #Sender name (From value at the email)
