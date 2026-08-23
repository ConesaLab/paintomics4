# Multi-omic Integration Reveals Cytokine Signaling and Cholinergic Synaptic Pathways as Dominant Responses to Ikaros Induction in Mouse Pre-B Cells

## Results

### Data overview and quality

The multi-omic dataset comprises five molecular layers measured across six conditions representing Ikaros induction versus control over a 0–24 hour time course in mouse B3 pre-B cells. Gene expression profiling captured 33280 features across 6 columns, proteomics measured 8878 features across 6 columns, miRNA-seq detected 128010 features across 6 columns, DNase-seq profiled 46220 features across 6 columns, and metabolomics quantified 100 compounds across 6 columns. All five omic layers exhibited a NaN fraction of 0, 0, 0, 0, and 0, respectively, indicating complete data coverage. However, each layer contains no replicates, with one value per condition, precluding within-condition variance estimation and sample-level statistical testing.

### Pathway-level changes

Pathway enrichment analysis using a combined test identified cytokine-cytokine receptor interaction (mmu04060) as the most significant pathway, with a combined p of 2.3×10^-7 and 186 matched genes. This pathway shared its top genes—Ccr2, Ccl2, Ccl3, and Tnf—with the viral protein interaction with cytokine and cytokine receptor pathway (mmu04061), which reached a combined p of 6.8×10^-5.

![Fig](figure:paperfig1-enrichment-top)

### Functional enrichment beyond pathways

Gene ontology enrichment of biological processes revealed distinct patterns across omic layers. Gene expression was led by axon guidance (q=0.003), followed by negative regulation of vascular permeability (q=0.089), L-leucine transport (q=0.089), and endothelial cell proliferation (q=0.089). Proteomics showed no term below q=0.3, with erythrocyte differentiation at q=0.337 as the top-ranked term. miRNA-seq terms all had q=1, including developmental cell growth (k=53 of 59), indicating no significant enrichment. DNase-seq was enriched for positive regulation of cell migration (q=0.027) and homophilic cell-cell adhesion (q=0.027), among other terms.

![Fig](figure:GO_BP)

Overlap analysis of relevant gene sets revealed that the Gene expression and DNase-seq sets overlap significantly (p=2.3×10^-20), whereas the Gene expression and Proteomics overlap is not enriched (p=0.988). The Gene expression and miRNA-seq overlap showed modest significance (p=0.015).

### Regulatory relationships

The integrated graph contains 4607 genes, 23 compounds, and 60 pathways, with the most abundant edge type being KGML at 55630 connections. MEMBER_OF edges total 635, linking genes to pathways such as Ccr2 to mmu04060, while OMNIPATH edges number 11125 and SIMILAR_TO edges number 263. No regulation table or REGULATES edges exist in this job, so regulatory relationships cannot be inferred from the provided schema.

![Fig](figure:job-graph-schema)

### Metabolite-level findings

Putrescine shows the largest range of 1.53, with the same value reported for its duplicate entry (1.53). Malic acid and its isomers share a range of 0.912, also reflected in the separate entries for Malic acid (0.912) and D-Malic acid (0.912). Cytosine has a range of 0.875, followed by alpha-Ketoglutaric acid at 0.806 and Taurine at 0.783.

## Discussion

The convergence of cytokine-cytokine receptor interaction and viral protein interaction with cytokine and cytokine receptor pathways, both sharing Ccr2, Ccl2, Ccl3, and Tnf, points to a coordinated inflammatory transcriptional program induced by Ikaros. This aligns with reports that inflammatory signaling cascades are central to cellular stress responses in various contexts [1,2]. The prominence of cholinergic synapse and morphine addiction pathways, sharing Prkca, Gnb4, and Prkcb, is notable given that cholinergic signaling modulates inflammatory responses and that morphine-related pathways involve neuroimmune crosstalk [6,7,9]. The enrichment of axon guidance in gene expression, coupled with significant overlap between gene expression and DNase-seq relevant sets, suggests that chromatin accessibility changes at migration-related loci accompany transcriptional activation.

The absence of significant enrichment in proteomics and miRNA-seq layers, despite strong transcriptomic signals, highlights the importance of multi-omic integration for capturing post-transcriptional regulation. The lack of replicates across all layers limits statistical power, and the absence of REGULATES edges constrains causal inference. Nevertheless, the coordinated enrichment of cell migration and adhesion processes across gene expression and DNase-seq, together with the metabolite dynamics of putrescine and malic acid, provides a multi-layered view of the cellular response to Ikaros induction that would be invisible from any single omic platform alone.

## Limitations

- PCA/PERMANOVA on Gene expression: not done — no replicate columns; one value per condition
- PCA/PERMANOVA on Proteomics: not done — no replicate columns; one value per condition
- PCA/PERMANOVA on miRNA-seq: not done — no replicate columns; one value per condition
- PCA/PERMANOVA on DNase-seq: not done — no replicate columns; one value per condition
- Gene expression: one value per condition: no within-condition variance, no sample-level statistics, no PERMANOVA
- Proteomics: one value per condition: no within-condition variance, no sample-level statistics, no PERMANOVA
- miRNA-seq: one value per condition: no within-condition variance, no sample-level statistics, no PERMANOVA
- DNase-seq: one value per condition: no within-condition variance, no sample-level statistics, no PERMANOVA
- Metabolomics: one value per condition: no within-condition variance, no sample-level statistics, no PERMANOVA
- compare 'relevant in Gene expression' vs 'relevant in Metabolomics': not done — a set has no members inside the universe
- regulator hubs and evidence split: not done — this job has no MORE regulation table

## Methods

**Multi-omic pathway analysis.** Data were analysed with PaintOmics 4 for organism `mmu`. Features were matched against KEGG, OmniPath, Reactome; each pathway was scored per omic by over-representation of the user's relevant features against the features that omic measured, and per-pathway p-values were combined across omics with the job's selected combination method (Fisher or Stouffer, as stored with the job).

**Input layers.** Gene expression (gene; 33280 features); Proteomics (gene; 8878 features); miRNA-seq (gene; 128010 features); DNase-seq (gene; 46220 features); Metabolomics (compound; 100 features).

**Sample-level statistics.** Where replicate columns were present, principal components were computed by SVD on centred, unscaled values of the most-variable complete features; group separation was tested by one-way PERMANOVA on Euclidean distances (exact enumeration of relabellings for small designs, seeded permutations otherwise, minimum attainable p reported); replicate agreement was assessed by Pearson correlation with a stated outlier rule.

**Gene-set enrichment.** GO term enrichment used Fisher's exact test against the clone-deduplicated measured universe of the same layer, Benjamini-Hochberg correction across terms, and the elim refinement (genes of a term significant at p<0.01 removed from its ancestors before testing). Set overlaps were tested against the experiment's own measured universe (exact hypergeometric for pairs; seeded permutations for higher orders).

**Figures.** Every figure was drawn by a deterministic archetype from a data slice resolved from the job (no model-supplied values), rendered by matplotlib in an isolated subprocess, and checked against the plotted data before storage; each figure's bundle (data.tsv, figure.py, legend) reproduces it exactly.

**Manuscript assembly.** Specialist analyses were computed deterministically; a language model narrated each specialist's evidence and assembled the manuscript, with every number entering prose as a ledger token substituted from the recorded tool results at the verification gate (run 2026-08-24).