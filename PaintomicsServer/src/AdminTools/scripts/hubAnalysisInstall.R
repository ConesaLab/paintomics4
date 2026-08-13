#!/usr/bin/env Rscript
flibrary <- library
library <- function(...) suppressPackageStartupMessages(flibrary(...))

# KEGGgraph was attached here and never called -- grep the whole hub path and it
# appears in no expression other than this line. It is a Bioconductor package, so
# loading it made a heavyweight dependency a hard prerequisite of every hub install
# for no benefit, and its absence aborted the run before the first pathway was read.
# Dropped. AnnotationDbi stays: unlist2() is used at the end of the compound loop.
# Fail with the package's NAME rather than a bare "there is no package called X"
# traceback from inside lapply().
for (pkg in c("readr", "tidyr", "rvest", "dplyr", "xml2", "stringr",
              "qdapRegex", "gtools", "jsonlite", "AnnotationDbi")) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    stop(paste0("Required R package '", pkg, "' is not installed; cannot build hub analysis data. ",
                "Install it and re-run: install.packages('", pkg, "')"))
  }
  library(pkg, character.only = TRUE)
}
options(timeout = 300) # Set timeout for the R session

result <- NULL

hubAnalysisInstall <- function(organism, scriptDir, outputDir, kgmlDir = NULL) {
  print(paste0("#######################STEP 0 ", "Start install hub analysis data...", "#######################"))
  source (paste0(scriptDir, "/GalaxyNetworkFunctionsv2.R"))

  print(paste0("#######################STEP 1 ", "Obtaining pathway information..."))
  listFile <- paste0(outputDir, "pathway_list.list")

  # The KEGG installer already wrote this exact list to <specie>/pathways.list --
  # byte-identical to what /list/pathway/<org> returns. Copy it instead of re-fetching,
  # which (with the local KGML below) makes a hub rebuild fully offline.
  localList <- if (!is.null(kgmlDir) && nzchar(kgmlDir)) {
    file.path(dirname(kgmlDir), "pathways.list")
  } else {
    NULL
  }

  if (!is.null(localList) && file.exists(localList) && file.info(localList)$size > 0) {
    print(paste0("STEP 1: reusing the already-downloaded pathway list at ", localList))
    file.copy(localList, listFile, overwrite = TRUE)
  } else {
    # https, not http: this was the only plain-http call in the installer, and
    # KeggParser already uses https for the very same host.
    # method="auto" (libcurl), not "wget": hardcoding wget made an external binary a
    # hard prerequisite, and it is absent on macOS by default -- the download failed
    # with a bare "sh: wget: command not found" before any pathway was read.
    listUrl <- sprintf("https://rest.kegg.jp/list/pathway/%s", organism)
    print(paste0("STEP 1: no local pathway list; downloading from ", listUrl))
    listStatus <- tryCatch(download.file(listUrl, listFile, method = "auto"),
                           error = function(e) { print(paste("pathway list download failed:", conditionMessage(e))); 1L })
    if (!identical(as.integer(listStatus), 0L)) {
      stop(paste0("Could not download the pathway list for '", organism, "' from ", listUrl))
    }
  }
  if (!file.exists(listFile) || file.info(listFile)$size == 0) {
    stop(paste0("Pathway list for '", organism, "' is missing or empty at ", listFile))
  }
  pathway_df <- read.delim(listFile, header = F)
  #Kegg_pathways<-unlist(sapply(strsplit(as.character(pathway_df$V1), split=':'), function (x) x[[2]]) )

  Kegg_pathways <- as.character(pathway_df$V1)
  # A truncated or error response used to sail straight into a 12-minute parse. Every
  # KEGG organism has far more than 50 pathways, and each id must look like <org><5 digits>.
  if (length(Kegg_pathways) < 50) {
    stop(paste0("Pathway list for '", organism, "' has only ", length(Kegg_pathways),
                " entries; refusing to build a hub network from it."))
  }
  bad <- !grepl(paste0("^(path:)?", organism, "[0-9]{5}$"), Kegg_pathways)
  if (any(bad)) {
    stop(paste0("Pathway list for '", organism, "' contains ", sum(bad),
                " entries that are not ", organism, " pathway ids (e.g. '",
                Kegg_pathways[which(bad)[1]], "')"))
  }

  print(paste0("#######################STEP 2 ", "Parsering pathway information..."))
  if (!is.null(kgmlDir) && nzchar(kgmlDir) && dir.exists(kgmlDir)) {
    print(paste0("STEP 2: reusing already-downloaded KGML from ", kgmlDir))
  } else {
    print("STEP 2: no local KGML directory supplied; every pathway will be fetched over HTTP")
    kgmlDir <- NULL
  }
  kegg_interactions <- KeggParser(Pathways=Kegg_pathways, kgmlDir=kgmlDir)

  # Record where the KGML came from, next to the data it produced.
  try(writeLines(
    c(paste0("local_kgml_hits=", attr(kegg_interactions, "local_kgml_hits")),
      paste0("http_fallbacks=",  attr(kegg_interactions, "http_fallbacks"))),
    paste0(outputDir, "kgml_source_report.txt")), silent = TRUE)
  
  print(paste0("#######################STEP 3 ", " Removing interactions with map..."))

  # Independent safety net for the group-expansion bug fixed in GalaxyNetworkFunctionsv2.R.
  # Nothing used to reject an endpoint that failed to parse, so such a row kept an empty
  # name and entered the graph as a node called "" that fused every unrelated complex
  # into one point (measured in the installed mmu data: "" reached degree 1381). An
  # unnamed endpoint is never a real biological entity. Drop it before anything else and
  # say how many, loudly -- a silent parse failure must never again look like a hub.
  # Applied to the full table so the CSV keeps its existing shape; the runtime
  # (hubAnalysis.R:65-66) still does its own map filter over whatever it is given.
  blankEndpoint <- is.na(kegg_interactions$entry_name_1) | !nzchar(kegg_interactions$entry_name_1) |
                   is.na(kegg_interactions$entry_name_2) | !nzchar(kegg_interactions$entry_name_2)
  if (any(blankEndpoint)) {
    print(paste0("STEP 3: dropped ", sum(blankEndpoint), " of ", nrow(kegg_interactions),
                 " interactions with a blank/NA endpoint"))
    kegg_interactions <- kegg_interactions[!blankEndpoint,]
  }

  hknomap1<-kegg_interactions[kegg_interactions$entry_type_1 != "map",]
  keggNoMap<-hknomap1[hknomap1$entry_type_2 != "map",]
  if (nrow(keggNoMap) == 0) {
    stop("No usable interactions left after filtering; refusing to write an empty network.")
  }

  write.csv(kegg_interactions, paste0(outputDir,"/kegg_interaction.csv"), row.names = FALSE)
  print(paste0("#######################STEP 4 ", " Generation interactions networks"))
  InteractionsByStepsAllmetabs<- function (InteractionsTable, Steps = 4, dir) {
    # Funtion to calculate the interactions by steps that can be provided by the user
    # Input: 
    # InteractionsTable: A table with the information of all possible interactions in a particular species like "All_human_kegg_interactions30march2020.csv"
    # SignificantNodes: A vector with the differentially expressed nodes
    # Steps: Number of steps to be analyzed as a measure of "distance" between nodes.
    # PreviousCalculation: To merge previous calculated data to be able to partition the data analysis
    # Output:
    # A list of tables of interacions between nodes, by steps.
    # and a table indicating if the node is significant or not
    ####
    
    print("STEP 4.1 Using all compounds present in the dataset")
    clu<- unique(as.character(InteractionsTable$entry_name_1[InteractionsTable$entry_type_1 == "compound"]))
    clu2<- unique(as.character(InteractionsTable$entry_name_2[InteractionsTable$entry_type_2 == "compound"]))
    allcompounds<-unique(c(clu,clu2))
    print(paste(length(allcompounds), "will be analyzed"  ))
    #allcompounds<-c("C00267", "C00221", "C01172", "C00668", "C05345")
    prety1<-unique(InteractionsTable[,c("entry_type_1","entry_name_1")])
    prety2<-unique(InteractionsTable[,c("entry_type_2","entry_name_2")])
    colnames(prety1) =colnames(prety2) = c("type", "name")
    types<-unique(rbind(prety1,prety2))
    rownames(types)<-seq(1:nrow(types))
    
    Allintersnorepeated<-InteractionsTable[,c("entry_name_1","entry_name_2")]
    Allintersnorepeated<-Allintersnorepeated[!duplicated(Allintersnorepeated), ]
    
    
    allactors<-unique(c(as.character(InteractionsTable$entry_name_1), as.character(InteractionsTable$entry_name_2)))
    
    
    prelist<-tabelita<-list()
    theTables<-NULL
    
    saveProcess <- 0 # track the process
    currentProcess <- 0
    
    for (i in 1:length (allcompounds)){
      currentProcess <- round(i/length(allcompounds)*100)
      if (currentProcess != saveProcess && currentProcess %% 10 == 0) {
        print(paste0(currentProcess,'% completed'))
        saveProcess = currentProcess
      }
      actor<-allcompounds[i]
      t1<-Allintersnorepeated[Allintersnorepeated$entry_name_1 == actor,]
      colnames(t1)<-c("Var1","Var2")
      t2<-Allintersnorepeated[Allintersnorepeated$entry_name_2 == actor,]
      t2<-t2[,c(2,1)]
      colnames(t2)<-c("Var1","Var2")
      t3<-unique(rbind(t1,t2))
      rownames(t3)<- seq(1:nrow(t3) )
      namecito<-unique(as.character(t3$Var1))
      preos<-as.character(t3$Var2)
      
      prelist["1"]<-list(preos)
      tabelita<-prelist
      theTables[[namecito]]<-tabelita

      if (Steps>1) {
        #print (paste (Steps,"Steps", sep=" "))
        #print("Analyzing more than one step")
        vectorNames<-c ("2","3","4","5","6","7","8","9",
                        "10","11","12","13","14","15",
                        "16","17","18","19","20", "21")
        vectitonumbs<-vectorNames[1:(Steps-1)]
        vectitonames<-paste(vectitonumbs)
        
        preos<-NULL
        prelist<-tabelita<-list()
        #prelist<-NULL
        for (vn in 1:length(vectitonames) ) {
          #print (vectitonames[vn])
          namestep<-vectitonames[vn]
          lalistita<-theTables[[vn]][[1]]
          elcompound<-names(theTables[1])
          susinteracciones<-lalistita
          #losactoresdecadalista<-theTables[[n]][[i]] 
          #preos<-prelist<-tabelita<-list()
          t1<-Allintersnorepeated[is.element(Allintersnorepeated$entry_name_1,susinteracciones),]
          colnames(t1)<-c("Var1","Var2")
          t2<-Allintersnorepeated[is.element(Allintersnorepeated$entry_name_2,susinteracciones),]
          t2<-t2[,c(2,1)]
          colnames(t2)<-c("Var1","Var2")
          t3<-unique(rbind(t1,t2))
          rownames(t3)<- seq(1:nrow(t3) )
          namecito<-elcompound
          preos<-unique(c(susinteracciones,setdiff(as.character(unique(t3$Var2) ),elcompound )) ) 
          prelist[namestep]<-list(preos)
          
          
          tabelita[[namecito]]<-prelist
          theTables<-c(theTables,tabelita)
          tabelita<-prelist<-list()
        } # End of steps
        
      }# End of if Steps>1
      save(theTables,file=paste(dir,"/",elcompound,".RData",sep=''))
      temp <- unlist2(theTables, 0)
      result[[actor]] <- temp
      theTables<-NULL
    } # End of all compounds
    return(result)
  }
  invisible(InteractionsByStepsAllmetabs(InteractionsTable = keggNoMap, Steps = 4,dir=paste0(outputDir)))
}
rawArgs <- commandArgs(T)
# Split on the FIRST '=' only, and build the list explicitly. The old parser was
#   as.data.frame(do.call("rbind", strsplit(..., "=")))
# which (a) split a value containing '=' into extra columns and (b) silently recycled
# through rbind when an argument had no '=' at all -- so `--kgmlDir=` produced
# args$kgmlDir == "kgmlDir", a relative path that exists nowhere and sent every
# pathway back over HTTP with no error.
argsL <- list()
for (a in rawArgs) {
  a <- gsub("\"", "", sub("^--", "", a))
  eq <- regexpr("=", a, fixed = TRUE)
  if (eq > 0) {
    key <- substr(a, 1, eq - 1)
    val <- substr(a, eq + 1, nchar(a))
    if (nzchar(key) && nzchar(val)) argsL[[key]] <- val
  }
}
args <- argsL
for (required in c("organism", "scriptDir", "outputDir")) {
  if (is.null(args[[required]])) stop(paste0("Missing required argument --", required))
}

result <- hubAnalysisInstall(organism = args$organism, scriptDir = args$scriptDir,
                             outputDir = args$outputDir, kgmlDir = args$kgmlDir)

print(paste0("#######################STEP 5 ", "Saving installation data..."))
# toJSON() already returns finished JSON; passing it to write_json() encoded it a SECOND
# time, so the file was a 1-element array wrapping ~62 MB of escaped text (77 MB on
# disk) that the reader had to unwrap twice. Write the JSON itself. The consumer's
# unwrap loop (PathwayAcquisitionJob.py:2273-2287) accepts both shapes, so this ships
# safely against already-installed data.
writeLines(jsonlite::toJSON(result, pretty = FALSE),
           con = paste0(args$outputDir, "/kegg_interaction.json"))

