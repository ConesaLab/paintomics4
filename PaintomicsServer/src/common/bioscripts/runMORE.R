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
omic_names  <- trimws(unlist(strsplit(opt$omic_names, ",")))
data_paths  <- unlist(strsplit(opt$data_files, ","))
assoc_paths <- unlist(strsplit(opt$assoc_files, ","))

regulatoryData <- list()
associations   <- list()

for (i in seq_along(omic_names)) {
  name <- gsub(" ", "_", omic_names[i])  # Match Python's safe_name sanitisation

  # Load Data
  reg_mat <- read_matrix(data_paths[i])
  if (is.null(reg_mat)) stop(paste("Data file for", name, "not found."))
  regulatoryData[[name]] <- reg_mat
  
  cat(paste("MORE: Loaded regulatory omic", name, "with", nrow(reg_mat), "features.\n"))
  cat(paste("MORE: First few regulator IDs:", paste(head(rownames(reg_mat), 5), collapse=", "), "\n"))
  
    # Load Association (Optional)
    a_path <- assoc_paths[i]
    if (a_path != "NULL") {
      assoc_df <- read.table(a_path, header=TRUE, sep="\t", stringsAsFactors=FALSE, check.names=FALSE)
      cat(paste("MORE: Loaded association file for", name, "with", nrow(assoc_df), "rows.\n"))
      cat(paste("MORE: First row of association file:", paste(assoc_df[1,], collapse=" | "), "\n"))
      
      # MORE expects [Target, Regulator]. Paintomics often provides [Regulator, Target] or [Target, Regulator].
      # We check regulator matches to ensure the regulator is in the SECOND column.
      col1_match_reg <- sum(assoc_df[,1] %in% rownames(reg_mat))
      col2_match_reg <- sum(assoc_df[,2] %in% rownames(reg_mat))
      
      cat(paste("MORE: Col 1 matches with reg IDs:", col1_match_reg, "\n"))
      cat(paste("MORE: Col 2 matches with reg IDs:", col2_match_reg, "\n"))
      
      if (col1_match_reg > col2_match_reg) {
        cat(paste("MORE: Detected Regulator in Column 1. Swapping to [Target, Regulator]...\n"))
        assoc_df <- assoc_df[, c(2, 1)]
      }
      
      colnames(assoc_df) <- c("target", "regulator")
      
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
# Find common samples across Target, Condition, and ALL Regulatory Omics
common_samples <- intersect(colnames(targetData), rownames(condition))
for (mat in regulatoryData) {
  common_samples <- intersect(common_samples, colnames(mat))
}

cat(paste("MORE: Found", length(common_samples), "common samples among all datasets.\n"))
if (length(common_samples) == 0) stop("No common samples found across input files.")

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

result_more <- more(
  targetData     = targetData,
  regulatoryData = regulatoryData,
  associations   = associations_to_pass,
  condition      = condition,
  method         = opt$method,
  varSel         = varSel_val,
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

for (name in omic_names) {
  # Significant pairs for this omic
  omic_df <- rpc_df[rpc_df$omic == name, , drop=FALSE]
  
  # Strip prefix added by MORE (e.g. "TF-" from "TF-ID")
  prefix <- paste0(name, "-")
  
  # A. Relevant Associations File (Yellow Stars)
  # In MORE, any row in the RPC result is significant
  rel_assoc_file <- file.path(opt$output_dir, paste0("MORE_relevant_assoc_", name, "_", opt$date_seed, ".tab"))
  
  if (nrow(omic_df) > 0) {
    # Strip prefix for relevant file too and JOIN with :::
    relevant_ids <- sapply(1:nrow(omic_df), function(idx) {
      g <- as.character(omic_df[idx, "targetF"])
      r_with_prefix <- as.character(omic_df[idx, "regulator"])
      
      if (startsWith(r_with_prefix, prefix)) {
        r <- substring(r_with_prefix, nchar(prefix) + 1)
      } else {
        r <- r_with_prefix
      }
      paste0(g, ":::", r)
    })
    write.table(unique(relevant_ids), rel_assoc_file, sep="\t", row.names=FALSE, col.names=FALSE, quote=FALSE)
  } else {
    file.create(rel_assoc_file) # Empty file
  }

  # A2. Relevant Regulators File (Red Stars)
  # List of unique regulators that appear in any significant model
  rel_reg_file <- file.path(opt$output_dir, paste0("MORE_relevant_reg_", name, "_", opt$date_seed, ".tab"))
  if (nrow(omic_df) > 0) {
    unique_regs_with_prefix <- unique(as.character(omic_df$regulator))
    unique_regs <- sapply(unique_regs_with_prefix, function(r_with_prefix) {
      if (startsWith(r_with_prefix, prefix)) {
        substring(r_with_prefix, nchar(prefix) + 1)
      } else {
        r_with_prefix
      }
    })
    write.table(unique(unique_regs), rel_reg_file, sep="\t", row.names=FALSE, col.names=FALSE, quote=FALSE)
  } else {
    file.create(rel_reg_file) # Empty file
  }
  
  # B. Values File (Evidence Plots)
  val_file <- file.path(opt$output_dir, paste0("MORE_output_", name, "_", opt$date_seed, ".tab"))
  out_lines <- c()
  
  reg_data <- regulatoryData[[name]]
  unique_pairs <- unique(omic_df[, c("targetF", "regulator")])
  
  # Strip prefix added by MORE (e.g. "TF-" from "TF-ID")
  prefix <- paste0(name, "-")
  
  if (nrow(unique_pairs) > 0) {
    for (j in 1:nrow(unique_pairs)) {
      g <- as.character(unique_pairs[j, "targetF"])
      r_with_prefix <- as.character(unique_pairs[j, "regulator"])
      
      # Strip prefix if it exists
      if (startsWith(r_with_prefix, prefix)) {
        r <- substring(r_with_prefix, nchar(prefix) + 1)
      } else {
        r <- r_with_prefix
      }
      
      if (r %in% rownames(reg_data)) {
        vals <- paste(as.character(reg_data[r, ]), collapse="\t")
        out_lines <- c(out_lines, paste0(g, ":::", r, "\t", vals))
      }
    }
  }
  
  header <- paste(colnames(reg_data), collapse="\t")
  writeLines(c(paste0("# ID\t", header), out_lines), val_file)
  
  cat(paste("MORE: Generated results for", name, "\n"))
}

cat("MORE: Analysis complete.\n")
