EXTERNAL_RESOURCES = {
                "ensembl"   :   [
                    {
                    "url"           :   "https://ftp.ebi.ac.uk/ensemblgenomes/pub/current/",
                    "species-dir"   :   "oryza_sativa",
                    "division"      :   "plants",
                    "output"        :   "ensembl_mapping.list",
                    "description"   :   "Source: Ensembl cross-reference TSV dumps. BioMart was retired (martservice answers HTTP 405), so the release/assembly and filename are resolved at run time rather than pinned here."
                    },
                    {
                    "url"           :   "https://ftp.ebi.ac.uk/ensemblgenomes/pub/current/",
                    "species-dir"   :   "oryza_sativa",
                    "division"      :   "plants",
                    "xref-type"     :   "uniprot",
                    "xref-db"       :   ["Uniprot/SWISSPROT", "Uniprot/SPTREMBL"],
                    "output"        :   "uniprot_mapping.list",
                    "description"   :   "Source: Ensembl UniProt cross-reference TSV dumps. BioMart was retired (martservice answers HTTP 405), so the release/assembly and filename are resolved at run time rather than pinned here."
                    }
                ]
        }