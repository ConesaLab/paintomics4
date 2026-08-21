#***************************************************************
#  This file is part of Paintomics v4
#**************************************************************

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
        # Which implementation runs `method`: "rust", "r", or "auto" for the
        # behaviour every job had before the engine could be chosen -- PLS1 to
        # the port when one is installed, everything else to R. Kept separate
        # from `method` because it is not a modelling choice: the two engines
        # were measured byte-identical on PLS1, so this decides how long the
        # job takes, not what it answers. See MOREServlet.MORE_ENGINES.
        self.engine = "auto"
        self.alpha = 0.05
        self.vip = 0.8
        self.filter_r2 = 0.0
        # Pathway enrichment counting unit. Defaults to "genes" because the values file
        # MORE writes is keyed by GENE:::REGULATOR — the gene side is what gets matched
        # against KEGG/Reactome pathways. The user may override per-omic via the
        # `more_enrichment` form field (see MOREServlet.fromMOREtoGenes_STEP1).
        self.enrichment = "genes"
        
        # Input file set by the servlet before Step 2 runs
        self.targetExpressionFile = None

        # Tracking for Step 2/3
        self.results = {} # {omicName: {outputFile, relevantFile}}
        self.load_model_path = None # For fast-track mode

    def addRegulatoryOmic(self, name, dataFile, dataType, associationsFile=None, relevantFile=None, minVariation=0.0):
        """
        Adds a regulatory omic dataset.
        associationsFile is optional (None -> passed as NULL to R).
        relevantFile is optional (None -> use MORE output for red stars).
        minVariation is the per-omic low-variation filter passed to MORE's
        `minVariation` argument (default 0.0 = keep all but constant regulators).
        """
        self.regulatoryOmics.append({
            "name": name,
            "file": dataFile,
            "type": dataType,
            "associations": associationsFile,
            "relevant": relevantFile,
            "minVariation": minVariation
        })

    def getTargetExpressionFile(self, mainJob):
        """Finds the target omic's data file in the parent PathwayAcquisitionJob.

        Matches against ``self.targetOmicName`` rather than a hardcoded
        literal, so setting that attribute actually takes effect. The default
        ("Gene Expression") resolves to exactly the string this used to look
        for, so the behaviour of an unmodified job is unchanged.
        """
        if not hasattr(mainJob, 'getGeneBasedInputOmics'):
            return None

        target = (self.targetOmicName or "").strip().lower()
        for omic in mainJob.getGeneBasedInputOmics() or []:
            # `or ""` rather than dict.get's default: the default only applies
            # when the key is absent, and an omicName that is present but None
            # is normal in a partially-populated job document.
            if (omic.get("omicName") or "").strip().lower() == target:
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
        # o.get(), not o['name']: parseBSON performs no shape validation, so a
        # job restored from a partial document can hold a regulator entry with
        # no "name" key, and a job description must never be what kills the
        # request.
        regulators = [str(o.get("name", "")).strip() for o in self.regulatoryOmics]
        desc += f"Regulators: {', '.join(r for r in regulators if r)}"
        return desc
