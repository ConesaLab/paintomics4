<div class="imageContainer" style="" >
    <img src="paintomics_150x690.png" title="Paintomics LOGO." style=" height: 70px !important; margin-bottom: 20px; ">
</div>

# Regulatroy omics analysis

## Introduction

PaintOmics 3 provided the Regulatory Omics option designed to upload data on features such as microRNA-seq, acting as regulators of gene expression. PaintOmics 4 extends this functionality to accept any type of trans-acting element operating on genes, transcripts or proteins and includes filtering functions to extract meaningful regulatory relationships. In addition to microRNA-seq, transcription factors (TF) and splicing factors (SF), detected by RNA-seq, RNA-binding proteins identified by CLIP-seq, etc., can be analysed with this option. The Regulatory Omics option takes a trans-regulatory-feature data matrix with expression or activity values for regulators in the conditions of the study. The regulator-gene/protein mapping file is provided by the user, together with an optional list of significant deferentially expressed regulators. PaintOmics 4 filtering options include thresholds for positive or negative correlation to select the expected regulatory relationships. Applying these criteria, regulatory features (regulators) will be mapped to their targeted features and their corresponding pathways. A pathway enrichment score is calculated either based on the number of regulators mapping to each pathway or on the number of regulated genes present in the pathway. Enriched pathways for the Regulatory Omics modality represent biological processes that are significantly impacted by that regulatory layer (Figure 1).

<div class="imageContainer" style="box-shadow: 0px 0px 20px #D0D0D0; text-align:center; font-size:10px; color:#898989" >
    <img src="paintomics_regulatory_omics_figure1.png"/>
    <p class="imageLegend"><b>Figure 1:</b> The pipeline of Regulatory Omics analysis in PaintOmics 4</p>
</div>

## Input data, visualisation and parameters

### Regulators expression and relevant files

Table 1 A shows the example of regulator expression files. The first column must contain the identifier of the regulators. The remaining columns contain the quantification values for each sample in the experiment, preferably on a logarithmic scale. Table 1B shows an example of a relevant features file for regulators: a unique column containing the identifiers or names for all significant features in the experiment.

<div class="imageContainer" style="box-shadow: 0px 0px 20px #D0D0D0; text-align:center; font-size:10px; color:#898989" >
    <img src="paintomics_regulatory_omics_figure2.png"/>
    <p class="imageLegend"><b>Table 1: Example input for a regulators expression and relevant file </b> (A) contains the regulators name (first column) followed by the quantification values for 3 different time-points, in logarithmic scale. Differentially expressed regulators are provided as a list (B).</p>
</div>

### Association and relevant associaiton file

Table 2 shows the example of the association file. The first column contains the identifier of the regulators, and the second column contains the feature name of the targeted features (gene name/metabolite name). This information is usually extracted from popular databases such as miRbase for miRNAs. See above the accepted format for the file.

<div class="imageContainer" style="box-shadow: 0px 0px 20px #D0D0D0; text-align:center; font-size:10px; color:#898989" >
    <img src="paintomics_regulatory_omics_figure3.png"/>
    <p class="imageLegend"><b>Table 2: Example for association file </b> The first column is associated features, and the second column is the regulator.</p>
</div>

The relevant association file is a subset of the association file that could be directly uploaded by the user or automatically selected using correlation (the correlation between targeted features and regulators) in PaintOmics 4 (Figure 2B). 

<div class="imageContainer" style="box-shadow: 0px 0px 20px #D0D0D0; text-align:center; font-size:10px; color:#898989" >
    <img src="paintomics_regulatory_omics_figure5.png"/>
    <p class="imageLegend"><b>Figure 2: the relevant file upload panel (A) and relevant association file upload panel (B)</b></p>
</div>

### Regulatory omics visualisation

Figure 3A and 3B show the visualisation of the regulatory omics inside the pathway. The feature with a yellow star symbol indicates a relevant association between the feature and its regulators, and the feature with a red star symbol indicates that its regulators are significant.

<div class="imageContainer" style="box-shadow: 0px 0px 20px #D0D0D0; text-align:center; font-size:10px; color:#898989" >
    <img src="paintomics_regulatory_omics_figure4.png"/>
    <p class="imageLegend"><b>Figure 3: visualisation of the regulatory omics in the main panel (A) and auxiliary panel shows the expression of regulators of the feature (B)</b></p>
</div>

### Parameters

***Omic Name:*** The **Omic Mame** parameter allows the user to define the name of its regulators or select from PaintOmics 4 build-in drop-down menu. If the omic name is **Transcription factor**, the transcription factor will map to the PaintOmics databases to find its gene symbol.<br>
***Enrichment type:*** The **Enrichment type** parameter defines how PaintOmics 4 must do the Fisher contingency table: counting genes, features (i.e., microRNA, proteins...), or associations (combination of genes & features).<br>
***Score method:*** The **score method** parameter defines how PaintOmics 4 calculate correlations between targeted features and regulators (only available when the relevant association file is not provided). As an example in miRNA, usually, a single miRNA has multiple potential target genes, but a certain miRNA is regulating not all targets at a certain moment. Consequently, we need to discriminate the real targets for a miRNA.Suppose Gene expression (GE) data is available. In that case, we calculate the correlation between each miRNA and each target gene and filter out all those miRNAs that have a lower correlation value than a given threshold. If no GE is available, we filter based on the fold-change for the expression of the miRNAs.Default: 'Kendall correlation' if GE is available. 'Fold Change' in other cases.<br>






## The MORE joint model: choosing a regulatory model

When a regulatory omic is submitted through the **MORE** option, PaintOmics fits
one model per target feature, using the experimental design and that feature's
candidate regulators. Two statistical methods are available, and each can run on
either of two implementations, so the **Regulatory model** drop-down offers four
choices. The list shown is what *this* server can actually run: an option the
host is missing stays visible but greyed out, with the reason, rather than
disappearing.

| Regulatory model | Method | Implementation | When to choose it |
| --- | --- | --- | --- |
| **PLS1 — Rust engine** | PLS1 | Rust | The default. Recommended for almost everything. |
| **PLS1 — R engine** | PLS1 | R (MORE package) | To reproduce a published run against the reference implementation. |
| **MLR — R engine** | MLR | R (MORE package) | The reference for MLR. |
| **MLR — Rust engine** | MLR | Rust | MLR, roughly an order of magnitude faster — see the caveat below. |

### PLS1 or MLR?

**PLS1 is the better default, including for the reason most people pick MLR.**
The usual argument for multiple linear regression is that it returns real
p-values and interpretable effect sizes. In MORE that is not the case: the MLR
path reports a coefficient per regulator and no p-value at all, because a
regulator is "relevant" precisely when elastic-net shrinkage left its
coefficient non-zero. There is no stepwise selection anywhere in it. This is why
the **Alpha (significance)** and **VIP threshold** fields disappear when you
select an MLR model — neither applies.

PLS1, by contrast, produces both a VIP score and a jackknife p-value, and a
regulator is significant only when it passes both. Prefer MLR when you have many
more samples than candidate regulators per gene, which is the regime it suits.

### Rust engine or R engine?

The Rust engine is a reimplementation of MORE's modelling kernel. It is not a
different model — it is the same model, written to run faster and to work on
servers where the R package is not installed.

* **For PLS1 the two are byte-identical.** Every output file matches the R
  engine exactly on the bundled datasets, which is why the Rust engine is the
  default and is used without asking.

* **For MLR they agree on every decision, but not on the last digits.** MORE's
  MLR makes random draws — which of a group of correlated regulators represents
  that group, and how cross-validation folds are assigned — and the Rust engine
  reproduces R's random number generator exactly, so those choices come out the
  same. What differs is arithmetic: MORE runs the underlying solver at a
  tolerance where it has not fully converged, and at that tolerance the R engine
  does not reproduce itself either (simply presenting the same regulators in a
  different order changes its answer by more than the two engines differ from
  each other). On the bundled real dataset the two engines agree on 99.1% of the
  reported regulator–target pairs.

  Because of that, **MLR is never switched to the Rust engine on your behalf**.
  Choosing "MLR — R engine", or submitting a job that does not name an engine at
  all, always runs R. Pick the Rust engine deliberately when you want the speed;
  pick the R engine when you need to match numbers you have already published.

### If an option is greyed out

The R engines need the MORE R package installed on the server, and the Rust
engines need the `more-rs` binary. Where one is missing, its options are listed
but disabled and give the reason, so that a missing option reads as "not
installed here" rather than "does not exist". If you submit a job for an engine
this server cannot run, it is refused up front with the same explanation instead
of failing part-way through the analysis.

### A note on very large submissions

MORE fits one model per target feature, so its cost grows with the number of
genes, with the number of candidate regulators per gene, and with the size of
the experimental design. PaintOmics estimates the runtime before queueing and
refuses a submission it predicts cannot finish inside the queue's time limit,
explaining what to reduce, rather than letting it run and be killed at the end.
