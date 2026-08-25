#***************************************************************
#  This file is part of Paintomics v4
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomicsai@gmail.com
#**************************************************************
"""Tier 1: what can be settled about a compound set without asking a model.

Measured on the STATegra metabolomics example (58 named metabolites, mmu), the
rules below settle 29 of the 49 sets that draw a card and hand 20 to the model.
They are ordered so that each one only fires when it leaves exactly one answer.

One rule that looks obvious is deliberately absent: **exact name wins**. It is
wrong, and quietly so. Measured against ``global-paintomics.kegg_compounds``:

    "Alanine"     -> C01401  (the unspecified form), NOT C00041 L-Alanine
    "Serine"      -> C00716 AND C00065, two ids with that literal name
    "Malic acid"  -> C00149 AND C00711
    "Lactic acid" -> C01432, not the L- form every animal pathway draws

For three of those the species filter below rescues the answer, because the
unspecified form is drawn on no mouse pathway. For "Alanine" it does not:
C01401 *is* on mouse maps, so that name stays ambiguous and is escalated. A
rule that had "resolved" it to C01401 would have produced a wrong compound with
no symptom at all -- the analysis would simply have been about a different
metabolite than the user measured.
"""

import logging

from src.classes.FoundFeature import FoundFeature
from src.common.CompoundNameSimilarity import nameSimilarity

#: Upper bound on how many candidates one residual set carries into a prompt.
#: "Glucose" reaches step 2 with 113; the ones that matter are always the main
#: candidates the organism actually draws, and a longer list is prompt weight
#: rather than information.
MAX_CANDIDATES_IN_PROMPT = 12

#: Cap on the ids one synonym lookup will fetch, so a pathological job cannot
#: turn tier 1 into a full scan of a 92,974-document collection.
MAX_SYNONYM_LOOKUP = 4000

#: How many synonyms one candidate carries into a card or a prompt. C00031 has
#: sixteen; the first few closest to what the user typed are what identify it,
#: and the rest are prompt weight.
MAX_NAMES_PER_CANDIDATE = 6


def _isUninformativeName(name):
    """Names in ``kegg_compounds`` that carry no chemistry.

    The collection stores one document per (id, synonym) and includes the KEGG
    accession repeated as its own name, plus ChEBI cross-references as
    "chebi:4167" and as a bare "4167". Shown to a user or to a model these are
    noise. They are dropped only when something else survives, because a
    candidate must never end up with no name at all.
    """
    text = (name or "").strip()
    if not text:
        return True
    if text.lower().startswith("chebi:"):
        return True
    if text.isdigit():
        return True
    # "C00031" stored as its own name.
    return len(text) == 6 and text[0] in "CDG" and text[1:].isdigit()


def _namesFor(compound, synonymsByID):
    """Every name to score and show this candidate under.

    Deliberately NOT split on commas. 6,581 names in ``kegg_compounds`` contain
    one -- "1D-myo-Inositol 1,4-bisphosphate", and C04137 is stored as
    "Arginine, N2-(1-carboxyethyl)-, L-". Splitting that last one produced a
    synonym "Arginine", which then scored as a direct hit for an input of
    "L-arginine" and pulled an unrelated compound into the choice.

    ``mapCompoundsIdentifiers`` does join merged duplicates with ", ", so a
    stored name genuinely can be two synonyms in one string. That ambiguity
    cannot be resolved from the string, which is why the authoritative list is
    fetched by KEGG id instead -- see :func:`loadCompoundSynonyms`.
    """
    names = []
    for name in list(synonymsByID.get(compound.getID(), ())) + [compound.getName()]:
        text = (name or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def candidatesByKeggID(compoundSet, synonymsByID=None):
    """Collapse a step-2 compound set into one entry per KEGG id.

    The same KEGG id routinely appears several times inside one set -- once per
    synonym that matched the input substring -- and the user is choosing
    between COMPOUNDS, not between spellings.

    ``isMain`` is taken from the bucket the mapper put the candidate in, not
    from rescoring the name here. That is the load-bearing choice in this
    module: ``mainCompounds`` is what step 2 pre-ticks and draws, so a ranker
    that recomputed "main" and disagreed would offer to resolve a set the user
    is not looking at. Recomputed similarity is used only to order the
    candidates a residual set carries into the prompt.

    @param compoundSet, a FoundFeature: getTitle/getMainCompounds/getOtherCompounds
    @param {Dict} synonymsByID, optional keggID -> [names] taken from KEGG
    @returns {Dict} keggID -> {"keggID", "names", "similarity", "isMain"}
    """
    title = compoundSet.getTitle() or ""
    synonymsByID = synonymsByID or {}
    byID = {}

    buckets = ([(c, True) for c in compoundSet.getMainCompounds()] +
               [(c, False) for c in compoundSet.getOtherCompounds()])

    for compound, isMain in buckets:
        keggID = (compound.getID() or "").strip()
        if not keggID:
            continue

        entry = byID.setdefault(keggID, {"keggID": keggID, "names": [],
                                         "similarity": 0.0, "isMain": False})
        # A candidate landing in BOTH buckets (the same id matched under a
        # close synonym and a distant one) counts as main: that is the bucket
        # whose checkbox the user sees ticked.
        entry["isMain"] = entry["isMain"] or isMain

        for name in _namesFor(compound, synonymsByID):
            if name not in entry["names"]:
                entry["names"].append(name)
            score = nameSimilarity(name, title)
            if score > entry["similarity"]:
                entry["similarity"] = score

    for entry in byID.values():
        informative = [n for n in entry["names"] if not _isUninformativeName(n)]
        names = informative or entry["names"][:1]
        # Closest spelling first. KEGG returns synonyms in insertion order, so
        # without this C00065 introduces itself to the user as
        # "L-2-Amino-3-hydroxypropionic acid" and C00077 as
        # "(S)-2,5-Diaminovaleric acid" -- both correct, both useless next to a
        # checkbox for an input that said "Serine" and "Ornithine".
        entry["names"] = sorted(names, key=lambda n: -nameSimilarity(n, title))[:MAX_NAMES_PER_CANDIDATE]

    return byID


def _isSelected(compound):
    """``selected`` as the model and the DAO each spell it."""
    getter = getattr(compound, "isSelected", None)
    if callable(getter):
        return bool(getter())
    return bool(getattr(compound, "selected", False))


def needsDisambiguation(compoundSet):
    """Whether step 2 draws a card for this set.

    Mirrors ``PA_Step2CompoundSetView.needsDisambiguation`` in PA_Step2Views.js,
    and has to: a set with no card is one the user cannot see, and changing its
    ticks would move the analysis under them. Anything this returns False for is
    left exactly as the mapper left it.
    """
    mainCompounds = compoundSet.getMainCompounds()
    otherCompounds = compoundSet.getOtherCompounds()

    if len(mainCompounds) + len(otherCompounds) == 0:
        return False
    if len(otherCompounds) > 0:
        return True
    return not (len(mainCompounds) == 1 and _isSelected(mainCompounds[0]))


def _promptPool(byID, preferred):
    """The candidates a set carries forward, best match first."""
    ordered = sorted(preferred, key=lambda keggID: (-byID[keggID]["similarity"], keggID))
    return [byID[keggID] for keggID in ordered[:MAX_CANDIDATES_IN_PROMPT]]


def rankCompoundSet(compoundSet, onMapIDs, organismLabel="", synonymsByID=None):
    """Decide one compound set, or report that it needs a model.

    @param compoundSet, a FoundFeature carrying one input name's candidates
    @param {Set} onMapIDs, KEGG compound ids drawn on any pathway of the job's
           organism. Empty means "unknown", and the filter is then skipped
           rather than applied as though nothing were on the map.
    @param {String} organismLabel, for the human-readable reason string
    @param {Dict} synonymsByID, optional keggID -> [names]
    @returns {Dict} with "status" in {"skip", "resolved", "residual"}
    """
    title = compoundSet.getTitle() or ""

    if not needsDisambiguation(compoundSet):
        return {"title": title, "status": "skip",
                "reason": "step 2 draws no card for this name"}

    byID = candidatesByKeggID(compoundSet, synonymsByID)
    if len(byID) == 0:
        return {"title": title, "status": "skip", "reason": "nothing matched"}

    if len(byID) == 1:
        keggID = next(iter(byID))
        return {"title": title, "status": "resolved", "keggID": keggID,
                "tier": "deterministic", "candidates": _promptPool(byID, byID.keys()),
                "reason": "the only KEGG compound this name matched"}

    mainIDs = {k for k, v in byID.items() if v["isMain"]}

    # Rule 1 -- exactly one main candidate. The rest are substring hits on a
    # different compound ("UDP-glucose" for "Glucose") and were never ticked.
    if len(mainIDs) == 1:
        keggID = next(iter(mainIDs))
        return {"title": title, "status": "resolved", "keggID": keggID,
                "tier": "deterministic", "candidates": _promptPool(byID, byID.keys()),
                "reason": "the only candidate whose name matches the one you uploaded"}

    # Rule 2 -- exactly one main candidate this organism actually draws. A
    # compound on no pathway of the species contributes nothing downstream, so
    # dropping it cannot change a result except by removing a false positive.
    # Applied to whichever pool this set actually has. Guarded on `mainIDs` it
    # skipped the sets that need it MOST: a name where nothing scores 0.9 has
    # only fuzzy substring hits, and those went to the model unfiltered --
    # including compounds drawn on no pathway of the organism at all.
    pool = mainIDs or set(byID.keys())
    if onMapIDs:
        onMap = pool & set(onMapIDs)
        if len(onMap) == 1 and mainIDs:
            keggID = next(iter(onMap))
            where = ("a %s pathway" % organismLabel) if organismLabel else "a pathway of this organism"
            return {"title": title, "status": "resolved", "keggID": keggID,
                    "tier": "deterministic", "candidates": _promptPool(byID, pool),
                    "reason": "the only matching candidate drawn on " + where}
        if len(onMap) > 1:
            pool = onMap  # narrow what the model is asked to choose between

    # What is left is a real judgement: L- against D-, an anomer, or a generic
    # form competing with a specific one. That goes to the model.
    return {"title": title, "status": "residual", "tier": "residual",
            "candidates": _promptPool(byID, pool),
            "reason": "%d candidates remain after the deterministic rules" % len(pool)}


def partitionCompoundSets(compoundSets, onMapIDs, organismLabel="", synonymsByID=None):
    """Rank every set and split it into settled, needs-a-model, and no-card.

    @returns {Tuple} (resolved, residual, skipped) lists of decision dicts
    """
    resolved, residual, skipped = [], [], []
    for compoundSet in compoundSets:
        decision = rankCompoundSet(compoundSet, onMapIDs, organismLabel, synonymsByID)
        if decision["status"] == "resolved":
            resolved.append(decision)
        elif decision["status"] == "residual":
            residual.append(decision)
        else:
            skipped.append(decision)
    return resolved, residual, skipped


def coerceCompoundSets(rawSets):
    """Give every compound set the accessors this module expects.

    A job carries its compound sets in two different shapes depending on how it
    was reached, and only one of them has methods:

      * straight from step 1, ``processFilesContent`` leaves real FoundFeature
        objects in memory, with getTitle/getMainCompounds/getOtherCompounds;
      * reopened from MongoDB, ``PathwayAcquisitionJobDAO.findByID`` loads them
        through ``FoundFeatureDAO.findAll`` -- which is ``FeatureDAO.findAll``,
        and that constructs a plain ``Feature("")`` regardless of subclass.
        ``Feature.parseBSON`` then setattrs the stored document onto it, so the
        object HAS ``title`` and ``mainCompounds``, but ``mainCompounds`` is a
        list of raw dicts and ``getMainCompounds()`` does not exist at all.

    The recover-job response survives that because it only ever calls toBSON()
    on them, which round-trips the dicts untouched. Anything that actually reads
    the candidates does not, which is how this surfaced: pressing "Choose for
    me" on a job opened by its ?jobID= URL failed with

        'Feature' object has no attribute 'getMainCompounds'

    Normalising here rather than fixing the DAO is deliberate. FeatureDAO.findAll
    is shared by every feature the application loads, and changing what it
    returns to make one button work would be a change to the job-loading path
    of the whole product for the sake of a feature that can adapt in nine lines.

    @param {List} rawSets, whatever ``getFoundCompounds()`` returned
    @returns {List} FoundFeature instances
    """
    coerced = []
    for rawSet in (rawSets or []):
        if hasattr(rawSet, "getMainCompounds"):
            coerced.append(rawSet)
            continue
        coerced.append(_foundFeatureFromRecord(rawSet))
    return coerced


def _candidateFromRecord(record):
    """One stored candidate as a Compound, tolerating a dict or an object."""
    from src.classes.Feature import Compound

    get = record.get if isinstance(record, dict) else (lambda key, default=None:
                                                       getattr(record, key, default))
    candidate = Compound(get("ID", "") or "")
    candidate.setName(get("name", "") or "")
    # `similarity` is persisted, and `selected` is not (it exists only in the
    # browser). Carry what is there and let the ranker default the rest.
    candidate.similarity = get("similarity", 0) or 0
    selected = get("selected", None)
    if selected is not None:
        candidate.selected = bool(selected)
    return candidate


def _foundFeatureFromRecord(record):
    """Rebuild a FoundFeature from the flat record a reopened job carries."""
    get = record.get if isinstance(record, dict) else (lambda key, default=None:
                                                       getattr(record, key, default))
    found = FoundFeature(get("ID", "") or "")
    found.setTitle(get("title", "") or "")
    for candidate in (get("mainCompounds", None) or []):
        found.addMainCompound(_candidateFromRecord(candidate))
    for candidate in (get("otherCompounds", None) or []):
        found.addOtherCompound(_candidateFromRecord(candidate))
    return found


def collectKeggIDs(compoundSets):
    """Every KEGG id mentioned by these sets, for one batched synonym lookup."""
    ids = set()
    for compoundSet in compoundSets:
        for compound in (list(compoundSet.getMainCompounds()) +
                         list(compoundSet.getOtherCompounds())):
            keggID = (compound.getID() or "").strip()
            if keggID:
                ids.add(keggID)
    return ids


def loadCompoundSynonyms(keggIDs):
    """KEGG's own names for these compound ids, one query for all of them.

    The stored candidate name is whichever synonym matched the user's substring,
    which is rarely the clearest one -- C00031 can arrive named "Grape sugar".
    This is what lets a card say "D-Glucose" and what gives the model the
    synonym list it needs to tell an anomer from its parent.

    Returns ``{}`` on any failure: the ranker then falls back to stored names,
    which degrades wording and ordering but never correctness, because
    ``isMain`` does not depend on this.

    @param {Iterable} keggIDs
    @returns {Dict} keggID -> [names]
    """
    # Sorted before slicing: `collectKeggIDs` returns a set, and slicing one
    # takes whatever order it happened to iterate in. Past the cap that gave a
    # different subset of candidates their real names on every run, and so a
    # different prompt -- which is the determinism TEMPERATURE = 0.0 is set for.
    keggIDs = sorted(keggIDs or ())[:MAX_SYNONYM_LOOKUP]
    if not keggIDs:
        return {}

    handle = None
    try:
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        from src.common.DBmanager import getSharedClient, SharedClientHandle

        client = getSharedClient(MONGODB_HOST, MONGODB_PORT)
        handle = SharedClientHandle(client)
        collection = client["global-paintomics"]["kegg_compounds"]

        synonyms = {}
        for document in collection.find({"id": {"$in": keggIDs}}, {"id": 1, "name": 1}):
            name = (document.get("name") or "").strip()
            if not name or _isUninformativeName(name):
                continue
            names = synonyms.setdefault(document["id"], [])
            if name not in names:
                names.append(name)
        return synonyms
    except Exception as ex:
        logging.warning("COMPOUND DISAMBIGUATION - could not load KEGG synonyms "
                        "(%s); falling back to the names stored on the job", ex)
        return {}
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


def loadOrganismCompoundIDs(organism):
    """KEGG compound ids drawn on at least one pathway of ``organism``.

    Read from the organism's own ``kegg`` collection, which stores one document
    per pathway with a ``compounds`` list of ``{id, x, y, ...}`` entries. On any
    failure this returns an empty set, and every caller treats empty as "no
    species information" and skips the filter -- a missing organism database
    must weaken the ranking, never silently narrow it to nothing.

    @param {String} organism, a KEGG organism code such as "mmu"
    @returns {FrozenSet} compound ids, possibly empty
    """
    if not organism:
        return frozenset()

    handle = None
    try:
        from src.common.KeggInformationManager import KeggInformationManager
        handle, db = KeggInformationManager().getConnectionByOrganismCode(organism)

        ids = set()
        # Projected to the one field that is read: the compounds list also
        # carries per-pathway pixel geometry, and a 1008-pathway organism would
        # otherwise pull all of it across for nothing.
        for pathway in db.kegg.find({}, {"compounds.id": 1}):
            for compound in (pathway.get("compounds") or []):
                keggID = compound.get("id")
                if keggID:
                    ids.add(keggID)
        return frozenset(ids)
    except Exception as ex:
        logging.warning("COMPOUND DISAMBIGUATION - could not read the pathway "
                        "compounds for organism %r (%s); the species filter is "
                        "skipped for this request", organism, ex)
        return frozenset()
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
