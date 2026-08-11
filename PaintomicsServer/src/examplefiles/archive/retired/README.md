# Retired example files

Files pulled out of a shipped example scenario because they misrepresent what they contain.
Kept here rather than deleted so the reason survives with the evidence.

## `transcription_factor_{values,relevant}.tab`

Retired 2026-08-11 from `08-stategra-multiomics`, where they were the sixth "omic".

They are not a transcription-factor assay. Every one of the 2,889 value tuples appears verbatim in
that scenario's `gene_expression_values.tab` — a 1:1, order-preserving selection with the ENSMUSG ID
swapped for the MGI symbol:

```
$ comm -12 <(awk -F'\t' 'NR>1{print $2"\t"$3"\t"$4"\t"$5"\t"$6"\t"$7}' transcription_factor_values.tab | sort -u) \
           <(awk -F'\t' 'NR>1{print $2"\t"$3"\t"$4"\t"$5"\t"$6"\t"$7}' gene_expression_values.tab   | sort -u) | wc -l
    2889          # of 2889 rows
```

Three further facts agree:

* STATegra published no TF-expression time course. Its omics are DNase-seq, RRBS, ChIP-seq, RNA-seq,
  miRNA-seq, proteomics and metabolomics (Gomez-Cabrero et al., *Sci Data* 6:256, 2019).
* 2,889 features exceeds the entire mouse TF repertoire (~1,600 in AnimalTFDB).
* The pre-reorganisation source of this layer is `../original-dat/factor_expression_fake.txt`.

Shipping it as an independent layer scored the same measurements twice in every pathway statistic,
inside the one example scenario that advertises itself as real rather than simulated. Renaming it
would not have fixed that; only removing it does.

Its relevance list was separately broken: 1,862 of 2,403 entries had no values row, inherited from
the gene-expression subsetting.

Rebuilding a genuine TF layer for this dataset is a construction, not a retrieval — intersect
GSE75417 with a TF census. The real Ikaros ChIP data (SRP013344 / SRP017277) has two conditions and
cannot yield a six-timepoint ratio.
