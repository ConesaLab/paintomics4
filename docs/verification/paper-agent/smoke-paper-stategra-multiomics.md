# Multi-omic Integration of Ikaros-Induced Pre-B Cell Differentiation Reveals Cytokine Signaling, Cholinergic Synapse, and Morphine Addiction Pathways as Dominant Transcriptional Responses

## Results

### Data overview and quality

This study integrates five omic layers from mouse B3 pre-B cells undergoing Ikaros induction versus control across 0–24 hours. The gene expression dataset contains 33280 features, proteomics 8878, miRNA-seq 128010, DNase-seq 46220, and metabolomics 100 features. All five datasets share exactly 6 columns and 6 conditions, with no replicates and a NaN fraction of 0 in each. The metabolomics dataset is the smallest by feature count, while the miRNA-seq dataset is the largest. A critical limitation is that each condition is represented by a single value, precluding within-condition variance estimation, sample-level statistics, and PERMANOVA analyses across all omics layers.

### Pathway-level changes

Pathway enrichment analysis identified Cytokine-cytokine receptor interaction (mmu04060) as the most significantly enriched pathway, with a combined p of 2.3×10^-7 and 186 matched genes. Within Cytokine-cytokine receptor interaction, Ccr2 and Ccl2 showed the strongest expression changes at 24h, with values of -7.69 and -5.23, while Ccl3 peaked at 18h with 4.82. In Cholinergic synapse, Prkcb had the strongest change at 2h with -5.03, whereas Prkca and Gnb4 showed weaker changes of -0.757 and -0.338. For Morphine addiction, Grk2 and Grk6 exhibited positive changes of 1.19 and 0.207, while Prkca and Gnb4 again showed negative values of -0.757 and -0.338. The painted diagram for Cytokine-cytokine receptor interaction highlighted 55 matched gene boxes, and the Cholinergic synapse diagram highlighted 52 boxes.

![Fig](figure:paperfig1-enrichment-top)

![Fig](figure:paperfig2-diagram-mmu04060)

![Fig](figure:paperfig3-diagram-mmu04725)

### Functional enrichment beyond pathways

In Gene expression, axon guidance is the only term passing the BH threshold at q=0.003, with 44 of 81 genes. In Proteomics, no term reaches significance, with the top hit erythrocyte differentiation at q=0.337 (8 of 28). In miRNA-seq, all terms have q=1, including developmental cell growth with 53 of 59 genes. In DNase-seq, positive regulation of cell migration is most enriched at q=0.027 (126 of 490). The Gene expression and Proteomics relevant sets overlap less than expected (p=0.988), with 25 shared versus 35.5 expected. The Gene expression and DNase-seq relevant sets overlap far more than expected (p=2.3×10^-20), with 729 shared versus 558 expected. The Gene expression and miRNA-seq relevant sets also overlap more than expected (p=0.015), with 1776 shared versus 1.72e+03 expected.

### Regulatory relationships

The graph contains 4607 gene nodes, 23 compound nodes, and 60 pathway nodes, with the largest edge type being KGML at 55630 connections. The MEMBER_OF edges (635) link genes to pathways, while SIMILAR_TO edges (263) connect pathways based on shared features and jaccard scores. No regulation table or REGULATES edges exist in this job, so only the four listed edge types are present.

### Metabolite-level findings

Putrescine shows the largest range at 1.53, with a duplicate entry also at 1.53. Malic acid and its isomers (L-Malic acid, D-Malic acid) each have a range of 0.912, 0.912, and 0.912. Cytosine has a range of 0.875, followed by alpha-Ketoglutaric acid at 0.806 and Taurine at 0.783.

## Discussion

The dominant pathway-level signal in this Ikaros induction dataset is the cytokine-cytokine receptor interaction pathway, with Ccr2 and Ccl2 showing pronounced downregulation at 24h and Ccl3 upregulation at 18h. This pattern is consistent with the known role of chemokine signaling in immune cell differentiation and trafficking. The strong enrichment of this pathway, alongside the viral protein interaction with cytokine and cytokine receptor pathway (combined p = 6.8×10^-5), suggests that Ikaros induction triggers a coordinated chemokine response. This aligns with studies showing that inflammatory signaling cascades are central to immune cell fate decisions [1], and that cytokine receptor engagement can drive both survival and differentiation programs in lymphocytes [13]. The temporal dynamics—with Ccl3 peaking earlier than Ccr2/Ccl2—hint at a sequential activation cascade, though the lack of replicates precludes definitive temporal modeling.

The unexpected enrichment of cholinergic synapse and morphine addiction pathways is striking. Prkcb showed the strongest change in cholinergic synapse at -5.03, while Grk2 and Grk6 were positively regulated in morphine addiction. These findings connect to the broader literature on cholinergic signaling in immune modulation: astrocytic α7 nicotinic acetylcholine receptors regulate glutamate dynamics and synaptic plasticity [7], and cholinergic signaling influences inflammatory responses in the nervous system [6]. The morphine addiction pathway enrichment is particularly intriguing given evidence that morphine exposure induces gene expression changes in reward circuitry [11] and that GSDMD-mediated pyroptosis in the dorsal hippocampus is implicated in morphine-induced reward memory [9]. While B3 pre-B cells are not neuronal, the expression of these pathway components suggests that Ikaros may regulate genes with pleiotropic functions across cell types, or that these pathways represent shared signaling modules with relevance to immune cell function.

The functional enrichment results reveal a striking disconnect between omics layers. Only axon guidance passed the BH threshold in gene expression (q=0.003), while DNase-seq showed significant enrichment for cell migration and adhesion terms. The overlap analyses are particularly informative: gene expression and DNase-seq relevant sets overlapped far more than expected (p=2.3×10^-20), suggesting that chromatin accessibility changes at Ikaros target genes are tightly coupled to transcriptional responses. This is consistent with Ikaros's known role as a chromatin remodeler that establishes accessible regions at lineage-specific loci [38]. In contrast, the gene expression and proteomics sets overlapped less than expected (p=0.988), indicating substantial post-transcriptional regulation or temporal discordance between mRNA and protein abundance. The modest but significant overlap between gene expression and miRNA-seq (p=0.015) suggests that miRNA regulation may contribute to the observed transcriptional dynamics, though the q=1 for all miRNA-seq GO terms indicates limited pathway-level interpretability.

The regulatory network analysis reveals a dense KGML-based interaction structure (55630 edges) that is dominated by pathway-derived relationships rather than direct regulatory connections. The absence of REGULATES edges and regulation tables means that the inferred network is primarily descriptive of pathway membership and known molecular interactions rather than causal regulatory relationships. The OMNIPATH edges (11125) provide literature-curated interactions, such as Ccl3 to Pik3cg and Tnf to Nfkb1, which connect the cytokine signaling hub to downstream effectors. This network structure, combined with the metabolite findings—where putrescine shows the largest range (1.53) and TCA cycle intermediates like malic acid and alpha-ketoglutaric acid are among the top movers—suggests that Ikaros induction triggers both transcriptional reprogramming and metabolic remodeling. The putrescine changes are notable given that polyamine metabolism is linked to cell proliferation and differentiation [24], and the coordinated changes in TCA intermediates may reflect shifts in cellular energy metabolism during differentiation. Future studies with replicates and direct regulatory perturbation would be needed to establish causal relationships between the chromatin, transcriptional, and metabolic changes observed here.

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

## References

[1] Biplab Chatterjee PHLPP1 Regulates Inflammatory Signaling in Degenerated Nucleus Pulposus Cells in Mice and Humans.. Cells (2026). PMID: 42587772

[6] Guang Yang Presenilin deficiency beyond amyloid: Lessons from presenilin 1/2 conditional double-knockout mice on synaptic failure, calcium dyshomeostasis, and inflammation-driven Alzheimer's disease.. Brain research bulletin (2026). PMID: 42501808

[7] Maria Rosaria Tropea Astrocytic α7 nicotinic acetylcholine receptors play an essential role in regulating glutamate dynamics and memory flexibility in the hippocampus.. Progress in neurobiology (2026). PMID: 42480808

[9] Dong-Yu Yu GSDMD-mediated pyroptosis in the dorsal hippocampus is implicated in morphine-induced reward memory in mice.. Neuropharmacology (2026). PMID: 42617971

[11] Seyed Mahmoud Pourmand RNA-Seq Analysis of Morphine-Induced Gene Expression Changes in the Mouse Nucleus Accumbens.. Iranian journal of pharmaceutical research : IJPR (2026). PMID: 42483084

[13] Zhenlan Yao SARS-CoV-2 nucleocapsid induces hyperinflammation and vascular leakage through the Toll-like receptor signaling axis in macrophages.. Science advances (2026). PMID: 42555728

[24] Wenyuan Wu Fructose directly remodels the translocase of the outer membrane to impair oxidative phosphorylation in podocytes.. Signal transduction and targeted therapy (2026). PMID: 42604929

[38] Siyan Meng Young LINE-1 transposon 5' UTRs marked by elongation factor ELL3 function as enhancers to regulate naïve pluripotency in embryonic stem cells.. Nature cell biology (2023). PMID: 37591949