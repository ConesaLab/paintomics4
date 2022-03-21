from math import log
from scipy.stats import chi2, fisher_exact, combine_pvalues
from statsmodels.sandbox.stats.multicomp import multipletests
##*******************************************************************************************
##****AUXLIAR FUNCTION DEFINITION************************************************************
##*******************************************************************************************
def calculateSignificance(test, totalFeatures, totalRelevantFeatures, totalFeaturesInPathway, totalRelevantFeaturesInPathway):
    if test == "fisher":
        return calculateFisher(totalFeatures, totalFeaturesInPathway, totalRelevantFeatures, totalRelevantFeaturesInPathway)
    else:
        raise NotImplementedError

def calculateCombinedSignificancePvalue(combinedTest, significanceValuesList):
    if len(significanceValuesList) < 2: #Do not calculate if only one omic
        return None
    elif combinedTest == "fisher-combined":
        return calculateCombinedFisher(significanceValuesList)
    else:
        raise NotImplementedError

def calculateFisher(totalElems, foundElems, totalSignificative, foundSignificative):
    foundNoSig = foundElems - foundSignificative
    notFoundSig = totalSignificative - foundSignificative
    notFoundNoSig = (totalElems - foundElems) - notFoundSig

    #___________| DE | Not DE |
    #     Found |    |        |
    # Not Found |    |        |
    #TODO: WHY RIGHT TAIL?
    p = fisher_exact([[foundSignificative, foundNoSig],[notFoundSig, notFoundNoSig]], 'greater')[1]
    return p

def calculateCombinedFisher(significanceValuesList):
    #X^2_2k ~ -2 * sum(ln(p_i))


    accumulatedValue = 0
    for significanceValues in significanceValuesList:
        accumulatedValue += log(significanceValues[2])

    accumulatedValue = accumulatedValue * -2

    return(chi2.sf(accumulatedValue, 2*len(significanceValuesList)))

# fdr_bh (default), fdr_by, nada
def adjustPvalues(pvaluesList):
    # Returns array [reject, pvals_corrected, alphacSidak, alphacBonf]
    adjust_methods = {'fdr_bh': 'FDR BH', 'fdr_by': 'FDR BY'}
    adjusted_pvalues = {adjust_methods[adjust_method]: dict(zip(pvaluesList.keys(), multipletests(list(pvaluesList.values()), method = adjust_method)[1].tolist())) for adjust_method in adjust_methods.keys()}

    return adjusted_pvalues


def calculateStoufferCombinedPvalue(pvalues, weights):
    # Stouffer method cannot deal with p-values equal to 1, returning Nan
    # Prevent that by removing a small value in those cases
    curatedPvalues = [min(pvalue[2], 0.9999999999) if type(pvalue) is list else min(pvalue, 0.9999999999) for pvalue in pvalues]

    # P-value in third position ([nFeatures, nRelevantFeatures, pValue])
    combinedPvalue = combine_pvalues(curatedPvalues, 'stouffer', weights)

    return combinedPvalue[1]

def calculateCombinedSignificancePvalues(significanceValuesList, stouferWeights):
    combined_methods = {
        'Fisher': calculateCombinedFisher(significanceValuesList),
        'Stouffer': calculateStoufferCombinedPvalue(significanceValuesList, stouferWeights)
    }

    return combined_methods