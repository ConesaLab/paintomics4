# Synthesis Report: Multi-Omics Analysis of B3 Pre-B Cell Differentiation

## Key Findings

1. **Coordinated metabolic reprogramming**: HIF-1-driven aerobic glycolysis is transcriptionally downregulated (27/40 genes DE, p=0.0058), with glycolytic enzymes (Hk2, Pfkl, Pfkp, Ldha, Aldoa, Gapdh) all declining 0.125-0.312 units by 24h.

2. **Growth axis silencing**: The insulin/IGF-1–PI3K–AKT–mTOR pathway shows progressive chromatin closing (DNase-seq p=0.0072), with Mtor (0.014→-0.502), Rptor (0.314→-0.396), and Rheb (0.521→-0.327) all losing accessibility.

3. **Anti-apoptotic shift**: Bcl2 rises dramatically across multiple layers (gene expression 1.507→3.058; four miRNA tracks corroborate), while pro-apoptotic effectors (Bak1, Casp3) show chromatin closing.

4. **Chromatin remodeling dominates**: DNase-seq is the strongest enriched layer across most pathways (apoptosis p=0.0128, GnRH p=0.0073, longevity p=0.0072, melanoma p=0.0265), suggesting widespread transcriptional silencing.

5. **Dynll1 outlier**: Massive protein upregulation (1.745→5.285) against closing chromatin—the most dramatic single-gene change in the dataset.

---

## Theme 1: Metabolic Reprogramming—Shutdown of Glycolytic Program

### HIF-1 Signaling Pathway (mmu04066)
The most transcriptionally coherent pathway in the dataset, driven by gene expression (p=0.0058, 27/40 relevant) and TF layers (p=0.0149, 9/20). All core glycolytic targets decline:
- **Hk2**: 0.016→-0.312 (expression); DNase 0.240→-0.309
- **Pfkl**: 0.023→-0.242; **Pfkp**: 0.006→-0.257
- **Ldha**: 0.008→-0.214; DNase 0.468→-0.437
- **Aldoa**: 0.017→-0.125; DNase 0.506→-0.624
- **Gapdh**: -0.003→-0.094; **Pdk1**: 0.060→-0.172
- **Vegfa**: -0.034→-0.356

HIF-1α itself is flat (0.039→0.046, not DE), but degradation machinery increases: **Vhl** (0.034→0.116) and sustained high **Egln3** (0.802→0.519). Translational regulators **Eif4e** (-0.021→-0.163) and **Eif4ebp1** (0.003→-0.255) decline.

**Layer disagreement**: Proteomics (0/15 genes), DNase-seq (p=0.5092), and metabolomics (p=0.8288) show no enrichment—the transcriptional signal is not confirmed at protein or metabolite level.

### Longevity Regulating Pathway (mmu04213)
Complementary chromatin-level evidence for growth pathway silencing. DNase-seq is dominant (p=0.0072, 39/57 relevant):
- **Mtor**: 0.014→-0.502; **Rptor**: 0.314→-0.396; **Rheb**: 0.521→-0.327
- **Prkaca**: 0.286→-0.488; **Prkab1**: 0.300→-0.515; **Prkag1**: 0.798→-0.214

miRNA layer shows large directional changes: **Sirt1** rises (1.715→2.986) while **Foxo3** (-0.266→-1.306), **Foxo1** (-0.021→-0.567), **Rb1cc1** (-0.067→-1.551), and **Atg13** (0.032→-0.794) fall.

Gene expression is weak (p=0.1359) but reinforces direction: **Eif4ebp1** (0.003→-0.255), **Eif4e** (-0.021→-0.163). Proteomics provides no support (0/3 relevant).

---

## Theme 2: Apoptosis Regulation—Pro-Survival Shift

### Intrinsic Pathway for Apoptosis
Chromatin layer dominates (22/30 relevant, p=0.0128) with TF layer also enriched (4/6, p=0.0151). Gene expression marginal (p=0.0863).

**Pro-survival signals**:
- **Bcl2**: Gene expression 1.507→3.058; four miRNA tracks corroborate (1.715→2.986, 0.457→1.004, 1.754→3.093)
- **Birc2** (cIAP1): 0.010→0.130 (expression)
- **Birc5** (survivin): -0.194→0.986 (miRNA)

**Pro-apoptotic silencing**:
- **Bak1**: DNase 0.378→-0.653
- **Casp3**: DNase 0.391→-0.357
- **Htra2**: -0.002→-0.197 (expression)
- **Cycs**: 0.004→-0.115 (expression); miRNA rises to 0.986

**Key contradictions**:
- **Casp9**: Rises in expression/TF (0.020→0.225) but DNase closes (0.795→-0.159)
- **Bcl2l11** (BIM): Expression rises (0.023→0.160) but DNase falls (1.092→-0.079)
- **Bax**: Protein drops to -1.289 at 12h, spikes to +0.882 at 18h

### Apoptosis—Multiple Species
Confirms the anti-apoptotic interpretation with additional detail:
- **Birc6** declines in expression (-0.010→-0.151) and DNase (0.692→-0.379)—counterintuitive for an IAP
- **Bbc3** (PUMA) is flat (-0.022→0.032)
- JNK pathway (Mapk8/9/10) shows no coordinated change

### Dynll1—The Outlier
Protein rises dramatically: 1.745→5.285 (24h) with transient dip to -0.821 at 12h, while DNase closes (0.632→-0.461). This dynein light chain interacts with BCL-2 family members and represents the most striking proteomic change in the dataset.

---

## Theme 3: Signaling Pathway Remodeling

### GnRH Secretion Pathway (mmu04929)
Primarily chromatin-driven (DNase p=0.0073, 20/26 relevant; TF p=0.0100, 7/13). Widespread chromatin closing:
- **Hras**: DNase 0.703→-0.333; **Kras**: 1.238→-0.167
- **Gna11**: 0.717→-0.463; **Pik3r3**: 0.567→-0.416
- **Mapk3**: 0.633→-0.395; **Hcn3**: 0.920→-0.240

Selective transcriptional upregulation despite closing chromatin:
- **Cacna1i**: Expression -0.098→0.452 (miRNA represses: 0.032→-1.123)
- **Kiss1r**: 0.035→0.270; **Pik3r3**: 0.095→0.452

**Paradox**: Chromatin closes broadly while specific genes (receptor, calcium channel) are induced—suggesting pathway remodeling rather than uniform silencing.

### Signaling by TGFBR3
Core receptor complex downregulated:
- **TGFBR3**: miRNA 0.247→-1.040 (steepest drop 12-18h: -0.360→-1.060)
- **TGFBR2**: Four miRNA probes decline; DNase 0.515→-0.278
- **TGFBR1**: miRNA -0.858→-1.538; DNase 0.816→0.046
- **TGFB1**: Expression -0.044→-0.089; DNase 0.871→-0.289

Exceptions: **GIPC1** (0.008→0.113) and **NCSTN** (-0.019→0.083) rise in expression; **ARRB1** miRNA rises (1.697→3.483) despite expression decline (0.089→-0.051).

Enrichment: TF (p=0.0151) and DNase (p=0.0587) strongest; expression weak (p=0.1055); miRNA not enriched (p=1.0).

### Melanoma Pathway (mmu05218)
Complex pattern with DNase (p=0.0265, 26/38) and TF (p=0.0138, 5/8) driving enrichment.

**Standout gene—Mitf**: miRNA rises dramatically (1.507→3.058 and 1.697→3.483) but DNase is negative and flat (-0.530→-0.416).

**Cell cycle**: **Ccnd1** elevated across miRNA tracks (1.754→3.093); **Rb1** rises in expression (0.011→0.158) with strong DNase (1.066).

**Discordant signals**:
- **Map2k1**: miRNA rises (0.102→1.280) but DNase declines (0.696→-0.265)
- **Pten**: DNase collapses (1.168→0.011 by 2h)
- **Mdm2**: miRNA declines (-0.240→-1.390) while **Trp53** also declines (expression -0.009→-0.069; DNase -0.055→-0.321)

---

## Cross-Pathway Themes

### 1. Chromatin Closing as Dominant Regulatory Mechanism
Across all pathways, DNase-seq shows progressive loss of accessibility. This is most consistent in the longevity (39/57 genes), intrinsic apoptosis (22/30), and GnRH (20/26) pathways. The pattern suggests differentiation involves large-scale transcriptional silencing of growth, glycolysis, and signaling modules.

### 2. Layer Discordance as a Recurring Feature
Multiple genes show opposing signals across layers:
- **Casp9**: Expression up, chromatin closing
- **Map2k1**: miRNA up, DNase down
- **Bcl2l11**: Expression up, DNase down
- **Cacna1i**: Expression up, miRNA repressing
- **Mitf**: miRNA up, DNase flat/negative

This suggests active regulatory tug-of-war during differentiation, with chromatin remodeling preceding or opposing transcriptional changes.

### 3. Selective Upregulation Amidst Global Silencing
Despite widespread downregulation, specific genes rise: **Pik3r3** (expression 0.095→0.378), **Kiss1r** (0.035→0.270), **Cacna1i** (-0.098→0.452), **GIPC1** (0.008→0.113), **NCSTN** (-0.019→0.083), **Sirt1** (miRNA 1.715→2.986). These may represent differentiation-specific programs.

### 4. Bcl2 as a Multi-Layer Pro-Survival Signal
The most consistent single-gene anti-apoptotic signal, rising across gene expression and four miRNA tracks. This is the strongest evidence for a functional anti-apoptotic shift.

---

## Limitations and Caveats

1. **Proteomic coverage is sparse**: Multiple pathways show 0/2-0/15 relevant genes in the proteomics layer, preventing confirmation of transcriptional changes at the protein level.

2. **Chromatin accessibility ≠ activity**: DNase-seq reflects regulatory potential, not actual transcription. The dominant chromatin signal may overstate the functional significance of pathway changes.

3. **miRNA enrichment is inconsistent**: Several pathways show large miRNA changes without statistical enrichment (TGFBR3 p=1.0, apoptosis p=0.596), suggesting these may reflect broad, non-specific shifts.

4. **Metabolomics provides no corroboration**: Only 1-4 genes per pathway, with no meaningful signal—glycolytic shutdown is inferred from transcription, not confirmed by metabolite measurements.

5. **Layer disagreements remain unresolved**: The Casp9, Map2k1, and Mitf discordances highlight that the net functional direction of several pathways cannot be firmly established.

6. **Cell population heterogeneity**: The time course may capture mixed populations transitioning between states, complicating interpretation of intermediate timepoints.

7. **Pathway context**: GnRH secretion and melanoma pathways are not canonical B-cell programs; their enrichment may reflect shared signaling components rather than pathway-specific biology in this cell type.

## Enriched Pathway Summary

Complete enrichment result, rendered directly from the analysis. Genes listed are those differentially expressed in this experiment.

| Pathway | Source | p-value | Driving omic layers | Differential genes |
|---|---|---|---|---|
| Herpes simplex virus 1 infection | KEGG | 6.09e-04 | Gene expression: p=0.0010 (43/65 relevant); DNase-seq: p=0.8194 (61/127 relevant | Syk, Srsf3, Srsf9, Mavs, Bcl2, Srsf4 |
| Autophagy - animal | KEGG | 6.57e-04 | Gene expression: p=0.2785 (36/71 relevant); DNase-seq: p=0.0029 (83/130 relevant | Smcr8, Mtmr3, Bcl2, Stx17, Irs1, Rab8a |
| Neutrophil degranulation | Reactome | 7.43e-04 | Gene expression: p=0.0001 (101/169 relevant); DNase-seq: p=0.9140 (140/292 relev | Dynll1, ENSMUSG00000025289, ENSMUSG00000065979, ENSMUSG00000032468, ENSMUSG00000001016, ENSMUSG00000021737 |
| Human T-cell leukemia virus 1 infection | KEGG | 2.13e-03 | Gene expression: p=0.0052 (49/80 relevant); miRNA-seq: p=0.1165 (5/45 relevant); | Smad3, Ranbp3, Ccnd2, Xpo1, H2-K1, H2-Q1 |
| Apoptosis | KEGG | 2.85e-03 | Gene expression: p=0.0164 (35/57 relevant); miRNA-seq: p=0.7163 (2/42 relevant); | Bcl2, Sptan1, Bcl2l11, Aifm1, Itpr1, Tuba4a |
| Human papillomavirus infection | KEGG | 4.34e-03 | Gene expression: p=0.0042 (61/102 relevant); miRNA-seq: p=0.6938 (3/60 relevant) | Pard3, Ccnd2, Fzd7, Ube3a, H2-K1, H2-Q1 |
| Spinocerebellar ataxia | KEGG | 4.49e-03 | Gene expression: p=0.9415 (20/54 relevant); DNase-seq: p=0.0001 (68/96 relevant) | Adrm1, Psmc6, Psma7, Afg3l2, Psmd6, Psmc5 |
| Intrinsic Pathway for Apoptosis | Reactome | 5.38e-03 | Gene expression: p=0.0863 (11/17 relevant); DNase-seq: p=0.0128 (22/30 relevant) | Dynll1, ENSMUSG00000040093, ENSMUSG00000057329, ENSMUSG00000027381, ENSMUSG00000019979, ENSMUSG00000020483 |
| AGE-RAGE signaling pathway in diabetic complications | KEGG | 5.60e-03 | Gene expression: p=0.0278 (18/27 relevant); DNase-seq: p=0.0012 (38/52 relevant) | Smad3, Bcl2, Cdc42, Stat5b, Tgfbr1, Vegfa |
| Hippo signaling pathway | KEGG | 5.89e-03 | Gene expression: p=0.0824 (24/41 relevant); miRNA-seq: p=0.3347 (3/35 relevant); | Pard3, Btrc, Smad3, Ccnd2, Fzd7, Tgfbr1 |
| Cellular response to heat stress | Reactome | 6.69e-03 | Gene expression: p=0.0798 (21/36 relevant); Proteomics: p=0.0626 (6/21 relevant) | Nup85, ENSMUSG00000020361, Nup50, Nup133, ENSMUSG00000026999, ENSMUSG00000027395 |
| Arginine and proline metabolism | KEGG | 7.33e-03 | Gene expression: p=0.0002 (14/15 relevant); DNase-seq: p=0.0613 (19/28 relevant) | Aldh18a1, Srm, Aldh4a1, Oat, Lap3, Got2 |
| Cellular senescence | KEGG | 7.34e-03 | Gene expression: p=0.2872 (33/65 relevant); miRNA-seq: p=0.1885 (4/39 relevant); | Ppid, Rad50, Btrc, Smad3, Ccnd2, H2-K1 |
| Efferocytosis | KEGG | 7.72e-03 | Gene expression: p=0.0856 (26/45 relevant); DNase-seq: p=0.0633 (53/88 relevant) | Dusp16, Crkl, Dusp4, Elmo1, Slc16a1, Dnmt3a |
| GnRH secretion | KEGG | 8.81e-03 | Gene expression: p=0.1106 (12/19 relevant); miRNA-seq: p=0.5961 (1/15 relevant); | Arrb1, Itpr1, Mapk1, Akt3, Pik3cd, Map2k1 |
| Adrenergic signaling in cardiomyocytes | KEGG | 9.65e-03 | Gene expression: p=0.9257 (13/36 relevant); Proteomics: p=0.2170 (3/13 relevant) | Myl4, Tpm1, Atp2b4, Bcl2, Ppp1ca, Mapk1 |
| Adherens junction | KEGG | 1.14e-02 | Gene expression: p=0.5101 (13/27 relevant); miRNA-seq: p=0.6635 (1/18 relevant); | Pard3, Smad3, Csnk2a2, Wasf2, Cdc42, Tgfbr1 |
| Longevity regulating pathway | KEGG | 1.25e-02 | Gene expression: p=0.1359 (19/33 relevant); DNase-seq: p=0.0072 (39/57 relevant) | Irs1, Akt3, Adcy7, Rb1cc1, Pik3cd, Cat |
| Pancreatic cancer | KEGG | 1.26e-02 | Gene expression: p=0.1314 (17/29 relevant); DNase-seq: p=0.0142 (41/62 relevant) | Smad3, Cdc42, Tgfbr1, Vegfa, Cdk6, Mapk1 |
| Melanoma | KEGG | 1.29e-02 | Gene expression: p=0.1517 (10/16 relevant); DNase-seq: p=0.0265 (26/38 relevant) | Mitf, Cdk6, Mapk1, Akt3, Mdm2, Braf |
| Hepatocellular carcinoma | KEGG | 1.34e-02 | Gene expression: p=0.0389 (31/52 relevant); DNase-seq: p=0.0010 (66/98 relevant) | Smarca4, Smad3, Gsto1, Gsto2, Fzd7, Smarcc2 |
| HIF-1 signaling pathway | KEGG | 1.40e-02 | Gene expression: p=0.0058 (27/40 relevant); Proteomics: p=1.0000 (0/15 relevant) | Bcl2, Gapdh, Vegfa, Egln3, Mapk1, Akt3 |
| Wnt signaling pathway | KEGG | 1.45e-02 | Gene expression: p=0.0320 (26/42 relevant); miRNA-seq: p=0.3018 (3/33 relevant); | Btrc, Smad3, Znrf3, Bambi, Csnk2a2, Ccnd2 |
| Resolution of Abasic Sites (AP sites) | Reactome | 1.66e-02 | Gene expression: p=0.2613 (10/18 relevant); Proteomics: p=0.1496 (2/5 relevant); | ENSMUSG00000035960, ENSMUSG00000027395, ENSMUSG00000028394, ENSMUSG00000000751, ENSMUSG00000033970, ENSMUSG00000020287 |
| Signaling by TGFBR3 | Reactome | 1.74e-02 | Gene expression: p=0.1055 (7/10 relevant); DNase-seq: p=0.0587 (10/13 relevant); | ENSMUSG00000018909, ENSMUSG00000007613, ENSMUSG00000032375, ENSMUSG00000032440, ENSMUSG00000019433, ENSMUSG00000002603 |
| Apoptosis - multiple species | KEGG | 1.79e-02 | Gene expression: p=0.0190 (9/11 relevant); miRNA-seq: p=0.5961 (1/15 relevant);  | Bcl2, Bcl2l11, Apaf1, Bax, Cycs, Birc5 |
