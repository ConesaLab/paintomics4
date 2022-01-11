#!/usr/bin/env Rscript
library(purrr)

args <- commandArgs(T)
parseArgs <- function(x) strsplit(sub("^--", "", gsub("\"", "", x)), "=")
argsDF <- as.data.frame(do.call("rbind", parseArgs(args)), stringsAsFactors=F)
argsL <- as.list(as.character(argsDF$V2))
names(argsL) <- argsDF$V1
args <- as.data.frame(argsL, stringsAsFactors=F)


tryCatch(               
  expr = {
    kegg_interactions = read.csv(paste0(args$inputDir,"kegg_interaction.csv"), sep = ',')
    userDataset = as.character(as.vector(t(read.table(paste0(args$data_dir,"userDataset.csv"), sep = ','))))
    userDEfeatures = as.character(as.vector(t(read.table(paste0(args$data_dir,"userDEfeatures.csv"), sep = ','))))
    print("STEP0: Finish Reading data...")
  },
  error = function(e){
    userDEfeatures = c()
    print("No compounds relevant/expression data...")
  },
  
  warning = function(w){      
    print("There was a warning message.")
  },
  
  finally = {            
    print("Next Step...")
  }
)


all_met_neigh <- list()
for (i in 1: length(dir(args$inputDir))) {
  if(grepl(".RData", dir(args$inputDir)[i], fixed=TRUE)){
    load(paste0(args$inputDir,dir(args$inputDir)[i]))
    theTablesFlat <- flatten(theTables)
    all_met_neigh[[i]] <- theTablesFlat
    names(all_met_neigh)[i] <- names(theTables)[1]
    names(all_met_neigh[[i]]) <- paste(names(theTables)[1], 1:4, sep = "_")
  }
}

PercDEinMetaboliteNeighbours <- function (neighbours, genes, DEG) {
  # This function calculate the number of DEG among a given metabolite gene neighbours
  if (class(neighbours) == "list") {neighbours = neighbours[[1]]}
  measured_neighbours <- intersect(neighbours, genes)
  DEneigbhours <- intersect(measured_neighbours, DEG) # neighbours that are DE
  notDEneigbhours <- setdiff(measured_neighbours, DEneigbhours) # neighbours that are notDE
  neigh <- length (neighbours)
  measured_neigh <- length (measured_neighbours)
  DEN <- length(DEneigbhours)
  noDEN <- length(notDEneigbhours)
  percDEN <- round(DEN/(noDEN+DEN),4)
  result <- c(KEEG_neighbours = neigh, InDataset_neighbours = measured_neigh,
              DEN = DEN, noDEN = noDEN, percDEN = percDEN)
  result
}
prepare_KEGG <- function (kegg_interactions, features, significant_features) {
  ################################################
  # Step 1: Removing interactions with  Map
  #dim(kegg_interactions) # 122875 x 9
  hknomap1<-kegg_interactions[kegg_interactions$entry_type_1 != "map",]
  keggNoMap<-hknomap1[hknomap1$entry_type_2 != "map",]
  table(keggNoMap$entry_type_1)
  table(keggNoMap$entry_type_2)
  dim(keggNoMap) # 120667 x 9... 122875 - 120667 = 2208 map links eliminated
  
  ################################################
  # Determining the number of differentially expressed metabolites 
  prety1 <- unique(keggNoMap[,c("entry_type_1","entry_name_1")])
  prety2 <- unique(keggNoMap[,c("entry_type_2","entry_name_2")])
  colnames(prety1) = colnames(prety2) = c("type", "name")
  types <- unique(rbind(prety1,prety2))
  rownames(types) <- seq(1:nrow(types))
  typesC <- types[types$type == "compound",]
  typesG <- types[(types$type == "gene"),]
  
  # Measured metabolites that are in KEGG
  metabolites <- intersect(features,as.character(typesC$name))
  
  # Measured genes that are in KEGG
  genes <- intersect(features ,as.character(typesG$name))
  
  # Differentially expressed metabolites that are in KEGG
  DEM <- intersect(significant_features,typesC$name)
  
  # Differentially expressed genes that are in KEGG
  DEG <- intersect(significant_features ,typesG$name)
  
  result <- list(metabolites = metabolites, 
              genes = genes,
              DEM = DEM,
              DEG = DEG)
  result
}

mydata <- prepare_KEGG (kegg_interactions = kegg_interactions, features = userDataset,
                        significant_features = userDEfeatures)
DEm <- mydata$DEM
myfunction <- function (x) {
  as.data.frame(purrr::map(x, PercDEinMetaboliteNeighbours, 
                           genes = mydata["genes"][[1]], DEG = mydata["DEG"][[1]])) }

all.perc <- purrr::map(all_met_neigh, myfunction)

extract.per <- function (x, step) {
  value <- x[5,step]
  value
}

step1 <- purrr::map_dbl( all.perc, extract.per, step = 1)
step2 <- purrr::map_dbl( all.perc, extract.per, step = 2)
step3 <- purrr::map_dbl( all.perc, extract.per, step = 3)
step4 <- purrr::map_dbl( all.perc, extract.per, step = 4)

processData = function(stepNumber) {
  stepNumber <- as.matrix(stepNumber)
  stepNumber[is.na(stepNumber)[,1],] <- 0
  stepNumber_DEm <-as.data.frame(stepNumber[rownames(stepNumber) %in% DEm,])
  stepNumber_except_DEm <- as.data.frame(stepNumber[!rownames(stepNumber) %in% DEm,])
  colnames(stepNumber_DEm) = colnames(stepNumber_except_DEm) = "Density"
  #Calculate percentile for each DEm
  percentile <- as.vector(apply(stepNumber_DEm, 1,  function(x) ecdf(stepNumber_except_DEm$Density)(x)))
  stepNumber_DEm$Name = rownames(stepNumber_DEm)
  stepNumber_DEm$Percentile <- percentile
  return(stepNumber_DEm)
}
step1_DEm <- processData(step1)
step1_DEm$Step <- 1

step2_DEm <- processData(step2)
step2_DEm$Step <- 2

step3_DEm <- processData(step3)
step3_DEm$Step <- 3

step4_DEm <- processData(step4)
step4_DEm$Step <- 4

final_result <- rbind(step1_DEm, step2_DEm, step3_DEm, step4_DEm)

final_result$DEN <- NA
final_result$noDEN <- NA
#extract DE/noDE neighbors
for (i in 1:nrow(final_result)){
  neighbors <- as.data.frame(all.perc[final_result$Name[i]])[3:4,final_result$Step[i]]
  DEN = neighbors[1]
  noDEN = neighbors[2]
  final_result$DEN[i] <- DEN
  final_result$noDEN[i] <- noDEN
}

#ggplot(step1_except_DEm, aes(x=Density)) + 
#  geom_vline(aes(xintercept=step1_95),
#             color="blue", linetype="dashed", size=1)+
#  geom_density() + 
#  geom_point(data = step1_DEm, aes(Density,2),
#             position = position_jitter(width = 0, height= 1, seed = 2))+
#  geom_text(data = step1_DEm, aes(Density, 2,label= name), position =position_jitter(width = 0, height= 1, seed = 2),vjust=-1, size=6)


output_file <- paste0(args$data_dir, "/hub_result.csv")
write.table(final_result, file=output_file, quote = FALSE, sep="\t", row.names = FALSE, col.names =FALSE)



