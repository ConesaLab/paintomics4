dicDatabases = {
        'mmu'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'hsa'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'dre'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'dme'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'bta'   :   [{'KEGG': 'kegg_id', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'dosa'  :   [{'KEGG': 'ensembl_transcript'}, {'KEGG': 'kegg_gene_symbol'}],
        'sly'   :   [{'KEGG': 'entrezgene', 'MapMan': 'mapman_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'MapMan': 'mapman_gene_id'}],
        'rno'   :   [{'KEGG': 'entrezgene', 'Reactome': 'reactome_gene_id'}, {'KEGG': 'refseq_gene_symbol', 'Reactome': 'reactome_gene_id'}],
        'sot'   :   [{'KEGG': 'kegg_id', 'MapMan': 'mapman_gene_id'}, {'KEGG': 'kegg_gene_symbol', 'MapMan': 'mapman_gene_id'}],
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
    
    
