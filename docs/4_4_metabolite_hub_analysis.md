<div class="imageContainer" style="" >
    <img src="paintomics_150x690.png" title="Paintomics LOGO." style=" height: 70px !important; margin-bottom: 20px; ">
</div>

# Metabolite Hub Analysis

Metabolite hub analysis finds differentially expressed metabolite (DEM) with a high percentage of differentially expressed gene (DEG) neighbors. Hub metabolites usually play a significant role in the biological network, so it is essential to detect them(7). PaintOmics 4 conducts metabolite hub analysis based on the KEGG pathways and provides a user-friendly visualization interface of the result.

<div class="imageContainer" style="box-shadow: 0px 0px 20px #D0D0D0; text-align:center; font-size:10px; color:#898989" >
    <img src="metabolite_hub_analysis_figure_1.png"/>
    <p class="imageLegend"><b>Figure 1:</b> The one-step means no other nodes between node 1 (analysis metabolite) and node 2 (means that node 1 is directly connected to node 2). The two steps allow one gap (node 2) between node 1 (analysis metabolite) and node 3. Therefore, with a higher step number, more nodes will be connected to the analysis metabolite.</p>
</div>

In the database installation step, Paintomics 4 extracted the relationship between each metabolite and their neighbors across total pathways in the KEGG database for a given number of steps (typically 4) and generated a JSON file containing such information (Figure 1). 

<div class="imageContainer" style="box-shadow: 0px 0px 20px #D0D0D0; text-align:center; font-size:10px; color:#898989" >
    <img src="metabolite_hub_analysis_figure_2"/>
    <p class="imageLegend"><b>Figure 2:</b> the method reaveals metabolite hotspot that accumulate a high umber of significant genes in their neighboring metabolic network</p>
</div>

In the installation step, we extracted the connection between each KEGG metabolite and its gene neighbors in different KEGG pathways and generating an R data file. In the analysis part, PaintOmics 4 will test the distribution of % DEG neighbors for all metabolites in KEGG. The 95th percentile percentage of the distribution is the threshold for the hub metabolite. All DEM with % DEG neighbors higher than the threshold is considered hub metabolites. In the result visualization part, PaintOmics 4 can represent all neighbor genes. In addition, those genes and metabolites can quickly analyze inside the pathways(Figure 2).