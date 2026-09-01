# What the AI does

PaintOmics has three separate AI features. They share a gateway and a set of
rules, but they do different jobs at different points in the analysis, and each
one can be switched off independently by whoever runs the server.

| Feature | Where | What it does |
|---|---|---|
| **[Input conversion](ai-input-converter.md)** | Step 1, on a file you pick | Turns a file that is not in PaintOmics' format — a DESeq2 table, a MaxQuant output, a multi-sheet workbook — into one that is, in your browser, and shows you the script it used. |
| **Compound disambiguation** | Step 2, **Choose for me** | Picks the most likely KEGG compound for each ambiguous metabolite name, using your organism and your experiment description. |
| **[Pathway interpretation](ai-interpretation.md)** | Step 3, **AI Interpret** | Reads your results and the literature and writes a cited draft of what they mean. |

## The rules they all follow

**You are told where your data goes, by name.** Section 2 of the upload form
names the gateway the model runs on — by default `llm.iiia.es`, operated by
IIIA-CSIC, the Artificial Intelligence Research Institute of the Spanish
National Research Council, on hardware in Spain — and the **Where your data
goes** link opens a full statement of what leaves the server. That statement is
worth reading once. In short: pathway names, p-values, matched feature names,
**the measured values with their condition labels** and your experiment
description are sent to the model; pathway and feature names also reach NCBI
PubMed and Europe PMC when the agent searches. Your uploaded files, as files,
are not sent, and neither are unmatched features or anything about your
account.

**The model never grades its own work.** Every AI output is checked by
something deterministic before you see it. A converted file must pass the same
format validator your own upload would; a claim in the report that cites a
paper must quote a sentence that actually appears in that paper, or the claim
is removed and the citations renumbered.

**Nothing is presented as fact.** Every report ends with the line *"Drafted by
a large language model, not by a person. Check every claim and every citation
against the sources before relying on it."* — inside the same block as the
text, so copying the write-up copies the attribution.

**Its work is inspectable.** The converter shows the Python it wrote and the
validator's verdict; the interpretation shows the tool calls it is making as it
works, and prints the verbatim sentence behind each citation together with
whether it came from an abstract or a full text.

## What is on by default

A PaintOmics server decides this, so the answer depends on where you are
running.

| Setting | Ships as | Controls |
|---|---|---|
| `AI_INTERPRETATION_ENABLED` | **on** | The report, the follow-up chat, the per-pathway drill-down and **Draft this for me**. |
| `AI_COMPOUND_SUGGESTIONS_ENABLED` | **on** | Step 2's **Choose for me**. Needs `AI_INTERPRETATION_ENABLED` as well. |
| `AI_INPUT_CONVERTER` | **off** | The input converter. It ships inert because it spends the same gateway quota as the reports. |

All of them also need an API key for the configured provider. If a server has
the feature enabled but no key, the interpretation never starts and the
progress bar sits at "Not started" — see [the failure
states](ai-interpretation.md#when-it-does-not-work).

!!! note "Consent"
    There is no consent checkbox on the form. Submitting a job through the
    upload form records consent for that job, and the server re-checks it on
    every request that would send anything outward — starting the
    interpretation, a follow-up question, a per-pathway drill-down. A job whose
    record says otherwise is refused. What replaces the checkbox is the
    **Where your data goes** statement, shown before you submit rather than
    buried in a tick-box.

## What to leave out of an AI job

Do not put personally identifiable information, protected health information,
or identifiable sequence reads into a job you intend to interpret with the AI.
The values and their condition labels are sent to the gateway; condition labels
in particular are free text you chose, so a column named after a patient is a
column that leaves the server.
