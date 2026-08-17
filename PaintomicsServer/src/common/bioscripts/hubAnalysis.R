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
# dir() was re-evaluated three times per iteration (once for the loop bound,
# once for the grepl, once for the load path): 1,865 iterations x a readdir of
# 1,869 entries each time. On mmu that directory listing, not the 60 MB of
# .RData, was where this loop spent its time -- measured 4.9 s per 1,865 dir()
# calls on the same directory, ~9.7 s of the 10.8 s loop. The listing cannot
# change while the loop runs, so read it once.
files <- dir(args$inputDir)
for (i in 1: length(files)) {
  if(grepl(".RData", files[i], fixed=TRUE)){
    load(paste0(args$inputDir,files[i]))
    theTablesFlat <- flatten(theTables)
    # The per-call unwrapping the scorer below used to do
    # (`if (class(neighbours) == "list") neighbours <- neighbours[[1]]`), hoisted
    # here so the block encoding downstream always sees plain id vectors. On
    # installed hubData flatten() already returns them, so this is a no-op.
    #
    # It unwraps to the bottom rather than one level, because the block encoding
    # measures each radius with length() while unlist() flattens recursively: a
    # radius still wrapped after one unwrap would advance the block's read
    # cursor by 1 instead of by its id count and so corrupt the counts of every
    # LATER metabolite in the same block. The old per-call form could only
    # produce garbage for the one (metabolite, radius) pair it was handed; that
    # containment has to survive here, and unwrapping fully is what gives it.
    theTablesFlat <- lapply(theTablesFlat, function(v) {
      while (is.list(v)) v <- v[[1]]
      v
    })
    all_met_neigh[[i]] <- theTablesFlat
    names(all_met_neigh)[i] <- names(theTables)[1]
    names(all_met_neigh[[i]]) <- paste(names(theTables)[1], 1:4, sep = "_")
  }
}

PercDEinMetaboliteNeighbours <- function (all_met_neigh, genes, DEG, blockIds = 200000L) {
  # This function calculates the number of DEG among a given metabolite gene
  # neighbours -- for every metabolite and every neighbourhood radius at once.
  #
  # It used to be called once per (metabolite, radius) pair, ~7,500 times, and
  # each call ran intersect(neighbours, genes) then intersect(., DEG).
  # intersect() is match()-based and match() builds a fresh hash table of its
  # `table` argument on every call, so the whole measured-genes vector (6.5k on
  # this mmu dataset, up to 40k on a large upload) and the DEG vector were
  # re-hashed for each pair: tens to hundreds of millions of hash insertions to
  # produce five counts per pair.
  #
  # Here each block of metabolites is hashed once: every id in the block is
  # mapped to an index into the block's own id universe (one match() for the
  # block), and that universe's membership of genes / DEG is one match() each.
  # Everything per radius is then integer work -- unique() over codes and
  # logical indexing -- i.e. O(neighbours), with no table rebuild. Blocks are
  # cut by id count rather than metabolite count so the temporary integer
  # vectors stay bounded whatever the size of an organism's hubData (mmu:
  # 4.0M ids across 1,865 metabolites; hsa is an order of magnitude larger).
  #
  # Every count is the one the set operations produced, by construction:
  #   InDataset_neighbours = |intersect(neighbours, genes)|. intersect() returns
  #     unique matches, and only its length is ever read, so deduplicating
  #     before the filter (unique() of the codes) gives the same number.
  #   DEN   = |intersect(measured, DEG)|, measured being already unique.
  #   noDEN = |setdiff(measured, DEneighbours)| = |measured| - DEN, because
  #     DEneighbours is a subset of an already-unique measured.
  #   KEEG_neighbours = length(neighbours) WITH duplicates -- the one count that
  #     is not deduplicated, and it stays that way.
  #   percDEN = round(DEN/(noDEN+DEN), 4) = round(DEN/|measured|, 4), which is
  #     NaN for a metabolite with no measured neighbour exactly as 0/0 was.
  statNames <- c("KEEG_neighbours", "InDataset_neighbours", "DEN", "noDEN", "percDEN")
  nMet <- length(all_met_neigh)
  result <- vector("list", nMet)
  first <- 1L
  while (first <= nMet) {
    last <- first; held <- 0L
    repeat {
      held <- held + sum(lengths(all_met_neigh[[last]]))
      if (last >= nMet || held >= blockIds) break
      last <- last + 1L
    }
    block <- all_met_neigh[first:last]
    blockIdVector <- unlist(block, use.names = FALSE)
    universe <- unique(blockIdVector)
    inGenes <- match(universe, genes, 0L) > 0L
    inDEG <- match(universe, DEG, 0L) > 0L
    codes <- match(blockIdVector, universe)
    at <- 0L                                  # read cursor into codes
    for (b in seq_along(block)) {
      radii <- block[[b]]
      counts <- vapply(seq_along(radii), function(r) {
        neigh <- length(radii[[r]])
        code <- unique(codes[at + seq_len(neigh)])
        at <<- at + neigh
        measured <- code[inGenes[code]]
        DEN <- sum(inDEG[measured])
        measured_neigh <- length(measured)
        noDEN <- measured_neigh - DEN
        c(neigh, measured_neigh, DEN, noDEN, round(DEN/(noDEN+DEN), 4))
      }, numeric(5))
      dimnames(counts) <- list(statNames, names(radii))
      result[[first + b - 1L]] <- as.data.frame(counts)
    }
    first <- last + 1L
  }
  names(result) <- names(all_met_neigh)
  result
}
prepare_KEGG <- function (kegg_interactions, features, significant_features) {
  ################################################
  # Step 1: Removing interactions with  Map
  #dim(kegg_interactions) # 122875 x 9
  print('Step 1: Removing interactions with  Map...')
  hknomap1<-kegg_interactions[kegg_interactions$entry_type_1 != "map",]
  keggNoMap<-hknomap1[hknomap1$entry_type_2 != "map",]
  table(keggNoMap$entry_type_1)
  table(keggNoMap$entry_type_2)
  dim(keggNoMap) # 120667 x 9... 122875 - 120667 = 2208 map links eliminated
  
  ################################################
  # Determining the number of differentially expressed metabolites
  print('Step 2: Determining the number of differentially expressed metabolites...')
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
  genes <- intersect(as.character(features) ,as.character(typesG$name))
  
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

globalSigPer <- length(mydata$DEG)/length(mydata$genes)

DEm <- mydata$DEM
if (length(DEm) == 0 && length(mydata$metabolites)) {
  print("No DEm input. Consider all input metabolites are relevant.")
  DEm = mydata$metabolites 
}

print('STEP 3: calculating the number of DEG among a given metabolite gene neighbours...')
# One call for every metabolite x radius (the per-pair purrr::map this replaces
# is what re-hashed genes/DEG 7,500 times); the returned list is the same list
# of per-metabolite data.frames, one column per radius, five named rows.
all.perc <- PercDEinMetaboliteNeighbours(all_met_neigh, genes = mydata["genes"][[1]],
                                         DEG = mydata["DEG"][[1]])

extract.per <- function (x, step) {
  value <- x[5,step]
  value
}

extract.den <- function (x, step) {
  value <- x[3,step]
  value
}
extract.noDen <- function (x, step) {
  value <- x[4,step]
  value
}

step1per <- purrr::map_dbl( all.perc, extract.per, step = 1)
step2per <- purrr::map_dbl( all.perc, extract.per, step = 2)
step3per <- purrr::map_dbl( all.perc, extract.per, step = 3)
step4per <- purrr::map_dbl( all.perc, extract.per, step = 4)

step1den <- purrr::map_dbl( all.perc, extract.den, step = 1)
step2den <- purrr::map_dbl( all.perc, extract.den, step = 2)
step3den <- purrr::map_dbl( all.perc, extract.den, step = 3)
step4den <- purrr::map_dbl( all.perc, extract.den, step = 4)

step1noDen <- purrr::map_dbl( all.perc, extract.noDen, step = 1) + step1den
step2noDen <- purrr::map_dbl( all.perc, extract.noDen, step = 2) + step2den
step3noDen <- purrr::map_dbl( all.perc, extract.noDen, step = 3) + step3den
step4noDen <- purrr::map_dbl( all.perc, extract.noDen, step = 4) + step4den

step1 = data.frame('per'=step1per, 'den'=step1den, 'noDen'= step1noDen)
step2 = data.frame('per'=step2per, 'den'=step2den, 'noDen'= step2noDen)
# 'den' was step2den here while the other three rows use their own step's count, so
# every step-3 binom.test took step 2's successes against step 3's total. Copy-paste
# slip from ff8fea3d; the step3noDen line just above always used step3den correctly.
step3 = data.frame('per'=step3per, 'den'=step3den, 'noDen'= step3noDen)
step4 = data.frame('per'=step4per, 'den'=step4den, 'noDen'= step4noDen)

processData = function(stepNumber) {
  stepNumber <- as.matrix(stepNumber)
  stepNumber[is.na(stepNumber)] = 0
  stepNumber_density = as.matrix(stepNumber[,1] )
  stepNumber_DEm <-as.data.frame(stepNumber_density[rownames(stepNumber_density) %in% DEm,],
                                 stringsAsFactors = FALSE)
  stepNumber_except_DEm <- as.data.frame(stepNumber_density[!rownames(stepNumber_density) %in% DEm,],
                                         stringsAsFactors = FALSE)
  colnames(stepNumber_DEm) = colnames(stepNumber_except_DEm) = "Density"
  if (nrow(stepNumber_DEm) == 0) {
    emptyResult <- data.frame(Density = numeric(0),
                              Name = character(0),
                              Percentile = numeric(0),
                              pvalue = numeric(0),
                              pvalue_adjust = numeric(0),
                              stringsAsFactors = FALSE)
    return(emptyResult)
  }
  #Calculate percentile for each DEm
  # The step function is built from the background densities, which do not
  # change across DEm rows, so build it once and evaluate it on the whole
  # column instead of rebuilding it per row inside apply().
  backgroundEcdf <- ecdf(stepNumber_except_DEm$Density)
  percentile <- as.vector(backgroundEcdf(stepNumber_DEm$Density))
  stepNumber_DEm$Name = rownames(stepNumber_DEm)
  stepNumber_DEm$Percentile <- percentile
  #Calculate p-value for each DEm
  stepNumber_DEm$pvalue <- NA
  stepNumber_DEm$pvalue_adjust <- NA
  # Loop-invariant: both columns were re-subset by the full DEm row-name vector
  # on every iteration (an O(nDEm x nMetabolites) row-name match each time) only
  # to read element i out of the result. Same values, resolved once.
  demRows <- rownames(stepNumber_DEm)
  demDEN <- as.numeric(stepNumber[demRows, 2])
  demTotal <- as.numeric(stepNumber[demRows, 3])
  for (i in 1:nrow(stepNumber_DEm)) {
    if (demTotal[i] == 0) {
      pvalue = 1
    } else {
      pvalue = binom.test(demDEN[i],
                          demTotal[i],
                          p = globalSigPer,
                          alternative = 'greater')$p.value
    }

    stepNumber_DEm$pvalue[i] <- pvalue

  }
  # p.adjust must see the whole vector. Called per-row on a scalar (as it was here),
  # R's BH branch collapses to min(1, p*n) -- i.e. Bonferroni, reported to the client
  # under the "BH" name. Adjusting after the loop makes it the BH it always claimed.
  # NOTE: this adjusts within a step. The four steps are nested by construction
  # (step k contains step k-1) and are still adjusted separately, which is the
  # pre-existing behaviour and a modelling decision, not a bug -- left unchanged.
  stepNumber_DEm$pvalue_adjust <- p.adjust(stepNumber_DEm$pvalue, method = "BH")
  return(stepNumber_DEm)
}
print('STEP 4: Calculating percentile/p-value for each DEm...')
step1_DEm <- processData(step1)
step1_DEm$Step <- rep(1, nrow(step1_DEm))

step2_DEm <- processData(step2)
step2_DEm$Step <- rep(2, nrow(step2_DEm))

step3_DEm <- processData(step3)
step3_DEm$Step <- rep(3, nrow(step3_DEm))

step4_DEm <- processData(step4)
step4_DEm$Step <- rep(4, nrow(step4_DEm))

final_result <- rbind(step1_DEm, step2_DEm, step3_DEm, step4_DEm)

final_result$DEN <- rep(NA_real_, nrow(final_result))
final_result$noDEN <- rep(NA_real_, nrow(final_result))
#extract DE/noDE neighbors
if (nrow(final_result) > 0){
  # Resolve every output row's metabolite to its position in all.perc in one
  # match() instead of a by-name list lookup plus an as.data.frame() rebuild per
  # row. The names come from all.perc itself (via the step data.frames' row
  # names), so every one of them resolves.
  percIndex <- match(final_result$Name, names(all.perc))
  for (i in seq_len(nrow(final_result))){
    neighbors <- all.perc[[percIndex[i]]][3:4,final_result$Step[i]]
    DEN = neighbors[1]
    noDEN = neighbors[2]
    final_result$DEN[i] <- DEN
    final_result$noDEN[i] <- noDEN
  }
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

