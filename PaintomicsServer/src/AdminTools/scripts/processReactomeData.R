#!/usr/bin/env Rscript

args <- commandArgs(T)
args <- commandArgs(T)
parseArgs <- function(x) strsplit(sub("^--", "", gsub("\"", "", x)), "=")
#args = parseArgs(args)

argsDF <- as.data.frame(do.call("rbind", parseArgs(args)), stringsAsFactors=F)
argsL <- as.list(as.character(argsDF$V2))
names(argsL) <- argsDF$V1
args <- as.data.frame(argsL, stringsAsFactors=F)

specie <- args$specie
ROOT <- args$root
#specie = 'hsa'
#ROOT = '/home/tian/Downloads/database/KEGG_DATA/current/common/'
ROOT_REACTOME = paste0(ROOT, "../", specie ,"/mapping/reactome/")

library(stringr)

cat("STEP 1 LOODING FILES...")
#ChEBI2Reactome = read.csv(file = paste0(ROOT, "ChEBI2Reactome_PE_All_Levels.txt"), sep = '\t', header = FALSE)
Ensembl2Reactome = read.csv(file = paste0(ROOT, "Ensembl2Reactome_PE_All_Levels.txt"), sep = '\t', header = FALSE)
NCBI2Reactome = read.csv(file = paste0(ROOT, "NCBI2Reactome_PE_All_Levels.txt"), sep = '\t', header = FALSE)
UniProt2Reactome = read.csv(file = paste0(ROOT, "UniProt2Reactome_PE_All_Levels.txt"), sep = '\t', header = FALSE)

Ensembl2Reactome$V8 = as.factor(Ensembl2Reactome$V8)
Ensembl2Reactome$V3 = sub(" .*", "", Ensembl2Reactome$V3)

NCBI2Reactome$V8 = as.factor(NCBI2Reactome$V8)
NCBI2Reactome$V3 = sub(" .*", "", NCBI2Reactome$V3)

UniProt2Reactome$V8 =  as.factor(UniProt2Reactome$V8)
UniProt2Reactome$V3 = sub(" .*", "", UniProt2Reactome$V3)


processData <- function(inputData, inputDataType, specie) {
  if (!dir.exists(ROOT_REACTOME)) {
    dir.create(ROOT_REACTOME)
  }
  for (i in levels( inputData$V8 )) {
    inputDataSave = inputData[inputData$V8 == i,]
    dirName = tolower(paste0(substr(strsplit(as.character(i), " ")[[1]][1], start = 1, stop = 1), substr(strsplit(as.character(i), " ")[[1]][2], start = 1, stop = 2)))
    if (dirName == specie) {
      write.table(inputDataSave[,1:4], file = paste0(ROOT_REACTOME,inputDataType, ".txt"), row.names = FALSE, col.names = FALSE, quote = FALSE, sep = '\t')
      break
    }
  }
}

cat("STEP 2 PROCESS DATA...")
processData(Ensembl2Reactome, "Ensembl2Reactome", specie)
processData(NCBI2Reactome, "NCBI2Reactome", specie)
processData(UniProt2Reactome, "UniProt2Reactome", specie)

