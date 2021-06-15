EXTERNAL_RESOURCES = {
                "reactome"   : {
                        "details_url" :   "https://reactome.org/ContentService/data/query/enhanced/{}",
                        "diagram_url" :   "https://reactome.org/ContentService/exporter/diagram/{}.png?diagramProfile=Modern&quality=5&margin=0&analysisProfile=Standard&held=false",                        
                        "nodes_url"   :   "https://reactome.org/download/current/diagram/{}.json",
                        "graph_url"   :   "https://reactome.org/download/current/diagram/{}.graph.json",
                        "entity_url"  :   "https://reactome.org/ContentService/data/participants/{}/referenceEntities",
                        "events_url"  :   "https://reactome.org/ContentService/data/pathway/{}/containedEvents"
                    },
                "mapman"      : {
                        "metabolites":
                            {
                            "url"           :   "http://localhost/",
                            "file"          :   "mapman_metabolites.txt",
                            "output"        :   "mapman_metabolites.txt",
                            "description"   :   "Source: <include description>"
                            }
                }
        }
