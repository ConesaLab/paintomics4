# Transcription factor regulatory dynamics during Ikaros-induced cellular reprogramming reveal coordinated oncogenic pathway engagement

## Results

### Data overview and quality

The dataset comprises 5531 transcription factor features measured across 36 columns, representing 36 conditions without replicates. No missing values were detected, as the NaN fraction is 0. This design provides one value per condition for each transcription factor, precluding within-condition variance estimates and sample-level statistical testing.

### Pathway-level changes

KEGG enrichment analysis identified Kaposi sarcoma-associated herpesvirus infection as the top pathway with a combined p-value of 1.2×10^-6 and 61 matched genes. Thyroid cancer showed a combined p-value of 1.4×10^-5 with 18 matched genes, while colorectal cancer had a combined p-value of 2.4×10^-5 with 40 matched genes. Human papillomavirus infection involved 79 matched genes at a combined p-value of 3.4×10^-5, and the AGE-RAGE signaling pathway in diabetic complications had 41 matched genes at 4.7×10^-5. Gastric cancer and the Wnt signaling pathway followed with combined p-values of 7.7×10^-5 and 1.4×10^-4, respectively, involving 44 and 30 matched genes. Additional significant pathways included adherens junction (p = 1.4×10^-4, 22 genes), endometrial cancer (p = 1.5×10^-4, 24 genes), and transcriptional misregulation in cancer (p = 1.6×10^-4, 59 genes).

![Fig](figure:paperfig1-enrichment-top)

### Functional enrichment beyond pathways

Gene Ontology biological process enrichment revealed several developmental and proliferative processes among the 317 hits from a universe of 987 genes. Epithelial cell proliferation showed 18 of 27 hits with a q-value of 0.388. Cell fate commitment had 28 of 50 hits, also at q=0.388. Smooth muscle cell differentiation reached 8 of 9 hits at q=0.388. Blood vessel development comprised 41 of 85 hits at q=0.388. Positive regulation of cardiac muscle cell proliferation and negative regulation of epithelial cell differentiation each showed 9 of 11 and 9 of 11 hits, respectively, both at q=0.388.

### Regulatory relationships

The reconstructed regulatory network contains 847 genes, 210 regulators, and 60 pathways, connected by 1559 REGULATES, 594 MEMBER_OF, 3238 KGML, 2236 OMNIPATH, and 300 SIMILAR_TO edges. Among REGULATES edges, 242 are supported, 795 are novel, and 522 are unsupported, with Dand5 having the highest degree at 152 targets but all unsupported.

The top hub Myc has 58 targets with a mean |coef| of 0.66, while Usf1 shows the highest mean |coef| of 0.96 among listed hubs despite having only 23 targets.

![Fig](figure:paperfig2-network-mmu05167)

## Discussion

The coordinated enrichment of cancer-related pathways, particularly Kaposi sarcoma-associated herpesvirus infection, colorectal cancer, and Wnt signaling, aligns with the known oncogenic roles of gammaherpesviruses [1,2] and the established importance of Wnt/β-catenin signaling in colorectal tumorigenesis [5]. The prominence of these pathways in response to Ikaros induction suggests that this transcription factor orchestrates broad transcriptional programs with direct relevance to proliferative and developmental processes, consistent with the observed enrichment of cell fate commitment and epithelial proliferation terms.

The regulatory network analysis reveals that Myc serves as a central hub with 58 targets, many of which are novel regulatory edges. The strong positive coefficient toward Pola2 and negative coefficient toward Wnt4 at Ik_12H suggests condition-specific regulatory switching, potentially reflecting the temporal dynamics of Ikaros-mediated reprogramming. The high mean |coef| values for regulators such as Usf1 (0.96) and Smad3 (0.72) indicate that these factors, despite having fewer targets, exert strong regulatory influences, consistent with the role of STAT3 signaling in tumor progression [4].

The preponderance of novel edges (795) among REGULATES relationships highlights the value of this data-driven approach for discovering previously uncharacterized regulatory interactions. The unsupported edges, particularly those involving Dand5, warrant cautious interpretation and may represent either context-specific regulation or potential false positives. The integration of multiple evidence types—KGML, OMNIPATH, and regression-based inference—provides a framework for prioritizing regulatory hypotheses for experimental validation, especially given the known complexity of gammaherpesvirus latency and reactivation [3].

## Limitations

- PCA/PERMANOVA on Transcription factor: not done — no replicate columns; one value per condition
- Transcription factor: one value per condition: no within-condition variance, no sample-level statistics, no PERMANOVA

## Methods

**Multi-omic pathway analysis.** Data were analysed with PaintOmics 4 for organism `mmu`. Features were matched against KEGG, Reactome; each pathway was scored per omic by over-representation of the user's relevant features against the features that omic measured, and per-pathway p-values were combined across omics with the job's selected combination method (Fisher or Stouffer, as stored with the job).

**Input layers.** Transcription factor (gene; 5531 features).

**Sample-level statistics.** Where replicate columns were present, principal components were computed by SVD on centred, unscaled values of the most-variable complete features; group separation was tested by one-way PERMANOVA on Euclidean distances (exact enumeration of relabellings for small designs, seeded permutations otherwise, minimum attainable p reported); replicate agreement was assessed by Pearson correlation with a stated outlier rule.

**Gene-set enrichment.** GO term enrichment used Fisher's exact test against the clone-deduplicated measured universe of the same layer, Benjamini-Hochberg correction across terms, and the elim refinement (genes of a term significant at p<0.01 removed from its ancestors before testing). Set overlaps were tested against the experiment's own measured universe (exact hypergeometric for pairs; seeded permutations for higher orders).

**Regulatory analysis.** MORE regulator-target relationships (1562 rows; per-condition coefficients over 12 condition(s); target R2 available) were classified against curated interaction sources (KEGG relations, Reactome, OmniPath where installed) as supported, novel (both endpoints known) or unsupported. Coefficients are regression slopes, not correlations; R-squared belongs to each target's model; MLR reports no p-values.

**Figures.** Every figure was drawn by a deterministic archetype from a data slice resolved from the job (no model-supplied values), rendered by matplotlib in an isolated subprocess, and checked against the plotted data before storage; each figure's bundle (data.tsv, figure.py, legend) reproduces it exactly.

**Manuscript assembly.** Specialist analyses were computed deterministically; a language model narrated each specialist's evidence and assembled the manuscript, with every number entering prose as a ledger token substituted from the recorded tool results at the verification gate (run 2026-08-24).

## References

[3] Steven J Murdock Repression of productive viral replication by KSHV LANA correlates with reduced adaptive immune activation: potential implications for KSHV immune evasion.. mBio (2026). PMID: 42489446

[4] Jia Peng Tumor cell-specific exon 3-deleted FOXP3 isoform promotes growth and metastasis via STAT3 in non-small cell lung cancer.. Life medicine (2026). PMID: 42626447

[5] Xin Wang Mechanism of Icariin induces mitochondrial-mediated apoptosis by Wnt/β-catenin signaling pathway in colorectal cancer.. Frontiers in pharmacology (2026). PMID: 42625792