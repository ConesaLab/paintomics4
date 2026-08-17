from .DAO import DAO
from .GraphicalDataDAO import GraphicalDataDAO
from src.classes.Pathway import Pathway

class PathwayDAO(DAO):
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, *args, **kwargs):
        super(PathwayDAO, self).__init__(*args, **kwargs)
        self.collectionName = "pathwaysCollection"

    #******************************************************************************************************************
    # GETTERS AND SETTER
    #******************************************************************************************************************
    def findAll(self, otherParams=None):
        matchedPathways = []
        queryParams={}

        if(otherParams != None and "jobID" in otherParams):
            queryParams["jobID"] = otherParams["jobID"]

        loadGraphicalData = False
        graphicalDataDAO = None
        if("loadGraphicalData" in otherParams and otherParams["loadGraphicalData"] == True ):
            loadGraphicalData = True
            graphicalDataDAO = GraphicalDataDAO(dbManager=self.dbManager)

        collection = self.dbManager.getCollection(self.collectionName)

        match = collection.find(queryParams)
        if(match != None):
            matchedPathways = []
            for instance in match:
                instance = self.adaptBSON(instance)
                pathwayInstance = Pathway("")
                pathwayInstance.parseBSON(instance)

                if(loadGraphicalData == True):
                    pathwayInstance.setGraphicalOptions(graphicalDataDAO.findByID(pathwayInstance.getID(), queryParams))

                matchedPathways.append(pathwayInstance)

        return matchedPathways

    def insert(self, instance, otherParams=None):
        pathwayInstance = instance
        jobID= otherParams["jobID"]

        collection = self.dbManager.getCollection(self.collectionName)

        instanceBSON = pathwayInstance.toBSON()
        instanceBSON["jobID"] = jobID

        collection.insert_one(instanceBSON)
        return True

    def insertAll(self, instancesList, otherParams=None):
        saveGraphicalData = False
        if(otherParams != None and "saveGraphicalData" in otherParams and otherParams["saveGraphicalData"] == True ):
            saveGraphicalData = True
            graphicalDataDAO = GraphicalDataDAO(dbManager=self.dbManager)

        if(saveGraphicalData == True):
            # Unchanged: the graphical-data write is interleaved per pathway and
            # reads otherParams["pathwayID"] as it goes, so this branch keeps
            # its original one-round-trip-per-pathway shape.
            for instance in instancesList:
                self.insert(instance, otherParams)
                otherParams["pathwayID"] = instance.getID()
                graphicalDataDAO.insert(instance.getGraphicalOptions(), otherParams)
            return True

        # One insert_many instead of one insert_one per pathway. A job stores
        # 300-2000 pathways (plus the matched Reactome classes, which arrive
        # through this same call), so this was 300-2000 sequential round trips
        # inside step 2's store phase. FeatureDAO.insertAll has always batched;
        # this mirrors it exactly.
        #
        # The documents are built the way insert() builds them -- toBSON() then
        # the jobID tag -- in the order the caller passed them, and
        # insert_many(ordered=True) writes them in that order, so the stored
        # documents and their natural order are identical.
        instanceBSONList = [pathwayInstance.toBSON() for pathwayInstance in instancesList]

        if not instanceBSONList:
            # An empty list touches neither otherParams nor the collection --
            # the old loop never entered its body, so insertAll([], None) has
            # to keep returning True rather than raising on otherParams["jobID"].
            return True

        jobID = otherParams["jobID"]
        for instanceBSON in instanceBSONList:
            instanceBSON["jobID"] = jobID

        collection = self.dbManager.getCollection(self.collectionName)
        collection.insert_many(instanceBSONList, ordered=True)

        return True

    def update(self, instance, otherParams=None):
        pathwayInstance = instance
        jobID= otherParams["jobID"]

        collection = self.dbManager.getCollection(self.collectionName)

        instanceBSON = pathwayInstance.toBSON()
        instanceBSON["jobID"] = jobID

        # replace_one(upsert=True), not update-then-insert: the old pair left a
        # duplicate behind whenever the pathway already existed, because update()
        # replaced it and insert() then added a second copy.
        collection.replace_one({"jobID": jobID, "ID": pathwayInstance.getID()},
                               instanceBSON, upsert=True)
        return True

    def updateAll(self, instancesList, otherParams=None):
        for instance in instancesList:
            self.update(instance, otherParams)
        return True

    def removeAll(self, otherParams=None):
        queryParams={}
        if(otherParams != None and "jobID" in otherParams):
            queryParams["jobID"] = otherParams["jobID"]

        collection = self.dbManager.getCollection(self.collectionName)
        collection.delete_many(queryParams)

        return True
