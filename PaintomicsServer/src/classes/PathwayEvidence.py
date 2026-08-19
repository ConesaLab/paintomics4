#***************************************************************
#  PathwayEvidence.py
#
#  Classify a job's MORE regulator -> target relationships against the
#  curated literature graph (OmniPath) and reduce them to the handful that
#  can honestly be drawn on one pathway diagram.
#
#  WHY THIS EXISTS
#  ---------------
#  A pathway map is a raster PNG with feature boxes placed on top; the app
#  has no model of the artwork underneath, so every drawn edge competes with
#  biology it cannot see. Measured on the STATegra MORE job (1,562
#  relationships, mouse) against the installed mmu pathway data:
#
#    * the readable ceiling is 5-8 edges per map -- crossings per edge passes
#      1.0 between N=5 and N=10, and bowing edges into arcs moves that by <8%,
#      so routing cannot buy a bigger budget, only drawing fewer edges can;
#    * a real job puts a median of 11 and a maximum of 196 edges on a single
#      KEGG map, i.e. 25x the budget on the map users open most;
#    * 63.6% of the bundled examples' regulators (100% of miRNAs) resolve to
#      no drawn box anywhere, so they cannot be an arrow at all.
#
#  The response therefore carries three ranked classes and an explicit account
#  of what was left out. Anything this module drops, it counts.
#***************************************************************

import logging

from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT

#: Relationship MORE found AND OmniPath independently records an interaction
#: for. This is an EXISTENCE claim only. Sign concordance between MORE's
#: regression coefficient and OmniPath's curated sign measured 58.3% against
#: 52.8% expected by chance (p ~ 0.21) -- it is not a signal and must never be
#: presented as agreement.
CLASS_CORROBORATED = "corroborated"

#: Relationship MORE found between two proteins OmniPath knows well, where
#: OmniPath records NO interaction between them. The candidate-for-promotion
#: class: an experimental link the curated literature does not contain.
CLASS_NOVEL = "novel"

#: Everything else -- one or both endpoints unknown to OmniPath, so there is
#: no external opinion either way. Carries no citation and leans entirely on
#: the coefficient.
CLASS_UNSUPPORTED = "unsupported"

#: Order in which classes earn scarce space on the canvas.
CLASS_PRIORITY = {CLASS_CORROBORATED: 0, CLASS_NOVEL: 1, CLASS_UNSUPPORTED: 2}

#: Default cap. Deliberately at the top of the measured 5-8 readable band.
DEFAULT_MAX_EDGES = 8

#: A single job may open many pathways; the literature graph is per organism
#: and identical for all of them, so it is built once. Bounded because the
#: process is long-lived and organisms are unbounded in principle.
_KNOWLEDGE_CACHE = {}
_KNOWLEDGE_CACHE_LIMIT = 4


class OmniPathKnowledge(object):
    """The curated literature interaction graph, in a pathway's own ID space.

    OmniPath stores UniProt accessions while a KEGG map is drawn in Entrez
    space, so the graph is translated once through the xref mates table and
    kept. The translation is measured to be clean rather than merely wide:
    79.6% of the 1,670 stored mouse accessions reach a drawn KEGG box, only 6
    accessions fan out to more than one Entrez ID, and the collapse creates no
    collisions and no self-loops.
    """

    def __init__(self, edges, known, sourceName):
        #: {(a, b): (sign, references, curationEffort)} with BOTH directions
        #: stored, so a lookup is one dict hit rather than two.
        self._edges = edges
        #: Every gene the literature graph has an opinion about. Membership
        #: here is what separates CLASS_NOVEL from CLASS_UNSUPPORTED.
        self._known = known
        self.sourceName = sourceName

    def __len__(self):
        return len(self._edges)

    def knows(self, featureID):
        return featureID in self._known

    def interaction(self, featureA, featureB):
        """Return (sign, references, curationEffort) or None.

        Direction-agnostic on purpose: MORE asserts a regulatory direction
        that a curated interaction database need not have recorded the same
        way round, and claiming "the literature disagrees about direction"
        from that would be an artefact of two different data models.
        """
        return self._edges.get((featureA, featureB)) or self._edges.get((featureB, featureA))

    @classmethod
    def forOrganism(cls, organism, targetDbnameId, jobID, db):
        """Build (or reuse) the translated graph for one organism/ID space."""
        cacheKey = (organism, str(targetDbnameId))
        if cacheKey in _KNOWLEDGE_CACHE:
            return _KNOWLEDGE_CACHE[cacheKey]

        knowledge = cls._build(organism, targetDbnameId, jobID, db)

        if len(_KNOWLEDGE_CACHE) >= _KNOWLEDGE_CACHE_LIMIT:
            _KNOWLEDGE_CACHE.pop(next(iter(_KNOWLEDGE_CACHE)))
        _KNOWLEDGE_CACHE[cacheKey] = knowledge
        return knowledge

    @classmethod
    def _build(cls, organism, targetDbnameId, jobID, db):
        from src.common.FeatureNamesToKeggIDsMapper import findIDsByFeaturesName

        # Accumulate the accession-space graph first. Documents are streamed
        # and released one at a time; only the edge tuples are retained.
        accessionEdges = {}
        accessions = set()
        try:
            for document in db["omnipath_network"].find({}, {"_id": 0, "edges": 1}):
                for edge in (document.get("edges") or []):
                    if len(edge) < 3:
                        continue
                    source, target, sign = edge[0], edge[1], edge[2]
                    # Edges gained `references` and `curation_effort` after the
                    # first release, so tolerate the three-element form rather
                    # than requiring a reinstall to render anything at all.
                    references = edge[3] if len(edge) > 3 else ""
                    effort = edge[4] if len(edge) > 4 else 0
                    accessionEdges[(source, target)] = (sign, references, effort)
                    accessions.add(source)
                    accessions.add(target)
        except Exception as ex:
            logging.warning("OmniPath knowledge unavailable for %s: %s", organism, ex)
            return cls({}, set(), "OmniPath")

        if not accessions:
            return cls({}, set(), "OmniPath")

        translation = findIDsByFeaturesName(jobID, list(accessions), db, targetDbnameId)

        edges, known = {}, set()
        for accession, featureIDs in translation.items():
            for featureID in (featureIDs or []):
                known.add(str(featureID))

        for (source, target), provenance in accessionEdges.items():
            for sourceID in (translation.get(source) or []):
                for targetID in (translation.get(target) or []):
                    sourceID, targetID = str(sourceID), str(targetID)
                    if sourceID == targetID:
                        continue          # an isoform collapse is not an edge
                    edges[(sourceID, targetID)] = provenance

        logging.info("OmniPath knowledge for %s: %d accessions -> %d genes, "
                     "%d translated interactions", organism, len(accessions),
                     len(known), len(edges))
        return cls(edges, known, "OmniPath")


def _parseReferences(raw):
    """Split OmniPath's reference string into citable records.

    Tokens are ``RESOURCE:PMID`` (13,764 of 13,765 sampled), so both halves
    are kept: the resource names who curated the claim, the PMID lets a reader
    go and check it.
    """
    records = []
    for token in str(raw or "").replace(",", ";").split(";"):
        token = token.strip()
        if not token:
            continue
        resource, _, pmid = token.partition(":")
        if pmid.isdigit():
            records.append({"resource": resource, "pmid": pmid})
        elif resource.isdigit():
            records.append({"resource": "", "pmid": resource})
    return records


class _RegulationTable(object):
    """Typed view over the job's stored MORE table.

    The table is a raw {columns, rows} pair whose shape varies by MORE method
    -- MLR emits a `representative` column PLS1 does not, and the Group_*
    coefficient columns are named after the job's own conditions. Reading it
    by position anywhere else in the codebase would break on the next method.
    """

    def __init__(self, regulationData):
        self.columns = list((regulationData or {}).get("columns") or [])
        self.rows = list((regulationData or {}).get("rows") or [])
        self.symbols = dict((regulationData or {}).get("symbols") or {})

        index = {name: position for position, name in enumerate(self.columns)}
        self._target = index.get("targetF")
        self._regulator = index.get("regulator")
        self._omic = index.get("omic")
        self._area = index.get("area")
        self._r2 = index.get("R2")
        #: Every Group_<condition> column, in table order.
        self._conditions = [(name[len("Group_"):], position)
                            for name, position in index.items()
                            if name.startswith("Group_")]
        self._conditions.sort(key=lambda entry: index[("Group_" + entry[0])])

    @property
    def usable(self):
        return self._target is not None and self._regulator is not None and bool(self.rows)

    @property
    def conditionNames(self):
        return [name for name, _ in self._conditions]

    def _cell(self, row, position):
        if position is None or position >= len(row):
            return None
        return row[position]

    def _coefficient(self, row, condition=None):
        """The coefficient to draw, and the condition it belongs to.

        With no condition requested the strongest one is used, because a
        relationship the model kept is most legible where the model says it
        acts. Coefficients are unbounded regression slopes and are NOT
        comparable across omics or targets, so this ranking is only ever
        within one job.
        """
        best, bestCondition = None, None
        for name, position in self._conditions:
            if condition is not None and name != condition:
                continue
            try:
                value = float(self._cell(row, position))
            except (TypeError, ValueError):
                continue
            if best is None or abs(value) > abs(best):
                best, bestCondition = value, name
        return best, bestCondition

    def relationships(self, condition=None):
        """Yield one dict per MORE relationship. Rows missing an endpoint or a
        usable coefficient are skipped -- they cannot be drawn or ranked."""
        for row in self.rows:
            target = self._cell(row, self._target)
            regulator = self._cell(row, self._regulator)
            if not target or not regulator:
                continue

            coefficient, coefficientCondition = self._coefficient(row, condition)
            if coefficient is None:
                continue

            try:
                r2 = float(self._cell(row, self._r2))
            except (TypeError, ValueError):
                r2 = None

            yield {
                "regulator": str(regulator),
                "target": str(target),
                "omic": self._cell(row, self._omic) or "",
                "area": self._cell(row, self._area) or "",
                "coefficient": coefficient,
                "condition": coefficientCondition,
                # R2 belongs to the TARGET's whole model, not to this edge:
                # runMORE merges it in by targetF, so every relationship of one
                # target carries the same number. Labelled at the boundary so a
                # consumer cannot mistake it for an edge statistic.
                "targetR2": r2,
            }


def _printedObstacles(pathwayDocument):
    """Large printed boxes the client draws nothing for but must not draw over.

    A KEGG map's cross-pathway links -- the rounded boxes reading "Cell cycle",
    "MAPK signaling pathway" -- are the biggest printed obstacles on the canvas
    (21 of them on mmu05200) and the installer has always stored them with full
    geometry. The client has simply never been sent them: nothing in
    PaintomicsClient references relatedPathways at all. Anything placing new
    marks in free space needs them, and they cost one field.

    Coordinates are the box CENTRE, matching the gene entries, and arrive from
    Mongo as strings because the KGML attributes were never cast.
    """
    obstacles = []
    for related in (pathwayDocument.get("relatedPathways") or []):
        try:
            obstacles.append({
                "x": float(related.get("x")),
                "y": float(related.get("y")),
                "width": float(related.get("width")),
                "height": float(related.get("height")),
            })
        except (TypeError, ValueError):
            # A related pathway without geometry is a link, not a drawn box.
            continue
    return obstacles


def _drawnFeatureIDs(pathwayDocument):
    """IDs of the genes this pathway actually draws.

    A coordinate-less entry has no box to attach to. 10.3% of mouse KEGG gene
    entries are coordinate-less and 12 maps have no coordinate-bearing gene at
    all, so this is a real filter and not a formality.
    """
    drawn = set()
    for gene in (pathwayDocument.get("genes") or []):
        if gene.get("x") is None or gene.get("y") is None:
            continue
        drawn.add(str(gene.get("id")))
    return drawn


def buildPathwayEvidence(jobInstance, pathwayID, condition=None,
                         maxEdges=DEFAULT_MAX_EDGES, classes=None):
    """Evidence edges drawable on one pathway, ranked, capped and accounted for.

    @param {Job} jobInstance, a loaded PathwayAcquisitionJob
    @param {String} pathwayID, the pathway whose diagram is open
    @param {String} condition, restrict coefficients to this condition, or None
                    for the strongest condition per relationship
    @param {int} maxEdges, hard cap on drawn edges
    @param {set} classes, which classes may be drawn (default: all three)
    @returns {dict} the payload delivered to the Step 4 view
    """
    from pymongo import MongoClient
    from src.common.FeatureNamesToKeggIDsMapper import (
        resolveDatabaseIds, findIDsByFeaturesName)

    allowedClasses = set(classes) if classes else set(CLASS_PRIORITY)
    obstacles = []
    organism = jobInstance.getOrganism()

    table = _RegulationTable(getattr(jobInstance, "regulationPerConditionData", None))
    statistics = {
        "totalRelationships": len(table.rows),
        "conditions": table.conditionNames,
        "condition": condition,
        "drawable": 0,
        "offMapRegulators": 0,
        "offMapTargets": 0,
        "hidden": 0,
        "byClass": {CLASS_CORROBORATED: 0, CLASS_NOVEL: 0, CLASS_UNSUPPORTED: 0},
        "literatureAvailable": False,
        "multiBoxEndpoints": 0,
    }

    if not table.usable:
        return {"pathwayID": pathwayID, "edges": [], "obstacles": [], "statistics": statistics}

    client = MongoClient(MONGODB_HOST, MONGODB_PORT)
    try:
        database = client[organism + "-paintomics"]
        pathwayDocument = database["kegg"].find_one({"ID": pathwayID})
        if pathwayDocument is None:
            return {"pathwayID": pathwayID, "edges": [], "obstacles": [], "statistics": statistics}

        sourceName = pathwayDocument.get("source") or "KEGG"
        obstacles = _printedObstacles(pathwayDocument)
        drawn = _drawnFeatureIDs(pathwayDocument)
        if not drawn:
            return {"pathwayID": pathwayID, "edges": [], "obstacles": [], "statistics": statistics}

        databaseConvertionIds, _symbolIds = resolveDatabaseIds(organism, [sourceName], database)
        targetDbnameId = databaseConvertionIds.get(sourceName)
        if targetDbnameId is None:
            return {"pathwayID": pathwayID, "edges": [], "obstacles": [], "statistics": statistics}

        relationships = list(table.relationships(condition))

        # One batched translation for every endpoint name in the job, rather
        # than a query per relationship: findIDsByFeaturesName caches misses as
        # well as hits, so the second pathway a user opens costs no queries.
        names = set()
        for relationship in relationships:
            names.add(relationship["regulator"])
            names.add(relationship["target"])
        translation = findIDsByFeaturesName(jobInstance.getJobID(), list(names),
                                            database, targetDbnameId)

        knowledge = OmniPathKnowledge.forOrganism(organism, targetDbnameId,
                                                  jobInstance.getJobID(), database)
        statistics["literatureAvailable"] = len(knowledge) > 0

        edges = []
        for relationship in relationships:
            regulatorIDs = [str(featureID) for featureID
                            in (translation.get(relationship["regulator"]) or [])]
            targetIDs = [str(featureID) for featureID
                         in (translation.get(relationship["target"]) or [])]

            drawnRegulators = [featureID for featureID in regulatorIDs if featureID in drawn]
            drawnTargets = [featureID for featureID in targetIDs if featureID in drawn]

            if not drawnRegulators:
                statistics["offMapRegulators"] += 1
                continue
            if not drawnTargets:
                statistics["offMapTargets"] += 1
                continue

            # Deterministic representative when a symbol resolves to several
            # genes drawn on this map. The alternative -- drawing all of them --
            # turns 131 Reactome edges into 3,252 line segments.
            regulatorID = sorted(drawnRegulators)[0]
            targetID = sorted(drawnTargets)[0]
            if regulatorID == targetID:
                continue

            ambiguous = len(drawnRegulators) > 1 or len(drawnTargets) > 1
            if ambiguous:
                statistics["multiBoxEndpoints"] += 1

            interaction = knowledge.interaction(regulatorID, targetID)
            if interaction is not None:
                edgeClass = CLASS_CORROBORATED
                references = _parseReferences(interaction[1])
                curationEffort = interaction[2]
            elif knowledge.knows(regulatorID) and knowledge.knows(targetID):
                edgeClass = CLASS_NOVEL
                references, curationEffort = [], 0
            else:
                edgeClass = CLASS_UNSUPPORTED
                references, curationEffort = [], 0

            statistics["drawable"] += 1
            statistics["byClass"][edgeClass] += 1

            if edgeClass not in allowedClasses:
                continue

            edges.append({
                "regulator": relationship["regulator"],
                "target": relationship["target"],
                "regulatorID": regulatorID,
                "targetID": targetID,
                "regulatorLabel": table.symbols.get(relationship["regulator"],
                                                    relationship["regulator"]),
                "targetLabel": table.symbols.get(relationship["target"],
                                                 relationship["target"]),
                "evidenceClass": edgeClass,
                "coefficient": relationship["coefficient"],
                "condition": relationship["condition"],
                "omic": relationship["omic"],
                "targetR2": relationship["targetR2"],
                "references": references,
                "curationEffort": curationEffort,
                "ambiguousEndpoint": ambiguous,
                "regulatorBoxes": len(drawnRegulators),
                "targetBoxes": len(drawnTargets),
            })
    finally:
        client.close()

    # Rank: corroborated first (it is the only class that can cite anything),
    # then novel, then the unsupported bulk, each by coefficient magnitude.
    edges.sort(key=lambda edge: (CLASS_PRIORITY[edge["evidenceClass"]],
                                 -abs(edge["coefficient"])))

    if maxEdges is not None and len(edges) > maxEdges:
        statistics["hidden"] = len(edges) - maxEdges
        edges = edges[:maxEdges]

    statistics["shown"] = len(edges)
    return {"pathwayID": pathwayID, "edges": edges,
            "obstacles": obstacles, "statistics": statistics}
