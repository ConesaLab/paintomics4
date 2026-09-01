# Converting your input files

PaintOmics wants a plain matrix: one row per feature, one column per condition,
identifiers in the first column. Almost nothing you have on disk is already
that. The AI input converter turns what you have — a DESeq2 results table, a
MaxQuant output, a MetaboLights MAF, a workbook with one sheet per tissue —
into what PaintOmics needs, in your browser, and shows you exactly what it did
before you accept it.

!!! warning "This feature ships switched off"
    `AI_INPUT_CONVERTER` defaults to **off**, because the converter spends the
    same gateway quota as the [pathway
    interpretation](ai-interpretation.md). The buttons appear regardless: the
    conversion sheet will open, start its sandbox and profile your file, and
    only then say *"AI file conversion is not enabled on this server."* If you
    see that, the server needs the setting turned on — nothing is wrong with
    your file.

## Before the converter: the format check

Every omic card checks each file the moment you pick it, without any AI and
without sending anything anywhere. It reads the file in the browser and reports
one of three things:

* **A green tick** with a one-line summary — the row count, the number of value
  columns, a few example identifiers, and a note if identifiers repeat.
* **An amber line** naming a mechanical fault it can repair itself, for example
  *"Numbers use commas as the decimal mark; PaintOmics needs dots."* The
  **Fix automatically** button beside it is a direct find-and-replace, not an
  AI conversion, and the interface says so. It carries no AI mark on purpose.
* **A red line** naming a fault it cannot repair — and, there, the offer to
  convert.

Each slot is judged against its own contract, so a relevant-features list, an
associations file, an experimental design and a values matrix are each checked
for what they are meant to be.

## Where the offer appears

There are four ways into the converter, because there are four ways to find out
a file is wrong:

1. **On a file the checker rejected** — **Convert it for me** on the red strip.
2. **On any spreadsheet.** `.xlsx`, `.xlsm`, `.xls` and `.ods` always go to the
   converter rather than being parsed in place.
3. **When you press Run PaintOmics** with a file that has already been
   rejected. The job is not submitted; a banner explains that submitting would
   only produce the same error more slowly, and offers **Fix them and run** if
   every fault is mechanical, or **Convert with the PaintOmics AI agent** if
   not. **Submit anyway** is always there if you disagree.
4. **On a server error dialog.** Some bad files never reach the browser check —
   a file taken from server storage, or a MORE failure that names an omic
   rather than a file. Those dialogs grow an **Ask the PaintOmics AI agent**
   button, which carries the server's own message into the conversion.

Pressing one of those buttons *is* the consent. Nothing about the file leaves
your browser before you do.

## What actually leaves your computer

Not your data. The converter sends a **profile** of the file — its shape — and
the model writes a script against that profile; the script runs in your
browser, on your file.

The sheet shows you the profile it is about to send: the container (a workbook
with *N* sheets, or delimited text with its separator and encoding), every
sheet with its row and column counts, every column tagged as an identifier
candidate, a number or text, the column families it detected, the handful of
example rows it will include, the size of the payload in characters, and the
name of the gateway it goes to. It is one card at the top of the sheet, so
"only the structure leaves your computer" is something you can check rather
than something you have to believe.

## The sandbox

The Python the model writes never runs on the server. It runs in a Pyodide
interpreter inside a sandboxed frame with no same-origin access: no cookies, no
storage, no access to the PaintOmics page, and **no network**. It is loaded from
the server's own files rather than from a CDN, carries pandas, numpy and
openpyxl, and a fresh interpreter is created for each conversion and destroyed
with the sheet.

## Following what it does

The sheet has six stages across the top — **Read, Plan, Run, Check, Apply,
Review** — lit from the agent's own state, so a retry visibly drops back to
*Plan* and a failure marks the stage that failed. Beneath them, a timeline
records every step with the seconds it cost.

Two things in that timeline matter more than the rest:

**The script.** At the step that ran it, the generated Python is one click away,
with a Copy button and the output it printed. If you are going to put a
converted file in a paper, this is the record of how it was made.

**The validator's verdict.** The converted files are checked by the same
validator your own upload would face, and when it refuses them its report is
quoted one failure per line rather than summarised. The model does not grade
its own work.

## When it asks you something

Some decisions cannot be made from the file. Duplicate identifiers with nothing
in the file to explain them, transcript-level values that might or might not
want summing to genes, rows the original authors flagged as false positives —
in those cases the agent stops and asks, as a card with up to five one-click
answers (its own recommendation first) and the option to answer in your own
words. Your answer is written into the timeline as *"You chose: …"*.

Duplicate identifiers in particular are enforced, not negotiated: the validator
refuses a values matrix with silent duplicates and tells the agent to ask.

## Steering it

The box at the foot of the sheet takes plain instructions — *"use the reads
sheet, not TPM"*, *"keep the flagged genes"*, *"column A is a KEGG ID"*. The
agent revises the script it already has, re-runs it and re-checks it, rather
than starting over, and your instruction is recorded in the timeline. The same
box answers an open question in free text.

## The review

A successful conversion does not hand back "a file". It shows one card per
table it produced, each with a preview, the columns it kept, the columns it
left out struck through, the relevant-features list that goes with it, and a
download button. The table the agent recommends is badged **Recommended**.
Lists, designs and association files appear under **Also produced**, and the
sheets it did *not* convert — methodology, legends, a "global" sheet that was
only the union of the others — are listed with a reason for each.

Then you choose. The button is labelled for what it will do: **Use this file**,
**Use this table**, or **Use this table + add N more**. Ticking *"Also add the
other N tables as separate omics, named after their source"* turns a
four-region workbook into four omic panels in one step. If the agent produced a
matching relevant-features list, it goes into that card's relevant-features
slot automatically.

## After you accept

The omic card's strip turns green and records where the file came from:

> Converted by the PaintOmics AI agent from *&lt;your file&gt;* (table "…",
> relevant-features list attached)

with a **Convert again** link that reopens the sheet on your *original* upload.
A converted file otherwise looks exactly like one you made yourself, so this
line is what a reader of your methods has to go on. It is worth keeping.

## When your omics disagree with each other

PaintOmics paints every omic on one set of conditions, so a one-column fold
change beside a fourteen-column sample table is refused by the server even
though each file is individually fine. The browser now notices this before you
submit: each affected card gains a note — *"6 conditions here, 14 conditions in
Proteomics"* — and one job-level action appears, **Make them agree with the
PaintOmics AI agent**.

That hands every values file to the agent together. It derives the narrower
quantities from the wider omics' own columns and never widens the narrow one,
and the review says, per omic, whether it was *Rewritten* or left *Unchanged*.

## Limits you may meet

Beyond the feature being switched off, these are the refusals you may meet.
The first four are the server's own wording; the last is the browser giving up
on a conversion the server no longer holds.

| Message | What it means |
|---|---|
| "Daily conversion limit reached for this account." | 120 conversation turns per user per day. |
| "The server is converting other files right now. Please try again in a moment." | Only two conversions run site-wide at a time. |
| A cooldown quoting the last gateway failure | The gateway failed recently; conversions pause for 90 seconds. |
| "The AI service did not answer within 150 seconds…" | A single request timed out. Try again. |
| "The server lost track of this conversion (it may have restarted)." | Start it again. |

## What it will not do

It will not invent measurements, and it will not quietly drop rows: anything it
leaves out is listed in the review as left out, with a reason. It cannot rescue
a file that does not contain the numbers PaintOmics needs — if there is no
per-condition quantification in it, no conversion will produce one. And the
result is still yours to check: read the preview, read the columns it dropped,
and read the script if the answer matters.
