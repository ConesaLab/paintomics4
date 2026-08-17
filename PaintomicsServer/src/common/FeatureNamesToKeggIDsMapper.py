from pymongo import MongoClient
import logging, itertools
import os, sys, signal, time
import re
from multiprocessing import Process, cpu_count, Manager, RawArray
from math import ceil
from re import compile as compile_re, IGNORECASE as IGNORECASE_re
from collections import defaultdict
from operator import attrgetter
from itertools import chain

from src.common.Util import chunks
from src.common.KeggInformationManager import KeggInformationManager
from src.common import JobProgress

from src.classes.FoundFeature import FoundFeature

from src.conf.organismDB import dicDatabases
from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT, MAX_THREADS, MAX_WAIT_THREADS #MULTITHREADING


# The parent's stream objects, kept alive in the fork child on purpose: see
# _refreshStandardStreamsInForkChild. Never read; never emptied.
_inheritedStreams = []


def _refreshStandardStreamsInForkChild():
    """
    The mapping workers below are forked from a server process that keeps
    serving requests on other threads. A fork can land while one of those
    threads is mid-write, and the child then inherits sys.stdout/sys.stderr
    (and logging file streams) whose buffer locks are held by a thread that
    does not exist in the child: its first print/log call blocks forever.
    CPython re-initialises logging's OWN locks after a fork, but not the
    locks inside buffered IO objects, so the streams themselves must be
    replaced. Observed in production as a worker frozen in
    PyThread_acquire_lock_timed under a progress print until the
    MAX_WAIT_THREADS timeout killed the job -- and terminate() could not
    reap it, because the child also inherits uWSGI's SIGTERM handler, so
    the default disposition is restored here as well.

    Two rules keep this hook from re-creating the very deadlock it exists
    to prevent (both were violated by its first version, and a Manager
    server child sat frozen for 32 minutes on paintomics.uv.es on
    2026-08-17, its parent's ``Manager()`` blocked forever waiting for the
    child's address, one queue worker gone until the service restarted):

      * never FLUSH an inherited stream in the child. That is what
        ``StreamHandler.setStream`` does before swapping, so handlers get
        their ``stream`` attribute assigned directly instead;
      * never DROP the last reference to an inherited stream in the child.
        A TextIOWrapper's finaliser closes it, and closing flushes -- the
        same lock again, this time from inside garbage collection. The old
        objects are parked in ``_inheritedStreams`` for the life of the
        child; whatever they buffered belongs to the parent, which still
        holds them and will write it out itself.
    """
    _inheritedStreams.extend((sys.stdout, sys.stderr))
    sys.stdout = open(1, "w", buffering=1, closefd=False)
    sys.stderr = open(2, "w", buffering=1, closefd=False)
    loggers = [logging.getLogger()] + [
        logger for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)]
    for handler in {h for logger in loggers for h in logger.handlers}:
        try:
            if isinstance(handler, logging.FileHandler):
                _inheritedStreams.append(handler.stream)
                handler.stream = handler._open()
            elif isinstance(handler, logging.StreamHandler):
                _inheritedStreams.append(handler.stream)
                handler.stream = sys.stderr
        except Exception:
            pass
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _joinAllWithinDeadline(processes, seconds):
    """
    Wait for every process in ``processes`` but never longer than ``seconds``
    IN TOTAL. ``for p in processes: p.join(seconds)`` -- the previous form --
    gives every process its own budget, so with six workers the "took too
    long" kill only fired after up to six times MAX_WAIT_THREADS (90 minutes
    at the configured 900 s), while the client kept polling.
    """
    deadline = time.monotonic() + seconds
    for process in processes:
        process.join(max(0.0, deadline - time.monotonic()))


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_refreshStandardStreamsInForkChild)

#*****************************************************************
#   _____ ____  __  __ __  __  ____  _   _
#  / ____/ __ \|  \/  |  \/  |/ __ \| \ | |
# | |   | |  | | \  / | \  / | |  | |  \| |
# | |   | |  | | |\/| | |\/| | |  | | . ` |
# | |___| |__| | |  | | |  | | |__| | |\  |
#  \_____\____/|_|  |_|_|  |_|\____/|_| \_|
#
#*****************************************************************

def getDatabasesByOrganismCode(organism):
    """
    Depending on the organism this function returns the name for the databases
    which contains the valid translations for names into valid KEGG identifiers

    @param {String} organism, the organim code e.g. mmu
    @returns {List} databaseConvertion
    """

    # dicDatabases is inside the conf file "organismDB" and should be
    # updated after installing new species with external annotation data.

    return dicDatabases.get(organism, [{'KEGG': "kegg_id"}, {'KEGG': "kegg_gene_symbol"}])

def getConnectionByOrganismCode(organism):
    """
    Devuelve la conexion a la base de datos del organismo correspondiente asi como el nombre de la tabla
    que se usara para realizar la conversion para dicho organismo y un cursor asociado a ella

    @param {String} organism
    @returns
    """
    client = MongoClient(MONGODB_HOST, MONGODB_PORT)
    db = client[organism + "-paintomics"]
    return client, db

#*****************************************************************
#   _____ ______ _   _ ______  _____
#  / ____|  ____| \ | |  ____|/ ____|
# | |  __| |__  |  \| | |__  | (___
# | | |_ |  __| | . ` |  __|  \___ \
# | |__| | |____| |\  | |____ ____) |
#  \_____|______|_| \_|______|_____/
#
#*****************************************************************
def findKeggIDByFeatureName(jobID, featureName, organism, db, databaseConvertion_id):
    """
    This function queries the MongoDB looking for the associated gene ID for the given gene name

    @param {String} jobID, the identifier for the running job, necessary to for the temporal caches
    @param {String} featureName, the name for the feature that we want to map
    @param {String} organism, the organims code
    @param  {pymongo.Database} db, the open connection with MongoDB database
    @param {String} databaseConvertion_id, identifier for the database which contains the translated feature name (e.g. entrezgene for mmu)
    @returns {List} matchedFeatures, a list of translated identifiers
    @returns {Boolean} found, True if we found at least one translation
    """
    #Check if the id is ath the cache of translation
    featureIDs = KeggInformationManager().findInTranslationCache(jobID, featureName, "id", databaseConvertion_id)
    if(featureIDs != None):
        return featureIDs, True

    matchedFeatures=[]
    try:
        mates  = db.xref.find({"display_id": featureName}, {"item" :1, "mates":1, "qty":1})[0].get("mates") #Will fail if not matches
        cursor = db.xref.find({"dbname_id" : databaseConvertion_id, "_id" : { "$in" : mates }}, {"display_id":1})

        # No count() guard: Cursor.count() was removed in pymongo 4, and because
        # this block swallows every exception the AttributeError would have been
        # invisible -- every lookup would silently report "not found". Iterating
        # an empty cursor is already a no-op, and this drops a server round-trip.
        for item in cursor:
            matchedFeatures.append(item.get("display_id"))
        return matchedFeatures, len(matchedFeatures) > 0

    except Exception as ex:
        return matchedFeatures, False

def findIDsByFeaturesName(jobID, featureNames, db, databaseConvertion_id):
    """
    This function queries the MongoDB looking for the associated gene ID for the given gene name

    @param {String} jobID, the identifier for the running job, necessary to for the temporal caches
    @param {String} featureName, the name for the feature that we want to map
    @param {String} organism, the organims code
    @param  {pymongo.Database} db, the open connection with MongoDB database
    @param {String} databaseConvertion_id, identifier for the database which contains the translated feature name (e.g. entrezgene for mmu)
    @returns {List} matchedFeatures, a list of translated identifiers
    @returns {Boolean} found, True if we found at least one translation
    """
    #Check if the id is ath the cache of translation
    cachedFeatureIDs = KeggInformationManager().findBatchInTranslationCache(jobID, featureNames, "id", databaseConvertion_id)

    notCachedIds = set(featureNames).difference(set(cachedFeatureIDs.keys()))

    listMongoPipeline = [
        {"$match": {"display_id": {"$in": list(notCachedIds)}}},
        {"$unwind": "$mates"},
        {"$lookup": {
            "from": "xref",
            "localField": "mates",
            "foreignField": "_id",
            "as": "unwind_mate"
        }},
        {"$match": {"unwind_mate.dbname_id": databaseConvertion_id}},
        {"$replaceRoot": {"newRoot": { "$mergeObjects": [{ "$arrayElemAt": ["$unwind_mate", 0]}, {"original_display_id": "$display_id"}]}}},
        {"$project": {"_id": 0, "display_id": 1, "original_display_id": 1}}
    ]

    matchedFeatures = defaultdict(list)

    try:
        if len(notCachedIds):
            listResultCursor = db.xref.aggregate(listMongoPipeline, batchSize = 2000)

            for foundFeature in listResultCursor:
                matchedFeatures[foundFeature.get("original_display_id")].append(str(foundFeature.get("display_id")))

            KeggInformationManager().updateTranslationCache(jobID, matchedFeatures, "id", databaseConvertion_id)
    except Exception as ex:
        logging.error("EXCEPTION %s", ex)
    finally:
        matchedFeatures.update(cachedFeatureIDs)

        return matchedFeatures

def findGeneSymbolByFeatureID(jobID, featureID, organism, db, databaseConvertion_id, databaseGeneSymbol_id):
    """
    This function queries the MongoDB looking for the associated gene symbol for the given gene ID

    @param {String} jobID, the identifier for the running job, necessary to for the temporal caches
    @param {String} featureID, the ID for the feature that we want to map
    @param {String} organism, the organims code
    @param  {pymongo.Database} db, the open connection with MongoDB database
    @param {String} databaseConvertion_id, identifier for the database which contains the translated feature name (e.g. entrezgene for mmu)
    @param {String} databaseGeneSymbol_id, identifier for the database which contains the translated feature symbol (e.g. refseq_gene_symbol for mmu)
    @returns {List} matchedFeature, a gene symbol for the translated identifier
    @returns {Boolean} found, True if we found at least one translation
    """
    #Check if the id is ath the cache of translation
    geneSymbol = KeggInformationManager().findInTranslationCache(jobID, featureID, "symbol", databaseConvertion_id)
    if(geneSymbol != None):
        return geneSymbol, True

    try:
        mates = db.xref.find({"display_id": featureID, "dbname_id" : databaseConvertion_id}, {"item" :1, "mates":1, "qty":1})[0].get("mates") #Will fail if not matches
        matchedFeature=db.xref.find_one({"dbname_id" : databaseGeneSymbol_id, "_id" : { "$in" : mates }}, {"display_id":1})
        if(matchedFeature != None):
            return matchedFeature.get("display_id"), True
        return None, False

    except Exception as ex:
        return None, False

def mapFeatureIdentifiers(jobID, organism, databases, featureList,  matchedFeatures, notMatchedFeatures, foundFeatures, enrichment, progressArray=None, progressSlot=0):
    """
    This function is used to query the database in different threads.

    @param  {String} organism, the specie code
    @param  {List}   featureList, the list of feature IDs to map
    @param  {Dict}   alreadyMatchedGenesTable, a dict shared between threads where we store the matching for identifiers
                     (will be combined later with KeggInfoManager cache)
    @param  {List}   matchedFeatures, a list shared between threads where we store the matched features
    @param  {List}   notMatchedFeatures, a list shared between threads where we store the unmatched features
    @param  {RawArray} progressArray, optional shared-memory counter allocated before
                     the fork; this worker writes its own completion percentage into
                     progressArray[progressSlot]. Defaults to None so the direct,
                     non-forked call in Job.parseGeneBasedFiles is unaffected.
    @param  {Integer} progressSlot, this worker's index in progressArray

    @returns True
    """


    #***********************************************************************************
    #* STEP 2. GET THE CORRESPONDING DATABASE FOR CURRENT SPECIES
    #***********************************************************************************
    databaseConvertion = getDatabasesByOrganismCode(organism)

    # Remove the user not-selected databases
    # databases_codes = [dbid for dbname, dbid in databaseConvertion[0].iteritems() if dbname in databases]

    gene_databases = databaseConvertion[0]
    symbol_databases = databaseConvertion[1]

    # Use/Not use features to count the total number of items matched
    featureEnrichment = (enrichment == "features")

    client, db  = getConnectionByOrganismCode(organism)

    databaseConvertion_ids = {dbname: db.dbname.find_one({"dbname": gene_databases.get(dbname)}, {"item": 1, "qty": 1}).get("_id") for dbname in databases}
    databaseGeneSymbol_ids = {dbname: db.dbname.find_one({"dbname": symbol_databases.get(dbname)}, {"item": 1, "qty": 1}).get("_id") for dbname in databases}

    # Iterate symbol-capable databases first so the per-featureID dedup below keeps
    # the clone whose name was resolved against a real gene-symbol database
    # (e.g. KEGG→refseq_gene_symbol for ath). Otherwise a caller-provided list ordered
    # with a same-DB symbol entry first (e.g. MapMan) silently wins and the symbol
    # lookup is skipped. Callers build `databases` from a set in some paths, so the
    # order is not stable — sort here to make the behavior deterministic.
    databases = sorted(
        databases,
        key=lambda d: gene_databases.get(d) == symbol_databases.get(d)
    )

    try:
        # Save found features for each database, plus the unique between them
        matches = {db: set() for db in databases + ["Total"]}

        # Extract names from features
        featureNames = set(map(attrgetter('name'), featureList))
        # Batch size sets how often this worker can report: a completed lookup is
        # the ONLY observable event inside it, since ~98% of its runtime is these
        # MongoDB round trips and the per-feature loop below is ~2%. Measured on
        # Drago over disjoint cold slices: 2000 -> 3 anchors/5.99s, 500 -> 6
        # anchors/5.69s, 250 -> 12 anchors/5.94s (-0.9%), 100 -> 30 anchors/+2.1%.
        # 250 buys 4x the resolution for no measurable time, and a bigger $in list
        # is not cheaper. Rate measured over the first half of the anchors predicts
        # the phase total to within ~5%.
        featureNamesBatches = chunks(list(featureNames), 250)
        totalBatches = len(featureNamesBatches) * max(1, len(databases))
        doneBatches = 0

        # Cache all database results upfront
        allCacheFeatureIDS = {}
        allCacheSymbolsIDS = {}

        for databaseConvertion_name in databases:
            # Reset the cache per database
            # TODO: cache para distintas omicas
            cacheFeatureIDS = {}
            cacheSymbolsIDS = {}

            databaseConvertion_id = databaseConvertion_ids.get(databaseConvertion_name)
            databaseGeneSymbol_id = databaseGeneSymbol_ids.get(databaseConvertion_name)

            # Check if ID and symbol databases are the same to avoid duplicate queries
            # This happens with Reactome where both map to 'reactome_gene_id'
            sameDatabase = (gene_databases.get(databaseConvertion_name) ==
                          symbol_databases.get(databaseConvertion_name))

            # Populate the feature and symbol cache
            for featureNameBatch in featureNamesBatches:
                newFeatureIDs = findIDsByFeaturesName(jobID, featureNameBatch, db, databaseConvertion_id)
                cacheFeatureIDS.update(newFeatureIDs)

                # Only query for symbols if the database is different from the ID database
                # Otherwise, reuse the ID results as symbols
                if sameDatabase:
                    # Reuse the feature IDs as symbols (they're the same database)
                    newSymbolIDs = newFeatureIDs
                else:
                    # Query for symbols separately
                    newSymbolIDs = findIDsByFeaturesName(jobID, list(chain.from_iterable(newFeatureIDs.values())), db,
                                                         databaseGeneSymbol_id)

                cacheSymbolsIDS.update(newSymbolIDs)

                # One anchor per completed lookup. Reported as this worker's own
                # percentage rather than a raw count so the reader needs no
                # agreement on batch counts — workers get different numbers of
                # batches, and a percentage makes every slot commensurable.
                # A store into shared memory is ~20ns and cannot block; there is
                # no manager process to outlive the call.
                doneBatches += 1
                if progressArray is not None:
                    try:
                        progressArray[progressSlot] = min(100, int(100 * doneBatches / totalBatches))
                    except Exception:
                        pass  # progress must never be able to fail a mapping

            allCacheFeatureIDS[databaseConvertion_name] = cacheFeatureIDS
            allCacheSymbolsIDS[databaseConvertion_name] = cacheSymbolsIDS

        # Now process all features once, checking all databases for each feature
        # Use a set to track which features matched in any database (O(1) lookups)
        localMatchedFeatures = set()

        for feature in featureList:
            originalName = feature.getName()
            featureMatchedInAnyDB = False
            # Track featureIDs already cloned for THIS feature across the database
            # loop. When two databases resolve the same input name to the same
            # featureID (e.g. ath: KEGG and MapMan both return AGI codes), cloning
            # twice would later collide in addInputGeneData and double every
            # OmicValue — Gene G1 ends up with [OV_R1, OV_R1, OV_R2, OV_R2] and
            # the pathway view shows each row twice. PathwayAcquisitionJob already
            # tags the merged gene with matchingDB=["KEGG","MapMan"] downstream,
            # so we keep the first DB on the clone and skip subsequent duplicates.
            seenIDs = set()

            # Check all databases for this feature
            for databaseConvertion_name in databases:
                cacheFeatureIDS = allCacheFeatureIDS[databaseConvertion_name]
                cacheSymbolsIDS = allCacheSymbolsIDS[databaseConvertion_name]
                featureIDs = cacheFeatureIDS.get(originalName, None)

                if featureIDs:
                    featureMatchedInAnyDB = True
                    # Increase the counter on the matching database, and keep track of the total
                    # counting only once the features. In this scenario the feature will only have one omic value
                    # containing the original name.
                    matches[databaseConvertion_name].add(
                        feature.getOmicsValues()[0].getOriginalName() if featureEnrichment else feature.getName())
                    matches["Total"].add(
                        feature.getOmicsValues()[0].getOriginalName() if featureEnrichment else feature.getName())

                    for featureID in set(featureIDs):
                        if featureID in seenIDs:
                            # Same featureID already cloned from a previous DB —
                            # cloning again would double OmicValues post-merge.
                            continue
                        seenIDs.add(featureID)

                        featureClone = feature.clone()  # IF MORE THAN 1 MATCH, CLONE THE FEATURE
                        featureClone.setID(featureID)

                        # TODO: check why this is not always applied as there are some features without matching DB
                        featureClone.setMatchingDB(databaseConvertion_name)

                        # For some IDs there might be more than one symbol, select the first
                        # one from the set. A cached entry can legitimately be an empty
                        # list (species installed with symbols=0), which indexed [0] and
                        # aborted the whole mapping.
                        cachedSymbols = cacheSymbolsIDS.get(featureID) or [featureClone.getName()]
                        featureName = cachedSymbols[0]

                        featureClone.setName(featureName)
                        matchedFeatures.append(featureClone)

            # Only add to notMatchedFeatures if it didn't match in ANY database
            if not featureMatchedInAnyDB:
                notMatchedFeatures.append(feature)
            else:
                # Track that this feature was matched (for deduplication if needed)
                localMatchedFeatures.add(originalName)

        #*************************************************************************************
        # STORE THE RESULTS
        #*************************************************************************************

        # If only one database was used for the species, remove the redundant "Total" counter
        if len(databaseConvertion_ids) < 2:
            matches.pop("Total", None)

        foundFeatures.append(matches)

        return matchedFeatures, notMatchedFeatures, foundFeatures

    except Exception as ex:
        raise ex
    finally:
        client.close()

def mapFeatureNamesToKeggIDs(jobID, organism, databases, featureList, enrichment, mapGeneIDs=True):
    """
    This function match the provided list of features
    to KEGG accepted feature ID (e.g. entrez gene ID for mmu)

    @param {String} organism, the organism code e.g. mmu
    @param {List} the list of features to be mapped
    @returns {Integer} foundFeatures, the number of matched features (no repetitions)
    @returns {List} matchedFeatures, the matched features
    @returns {List} notMatchedFeatures, the unmatched features
    """
    #TODO: USE mapGeneIDs

    #***********************************************************************************
    #* STEP 1. CALCULATE THE MAX NUMBER OF THREADS AND PREPARE DATA
    #***********************************************************************************
    # try:
    #     nThreads = min(cpu_count(), MAX_THREADS)        #NUMBER OF THREADS
    # except NotImplementedError as ex:
    #     nThreads = MAX_THREADS

    # Avoid unnecesary calculations when there are no features
    if len(featureList) < 1:
        logging.info("NO FEATURES GIVEN. SKIPPING MAPPING - JOB: " + str(jobID))
        return [dict.fromkeys(databases, 0), [], []]

    nThreads = MAX_THREADS

    logging.info("USING " + str(nThreads) + " THREADS")
    logging.info("INPUT " + str(len(featureList)) + " FEATURES")
    logging.info("ORGANISM " + organism)

    #GET THE NUMBER OF GENES TO BE PROCESSED PER THREAD
    nLinesPerThread = int(ceil(len(featureList)/nThreads)) + 1
    #SPLIT THE ARRAY IN n PARTS
    genesListParts = chunks(featureList, nLinesPerThread)


    #***********************************************************************************
    #matchedFeatures = list()
    #notMatchedFeatures = list()
    #foundFeatures = list()
    #***********************************************************************************


    manager=Manager()
    #CONCATENATE THE OUTPUT LISTS
    matchedFeatures = manager.list()
    notMatchedFeatures= manager.list()
    foundFeatures = manager.list()

    #***********************************************************************************
    #* STEP 2. START THE MAPPING USING N DIFFERENT THREADS IN PARALLEL
    #***********************************************************************************
    # Shared-memory progress slots, one per worker, allocated BEFORE the fork so
    # every child inherits the same mapping. Deliberately NOT a Manager list: the
    # `manager` above is a local created per call, so a proxy held for the status
    # endpoint would point at a dead process between omics and raise inside the
    # request handler. A RawArray has no server process, and reading it is a
    # memory load that cannot block or raise.
    progressArray = RawArray('i', len(genesListParts))
    JobProgress.attachAnchors(jobID, progressArray, perWorker=100)

    try:
        #matchedFeatures, notMatchedFeatures, foundFeatures = mapFeatureIdentifiers(jobID, organism, databases, featureList, matchedFeatures, notMatchedFeatures, foundFeatures, enrichment)
        threadsList = []
        i=0
        for genesListPart in genesListParts:
            thread = Process(target=mapFeatureIdentifiers, args=(jobID, organism, databases, genesListPart, matchedFeatures, notMatchedFeatures, foundFeatures, enrichment, progressArray, i))
            threadsList.append(thread)
            thread.start()
            i+=1

        #WAIT UNTIL ALL THREADS FINISHED (one shared budget, not one per thread)
        _joinAllWithinDeadline(threadsList, MAX_WAIT_THREADS)

        isFinished = True
        for thread in threadsList:
            if thread.is_alive():
                # TODO: possible deadlock with KeggInformationManager lock? Raise an exception to force the release there?
                isFinished = False
                thread.terminate()
                logging.info("THREAD TERMINATED IN mapFeatureNamesToKeggIDs")

        if not isFinished:
            raise Exception('Your data took too long to process and it was killed. Try it again later or upload smaller files if it persists.')


    except Exception as ex:
        manager.shutdown()
        raise ex

    #***********************************************************************************
    #* STEP 3. COMBINE THE RESULTS FOR ALL THE THREADS
    #***********************************************************************************
    # A child that DIED (unhandled exception, OOM kill) is not alive at join time,
    # so the liveness check above passes and its results are simply absent. Reading
    # foundFeatures[0] then silently returns a mapping built from a subset of the
    # input, and _matched.txt is written short — wrong results reported as success.
    # Every child appends exactly once, so a short list means a child was lost.
    if len(foundFeatures) != len(threadsList):
        manager.shutdown()
        raise Exception(
            "Identifier mapping lost %d of %d worker processes. This is usually "
            "memory pressure on the server; please try again, and upload smaller "
            "files if it persists."
            % (len(threadsList) - len(foundFeatures), len(threadsList)))

    #COMBINE DICTIONARIES
    sumFoundFeatures = dict.fromkeys(foundFeatures[0].keys())
    for dbname in sumFoundFeatures.keys():
        sumFoundFeatures[dbname] = len(set(itertools.chain.from_iterable(dbmatches[dbname] for dbmatches in foundFeatures)))

    #***********************************************************************************
    #* STEP 4. RETURN THE RESULTS
    #***********************************************************************************
    logging.info("FINISHED. %s uniquely matched features, %d features matched. %d features not matched.",
                 next(iter(sumFoundFeatures.values()), 0), len(matchedFeatures), len(notMatchedFeatures))

    # Materialise the proxies with ONE round trip each before returning them.
    # BaseListProxy exposes __getitem__/__len__ but not __iter__, so a caller's
    # `for x in matchedFeatures` falls back to the sequence protocol and pays an
    # IPC round trip per element — measured at 92us x 39,527 elements = 6.9s of an
    # 83s job. A slice is a single __getitem__ call carrying the whole list, 10x
    # faster in-container. `list(proxy)` does NOT help: it iterates the same way.
    matchedFeatures, notMatchedFeatures = matchedFeatures[:], notMatchedFeatures[:]
    # The Manager server is a forked process holding a copy of everything the
    # workers sent it; release it now rather than when the GC gets round to it.
    manager.shutdown()
    return sumFoundFeatures, matchedFeatures, notMatchedFeatures

# *****************************************************************
#    _____ ____  __  __ _____   ____  _    _ _   _ _____   _____
#   / ____/ __ \|  \/  |  __ \ / __ \| |  | | \ | |  __ \ / ____|
#  | |   | |  | | \  / | |__) | |  | | |  | |  \| | |  | | (___
#  | |   | |  | | |\/| |  ___/| |  | | |  | | . ` | |  | |\___ \
#  | |___| |__| | |  | | |    | |__| | |__| | |\  | |__| |____) |
#   \_____\____/|_|  |_|_|     \____/ \____/|_| \_|_____/|_____/
#
# *****************************************************************
# Upper bound on the compound-name candidates one input name may produce.
# The lookup is a case-insensitive SUBSTRING match, so a generic name matches a
# lot: on the 99k-name kegg_compounds collection "glucose" hits 198, "acid"
# 2,648, "a" 26,711 and "-" 19,778. Every hit is a cloned Feature pushed
# through a Manager pipe, so an unbounded match is a memory bill paid per
# input row. A name over the cap is treated as too generic to be a substring
# query and only its exact-name hits are kept.
MAX_COMPOUND_MATCHES = int(os.getenv("PAINTOMICS_MAX_COMPOUND_MATCHES", "500"))


def isPlaceholderCompoundName(featureName):
    """
    True when ``featureName`` cannot identify anything: empty, or made only of
    punctuation such as ``-``, ``.``, ``?`` or ``N/A``-style dashes that
    spreadsheets and pipelines leave in place of a missing identifier.

    Why this matters: on 2026-08-17 a metabolomics upload on paintomics.uv.es
    carried 1,172 rows whose identifier column was ``-``. Each became the
    regex ``.*-.*``, matched the 19,778 KEGG compound names containing a
    hyphen, and cloned the input feature once per hit -- 23 million Feature
    objects into a Manager process that reached 3.8 GB, filled the 8 GB
    machine plus its 4 GB of swap, and left every other job on the server
    (including unrelated gene-expression mappings) crawling in swap for
    26 minutes until the processes were killed by hand.
    """
    return not any(ch.isalnum() for ch in (featureName or ""))


def findCompoundIDByFeatureName(jobID, featureName, db):
    """
    This function queries the MongoDB looking for the KEGG compounds whose name
    contains the given feature name (case-insensitive).

    @param {String} jobID, the identifier for the running job, necessary to for the temporal caches
    @param {String} featureName, the name for the feature that we want to map
    @param  {pymongo.Database} db, the open connection with MongoDB database
    @returns {List} matchedFeatures, a list of translated identifiers
    @returns {Boolean} found, True if we found at least one translation
    """
    #Check if the id is ath the cache of translation
    # TODO: change "KEGG" for the proper database or leave it as it is?
    # featureIDs = KeggInformationManager().findInTranslationCache(jobID, featureName, "compound")
    # if(featureIDs != None):
    #     return featureIDs, True

    matchedFeatures=[]
    name = (featureName or "").strip()
    if isPlaceholderCompoundName(name):
        return matchedFeatures, False
    try:
        # The name is data, not a pattern: escape it. Unescaped, "NAD+" read as
        # "NA" then one or more "D", "(R)-lactate" as a group that never
        # matches its own parentheses, and a lone "." as any compound at all.
        # $regex is a substring search already, so no ".*" padding is needed.
        pattern = compile_re(re.escape(name), IGNORECASE_re)
        cursor = db.kegg_compounds.find({"name": {"$regex": pattern}}).limit(MAX_COMPOUND_MATCHES + 1)
        # See findIDsByFeatureName: Cursor.count() is gone in pymongo 4 and the
        # surrounding except would have hidden the failure entirely.
        for item in cursor:
            matchedFeatures.append(item)

        if len(matchedFeatures) > MAX_COMPOUND_MATCHES:
            # Too generic for a substring query; keep exact-name hits only.
            exact = compile_re("^" + re.escape(name) + "$", IGNORECASE_re)
            matchedFeatures = list(db.kegg_compounds.find({"name": {"$regex": exact}}).limit(MAX_COMPOUND_MATCHES))
            logging.warning("COMPOUND NAME %r MATCHES MORE THAN %d KEGG NAMES; KEEPING %d EXACT MATCH(ES) ONLY (JOB %s)",
                            name, MAX_COMPOUND_MATCHES, len(matchedFeatures), jobID)

        return matchedFeatures, len(matchedFeatures) > 0
    except Exception as ex:
        return matchedFeatures, False

def mapCompoundsIdentifiers(jobID, featureList, matchedFeatures, notMatchedFeatures, foundFeatures):
    """
    This function is used to query the database in different threads.

    @param  {List}   featureList, the list of feature IDs to map
    @param  {List}   matchedFeatures, a list shared between threads where we store the matched features
    @param  {List}   notMatchedFeatures, a list shared between threads where we store the unmatched features
    @param  {List}   foundFeatures,
    @param  {matchedGeneIDsTablesList}   foundFeatures,
    @returns True
    """


    #***********************************************************************************
    #* STEP 2. GET THE CORRESPONDING DATABASE FOR CURRENT SPECIE
    #***********************************************************************************
    client, db  = getConnectionByOrganismCode("global")

    try:
        matches=0
        # matchedCompoundIDsTable={}
        for feature in featureList:
            if feature.getName() != "" and feature.getName()!= None:
                matchedCompounds, found = findCompoundIDByFeatureName(jobID, feature.getName(), db)

                if(found == True):
                    matches+=1 #computes the total unique matching
                    oldName = feature.getName()
                    # matchedCompoundIDsTable[oldName] = matchedCompounds
                    # matchedElement = {"title" : oldName, "mainCompounds" : [], "otherCompounds" : []}
                    matchedElement = FoundFeature("")
                    matchedElement.setTitle(oldName)

                    for matchedCompound in matchedCompounds:
                        feature = feature.clone() #IF MORE THAN 1 MATCH, CLONE THE FEATURE
                        feature.setID(matchedCompound.get("id"))
                        feature.setName(matchedCompound.get("name"))
                        feature.getOmicsValues()[0].setInputName(matchedCompound.get("name"))

                        if feature.calculateSimilarity(oldName) >=  0.9:
                            # matchedElement["mainCompounds"].append(feature)
                            matchedElement.addMainCompound(feature)
                        else:
                            feature.getOmicsValues()[0].setOriginalName(oldName)
                            # matchedElement["otherCompounds"].append(feature)
                            matchedElement.addOtherCompound(feature)

                    #Remove some special cases of repeated features
                    # 1.  Find all repeated features
                    repeatedFeatures = {}
                    for i in range(len(matchedElement.getMainCompounds())):
                        feature = matchedElement.getMainCompounds()[i]
                        if feature.getID() not in repeatedFeatures:
                            repeatedFeatures[feature.getID()] = ([],[])
                        repeatedFeatures[feature.getID()][0].append(i)
                    for i in range(len(matchedElement.getOtherCompounds())):
                        feature = matchedElement.getOtherCompounds()[i]
                        if feature.getID() not in repeatedFeatures:
                            repeatedFeatures[feature.getID()] = ([],[])
                        repeatedFeatures[feature.getID()][1].append(i)

                    # 2.  For each repeated features check if name is the same than the input and remove
                    #     e.g. Leucine is repeated as "Leucine" and as "Leucine" but refering "L-Leucine"
                    toRemove = ([],[])
                    for indexes in repeatedFeatures.values():
                        #Take the first feature
                        if len(indexes[0]) > 1:
                            mainFeature = matchedElement.getMainCompounds()[indexes[0][0]]
                            del indexes[0][0]
                        elif len(indexes[1]) > 1:
                            mainFeature = matchedElement.getOtherCompounds()[indexes[1][0]]
                            del indexes[1][0]
                        else:
                            continue

                        #Combine the name for the remaining features
                        for i in indexes[0]:
                            mainFeature.setName(mainFeature.getName() + ", " + matchedElement.getMainCompounds()[i].getName())
                            toRemove[0].append(i)
                        for i in indexes[1]:
                            mainFeature.setName(mainFeature.getName() + ", " + matchedElement.getOtherCompounds()[i].getName())
                            toRemove[1].append(i)

                    #Delete invalid features
                    for i in sorted(toRemove[0], reverse=True): #looping in reverse order avoid "index out of range" errors (we are removing items from the array)
                        del matchedElement.getMainCompounds()[i]
                    for i in sorted(toRemove[1], reverse=True):
                        del matchedElement.getOtherCompounds()[i]

                    #Add the CompoundSet to the list
                    matchedFeatures.append(matchedElement)
                else:
                    notMatchedFeatures.append(feature)

        #*************************************************************************************
        # STORE THE RESULTS
        #*************************************************************************************
        foundFeatures.append(matches)
        # matchedCompoundIDsTablesList.append(matchedCompoundIDsTable)

        return True

    except Exception as ex:
        raise ex
    finally:
        client.close()

def mapFeatureNamesToCompoundsIDs(jobID, featureList):
    """
    This function match the provided list of features
    to KEGG accepted compounds ID

    @param {String} organism, the organism code e.g. mmu
    @param {List} the list of features to be mapped
    @returns {Integer} foundFeatures, the number of matched features (no repetitions)
    @returns {List} matchedFeatures, the matched features
    @returns {List} notMatchedFeatures, the unmatched features
    """

    #***********************************************************************************
    #* STEP 1. CALCULATE THE MAX NUMBER OF THREADS AND PREPARE DATA
    #***********************************************************************************
    # try:
    #     nThreads = min(cpu_count(), MAX_THREADS)        #NUMBER OF THREADS
    # except NotImplementedError as ex:
    #     nThreads = MAX_THREADS
    nThreads = MAX_THREADS

    logging.info("USING " + str(nThreads) + " THREADS")
    logging.info("INPUT " + str(len(featureList)) + " FEATURES")

    #GET THE NUMBER OF GENES TO BE PROCESSED PER THREAD
    nLinesPerThread = int(ceil(len(featureList)/nThreads)) + 1
    #SPLIT THE ARRAY IN n PARTS
    compoundsListParts = chunks(featureList, nLinesPerThread)

    manager=Manager()

    #CONCATENATE THE OUTPUT LISTS

    matchedFeatures = manager.list()
    notMatchedFeatures= manager.list()
    foundFeatures= manager.list([0]*nThreads)

    #matchedFeatures = list()
    #notMatchedFeatures = list()
    #foundFeatures = list()
    #for compoundListPart in compoundsListParts:
    #   mapCompoundsIdentifiers(jobID, compoundListPart, matchedFeatures, notMatchedFeatures, foundFeatures)

    # matchedCompoundIDsTablesList=manager.list() #STORES THE MAPPING RESULTS TO UPDATE LATER THE CACHE

    #***********************************************************************************
    #* STEP 2. START THE MAPPING USING N DIFFERENT THREADS IN PARALLEL
    #***********************************************************************************
    try:
        threadsList = []
        i=0
        for compoundListPart in compoundsListParts:
            thread = Process(target=mapCompoundsIdentifiers, args=(jobID, compoundListPart, matchedFeatures, notMatchedFeatures, foundFeatures))
            threadsList.append(thread)
            thread.start()
            i+=1

        #WAIT UNTIL ALL THREADS FINISHED (one shared budget, not one per thread)
        _joinAllWithinDeadline(threadsList, MAX_WAIT_THREADS)

        isFinished = True
        for thread in threadsList:
            if(thread.is_alive()):
                isFinished = False
                thread.terminate()
                logging.info("THREAD TERMINATED IN mapFeatureNamesToCompoundsIDs")

        if not isFinished:
            raise Exception('Your data took too long to process and it was killed. Try it again later or upload smaller files if it persists.')

    except Exception as ex:
        manager.shutdown()
        raise ex

    #***********************************************************************************
    #* STEP 3. COMBINE THE RESULTS FOR ALL THE THREADS
    #***********************************************************************************
    #COMBINE DICTIONARIES
    # for matchedCompoundIDsTable in matchedCompoundIDsTablesList:
    #     KeggInformationManager().updateTranslationCache(jobID, matchedCompoundIDsTable, "compound")

    foundFeatures = sum(foundFeatures)

    #***********************************************************************************
    #* STEP 4. RETURN THE RESULTS
    #***********************************************************************************
    logging.info("FINISHED. " + str(foundFeatures) + " uniquely matched compounds, " +  str(len(matchedFeatures)) + " compounds matched. " + str(len(notMatchedFeatures)) + " compounds not matched.")

    # One round trip each instead of one per element — see the note on the same
    # return in mapFeatureNamesToKeggIDs. Compound lists are short today (58 in the
    # bundled example), so this is correctness-by-consistency rather than a win.
    matchedFeatures, notMatchedFeatures = matchedFeatures[:], notMatchedFeatures[:]
    manager.shutdown()
    return foundFeatures, matchedFeatures, notMatchedFeatures
