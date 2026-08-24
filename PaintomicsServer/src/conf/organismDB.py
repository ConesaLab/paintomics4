dicDatabases = {
        'mmu'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id', 'OmniPath': 'uniprot_acc'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id', 'OmniPath': 'refseq_gene_symbol'}],
        'hsa'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id', 'OmniPath': 'uniprot_acc'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id', 'OmniPath': 'refseq_gene_symbol'}],
        # Zebrafish. Named `entrezgene`, which its build produces from
        # `mapping/ensembl_mapping.list` -- a file that was never downloaded for
        # dre, so the table does not exist and EVERY dre job died in
        # resolveDatabaseIds (KEGG is mandatory, so no submission could avoid
        # it). The KEGG mapping files ARE on disk, so `processKEGGMappingData()`
        # was enabled in its build script and dre rebuilt; `kegg_id` then holds
        # the numeric NCBI gene ids its pathway documents reference (measured:
        # 500/500 of them). `refseq_gene_symbol` is likewise absent and cannot
        # be built without the RefSeq downloads, so the symbol slot moves to
        # `kegg_gene_symbol`, which the same KEGG mapping produces.
        'dre'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'dme'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        # bta/ptr/acs declared kegg_id, which only processKEGGMappingData() builds
        # and none of their build scripts calls -- so `resolveDatabaseIds` found no
        # such table and every gene-based job on them died with
        # "'NoneType' object has no attribute 'get'". They do not need that table:
        # verified 2026-08-24 against rest.kegg.jp/list/<code> and against the
        # installed pathway documents, all three name their genes by NCBI gene id
        # (bta:281543, ptr:450664, acs:100552963), which is exactly what their
        # Ensembl-based build already installs as `entrezgene`. Same shape as
        # hsa/mmu/rno. Drosophila is the odd one out -- KEGG keys dme on
        # Dmel_CG#### -- so dme keeps kegg_id and builds it instead.
        'bta'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'ptr'   :   [{'KEGG': 'entrezgene'}, {'KEGG': 'refseq_gene_symbol'}],
        'acs'   :   [{'KEGG': 'entrezgene'}, {'KEGG': 'refseq_gene_symbol'}],
        # Rice (RAP-DB). `ensembl_transcript` is registered by dosa's own
        # processEnsemblData -- insertDatabase runs before the file read, so a
        # missing input leaves the table declared and EMPTY (0 documents), which
        # resolves without error and maps nothing: every dosa job reported
        # success having translated no gene at all. Its KEGG pathway documents
        # reference RAP-DB gene ids (`Os01g0147900`) and only `kegg_id` holds
        # them -- measured 500/500, and 100% reachable from uniprot_acc and
        # kegg_gene_symbol, the species' other populated tables.
        'dosa'  :   [{'KEGG': 'kegg_id'}, {'KEGG': 'kegg_gene_symbol'}],
        # Tomato. `entrezgene` (16,173 entries, from Ensembl) holds only part
        # of the NCBI gene space KEGG references: it matched 340 of 500 sampled
        # pathway gene ids, so ~1 gene in 3 could never be painted whatever the
        # user uploaded. `kegg_id` (35,181) matched 500/500 and measured
        # better-or-equal from EVERY installed table -- Solyc ids stay at
        # 150/150, while uniprot_acc and kegg_gene_symbol go from 0% to 100%
        # because the target no longer sits on the far side of the
        # Ensembl/KEGG mate split.
        'sly'   :   [{'KEGG': 'kegg_id', 'MapMan': 'mapman_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'MapMan': 'mapman_gene_id'}],
        'rno'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id', 'OmniPath': 'uniprot_acc'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id', 'OmniPath': 'refseq_gene_symbol'}],
        'sot'   :   [{'KEGG': 'kegg_id', 'MapMan': 'mapman_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'MapMan': 'mapman_gene_id'}],
        # Rice. The KEGG half repeats the default this species already got
        # from getDatabasesByOrganismCode's fallback (kegg_id + kegg_gene_symbol,
        # FeatureNamesToKeggIDsMapper.py:116), so adding the entry changes
        # nothing about how osa's KEGG identifiers resolve -- it only makes the
        # installed MapMan data reachable. Rice's other KEGG code, `dosa`, must
        # NOT get MapMan: it is keyed on RAP-DB ids and KEGG answers HTTP 400
        # for /conv/dosa/ncbi-geneid, so the gene-to-bin cross-link has nothing
        # to join through.
        'osa'   :   [{'KEGG': 'kegg_id', 'MapMan': 'mapman_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'MapMan': 'mapman_gene_id'}],
        'ath'   :   [{'KEGG': 'kegg_id', 'MapMan': 'mapman_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'MapMan': 'mapman_gene_id'}],
        'sce'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'bbb'   :   [{'KEGG': 'kegg_id'}, {'KEGG': 'kegg_gene_symbol'}],
        # The seven Reactome species below carried installed reactome_gene_id
        # xrefs (2026-08-14 full reinstall) that the app never offered, because
        # this table is what turns installed data into a selectable database.
        # Patterns follow each species' actual identifier inventory: entrez +
        # refseq symbols where its build produced them (mmu-style), kegg_id +
        # kegg symbols otherwise (sce-style). cfa's build yields no gene
        # symbols, so its name slot degrades to entrezgene.
        # C. elegans. Same shape as dme: KEGG keys it on its OWN identifier
        # space (`CELE_C17G1.7`), so the configured `entrezgene` -- numeric NCBI
        # ids -- matched 0 of 500 sampled pathway gene ids and no other installed
        # table matched one either. Every worm job mapped nothing and reported
        # success. `processKEGGMappingData()` was enabled in its build script so
        # `kegg_id` carries the CELE_ ids. The symbol slot keeps
        # `refseq_gene_symbol` (44,150 entries against kegg_gene_symbol's fewer,
        # and reachable from what worm users upload).
        'cel'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'cfa'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}],
        'ddi'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'gga'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'pfa'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'spo'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'xtr'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        # ssc's build never called processReactomePathwaysData (the call sat
        # commented out since the file was written); wired together with that
        # fix on 2026-08-14.
        'ssc'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}]
    }
    
    
