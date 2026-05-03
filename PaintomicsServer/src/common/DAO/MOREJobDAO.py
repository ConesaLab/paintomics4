#***************************************************************
#  This file is part of Paintomics v4
#**************************************************************

from src.common.DAO.JobDAO import JobDAO
from src.classes.JobInstances.MOREJob import MOREJob

class MOREJobDAO(JobDAO):
    """
    DAO for the MOREJob class. 
    Handles persistence of MORE analysis jobs in MongoDB.
    """
    def __init__(self, *args, **kwargs):
        super(MOREJobDAO, self).__init__(*args, **kwargs)
        self.clazz = MOREJob

    def insert(self, instance, otherParams=None):
        collection = self.dbManager.getCollection(self.collectionName)
        instanceBSON = instance.toBSON(recursive=False)
        instanceBSON["jobType"] = "MOREJob"
        collection.insert(instanceBSON)
        return True

    def findByID(self, id, otherParams=None):
        collection = self.dbManager.getCollection(self.collectionName)
        match = collection.find_one({"jobID": id})
        if match is not None:
            match = self.adaptBSON(match)
            from src.conf.serverconf import CLIENT_TMP_DIR
            jobInstance = MOREJob(id, match.get("userID", ""), CLIENT_TMP_DIR)
            jobInstance.parseBSON(match)
            return jobInstance
        return None

    def update(self, instance, otherParams=None):
        collection = self.dbManager.getCollection(self.collectionName)
        instanceBSON = instance.toBSON(recursive=False)
        collection.update({"jobID": instance.getJobID()}, instanceBSON)
        return True

    def remove(self, id, otherParams=None):
        collection = self.dbManager.getCollection(self.collectionName)
        if otherParams and "userID" in otherParams:
            collection.remove({"jobID": id, "userID": otherParams.get("userID")})
        else:
            collection.remove({"jobID": id})
        return True
