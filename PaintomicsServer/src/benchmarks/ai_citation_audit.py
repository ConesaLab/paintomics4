#!/usr/bin/env python3
"""Audit the citations in stored interpretations. Are they grounded, and do they add up?

The framework's central claim is that every [N] carries a verbatim sentence from
the paper it points at. That is enforced at generation time by the gate and was
never checked afterwards -- so the claim rested on the same code that makes it.
These checks are written to be runnable at any time, against whatever is in the
database, by someone who did not write the pipeline.

    python -m src.benchmarks.ai_citation_audit integrity
        Cheap, whole corpus. Three failures worth knowing about:
          dangling  a [N] in the prose with no entry in the references
          uncited   an entry in the references the prose never cites -- it
                    inflates the reader's sense of how much evidence there is
          gaps      holes in the numbering, which is what uncited entries leave

    python -m src.benchmarks.ai_citation_audit quotes
        Every "Cited Text" against the paper copy stored beside it. Fast, and
        weaker than it looks: the gate enforced this with the same matcher, so a
        pass mostly confirms the gate ran.

    python -m src.benchmarks.ai_citation_audit pubmed [--sample N]
        The independent one. Re-fetches papers from NCBI and checks the quotes
        against text this system never stored. A quote from a full-text paper is
        not expected in an abstract, so those are reported separately rather
        than counted as failures.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.verification import _fuzzy_contains       # noqa: E402
from src.conf.serverconf import AI_VERIFICATION_FUZZY_THRESHOLD as THRESHOLD  # noqa: E402
from src.common.DAO.AIInterpretDAO import AIInterpretDAO              # noqa: E402

REFS_HEADER = "### References"


def _reports(since=None):
    dao = AIInterpretDAO()
    try:
        collection = dao.dbManager.getCollection(dao.collectionName)
        docs = list(collection.find({}, {"jobID": 1, "report": 1, "papers": 1,
                                         "updatedAt": 1}))
    finally:
        dao.closeConnection()
    out = []
    for doc in docs:
        report = doc.get("report") or ""
        if REFS_HEADER not in report:
            continue
        when = str(doc.get("updatedAt"))[:10]
        if since and when < since:
            continue
        out.append((when, doc.get("jobID"), report, doc.get("papers") or []))
    return sorted(out)


def _split(report):
    body, refs = report.split(REFS_HEADER, 1)
    return body, refs


def _quotes(refs_text):
    """(ref_index, quote) for every entry carrying a Cited Text line."""
    found, current = [], None
    for line in refs_text.split("\n"):
        entry = re.match(r"\s*\[(\d+)\]", line)
        if entry:
            current = int(entry.group(1))
        quote = re.search(r"\*\*Cited Text:\*\*\s*(.+)", line)
        if quote and current is not None:
            found.append((current, quote.group(1).strip().strip('"').strip()))
    return found


def _haystack(paper):
    parts = [str(v) for v in (paper.get("sections") or {}).values()]
    parts.append(paper.get("abstract") or "")
    parts.append(paper.get("title") or "")
    return " ".join(parts)


def cmd_integrity(args):
    rows = _reports(args.since)
    dangling_n = uncited_n = gap_n = 0
    print("%-12s %-12s %6s %6s %-14s %-14s %s"
          % ("date", "job", "cites", "refs", "dangling", "uncited", "gaps"))
    for when, job, report, _papers in rows:
        body, refs = _split(report)
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", body)}
        listed = {int(n) for n in re.findall(r"^\s*\[(\d+)\]", refs, re.M)}
        dangling = sorted(cited - listed)
        uncited = sorted(listed - cited)
        gaps = sorted(set(range(1, max(listed) + 1)) - listed) if listed else []
        dangling_n += bool(dangling)
        uncited_n += bool(uncited)
        gap_n += bool(gaps)
        if dangling or uncited or gaps:
            print("%-12s %-12s %6d %6d %-14s %-14s %s"
                  % (when, job, len(cited), len(listed), dangling[:4] or "-",
                     uncited[:4] or "-", gaps[:4] or "-"))
    print("\n%d report(s) checked" % len(rows))
    print("  citations with no reference entry : %d report(s)" % dangling_n)
    print("  reference entries never cited     : %d report(s)" % uncited_n)
    print("  gaps in the numbering             : %d report(s)" % gap_n)
    return 1 if dangling_n else 0


def cmd_quotes(args):
    rows = _reports(args.since)
    checked = unmatched = 0
    offenders = []
    for when, job, report, papers in rows:
        index = {p.get("ref_index"): p for p in papers}
        for ref, quote in _quotes(_split(report)[1]):
            paper = index.get(ref)
            if not paper or len(quote) < 25:
                continue
            text = _haystack(paper)
            if not text.strip():
                continue
            checked += 1
            if not _fuzzy_contains(text, quote, THRESHOLD):
                unmatched += 1
                offenders.append((when, job, ref, quote[:70]))
    print("threshold %.2f -- %d quote(s) checked against the stored paper copy"
          % (THRESHOLD, checked))
    print("%d did not appear in the paper they are attributed to (%.1f%%)"
          % (unmatched, 100.0 * unmatched / max(checked, 1)))
    for row in offenders[:15]:
        print("  %s %s [%d] %r" % row)
    print("\nNote: the gate enforced this with the same matcher, so a pass here "
          "mostly confirms the gate ran. Use `pubmed` for an independent check.")
    return 0


def cmd_pubmed(args):
    from src.classes.AIInterpret.pubmed_client import PubMedClient
    rows = _reports(args.since)
    pairs = []
    for when, job, report, papers in reversed(rows):        # newest first
        index = {p.get("ref_index"): p for p in papers}
        for ref, quote in _quotes(_split(report)[1]):
            paper = index.get(ref)
            if paper and paper.get("pmid") and len(quote) > 40:
                pairs.append((job, str(paper["pmid"]),
                              bool(paper.get("full_text_available")), quote))
        if len(pairs) >= args.sample:
            break
    pairs = pairs[:args.sample]
    if not pairs:
        print("no quotes to check")
        return 0
    print("re-fetching %d paper(s) from NCBI -- text this system never stored\n"
          % len(pairs), flush=True)

    client = PubMedClient()
    fresh = {}
    for paper in client.fetch_abstracts([p[1] for p in pairs]) or []:
        fresh[str(paper.get("pmid"))] = " ".join(
            [paper.get("title") or "", paper.get("abstract") or ""])

    matched = from_full_text = missing = 0
    for job, pmid, has_full_text, quote in pairs:
        text = fresh.get(pmid, "")
        if not text.strip():
            missing += 1
            continue
        if _fuzzy_contains(text, quote, THRESHOLD):
            matched += 1
        elif has_full_text:
            # the sentence is in the body; an abstract cannot contain it
            from_full_text += 1
        else:
            print("  NOT FOUND  %s pmid=%s %r" % (job, pmid, quote[:70]))
            missing += 1
    print("\n%d matched the freshly fetched abstract" % matched)
    print("%d came from full-text papers, so correctly absent from the abstract"
          % from_full_text)
    print("%d unexplained" % missing)
    return 1 if missing else 0


def main(argv=None):
    # --since belongs to every subcommand, and reads naturally after it. The
    # database holds several code eras at once; three conclusions this session
    # reversed when the same data was split by date instead of pooled.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--since", default=None,
                        help="only reports updated on/after YYYY-MM-DD")

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                     parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("integrity", parents=[common])
    sub.add_parser("quotes", parents=[common])
    pubmed = sub.add_parser("pubmed", parents=[common])
    pubmed.add_argument("--sample", type=int, default=12)
    args = parser.parse_args(argv)
    return {"integrity": cmd_integrity, "quotes": cmd_quotes,
            "pubmed": cmd_pubmed}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
