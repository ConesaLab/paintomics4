#!/usr/bin/env python3
"""Can each installed species actually translate its own pathway identifiers?

Why this exists
---------------
`conf/organismDB.py` names the xref table each pathway database translates
INTO. Nothing has ever checked that the named table exists, holds anything, or
holds the identifiers the pathway documents actually reference -- and all three
have failed in production, each in a way no offline test can see:

  * **absent** -- `dme` and `dre` named tables their build never produced.
    `resolveDatabaseIds` did `find_one(...).get("_id")` on a None, and every
    gene-based job on the species died at step 1 with "Oops..Internal error!".
    One user hit it 7 times in 20 minutes before reporting it.
  * **empty** -- `dosa` named `ensembl_transcript`, which its build *registers*
    before reading the input file it never received. The table exists with 0
    documents, resolves without error, and maps nothing. Every rice job
    reported success having translated not one gene.
  * **wrong identifier space** -- `cel` named `entrezgene` (numeric NCBI ids)
    while KEGG keys C. elegans on `CELE_C17G1.7`. The table is present and
    populated and matched 0 of 500 sampled pathway genes. Also silent.
  * **partially covering** -- `sly` named `entrezgene`, which held 68% of the
    gene ids its KEGG pathways reference; the rest could never be painted.

The last three are worse than the crash: a job that maps nothing still reaches
step 3 and reports success, so the failure reaches the user as an empty result
they will read as biology.

What it checks
--------------
For every installed species, for every pathway database whose pathways are
loaded, that the configured identifier and gene-symbol tables (a) exist,
(b) are non-empty, and (c) contain the gene ids the species' own pathway
documents reference. The pathway documents are the authority: they are what
mapping has to produce to paint anything.

Read-only -- it opens no cursor it does not close and writes nothing.

Usage:
    python3 checkIdentifierMapping.py                 # every installed species
    python3 checkIdentifierMapping.py --species=cel,dre
    python3 checkIdentifierMapping.py --verbose       # show the passes too

Exits 1 if any ERROR was found, so it can gate a deploy or an install.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.conf.organismDB import dicDatabases

#: How many of a database's pathway gene ids to test the configured table
#: against. The question is "does this table speak the same identifier space",
#: which a few hundred ids answer as well as fifty thousand, and the query is
#: one indexed `$in` per table.
PATHWAY_GENE_SAMPLE = 500

#: Below this share of pathway gene ids the table is not merely incomplete, it
#: is the wrong table: no plausible annotation gap loses half a gene space.
#: `sly` sat at 68% with a 100% table installed alongside it, `hsa` sits at 90%
#: on the right one, so the two populations are well separated.
COVERAGE_FLOOR = 0.80

#: `getDatabasesByOrganismCode`'s fallback for a species absent from
#: dicDatabases -- checked here too, since that is how two broken species
#: (ptr, acs) went unnoticed.
FALLBACK = [{"KEGG": "kegg_id"}, {"KEGG": "kegg_gene_symbol"}]

#: KEGG is unioned into every job by PathwayAcquisitionServlet whatever the user
#: submitted, so a KEGG finding cannot be dodged by picking another database.
MANDATORY_DATABASE = "KEGG"

ERROR, WARNING, INFO = "ERROR", "WARNING", "INFO"


class Finding(object):
    """One thing wrong with one species' mapping configuration."""

    def __init__(self, severity, organism, database, message, table=None):
        self.severity = severity
        self.organism = organism
        self.database = database
        self.table = table
        self.message = message

    def __str__(self):
        return "%-7s %-6s %-9s %s" % (self.severity, self.organism,
                                      self.database, self.message)


def _configuredTables(organism, configuration=None):
    """(identifier table, gene-symbol table) per pathway database.

    `configuration` overrides what organismDB.py says, so a caller -- a test,
    or an operator asking "what would this species do if I pointed it there?"
    -- can check a configuration that is not the installed one.
    """
    variants = configuration if configuration is not None else dicDatabases.get(organism, FALLBACK)
    identifiers = variants[0] if len(variants) > 0 else {}
    symbols = variants[1] if len(variants) > 1 else {}
    return identifiers, symbols


def _installedSources(db):
    """Pathway databases whose pathways are loaded, KEGG for an absent `source`.

    `source` was added when Reactome was, so a document without one predates
    there being anything but KEGG -- the same reading `DatabaseAvailability`
    takes.
    """
    return sorted({source or MANDATORY_DATABASE for source in db.kegg.distinct("source")})


def _pathwayGeneIDs(db, source, limit=PATHWAY_GENE_SAMPLE):
    """A sample of the gene ids this database's pathway documents reference.

    Spread evenly across the sorted gene space rather than taken from the front
    of it. Stopping at the first `limit` ids collected instead measured a few
    early pathways, and taking the first `limit` sorted ones measured a single
    prefix: on `sly` -- numeric NCBI ids -- that sampled almost only ids
    beginning "1", which happen to be the well-annotated ones, and reported 87%
    coverage for a table that holds 68% of the real space. A stride sample of
    the whole set puts both back at the true figure and stays deterministic, so
    two runs a week apart are comparable.
    """
    query = ({"$or": [{"source": MANDATORY_DATABASE}, {"source": {"$exists": False}}]}
             if source == MANDATORY_DATABASE else {"source": source})
    identifiers = set()
    for pathway in db.kegg.find(query, {"genes": 1}):
        for gene in (pathway.get("genes") or []):
            geneID = gene.get("id") if isinstance(gene, dict) else gene
            if geneID:
                identifiers.add(str(geneID))
    ordered = sorted(identifiers)
    if len(ordered) <= limit:
        return ordered
    stride = len(ordered) / float(limit)
    return [ordered[int(index * stride)] for index in range(limit)][:limit]


def _covers(db, tableID, geneIDs):
    """How many of `geneIDs` the table holds. One indexed $in, no cursor kept."""
    if not geneIDs:
        return 0
    return len(db.xref.distinct("display_id",
                                {"dbname_id": tableID, "display_id": {"$in": geneIDs}}))


def _bestAlternative(db, tables, geneIDs, exclude=None):
    """The installed table that covers these gene ids best, so a finding can
    name the fix instead of only the fault."""
    best = (None, 0)
    for name, tableID in tables.items():
        if name == exclude:
            continue
        hits = _covers(db, tableID, geneIDs)
        if hits > best[1]:
            best = (name, hits)
    return best


def checkOrganism(db, organism, configuration=None):
    """Every mapping fault this species' installed data can show. Read-only."""
    findings = []
    tables = {row["dbname"]: row["_id"] for row in db.dbname.find({}, {"dbname": 1})}
    identifierTables, symbolTables = _configuredTables(organism, configuration)

    for source in _installedSources(db):
        configuredIdentifier = identifierTables.get(source)
        if configuredIdentifier is None:
            # Not a crash: DatabaseAvailability will not offer a database it
            # cannot map, and the servlet intersects the selection with this
            # same config. The data is installed and unreachable, which is
            # worth saying out loud but is not a broken job.
            findings.append(Finding(
                INFO, organism, source,
                "pathways are installed but organismDB.py names no identifier "
                "table, so the database is never offered"))
            continue

        geneIDs = _pathwayGeneIDs(db, source)

        for role, configured in (("identifier", configuredIdentifier),
                                 ("gene-symbol", symbolTables.get(source))):
            if configured is None:
                findings.append(Finding(
                    ERROR, organism, source,
                    "no %s table is configured, so resolveDatabaseIds raises "
                    "and every job on this species fails%s"
                    % (role, " (KEGG cannot be deselected)"
                       if source == MANDATORY_DATABASE else "")))
                continue
            if configured not in tables:
                findings.append(Finding(
                    ERROR, organism, source,
                    "configured %s table '%s' does not exist -- it was never "
                    "built, so every job on this species fails at step 1%s"
                    % (role, configured,
                       " (KEGG cannot be deselected)"
                       if source == MANDATORY_DATABASE else ""),
                    table=configured))
                continue

            total = db.xref.count_documents({"dbname_id": tables[configured]})
            if total == 0:
                # The two roles fail differently. The identifier table is what
                # a feature must reach to be painted at all, so an empty one is
                # a job that maps nothing and still reports success. The symbol
                # table only feeds a separate display pass
                # (FeatureNamesToKeggIDsMapper.mapFeatureIdentifiers), so an
                # empty one costs gene symbols and nothing else -- which is the
                # ordinary state of the ~18 bacteria and fungi for which KEGG
                # publishes no symbols, not a misconfiguration.
                findings.append(Finding(
                    ERROR if role == "identifier" else WARNING, organism, source,
                    ("configured identifier table '%s' is registered but EMPTY, "
                     "so jobs map nothing and still report success" % configured)
                    if role == "identifier" else
                    ("configured gene-symbol table '%s' is registered but empty, "
                     "so features are shown by identifier and cannot be matched "
                     "by symbol" % configured),
                    table=configured))
                continue

            # Coverage is only meaningful for the identifier table: the symbol
            # table names genes for display and is not what pathway documents
            # are keyed on.
            if role != "identifier" or not geneIDs:
                continue

            hits = _covers(db, tables[configured], geneIDs)
            share = float(hits) / len(geneIDs)
            if share >= COVERAGE_FLOOR:
                continue
            bestName, bestHits = _bestAlternative(db, tables, geneIDs, exclude=configured)
            advice = ""
            if bestHits > hits:
                advice = ("; '%s' holds %d of them (%.0f%%) and is installed"
                          % (bestName, bestHits, 100.0 * bestHits / len(geneIDs)))
            findings.append(Finding(
                ERROR if hits == 0 else WARNING, organism, source,
                "configured identifier table '%s' holds %d of %d gene ids this "
                "database's pathways reference (%.0f%%)%s"
                % (configured, hits, len(geneIDs), 100.0 * share, advice),
                table=configured))
    return findings


def checkAll(client, organisms=None, suffix="-paintomics", progress=None):
    """Findings for every installed species, or just the ones named."""
    names = sorted(name for name in client.list_database_names()
                   if name.endswith(suffix) and name != "global" + suffix)
    findings = []
    for name in names:
        organism = name[:-len(suffix)]
        if organisms and organism not in organisms:
            continue
        if progress:
            progress(organism)
        findings.extend(checkOrganism(client[name], organism))
    return findings


def main(argv):
    organisms = None
    verbose = False
    for argument in argv[1:]:
        if argument.startswith("--species="):
            organisms = [code.strip() for code in argument.split("=", 1)[1].split(",") if code.strip()]
        elif argument in ("--verbose", "-v"):
            verbose = True
        elif argument in ("--help", "-h"):
            print(__doc__)
            return 0
        else:
            sys.stderr.write("Unknown argument: %s\n" % argument)
            return 2

    from pymongo import MongoClient
    from src.conf.serverconf import MONGODB_HOST, MONGODB_PORT

    client = MongoClient(MONGODB_HOST, MONGODB_PORT)
    try:
        checked = []
        findings = checkAll(client, organisms, progress=checked.append)
    finally:
        client.close()

    errors = [f for f in findings if f.severity == ERROR]
    warnings = [f for f in findings if f.severity == WARNING]
    for finding in findings:
        if finding.severity == INFO and not verbose:
            continue
        print(finding)

    print("\n%d species checked, %d error(s), %d warning(s)"
          % (len(checked), len(errors), len(warnings)))
    if not errors and not warnings:
        print("Every installed species can translate the identifiers its own "
              "pathway documents use.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
