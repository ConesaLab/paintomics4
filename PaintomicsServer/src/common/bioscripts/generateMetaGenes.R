#!/usr/bin/env Rscript

#Functions
getBestIndexBy2SlopeLesser1stQuartilSlope <- function(p) {
  v = 2:nrow(p$data)
  y = p$data$y[v]-p$data$y[v-1]
  firstQ = summary(y)[2]
  c = NULL
  for(i in 1:(length(y)-1)){
    if(y[i]<=firstQ & y[i+1]<=abs(firstQ)){
      c = c(c,i+2)
    }
  }
  index = which(p$data$y==min(p$data$y[c])) #de los elegidos, el de menor suma de cuadrado
  return(index)
}
## Collect arguments   -----------------------------------------------------------------------------------------------
args <- commandArgs(T)

## Default setting when no arguments passed --------------------------------------------------------------------------
if(length(args) < 5) {
  args <- c("--help")
}

## Help section
if("--help" %in% args) {
  cat('
      The R Script
 
      Arguments:
      --specie=someValue       - character, specie code e.g. mmu
      --input_file=someValue   - character, name for the input file
      --ouput_prefix=someValue - character, prefix for all output files
      --data_dir=someValue     - character, directory where saving temporal and output files 
      --kegg_dir=someValue     - character, location for KEGG data
      --sources_dir=someValue  - character, location for other R scritps
      --cutoff=someValue       - numerical, cutoff for the PCA Function (optional, default 0.3)
      --cluster=someValue      - character, clustering method (kmeans or hmclust),  (optional, default kmeans)
      --kclusters=someValue    - numerical, number of clusters for K-means/Mclust (optional, default calculated dinamically)
      --database=someValue     - character, name of the database (optional, default KEGG)

      --help                 - print this text
 
      Example:
      ./generateMetaGenes.R --specie="mmu" --input_file="Gene expression_matched.txt" --output_prefix="gene_expression" --data_dir="/home/rhernandez/Desktop/test/" --kegg_dir="/data/KEGG_DATA/ --sources_dir="/home/rhernandez/Desktop/workspace/paintomics/PaintomicsServer/src/common/bioscripts/"\n\n')
  
  q(save="no")
}

## Parse arguments (we expect the form --arg=value)
cat("generateMetaGenes.R - STEP 1. Parse arguments, ")
parseArgs <- function(x) strsplit(sub("^--", "", gsub("\"", "", x)), "=")
argsDF <- as.data.frame(do.call("rbind", parseArgs(args)), stringsAsFactors=F)
argsL <- as.list(as.character(argsDF$V2))
names(argsL) <- argsDF$V1
args <- as.data.frame(argsL, stringsAsFactors=F)

args <- data.frame(specie="ath",
                   input_file="Gene expression_matched_test.txt",
                   output_prefix="res",
                   data_dir="/home/tian/Downloads/",
                   kegg_dir='/home/tian/database/KEGG_DATA/',
                   sources_dir='/home/tian/paintomics/paintomics4/PaintomicsServer/src/common/bioscripts',
                   stringsAsFactors = F,
                   cluster="kmeans")

## cutoff default
if(is.null(args$cutoff)) {
  # use mean(apply(data,1,var))*1.3  when B2GScore was not run
  args$cutoff <- 0.3
}
## cutoff default
if(is.null(args$cluster)) {
  args$cluster <- "kmeans" #default
}

if(is.null(args$database)) {
  args$database <- ""
} else {
  args$database <- paste("_", tolower(args$database), sep="")
}

args$kegg_dir <- paste0(args$kegg_dir, "current/", args$specie, "/gene2pathway",args$database, ".list", sep="")


# LOAD DEPENDENCIES   --------------------------------------------------------------------------------------------
cat("STEP 2. Load dependencies, ")
setwd(args$sources_dir)
source("PCA2GO.2.R")
source("PCA-GENES.R")

# parameters for PCA on genes of a GO
PCA2GO.fun = "PCA2GO.2"  # change to PCA2GO.2 when  B2GScore was not run
sel = "single%"


#LOAD DATA    ---------------------------------------------------------------------------------------------------
cat("STEP 3. Load input data, ")
#dir.create(args$data_dir, showWarnings = FALSE)
setwd(args$data_dir)
# Read the reference file
genes2pathway <- data.frame(read.table(file=args$kegg_dir, header=FALSE, sep="\t", quote="", as.is=TRUE))
# genes2pathway <-data.frame(lapply(genes2pathway, function(v) {
#   # if (is.character(v)) return(tolower(v))
#   # else return(v)
#   return(v)
# }))

# Lower gene names only
genes2pathway[,1] <- tolower(genes2pathway[,1])

# Read the input file
# Example 
# ENSMUSG00000034875	Nudt19	110959	0.0013615644203	-0.00727757835919	-0.015612884896	-0.0444182798681	-0.132208079869	-0.163256775828
input_data <- read.table(file=args$input_file, header=FALSE, sep="\t", quote="")
# Remove duplicates 
# TODO: now we are just ignoring the duplicates and taking the first match, maybe we should calculate mean?
input_data <- input_data[!duplicated(input_data$V3),]
# Adapt input data to a data.frame object
if (args$database == "") {
  input_data <- data.frame(input_data[,4:ncol(input_data)], row.names=paste(args$specie,":", tolower(input_data[,3]), sep=""))
  
  input_data <- input_data[,2:ncol(input_data)]
  #input_data <- data.frame(input_data[,5:ncol(input_data)], row.names=paste(args$specie, ":", tolower(input_data[,3]), sep=""))
} else {
  input_data <- data.frame(input_data[,5:ncol(input_data)], row.names=tolower(input_data[,3]))
}

#genes2pathway[which(genes2pathway[,1] %in% rownames(input_data)),]
# GET METAGENES  ------------------------------------------------------------------------------------------------
cat("STEP 4. Obtaining metagenes, ")
expression_GO <- get(PCA2GO.fun)(input_data, genes2pathway, var.cutoff = args$cutoff, fac.sel =  sel)


# ADJUST GENE DIRECTION -----------------------------------------------------------------------------------------
##for each metagene
adjust.direction <- function (expression_GO) {
  metagenes <- expression_GO$X.sel
  for (i in 1:length(row.names(metagenes)) ) {
    cur_pathway_id <- unlist(lapply(strsplit(row.names(metagenes)[i], "_"), function(x) x[1]))
    #loadings indicates the contribution of each gene to PC1
    #The loading sign is not arbitrary. 
    #Positive loading indicates positive correlation of gene expression with the scores while negative loading indicates negative correlation.
    gene_loadings <- unlist(expression_GO$X.loadings[i])
    #select genes that contribute most in a given component as
    # abs(loading del gen)/sum(abs(loadings de todos los genes)
    nGenes <- length(gene_loadings)
    loadings_sum <- sum(abs(gene_loadings))
    has_positives<-0
    has_negatives<-0
    selected <- c()
    for(j in gene_loadings ){
      #If this value is greater than 1/total_genes, the gene is selected because it has a greater contribution 
      #than the value of contribution if all the same genes contribute together.
      if(abs(j)/loadings_sum > 1/nGenes){
        selected <- c(selected, j)    
        has_positives<- has_positives + ifelse(j > 0, 1, 0)
        has_negatives<- has_negatives + ifelse(j < 0, 1, 0)
      }
    }
    
    ## Change the direction for the metagene
    ##If most or all of the genes have a positive loading then
    if(has_positives > has_negatives ){
      #leave metagene as it is
      ##If most or all of the genes have a negative loading then invert metagene
    }else if(has_negatives > has_positives){
      metagenes[i,] <-metagenes[i,] * -1 
      ##If same number of negative and positive loadings then resolve
    }else if(has_negatives > 0 && has_positives > 0){
      has_positives <- sum(selected[selected>0])
      has_negatives <- abs(sum(selected[selected<0]))
      if(has_negatives > has_positives){
        ##If negative loadings genes are bigger then invert metagene
        metagenes[i,] <-metagenes[i,] * -1 
      }
    }
  }
  return(metagenes)
}
metagenes <- adjust.direction(expression_GO)

# CLUSTERIZE ----------------------------------------------------------------------------------------------------
data <- metagenes

library(cluster)
library(amap) 
library(mclust) #new
library(factoextra) #new
dataScaled <- t(scale(t(data), center = T, scale = F)) #no do scaling with all subset
dist.res <- Dist(dataScaled, method = "pearson")

if(is.null(args$kclusters)) {

  ## cutoff default

  # Compute pairwise distance matrices

  k.max <- round(sqrt(length(row.names(dataScaled))/2)) + 1

  if(args$cluster=="kmeans"){
    # Check best cluster using WSS
    p = fviz_nbclust(x = dataScaled, FUNcluster = stats::kmeans, method = c("wss"), 
                     diss = dist.res,
                     k.max = k.max, verbose = TRUE) +
      labs(title = "Optimal number of clusters")
    args$kclusters <- getBestIndexBy2SlopeLesser1stQuartilSlope(p)
    p <- p + geom_vline(xintercept = args$kclusters, linetype = 2)
    ggsave(plot = p, filename=paste0(args$output_prefix,"_elbow.png"), width = 15, height = 6, dpi = 200, units = "cm")
    
  }else{
    # Compute clusters using Mclust (ML)
    fit <- Mclust(dist.res, G = 1:k.max)
    args$kclusters <- fit$G
  }
  
} else {
  args$kclusters = as.integer(args$kclusters)
}

if(args$cluster=="kmeans"){
  clusters <- stats::kmeans(dist.res, centers = args$kclusters, iter.max = 500)
}else{
  clusters <- fit <- Mclust(dist.res, G = args$kclusters)
}




# GENERATE THE METAGENES IMAGES-----------------------------------------------------------------------------------
cat("STEP 5. Generate output files...\n")
prev_pathway_id <- ""

# function to find medoid in cluster i
clust.centroid = function(method, data, clusters, i) {
  if(method == 'kmeans'){
    ind = (which(clusters$cluster == i))
    colMeans(data[ind,])
  }else{ #mclust
    ind = (which(clusters$classification == i))
    colMeans(data[ind,])
  }
}

minMax <- range(data)
# GENERATE THE METAGENES IMAGES-----------------------------------------------------------------------------------
for (i in 1:args$kclusters){
  #GET THE PATHWAY IDS FOR CURRENT CLUSTER
  if(args$cluster=="kmeans"){
    pathway_ids <- names(which(clusters$cluster==i))
  }else{
    pathway_ids <- names(which(clusters$classification==i))
  }
  #GET THE VALUES FOR THESE PATHWAYS
  values <- as.matrix(dataScaled[pathway_ids,])
  minMax <- range(values)
  #CREATE THE PNG
  png(paste(args$output_prefix, "_cluster_", i, args$database, ".png", sep=""), height = 150, width = 150)
  par(mai = rep(0, 4), mar = rep(0.8, 4))
  
  if(length(row.names(values)) > 1){
    #Plot first cluster
    plot(as.matrix(values[1,]), type="l", col="gray88", main=paste(length(pathway_ids), "metagenes"), axes=F, xlab=NULL, ylim = minMax)
    #Plot remaining clusters (if any)
    for (n in 2:length(row.names(values)) ) {
      lines(as.matrix(values[n,]), type="l", col="gray88")
    }
    #Plot centroid if multiple lines
    lines(clust.centroid(args$cluster, dataScaled, clusters, i), type="l", col="red", lwd=2)
  }else{
    plot(as.matrix(values), type="l", col="red", main=paste(length(pathway_ids), "metagenes"), axes=F, xlab=NULL, ylim = minMax)
  }
  abline(h =0)
  box()
  
  dev.off()
}

#Add cluster info to table
metagenes <- as.data.frame(data)
for (i in 1:args$kclusters){
  #GET THE PATHWAY IDS FOR CURRENT CLUSTER
  if(args$cluster=="kmeans"){
    pathway_ids <- names(which(clusters$cluster==i))
  }else{
    pathway_ids <- names(which(clusters$classification==i))
  }
  metagenes[pathway_ids, "cluster"] <- i
}
#Update the name for the rows
rownames(metagenes) <- gsub("_", "\t", gsub("path:", "", rownames(metagenes)))
#rownames(metagenes) <- gsub("_*", "", gsub("path:", "", rownames(metagenes)))

#Save table to file
if (args$database == "") {
  output_file = paste(args$output_prefix, "metagenes.tab", sep="_")
} else {
  output_file = paste(args$output_prefix, "metagenes", paste0(substring(args$database, 2), ".tab"), sep="_")
}
write.table(metagenes[, c(ncol(metagenes), 1:(ncol(metagenes) - 1))], file=output_file, quote = FALSE, sep="\t", col.names = FALSE)
