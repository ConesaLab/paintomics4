#!/usr/bin/env Rscript
library(stringr)

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

# Create output directory if needed
if (!dir.exists(ROOT_REACTOME)) {
  dir.create(ROOT_REACTOME, recursive = TRUE)
}

# Function to process a single file - loads, processes, writes, and frees memory
processFile <- function(fileName, outputName, specie) {
  cat(paste0("Processing ", fileName, "...\n"))

  # Load file
  inputData = read.csv(file = paste0(ROOT, fileName, "_PE_All_Levels.txt"), sep = '\t', header = FALSE)

  # Process data
  inputData$V8 = as.factor(inputData$V8)
  inputData$V3 = sub(" .*", "", inputData$V3)

  # Filter and write for target species
  for (i in levels(inputData$V8)) {
    inputDataSave = inputData[inputData$V8 == i,]
    dirName = tolower(paste0(substr(strsplit(as.character(i), " ")[[1]][1], start = 1, stop = 1), substr(strsplit(as.character(i), " ")[[1]][2], start = 1, stop = 2)))
    if (dirName == specie) {
      write.table(inputDataSave[,1:4], file = paste0(ROOT_REACTOME, outputName, ".txt"), row.names = FALSE, col.names = FALSE, quote = FALSE, sep = '\t')
      cat(paste0("  Wrote ", nrow(inputDataSave), " rows for ", specie, "\n"))
      break
    }
  }

  # Explicitly free memory
  rm(inputData, inputDataSave)
  gc(verbose = FALSE)

  cat(paste0("Completed ", fileName, "\n"))
}

# Process files sequentially to minimize memory usage
cat("STEP 1: Processing Ensembl2Reactome...\n")
processFile("Ensembl2Reactome", "Ensembl2Reactome", specie)

cat("STEP 2: Processing NCBI2Reactome...\n")
processFile("NCBI2Reactome", "NCBI2Reactome", specie)

cat("STEP 3: Processing UniProt2Reactome...\n")
processFile("UniProt2Reactome", "UniProt2Reactome", specie)

cat("All Reactome data processing completed successfully.\n")

