import os, inspect, sys, shutil
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + "/../")
import logging
import logging.config

import datetime
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from conf.serverconf import (
    MONGODB_HOST,
    smpt_sender,
    MONGODB_PORT,
    MONGODB_DATABASE,
    CLIENT_TMP_DIR,
    ADMIN_ACCOUNTS,
    MAX_GUEST_DAYS,
    MAX_JOB_DAYS,
    PAINTOMICS_BASE_URL,
    PAINTOMICS_LOGO_URL,
)

from src.common.Util import sendEmail

# Directories directly under CLIENT_TMP that are NOT user directories.
#
# Everything else there is read as a "<userID>" directory, and STEP 7 rmtree's
# any of them that no user in the database claims. "nologin" was always
# excluded; "gtfcache" is the shared GTF cache Bed2GeneJob points at
# (Bed2GeneJob.getOptions -> "cache_dir": CLIENT_TMP + "gtfcache"), and no user
# will ever own it, so every cleanup run would have deleted the whole cache and
# made the next regions-to-genes job re-parse its annotation from scratch.
NON_USER_CLIENT_TMP_DIRS = ("nologin", "gtfcache")

# Every index the running server depends on, as (collection, create_index keys).
# Shared with paintomicsserver so startup and the nightly cron cannot drift:
# rebuildIndexes is on a 24h timer, so without the startup pass a fresh
# deployment answers every jobID query with a collection scan until it fires.
#
# aiInterpretationCollection was missing entirely. Its documents average 125KB
# and ai_interpret_status polls {"jobID": ...} every few seconds for the whole
# length of a multi-minute report, so it was the collection that most needed
# the index and the only one that never had it.
JOBID_INDEXES = [
    ('jobInstanceCollection', "jobID"),
    ('featuresCollection', "jobID"),
    ('featuresCollection', [("jobID", 1), ("featureType", 1)]),
    ('pathwaysCollection', "jobID"),
    ('foundFeaturesCollection', "jobID"),
    ('aiInterpretationCollection', "jobID"),
]

def cleanDatabases(force=False):
    log("Starting Clean Databases routine")

    connection = MongoClient(MONGODB_HOST, MONGODB_PORT)

    import os
    ROOT_DIRECTORY = os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + "/../") + "/"

    # STEP 1. GET ALL USERS BY DIRECTORY
    user_dirs = os.listdir(CLIENT_TMP_DIR)

    for reservedDir in NON_USER_CLIENT_TMP_DIRS:
        if reservedDir in user_dirs:
            user_dirs.remove(reservedDir)

    # STEP 2. GET ALL USERS IN DB
    users_list = connection[MONGODB_DATABASE]['userCollection'].find()

    # STEP 3. CHECK CURRENT INFORMATION
    #Users that are out of date (guest users)
    users_to_remove = []
    #Users that for any reason have lost the data dir -> create new one and clean files and Jobs from DB
    users_to_fix = []
    #Jobs that are out of date (normal and guest users)
    jobs_to_remove = {}
    #Jobs that need to be reminded (normal users)
    jobs_to_remind = {}
    #In addition we have to clean all files from db and dir

    # TODO: "nologin" user will not be present in the DB
    for user in users_list:
        user_id = int(user["userID"])
        if str(user_id) in user_dirs:
            # User is in database, so dir is OK
            user_dirs.remove(str(user_id))
        else:
            #Data dir missing, need to be fixed
            log("User " + str(user_id) + " marked to be fixed.")
            users_to_fix.append(user_id)

        force_remove = False
        if "is_guest" in user and user["is_guest"] == True and checkRemoveGuestUser(user, user_id):
            # If guest user, check if should be removed
            users_to_remove.append(user_id)
            force_remove = True
        else:
            # Check if user has jobs to be removed soon that need to be remained about
            # (only for "no guest" accounts)
            reminders = checkRemindJobsForUser(connection, user_id)

            if len(reminders) > 0:
                jobs_to_remind[user_id] = reminders


        # If check if user has jobs that should be removed
        aux = checkRemoveJobsForUser(connection, user_id, force_remove)
        if len(aux) > 0:
            jobs_to_remove[user_id] = aux

    log("Summary:")
    log("   - " + str(str(sum(len(x) for x in jobs_to_remove.values()))) + " jobs will be removed.")
    log("   - " + str(str(sum(len(x) for x in jobs_to_remind.values()))) + " reminder e-mails will be sent.")
    log("   - " + str(len(users_to_remove)) + " users will be removed.")
    log("   - " + str(len(users_to_fix)) + " users will be fixed.")
    log("   - " + str(len(user_dirs)) + " orphan directories will be removed.")
    log("")

    if not force:
        if not confirm(prompt='"Proceed?', resp=False):
            log("Bye.")
            return

    # STEP 4. REMOVE ALL OUTDATED JOBS (+ FEATURES AND FILES)
    for user_id, jobs_to_remove in jobs_to_remove.items():
        for job_id in jobs_to_remove:
            removeJobByJobID(connection, user_id, job_id)

    # STEP 5. REMOVE ALL OUTDATED GUEST USERS (+ FILES)
    for user_id in users_to_remove:
        #IF USER IN TO_FIX REMOVE IT
        if user_id in users_to_fix:
            users_to_fix.remove(user_id)
        #Jobs have been already removed
        removeAllFilesByUserID(connection, user_id)
        removeUserByUserID(connection, user_id)

    # STEP 6. FIX ALL ERRONEOUS USERS (BUT CLEAN FIRST THE BED2GENES, JOBS AND FILES)
    for user_id in users_to_fix:
        removeAllFilesByUserID(connection, user_id, only_db=True)
        fixUserDataByUserID(connection, user_id)

    # STEP 7. REMOVE THE ORPHAN DIRECTORIES
    for user_id in user_dirs:
        removeDirectoryByUserID(user_id)

    # STEP 8. SEND REMINDER E-MAILS
    for user_id, jobs_to_remind in jobs_to_remind.items():
        for job_id in jobs_to_remind:
            remindJobByJobID(connection, user_id, job_id, ROOT_DIRECTORY)

    # STEP 9. REBUILD INDEXES
    rebuildIndexes(connection)

def checkRemoveGuestUser(user, user_id):
    last_login = datetime.datetime.strptime(user['last_login'], "%Y%m%d").date()
    max_date = datetime.date.today() - datetime.timedelta(days=MAX_GUEST_DAYS)
    remove = (last_login < max_date)
    if remove:
        log("User " + str(user_id) + " marked to be removed.")
    return remove

def checkRemoveJobsForUser(connection, user_id, force_remove=False):
    #Get all jobs for user
    jobs_list = connection[MONGODB_DATABASE]['jobInstanceCollection'].find({"userID":str(user_id)})
    max_date = datetime.date.today() - datetime.timedelta(days=MAX_JOB_DAYS)
    jobs_remove = []
    # for each job
    for job in jobs_list:
        #Check if date OR if force_remove
        date = datetime.datetime.strptime(job['accessDate'][0:8], "%Y%m%d").date()
        if force_remove or date < max_date:
            log("Job " + str(job["jobID"]) + " (user " + str(user_id) + ") marked to be removed.")
            jobs_remove.append(job['jobID'])
    return jobs_remove

def checkRemindJobsForUser(connection, user_id):
    #Get all jobs for user
    jobs_list = connection[MONGODB_DATABASE]['jobInstanceCollection'].find({"userID":str(user_id),
                                                                            "reminderSent": {"$exists": False}
                                                                            })
    max_date = datetime.date.today() - datetime.timedelta(days=MAX_JOB_DAYS + 7)
    min_date = datetime.date.today() - datetime.timedelta(days=MAX_JOB_DAYS)
    jobs_remind = []
    # for each job
    for job in jobs_list:
        #Check if date OR if force_remove
        date = datetime.datetime.strptime(job['accessDate'][0:8], "%Y%m%d").date()
        # Avoid sending reminders of jobs that will be deleted today
        if date >= max_date and date < min_date:
            log("Job " + str(job["jobID"]) + " (user " + str(user_id) + ") marked to be reminded.")
            jobs_remind.append(job['jobID'])
    return jobs_remind


def removeJobByJobID(connection, user_id, job_id):
    log("Removing job " + job_id)
    #STEP 1. REMOVE ALL THE FEATURES ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['featuresCollection'].delete_many({"jobID": job_id})
    #STEP 2. REMOVE ALL THE VISUAL OPTIONS ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['visualOptionsCollection'].delete_many({"jobID": job_id})
    #STEP 3. REMOVE ALL THE PATHWAYS ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['pathwaysCollection'].delete_many({"jobID": job_id})
    #STEP 4. REMOVE ALL THE FOUND FEATURES ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['foundFeaturesCollection'].delete_many({"jobID": job_id})
    #STEP 5. REMOVE THE JOB FROM DATABASE
    connection[MONGODB_DATABASE]['jobInstanceCollection'].delete_many({"jobID": job_id})
    #STEP 6. REMOVE THE JOB DIRECTORY FROM USER DIR
    removeDirectoryByUserID(user_id, job_id)


def remindJobByJobID(connection, user_id, job_id, ROOT_DIRECTORY):
    log("Reminding job " + job_id)

    ROOT_DIRECTORY_CORRECTED = os.path.abspath(ROOT_DIRECTORY + '/../../../PaintomicsClient/') + '/'

    try:
        job_data = connection[MONGODB_DATABASE]['jobInstanceCollection'].find_one({"jobID": job_id})
        user_data = connection[MONGODB_DATABASE]['userCollection'].find_one({"userID": user_id})

        message = '<html><body>'
        message += "<a href='" + PAINTOMICS_BASE_URL + "/' target='_blank'>"
        message += "  <img src='" + PAINTOMICS_LOGO_URL + "' border='0' width='150' height='33' alt='PaintOmics logo'>"
        message += "</a>"
        message += "<div style='width:100%; height:10px; border-top: 1px dotted #333; margin-top:20px; margin-bottom:30px;'></div>"
        message += "<h1>Your Paintomics job " + job_id + " will be deleted soon!</h1>"
        message += "<p>Hello, " + user_data["userName"] + "! Your job with ID " + job_id + " will be deleted in one week.</p>"
        message += "<p>To avoid it, please visit the following link to update the accession date:</p>"
        reminder_link = PAINTOMICS_BASE_URL + "/?jobID=" + job_id
        message += "<p><a target='_blank' href='" + reminder_link + "'>" + reminder_link + "</a></p></br>"
        message += "<div style='width:100%; height:10px; border-top: 1px dotted #333; margin-top:20px; margin-bottom:30px;'></div>"
        message += "<p>Problems? E-mail <a href='mailto:" + smpt_sender + "'>" + smpt_sender + "</a></p>"
        message += "<p>Legal notice: you are receiving this e-mail because you accepted Paintomics conditions. Your data will be stored for the"
        message += "solely purpose of informing you about actions involving your jobs."
        message += '</body></html>'

        sendEmail(ROOT_DIRECTORY_CORRECTED, user_data["email"], user_data["userName"], "PaintOmics 4: one job is going to expire soon",
                  message, isHTML=True)
    except Exception as e:
        logging.error("Failed to send the email.")

    #STEP 3.REMOVE THE JOB FROM DATABASE
    connection[MONGODB_DATABASE]['jobInstanceCollection'].update_many({"jobID": job_id}, {'$set': {"reminderSent": 1}}, upsert=False)


def removeAllFilesByUserID(connection, user_id, only_db=False):
    log("Removing files for user " + str(user_id) + " from database")
    #STEP 1. REMOVE ALL THE FEATURES ASSOCIATED TO JOB
    connection[MONGODB_DATABASE]['fileCollection'].delete_many({"userID": str(user_id)})
    #STEP 2. REMOVE THE DIRECTORIES FOR USER
    if not only_db:
        removeDirectoryByUserID(user_id)

def removeDirectoryByUserID(user_id, job_id=None):
    #STEP 1. BUILD THE PATH
    dir = CLIENT_TMP_DIR.rstrip("/") + "/" + str(user_id)
    if job_id != None:
        dir+= "/jobsData/" + job_id
    #STEP 2. REMOVE THE DIRECTORY AND ALL CHILDREN
    if os.path.isdir(dir):
        log("Removing files for user " + str(user_id) + " from directory " + dir)
        shutil.rmtree(dir)
    else:
        log("Directory " + dir + " not found!")


def removeUserByUserID(connection, user_id):
    #STEP 1. REMOVE THE USER ENTRY
    user = connection[MONGODB_DATABASE]['userCollection'].find_one({"userID": user_id})
    if not user["userName"] in ADMIN_ACCOUNTS: #prevent admin accounts to be removed
        log("Removing user " + str(user_id) + " from database.")
        connection[MONGODB_DATABASE]['userCollection'].delete_many({"userID": user_id})
    else:
        log("User " + user["userName"] + " cannot be removed.")


def fixUserDataByUserID(connection, user_id):
    log("Fixing user " + str(user_id))
    #STEP 1. REMOVE ALL FILES ENTRIES
    removeAllFilesByUserID(connection, user_id, only_db=True)
    #STEP 2. REMOVE ALL JOBS
    jobs_to_remove = checkRemoveJobsForUser(connection, user_id, force_remove=True)
    for job_id in jobs_to_remove:
        removeJobByJobID(connection, user_id, job_id)
    #STEP 3. CREATE THE DIRECTORIES
    dir = CLIENT_TMP_DIR.rstrip("/") + "/" + str(user_id)
    log("Creating directories at " + dir)
    paths = [
        dir,
        os.path.join(dir, "inputData"),
        os.path.join(dir, "jobsData"),
        os.path.join(dir, "tmp"),
    ]
    for path in paths:
        os.makedirs(path, exist_ok=True)

def rebuildIndexes(connection):
    # The daily reindex() loop that used to stand here is gone.
    #
    # It rebuilt every index of all eight job collections from scratch, inside
    # the single serving process, once every 24h -- including featuresCollection
    # (2.85M documents / 2.1GB on this machine), which takes a strong collection
    # lock for the duration. It produced no observable output: the indexes it
    # rebuilt were the indexes it started with.
    #
    # It was also a live crash. reindex() is deprecated in pymongo 3.11 and
    # REMOVED in pymongo 4, which requirements.txt now pins: under pymongo 4
    # `collection.reindex` resolves to a *sub-collection* named "reindex"
    # instead of a method, and calling it raises TypeError, which the
    # `except OperationFailure` did not catch. The cron would have died before
    # reaching the create_index calls below -- and this function is the only
    # place job indexes are ever created, so a fresh deployment would have run
    # every jobID query as a collection scan.
    #
    # The create_index calls stay: they are idempotent, cheap when the index
    # exists, and they are the point of the whole function.
    log("Creating jobID indexes...")
    for collectionName, keys in JOBID_INDEXES:
        try:
            connection[MONGODB_DATABASE][collectionName].create_index(keys)
        except OperationFailure as err:
            # One unindexable collection must not cost the others their index.
            log("Failed to create index " + str(keys) + " on " + collectionName + ": " + str(err))
    log("jobID indexes created.")

def log(msg):
    print(msg)
    frame,filename,line_number,function_name,lines,index=inspect.getouterframes(inspect.currentframe())[1]
    line=lines[0]
    indentation_level=line.find(line.lstrip())
    logging.info('{i} {m}'.format(i=' '*indentation_level,m=msg))


def readConfigurationFile():
    import os
    ROOT_DIRECTORY = os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + "/../") + "/"
    #PREPARE LOGGING
    from src.common.LoggingSetup import configureLogging
    configureLogging(ROOT_DIRECTORY + 'conf/logging.cfg')


def confirm(prompt=None, resp=False):
    """prompts for yes or no response from the user. Returns True for yes and
    False for no.

    'resp' should be set to the default value assumed by the caller when
    user simply types ENTER.

    >>> confirm(prompt='Create Directory?', resp=True)
    Create Directory? [y]|n:
    True
    >>> confirm(prompt='Create Directory?', resp=False)
    Create Directory? [n]|y:
    False
    >>>
    Create Directory? [n]|y: y
    True

    """

    if prompt is None:
        prompt = 'Confirm'

    if resp:
        prompt = '%s [%s]|%s: ' % (prompt, 'y', 'n')
    else:
        prompt = '%s [%s]|%s: ' % (prompt, 'n', 'y')

    while True:
        ans = input(prompt)
        if not ans:
            return resp
        if ans not in ['y', 'Y', 'n', 'N']:
            print('please enter y or n.')
            continue
        if ans == 'y' or ans == 'Y':
            return True
        if ans == 'n' or ans == 'N':
            return False

# cleanDatabases(force=True)
