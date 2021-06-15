import os
import json
from collections import defaultdict
from subprocess import check_call
from sys import stderr
import requests
from src.AdminTools.DBManager import wait, generateThumbnail
from src.AdminTools.scripts.common_resources.download_conf import EXTERNAL_RESOURCES

SPECIES = "BTA"# Change to the one you want to donwload


DATA_DIR = '/home/tian/Downloads/database/KEGG_DATA/current/' + SPECIES.lower() + '/'
REACTOME_DIR = DATA_DIR + "reactome"
ReactomePathwaysRelationFile = DATA_DIR + "../common/ReactomePathwaysRelation.list"
ReactomePathwayHigh = set()
ReactomePathwayLow = set()
ReactomePathwayHighList = []
ReactomePathwayLowList = []
ReactomePathwayList = []

def downloadFile(URL, fileName, outputName, delay, maxTries, checkIfExists=False):
    #stderr.write("DOWNLOADING " + URL + fileName + "\n")

    # If the file already exists, avoid downloading it again
    if checkIfExists and os.path.isfile(outputName) and os.stat(outputName).st_size > 0:
        return True

    nTry = 1
    while nTry <= maxTries:
        wait(delay)
        try:
            check_call(["curl", "--connect-timeout", "90", "--max-time", "1000",  URL + fileName, "-o", outputName])
            return True
        except Exception as e:
            nTry+=1
    raise Exception('Unable to retrieve ' + fileName + " from " + URL + "\n")

def showPercentageSimple(n, total):
    percen = int(n / float(total) * 10)
    stderr.write("0%[" + ("#" * percen) + (" " * (10 - percen)) + "]100% [" + str(n) + "/" + str(total) + "]\t \n")
    return percen

with open( ReactomePathwaysRelationFile, 'r' ) as ReactomePathwaysRelation:
    for row in ReactomePathwaysRelation:
        if SPECIES in row:
            ReactomePathwayHigh.add( row.rstrip( '\n' ).split( '\t' )[0] )
            ReactomePathwayLow.add( row.rstrip( '\n' ).split( '\t' )[1] )
            ReactomePathwayHighList.append( row.rstrip( '\n' ).split( '\t' )[0] )
            ReactomePathwayLowList.append( row.rstrip( '\n' ).split( '\t' )[1] )
            ReactomePathwayList.append( row.rstrip( '\n' ).split( '\t' ) )

ReactomePathwayLast = ReactomePathwayLow.difference (ReactomePathwayHigh)
ReactomePathwayTop = ReactomePathwayHigh.difference (ReactomePathwayLow)
ReactomeHierarchy = dict()
PATHWAY_ID = set()

i = 0


stderr.write("DOWNLOADING " + "STEP(1/2)" + "\n")


def downloadPathwayInf(pathway_id, PathwayList):
    nodes_url = EXTERNAL_RESOURCES['reactome'].get( "nodes_url" ).format( pathway_id )
    nodes_tmp_file = REACTOME_DIR + "/" + pathway_id + ".json"

    if requests.get( nodes_url ).status_code == 404:
        for item in PathwayList:
            if item[1] == pathway_id:
                downloadPathwayInf( item[0], ReactomePathwayList )  # get the upper pathway id
    else:
        downloadFile( URL=nodes_url, fileName="", outputName=nodes_tmp_file, delay=2, maxTries=10,
                      checkIfExists=True )
        diagram_url = "https://reactome.org/ContentService/exporter/diagram/" + pathway_id + ".png?diagramProfile=Modern&quality=5&margin=0&analysisProfile=Standard&held=false"
        diagram_filename = REACTOME_DIR + "/png/" + pathway_id + ".png"
        downloadFile( URL=diagram_url,
                      fileName="",
                      outputName=diagram_filename,
                      delay=2,
                      maxTries=3,
                      checkIfExists=True )
        filenameGraph = REACTOME_DIR + "/" + pathway_id + ".graph.json"
        downloadFile( URL="https://reactome.org/download/current/diagram/" + pathway_id + ".graph.json",
                      fileName="",
                      outputName=filenameGraph,
                      delay=2,
                      maxTries=3,
                      checkIfExists=True )
        generateThumbnail( diagram_filename )
        PATHWAY_ID.add( pathway_id )

from os import path
if not path.exists(REACTOME_DIR):
    os.mkdir(REACTOME_DIR)
if not path.exists(REACTOME_DIR +"/png"):
    os.mkdir(REACTOME_DIR +"/png")
if not path.exists(REACTOME_DIR + "/png/thumbnails"):
    os.mkdir(REACTOME_DIR + "/png/thumbnails")
for pathway_id in ReactomePathwayLast:
#import random
#test = random.sample(ReactomePathwayLast, 50)
#for pathway_id in test:

    i += 1
    stderr.write('\n')

    stderr.write("Start Downloading: " + pathway_id + "   ")
    showPercentageSimple(i, len(ReactomePathwayLast))


    # The function download the lowest level nodes information. If it could not find the nodes information, it will
    # go to the higher level to find the pathway information.
    downloadPathwayInf(pathway_id, ReactomePathwayList)


def findHighLevelPathway(ID, hierachy, PathwayHighList, PathwayLowList):
    for Top, subTop in hierachy.items():
        if ID in subTop:
            Top_url = EXTERNAL_RESOURCES['reactome'].get( "details_url" ).format( Top )
            subTop_url = EXTERNAL_RESOURCES['reactome'].get( "details_url" ).format( ID )
            TopName = REACTOME_DIR + '/' + Top + "details.json"
            subTopName = REACTOME_DIR + '/' + ID + "details.json"
            downloadFile( Top_url, "", TopName,
                          2, 3,
                          True)
            downloadFile( subTop_url, "", subTopName,
                          2, 3,
                          True )
            return [Top, ID]

    ID = PathwayHighList[PathwayLowList.index( ID )]
    return findHighLevelPathway( ID, hierachy, PathwayHighList, PathwayLowList )



ReactomePathwaysRelationFile = DATA_DIR + "../common/ReactomePathwaysRelation.list"
with open(ReactomePathwaysRelationFile, 'r') as ReactomePathwaysRelation:
    for row in ReactomePathwaysRelation:
        if SPECIES in row:
            ReactomePathwayHigh.add(row.rstrip('\n').split('\t')[0])
            ReactomePathwayLow.add(row.rstrip('\n').split('\t')[1])
            ReactomePathwayHighList.append(row.rstrip('\n').split('\t')[0])
            ReactomePathwayLowList.append(row.rstrip('\n').split('\t')[1])
            ReactomePathwayList.append(row.rstrip('\n').split('\t'))


ReactomeHierarchy = dict()
for key in ReactomePathwayTop:
    ReactomeHierarchy[key] = set()
    for item in ReactomePathwayList:
        if key == item[0]:
            ReactomeHierarchy[key].add(item[1])

ReactomeHierarchyPathway = defaultdict(list)
i=0
stderr.write("DOWNLOADING " + "STEP(2/2)" + "\n")
for pathway_id in PATHWAY_ID:
    i += 1
    stderr.write('\n')
    stderr.write("Start Downloading: " + pathway_id + "   ")
    showPercentageSimple( i, len( PATHWAY_ID ) )
    try:
        # Find Higher Level Pathway information and download them
        IDList = findHighLevelPathway( pathway_id, ReactomeHierarchy, ReactomePathwayHighList, ReactomePathwayLowList )
    except Exception as ex:
        IDList = [pathway_id, pathway_id]
    ReactomeHierarchyPathway[pathway_id] = IDList




REACTOME_PATHWAY = DATA_DIR + 'ReactomePathway.txt'
with open(REACTOME_PATHWAY, 'w') as output:
    for id in PATHWAY_ID:
        output.write(id + '\n')

ReactomeHierarchyPathway_DIR = DATA_DIR + "ReactomePathwayHierarchy.json"
with open(ReactomeHierarchyPathway_DIR, "w") as PATHWAY_HIERARCHY:
    json.dump(ReactomeHierarchyPathway,PATHWAY_HIERARCHY)