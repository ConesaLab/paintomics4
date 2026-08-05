#!/usr/bin/env Rscript
#
# Extract the rows for one species from the Reactome "*2Reactome_PE_All_Levels"
# tables and write them to <root>/../<specie>/mapping/reactome/.
#
# Called by common_build_database.py::processReactomePathwaysData().
#
# Usage: processReactomeData.R --specie=hsa --root=/path/to/KEGG_DATA/current/common/

args <- commandArgs(TRUE)
parseArgs <- function(x) strsplit(sub("^--", "", gsub("\"", "", x)), "=")

argsDF <- as.data.frame(do.call("rbind", parseArgs(args)), stringsAsFactors = FALSE)
argsL <- as.list(as.character(argsDF$V2))
names(argsL) <- argsDF$V1
args <- as.data.frame(argsL, stringsAsFactors = FALSE)

specie <- args$specie
ROOT <- args$root

if (is.null(specie) || is.na(specie) || specie == "") {
  stop("processReactomeData.R: --specie is required (e.g. --specie=hsa)")
}
if (is.null(ROOT) || is.na(ROOT) || ROOT == "") {
  stop("processReactomeData.R: --root is required")
}

ROOT_REACTOME <- paste0(ROOT, "../", specie, "/mapping/reactome/")

if (!dir.exists(ROOT_REACTOME)) {
  dir.create(ROOT_REACTOME, recursive = TRUE)
}

# ---------------------------------------------------------------------------
# KEGG organism code -> Reactome species name.
#
# The species column holds a full binomial ("Homo sapiens"). The previous
# implementation derived a KEGG code from it as first-letter + first-two-letters
# of the epithet. That silently produces the wrong code wherever KEGG does not
# follow the pattern -- rice is "osa" by the heuristic but "dosa" in KEGG and in
# this repo's resource directories -- and a wrong code means zero rows matched,
# no output file, and a build that still reported success.
#
# Explicit table first, heuristic only as a fallback for species not listed.
# ---------------------------------------------------------------------------
KEGG_TO_REACTOME_SPECIES <- c(
  hsa  = "Homo sapiens",
  mmu  = "Mus musculus",
  rno  = "Rattus norvegicus",
  ptr  = "Pan troglodytes",
  bta  = "Bos taurus",
  cfa  = "Canis familiaris",
  ssc  = "Sus scrofa",
  gga  = "Gallus gallus",
  xtr  = "Xenopus tropicalis",
  dre  = "Danio rerio",
  dme  = "Drosophila melanogaster",
  cel  = "Caenorhabditis elegans",
  sce  = "Saccharomyces cerevisiae",
  spo  = "Schizosaccharomyces pombe",
  ddi  = "Dictyostelium discoideum",
  pfa  = "Plasmodium falciparum",
  mtu  = "Mycobacterium tuberculosis",
  ath  = "Arabidopsis thaliana",
  dosa = "Oryza sativa",
  sly  = "Solanum lycopersicum"
)

speciesName <- unname(KEGG_TO_REACTOME_SPECIES[specie])

if (is.na(speciesName)) {
  cat(paste0("WARNING: '", specie, "' is not in the KEGG->Reactome species table; ",
             "falling back to name matching.\n"))
  speciesName <- NA
}

#' Read one mapping table, keep the rows for this species, and write them out.
#'
#' quote = "" and comment.char = "" are required. Reactome display names contain
#' apostrophes ("5'-phosphate") and double quotes, which R's defaults treat as
#' string delimiters -- silently merging rows and shifting every column.
processFile <- function(fileName, outputName, specie, speciesName) {
  inputPath <- paste0(ROOT, fileName, "_PE_All_Levels.txt")
  cat(paste0("Processing ", basename(inputPath), "...\n"))

  if (!file.exists(inputPath)) {
    stop(paste0("Reactome source file missing: ", inputPath,
                "\nRun the download step with --reactome=1 first."))
  }

  # Pre-filter with grep so only this species' rows are parsed. These tables run
  # to hundreds of MB across all species; read.delim on the whole file needs
  # several GB of RAM and minutes of parsing to then discard almost all of it.
  # The grep is a superset filter -- the exact match below still decides.
  filtered <- NULL
  if (!is.na(speciesName)) {
    filtered <- tryCatch(
      read.delim(pipe(paste("grep -F", shQuote(speciesName), shQuote(inputPath))),
                 header = FALSE, quote = "", comment.char = "",
                 stringsAsFactors = FALSE),
      error = function(e) NULL
    )
  }

  # Fallback: no species table entry, or grep produced nothing usable.
  if (is.null(filtered) || nrow(filtered) == 0) {
    inputData <- read.delim(inputPath, header = FALSE, quote = "",
                            comment.char = "", stringsAsFactors = FALSE)
    if (ncol(inputData) < 8) {
      stop(paste0("Unexpected column count (", ncol(inputData), ") in ", inputPath))
    }
    if (is.na(speciesName)) {
      # Heuristic: "Mus musculus" -> "mmu".
      codes <- tolower(paste0(
        substr(sub(" .*", "", inputData$V8), 1, 1),
        substr(sub("^\\S+ ", "", inputData$V8), 1, 2)))
      filtered <- inputData[codes == specie, , drop = FALSE]
    } else {
      filtered <- inputData[inputData$V8 == speciesName, , drop = FALSE]
    }
    rm(inputData)
    gc(verbose = FALSE)
  } else {
    if (ncol(filtered) < 8) {
      stop(paste0("Unexpected column count (", ncol(filtered), ") in ", inputPath))
    }
    filtered <- filtered[filtered$V8 == speciesName, , drop = FALSE]
  }

  if (nrow(filtered) == 0) {
    stop(paste0("No rows matched species '", specie, "'",
                if (!is.na(speciesName)) paste0(" ('", speciesName, "')") else "",
                " in ", basename(inputPath), ".\n",
                "Reactome does not cover every KEGG organism. Install this ",
                "species with --reactome=0, or add it to KEGG_TO_REACTOME_SPECIES."))
  }

  # Column 3 is "<id> <description>"; downstream code wants only the identifier.
  filtered$V3 <- sub(" .*", "", filtered$V3)

  outputPath <- paste0(ROOT_REACTOME, outputName, ".txt")
  write.table(filtered[, 1:4], file = outputPath, row.names = FALSE,
              col.names = FALSE, quote = FALSE, sep = "\t")
  cat(paste0("  Wrote ", nrow(filtered), " rows for ", specie, " -> ", outputPath, "\n"))

  rm(filtered)
  invisible(gc(verbose = FALSE))
}

cat("STEP 1: Processing Ensembl2Reactome...\n")
processFile("Ensembl2Reactome", "Ensembl2Reactome", specie, speciesName)

cat("STEP 2: Processing NCBI2Reactome...\n")
processFile("NCBI2Reactome", "NCBI2Reactome", specie, speciesName)

cat("STEP 3: Processing UniProt2Reactome...\n")
processFile("UniProt2Reactome", "UniProt2Reactome", specie, speciesName)

cat("All Reactome data processing completed successfully.\n")
