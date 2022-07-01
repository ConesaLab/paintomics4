#!/usr/bin/env Rscript
flibrary <- library
library <- function(...) suppressPackageStartupMessages(flibrary(...))
library(KEGGgraph)
library(readr)
library(tidyr)
library(rvest)
library(dplyr)
library(xml2)
library(stringr)
library(qdapRegex)
library(gtools)
library(jsonlite)
library(AnnotationDbi)
result <- NULL

hubAnalysisInstall <- function(organism, scriptDir, outputDir) {
  print(paste0("#######################STEP 0 ", "Start install hub analysis data...", "#######################"))
  source (paste0(scriptDir, "/GalaxyNetworkFunctionsv2.R"))
  
  print(paste0("#######################STEP 1 ", "Downloading pathway information..."))
  download.file(sprintf("http://rest.kegg.jp/list/pathway/%s", organism),
                paste0(outputDir,"/pathway_list.list"))
  pathway_df <- read.delim(paste0(outputDir,"/pathway_list.list"), header = F)
  Kegg_pathways<-unlist(sapply(strsplit(as.character(pathway_df$V1), split=':'), function (x) x[[2]]) )
  print(paste0("#######################STEP 2 ", "Parsering pathway information..."))
  kegg_interactions <- KeggParser(Pathways=Kegg_pathways)
  
  print(paste0("#######################STEP 3 ", " Removing interactions with map..."))
  hknomap1<-kegg_interactions[kegg_interactions$entry_type_1 != "map",]
  keggNoMap<-hknomap1[hknomap1$entry_type_2 != "map",]
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
args <- commandArgs(T)
parseArgs <- function(x) strsplit(sub("^--", "", gsub("\"", "", x)), "=")
#args = parseArgs(args)
argsDF <- as.data.frame(do.call("rbind", parseArgs(args)), stringsAsFactors=F)
argsL <- as.list(as.character(argsDF$V2))
names(argsL) <- argsDF$V1
args <- as.data.frame(argsL, stringsAsFactors=F)
result <- hubAnalysisInstall(organism = args$organism, scriptDir = args$scriptDir, outputDir = args$outputDir)

print(paste0("#######################STEP 5 ", "Saving installation data..."))
jsonResult <- jsonlite::toJSON(result, pretty = FALSE)

write_json(jsonResult, path = paste0(args$outputDir, "/kegg_interaction.json"))

