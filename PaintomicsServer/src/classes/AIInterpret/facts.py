"""FactsLedger — every number in the paper is a fact id, by construction.

Why this exists
---------------
The verification pass used to *attribute* numbers after the fact: a regex found
"412" in a sentence and went looking for a tool result that could have said it.
Attribution can misattribute — the measured failure mode is a sentence whose
number is real but whose subject is not the thing the tool measured. This
module inverts the direction. Every tool result **registers** the numbers it
prints and shows the id beside the value (``p = 3.2e-4 [f17]``); the author
writes ``{{f17}}`` in prose and never the number; the gate substitutes the
formatted value. A number that appears bare in a Results sentence — not a fact
id, a year, a citation index, a figure/table reference or a condition label —
is a defect the gate can *see*, because the only legitimate path for a number
into prose is a token.

The ledger is per run: built empty in Phase 0, filled by every tool call,
stored beside the paper as a supplementary table so a reader can trace any
value to the tool and call that produced it.

Nothing here talks to a model or a database; it is a dict with manners, which
is what lets every rule in it be tested to the digit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# The kinds are a closed set on purpose: a kind picks a formatting rule, and a
# formatting rule is a claim about how a reader should see the value. A tool
# that needs a new kind adds it HERE, with its rule, not inline.
KINDS = ("pvalue", "q", "log2fc", "percent", "count", "coef", "r2", "n",
         "stat", "value")

_TOKEN = re.compile(r"\{\{\s*(f\d+)\s*\}\}")

# A standalone numeric token: not part of an identifier (p53, IL6, mmu04140),
# not already inside a {{...}} token. Percent signs ride along.
_NUMBER = re.compile(
    r"(?<![\w{.\-])"                 # not glued to a word, id, or decimal tail
    r"[-+]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?%?"
    r"(?![\w}])")

# What a bare number is allowed to be, in Results prose.
_CITATION = re.compile(r"\[\d+(?:\s*[,;–-]\s*\d+)*\]")          # [3], [3-5]
_FIGREF = re.compile(r"\b(?:Fig(?:ure)?s?\.?|Supplementary\s+Fig(?:ure)?s?\.?|"
                     r"Tables?|Supplementary\s+Tables?)\s*S?\d+[A-Za-z]?\b",
                     re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


@dataclass
class Fact:
    fid: str
    kind: str
    value: float
    scope: Dict[str, str] = field(default_factory=dict)
    tool: str = ""
    call_seq: Optional[int] = None

    def formatted(self):
        return format_value(self.kind, self.value)


def format_value(kind, value):
    """One reader-facing rendering per kind. Deterministic, locale-free."""
    v = float(value)
    if kind in ("pvalue", "q"):
        if v == 0.0:
            # A true zero is a floor, not a measurement; the tool that hit a
            # permutation floor is expected to register the floor separately.
            return "0"
        if v < 1e-3:
            mantissa, exponent = ("%.1e" % v).split("e")
            return "%s×10^%d" % (mantissa, int(exponent))
        return ("%.3f" % v).rstrip("0").rstrip(".") or "0"
    if kind == "percent":
        return ("%.1f" % v).rstrip("0").rstrip(".") + "%"
    if kind in ("count", "n"):
        return "%d" % round(v)
    if kind in ("log2fc", "coef", "stat"):
        return "%.2f" % v
    if kind == "r2":
        return "%.2f" % v
    # generic value: three significant digits without scientific pomp for
    # ordinary magnitudes.
    if v != 0 and (abs(v) >= 1e5 or abs(v) < 1e-3):
        mantissa, exponent = ("%.2e" % v).split("e")
        return "%s×10^%d" % (mantissa, int(exponent))
    return ("%.3g" % v)


class FactsLedger:
    """Registry of every number a tool printed, keyed by short ids."""

    def __init__(self):
        self._facts: Dict[str, Fact] = {}
        self._index: Dict[Tuple, str] = {}
        self._next = 1

    def __len__(self):
        return len(self._facts)

    def add(self, kind, value, scope=None, tool="", call_seq=None):
        """Register one number; returns its id (``f17``).

        Registering the same (kind, value, scope, tool) twice returns the SAME
        id: a tool that is called twice on the same slice must not mint a
        second identity for the same fact, or the supplementary table reads as
        if the run measured it twice.
        """
        if kind not in KINDS:
            raise ValueError("unknown fact kind %r (kinds: %s)"
                             % (kind, ", ".join(KINDS)))
        value = float(value)
        scope = {str(k): str(v) for k, v in (scope or {}).items()}
        key = (kind, repr(value), tuple(sorted(scope.items())), str(tool))
        fid = self._index.get(key)
        if fid is None:
            fid = "f%d" % self._next
            self._next += 1
            self._index[key] = fid
            self._facts[fid] = Fact(fid, kind, value, scope, str(tool),
                                    call_seq)
        return fid

    def tag(self, kind, value, scope=None, tool="", call_seq=None):
        """``[f17]`` — the marker a tool prints beside the value it shows."""
        return "[%s]" % self.add(kind, value, scope, tool, call_seq)

    def get(self, fid):
        return self._facts.get(str(fid))

    def items(self):
        return [self._facts[k] for k in sorted(self._facts,
                                               key=lambda f: int(f[1:]))]

    # -- the gate ----------------------------------------------------------

    def substitute(self, text):
        """Replace every ``{{fN}}`` with its formatted value.

        Returns ``(out, used_ids, unknown_ids)``. An unknown id is left in
        place, visibly — a silently dropped token would read as an omitted
        value, and the caller (the gate) must know to reject the sentence.
        """
        used, unknown = [], []

        def _sub(match):
            fid = match.group(1)
            fact = self._facts.get(fid)
            if fact is None:
                unknown.append(fid)
                return match.group(0)
            used.append(fid)
            return fact.formatted()

        return _TOKEN.sub(_sub, text or ""), used, unknown

    def to_tsv(self):
        """The supplementary table: every fact, its value, scope and source."""
        lines = ["fact_id\tkind\tvalue\tformatted\tscope\ttool\tcall_seq"]
        for fact in self.items():
            scope = "; ".join("%s=%s" % kv for kv in sorted(fact.scope.items()))
            lines.append("\t".join([
                fact.fid, fact.kind, repr(fact.value), fact.formatted(),
                scope, fact.tool,
                "" if fact.call_seq is None else str(fact.call_seq)]))
        return "\n".join(lines) + "\n"


def bare_numbers(text, condition_labels=()):
    """Numeric tokens in prose that are NOT allowed to be there.

    Allowed and therefore masked before the scan: ``{{fN}}`` tokens, citation
    indices (``[3]``, ``[3-5]``), figure/table references (``Fig. 2``,
    ``Supplementary Table S1``), four-digit years, and the condition labels
    the job actually uses (``Day 7`` is a name, not a measurement). Everything
    numeric that survives is returned with a pinch of context so the gate can
    name the sentence it rejects.
    """
    masked = _TOKEN.sub(" ", text or "")
    masked = _CITATION.sub(" ", masked)
    masked = _FIGREF.sub(" ", masked)
    masked = _YEAR.sub(" ", masked)
    for label in sorted({str(l) for l in condition_labels if str(l).strip()},
                        key=len, reverse=True):
        masked = re.sub(re.escape(label), " ", masked, flags=re.IGNORECASE)

    offenders = []
    for match in _NUMBER.finditer(masked):
        start, end = match.span()
        context = masked[max(0, start - 40):min(len(masked), end + 40)]
        offenders.append((match.group(0), " ".join(context.split())))
    return offenders


if __name__ == "__main__":
    ledger = FactsLedger()
    fid = ledger.add("pvalue", 3.2e-4, {"pathway": "mmu04110"}, "enrich")
    print(ledger.substitute("cell cycle ({{%s}})" % fid)[0])
    print(bare_numbers("412 genes overlapped (Fig. 2) [3] in 2024"))
