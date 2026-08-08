#***************************************************************
#  This file is part of PaintOmics 3
#
#  PaintOmics 3 is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  PaintOmics 3 is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with PaintOmics 3.  If not, see <http://www.gnu.org/licenses/>.
#  Contributors:
#     Rafael Hernandez de Diego <paintomics4@gmail.com>
#     Ana Conesa Cegarra
#     and others
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomics4@gmail.com
#
#**************************************************************

from src.common.DAO.DAO import DAO

class Bed2GeneJobDAO(DAO):
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, *args, **kwargs):
        super(Bed2GeneJobDAO, self).__init__(*args, **kwargs)
        self.collectionName = "jobInstanceCollection"

    #******************************************************************************************************************
    # GETTERS AND SETTER
    #******************************************************************************************************************
    def insert(self, instance, otherParams=None):
        jobInstance=instance
        collection = self.dbManager.getCollection(self.collectionName)
        instanceBSON = jobInstance.toBSON(recursive= False)

        instanceBSON["jobType"] = "Bed2GeneJob"

        collection.insert_one(instanceBSON)

        return True

    #******************************************************************************************************************
    # DELETE INSTANCES
    #******************************************************************************************************************
    def remove(self, id, otherParams=None):
        if(otherParams == None or not "userID" in otherParams):
            return False
        collection = self.dbManager.getCollection(self.collectionName)

        # jobID, not jobId. Every document in jobInstanceCollection stores the
        # key as "jobID" -- these two DAOs never wrote a "jobId" and neither
        # does anything else, so this filter matched nothing and the delete
        # silently removed no rows while still returning True. Deleting a
        # Regions2Genes or miRNA2Genes job appeared to work and left it in the
        # database. Checked across the whole database before changing it: zero
        # documents in any collection have a "jobId" field.
        collection.delete_many({"jobID": id, "userID" : otherParams.get("userID")})

        return True
