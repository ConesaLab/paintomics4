#***************************************************************
#  This file is part of Paintomics v4
#**************************************************************

import logging
import os
from src.classes.Job import Job

class MOREJob(Job):
    """
    Job class for the MORE (Model-based Omics REgulation) analysis.
    This job bridges the main Gene Expression data with regulatory omics 
    using regression models (MLR/PLS).
    """

    def __init__(self, jobID, userID, CLIENT_TMP_DIR):
        super(MOREJob, self).__init__(jobID, userID, CLIENT_TMP_DIR)
        
        # Inputs from Step 1
        self.regulatoryOmics = []  # List of dicts: {name, file, type, associations}
        self.conditionsFile = None # The Experimental Design file
        self.targetOmicName = "Gene Expression" # Fixed per contract
        
        # Model Parameters
        self.method = "PLS1"  # PLS1 or MLR
        self.alpha = 0.05
        self.vip = 0.8
        self.filter_r2 = 0.0
        self.enrichment = "associations"
        
        # Input file set by the servlet before Step 2 runs
        self.targetExpressionFile = None

        # Tracking for Step 2/3
        self.results = {} # {omicName: {outputFile, relevantFile}}
        self.load_model_path = None # For fast-track mode

    def addRegulatoryOmic(self, name, dataFile, dataType, associationsFile=None, relevantFile=None):
        """
        Adds a regulatory omic dataset. 
        associationsFile is optional (None -> passed as NULL to R).
        relevantFile is optional (None -> use MORE output for red stars).
        """
        self.regulatoryOmics.append({
            "name": name,
            "file": dataFile,
            "type": dataType,
            "associations": associationsFile,
            "relevant": relevantFile
        })

    def getTargetExpressionFile(self, mainJob):
        """Finds the main Gene Expression file from the parent PathwayAcquisitionJob."""
        if hasattr(mainJob, 'getGeneBasedInputOmics'):
            gene_omics = mainJob.getGeneBasedInputOmics()
            for omic in gene_omics:
                if omic.get("omicName", "").lower() == "gene expression":
                    return omic.get("inputDataFile")
        return None

    def getValidationErrors(self, mainJob):
        """Pre-flight checks."""
        errors = []
        if not self.getTargetExpressionFile(mainJob):
            errors.append("Target 'Gene Expression' omic not found in main job.")
        if not self.conditionsFile:
            errors.append("Experimental Design (Conditions) file is missing.")
        if not self.regulatoryOmics:
            errors.append("No regulatory omics provided for MORE analysis.")
        return errors

    def getJobDescription(self):
        desc = f"MORE Analysis ({self.method})\n"
        desc += f"Alpha: {self.alpha}, VIP: {self.vip}, R2 Filter: {self.filter_r2}\n"
        desc += f"Regulators: {', '.join([o['name'] for o in self.regulatoryOmics])}"
        return desc
