/*
 * What a correct conversion of each real-world test file must contain.
 *
 * Every entry was written after reading the file: which sheets hold
 * measurements, which columns are per-sample values rather than statistics or
 * annotation, which rows the authors flag, where the header really is. The
 * harness extracts each expected table with realworld_truth.py and compares
 * the agent's output against it -- identifiers as a set, values by identifier
 * with column matching by name or by vector, so renaming or reordering columns
 * is not an error but losing a gene, a sheet or a measurement family is.
 *
 * `tableSets` lists alternative complete answers; a file passes when every
 * non-optional table of ANY set is matched by one of the produced values
 * files. `anyOf` on a table lists equivalent extractions (e.g. duplicates
 * averaged or kept). `relevant` entries are lists the file's significance
 * column should become. `noValues` marks files that carry no measurement at
 * all -- for those, building a matrix out of statistics is the failure.
 *
 * The files live outside the repository (they are 300 MB of other people's
 * data); pass --dir to the harness.
 */

const CONTRASTS = ["SCI_vs_H_10d", "SCI_vs_H_30d", "bPAC_vs_SCI_10d",
                   "bPAC_vs_SCI_30d", "bPAC_vs_H_10d", "bPAC_vs_H_30d"];

// Regional sheets of the SCI workbooks: header, a "GENI VALIDATI (n)" banner,
// the validated genes, a "GENI FLAGGATI" banner, the flagged genes. The
// validated section is the answer; all rows minus banners is accepted too,
// because whether false positives belong is the authors' call, not ours.
function region(sheet) {
  return { name: sheet, anyOf: [
    { sheet, header: 0, section: 1, id: "Gene", values: CONTRASTS },
    { sheet, header: 0, drop_banners: true, id: "Gene", values: CONTRASTS },
  ] };
}

function sig(col, idCol, extra) {
  // A relevant list from a significance column, at any conventional threshold.
  return { name: col + " < 0.05", anyOf: [0.05, 0.01, 0.1].map(t =>
    Object.assign({ mode: "ids", id: idCol, filter: [{ col, lt: t }] }, extra || {})) };
}

// Order matters: a transcript-level question also mentions that gene_id
// "repeats", and the duplicates rule would otherwise answer it.
const ANSWERS_DEFAULT = [
  [/transcript/i, /transcript/i],
  [/flag|false positive|validat/i, /leave out|exclude|validated|without|only/i],
  [/duplicate|repeated|collapse|average/i, /average|mean/i],
];

const KEY = {
  "Caudal SCI_bPAC_FINAL.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [["Dorsal GM", "Medial GM", "Ventral GM", "MN spots"].map(region)],
  },
  "Rostral SCI_bPAC_FINAL.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [["MN spots", "Dorsal GM", "Medial GM", "Ventral GM"].map(region)],
  },

  "gene-expression/ENCODE_GM12878_RSEM_genes.tsv": {
    species: "hsa", omic: "Gene expression",
    tableSets: [[
      { name: "TPM", anyOf: [{ id: "gene_id", values: ["TPM"] }] },
      { name: "expected_count", anyOf: [{ id: "gene_id", values: ["expected_count"] }] },
      { name: "FPKM", optional: true, anyOf: [{ id: "gene_id", values: ["FPKM"] }] },
    ]],
  },
  "gene-expression/GSE103722_MERKO_DESeq2_results.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[
      { name: "counts", anyOf: ["ensembl_gene_id", "gene_symbol"].map(id => ({ sheet: "male", id,
        values: ["915_merko_male", "916_merko_male", "917_merko_male", "923_f_f_male", "924_f_f_male", "925_f_f_male"] })) },
      { name: "log2FoldChange", optional: true, anyOf: ["ensembl_gene_id", "gene_symbol"].map(id => ({ sheet: "male", id, values: ["log2FoldChange"] })) },
    ]],
    relevant: [{ name: "padj < 0.05", anyOf: [].concat.apply([], ["ensembl_gene_id","gene_symbol"].map(id => [0.05,0.01,0.1].map(t => ({ mode:"ids", id, sheet:"male", filter:[{col:"padj", lt:t}] })))) }],
  },
  "gene-expression/GSE173406_featureCounts_matrix.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[{ name: "counts", anyOf: [{ id: "Geneid", values: { all_except: ["Geneid"] } }] }]],
  },
  "gene-expression/GSE246713_raw-counts.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[{ name: "counts", anyOf: [{ id: "ID", values: { all_except: ["ID"] } }] }]],
  },
  "gene-expression/GSE267413_processed_data_TPM.xlsx": {
    species: "pfa", omic: "Gene expression",
    tableSets: [[
      { name: "IT4 var tpm", anyOf: [{ sheet: "IT4 var genes tpm", id: "var-names", values: { regex: "\\.bam$" } }] },
      { name: "IT4 var reads", anyOf: [{ sheet: "IT4 var genes reads", id: "var-names", values: { regex: "\\.bam$" } },
                                       { sheet: "IT4 var genes reads", id: "pf-names", values: { regex: "\\.bam$" } }] },
      { name: "3D7 var tpm", anyOf: [{ sheet: "3D7 var genes tpm", id: "var-names", values: { regex: "\\.bam$" } },
                                     { sheet: "3D7 var genes tpm", id: "pf-names", values: { regex: "\\.bam$" } }] },
      { name: "3D7 var reads", anyOf: [{ sheet: "3D7var genes reads", id: "var-names", values: { regex: "\\.bam$" } },
                                       { sheet: "3D7var genes reads", id: "pf-names", values: { regex: "\\.bam$" } }] },
      { name: "3D7 rif tpm", anyOf: [{ sheet: "3D7 rif genes tpm", id: "Geneid", values: { regex: "\\.bam$" } }] },
      { name: "3D7 rif reads", anyOf: [{ sheet: "3D7 rif genes reads", id: "Geneid", values: { regex: "\\.bam$" } }] },
      { name: "IT4 var tpm percent", optional: true, anyOf: [{ sheet: "IT4 var genes tpm (percent)", id: "var-names", values: { regex: "\\.bam$" } }] },
      { name: "deseq2 log2FC", optional: true, anyOf: [{ sheet: "deseq2 var19", header: 3, id: "Row_Names", values: ["log2FoldChange"] }] },
    ]],
    relevant: [Object.assign(sig("padj", "Row_Names", { sheet: "deseq2 var19", header: 3 }), { optional: true })],
  },
  "gene-expression/GSE268770_raw_counts.csv": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[{ name: "counts", anyOf: [{ sep: ",", id: "ID", values: { regex: "^iWAT" } }] }]],
  },
  "gene-expression/GSE271521_D8_DIAvsSHAM_DEG.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[
      { name: "counts", anyOf: [{ id: "gene_id", values: ["D8_D20", "D8_D21", "D8_D22", "SHAM_D12", "SHAM_D14", "SHAM_D15"] }] },
      { name: "fpkm", anyOf: [{ id: "gene_id", values: { regex: "_fpkm$" } }] },
      { name: "log2FoldChange", optional: true, anyOf: [{ id: "gene_id", values: ["log2FoldChange"] }] },
    ]],
    relevant: [sig("padj", "gene_id")],
  },
  "gene-expression/GSE271521_END_DIAvsSHAM_DEG.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[
      { name: "counts", anyOf: [{ id: "gene_id", values: ["END_D37", "END_D38", "END_D39", "SHAM_D12", "SHAM_D14", "SHAM_D15"] }] },
      { name: "fpkm", anyOf: [{ id: "gene_id", values: { regex: "_fpkm$" } }] },
      { name: "log2FoldChange", optional: true, anyOf: [{ id: "gene_id", values: ["log2FoldChange"] }] },
    ]],
    relevant: [sig("padj", "gene_id")],
  },
  "gene-expression/GSE272283_Mfap2_processed_data-reverse.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[{ name: "values", anyOf: [{ id: "EnsemblGene", values: { regex: "^(WT|KO)-R-" } }] }]],
  },
  "gene-expression/GSE272283_Mfap2_processed_data.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[{ name: "values", anyOf: [{ id: "#ID", values: { regex: "^Sample " } }] }]],
  },
  "gene-expression/GSE297370_edgeR_DEGs_all_Samples.csv": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[
      { name: "counts", anyOf: ["mean", "first", null].map(aggregate => ({ sep: ",", id: "ENSEMBL", aggregate, values: { regex: ", counts$" } })) },
      { name: "TPM", anyOf: ["mean", "first", null].map(aggregate => ({ sep: ",", id: "ENSEMBL", aggregate, values: { regex: ", TPM$" } })) },
      { name: "log2TPM", anyOf: ["mean", "first", null].map(aggregate => ({ sep: ",", id: "ENSEMBL", aggregate, values: { regex: ", log2TPM$" } })) },
      { name: "logFC", optional: true, anyOf: ["mean", "first", null].map(aggregate => ({ sep: ",", id: "ENSEMBL", aggregate, values: ["logFC"] })) },
    ]],
    relevant: [sig("FDR", "ENSEMBL", { sep: "," })],
  },
  "gene-expression/GSE304963_gene_allExp.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[
      { name: "samples", anyOf: [{ id: "gene_id", values: ["KO_1", "KO_2", "NC_1", "NC_2"] }] },
      { name: "logFC", optional: true, anyOf: [{ id: "gene_id", values: ["logFC"] }] },
    ]],
    relevant: [sig("pAdj", "gene_id")],
  },
  "gene-expression/GSE309108_Gene_counts_all_samples.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[{ name: "counts", anyOf: [{ id: "mouse_gene_id", values: { all_except: ["mouse_gene_id"] } }] }]],
  },
  "gene-expression/STATegra_rnaseq_raw_counts.csv": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[{ name: "counts", anyOf: [{ sep: ",", id: "column_1", values: { regex: "^Batch_" } }] }]],
  },
  "gene-expression/WTC11_PacBio_transcript_counts.tsv": {
    species: "hsa", omic: "Gene expression",
    tableSets: [
      [{ name: "transcript counts", anyOf: [{ id: "transcript_id", values: ["counts"] }] }],
      [{ name: "gene counts (summed)", anyOf: [{ id: "gene_id", values: ["counts"], aggregate: "sum" }] }],
    ],
  },
  "gene-expression/dGTEx_gene_tpm_v1_liver.gct": {
    species: "hsa", omic: "Gene expression",
    tableSets: [[{ name: "TPM", anyOf: [{ skiprows: 2, id: "Name", values: { regex: "^DGTEX" } }] }]],
  },
  "gene-expression/evodevo_Chicken_rpkm.txt": {
    species: "gga", omic: "Gene expression",
    tableSets: [[{ name: "rpkm", anyOf: [{ read_kwargs: { sep: " ", quotechar: "\"" }, id: "Names", id_transform: "unquote", values: { all_except: ["Names"] } }] }]],
  },
  "gene-expression/pig_human_cross_species_per_tissue_log2fc.csv": {
    species: "ssc", omic: "Gene expression",
    tableSets: [
      [{ name: "log2fc by tissue (wide)", anyOf: ["gene_symbol", "pig_gene_id", "human_gene_id"].map(id =>
          ({ sep: ",", id, pivot: { category: "tissue" }, values: ["log2fc_pig", "log2fc_human"] })) }],
      [{ name: "pig log2fc by tissue", anyOf: ["gene_symbol", "pig_gene_id", "human_gene_id"].map(id =>
          ({ sep: ",", id, pivot: { category: "tissue" }, values: ["log2fc_pig"] })) },
       { name: "human log2fc by tissue", anyOf: ["gene_symbol", "pig_gene_id", "human_gene_id"].map(id =>
          ({ sep: ",", id, pivot: { category: "tissue" }, values: ["log2fc_human"] })) }],
      [{ name: "Brain", anyOf: ["gene_symbol", "pig_gene_id", "human_gene_id"].map(id =>
          ({ sep: ",", id, filter: [{ col: "tissue", eq: "Brain" }], values: ["log2fc_pig", "log2fc_human"] })) },
       { name: "Liver", anyOf: ["gene_symbol", "pig_gene_id", "human_gene_id"].map(id =>
          ({ sep: ",", id, filter: [{ col: "tissue", eq: "Liver" }], values: ["log2fc_pig", "log2fc_human"] })) }],
    ],
  },
  "gene-expression/supp_40364_2025_845_Seurat_markers.xlsx": {
    species: "rno", omic: "Gene expression",
    tableSets: [[
      { name: "Table S4 avg_log2FC", anyOf: [{ sheet: "Table S4", id: "column_1", values: ["avg_log2FC"] }] },
      { name: "Table S2 markers by cell type", anyOf: [
          { sheet: "Table S2", id: "gene", pivot: { category: "cell_type" }, values: ["avg_log2FC"] }] },
    ].concat(["Pericyte", "Monocyte", "OPC", "Macrophage", "Neutrophil", "Fibroblast", "Microglia", "Schwann", "Endothelial", "Ependymal"].map(ct => ({
      name: "S2 " + ct, optional: true, anyOf: [{ sheet: "Table S2", id: "gene", filter: [{ col: "cell_type", eq: ct }], values: ["avg_log2FC"] }] }))),
    ["Pericyte", "Monocyte", "OPC", "Macrophage", "Neutrophil", "Fibroblast", "Microglia", "Schwann", "Endothelial", "Ependymal"].map(ct => ({
      name: "S2 " + ct, anyOf: [{ sheet: "Table S2", id: "gene", filter: [{ col: "cell_type", eq: ct }], values: ["avg_log2FC"] }] }))
      .concat([{ name: "Table S4 avg_log2FC", anyOf: [{ sheet: "Table S4", id: "column_1", values: ["avg_log2FC"] }] }]),
    ],
  },
  "gene-expression/supp_GENOME_2025_281698_Data_1.xlsx": {
    species: "mmu", omic: "Gene expression",
    noValues: true,
    relevant: [{ name: "experience-variable genes", anyOf: [
      { mode: "ids", header: 1, id: "Gene_ID" }, { mode: "ids", header: 1, id: "Gene_Name" }] }],
  },
  "gene-expression/supp_GENOME_2025_281698_Data_2.xlsx": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[{ name: "mean expression per cell type", anyOf: [
      { header: 2, id: "Transcript", values: { all_except: ["Transcript", "Gene", "Q val"] } }] }]],
  },
  "gene-expression/supp_GENOME_2025_281698_Data_3.xlsx": {
    species: "mmu", omic: "Gene expression",
    noValues: true,
    relevant: [{ name: "experience-variable isoforms", anyOf: [
      { mode: "ids", header: 1, id: "Transcript_ID" }, { mode: "ids", header: 1, id: "Gene_ID" },
      { mode: "ids", header: 1, id: "Transcript_Name" }, { mode: "ids", header: 1, id: "Gene_Name" }] }],
  },
  "gene-expression/tappAS_DEA_result_gene.tsv": {
    species: "mmu", omic: "Gene expression",
    tableSets: [[
      { name: "group means", anyOf: [{ id: "gene", values: ["1_mean", "2_mean"] }] },
      { name: "log2FC", optional: true, anyOf: [{ id: "gene", values: ["log2FC"] }] },
    ]],
  },

  "metabolomics/MTBLS6502_pos_hilic_maf.tsv": {
    species: "mmu", omic: "Metabolomics",
    tableSets: [[{ name: "abundances", anyOf: [].concat.apply([], [
      ["database_identifier", "metabolite_identification"], "metabolite_identification", "database_identifier"].map(id =>
      ["mean", "first", null].map(aggregate => ({ id, aggregate, values: { regex: "^(QC|GM-TC|M-TC)-" } })))) }]],
  },
  "metabolomics/MTBLS795_maf.tsv": {
    species: "mmu", omic: "Metabolomics",
    tableSets: [[{ name: "abundances", anyOf: [
      { header: 0, skip_after_header: 1, id: ["database_identifier", "metabolite_identification"], values: { regex: "^GILL-" } },
      { header: 0, skip_after_header: 1, id: "metabolite_identification", values: { regex: "^GILL-" } }] }]],
  },

  "proteomics/PXD026984_Perseus_volcano_export.xlsx": {
    species: "mmu", omic: "Proteomics",
    tableSets: [[
      { name: "normalised abundances", anyOf: [{ id: "Accession", values: { regex: "^Abundances \\(Normalized\\)" } }] },
      { name: "Difference (log2 FC)", optional: true, anyOf: [{ id: "Accession", values: ["Difference"] }] },
    ]],
    relevant: [{ name: "Significant", optional: true, anyOf: [{ mode: "ids", id: "Accession", filter: [{ col: "Significant", eq: "+" }] }] }],
  },
  "proteomics/PXD032766_limma_results.xlsx": {
    species: "mmu", omic: "Proteomics",
    answers: [[/duplicate|repeated|phospho|site/i, /keep them as they are|as they are|keep all/i]],
    tableSets: [[
      { name: "phosphosite log2 intensities", anyOf: [
        { sheet: "Raw_data", id: "Proteins", id_transform: "lead", values: { regex: "^(WT|ErbB2 KI|ERR⍺ KO|KI:KO)_\\d$" } },
        { sheet: "Raw_data", id: "Proteins", id_transform: "lead", aggregate: "mean", values: { regex: "^(WT|ErbB2 KI|ERR⍺ KO|KI:KO)_\\d$" } },
        { sheet: "Raw_data", id: "Proteins", id_transform: "lead", aggregate: "first", values: { regex: "^(WT|ErbB2 KI|ERR⍺ KO|KI:KO)_\\d$" } }] },
    ]],
  },
  "proteomics/PXD036948_PD_abundance_ratios.xlsx": {
    species: "hsa", omic: "Proteomics",
    tableSets: [[
      { name: "normalised abundances", anyOf: [{ sheet: "All Proteins", id: "Accession", values: { regex: "^Abundances \\(Normalized\\)" } }] },
      { name: "abundance ratio", optional: true, anyOf: [{ sheet: "All Proteins", id: "Accession", values: { regex: "^Abundance Ratio: " } }] },
    ]],
    relevant: [Object.assign(sig("Abundance Ratio Adj. P-Value: (QVD) / (DMSO)", "Accession", { sheet: "All Proteins" }), { optional: true })],
  },
  "proteomics/PXD060158_MaxQuant_proteinGroups.txt": {
    species: "mmu", omic: "Proteomics",
    tableSets: [[{ name: "LFQ intensities", tolerateMissing: 0.02, anyOf: [
      { id: "Protein IDs", id_transform: "lead", tolerateMissing: 0.02, values: { regex: "^LFQ intensity " },
        filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }] },
      { id: "Protein IDs", id_transform: "lead", values: { regex: "^LFQ intensity " },
        filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }, { col: "Only identified by site", ne: "+" }] },
      { id: "Majority protein IDs", id_transform: "lead", values: { regex: "^LFQ intensity " },
        filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }] }] }]],
  },
  "proteomics/PXD063043_MaxQuant_proteinGroups.txt": {
    species: "hsa", omic: "Proteomics",
    tableSets: [[{ name: "LFQ or raw intensities", anyOf: [
      { id: "Protein IDs", id_transform: "lead", values: { regex: "^LFQ intensity " },
        filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }] },
      { id: "Protein IDs", id_transform: "lead", values: { regex: "^LFQ intensity " },
        filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }, { col: "Only identified by site", ne: "+" }] },
      { id: "Protein IDs", id_transform: "lead", values: { regex: "^Intensity [A-Za-z]" },
        filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }] }] }]],
  },
  "proteomics/PXD063043_ProteomeDiscoverer_proteins.xlsx": {
    species: "hsa", omic: "Proteomics",
    noValues: true,
    relevant: [{ name: "identified proteins", optional: true, anyOf: [{ mode: "ids", id: "Accession" }] }],
  },
  "proteomics/PXD068742_DIANN_pg_matrix.tsv": {
    species: "mmu", omic: "Proteomics",
    tableSets: [[{ name: "protein group quantities", anyOf: [
      { id: "Protein.Group", id_transform: "lead", values: { regex: "raw_DIA" } },
      { id: "Protein.Ids", id_transform: "lead", values: { regex: "raw_DIA" } }] }]],
  },
  "proteomics/PXD075073_Spectronaut_proteins_report.tsv": {
    species: "mmu", omic: "Proteomics",
    tableSets: [[
      { name: "PG.Quantity", anyOf: ["PG.ProteinGroups", "PG.ProteinAccessions", "PG.UniProtIds"].map(id =>
        ({ id, id_transform: "lead", values: { regex: "\\.PG\\.Quantity$" } })) },
      { name: "PG.IBAQ", optional: true, anyOf: ["PG.ProteinGroups", "PG.ProteinAccessions", "PG.UniProtIds"].map(id =>
        ({ id, id_transform: "lead", values: { regex: "\\.PG\\.IBAQ$" } })) },
    ]],
  },
  "proteomics/STATegra_Proteomics_NOT_imputed.txt": {
    species: "mmu", omic: "Proteomics",
    tableSets: [[{ name: "intensities (NA kept)", anyOf: [
      { id: "Protein.IDs", id_transform: "lead", values: { regex: "^(con|IKA)_" } },
      { id: "Majority.protein.IDs", id_transform: "lead", values: { regex: "^(con|IKA)_" } }] }]],
  },
  "proteomics/pmid40238785_MaxQuant_proteinGroups_small.txt": {
    species: "mmu", omic: "Proteomics",
    tableSets: [[
      { name: "SILAC ratios or intensities", tolerateMissing: 0.02, anyOf: [
        { id: "Protein IDs", id_transform: "lead", tolerateMissing: 0.02, values: ["Intensity 1", "Intensity 2", "Intensity 3"],
          filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }] },
        { id: "Protein IDs", id_transform: "lead", tolerateMissing: 0.02, values: ["Intensity 1", "Intensity 2", "Intensity 3"],
          filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }, { col: "Only identified by site", ne: "+" }] },
        { id: "Protein IDs", id_transform: "lead", values: ["Ratio H/L normalized 1", "Ratio H/L normalized 2", "Ratio H/L normalized 3"],
          filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }] },
        { id: "Protein IDs", id_transform: "lead", values: ["Ratio H/L 1", "Ratio H/L 2", "Ratio H/L 3"],
          filter: [{ col: "Reverse", ne: "+" }, { col: "Potential contaminant", ne: "+" }] }] },
    ]],
  },
  "proteomics/pmid41526722_FragPipe_combined_protein.tsv": {
    species: "mmu", omic: "Proteomics",
    tableSets: [[
      { name: "TAILS intensity", anyOf: ["Protein ID", "Protein"].map(id => ({ id, values: ["TAILS Intensity"] })) },
      { name: "spectral counts", optional: true, anyOf: ["Protein ID", "Protein"].map(id => ({ id, values: ["TAILS Spectral Count"] })) },
    ]],
  },
};

module.exports = { KEY, ANSWERS_DEFAULT };
