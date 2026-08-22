from .FeatureDAO import FeatureDAO

class FoundFeatureDAO(FeatureDAO):
    #******************************************************************************************************************
    # CONSTRUCTORS
    #******************************************************************************************************************
    def __init__(self, *args, **kwargs):
        super(FoundFeatureDAO, self).__init__(*args, **kwargs)
        self.collectionName = "foundFeaturesCollection"