#!/usr/bin/env python3
"""An auditor that parses nothing reports a clean bill of health.

`ai_citation_audit` reads reference sections with regexes and reports how many
quotes failed. If the parser silently stops matching -- a heading renamed, the
Cited Text label reworded -- it returns zero problems out of zero quotes, which
is indistinguishable in the output from a corpus that is fine. These tests pin
the parsers against reports whose answers are known.

    python -m src.tests.test_citation_audit_parsers
"""
from __future__ import annotations

import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.benchmarks.ai_citation_audit import _quotes, _split, _haystack  # noqa: E402

_PASSED, _FAILED = [], []

REPORT = """Some prose citing [1] and [2].

### References

[1] Smith et al. Nature 2020.
    **Cited Text:** "glycolytic flux fell by half in treated cells"
[2] Jones et al. Cell 2021.
    **Cited Text:** "succinate dehydrogenase rose in parallel"
[9] Chen et al. Unrelated 2022.
"""


def test_quotes_are_found_and_attributed_to_the_right_entry():
    found = _quotes(_split(REPORT)[1])
    assert len(found) == 2, "expected 2 quotes, parsed %d: %r" % (len(found), found)
    assert found[0][0] == 1 and "glycolytic flux" in found[0][1]
    assert found[1][0] == 2 and "succinate dehydrogenase" in found[1][1]


def test_the_quote_is_stripped_of_its_label_and_quotation_marks():
    quote = _quotes(_split(REPORT)[1])[0][1]
    assert not quote.startswith('"'), "quotation marks were not stripped: %r" % quote
    assert "Cited Text" not in quote


def test_an_entry_without_a_quote_yields_none():
    """[9] carries no Cited Text and must not inherit [2]'s."""
    found = dict(_quotes(_split(REPORT)[1]))
    assert 9 not in found, "an entry with no quote picked one up: %r" % found


def test_the_body_and_references_split_where_the_heading_is():
    body, refs = _split(REPORT)
    assert "Some prose" in body and "Smith" not in body
    assert "Smith" in refs


def test_the_haystack_covers_every_stored_section():
    paper = {"sections": {"abstract": "alpha", "results": "beta"},
             "abstract": "alpha", "title": "gamma"}
    text = _haystack(paper)
    for piece in ("alpha", "beta", "gamma"):
        assert piece in text, "%r missing from the searchable text" % piece


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_quotes_are_found_and_attributed_to_the_right_entry,
              test_the_quote_is_stripped_of_its_label_and_quotation_marks,
              test_an_entry_without_a_quote_yields_none,
              test_the_body_and_references_split_where_the_heading_is,
              test_the_haystack_covers_every_stored_section):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
