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
"""Deciding which KEGG compound a metabolite name in a user's file meant.

Step 1 maps a metabolite name to KEGG by case-insensitive SUBSTRING match, so
"Glucose" arrives at step 2 carrying 113 candidates and "Alanine" carrying 105.
Step 2 asks the user to tick the right ones. This package answers that question
for them, in two tiers:

  * :mod:`.ranker` -- deterministic. Reproducible, needs no network, and on the
    STATegra metabolomics example it settles 31 of the 46 ambiguous names.
  * :mod:`.resolver` -- the residual, put to an LLM as a CLOSED-SET choice: the
    model may only answer with one of the KEGG ids it was shown, and an answer
    outside that set is rejected rather than applied.

Neither tier writes to the job. Both return advice; the user confirms it, and
``pathwayAcquisitionStep2`` remains the only thing that ever stores a
selection.
"""
