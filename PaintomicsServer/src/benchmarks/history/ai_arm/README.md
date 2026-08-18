# Agent-arm measurement history (rounds 1-24)

Per-run metrics for every round of the full-agent comparison, as written by
`src/benchmarks/ai_arm_bench.py` (and by the scratchpad scripts that preceded
it -- those rows carry `mode` where later ones carry `arm`; the scorer reads
both).

    python -m src.benchmarks.ai_arm_bench score src/benchmarks/history/ai_arm

Kept because the numbers in `docs/ai-agent-benchmark.md` are conclusions, and a
conclusion without its data cannot be re-checked. It reproduces every verdict in
that document, including the ones that went against the agent arm.

The reports themselves (~2.4 MB of prose) are not kept here; the metrics are.

**Grouping decides the verdict, so it is part of the protocol.** `agent-v20`
alone fails rule 3 (redactions 7.5 vs base 4.5 + 2); pooled with `agent-v19` it
passes at 6.25. Both are honest, and they disagree -- which is why round 25
fixes its grouping in advance: every replicate carrying code fingerprint
9e291e18a2 is one arm.
