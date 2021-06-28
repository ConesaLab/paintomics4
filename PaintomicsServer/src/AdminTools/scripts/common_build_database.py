#!/usr/bin/env python
import os, csv, json, shutil, re, itertools, glob
from collections import defaultdict, Counter
from operator import sub
from time import sleep, strftime
from sys import argv, stdout, stderr, path
from subprocess import check_call, check_output, CalledProcessError
from urllib.request import urlopen

path.insert(0, os.path.dirname(os.path.realpath(__file__)) + "/../")

class XREF_Entry (object):
    def __init__(self, display_id, dbname_id, description):
        self._id= None
        self.display_id= display_id
        self.dbname_id= dbname_id
        self.description= description

    def setID(self, _id):
        self._id = _id
    def getID(self):
        return self._id
    def setDisplayID(self, display_id):
        self.display_id = display_id
    def getDisplayID(self):
        return self.display_id
    def __str__(self):
        return "{_id : " + self._id + "display_id : " + self.display_id + "dbname_id : " + self.dbname_id + "description : " + self.description + "}"
    def __repr__(self):
        return self.__str__()

class DBNAME_Entry (object):
    def __init__(self, dbname, display_label, dbname_type):
        self._id= None
        self.dbname= dbname
        self.display_label= display_label
        self.dbname_type = dbname_type

    def setID(self, _id):
        self._id = _id
    def getID(self):
        return self._id

def generateRandomID(database = 'global'):
    import string, random
    randomID = ""
    valid = False
    while not valid:
        randomID = ''.join(random.sample(string.hexdigits*5,24))
        valid = ((not randomID in xref[database]) and (not randomID in transcript2xref[database]) and (not randomID in dbname))

    return randomID

def insertXREF(item, database = 'global'):
    id_key = item.display_id
    elemAux = ALL_ENTRIES.get(id_key+"#"+item.dbname_id, None)

    if elemAux == None: #did not exists
        item.setID(generateRandomID(database))
        xref[database][item.getID()] = item
        ALL_ENTRIES[id_key+"#"+item.dbname_id] = item
        # For Reactome save the real key in ALL_ENTRIES based on the display name
        KEY_ENTRIES[id_key] = id_key+"#"+item.dbname_id
        elemAux=item

    return elemAux.getID()

def findXREF(entry_name, db_id):
    return ALL_ENTRIES.get(entry_name + "#" + db_id, None)

def findXREFByEntry(entry_name):
    return ALL_ENTRIES.get(KEY_ENTRIES.get(entry_name, None), None)

def deleteXREF(itemID, database = 'global'):
    del ALL_ENTRIES[xref[database].get(itemID).display_id + "#" + xref[database].get(itemID).dbname_id]
    del xref[database][itemID]

def insertTR_XREF(item_id, transcript_id, database = 'global'):
    elemAux = transcript2xref[database].get(transcript_id, set([]))
    if not transcript_id in transcript2xref[database]:
        transcript2xref[database][transcript_id] = elemAux
    elemAux.add(item_id)

    elemAux = xref2transcript[database].get(item_id, set([]))
    if not item_id in xref2transcript[database]:
        xref2transcript[database][item_id] = elemAux
    elemAux.add(transcript_id)

def insertDatabase(item):
    elemAux = ALL_DBS.get(item.dbname, None)

    if elemAux == None: #did not exists
        item.setID(generateRandomID())
        dbname[item.getID()] = item
        ALL_DBS[item.dbname] = item
        elemAux = item

    return elemAux.getID()

# def translate(featureName, destinationDB):
#     found=[]
#
#     #FIND THE ID FOR DATABASE
#     for item in dbname.itervalues():
#         if(item.dbname == destinationDB):
#             destinationDB = item.getID()
#             break
#
#     #FIND THE FEATURES WHOSE NAME MATCH TO PROVIDED
#     for item in xref.itervalues():
#         if(item.display_id == featureName):
#             found.append(item.getID())
#
#     #FOR EACH MATCH, FIND THE ASSOCIATED TRANSCRIPTS
#     found2 = set([])
#     for item in found:
#         for key, value in transcript2xref.iteritems():
#             if(item in value): #IF THE TRANSCRIPT IS ASSOCIATED TO CURRENT ITEM
#                 found2 = found2.union(value) #MERGE ALL POSSIBLE MATCHES (WE WILL FILTER LATER BY DB ID)
#
#     #FOR EACH MATCHED ITEM, FILTER BY DATABASE ID
#     found=[]
#     for item_id in found2:
#         item = xref.get(item_id)
#         if(item.dbname_id == destinationDB):
#             found.append(item)
#
#     return found

def showPercentage(n, total, prev, errorMessage):
    percen = int(n/float(total)*10)
    stderr.write("0%[" + ("#"*percen) + (" "*(10 - percen)) + "]100% [" + str(n) + "/" + str(total) + "]\t"+ errorMessage + "\r" )
    return percen

#**************************************************************************
#  ______ _   _  _____ ______ __  __ ____  _
# |  ____| \ | |/ ____|  ____|  \/  |  _ \| |
# | |__  |  \| | (___ | |__  | \  / | |_) | |
# |  __| | . ` |\___ \|  __| | |\/| |  _ <| |
# | |____| |\  |____) | |____| |  | | |_) | |____
# |______|_| \_|_____/|______|_|  |_|____/|______|
#
#**************************************************************************
def processEnsemblData():
    """
    # ENSEMBL MAPPING FILE CONTAINS THE FOLLOWING COLUMNS
    # 1. Ensembl Gene ID
    # 2. EntrezGene ID
    # 3. Ensembl Protein ID
    # 4. Ensembl Transcript ID
    """
    FAILED_LINES["ENSEMBL"]=[]

    resource = EXTERNAL_RESOURCES.get("ensembl")[0]
    file_name= DATA_DIR + "mapping/" + resource.get("output")
    if not os.path.isfile(file_name):
        stderr.write("Unable to find the ENSEMBL MAPPING file: " + file_name + "###########################################333")
        exit(1)

    #Get line count (for percentage)
    total_lines = int(check_output(['wc', '-l', file_name]).decode('utf-8').split(" ")[0])

    #Register databases and get the assigned IDs
    ensembl_transcript_db_id = insertDatabase(DBNAME_Entry("ensembl_transcript", "Ensembl transcript", "Identifier"))
    ensembl_gene_db_id = insertDatabase(DBNAME_Entry("ensembl_gene", "Ensembl gene", "Identifier"))
    ensembl_peptide_db_id = insertDatabase(DBNAME_Entry("ensembl_peptide", "Ensembl protein", "Identifier"))
    entrezgene_db_id = insertDatabase(DBNAME_Entry("entrezgene", "EntrezGene ID", "Identifier"))

    #Process files
    stderr.write("PROCESSING ENSEMBL MAPPING FILE...\n")
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        i =0
        prev=-1
        errorMessage=""

        for row in rows:
            i+=1
            prev = showPercentage(i, total_lines, prev, errorMessage)
            try:
                ensembl_gi = row[0]
                entrez_gi = row[1]
                ensembl_pi = row[2]
                ensembl_ti = row[3]

                if ensembl_ti == "": #ALWAYS FALSE
                    raise Exception("Empty ENSEMBL transcript value.")

                ensembl_ti = insertXREF(XREF_Entry(ensembl_ti, ensembl_transcript_db_id, resource.get("description")))
                insertTR_XREF(ensembl_ti, ensembl_ti)

                if ensembl_gi != "": #ALWAYS TRUE
                    ensembl_gi = insertXREF(XREF_Entry(ensembl_gi, ensembl_gene_db_id, resource.get("description")))
                    insertTR_XREF(ensembl_gi, ensembl_ti)

                if entrez_gi != "":
                    entrez_gi = insertXREF(XREF_Entry(entrez_gi, entrezgene_db_id, resource.get("description")))
                    insertTR_XREF(entrez_gi, ensembl_ti)

                if ensembl_pi != "":
                    ensembl_pi = insertXREF(XREF_Entry(ensembl_pi, ensembl_peptide_db_id, resource.get("description")))
                    insertTR_XREF(ensembl_pi, ensembl_ti)

            except Exception as ex:
                errorMessage = "FAILED WHILE PROCESSING ENSEMBL MAPPING FILE [line " + str(i) + "]: "+ str(ex)
                FAILED_LINES["ENSEMBL"].append([errorMessage] + row)
    csvfile.close()

    TOTAL_FEATURES["ENSEMBL"]=total_lines

    return total_lines

#**************************************************************************
#
# |  __ \|  ____|  ____/ ____|  ____/ __ \
# | |__) | |__  | |__ | (___ | |__ | |  | |
# |  _  /|  __| |  __| \___ \|  __|| |  | |
# | | \ \| |____| |    ____) | |___| |__| |
# |_|  \_\______|_|   |_____/|______\___\_\
#
#**************************************************************************
def processRefSeqData():
    """
    # REFSEQ MAPPING FILE CONTAINS THE LOT OF COLUMNS
    # 1. tax_id
    # 2. Entrez ID
    # ...
    # 4. RNA_nucleotide_accession.version
    # 5. RNA_nucleotide_gi
    # 6. protein_accession.version
    # 7. protein_gi
    # ...
    """
    stderr.write("\n\nPROCESSING REFSEQ MAPPING FILE...\n")
    FAILED_LINES["REFSEQ"]=[]

    #Get settings for the file
    resource = EXTERNAL_RESOURCES.get("refseq")[0]
    file_name= DATA_DIR + "mapping/" + resource.get("output")

    #Check if file exists
    if not os.path.isfile(file_name):
        stderr.write("Unable to find the REFSEQ MAPPING file: " + file_name)
        exit(1)

    #Extract the file in a temporal directory
    stderr.write("  * EXTRACTING FILE...\n")
    command = "gunzip -c  " + file_name + " | awk '{if($1==\"" + str(resource.get("specie-code")) + "\"){print $0}}' > /tmp/build.tmp"
    check_call(command, shell=True)
    stderr.write("  * PROCESSING FILE...\n")

    #Count the number of genes (for percentage)
    total_lines = int(check_output(['wc', '-l', "/tmp/build.tmp"]).decode('utf-8').split(" ")[0])

    #Register the databases
    refseq_rna_predicted_db_id = insertDatabase(DBNAME_Entry("refseq_rna_predicted", "RefSeq RNA nucleotide accession (predicted)", "Identifier"))
    refseq_rna_curated_db_id = insertDatabase(DBNAME_Entry("refseq_rna_curated", "RefSeq RNA nucleotide accession (curated)", "Identifier"))
    refseq_peptide_predicted_db_id = insertDatabase(DBNAME_Entry("refseq_peptide_predicted", "RefSeq protein accession (predicted)", "Identifier"))
    refseq_peptide_curated_db_id = insertDatabase(DBNAME_Entry("refseq_peptide_curated", "RefSeq protein accession (curated)", "Identifier"))
    entrezgene_db_id = insertDatabase(DBNAME_Entry("entrezgene", "EntrezGene ID", "Identifier"))

    #Add the entries for tables
    with open("/tmp/build.tmp", "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        i =0
        prev=-1
        errorMessage=""

        for row in rows:
            i+=1
            prev = showPercentage(i, total_lines, prev, errorMessage)
            try:
                entrez_tax = row[0]

                if entrez_tax != str(resource.get("specie-code")):
                    continue

                entrez_gi = row[1]
                rna_acc   = row[3]
                rna_gi    = row[4]
                prot_acc  = row[5]
                prot_gi   = row[6]

                if rna_acc == "-":
                    raise Exception("Empty REFSEQ transcript value.")

                if rna_acc[0].lower() == "x": #predicted
                    rna_acc = insertXREF(XREF_Entry(rna_acc, refseq_rna_predicted_db_id, resource.get("description")))
                else:
                    rna_acc = insertXREF(XREF_Entry(rna_acc, refseq_rna_curated_db_id, resource.get("description")))
                insertTR_XREF(rna_acc, rna_acc)

                if entrez_gi != "-": #ALWAYS TRUE
                    entrez_gi = insertXREF(XREF_Entry(entrez_gi, entrezgene_db_id, resource.get("description")))
                    insertTR_XREF(entrez_gi, rna_acc)

                if prot_acc != "-":
                    if prot_acc[0].lower() == "x": #predicted
                        internalID = insertXREF(XREF_Entry(prot_acc, refseq_peptide_predicted_db_id, resource.get("description")))
                    else:
                        internalID = insertXREF(XREF_Entry(prot_acc, refseq_peptide_curated_db_id, resource.get("description")))

                    insertTR_XREF(internalID, rna_acc)

            except Exception as ex:
                errorMessage= "FAILED WHILE PROCESSING REFSEQ MAPPING FILE [line " + str(i) + "]: "+ str(ex)
                FAILED_LINES["REFSEQ"].append([errorMessage] + row)

    csvfile.close()
    os.remove("/tmp/build.tmp")

    TOTAL_FEATURES["REFSEQ"]=total_lines

    return total_lines

def processRefSeqGeneSymbolData():
    """
    # REFSEQ MAPPING FILE CONTAINS THE LOT OF COLUMNS
    # 1. tax_id
    # 2. Entrez ID
    # 3. Symbol
    # 4. ...
    # 5. Synonyms
    # ...
    """
    FAILED_LINES["REFSEQ GENE SYMBOL"]=[]

    stderr.write("\n\nPROCESSING REFSEQ GENE SYMBOL MAPPING FILE...\n")

    #Get settings for the file
    resource = EXTERNAL_RESOURCES.get("refseq")[1]
    file_name= DATA_DIR + "mapping/" + resource.get("output")

    #Check if file exists
    if not os.path.isfile(file_name):
        stderr.write("Unable to find the REFSEQ GENE SYMBOL MAPPING file: " + file_name)
        exit(1)

    #Extract the file in a temporal directory
    stderr.write("  * EXTRACTING FILE...\n")
    command = "gunzip -c  " + file_name + " | awk '{if($1==\"" + str(resource.get("specie-code")) + "\"){print $0}}' > /tmp/build.tmp"
    check_call(command, shell=True)
    stderr.write("  * PROCESSING FILE...\n")

    #Count the number of genes (for percentage)
    total_lines = int(check_output(['wc', '-l', "/tmp/build.tmp"]).decode('utf-8').split(" ")[0])

    #Register the databases
    refseq_gene_symbol_db_id = insertDatabase(DBNAME_Entry("refseq_gene_symbol", "RefSeq Gene Symbol", "Identifier"))
    refseq_gene_symbol_synonyms_db_id = insertDatabase(DBNAME_Entry("refseq_gene_symbol_synonyms", "RefSeq Gene Symbol Synonyms", "Identifier"))
    entrezgene_db_id = insertDatabase(DBNAME_Entry("entrezgene", "EntrezGene ID", "Identifier"))

    #Add the entries for tables
    with open("/tmp/build.tmp", "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        i =0
        prev=-1
        errorMessage=""

        for row in rows:
            i+=1
            prev = showPercentage(i, total_lines, prev, errorMessage)
            try:
                #CHECK IF THE SPECIE CODE IS VALID
                entrez_tax = row[0]
                if entrez_tax != str(resource.get("specie-code")):
                    continue

                #READ THE VALUES
                entrez_gi    = row[1]
                gene_symbol  = row[2]
                synonyms     = row[4]

                if gene_symbol == "-":
                    raise Exception("Empty REFSEQ Gene Symbol value.")

                #CHECK ENTREZ ID WAS PREVIOSLY REGISTERED
                entrez_gi = findXREF(entrez_gi, entrezgene_db_id)
                if entrez_gi == None:
                    raise Exception("ENTREZ ID not found at database.")

                #GET THE SYNONYMS IN A LIST(IF ANY)
                if synonyms == "-":
                    gene_symbols=[]
                else:
                    gene_symbols = synonyms.split("|")

                #ADD A NEW ENTRY FOR EACH GENE SYMBOL
                gene_symbol = insertXREF(XREF_Entry(gene_symbol, refseq_gene_symbol_db_id, resource.get("description")))

                aux=[gene_symbol]
                for gene_symbol in gene_symbols:
                    gene_symbol = insertXREF(XREF_Entry(gene_symbol, refseq_gene_symbol_synonyms_db_id, resource.get("description")))
                    aux.append(gene_symbol)

                gene_symbols=aux

                #GET ALL THE TRANSCRIPT IDS ASSOCIATED WITH THE ENTREZ ID
                transcript_ids = xref2transcript['global'].get(entrez_gi.getID(), [])

                #IF NO TRANSCRIPTS REMOVE THE ENTRIES AND FAIL (SHOULD NOT HAPPEN)
                if len(transcript_ids) == 0:
                    for gene_symbol in gene_symbols:
                        deleteXREF(gene_symbol)
                    raise Exception("No transcript ID associated for current ENTREZ ID.")

                #IF THERE IS AT LEAST ONE TRANSCRIPT, CREATE THE ASSOCIATIONS
                for transcript_id in transcript_ids:
                    for gene_symbol in gene_symbols:
                        insertTR_XREF(gene_symbol, transcript_id)

            except Exception as ex:
                errorMessage= "FAILED WHILE PROCESSING REFSEQ GENE SYMBOL MAPPING FILE [line " + str(i) + "]: "+ str(ex)
                FAILED_LINES["REFSEQ GENE SYMBOL"].append([errorMessage] + row)

    csvfile.close()
    os.remove("/tmp/build.tmp")

    TOTAL_FEATURES["REFSEQ GENE SYMBOL"]=total_lines

    return total_lines


#**************************************************************************
#  _    _ _   _ _____ _____  _____   ____ _______
# | |  | | \ | |_   _|  __ \|  __ \ / __ \__   __|
# | |  | |  \| | | | | |__) | |__) | |  | | | |
# | |  | | . ` | | | |  ___/|  _  /| |  | | | |
# | |__| | |\  |_| |_| |    | | \ \| |__| | | |
#  \____/|_| \_|_____|_|    |_|  \_\\____/  |_|
#
#**************************************************************************
def processUniProtData():
    """
    # UNIPROT MAPPING FILE CONTAINS THE LOT OF COLUMNS
    # 1. UniProtKB-AC
    # 2. UniProtKB-ID
    # 3. GeneID (EntrezGene)
    # 4. RefSeq (Peptide)
    # 5. GI
    # 6. PDB
    # ...
    # 12. PIR
    # ...
    # 15. UniGene
    # ...
    # 19. Ensembl
    # 20. Ensembl_TRS
    # 21. Ensembl_PRO
    """
    FAILED_LINES["UNIPROT"]=[]
    stderr.write("\n\nPROCESSING UniProt MAPPING FILE...\n")

    resource = EXTERNAL_RESOURCES.get("uniprot")[0]
    file_name= DATA_DIR + "mapping/" + resource.get("output")
    if not os.path.isfile(file_name):
        stderr.write("\n\nUnable to find the UniProt MAPPING file: " + file_name + "\n")
        exit(1)

    #Extract the file in a temporal directory
    stderr.write("  * EXTRACTING FILE...\n")
    command = "gunzip -c  " + file_name + " > /tmp/build.tmp"
    check_call(command, shell=True)

    stderr.write("  * PROCESSING FILE...\n")
    #Get line count (for percentage)
    total_lines = int(check_output(['wc', '-l', '/tmp/build.tmp']).decode('utf-8').split(" ")[0])

    #Register databases and get the assigned IDs
    uniprot_acc_db_id = insertDatabase(DBNAME_Entry("uniprot_acc", "UniProt Accession", "Identifier"))
    uniprot_id_db_id = insertDatabase(DBNAME_Entry("uniprot_id", "UniProt Identifier", "Identifier"))
    ensembl_transcript_db_id = insertDatabase(DBNAME_Entry("ensembl_transcript", "Ensembl transcript", "Identifier"))
    refseq_peptide_predicted_db_id = insertDatabase(DBNAME_Entry("refseq_peptide_predicted", "RefSeq protein accession (predicted)", "Identifier"))
    refseq_peptide_curated_db_id = insertDatabase(DBNAME_Entry("refseq_peptide_curated", "RefSeq protein accession (curated)", "Identifier"))

    #Process files
    with open('/tmp/build.tmp', "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        i =0
        prev=-1
        errorMessage=""
        for row in rows:
            i+=1
            prev = showPercentage(i, total_lines, prev, errorMessage)
            errorMessage=""
            try:
                uniprot_acc = row[0]
                uniprot_id  = row[1]
                ref_prot_acc= row[3]
                ensembl_ti  = row[19]

                if ensembl_ti == "" and ref_prot_acc == "":
                    raise Exception("Empty UniProt transcript information.")

                uniprot_acc = insertXREF(XREF_Entry(uniprot_acc, uniprot_acc_db_id, resource.get("description")))
                uniprot_id  = insertXREF(XREF_Entry(uniprot_id, uniprot_id_db_id, resource.get("description")))

                transcript_ids = []
                if ensembl_ti != "":
                    ensembl_ti = ensembl_ti.replace(" ", "").split(";")
                    #FOR EACH TRANSCRIPT
                    for transcript_id in ensembl_ti:
                        #GET THE ID FOR THE ENTRY
                        transcript_id = findXREF(transcript_id, ensembl_transcript_db_id)
                        #IF THE TRANSCRIPT EXISTS
                        if transcript_id != None:
                            transcript_ids.append(transcript_id.getID())

                if ref_prot_acc != "":
                    ref_prot_acc = ref_prot_acc.replace(" ", "").split(";")
                    for peptide_acc in ref_prot_acc:
                        #GET THE ID FOR THE ENTRY
                        peptide_id = findXREF(peptide_acc, refseq_peptide_predicted_db_id)
                        if peptide_id == None:
                            peptide_id = findXREF(peptide_acc, refseq_peptide_curated_db_id)

                        if peptide_id != None:
                            # GET THE ASSOCIATED TRANSCRIPT ID FOR CURRENT PEPTIDE
                            transcript_ids += xref2transcript['global'].get(peptide_id.getID(), [])

                #IF NO TRANSCRIPTS REMOVE THE ENTRIES AND FAIL (SHOULD NOT HAPPEN)
                if len(transcript_ids) == 0:
                    deleteXREF(uniprot_id)
                    deleteXREF(uniprot_acc)
                    raise Exception("UniProt transcripts are not in Database (possible retired transcripts)")

                #IF THERE IS AT LEAST ONE TRANSCRIPT, CREATE THE ASSOCIATIONS
                for transcript_id in transcript_ids:
                    insertTR_XREF(uniprot_id, transcript_id)
                    insertTR_XREF(uniprot_acc, transcript_id)
            except Exception as ex:
                errorMessage = "FAILED WHILE PROCESSING UNIPROT MAPPING FILE [line " + str(i) + "]: "+ str(ex)
                FAILED_LINES["UNIPROT"].append([errorMessage] + row)

    csvfile.close()
    os.remove("/tmp/build.tmp")

    TOTAL_FEATURES["UNIPROT"]=total_lines

    return total_lines

#**************************************************************************
# __      ________ _____
# \ \    / /  ____/ ____|   /\
#  \ \  / /| |__ | |  __   /  \
#   \ \/ / |  __|| | |_ | / /\ \
#    \  /  | |___| |__| |/ ____ \
#     \/   |______\_____/_/    \_\
#
#**************************************************************************
def processVegaData():
    """
    #
    # ENSEMBL MAPPING FILE CONTAINS THE FOLLOWING COLUMNS
    # 1. Vega Gene ID
    # 2. EntrezGene ID
    # 3. Vega Protein ID
    # 4. Vega Transcript ID
    # 5. Ensembl Transcript ID
    """
    FAILED_LINES["VEGA"]=[]
    resource = EXTERNAL_RESOURCES.get("vega")[0]
    file_name= DATA_DIR + "mapping/" + resource.get("output")
    if not os.path.isfile(file_name):
        stderr.write("\n\nUnable to find the ENSEMBL VEGA MAPPING file: " + file_name + "\n")
        exit(1)

    #Get line count (for percentage)
    total_lines = int(check_output(['wc', '-l', file_name]).decode('utf-8').split(" ")[0])

    #Register databases and get the assigned IDs
    ensembl_transcript_db_id = insertDatabase(DBNAME_Entry("ensembl_transcript", "Ensembl transcript", "Identifier"))
    vega_transcript_db_id = insertDatabase(DBNAME_Entry("vega_transcript", "Vega transcript", "Identifier"))
    vega_gene_db_id = insertDatabase(DBNAME_Entry("vega_gene", "Vega gene", "Identifier"))
    vega_peptide_db_id = insertDatabase(DBNAME_Entry("vega_peptide", "Vega protein", "Identifier"))
    entrezgene_db_id = insertDatabase(DBNAME_Entry("entrezgene", "EntrezGene ID", "Identifier"))

    #Process files
    stderr.write("\n\nPROCESSING ENSEMBL Vega MAPPING FILE...\n")
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter=',')
        i =0
        prev=-1
        errorMessage=""

        for row in rows:
            i+=1
            prev = showPercentage(i, total_lines, prev, errorMessage)
            try:
                vega_gi = row[0]
                entrez_gi = row[1]
                vega_pi = row[2]
                vega_ti = row[3]
                ensembl_ti = row[4]

                if ensembl_ti == "": #ALWAYS FALSE
                    raise Exception("Empty ENSEMBL Vega transcript value.")

                ensembl_ti = insertXREF(XREF_Entry(ensembl_ti, ensembl_transcript_db_id, resource.get("description")))
                #TODO: IF TI NOT IN DB?

                if vega_ti != "": #ALWAYS TRUE
                    vega_ti = insertXREF(XREF_Entry(vega_ti, vega_transcript_db_id, resource.get("description")))
                    insertTR_XREF(vega_ti, ensembl_ti)

                if vega_gi != "": #ALWAYS TRUE
                    vega_gi = insertXREF(XREF_Entry(vega_gi, vega_gene_db_id, resource.get("description")))
                    insertTR_XREF(vega_gi, ensembl_ti)

                if entrez_gi != "":
                    entrez_gi = insertXREF(XREF_Entry(entrez_gi, entrezgene_db_id, resource.get("description")))
                    insertTR_XREF(entrez_gi, ensembl_ti)

                if vega_pi != "":
                    vega_pi = insertXREF(XREF_Entry(vega_pi, vega_peptide_db_id, resource.get("description")))
                    insertTR_XREF(vega_pi, ensembl_ti)

            except Exception as ex:
                errorMessage = "FAILED WHILE PROCESSING ENSEMBL VEGA MAPPING FILE [line " + str(i) + "]: "+ str(ex)
                FAILED_LINES["VEGA"].append([errorMessage] + row)
    csvfile.close()

    TOTAL_FEATURES["VEGA"]=total_lines

    return total_lines


def processMapManMappingData():
    global external_mapping, kegg_id_2_refseq_tid

    # TODO: split into different types of IDs? Seems like potato can have at least two (PGSC and ITAG)
    # keep it simple just to try.
    #STEP 1. Register databases and get the assigned IDs
    mapman_gene_db_id = insertDatabase(DBNAME_Entry("mapman_gene_id", "MapMan Gene identifier", "Identifier"))
    kegg_id_db_id = insertDatabase(DBNAME_Entry("kegg_id", "KEGG Feature ID", "Identifier"))
    # mapman_id_db_id = insertDatabase(DBNAME_Entry("mapman_id", "Mapman Feature ID", "Identifier"))

    # XREF descriptions
    mapman_gene_desc = "Extracted from MapMan Database"
    # mapman_feature_desc = "Extracted from Mapman Database (GENE 2 MAPMAN file)"
    ncbi_kegg_desc = "Extracted from KEGG Database (NCBI Gene ID 2 KEGG  file)"

    #STEP 2. READ THE UniProt 2 KEGG FILE but DO NOT process it as it will be done in "processKEGGMappingData
    # Instead, load the contents and keep as a link table to KEGG gene ids
    ncbi_file_name= DATA_DIR + "mapping/" + "ncbi-geneid2kegg.list"
    if not os.path.isfile(ncbi_file_name):
        stderr.write("\n\nUnable to find the NCBI 2 KEGG MAPPING file: " + ncbi_file_name + "\n")
        exit(1)

    # File containing MapMan metabolites to MapMan feature IDs



    mapman_cpd_resource = COMMON_RESOURCES.get("mapman").get("metabolites")
    mapman_cpd_file_name = DATA_DIR + "mapping/" + mapman_cpd_resource.get("output")
    if not os.path.isfile(mapman_cpd_file_name):
        stderr.write("\n\nUnable to find the MapMan Compound 2 MapMan ID MAPPING file: " + mapman_cpd_file_name + "\n")
        exit(1)

    # File containing MapMan genes to MapMan feature IDs
    mapman_resource = EXTERNAL_RESOURCES.get("mapman_gene")[0]
    mapman_file_name = DATA_DIR + "mapping/" + mapman_resource.get("output")
    if not os.path.isfile(mapman_file_name):
        stderr.write("\n\nUnable to find the MapMan Gene 2 MapMan ID MAPPING file: " + mapman_file_name + "\n")
        exit(1)

    # File containing MapMan genes to NCBI genes
    mapman_kegg_resource = EXTERNAL_RESOURCES.get("mapman_kegg")[0]
    mapman_kegg_file_name = DATA_DIR + "mapping/" + mapman_kegg_resource.get("output")
    if not os.path.isfile(mapman_kegg_file_name):
        stderr.write("Unable to find the MapMan Gene to KEGG ID MAPPING file: " + mapman_kegg_file_name)
        exit(1)

    # Insert compounds
    processMapMan2CompoundSymbolMappingData(mapman_cpd_file_name)

    # Initialize the mapping_dict NCBI Gene ID => [many possible KEGG_IDs]
    ncbi_mapping_dict = defaultdict(list)

    with open(ncbi_file_name, 'r') as mapping_file:
        dict_reader = csv.DictReader(mapping_file, fieldnames=["ncbi_gene", "kegg_id"], delimiter="\t")
        for mapping_entry in dict_reader:
            # Remove prefix
            ncbi_mapping_dict[mapping_entry["ncbi_gene"].replace("ncbi-geneid:", "")] += [mapping_entry["kegg_id"].replace(SPECIE + ":", "")]

    # Initialize the mapping dict MapmMan Gene => [many possible MapMan feature IDs]
    external_mapping = defaultdict(list)

    with open(mapman_file_name, 'r') as mapping_file:
        dict_reader = csv.DictReader(mapping_file, fieldnames=["mapman_gene", "version", "mapman_ids"], delimiter="\t")
        for mapping_entry in dict_reader:
            # Each gene might be associated to multiple terms
            ontology_terms = mapping_entry["mapman_ids"].split()

            # Prepare the dictionary in the form <Term>: [<list of genes>]
            for ontology_term in ontology_terms:
                external_mapping[ontology_term].extend([mapping_entry["mapman_gene"]])

    total_lines = int(check_output(['wc', '-l', mapman_kegg_file_name]).decode('utf-8').split(" ")[0])

    with open(mapman_kegg_file_name, 'r') as mapman_file:
        i = 0
        prev = -1
        errorMessage = ""
        file_reader = csv.reader(mapman_file, delimiter="\t")
        genes_present = set()

        for mapping_entry in file_reader:
            i += 1

            ncbi_gene_id = mapping_entry[1]
            gene_id = mapping_entry[0]

            prev = showPercentage(i, total_lines, prev, errorMessage)

            # If the gene is present in the mapping dict, we use the KEGG ID transcript id to link
            # each with one another, otherwise we leave the gene to be linked with "itself" later
            # in the dump process.
            try:
                external_gi = insertXREF(XREF_Entry(gene_id, mapman_gene_db_id, mapman_gene_desc))

                # Keep track of the genes located in this file
                genes_present.add(gene_id)

                # Insert link with KEGG features (if available)
                if ncbi_gene_id in ncbi_mapping_dict:

                        mapped_kegg_ids = ncbi_mapping_dict[ncbi_gene_id]

                        # Add a reference for each one
                        for kegg_id in mapped_kegg_ids:
                            kegg_gi = insertXREF(XREF_Entry(kegg_id, kegg_id_db_id, ncbi_kegg_desc))

                            transcript_id = kegg_id_2_refseq_tid.get(kegg_gi,
                                                                 generateRandomID())  # Try to reuse the ids for random transcripts
                            kegg_id_2_refseq_tid[kegg_gi] = transcript_id

                            insertTR_XREF(external_gi, transcript_id)
                            insertTR_XREF(kegg_gi, transcript_id)

                # If no mates were linked, add a transcript with itself
                if not external_gi in xref2transcript['global']:
                    insertTR_XREF(external_gi, generateRandomID())
            except Exception as ex:
                errorMessage = "FAILED WHILE PROCESSING " + mapman_kegg_file_name +" MAPPING FILE [line " + str(i) + "]: "+ str(ex)

        # If we still have info about other genes not present in that file, add them
        all_genes = set(list(itertools.chain.from_iterable(external_mapping.values())))

        for remaining_gene in all_genes.difference(genes_present):
            gene_gi = insertXREF(XREF_Entry(remaining_gene, mapman_gene_db_id, mapman_gene_desc))

            insertTR_XREF(gene_gi, generateRandomID())

    version = open(DATA_DIR + 'MAPMAN_MAPPING', 'w')
    version.write("# CREATION DATE:\t" + strftime("%Y%m%d %H%M"))
    version.close()

    return total_lines


#**************************************************************************
#  _  ________ _____  _____
# | |/ /  ____/ ____|/ ____|
# | ' /| |__ | |  __| |  __
# |  < |  __|| | |_ | | |_ |
# | . \| |___| |__| | |__| |
# |_|\_\______\_____|\_____|
#
#**************************************************************************
def processKEGGMappingData():
    """
    # KEGG MAPPING FILE CONTAINS THE FOLLOWING COLUMNS
    # WE USE THIS FUNCTION WHEN NO EXTERNAL DATA IS AVAILABLE
    # 1. EXTERNAL DB ID (uniprot acc, entrezid,...)
    # 2. KEGG DB ID (entrezid, Ensembl id...)
    """
    #STEP 1. Register databases and get the assigned IDs
    random_transcript_db_id = insertDatabase(DBNAME_Entry("random_transcript_db_id", "Random transcripts (not real)", "Identifier"))
    uniprot_acc_db_id = insertDatabase(DBNAME_Entry("uniprot_acc", "UniProt Accession", "Identifier"))
    ncbi_geneid_db_id = insertDatabase(DBNAME_Entry("ncbi_geneid", "NCBI Gene ID", "Identifier"))
    # ncbi_gi_db_id = insertDatabase(DBNAME_Entry("ncbi_gi", "NCBI GI ID", "Identifier"))
    kegg_id_db_id = insertDatabase(DBNAME_Entry("kegg_id", "KEGG Feature ID", "Identifier"))
    kegg_gene_symbol_db_id = insertDatabase(DBNAME_Entry("kegg_gene_symbol", "KEGG Gene Symbol", "Identifier"))
    kegg_gene_symbol_synonyms_db_id = insertDatabase(DBNAME_Entry("kegg_gene_symbol_synonyms", "KEGG Gene Symbol Synonyms", "Identifier"))

    total_lines=[0,0,0]

    #STEP 2. READ THE UniProt 2 KEGG FILE
    file_name= DATA_DIR + "mapping/" + "uniprot2kegg.list"
    if not os.path.isfile(file_name):
        stderr.write("\n\nUnable to find the UNIPROT 2 KEGG MAPPING file: " + file_name + "\n")
    else:
        processKEGGMappingDataAUX("UNIPROT 2 KEGG", file_name, uniprot_acc_db_id, kegg_id_db_id, random_transcript_db_id, "up:")

    #STEP 3. READ THE NCBI Gene ID 2 KEGG FILE
    file_name= DATA_DIR + "mapping/" + "ncbi-geneid2kegg.list"
    if not os.path.isfile(file_name):
        stderr.write("\n\nUnable to find the NCBI Gene ID 2 KEGG MAPPING file: " + file_name + "\n")
    else:
        processKEGGMappingDataAUX("NCBI Gene ID 2 KEGG", file_name, ncbi_geneid_db_id, kegg_id_db_id, random_transcript_db_id, "ncbi-geneid:")

    #STEP 4. READ THE NCBI GI 2 KEGG FILE
    # file_name= DATA_DIR + "mapping/" + "ncbi-gi2kegg.list"
    # if not os.path.isfile(file_name):
    #     stderr.write("\n\nUnable to find the NCBI GI 2 KEGG MAPPING file: " + file_name + "\n")
    # else:
    #     processKEGGMappingDataAUX("NCBI GI 2 KEGG", file_name, ncbi_gi_db_id, kegg_id_db_id, random_transcript_db_id, "ncbi-gi:")

    #STEP 4. READ THE KEGG 2 GENE SYMBOL FILE
    file_name= DATA_DIR + "mapping/" + "kegg2genesymbol.list"
    if not os.path.isfile(file_name):
        stderr.write("\n\nUnable to find the KEGG 2 GENE SYMBOL MAPPING file: " + file_name + "\n")
    else:
        processKEGG2GeneSymbolMappingData("KEGG 2 GENE SYMBOL", file_name, kegg_gene_symbol_db_id, kegg_gene_symbol_synonyms_db_id, kegg_id_db_id, random_transcript_db_id)

    kegg_id_2_refseq_tid.clear()

    return total_lines

def processKEGGMappingDataAUX(display_file_name, file_name, current_db_id, kegg_id_db_id, transcripts_db_id, prefix):
    #Get line count (for percentage)
    total_lines = int(check_output(['wc', '-l', file_name]).decode('utf-8').split(" ")[0])

    #Process files
    stderr.write("\n\nPROCESSING " + display_file_name +" MAPPING FILE...\n")
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        i =0
        prev=-1
        errorMessage=""

        for row in rows:
            i+=1
            prev = showPercentage(i, total_lines, prev, errorMessage)
            try:
                external_gi  = row[0].replace(prefix, "")
                kegg_gi      = row[1].replace(SPECIE + ":", "")

                external_gi = insertXREF(XREF_Entry(external_gi, current_db_id, "Extracted from KEGG Database (" + display_file_name + " file)"))
                kegg_gi = insertXREF(XREF_Entry(kegg_gi, kegg_id_db_id, "Extracted from KEGG Database (" + display_file_name + " file)"))

                transcript_id= kegg_id_2_refseq_tid.get(kegg_gi, generateRandomID()) #Try to reuse the ids for random transcripts
                kegg_id_2_refseq_tid[kegg_gi] = transcript_id

                insertTR_XREF(external_gi, transcript_id)
                insertTR_XREF(kegg_gi, transcript_id)

            except Exception as ex:
                errorMessage = "FAILED WHILE PROCESSING " + display_file_name +" MAPPING FILE [line " + str(i) + "]: "+ str(ex)
    csvfile.close()

    return total_lines

def processKEGG2GeneSymbolMappingData(display_file_name, file_name, kegg_gene_symbol_db_id, kegg_gene_symbol_synonyms_db_id, kegg_id_db_id, transcripts_db_id):
    #Get line count (for percentage)
    total_lines = int(check_output(['wc', '-l', file_name]).decode('utf-8').split(" ")[0])

    #Process files
    stderr.write("\n\nPROCESSING " + display_file_name +" MAPPING FILE...\n")
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        i =0
        prev=-1
        errorMessage=""

        for row in rows:
            i+=1
            prev = showPercentage(i, total_lines, prev, errorMessage)
            try:
                kegg_gi      = row[0].replace(SPECIE + ":", "")
                gene_symbol  = row[1]

                gene_symbol = gene_symbol.split(";")
                if len(gene_symbol) < 2: #it means that the line only contains a description, not a gene symbol
                    continue

                gene_synonyms = gene_symbol[0].split(", ") #COULD BE A LIST OF GENE SYMBOLS
                gene_symbol   = gene_synonyms.pop(0)

                if len(gene_symbol) > 15: #discard long ids -> could be a description
                    continue

                kegg_gi = insertXREF(XREF_Entry(kegg_gi, kegg_id_db_id, "Extracted from KEGG Database (" + display_file_name + " file)"))
                gene_symbol = insertXREF(XREF_Entry(gene_symbol, kegg_gene_symbol_db_id, "Extracted from KEGG Database (" + display_file_name + " file)"))

                gene_synonyms_aux=[gene_symbol]
                for gene_symbol in gene_synonyms:
                    gene_synonyms_aux.append(insertXREF(XREF_Entry(gene_symbol, kegg_gene_symbol_synonyms_db_id, "Extracted from KEGG Database (" + display_file_name + " file)")))

                transcript_id= kegg_id_2_refseq_tid.get(kegg_gi, generateRandomID()) #Try to reuse the ids for random transcripts
                kegg_id_2_refseq_tid[kegg_gi] = transcript_id

                insertTR_XREF(kegg_gi, transcript_id)
                for gene_symbol in gene_synonyms_aux:
                    insertTR_XREF(gene_symbol, transcript_id)

            except Exception as ex:
                errorMessage = "FAILED WHILE PROCESSING " + display_file_name +" MAPPING FILE [line " + str(i) + "]: "+ str(ex)
    csvfile.close()

    return total_lines

def processKEGGCommonData(dirName, ROOT_DIRECTORY):
    #STEP1. PROCESS KEGG COMPOUND DATA
    processKEGG2CompoundSymbolMappingData(dirName + "compounds_all.list")

    #STEP2. PROCESS ALL SPECIES FILES
    stderr.write("\nPROCESSING AVAILABLE SPECIES FILE...\n")
    file_name = dirName + "organisms_all.list"

    SPECIES_AUX={}
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        for row in rows:
            SPECIES_AUX[row[2]] = {"value": row[1], "name": row[2]}
    csvfile.close()

    SPECIES=[]
    for specie_name in sorted(SPECIES_AUX.keys()):
        SPECIES.append(SPECIES_AUX.get(specie_name))

    SPECIES = {"success": True, "species": SPECIES}
    csvfile = open(ROOT_DIRECTORY + "public_html/resources/data/all_species.json", 'w')
    csvfile.write(json.dumps(SPECIES, separators=(',',':')) + "\n")
    csvfile.close()

    stderr.write("\nPROCESSING VERSIONS FILE...\n")
    #STEP3. PROCESS VERSION FILE
    file_name= dirName + "/VERSION"
    file = open(file_name, 'r')
    ALL_VERSIONS["COMMON"] = {"name" : "COMMON", "date" : file.readline().rstrip().split("\t")[1]}
    file.close()

    stderr.write("\nDUMP FILES...\n")
    #STEP4. DUMP VERSION INFO
    file = open("/tmp/versions.tmp", 'w')
    for elem in ALL_VERSIONS.values():
        file.write(json.dumps(elem, separators=(',',':')) + "\n")
    file.close()

    #STEP4. CREATE DATABASES
    stderr.write("\nCREATING GLOBAL DATABASES...\n")
    createGlobalDatabase()

def processMapMan2CompoundSymbolMappingData(file_name):
    #Get line count (for percentage)
    total_lines = int(check_output(['wc', '-l', file_name]).decode('utf-8').split(" ")[0])

    # The process will also insert information about compounds, thus discarding the previous database
    # and importing a new one, needing again the KEGG compounds.
    processKEGG2CompoundSymbolMappingData(DATA_DIR + "../common/compounds_all.list")

    #STEP 1. Process files
    stderr.write("\n\nPROCESSING Mapman 2 Compound MAPPING FILE...\n")
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        i =0
        prev=-1
        errorMessage=""

        for row in rows:
            i+=1
            #prev = showPercentage(i, total_lines, prev, errorMessage)
            try:
                mapman_id      = row[0]
                compound_symbols  = row[1].split(".")[-1].split("|")

                for compound_symbol in compound_symbols:
                    # KEGG_COMPOUNDS.append({"id" : kegg_id, "name" : compound_symbol.lstrip()})
                    MAPMAN_COMPOUNDS[compound_symbol.lstrip()] = mapman_id
            except Exception as ex:
                errorMessage = "FAILED WHILE PROCESSING Mapman 2 Compound MAPPING FILE [line " + str(i) + "]: "+ str(ex)
    csvfile.close()

    #STEP 2. DUMP THE TABLE INTO A FILE
    file = open("/tmp/compounds.tmp", 'a')
    for cpdName, cpdID in MAPMAN_COMPOUNDS.items():
        file.write(json.dumps({"id" : cpdID, "name" : cpdName}, separators=(',', ':')) + "\n")
    file.close()

    # Insert the compounds collection
    createCompoundsCollection()

    return total_lines

def processKEGG2CompoundSymbolMappingData(file_name):
    #Get line count (for percentage)
    total_lines = int(check_output(['wc', '-l', file_name]).decode('utf-8').split(" ")[0])
    # KEGG_COMPOUNDS = []

    #STEP 1. Process files
    stderr.write("\n\nPROCESSING KEGG 2 Compound MAPPING FILE...\n")
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        i =0
        prev=-1
        errorMessage=""

        for row in rows:
            i+=1
            #prev = showPercentage(i, total_lines, prev, errorMessage)
            try:
                kegg_id      = row[0].replace("cpd:", "")
                compound_symbols  = row[1]

                compound_symbols = compound_symbols.split("; ")
                for compound_symbol in compound_symbols:
                    # KEGG_COMPOUNDS.append({"id" : kegg_id, "name" : compound_symbol.lstrip()})
                    KEGG_COMPOUNDS[compound_symbol.lstrip()] = kegg_id
            except Exception as ex:
                errorMessage = "FAILED WHILE PROCESSING KEGG 2 Compound MAPPING FILE [line " + str(i) + "]: "+ str(ex)
    csvfile.close()

    #STEP 2. DUMP THE TABLE INTO A FILE
    file = open("/tmp/compounds.tmp", 'w')
    for cpdName, cpdID in KEGG_COMPOUNDS.items():
        # file.write(json.dumps(elem, separators=(',',':')) + "\n")
        file.write(json.dumps({"id" : cpdID, "name" : cpdName}, separators=(',', ':')) + "\n")
    file.close()

    return total_lines

def processMapManPathwaysData():
    from DBManager import generateThumbnail
    import xml.etree.ElementTree as XMLParser

    # Declare later used variables
    FAILED_LINES["MAPMAN PATHWAYS"] = []
    NODES = {}
    EDGES = []

    REVERSE_MAPMAN_CPD = {v: k for k, v in MAPMAN_COMPOUNDS.items()}

    if not len(external_mapping):
        stderr.write("The MapMan dictionary is not filled. Mapping files must be processed first.")
        exit(1)

    # Check if classification file exists
    mapman_classification_resource = EXTERNAL_RESOURCES.get("mapman_classification")[0]
    mapman_classification_file_name = DATA_DIR + "mapping/" + mapman_classification_resource.get("output")

    if not os.path.isfile(mapman_classification_file_name):
        stderr.write("\n\nUnable to find the MapMan classification file: " + mapman_classification_file_name + "\n")
        exit(1)

    # MapMan pathways files are the same for each species, even the XML files.
    # The handful of species compatible with MapMan will specify to download the same dataset.
    # Here we override the data always.
    # TODO: modify DBManager.py and move the code to "downloadData"?
    MAPMAN_DIR = DATA_DIR + "../mapman"
    MAPMAN_XML = MAPMAN_DIR + "/xml/"

    # If the path already exists rename it
    if os.path.exists(MAPMAN_DIR):
        shutil.rmtree(MAPMAN_DIR + ".bak", ignore_errors=True)
        shutil.move(MAPMAN_DIR, MAPMAN_DIR + ".bak")
    else:
        os.makedirs(MAPMAN_DIR)

    mapman_pathways = EXTERNAL_RESOURCES.get("mapman_pathways")[0]
    pathways_file_name = DATA_DIR + "mapping/" + mapman_pathways.get("output")

    # Try to extract the archive on the final dir, if there is an error
    # rename the previous dir
    try:
        os.makedirs(MAPMAN_DIR)
        check_call(["tar", "xzvf", pathways_file_name, "-C", MAPMAN_DIR])
    except Exception as e:
        if os.path.exists(MAPMAN_DIR):
            shutil.move(MAPMAN_DIR + ".bak", MAPMAN_DIR)
        stderr.write("Failed extraction of MapMan pathways. Aborting.")
        exit(1)

    # Make sure to create the thumbnail directory
    os.makedirs(MAPMAN_DIR + "/png/thumbnails/")

    # Process the clasiffication file
    classiffication_mapping_dict = defaultdict(list)

    with open(mapman_classification_file_name, 'r') as mapping_file:
        dict_reader = csv.DictReader(mapping_file, fieldnames=["primary", "secondary", "pathway"], delimiter="\t")
        for pathway_entry in dict_reader:
            # Remove prefix
            classiffication_mapping_dict[pathway_entry["pathway"].strip()] = ';'.join([pathway_entry["primary"].strip(), pathway_entry["secondary"].strip()])

    i = 0;
    prev = -1;
    errorMessage = "";
    xml_files = os.listdir(MAPMAN_XML)
    total_lines = len(xml_files)

    # Initialize classification counters
    mainClassificationIDs = {}
    secClassificationIDs = {}
    pathway2gene = defaultdict(set)
    gene2pathway = defaultdict(set)

    for xml_file in xml_files:
        i+=1
        prev = showPercentage(i, total_lines, prev, errorMessage)

        file_name = MAPMAN_XML + xml_file
        pathway_id = xml_file.replace(".xml", "")

        # Generate thumbnail
        png_file = MAPMAN_DIR + "/png/" + xml_file.replace(".xml", ".png")
        try:
            generateThumbnail(png_file)
        except Exception as e:
            print(png_file)

        # Classification (network) data
        classification = classiffication_mapping_dict.get(pathway_id, "Not classified;Unclassified")
        classification_terms = classification.split(";")

        mainClassification = classification_terms[0]
        secondClassification = classification_terms[1]

        # Primary classification
        if not mainClassification in mainClassificationIDs:
            mainClassificationIDs[mainClassification] = len(mainClassificationIDs) + 1
            NODES[str(mainClassificationIDs[mainClassification]) + "A"] = {"data": {"id": mainClassification.lower().replace(" ", "_"), "label": mainClassification, "is_classification": "A"}, "group": "nodes"}

        # Secondary classification
        if not secondClassification in secClassificationIDs:
            secClassificationIDs[mainClassification] = len(secClassificationIDs) + 1
            NODES[str(secClassificationIDs[mainClassification]) + "B"] = {"data": {"id": secondClassification.lower().replace(" ", "_"),
                                                                 "parent": mainClassification.lower().replace(" ", "_"),
                                                                 "label": secondClassification,
                                                                 "is_classification": "B"}, "group": "nodes"}


        # Append to the global pathways container
        ALL_PATHWAYS[pathway_id] = {"ID": pathway_id, "name": pathway_id, "genes": [],
                                    "compounds": [], "relatedPathways": [], "source": "MapMan", "featureDB": "mapman_id",
                                    "classification": classification}

        # Pathway node information
        NODES[pathway_id] = {"data": {"id": pathway_id, "label": pathway_id, "total_features": 0}, "group": "nodes"}
        NODES[pathway_id]["data"]["parent"] = mainClassification.lower().replace(" ","_"),


        try:
            pathwayInfoXML = XMLParser.parse(file_name)
            # Image element
            root = pathwayInfoXML.getroot()
            already_added = {}
            # FOR EACH NODE IN THE XML FILE (DataArea)
            for child in root:
                try:
                    # Somewhere in the future maybe MapMan would get compound support added,
                    # leave here the possibility of getting the type like in KEGG
                    # entryType = child.get("type")

                    entry = {
                        "id": "",
                        "x": int(child.get("x")),
                        "y": int(child.get("y")),
                        "width": int(child.get("width", 0)),
                        "height": int(child.get("height", 0)),
                        "title": child.get("title", None),
                        "blockFormat": child.get("blockFormat"),
                        "type": child.get("type"),
                        "visualizationType": child.get("visualizationType"),
                        "recursive": True
                    }

                    # Each DataArea has at least one 'Identifier' child
                    for featureID in child:
                        # and not already_added.has_key(featureID)
                        id_terms = featureID.get("id")

                        # Mapman does not have a way to tell if the node is a gene or compound,
                        # so we determine it by checking the presence of the id inside the compounds
                        # dict.
                        if id_terms in REVERSE_MAPMAN_CPD:
                            compound_linked = REVERSE_MAPMAN_CPD.get(id_terms)

                            entryAux = entry.copy()
                            entryAux["id"] = compound_linked
                            entryAux["recursive"] = featureID.get("recursive")

                            ALL_PATHWAYS[pathway_id]["compounds"].append(entryAux)

                        else:
                            # As opposed to KEGG, where there are multiple identifiers
                            # mapped to the same coordinates, MapMan refers to orthology terms
                            # instead of genes.
                            #
                            # We transform the term to its mapped genes and clone the same
                            # entry pointing to the same x & y coordinates to allow to work
                            # as a KEGG pathway.
                            #
                            # General terms should also include child terms. I.e. 20.1 should
                            # reference also 20.1.*.*
                            pattern_search = re.compile(r"{0}(\.|\Z)".format(id_terms))

                            # external_mapping
                            genes_linked = set(list(itertools.chain.from_iterable([v for k, v in external_mapping.items() if pattern_search.search(k)])))

                            # Link pathway to genes for network construction
                            pathway2gene[pathway_id].update(genes_linked)

                            for gene_id in genes_linked:

                                # Link gene to pathway for network construction
                                gene2pathway[gene_id].add(pathway_id)

                                entryAux = entry.copy()
                                entryAux["id"] = gene_id
                                entryAux["recursive"] = featureID.get("recursive")

                                ALL_PATHWAYS[pathway_id]["genes"].append(entryAux)

                except Exception as ex:
                    errorMessage = "FAILED WHILE PROCESSING PATHWAY XML FILE [" + file_name + "]: " + str(ex)
                    FAILED_LINES["MAPMAN PATHWAYS"].append([errorMessage])

        except Exception as ex:
            errorMessage = "FAILED WHILE PROCESSING PATHWAY XML FILE [" + file_name + "]: " + str(ex)

    #***********************************************************************************
    #* GENERATE THE NETWORK FILE DATA FOR MAPMAN
    #***********************************************************************************

    #***********************************************************************************
    #* FIRST PROCESS THE FILE WITH ALL PATHWAYS AND GENERATE A DIAGONAL MATRIX
    #          mmu00100 -> [ mmu00101 = 0, mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00101 -> [               mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00102 -> [                             mmu00103 = 0,...]
    #***********************************************************************************
    all_pathways = sorted(NODES.keys())

    pathways_matrix = {}
    while len(all_pathways) > 0:
        current_path = all_pathways[0]
        del all_pathways[0]
        pathways_matrix[current_path] = dict(zip(all_pathways, [0]*len(all_pathways)))

    #***********************************************************************************
    #* PROCESS THE FILE WITH THE RELATION GENE ID -> PATHWAY ID AND FILL THE MATRIX
    #          WITH THE NUMBER OF SHARED GENES
    #          mmu00100 -> [ mmu00101 = 1, mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00101 -> [               mmu00102 = 5, mmu00103 = 3,...]
    #          mmu00102 -> [                             mmu00103 =20,...]
    #***********************************************************************************
    previous_gene = ""
    associated_paths = set()

    for gene_id, pathway_ids in gene2pathway.items():
        for path_id in pathway_ids:
            if gene_id != previous_gene:
                associated_paths = sorted(associated_paths)
                while len(associated_paths) > 0:
                    current_path = associated_paths[0]
                    del associated_paths[0]
                    for other_path in associated_paths:
                        try:
                            pathways_matrix[current_path][other_path] += 1
                        except:
                            stderr.write("Pathways " + current_path + " or " + other_path + " not found in MapMan network values.\n")

                associated_paths = set([])

            associated_paths.add(path_id)
            previous_gene = gene_id

    # LAST PATHWAY
    associated_paths = sorted(associated_paths)
    while len(associated_paths) > 0:
        current_path = associated_paths[0]
        del associated_paths[0]
        for other_path in associated_paths:
            try:
                pathways_matrix[current_path][other_path] += 1
            except:
                try:
                    pathways_matrix[other_path][current_path] += 1
                except:
                    stderr.write("Pathways " + current_path + " or " + other_path + " not found in MapMan network values.\n")

    #***********************************************************************************
    #* GET THE NUMBER OF GENES FOR EACH PATHWAY
    #***********************************************************************************
    mapman_g2p_file = DATA_DIR + "gene2pathway_mapman.list"

    # Write a "gene2pathway_mapman.list" to be used for metagenes generation.
    with open(mapman_g2p_file, 'w') as mapman_gene2pathway:
        for path_id, gene_ids in pathway2gene.items():
            new_string = set([w for w in gene_ids if len( w ) == 20])
            NODES[path_id]["data"]["total_features"] = len(new_string)

            # Write one row for each gene and pathway
            mapman_gene2pathway.writelines(str(geneID) + "\t" + str(path_id) + "\n" for geneID in gene_ids)


    #***********************************************************************************
    #* BULK THE MATRIX INTO JSON:
    #          FOR EACH PATHWAY ID AND FOR EACH POSITION WITH NON ZERO (SHARE AT LEAST 1 GENE), CREATE AN EDGE
    #***********************************************************************************
    already_linked_pathways={}
    for path_id, shared_genes in pathways_matrix.items():
        #First create the edges based on the links between networks (extracted from KGML files)
        if path_id in ALL_PATHWAYS:
            relatedPathways = ALL_PATHWAYS[path_id]["relatedPathways"]
            for other_path_id in relatedPathways:
                if not path_id + "-" + other_path_id["id"] in already_linked_pathways:
                    EDGES.append({"data": {"id": path_id + "-" + other_path_id["id"], "source": path_id, "target": other_path_id["id"], "weight": 1, "class": 'l'}, "group":"edges"})
                    #Avoid repeated edges (including the opposite links)
                    already_linked_pathways[path_id + "-" + other_path_id["id"]] = 1
                    already_linked_pathways[other_path_id["id"]+ "-" + path_id] = 1
        #Add the edges based on the existance of shared genes
        for other_path_id, n_shared_genes in shared_genes.items():
            if n_shared_genes > 0:
                EDGES.append({"data": {"id": path_id + "-" + other_path_id, "source": path_id, "target": other_path_id, "weight": n_shared_genes, "class": 's'}, "group":"edges"})

    #***********************************************************************************
    #* SAVE THE NETWORK TO A FILE
    #***********************************************************************************
    network = {
        "nodes": list(NODES.values()),
        "edges": EDGES
    }
    csvfile = open(DATA_DIR + "pathways_network_MapMan.json", 'w')
    csvfile.write(json.dumps(network, separators=(',',':')) + "\n")
    csvfile.close()

    TOTAL_FEATURES["MAPMAN PATHWAYS"]=total_lines

    #***********************************************************************************
    #* PROCESS THE VERSION FILES
    #***********************************************************************************
    version = open(DATA_DIR + 'MAPMAN_VERSION', 'w')
    version.write("# CREATION DATE:\t" + strftime("%Y%m%d %H%M"))
    version.close()

    ALL_VERSIONS["MAPMAN"] = {"name" : "MAPMAN", "date" : strftime("%Y%m%d %H%M")}
    ALL_VERSIONS["MAPMAN_MAPPING"] = {"name": "MAPMAN_MAPPING", "date": strftime("%Y%m%d %H%M")}
    #
    # file_name= DATA_DIR + "mapping/MAP_VERSION"
    # file = open(file_name, 'r')
    #
    # file.close()

def processReactomePathwaysData():

    # Declare later used variables
    FAILED_LINES["REACTOME PATHWAYS"] = []
    TOTAL_FEATURES["REACTOME PATHWAYS"] = 0
    NODES = {}
    EDGES = []
    #
    if not len(ALL_ENTRIES):
        stderr.write("The mapping entries dictionary is not filled. Mapping of KEGG & auxiliary files must be processed first.")
        exit(1)

    REACTOME_DIR = DATA_DIR + "reactome"

    print("REACTOME_DATA_DIR:" + REACTOME_DIR)
    #REACTOME_DIR = DATA_DIR + "reactome"

    # If the path already exists rename it
    #if (os.path.exists(REACTOME_DIR)):
    #    shutil.rmtree(REACTOME_DIR + ".bak", ignore_errors=True)
    #    shutil.move(REACTOME_DIR, REACTOME_DIR + ".bak")

    #os.makedirs(REACTOME_DIR)
    #os.makedirs(REACTOME_DIR + "/png/thumbnails/")

    # When downloading Reactome data we only retrieve the top pathways from the species.
    # The rest of them need to be downloaded in the installation process.
    #reactome_top_pathways = EXTERNAL_RESOURCES.get("reactome")[0]
    #reactome_top_pathways_file_name = DATA_DIR + "mapping/" + reactome_top_pathways.get("output")

    #if not os.path.isfile(reactome_top_pathways_file_name):
    #    stderr.write("\n\nUnable to find the Reactome top pathways file: " + reactome_top_pathways_file_name + "\n")
    #    exit(1)

    # Because of the current particularities of the Reactome data, the mapping process must be done parallel
    # to the insertion of pathways.
    reactome_gene_db_id = insertDatabase(
        DBNAME_Entry("reactome_gene_id", "Reactome Gene identifier", "Identifier"))

    reactome_gene_db_id_other = insertDatabase(
        DBNAME_Entry("reactome_gene_id_other", "Reactome Gene identifier (other ids)", "Identifier"))

    reactome_gene_desc = "Extracted from Reactome Database"
    reactome_gene_desc_other = "Extracted from Reactome Database (other identifiers)"

    # Initialize classification counters
    mainClassificationIDs = {}
    secClassificationIDs = {}
    pathway2gene = defaultdict(set)
    gene2pathway = defaultdict(set)
    REACTOME_COMPOUNDS = {}
    total_lines = 0


    PATHWAY_ID = set()

    # In case we want to split the linking process with KEGG & other databases, keeping
    # Reactome isolated.
    dbname = 'global'

    # Cache variables
    event_cache = {}
    reactome_id_2_refseq_tid = {}  # We use a different one

    reuseDownloadedFiles = True



    # The process will also insert information about compounds, thus discarding the previous database
    # and importing a new one, needing again the KEGG compounds.
    processKEGG2CompoundSymbolMappingData(DATA_DIR + "../common/compounds_all.list")

    mapReactomeDir = DATA_DIR + "mapping/reactome/"

    command = ROOT_DIR + "/scripts/processReactomeData.R" + " --specie=" + SPECIE + " --root=" + DATA_DIR + "/../common/"

    check_call(command ,shell=True)


    #In the first step, we need to process the mapping data
    ensemblList = list()
    ensemblListID = list()
    ensemblSymbol = list()

    with open(mapReactomeDir + "Ensembl2Reactome.txt") as Ensembl2Reactome:
        ensembl2Reactome = csv.reader(Ensembl2Reactome, delimiter='\t')
        for row in ensembl2Reactome:
            ensemblList.append(row[0])
            ensemblListID.append(row[1])
            ensemblSymbol.append(row[2])

    ncbiList = list()
    ncbiListID = list()
    ncbiSymbol = list()


    with open(mapReactomeDir + "NCBI2Reactome.txt") as NCBI2Reactome:
        ncbi2Reactome = csv.reader(NCBI2Reactome, delimiter = '\t')
        for row in ncbi2Reactome:
            ncbiList.append(row[0])
            ncbiListID.append(row[1])
            ncbiSymbol.append(row[2])

    uniprotList = list()
    uniprotListID = list()
    uniprotSymbol = list()

    with open (mapReactomeDir + "UniProt2Reactome.txt") as UniProt2Reactome:
        uniProt2Reactome = csv.reader(UniProt2Reactome, delimiter='\t')
        for row in uniProt2Reactome:
            uniprotList.append(row[0])
            uniprotListID.append(row[1])
            uniprotSymbol.append(row[2])

    chebi2ReactomeList = list()
    chebi2ReactomeListID = list()

    with open (DATA_DIR + "../common/ChEBI2Reactome.list") as ChEBI2Reactome:
        chebi2Reactome = csv.reader(ChEBI2Reactome, delimiter='\t')
        for row in chebi2Reactome:
            chebi2ReactomeList.append(row[0])
            chebi2ReactomeListID.append(row[1])

    kegg2chebiList = list()
    kegg2chebiListID = list()

    with open (DATA_DIR + "../common/kegg2chebi") as KEGG2ChEBI:
        kegg2chebi = csv.reader(KEGG2ChEBI, delimiter='\t')
        for row in kegg2chebi:
            row[0] = row[0].split(":")[1]
            row[1] = row[1].split(":")[1]
            kegg2chebiList.append(row[0])
            kegg2chebiListID.append(row[1])



    REACTOME_PATHWAY = DATA_DIR + 'ReactomePathway.txt'

    with open( file=REACTOME_PATHWAY ) as pathwayList:
        for line in pathwayList:
            PATHWAY_ID.add(line.strip())

    def showPercentageSimple(n, total):
        percen = int( n / float( total ) * 10 )
        stderr.write(
            "0%[" + ("#" * percen) + (" " * (10 - percen)) + "]100% [" + str( n ) + "/" + str( total ) + "]\t" )
        return percen


    stderr.write("\nClassification part \n")

    #pathway_id = ""
    indexFinal = 0

    total_feature = defaultdict(set)





    for pathway_id in PATHWAY_ID:


        stderr.write("Start Installing: " + pathway_id + "   ")
        indexFinal += 1
        showPercentageSimple( indexFinal, len( PATHWAY_ID ) )
        stderr.write('\n')

        #stderr.write("\nStart Analysis:" + pathway_id +"\n")
        nodes_tmp_file = REACTOME_DIR + "/" + pathway_id + ".json"

        with open(nodes_tmp_file) as pathway_info:
            pathway_data = json.load(pathway_info)

        #try:
            # Find Higher Level Pathway information and download them
        #    IDList = findHighLevelPathway(pathway_id, ReactomeHierarchy, ReactomePathwayHighList, ReactomePathwayLowList)
        #except Exception as ex:
        #   IDList = [pathway_id,pathway_id]
        pathway_hierachy_file = DATA_DIR + "ReactomePathwayHierarchy.json"
        with open(pathway_hierachy_file) as HierachyRelation:
            hierachyRelation = json.load(HierachyRelation)

        pathway_name = pathway_data.get("displayName")

        ## Some time this could happen
        IDList = hierachyRelation.get(pathway_id)
        top_pathway_details_filename = REACTOME_DIR + '/' + IDList[0] + "details.json"
        secondary_pathway_details_filename= REACTOME_DIR + '/' + IDList[1] + "details.json"
        try:
            with open(top_pathway_details_filename) as top_pathways:
                top_pathway=json.load(top_pathways)
            with open(secondary_pathway_details_filename) as secondary_pathways:
                secondary_pathway=json.load(secondary_pathways)
        except Exception as ex:
            continue

        mainClassification = top_pathway.get("displayName")
        secondClassification = secondary_pathway.get("displayName")

        if not mainClassification in mainClassificationIDs:
            mainClassificationIDs[mainClassification] = len(mainClassificationIDs) + 1
            NODES[str(mainClassificationIDs[mainClassification]) + "A"] = {
                "data": {"id": mainClassification.lower().replace(" ", "_"),
                         "label": mainClassification, "is_classification": "A"},
                "group": "nodes"}

        # Secondary classification
        if not secondClassification in secClassificationIDs:
            secClassificationIDs[mainClassification] = len(secClassificationIDs) + 1
            NODES[str(secClassificationIDs[mainClassification]) + "B"] = {
                "data": {"id": secondClassification.lower().replace(" ", "_"),
                         "parent": mainClassification.lower().replace(" ", "_"),
                         "label": secondClassification,
                         "is_classification": "B"}, "group": "nodes"}

        # Append to the global pathways container
        ALL_PATHWAYS[pathway_id] = {"ID": pathway_id, "name": pathway_name, "genes": [],
                                    "compounds": [], "relatedPathways": [],
                                    "source": "Reactome",
                                    "featureDB": "reactome_gene_id",
                                    "classification": ';'.join([mainClassification, secondClassification])}

        # Pathway node information
        NODES[pathway_id] = {
            "data": {"id": pathway_id, "label": pathway_name, "total_features": 0},
            "group": "nodes"}
        NODES[pathway_id]["data"]["parent"] = mainClassification.lower().replace(" ", "_"),

        # Select the first and only component

        #stderr.write("\nLoading pathway info ")


        with open (REACTOME_DIR + "/" + pathway_id + ".graph.json") as graphInf:
            graphData = json.load(graphInf)

        nodesInf = graphData.get( "nodes" )

        # Build a hierarchy relationship for nodes class as complex
        nodesHighList = list()  # high level
        nodesLowList = list()  # low level
        nodesLastSet = set()  # lowest level
        for item in graphData.get('nodes'):
            #if item['schemaClass'] == 'Complex' | item['schemaClass'] == 'DefinedSet' | item['schemaClass'] == 'CandidateSet' | item['schemaClass'] == 'Polymer':
            try:
                for children in item['children']:
                    nodesHighList.append(item['dbId'])
                    nodesLowList.append(children)
            except Exception as ex:
                continue
        nodesHighSet = set(nodesHighList)
        nodesLowSet = set(nodesLowList)

        nodesMiddleSet = nodesHighSet.intersection(nodesLowSet)
        nodesLastSet = nodesLowSet.difference(nodesHighSet)
        nodesTopSet = nodesHighSet.difference(nodesLowSet)




        # Complex item contains several proteins, we need to find out which protein it represents.
        def findLastLevelNodes( nodesList ):
            length = len( nodesList )
            for subNode in nodesList:
                try:
                    tempList= next( item for item in nodesInf if item["dbId"] == subNode )['children']
                    nodesList.pop( nodesList.index( subNode ) )
                    nodesList = nodesList + tempList
                except Exception as ex:
                    continue

            hasSubList = False

            if len(nodesList) == length:
                for subNode in nodesList:
                    try:
                        next( item for item in nodesInf if item["dbId"] == subNode )['children']
                        hasSubList = True
                    except Exception as ex:
                        continue
                if hasSubList:
                    return findLastLevelNodes( nodesList )
                else:
                    return set( nodesList )
            else:
                return findLastLevelNodes( nodesList )

        highHierarchySet = defaultdict( set )
        middleHierarchySet = defaultdict( set )
        #node = 10032727
        for node in nodesTopSet:
            inputList = next( item for item in nodesInf if item["dbId"] == node )['children']
            outputSet = findLastLevelNodes(inputList)
            for value in outputSet:
                highHierarchySet[node].add(value)
        for node in nodesMiddleSet:
            inputList = next( item for item in nodesInf if item["dbId"] == node )['children']
            outputSet = findLastLevelNodes(inputList)
            for value in outputSet:
                middleHierarchySet[node].add(value)


        # Parse each node of the pathway
        #reactome_entity = pathway_data.get("nodes")[20]
        #reactome_entity = next( item for item in pathway_data.get("nodes") if item["reactomeId"] == 188833 )
        for reactome_entity in pathway_data.get("nodes"):

            entity_id = reactome_entity.get("reactomeId")

            try:
                 entity_reactome = next( item for item in nodesInf if item["dbId"] == entity_id )
            except Exception as ex:
                continue

            #graphic_id = reactome_entity.get("id")

            #stderr.write("\nChecking entity id " + str(entity_id))

            # Calculate the middle point
            propX = int(reactome_entity.get("prop").get("x"))
            propY = int(reactome_entity.get("prop").get("y"))

            propHeight = int(reactome_entity.get("prop").get("height"))
            propWidth = int(reactome_entity.get("prop").get("width"))

            entry = {
                "id": "",
                "x": int(propX + (propWidth / 2)),
                "y": int(propY + (propHeight / 2)),
                "height": propHeight,
                "width": propWidth,
                "schemaClass": reactome_entity.get("schemaClass")
            }
            entry['schemaClass'] = entity_reactome["schemaClass"]

            #There are complex item in Reactome, which means that a protein contains some other components. We need to find out the protein
            #ID to make PaintOmics work.

                ## Sometime the graph.json file may not contain all nodes in the json file. We should use previous method to install that node.


            # Sometimes the reactome id has subclasses we need to manage them one by one
            if entity_id in nodesHighSet:
                if reactome_entity['reactomeId'] in highHierarchySet.keys():
                    nodeIDSet = highHierarchySet[reactome_entity['reactomeId']]
                else:
                    nodeIDSet = middleHierarchySet[reactome_entity['reactomeId']]
            else:
                nodeIDSet = {entity_id}

                # Find element in the database. if we can not find it return the Reactome id
            for nodeID in nodeIDSet:

                #stderr.write('\n \nstart analysising:' + str(nodeID))

                entity_reactome = next( item for item in nodesInf if item["dbId"] == nodeID )
                entity_reactome_id = entity_reactome['stId']
                #entry['schemaClass'] = next( item for item in nodesInf if item["dbId"] == entity_id )["schemaClass"]
                entity_reactome_id_name = entity_reactome['displayName']
                entity_reactome_id_name_simple = entity_reactome_id_name.rsplit(' ', 1)[0]
                if entity_reactome.get("schemaClass") == 'SimpleEntity':
                    indices = [i for i, x in enumerate(chebi2ReactomeListID) if x == entity_reactome_id]
                    ## Can not find chebi ID
                    if not indices:
                        #print("Can not find:" + entity_reactome_id)
                        entryAux = entry.copy()
                        entryAux["id"] = entity_reactome_id_name_simple
                        REACTOME_COMPOUNDS[entity_reactome_id_name_simple] = entity_reactome_id
                        ALL_PATHWAYS[pathway_id]["compounds"].append(entryAux)
                    else:
                        chebiID = set()
                        for i in indices:
                            chebiID.add(chebi2ReactomeList[i])

                        def findKeggCpdID (chebiID):
                            subChebiID = chebiID.pop()
                            indicesFinal = [i for i, x in enumerate(kegg2chebiList) if x == subChebiID]
                            if not indicesFinal and not chebiID:
                                return None
                                #print ("Can not find kegg key for chebi ID:" + subChebiID)
                            elif not indicesFinal:
                                return findKeggCpdID(chebiID)
                            else:
                                return indicesFinal
                        keggIndex = findKeggCpdID(chebiID)

                        if not keggIndex:
                            entryAux = entry.copy()
                            entryAux["id"] =entity_reactome_id_name_simple
                            REACTOME_COMPOUNDS[entity_reactome_id_name_simple] = entity_reactome_id
                            ALL_PATHWAYS[pathway_id]["compounds"].append(entryAux)
                        else:
                            keggIndex = keggIndex[0]
                            keggID = kegg2chebiListID[keggIndex]

                            # Sometimes the kegg id is not present in the kegg_compounds. We need use entity_reactome_id_name to server as the key
                            try:
                                ## Get the key from KEGG and use it to save reactome
                                indicesList = [i for i, x in enumerate( list(KEGG_COMPOUNDS.values()) ) if x == keggID]
                                for index in indicesList:
                                    REACTOME_COMPOUNDS[list(KEGG_COMPOUNDS.keys())[index]] = keggID
                                    entryAux = entry.copy()
                                    entryAux["id"] = keggID
                                    ALL_PATHWAYS[pathway_id]["compounds"].append(entryAux)
                            except Exception as ex:
                                REACTOME_COMPOUNDS[entity_reactome_id_name_simple] = keggID
                                entryAux = entry.copy()
                                entryAux["id"] = keggID
                                ALL_PATHWAYS[pathway_id]["compounds"].append( entryAux )

                elif entity_reactome.get("schemaClass") == "EntityWithAccessionedSequence":

                    indicesEnsembl = [i for i, x in enumerate(ensemblListID) if x == entity_reactome_id]
                    indicesNcbi = [i for i, x in enumerate(ncbiListID) if x == entity_reactome_id]
                    indicesUniPort =  [i for i, x in enumerate(uniprotListID) if x == entity_reactome_id]
                    other_ids = set()

                    for i in indicesEnsembl:
                        other_ids.add(ensemblList[i])
                        other_ids.add(ensemblSymbol[i])
                    for i in indicesNcbi:
                        other_ids.add(ncbiList[i])
                        other_ids.add(ncbiSymbol[i])
                    for i in indicesUniPort:
                        other_ids.add(uniprotList[i])
                        other_ids.add(uniprotSymbol[i])

                    # IF this is not a gene, we should skip it
                    try:
                        total_feature[pathway_id].add( entity_reactome.get( 'geneNames' ).copy()[0] )
                        gene_ids = entity_reactome.get('geneNames').copy()
                    except Exception as ex:
                        continue

                    gene_id = gene_ids.pop( 0 ).upper()



                    for ID in gene_ids:
                        other_ids.add(ID.upper())


                    pathway2gene[pathway_id].update([gene_id] + list(other_ids))
                    for gene in [gene_id] + list(other_ids):
                        gene2pathway[gene].add(pathway_id)
                    entryAux = entry.copy()
                    entryAux["id"] = gene_id

                    ALL_PATHWAYS[pathway_id]["genes"].append(entryAux)

                    # Reactome may use as gene id symbols already provided by KEGG
                    # or other linked databases. As Paintomics uses the database id
                    # to properly identify which symbol to display, we need to have
                    # a copy for reactome database, using an empty string so as to avoid
                    # conflictions.
                    previous_symbol_item = findXREFByEntry(gene_id)

                    reactome_gi = insertXREF(
                        XREF_Entry(gene_id, reactome_gene_db_id,
                                   reactome_gene_desc), dbname)

                    if previous_symbol_item:
                        transcript_id = previous_symbol_item.getID()
                    else:
                        # Generate a random ID for the reactome identifier
                        transcript_id = reactome_id_2_refseq_tid.get(
                            reactome_gi,
                            generateRandomID(dbname))  # Try to reuse the ids for random transcripts
                        reactome_id_2_refseq_tid[reactome_gi] = transcript_id

                    # Save the reference
                    insertTR_XREF(reactome_gi, transcript_id, dbname)

                    for synonym_id in other_ids:
                        # Check if the id already exists as a previous XREF.
                        # Note: this requires KEGG mapping to be done BEFORE inserting
                        # reactome pathways.
                        #stderr.write("\n\t\tSynonym " + str(synonym_id))

                        entity_item = findXREFByEntry(synonym_id)

                        if not entity_item:
                            entity_gi = insertXREF(XREF_Entry(synonym_id,
                                                              reactome_gene_db_id_other,
                                                              reactome_gene_desc_other),
                                                   dbname)

                        else:
                            entity_gi = entity_item.getID()

                        insertTR_XREF(entity_gi, transcript_id, dbname)

                elif entity_reactome.get( "schemaClass" ) == "Pathway":
                    entry = {
                        "id": entity_reactome_id,
                        "name": entity_reactome_id_name,
                        "x": int( propX + (propWidth / 2) ),
                        "y": int( propY + (propHeight / 2) ),
                        "height": propHeight,
                        "width": propWidth
                    }
                    ALL_PATHWAYS[pathway_id]["relatedPathways"].append( entry )

                else:
                    continue




    # Append the new Reactome compounds to the file previously generated
    # by KEGG process.
    file = open("/tmp/compounds.tmp", 'a')
    for cpdName, cpdID in REACTOME_COMPOUNDS.items():
        file.write(json.dumps({"id": cpdID, "name": cpdName}, cls=SetEncoder, separators=(',', ':')) + "\n")
    file.close()

    # Insert the compounds collection
    createCompoundsCollection()

    # MapMan pathways files are the same for each species, even the XML files.
    # The handful of species compatible with MapMan will specify to download the same dataset.
    # Here we override the data always.
    # TODO: modify DBManager.py and move the code to "downloadData"?

    # mapman_pathways = EXTERNAL_RESOURCES.get("mapman_pathways")[0]
    # pathways_file_name = DATA_DIR + "mapping/" + mapman_pathways.get("output")

    # i = 0;
    # prev = -1;
    # errorMessage = "";
    # xml_files = os.listdir(MAPMAN_XML)
    # total_lines = len(xml_files)
    #
    # for xml_file in xml_files:
    #     i+=1
    #     prev = showPercentage(i, total_lines, prev, errorMessage)

    # ***********************************************************************************
    # * GENERATE THE NETWORK FILE DATA FOR REACTOME
    # ***********************************************************************************

    # ***********************************************************************************
    # * FIRST PROCESS THE FILE WITH ALL PATHWAYS AND GENERATE A DIAGONAL MATRIX
    #          mmu00100 -> [ mmu00101 = 0, mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00101 -> [               mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00102 -> [                             mmu00103 = 0,...]
    # ***********************************************************************************
    all_pathways = sorted(NODES.keys())

    pathways_matrix = {}
    while len(all_pathways) > 0:
        current_path = all_pathways[0]
        del all_pathways[0]
        pathways_matrix[current_path] = dict(zip(all_pathways, [0] * len(all_pathways)))

    # ***********************************************************************************
    # * PROCESS THE FILE WITH THE RELATION GENE ID -> PATHWAY ID AND FILL THE MATRIX
    #          WITH THE NUMBER OF SHARED GENES
    #          mmu00100 -> [ mmu00101 = 1, mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00101 -> [               mmu00102 = 5, mmu00103 = 3,...]
    #          mmu00102 -> [                             mmu00103 =20,...]
    # ***********************************************************************************
    previous_gene = ""
    associated_paths = set()

    for gene_id, pathway_ids in gene2pathway.items():
        for path_id in pathway_ids:
            if gene_id != previous_gene:
                associated_paths = sorted(associated_paths)
                while len(associated_paths) > 0:
                    current_path = associated_paths[0]
                    del associated_paths[0]
                    for other_path in associated_paths:
                        try:
                            pathways_matrix[current_path][other_path] += 1
                        except:
                            stderr.write("Pathways " + current_path + " or " + other_path + " not found in Reactome network values.\n")

                associated_paths = set([])

            associated_paths.add(path_id)
            previous_gene = gene_id

    # LAST PATHWAY
    associated_paths = sorted(associated_paths)
    while len(associated_paths) > 0:
        current_path = associated_paths[0]
        del associated_paths[0]
        for other_path in associated_paths:
            try:
                pathways_matrix[current_path][other_path] += 1
            except:
                stderr.write(
                    "Pathways " + current_path + " or " + other_path + " not found in Reactome network values.\n")

    # ***********************************************************************************
    # * GET THE NUMBER OF GENES FOR EACH PATHWAY
    # ***********************************************************************************
    reactome_g2p_file = DATA_DIR + "gene2pathway_reactome.list"

    # Write a "gene2pathway_mapman.list" to be used for metagenes generation.
    with open(reactome_g2p_file, 'w') as reactome_gene2pathway:
        for path_id, gene_ids in pathway2gene.items():
            # Write one row for each gene and pathway
            # reactome_gene2pathway.writelines(geneID.encode('utf-8') + "\t".encode('utf-8') + path_id.encode('utf-8') + "\n".encode('utf-8') for geneID in gene_ids)
            reactome_gene2pathway.writelines("{}\t{}\n".format(geneID, path_id) for geneID in gene_ids)


    for path_id, gene_ids in total_feature.items():
        try:
            NODES[path_id]["data"]["total_features"] = len(gene_ids)
        except Exception as e:
            print(path_id)
            continue

    # ***********************************************************************************
    # * BULK THE MATRIX INTO JSON:
    #          FOR EACH PATHWAY ID AND FOR EACH POSITION WITH NON ZERO (SHARE AT LEAST 1 GENE), CREATE AN EDGE
    # ***********************************************************************************
    already_linked_pathways = {}
    for path_id, shared_genes in pathways_matrix.items():
        # First create the edges based on the links between networks (extracted from KGML files)
        if path_id in ALL_PATHWAYS:
            relatedPathways = ALL_PATHWAYS[path_id]["relatedPathways"]
            for other_path_id in relatedPathways:
                if not path_id + "-" + other_path_id["id"] in already_linked_pathways:
                    EDGES.append({"data": {"id": path_id + "-" + other_path_id["id"], "source": path_id,
                                           "target": other_path_id["id"], "weight": 1, "class": 'l'}, "group": "edges"})
                    # Avoid repeated edges (including the opposite links)
                    already_linked_pathways[path_id + "-" + other_path_id["id"]] = 1
                    already_linked_pathways[other_path_id["id"] + "-" + path_id] = 1
        # Add the edges based on the existance of shared genes
        for other_path_id, n_shared_genes in shared_genes.items():
            if n_shared_genes > 0:
                EDGES.append({"data": {"id": path_id + "-" + other_path_id, "source": path_id, "target": other_path_id,
                                       "weight": n_shared_genes, "class": 's'}, "group": "edges"})

    # ***********************************************************************************
    # * SAVE THE NETWORK TO A FILE
    # ***********************************************************************************
    network = {
        "nodes": list(NODES.values()),
        "edges": EDGES
    }
    csvfile = open(DATA_DIR + "pathways_network_Reactome.json", 'w')
    csvfile.write(json.dumps(network, separators=(',', ':')) + "\n")
    csvfile.close()

    TOTAL_FEATURES["REACTOME PATHWAYS"] = total_lines

    # ***********************************************************************************
    # * PROCESS THE VERSION FILES
    # ***********************************************************************************
    version = open(DATA_DIR + 'REACTOME_VERSION', 'w')
    version.write("# CREATION DATE:\t" + strftime("%Y%m%d %H%M"))
    version.close()

    ALL_VERSIONS["REACTOME"] = {"name": "REACTOME", "date": strftime("%Y%m%d %H%M")}
    ALL_VERSIONS["REACTOME_MAPPING"] = {"name": "REACTOME_MAPPING", "date": strftime("%Y%m%d %H%M")}
    #
    # file_name= DATA_DIR + "mapping/MAP_VERSION"
    # file = open(file_name, 'r')
    #
    # file.close()



def processKEGGPathwaysData():
    FAILED_LINES["KEGG PATHWAYS"] = []

    #STEP 1. PROCESS THE pathways.list FILE
    file_name= DATA_DIR + "pathways.list"
    file = open(file_name, 'r')
    for line in file:
        line = line.rstrip().split("\t")
        pathway_id   = line[0].replace("path:","")
        pathway_name = line[1]
        pathway_name = pathway_name[0:pathway_name.rfind(" - ")]

        ALL_PATHWAYS[pathway_id] = {"ID": pathway_id, "name": pathway_name, "classification": set([]), "genes":[], "compounds":[], "relatedPathways":[], "source": "KEGG", "featureDB": "kegg_id" }

    file.close()

    #STEP 2. PROCESS THE pathways_classification.list FILE
    file_name= DATA_DIR + "../common/pathways_classification.list"
    file = open(file_name, 'r')
    mainClassification=""; secondClassification="";
    for line in file:
        line = line.rstrip().split("  ")

        if line[0][0] == "A": #main classification
            mainClassification=line[0][1:]
        elif line[0][0] == "B":
            secondClassification = line[1]
        elif line[0][0] == "C":
            pathway_id   = line[2]
            if SPECIE + pathway_id in ALL_PATHWAYS:
                ALL_PATHWAYS[SPECIE + pathway_id]["classification"] = mainClassification + ";" + secondClassification
    file.close()

    #STEP 3. PROCESS ALL THE KGML FILES
    i =0; prev=-1; errorMessage=""; total_lines= len(list(ALL_PATHWAYS.keys()))
    for pathway_id in ALL_PATHWAYS.keys():
        i+=1
        prev = showPercentage(i, total_lines, prev, errorMessage)
        #FOR EACH PATHWAY READ THE XML DATA
        file_name= DATA_DIR + "kgml/" + pathway_id +".kgml"
        try:
            import xml.etree.ElementTree as XMLParser
            pathwayInfoXML = XMLParser.parse(file_name)
            root = pathwayInfoXML.getroot()
            already_added = {}
            #FOR EACH NODE IN THE XML FILE
            for child in root:
                try:
                    entryType =  child.get("type")

                    if (entryType == "compound") or (entryType == "gene"):
                        graphicInfo = child.find("graphics")
                        featureIDList = child.get("name").split(" ")
                        entry = {
                            "id"     : "",
                            "x"      : graphicInfo.get("x"),
                            "y"      : graphicInfo.get("y"),
                            "height" : graphicInfo.get("height"),
                            "width"  : graphicInfo.get("width")
                        }

                        for featureID in featureIDList:
                            if (entryType == "compound") and not featureID in already_added:
                                entryAux = entry.copy()
                                entryAux["id"] = featureID.replace("cpd:","")
                                ALL_PATHWAYS[pathway_id]["compounds"].append(entryAux)
                                #already_added[featureID] = 1
                            elif(entryType == "gene") and not featureID in already_added:
                                entryAux = entry.copy()
                                entryAux["id"] = featureID.replace(SPECIE + ":","")
                                ALL_PATHWAYS[pathway_id]["genes"].append(entryAux)
                                #already_added[featureID] = 1
                    elif (entryType == "map"):
                        graphicInfo = child.find("graphics")
                        pathAuxID = child.get("name").replace("path:", "").replace(SPECIE,"")
                        if pathway_id != SPECIE + pathAuxID:
                            entry = {
                                "id"     : pathAuxID,
                                "name"   : graphicInfo.get("name"),
                                "x"      : graphicInfo.get("x"),
                                "y"      : graphicInfo.get("y"),
                                "height" : graphicInfo.get("height"),
                                "width"  : graphicInfo.get("width")
                            }
                            ALL_PATHWAYS[pathway_id]["relatedPathways"].append(entry)


                except Exception as ex:
                    errorMessage = "FAILED WHILE PROCESSING PATHWAY KGML FILE [" + file_name + "]: " + str(ex)
                    FAILED_LINES["KEGG PATHWAYS"].append([errorMessage])

        except Exception as ex:
            errorMessage = "FAILED WHILE PROCESSING PATHWAY KGML FILE [" + file_name + "]: " + str(ex)

    TOTAL_FEATURES["KEGG PATHWAYS"]=total_lines

    # Select only KEGG pathways
    generatePathwaysNetwork({k: v for k,v in ALL_PATHWAYS.items() if v["source"] == "KEGG"})

    #STEP 4. PROCESS THE VERSION FILES
    file_name= DATA_DIR + "KEGG_VERSION"
    file = open(file_name, 'r')
    ALL_VERSIONS["KEGG"] = {"name" : "KEGG", "date" : file.readline().rstrip().split("\t")[1]}
    file.close()

    file_name= DATA_DIR + "mapping/MAP_VERSION"
    file = open(file_name, 'r')
    ALL_VERSIONS["MAPPING"] = {"name" : "MAPPING", "date" : file.readline().rstrip().split("\t")[1]}
    file.close()

def generatePathwaysNetwork(ALL_PATHWAYS):
    NODES = {}
    EDGES = []

    #***********************************************************************************
    #* STEP 1. FIRST PROCESS THE FILE WITH ALL PATHWAYS AND GENERATE A DIAGONAL MATRIX
    #          mmu00100 -> [ mmu00101 = 0, mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00101 -> [               mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00102 -> [                             mmu00103 = 0,...]
    #***********************************************************************************
    file_name = DATA_DIR + "../common/pathways_all.list"
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        for row in rows:
            path_id = row[0].replace("path:map","")
            path_name = row[1]
            NODES[path_id] = {"data": {"id": SPECIE + path_id, "label": path_name, "total_features": 0}, "group" : "nodes"}
    csvfile.close()
    all_pathways = sorted(NODES.keys())

    pathways_matrix = {}
    while len(all_pathways) > 0:
        current_path = all_pathways[0]
        del all_pathways[0]
        pathways_matrix[current_path] = dict(zip(all_pathways, [0]*len(all_pathways)))

    #***********************************************************************************
    #* STEP 2. PROCESS THE PATHWAYS CLASSIFICATION FILE AND ADD THE PARENT NODES AND UPDATE
    #          THE PATHWAYS parent FIELD
    #***********************************************************************************
    file_name= DATA_DIR + "../common/pathways_classification.list"
    csvfile = open(file_name, 'r')
    mainClassification=""; secondClassification=""
    mainClassificationID=0; secondClassificationID=0
    for line in csvfile:
        line = line.rstrip().split("  ")
        if line[0][0] == "A": #main classification
            mainClassificationID+=1
            mainClassification=line[0][1:]
            NODES[str(mainClassificationID) + "A"] = {"data": {"id": mainClassification.lower().replace(" ","_"), "label": mainClassification, "is_classification" : "A"}, "group" : "nodes"}
        elif line[0][0] == "B":
            secondClassificationID+=1
            secondClassification = line[1]
            NODES[str(secondClassificationID) + "B"] = {"data": {"id": secondClassification.lower().replace(" ","_"), "parent" : mainClassification.lower().replace(" ","_"), "label": secondClassification, "is_classification" : "B"}, "group" : "nodes"}
        elif line[0][0] == "C":
            pathway_id   = line[2]
            NODES[pathway_id]["data"]["parent"] = mainClassification.lower().replace(" ","_"),

    csvfile.close()
    #***********************************************************************************
    #* STEP 3. PROCESS THE FILE WITH THE RELATION GENE ID -> PATHWAY ID AND FILL THE MATRIX
    #          WITH THE NUMBER OF SHARED GENES
    #          mmu00100 -> [ mmu00101 = 1, mmu00102 = 0, mmu00103 = 0,...]
    #          mmu00101 -> [               mmu00102 = 5, mmu00103 = 3,...]
    #          mmu00102 -> [                             mmu00103 =20,...]
    #***********************************************************************************
    file_name = DATA_DIR + "gene2pathway.list"

    # Read the file into a dictionary to not rely on the KEGG
    # return format.
    gene2pathway = defaultdict(set)

    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')

        for row in rows:
            gene2pathway[row[0]].add(row[1].replace("path:" + SPECIE, ""))

    # Process the info
    for gene, associated_paths in gene2pathway.items():
        while len(associated_paths) > 0:
            current_path = associated_paths.pop()
            for other_path in associated_paths:
                try:
                    pathways_matrix[current_path][other_path] += 1
                except:
                    try:
                        pathways_matrix[other_path][current_path] += 1
                    except:
                        stderr.write("Pathways " + current_path + " or " + other_path + " not found at pathways_all.list. Updating common KEGG information may solve this issue. Reinstall this specie after that.\n")


    # Free memory
    del gene2pathway

    #***********************************************************************************
    #* STEP 4. GET THE NUMBER OF GENES FOR EACH PATHWAY
    #***********************************************************************************
    file_name = DATA_DIR + "pathway2gene.list"
    previous_pathway=""
    nGenes = 0
    with open(file_name, "r") as csvfile:
        rows = csv.reader(csvfile, delimiter='\t')
        for row in rows:
            path_id = row[0].replace("path:" + SPECIE, "")
            gene_id = row[1]
            if path_id != previous_pathway and previous_pathway!= "":
                try:
                    NODES[previous_pathway]["data"]["total_features"] += nGenes
                except:
                    stderr.write("No nodes information for Pathway " + previous_pathway + ".\n")
                    stderr.write("Updating the installed common KEGG information may solve this issue. Reinstall this species after that.\n")
                nGenes=0
            nGenes+=1
            previous_pathway = path_id
        #LAST PATHWAY
        NODES[previous_pathway]["data"]["total_features"] += nGenes
    csvfile.close()

    #***********************************************************************************
    #* STEP 5. BULK THE MATRIX INTO JSON:
    #          FOR EACH PATHWAY ID AND FOR EACH POSITION WITH NON ZERO (SHARE AT LEAST 1 GENE), CREATE AN EDGE
    #***********************************************************************************
    already_linked_pathways={}
    for path_id, shared_genes in pathways_matrix.items():
        #First create the edges based on the links between networks (extracted from KGML files)
        if SPECIE + path_id in ALL_PATHWAYS:
            relatedPathways = ALL_PATHWAYS[SPECIE + path_id]["relatedPathways"]
            for other_path_id in relatedPathways:
                if not path_id + "-" + other_path_id["id"] in already_linked_pathways:
                    EDGES.append({"data": {"id": path_id + "-" + other_path_id["id"], "source": SPECIE + path_id, "target": SPECIE + other_path_id["id"], "weight": 1, "class": 'l'}, "group":"edges"})
                    #Avoid repeated edges (including the opposite links)
                    already_linked_pathways[path_id + "-" + other_path_id["id"]] = 1
                    already_linked_pathways[other_path_id["id"]+ "-" + path_id] = 1
        #Add the edges based on the existance of shared genes
        for other_path_id, n_shared_genes in shared_genes.items():
            if n_shared_genes > 0:
                EDGES.append({"data": {"id": path_id + "-" + other_path_id, "source": SPECIE + path_id, "target": SPECIE + other_path_id, "weight": n_shared_genes, "class": 's'}, "group":"edges"})

    #***********************************************************************************
    #* STEP 6 SAVE THE NETWORK TO A FILE
    #***********************************************************************************
    network = {
        "nodes": list(NODES.values()),
        "edges": EDGES
    }
    csvfile = open(DATA_DIR + "pathways_network.json", 'w')
    csvfile.write(json.dumps(network, separators=(',',':')) + "\n")
    csvfile.close()


def mergeNetworkFiles():
    # Other files (MapMan or others)
    other_files = glob.glob(DATA_DIR + "pathways_network_*.json")

    if other_files:
        # Initialize the final dictionary in the way:
        # { DB: {network_info}, DB2: {network2_info}, ...}
        network_data = {}

        # Load KEGG network file
        with open(DATA_DIR + "pathways_network.json", 'r+') as kegg_handler:
            # Append KEGG data
            network_data["KEGG"] = json.load(kegg_handler)

            # Load each other databases
            for db_file in other_files:
                # Extract the DB name
                db_name = re.search(r"pathways_network_(.*)\.json", db_file).group(1)

                with open(db_file, 'r') as db_handler:
                    network_data[db_name] = json.load(db_handler)

            # Override the old contents with the new ones
            kegg_handler.seek(0)
            kegg_handler.write(json.dumps(network_data, separators=(',', ':')) + "\n")
            kegg_handler.truncate()


#**************************************************************************
# OTHER DATABASES
#**************************************************************************
def printResults():
    stderr.write("\n\n\n")
    stderr.write("\nVALID FEATURES LINES    : " + str(len(ALL_ENTRIES)))
    for key, value in FAILED_LINES.items():
        print("DATABASE:"+ key)
        print("Failed:" + len(value))
        print("All Feature:" + TOTAL_FEATURES[key])

    stderr.write("\n\n")

def dumpDatabase():
    #STEP1. GENERATE THE TABLE feature id --> [transcripts ids]

    # Remove the file if already exists to avoid adding
    # at the end of an invalid file.
    dump_xref_file = "/tmp/xref.tmp"

    if os.path.exists(dump_xref_file):
        os.remove(dump_xref_file)

    # To avoid depleting the ram completely, repeat the process for each database
    for dbid, db_values in transcript2xref.items():
        stderr.write("\nDumping database " + str(dbid))

        xref2xref = defaultdict(list)

        for transcriptID, value in db_values.items():
            for feature_id in value:
                xref2xref[feature_id].append(value)

        #STEP 2. DUMP THE xref TABLE INTO A FILE
        # Note: open the file for appending
        file = open(dump_xref_file, 'a')

        for elem in xref[dbid].values():
            item = elem.__dict__
            # item["mates"] = list(xref2xref.get(elem.getID(), []))
            item["mates"] = list(set(itertools.chain.from_iterable(xref2xref.get(elem.getID(), []))))

            if(len(item["mates"])> 0):
                file.write(json.dumps(item, separators=(',',':')) + "\n")
            else:
                stderr.write("No transcripts detected for " + elem.display_id + " ["+ elem.description + "]\n")

        file.close()

    #STEP 2. DUMP THE transcript2xref TABLE INTO A FILE
    file = open("/tmp/dbname.tmp", 'w')

    for elem in dbname.values():
        file.write(json.dumps(elem.__dict__, separators=(',',':')) + "\n")
    file.close()

    #STEP 3. DUMP THE pathways TABLE INTO A FILE
    file = open("/tmp/pathways.tmp", 'w')

    error_tolerance = int(len(list(ALL_PATHWAYS.items())) * 0.05)
    for elem in ALL_PATHWAYS.values():
        try:
            file.write(json.dumps(elem, cls=SetEncoder, separators=(',',':')) + "\n")
        except Exception as e:
            stderr.write(f"Error when dumping the pathways: {str(e)}\n")
            error_tolerance-=1
            if error_tolerance == 0:
                raise Exception("Too many errors while installing the pathways information. Aborting.")

    file.close()

    #STEP 4. DUMP THE VERSIONS TABLE INTO A FILE
    file = open("/tmp/versions.tmp", 'w')
    for elem in ALL_VERSIONS.values():
        file.write(json.dumps(elem, separators=(',',':')) + "\n")
    file.close()

def dumpErrors():
    #STEP 1. DUMP THE ERROR TABLE INTO A FILE
    file = open("/tmp/errors.tmp", 'w')

    try:
        for key, value in FAILED_LINES.items():
            if len(value) > 0:
                file.write("#************************************\n#\n# " + key + "\n#\n#************************************\n")
                for line in value:
                    file.write(line[0] + "\n")
                    file.write("\t" + "\t".join(line[1:]) + "\n")
                file.write("\n\n\n")
    except Exception as ex:
        raise ex
    finally:
        file.close()

def createDatabase():
    try:
        command = "mongoimport --db " + SPECIE + "-paintomics --collection xref  --drop --file /tmp/xref.tmp"
        check_call(command, shell=True)

        command = "mongoimport --db " + SPECIE + "-paintomics --collection dbname  --drop --file /tmp/dbname.tmp"
        check_call(command, shell=True)

        command = "mongoimport --db " + SPECIE + "-paintomics --collection kegg  --drop --file /tmp/pathways.tmp  --batchSize 1 --type json"
        check_call(command, shell=True)

        command = "mongoimport --db " + SPECIE + "-paintomics --collection versions  --drop --file /tmp/versions.tmp"
        check_call(command, shell=True)

        from pymongo import MongoClient, ASCENDING, TEXT
        from conf.serverconf import MONGODB_HOST, MONGODB_PORT
        client = MongoClient(MONGODB_HOST, MONGODB_PORT)

        db = client[SPECIE + "-paintomics"]

        db.xref.create_index([("dbname_id", ASCENDING),("_id", ASCENDING)])
        db.xref.create_index([("display_id", ASCENDING)])

    except CalledProcessError as ex:
        raise ex
    except Exception as ex:
        raise ex

def createGlobalDatabase():
    try:
        command = "mongoimport --db global-paintomics --collection versions  --drop --file /tmp/versions.tmp"
        check_call(command, shell=True)

        createCompoundsCollection()

    except CalledProcessError as ex:
        raise ex
    except Exception as ex:
        raise ex

def createCompoundsCollection():
    try:
        command = "mongoimport --db global-paintomics --collection kegg_compounds  --drop --file /tmp/compounds.tmp"
        check_call(command, shell=True)

        from pymongo import MongoClient, ASCENDING, TEXT
        from conf.serverconf import MONGODB_HOST, MONGODB_PORT
        client = MongoClient(MONGODB_HOST, MONGODB_PORT)
        db = client["global-paintomics"]
        db.kegg_compounds.create_index([("name", TEXT)])

    except CalledProcessError as ex:
        raise ex
    except Exception as ex:
        raise ex

def queryBiomart(URL, fileName, outputName, delay, maxTries):
    stderr.write("DOWNLOADING FROM " + URL + "\n")
    nTry = 1
    while nTry <= maxTries:
        wait(delay)
        try:
            check_call(["curl", "-G", "--connect-timeout", "300", "--max-time", "900", "--data-urlencode", 'query@' + fileName, URL, "-o", outputName])
            return True
        except Exception as e:
            nTry+=1
    raise Exception('Unable to retrieve ' + fileName + " from " + URL + "\n")

def downloadFile(URL, fileName, outputName, delay, maxTries, checkIfExists=False):
    stderr.write("DOWNLOADING " + URL + fileName + "\n")

    # If the file already exists, avoid downloading it again
    if checkIfExists and os.path.isfile(outputName) and os.stat(outputName).st_size > 0:
        return True

    nTry = 1
    while nTry <= maxTries:
        wait(delay)
        try:
            check_call(["curl", "--connect-timeout", "300", "--max-time", "1800",  URL + fileName, "-o", outputName])
            return True
        except Exception as e:
            nTry+=1
    raise Exception('Unable to retrieve ' + fileName + " from " + URL + "\n")

def wait(nSeconds):
    sleep(nSeconds)

class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)

#**************************************************************************
# VARIABLE DECLARATION
#**************************************************************************
#Temporal representation for XREF TABLES
xref = defaultdict(dict)
transcript2xref= defaultdict(dict)
xref2transcript = defaultdict(dict)
dbname = {}

#STORE ALL ENTRIES TO BE SAVED
ALL_ENTRIES = {}
ALL_DBS = {}
ALL_PATHWAYS = {}
ALL_VERSIONS = {}
KEY_ENTRIES = {}
KEGG_COMPOUNDS = {}
MAPMAN_COMPOUNDS = {}

#OTHER AUXILIAR TABLES OR VARIABLES
TOTAL_FEATURES = {}
FAILED_LINES = {}


DATA_DIR = ""
ROOT_DIR = ""
SPECIE  = ""
EXTERNAL_RESOURCES = None
COMMON_RESOURCES = None

kegg_id_2_refseq_tid = {}
external_mapping = {}
