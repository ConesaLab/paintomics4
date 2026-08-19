#***************************************************************
#  This file is part of Paintomics v3
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomicsai@gmail.com
#**************************************************************

from .DAO import DAO
from src.classes.Report import Report

class ReportDAO(DAO):
    """Durable storage for user-submitted reports.

    The report is written here *before* the mail provider is contacted, so a
    provider outage (bad credentials, exhausted quota, blocked egress) degrades
    delivery only -- it never loses the user's message.
    """
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, *args, **kwargs):
        super(ReportDAO, self).__init__(*args, **kwargs)
        self.collectionName = "reportCollection"

    #******************************************************************************************************************
    # GETTERS AND SETTER
    #******************************************************************************************************************
    def findAll(self, otherParams=None):
        queryParams = {}

        if otherParams != None and otherParams.get("report_type") != None:
            queryParams = {"report_type": otherParams.get("report_type")}

        collection = self.dbManager.getCollection(self.collectionName)

        # Newest first: the admin panel reads this top-down, and a report only
        # matters until it is acted on.
        matchedReports = []
        for instance in collection.find(queryParams).sort("_id", -1):
            instance = self.adaptBSON(instance)
            # Model.parseBSON pops _id, but the panel needs it to dismiss a
            # report, so keep it before it is discarded.
            reportID = instance.get("_id", "")
            reportInstance = Report("")
            reportInstance.parseBSON(instance)
            reportInstance.setReportID(reportID)
            matchedReports.append(reportInstance)
        return matchedReports

    def insert(self, instance, otherParams=None):
        collection = self.dbManager.getCollection(self.collectionName)
        instanceBSON = instance.toBSON()
        # insert_one stamps the generated _id onto the dict it is handed, which
        # is the instance's own __dict__ (Model.toBSON returns it, it does not
        # copy). Insert a shallow copy so the caller's Report keeps the plain
        # scalar fields it was built with and stays safe to serialise.
        instanceBSON = dict(instanceBSON)
        # report_id is a read-side convenience carrying Mongo's own _id back to
        # the admin panel; storing an empty copy of it would be noise.
        instanceBSON.pop("report_id", None)
        result = collection.insert_one(instanceBSON)
        return str(result.inserted_id)

    def remove(self, reportID, otherParams=None):
        """Dismiss one report once it has been acted on."""
        from bson.objectid import ObjectId

        collection = self.dbManager.getCollection(self.collectionName)
        result = collection.delete_one({"_id": ObjectId(reportID)})
        return result.deleted_count > 0

    def markDelivered(self, reportID, delivered, deliveryError="", otherParams=None):
        """Record the outcome of the delivery attempt for an already-stored report."""
        from bson.objectid import ObjectId

        collection = self.dbManager.getCollection(self.collectionName)
        collection.update_one(
            {"_id": ObjectId(reportID)},
            {"$set": {"delivered": bool(delivered), "delivery_error": deliveryError or ""}})
        return True
