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
"""What the model is shown, and the shape it must answer in.

The task is a CLOSED-SET choice. Each set arrives with its candidate KEGG ids
listed, and the only legal answers are one of those ids or an abstention. The
prompt says so, the schema says so, and :func:`resolver.validateChoice` enforces
it -- an id outside the set is dropped, not applied. That is deliberate
belt-and-braces: a prompt is a request, and the analysis a user publishes should
not depend on a model having honoured one.
"""

#: Cap on how many of the file's other metabolite names go into the context.
#: The panel is the single most informative thing available when no experiment
#: design was written -- 58 amino acids and TCA intermediates identify
#: themselves as primary metabolism without anyone saying so -- but a 6,592-name
#: job would otherwise fill the whole prompt with it.
MAX_PANEL_NAMES = 120

#: Free-text the user wrote. Trimmed rather than trusted: it is theirs, it is
#: unbounded, and it is not worth a truncated candidate list.
MAX_DESIGN_CHARS = 1200


SYSTEM_PROMPT = (
    "You are a metabolomics data curator mapping the compound names in an "
    "uploaded table to KEGG COMPOUND identifiers.\n"
    "\n"
    "For each input name you are given the candidate KEGG compounds it matched. "
    "Choose the one the experiment most likely measured, or abstain.\n"
    "\n"
    "Rules:\n"
    "1. Answer only with a kegg_id that appears in that input name's own "
    "candidate list. Never invent one, and never borrow one from another "
    "input name.\n"
    "2. Use the organism. L-amino acids are the proteinogenic forms in "
    "animals, plants and fungi. D-amino acids are largely bacterial "
    "(peptidoglycan D-Ala and D-Glu) or confined to specific pathways, so in a "
    "mammalian or plant sample an unqualified amino-acid name means the L- "
    "form.\n"
    "3. Prefer a specific form over an unspecified generic entry when the "
    "biology is not in doubt: for a mouse sample, 'Alanine' is L-Alanine, not "
    "the generic 'Alanine' entry.\n"
    "4. Never choose between alpha and beta anomers unless the input name "
    "states one. If a sugar's candidates differ only by anomer, abstain.\n"
    "5. Abstain whenever more than one candidate is genuinely plausible for "
    "this organism and this experiment. Abstaining is correct and expected; a "
    "confident wrong compound silently changes which pathways the user's "
    "analysis reports.\n"
    "\n"
    "To abstain, set kegg_id to \"ABSTAIN\". Give one short reason for every "
    "answer, naming the organism or the evidence you used. Return one entry "
    "per input name you were given, in the same order."
)


#: Strict JSON schema for the batch answer. `confidence` is an enum rather than
#: a number because a model asked for 0-1 returns 0.9 for everything, and a
#: threshold on that is a threshold on nothing.
CHOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "input_name": {"type": "string"},
                    "kegg_id": {"type": "string"},
                    "confidence": {"type": "string",
                                   "enum": ["high", "medium", "low"]},
                    "reason": {"type": "string"},
                },
                "required": ["input_name", "kegg_id", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["choices"],
    "additionalProperties": False,
}


def _trim(text, limit):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " [...]"


def buildContextBlock(context):
    """What is known about the experiment, in the order it is worth reading.

    Everything here is already on the job -- nothing new is asked of the user.
    When no experiment design was written, the metabolite panel carries most of
    the signal on its own.

    @param {Dict} context, keys: organism, organismLabel, jobDescription,
           experimentDesign, omics, panel
    @returns {String}
    """
    lines = []

    label = (context.get("organismLabel") or "").strip()
    code = (context.get("organism") or "").strip()
    if label and code and label.lower() != code.lower():
        lines.append("Organism: %s (KEGG code %s)" % (label, code))
    elif code:
        # No display name is available server-side (organism names live in the
        # browser's KEGG organism list, not in any collection this process
        # reads), so the code is labelled as what it is rather than dropped in
        # bare -- "mmu" alone reads like a column header.
        lines.append("Organism: KEGG organism code %s" % code)
    elif label:
        lines.append("Organism: %s" % label)

    omics = [o for o in (context.get("omics") or []) if o]
    if omics:
        lines.append("Omics uploaded: %s" % ", ".join(omics))

    description = _trim(context.get("jobDescription"), 200)
    if description:
        lines.append("Job title: %s" % description)

    design = _trim(context.get("experimentDesign"), MAX_DESIGN_CHARS)
    if design:
        lines.append("Experiment design, as the user described it:\n%s" % design)
    else:
        lines.append("Experiment design: not provided. Infer what you can from "
                     "the organism and from the panel of metabolites below.")

    panel = [name for name in (context.get("panel") or []) if name]
    if panel:
        shown = panel[:MAX_PANEL_NAMES]
        suffix = "" if len(panel) <= MAX_PANEL_NAMES else \
            " (and %d more)" % (len(panel) - MAX_PANEL_NAMES)
        lines.append("All metabolite names in this file%s: %s"
                     % (suffix, ", ".join(shown)))

    return "\n".join(lines)


def renderCandidates(decision):
    """One residual set as the model sees it: the name, then its candidates."""
    lines = ["Input name: %s" % decision["title"]]
    for candidate in decision["candidates"]:
        names = ", ".join(candidate["names"])
        lines.append("  - %s: %s" % (candidate["keggID"], names))
    return "\n".join(lines)


def buildBatchPrompt(decisions, context):
    """The user turn for one batch of residual compound sets.

    @param {List} decisions, residual decisions from the ranker
    @param {Dict} context, as accepted by :func:`buildContextBlock`
    @returns {String}
    """
    header = buildContextBlock(context)
    body = "\n\n".join(renderCandidates(decision) for decision in decisions)
    return (
        "%s\n\n"
        "Choose one KEGG compound for each of the %d input names below, or "
        "abstain. Only the ids listed under an input name are legal answers "
        "for that name.\n\n"
        "%s" % (header, len(decisions), body))
