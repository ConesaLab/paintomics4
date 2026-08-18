#!/usr/bin/env python3
"""Which pathway databases an organism can actually be analysed against.

The problem this solves
-----------------------
The database checkboxes on step 1 were a hardcoded list of three -- KEGG,
MapMan, Reactome -- offered to every visitor for every organism. Two of them
were a lie for almost every organism: `PathwayAcquisitionServlet` has always
intersected the submitted selection with the organism's own databases

    organismDB = set(dicDatabases.get(specie, [{}])[0].keys())
    jobInstance.setDatabases(list(set([u'KEGG']) | set(databases).intersection(organismDB)))

so ticking MapMan for mouse, or Reactome for tomato, changed nothing at all and
said nothing about it. The form invited a choice the server then discarded in
silence.

What "installed" means
----------------------
Two things have to be true before a database can contribute a single pathway to
a job, and neither of them is a constant:

  * **Its pathways are loaded.** Each organism has its own MongoDB database,
    `<code>-paintomics`, whose `kegg` collection holds one document per pathway
    tagged with the database it came from. `distinct("source")` answers the
    question exactly and costs about half a millisecond -- measured at 0.0018s
    cold and 0.0004s warm over the 888 documents of `mmu-paintomics`. This is
    per deployment, which is the whole point: the same code reports Reactome on
    a host where Reactome was installed and does not on a host where it was not.

  * **Its identifiers can be mapped.** `src/conf/organismDB.py` names the xref
    database that carries each organism's identifiers for each pathway
    database. Without an entry there `FeatureNamesToKeggIDsMapper` cannot turn
    a feature name into an identifier that database recognises, so its pathways
    would be present and permanently empty.

The intersection of the two is what this module reports, plus KEGG, which the
servlet forces on every job whatever was submitted.

Degrading rather than raising
-----------------------------
A step 1 that cannot be submitted is worse than a database that is missing from
the offer, so a MongoDB that cannot be reached falls back to the identifier
mapping alone -- the pre-existing behaviour, and never more permissive than the
servlet's own filter. The failure is logged once per organism per TTL, not per
request.

Usage:
    from src.common import DatabaseAvailability
    DatabaseAvailability.getInstalledDatabases("mmu")   # ['KEGG', 'Reactome']
    DatabaseAvailability.resolveDatabases("mmu", ["Reactome", "MapMan"])
"""
import logging
import threading
import time

from src.conf.organismDB import dicDatabases

#: Every database the client can draw a checkbox for, in the order it draws
#: them. Anything MongoDB reports that is not in here is ignored rather than
#: forwarded to a client that has no box to put it in.
KNOWN_DATABASES = ("KEGG", "MapMan", "Reactome", "OmniPath")

#: KEGG is not a choice. `PathwayAcquisitionServlet` unions it into every job's
#: databases regardless of what was submitted, and the checkbox that represents
#: it has always been rendered ticked and disabled.
MANDATORY_DATABASE = "KEGG"

#: The suffix `KeggInformationManager.getConnectionByOrganismCode` appends to an
#: organism code to reach its MongoDB database.
_DB_SUFFIX = "-paintomics"

#: Not an organism: the shared database that holds cross-organism data.
_NON_ORGANISM_DATABASES = frozenset(["global" + _DB_SUFFIX])

#: Installing an organism means running DBManager and, in practice, restarting;
#: this exists so that a server which is *not* restarted still notices within a
#: few minutes rather than never. The read it saves is cheap -- what it really
#: saves is opening a MongoDB connection on every keystroke in the organism
#: combo.
CACHE_TTL_SECONDS = 300

_cache = {}
_cacheLock = threading.RLock()


def _now():
    """Indirection so the TTL can be exercised without sleeping in a test."""
    return time.time()


def _mappableDatabases(organism):
    """The databases `organism` has identifier mappings for, from conf.

    `dicDatabases[organism]` is a list of variants -- the same set of databases
    spelled with different identifier types, one for accessions and one for
    symbols -- and every shipped entry lists identical keys in both. The union
    is taken rather than `[0]` because the two disagreeing is a curation slip,
    and dropping a database on the strength of one is worse than offering it:
    `FeatureNamesToKeggIDsMapper.getDatabasesByOrganismCode` hands the mapper
    both variants and it tries each in turn.

    An organism with no entry gets KEGG only, which is what the mapper's own
    fallback (`{'KEGG': "kegg_id"}`) already gives it.
    """
    variants = dicDatabases.get(organism) or []
    mappable = {MANDATORY_DATABASE}
    for variant in variants:
        try:
            mappable.update(variant.keys())
        except AttributeError:
            # A malformed conf entry is a reason to offer less, not to take
            # step 1 down with it.
            logging.warning(
                "organismDB: ignoring malformed variant %r for organism %s",
                variant, organism)
    return mappable


def _loadedSources(organism, client=None):
    """The databases whose pathways are in `organism`'s MongoDB, or None.

    None means "could not tell" -- an unreachable MongoDB, an organism with no
    database of its own -- and is deliberately distinct from the empty set,
    which would mean "asked, and nothing is loaded". The caller degrades on
    None and reports nothing but KEGG on empty.

    A pathway document written without a `source` is counted as KEGG: `source`
    was added when Reactome was, and the field's absence dates a document to
    before there was anything but KEGG.
    """
    ownClient = None
    try:
        if client is None:
            from pymongo import MongoClient
            from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
            ownClient = MongoClient(MONGODB_HOST, MONGODB_PORT,
                                    serverSelectionTimeoutMS=3000)
            client = ownClient

        sources = client[organism + _DB_SUFFIX].kegg.distinct("source")
        return {source or MANDATORY_DATABASE for source in sources}
    except Exception as ex:
        logging.warning(
            "Could not read the installed pathway databases for organism %s "
            "(%s: %s); falling back to the identifier mappings in "
            "organismDB.py", organism, type(ex).__name__, ex)
        return None
    finally:
        if ownClient is not None:
            ownClient.close()


def _order(databases):
    """KNOWN_DATABASES order, so the client never has to sort and KEGG is first."""
    return [database for database in KNOWN_DATABASES if database in databases]


def _compute(organism, client=None):
    mappable = _mappableDatabases(organism)
    loaded = _loadedSources(organism, client=client)

    if loaded is None:
        return _order(mappable)

    unmappable = loaded - mappable - set([MANDATORY_DATABASE])
    if unmappable:
        # Worth a line in the log rather than silence: the pathways are
        # installed and the analysis still cannot use them, and the fix is one
        # entry in organismDB.py.
        logging.info(
            "Organism %s has %s pathways loaded but no identifier mapping for "
            "them in organismDB.py, so they are not offered",
            organism, ", ".join(sorted(unmappable)))

    return _order((loaded & mappable) | set([MANDATORY_DATABASE]))


def getInstalledDatabases(organism, client=None, refresh=False):
    """The databases `organism` can actually be analysed against.

    Always contains KEGG. Ordered by KNOWN_DATABASES, so the caller can compare
    two results with `==` and the client can render them in a stable order.

    @param {String} organism, an organism code e.g. "mmu"
    @param {MongoClient} client, an open connection to reuse; one is opened and
           closed per call when omitted.
    @param {Boolean} refresh, skip the cached answer and read MongoDB again.
    @returns {List} of database names
    """
    if not organism:
        return [MANDATORY_DATABASE]

    with _cacheLock:
        cached = _cache.get(organism)
        if cached is not None and not refresh and cached[0] > _now():
            return list(cached[1])

    # Computed outside the lock: this reads MongoDB, and holding the lock across
    # it would serialise every organism's first lookup behind the slowest one.
    databases = _compute(organism, client=client)

    with _cacheLock:
        _cache[organism] = (_now() + CACHE_TTL_SECONDS, tuple(databases))
    return list(databases)


def getInstalledDatabasesByOrganism(refresh=False):
    """`{organism: [databases]}` for every organism installed on this server.

    The organism list comes from MongoDB rather than from `species.json`,
    because `species.json` is written once by DBManager and is a snapshot of
    what was installed when it last ran -- this repository's own copy lists
    around a hundred species on a machine that has two. What has a
    `<code>-paintomics` database is what can be analysed.

    One connection is opened for the whole sweep and reused across organisms.
    """
    client = None
    try:
        from pymongo import MongoClient
        from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT
        client = MongoClient(MONGODB_HOST, MONGODB_PORT,
                             serverSelectionTimeoutMS=3000)
        names = client.list_database_names()
    except Exception as ex:
        logging.warning(
            "Could not list the installed organisms (%s: %s); reporting the "
            "identifier mappings from organismDB.py instead",
            type(ex).__name__, ex)
        names = [organism + _DB_SUFFIX for organism in dicDatabases]
        client = None

    try:
        availability = {}
        for name in names:
            if not name.endswith(_DB_SUFFIX) or name in _NON_ORGANISM_DATABASES:
                continue
            organism = name[:-len(_DB_SUFFIX)]
            availability[organism] = getInstalledDatabases(
                organism, client=client, refresh=refresh)
        return availability
    finally:
        if client is not None:
            client.close()


def resolveDatabases(organism, requested=None, client=None):
    """The databases a job should run, given what was asked for.

    This is the rule `PathwayAcquisitionServlet` applied inline, moved here so
    that the form and the job cannot disagree about it: whatever this function
    would drop is exactly what the client refuses to offer.

    @param {String} organism, an organism code e.g. "mmu"
    @param {List} requested, the submitted selection, or None for "everything
           this organism has" -- which is what an example dataset asks for,
           having no form to submit.
    @returns {List} of database names, always including KEGG
    """
    installed = getInstalledDatabases(organism, client=client)
    if requested is None:
        return installed

    selected = set(requested) & set(installed)
    selected.add(MANDATORY_DATABASE)
    return _order(selected)


def clearCache():
    """Drop the memoised availability. For tests and for a post-install reload."""
    with _cacheLock:
        _cache.clear()
