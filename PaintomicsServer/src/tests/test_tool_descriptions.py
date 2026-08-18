#!/usr/bin/env python3
"""Tool descriptions are prompt text, and prompt text goes stale.

Every description in TOOLBELT rides in EVERY Decide turn of every run, so it is
both the most-read documentation in the system and a standing token cost. Two
failure modes have already happened here:

  * a claim that stopped being true. read_paper said "an unread citation is the
    kind the verifier removes". Measured over 28 runs, citations to papers the
    agent had read passed verification at 73% against 84% for ones it had not --
    so the description was telling the agent the opposite of the evidence.

  * a claim that discouraged what works. check_my_citations said it was "worth
    running once", while the runs that ran it twice improved every time.

These tests do not check that a description is true -- nothing can. They check
that it does not promise an outcome the pipeline cannot deliver, and that it
stays short enough to be worth its place in every turn.

    python -m src.tests.test_tool_descriptions
"""
from __future__ import annotations

import os
import re
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.classes.AIInterpret.agent_loop import TOOLBELT  # noqa: E402

_PASSED, _FAILED = [], []

# Phrases that promise a verification outcome. The gate decides that, on the
# quote it can find, and no tool can commit to it in advance.
OUTCOME_PROMISES = (
    "the verifier removes", "will survive", "guarantees", "guaranteed",
    "always passes", "never removed", "ensures the citation",
)


def test_no_description_promises_a_verification_outcome():
    offenders = []
    for tool in TOOLBELT:
        text = (tool.description or "").lower()
        for phrase in OUTCOME_PROMISES:
            if phrase in text:
                offenders.append("%s: %r" % (tool.name, phrase))
    assert not offenders, (
        "descriptions promising what the gate decides: %s" % "; ".join(offenders))


def test_every_tool_has_a_description():
    missing = [t.name for t in TOOLBELT if not (t.description or "").strip()]
    assert not missing, "tools with no description: %s" % ", ".join(missing)


def test_descriptions_stay_affordable():
    """They are re-sent on every turn; a runaway description is a per-turn tax."""
    oversized = [(t.name, len(t.description or "")) for t in TOOLBELT
                 if len(t.description or "") > 700]
    assert not oversized, ("descriptions over 700 chars: %s"
                           % ", ".join("%s=%d" % o for o in oversized))
    total = sum(len(t.description or "") for t in TOOLBELT)
    assert total < 3500, (
        "the toolbelt's descriptions total %d chars, re-sent every Decide turn; "
        "trim one before adding another" % total)


def test_a_timing_claim_belongs_only_to_a_tool_that_costs_time():
    """The free tools say "instant and free" and must not grow a seconds figure;
    the expensive ones carry one because the agent budgets with it."""
    free = {"get_experiment_overview", "get_pathway_details",
            "compare_gene_profiles", "notebook_write", "submit_report"}
    for tool in TOOLBELT:
        says_seconds = re.search(r"\b\d+\s*(?:s\b|seconds?)", tool.description or "")
        if tool.name in free:
            assert not says_seconds, (
                "%s is a free tool but advertises %r"
                % (tool.name, says_seconds.group(0)))


def test_the_lead_prompt_does_not_contradict_itself_about_checking_citations():
    """The prompt told the agent both to run check_my_citations before
    submitting and that running it was optional, three bullets apart.

    That matters more than a tidiness point: of the 28 archived runs that called
    the tool, the 10 that ran it again after a bad result improved every time and
    none got worse. Marking the most valuable tool in the belt "optional" is the
    line most likely to stop it being used twice.
    """
    from src.classes.AIInterpret import prompts
    text = prompts.SYSTEM_PROMPT_LEAD_AGENT
    mentions = [l.strip() for l in text.split("\n") if "check_my_citations" in l]
    assert mentions, "the prompt no longer mentions check_my_citations at all"
    optional = [l for l in mentions
                if "optional" in l.lower() or "if you like" in l.lower()]
    assert not optional, ("the prompt calls check_my_citations optional while also "
                          "requiring it: %s" % optional)
    assert len(mentions) == 1, (
        "check_my_citations is described in %d separate places, which is how the "
        "contradiction arose: %s" % (len(mentions), mentions))



# Unused since the March 2026 feature commit that introduced them, and never
# referenced since. Left in place rather than deleted from a branch about the
# agent arm -- named here so they are visible instead of merely unused.
KNOWN_ORPHAN_PROMPTS = {"SYSTEM_PROMPT_INTERPRET_V2", "SYSTEM_PROMPT_SYNTHESIZE_V2"}


def test_no_new_orphan_prompts():
    """A prompt nobody sends is dead weight that reads as live configuration.

    SYSTEM_PROMPT_DELEGATED_INTERPRET was written, measured, reverted on the
    evidence -- citations fell 5 -> 18 under the old prompt against 7 -> 3 under
    it -- and then sat in the file looking exactly like the prompt that is
    actually used. The next person to tune delegation would have edited it and
    measured nothing.
    """
    import re
    from src.classes.AIInterpret import prompts

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    sources = []
    for base, _dirs, files in os.walk(os.path.join(root, "src")):
        if "/tests" in base or "__pycache__" in base:
            continue
        for name in files:
            if name.endswith(".py") and name != "prompts.py":
                with open(os.path.join(base, name)) as handle:
                    sources.append(handle.read())
    blob = "\n".join(sources)

    orphans = sorted(name for name in dir(prompts)
                     if name.startswith("SYSTEM_PROMPT")
                     and name not in KNOWN_ORPHAN_PROMPTS
                     and name not in blob)
    assert not orphans, (
        "prompt constants nobody sends: %s -- delete them or wire them up"
        % ", ".join(orphans))



def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print("PASS  %s" % name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  %s" % name)


def main():
    for t in (test_no_description_promises_a_verification_outcome,
              test_every_tool_has_a_description,
              test_descriptions_stay_affordable,
              test_a_timing_claim_belongs_only_to_a_tool_that_costs_time,
              test_the_lead_prompt_does_not_contradict_itself_about_checking_citations,
              test_no_new_orphan_prompts):
        _check(t.__name__, t)
    print("\nPassed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
