import csv
import re
import urllib.request
from sys import stderr

SPECIES = "BTA"# Change to the one you want to donwload
DATA_DIR = '/home/tian/Downloads/database/KEGG_DATA/current/' + SPECIES.lower() + '/'
DATA = DATA_DIR + "mapping/reactome/"

stid = set()
with open( DATA + "Ensembl2Reactome.txt" ) as Ensembl2Reactome:
    ensembl2Reactome = csv.reader( Ensembl2Reactome, delimiter='\t' )
    for row in ensembl2Reactome:
        stid.add(row[1])
        stid.add(row[3])


def showPercentageSimple(n, total):
    percen = int(n / float(total) * 10)
    stderr.write("0%[" + ("#" * percen) + (" " * (10 - percen)) + "]100% [" + str(n) + "/" + str(total) + "]\t")
    return percen

stid2Dbid = {}
i = 0
for id in stid:
    i = i + 1
    showPercentageSimple( i, len(stid) )
    stderr.write('\n')
    data = urllib.request.urlopen("https://reactome.org/ContentService/data/query/"+id+"/dbid")
    dbid = re.sub( '\D', '', str( data ))
    stid2Dbid[dbid] = id
    print(stid2Dbid)


