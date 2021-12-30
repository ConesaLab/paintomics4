# Metabolite class activity analysis

Like the pathway enrichment analysis, the metabolite class activity analysis in PaintOmics 4 is for semi-targeted metabolomics, assessing the hypothesis that a targeted metabolic class is significantly activated. This approach seeks to solve the issue that the input metabolite data are insufficient to map to pathways, leading to a non-significant p-value in the pathway enrichment analysis part.

In metabolite class activity analysis, the input dataset maps to a list of metabolites classes. The proportion of relevant metabolites in each class is compared with the global proportion of relevant metabolites in the input dataset using the binomial test. All classes with significant differences in the binomial test are significantly activated (Figure 1).

<div class="imageContainer" style="box-shadow: 0px 0px 20px #D0D0D0; text-align:center; font-size:10px; color:#898989" >
    <img src="metabolite_class_activity_analysis_1.png"/>
    <p class="imageLegend"><b>Figure 1:</b> An example of metabolite class activity analysis in PaintOmics 4</p>
</div>

