#SERVER SETTINGS
SERVER_HOST_NAME          = "0.0.0.0" ##THE IP ADDRESS FOR GALAKSIO, LEAVE 0.0.0.0 FOR LISTENING ALL REQUESTS
SERVER_PORT_NUMBER        = 8000 ##THE PORT NUMBER THAT GALAKSIO LISTENS FOR REQUESTS
SERVER_ALLOW_DEBUG        = False ##ENABLE DEBUG, THIS OPTION IS JUST FOR DEVELOPMENT
SERVER_SUBDOMAIN          = "" ##USE THIS OPTION IF GALAKSIO RUNS UNDER AN SPECIFIC SUBDOMAIN, E.G. myserver.com/paintomics (w/o proxy)
SERVER_MAX_CONTENT_LENGTH = 200 * pow(1024,2) ##THE MAX SIZE FOR THE REQUESTS SENT BY THE CLIENTS, IN MB
ADMIN_ACCOUNTS            = "admin"

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
MAX_WAIT_THREADS = 900 #IN SECONDS
N_WORKERS        = 4

#CACHE SIZES
JOB_CACHE_MAX_SIZE  = 50
KEGG_CACHE_MAX_SIZE = 25

#DOWNLOAD SETTINGS
DOWNLOAD_DELAY_1    =2
DOWNLOAD_DELAY_2    =2
MAX_TRIES_1 = 3
MAX_TRIES_2 = 5

#SMTP CONFIGURATION (DEPRECATED - kept for reference)
# smtp_host       = "smtp-mail.outlook.com"    #Sets Gmail, Office... as the SMTP server
# smtp_port       = 587                        #Set the SMTP port for the GMAIL
# use_smtp_auth   = True                       #Enable SMTP authentication
# use_smtp_ssl    = False                      #Whether use normal SMTP or SMTP_SSL
# smtp_secure     = "tls"                      #Use tls, etc.
# smpt_username   = "paintomics4@outlook.com"  #THE SENDER EMAIL, DEPENDS ON THE SMTP SETTINGS
# smpt_pass       = "<redacted>"                # Do not commit credentials. Provide via environment/secrets manager.
# smpt_sender     = "paintomics4@outlook.com"  #Sender email (From value at the email)
# smpt_sender_name= "Paintomics 4"             #Sender name (From value at the email)

#EMAIL CONFIGURATION (SMTP via SendGrid)
import os
from urllib.parse import urlparse
EMAIL_PROVIDER      = "smtp"                                           #Email provider type
EMAIL_FROM_ADDRESS  = "paintomics4@outlook.com"                        #Sender email address
EMAIL_FROM_DISPLAY  = "PaintOmics"                                     #Sender display name
SMTP_HOST           = os.getenv("SMTP_HOST", "smtp.sendgrid.net")      #SMTP server hostname
SMTP_PORT           = int(os.getenv("SMTP_PORT", "587"))               #SMTP server port (587 for TLS)
SMTP_USERNAME       = os.getenv("SMTP_USERNAME", "apikey")             #SMTP username
SMTP_PASSWORD       = os.getenv("SMTP_PASSWORD", "")                   #SMTP password (SendGrid API key)
SMTP_USE_TLS        = True                                             #Use TLS encryption

# Web-facing constants
PAINTOMICS_BASE_URL        = os.getenv("PAINTOMICS_BASE_URL", "https://paintomics.uv.es").rstrip("/")
PAINTOMICS_LOGO_PATH       = os.getenv("PAINTOMICS_LOGO_PATH", "/resources/images/paintomics_white_300x66")
PAINTOMICS_LOGO_URL        = f"{PAINTOMICS_BASE_URL}{PAINTOMICS_LOGO_PATH}"
PAINTOMICS_LOGIN_URL       = os.getenv("PAINTOMICS_LOGIN_URL", f"{PAINTOMICS_BASE_URL}/")
PAINTOMICS_DOCS_URL        = os.getenv("PAINTOMICS_DOCS_URL", "https://paintomics.readthedocs.io/en/latest/")
PAINTOMICS_EMAIL_DOMAIN    = os.getenv(
    "PAINTOMICS_EMAIL_DOMAIN",
    urlparse(PAINTOMICS_BASE_URL).netloc or "paintomics.uv.es"
)
EMAIL_REPORT_RECIPIENTS    = [
    email.strip()
    for email in os.getenv("EMAIL_REPORT_RECIPIENTS", "paintomics4@outlook.com").split(",")
    if email.strip()
]

# Backwards compatibility for legacy SMTP-based imports
smpt_sender      = EMAIL_FROM_ADDRESS
smpt_sender_name = EMAIL_FROM_DISPLAY
