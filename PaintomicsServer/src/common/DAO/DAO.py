from ..DBmanager import DBmanager
from src.common.Util import adapt_string

class DAO(object):
    def __init__(self, *args, **kwargs):
        self.dbManager = kwargs.get("dbManager", DBmanager())
        self.collectionName = ""

    def getDBManager(self):
        return self.dbManager

    def findByID(self, id, otherParams=None):
        raise NotImplementedError

    def findAll(self,otherParams=None):
        raise NotImplementedError

    def insert(self, instance, otherParams=None):
        raise NotImplementedError

    def insertAll(self, instancesList, otherParams=None):
        raise NotImplementedError

    def update(self, instance, otherParams=None):
        raise NotImplementedError

    def updateAll(self, instance, otherParams=None):
        raise NotImplementedError

    def remove(self, id, otherParams=None):
        raise NotImplementedError

    def removeAll(self, otherParams=None):
        raise NotImplementedError

    def closeConnection(self, otherParams=None):
        if(self.dbManager != None):
            self.dbManager.closeConnection()
        return True

    def adaptBSON(self, object, otherParams=None):
        # Fast path for the types pymongo actually decodes into, checked by
        # EXACT class rather than isinstance so it can never shadow a subclass
        # the slow path below would treat differently (bson.Int64, SON, ...).
        #
        # For an exact str/int/float/bool, the slow path's str(x)/int(x)/
        # float(x)/bool(x) returns the very object it was given, so returning
        # it here is not "close enough", it is the same result. dicts and
        # lists are still rebuilt (callers get a fresh container, as before)
        # but without a function call per leaf.
        #
        # This is a no-op transformation only for those types. Everything else
        # -- None -> "None", ObjectId -> its hex string, and any exotic leaf --
        # falls through to the original code untouched, because the callers
        # depend on it: adaptBSON(doc) != doc on EVERY document in this
        # database (_id is an ObjectId), and foundFeaturesCollection alone
        # holds ~193k None leaves that must keep becoming "None".
        #
        # Measured over the real local database (332,869 documents:
        # jobInstance 278, pathways 112,769, visualOptions 60, foundFeatures
        # 19,762, features 200,000 sampled of 2.85M): 0 mismatches against the
        # old implementation under a type-strict deep compare, and no leaf type
        # outside {str, int, float, bool, NoneType, ObjectId, dict, list} and
        # no non-str key anywhere.
        cls = object.__class__
        if cls is str or cls is int or cls is float or cls is bool:
            return object
        if cls is dict:
            adaptBSON = self.adaptBSON
            return dict(
                (key if key.__class__ is str else str(key), adaptBSON(value))
                for (key, value) in object.items())
        if cls is list:
            adaptBSON = self.adaptBSON
            return [adaptBSON(value) for value in object]

        if isinstance(object, dict):
            newDict = {}
            for (key, value) in object.items():
                newDict[str(key)] = self.adaptBSON(value)
            return newDict
        elif isinstance(object, list):
            newList = []
            for value in object:
                newList.append(self.adaptBSON(value))
            return newList
        elif isinstance(object, bool):
            return bool(object)
        elif isinstance(object, int):
            return int(object)
        elif isinstance(object, float):
            return float(object)
        else:
            return adapt_string(object)
