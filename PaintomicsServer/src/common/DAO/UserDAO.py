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
#  Technical contact paintomics4@gmail.com
#**************************************************************

import logging

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .DAO import DAO
from src.classes.User import User
from src.common.ServerErrorManager import CredentialException

class UserDAO(DAO):
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, *args, **kwargs):
        super(UserDAO, self).__init__(*args, **kwargs)
        self.collectionName = "userCollection"

    #******************************************************************************************************************
    # GETTERS AND SETTER
    #******************************************************************************************************************
    def findByID(self, userID, otherParams=None):
        """The user with this ID, or None. Refuses if more than one has it.

        This used `find_one`, which returns whichever document Mongo reaches
        first. With two accounts on the same userID the caller got one of them
        arbitrarily and had no way to tell.

        `getNextUserID` used to return `len(userCollection)`, so deleting a user
        made the next signup collide with a live ID. That allocator is now an
        atomic counter and issues no new duplicates, but it cannot undo the ones
        already in a deployment's database.

        What the arbitrary pick cost, measured against a running server: an
        account on a duplicated ID changed its password, the reply said
        `success: true`, its own password was unchanged, and the *other*
        account's password was set to the value it had chosen. The same lookup
        backs `isValidAdminUser`, where picking the wrong document decides an
        administrator check.

        `find_one` cannot express "there should be exactly one", so this reads
        two and refuses if it gets them. The database is then in a state the
        code has no rule for, and acting on an arbitrary candidate is the worst
        of the available answers. All three callers already sit inside a
        handleException, so the refusal reaches the user as an error instead of
        as someone else's account.

        A unique index on userID is the structural fix; it cannot be built while
        duplicates exist, and repairing user rows is an operator's decision.
        """
        queryParams={"userID" : int(userID)}

        if(otherParams != None and "password" in otherParams):
            queryParams["password"] = otherParams["password"]

        collection = self.dbManager.getCollection(self.collectionName)

        candidates = list(collection.find(queryParams).limit(2))
        if len(candidates) > 1:
            raise CredentialException(
                "[b]Account lookup is ambiguous[/b]. More than one account is "
                "stored with user ID %s, so PaintOmics cannot tell which one "
                "this request belongs to. Please contact the administrator: "
                "the duplicate accounts have to be resolved before this ID can "
                "be used." % (int(userID),))

        match = candidates[0] if candidates else None
        if(match != None):
            match = self.adaptBSON(match)
            userInstance = User(userID)
            userInstance.parseBSON(match)
            return userInstance
        return None

    def findByEmail(self, email, otherParams=None):
        queryParams={"email" : email}

        if otherParams is not None and "password" in otherParams:
            queryParams["password"] = otherParams["password"]

        collection = self.dbManager.getCollection(self.collectionName)

        match = collection.find_one(queryParams)
        if match is not None:
            match = self.adaptBSON(match)
            userInstance = User("")
            userInstance.parseBSON(match)
            return userInstance
        return None

    def findAll(self,otherParams=None):
        queryParams={}
        matchedUsers = []
        # if(otherParams != None and otherParams.has_key("omicType")):
        #     queryParams["omicType"] = otherParams["omicType"]

        collection = self.dbManager.getCollection(self.collectionName)

        match = collection.find(queryParams)
        if(match != None):
            userInstance = None
            for instance in match:
                instance = self.adaptBSON(instance)
                userInstance = User("")
                userInstance.parseBSON(instance)
                matchedUsers.append(userInstance)
            return matchedUsers
        return None

    def insert(self, instance, otherParams=None):
        userInstance = instance
        collection = self.dbManager.getCollection(self.collectionName)

        instanceBSON = userInstance.toBSON()
        #GET THE NEXT USER ID
        userID = self.getNextUserID()
        instanceBSON["userID"] = userID
        collection.insert_one(instanceBSON)
        return userID

    def update(self, instance, otherParams=None):
        userInstance=instance
        collection = self.dbManager.getCollection(self.collectionName)
        instanceBSON = userInstance.toBSON()

        if(otherParams.get("fieldList", None) != None):
            setFields = {}
            for i in otherParams.get("fieldList"):
                setFields[i] = instanceBSON.get(i)

            collection.update_one({"userID" :userInstance.getUserId()}, {'$set': setFields})
            return True


        collection.replace_one({"userID" :userInstance.getUserId()}, instanceBSON)

        return True

    def remove(self, id, otherParams=None):
        userID = id
        collection = self.dbManager.getCollection(self.collectionName)
        collection.delete_many({"userID" : userID})

        return True

    def getNextUserID(self):
        """Allocate a user ID from an atomic counter.

        This used to return len(userCollection), which was wrong twice over.

        The first person to register got userID 0, and isValidUser accepted
        "0" with any session token -- so that account was usable by anyone who
        sent the cookie. The counter therefore starts at 1 and never issues 0.

        And because a count is not a sequence, IDs were reused: with users
        0,1,2 present, deleting user 1 left a count of 2, so the next signup
        was handed ID 2 and collided with the existing account -- two users
        sharing an identity, and one inheriting the other's jobs and files.
        $inc on a counter document is atomic, so an ID is never handed out
        twice regardless of concurrent signups.

        The counter is seeded above the highest ID already in the collection,
        so an existing deployment keeps working without a migration.
        """
        counters = self.dbManager.getCollection("counters")

        if counters.find_one({"_id": "userID"}) is None:
            highestExisting = 0
            for document in self.dbManager.getCollection(self.collectionName).find({}, {"userID": 1}):
                try:
                    highestExisting = max(highestExisting, int(document.get("userID")))
                except (TypeError, ValueError):
                    continue  # malformed or missing userID: cannot raise the floor
            try:
                counters.insert_one({"_id": "userID", "sequence_value": highestExisting})
            except DuplicateKeyError:
                pass  # another request seeded it first; its value is equally valid

        # Seeding happens once, and that is the gap: if the counter ever sits
        # *below* the collection -- seeded while it held fewer users, rows
        # restored over it, a database copied in -- $inc keeps handing out IDs
        # that already belong to somebody, and nothing notices, because the
        # index on userID is not unique so insert_one writes the duplicate
        # happily.
        #
        # Found live rather than theorised: the counter read sequence_value 4
        # while accounts existed at IDs 1-5, so a new signup was issued 4 and
        # collided. Three IDs ended up shared by two accounts each. What a
        # shared ID costs is in findByID above -- an arbitrary pick between the
        # two, so changing your password changed someone else's.
        #
        # The counter stays the fast path; the result is checked against the
        # collection and stepped past if taken. Bounded, because a collection
        # pathological enough to exhaust this is a problem to report rather
        # than to spin on.
        users = self.dbManager.getCollection(self.collectionName)

        for _attempt in range(1000):
            document = counters.find_one_and_update(
                {"_id": "userID"},
                {"$inc": {"sequence_value": 1}},
                return_document=ReturnDocument.AFTER
            )
            candidate = int(document["sequence_value"])

            if users.count_documents({"userID": candidate}) == 0:
                return candidate

            logging.warning(
                "User ID counter is behind the collection: %s is already taken, "
                "skipping it. The counter was seeded before these accounts "
                "existed.", candidate)

        raise Exception(
            "Could not allocate a free user ID after 1000 attempts. The user ID "
            "counter is far behind the accounts collection; it needs to be "
            "reset above the highest existing userID.")
