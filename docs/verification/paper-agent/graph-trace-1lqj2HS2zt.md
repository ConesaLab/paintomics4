# JobGraph run trace — job 1lqj2HS2zt (STATegra mouse, MORE)

Built by `job_graph.from_job` on 2026-08-23; evidence classified job-wide against the installed interaction sources.

## graph_schema

```
JOB GRAPH SCHEMA
nodes: gene 1220 [f1], regulator 210 [f2], pathway 60 [f3]
edges: REGULATES 1562 [f4], MEMBER_OF 594 [f5], KGML 3238 [f6], SIMILAR_TO 300 [f7]
REGULATES evidence: supported 242 [f8], novel 795 [f9], unsupported 525 [f10]
conditions: Ctr_0H, Ctr_2H, Ctr_6H, Ctr_12H, Ctr_18H, Ctr_24H, Ik_0H, Ik_2H, Ik_6H, Ik_12H, Ik_18H, Ik_24H
  REGULATES (props: coefficient, condition, coef_by_condition, target_r2, omic, area, evidence, support) e.g. Esr1 -> ENSMUSG00000000031; Esr1 -> ENSMUSG00000002985; Esr1 -> ENSMUSG00000004040
  MEMBER_OF (props: -) e.g. Smad3 -> mmu05210; Smad3 -> mmu04933; Smad3 -> mmu05226
  KGML (props: relation_type, pathway_id) e.g. Esr1 -> Ncoa3; Esr1 -> Med1; Esr1 -> Prkaca
  SIMILAR_TO (props: shared_features, jaccard) e.g. mmu05167 -> mmu05210; mmu05167 -> mmu05224; mmu05167 -> mmu05216
note: no compound layer; no NEIGHBOUR_OF edges
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.)
```

## graph_hubs (regulators by REGULATES degree)

```
HUBS: regulator by REGULATES degree
  Dand5: 152 target(s) [f11], mean |coef| 0.44 [f12] (unsupported 152)
  Jun: 91 target(s) [f13], mean |coef| 0.44 [f14] (novel 54, supported 22, unsupported 15)
  Myc: 58 target(s) [f15], mean |coef| 0.66 [f16] (novel 32, supported 16, unsupported 10)
  Ets1: 56 target(s) [f17], mean |coef| 0.67 [f18] (novel 39, supported 7, unsupported 10)
  Egr1: 50 target(s) [f19], mean |coef| 0.60 [f20] (novel 44, supported 3, unsupported 3)
  Stat3: 49 target(s) [f21], mean |coef| 0.56 [f22] (novel 25, supported 19, unsupported 5)
  Hif1a: 38 target(s) [f23], mean |coef| 0.40 [f24] (novel 20, supported 16, unsupported 2)
  Myb: 34 target(s) [f25], mean |coef| 0.66 [f26] (novel 29, supported 2, unsupported 3)
  Ep300: 31 target(s) [f27], mean |coef| 0.59 [f28] (novel 20, supported 9, unsupported 2)
  Nfe2l2: 29 target(s) [f29], mean |coef| 0.46 [f30] (novel 20, supported 6, unsupported 3)
  Smad3: 28 target(s) [f31], mean |coef| 0.72 [f32] (novel 16, supported 7, unsupported 5)
  Esr1: 26 target(s) [f33], mean |coef| 0.36 [f34] (novel 15, supported 8, unsupported 3)
  Etv4: 25 target(s) [f35], mean |coef| 0.74 [f36] (unsupported 25)
  Runx2: 24 target(s) [f37], mean |coef| 0.73 [f38] (novel 18, supported 2, unsupported 4)
  Usf1: 23 target(s) [f39], mean |coef| 0.96 [f40] (novel 17, unsupported 6)
  ... 195 more not shown
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.)
```

## graph_filter: supported and strong

```
FILTER 'type == REGULATES and abs(coef) > 1 and evidence == supported': 15 edge(s) [f41]
  Smad3 -> ENSMUSG00000025358 [REGULATES; coef 2.41 [f42] at Ik_2H, target R2 0.91 [f43]; supported]
  Stat3 -> ENSMUSG00000024962 [REGULATES; coef -2.11 [f44] at Ik_6H, target R2 0.92 [f45]; supported]
  Egr1 -> ENSMUSG00000015605 [REGULATES; coef 1.96 [f46] at Ctr_2H, target R2 0.90 [f47]; supported]
  Nfe2l2 -> ENSMUSG00000008540 [REGULATES; coef -1.89 [f48] at Ctr_18H, target R2 0.81 [f49]; supported]
  Esr1 -> ENSMUSG00000050965 [REGULATES; coef 1.89 [f50] at Ik_6H, target R2 0.85 [f51]; supported]
  Srebf1 -> ENSMUSG00000025153 [REGULATES; coef -1.67 [f52] at Ctr_18H, target R2 0.66 [f53]; supported]
  Xbp1 -> ENSMUSG00000020715 [REGULATES; coef -1.57 [f54] at Ctr_12H, target R2 0.91 [f55]; supported]
  Hif1a -> ENSMUSG00000026773 [REGULATES; coef 1.22 [f56] at Ctr_18H, target R2 0.95 [f57]; supported]
  Myc -> ENSMUSG00000044303 [REGULATES; coef -1.19 [f58] at Ik_18H, target R2 0.78 [f59]; supported]
  Ets1 -> ENSMUSG00000044303 [REGULATES; coef 1.19 [f60] at Ik_18H, target R2 0.78 [f61]; supported]
  Ccnd1 -> ENSMUSG00000044303 [REGULATES; coef -1.19 [f62] at Ik_18H, target R2 0.78 [f63]; supported]
  Jun -> ENSMUSG00000026728 [REGULATES; coef -1.14 [f64] at Ctr_18H, target R2 0.92 [f65]; supported]
  Jun -> ENSMUSG00000015839 [REGULATES; coef -1.13 [f66] at Ctr_2H, target R2 0.94 [f67]; supported]
  Hif1a -> ENSMUSG00000062070 [REGULATES; coef 1.13 [f68] at Ik_2H, target R2 0.78 [f69]; supported]
  Myc -> ENSMUSG00000063524 [REGULATES; coef 1.02 [f70] at Ik_0H, target R2 0.92 [f71]; supported]
```

## graph_subgraph: mmu05167 (Kaposi sarcoma-associated herpesvirus infection)

```
SUBGRAPH of mmu05167 (Kaposi sarcoma-associated herpesvirus infection): 10 member(s), 665 edge(s) of KGML/REGULATES
  regulators 2; evidence novel 21, supported 14, unsupported 5; sign +22/-18
  Jun -> ENSMUSG00000015812 [coef 2.78 at Ctr_24H, target R2 0.96; novel]
  Myc -> ENSMUSG00000020857 [coef -1.79 at Ik_18H, target R2 0.67; novel]
  Myc -> ENSMUSG00000024833 [coef 1.65 at Ik_12H, target R2 0.82; novel]
  Myc -> ENSMUSG00000036856 [coef -1.49 at Ik_12H, target R2 0.90; novel]
  Myc -> ENSMUSG00000044303 [coef -1.19 at Ik_18H, target R2 0.78; supported]
  Jun -> ENSMUSG00000026728 [coef -1.14 at Ctr_18H, target R2 0.92; supported]
  Jun -> ENSMUSG00000015839 [coef -1.13 at Ctr_2H, target R2 0.94; supported]
  Jun -> ENSMUSG00000006005 [coef -1.07 at Ik_0H, target R2 0.89; novel]
  Myc -> ENSMUSG00000063524 [coef 1.02 at Ik_0H, target R2 0.92; supported]
  Myc -> ENSMUSG00000026234 [coef 0.99 at Ik_2H, target R2 0.93; unsupported]
  Myc -> ENSMUSG00000021144 [coef 0.98 at Ik_18H, target R2 0.84; novel]
  Myc -> ENSMUSG00000021116 [coef 0.98 at Ik_12H, target R2 0.86; novel]
  Myc -> ENSMUSG00000011179 [coef 0.93 at Ik_2H, target R2 0.99; novel]
  Myc -> ENSMUSG00000006215 [coef -0.93 at Ik_2H, target R2 0.80; supported]
  Myc -> ENSMUSG00000046711 [coef -0.91 at Ik_2H, target R2 0.90; novel]
  Myc -> ENSMUSG00000021611 [coef -0.91 at Ctr_2H, target R2 0.86; supported]
  Myc -> ENSMUSG00000045482 [coef 0.89 at Ik_2H, target R2 0.84; novel]
  Myc -> ENSMUSG00000055612 [coef 0.89 at Ik_2H, target R2 0.98; unsupported]
  Jun -> ENSMUSG00000038615 [coef 0.89 at Ctr_0H, target R2 0.87; unsupported]
  Myc -> ENSMUSG00000013629 [coef 0.88 at Ctr_0H, target R2 0.97; supported]
  Jun -> ENSMUSG00000005413 [coef 0.88 at Ctr_0H, target R2 0.97; supported]
  Myc -> ENSMUSG00000005054 [coef -0.85 at Ik_2H, target R2 0.83; unsupported]
  Jun -> ENSMUSG00000037868 [coef 0.84 at Ctr_24H, target R2 0.87; novel]
  Myc -> ENSMUSG00000030268 [coef 0.83 at Ctr_24H, target R2 0.99; novel]
  Myc -> ENSMUSG00000057113 [coef 0.82 at Ik_2H, target R2 0.81; supported]
  Jun -> ENSMUSG00000038780 [coef -0.81 at Ik_12H, target R2 0.99; novel]
  Myc -> ENSMUSG00000028156 [coef 0.80 at Ik_2H, target R2 0.97; supported]
  Myc -> ENSMUSG00000002325 [coef -0.77 at Ik_12H, target R2 0.63; novel]
  Myc -> ENSMUSG00000020534 [coef 0.77 at Ctr_0H, target R2 0.98; novel]
  Jun -> ENSMUSG00000027187 [coef -0.73 at Ctr_12H, target R2 0.95; novel]
  Jun -> ENSMUSG00000058135 [coef -0.73 at Ctr_2H, target R2 0.97; novel]
  Jun -> ENSMUSG00000002983 [coef -0.72 at Ctr_18H, target R2 0.71; novel]
  Myc -> ENSMUSG00000003923 [coef 0.72 at Ik_2H, target R2 0.71; novel]
  Myc -> ENSMUSG00000027405 [coef 0.71 at Ik_0H, target R2 0.96; novel]
  Jun -> ENSMUSG00000024401 [coef -0.70 at Ctr_0H, target R2 0.91; supported]
  Myc -> ENSMUSG00000044786 [coef -0.70 at Ik_6H, target R2 0.77; novel]
  Jun -> ENSMUSG00000000184 [coef -0.70 at Ik_18H, target R2 0.98; supported]
  Myc -> ENSMUSG00000000184 [coef 0.70 at Ik_18H, target R2 0.98; supported]
  Myc -> ENSMUSG00000032477 [coef 0.70 at Ctr_0H, target R2 0.75; supported]
  Jun -> ENSMUSG00000023169 [coef 0.68 at Ik_6H, target R2 0.77; unsupported]
  ... 625 more not shown (readable budget; ranked by |coef|)
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.)
```

## graph_evidence: Esr1 -> ENSMUSG00000004040

```
EVIDENCE Esr1 -> ENSMUSG00000004040
  coefficients: Ctr_0H -0.01 [f1], Ctr_2H -0.01 [f2], Ctr_6H -0.42 [f3], Ctr_12H -0.28 [f4], Ctr_18H -0.31 [f5], Ctr_24H -0.32 [f6], Ik_0H -0.20 [f7], Ik_2H -0.01 [f8], Ik_6H -0.45 [f9], Ik_12H -0.01 [f10], Ik_18H -0.01 [f11], Ik_24H -0.01 [f12]
  omic Transcription_factor; area ; evidence supported (KEGG)
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.) MLR reports no p-values.
```

## graph_neighbors: Esr1 (out, REGULATES)

```
NEIGHBOURS of Esr1 (depth 1, 26 edge(s) [f13])
  Esr1 -> ENSMUSG00000050965  [REGULATES; coef 1.89 [f14] at Ik_6H, target R2 0.85 [f15]; evidence supported]
  Esr1 -> ENSMUSG00000020184  [REGULATES; coef -1.36 [f16] at Ik_12H, target R2 0.91 [f17]; evidence novel]
  Esr1 -> ENSMUSG00000004043  [REGULATES; coef -0.69 [f18] at Ik_12H, target R2 0.66 [f19]; evidence supported]
  Esr1 -> ENSMUSG00000041313  [REGULATES; coef 0.68 [f20] at Ctr_2H, target R2 0.92 [f21]; evidence novel]
  Esr1 -> ENSMUSG00000030036  [REGULATES; coef 0.50 [f22] at Ctr_2H, target R2 0.97 [f23]; evidence novel]
  Esr1 -> ENSMUSG00000004040  [REGULATES; coef -0.45 [f24] at Ik_6H, target R2 0.96 [f25]; evidence supported]
  Esr1 -> ENSMUSG00000038615  [REGULATES; coef 0.44 [f26] at Ctr_2H, target R2 0.87 [f27]; evidence unsupported]
  Esr1 -> ENSMUSG00000024955  [REGULATES; coef -0.31 [f28] at Ik_12H, target R2 0.80 [f29]; evidence unsupported]
  Esr1 -> ENSMUSG00000023067  [REGULATES; coef 0.31 [f30] at Ik_6H, target R2 0.93 [f31]; evidence novel]
  Esr1 -> ENSMUSG00000005886  [REGULATES; coef -0.29 [f32] at Ctr_6H, target R2 0.88 [f33]; evidence supported]
  Esr1 -> ENSMUSG00000002985  [REGULATES; coef -0.28 [f34] at Ctr_2H, target R2 0.93 [f35]; evidence novel]
  Esr1 -> ENSMUSG00000041417  [REGULATES; coef -0.25 [f36] at Ctr_6H, target R2 0.88 [f37]; evidence supported]
  Esr1 -> ENSMUSG00000015243  [REGULATES; coef 0.23 [f38] at Ik_0H, target R2 0.97 [f39]; evidence novel]
  Esr1 -> ENSMUSG00000035778  [REGULATES; coef -0.22 [f40] at Ctr_6H, target R2 0.77 [f41]; evidence novel]
  Esr1 -> ENSMUSG00000023951  [REGULATES; coef -0.17 [f42] at Ik_18H, target R2 0.94 [f43]; evidence novel]
  Esr1 -> ENSMUSG00000058440  [REGULATES; coef 0.16 [f44] at Ctr_18H, target R2 0.86 [f45]; evidence novel]
  Esr1 -> ENSMUSG00000038418  [REGULATES; coef -0.16 [f46] at Ik_12H, target R2 0.95 [f47]; evidence novel]
  Esr1 -> ENSMUSG00000022015  [REGULATES; coef 0.15 [f48] at Ik_0H, target R2 0.78 [f49]; evidence novel]
  Esr1 -> ENSMUSG00000032312  [REGULATES; coef 0.14 [f50] at Ik_18H, target R2 0.54 [f51]; evidence novel]
  Esr1 -> ENSMUSG00000000031  [REGULATES; coef -0.13 [f52] at Ik_12H, target R2 0.44 [f53]; evidence unsupported]
  ... 6 more not shown (top_k=20, ranked |coef| then evidence)
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.)
```

## graph_path: Esr1 -> ENSMUSG00000004043

```
PATHS Esr1 -> ENSMUSG00000004043 (4 shown, shortest first)
  Esr1 -[REGULATES(supported)]- ENSMUSG00000004043
  Esr1 -[REGULATES(supported)]- ENSMUSG00000021250; ENSMUSG00000021250 -[REGULATES(novel)]- Ep300; Ep300 -[REGULATES(supported)]- ENSMUSG00000004043
  Esr1 -[REGULATES(novel)]- ENSMUSG00000023067; ENSMUSG00000023067 -[REGULATES(supported)]- Ep300; Ep300 -[REGULATES(supported)]- ENSMUSG00000004043
  Esr1 -[REGULATES(supported)]- ENSMUSG00000070348; ENSMUSG00000070348 -[REGULATES(supported)]- Ep300; Ep300 -[REGULATES(supported)]- ENSMUSG00000004043
```

Facts ledger after this trace: 53 registered numbers (counts, coefficients, R2), each shown beside its value above.
