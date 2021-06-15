from src.common.DAO.DAO import DAO
from src.classes.Job import Job

from src.common.DAO.Bed2GeneJobDAO import Bed2GeneJobDAO
from src.common.DAO.PathwayAcquisitionJobDAO import PathwayAcquisitionJobDAO

class JobDAO(DAO):
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, *args, **kwargs):
        super(JobDAO, self).__init__(*args, **kwargs)
        self.collectionName = "jobInstanceCollection"

    #******************************************************************************************************************
    # GETTERS AND SETTER
    #******************************************************************************************************************
    def findAll(self, otherParams=None):
        #TODO: USE INDEXES
        matchedJobs = []
        queryParams={}

        if("userID" in otherParams):
            queryParams["userID"] = otherParams["userID"]
        if("jobType" in otherParams):
            queryParams["jobType"] = otherParams["jobType"]

        collection = self.dbManager.getCollection(self.collectionName)
        match = collection.find(queryParams)

        if(match != None):
            jobInstance = None
            for instance in match:
                instance = self.adaptBSON(instance)
                jobInstance = Job("","","")
                jobInstance.parseBSON(instance)
                matchedJobs.append(jobInstance)

        return matchedJobs


    #******************************************************************************************************************
    # DELETE INSTANCES
    #******************************************************************************************************************
    def remove(self, id, otherParams=None):
        if(otherParams == None or not "userID" in otherParams):
            return False
        daoInstance = None
        jobType = otherParams.get("jobType")

        if jobType == "Bed2GeneJob":
            daoInstance = Bed2GeneJobDAO()
        else:
            daoInstance = PathwayAcquisitionJobDAO()

        daoInstance.remove(id, otherParams)
        daoInstance.closeConnection()

        return True