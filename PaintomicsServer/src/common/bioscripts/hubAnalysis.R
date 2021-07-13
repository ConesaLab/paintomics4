#!/usr/bin/env Rscript

SignificanceTestbyMetabolite<- function(UserDataset, UserDEfeatures,dir,iter){
  ################################################
  # Step 1: Removing interactions with  Map
  #dim(kegg_interactions) # 122875 x 9
  hknomap1<-kegg_interactions[kegg_interactions$entry_type_1 != "map",]
  keggNoMap<-hknomap1[hknomap1$entry_type_2 != "map",]
  table(keggNoMap$entry_type_1)
  table(keggNoMap$entry_type_2)
  dim(keggNoMap) # 120667 x 9... 122875 - 120667 = 2208 map links eliminated
  
  ################################################
  # Determining the number of differentially expressed metabolites 
  prety1<-unique(keggNoMap[,c("entry_type_1","entry_name_1")])
  prety2<-unique(keggNoMap[,c("entry_type_2","entry_name_2")])
  colnames(prety1) =colnames(prety2) = c("type", "name")
  types<-unique(rbind(prety1,prety2))
  rownames(types)<-seq(1:nrow(types))
  typesC<-types[types$type == "compound",]
  typesG<-types[!(types$type == "compound"),]
  
  # Differentially expressed metabolites
  DEm<-UserDEfeatures[is.element(UserDEfeatures,typesC$name)] 
  
  # Differentially expressed genes
  DEg<-UserDEfeatures[is.element(UserDEfeatures,typesG$name)]
  
  
  PRETAB2<-NULL
  for (i in 1: length (DEm) ){
    elcompound<-DEm[i]
    load(paste(dir,"/",elcompound,".RData",sep=''))
    theTables
    pretab<-PRETAB<-NULL
    for (ii in 1: length(theTables)){
      elstep<-names(theTables[[ii]])
      losnodos<-theTables[[ii]][[1]]
      losDEs<-losnodos[is.element(losnodos,UserDEfeatures)]
      preNODE<-losnodos[!(is.element(losnodos,UserDEfeatures))]
      losNODE<-preNODE[is.element(preNODE,UserDataset)]
      numblosDEs<-length(losDEs)
      numblosNODE<-length(losNODE)
      
      prcnt<-round(numblosDEs/(numblosDEs+numblosNODE), digits = 3)
      pretab<-cbind(elcompound,elstep,numblosDEs,numblosNODE,prcnt)
      PRETAB<-rbind(PRETAB,pretab)
    }
    PRETAB2<-rbind(PRETAB2,PRETAB)
  }
  PRETAB2<-data.frame(PRETAB2)
  rownames(PRETAB2)<-seq(1:nrow(PRETAB2))
  colnames(PRETAB2)<-c("Metabolite", "Step", "DE_neighbors", "not_DE_neighbors","Percentage")
  PRETAB2
  
  ################################################
  # Randomization of label "Differentially expressed" in the same size and iterated 100X
  
  BIGtabresumiterations<-NULL
  tabresumiterations<-NULL
  for(i in 1: length(DEm)) {
    elcompound<-DEm[i]
    load(paste(dir,"/",elcompound,".RData",sep=''))
    
    tpretab<-tPRETAB<-tPRETAB2<-NULL
    
    for (ii in 1: length(theTables)){
      elstep<-names(theTables[[ii]])
      losnodos<-theTables[[ii]][[1]]
      
      for (r in 1: iter){
        print (paste("iter",r, sep =" ") )
        SupposedUserDEfeatures<-sample(x = UserDataset,size = length(UserDEfeatures)-1)
        SupposedUserDEfeatures<-c(elcompound,SupposedUserDEfeatures)
        losDEs <- losnodos[is.element(losnodos,SupposedUserDEfeatures)]
        preNODE <- losnodos[!(is.element(losnodos,SupposedUserDEfeatures))]
        losNODE <- preNODE[is.element(preNODE,UserDataset)]
        numblosDEs <- length(losDEs)
        numblosNODE <- length(losNODE)
        prcnt <- formatC(numblosDEs/(numblosDEs+numblosNODE),  format = "e", digits = 2)
        tpretab <- cbind(elcompound,elstep,numblosDEs,numblosNODE,prcnt)
        tPRETAB <- rbind(tPRETAB,tpretab)
      }
      tPRETAB2 <- tPRETAB
      #tPRETAB2<-data.frame(tPRETAB2)
      #rownames(tPRETAB2)<-seq(1:nrow(tPRETAB2))
      #colnames(tPRETAB2)<-c("Metabolite", "Step", "DE_neighbors", "not_DE_neighbors","Percentage")
    }
    print("tPRETAB2")
    print(tPRETAB2)
    for (lu in 1:length(unique(tPRETAB2[,2]))){
      elstep<-as.character(unique(tPRETAB2[,2])[lu])
      minitab<-tPRETAB2[tPRETAB2[,2] == elstep,]
      vecDEneighbors<-as.vector(minitab[,3])
      vecNOTDEneighbors<-as.vector(minitab[,4])
      pval <- tryCatch(
        {
          pval <- t.test(x=as.numeric(as.character(vecDEneighbors)),mu=as.numeric(as.character(PRETAB2$DE_neighbors[lu])))$p.value
          pval <- formatC(pval, format = "e", digits = 2)
        }, 
        error = function(e) 
        {
          pval <- 1
          return(pval)
        }
      )
      # Agregar Multiple Testing Correction 
      met<-as.character(unique(minitab[,1]))
      DEn<-round(mean(as.numeric(as.character(minitab[,3]))), digits = 0)
      notDEn<-round(mean(as.numeric(as.character(minitab[,4]))), digits = 0)
      prcnt<-formatC(DEn/(DEn+notDEn), format = "e", digits = 2)
      pretabresumiterations<-cbind(RMetabolite=elcompound,RStep=elstep,RDE_neighbors=DEn,Rnot_DE_neighbors=notDEn,RPercentage=prcnt,P_value=pval)
      
      tabresumiterations<-rbind(tabresumiterations,pretabresumiterations)
      colnames(tabresumiterations)<- colnames(pretabresumiterations)
    }
  }
  tabresumiterations<-data.frame(tabresumiterations)
  p.adj<-formatC(p.adjust(as.numeric(as.character(tabresumiterations$P_value)), "BH"), format = "e", digits = 2)
  tabresumiterations$p.adj<-p.adj
  rownames(tabresumiterations)<-seq(1:nrow(tabresumiterations))
  colnames(tabresumiterations)<-c("RMetabolite", "RStep", "RDE_neighbors", "Rnot_DE_neighbors","RPercentage", "P_value","P_adjusted")
  
  FinalTable<- cbind (PRETAB2,tabresumiterations)
  FinalTable<-FinalTable[,-c(6,7)]
  return (FinalTable)
}

args <- commandArgs(T)
parseArgs <- function(x) strsplit(sub("^--", "", gsub("\"", "", x)), "=")
#args = parseArgs(args)

argsDF <- as.data.frame(do.call("rbind", parseArgs(args)), stringsAsFactors=F)
argsL <- as.list(as.character(argsDF$V2))
names(argsL) <- argsDF$V1
args <- as.data.frame(argsL, stringsAsFactors=F)

kegg_interactions = read.csv(paste0(args$inputDir,"kegg_interaction.csv"), sep = ',')
userDataset = read.table(paste0(args$data_dir,"userDataset.csv"), sep = ',')
userDataset<- as.vector(t(userDataset))
userDEfeatures = read.table(paste0(args$data_dir,"userDEfeatures.csv"), sep = ',')
userDEfeatures <- as.vector(t(userDEfeatures))
result<-SignificanceTestbyMetabolite(UserDataset=userDataset,UserDEfeatures=userDEfeatures, dir=args$inputDir, iter=5)
print(result)
output_file <- paste0(args$data_dir, "/hub_result.csv")
write.table(result, file=output_file, quote = FALSE, sep="\t", row.names = FALSE, col.names = FALSE)

