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


#: Raw interaction graphs in each source's OWN identifier space, keyed by
#: organism. Built once per process (0.40 s for KEGG, 0.62 s for Reactome on
#: mouse, measured) because this server is single-process: a rebuild per
#: request would stall every other user's job.
_RAW_GRAPH_CACHE = {}
_RAW_GRAPH_LIMIT = 4


def _keggRelationGraph(organism):
    """Every gene-gene relation KEGG draws for this organism, ANY pathway.

    This is the point of reading it at all. A regulator and its target are
    routinely joined by KEGG in a DIFFERENT map from the one on screen -- and
    consulting only OmniPath threw that away. Measured on the STATegra mouse
    job: of the 492 MORE relationships drawable on some mmu KEGG map, 132
    (26.8%) are recorded in KEGG's own relation graph while being labelled
    "novel" (54) or "unsupported" (78), the second of which claims there is no
    external evidence either way about a curated interaction.

    `maplink` is excluded: it joins an entry to another PATHWAY, not to a gene,
    so treating it as an interaction would manufacture edges. The remaining
    types are the ones MORE is actually modelling -- 238 of the hits are GErel
    (transcriptional) and 245 PPrel (protein-protein).

    Identifiers are KEGG's own (`mmu:15962` -> `15962`), i.e. the space the
    pathway documents are already stored in.

    @returns {dict} {(a, b): [(relationType, pathwayID), ...]}
    """
    import os
    import glob
    import xml.etree.ElementTree as ElementTree
    from src.conf.serverconf import KEGG_DATA_DIR

    graph = {}
    pattern = os.path.join(KEGG_DATA_DIR, "current", organism, "kgml", "*.kgml")
    for kgmlPath in glob.glob(pattern):
        pathwayID = os.path.basename(kgmlPath)[:-len(".kgml")]
        try:
            root = ElementTree.parse(kgmlPath).getroot()
        except Exception:
            # One unreadable KGML costs its own relations, not the whole graph.
            continue

        members = {}
        for entry in root.findall("entry"):
            if entry.get("type") in ("gene", "ortholog"):
                members[entry.get("id")] = [name.split(":")[-1]
                                            for name in (entry.get("name") or "").split()]
        # Groups are complexes whose members are other entries, so they resolve
        # only after every gene entry is known.
        for entry in root.findall("entry"):
            if entry.get("type") == "group":
                members[entry.get("id")] = [gene
                                            for component in entry.findall("component")
                                            for gene in members.get(component.get("id"), [])]

        for relation in root.findall("relation"):
            relationType = relation.get("type")
            if relationType == "maplink":
                continue
            for source in members.get(relation.get("entry1"), []):
                for target in members.get(relation.get("entry2"), []):
                    if source == target:
                        continue
                    graph.setdefault((source, target), []).append((relationType, pathwayID))
    return graph


def _reactomeRelationGraph(organism):
    """Reactome's catalyst / activator / inhibitor -> output relations.

    Only those three roles. A reaction's input -> output pair is usually the
    SAME molecule before and after a modification, so reading transformations
    as interactions would fill the graph with self-claims; the three regulatory
    roles are the ones that assert one gene product acting on another.

    Honest about its weight: this source rescues 7 of the 491 drawable mouse
    relationships (1.4%) against KEGG's 132. It is here because it is cheap and
    it is real, not because it is decisive.

    Identifiers are UniProt accessions -- the same space OmniPath uses, and the
    one the xref mates table is already proven to translate cleanly.

    @returns {dict} {(a, b): [(role, pathwayStId), ...]}
    """
    import os
    import glob
    import json

    from src.conf.serverconf import KEGG_DATA_DIR

    graph = {}
    pattern = os.path.join(KEGG_DATA_DIR, "current", organism, "reactome", "*.graph.json")
    for graphPath in glob.glob(pattern):
        try:
            with open(graphPath) as handle:
                document = json.load(handle)
        except Exception:
            continue

        nodes = {node.get("dbId"): node for node in (document.get("nodes") or [])}
        resolved = {}

        def accessions(dbId, depth=0):
            """A node's accessions, following complex membership downwards."""
            if dbId in resolved:
                return resolved[dbId]
            found = set()
            node = nodes.get(dbId)
            if node is not None and depth <= 4:
                identifier = node.get("identifier")
                if identifier and node.get("referenceType") == "ReferenceGeneProduct":
                    found.add(identifier)
                for child in (node.get("children") or []):
                    found |= accessions(child, depth + 1)
            resolved[dbId] = found
            return found

        pathwayStId = document.get("stId") or os.path.basename(graphPath)
        for reaction in (document.get("edges") or []):
            outputs = set()
            for output in (reaction.get("outputs") or []):
                outputs |= accessions(output)
            if not outputs:
                continue
            for role in ("catalysts", "activators", "inhibitors"):
                for regulator in (reaction.get(role) or []):
                    for source in accessions(regulator):
                        for target in outputs:
                            if source == target:
                                continue
                            graph.setdefault((source, target), []).append((role, pathwayStId))
    return graph


def _rawGraph(kind, organism):
    """Cached raw graph for one source, or {} when its files are not installed."""
    cacheKey = (kind, organism)
    if cacheKey in _RAW_GRAPH_CACHE:
        return _RAW_GRAPH_CACHE[cacheKey]

    builder = {"KEGG": _keggRelationGraph, "Reactome": _reactomeRelationGraph}[kind]
    try:
        graph = builder(organism)
    except Exception as buildError:
        # A missing data directory must cost this SOURCE, never the overlay.
        logging.warning("%s relation graph unavailable for %s: %s",
                        kind, organism, buildError)
        graph = {}

    if len(_RAW_GRAPH_CACHE) >= _RAW_GRAPH_LIMIT:
        _RAW_GRAPH_CACHE.pop(next(iter(_RAW_GRAPH_CACHE)))
    _RAW_GRAPH_CACHE[cacheKey] = graph
    return graph


class InteractionSource(object):
    """One curated interaction graph, translated into a pathway's ID space.

    Each source stores UniProt accessions or its own gene ids while a KEGG map
    is drawn in Entrez space, so every graph is translated once through the
    xref mates table and kept. The OmniPath translation is measured to be clean
    rather than merely wide: 79.6% of the 1,670 stored mouse accessions reach a
    drawn KEGG box, only 6 accessions fan out to more than one Entrez ID, and
    the collapse creates no collisions and no self-loops.
    """

    def __init__(self, name, edges, known):
        #: Source label as shown to the reader: "KEGG", "Reactome", "OmniPath".
        self.name = name
        #: {(a, b): provenance} with BOTH directions stored, so a lookup is one
        #: dict hit rather than two.
        self._edges = edges
        #: Every gene this source has an opinion about. Membership here is what
        #: separates CLASS_NOVEL from CLASS_UNSUPPORTED.
        self._known = known

    def __len__(self):
        return len(self._edges)

    def knows(self, featureID):
        return featureID in self._known

    def interaction(self, featureA, featureB):
        """Return this source's provenance for the pair, or None.

        Direction-agnostic on purpose: MORE asserts a regulatory direction that
        a curated interaction database need not have recorded the same way
        round, and claiming "the literature disagrees about direction" from
        that would be an artefact of two different data models.
        """
        return self._edges.get((featureA, featureB)) or self._edges.get((featureB, featureA))


class EvidenceKnowledge(object):
    """Every interaction source, consulted together.

    Consulting only OmniPath was losing curated biology: measured on the
    STATegra mouse job, 132 of 492 drawable relationships (26.8%) are recorded
    in KEGG -- usually in a pathway OTHER than the one on screen -- while being
    labelled novel or unsupported. The sources are complementary rather than
    nested: 41 of the 93 OmniPath-corroborated pairs are absent from KEGG, so
    neither is a superset of the other and the union is the honest question.
    """

    def __init__(self, sources):
        self.sources = [source for source in sources if source is not None]

    def __len__(self):
        return sum(len(source) for source in self.sources)

    def knows(self, featureID):
        return any(source.knows(featureID) for source in self.sources)

    def interactions(self, featureA, featureB):
        """[(sourceName, provenance)] for every source recording the pair."""
        found = []
        for source in self.sources:
            provenance = source.interaction(featureA, featureB)
            if provenance is not None:
                found.append((source.name, provenance))
        return found

    @classmethod
    def forOrganism(cls, organism, targetDbnameId, jobID, db):
        """Build (or reuse) all three graphs for one organism/ID space."""
        cacheKey = (organism, str(targetDbnameId))
        if cacheKey in _KNOWLEDGE_CACHE:
            return _KNOWLEDGE_CACHE[cacheKey]

        knowledge = cls([
            _buildOmniPathSource(organism, targetDbnameId, jobID, db),
            _buildTranslatedSource("KEGG", _rawGraph("KEGG", organism),
                                   targetDbnameId, jobID, db),
            _buildTranslatedSource("Reactome", _rawGraph("Reactome", organism),
                                   targetDbnameId, jobID, db),
        ])

        if len(_KNOWLEDGE_CACHE) >= _KNOWLEDGE_CACHE_LIMIT:
            _KNOWLEDGE_CACHE.pop(next(iter(_KNOWLEDGE_CACHE)))
        _KNOWLEDGE_CACHE[cacheKey] = knowledge
        return knowledge


def _translateIdentifiers(identifiers, jobID, db, targetDbnameId):
    """Map a source's own identifiers into the pathway's ID space."""
    from src.common.FeatureNamesToKeggIDsMapper import findIDsByFeaturesName

    if not identifiers:
        return {}
    return findIDsByFeaturesName(jobID, list(identifiers), db, targetDbnameId)


def _buildTranslatedSource(name, rawGraph, targetDbnameId, jobID, db):
    """Translate a raw {(a, b): [(detail, pathway)]} graph into feature IDs."""
    if not rawGraph:
        return InteractionSource(name, {}, set())

    identifiers = set()
    for source, target in rawGraph.keys():
        identifiers.add(source)
        identifiers.add(target)

    try:
        translation = _translateIdentifiers(identifiers, jobID, db, targetDbnameId)
    except Exception as translationError:
        logging.warning("%s knowledge untranslatable for this ID space: %s",
                        name, translationError)
        return InteractionSource(name, {}, set())

    edges, known = {}, set()
    for featureIDs in translation.values():
        for featureID in (featureIDs or []):
            known.add(str(featureID))

    for (source, target), records in rawGraph.items():
        for sourceID in (translation.get(source) or []):
            for targetID in (translation.get(target) or []):
                sourceID, targetID = str(sourceID), str(targetID)
                if sourceID == targetID:
                    continue          # an isoform collapse is not an edge
                edges.setdefault((sourceID, targetID), []).extend(records)

    logging.info("%s knowledge: %d identifiers -> %d genes, %d translated "
                 "interactions", name, len(identifiers), len(known), len(edges))
    return InteractionSource(name, edges, known)


def _buildOmniPathSource(organism, targetDbnameId, jobID, db):
    """OmniPath's curated literature graph, with its PMIDs kept."""
    # Accumulate the accession-space graph first. Documents are streamed and
    # released one at a time; only the edge tuples are retained.
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
        return InteractionSource("OmniPath", {}, set())

    if not accessions:
        return InteractionSource("OmniPath", {}, set())

    translation = _translateIdentifiers(accessions, jobID, db, targetDbnameId)

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
    return InteractionSource("OmniPath", edges, known)


#: How many pathway names one source may name per edge before the rest are
#: counted instead. A tooltip is read, not scrolled.
_MAX_NAMED_PATHWAYS = 3


def _summariseEvidence(hits, openPathwayID, pathwayNames):
    """Turn each source's raw provenance into something a reader can act on.

    The point of naming the pathway is the whole reason for looking beyond the
    open map: a KEGG relation recorded in mmu04010 tells the reader that this
    interaction IS curated, just not drawn here. Saying only "corroborated"
    would keep the fact and lose the address.
    """
    summaries = []
    for sourceName, provenance in hits:
        record = {"source": sourceName, "references": [], "curationEffort": 0,
                  "detail": "", "pathways": [], "morePathways": 0,
                  "onThisPathway": False}

        if isinstance(provenance, tuple):
            # OmniPath: (sign, references, curationEffort). It is not organised
            # by pathway at all -- it is an interaction list.
            record["detail"] = str(provenance[0] or "")
            record["references"] = _parseReferences(provenance[1])
            record["curationEffort"] = provenance[2]
            summaries.append(record)
            continue

        details, pathways = [], []
        for detail, pathwayID in provenance:
            if detail not in details:
                details.append(detail)
            if pathwayID == openPathwayID:
                record["onThisPathway"] = True
                continue
            if pathwayID not in [entry["id"] for entry in pathways]:
                pathways.append({"id": pathwayID,
                                 "name": pathwayNames.get(pathwayID, pathwayID)})

        record["detail"] = ", ".join(details)
        record["morePathways"] = max(0, len(pathways) - _MAX_NAMED_PATHWAYS)
        record["pathways"] = pathways[:_MAX_NAMED_PATHWAYS]
        summaries.append(record)

    return summaries


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


#: Parsed KGML entry geometry, keyed (organism, pathwayID). A KGML is 100-600 kB
#: of XML and a diagram is reopened constantly, so it is read once per process.
#: Bounded because a session can only open so many maps; nothing here is large.
_KGML_BOX_CACHE = {}
_KGML_CACHE_LIMIT = 256


def _kgmlOnlyBoxes(organism, pathwayID):
    """Boxes KEGG prints that the installed pathway document does not store.

    The Mongo document keeps `genes`, `compounds` and `relatedPathways` only.
    The KGML also carries `ortholog` entries -- KO boxes for proteins with no
    ortholog in this organism, which on infection and disease maps are the
    VIRAL proteins -- and `group` entries for complexes. Measured on mmu05167
    (Kaposi sarcoma-associated herpesvirus infection): 122 gene, 5 compound and
    15 map entries are stored, while 31 ortholog and 6 group entries are not.
    One of the missing ones is ko:K21664 -- LANA -- and a satellite was landing
    on 44.7% of its own area on top of it.

    Reading the KGML at request time rather than re-installing is deliberate:
    the geometry is already on disk beside the PNG the server serves, and an
    installed database must not have to be rebuilt to fix a drawing bug.

    @returns {list} obstacle dicts, or [] when the file is absent or unreadable
    """
    cacheKey = (organism, pathwayID)
    if cacheKey in _KGML_BOX_CACHE:
        return _KGML_BOX_CACHE[cacheKey]

    import os
    import xml.etree.ElementTree as ElementTree
    from src.conf.serverconf import KEGG_DATA_DIR

    boxes = []
    kgmlPath = os.path.join(KEGG_DATA_DIR, "current", organism, "kgml",
                            pathwayID + ".kgml")
    try:
        if os.path.isfile(kgmlPath):
            root = ElementTree.parse(kgmlPath).getroot()
            for entry in root.findall("entry"):
                # gene/compound/map geometry is already in Mongo; taking it
                # from here too would only duplicate rectangles.
                if entry.get("type") not in ("ortholog", "group"):
                    continue
                graphics = entry.find("graphics")
                if graphics is None:
                    continue
                try:
                    boxes.append({
                        "x": float(graphics.get("x")),
                        "y": float(graphics.get("y")),
                        "width": float(graphics.get("width")),
                        "height": float(graphics.get("height")),
                    })
                except (TypeError, ValueError):
                    # An entry with no geometry is a label, not a drawn box.
                    continue
    except Exception as parseError:
        # A malformed or unreadable KGML must cost the overlay its extra
        # obstacles, never the whole diagram: placement stays optimistic,
        # which is exactly the behaviour before this function existed.
        logging.warning("Evidence overlay: could not read %s (%s)",
                        kgmlPath, parseError)
        boxes = []

    if len(_KGML_BOX_CACHE) >= _KGML_CACHE_LIMIT:
        _KGML_BOX_CACHE.clear()
    _KGML_BOX_CACHE[cacheKey] = boxes
    return boxes


def _printedObstacles(pathwayDocument, organism=None, pathwayID=None):
    """Every box the map prints, so a new mark can be placed where none is.

    Three sources, in descending order of how badly they were missed:

      * `genes` -- all 268 rows on mmu05167, of which the client only ever
        knew the ~61 its own data painted. An unmatched KEGG box is still
        printed, still carries a gene symbol, and is still ruined by a mark
        dropped on top of it;
      * `relatedPathways` -- the rounded cross-pathway boxes ("Cell cycle",
        "MAPK signaling pathway"), 21 of them on mmu05200, the largest
        printed obstacles on a KEGG map;
      * `compounds` -- small, but they sit in the open space a placer wants.

    plus the ortholog and group boxes only the KGML has (see _kgmlOnlyBoxes).

    Rectangles are deduplicated on rounded geometry: co-located genes share
    one printed box, so mmu05167's 268 gene rows collapse to far fewer
    distinct rectangles and the payload stays small.

    Coordinates are the box CENTRE, matching the gene entries, and arrive from
    Mongo as strings because the KGML attributes were never cast.
    """
    obstacles = []
    seen = set()

    def add(entry):
        try:
            box = {
                "x": float(entry.get("x")),
                "y": float(entry.get("y")),
                "width": float(entry.get("width")),
                "height": float(entry.get("height")),
            }
        except (TypeError, ValueError):
            # An entry without geometry is a link or a label, not a drawn box.
            return
        if box["width"] <= 0 or box["height"] <= 0:
            # MapMan stores every feature with width = height = 0; a zero-area
            # rectangle blocks nothing and would only inflate the payload.
            return
        key = (round(box["x"], 1), round(box["y"], 1),
               round(box["width"], 1), round(box["height"], 1))
        if key in seen:
            return
        seen.add(key)
        obstacles.append(box)

    for field in ("relatedPathways", "genes", "compounds"):
        for entry in (pathwayDocument.get(field) or []):
            add(entry)

    # KEGG only: Reactome and MapMan diagrams have no KGML, and OmniPath has
    # no diagram at all.
    if organism and pathwayID and (pathwayDocument.get("source") or "KEGG") == "KEGG":
        for entry in _kgmlOnlyBoxes(organism, pathwayID):
            add(entry)

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
        #: How many corroborating hits each source contributed, so the panel can
        #: say which database is doing the work on this map.
        "bySource": {},
        #: Corroborated by a pathway database that draws the interaction on a
        #: DIFFERENT map. This is the count that used to be lost entirely.
        "recordedElsewhere": 0,
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
        # One pass for every pathway name in the organism (1,008 documents on
        # mouse), so naming the map an interaction was recorded on costs no
        # query per edge.
        pathwayNames = {document.get("ID"): document.get("name")
                        for document in database["kegg"].find({}, {"ID": 1, "name": 1})}
        obstacles = _printedObstacles(pathwayDocument, organism, pathwayID)
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

        knowledge = EvidenceKnowledge.forOrganism(organism, targetDbnameId,
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

            hits = knowledge.interactions(regulatorID, targetID)
            if hits:
                edgeClass = CLASS_CORROBORATED
                evidenceSources = _summariseEvidence(hits, pathwayID, pathwayNames)
                # Kept at the top level for the tooltip's citation line: only
                # OmniPath carries PMIDs, KEGG and Reactome cite themselves.
                omniPath = [entry for entry in evidenceSources
                            if entry["source"] == "OmniPath"]
                references = omniPath[0]["references"] if omniPath else []
                curationEffort = omniPath[0]["curationEffort"] if omniPath else 0
                for entry in evidenceSources:
                    statistics["bySource"][entry["source"]] = \
                        statistics["bySource"].get(entry["source"], 0) + 1
                    if entry["source"] != "OmniPath" and entry["pathways"]:
                        statistics["recordedElsewhere"] += 1
                        break
            elif knowledge.knows(regulatorID) and knowledge.knows(targetID):
                edgeClass = CLASS_NOVEL
                references, curationEffort, evidenceSources = [], 0, []
            else:
                edgeClass = CLASS_UNSUPPORTED
                references, curationEffort, evidenceSources = [], 0, []

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
                "evidenceSources": evidenceSources,
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
