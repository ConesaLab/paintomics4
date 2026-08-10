##############################################################
# This functions performs PCA and selects scores for genes
# associated by belonging to a GO, given a selection of GOs
# It prodices a matrix X.sel with columns the number of
# conditions and rows the number of GO_genes
#
# Input data
# X: expression data matrix
# selection: GO selection object obtained by select.GO
# fac.sel = criterion to select components, con be:
# 	%accum = percentage of accumulated variability
#	single% = percentage of variability of that PC
#	abs.val = absolute value of the variabily of that PC
#	rel.abs = fold variability of tot.var/rank(X)
# var.cutoff = variability cut off value
#
# Ana Conesa aconesa@cipf.es 8 September 2007
############################################################

# pca4NA: row-mean imputation of NA entries before PCA. Called from PCA2GO.2
# whenever the per-GO gene submatrix contains any NA, which happens for omics
# with legitimate missing measurements (e.g. methylation CpG sites not assayed
# in every sample). PCA.GENES propagates NAs through mean()/eigen() and fails;
# imputing each NA with its row's mean across observed cells keeps the row's
# centre intact and lets PC1 still capture between-sample variance. Rows that
# are entirely NA are dropped — there's no signal to recover. The function was
# referenced in this script for years but never defined; pre-MORE omics never
# carried NAs, so the branch was effectively dead code.
pca4NA <- function(X) {
  X <- as.matrix(X)
  row_means <- rowMeans(X, na.rm = TRUE)
  keep <- !is.nan(row_means) & !is.na(row_means)
  X <- X[keep, , drop = FALSE]
  row_means <- row_means[keep]
  if (nrow(X) == 0) return(X)
  na_mask <- is.na(X)
  if (any(na_mask)) {
    X[na_mask] <- row_means[row(X)[na_mask]]
  }
  X
}


PCA2GO.2 <- function (X, annotation, var.cutoff = 2, fac.sel = "rel.abs")
{
fac.sel <- match.arg(fac.sel, c("%accum", "single%", "abs.val", "rel.abs"))
# initialize variables
X.sel <- NULL 
n.go <- NULL
total.genes <- NULL
variab <- vector (mode="numeric")
tot.variab <- vector (mode="numeric")
eigen.val <- NULL
# Sorted, not just unique: the raw order is whatever order the pathways happen
# to appear in gene2pathway.list, so a regenerated KEGG snapshot would silently
# permute the rows of X.sel. Every value would be identical and the clustering
# would still move, because both clusterers downstream break ties by row
# position. radix pins C-locale collation so the order does not depend on LANG.
go.sel <- sort(unique(annotation[,2]), method = "radix")
n.ge <- NULL
X.loadings <- vector(mode = "list", length = 0)
# PCAs for all GOs loop
   for (i in 1: length(go.sel)) {
	gene.sel <- annotation[annotation[,2] == go.sel[i],1]
        if (length(gene.sel) > 1) {
      total.genes <- unique(c(total.genes, gene.sel))
      gene.sel <- is.element(rownames(X), gene.sel)
      if (length(which(gene.sel)) > 1) {
         # drop = FALSE: a single-column X (one condition) would collapse this
         # subset to a plain vector, nrow() would return NULL, and the guard
         # below would then fail with "argument is of length zero" rather than
         # skipping. generateMetaGenes.R now routes single-condition input to
         # CENTROID2GO so PCA never sees one column, but the subset should not
         # depend on that being true.
         gene.sel <- X[gene.sel, , drop = FALSE]
         # Sort the member genes by name so this pathway's PCA does not depend
         # on the row order of X. eigen() of a permuted covariance matrix is the
         # same decomposition in exact arithmetic but not in floating point, and
         # the "single%" criterion below counts how many components clear a
         # threshold -- so those last bits decide how many metagenes this
         # pathway contributes, not merely their precision. The caller already
         # sorts its input; doing it here as well makes the estimator itself
         # order-invariant instead of only being so when called correctly.
         # Rows move as units, so each gene keeps its own values, and the
         # loadings handed back stay named, which is all adjust.direction reads.
         gene.sel <- gene.sel[order(rownames(gene.sel), method = "radix"), , drop = FALSE]
         if (any(is.na(gene.sel))) { gene.sel <- pca4NA(gene.sel)}
         # If row-mean imputation dropped every row (all genes for this GO were
         # entirely NA), skip the GO instead of feeding an empty matrix to
         # PCA.GENES, which would crash on eigen() of a 0-dim matrix.
         if (nrow(gene.sel) < 2) next
		pca.sel <- PCA.GENES(t(gene.sel))  # pca
		eigen <- pca.sel$eigen$values
		tot.var <- sum(eigen)
		eigen.val <- c(eigen.val, tot.var)
		rank <- length(which(eigen > 1e-16))
		level <- 1
		# num fac
      	if (fac.sel == "%accum") {
			fac <- max(length(which(pca.sel$var.exp[,2] <= var.cutoff / sqrt(level))),1)
		} else if (fac.sel == "single%"){
      		fac <- length(which(pca.sel$var.exp[,1] >= (var.cutoff / sqrt(level))))
		} else if (fac.sel == "rel.abs"){
			mean.expl.var <- tot.var/ nrow(gene.sel)
			fac <- length(which(eigen >= (mean.expl.var*var.cutoff / sqrt(level))))
		} else if (fac.sel == "abs.val"){
			abs.val.bycomp <- mean(apply(pca.sel$Xoff,2,var)) * nrow(gene.sel)
			fac <- length(which(eigen >= abs.val.bycomp * var.cutoff / sqrt(level)))
		}
		tot.variab <- c(tot.variab, pca.sel$var.exp[,1])
		#variab <- c(variab, pca.sel$var.exp[1:fac,1])
		if (fac > 0 ) { # num fac
		
            	variab <- c(variab, pca.sel$var.exp[1:fac,1])
            	n.ge <- c(n.ge, nrow(gene.sel))
      		n.go <- c(n.go, fac)
      		data.h <- as.matrix(pca.sel$scores[,1:fac])
                loads <-  as.matrix(pca.sel$loadings[, 1:fac])
		colnames(data.h) <- paste(go.sel[i], c(1:fac), sep="_")
      		X.sel <- cbind(X.sel,data.h) # attach to results matrix
                for (u in 1:fac)  { X.loadings[[length(X.loadings)+1]] <- loads[,u] }
               	}
            }
	}
   }
# Rearrange result
if (!is.null(X.sel)) {
    rownames(X.sel) <- colnames(X)
    names(X.loadings) <- colnames(X.sel)
    X.sel <- t(X.sel)
}
return(list("X.sel" = X.sel, "X.loadings" = X.loadings,"n.ge" = n.ge,"n.go" = n.go, "go.sel" = go.sel, "total.genes" = total.genes, "var.cutoff" = var.cutoff, "variab" = variab, "tot.variab" = tot.variab, "eigen.val" = eigen.val))
}


##############################################################
# CENTROID2GO: the metagene estimator for a single condition.
#
# PCA2GO.2 summarises a pathway by the first principal component of its member
# genes ACROSS CONDITIONS. That estimator needs at least two observations:
# PCA.GENES centres t(gene.sel) over conditions, so with one condition every
# centred value is exactly 0 and the covariance PC1 maximises is undefined.
# This is not a numerical edge case to be guarded away -- "the direction of
# greatest variation across conditions" has no referent when there is one
# condition.
#
# What survives is the definition one level up: a metagene is a representative
# summary of a pathway's member genes, one value per condition, and PC1 is one
# estimator of it. With a single condition every linear summary of the members
# reduces to a weighted mean, so the choice collapses to a location statistic.
# The median is used rather than the mean because a pathway's members are a
# mixture of responders and non-responders and the mean is dragged by the tail.
# Measured on the bundled single-condition example (335 pathways, 8 of them
# carrying a planted signal): the median centroid ranks those 8 as 1-8, the
# mean ranks them 1,2,3,4,5,7,16,18.
#
# The function is written for any number of conditions -- it is a genuine
# generalisation, not a special case -- but generateMetaGenes.R only selects it
# when PCA is unavailable, because with >= 2 conditions PC1 carries shape
# information a per-condition median throws away.
#
# Returns exactly the shape PCA2GO.2 returns, so every downstream consumer is
# untouched. One metagene per pathway (there is no second component to select).
# Loadings are equal and positive: a median is already in the data's own units
# and direction, so there is no sign ambiguity for adjust.direction to repair.
##############################################################
CENTROID2GO <- function (X, annotation, var.cutoff = 2, fac.sel = "rel.abs")
{
  X <- as.matrix(X)
  # Sorted for the same reason as in PCA2GO.2: the metagene row order must be a
  # function of which pathways exist, not of how the annotation file is written.
  go.sel <- sort(unique(annotation[, 2]), method = "radix")
  X.sel <- NULL
  X.loadings <- vector(mode = "list", length = 0)
  n.ge <- NULL
  n.go <- NULL
  total.genes <- NULL
  metagene.names <- character(0)

  for (i in 1:length(go.sel)) {
    gene.sel <- annotation[annotation[, 2] == go.sel[i], 1]
    if (length(gene.sel) > 1) {
      total.genes <- unique(c(total.genes, gene.sel))
      member <- is.element(rownames(X), gene.sel)
      # Same floor as PCA2GO.2: a single measured gene is not a pathway
      # summary, it is that gene.
      if (length(which(member)) > 1) {
        values <- X[member, , drop = FALSE]
        # The median itself is order-invariant, so this is not load-bearing for
        # the centroid -- but the loading names returned below follow the row
        # order, and keeping both estimators canonical means "does the answer
        # depend on input order" has one answer here rather than two.
        values <- values[order(rownames(values), method = "radix"), , drop = FALSE]
        if (any(is.na(values))) values <- pca4NA(values)
        if (nrow(values) < 2) next
        centroid <- apply(values, 2, median, na.rm = TRUE)
        if (!all(is.finite(centroid))) next
        X.sel <- cbind(X.sel, centroid)
        metagene.names <- c(metagene.names, paste(go.sel[i], 1, sep = "_"))
        X.loadings[[length(X.loadings) + 1]] <- setNames(rep(1, nrow(values)),
                                                         rownames(values))
        n.ge <- c(n.ge, nrow(values))
        n.go <- c(n.go, 1)
      }
    }
  }
  if (!is.null(X.sel)) {
    colnames(X.sel) <- metagene.names
    rownames(X.sel) <- colnames(X)
    names(X.loadings) <- colnames(X.sel)
    X.sel <- t(X.sel)
  }
  return(list("X.sel" = X.sel, "X.loadings" = X.loadings, "n.ge" = n.ge,
              "n.go" = n.go, "go.sel" = go.sel, "total.genes" = total.genes,
              "var.cutoff" = var.cutoff, "variab" = NULL, "tot.variab" = NULL,
              "eigen.val" = NULL))
}

