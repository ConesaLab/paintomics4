###########################################################
############     GalaxyNetworkFunctions.R     #############
###########################################################
# Author: Leandro Balzano-Nogueira
# Genetics Institute, University of Florida (Gainesville)
# Last update: Oct/06/2020

# This script is to gather together the functions used for the Galaxy Network Analysis

###########################################################
# Libraries required
library (dplyr)
library(tidyverse)
library(igraph)
library(visNetwork)
library(ggplot2)
library(ggsignif)
library(ggpubr)
library(gridExtra)
library(reshape2)
library (data.table)

###########################################################
# Functions related to the downloading and parsing of the data:

KeggParser<- function (Pathways) {
  # Function to create a table with the interactions between features inside KEGG pathways. These features can be genes or met$
  # Input: A file with a list of the KEGG pathways
  # Output: A data frame with all information needed to analyze and interpret the interaction among features
  # node_id_1: This is the ID number of the first feature of the interaction
  # node_id_2: It This the ID number of the second feature of the interaction
  # relationship: This is the type of relationship reported in KEGG (ECrel, PPrel, etc)
  # relationship_suptype: This is the subtype of relationship reported in KEGG pathways
  # entry_type_1: This is the type of the first feature of the interaction, It can be gene or compound
  # entry_type_2: This is the type of the second feature of the interaction, It can be gene or compound
  # entry_name_1: This is the ID name or names of the first feature of the interaction. If several isoforms, the algorithm saves them all and locates them in different rows.
  # entry_name_2: This is the ID name or names of the second feature of the interaction. If several isoforms, the algorithm saves them all and locates them in different rows.
  # pathway: This is the pathway KEGG code.
  
  suppressWarnings({ 
    ParserData<-NULL
    # Loop over all KEGG pathways in the input data
    for (path in 1:length(Pathways)) {
      print (Pathways[path])
      url= paste0("http://rest.kegg.jp/get/",Pathways[path],"/kgml")  
      #print(url)
      html_data <- read_html(url)
      ####
      entry <- html_nodes(html_data,"entry")
      #print(entry)
      entrytable<-bind_rows(lapply(xml_attrs(entry), function(x) data.frame(as.list(x), stringsAsFactors=FALSE)))
      entrytable$pathway<-rep(Pathways[path],nrow(entrytable))
      #print(head(entrytable))
      ####
      relation<-html_nodes(html_data,"relation")
      subtype<-html_nodes(html_data,"subtype")
      reaction<-html_nodes(html_data,"reaction")
      
      #print(relation)
      #length(relation)
      
      # Some KEGG pathways do not report any relation between features (i.e. hsa00472 D-Arginine and D-ornithine metabolism - Homo sapiens (human))
      # First Analysis: Relation
      
      if (length(relation)==0 & length(reaction)==0) {
        print ("This Pathway has zero relations and zero reactions reported")
        next
      }
      
      
      RelationTable<-NULL
      if (length(relation)==0) {
        print ("This Pathway has zero relations reported")
        RelationTable2<-NULL
      } else {
        #print("Yes relation")
        for (i in 1:length(relation)) {
          #print(i)
          #relation [i]
          relationtable<-bind_rows(lapply(xml_attrs(relation[i]), function(x) data.frame(as.list(x), stringsAsFactors=FALSE)))
          subtypetableTest<-try (bind_rows(lapply(xml_attrs(subtype[i]), function(x) data.frame(as.list(x), stringsAsFactors=FALSE))) ,silent = TRUE)
          
          
          if (class(subtypetableTest) == "try-error" |length(subtypetableTest)==0 ) {
            #print(paste("Atrape un error de subtype repetido en ", relation[i]), sep=" ")
            relation2<-as.character(relation)
            prerelation1<-unlist(strsplit(relation2 [i], split='=\"'))
            prerelation1<-unlist(strsplit(prerelation1, split=' '))
            prerelation1<-unlist(strsplit(prerelation1, split='\"'))
            prerelation2<-t(data.frame(c(prerelation1[3],prerelation1[5], prerelation1[7],prerelation1[10],prerelation1[12])))
            
            rownames(prerelation2)<-seq(1:nrow(prerelation2))
            colnames(prerelation2)<-c("entry1","entry2","type","relationship_suptype","value")
            #print(prerelation2)
            RelationTable<-data.frame(rbind(RelationTable,prerelation2))  
            
          } else {
            prerelation2<-cbind(relationtable,subtypetableTest)
            rownames(prerelation2)<-seq(1:nrow(prerelation2))
            colnames(prerelation2)<-c("entry1","entry2","type","relationship_suptype","value")
            #print(prerelation2)
            RelationTable<-data.frame(rbind(RelationTable,prerelation2))  
            
          }
          subtypetableTest<-NULL
        }
        
        #head(RelationTable)
        #head(entrytable)
        # The type of relation between features is very important:
        # If the relation is "PPrel", "PCrel" or "GErel" the relation is physically direct, so there is no intermediate compound between features
        
        RelationTable2<-NULL
        for (row in 1:nrow(RelationTable)) {
          if (RelationTable[row,]$type == "PPrel"| RelationTable[row,]$type == "PCrel"| RelationTable[row,]$type == "GErel" | RelationTable[row,]$type == "maplink" ){
            preRelationTable2<-RelationTable[row,-5]
            colnames(preRelationTable2)<-c("node_id_1","node_id_2","relationship","relationship_suptype")
            RelationTable2<-rbind(RelationTable2,preRelationTable2)
            
            # The other case is "ECrel" in which the interactions occur gene1-metabolite-gene2
            # In these cases the algorithm converts these interactions in two separate ones as follows:
            # gene1-metabolite
            # metabolite-gene2
            # So the interactions among these features is not lost.
            
          } else {
            preRelationTable2step1<-RelationTable[row,c("entry1","value","type","relationship_suptype")];colnames(preRelationTable2step1)<-c("node_id_1","node_id_2","relationship","relationship_suptype")
            preRelationTable2step2<-RelationTable[row,c("value","entry2","type","relationship_suptype")]; colnames(preRelationTable2step2)<-c("node_id_1","node_id_2","relationship","relationship_suptype")
            preRelationTable2<-rbind(preRelationTable2step1,preRelationTable2step2)
            RelationTable2<-rbind(RelationTable2,preRelationTable2)
          }  
        }
      }
      ##############
      # Reaction section
      
      if (length(reaction)==0) {
        print ("This Pathway has zero reactions reported")
        ReactionTable<-NULL
        
      } else {  
        
        ReactionTable<-preReactionTable<-NULL
        reaction2<-as.character(reaction)
        for (ii in 1:length(reaction2)) {
          #print(reaction2 [ii]) # 17 has 2 substrates,27 has 3 products
          if (str_count(reaction2 [ii], "<substrate") >1 ) {
            lossubs<-qdapRegex::ex_between(reaction2 [ii], "><substrate", "></substrate>")[[1]]
            prereaction1<-unlist(strsplit(reaction2 [ii], split='=\"'))
            prereaction1<-unlist(strsplit(prereaction1, split=' '))
            prereaction1<-unlist(strsplit(prereaction1, split='\"'))
            prereaction2<-t(data.frame(c(prereaction1[3],prereaction1[5], prereaction1[7])))
            
            
            
            
            presubstrate3<-prereactionSubstrate<-NULL
            for (iii in 1: length(lossubs)) {
              presubstrate1<-unlist(strsplit(lossubs[iii], split='=\"'))
              presubstrate1<-unlist(strsplit(presubstrate1, split=' '))
              presubstrate1<-unlist(strsplit(presubstrate1, split='\"'))
              presubstrate2<-t(data.frame(c(presubstrate1[2],presubstrate1[4])))
              prereaction3tita<-cbind(prereaction2,presubstrate2)
              #presubstrate3<-rbind(presubstrate3,presubstrate2)
              prereactionSubstrate<-rbind(prereactionSubstrate,prereaction3tita)
              
            }
            rownames(prereactionSubstrate)<-seq(1:nrow(prereactionSubstrate))
            colnames(prereactionSubstrate)<-c("entry1","relationship_suptype","relationship","substrate_id",
                                              "substrate_name")
            prereactionSubstrate<-prereactionSubstrate[,c("substrate_id","entry1","relationship","relationship_suptype")]
            colnames(prereactionSubstrate)<-c("node_id_1","node_id_2","relationship","relationship_suptype")
            
            #prereactionSubstrate
            vectsubstrates<-as.vector(prereactionSubstrate[,1])
            LaCombinatoria<-combinations(nrow(prereactionSubstrate),2,vectsubstrates)
            lacol3<-rep(prereactionSubstrate[1,3],nrow(LaCombinatoria))
            lacol4<-rep(prereactionSubstrate[1,4],nrow(LaCombinatoria))
            
            LaCombinatoria2=NULL
            for (lc in 1:nrow(LaCombinatoria)) {
              prelacomb<-c(LaCombinatoria[lc,],lacol3[lc],lacol4[lc])
              LaCombinatoria2<-rbind(LaCombinatoria2,prelacomb)
            }
            
            prereactionSubstrate<-rbind(prereactionSubstrate,LaCombinatoria2)
            rownames(prereactionSubstrate)<-seq(1:nrow(prereactionSubstrate))
            #Allsubstrates<-rbind(Allsubstrates,prereactionSubstrate)
          } else { # El else de si es un solo sustrato
            lossubs<-qdapRegex::ex_between(reaction2 [ii], "><substrate", "></substrate>")[[1]]
            prereaction1<-unlist(strsplit(reaction2 [ii], split='=\"'))
            prereaction1<-unlist(strsplit(prereaction1, split=' '))
            prereaction1<-unlist(strsplit(prereaction1, split='\"'))
            prereaction2<-t(data.frame(c(prereaction1[3],prereaction1[5], prereaction1[7])))
            
            rownames(prereaction2)<-seq(1:nrow(prereaction2))
            colnames(prereaction2)<-c("entry1","relationship_suptype","relationship")
            
            presubstrate1<-unlist(strsplit(lossubs, split='=\"'))
            presubstrate1<-unlist(strsplit(presubstrate1, split=' '))
            presubstrate1<-unlist(strsplit(presubstrate1, split='\"'))
            presubstrate2<-t(data.frame(c(presubstrate1[2],presubstrate1[4])))
            preproduct3tita<-cbind(prereaction2,presubstrate2)
            
            prereactionSubstrate<-preproduct3tita
            colnames(prereactionSubstrate)<-c("entry1","relationship_suptype","relationship","substrate_id",
                                              "substrate_name")
            prereactionSubstrate<-t(as.data.frame(prereactionSubstrate[,c("substrate_id","entry1","relationship","relationship_suptype")]) )
            colnames(prereactionSubstrate)<-c("node_id_1","node_id_2","relationship","relationship_suptype")
            
          }
          #prereactionSubstrate
          
          
          
          # Now the products  # 27has 3 products
          if (str_count(reaction2 [ii], "<product") >1 ) {
            losprods<-qdapRegex::ex_between(reaction2 [ii], "><product", "></product>")[[1]]
            prereaction1<-unlist(strsplit(reaction2 [ii], split='=\"'))
            prereaction1<-unlist(strsplit(prereaction1, split=' '))
            prereaction1<-unlist(strsplit(prereaction1, split='\"'))
            prereaction2<-t(data.frame(c(prereaction1[3],prereaction1[5], prereaction1[7])))
            
            preproduct3<-prereactionProduct<-NULL
            for (iii in 1: length(losprods)) {
              preproduct1<-unlist(strsplit(losprods[iii], split='=\"'))
              preproduct1<-unlist(strsplit(preproduct1, split=' '))
              preproduct1<-unlist(strsplit(preproduct1, split='\"'))
              preproduct2<-t(data.frame(c(preproduct1[2],preproduct1[4])))
              preproduct3tita<-cbind(prereaction2,preproduct2)
              
              prereactionProduct<-rbind(prereactionProduct,preproduct3tita)
              
            }
            rownames(prereactionProduct)<-seq(1:nrow(prereactionProduct)) +5000
            colnames(prereactionProduct)<-c("entry1","relationship_suptype","relationship","product_id",
                                            "product_name")
            
            prereactionProduct<-prereactionProduct[,c("entry1","product_id","relationship","relationship_suptype")]
            colnames(prereactionProduct)<-c("node_id_1","node_id_2","relationship","relationship_suptype")
            
            #prereactionProduct
            vectproducts<-as.vector(prereactionProduct[,2])
            LaCombinatoria<-combinations(nrow(prereactionProduct),2,vectproducts)
            lacol3<-rep(prereactionSubstrate[1,3],nrow(LaCombinatoria))
            lacol4<-rep(prereactionSubstrate[1,4],nrow(LaCombinatoria))
            
            LaCombinatoria2=NULL
            for (lc in 1:nrow(LaCombinatoria)) {
              prelacomb<-c(LaCombinatoria[lc,],lacol3[lc],lacol4[lc])
              LaCombinatoria2<-rbind(LaCombinatoria2,prelacomb)
            }
            
            prereactionProduct<-rbind(prereactionProduct,LaCombinatoria2)
            rownames(prereactionProduct)<-seq(1:nrow(prereactionProduct))
            
            
            
            
            
            
          } else{ # else de si es un solo producto
            losprods<-qdapRegex::ex_between(reaction2 [ii], "><product", "></product>")[[1]]
            prereaction1<-unlist(strsplit(reaction2 [ii], split='=\"'))
            prereaction1<-unlist(strsplit(prereaction1, split=' '))
            prereaction1<-unlist(strsplit(prereaction1, split='\"'))
            prereaction2<-t(data.frame(c(prereaction1[3],prereaction1[5], prereaction1[7])))
            
            preproduct1<-unlist(strsplit(losprods, split='=\"'))
            preproduct1<-unlist(strsplit(preproduct1, split=' '))
            preproduct1<-unlist(strsplit(preproduct1, split='\"'))
            preproduct2<-t(data.frame(c(preproduct1[2],preproduct1[4])))
            preproduct3tita<-cbind(prereaction2,preproduct2)
            
            prereactionProduct<-preproduct3tita
            colnames(prereactionProduct)<-c("entry1","relationship_suptype","relationship","product_id",
                                            "product_name")
            prereactionProduct<-t(as.data.frame(prereactionProduct[,c("entry1","product_id","relationship","relationship_suptype")]) )
            colnames(prereactionProduct)<-c("node_id_1","node_id_2","relationship","relationship_suptype")
          }
          #
          preReactionTable<-data.frame(rbind(prereactionSubstrate,prereactionProduct)) ;
          rownames(preReactionTable)<- seq(1:nrow(preReactionTable))
          ReactionTable<-rbind(ReactionTable,preReactionTable)  
          
        } # Fin del for de todas las reacciones
        ####### ENd of reaction section
      } # Fin del else de reaction > 0
      RelationTable3<-rbind(RelationTable2,ReactionTable)
      #}
      #head(entrytable)
      id_feature<-entrytable[,c("id","type")]
      
      
      RelationTable3$entry_type_1<- id_feature$type[match(RelationTable3$node_id_1, id_feature$id)]
      RelationTable3$entry_type_2<- id_feature$type[match(RelationTable3$node_id_2, id_feature$id)]
      id_name<-entrytable[,c("id","name")]
      RelationTable4<-RelationTable3
      RelationTable4$entry_name_1<- id_name$name[match(RelationTable4$node_id_1, id_name$id)]
      RelationTable4<-separate_rows(RelationTable4,entry_name_1,sep=" ")
      RelationTable5<-RelationTable4
      RelationTable5$entry_name_1<-sapply(strsplit(RelationTable5$entry_name_1, split=':', fixed=TRUE), function(x) (x[2]))
      RelationTable5$entry_name_2<- id_name$name[match(RelationTable5$node_id_2, id_name$id)]
      RelationTable5<-separate_rows(RelationTable5,entry_name_2,sep=" ") #Esta es
      RelationTable5$entry_name_2<-sapply(strsplit(RelationTable5$entry_name_2, split=':', fixed=TRUE), function(x) (x[2]))
      RelationTable5$pathway<-rep(Pathways[path], nrow(RelationTable5))
      
      # replace NA
      RelationTable5[is.na(RelationTable5)] <- ''
      
 
      
      ##### Working woth groups of proteins
      if (any(RelationTable5$entry_type_1 == "group" | RelationTable5$entry_type_2=="group" )) {
        #RelationTable5wGroups<-RelationTable5[RelationTable5$entry_type_1 == "group" | RelationTable5$entry_type_2=="group",]
        #losagrupados<-c(RelationTable5wGroups$node_id_1[RelationTable5wGroups$entry_type_1 =="group"],
        #               RelationTable5wGroups$node_id_2[RelationTable5wGroups$entry_type_2 =="group"]
        #                )
        
        entrycongroups<- as.character(entry)
        entrytablesubsetgroup<-entrytable[entrytable$type=="group",]
        entrytablesubsetgroup$id
        elSubset<-NULL
        for (all in 1:length(entrycongroups)) {
          entrycongroups1<-unlist(strsplit(entrycongroups[all], split='=\"'))
          entrycongroups1<-unlist(strsplit(entrycongroups1, split=' '))
          entrycongroups1<-unlist(strsplit(entrycongroups1, split='\"'))
          if (entrycongroups1[3] %in% entrytablesubsetgroup$id ) {
            subseteo<-entrycongroups[all]
            elSubset<-rbind(elSubset,subseteo)
          } else {
            next  
          }
        }
        
        vectemplado<-seq(2,100,by=2)
        preloscomponentes4<-NULL
        for (s in 1:length(elSubset)) {
          entrytbls<-entrytablesubsetgroup[s,]
          loscomponentes<-qdapRegex::ex_between(elSubset [s], "><component", "></component>")[[1]]
          cuantosSon<-length(loscomponentes)
          losqueson<-vectemplado[1:cuantosSon]
          preloscomponentes1<-unlist(strsplit(loscomponentes, split='=\"'))
          preloscomponentes1<-unlist(strsplit(preloscomponentes1, split=' '))
          preloscomponentes1<-unlist(strsplit(preloscomponentes1, split='\"'))
          
          preloscomponentes2<-NULL
          for (t in 1:length(losqueson)) {
            plc1<-preloscomponentes1[losqueson[t]]
            preloscomponentes2<-c(preloscomponentes2,plc1)
            
          }
          preloscomponentes3<-cbind(entrytbls,preloscomponentes2)
          #preloscomponentes2<-t(data.frame(preloscomponentes2))
          
          preloscomponentes4<-rbind(preloscomponentes4,preloscomponentes3)
          #presubstrate3<-rbind(presubstrate3,presubstrate2)
          #prereactionSubstrate<-rbind(prereactionSubstrate,prereaction3tita)
        }
        
        RealType<-RealName<-VectTable<-NULL
        for (all in 1:length(entrycongroups)) {
          #print(all)
          entrycongroups1<-unlist(strsplit(entrycongroups[all], split='=\"'))
          entrycongroups1<-unlist(strsplit(entrycongroups1, split=' '))
          entrycongroups1<-unlist(strsplit(entrycongroups1, split='\"'))
          
          prepositionid<-which(entrycongroups1 == "id") [1]
          prepositiontype<-which(entrycongroups1 == "type")[1]
          prepositionname<-which(entrycongroups1 == "name")[1]
          #entrycongroups11<-bind_rows(lapply(xml_attrs(entry[all]), function(x) data.frame(as.list(x), stringsAsFactors=FALSE)))
          #print(entrycongroups1[prepositionid+1])
          if (entrycongroups1[prepositionid+1] %in% preloscomponentes4$preloscomponentes2) {
            
            preRealType<-entrycongroups1[prepositiontype+1]
            
            #RealType<-rbind(RealType,preRealType)
            losprobablesnames<-seq(from=prepositionname, to=prepositiontype,by=1)
            values<-losprobablesnames[which(prepositionname<losprobablesnames & losprobablesnames<prepositiontype)]
            preRealName<-entrycongroups1[values]
            #print(preRealName)
            
            if(length(preRealName) >1 ){
              preRealName<-paste(preRealName,collapse = ",")
            }
            vect<-c(entrycongroups1[prepositionid+1],preRealType,preRealName )
            VectTable<-rbind(VectTable,vect)
            #RealName<-rbind(RealName,preRealName)
          } else {
            next  
          }
        }
        VectTable<-data.frame(VectTable)
        
        preloscomponentes4<-merge(preloscomponentes4,VectTable, by.x="preloscomponentes2",by.y=1)
        
        colnames(preloscomponentes4)[which(names(preloscomponentes4) == "X2")] <- "RealType"
        colnames(preloscomponentes4)[which(names(preloscomponentes4) == "X3")] <- "RealName"
        
        
        
        preloscomponentes4<-preloscomponentes4[,c("id","preloscomponentes2","RealType","RealName")]
        RelationTableGroup<-rbind(merge(RelationTable5,preloscomponentes4, by.x=1,by.y=1),merge(RelationTable5,preloscomponentes4, by.x=2,by.y=1) )
        
        
        for (i in 1: nrow(RelationTableGroup)) {
          if (is.na(RelationTableGroup$entry_name_2[i]) & is.na(RelationTableGroup$RealName[i]) ) {
            next
          } else if (is.na(RelationTableGroup$entry_name_2[i]) & !is.na(RelationTableGroup$RealName[i])){
            RelationTableGroup$entry_name_2[i] <-as.character(RelationTableGroup$RealName[i])
            RelationTableGroup$entry_type_2[i] <-as.character(RelationTableGroup$RealType[i])
            RelationTableGroup$node_id_2[i] <-as.numeric(as.character(RelationTableGroup$preloscomponentes2[i]))
          }
          if (is.na(RelationTableGroup$entry_name_1[i]) & is.na(RelationTableGroup$RealName[i]) ) {
            next
          } else if (is.na(RelationTableGroup$entry_name_1[i]) & !is.na(RelationTableGroup$RealName[i])){
            #print("entre aqui")
            RelationTableGroup$entry_name_1[i] <-as.character(RelationTableGroup$RealName[i])
            RelationTableGroup$entry_type_1[i] <-as.character(RelationTableGroup$RealType[i])
            RelationTableGroup$node_id_1[i] <-as.numeric(as.character(RelationTableGroup$preloscomponentes2[i]))
          }
          
        }
        RelationTableGroup<-separate_rows(RelationTableGroup,entry_name_1,sep=",") #Esta es
        RelationTableGroup<-separate_rows(RelationTableGroup,entry_name_2,sep=",") #Esta es
        
        for (i in 1:nrow(RelationTableGroup)){
          if(str_detect(RelationTableGroup$entry_name_1[i], ":")) {
            RelationTableGroup$entry_name_1[i]<-sapply(strsplit(RelationTableGroup$entry_name_1[i], split=':', fixed=TRUE), function(x) (x[2]))
          } else {
            RelationTableGroup$entry_name_1[i]<-RelationTableGroup$entry_name_1[i]
          }
          
          if(str_detect(RelationTableGroup$entry_name_2[i], ":")) {
            RelationTableGroup$entry_name_2[i]<-sapply(strsplit(RelationTableGroup$entry_name_2[i], split=':', fixed=TRUE), function(x) (x[2]))
          } else {
            RelationTableGroup$entry_name_2[i]<-RelationTableGroup$entry_name_2[i]
          }
        }
        
        RelationTableGroup<-RelationTableGroup[,c("node_id_1","node_id_2","relationship","relationship_suptype",
                                                  "entry_type_1","entry_type_2","entry_name_1","entry_name_2",
                                                  "pathway" )]
        
        RelationTable55<-RelationTable5[RelationTable5$entry_type_1 != "group" & RelationTable5$entry_type_2 != "group",]
        #table(RelationTable55$entry_type_1);table(RelationTable5$entry_type_1)
        #table(RelationTable55$entry_type_2);table(RelationTable5$entry_type_2)
        RelationTable6<-rbind(RelationTable55,RelationTableGroup)
        
        ####End of Working with groups pf proteins
        
        #RelationTable6<-RelationTable5[!(RelationTable5$entry_type_1 == "group" | RelationTable5$entry_type_2=="group"),]
        #ParserData<-rbind(ParserData,RelationTable6)
      } else {
        RelationTable6<-RelationTable5
      }
      ParserData<-rbind(ParserData,RelationTable6)
    }# Closing the for loop pathways[path]
    
    ParserData<-unique(ParserData)
    ParserData<-ParserData[rowSums(is.na(ParserData)) != ncol(ParserData), ]
    
    
    
    rownames(ParserData)<-seq(1:nrow(ParserData))
    res<-ParserData
    return(res)
  })
}


###########################################################
# Function to subset the KEGG data to the size of the user

SubsetFunction <- function (Data, Retain=NULL, Strictness="High") {
  # Function to subset the data to be studied
  # Input :
  # Data: The data as data.frame to be studied
  # SubsetBy: Column name from which the subset is done.
  # Retain: A vector indicating the nodes to be retained.
  # Strictness: A vector to determine how strict is the retention of nodes. If "High" the exact same name of the node would be retained, this is susceptible to lowercase, uppercase or misspellings. If "Low", The retention ignores lowercase or uppercase.
  
  # Output:
  # A data.frame subset
  LosColNames<-colnames (Data) 
  if (is.null (Retain)) {
    print("Retain parameter is empty, no subset have been done")
    DataSubsetted <-Data
    return (DataSubsetted)
  } else {
    #head (Data)
    #Retain = c("atp","adenosine")
    #Data<-kegg_table
    Dat2<-dat1<-NULL
    tt<-0
    lascolumnasaevaluar<-NULL
    if(length(Retain)>= 100){
      retaincolumnidentificator<-as.character(Retain[1:100])
      for (rci in 7:ncol (Data)) {
        if (any(retaincolumnidentificator %in% as.character(Data[,rci]) ) ) {
          #print("yes")
          lcae<-colnames(Data)[rci]
          lascolumnasaevaluar<-c(lascolumnasaevaluar,lcae)
        } else {#print("no")
          }
      }
    }else{
      lascolumnasaevaluar<-colnames(Data)
      }
    
      
    for (nm in 1:length(Retain)) {
      for (i in 1:length(lascolumnasaevaluar)) {
        elcolname<-lascolumnasaevaluar[i]
        if (Strictness == "High") {
        dat1<-Data[which(Data[[elcolname]] == Retain[nm]),]
        #print("algo")
      } else {
        tryCatch({
          dat1<-Data[grep(x = Data[[elcolname]], pattern = Retain[nm]),]
        }, error=function(e){})
        
      }
        Dat2<-rbind(Dat2,dat1)
        
        if (tt!=nrow(Dat2)) {
          tt=nrow(Dat2)
          #print(nrow(Dat2))
        } else { }
        
      }
    }
    }
    DataSubsetted<-Dat2
    return(DataSubsetted)
}

###########################################################

MetricsCalculator<- function (Data,Percentile=NULL, iter=1) {
  # Function to calculate the metrics of the data subset given by the user
  # Input :
  # Data: The data as data.frame to be studied
  # Percentile: A vector of percentiles that we want to analyze. If NULL, the entire dataset will be used to calculate the metrics of the user-given data
  # iter: Number of iterations when any value of percentile is added
  
  # Output:
  # If Percentile = NULL
  # The output is a data frame with 10 columns
  # If Percentile != NULL
  # The output is a list of data frames with 10 columns. For any percentile required, a number = iterations, of data frames will be inside.
  # Column names: id: row Id
  #               Entry_Name: The feature name
  #               Type: The type of the feature (gene or compound)
  # Degree: The degree of that particular feature
  # Eig: The eigenvalue of that particular feature
  # Hub: The hub score of that particular feature
  # Authority: The Authority of that particular feature
  # Closeness: The Closeness of that particular feature
  # Betweenness: The Betweenness of that particular feature
  # Species: The species studied
  
  hknomap1<-Data[Data$entry_type_1 != "map",]
  humanKeggNoMap<-hknomap1[hknomap1$entry_type_2 != "map",]
  Data<-humanKeggNoMap
  
  IDs=c(7,8)   # These are the columns with nodes info, two columns because there are two actors in each interaction
  types=c(5,6) # These are the types corresponding to the nodes. Make sure that nodes and tyypre correspond to each other
  tab1<-Data[,c(IDs[1],types[1])]
  colnames(tab1)<-c("Entry_Name", "Type")
  
  tab2<-humanKeggNoMap[,c(IDs[2],types[2])]
  colnames(tab2)<-c("Entry_Name", "Type")
  Allactors<-unique(rbind(tab1,tab2))#; dim(Allactors)
  #head(Allactors)
  #table (Allactors$type) # 6423 genes and 1788 compounds
  numofclasses<-length(unique (Allactors$Type))
  namesofclasses<-as.character(unique (Allactors$Type))
  
  
  if (is.null(Percentile)){
    print ("yes")
    
    
    sources<-unique(Data[,c(7,5)])
    table(sources$entry_type_1)
    sources$entry_type_1<-as.character(sources$entry_type_1)
    
    colnames(sources)<-c("Entry_Name","Type")
    #head(sources)
    #anyNA(sources)
    
    destinations<-unique(Data[,c(8,6)])
    table(destinations$entry_type_2) # Again we have to eliminate maps
    
    NoMapsSubsetdestinations<-Data[,c(8,6)]
    NoMapsSubsetdestinations<-NoMapsSubsetdestinations[NoMapsSubsetdestinations$entry_type_2 != "map",]#;dim(NoMapsSubsetdestinations)
    destinations<-unique(NoMapsSubsetdestinations)
    #table(destinations$entry_type_2)
    destinations$entry_type_2<-as.character(destinations$entry_type_2)
    colnames(destinations)<-c("Entry_Name","Type")
    #head(destinations)
    #str(destinations)
    #anyNA(destinations)
    
    nodes <- full_join(sources, destinations, by = c("Entry_Name","Type"))
    nodes <- nodes %>% rowid_to_column("id")
    nodes
    #anyNA(nodes)
    #str(nodes)
    #nodes$id<-as.numeric(as.character(nodes$id))
    
    per_route <- Data %>%  
      group_by(entry_name_1, entry_name_2) %>%
      summarise(weight = n()) %>% 
      ungroup()
    #per_route
    
    
    edges<-merge(per_route,nodes, by.x=1 ,by.y=2)
    #edges
    #anyNA(edges)
    colnames(edges)[4]<-"from"
    
    edges<-merge(edges,nodes, by.x=2 ,by.y=2)
    #edges
    #anyNA(edges)
    colnames(edges)[6]<-"to"
    
    ###################
    # Metrics
    
    routes_igraph <- graph_from_data_frame(d = edges[,c(4,6)], vertices = nodes[,c(1,2)], directed = F)
    
    Degree<-degree(routes_igraph, v = V(routes_igraph), 
                   normalized = FALSE)
    Eig <- evcent(routes_igraph)$vector
    Hub <- hub.score(routes_igraph)$vector
    Authority <- authority.score(routes_igraph)$vector
    Closeness <- closeness(routes_igraph)
    Betweenness <- betweenness(routes_igraph)
    #######################
    TheNetworkMetrics <- cbind(Degree, Eig, Hub, Authority, Closeness, Betweenness)
    #dim(TheNetworkMetrics)
    #head(TheNetworkMetrics)
    #table(as.data.frame(TheNetworkMetrics[,6]) )
    #head(nodes)
    TheNetworkMetrics<- merge(nodes,TheNetworkMetrics, by.x=1,by.y=0 )
    dim(nodes);dim(TheNetworkMetrics)
    
    vec<-Data$pathway
    thesp<- ifelse(substr(vec, start=1, stop=3) == "hsa","Human",
                   ifelse(substr(vec, start=1, stop=3) == "dme","Dmel",
                          ifelse(substr(vec, start=1, stop=3) == "ath","Athal",
                                 ifelse (substr(vec, start=1, stop=3) == "cel", "Celegans",
                                         ifelse(substr(vec, start=1, stop=3) == "mmu","Mmus",
                                                substr(vec, start=1, stop=3) ))) ) )
    
    TheNetworkMetrics$Species<-thesp[1:nrow(TheNetworkMetrics)]
    res<-TheNetworkMetrics
    
    
    
    ############################
  } else {   # If percentile is NOT NULL
    MetricsByPercentiles<-list()
    for (p in 1: length(Percentile)) {
      print(Percentile[p])
      NamecitoPercentil<-paste0("p",Percentile[p])
      sampel<-NULL
      # ACA VA LA ITERACION
      theMetrics<-list()
      for (it in 1:iter) {
        namecitoIteration<- paste("Iter ",it, sep = "")
        print(namecitoIteration)
        for ( i in 1: numofclasses){
          gs<-as.vector(sample(x = Allactors$Entry_Name[Allactors$Type == namesofclasses[i]], size = round(length(Allactors$Entry_Name[Allactors$Type ==namesofclasses[i]]) * Percentile[p],digits=0)) )
          sampel<-c(sampel, gs)
        }
        elsubset<-elsubset2<-NULL
        for (ii in 1: length(IDs)){
          elsubset1<-Data[Data[,IDs[ii]] %in% sampel, ]
          #print(dim(elsubset1))
          elsubset2<-rbind(elsubset2,elsubset1)
          #print(dim(elsubset2))
        }
        elsubset<- unique(elsubset2)
        #head(elsubset)
        
        sources<-unique(elsubset [,c(IDs[1],types[1])])
        #str(sources)
        #sources$entry_type_1<-as.character(sources$entry_type_1)
        
        colnames(sources)<-c("Entry_Name","Type")
        #head(sources)
        #anyNA(sources)
        
        destinations<-unique(elsubset [,c(IDs[2],types[2])])
        #table(destinations$entry_type_2) # Again we have to eliminate maps
        colnames(destinations)<-c("Entry_Name","Type")
        head(destinations)
        #str(destinations)
        #anyNA(destinations)
        
        nodes <- full_join(sources, destinations, by = c("Entry_Name","Type"))
        nodes <- nodes %>% rowid_to_column("id")
        nodes
        #anyNA(nodes)
        #str(nodes)
        #nodes$id<-as.numeric(as.character(nodes$id))
        
        #head(elsubset)
        #str(elsubset)
        per_route <- elsubset %>%  
          group_by(entry_name_1, entry_name_2) %>%
          summarise(weight = n()) %>% 
          ungroup()
        per_route
        #anyNA(per_route)
        
        edges<-merge(per_route,nodes, by.x=1 ,by.y=2)
        edges
        #anyNA(edges)
        colnames(edges)[4]<-"from"
        
        edges<-merge(edges,nodes, by.x=2 ,by.y=2)
        edges
        #anyNA(edges)
        colnames(edges)[6]<-"to"
        
        ###################
        # Metrics
        routes_igraph <- graph_from_data_frame(d = edges[,c(4,6)], vertices = nodes[,c(1,2)], directed = F)
        
        Degree<-degree(routes_igraph, v = V(routes_igraph), 
                       normalized = FALSE)
        Eig <- evcent(routes_igraph)$vector
        Hub <- hub.score(routes_igraph)$vector
        Authority <- authority.score(routes_igraph)$vector
        Closeness <- closeness(routes_igraph)
        Betweenness <- betweenness(routes_igraph)
        # Saving the metrics
        theMetrics1 <- cbind(Degree, Eig, Hub, Authority, Closeness, Betweenness)
        #dim(theMetrics1)
        #head(theMetrics1)
        #head(nodes)
        theMetrics2<- merge(nodes,theMetrics1, by.x=1,by.y=0 )
        #dim(nodes);dim(theMetrics2)
        vec<-Data$pathway
        
        thesp<- ifelse(substr(vec, start=1, stop=3) == "hsa","Human",
                       ifelse(substr(vec, start=1, stop=3) == "dme","Dmel",
                              ifelse(substr(vec, start=1, stop=3) == "ath","Athal",
                                     ifelse (substr(vec, start=1, stop=3) == "cel", "Celegans",
                                             ifelse(substr(vec, start=1, stop=3) == "mmu","Mmus",
                                                    substr(vec, start=1, stop=3) ))) ) )
        
        
        
        theMetrics2$Species<-thesp[1:nrow(theMetrics2)]
        
        theMetrics3<-list(theMetrics2)
        theMetrics[namecitoIteration]<-theMetrics3
      } # END of the iterations
      
      MetricsByPercentiles[NamecitoPercentil]<-list(theMetrics)
    } # END of the percentile
    res<-MetricsByPercentiles
  }
  
  
  return (res)
}

###########################################################

UMann<- function (Data) {
  # Function to calculate the Mann-Whitney U for the data evaluated to determine significance between a qualitative (i.e. gene/compounds) and quantitative (i.e. degree, hub score) variable
  # Input:
  # One qualitative (i.e. gene/compounds) and one quantitative (i.e. degree, hub score) variable from the metrics table 
  
  # Output:
  # A table with three columns:
      # Pair: The significant pairs evaluated
      # p-value: The p-value indicating if there is a significant difference between the pair classes
      # Significance: How significant is this diference. 
  #         if (0.05 >= p >0.01) --> "*"
  #         if (0.01>= p >0.001) --> "**"
  #         if (p<=0.001) --> "***"
  GroupColumn<-as.factor(Data[,2])
  Combinations<-combn(unique(GroupColumn), 2)
  Wilcoito<-UMannWitney<-NULL
  for (i in 1:ncol(Combinations)) {
    #print(Combinations [,i])
    PairToTest<-as.vector(Combinations [,i])
    namecito<-paste(PairToTest[1],PairToTest[2],sep = "_" )
    Datita<-Data[Data[,2]==PairToTest,]
    #head(Datita)
    #str(Datita)
    #table(Datita[,2])
    #dim(Data);dim(Datita)
    Wilco<-wilcox.test(as.numeric(as.character(Datita[,1]))~as.factor(as.vector(Datita[,2])), data=Datita)$p.value
    if (Wilco>0.05){
      Signi<-"NS"
    } else if (Wilco<=0.05 & Wilco >0.01){
      Signi<-"*"
    } else if (Wilco<=0.01 & Wilco>0.001){
      Signi<-"**"
    } else if (Wilco<=0.001){
      Signi<- "***"
    }
    
    Wilcoito<-c(namecito,Wilco,Signi)
    UMannWitney<-rbind(UMannWitney,Wilcoito)
    
  }
  rownames(UMannWitney)<-seq(1:nrow(UMannWitney))
  colnames(UMannWitney)<-c("Pair","p_value", "Significance")
  UMannWitney<-data.frame(UMannWitney)
  UMannWitney$p_value<-round(as.numeric(as.character(UMannWitney$p_value)),digits=4)
  return(UMannWitney)
}
###########################################################
NullHypothesisTester <- function (Subset, DESubset, iter, Percentile=NULL ) {
  # Function to test the null hypothesis of the user-provided test of differentially expressed nodes
  # Input:
  # Subset: The Complete data with no map category
  # DESubset: The table subset of all differentially expressed nodes
  # iter: Number of iterations to calculate the null hypothesis
  # Percentile: A vector to indicate the percentile the user wants to calculatee the Retain: A vector indicating the nodes to be retained.
  
  
  # Output:
  # A list of two elements
  # DEResult: A data.frame with all metrics by reference node
  # MetricsByNodes: A list by node with all iterations inside each node
  
  #head(Data)
  AHD<-read.csv("/Users/leobalzano/Dropbox (UFL)/Projects/2019/Galaxy2019/AnalysisAndResults/Data/All_human_kegg_interactions30march2020.csv", row.names = 1) # Laptop
  hknomap1<-All_human_kegg_interactions30march2020[All_human_kegg_interactions30march2020$entry_type_1 != "map",]
  humanKeggNoMap<-hknomap1[hknomap1$entry_type_2 != "map",]
  if(is.vector(Subset)) {
    DataSubset<-SubsetFunction (Data=humanKeggNoMap, Retain=Subset, Strictness="High")
  } else{
    DataSubset<-Subset
  }
  
  TheDESubset<-SubsetFunction (Data=humanKeggNoMap, Retain=DESubset, Strictness="High")
  IDs=c(7,8)
  types=c(5,6)
  tab1<-DataSubset[,c(IDs[1],types[1])]
  colnames(tab1)<-c("Entry_Name", "Type")
  
  tab2<-DataSubset[,c(IDs[2],types[2])]
  colnames(tab2)<-c("Entry_Name", "Type")
  Allactors<-unique(rbind(tab1,tab2))#; dim(Allactors)
  #head(Allactors)
  #table (Allactors$type) # 6423 genes and 1788 compounds
  numofclasses<-length(unique (Allactors$type))
  namesofclasses<-as.character(unique (Allactors$type))
  
  if (is.null(Percentile)) {
    #themetrics<-MetricsCalculator(Data=DataSubset, Percentile=NULL, iter=iter)
    MetricsByPercentiles<-list()
    #### The data per se
    #Subset
    sources<-unique(TheDESubset [,c(IDs[1],types[1])])
    #str(sources)
    #sources$entry_type_1<-as.character(sources$entry_type_1)
    
    colnames(sources)<-c("Entry_Name","Type")
    #head(sources)
    #anyNA(sources)
    
    destinations<-unique( TheDESubset [,c(IDs[2],types[2])])
    #table(destinations$entry_type_2) # Again we have to eliminate maps
    colnames(destinations)<-c("Entry_Name","Type")
    #head(destinations)
    #str(destinations)
    #anyNA(destinations)
    
    nodes <- full_join(sources, destinations, by = c("Entry_Name","Type"))
    nodes <- nodes %>% tibble::rowid_to_column("id")
    nodes
    #anyNA(nodes)
    #str(nodes)
    #nodes$id<-as.numeric(as.character(nodes$id))
    
    #head(elsubset)
    #str(elsubset)
    per_route <- TheDESubset %>%  
      group_by(entry_name_1, entry_name_2) %>%
      summarise(weight = n(), .groups = "drop") %>% 
      ungroup()
    per_route
    #anyNA(per_route)
    
    edges<-merge(per_route,nodes, by.x=1 ,by.y=2)
    edges
    #anyNA(edges)
    colnames(edges)[4]<-"from"
    
    edges<-merge(edges,nodes, by.x=2 ,by.y=2)
    edges
    #anyNA(edges)
    colnames(edges)[6]<-"to"
    
    ###################
    # Metrics
    routes_igraph <- graph_from_data_frame(d = edges[,c(4,6)], vertices = nodes[,c(1,2)], directed = F)
    
    Degree<-degree(routes_igraph, v = V(routes_igraph), 
                   normalized = FALSE)
    Eig <- evcent(routes_igraph)$vector
    Hub <- hub.score(routes_igraph)$vector
    Authority <- authority.score(routes_igraph)$vector
    Closeness <- closeness(routes_igraph)
    Betweenness <- betweenness(routes_igraph)
    # Saving the metrics
    theMetrics1 <- cbind(Degree, Eig, Hub, Authority, Closeness, Betweenness)
    #dim(theMetrics1)
    #head(theMetrics1)
    #head(nodes)
    theMetrics2<- merge(nodes,theMetrics1, by.x=1,by.y=0 )
    #dim(nodes);dim(theMetrics2)
    
    
    
    theMetrics2$Species<-rep("Human",nrow(theMetrics2))
    DEResult<-theMetrics2
    
    
    ####
    subsetnodes<-unique(c(as.character(TheDESubset$entry_name_1),as.character(TheDESubset$entry_name_2) ) )
    numsubsetnodes<-length(subsetnodes)
    subsettab1<-TheDESubset[,c(IDs[1],types[1])]
    colnames(subsettab1)<-c("node", "type")
    
    subsettab2<-TheDESubset[,c(IDs[2],types[2])]
    colnames(subsettab2)<-c("node", "type")
    subsetactors<-unique(rbind(subsettab1,subsettab2))
    subsetnumofclasses<-length(unique (subsetactors$type))
    subsetnamesofclasses<-as.character(unique (subsetactors$type))
    
    for (fu in 1: numsubsetnodes) {
      #print(paste (numsubsetnodes, "nodes, recuerda que aca estamos jalando todo lo que interactue, no solo lo que esta en el pathway, eso lo debes sacar tu al final, cuando ya tengas la tabla"))
      elnodo<-subsetnodes[fu]
      classdelNodo<-subsetactors$type[subsetactors$node == elnodo]
      
      # ACA VA LA ITERACION
      #sampel<-NULL
      theMetrics<-list()
      for (it in 1:iter) {
        namecitoIteration<- paste("Iter ",it, sep = "")
        print(namecitoIteration)
        gs1<-c(
          as.vector(sample (x = Allactors$Entry_Name[Allactors$Type == as.character(classdelNodo)], size = length(subsetactors$type[subsetactors$type== classdelNodo])-1 ) ),
          as.vector(sample (x = Allactors$Entry_Name[Allactors$Type != as.character(classdelNodo)], size = length(subsetactors$type[subsetactors$type!= classdelNodo]) ) ), elnodo
        )
        # Lo que debes buscar en data es la combinacion por tanto...
        #gs1test<-gs1[1:4]
        
        testeo<-combn(gs1,2)
        testeo2<-rbind(testeo[2,],testeo[1,])
        mixtura<-NULL
        testeo3<-testeo[,1:10]
        
        mixtura<-apply(testeo,2,function (x) paste(as.vector(x), collapse="_"))
        for (ts in 1:ncol(testeo3)){
          elmix<-paste(as.vector(testeo3[,ts]), collapse="_")
          mixtura<-c(mixtura,elmix)
        }
        mixtura2 = NULL
        for (ts in 1:ncol(testeo2)){
          elmix2<-paste(as.vector(testeo2[,ts]), collapse="_")
          mixtura2<-c(mixtura2,elmix2)
        }
        
        edgesdelsubset<-c(mixtura,mixtura2)
        Data2<-Data
        Data2$ALledges<-paste(Data[,IDs[1]],Data[,IDs[2]], sep="_")
        elsubset<-Data2[Data2$ALledges %in% edgesdelsubset,]
        #elsubset<-elsubset2<-NULL
        #for (i in 1: length(IDs)){
        #   elsubset1<-Data[Data[,IDs[i]] %in% gs1, ]
        #   #print(dim(elsubset1))
        #   elsubset2<-rbind(elsubset2,elsubset1)
        #   #print(dim(elsubset2))
        # }
        # elsubset<- unique(elsubset2)
        #head(elsubset)
        
        sources<-unique(elsubset [,c(IDs[1],types[1])])
        #str(sources)
        #sources$entry_type_1<-as.character(sources$entry_type_1)
        
        colnames(sources)<-c("Label","Type")
        #head(sources)
        #anyNA(sources)
        
        destinations<-unique(elsubset [,c(IDs[2],types[2])])
        #table(destinations$entry_type_2) # Again we have to eliminate maps
        colnames(destinations)<-c("Label","Type")
        #head(destinations)
        #str(destinations)
        #anyNA(destinations)
        
        nodes <- full_join(sources, destinations, by = c("Label","Type"))
        nodes <- nodes %>% rowid_to_column("id")
        nodes
        #anyNA(nodes)
        #str(nodes)
        #nodes$id<-as.numeric(as.character(nodes$id))
        
        #head(elsubset)
        #str(elsubset)
        per_route <- elsubset %>%  
          group_by(entry_name_1, entry_name_2) %>%
          summarise(weight = n(), .groups = "drop") %>% 
          ungroup()
        per_route
        #anyNA(per_route)
        
        edges<-merge(per_route,nodes, by.x=1 ,by.y=2)
        edges
        #anyNA(edges)
        colnames(edges)[4]<-"from"
        
        edges<-merge(edges,nodes, by.x=2 ,by.y=2)
        edges
        #anyNA(edges)
        colnames(edges)[6]<-"to"
        
        ###################
        # Metrics
        #edges[edges$entry_name_2 == "10312",]
        #edges[edges$entry_name_1 == "10312",]
        
        routes_igraph <- graph_from_data_frame(d = edges[,c(4,6)], vertices = nodes[,c(1,2)], directed = F)
        
        Degree<-degree(routes_igraph, v = V(routes_igraph), 
                       normalized = FALSE)
        
        Eig <- evcent(routes_igraph)$vector
        Hub <- hub.score(routes_igraph)$vector
        Authority <- authority.score(routes_igraph)$vector
        Closeness <- closeness(routes_igraph)
        Betweenness <- betweenness(routes_igraph)
        # Saving the metrics
        theMetrics1 <- cbind(Degree, Eig, Hub, Authority, Closeness, Betweenness)
        #dim(theMetrics1)
        #head(theMetrics1)
        #head(nodes)
        theMetrics2<- merge(nodes,theMetrics1, by.x=1,by.y=0 )
        #dim(nodes);dim(theMetrics2)
        vec<-humanKeggNoMap$pathway
        thesp<- ifelse(substr(vec, start=1, stop=3) == "hsa","Human",
                       ifelse(substr(vec, start=1, stop=3) == "dme","Dmel",
                              ifelse(substr(vec, start=1, stop=3) == "ath","Athal",
                                     ifelse (substr(vec, start=1, stop=3) == "cel", "Celegans",
                                             ifelse(substr(vec, start=1, stop=3) == "mmu","Mmus",
                                                    substr(vec, start=1, stop=3) ))) ) )
        
        theMetrics2$Species<-thesp[1:nrow(theMetrics2)]
        theMetrics3<-list(theMetrics2)
        theMetrics[namecitoIteration]<-theMetrics3
        #elnodo<- "10312"
        #elnodo<-"5137"
        if (elnodo %in% theMetrics[[namecitoIteration]]$Entry_Name ){
          
        } else{
          vec<-c(nrow(theMetrics[[namecitoIteration]])+1,
                 elnodo,as.character(classdelNodo),0,0,0,0,0,0,"Human")
          theMetrics[[namecitoIteration]]<-rbind(vec, theMetrics[[namecitoIteration]])
          
        }
      } # END of the iterations
      MetricsByPercentiles[elnodo]<-list(theMetrics)
      
    }
    res<-list(DEResult=DEResult,
              MetricsByNodes=MetricsByPercentiles
    )
    
  } else { # ELSE of Percentile is NOT NULL
    print("entra al else del percentil is not null")
    MetricsByPercentiles<-list()
    
    for (p in 1: length(Percentile)) {
      print(Percentile[p])
      NamecitoPercentil<-paste0("p",Percentile[p])
      sampel<-NULL
      # ACA VA LA ITERACION
      theMetrics<-list()
      for (it in 1:iter) {
        namecitoIteration<- paste("Iter ",it, sep = "")
        print(namecitoIteration)
        for ( i in 1: numofclasses){
          gs<-as.vector(sample(x = Allactors$node[Allactors$type == namesofclasses[i]], size = round(length(Allactors$node[Allactors$type ==namesofclasses[i]]) * Percentile[p],digits=0)) )
          sampel<-c(sampel, gs)
        }
        elsubset<-elsubset2<-NULL
        for (i in 1: length(IDs)){
          elsubset1<-Data[Data[,IDs[i]] %in% sampel, ]
          #print(dim(elsubset1))
          elsubset2<-rbind(elsubset2,elsubset1)
          #print(dim(elsubset2))
        }
        elsubset<- unique(elsubset2)
        #head(elsubset)
        
        sources<-unique(elsubset [,c(IDs[1],types[1])])
        #str(sources)
        #sources$entry_type_1<-as.character(sources$entry_type_1)
        
        colnames(sources)<-c("Label","Type")
        #head(sources)
        #anyNA(sources)
        
        destinations<-unique(elsubset [,c(IDs[2],types[2])])
        #table(destinations$entry_type_2) # Again we have to eliminate maps
        colnames(destinations)<-c("Label","Type")
        head(destinations)
        #str(destinations)
        #anyNA(destinations)
        
        nodes <- full_join(sources, destinations, by = c("Label","Type"))
        nodes <- nodes %>% rowid_to_column("id")
        nodes
        #anyNA(nodes)
        #str(nodes)
        #nodes$id<-as.numeric(as.character(nodes$id))
        
        #head(elsubset)
        #str(elsubset)
        per_route <- elsubset %>%  
          group_by(entry_name_1, entry_name_2) %>%
          summarise(weight = n()) %>% 
          ungroup()
        per_route
        #anyNA(per_route)
        
        edges<-merge(per_route,nodes, by.x=1 ,by.y=2)
        edges
        #anyNA(edges)
        colnames(edges)[4]<-"from"
        
        edges<-merge(edges,nodes, by.x=2 ,by.y=2)
        edges
        #anyNA(edges)
        colnames(edges)[6]<-"to"
        
        ###################
        # Metrics
        routes_igraph <- graph_from_data_frame(d = edges[,c(4,6)], vertices = nodes[,c(1,2)], directed = F)
        
        Degree<-degree(routes_igraph, v = V(routes_igraph), 
                       normalized = FALSE)
        Eig <- evcent(routes_igraph)$vector
        Hub <- hub.score(routes_igraph)$vector
        Authority <- authority.score(routes_igraph)$vector
        Closeness <- closeness(routes_igraph)
        Betweenness <- betweenness(routes_igraph)
        # Saving the metrics
        theMetrics1 <- cbind(Degree, Eig, Hub, Authority, Closeness, Betweenness)
        #dim(theMetrics1)
        #head(theMetrics1)
        #head(nodes)
        theMetrics2<- merge(nodes,theMetrics1, by.x=1,by.y=0 )
        #dim(nodes);dim(theMetrics2)
        theMetrics2$Species<-rep("Human",nrow(theMetrics2))
        theMetrics3<-list(theMetrics2)
        theMetrics[namecitoIteration]<-theMetrics3
      } # END of the iterations
      
      MetricsByPercentiles[NamecitoPercentil]<-list(theMetrics)
    } # END of the else (if is.null(Percentile) )
    res<-MetricsByPercentiles
  } # END of the percentile
  
  return (res)
}

###########################################################
perm <- function(v) {
  # Function to perform permutation of elements to create different combinations
  n <- length(v)
  if (n == 1) v
  else {
    X <- NULL
    for (i in 1:n) X <- rbind(X, cbind(v[i], perm(v[-i])))
    X
  }
}

###########################################################
plotNullvsReference<- function (Reference=OPNULL$SubsetResult,Data=AllMedians2, Pathway= "Several") {
  # Function to create plots to see the differences between the matrix-reference values vs the values of several iterations of the same size of the reference. It uses the data frame obtained from the "NullHypothesisTester" function.
  # Input:
    # Reference:  The DE result of the reference.
    # Data: All data gathered from the null distribution in which the node that you want to plot is involved.
  # Pathway: The title of the plot
  
  # Output:
  # A plot with all metrics describing the values of the node
  
  suppressWarnings({ 
    thefeatures<-unique(Data$Feature)
    for (i in 1:length(thefeatures) ) {
      elfeature<-thefeatures[i]
      lasrefs<-Reference[Reference$Label == elfeature,4:9]
      lasrefsmelted<-melt(lasrefs, id.vars= )
      tab<-Data[Data$Feature==elfeature,]
      
      tabmelted<-melt(tab[,1:6], id.vars = )
      p = ggplot(tabmelted, aes(x=variable,y=value, colour = variable)) + geom_point(position = position_jitterdodge(), size = 5) +
        theme(axis.title=element_text(face="bold",size="14"),
              axis.text.x = element_text(face="bold", size=18,angle = 330, hjust = 0),
              axis.text.y = element_text(face="bold", size=18),
              plot.title = element_text(size = "16", face = "bold"),
              legend.title = element_blank()#,
              #legend.text = element_text(labels="Reference")
              #legend.position = "none"
        )
      p2<-p + geom_point(data=lasrefsmelted,colour="red",aes(size="Reference"), shape=13 ) +
        ggtitle(paste(Pathway, ", feature: ",elfeature, sep="")) +
        scale_size_manual(values = c(7))
      print (p2)      
      
      
      
    }
  })
}

###########################################################
ProbabilitiesCalculator<- function (Data,vars=c(4:9)) {
  
  # Function to calculate the probabilities of obatining certain metric value by node
  # Input:
  # Data: The list of elementes calculated using "NullHypothesisTester" 
  # vars: a vector with the column numbers to be analyzed in terms of probabilities
  
  # Output:
  # It adds a probability calculation by metric, adding 6 more columns to the reference data called SubsetResult.
  # SubsetResult: A data.frame with all metrics by reference node and the probabilities by metric
  # MetricsByNodes: A list by node with all iterations inside each node
  dataref<-Data$SubsetResult
  databyNode<-Data$MetricsByNodes
  
  TabProbs<-NULL
  for (col in min(vars):max(vars)){
    #print (col)
    elcolname<-colnames(dataref)[col]
    vectorderefs<-dataref[,col]
    vectordeiterations<-as.numeric(as.character(unlist(lapply(unlist(databyNode, recursive = FALSE), `[`, col))) )
    Probabilities<-NULL
    for (i in 1: length(vectorderefs) ) {
      elvalue<-vectorderefs[i]
      casosPosibles<-length(vectordeiterations)
      casosFavorables<-length(vectordeiterations[vectordeiterations>=elvalue])
      laprob<-casosFavorables/casosPosibles
      Probabilities<-rbind(Probabilities,laprob)
    }
    colnames(Probabilities)<-paste("Prob_",elcolname,sep="")
    rownames(Probabilities)<-seq(1:nrow(Probabilities))
    head(Probabilities)
    TabProbs<-cbind(TabProbs,Probabilities)
  }
  dataref2<-cbind(dataref,TabProbs)
  colnames(dataref2)
  dataref2<-dataref2[,c(1:4,11,5,12,6,13,7,14,8,15,9,16,10)]
  res<- list(SubsetResult=dataref2, MetricsByNodes=databyNode)
  return(res)
}

###########################################################
NodeRetainerinNUll<- function (Data, Actors){
  # Function to retain the nodes per iteration
  # Input:
  # Data: The list of elementes in "MetricsByNodes". It could be a result of the "NullHypothesisTester" or "ProbabilitiesCalculator"
  # Actors: a vector with the entry_names of the nodes to be analyzed
  
  # Output:
  # A data.frame with all the values of the metrics of the reference node by iteration. In other words, Row1 contains node1/iter1/values, Row2 contains node1/iter2/values... and so on.
  LosActores<-NULL
  for (i in 1: length(Actors)){
    print (i)
    namedelactor<-Actors[i]
    print (namedelactor)
    datita<-Data[[namedelactor]]
    
    ElActor<-NULL
    for (iter in 1: length(datita)) {
      namedelaiter<-names(datita)[iter]
      namedelaiter2<-gsub(x = namedelaiter," ", "_")
      print(namedelaiter2)
      
      elactor<-datita[[namedelaiter]][datita[[namedelaiter]]$Label == namedelactor,]
      if (dim(elactor)[1]==0 |dim(elactor)[2]==0) {
        next
      }else {
        elactor$Iteration <-namedelaiter2
        ElActor<-rbind(ElActor,elactor)  
      }
      
    }
    LosActores<-rbind(LosActores,ElActor)
  }
  res<-LosActores
  return (res)
}

###########################################################
pvaluesCalculator<- function (RefData, DistData, vars){
  # Function to calculate the p-values of the dataset created with "ProbabilitiesCalculator"
  # Input:
  # RefData: The data.frame of the "SubsetResult" with the desired nodes.
  # DistData: The  data.frame of the "MetricsByNodes" section obtained from "ProbabilitiesCalculator"
  #vars: a vector indicating the number of the metrics columns to be analyzed
  
  # Output:
  # A data.frame with the metrics values and the p values associated with them. 
  colnamesdeTabdepvals<-precols<-prenamessignifs<-colnamesdeprenamessignifs<-NULL
  for (i in 1:length(vars) ){
    lavarnum<-vars[i]
    Var<-colnames(RefData) [lavarnum]
    precols<-paste("p-val",Var, sep= "_")
    colnamesdeTabdepvals<-c(colnamesdeTabdepvals,precols)
    prenamessignifs<-paste("Signif",Var, sep= "_")
    colnamesdeprenamessignifs<-c(colnamesdeprenamessignifs,prenamessignifs)
  }
  Tabdepvals<-TabdeSignifs<-NULL
  for (i in 1: length(vars)) {
    pvalores<-NULL
    lavarnum<-vars[i]
    Var<-colnames(RefData) [lavarnum]
    print (paste("Analyzing Variable:", Var))
    vectitonulo<-as.numeric(as.character(DistData[,colnames(DistData) == Var]))
    vectitodereferencia<-as.numeric(as.character(RefData[,colnames(RefData) == Var]))
    #Tabdepvals<-data.frame(matrix (NA,ncol = length(vars), nrow=nrow(RefData)))
    pvalores<-Significancias<- NULL
    
    ### t.test
    for (v in 1: length(vectitodereferencia)) {
      valorreferencia<-vectitodereferencia[v]
      prepvalor<-t.test(vectitonulo,mu=valorreferencia)
      elpval<-prepvalor$p.value
      lasignif<-if (elpval>0.05){
        lasignif<-"NS"
      } else if (elpval<=0.05 & elpval >0.01){
        lasignif<-"*"
      } else if (elpval<=0.01 & elpval>0.001){
        lasignif<-"**"
      } else if (elpval<=0.001){
        lasignif<- "***"
      }
      pvalores<-c(pvalores,elpval )
      Significancias<-c(Significancias,lasignif)
    }
    Tabdepvals<-cbind(Tabdepvals,pvalores)
    TabdeSignifs<-cbind(TabdeSignifs,Significancias)
    
  }
  colnames(Tabdepvals)<-colnamesdeTabdepvals
  rownames(Tabdepvals)<-seq(1:nrow(Tabdepvals))
  
  colnames(TabdeSignifs)<-colnamesdeprenamessignifs
  rownames(TabdeSignifs)<-seq(1:nrow(TabdeSignifs))
  
  
  Tabla<-cbind(RefData,Tabdepvals,TabdeSignifs)
  
  res<-Tabla
  return(res)
}

###########################################################
NodeRetainerinNUllPlotter<- function (DataReference,DataNullDist,MetricName,NodeName) {
  # Function to create density plots of a particular metric for a particular node to determine if its behavior is statistically significant
  # Input:
  # DataReference: The metrics values of the reference (DE) features
  # DataNullDist: The metrics values of the reference (DE) features but related with other nodes different from the reference, sapled randomly
  # MetricName: The name of the metric you want to plot. If you want to plot more than one, input them as a vector
  # NodeName: The name of the node you want to plot. If you want to plot more than one node, input them as a vector
  
  # Output:
  # Density plots of the metric behavior for a particular node and the evaluation of its significance
  
  
  vectito<-NULL
  for(i in 1:length (MetricName)) {
    elnum<-which(colnames(DataReference) == MetricName[i])
    vectito<-c(vectito,elnum)
  }
  
  calculo<-pvaluesCalculator (RefData = DataReference,DistData = DataNullDist,vars =vectito )
  
  for (a in 1 : length(NodeName)) {
    nombredelnodo<-NodeName[a]
    print(nombredelnodo)
    for (b in 1:length(MetricName)) {
      nombredelametrica<-MetricName[b]
      print (nombredelametrica)
      datita<-DataNullDist[DataNullDist$Label ==nombredelnodo, ]
      valordelareferencia<-DataReference[DataReference$Label ==nombredelnodo ,colnames(DataReference) == nombredelametrica ]
      equislim<-c(min(valordelareferencia,min(as.numeric(as.character(datita[,colnames(datita) == nombredelametrica]))) ), max(valordelareferencia,max(as.numeric(as.character(datita[,colnames(datita) == nombredelametrica]))) ) )
      namedelasignif<- paste("Signif",nombredelametrica, sep="_")
      density <- density(as.numeric(as.character(datita[,colnames(datita) == nombredelametrica])) ) # returns the density data
      if (equislim[1]==equislim[2]) {
        plot(density, main = paste("Density plot of",nombredelametrica,"for node",nombredelnodo),cex.main=2,cex.lab=1.5, lwd=2) # plots the results
        abline(v=valordelareferencia,lwd =2)
        text(x=equislim[2]-0.08*equislim[2],y=max(density$y)-0.08*max(density$y),labels= round(valordelareferencia,digits = 4),
             col="gray55",
             cex=1.5 )
        text(x=equislim[2]-0.16*equislim[2],y=max(density$y)-0.16*max(density$y),labels= calculo[calculo$Label == nombredelnodo,colnames(calculo)==namedelasignif],
             col="gray55",
             cex=1.5)
      } else{
        if (sum( as.numeric(as.character(datita[,colnames(datita) == nombredelametrica]))  ) == 0) {
          
          plot(density, main = paste("Density plot of",nombredelametrica,"for node",nombredelnodo), xlim=equislim, cex.main=2, cex.lab=1.5,type = "n") # plots the results
          abline(v=0, lwd=2 )
          abline(v=valordelareferencia, lwd=2)
          text(x=equislim[2]-0.08*equislim[2],y=max(density$y)-0.08*max(density$y),labels= round(valordelareferencia,digits = 4),
               col="gray55",
               cex=1.5 )
          text(x=equislim[2]-0.08*equislim[2],y=max(density$y)-0.16*max(density$y),labels= calculo[calculo$Label == nombredelnodo,colnames(calculo)==namedelasignif],
               col="gray55",
               cex=1.5 )
          
          
        } else {
          plot(density, main = paste("Density plot of",nombredelametrica,"for node",nombredelnodo),cex.main=2,cex.lab=1.5, xlim=equislim) # plots the results
          abline(v=valordelareferencia,lwd=2)
          text(x=equislim[2]-0.08*equislim[2],y=max(density$y)-0.08*max(density$y),labels= round(valordelareferencia,digits = 4),
               col="gray55",
               cex=2 )
          text(x=equislim[2]-0.08*equislim[2],y=max(density$y)-0.16*max(density$y),labels= calculo[calculo$Label == nombredelnodo,colnames(calculo)==namedelasignif],
               col="gray55",
               cex=2 )
        }
        
      }
      
    }
    
    
  }
}

###########################################################
InteractionsByStepsCalculator<- function (InteractionsTable, SignificantNodes, Steps = 3, PreviousCalculation=NULL) {
  # Funtion to calculate the interactions by steps that can be provided by the user
  # Input: 
  # InteractionsTable: A table with the information of all possible interactions in a particular species like "All_human_kegg_interactions30march2020.csv"
  # SignificantNodes: A vector with the differentially expressed nodes
  # Steps: Number of steps to be analyzed as a measure of "distance" between nodes.
  # PreviousCalculation: To merge previous calculated data to be able to partition the data analysis
  
  # Output:
  # A list of tables of interacions between nodes, by steps.
  # and a table indicating if the node is significant or not
  
  ####
  
  prety1<-unique(InteractionsTable[,c("entry_type_1","entry_name_1")])
  prety2<-unique(InteractionsTable[,c("entry_type_2","entry_name_2")])
  colnames(prety1) =colnames(prety2) = c("type", "name")
  types<-unique(rbind(prety1,prety2))
  rownames(types)<-seq(1:nrow(types))
  types$Significant<-ifelse(types$name %in% SignificantNodes,"Yes","No")
  
  Allintersnorepeated<-InteractionsTable[,c("entry_name_1","entry_name_2")]
  Allintersnorepeated<-Allintersnorepeated[!duplicated(Allintersnorepeated), ]
  
  
  allactors<-unique(c(as.character(InteractionsTable$entry_name_1), as.character(InteractionsTable$entry_name_2)))
  
  allMetabs<-unique(c(unique(as.character(InteractionsTable$entry_name_1)[InteractionsTable$entry_type_1 == "compound"]),unique(as.character(InteractionsTable$entry_name_2)[InteractionsTable$entry_type_2 == "compound"]) ) )
  
  pretab<-NULL
  for (i in 1:length (allMetabs)){
    print(allMetabs[i])
    actor<-allMetabs[i]
    for (ii in 1:nrow(Allintersnorepeated)) {
      
      ss<-as.vector(Allintersnorepeated[ii,])
      if (length(ss[ss == actor]) == 0) {
        next
      } else {
        Intwith<-ss[ss != actor]
        vectito<-c(actor,Intwith)
        pretab<-rbind(pretab,vectito)
        
        
      }
    }
  }
  rownames(pretab)<- seq(1:nrow(pretab) )
  colnames(pretab)<- c("Actor","Interact_With")                 
  pretab<-as.data.frame(as.matrix(pretab))
  pretab<-pretab [!duplicated (pretab),]
  rownames(pretab)<- seq(1:nrow(pretab) )
  
  pretab
  #culo<-pretab
  #pretab<-culo
  sg=sig=NULL
  for(iii in 1: nrow(pretab) ) {
    if (pretab$Actor[iii] %in% SignificantNodes) {
      sg="Yes"
      sig<-c(sig,sg)
    } else {
      sg="No"
      sig<-c(sig,sg) 
    }
    
  }  
  pretab$Actor_is_Significant<-sig
  
  
  
  sg=sig=NULL
  for(iii in 1: nrow(pretab) ) {
    if (pretab$Interact_With[iii] %in% SignificantNodes) {
      sg="Yes"
      sig<-c(sig,sg)
    } else {
      sg="No"
      sig<-c(sig,sg) 
    }
    
  }  
  pretab$Significant<-sig
  bp<-One_Step<-pretab
  theTables<-list()
  preos<-list(One_Step)
  theTables["One_Step"]<-preos
  bypass<-bp[,1:(ncol(bp)-2)]
  ####
  
  if (Steps>1) {
    print (paste ("Steps",Steps, sep=" "))
    #print("Analyzing more than one step")
    vectorNames<-c ("Two","Three","Four","Five","Six","Seven","Eight","Nine",
                    "Ten","Eleven","Twelve","Thirteen","Fourteen","Fifteen",
                    "Sixteen","Seventeen","Eighteen","Nineteen","Twenty"
                    ,"TwentyOne")
    vectitonumbs<-vectorNames[1:(Steps-1)]
    vectitonames<-paste(vectitonumbs,"Steps", sep="_")
    
    namecolumns<- c("Through","Through2","Through3","Through4","Through5",
                    "Through6","Through7","Through8","Through9","Through10",
                    "Through11","Through12","Through13","Through14","Through15",
                    "Through16","Through17","Through18","Through19","Through20")
    losthrough<-unique(as.vector(One_Step$Interact_With))
    theorder<-c("Actor", "Interact_With", "Through")
    
    for (n in 1:length(vectitonames) ) {
      
      # 1
      subsetS<-InteractionsTable[as.character(InteractionsTable$entry_name_1) %in%losthrough | as.character(InteractionsTable$entry_name_2) %in%losthrough,]
      subsetS2<-subsetS[,c("entry_name_1","entry_name_2")]
      subsetS2<-subsetS2[!duplicated(subsetS2), ]
      # 2
      pretab<-NULL
      for (i in 1:length (losthrough)){
        #for (i in 1:5){
        actor<-losthrough[i]
        print(paste("Actor",actor,":",i, "out of", length(losthrough), sep=" "))
        
        for (ii in 1:nrow(subsetS2)) {
          
          ss<-as.vector(subsetS2[ii,])
          if (length(ss[ss == actor]) == 0) {
            next
          } else {
            Intwith<-ss[ss != actor]
            vectito<-c(Intwith,actor)
            pretab<-rbind(pretab,vectito)
            
            
          }
        }
      }
      rownames(pretab)<- seq(1:nrow(pretab) )
      colnames(pretab)<- c("Interact_With","Through")                 
      pretab<-as.data.frame(as.matrix(pretab))
      pretab<-pretab [!duplicated (pretab),]
      rownames(pretab)<- seq(1:nrow(pretab) )
      pretab
      
      names(pretab)[names(pretab)=="Through"] <- namecolumns[n]
      
      names(bypass)[names(bypass)=="Interact_With"] <- namecolumns[n]
      #culo<-pretab
      #pretab<-culo      
      
      # 3
      pretab2<-merge (pretab,bypass, by.x=2,by.y=2)
      head(pretab2)
      pretab2<-pretab2[!duplicated(pretab2), ]
      dim(pretab2)
      # If somebody is repeated in a row that row has to be eliminated
      pretab3<-NULL
      for (li in 1:nrow(pretab2)) {
        vectito<-as.vector(unlist(pretab2[li,]))
        
        if (length(vectito) !=length(unique(vectito)) ) { 
          next
        } else {
          pretab3<-rbind(pretab3,vectito)
        }
        
      }
      if (is.null(pretab3) ){
        pretab3<-paste("No interactions observed with that number of steps")
      } else {
        pretab3<-as.data.frame(as.matrix(pretab3))
        colnames(pretab3)<- colnames(pretab2)
        rownames(pretab3) <- seq(1: nrow(pretab3))
        pretab3<-pretab3[theorder]
        pretab3<-pretab3[!duplicated(pretab3),]
        
        sg=sig=NULL
        for(iii in 1: nrow(pretab3) ) {
          if (pretab3$Actor[iii] %in% SignificantNodes) {
            sg="Yes"
            sig<-c(sig,sg)
          } else {
            sg="No"
            sig<-c(sig,sg) 
          }
          
        }  
        pretab3$Actor_is_Significant<-sig
        
        
        sg=sig=NULL
        for(iii in 1: nrow(pretab3) ) {
          if (pretab3$Interact_With[iii] %in% SignificantNodes) {
            sg="Yes"
            sig<-c(sig,sg)
          } else {
            sg="No"
            sig<-c(sig,sg) 
          }
          
        }  
        sig
        pretab3$Significant<-sig
      }
      
      
      theTables3<- list(pretab3)
      theTables[vectitonames[n]]<-theTables3
      
      losthrough<-try (unique(as.vector(pretab3$Interact_With)), silent = TRUE)
      if (class(losthrough) == "try-error") {
        break
      }
      
      bypass<-pretab3[,1:(ncol(pretab3)-2)]
      theorder<-c(theorder,namecolumns[n+1])
      print("END of the for loop of steps")
    } # END of the for loop of steps
    print("END of thr If Steps >1")
  } # END of thr If Steps >1
  
  res<-list(Interactions=theTables,Type=types)
  return (res)
}

###########################################################
ProbCalculatorbySteps<- function (List, SignificantNodes) {
  # Funtion to calculate the probabilities by steps
  # Input: 
  # List: All interactions by steps. The result obtained from "InteractionsByStepsCalculator"
  # SignificantNodes: A vector with The DE features
  
  
  # Output:
  # A list of 8 elements:
  # DE_DEByStep: Interaction rates of the differentially expressed features between them
  # DE_X3ByStep: Interaction rates of the differentially expressed features interacting with onother DE feature and in turn, also this one with another DE feature.
  # TabInGeneralTotalbySteps: Interaction rates without indicating if the interaction is with a gene or a compound
  # TabsInGeneralbyPercentilesbySteps: Interaction rates without indicating if the interaction is with a gene or a compound, splitted into percentiles in a cummulative way.
  # TabsInGeneralbyPercentilesNonAccbySteps:  Interaction rates without indicating if the interaction is with a gene or a compound, splitted into percentiles in a NON-cummulative way.
  # TabSpecificTotalbySteps: Interaction rates indicating if the interaction is with a gene or a compound
  # TabsSpecificbyPercentilesbySteps: Interaction rates indicating if the interaction is with a gene or a compound, splitted into percentiles in a cummulative way.
  # TabsSpecificbyPercentilesNonAccbySteps:  Interaction rates indicating if the interaction is with a gene or a compound, splitted into percentiles in a NON-cummulative way.
  ##### DE_DE
  SigniMetabs<-List$Type[List$Type$type == "compound" & List$Type$Significant== "Yes",]
  DE_DEByStep<-list()
  for (nl in 1: length(List$Interactions)) {
    namedelatab<-names(List$Interactions[nl])
    tab<-List$Interactions[[nl]]
    ###
    if (is.data.frame(tab)) {
      TabDE_DE <-NULL
      for (ac in 1: length(SigniMetabs$name)) {
        elnodo<-as.character(SigniMetabs$name[ac])
        
        tabpiece<-tab[tab$Actor == elnodo,]
        DE_DE<-sum(tabpiece$Significant == "Yes")
        NTotal<-nrow(tabpiece)
        LaProb<-round(DE_DE / NTotal, digits = 3)
        #vectito<-c(as.character(elnodo),as.numeric(as.character(DE_DE)),as.numeric(as.character(NTotal)),as.numeric(as.character(LaProb)) )
        vectito<-c(elnodo,DE_DE,NTotal,LaProb )
        TabDE_DE<-rbind(TabDE_DE,vectito)
      }
      #}
      TabDE_DE<-as.data.frame(as.matrix (TabDE_DE))
      rownames(TabDE_DE)<-seq (1:nrow(TabDE_DE))
      colnames(TabDE_DE)<-c("Node","DE_DE","NTotal","Frequency")
      
      preTabDE_DE<-list(TabDE_DE)
      DE_DEByStep[namedelatab]<-preTabDE_DE
      #print ("fin de la ronda")
    } else {
      preTabDE_DE<-list(tab)
      DE_DEByStep[namedelatab]<-preTabDE_DE
      ####
    }
  }
  ##### END of DE_DE
  ##### DE_DE_DE
  if (length(List$Interactions)>1 ) {
    DEx3ByStep<-list()
    for (nl in 2: length(List$Interactions)) {
      namedelatab<-names(List$Interactions[nl])
      tab<-List$Interactions[[nl]]
      if (is.data.frame(tab)) {
        TabDEX3<-NULL
        for (tbc in 1:length(SigniMetabs$name) ) {
          elnodo<-as.character(SigniMetabs$name[tbc])
          
          tabpiece<-tab[tab$Actor == elnodo,]
          NTotal<-nrow(tabpiece)
          if (nrow(tabpiece) == 0 ) {
            Dex3 = 0
          } else {
            Dex3=0
            for (nr in 1:nrow(tabpiece)) {
              vc<-as.vector(unlist(tabpiece[nr,1:(ncol(tabpiece)-2)]))
              
              if (sum(vc %in% SignificantNodes) == length(vc) ) {
                dex3<-1
              } else {
                dex3<-0
              }
              Dex3<- sum(Dex3,dex3)
            }
          }
          LaProb<-round(Dex3 / NTotal, digits = 3)
          vectito<-c(elnodo,Dex3,NTotal,LaProb )
          TabDEX3<-rbind(TabDEX3,vectito)
        } 
        TabDEX3<-as.data.frame(as.matrix (TabDEX3))
        rownames(TabDEX3)<-seq (1:nrow(TabDEX3))
        colnames(TabDEX3)<-c("Node","All_DE","NTotal","Frequency")
        
        preTabDEX3<-list(TabDEX3)
        DEx3ByStep[namedelatab]<-preTabDEX3
        
      } else {
        preTabDEX3<-list(tab)
        DEx3ByStep[namedelatab]<-preTabDEX3
      }
    }
    ##### END of DE_DE_DE
  } else {
    DEx3ByStep = NULL
  }
  
  ##### Summary of Interaction probabilities
  ########## Summary in General
  TabInGeneralTotalbySteps<-TabsbyPercentilesbySteps<-TabsbyPercentilesNonAccbySteps <-NULL
  for (nl in 1: length(List$Interactions)) {
    namedelatab<-names(List$Interactions[nl])
    tab<-List$Interactions[[nl]]
    ###
    if (is.data.frame(tab)) {
      
      actores<-c(length(as.character(unique(tab$Actor[tab$Actor_is_Significant == "Yes"]) )),length(as.character(unique(tab$Actor[tab$Actor_is_Significant == "No"]) ) ) )
      
      thequantiles<-as.numeric(as.character(round(quantile(as.numeric(as.character(table(as.character(tab$Actor[tab$Actor_is_Significant == "Yes"])))) ,probs = c(0.1,.25,.5,.75,.9,1)),digits = 0) ))
      namesdequantiles<-names(quantile(as.numeric(as.character(table(as.character(tab$Actor[tab$Actor_is_Significant == "Yes"])))) ,probs = c(0.1,.25,.5,.75,.9,1)))
      
      TablaSig<-tab[tab$Actor_is_Significant == "Yes", ]
      TablaNoSig<-tab[tab$Actor_is_Significant == "No", ]
      TablaSig_Sig<-tab[tab$Actor_is_Significant == "Yes" & tab$Significant == "Yes", ]
      TablaSig_NoSig<-tab[tab$Actor_is_Significant == "Yes" & tab$Significant == "No", ]
      TablaNoSig_Sig<-tab[tab$Actor_is_Significant == "No" & tab$Significant == "Yes", ]
      TablaNoSig_NoSig<-tab[tab$Actor_is_Significant == "No" & tab$Significant == "No", ]
      
      ############### in General/Total
      NodesSignifs<-c(length(unique(TablaSig_Sig$Interact_With)),length(unique(TablaNoSig_Sig$Interact_With)))
      NodesNOSignifs<-c(length(unique(TablaSig_NoSig$Interact_With)),length(unique(TablaNoSig_NoSig$Interact_With)))
      TabInGeneralTotal<-cbind(actores,NodesSignifs,NodesNOSignifs)
      rownames(TabInGeneralTotal)<-c("Significant","Non_Significant")
      colnames(TabInGeneralTotal)<-c("Metabolites","Significant_Nodes","Non_Significant_Nodes")
      TabInGeneralTotal
      TabInGeneralTotalsas<-list(TabInGeneralTotal)
      TabInGeneralTotalbySteps[namedelatab]<-TabInGeneralTotalsas
      ############### END of in General/Total
      ############### in General/Fragmented
      #################### in General/Fragmented/Accumulated
      TabsbyPercentiles<-NULL
      for (qu in 1:length(thequantiles)) {
        cuantil<-thequantiles[qu]
        namecitoP<-paste("Global_Accumulated_Analysis_P",namesdequantiles[qu],": until ",cuantil," edges", sep="")
        Csig<-names(table(as.character(TablaSig$Actor))[table(as.character(TablaSig$Actor)) <= cuantil])
        CNosig<-names(table(as.character(TablaNoSig$Actor))[table(as.character(TablaNoSig$Actor)) <= cuantil])
        Pactores<- c(length(Csig),length(CNosig))
        
        PrenodesSig_Sig<-TablaSig_Sig[TablaSig_Sig$Actor %in% Csig,]
        PrenodesNoSig_Sig<-TablaNoSig_Sig[TablaNoSig_Sig$Actor %in% CNosig,]
        PNodesSignifs<-c(length(unique(PrenodesSig_Sig$Interact_With)),length(unique(PrenodesNoSig_Sig$Interact_With)))
        
        PrenodesSig_NoSig<-TablaSig_NoSig[TablaSig_NoSig$Actor %in% Csig,]
        PrenodesNoSig_NoSig<-TablaNoSig_NoSig[TablaNoSig_NoSig$Actor %in% CNosig,]
        PNodesNoSignifs<-c(length(unique(PrenodesSig_NoSig$Interact_With)),length(unique(PrenodesNoSig_NoSig$Interact_With)))
        
        TabInGeneralbyP<-cbind(Pactores,PNodesSignifs,PNodesNoSignifs)
        rownames(TabInGeneralbyP)<-c("Significant","Non_Significant")
        colnames(TabInGeneralbyP)<-c("Metabolites","Significant_Nodes","Non_Significant_Nodes")
        TabInGeneralbyP 
        tabsP<- list(TabInGeneralbyP)
        TabsbyPercentiles[namecitoP]<-tabsP
        TabsbyPercentilessas<-list(TabsbyPercentiles)
        TabsbyPercentilesbySteps[namedelatab]<-TabsbyPercentilessas
      }
      #################### END of in General/Fragmented/Accumulated
      #################### in General/Fragmented/NonAccumulated
      TabsbyPercentilesNonAcc<-NULL
      prevqu<-0
      for (qu in 1:length(thequantiles)) {
        cuantil<-thequantiles[qu]
        namecitoP<-paste("Global_Non_Accumulated_Analysis_P",namesdequantiles[qu],": from ",prevqu+1, " to ",cuantil," edges", sep="")
        Csig<-names(table(as.character(TablaSig$Actor))[ table(as.character(TablaSig$Actor)) > prevqu & table(as.character(TablaSig$Actor)) <= cuantil])
        CNosig<-names(table(as.character(TablaNoSig$Actor))[table(as.character(TablaNoSig$Actor)) > prevqu & table(as.character(TablaNoSig$Actor)) <= cuantil])
        Pactores<- c(length(Csig),length(CNosig))
        
        PrenodesSig_Sig<-TablaSig_Sig[TablaSig_Sig$Actor %in% Csig,]
        PrenodesNoSig_Sig<-TablaNoSig_Sig[TablaNoSig_Sig$Actor %in% CNosig,]
        PNodesSignifs<-c(length(unique(PrenodesSig_Sig$Interact_With)),length(unique(PrenodesNoSig_Sig$Interact_With)))
        
        PrenodesSig_NoSig<-TablaSig_NoSig[TablaSig_NoSig$Actor %in% Csig,]
        PrenodesNoSig_NoSig<-TablaNoSig_NoSig[TablaNoSig_NoSig$Actor %in% CNosig,]
        PNodesNoSignifs<-c(length(unique(PrenodesSig_NoSig$Interact_With)),length(unique(PrenodesNoSig_NoSig$Interact_With)))
        
        TabInGeneralbyPNonAcc<-cbind(Pactores,PNodesSignifs,PNodesNoSignifs)
        rownames(TabInGeneralbyPNonAcc)<-c("Significant","Non_Significant")
        colnames(TabInGeneralbyPNonAcc)<-c("Metabolites","Significant_Nodes","Non_Significant_Nodes")
        TabInGeneralbyPNonAcc 
        tabsPNonAcc<- list(TabInGeneralbyPNonAcc)
        TabsbyPercentilesNonAcc[namecitoP]<-tabsPNonAcc
        TabsbyPercentilesNonAccsas<-list(TabsbyPercentilesNonAcc)
        TabsbyPercentilesNonAccbySteps[namedelatab]<-TabsbyPercentilesNonAccsas
        
        prevqu<-cuantil
      }
      
    } else {
      preTabInGeneralTotalbySteps<-list (tab)
      TabInGeneralTotalbySteps[namedelatab]<-preTabInGeneralTotalbySteps
      preTabsbyPercentilesbySteps<-list(tab)
      TabsbyPercentilesbySteps[namedelatab]<-preTabsbyPercentilesbySteps
      preTabsbyPercentilesNonAccbySteps<-list(tab)
      TabsbyPercentilesNonAccbySteps[namedelatab]<-preTabsbyPercentilesNonAccbySteps
      
    }
  }
  #################### END of in General/Fragmented/NonAccumulated
  ############### END of in General/Fragmented
  ########## END of Summary in General
  ########## Specific Summary
  
  
  TabSpecificTotalbySteps<-TabsSpecificbyPercentilesbySteps<-TabsSpecificbyPercentilesNonAccbySteps <-NULL
  for (nl in 1: length(List$Interactions)) {
    namedelatab<-names(List$Interactions[nl])
    tab<-List$Interactions[[nl]]
    
    ###
    if (is.data.frame(tab)) {
      
      actores<-c(length(as.character(unique(tab$Actor[tab$Actor_is_Significant == "Yes"]) )),length(as.character(unique(tab$Actor[tab$Actor_is_Significant == "No"]) ) ) )
      
      thequantiles<-as.numeric(as.character(round(quantile(as.numeric(as.character(table(as.character(tab$Actor[tab$Actor_is_Significant == "Yes"])))) ,probs = c(0.1,.25,.5,.75,.9,1)),digits = 0) ))
      namesdequantiles<-names(quantile(as.numeric(as.character(table(as.character(tab$Actor[tab$Actor_is_Significant == "Yes"])))) ,probs = c(0.1,.25,.5,.75,.9,1)))
      
      TablaSig<-tab[tab$Actor_is_Significant == "Yes", ]
      TablaNoSig<-tab[tab$Actor_is_Significant == "No", ]
      
      TablaSig_Sig<-tab[tab$Actor_is_Significant == "Yes" & tab$Significant == "Yes", ]
      TablaSig_Sig<-merge(TablaSig_Sig,List$Type, by.x="Interact_With",by.y="name")
      TablaSig_NoSig<-tab[tab$Actor_is_Significant == "Yes" & tab$Significant == "No", ]
      TablaSig_NoSig<-merge(TablaSig_NoSig,List$Type, by.x="Interact_With",by.y="name")
      TablaNoSig_Sig<-tab[tab$Actor_is_Significant == "No" & tab$Significant == "Yes", ]
      TablaNoSig_Sig<-merge(TablaNoSig_Sig,List$Type, by.x="Interact_With",by.y="name")
      TablaNoSig_NoSig<-tab[tab$Actor_is_Significant == "No" & tab$Significant == "No", ]
      TablaNoSig_NoSig<-merge(TablaNoSig_NoSig,List$Type, by.x="Interact_With",by.y="name")
      
      ############### Specific/Total
      GenesSignifs<-c(length(unique(as.character(TablaSig_Sig$Interact_With[TablaSig_Sig$type == "gene"]))),length(unique(as.character(TablaNoSig_Sig$Interact_With[TablaNoSig_Sig$type == "gene"]))) )
      GenesNOSignifs<-c(length(unique(as.character(TablaSig_NoSig$Interact_With[TablaSig_NoSig$type == "gene"]))),length(unique(as.character(TablaNoSig_NoSig$Interact_With[TablaNoSig_NoSig$type == "gene"]))) )
      
      MetabsSignifs<-c(length(unique(as.character(TablaSig_Sig$Interact_With[TablaSig_Sig$type == "compound"]))),length(unique(as.character(TablaNoSig_Sig$Interact_With[TablaNoSig_Sig$type == "compound"]))) )
      MetabsNOSignifs<-c(length(unique(as.character(TablaSig_NoSig$Interact_With[TablaSig_NoSig$type == "compound"]))),length(unique(as.character(TablaNoSig_NoSig$Interact_With[TablaNoSig_NoSig$type == "compound"]))) )
      
      
      
      TabSpecificTotal<-cbind(actores,GenesSignifs,GenesNOSignifs,MetabsSignifs,MetabsNOSignifs)
      rownames(TabSpecificTotal)<-c("Significant","Non_Significant")
      colnames(TabSpecificTotal)<-c("Metabolites","Significant_Genes","Non_Significant_Genes","Significant_Metabolites","Non_Significant_Metabolites")
      TabSpecificTotal
      TabSpecificTotalsas<-list(TabSpecificTotal)
      TabSpecificTotalbySteps[namedelatab]<-TabSpecificTotalsas
      
      ############### END of Specific/Total
      
      ############### Specific/Fragmented
      #################### Specific/Fragmented/Accumulated
      
      TabsSpecificbyPercentiles<-NULL
      for (qu in 1:length(thequantiles)) {
        cuantil<-thequantiles[qu]
        namecitoP<-paste("Specific_Accumulated_Analysis_P",namesdequantiles[qu],": until ",cuantil," edges", sep="")
        Csig<-names(table(as.character(TablaSig$Actor))[table(as.character(TablaSig$Actor)) <= cuantil])
        CNosig<-names(table(as.character(TablaNoSig$Actor))[table(as.character(TablaNoSig$Actor)) <= cuantil])
        Pactores<- c(length(Csig),length(CNosig))
        
        PrenodesSig_Sig<-TablaSig_Sig[TablaSig_Sig$Actor %in% Csig,]
        PrenodesNoSig_Sig<-TablaNoSig_Sig[TablaNoSig_Sig$Actor %in% CNosig,]
        PrenodesSig_NoSig<-TablaSig_NoSig[TablaSig_NoSig$Actor %in% Csig,]
        PrenodesNoSig_NoSig<-TablaNoSig_NoSig[TablaNoSig_NoSig$Actor %in% CNosig,]
        
        PGenesSignifs<-c(length(unique(as.character(PrenodesSig_Sig$Interact_With[PrenodesSig_Sig$type == "gene"]))),length(unique(as.character(PrenodesNoSig_Sig$Interact_With[PrenodesNoSig_Sig$type == "gene"]))))
        PGenesNOSignifs<-c(length(unique(as.character(PrenodesSig_NoSig$Interact_With[PrenodesSig_NoSig$type == "gene"]))),length(unique(as.character(PrenodesNoSig_NoSig$Interact_With[PrenodesNoSig_NoSig$type == "gene"]))))
        
        PMetabsSignifs<-c(length(unique(as.character(PrenodesSig_Sig$Interact_With[PrenodesSig_Sig$type == "compound"]))),length(unique(as.character(PrenodesNoSig_Sig$Interact_With[PrenodesNoSig_Sig$type == "compound"]))))
        PMetabsNOSignifs<-c(length(unique(as.character(PrenodesSig_NoSig$Interact_With[PrenodesSig_NoSig$type == "compound"]))),length(unique(as.character(PrenodesNoSig_NoSig$Interact_With[PrenodesNoSig_NoSig$type == "compound"]))))
        
        
        TabSpecificbyP<-cbind(Pactores,PGenesSignifs,PGenesNOSignifs,PMetabsSignifs,PMetabsNOSignifs)
        rownames(TabSpecificbyP)<-c("Significant","Non_Significant")
        colnames(TabSpecificbyP)<-c("Metabolites","Significant_Genes","Non_Significant_Genes","Significant_Metabolites","Non_Significant_Metabolites")
        TabSpecificbyP 
        tabsP<- list(TabSpecificbyP)
        TabsSpecificbyPercentiles[namecitoP]<-tabsP
        TabsbyPercentilessas<-list(TabsSpecificbyPercentiles)
        TabsSpecificbyPercentilesbySteps[namedelatab]<-TabsbyPercentilessas
      }
      #################### END of Specific/Fragmented/Accumulated
      #################### Specific/Fragmented/NonAccumulated
      
      TabsSpecificbyPercentilesNonAcc<-NULL
      prevqu<-0
      for (qu in 1:length(thequantiles)) {
        cuantil<-thequantiles[qu]
        namecitoP<-paste("Specific_Non_Accumulated_Analysis_P",namesdequantiles[qu],": from ",prevqu+1, " to ",cuantil," edges", sep="")
        Csig<-names(table(as.character(TablaSig$Actor))[ table(as.character(TablaSig$Actor)) > prevqu & table(as.character(TablaSig$Actor)) <= cuantil])
        CNosig<-names(table(as.character(TablaNoSig$Actor))[table(as.character(TablaNoSig$Actor)) > prevqu & table(as.character(TablaNoSig$Actor)) <= cuantil])
        Pactores<- c(length(Csig),length(CNosig))
        
        PrenodesSig_Sig<-TablaSig_Sig[TablaSig_Sig$Actor %in% Csig,]
        PrenodesNoSig_Sig<-TablaNoSig_Sig[TablaNoSig_Sig$Actor %in% CNosig,]
        PrenodesSig_NoSig<-TablaSig_NoSig[TablaSig_NoSig$Actor %in% Csig,]
        PrenodesNoSig_NoSig<-TablaNoSig_NoSig[TablaNoSig_NoSig$Actor %in% CNosig,]
        
        PGenesSignifs<-c(length(unique(as.character(PrenodesSig_Sig$Interact_With[PrenodesSig_Sig$type == "gene"]))),length(unique(as.character(PrenodesNoSig_Sig$Interact_With[PrenodesNoSig_Sig$type == "gene"]))))
        PGenesNOSignifs<-c(length(unique(as.character(PrenodesSig_NoSig$Interact_With[PrenodesSig_NoSig$type == "gene"]))),length(unique(as.character(PrenodesNoSig_NoSig$Interact_With[PrenodesNoSig_NoSig$type == "gene"]))))
        
        PMetabsSignifs<-c(length(unique(as.character(PrenodesSig_Sig$Interact_With[PrenodesSig_Sig$type == "compound"]))),length(unique(as.character(PrenodesNoSig_Sig$Interact_With[PrenodesNoSig_Sig$type == "compound"]))))
        PMetabsNOSignifs<-c(length(unique(as.character(PrenodesSig_NoSig$Interact_With[PrenodesSig_NoSig$type == "compound"]))),length(unique(as.character(PrenodesNoSig_NoSig$Interact_With[PrenodesNoSig_NoSig$type == "compound"]))))
        
        
        TabSpecificbyPNonAcc<-cbind(Pactores,PGenesSignifs,PGenesNOSignifs,PMetabsSignifs,PMetabsNOSignifs)
        rownames(TabSpecificbyPNonAcc)<-c("Significant","Non_Significant")
        colnames(TabSpecificbyPNonAcc)<-c("Metabolites","Significant_Genes","Non_Significant_Genes","Significant_Metabolites","Non_Significant_Metabolites")
        TabSpecificbyPNonAcc 
        tabsSpecificPNonAcc<- list(TabSpecificbyPNonAcc)
        TabsSpecificbyPercentilesNonAcc[namecitoP]<-tabsSpecificPNonAcc
        TabsSpecificbyPercentilesNonAccsas<-list(TabsSpecificbyPercentilesNonAcc)
        TabsSpecificbyPercentilesNonAccbySteps[namedelatab]<-TabsSpecificbyPercentilesNonAccsas
        
        prevqu<-cuantil
      }
      
    } else {
      preTabSpecificTotalbySteps<-list (tab)
      TabSpecificTotalbySteps[namedelatab]<-preTabSpecificTotalbySteps
      preTabsSpecificbyPercentilesbySteps<-list(tab)
      TabsSpecificbyPercentilesbySteps[namedelatab]<-preTabsSpecificbyPercentilesbySteps
      preTabsSpecificbyPercentilesNonAccbySteps<-list(tab)
      TabsSpecificbyPercentilesNonAccbySteps[namedelatab]<-preTabsSpecificbyPercentilesNonAccbySteps
    }
  }
  #################### END of Specific/Fragmented/NonAccumulated
  ############### END of Specific/Fragmented
  ########## END of Specific Summary
  
  ##### END of Summary of Interaction probabilities
  
  res<-list (DE_DEByStep=DE_DEByStep, DEx3ByStep=DEx3ByStep,
             TabInGeneralTotalbySteps=TabInGeneralTotalbySteps,
             TabsInGeneralbyPercentilesbySteps=TabsbyPercentilesbySteps, 
             TabsInGeneralbyPercentilesNonAccbySteps=TabsbyPercentilesNonAccbySteps,
             TabSpecificTotalbySteps=TabSpecificTotalbySteps,
             TabsSpecificbyPercentilesbySteps=TabsSpecificbyPercentilesbySteps,
             TabsSpecificbyPercentilesNonAccbySteps=TabsSpecificbyPercentilesNonAccbySteps
             
  )
  return(res)
}


###########################################################
# Functions Deprecated
Boxplotter<- function (L, Metric) {
  Tabelonga<-tabelita<-Lametrica<-NULL
  for (li in 1: length(L)) {
    print (names(L[li]))
    namecito<-names(L[li])
    Lametrica<-L[[li]][,Metric ]
    #tabelita<-L[[li]][,c(2,3,4) ]
    tabelita<-L[[li]][,c(1,2,3) ]
    tabelita<-cbind(tabelita,Lametrica)
    colnames(tabelita)[ncol(tabelita)]<-Metric
    tabelita<-cbind(tabelita,rep(namecito,nrow(tabelita) ))
    colnames(tabelita)[ncol(tabelita)]<-"Species"
    Tabelonga<-rbind(Tabelonga,tabelita)
  }
  return (Tabelonga)
}

###########################################################
FeatureMeanCalculator<- function (Dat,grouping) {
  class (grouping)
  Datita<- merge(grouping,Dat, by=0);rownames(Datita)<-Datita[,1];Datita<-Datita[,-1]
  elgroup<-colnames(Datita)[1]
  DatitaMean<-aggregate(. ~ Datita[,1] , data = Datita, FUN = mean);DatitaMean<-DatitaMean[,-1]
  colnames(DatitaMean)[1]<-"Groups"
  return (DatitaMean)
  
}

###########################################################
WishedMetrictoPlot<- function (Data, metric ) {
  colvector<-c("Species","Type",metric)
  colvector<-unique(colvector)
  TheBigTables<-list()
  namecitodepercentile3<-namecitodepercentile2<-NULL
  oldtamanio<-0
  for (i in 1 : length( Data)) {
    #for (i in 1 : 3) {
    namecitodepercentile<-names(Data)[i]
    print(namecitodepercentile)
    BigTable<-NULL
    #for (ii in 1: 200) {
    for (ii in 1: length (Data[[i]])) { 
      namecitodeIter<-names(Data[[i]][ii])
      namecitodeIter<-gsub(x = namecitodeIter," ", "_")
      print(namecitodeIter)
      head(Data[[i]][[ii]])
      smtab<-Data[[i]][[ii]][,colnames(Data[[i]][[ii]]) %in% colvector]
      smtab$Iter<-rep(namecitodeIter, nrow(smtab))
      smtab$Percentile<-rep(namecitodepercentile, nrow(smtab))
      #print(dim(smtab))
      BigTable<-rbind(BigTable,smtab)
      #print(dim(BigTable))
      tamanio<-dim(BigTable)[1]
      
      
    }
    #print(paste("DimdeBigTable",dim(BigTable)[1]) )
    #print(paste("tamanio:",tamanio))
    #namecitodepercentile2<-c(namecitodepercentile2,rep(namecitodepercentile, (tamanio- oldtamanio) ) )
    #print(paste("oldtamanio:",oldtamanio))
    #print(paste("difference tamanio - oldtamanio:", (tamanio - oldtamanio) ) )
    BTSAS<-list(BigTable)
    TheBigTables[namecitodepercentile]<-BTSAS
    #namecitodepercentile3<-c(namecitodepercentile3,namecitodepercentile2)
    oldtamanio<-tamanio
    #print (paste("lengthdepercentil2",length(namecitodepercentile2)) )
    #print (paste("lengthdepercentil3",length(namecitodepercentile3)) )
    #print("Next round")
  }
  print("R-binding all tables")
  BigBigTable<-do.call(rbind, TheBigTables)
  rownames(BigBigTable)<-seq(1:nrow(BigBigTable))
  #BigTable$Percentile<-namecitodepercentile2
  res<- BigBigTable
  return (res)
}

# END
