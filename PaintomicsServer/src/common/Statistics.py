from math import log
from scipy.stats import chi2, fisher_exact, combine_pvalues, hypergeom
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
    # Using hypergeom.sf is faster than fisher_exact for right-tailed tests
    # Population size: totalElems
    # Number of successes in population: totalSignificative
    # Sample size: foundElems
    # Number of successes in sample: foundSignificative
    # sf(k) = P(X > k)
    # We want P(X >= foundSignificative) = sf(foundSignificative - 1)
    if foundSignificative == 0:
        return 1.0
    p = hypergeom.sf(foundSignificative - 1, totalElems, totalSignificative, foundElems)
    # Ensure we don't return absolute 0 for display consistency
    return max(p, 1e-300)

def calculateCombinedFisher(significanceValuesList):
    #X^2_2k ~ -2 * sum(ln(p_i))
    if not significanceValuesList: return 1.0

    accumulatedValue = 0
    for significanceValues in significanceValuesList:
        # Handle both [nFeatures, nRelevant, pValue] and simple pValue
        if isinstance(significanceValues, (list, tuple)) and len(significanceValues) >= 3:
            pVal = significanceValues[2]
        else:
            pVal = significanceValues
        accumulatedValue += log(max(pVal, 1e-300)) # Avoid log(0)

    accumulatedValue = accumulatedValue * -2

    return(chi2.sf(accumulatedValue, 2*len(significanceValuesList)))

# fdr_bh (default), fdr_by, nada
def adjustPvalues(pvaluesList):
    # Returns array [reject, pvals_corrected, alphacSidak, alphacBonf]
    adjust_methods = {'fdr_bh': 'FDR BH', 'fdr_by': 'FDR BY'}

    # multipletests([]) raises ZeroDivisionError: float division by zero, so an
    # analysis that legitimately matched nothing died in step 2 with a division
    # error instead of reporting an empty result. Reached by uploading features
    # that map to no pathway -- a compound-only job whose metabolites are not in
    # the organism's pathways will do it. There is nothing to correct in that
    # case, and an empty correction is the right answer.
    if not pvaluesList:
        return {label: {} for label in adjust_methods.values()}

    adjusted_pvalues = {adjust_methods[adjust_method]: dict(zip(pvaluesList.keys(), multipletests(list(pvaluesList.values()), method = adjust_method)[1].tolist())) for adjust_method in adjust_methods.keys()}

    return adjusted_pvalues


def calculateStoufferCombinedPvalue(pvalues, weights):
    # Stouffer method cannot deal with p-values equal to 1, returning Nan
    # Prevent that by removing a small value in those cases
    curatedPvalues = []
    for pvalue in pvalues:
        if isinstance(pvalue, (list, tuple)) and len(pvalue) >= 3:
            val = pvalue[2]
        else:
            val = pvalue
        curatedPvalues.append(min(val, 0.9999999999))

    # P-value in third position ([nFeatures, nRelevantFeatures, pValue])
    combinedPvalue = combine_pvalues(curatedPvalues, 'stouffer', weights)

    return combinedPvalue[1]

def calculateCombinedSignificancePvalues(significanceValuesList, stouferWeights):
    combined_methods = {
        'Fisher': calculateCombinedFisher(significanceValuesList),
        'Stouffer': calculateStoufferCombinedPvalue(significanceValuesList, stouferWeights)
    }

    return combined_methods