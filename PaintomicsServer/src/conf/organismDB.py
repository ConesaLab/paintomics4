dicDatabases = {
        'mmu'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id', 'OmniPath': 'uniprot_acc'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id', 'OmniPath': 'refseq_gene_symbol'}],
        'hsa'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id', 'OmniPath': 'uniprot_acc'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id', 'OmniPath': 'refseq_gene_symbol'}],
        'dre'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'dme'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'bta'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'dosa'  :   [{'KEGG': 'ensembl_transcript'}, {'KEGG': 'kegg_gene_symbol'}],
        'sly'   :   [{'KEGG': 'entrezgene', 'MapMan': 'mapman_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'MapMan': 'mapman_gene_id'}],
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
        'cel'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
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
    
    
