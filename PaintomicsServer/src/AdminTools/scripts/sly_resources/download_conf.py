EXTERNAL_RESOURCES = {
                "ensembl"   :   [
                    {
                    "url"           :   "http://plants.ensembl.org/biomart/martservice?query=",
                    "file"          :   "sly_resources/ensembl_mapping.xml",
                    "output"        :   "ensembl_mapping.list",
                    "description"   :   "Source: Ensembl Plants databases. Downloaded from Biomart."
                    },
                    {
                    "url"           :   "http://plants.ensembl.org/biomart/martservice?query=",
                    "file"          :   "sly_resources/uniprot_mapping.xml",
                    "output"        :   "uniprot_mapping.list",
                    "description"   :   "Source: UniProt + Ensembl Plants databases. Downloaded from Biomart."
                    }
                ],
                "mapman_kegg"   :   [
                    {
                    "url"           :   "/home/tian/mapman/sly/",
                    "file"          :   "gene-to-entrez_sly.tsv",
                    "output"        :   "gene-to-entrez_sly.list",
                    "description"   :    "Source: <include description>"
                    }
                ],
                "mapman_gene"   :   [
                    {
                    "url"           :   "/home/tian/mapman/sly/",
                    "file"          :   "gene-to-mapman_sly.tsv",
                    "output"        :   "gene-to-mapman_sly.list",
                    "description"   :   "Source: <include description>"
                    }
                ],
                "mapman_pathways"   :   [
                    {
                    "url"           :   "/home/tian/mapman/common/",
                    "file"          :   "mapman_pathways.tar.gz",
                    "output"        :   "mapman_pathways.tar.gz",
                    "description"   :   "Source: <include description>"
                    }
                ],
                "mapman_classification"   :   [
                    {
                    "url"           :   "/home/tian/mapman/common/",
                    "file"          :   "mapman_classification.txt",
                    "output"        :   "mapman_classification.txt",
                    "description"   :   "Source: <include description>"
                    }
                ],
                "metabolites"	:	[                    
                    {
                    "url"           :   "/home/tian/mapman/common/",
                    "file"          :   "mapman_metabolites.txt",
                    "output"        :   "mapman_metabolites.txt",
                    "description"   :   "Source: <include description>"
                    }
                    ]
        }
