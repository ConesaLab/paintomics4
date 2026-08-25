#***************************************************************
#  This file is part of Paintomics v4
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#
#  More info http://bioinfo.cipf.es/paintomics
#  Technical contact paintomicsai@gmail.com
#**************************************************************
"""How close a KEGG compound name is to the name a user actually uploaded.

Two callers have to agree on this number or step 2 contradicts itself:

  * :meth:`src.classes.Feature.Compound.calculateSimilarity`, run once per
    candidate while step 1 maps names. Its answer is what splits a matched
    name's candidates into ``mainCompounds`` and ``otherCompounds``, and that
    split is what the step-2 cards are drawn from.
  * :mod:`src.classes.CompoundDisambiguation.ranker`, run again at step 2 when
    the user asks for help. It scores candidates that were loaded back out of
    MongoDB, where nothing guarantees a stored ``similarity`` survived a
    reopen, so it recomputes rather than trusting the record.

A ranker that scored "main" differently from the mapper would offer to resolve
a set the user cannot see, or leave one it can. One function, imported twice.
"""

from difflib import SequenceMatcher

#: Prefixes that do not change which compound is meant, only which form of it.
#: A candidate whose name is the input plus one of these is treated as a direct
#: hit rather than as a fuzzy one -- "L-Alanine" for an input of "Alanine".
#:
#: Note what this deliberately does NOT settle: it makes L-Alanine, D-Alanine
#: and beta-Alanine all score 0.9 against "Alanine". They are three different
#: metabolites, and choosing between them is exactly the judgement the ranker
#: escalates rather than guesses.
MAIN_PREFIXES = frozenset([
    "", "cis-", "trans-", "d-", "l-", "(s)-", "alpha-", "beta-",
    "alpha-d-", "beta-d-", "alpha-l-", "beta-l-",
])

#: At or above this, a candidate is a "main" compound: the same substance under
#: a spelling the mapper recognises. Below it, an "other" -- a substring hit
#: like "UDP-glucose" for "Glucose".
MAIN_SIMILARITY_THRESHOLD = 0.9


def nameSimilarity(candidateName, inputName):
    """Score a KEGG candidate name against the name the user uploaded.

    @param {String} candidateName, a name or synonym from ``kegg_compounds``
    @param {String} inputName, the identifier as it appeared in the user's file
    @returns {Float} 1.0 for an exact match, 0.9 for a main-prefix variant,
             otherwise difflib's ratio in [0, 1]
    """
    candidate = (candidateName or "").lower()
    query = (inputName or "").lower()

    if candidate == query:
        return 1.0
    # `query` is guarded because "".replace("", "") returns the whole string,
    # which would score every candidate 0.9 against an empty input name.
    if query and candidate.replace(query, "") in MAIN_PREFIXES:
        return MAIN_SIMILARITY_THRESHOLD
    return SequenceMatcher(a=candidate, b=query).ratio()

