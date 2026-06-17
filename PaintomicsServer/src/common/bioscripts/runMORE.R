#!/usr/bin/env Rscript

#***************************************************************
# MORE backend for Paintomics v4
# Performs regulatory analysis using regression models.
#***************************************************************

suppressPackageStartupMessages({
  library(optparse)
  library(MORE)
})

option_list <- list(
  make_option(c("-t", "--target_file"), type="character", help="Target omic data (Gene Expression)"),
  make_option(c("-c", "--condition_file"), type="character", help="Experimental design / Conditions file"),
  make_option(c("-o", "--omic_names"), type="character", help="Comma-separated names of regulatory omics"),
  make_option(c("-d", "--data_files"), type="character", help="Comma-separated paths to regulatory data files"),
  make_option(c("-a", "--assoc_files"), type="character", help="Comma-separated paths to association files (or 'NULL')"),
  make_option(c("--min_variation"), type="character", default="0", help="Comma-separated per-omic minVariation (numeric, or 'NA' for the auto threshold). One value per omic, in --omic_names order; a single value applies to all."),
  make_option(c("-m", "--method"), type="character", default="PLS1", help="Model method: PLS1 or MLR"),
  make_option(c("--alpha"), type="numeric", default=0.05, help="Significance threshold (alpha)"),
  make_option(c("--vip"), type="numeric", default=0.8, help="VIP threshold for PLS1"),
  make_option(c("--filter_r2"), type="numeric", default=0.0, help="R2 filter threshold"),
  make_option(c("--output_dir"), type="character", help="Directory to save results"),
  make_option(c("--date_seed"), type="character", default="results", help="Prefix/seed for filenames")
)

opt <- parse_args(OptionParser(option_list=option_list))

# --- Helper: Robust Matrix Loading ---
read_matrix <- function(path) {
  if (is.null(path) || path == "NULL" || !file.exists(path)) {
    if (!is.null(path) && path != "NULL") cat(paste("MORE ERROR: File does not exist at path:", path, "\n"))
    return(NULL)
  }
  
  # Try tab first, then comma
  data <- tryCatch({
    read.table(path, header=TRUE, sep="\t", check.names=FALSE, quote="\"", row.names=1)
  }, error = function(e) {
    read.table(path, header=TRUE, sep=",", check.names=FALSE, quote="\"", row.names=1)
  })
  
  # Ensure numeric
  return(as.matrix(data))
}

cat("MORE: Starting analysis...\n")
cat(paste("MORE: Target file path:", opt$target_file, "\n"))
cat(paste("MORE: Condition file path:", opt$condition_file, "\n"))

# 1. Load Primary Data
targetData <- read_matrix(opt$target_file)
condition  <- read_matrix(opt$condition_file)

if (is.null(targetData)) stop("Target file not found or invalid.")
if (is.null(condition)) stop("Condition file not found or invalid.")

cat(paste("MORE: Loaded target data with", nrow(targetData), "features.\n"))
cat(paste("MORE: First few target IDs:", paste(head(rownames(targetData), 5), collapse=", "), "\n"))

# 2. Load Regulatory Omics and Associations
omic_names  <- gsub(" ", "_", trimws(unlist(strsplit(opt$omic_names, ","))))
data_paths  <- unlist(strsplit(opt$data_files, ","))
assoc_paths <- unlist(strsplit(opt$assoc_files, ","))

regulatoryData <- list()
associations   <- list()

for (i in seq_along(omic_names)) {
  name <- omic_names[i]  # Already sanitised (spaces→underscores) when omic_names was parsed

  # Load Data
  reg_mat <- read_matrix(data_paths[i])
  if (is.null(reg_mat)) stop(paste("Data file for", name, "not found."))
  regulatoryData[[name]] <- reg_mat
  
  cat(paste("MORE: Loaded regulatory omic", name, "with", nrow(reg_mat), "features.\n"))
  cat(paste("MORE: First few regulator IDs:", paste(head(rownames(reg_mat), 5), collapse=", "), "\n"))
  
    # Load Association (Optional). MORE's documented contract:
    #   col 1 = target feature ID
    #   col 2 = regulator ID
    #   col 3 = interaction type / "area" (OPTIONAL — e.g. PROMOTER, 1st_EXON)
    # We auto-detect column order using only cols 1-2 so that a 3-col file
    # keeps its area column intact when a swap is needed. Files with >= 4
    # columns are rejected outright — silently truncating could hide a
    # malformed upload.
    a_path <- assoc_paths[i]
    if (a_path != "NULL") {
      assoc_df <- read.table(a_path, header=TRUE, sep="\t", stringsAsFactors=FALSE, check.names=FALSE)
      cat(paste("MORE: Loaded association file for", name, "with", nrow(assoc_df), "rows and", ncol(assoc_df), "columns.\n"))
      cat(paste("MORE: First row of association file:", paste(assoc_df[1,], collapse=" | "), "\n"))

      n_cols <- ncol(assoc_df)
      if (n_cols < 2) {
        stop(paste0("Association file for omic '", name, "' has only ", n_cols,
                    " column(s). MORE requires 2 columns (target, regulator) ",
                    "with an optional 3rd column for interaction type."))
      }
      if (n_cols > 3) {
        stop(paste0("Association file for omic '", name, "' has ", n_cols,
                    " columns. MORE accepts at most 3 columns: target, regulator, ",
                    "and an optional interaction-type/area column. Please check the file."))
      }

      # Orientation detection uses ONLY the first two columns.
      col1_match_reg <- sum(assoc_df[[1]] %in% rownames(reg_mat))
      col2_match_reg <- sum(assoc_df[[2]] %in% rownames(reg_mat))

      cat(paste("MORE: Col 1 matches with reg IDs:", col1_match_reg, "\n"))
      cat(paste("MORE: Col 2 matches with reg IDs:", col2_match_reg, "\n"))

      if (col1_match_reg > col2_match_reg) {
        cat("MORE: Detected Regulator in Column 1. Swapping to [Target, Regulator(, Area)]...\n")
        # Swap cols 1 <-> 2 and keep col 3 in place if it exists.
        if (n_cols == 3) {
          assoc_df <- assoc_df[, c(2, 1, 3), drop=FALSE]
        } else {
          assoc_df <- assoc_df[, c(2, 1), drop=FALSE]
        }
      }

      # Rename only the columns we own; preserve col 3's user-provided name
      # if present, or default it to "area" (the column name MORE itself uses
      # internally — see MORE:::GetAllReg).
      new_names <- colnames(assoc_df)
      new_names[1] <- "target"
      new_names[2] <- "regulator"
      if (n_cols == 3 && (is.na(new_names[3]) || new_names[3] == "")) {
        new_names[3] <- "area"
      }
      colnames(assoc_df) <- new_names

      if (n_cols == 3) {
        cat(paste("MORE: Detected optional interaction-type column '",
                  colnames(assoc_df)[3], "' — will be propagated to RegulationPerCondition.\n", sep=""))
      }

      # Check target overlap too
      target_overlap <- sum(assoc_df$target %in% rownames(targetData))
      cat(paste("MORE: Number of unique targets in association file:", length(unique(assoc_df$target)), "\n"))
      cat(paste("MORE: Number of targets in association file that exist in expression data:", target_overlap, "\n"))

      associations[[name]] <- assoc_df
    } else {
      cat(paste("MORE: No association file provided for", name, ". MORE will use all-to-all or internal mapping.\n"))
      associations[[name]] <- NULL
    }
}

# 3. Sample Alignment (CRITICAL)
# Strict name-based intersection. We deliberately do NOT fall back to positional
# alignment the way MORE's R API does: in a web context the user does not see
# console warnings, and silently aligning differently-named samples by column
# order is the canonical way to publish statistically meaningless results.
# Force the user to harmonise sample names upstream so the 1:1 mapping is
# explicit and verifiable.
common_samples <- intersect(colnames(targetData), rownames(condition))
for (mat in regulatoryData) {
  common_samples <- intersect(common_samples, colnames(mat))
}

cat(paste("MORE: Found", length(common_samples), "common samples among all datasets.\n"))
if (length(common_samples) == 0) {
  # Diagnostic error: surface the first few sample IDs from every input so the
  # user can spot the naming mismatch without re-opening their files.
  reg_lines <- sapply(names(regulatoryData), function(n) {
    paste0("  ", n, " samples: ",
           paste(head(colnames(regulatoryData[[n]]), 3), collapse=", "),
           if (ncol(regulatoryData[[n]]) > 3) ", ..." else "")
  })
  stop(paste0(
    "No common sample names across input files.\n",
    "  Target samples:  ",
    paste(head(colnames(targetData), 3), collapse=", "),
    if (ncol(targetData) > 3) ", ..." else "", "\n",
    "  Condition rows:  ",
    paste(head(rownames(condition), 3), collapse=", "),
    if (nrow(condition) > 3) ", ..." else "", "\n",
    paste(reg_lines, collapse="\n"), "\n",
    "Paintomics requires the same biological sample to carry the SAME column ",
    "name in the target expression file, the condition file, and every ",
    "regulatory omic file. Rename columns in R (e.g. ",
    "colnames(data.omics$miRNA) <- canonical_names) before saving so the ",
    "alignment is explicit. Positional alignment is intentionally not used."
  ))
}

# Re-order everything
targetData <- targetData[, common_samples, drop=FALSE]
condition  <- condition[common_samples, , drop=FALSE]
for (name in names(regulatoryData)) {
  regulatoryData[[name]] <- regulatoryData[[name]][, common_samples, drop=FALSE]
}

# 4. Run MORE
cat(paste("MORE: Running model (method =", opt$method, ")...\n"))

# If all associations are NULL, pass NULL instead of a list of NULLs
if (all(sapply(associations, is.null))) {
  associations_to_pass <- NULL
} else {
  associations_to_pass <- associations
}

# Configure parameters based on method
if (opt$method == "MLR") {
  varSel_val <- "EN"
} else {
  # For PLS1, use Jackknife by default as it is fast and robust
  varSel_val <- "Jack"
}

# Per-omic minVariation: low-variation filter applied independently to each
# regulatory omic. The servlet sends one token per omic (in omic_names order);
# "NA"/blank coerces to R's NA, which MORE reads as "auto" (10% of the maximum
# observed variability across conditions). A single token is recycled to all
# omics; an unexpected count falls back to 0 (MORE's documented default) rather
# than risking a silent mis-alignment between thresholds and omics.
parse_min_variation <- function(raw, omics) {
  tokens <- trimws(unlist(strsplit(raw, ",")))
  vals   <- suppressWarnings(as.numeric(tokens))  # "NA"/non-numeric -> NA (auto)
  if (length(vals) == 1L && length(omics) > 1L) {
    vals <- rep(vals, length(omics))
  }
  if (length(vals) != length(omics)) {
    warning(sprintf(
      "MORE: minVariation has %d value(s) for %d omic(s); using 0 for all.",
      length(vals), length(omics)))
    vals <- rep(0, length(omics))
  }
  names(vals) <- omics  # MORE matches the vector to regulatoryData by name
  vals
}
minVariation_vec <- parse_min_variation(opt$min_variation, names(regulatoryData))
cat(paste0("MORE: minVariation per omic -> ",
           paste(names(minVariation_vec),
                 ifelse(is.na(minVariation_vec), "NA (auto)", minVariation_vec),
                 sep = "=", collapse = ", "), "\n"))

result_more <- more(
  targetData     = targetData,
  regulatoryData = regulatoryData,
  associations   = associations_to_pass,
  condition      = condition,
  method         = opt$method,
  varSel         = varSel_val,
  minVariation   = minVariation_vec,
  alfa           = opt$alpha,
  vip            = opt$vip
)

# 5. Extract and Write Results
if (!dir.exists(opt$output_dir)) dir.create(opt$output_dir, recursive=TRUE)

# Compute coefficients
result_rpc <- RegulationPerCondition(result_more)

# Optional R2 Filter
if (opt$filter_r2 > 0) {
  result_rpc <- FilterRegulationPerCondition(result_more, result_rpc, filterR2 = opt$filter_r2)
}

rpc_df <- as.data.frame(result_rpc)

# Attach per-target R2 to rpc_df so the Step-3 Regulator-Target Network view
# can apply a post-hoc R2 slider client-side without re-querying the server.
# In MORE, GlobalSummary$GoodnessOfFit is a flat matrix with rownames = targetF
# and a method-dependent R2 column: MLR uses "Rsquared", PLS uses "RsquaredY".
# The R2/R-squared/Adj.R2 candidates are kept as defensive fallbacks in case a
# future MORE version renames the column.
gof <- result_more$GlobalSummary$GoodnessOfFit
.r2_candidates <- c("Rsquared", "RsquaredY", "R2", "R2.adj", "R-squared", "Adj.R2")

if (is.null(gof) || (is.list(gof) && length(gof) == 0)) {
  warning("MORE: GoodnessOfFit is empty or NULL; rpc table will lack R2")
} else {
  gof_df <- as.data.frame(gof)
  gof_df$targetF <- rownames(gof_df)
  r2_col <- intersect(.r2_candidates, colnames(gof_df))[1]
  if (!is.na(r2_col)) {
    colnames(gof_df)[colnames(gof_df) == r2_col] <- "R2"
    rpc_df <- merge(rpc_df, gof_df[, c("targetF", "R2")],
                    by = "targetF", all.x = TRUE, sort = FALSE)
    cat(paste0("MORE: attached R2 from GoodnessOfFit ('", r2_col, "')\n"))
  } else {
    # Surface the actual column names so future drift is debuggable without
    # source-diving into the MORE package.
    warning(sprintf(
      "MORE: no recognised R2 column in GoodnessOfFit (saw: %s); rpc table will lack R2",
      paste(colnames(gof_df), collapse = ", ")
    ))
  }
}

# Persist the full RegulationPerCondition table so PaintOmics' Step 3 panel
# can render it. Written here, BEFORE the per-omic loop below strips the
# `<omic>-` prefix in the yellow-star file — we apply the same prefix strip
# to the saved copy so what the user sees matches the regulator IDs in the
# original data file. The loop below still operates on the untouched rpc_df.
rpc_out_file <- file.path(opt$output_dir, paste0("MORE_rpc_", opt$date_seed, ".tab"))

if (nrow(rpc_df) > 0) {
  rpc_display <- rpc_df
  for (.omic in omic_names) {
    .prefix <- paste0(.omic, "-")
    .mask <- rpc_display$omic == .omic & startsWith(as.character(rpc_display$regulator), .prefix)
    if (any(.mask)) {
      rpc_display$regulator[.mask] <- substring(
        as.character(rpc_display$regulator[.mask]),
        nchar(.prefix) + 1
      )
    }
  }
  write.table(rpc_display, rpc_out_file,
              sep = "\t", row.names = FALSE, quote = FALSE, na = "")
  cat(paste0("MORE: wrote RegulationPerCondition table (",
             nrow(rpc_display), " rows, ", ncol(rpc_display), " cols) to ",
             basename(rpc_out_file), "\n"))
} else {
  # No relevant regulations at all — still create the file so Python can rely
  # on its existence; an absent file means MORE wasn't run at all.
  file.create(rpc_out_file)
  cat("MORE: RegulationPerCondition produced zero rows; wrote empty file.\n")
}

for (name in omic_names) {
  # Significance-filtered pairs (used ONLY for the yellow-star file).
  # The values file and the associations file both need every input pair, not just these.
  omic_df <- rpc_df[rpc_df$omic == name, , drop=FALSE]

  prefix   <- paste0(name, "-")
  reg_data <- regulatoryData[[name]]
  assoc_df <- associations[[name]]   # already normalised to columns: target, regulator (or NULL)

  # Build the full pair set: every (target, regulator) from the input association file
  # whose regulator is present in the regulator expression matrix. This matches the
  # miRNA2Genes contract — values + associations are an unfiltered snapshot of the
  # input data; significance only drives the yellow-star overlay.
  if (!is.null(assoc_df) && nrow(assoc_df) > 0) {
    keep_rows <- assoc_df$regulator %in% rownames(reg_data)
    full_pairs <- unique(assoc_df[keep_rows, c("target", "regulator"), drop=FALSE])
  } else {
    # No association file → fall back to MORE's significant pairs (best we can do).
    full_pairs <- unique(data.frame(
      target    = as.character(omic_df$targetF),
      regulator = sapply(as.character(omic_df$regulator), function(r) {
        if (startsWith(r, prefix)) substring(r, nchar(prefix) + 1) else r
      }),
      stringsAsFactors = FALSE
    ))
  }

  # A. Associations file (full set, 2-column TARGET\tREGULATOR for parseAssociationsFile).
  rel_assoc_file <- file.path(opt$output_dir, paste0("MORE_relevant_assoc_", name, "_", opt$date_seed, ".tab"))
  if (nrow(full_pairs) > 0) {
    write.table(full_pairs, rel_assoc_file, sep="\t", row.names=FALSE, col.names=FALSE, quote=FALSE)
  } else {
    file.create(rel_assoc_file)
  }

  # B. Relevant Pairs File — yellow-star source. Always significance-filtered (omic_df).
  # NOTE: We deliberately do NOT write MORE_relevant_reg_*.tab here. That file is the
  # red-star source and follows the miRNA2Genes contract: it only has content when the
  # user uploads a "Significant regulators" file. The MOREServlet creates it (empty or
  # expanded) after this script returns.
  rel_pairs_file <- file.path(opt$output_dir, paste0("MORE_relevant_pairs_", name, "_", opt$date_seed, ".tab"))
  if (nrow(omic_df) > 0) {
    pair_ids <- unique(paste0(
      as.character(omic_df$targetF),
      ":::",
      sapply(as.character(omic_df$regulator), function(r) {
        if (startsWith(r, prefix)) substring(r, nchar(prefix) + 1) else r
      })
    ))
    write.table(pair_ids, rel_pairs_file, sep="\t", row.names=FALSE, col.names=FALSE, quote=FALSE)
  } else {
    file.create(rel_pairs_file)
  }

  # C. Values file — one row per full pair, with the regulator's expression values.
  # Same set as the associations file so PA Step 1 sees every input pair (independent
  # of MORE's significance verdict). Header matches miRNA2Genes' "# Gene name\t..." style.
  val_file <- file.path(opt$output_dir, paste0("MORE_output_", name, "_", opt$date_seed, ".tab"))
  header <- paste(colnames(reg_data), collapse="\t")
  out_lines <- character(0)

  if (nrow(full_pairs) > 0) {
    for (j in seq_len(nrow(full_pairs))) {
      g <- as.character(full_pairs[j, "target"])
      r <- as.character(full_pairs[j, "regulator"])
      # Coerce R's NA → "NaN" so PA Step 1's validator (which calls float() on
      # every value) accepts the row. float("NA") raises; float("NaN") returns
      # nan. Real biological signal — e.g. CpG sites not measured in a sample
      # — would otherwise be silently rejected as "invalid values".
      v <- reg_data[r, ]
      v_char <- ifelse(is.na(v), "NaN", as.character(v))
      vals <- paste(v_char, collapse="\t")
      out_lines <- c(out_lines, paste0(g, ":::", r, "\t", vals))
    }
  }

  writeLines(c(paste0("# Gene name\t", header), out_lines), val_file)

  cat(paste("MORE:", name, "— wrote", length(out_lines), "pairs to values file (",
            nrow(omic_df), "significant for yellow stars)\n"))
}

cat("MORE: Analysis complete.\n")
