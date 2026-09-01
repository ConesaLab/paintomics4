# Metagenes

A metagene is one profile that stands for a group of features that move
together. PaintOmics uses them in two places where there are more values than
there is room to draw: a pathway map node that holds many genes, and a pathway
node in the network view, where a whole pathway has to be summarised by a single
colour. This page explains what is computed, when, and how to read it.

A metagene is not a gene. It has no identifier in your data and no position of
its own in a pathway; it is a summary of the features that are already there.

## Where metagenes are computed

There are two levels, computed at different times by different code, and they do
not cover the same omics.

| | Pathway level | Node level |
| --- | --- | --- |
| Summarises | Every matched feature of one omic in one pathway | The features sharing one position on a pathway map |
| Computed | During Step 2, once per omic and per pathway database | In the browser, when you open a crowded box in Step 4 |
| Covers | **Gene-based omics only** | Every omic in the job |
| Appears in | The pathway network colouring and the *major trends* charts | The pathway diagram, behind the **Genes** / **Metagenes** toggle |

The pathway-level pass runs over the job's gene-based omics, so a compound-based
omic such as metabolomics never gets a pathway-level metagene and never appears
as a cluster colouring on the network. Node-level metagenes in Step 4 do cover
every omic in the box.

An omic that matched no feature at all is skipped rather than failing the run,
and so is a pathway or database whose data is too degenerate to cluster.

## How a metagene is computed

The values of the group are centred and reduced by principal component analysis.
The metagene is the component's score — the profile across conditions — and the
loadings say how much each feature contributed to it.

* **Not every component becomes a metagene.** A component is kept only while its
  explained variance passes a cutoff of 0.3. That is why a node or a pathway
  usually yields one or two trends rather than as many as it has features, and
  why some yield none at all.
* **The sign is corrected.** The sign of a principal component is arbitrary, so
  each metagene is flipped where necessary to follow the majority of its
  members' loadings. A metagene that goes up therefore means the features that
  built it mostly go up.

### With a single condition there is no PCA

One condition gives no direction of maximum variance across conditions, so
neither level runs a PCA:

* The pathway-level pass uses a **median centroid** of the pathway's members.
* The browser uses an **outlier-trimmed mean** of the box's members, dropping
  values more than three standard deviations from the mean.

The sign-orientation step is skipped in this regime, because there is no
arbitrary component sign to resolve. Single-condition jobs are also clustered
with a model-based clusterer in one dimension rather than with k-means, since
with one condition the amplitude *is* the profile.

## Pathway-level metagenes on the network

Open the pathway network on Step 3 and set **Node coloring** to an omic name
instead of Classification. Each pathway node is then coloured by the cluster its
metagene fell into, and the rail shows:

* the heading **N Clusters found from M in total** — the second number is every
  cluster the job produced, the first is how many still own a pathway that
  survived the filters you have applied;
* one thumbnail per cluster, plotting its member trends in grey with the cluster
  centroid in red, and captioned with how many metagenes it holds. Click a
  thumbnail to hide or show its nodes, so you can isolate the pathways that move
  together;
* **Modify number of clusters**, a slider from 1 to 20 with an **Apply** button.

By default PaintOmics chooses the number of clusters itself — an elbow scan for
k-means, or BIC for the model-based clusterer — and clamps it to the number of
distinguishable profiles the data actually holds. Asking for more than that
yields fewer than you asked for rather than an error: with only two conditions,
for instance, every centred profile lands on one of two points, and no amount of
sliding will produce more than two meaningful groups.

!!! note
    **Apply** re-runs the clustering as a queued job, and the panel says so: it
    is an intensive process and the results take time to come back. The slider
    is hidden on a job you are only viewing rather than one you own.

## Major trends in a pathway

Click a pathway node in the network, or a row in the pathway table, and the
details panel lists that pathway's metagenes for each omic — *N major trends in
this pathway* — with a **Heatmap** / **Line chart** toggle. The same panel
appears in the **Pathway information** column beside an open diagram in Step 4.

In the heatmap each row is one trend, labelled **Trend n** and the cluster it
belongs to. Where the pathway has no data for an omic the panel says **No data
for this pathway**.

!!! warning
    The colours in a trend chart are scaled to **the metagenes' own range**, not
    to the omic's. A metagene is a component centred on zero, so it goes negative
    whatever the omic did, and its magnitude is not in the omic's units — on a
    real job here an omic ran 0.79 to 1.41 while its metagenes reached ±9.4.
    Compare the *shape* of two trends, never the strength of a trend colour
    against the colour of a gene box.

When you switch the job to the averaged view, metagene charts are collapsed the
same way every other chart is, so a trend has one cell per condition and its
tooltip names the condition, instead of one cell per replicate.

## Node-level metagenes on a pathway diagram

Features bucket onto a map by their literal position, so co-located genes share
one drawn box. When a single position holds **more than five features**, the box
no longer paints one arbitrary member: PaintOmics computes metagenes for that
group in the browser and paints those instead. A box holding exactly five
features still paints an individual feature.

The feature window for such a box carries a **Genes** | **Metagenes** toggle in
its title bar — the only way back from the compressed view to the individual
features — and the **Prev.** / **Next** arrows step through the metagenes just
as they step through genes. The **N more … at this position** line says how many
are behind them.

Node-level metagenes are named in order: **Metagene 1**, **Metagene 2**, and so
on, within that box. The name is positional and means nothing outside the box it
was computed for. If the computation fails for any reason, the box falls back
silently to the ordinary single-feature display.

## Reading a metagene honestly

* A metagene is a **component, not a measurement**. Its units are not the omic's
  units, and two metagenes from different pathways or different boxes are not on
  a common scale.
* **Trend n** and **Metagene n** are positional labels. They are stable within
  one pathway or one box in one job; they carry no meaning between them, and
  re-clustering renumbers them.
* A cluster tells you that a set of pathways move alike for that omic. It says
  nothing about whether they are enriched — that is a separate test, described in
  [Pathway enrichment](4_1_pathway_enrichment.md).
* When you need the individual features, they are always still there: the
  **Genes** toggle in the feature window, and the per-feature charts described in
  [the detail views](5_2_detailed_views.md) and
  [heatmaps](5_3_heatmaps.md).

## Where to go next

* [The pathway network](4_3_pathways_network.md)
* [Reading a pathway diagram](5_1_browsing_pathways.md)
* [A whole job, step by step](8_step_by_step.md)
