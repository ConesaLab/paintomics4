from pymongo import MongoClient
import logging, itertools
from multiprocessing import Process, cpu_count, Manager
from math import ceil
from re import compile as compile_re, IGNORECASE as IGNORECASE_re
from collections import defaultdict
from operator import attrgetter
from itertools import chain

from src.common.Util import chunks
from src.common.KeggInformationManager import KeggInformationManager

from src.classes.FoundFeature import FoundFeature

from src.conf.organismDB import dicDatabases
from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT, MAX_THREADS, MAX_WAIT_THREADS #MULTITHREADING

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

        if(cursor.count() > 0):
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
        print("EXCEPTION " + str(ex))
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

# def mapFeatureIdentifiers(jobID, organism, databases, featureList, matchedFeatures, notMatchedFeatures, foundFeatures, enrichment):
def mapFeatureIdentifiers(jobID, organism, databases, featureList,  matchedFeatures, notMatchedFeatures, foundFeatures, enrichment):
    """
    This function is used to query the database in different threads.

    @param  {String} organism, the specie code
    @param  {List}   featureList, the list of feature IDs to map
    @param  {Dict}   alreadyMatchedGenesTable, a dict shared between threads where we store the matching for identifiers
                     (will be combined later with KeggInfoManager cache)
    @param  {List}   matchedFeatures, a list shared between threads where we store the matched features
    @param  {List}   notMatchedFeatures, a list shared between threads where we store the unmatched features

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

    try:
        # Save found features for each database, plus the unique between them
        matches = {db: set() for db in databases + ["Total"]}

        # Extract names from features
        featureNames = set(map(attrgetter('name'), featureList))
        featureNamesBatches = chunks(list(featureNames), 2000)


        for databaseConvertion_name in databases:
            # Reset the cache per database
            # TODO: cache para distintas omicas
            cacheFeatureIDS = {}
            cacheSymbolsIDS = {}

            databaseConvertion_id = databaseConvertion_ids.get(databaseConvertion_name)
            databaseGeneSymbol_id = databaseGeneSymbol_ids.get(databaseConvertion_name)

            # Populate the feature and symbol cache
            for featureNameBatch in featureNamesBatches:
                newFeatureIDs = findIDsByFeaturesName(jobID, featureNameBatch, db, databaseConvertion_id)
                newSymbolIDs = findIDsByFeaturesName(jobID, list(chain.from_iterable(newFeatureIDs.values())), db,
                                                     databaseGeneSymbol_id)

                cacheFeatureIDS.update(newFeatureIDs)
                cacheSymbolsIDS.update(newSymbolIDs)


            total = len(featureList)
            current = 0
            prev = -1
            aux = 0

            for feature in featureList:
                current += 1
                if (current * 100 / total) % 20 == 0:
                    aux = (current * 100 / total)
                    if aux != prev:
                        prev = aux
                        print( "Processed " + str(prev) + "% of " + str(total) + " total features (DB " + databaseConvertion_name + ")")

                originalName = feature.getName()
                featureIDs = cacheFeatureIDS.get(originalName, None)

                if (featureIDs):
                    # matches+=1
                    # Increase the counter on the matching database, and keep track of the total
                    # counting only once the features. In this scenario the feature will only have one omic value
                    # containing the original name.
                    matches[databaseConvertion_name].add(
                        feature.getOmicsValues()[0].getOriginalName() if featureEnrichment else feature.getName())
                    matches["Total"].add(
                        feature.getOmicsValues()[0].getOriginalName() if featureEnrichment else feature.getName())

                    # Remove the feature from not matched features in case in wasn't found in
                    # the previous database (when multiple databases are selected)
                    if feature in notMatchedFeatures:
                        notMatchedFeatures.remove(feature)

                    for featureID in featureIDs:
                        featureClone = feature.clone()  # IF MORE THAN 1 MATCH, CLONE THE FEATURE
                        featureClone.setID(featureID)

                        # TODO: check why this is not always applied as there are some features without matching DB
                        featureClone.setMatchingDB(databaseConvertion_name)

                        # For some IDs there might be more than one symbol, select the first one from the set
                        featureName = cacheSymbolsIDS.get(featureID, [featureClone.getName()])[0]

                        featureClone.setName(featureName)
                        matchedFeatures.append(featureClone)
                else:
                    notMatchedFeatures.append(feature)

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
    logging.info("USING " + str(nThreads) + " THREADS")

    #GET THE NUMBER OF GENES TO BE PROCESSED PER THREAD
    nLinesPerThread = int(ceil(len(featureList)/nThreads)) + 1
    #SPLIT THE ARRAY IN n PARTS
    genesListParts = chunks(featureList, nLinesPerThread)

    manager=Manager()

    #CONCATENATE THE OUTPUT LISTS
    matchedFeatures = manager.list()
    notMatchedFeatures= manager.list()
    foundFeatures = manager.list()

    #***********************************************************************************
    #* STEP 2. START THE MAPPING USING N DIFFERENT THREADS IN PARALLEL
    #***********************************************************************************
    try:
        # matchedFeatures, notMatchedFeatures, foundFeatures = mapFeatureIdentifiers(jobID, organism, databases, featureList, enrichment)
        threadsList = []
        i=0
        for genesListPart in genesListParts:
            thread = Process(target=mapFeatureIdentifiers, args=(jobID, organism, databases, genesListPart, matchedFeatures, notMatchedFeatures, foundFeatures, enrichment))
            threadsList.append(thread)
            thread.start()
            i+=1

        #WAIT UNTIL ALL THREADS FINISHED
        for thread in threadsList:
            thread.join(MAX_WAIT_THREADS)

        isFinished = True
        for thread in threadsList:
            if(thread.is_alive()):
                # TODO: possible deadlock with KeggInformationManager lock? Raise an exception to force the release there?
                isFinished = False
                thread.terminate()
                logging.info("THREAD TERMINATED IN mapFeatureNamesToKeggIDs")

        if not isFinished:
            raise Exception('Your data took too long to process and it was killed. Try it again later or upload smaller files if it persists.')


    except Exception as ex:
        raise ex

    #***********************************************************************************
    #* STEP 3. COMBINE THE RESULTS FOR ALL THE THREADS
    #***********************************************************************************
    #COMBINE DICTIONARIES
    sumFoundFeatures = dict.fromkeys(foundFeatures[0].keys())
    for dbname in sumFoundFeatures.keys():
        sumFoundFeatures[dbname] = len(set(itertools.chain.from_iterable(dbmatches[dbname] for dbmatches in foundFeatures)))

    #***********************************************************************************
    #* STEP 4. RETURN THE RESULTS
    #***********************************************************************************
    logging.info("FINISHED. " + str(sumFoundFeatures[list(sumFoundFeatures.keys())[0]]) + " uniquely matched features, " +  str(len(matchedFeatures)) + " features matched. " + str(len(notMatchedFeatures)) + " features not matched.")

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
def findCompoundIDByFeatureName(jobID, featureName, db):
    """
    This function queries the MongoDB looking for the associated gene ID for the given gene name

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
    try:
        cursor = db.kegg_compounds.find({"name": {"$regex" : compile_re(".*" + featureName +".*", IGNORECASE_re) }})
        if(cursor.count() > 0):
            for item in cursor:
                matchedFeatures.append(item)

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

        #WAIT UNTIL ALL THREADS FINISHED
        for thread in threadsList:
            thread.join(MAX_WAIT_THREADS)

        isFinished = True
        for thread in threadsList:
            if(thread.is_alive()):
                isFinished = False
                thread.terminate()
                logging.info("THREAD TERMINATED IN mapFeatureNamesToCompoundsIDs")

        if not isFinished:
            raise Exception('Your data took too long to process and it was killed. Try it again later or upload smaller files if it persists.')

    except Exception as ex:
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
    return foundFeatures, matchedFeatures, notMatchedFeatures
