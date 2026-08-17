# Tool usefulness in the agent arm — measured, not assumed

The design argument for the full-agent arm is that the agent chooses WHAT and the
tools enforce HOW MUCH. That only holds if the toolbelt is judged the way any
other interface is: by what callers actually do with it. This file is the running
record.

## How to get the data

Every tool call is archived to `CLIENT_TMP/ai_traces/<jobID>-<loopStart>.jsonl`
(one file per run, `seq`, `t`, `tool`, `args`, `result`, `ms`). The DAO's
`toolTrace` field keeps only the **current** run capped at 200 events, because
that is what a UI needs — twelve benchmark runs left two surviving traces, and
four tools sat unjudged as a result. The archive exists for the other question.

```bash
python - <<'PY'
import glob, json
from collections import Counter, defaultdict
calls, ms = Counter(), defaultdict(list)
for f in glob.glob("<CLIENT_TMP>/ai_traces/*.jsonl"):
    for line in open(f):
        e = json.loads(line); calls[e["tool"]] += 1; ms[e["tool"]].append(e["ms"])
for t, n in calls.most_common():
    v = sorted(ms[t]); print("%-26s %4d calls  median %6d ms" % (t, n, v[len(v)//2]))
PY
```

## First measurement (rounds 1–6, the two traces that survived)

| tool | calls | median ms | reading |
|---|---|---|---|
| `search_literature` | 18 | 1 885 | the workhorse |
| `delegate_interpretation` | 6 | **23 626** | 142 s of a 450 s loop budget for six calls |
| `read_paper` | 5 | 3 202 | |
| `notebook_write` | 6 | 4 | free |
| `get_pathway_details` | 4 | 0 | free, and **under-used** — 2 per run |
| `get_experiment_overview` | 2 | 79 | once per run, as intended |
| `cluster_pathways` | 2 | 411 | once per run, as intended |
| `check_my_citations` | 2 | 6 | free, used just before submitting |
| `submit_report` | 2 | 0 | the door |
| `get_gene_profile` · `compare_gene_profiles` · `notebook_read` · `delegate_literature` | 0 | — | not called *in these two runs* |

## What this changed in the tools

1. **Costs are now in the descriptions.** A 23.6 s tool and a 0 ms tool looked
   identical to the model. `delegate_interpretation` now says it costs ~25 s and
   is the costliest call available; `search_literature` ~2 s; `read_paper` ~3 s;
   the four instant tools say they are free. An agent cannot budget what it
   cannot see, and the ledger line only reports searches, seconds and characters.
2. **The free data tools now invite use.** `get_pathway_details` costs nothing and
   was called twice a run while the agent theorised from the overview; its
   description now says to read the data before theorising and to ask for several
   pathways at once.
3. **`read_paper` states its purpose, not just its mechanics** — an uncited-but-read
   paper is cheap, an unread-but-cited one is what the verifier removes.

## Second measurement — four archived runs, 62 calls (`python -m src.benchmarks.ai_tool_usage`)

| tool | calls | runs using it | median ms |
|---|---|---|---|
| `search_literature` | 20 | **4/4** | 1 673 |
| `notebook_write` | 7 | **4/4** | 2 |
| `delegate_interpretation` | 7 | 2/4 | **28 620** |
| `read_paper` | 9 | 2/4 | 2 263 |
| `get_experiment_overview` · `get_pathway_details` · `cluster_pathways` · `submit_report` | 4 each | **4/4** | 0–420 |
| `check_my_citations` | 2 | 2/4 | 15 |
| `compare_gene_profiles` | 1 | 1/4 | 9 |
| `get_gene_profile` · `notebook_read` · `delegate_literature` | 0 | 0/4 | — |

**`read_paper` payoff: 5 papers opened, 2 cited in the shipped report (40 %).**
Reading is neither decorative nor decisive — worth its 2.3 s, not worth making
mandatory. This is measurable only because the trace now records `pmid=`:
`renumber_citations` rewrites every `ref_index` at the gate, so PMIDs are the
only key that survives into the stored papers.

### What this changed

- **Thirteen tools became eleven.** `get_gene_profile` was
  `compare_gene_profiles` with one argument (my own rule above: if two tools
  differ only by arity, that is one tool), and `notebook_read` re-read what the
  SDK already keeps in the conversation. Both went uncalled in every archived
  run, but the reason to remove them is structural — each cost its schema in
  **every** Decide turn of every run.
- **Delegation latency is per CALL, not per pathway** — 28.6 s median whether it
  covers three pathways or ten, and two runs spent ~100 s on 3.5 calls each. The
  description now says covering ten pathways in one call costs what three would.
- `delegate_literature` stays for now: uncalled in these four runs, but earlier
  rounds did use it, and four runs is not enough to retire a tool that has been
  used.

### A trap this nearly caused

Round 6's two surviving traces showed `compare_gene_profiles` as never called;
round 7 called it. Removing a tool on two traces would have been wrong, and it is
exactly why the archive exists. **Adoption needs runs, not calls.**

## Third measurement — the gate, which was the biggest cost and invisible

Gate-side LLM calls are now archived as `gate: True` events. The first numbers
settled a question that had been costing citations for the whole experiment:

| verifier | per call | verdict returned? | redactions it caused |
|---|---|---|---|
| tool loop (`search_paper_text` + `fetch_paper_section`) | 45 s hedge timeouts, ~90 s worst | **9 of 14 failures were "Max turns (6) exceeded"** | 12–14 per run |
| prefetched, tool-less | **median 2 464 ms** | **29 of 29** | 2 per run |

29 prefetched calls returned 27 `match=True supports=True` and 2 genuine
refutations — and the run's redaction count was exactly 2. **Ten of the twelve
redactions in the previous configuration were a verifier that never reached a
verdict, not a citation that failed.** Verify-loop wall clock fell 291 s → 117 s
and the whole run 485 s → 338 s.

The lesson generalises past this arm: **if a tool loop exists only to fetch
something a function could fetch, it is not agency, it is latency and a failure
mode.** Locating a quote in a paper is `str.find` with a fuzzy fallback; judging
whether it supports a claim is the part that needs a model. Splitting those two
made the check faster, more reliable, and cheaper.

The same `Max turns (6) exceeded` warning appears in the **workflow arm's** logs,
so its shipped reports lose citations the same way. That fix belongs in its own PR.

Also measured, ending two suspicions: the quote-collection phase costs **3 s**,
not the tens of seconds assumed (it is not worth optimising), and
`read_paper`'s payoff held at 40 % (5 opened, 2 cited).

## Open questions the archive will answer

- Are `get_gene_profile`, `notebook_read` and `delegate_literature` dead weight?
  Each unused tool still costs its schema in **every** Decide turn. Remove on
  evidence across runs, not on two traces.
- Does `compare_gene_profiles` subsume `get_gene_profile`? If so, one tool.
- Is `check_my_citations` doing anything? It reported "0 failed" before submitting
  in runs whose citations were then redacted at the gate — a check that always
  passes is worse than none (the same trap as the rubber-stamping verifier).

## Rules for adding a tool here

- Say what it costs if it costs more than a few seconds; say it is free if it is.
- Enforce budgets inside the tool and report the remainder in the result.
- Return the reason for an empty result, not just the emptiness.
- If two tools differ only by arity, that is one tool.
