import os
import json
from collections import defaultdict
from subprocess import check_call, STDOUT, DEVNULL
from sys import stderr
import requests
from requests.exceptions import RequestException
from src.AdminTools.DBManager import wait, generateThumbnail, log
from src.AdminTools.scripts.common_resources.download_conf import EXTERNAL_RESOURCES
from src.conf.serverconf import KEGG_DATA_DIR


def showPercentageSimple(n, total):
    percen = int( n / float( total ) * 10 )
    log(
        "                      0%[" + ("#" * percen) + (" " * (10 - percen)) + "]100% [" + str( n ) + "/" + str( total ) + "]\t \n" )
    return percen


def isValidDownload(path, expectJson):
    """A file counts as downloaded only if it is non-empty and, for .json, parses.

    Reactome serves HTML error pages with a 200 in some failure modes, and curl
    without -f writes 4xx/5xx bodies to the output file. Checking size alone
    accepted both as valid.
    """
    if not os.path.isfile(path) or os.stat(path).st_size == 0:
        return False
    if not expectJson:
        return True
    try:
        with open(path) as handle:
            json.load(handle)
        return True
    except (ValueError, UnicodeDecodeError):
        return False


def downloadFile(URL, fileName, outputName, delay, maxTries, checkIfExists=False, required=True):
    """Fetch a URL to outputName. Returns True on success.

    Raises when required=True and every attempt failed; returns False otherwise,
    so optional assets (diagram PNGs) cannot abort a whole species download.
    """
    url = URL + fileName
    expectJson = outputName.endswith(".json")

    # A cached file is only reusable if it is actually valid. The previous check
    # accepted any non-empty file, so an error page saved as .json was cached
    # permanently and every later run skipped re-downloading it -- the reason a
    # failed run stayed broken until the download directory was deleted by hand.
    if checkIfExists and isValidDownload(outputName, expectJson):
        return True

    directory = os.path.dirname(outputName)
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmpName = outputName + ".part"
    lastError = None

    for attempt in range(1, maxTries + 1):
        wait(delay)
        try:
            # -f makes curl fail on 4xx/5xx instead of writing the error body to
            # the output file. Download to .part and rename only after the
            # content validates, so an interrupted attempt can never leave a
            # file that looks complete to the next run.
            check_call(["curl", "-sfS", "--connect-timeout", "90", "--max-time", "1000",
                        url, "-o", tmpName], stderr=DEVNULL)
            if not isValidDownload(tmpName, expectJson):
                raise Exception("empty response or malformed JSON")
            os.replace(tmpName, outputName)
            return True
        except Exception as exc:
            lastError = exc
        finally:
            if os.path.exists(tmpName):
                os.remove(tmpName)

    message = ("Unable to retrieve " + url + " after " + str(maxTries) +
               " attempts: " + str(lastError))
    if required:
        raise Exception(message + "\n")
    log("                      SKIPPED (optional): " + message)
    return False


def get_status_with_retry(url, tries=5, delay=3):
    """
    Requests the given URL with a few retries to tolerate transient network drops
    (e.g., Connection reset by peer from Reactome).
    """
    last_exc = None
    for attempt in range(1, tries + 1):
        try:
            resp = requests.get(url, timeout=120)
            return resp.status_code
        except RequestException as exc:
            last_exc = exc
            log(f"                      Connection issue ({attempt}/{tries}) for {url}: {exc}")
            wait(delay)
    if last_exc:
        raise last_exc
    return 500


def readPathwayRelations(relationFile, species):
    """Parse ReactomePathwaysRelation.list into the structures the walk needs.

    Matching on "R-<SPECIES>-" rather than a bare substring: the species code can
    otherwise appear inside an unrelated identifier and pull in foreign pathways.
    """
    marker = "R-" + species + "-"
    high, low = set(), set()
    highList, lowList, pairs = [], [], []

    with open(relationFile, 'r') as handle:
        for row in handle:
            if marker not in row:
                continue
            columns = row.rstrip('\n').split('\t')
            if len(columns) < 2:
                continue
            high.add(columns[0])
            low.add(columns[1])
            highList.append(columns[0])
            lowList.append(columns[1])
            pairs.append(columns)

    return high, low, highList, lowList, pairs


def downloadReactome( specie ):

    SPECIES = specie.upper()
    downloadDir = KEGG_DATA_DIR + "download/"
    DATA_DIR =  downloadDir + SPECIES.lower() + '/'
    REACTOME_DIR = os.path.join(DATA_DIR, "reactome")

    if os.path.isdir(DATA_DIR + "../common/"):
        ReactomePathwaysRelationFile = DATA_DIR + "../../download/common/ReactomePathwaysRelation.list"
    else:
        ReactomePathwaysRelationFile = DATA_DIR + "/../../current/common/ReactomePathwaysRelation.list"

    if not os.path.isfile(ReactomePathwaysRelationFile):
        raise Exception(
            "Reactome pathway relations file not found: " + ReactomePathwaysRelationFile +
            "\nRun the common download step with --reactome=1 first.")

    # Parsed once. This used to be read twice into the same lists, silently
    # doubling every entry and every downstream loop.
    (ReactomePathwayHigh, ReactomePathwayLow, ReactomePathwayHighList,
     ReactomePathwayLowList, ReactomePathwayList) = readPathwayRelations(
        ReactomePathwaysRelationFile, SPECIES)

    if not ReactomePathwayList:
        raise Exception(
            "No pathway relations found for species '" + specie + "' in " +
            ReactomePathwaysRelationFile +
            "\nReactome does not cover every KEGG organism; install this species with --reactome=0.")

    # Parent lookup: a low-level pathway maps to the first high-level pathway
    # that lists it. Built once instead of calling list.index() per query.
    parentOf = {}
    for high, low in zip(ReactomePathwayHighList, ReactomePathwayLowList):
        parentOf.setdefault(low, high)

    ReactomePathwayLast = ReactomePathwayLow.difference(ReactomePathwayHigh)
    ReactomePathwayTop = ReactomePathwayHigh.difference(ReactomePathwayLow)
    ReactomeHierarchy = dict()
    PATHWAY_ID = set()

    log("                      *DOWNLOADING REACTOME " + SPECIES + " STEP(1/2)..." + "\n")

    for subdirectory in ("", "png", os.path.join("png", "thumbnails")):
        os.makedirs(os.path.join(REACTOME_DIR, subdirectory), exist_ok=True)

    def downloadPathwayInf(pathway_id, visited):
        """Download one pathway's node and graph JSON, walking up on 404.

        `visited` bounds the walk. Reactome's relation file contains cycles and
        diamonds, so the previous unguarded recursion could revisit a pathway
        forever or fan out exponentially across every parent of every parent.
        """
        if pathway_id in visited:
            return
        visited.add(pathway_id)

        nodes_url = EXTERNAL_RESOURCES['reactome'].get("nodes_url").format(pathway_id)
        nodes_tmp_file = os.path.join(REACTOME_DIR, pathway_id + ".json")

        try:
            status_code = get_status_with_retry(nodes_url)
        except RequestException as exc:
            log(f"                      Skipping {pathway_id} after repeated connection errors: {exc}")
            return

        if status_code == 404:
            # No diagram at this level; try the parent instead.
            parent = parentOf.get(pathway_id)
            if parent is None:
                log("                      No diagram and no parent for " + pathway_id)
                return
            downloadPathwayInf(parent, visited)
            return

        try:
            downloadFile(URL=nodes_url, fileName="", outputName=nodes_tmp_file,
                         delay=2, maxTries=10, checkIfExists=True)
        except Exception as exc:
            log("                      Skipping " + pathway_id + ": nodes download failed: " + str(exc))
            return

        # The build reads <id>.graph.json unconditionally, so a pathway missing
        # one must not be registered -- that combination used to surface as a
        # FileNotFoundError halfway through the database build.
        filenameGraph = os.path.join(REACTOME_DIR, pathway_id + ".graph.json")
        try:
            downloadFile(URL=EXTERNAL_RESOURCES['reactome'].get("graph_url").format(pathway_id),
                         fileName="", outputName=filenameGraph,
                         delay=2, maxTries=3, checkIfExists=True)
        except Exception as exc:
            log("                      Skipping " + pathway_id + ": graph download failed: " + str(exc))
            return

        # The diagram PNG is presentation only: never fail the species for it.
        diagram_filename = os.path.join(REACTOME_DIR, "png", pathway_id + ".png")
        if downloadFile(URL=EXTERNAL_RESOURCES['reactome'].get("diagram_url").format(pathway_id),
                        fileName="", outputName=diagram_filename,
                        delay=2, maxTries=3, checkIfExists=True, required=False):
            try:
                generateThumbnail(diagram_filename)
            except Exception as exc:
                log("                      Thumbnail failed for " + pathway_id + ": " + str(exc))

        PATHWAY_ID.add(pathway_id)

    i = 0
    for pathway_id in sorted(ReactomePathwayLast):
        i += 1
        log("                      Start Downloading: " + pathway_id + "   ")
        showPercentageSimple(i, len(ReactomePathwayLast))

        # The function downloads the lowest level nodes information. If it cannot
        # find it, it walks up to the higher level pathway.
        downloadPathwayInf(pathway_id, set())

    if not PATHWAY_ID:
        raise Exception(
            "No Reactome pathways could be downloaded for species '" + specie + "'.\n"
            "Every pathway either lacked a diagram or failed to download; check network access to reactome.org.")

    def findHighLevelPathway(ID, hierachy):
        """Return [top_level_id, id], downloading the details for both.

        Walks up via parentOf with a visited set. The previous version called
        PathwayHighList[PathwayLowList.index(ID)], which raised ValueError for a
        pathway absent from the low column and recursed forever on a cycle --
        both swallowed by a bare except that substituted a wrong hierarchy.
        """
        seen = set()
        current = ID

        while current not in seen:
            seen.add(current)
            for top, subTop in hierachy.items():
                if current in subTop:
                    for identifier in (top, current):
                        downloadFile(
                            EXTERNAL_RESOURCES['reactome'].get("details_url").format(identifier),
                            "", os.path.join(REACTOME_DIR, identifier + "details.json"),
                            2, 3, True)
                    return [top, current]

            parent = parentOf.get(current)
            if parent is None:
                break
            current = parent

        raise Exception("No top-level pathway found for " + ID)

    for key in ReactomePathwayTop:
        ReactomeHierarchy[key] = set()
        for item in ReactomePathwayList:
            if key == item[0]:
                ReactomeHierarchy[key].add(item[1])

    ReactomeHierarchyPathway = defaultdict(list)

    log("                      *DOWNLOADING REACTOME " + SPECIES + "STEP(2/2)" + "\n")

    i = 0
    for pathway_id in sorted(PATHWAY_ID):
        i += 1
        log("                      Start Downloading: " + pathway_id + "   ")
        showPercentageSimple( i, len( PATHWAY_ID ) )
        try:
            # Find Higher Level Pathway information and download them
            IDList = findHighLevelPathway( pathway_id, ReactomeHierarchy )
        except Exception as ex:
            log("                      Using " + pathway_id + " as its own top level: " + str(ex))
            IDList = [pathway_id, pathway_id]
            # The build opens <id>details.json for both entries, so the
            # self-referential fallback still needs its details file present.
            try:
                downloadFile(
                    EXTERNAL_RESOURCES['reactome'].get("details_url").format(pathway_id),
                    "", os.path.join(REACTOME_DIR, pathway_id + "details.json"),
                    2, 3, True)
            except Exception as exc:
                log("                      Details download failed for " + pathway_id + ": " + str(exc))
        ReactomeHierarchyPathway[pathway_id] = IDList

    REACTOME_PATHWAY = DATA_DIR + 'ReactomePathway.txt'
    with open(REACTOME_PATHWAY, 'w') as output:
        for id in sorted(PATHWAY_ID):
            output.write(id + '\n')

    ReactomeHierarchyPathway_DIR = DATA_DIR + "ReactomePathwayHierarchy.json"
    with open(ReactomeHierarchyPathway_DIR, "w") as PATHWAY_HIERARCHY:
        json.dump(ReactomeHierarchyPathway,PATHWAY_HIERARCHY)

    log("                      Reactome download complete: " + str(len(PATHWAY_ID)) +
        " pathways for " + SPECIES + "\n")
