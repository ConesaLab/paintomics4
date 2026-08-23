# JobGraph run trace — job 1lqj2HS2zt (STATegra mouse, MORE)

Built by `job_graph.from_job` on 2026-08-23; evidence classified job-wide against the installed interaction sources (KEGG, Reactome, OmniPath).

## graph_schema

```
JOB GRAPH SCHEMA
nodes: gene 847 [f1], regulator 210 [f2], pathway 60 [f3]
edges: REGULATES 1559 [f4], MEMBER_OF 594 [f5], KGML 3238 [f6], OMNIPATH 2236 [f7], SIMILAR_TO 300 [f8]
REGULATES evidence: supported 242 [f9], novel 795 [f10], unsupported 522 [f11]
conditions: Ctr_0H, Ctr_2H, Ctr_6H, Ctr_12H, Ctr_18H, Ctr_24H, Ik_0H, Ik_2H, Ik_6H, Ik_12H, Ik_18H, Ik_24H
  REGULATES (props: coefficient, condition, coef_by_condition, target_r2, omic, area, evidence, support) e.g. Esr1 -> H19; Esr1 -> Apoe; Esr1 -> Stat3
  MEMBER_OF (props: -) e.g. Smad3 -> mmu05210; Smad3 -> mmu04933; Smad3 -> mmu05226
  KGML (props: relation_type, pathway_id) e.g. Esr1 -> Stat3; Esr1 -> Stat5a; Esr1 -> Fos
  OMNIPATH (props: sources, references) e.g. Esr1 -> Ncoa2; Esr1 -> Myc; Esr1 -> Pik3r1
  SIMILAR_TO (props: shared_features, jaccard) e.g. mmu05167 -> mmu05210; mmu05167 -> mmu05224; mmu05167 -> mmu05216
note: no compound layer; no NEIGHBOUR_OF edges
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.)
```

## graph_hubs (regulators by REGULATES degree)

```
HUBS: regulator by REGULATES degree
  Dand5: 152 target(s) [f12], mean |coef| 0.44 [f13] (unsupported 152)
  Jun: 91 target(s) [f14], mean |coef| 0.44 [f15] (novel 54, supported 22, unsupported 15)
  Myc: 58 target(s) [f16], mean |coef| 0.66 [f17] (novel 32, supported 16, unsupported 10)
  Ets1: 56 target(s) [f18], mean |coef| 0.67 [f19] (novel 39, supported 7, unsupported 10)
  Egr1: 50 target(s) [f20], mean |coef| 0.60 [f21] (novel 44, supported 3, unsupported 3)
  Stat3: 48 target(s) [f22], mean |coef| 0.57 [f23] (novel 24, supported 19, unsupported 5)
  Hif1a: 38 target(s) [f24], mean |coef| 0.40 [f25] (novel 20, supported 16, unsupported 2)
  Myb: 34 target(s) [f26], mean |coef| 0.66 [f27] (novel 29, supported 2, unsupported 3)
  Ep300: 31 target(s) [f28], mean |coef| 0.59 [f29] (novel 20, supported 9, unsupported 2)
  Nfe2l2: 29 target(s) [f30], mean |coef| 0.46 [f31] (novel 20, supported 6, unsupported 3)
  Smad3: 28 target(s) [f32], mean |coef| 0.72 [f33] (novel 17, supported 7, unsupported 4)
  Esr1: 26 target(s) [f34], mean |coef| 0.36 [f35] (novel 16, supported 8, unsupported 2)
  Etv4: 25 target(s) [f36], mean |coef| 0.74 [f37] (unsupported 25)
  Runx2: 24 target(s) [f38], mean |coef| 0.73 [f39] (novel 18, supported 2, unsupported 4)
  Usf1: 23 target(s) [f40], mean |coef| 0.96 [f41] (novel 17, unsupported 6)
  ... 195 more not shown
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.)
```

## graph_filter: supported and strong

```
FILTER 'type == REGULATES and abs(coef) > 1 and evidence == supported': 15 edge(s) [f42]
  Smad3 -> Cdk2 [REGULATES; coef 2.41 [f43] at Ik_2H, target R2 0.91 [f44]; supported]
  Stat3 -> Vegfb [REGULATES; coef -2.11 [f45] at Ik_6H, target R2 0.92 [f46]; supported]
  Egr1 -> Srf [REGULATES; coef 1.96 [f47] at Ctr_2H, target R2 0.90 [f48]; supported]
  Nfe2l2 -> Mgst1 [REGULATES; coef -1.89 [f49] at Ctr_18H, target R2 0.81 [f50]; supported]
  Esr1 -> Prkca [REGULATES; coef 1.89 [f51] at Ik_6H, target R2 0.85 [f52]; supported]
  Srebf1 -> Fasn [REGULATES; coef -1.67 [f53] at Ctr_18H, target R2 0.66 [f54]; supported]
  Xbp1 -> Ern1 [REGULATES; coef -1.57 [f55] at Ctr_12H, target R2 0.91 [f56]; supported]
  Hif1a -> Pfkfb3 [REGULATES; coef 1.22 [f57] at Ctr_18H, target R2 0.95 [f58]; supported]
  Myc -> Cdkn2a [REGULATES; coef -1.19 [f59] at Ik_18H, target R2 0.78 [f60]; supported]
  Ets1 -> Cdkn2a [REGULATES; coef 1.19 [f61] at Ik_18H, target R2 0.78 [f62]; supported]
  Ccnd1 -> Cdkn2a [REGULATES; coef -1.19 [f63] at Ik_18H, target R2 0.78 [f64]; supported]
  Jun -> Vim [REGULATES; coef -1.14 [f65] at Ctr_18H, target R2 0.92 [f66]; supported]
  Jun -> Nfe2l2 [REGULATES; coef -1.13 [f67] at Ctr_2H, target R2 0.94 [f68]; supported]
  Hif1a -> Pgk1 [REGULATES; coef 1.13 [f69] at Ik_2H, target R2 0.78 [f70]; supported]
  Myc -> Eno1 [REGULATES; coef 1.02 [f71] at Ik_0H, target R2 0.92 [f72]; supported]
```

## graph_subgraph: mmu05167

```
SUBGRAPH of mmu05167 (Kaposi sarcoma-associated herpesvirus infection): 10 member(s), 731 edge(s) [f73] of KGML/REGULATES
  regulators 12; evidence novel 21, supported 13, unsupported 6; sign +22/-18
  Jun -> Gnrh1 [coef 2.78 [f74] at Ctr_24H, target R2 0.96 [f75]; novel]
  Myc -> Nme2 [coef -1.79 [f76] at Ik_18H, target R2 0.67 [f77]; novel]
  Myc -> Pola2 [coef 1.65 [f78] at Ik_12H, target R2 0.82 [f79]; novel]
  Myc -> Wnt4 [coef -1.49 [f80] at Ik_12H, target R2 0.90 [f81]; novel]
  Myc -> Cdkn2a [coef -1.19 [f82] at Ik_18H, target R2 0.78 [f83]; supported]
  Jun -> Vim [coef -1.14 [f84] at Ctr_18H, target R2 0.92 [f85]; supported]
  Jun -> Nfe2l2 [coef -1.13 [f86] at Ctr_2H, target R2 0.94 [f87]; supported]
  Jun -> Tpr [coef -1.07 [f88] at Ik_0H, target R2 0.89 [f89]; novel]
  Myc -> Eno1 [coef 1.02 [f90] at Ik_0H, target R2 0.92 [f91]; supported]
  Myc -> Nucleolin [coef 0.99 [f92] at Ik_2H, target R2 0.93 [f93]; unsupported]
  Myc -> Mta1 [coef 0.98 [f94] at Ik_18H, target R2 0.84 [f95]; novel]
  Myc -> Eif2s1 [coef 0.98 [f96] at Ik_12H, target R2 0.86 [f97]; novel]
  Myc -> Odc1 [coef 0.93 [f98] at Ik_2H, target R2 0.99 [f99]; novel]
  Myc -> Zbtb17 [coef -0.93 [f100] at Ik_2H, target R2 0.80 [f101]; supported]
  Myc -> Hmga1 [coef -0.91 [f102] at Ik_2H, target R2 0.90 [f103]; novel]
  Myc -> Tert [coef -0.91 [f104] at Ctr_2H, target R2 0.86 [f105]; supported]
  Myc -> Trrap [coef 0.89 [f106] at Ik_2H, target R2 0.84 [f107]; novel]
  Myc -> Cdca7 [coef 0.89 [f108] at Ik_2H, target R2 0.98 [f109]; unsupported]
  Jun -> Nfe2l1 [coef 0.89 [f110] at Ctr_0H, target R2 0.87 [f111]; unsupported]
  Myc -> Cad [coef 0.88 [f112] at Ctr_0H, target R2 0.97 [f113]; supported]
  Jun -> Hmox1 [coef 0.88 [f114] at Ctr_0H, target R2 0.97 [f115]; supported]
  Stat3 -> Myc [coef -0.85 [f116] at Ctr_0H, target R2 0.97 [f117]; supported]
  Ets1 -> Myc [coef -0.85 [f118] at Ctr_0H, target R2 0.97 [f119]; novel]
  Bcl6 -> Myc [coef -0.85 [f120] at Ctr_0H, target R2 0.97 [f121]; novel]
  Ikzf1 -> Myc [coef -0.85 [f122] at Ctr_0H, target R2 0.97 [f123]; unsupported]
  Tcf4 -> Myc [coef -0.85 [f124] at Ctr_0H, target R2 0.97 [f125]; supported]
  Rel -> Myc [coef -0.85 [f126] at Ctr_0H, target R2 0.97 [f127]; novel]
  Myc -> Cstb [coef -0.85 [f128] at Ik_2H, target R2 0.83 [f129]; unsupported]
  Jun -> Egr2 [coef 0.84 [f130] at Ctr_24H, target R2 0.87 [f131]; novel]
  Myc -> Bcat1 [coef 0.83 [f132] at Ctr_24H, target R2 0.99 [f133]; novel]
  Myc -> Npm1 [coef 0.82 [f134] at Ik_2H, target R2 0.81 [f135]; supported]
  Stat3 -> Tcf7l2 [coef 0.82 [f136] at Ik_0H, target R2 0.91 [f137]; novel]
  Sox4 -> Tcf7l2 [coef 0.82 [f138] at Ik_0H, target R2 0.91 [f139]; novel]
  Jun -> Smurf1 [coef -0.81 [f140] at Ik_12H, target R2 0.99 [f141]; novel]
  Myc -> Eif4e [coef 0.80 [f142] at Ik_2H, target R2 0.97 [f143]; supported]
  Myc -> Irf9 [coef -0.77 [f144] at Ik_12H, target R2 0.63 [f145]; novel]
  Fos -> Jun [coef 0.77 [f146] at Ik_12H, target R2 0.95 [f147]; supported]
  Myc -> Shmt1 [coef 0.77 [f148] at Ctr_0H, target R2 0.98 [f149]; novel]
  Smad3 -> Ctnnb1 [coef 0.74 [f150] at Ctr_0H, target R2 0.85 [f151]; novel]
  Zbtb33 -> Ctnnb1 [coef 0.74 [f152] at Ctr_0H, target R2 0.85 [f153]; unsupported]
  ... 691 more not shown (readable budget; ranked by |coef|)
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.)
```

## graph_evidence: Esr1 -> Stat3

```
EVIDENCE Esr1 -> Stat3
  coefficients: Ctr_0H -0.01 [f154], Ctr_2H -0.01 [f155], Ctr_6H -0.42 [f156], Ctr_12H -0.28 [f157], Ctr_18H -0.31 [f158], Ctr_24H -0.32 [f159], Ik_0H -0.20 [f160], Ik_2H -0.01 [f161], Ik_6H -0.45 [f162], Ik_12H -0.01 [f163], Ik_18H -0.01 [f164], Ik_24H -0.01 [f165]
  omic Transcription_factor; area ; evidence supported (KEGG)
  KGML: GErel on mmu04917
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.) MLR reports no p-values.
```

## graph_neighbors: Esr1 (out, REGULATES)

```
NEIGHBOURS of Esr1 (depth 1, 26 edge(s) [f166])
  Esr1 -> Prkca  [REGULATES; coef 1.89 [f167] at Ik_6H, target R2 0.85 [f168]; evidence supported]
  Esr1 -> Mdm2  [REGULATES; coef -1.36 [f169] at Ik_12H, target R2 0.91 [f170]; evidence novel]
  Esr1 -> Stat5a  [REGULATES; coef -0.69 [f171] at Ik_12H, target R2 0.66 [f172]; evidence supported]
  Esr1 -> Slc7a1  [REGULATES; coef 0.68 [f173] at Ctr_2H, target R2 0.92 [f174]; evidence novel]
  Esr1 -> Mogs  [REGULATES; coef 0.50 [f175] at Ctr_2H, target R2 0.97 [f176]; evidence novel]
  Esr1 -> Stat3  [REGULATES; coef -0.45 [f177] at Ik_6H, target R2 0.96 [f178]; evidence supported]
  Esr1 -> Nfe2l1  [REGULATES; coef 0.44 [f179] at Ctr_2H, target R2 0.87 [f180]; evidence unsupported]
  Esr1 -> Esrra  [REGULATES; coef -0.31 [f181] at Ik_12H, target R2 0.80 [f182]; evidence unsupported]
  Esr1 -> Cdkn1a  [REGULATES; coef 0.31 [f183] at Ik_6H, target R2 0.93 [f184]; evidence novel]
  Esr1 -> Ncoa2  [REGULATES; coef -0.29 [f185] at Ctr_6H, target R2 0.88 [f186]; evidence supported]
  Esr1 -> Apoe  [REGULATES; coef -0.28 [f187] at Ctr_2H, target R2 0.93 [f188]; evidence novel]
  Esr1 -> Pik3r1  [REGULATES; coef -0.25 [f189] at Ctr_6H, target R2 0.88 [f190]; evidence supported]
  Esr1 -> Abca1  [REGULATES; coef 0.23 [f191] at Ik_0H, target R2 0.97 [f192]; evidence novel]
  Esr1 -> Ggta1  [REGULATES; coef -0.22 [f193] at Ctr_6H, target R2 0.77 [f194]; evidence novel]
  Esr1 -> Vegfa  [REGULATES; coef -0.17 [f195] at Ik_18H, target R2 0.94 [f196]; evidence novel]
  Esr1 -> Nrf1  [REGULATES; coef 0.16 [f197] at Ctr_18H, target R2 0.86 [f198]; evidence novel]
  Esr1 -> Egr1  [REGULATES; coef -0.16 [f199] at Ik_12H, target R2 0.95 [f200]; evidence novel]
  Esr1 -> Tnfsf11  [REGULATES; coef 0.15 [f201] at Ik_0H, target R2 0.78 [f202]; evidence novel]
  Esr1 -> Csk  [REGULATES; coef 0.14 [f203] at Ik_18H, target R2 0.54 [f204]; evidence novel]
  Esr1 -> H19  [REGULATES; coef -0.13 [f205] at Ik_12H, target R2 0.44 [f206]; evidence novel]
  ... 6 more not shown (top_k=20, ranked |coef| then evidence)
(coefficients are regression slopes, not correlations; not comparable across omics or targets. R2 is the target's whole model, not this edge.)
```

## graph_path: Esr1 -> Stat5a

```
PATHS Esr1 -> Stat5a (5 shown, shortest first)
  Esr1 -[REGULATES(supported)]- Stat5a
  Esr1 -[REGULATES(supported)]- Fos; Fos -[KGML]- Stat5a
  Esr1 -[OMNIPATH]- Ep300; Ep300 -[REGULATES(supported)]- Stat5a
  Esr1 -[OMNIPATH]- Jak2; Jak2 -[KGML]- Stat5a
  Esr1 -[REGULATES(supported)]- Ccnd1; Ccnd1 -[KGML]- Stat5a
```

Facts ledger after this trace: 206 registered numbers.
