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
  if (is.null(c)) { return(1) }
  index = which(p$data$y==min(p$data$y[c])) #de los elegidos, el de menor suma de cuadrado
  if (length(index) == 0) { return(1) }
  return(index[1])
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

#args <- data.frame(specie="ath",
#                   input_file="Gene expression_matched.txt",
#                   output_prefix="res",
#                   data_dir="/home/tian/Downloads/",
#                   kegg_dir='/home/tian/database/KEGG_DATA/',
#                   sources_dir='/home/tian/paintomics/paintomics4/PaintomicsServer/src/common/bioscripts',
#                   stringsAsFactors = F,
#                  cluster="kmeans")

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
# Column layout, written by Job.py -- both the gene based writer and the
# compound based one use the same shape:
#
#   1 inputName | 2 featureName | 3 featureID | 4 matchingDB | 5..(4+n) values | last relevance flag
#
# Example (n = 6 conditions, so 11 columns):
# ENSMUSG00000000001	Gnai3	14679	KEGG	0.01523	0.01042	0.04686	0.01663	0.04748	0.04169	0
#                                                                                                 ^ relevance flag
input_data <- read.table(file=args$input_file, header=FALSE, sep="\t", quote="")
# Remove duplicates
# TODO: now we are just ignoring the duplicates and taking the first match, maybe we should calculate mean?
# Deduplicate on the *lowercased* ID because that is what becomes row.names
# below; two IDs differing only in case would otherwise reach data.frame() as
# duplicate row names and abort the run.
input_data <- input_data[!duplicated(tolower(input_data$V3)),]

# Drop the trailing relevance flag. It is a 0/1 significance indicator, NOT a
# condition. Commit 6c7a7934 ("Add multi-condition support for PaintOmics4")
# appended it to the mapping files and this script was never updated, so it has
# been read as an extra condition ever since. A binary column sitting next to
# log-ratios of order 1e-2 dominates the per-pathway PCA: PC1 degenerates into
# "how many genes of this pathway are significant", every metagene comes out as
# a flat line with a spike at the last point, and the cluster thumbnails then
# differ only in the height of that spike -- which is why they all looked alike.
#
# Job.py always writes exactly one flag column (isRelevant() is called with no
# conditionIndex, so it collapses a per-condition list to a single boolean).
# test_metagenes_clustering.py pins that contract; if it ever changes, that test
# fails and points back here.
n_conditions <- ncol(input_data) - 5
if (n_conditions < 1) {
  stop("Input file has no condition columns (only ", ncol(input_data),
       " columns): ", args$input_file)
}
value_cols <- 5:(4 + n_conditions)
# Adapt input data to a data.frame object
feature_ids <- tolower(input_data[,3])
if (args$database == "") {
  feature_ids <- paste(args$specie, ":", feature_ids, sep="")
}
input_data <- data.frame(input_data[, value_cols, drop=FALSE], row.names=feature_ids)

#genes2pathway[which(genes2pathway[,1] %in% rownames(input_data)),]
# GET METAGENES  ------------------------------------------------------------------------------------------------
cat("STEP 4. Obtaining metagenes, ")
expression_GO <- get(PCA2GO.fun)(input_data, genes2pathway, var.cutoff = args$cutoff, fac.sel =  sel)
if (is.null(expression_GO$X.sel)) {
  cat("No metagenes found for this database and input data. Exiting gracefully.\n")
  q(save="no", status=0)
}


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

# Matrix the clustering actually runs on: each metagene centred across
# conditions (above) and then rescaled to unit length. For centred, unit-norm
# vectors ||x - y||^2 == 2 * (1 - pearson(x, y)), so plain Euclidean k-means on
# this matrix minimises exactly the pearson dissimilarity the script used to
# build with amap::Dist(). That is what a metagene profile wants: cluster on the
# *shape* of the response across conditions, independent of amplitude.
#
# This replaces `dist.res <- Dist(dataScaled, method = "pearson")` fed straight
# into stats::kmeans(). kmeans() opens with as.matrix(x), and as.matrix.dist
# expands a dist object into the full n x n distance matrix -- so kmeans was
# clustering the *rows of the distance matrix*, i.e. n points in n dimensions,
# under Euclidean distance. The pearson metric was never applied, the call was
# O(n^2) in time and memory, and the partitions came out badly unbalanced: on
# the example dataset k = 6 gave cluster sizes like 1, 5, 11, 36, 140, 166.
# Clusters that small routinely have no pathway left after Step 3's p-value
# filter, and the Step 3 panel only renders clusters that still own a visible
# pathway (PA_Step3Views.js builds CLUSTERS from surviving nodes), so asking for
# 6 clusters could display 4.
#
# Nothing needs the pairwise distance matrix any more, so it is no longer built:
# it was O(n^2) memory for a value that is now unused.
rowNorms <- sqrt(rowSums(dataScaled^2))
# A metagene that is flat across every condition has zero norm. Leave it at the
# origin rather than dividing by zero and seeding the matrix with NaN, which
# kmeans() rejects outright.
rowNorms[!is.finite(rowNorms) | rowNorms == 0] <- 1
dataForClustering <- dataScaled / rowNorms

# k-means seeds its centres from a random sample of rows. With no fixed seed the
# same job produced a different partition on every run, so the thumbnails and
# the cluster column of the .tab file disagreed between Step 2 and any later
# recomputation of the same omic.
set.seed(149)

if(is.null(args$kclusters) || args$kclusters == "dynamic") {
  if (nrow(dataScaled) < 3) {
    args$kclusters <- 1
  } else {
    ## cutoff default

    # Compute pairwise distance matrices

    k.max <- round(sqrt(length(row.names(dataScaled))/2)) + 1
    if (k.max < 2) k.max <- 2

    if(args$cluster=="kmeans"){
      # Check best cluster using WSS. Run the elbow over the same matrix the
      # final clustering uses -- it previously scanned dataScaled while the
      # clustering ran on the distance matrix, so the chosen k described a
      # different space than the partition it was chosen for.
      p = fviz_nbclust(x = dataForClustering, FUNcluster = stats::kmeans, method = c("wss"),
                       k.max = k.max, nstart = 25, iter.max = 500, verbose = TRUE) +
        labs(title = "Optimal number of clusters")
      args$kclusters <- getBestIndexBy2SlopeLesser1stQuartilSlope(p)
      p <- p + geom_vline(xintercept = args$kclusters, linetype = 2)
      ggsave(plot = p, filename=paste0(args$output_prefix,"_elbow.png"), width = 15, height = 6, dpi = 200, units = "cm")

    }else{
      # Compute clusters using Mclust (ML)
      fit <- Mclust(dataForClustering, G = 1:k.max)
      args$kclusters <- fit$G
    }
  }
} else {
  args$kclusters = as.integer(args$kclusters)
}

# Clamp k to what the clustering can actually express. stats::kmeans() rejects
# k >= nrow(x) ("number of cluster centres must lie between 1 and nrow(x)") and,
# with nstart > 1, k above the number of *distinct* rows ("more cluster centers
# than distinct data points"). Either one aborts the script and takes the whole
# omic-and-database pair down with it, which the caller surfaces as a failed
# job. A secondary database (a MapMan or Reactome subset matching a handful of
# pathways) reaches that easily as soon as a user drags the Step 3 slider up.
args$kclusters <- as.integer(args$kclusters)
if (is.na(args$kclusters) || args$kclusters < 1) args$kclusters <- 1
nMetagenes <- nrow(dataForClustering)
maxClusters <- min(nrow(unique(dataForClustering)), nMetagenes - 1L)
if (args$kclusters > maxClusters) {
  cat("Requested", args$kclusters, "clusters but only", nMetagenes,
      "metagenes are available; using", max(maxClusters, 1L), ". ")
  args$kclusters <- maxClusters
}
if (args$kclusters < 1) args$kclusters <- 1

if(nMetagenes < 2 || args$kclusters < 2){
  # Nothing to partition. Worth special-casing rather than leaving to kmeans():
  # it cannot express k = nrow(x) at all, so a database matching a single
  # pathway used to abort here even though the answer is trivially one cluster.
  # Both member names are supplied so clust.centroid() works for either method.
  args$kclusters <- 1
  singleton <- setNames(rep(1L, nMetagenes), rownames(dataForClustering))
  clusters <- list(cluster = singleton, classification = singleton)
}else if(args$cluster=="kmeans"){
  # nstart = 25: a single random start regularly settled in a poor local
  # optimum, so re-running the same omic could return visibly different clusters.
  clusters <- stats::kmeans(dataForClustering, centers = args$kclusters,
                            iter.max = 500, nstart = 25)
}else{
  clusters <- fit <- Mclust(dataForClustering, G = args$kclusters)
}




# GENERATE THE METAGENES IMAGES-----------------------------------------------------------------------------------
cat("STEP 5. Generate output files...\n")
prev_pathway_id <- ""

# function to find medoid in cluster i
#
# drop = FALSE is required. R drops a single-row matrix subset to a plain
# vector, and colMeans then aborts with
#   Error in colMeans(data[ind, ]) : 'x' must be an array of at least two
#   dimensions
# which halts the whole script. Clusters of exactly one gene are common, so
# this took out metagene generation for an entire omic-and-database pair at a
# time: on the example job it killed Gene expression for all of KEGG, and the
# pathway panel then reported "No data for this pathway" for every KEGG
# pathway even where the omic had matched features.
clust.centroid = function(method, data, clusters, i) {
  if(method == 'kmeans'){
    ind = (which(clusters$cluster == i))
    colMeans(data[ind, , drop = FALSE])
  }else{ #mclust
    ind = (which(clusters$classification == i))
    colMeans(data[ind, , drop = FALSE])
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
  # drop = FALSE again: for a cluster holding a single pathway the subset
  # collapses to a vector, and as.matrix() then turns it into an
  # nConditions x 1 column rather than a 1 x nConditions row. row.names() would
  # be the condition names, so the length > 1 test below took the multi-line
  # branch and plotted values[1,] -- one number -- instead of the single
  # pathway's profile.
  values <- as.matrix(dataScaled[pathway_ids, , drop = FALSE])
  #CREATE THE PNG
  png(paste(args$output_prefix, "_cluster_", i, args$database, ".png", sep=""), height = 150, width = 150)
  par(mai = rep(0, 4), mar = rep(0.8, 4))

  # An empty cluster makes range() return c(Inf, -Inf), and plot() then aborts
  # with "need finite 'ylim' values", which would kill the script here -- after
  # some thumbnails exist but before the .tab file is written. Emit an empty
  # framed panel instead: the client requests one image per cluster index and a
  # missing file shows up as a broken image.
  if(nrow(values) == 0){
    plot.new()
    title(main = "0 metagenes")
    box()
    dev.off()
    next
  }
  minMax <- range(values)

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
