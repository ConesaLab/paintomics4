from math import log, isfinite
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

def _extractPvalue(significanceValues):
    """Accept both [nFeatures, nRelevant, pValue] and a bare p-value."""
    if isinstance(significanceValues, (list, tuple)) and len(significanceValues) >= 3:
        return significanceValues[2]
    return significanceValues


def _usablePvalues(significanceValuesList):
    """The p-values in [0, 1]; anything else is not evidence and is dropped.

    A p-value outside that range is not something either combining method can
    do anything sensible with, and the arithmetic quietly picks the worst
    available answer if left alone. Fisher's method needs ln(p), so the clamp
    below is `max(pVal, 1e-300)` to avoid log(0) -- correct for zero, and wrong
    for everything under it, because a negative clamps *up* to the smallest
    positive p-value the function admits, i.e. the strongest possible evidence.

    `Pathway` initialises its p-value slot to the sentinel -1.0, so a slot
    meaning "not computed yet" would read as "overwhelmingly significant": one
    of them drags a pathway from p=0.98 to p=6e-298, straight to the top of the
    results table. No reachable path through today's callers was found, but a
    silent maximally-significant answer is the worst of the available failures,
    so out-of-range input is ignored rather than clamped into evidence.

    Returns (pvalues, keptIndices) so a parallel weight vector can be filtered
    the same way.
    """
    pvalues, keptIndices = [], []
    for index, significanceValues in enumerate(significanceValuesList or []):
        pVal = _extractPvalue(significanceValues)
        if isinstance(pVal, bool) or not isinstance(pVal, (int, float)):
            continue
        if pVal < 0 or pVal > 1:
            continue
        pvalues.append(pVal)
        keptIndices.append(index)
    return pvalues, keptIndices


def calculateCombinedFisher(significanceValuesList):
    #X^2_2k ~ -2 * sum(ln(p_i))
    if not significanceValuesList: return 1.0

    pvalues, _kept = _usablePvalues(significanceValuesList)
    if not pvalues:
        return 1.0

    accumulatedValue = 0
    for pVal in pvalues:
        accumulatedValue += log(max(pVal, 1e-300)) # Avoid log(0)

    accumulatedValue = accumulatedValue * -2

    return(chi2.sf(accumulatedValue, 2*len(pvalues)))

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
    # Out-of-range values are dropped for the same reason as in
    # calculateCombinedFisher: the -1.0 sentinel is "not computed yet", not
    # evidence. The weight vector is filtered alongside so the two stay
    # aligned -- Stouffer pairs them positionally.
    pvalueList = list(pvalues)
    usable, keptIndices = _usablePvalues(pvalueList)
    curatedPvalues = [min(val, 0.9999999999) for val in usable]

    if weights is not None:
        weightList = list(weights)
        if len(weightList) == len(pvalueList):
            weights = [weightList[index] for index in keptIndices]

    # Nothing to combine: no omic in this pathway carried a usable p-value.
    if not curatedPvalues:
        return 1.0

    # Stouffer divides by sqrt(sum(w**2)), so an all-zero weight vector is
    # 0/0 -> NaN. That is reachable from the interface: the Stouffer weight
    # sliders have minValue 0, so a user can drag every omic to zero. The NaN
    # then reaches jsonify, which writes it as the bare token `NaN` -- not
    # valid JSON (RFC 8259) -- and since the client moved from eval() to
    # JSON.parse() the whole response is rejected, surfacing as
    # "Oops..Internal error! Unable to parse the error message".
    #
    # With no weight on any omic there is no evidence to combine, so the
    # honest answer is "not significant", which is also what the rest of the
    # pipeline stores when a p-value is absent.
    if weights is not None:
        weightList = list(weights)
        if weightList and not any(weightList):
            return 1.0

    # P-value in third position ([nFeatures, nRelevantFeatures, pValue])
    combinedPvalue = combine_pvalues(curatedPvalues, 'stouffer', weights)

    result = combinedPvalue[1]

    # Backstop for any other degenerate input: a non-finite float would be
    # serialised as invalid JSON and break the client the same way.
    if not isfinite(result):
        return 1.0

    return result

def calculateCombinedSignificancePvalues(significanceValuesList, stouferWeights):
    combined_methods = {
        'Fisher': calculateCombinedFisher(significanceValuesList),
        'Stouffer': calculateStoufferCombinedPvalue(significanceValuesList, stouferWeights)
    }

    return combined_methods