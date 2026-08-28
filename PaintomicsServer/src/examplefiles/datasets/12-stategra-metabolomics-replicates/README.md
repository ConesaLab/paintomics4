# STATegra metabolomics — replicates and experimental design

The STATegra mouse Ikaros metabolomics time course at **sample level**: 58 targeted GC-MS + LC-MS analytes across 36 samples (Ikaros-induced vs control, six time points, three biological replicates), with the experimental design that maps every column to its condition. `08-stategra-multiomics` ships the same 58 metabolites as six averaged Ikaros/Control ratios; this dataset keeps the replicates, which is what the metabolite class activity test needs to estimate noise.

|  |  |
| --- | --- |
| **id** | `stategra-metabolomics-replicates` |
| **pipeline** | `pathway-acquisition` |
| **organism** | `mmu` |
| **conditions** | 12 (`Ctr_0H` … `Ctr_24H`, `Ik_0H` … `Ik_24H`), 3 replicates each |
| **simulated** | no, real data |

## What it exercises

* An experimental design file applied to a values file with one column per sample (36 → 12 conditions for painting)
* Metabolite class activity by **permutation test on the replicates** — self-contained, at BRITE levels 1, 2 and 3 — instead of the binomial on the relevant list
* Direction of change per class across the time course

## Files

**Metabolomics**
* values — `metabolomics_replicates.tab` (58 × 36, log2 of the fused, median-centred matrix; columns `Ctr_0H_B10`, `Ctr_0H_B11`, `Ctr_0H_B9`, …)
* experimental design — `experimental_design.tab` (long form: `column<TAB>condition`)
* relevant features — `metabolomics_relevant.tab` (34 names)

## Provenance

Gomez-Cabrero et al., *STATegra, a comprehensive multi-omics dataset of B-cell differentiation in mouse*, Sci Data 6:256 (2019), [doi:10.1038/s41597-019-0202-7](https://doi.org/10.1038/s41597-019-0202-7). Metabolomics deposited as MetaboLights MTBLS283.

Processed exactly as in the authors' MATLAB/R script (`Script_STATegra_Metabolomics`): targeted GC-MS (39 analytes) and LC-MS (59 analytes) with 13C internal-standard normalisation, amines taken from LC, batch 12 removed after PCA, fused, natural log, per-sample median centring — the deposited `Metabolomics_fused_log_mean_2019.txt`. `src/AdminTools/scripts/exampledata/stategrametabolomics.py` converts it to log2, renames the analytes to the spelling `08-stategra-multiomics` uses (so both map to the same KEGG compounds) and writes the design.

**Relevant list, recorded rule.** Per metabolite, an F-test for Ikaros — main effect plus Ikaros × time, adjusting for time (`y ~ time + Ikaros + Ikaros:time` against `y ~ time`, F(6, 24)) — at Benjamini–Hochberg FDR < 0.05: 34 of 58. This is the same per-metabolite model the class activity permutation test uses, so the list and the test agree by construction. The list in `08-stategra-multiomics` has no recorded rule.

## What the replicates buy

With ratios alone a class of four metabolites is 4 × 6 numbers and no noise estimate: no test can put it below p = 0.06 (signed-rank floor 2⁻ⁿ), and the binomial on the relevant list can only ask whether the class is *more* relevant than the rest of a panel in which 67 % of metabolites respond. With the 36 samples the test asks whether the class responds at all — per class, the mean F of its members against 2000 re-labellings of Ikaros/Control inside each time point. On this data: Amines (putrescine), Neurotransmitters, Amino acids and Carboxylic acids respond (p ≤ 0.001); Monosaccharides, Bases and Nucleosides do not.
