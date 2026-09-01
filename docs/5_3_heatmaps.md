# Heatmaps

The **Global heatmap** panel draws every feature of the open pathway as a
heatmap, one block per omic, so you can read the whole pathway as a matrix
instead of hunting for painted boxes on the map. Open it with **Show Heatmap**
in the pathway view's toolbar; see [the pathway view](5_1_browsing_pathways.md)
for the toolbar and for the diagram itself, and
[Feature details](5_2_detailed_views.md) for the charts behind a single box.

The panel takes the same slot as the **Feature set overview**, so opening one
closes the other. Its header carries hide, configure (the cogs), expand and
shrink controls, and its left edge can be dragged to widen it.

## Choosing what to draw

The configurator is open when the panel first appears, and nothing is drawn
until you press **Apply**. The cogs icon reopens it later; it slides shut again
each time a drawing finishes.

Under **Choose the omics to draw** there is one entry per omic that has at
least one matched feature in this pathway — an omic that matched nothing here
is not offered. Each entry has:

| Control | What it does |
|---|---|
| The checkbox | Whether this omic gets a heatmap at all. All are ticked to begin with. |
| **All features (Genes or compounds)** | Draw a row for every feature of this pathway that this omic measured. |
| **Only relevant features** | Draw only the rows that are relevant, or that carry a relevant association, for this omic. This is the initial choice. |
| The numbered handle | Drag the entry up or down to change the order the heatmaps are drawn in. The numbers renumber as you drop. |

The order matters for more than layout: with **Force order for features**
switched on, the omic at the top of the list is the one every other heatmap
follows.

An omic with nothing left to draw — **Only relevant features** chosen and
nothing relevant in this pathway — shows "No data" in place of its heatmap.

## Advanced options

!!! note "This can take up to ten seconds"
    The panel warns you here in its own words: depending on the settings
    chosen, generating the heatmaps can take up to ten seconds. A pathway with
    hundreds of matched features, several omics and clustering switched on is
    the slow case; **Only relevant features** is the fast one.

### Force order for features

Off by default. Each heatmap is then clustered and ordered on its own, and the
row at a given height in one omic has nothing to do with the row at that height
in the next.

Switched on, only the first omic in the list is ordered. Every other heatmap is
redrawn in that omic's row order, so a row sits at the same height in all of
them and a profile can be followed straight across. Two consequences follow
from that, and both are visible on screen:

* A feature the reference omic has but a secondary omic does not still gets a
  row there, drawn empty and labelled **NO DATA**, to keep the rows aligned.
* A secondary omic will draw a row that is *not* relevant for it, if the
  reference omic contributed that row. The shared order takes precedence over
  that omic's **Only relevant features** setting.

### Show per-condition significance stars

On by default. A star on a cell means the feature is relevant for that
condition — that your relevant-features file listed it there. The star's ink is
chosen against the cell's own colour so it stays legible on the pale middle of
the scale.

Two limits are worth knowing. Stars are only drawn when the omic has more than
one column, and a relevant-features file that is a single column of identifiers
means "relevant overall": it produces no per-cell stars anywhere, only the star
in the row label. Per-condition stars need a
[per-condition relevance file](2_1_accepted_input.md), one column per value
column. Turning the checkbox off is useful when a heatmap is dense enough that
the stars fight with the colours.

### Clusterize data

On by default, with **Hierarchical clustering** selected. Clustering is
skipped, whatever the setting, for a heatmap with fewer than three rows.

**Hierarchical clustering** groups the rows and draws a dendrogram to the right
of the heatmap. The tree is computed on the rows themselves: each row is the
vector of values you can see in it — one number per column, in the
replicate/sample mode currently selected — compared by euclidean distance and
merged by complete linkage. The leaves are reordered so that similar profiles
end up adjacent, which is what makes blocks of common behaviour visible.

Read the dendrogram for its *grouping*, not for its distances. Branches are
drawn one step per level of the tree, so the horizontal position of a join
records its depth in the tree, not how far apart the two groups were.

**K-means clustering** partitions the rows into k groups instead, and marks
them with a numbered coloured bar down the right-hand side, one per cluster,
rather than a dendrogram. A box appears per omic so you can set its own k. The
bar colours are generated per drawing and mean nothing beyond "these rows are
in the same cluster"; they are not stable between redraws.

## Reading a heatmap

**Rows.** The label is the feature's symbol with its KEGG identifier on the
first line and the identifier you uploaded on the second. A long label is
shortened from the end that carries least: the symbol keeps its beginning, the
uploaded identifier keeps its ending, which is where identifiers that share a
prefix differ. Hover the label for both in full. A red star marks a relevant
feature and a gold star a relevant association.

For an omic uploaded with associations — transcription factors, miRNAs,
methylation, anything using the `target:::regulator` input form — the two lines
are swapped: the row is identified by the **regulator**, with the target
underneath. It is the inverse of an ordinary omic, where the row is the gene.
See [Regulatory omics](4_6_Regulatory_omics.md).

**Hovering a row** outlines the same feature's row in every other omic's
heatmap, which is the quickest way to ask whether a gene that moves in the
transcriptome moves in the proteome too. The linkage follows the target, so a
regulator row lights up with its target's gene-expression row.

**Columns** are labelled with the condition names from that omic's own file
header, rotated and length-capped, with the full name in the cell tooltip.
Where the header cannot be matched to the columns being drawn, the labels fall
back to "Condition 1", "Condition 2" and so on rather than risk naming a column
wrongly.

**Colours** come from the same settings as the painted diagram: each omic is
coloured against its own reference range, chosen in the **Settings** panel, and
a legend under each omic heading shows the two ends of that range, a tick at
zero where the range crosses it, and a caption naming the reference in words —
"10th-90th percentile" by default. Changing a colour setting and pressing
**Apply** in **Settings** repaints this panel along with the diagram. On the
default Blue-Grey-Red scale a value past either end of the range is painted
darker rather than clipped, so an extreme value still reads as extreme.

## What this panel does not do

There is no download here: the heatmaps cannot be exported as an image or as a
table, and the only export in the pathway view is the diagram's own **Download**
button, which writes a PNG of the map. If you need the numbers themselves, they
are in the files you uploaded, and the matched feature lists are in the
**Pathway information** panel.
